"""CMTV+ automatic setup (CMTV local addition 2026-10-05; before this CMTV+ was set up by hand).
CMTV+ = Nuvio (or Stremio, the customer's pick) + CMTVpn + CMTV Audiobooks for one yearly price. The CMTV+ product is
marked `cmtv_plus: True`. Buying OR renewing CMTV+ makes sure the customer has all three, each with the plan's months:
- a part the customer already has (paid, trial or ended, same login) is EXTENDED: no second account;
- a missing part is CREATED (login email as usual).
Each part runs through the normal provision_cockpit_service (Cockpit / CMTV Nuvio server / abadmin), so failures are
reported per part ("CMTV+: CMTVpn: ...") and the order shows Not provisioned / partial like any other.
The part services get `cmtv_plus: True` (+ product = the paid part, is_trial False), so the dashboard shows them as
"Part of CMTV+" and their Renew button renews CMTV+ (all three) instead of each part at its own price.
Stremio instead of Nuvio: the cart item says "Stremio" (checkout drop-down: "CMTV+ (with Stremio)"), or on a renewal the
customer's CMTV+ already has Stremio and no Nuvio.
"""
import logging
from datetime import datetime

from bson import ObjectId

logger = logging.getLogger(__name__)
D = {}
PARTS = ["nuviocloud", "vpn", "audiobooks"]
STREMIO = "nuvio"   # Cockpit's Nuvio module is the classic Stremio add-on
NAMES = {"nuviocloud": "Nuvio", "nuvio": "Stremio", "vpn": "CMTVpn", "audiobooks": "CMTV Audiobooks"}
GONE = ["deleted", "cancelled", "terminated", "failed", "removed"]


def init(**deps):
    D.update(deps)


async def part_product(module):
    """The paid yearly product for a part (not a trial, not a reseller pack)."""
    best = None
    async for p in D["db"].products.find({"cockpit_module": module, "is_trial": {"$ne": True},
                                         "account_type": {"$ne": "reseller"}, "cmtv_gift": {"$ne": True}}):
        if (p.get("prices") or {}).get("12") is None:
            continue
        if best is None or (p.get("active") and not best.get("active")):
            best = p
    return best


async def existing(user_id, module):
    """The customer's own account for this part (same login gets extended), newest expiry first."""
    return await D["db"].services.find_one(
        {"user_id": user_id, "cockpit_module": module, "username": {"$nin": [None, ""]}, "status": {"$nin": GONE}},
        sort=[("cmtv_plus", -1), ("expiry_date", -1)])


async def wants_stremio(user_id, item):
    if "stremio" in str(item.get("product_name") or "").lower():
        return True
    has = lambda m: D["db"].services.find_one({"user_id": user_id, "cockpit_module": m, "cmtv_plus": True,
                                               "status": {"$nin": GONE}}, {"_id": 1})
    return bool(await has(STREMIO)) and not await has("nuviocloud")


async def plan(user_id, item):
    """[(module, part product, existing service or None)] for this CMTV+ item. Missing products -> part product None."""
    modules = [STREMIO if m == "nuviocloud" and await wants_stremio(user_id, item) else m for m in PARTS]
    return [(m, await part_product(m), await existing(user_id, m)) for m in modules]


async def provision(order_id, order, user, item, settings, email_service, run_item, provision_cockpit_service):
    """Called from provision_order_services for a CMTV+ item (product.cmtv_plus)."""
    uid = order["user_id"]
    months = max(1, int(item.get("term_months") or 12))
    bundle_id = str(item.get("product_id") or "")
    for module, product, svc in await plan(uid, item):
        name = NAMES.get(module, module)
        if not product:
            await run_item(f"CMTV+: {name}", {**item, "renewal_service_id": None},
                           _fail(f"no paid {name} product with a 12-month price (Admin > Products)"))
            continue
        part = {"product_id": str(product["_id"]), "product_name": product.get("name") or name, "term_months": months,
                "price": 0, "account_type": "subscriber",
                "action_type": "extend" if svc else "create_new", "renewal_service_id": str(svc["_id"]) if svc else None}
        before = datetime.utcnow()
        await run_item(f"CMTV+: {product.get('name') or name}", part,
                       provision_cockpit_service(order_id, order, user, part, product, settings, email_service))
        # tag the part only if it worked: the extended one (renewal sets updated_at) or the one just created for this order
        q = {"_id": svc["_id"], "updated_at": {"$gte": before}} if svc else \
            {"user_id": uid, "order_id": order_id, "cockpit_module": module, "created_at": {"$gte": before}}
        await D["db"].services.update_one(q, {"$set": {
            "cmtv_plus": True, "cmtv_plus_product_id": bundle_id, "cmtv_plus_order_id": order_id,
            "product_id": str(product["_id"]), "product_name": product.get("name") or name, "is_trial": False}})
        logger.info(f"CMTV+ order {order_id}: {name} {'extended' if svc else 'created'}")


async def _fail(why):
    raise RuntimeError(why)
