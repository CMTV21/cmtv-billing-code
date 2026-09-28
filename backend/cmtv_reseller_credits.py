"""Reseller credits in any amount, priced per credit (CMTV local addition 2026-09-28).

A reseller picks 50-1000 credits instead of a fixed 100/250/500/1000 pack. The order item carries `credits` (models.py
OrderItemCreate); create_order (server.py) prices it here, on the server, from the per-credit steps below, and
provision_order_services hands the panel code a copy of the pack product with reseller_credits = the chosen amount, so
every path (new CCTV reseller, CCTV top-up, new Imperium sub-reseller, Imperium top-up) gives exactly that many.
The fixed packs still work as before. Steps can be changed in cmtv_config {_id: "reseller_pricing"} without a deploy.
  GET /api/cmtv/reseller/pricing -> {min, max, servers: {cctv|imperium: {label, product_id, tiers [{min, rate}]}}}
"""
from fastapi import APIRouter

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
