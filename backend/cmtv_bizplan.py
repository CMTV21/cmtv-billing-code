"""Admin > Business plan (CMTV local addition 2026-10-05, the owner: "create a business plan section and put the marketing
section on billing"). The page (pages/cmtv/AdminBusinessPlanPage.js) holds the plan's words; this works out the live
numbers behind each 2027 marketing target, so the plan shows progress instead of sitting in a document:
  revenue (Finances ledger, this calendar year), reachable customers (active paying customers with a real email),
  yearly share (12-month share of paid TV plan purchases, last 12 months), referrals (referred sign-ups this year),
  reviews (approved), website trial -> paid (TV trials 7-120 days old, people who hadn't paid before), auto-renew on.
Targets: cmtv_config {_id: "bizplan", targets: {...}} (defaults below; editable on the page).
"""
from datetime import datetime, timedelta

from bson import ObjectId
from fastapi import APIRouter, Body, Depends, HTTPException

router = APIRouter(prefix="/api/cmtv/bizplan", tags=["cmtv-bizplan"])
D = {}
TARGETS = {"revenue": 45000, "reachable": 150, "yearly_share": 50, "referrals": 40, "reviews": 25, "trial_conversion": 40,
           "autorenew": 25}


def init(**deps):
    D.update(deps)


async def targets():
    doc = await D["db"].cmtv_config.find_one({"_id": "bizplan"}) or {}
    return {**TARGETS, **(doc.get("targets") or {})}


async def metrics(now=None):
    db = D["db"]
    now = now or datetime.utcnow()
    year = datetime(now.year, 1, 1)
    out = {"year": now.year}
    # revenue, this year and the last 12 months (Finances ledger)
    agg = await db.fin_transactions.aggregate([{"$match": {"deleted": {"$ne": True}, "date": {"$gte": year}}},
                                               {"$group": {"_id": None, "r": {"$sum": "$amount"}}}]).to_list(1)
    out["revenue"] = round((agg or [{"r": 0}])[0]["r"])
    agg = await db.fin_transactions.aggregate([{"$match": {"deleted": {"$ne": True}, "date": {"$gte": now - timedelta(days=365)}}},
                                               {"$group": {"_id": None, "r": {"$sum": "$amount"}}}]).to_list(1)
    out["revenue_12m"] = round((agg or [{"r": 0}])[0]["r"])
    # active paying customers, and how many we can reach by email
    active = set()
    async for s in db.services.find({"status": "active", "is_trial": {"$ne": True}, "account_type": {"$ne": "reseller"}},
                                    {"user_id": 1, "start_date": 1, "created_at": 1, "expiry_date": 1}):
        st = s.get("start_date") or s.get("created_at")
        if st and s.get("expiry_date") and (s["expiry_date"] - st).days < 25 and s["expiry_date"] - now < timedelta(days=25):
            continue   # a short panel trial without the trial flag
        active.add(str(s.get("user_id")))
    reach = 0
    async for u in db.users.find({"_id": {"$in": [ObjectId(x) for x in active if ObjectId.is_valid(x)]}}, {"email": 1}):
        e = str(u.get("email") or "")
        reach += "@" in e and not e.endswith("@panel.local")
    out["active_customers"], out["reachable"] = len(active), reach
    # yearly share of paid TV plan purchases, last 12 months
    tv = yearly = 0
    async for o in db.orders.find({"status": "paid", "total": {"$gt": 0}, "payment_method": {"$ne": "test"},
                                   "paid_at": {"$gte": now - timedelta(days=365)}}, {"items": 1}):
        for i in o.get("items") or []:
            if i.get("account_type") == "subscriber" and int(i.get("term_months") or 0) > 0 and not i.get("gift"):
                tv += 1
                yearly += int(i.get("term_months") or 0) >= 12
    out["yearly_share"] = round(100 * yearly / tv) if tv else 0
    out["referrals"] = await db.referrals.count_documents({"created_at": {"$gte": year}})
    out["referrals_completed"] = await db.referrals.count_documents({"created_at": {"$gte": year}, "status": "completed"})
    out["reviews"] = await db.cmtv_reviews.count_documents({"status": "approved"})
    out["autorenew"] = await db.services.count_documents({"auto_renew.status": "ACTIVE"})
    # website TV trials -> paid
    tps = {str(p["_id"]) async for p in db.products.find({"is_trial": True, "panel_type": {"$in": ["xtream", "aether"]}}, {"_id": 1})}
    seen, new, paid = set(), 0, 0
    async for o in db.orders.find({"status": "paid", "created_at": {"$gte": now - timedelta(days=120), "$lt": now - timedelta(days=7)}},
                                  {"user_id": 1, "items": 1, "created_at": 1}).sort("created_at", 1):
        if not any(i.get("product_id") in tps for i in o.get("items") or []) or o["user_id"] in seen:
            continue
        seen.add(o["user_id"])
        if await db.orders.find_one({"user_id": o["user_id"], "status": "paid", "total": {"$gt": 0}, "paid_at": {"$lt": o["created_at"]}}, {"_id": 1}):
            continue
        new += 1
        paid += bool(await db.orders.find_one({"user_id": o["user_id"], "status": "paid", "total": {"$gt": 0},
                                               "paid_at": {"$gte": o["created_at"]}}, {"_id": 1}))
    out["trial_conversion"] = round(100 * paid / new) if new else 0
    out["trials_counted"] = new
    return out


def init_routes():
    admin = D["get_current_admin_user"]

    @router.get("/admin")
    async def get_plan(current_user: dict = Depends(admin)):
        return {"metrics": await metrics(), "targets": await targets()}

    @router.post("/admin/targets")
    async def set_targets(data: dict = Body(...), current_user: dict = Depends(admin)):
        t = await targets()
        for k in TARGETS:
            if k in data:
                try:
                    v = float(data[k])
                except (TypeError, ValueError):
                    raise HTTPException(400, f"{k}: a number")
                if v < 0:
                    raise HTTPException(400, f"{k}: 0 or more")
                t[k] = int(v) if v == int(v) else v
        await D["db"].cmtv_config.update_one({"_id": "bizplan"}, {"$set": {"targets": t, "updated_at": datetime.utcnow()}}, upsert=True)
        return {"targets": t}
