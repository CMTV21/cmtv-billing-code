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

Custom channel groups (2026-09-30, the user's request): the three line-ups allow the same ~70 channel groups (bouquets)
and differ only in which are on by default. An order item may carry `bouquets` (group ids): a NEW line is then created
with exactly those groups (they must be allowed by the line-up's package; anything else is dropped). Renewals keep the
line's groups (the panel's renew call doesn't touch them). The line remembers its groups in service.cmtv_bouquets.
  GET /api/cmtv/lineups/{lineup}/groups?product_id= -> the groups, their channel counts and which are standard
CCTV (same day): the plan's own group list is the choice (no line-ups); renewals send the line's saved picks.
  GET /api/cmtv/cctv/groups?product_id= -> the groups + sections
"""
import asyncio
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


_bq = {}   # package id -> (time, groups)
MAIN = {"usa", "united kingdom", "canada", "live events / ppv", "live events / ppv -- usa only", "4k / uhd", "24/7",
        "24-7 movies", "cinemania", "cine play", "australia", "new zealand"}


def _section(g):
    name = str(g.get("name") or "").strip().lower()
    if name in ("xxx", "adult") or "xxx" in name or "adult" in name:
        return "adult"
    if (g.get("movie_count") or 0) > 0 or (g.get("series_count") or 0) > 0:
        return "vod"
    return "main" if name in MAIN else "world"


async def groups_for(pkg):
    """The channel groups a package allows (cached 1 h): [{id, name, live, movies, series, standard, section}]"""
    hit = _bq.get(str(pkg))
    if hit and time.time() - hit[0] < 3600:
        return hit[1]
    out = []
    try:
        from aether_service import get_aether_service
        panels = ((await D["get_settings"]()).get("aether") or {}).get("panels") or []
        if panels:
            r = await get_aether_service(panels[0]).get_package_bouquets(int(pkg))
            for g in r.get("bouquets") or []:
                if g.get("enabled", True) is False:
                    continue
                out.append({"id": int(g["id"]), "name": str(g.get("name") or "").strip(), "live": int(g.get("stream_count") or 0),
                            "movies": int(g.get("movie_count") or 0), "series": int(g.get("series_count") or 0),
                            "standard": bool(g.get("default_included")), "section": _section(g), "order": g.get("order") or 0})
    except Exception as e:
        log.warning(f"line-ups: couldn't read the groups of package {pkg}: {e}")
    if out:
        out.sort(key=lambda g: (g["order"], g["name"]))
        _bq[str(pkg)] = (time.time(), out)
    return out


def clean_bouquets(raw):
    """A customer's group picks as a list of unique ints (None if empty or not a list)"""
    if not isinstance(raw, (list, tuple)):
        return None
    out = []
    for v in raw[:120]:
        try:
            v = int(v)
        except (TypeError, ValueError):
            continue
        if v > 0 and v not in out:
            out.append(v)
    return out or None


# ---------------- CCTV channel groups (2026-09-30) ----------------
# CCTV (XtreamUI) has no line-ups: a plan's groups are its product's `bouquets` list (the owner keeps Brazil, Iran and Africa
# off on purpose, although the panel packages have them). Tested on the panel 2026-09-30: a line created with 3 groups got
# only those. Unlike Imperium, a CCTV renewal re-posts a group list, so renewals send the line's saved picks.
CCTV_SECTIONS = [["main", "Main channels"], ["sports", "Sports"], ["locals", "US local networks"], ["vod", "Movies & series"],
                 ["world", "International"], ["adult", "Adult"]]
CCTV_MAIN = {"usa ent", "usa news", "usa kids", "movie channels", "canada ent", "canada locals", "canada french", "uk", "247", "music"}
CCTV_SPORTS = {"usa sports", "canada sports", "uk sports", "nba", "nfl", "nhl", "mlb", "mls", "ncaa", "bein sports", "espn",
               "fanduel", "flosports and dirtvision", "ppv"}
_cctv = {}   # package id -> (time, {group id: (name, channels, series)})


def _cctv_section(name):
    n = str(name or "").strip().lower()
    if "adult" in n or "xxx" in n:
        return "adult"
    if "vod" in n:
        return "vod"
    if n in CCTV_SPORTS:
        return "sports"
    if n.endswith("locals") and not n.startswith("canada"):
        return "locals"
    return "main" if n in CCTV_MAIN else "world"


def _count(v):
    return len(v) if isinstance(v, (list, tuple)) else int(v or 0)


async def _cctv_names(pkg):
    """{group id: (name, channels, series)} for a CCTV package, read from the panel (cached 1 h)"""
    hit = _cctv.get(str(pkg))
    if hit and time.time() - hit[0] < 3600:
        return hit[1]
    panels = ((await D["get_settings"]()).get("xtream") or {}).get("panels") or []
    if not panels or not pkg:
        return {}
    p = panels[0]

    def read():
        from xtreamui_service import XtreamUIService
        x = XtreamUIService(panel_url=p["panel_url"], admin_username=p["admin_username"], admin_password=p["admin_password"],
                            ssl_verify=p.get("ssl_verify", False), http_basic_user=p.get("http_basic_user", ""),
                            http_basic_pass=p.get("http_basic_pass", ""), proxy_url=p.get("proxy_url", ""), api_key=p.get("api_key", ""))
        sc = x._get_session_client()
        if not sc.login():
            return {}
        d = sc.session.get(f"{sc.panel_url}/api.php", params={"action": "get_package", "package_id": int(pkg)},
                           auth=getattr(sc, "http_auth", None), timeout=20).json()
        return {int(b["id"]): (str(b.get("bouquet_name") or "").strip(), _count(b.get("bouquet_channels")), _count(b.get("bouquet_series")))
                for b in d.get("bouquets") or [] if str(b.get("id", "")).isdigit()}
    out = {}
    try:
        out = await asyncio.to_thread(read)
    except Exception as e:
        log.warning(f"CCTV groups: couldn't read package {pkg}: {type(e).__name__}")
    if out:
        _cctv[str(pkg)] = (time.time(), out)
    return out


def _cctv_ids(product):
    out = []
    for b in (product or {}).get("bouquets") or []:
        try:
            out.append(int(b))
        except (TypeError, ValueError):
            pass
    return out


def _is_line_plan(p, panel):
    return bool(p) and p.get("panel_type") == panel and p.get("account_type", "subscriber") == "subscriber" and not p.get("is_trial")


async def _apply_cctv(product: dict, item: dict):
    if not _is_line_plan(product, "xtream"):
        return product
    allowed = _cctv_ids(product)
    if item.get("renewal_service_id"):   # renewals re-post a group list: send the line's own picks
        svc = await D["db"].services.find_one({"_id": _oid(item["renewal_service_id"])})
        keep = [b for b in ((svc or {}).get("cmtv_bouquets") or []) if b in allowed]
        if keep:
            log.info(f"CCTV groups: renewal keeps the line's {len(keep)} chosen groups")
            return {**product, "bouquets": keep}
        return product
    picks = clean_bouquets(item.get("bouquets"))
    if not picks:
        return product
    keep = [b for b in picks if b in allowed]
    if len(keep) < len(picks):
        log.warning(f"CCTV groups: {len(picks) - len(keep)} picked group(s) aren't in {product.get('name')}, left out")
    if not keep or set(keep) == set(allowed):
        return product
    log.info(f"CCTV groups: {product.get('name')} with {len(keep)} chosen groups")
    return {**product, "bouquets": keep, "cmtv_bouquets": keep}


async def apply(product: dict, item: dict):
    """Imperium subscriber item: the chosen line-up's package, plus the customer's own channel groups on a new line.
    CCTV subscriber item: the customer's own groups on a new line, the line's saved groups on a renewal."""
    if product and product.get("panel_type") == "xtream":
        return await _apply_cctv(product, item)
    out = await _apply_lineup(product, item)
    picks = clean_bouquets(item.get("bouquets"))
    if not picks or item.get("renewal_service_id") or out is None or out.get("panel_type") != "aether" \
            or out.get("account_type", "subscriber") != "subscriber" or out.get("is_trial"):
        return out
    pkg = out.get("panel_package_id") or out.get("xtream_package_id")
    allowed = await groups_for(pkg) if pkg else []
    if not allowed:
        log.warning(f"line-ups: groups of package {pkg} unknown; the line gets the line-up's standard groups")
        return out
    ids = {g["id"] for g in allowed}
    keep = [b for b in picks if b in ids]
    if len(keep) < len(picks):
        log.warning(f"line-ups: {len(picks) - len(keep)} picked group(s) not allowed by package {pkg}, left out")
    if not keep or set(keep) == {g["id"] for g in allowed if g["standard"]}:
        return out   # same as the line-up's own groups
    log.info(f"line-ups: {out.get('name')} with {len(keep)} chosen channel groups")
    return {**out, "bouquets": keep, "cmtv_bouquets": keep}


async def _apply_lineup(product: dict, item: dict):
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
        picks = clean_bouquets(it.get("bouquets"))
        if picks and not it.get("renewal_service_id"):   # 2026-09-30: the groups the customer picked (Imperium + CCTV)
            prod = await D["db"].products.find_one({"_id": _oid(it.get("product_id"))}) if it.get("product_id") else None
            if (prod or {}).get("panel_type") == "xtream":
                picks = [b for b in picks if b in _cctv_ids(prod)]
                if not picks or set(picks) == set(_cctv_ids(prod)):
                    continue
            q = {"order_id": order_id, "panel_type": {"$in": ["aether", "xtream"]}, "cmtv_bouquets": {"$exists": False}}
            if it.get("product_id"):
                q["product_id"] = str(it["product_id"])
            await D["db"].services.update_many(q, {"$set": {"cmtv_bouquets": picks}})


@router.get("/lineups")
async def lineups():
    return {"lineups": [{"key": k, "label": v["label"], "note": v["note"]} for k, v in LINEUPS.items()], "default": "full"}


@router.get("/lineups/{lineup}/groups")
async def lineup_groups(lineup: str, product_id: str):
    """Public (the storefront shows it before sign-in): the channel groups a customer can pick for this plan + line-up"""
    from fastapi import HTTPException
    p = await D["db"].products.find_one({"_id": _oid(product_id)}) if _oid(product_id) else None
    if not p or p.get("panel_type") != "aether" or p.get("account_type", "subscriber") != "subscriber" or p.get("is_trial") \
            or lineup not in LINEUPS:
        raise HTTPException(status_code=404, detail="No channel groups for this plan")
    pk = await packages()
    base = p.get("panel_package_id") or p.get("xtream_package_id")
    pkg = variant(base, lineup, pk) if pk else base
    groups = await groups_for(pkg) if pkg else []
    if not groups:
        raise HTTPException(status_code=503, detail="Channel groups can't be loaded right now")
    return {"lineup": lineup, "groups": [{k: g[k] for k in ("id", "name", "live", "movies", "series", "standard", "section")}
                                         for g in groups]}


@router.get("/cctv/groups")
async def cctv_groups(product_id: str):
    """Public: the channel groups a customer can pick for a CCTV plan (all of the plan's groups start ticked)"""
    from fastapi import HTTPException
    p = await D["db"].products.find_one({"_id": _oid(product_id)}) if _oid(product_id) else None
    if not _is_line_plan(p, "xtream"):
        raise HTTPException(status_code=404, detail="No channel groups for this plan")
    names = await _cctv_names(p.get("xtream_package_id"))
    groups = []
    for i in _cctv_ids(p):
        if i not in names:
            continue
        name, ch, ser = names[i]
        vod = "vod" in name.lower()   # VOD groups hold movies (counted as "channels" by the panel) or series
        groups.append({"id": i, "name": name, "live": 0 if vod else ch, "movies": ch if vod else 0, "series": ser,
                       "standard": True, "section": _cctv_section(name)})
    if not groups:
        raise HTTPException(status_code=503, detail="Channel groups can't be loaded right now")
    return {"groups": groups, "sections": CCTV_SECTIONS}
