"""Reseller credits in any amount, priced per credit (CMTV local addition 2026-09-28).

A reseller picks 50-1000 credits instead of a fixed 100/250/500/1000 pack. The order item carries `credits` (models.py
OrderItemCreate); create_order (server.py) prices it here, on the server, from the per-credit steps below, and
provision_order_services hands the panel code a copy of the pack product with reseller_credits = the chosen amount, so
every path (new CCTV reseller, CCTV top-up, new Imperium sub-reseller, Imperium top-up) gives exactly that many.
The fixed packs still work as before. Steps can be changed in cmtv_config {_id: "reseller_pricing"} without a deploy.
  GET /api/cmtv/reseller/pricing -> {min, max, servers: {cctv|imperium: {label, product_id, tiers [{min, rate}]}}}
"""
import logging
from datetime import datetime

from fastapi import APIRouter, Depends

log = logging.getLogger("server")
router = APIRouter(prefix="/api/cmtv/reseller", tags=["cmtv-reseller"])
D = {}
MIN_CREDITS, MAX_CREDITS = 50, 1000
LABEL = {"cctv": "CCTV", "imperium": "Imperium"}
# price per credit from each amount up (the user's prices, 2026-09-28)
DEFAULT_TIERS = {
    "cctv": [{"min": 50, "rate": 3.00}, {"min": 250, "rate": 2.75}, {"min": 500, "rate": 2.50}, {"min": 1000, "rate": 2.25}],
    "imperium": [{"min": 50, "rate": 4.00}, {"min": 250, "rate": 3.80}, {"min": 500, "rate": 3.70}, {"min": 1000, "rate": 3.50}],
}


def init(**deps):
    D.update(deps)


def server_of(product: dict):
    pt = (product or {}).get("panel_type")
    if pt in ("aether", "nxtdash"):
        return "imperium"
    if pt in ("xtream", "xuione"):
        return "cctv"
    return None


async def tiers_for(server: str):
    cfg = await D["db"].cmtv_config.find_one({"_id": "reseller_pricing"}) or {}
    t = (cfg.get("tiers") or {}).get(server) or DEFAULT_TIERS.get(server) or []
    return sorted(({"min": int(x["min"]), "rate": float(x["rate"])} for x in t), key=lambda x: x["min"])


def rate_for(tiers, credits: int) -> float:
    r = None
    for t in tiers:
        if credits >= t["min"]:
            r = t["rate"]
    if r is None:
        raise ValueError("No price for that amount")
    return r


async def custom_price(product: dict, credits: int):
    """(price, item name) for `credits` of this reseller pack's server. Raises ValueError with a customer-readable reason."""
    if (product or {}).get("account_type") != "reseller":
        raise ValueError("Only reseller packs can have a credit amount")
    server = server_of(product)
    if not server:
        raise ValueError("This pack can't be bought in a custom amount")
    if not (MIN_CREDITS <= int(credits) <= MAX_CREDITS):
        raise ValueError(f"Choose between {MIN_CREDITS} and {MAX_CREDITS} credits (message us for more)")
    rate = rate_for(await tiers_for(server), int(credits))
    return round(int(credits) * rate, 2), f"{LABEL[server]} Reseller Credits - {int(credits)} credits"


def init_routes():
    """Routes that need the signed-in customer (dependency passed in from server.py)"""
    current = D["get_current_user"]

    @router.get("/mine")
    async def mine(current_user: dict = Depends(current)):
        """The customer's own reseller panels, with the credit balance: CCTV from the hourly panel sync
        (imported_users.credits), Imperium read live from the Aether API. Used by the dashboard's reseller box."""
        db = D["db"]
        uid = current_user["sub"]
        out = []
        async for s in db.services.find({"user_id": uid, "account_type": "reseller", "status": "active"}).sort("created_at", 1):
            server = "imperium" if s.get("panel_type") in ("aether", "nxtdash") else "cctv"
            username = s.get("xtream_username") or s.get("username") or ""
            balance, as_of = None, None
            if server == "cctv":
                iu = await db.imported_users.find_one({"username": username, "account_type": "reseller"})
                if iu and iu.get("credits") is not None:
                    balance, as_of = float(iu["credits"]), iu.get("last_synced") or iu.get("updated_at")
            else:
                try:
                    from aether_service import get_aether_service
                    import cmtv_aether_reseller
                    panels = ((await D["get_settings"]()).get("aether") or {}).get("panels") or []
                    ae = get_aether_service(panels[int(s.get("panel_index") or 0)]) if panels else None
                    if ae:
                        sub = await cmtv_aether_reseller._find_sub(ae, await ae._base(), username)
                        if sub and sub.get("credits_balance") is not None:
                            balance, as_of = float(sub["credits_balance"]), datetime.utcnow()
                except Exception as e:
                    log.warning(f"reseller balance for {username}: {e}")
            out.append({"id": str(s["_id"]), "server": server, "label": LABEL[server], "username": username,
                        "password": s.get("xtream_password") or s.get("password") or "",
                        "panel_url": s.get("panel_url") or ("https://bestpanel.xyz" if server == "imperium" else ""),
                        "credits": balance, "as_of": as_of.isoformat() + "Z" if isinstance(as_of, datetime) else None})
        return {"panels": out}


@router.get("/pricing")
async def pricing():
    out = {}
    for server in ("cctv", "imperium"):
        # the pack product a custom amount is ordered through: the smallest active pack of that server
        base = None
        async for p in D["db"].products.find({"account_type": "reseller", "active": {"$ne": False}}):
            if server_of(p) == server and (base is None or float(p.get("reseller_credits") or 0) < float(base.get("reseller_credits") or 0)):
                base = p
        if base:
            out[server] = {"label": LABEL[server], "product_id": str(base["_id"]), "tiers": await tiers_for(server)}
    return {"min": MIN_CREDITS, "max": MAX_CREDITS, "servers": out}
