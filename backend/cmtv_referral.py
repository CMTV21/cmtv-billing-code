"""Referral tiers for CMTV (CMTV local addition 2026-09-25).

Lifetime referrals = referrals completed in billing (`referrals`, status "completed") + past referrals the admin adds
(`cmtv_referral_history`, for the ones tracked by hand before billing, or that billing missed).

Tiers (defaults in DEFAULT_CONFIG, stored in `cmtv_config` _id "referral_tiers"):
  Member      0+   referrer $15 credit / friend $5 (the panel's own referral settings, unchanged)
  Advocate    5+   10% off every purchase
  Ambassador  10+  20% off every purchase, and the CMTV+ products are free (bundle and its add-ons)
The discount is applied by the server when the order is created (never trusted from the browser); if the customer
also enters a coupon, the bigger of the two applies. Trials and reseller packages never get a tier discount.
A free CMTV+ product is free when it renews the customer's own service, or when they don't have one yet (so an
Ambassador can't make extra free accounts).
"""
import logging
import re
from datetime import datetime

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/cmtv/referral", tags=["cmtv-referral"])
D = {}

DEFAULT_CONFIG = {
    "_id": "referral_tiers",
    "enabled": True,
    "tiers": [
        {"name": "Member", "min": 0, "pct": 0, "free_cmtv_plus": False},
        {"name": "Advocate", "min": 5, "pct": 10, "free_cmtv_plus": False},
        {"name": "Ambassador", "min": 10, "pct": 20, "free_cmtv_plus": True},
    ],
    # CMTV+ bundle, Stremio, CMTVpn, CMTV Audiobooks
    "free_product_ids": ["69b4c1fd58d8f7638531330b", "69da428e2e35f1db398fe722",
                         "69b4c17d58d8f76385313305", "69b4c26358d8f7638531330f"],
}
ENDED = ("failed", "cancelled", "terminated", "deleted")


def init(**deps):
    D.update(deps)
    db = deps["db"]
    D["history"] = db.cmtv_referral_history
    D["config_col"] = db.cmtv_config


async def startup():
    await D["history"].create_index([("user_id", 1), ("deleted", 1)])
    if not await D["config_col"].find_one({"_id": "referral_tiers"}):
        await D["config_col"].insert_one(dict(DEFAULT_CONFIG))


async def config():
    return await D["config_col"].find_one({"_id": "referral_tiers"}) or DEFAULT_CONFIG


def _oid(v):
    return ObjectId(v) if ObjectId.is_valid(str(v)) else None


def _get(item, key):
    return item.get(key) if isinstance(item, dict) else getattr(item, key, None)


# ---------------- counting and tiers ----------------

async def counts(user_id):
    billing = await D["referrals"].count_documents({"referrer_id": str(user_id), "status": "completed"})
    past = await D["history"].count_documents({"user_id": str(user_id), "deleted": {"$ne": True}})
    return billing, past


def tier_for_count(cfg, n):
    tiers = sorted(cfg["tiers"], key=lambda t: t["min"])
    cur = tiers[0]
    for t in tiers:
        if n >= t["min"]:
            cur = t
    nxt = next((t for t in tiers if t["min"] > n), None)
    return cur, nxt


async def status(user_id):
    cfg = await config()
    billing, past = await counts(user_id)
    n = billing + past
    cur, nxt = tier_for_count(cfg, n)
    return {"count": n, "billing_count": billing, "past_count": past,
            "tier": cur["name"], "pct": cur["pct"], "free_cmtv_plus": bool(cur.get("free_cmtv_plus")),
            "next": {"name": nxt["name"], "min": nxt["min"], "needs": nxt["min"] - n, "pct": nxt["pct"],
                     "free_cmtv_plus": bool(nxt.get("free_cmtv_plus"))} if nxt else None,
            "tiers": [{k: t[k] for k in ("name", "min", "pct")} | {"free_cmtv_plus": bool(t.get("free_cmtv_plus"))}
                      for t in sorted(cfg["tiers"], key=lambda t: t["min"])],
            "enabled": bool(cfg.get("enabled", True))}


# ---------------- discount at checkout ----------------

async def _free_allowed(user_id, product_id, renewal_service_id, seen):
    """Ambassador's free CMTV+ product: a renewal of their own service, or their first one"""
    if product_id in seen:
        return False
    if renewal_service_id:
        svc = await D["services"].find_one({"_id": _oid(renewal_service_id), "user_id": str(user_id)})
        return bool(svc) and str(svc.get("product_id")) == product_id
    have = await D["services"].find_one({"user_id": str(user_id), "product_id": product_id, "status": {"$nin": list(ENDED)}})
    return not have


async def order_discount(user_id, items):
    """{"amount", "tier", "pct", "lines"} for these order items. Item prices must already be the real product prices."""
    none = {"amount": 0.0, "tier": None, "pct": 0, "lines": []}
    cfg = await config()
    if not cfg.get("enabled", True) or not user_id:
        return none
    st = await status(user_id)
    if not st["pct"] and not st["free_cmtv_plus"]:
        return none
    free_ids = set(cfg.get("free_product_ids") or [])
    lines, total, seen = [], 0.0, set()
    for it in items:
        pid = str(_get(it, "product_id") or "")
        price = float(_get(it, "price") or 0)
        product = await D["products"].find_one({"_id": _oid(pid)}) if pid else None
        if not product or price <= 0 or product.get("is_trial") or product.get("account_type") == "reseller" \
                or str(_get(it, "account_type") or "") == "reseller":
            continue
        free = False
        if st["free_cmtv_plus"] and pid in free_ids:
            free = await _free_allowed(user_id, pid, _get(it, "renewal_service_id"), seen)
            seen.add(pid)
        off = price if free else round(price * st["pct"] / 100.0, 2)
        if off > 0:
            lines.append({"product_id": pid, "product_name": product.get("name"), "discount": off, "free": free})
            total += off
    total = round(total, 2)
    return {"amount": total, "tier": st["tier"] if total > 0 else None, "pct": st["pct"], "lines": lines}


async def member_price(user_id, product, renewal_service_id=None):
    """What this customer pays for one period of this product (used by PayPal auto-renew)"""
    prices = product.get("prices") or {}
    price = float(next(iter(prices.values()))) if prices else 0.0
    d = await order_discount(user_id, [{"product_id": str(product["_id"]), "price": price,
                                        "account_type": product.get("account_type"), "renewal_service_id": renewal_service_id}])
    return round(max(0.0, price - d["amount"]), 2)


# ---------------- tier changes ----------------

async def check_tier_change(user_id, reason=""):
    """Remember each customer's tier; tell the admin (Telegram, Billing topic) when someone moves up"""
    try:
        user = await D["users"].find_one({"_id": _oid(user_id)})
        if not user:
            return
        st = await status(user_id)
        old = user.get("cmtv_referral_tier") or "Member"
        if st["tier"] == old:
            return
        await D["users"].update_one({"_id": user["_id"]}, {"$set": {"cmtv_referral_tier": st["tier"],
                                                                    "cmtv_referral_tier_at": datetime.utcnow()}})
        order = [t["name"] for t in st["tiers"]]
        if old in order and order.index(st["tier"]) > order.index(old):
            import cmtv_autorenew
            perks = f"{st['pct']}% off everything" + (", CMTV+ free" if st["free_cmtv_plus"] else "")
            await cmtv_autorenew._notify_admin(
                f"🏆 {user.get('name', '')} <{user.get('email', '')}> reached {st['tier']} with {st['count']} referrals "
                f"({perks}; applied automatically at checkout).{(' ' + reason) if reason else ''}", kind="billing")
    except Exception as e:
        logger.warning(f"referral tier check for {user_id} failed: {e}")


async def on_order_referral(referred_user_id):
    """Called after a referral may have completed: re-check the referrer's tier"""
    ref = await D["referrals"].find_one({"referred_id": str(referred_user_id), "status": "completed"})
    if ref:
        await check_tier_change(ref["referrer_id"], "Their latest referral just made a purchase.")


# ---------------- admin helpers ----------------

def _clean(doc):
    doc = dict(doc)
    doc["id"] = str(doc.pop("_id"))
    return doc


async def _user_summary(u, billing, past, cfg):
    n = billing + past
    cur, _ = tier_for_count(cfg, n)
    return {"id": str(u["_id"]), "name": u.get("name"), "email": u.get("email"), "username": u.get("username"),
            "referral_code": u.get("referral_code"), "credit_balance": round(float(u.get("credit_balance") or 0), 2),
            "count": n, "billing_count": billing, "past_count": past, "tier": cur["name"]}


def init_routes():
    get_user, get_admin = D["get_current_user"], D["get_current_admin_user"]

    @router.get("/me")
    async def me(current_user: dict = Depends(get_user)):
        st = await status(current_user["sub"])
        st["past"] = [{"name": h.get("referred_name"), "date": h.get("date")} async for h in
                      D["history"].find({"user_id": current_user["sub"], "deleted": {"$ne": True}}).sort("date", -1)]
        return st

    @router.post("/quote")
    async def quote(data: dict, current_user: dict = Depends(get_user)):
        items = []
        for it in (data.get("items") or [])[:50]:
            product = await D["products"].find_one({"_id": _oid(it.get("product_id"))})
            if product:
                prices = product.get("prices") or {}
                items.append({"product_id": str(product["_id"]), "account_type": product.get("account_type"),
                              "price": float(next(iter(prices.values()))) if prices else 0.0,
                              "renewal_service_id": it.get("renewal_service_id")})
        return await order_discount(current_user["sub"], items)

    @router.get("/admin/overview")
    async def overview(q: str = "", current_user: dict = Depends(get_admin)):
        cfg = await config()
        billing = {r["_id"]: r["n"] async for r in D["referrals"].aggregate([
            {"$match": {"status": "completed"}}, {"$group": {"_id": "$referrer_id", "n": {"$sum": 1}}}])}
        past = {r["_id"]: r["n"] async for r in D["history"].aggregate([
            {"$match": {"deleted": {"$ne": True}}}, {"$group": {"_id": "$user_id", "n": {"$sum": 1}}}])}
        q = (q or "").strip()[:80]
        if q:
            rx = {"$regex": re.escape(q), "$options": "i"}
            cursor = D["users"].find({"role": "user", "$or": [{"name": rx}, {"email": rx}, {"username": rx}, {"referral_code": rx}]}).limit(30)
        else:
            ids = [_oid(i) for i in set(billing) | set(past) if _oid(i)]
            cursor = D["users"].find({"_id": {"$in": ids}})
        rows = [await _user_summary(u, billing.get(str(u["_id"]), 0), past.get(str(u["_id"]), 0), cfg) async for u in cursor]
        rows.sort(key=lambda r: (-r["count"], (r["name"] or "").lower()))
        return {"rows": rows, "tiers": (await status("none"))["tiers"]}

    @router.get("/admin/user/{user_id}")
    async def user_detail(user_id: str, current_user: dict = Depends(get_admin)):
        u = await D["users"].find_one({"_id": _oid(user_id)})
        if not u:
            raise HTTPException(status_code=404, detail="Customer not found")
        st = await status(user_id)
        refs = []
        async for r in D["referrals"].find({"referrer_id": user_id}).sort("created_at", -1):
            friend = await D["users"].find_one({"email": r.get("referred_email")}, {"name": 1})
            refs.append({"email": r.get("referred_email"), "name": (friend or {}).get("name"), "status": r.get("status"),
                         "rewarded": bool(r.get("rewarded")), "reward": r.get("reward_amount"),
                         "created_at": r.get("created_at"), "completed_at": r.get("completed_at")})
        past = [_clean(h) async for h in D["history"].find({"user_id": user_id, "deleted": {"$ne": True}}).sort("date", -1)]
        credits = []
        async for t in D["credit_transactions"].find({"user_id": user_id}).sort("created_at", -1).limit(15):
            credits.append({"amount": t.get("amount"), "type": t.get("transaction_type"), "description": t.get("description"),
                            "balance_after": t.get("balance_after"), "created_at": t.get("created_at")})
        return {**st, "name": u.get("name"), "email": u.get("email"), "referral_code": u.get("referral_code"),
                "credit_balance": round(float(u.get("credit_balance") or 0), 2),
                "referrals": refs, "past": past, "credits": credits}

    @router.post("/admin/user/{user_id}/past")
    async def add_past(user_id: str, data: dict, current_user: dict = Depends(get_admin)):
        if not await D["users"].find_one({"_id": _oid(user_id)}):
            raise HTTPException(status_code=404, detail="Customer not found")
        name = str(data.get("name") or "").strip()[:120]
        if not name:
            raise HTTPException(status_code=400, detail="Enter who they referred")
        try:
            date = datetime.strptime(str(data.get("date") or "")[:10], "%Y-%m-%d") if data.get("date") else None
        except ValueError:
            raise HTTPException(status_code=400, detail="Date must be YYYY-MM-DD")
        await D["history"].insert_one({"user_id": user_id, "referred_name": name, "date": date,
                                       "note": str(data.get("note") or "").strip()[:300], "source": "admin",
                                       "created_by": current_user.get("sub"), "created_at": datetime.utcnow()})
        await check_tier_change(user_id, "Past referral added by admin.")
        return {"ok": True, **(await status(user_id))}

    @router.delete("/admin/past/{hid}")
    async def remove_past(hid: str, current_user: dict = Depends(get_admin)):
        h = await D["history"].find_one({"_id": _oid(hid)})
        if not h:
            raise HTTPException(status_code=404, detail="Not found")
        await D["history"].update_one({"_id": h["_id"]}, {"$set": {"deleted": True, "deleted_at": datetime.utcnow(),
                                                                   "deleted_by": current_user.get("sub")}})
        await check_tier_change(h["user_id"])
        return {"ok": True}

    @router.post("/admin/user/{user_id}/credit")
    async def adjust_credit(user_id: str, data: dict, current_user: dict = Depends(get_admin)):
        try:
            amount = round(float(data.get("amount")), 2)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Enter an amount")
        reason = str(data.get("reason") or "").strip()[:200]
        if not amount or abs(amount) > 5000:
            raise HTTPException(status_code=400, detail="Amount must be between -5000 and 5000, not 0")
        if not reason:
            raise HTTPException(status_code=400, detail="Enter a reason (the customer sees it in their credit history)")
        if not await D["users"].find_one({"_id": _oid(user_id)}):
            raise HTTPException(status_code=404, detail="Customer not found")
        cs = D["credit_service"]
        try:
            if amount > 0:
                bal = await cs.add_credits(user_id=user_id, amount=amount, transaction_type="admin_adjustment",
                                           description=reason, created_by=current_user.get("sub"), bypass_enabled_check=True)
            else:
                bal = await cs.deduct_credits(user_id=user_id, amount=-amount, transaction_type="admin_adjustment", description=reason)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        logger.info(f"Admin {current_user.get('sub')} adjusted credit for {user_id} by {amount:+.2f}: {reason}")
        return {"ok": True, "credit_balance": round(float(bal), 2)}
