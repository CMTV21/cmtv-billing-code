"""Imperium channel line-ups (CMTV local addition 2026-09-29; the user's idea: a drop-down on each Imperium plan).
The Imperium (Aether) panel has the same plans in several line-ups at the same credit cost:
  full      "Full Package - ..."            everything (~48,800 live), incl. adult        (what billing sold before)
  no_adult  "Full Package (No adult) - ..."  the same minus the adult group
  na        "US/UK/CA/PPV - ..."             USA, UK, Canada, AU/NZ, PPV, 24/7, 4K (~33,200 live), no adult, no international
("USA Only" is left out on purpose: no Canadian channels, and it includes adult.)
Billing products keep pointing at the Full packages. An order item may carry `lineup`; provisioning swaps the product's
package for the one with the same length and connections in that line-up (matched from the panel's package list, cached
1 h). A renewal without a choice keeps the line's current line-up (service.cmtv_lineup, else its Aether package).
  GET /api/cmtv/lineups -> the choices for the storefront/checkout
"""
import logging
import time
from datetime import datetime

from bson import ObjectId
from fastapi import APIRouter

log = logging.getLogger("server")
router = APIRouter(prefix="/api/cmtv", tags=["cmtv-lineups"])
D = {}
LINEUPS = {
    "full": {"prefix": "Full Package - ", "label": "Full: all countries",
             "note": "Everything: USA, UK, Canada, PPV, 4K, 24/7, about 55 countries, and adult channels."},
    "no_adult": {"prefix": "Full Package (No adult) - ", "label": "Full: no adult channels",
                 "note": "Everything in Full except the adult channels."},
    "na": {"prefix": "US/UK/CA/PPV - ", "label": "North America: US, UK, Canada + PPV",
           "note": "USA, UK, Canada, Australia/NZ, PPV, 24/7 and 4K. Fewer channels to scroll, no adult, no international."},
}
_cache = {"at": 0.0, "pk": None}


def init(**deps):
    D.update(deps)


def _oid(v):
    return ObjectId(v) if ObjectId.is_valid(str(v)) else None


async def packages():
    """The Aether panel's packages, cached for an hour. [] if the panel can't be reached."""
    if _cache["pk"] is not None and time.time() - _cache["at"] < 3600:
        return _cache["pk"]
    pk = []
    try:
        from aether_service import get_aether_service
        panels = ((await D["get_settings"]()).get("aether") or {}).get("panels") or []
        if panels:
            r = await get_aether_service(panels[0]).get_packages()
            pk = (r.get("packages") if isinstance(r, dict) else r) or []
    except Exception as e:
        log.warning(f"line-ups: couldn't read Imperium packages: {e}")
    if pk:
        _cache.update(at=time.time(), pk=pk)
    return pk


def lineup_of(pkg, pk):
    """Which line-up a package id belongs to (None if not one of ours)."""
    p = next((x for x in pk if str(x.get("id")) == str(pkg)), None)
    if not p:
        return None
    name = str(p.get("name") or "")
    for key, v in sorted(LINEUPS.items(), key=lambda kv: -len(kv[1]["prefix"])):   # longest prefix first ("(No adult)")
        if name.startswith(v["prefix"]):
            return key
    return None


def variant(pkg, lineup, pk):
    """The package with the same length and connections as `pkg`, in `lineup`. Returns pkg itself if there's no match."""
    src = next((x for x in pk if str(x.get("id")) == str(pkg)), None)
    want = LINEUPS.get(lineup)
    if not src or not want or lineup_of(pkg, pk) is None:
        return pkg
    for x in pk:
        if str(x.get("name") or "").startswith(want["prefix"]) and lineup_of(x.get("id"), pk) == lineup \
                and x.get("duration") == src.get("duration") and x.get("max_connections") == src.get("max_connections") \
                and not x.get("is_trial"):
            return x.get("id")
    return pkg


async def apply(product: dict, item: dict):
    """For an Imperium subscriber item: a copy of the product pointing at the chosen (or kept) line-up's package.
    Anything else comes back unchanged."""
    if not product or product.get("panel_type") != "aether" or product.get("account_type", "subscriber") != "subscriber" \
            or product.get("is_trial"):
        return product
    choice = item.get("lineup") if item.get("lineup") in LINEUPS else None
    db = D["db"]
    svc = None
    if item.get("renewal_service_id"):
        svc = await db.services.find_one({"_id": _oid(item["renewal_service_id"])})
    pk = await packages()
    if not pk:
        return product
    if not choice and svc:   # renewals keep the line-up the line is on
        choice = svc.get("cmtv_lineup")
        if not choice:
            cur = svc.get("aether_package_id")
            if not cur:
                name = svc.get("xtream_username") or svc.get("username")
                iu = await db.imported_users.find_one({"username": name, "panel_type": "aether"}) if name else None
                cur = (iu or {}).get("aether_package_id")
            choice = lineup_of(cur, pk) if cur else None
    if not choice or choice == "full" and lineup_of(product.get("xtream_package_id"), pk) == "full":
        if svc and choice:
            await db.services.update_one({"_id": svc["_id"]}, {"$set": {"cmtv_lineup": choice}})
        return product
    base = product.get("panel_package_id") or product.get("xtream_package_id")
    new = variant(base, choice, pk)
    if str(new) == str(base):
        log.warning(f"line-ups: no '{choice}' package matching {base} ({product.get('name')}); using the product's own")
        return product
    if svc:
        await db.services.update_one({"_id": svc["_id"]}, {"$set": {"cmtv_lineup": choice, "cmtv_lineup_at": datetime.utcnow()}})
    log.info(f"line-ups: {product.get('name')} -> {choice} package {new}")
    new = str(new) if isinstance(base, str) else new   # same type as the product stores
    out = {**product, "xtream_package_id": new, "cmtv_lineup": choice}
    if product.get("panel_package_id"):
        out["panel_package_id"] = new
    return out


async def remember(order_id: str, order: dict):
    """After provisioning: new Imperium lines remember the line-up they were ordered with."""
    for it in order.get("items") or []:
        if it.get("lineup") in LINEUPS and not it.get("renewal_service_id"):
            await D["db"].services.update_many({"order_id": order_id, "panel_type": "aether", "cmtv_lineup": {"$exists": False}},
                                               {"$set": {"cmtv_lineup": it["lineup"]}})


@router.get("/lineups")
async def lineups():
    return {"lineups": [{"key": k, "label": v["label"], "note": v["note"]} for k, v in LINEUPS.items()], "default": "full"}
