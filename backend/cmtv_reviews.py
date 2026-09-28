"""Customer reviews, collected by billing (CMTV local addition 2026-09-28). No Google / Trustpilot account needed.

Invites: an hourly job (sends 11:00-19:00 Toronto, at most DAILY_CAP a day so the backlog trickles out) picks customers
with a real email, an active paid (non-trial) service and a first paid order at least 30 days ago, who were never invited
and never reviewed. It makes a one-time link https://billing.cmtv.info/review?t=<token> (60 days) and sends a short
email (marketing: has the unsubscribe link, skipped for unsubscribed customers) plus a Telegram message if they
connected Telegram (cmtv_telegram_alerts.queue). Invites: cmtv_review_invites (_id = token).
Reviews: cmtv_reviews {user_id, rating 1-5, text, display_name ("Chris M."), province, consent, status pending/approved/
rejected, created_at, decided_at, decided_by}. Nothing is public until the admin approves it in Admin > Reviews, and only
with the customer's consent. The Ops bot (Billing topic) is told about each new review.
Public: GET /api/cmtv/reviews/public -> approved reviews (newest first, max 12) + count + average (cmtv.info shows them).
"""
import asyncio
import html
import logging
import re
import secrets
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from bson import ObjectId
from fastapi import APIRouter, Body, Depends, HTTPException

log = logging.getLogger("server")
router = APIRouter(prefix="/api/cmtv/reviews", tags=["cmtv-reviews"])
D = {}
SITE = "https://billing.cmtv.info"
TZ = ZoneInfo("America/Toronto")
DAILY_CAP = 10
MIN_DAYS = 30
INVITE_TTL = timedelta(days=60)
PROVINCES = ["Alberta", "British Columbia", "Manitoba", "New Brunswick", "Newfoundland and Labrador", "Nova Scotia",
             "Ontario", "Prince Edward Island", "Quebec", "Saskatchewan", "Northwest Territories", "Nunavut", "Yukon"]


def init(**deps):
    D.update(deps)


def _oid(v):
    return ObjectId(v) if ObjectId.is_valid(str(v)) else None


def short_name(name: str) -> str:
    """'Chris Marshall' -> 'Chris M.'; one word stays as it is"""
    parts = [p for p in re.sub(r"[^\w\s'-]", " ", str(name or "")).split() if p]
    if not parts:
        return "CMTV customer"
    return parts[0].capitalize() if len(parts) == 1 else f"{parts[0].capitalize()} {parts[-1][0].upper()}."


async def _notify(text: str):
    try:
        import cmtv_notify
        await cmtv_notify.ops(text, "billing", await D["get_settings"]())
    except Exception as e:
        log.warning(f"review notify failed: {e}")


def _public_review(r: dict) -> dict:
    return {"id": str(r["_id"]), "rating": r["rating"], "text": r["text"], "name": r["display_name"],
            "province": r.get("province") or "", "date": r["created_at"].date().isoformat()}


# ---------- invites ----------

async def eligible_customers(now: datetime):
    """Customers to invite now: real email, active paid service, first paid order >= 30 days ago, never invited/reviewed"""
    db = D["db"]
    out = []
    invited = set(await db.cmtv_review_invites.distinct("user_id"))
    reviewed = set(await db.cmtv_reviews.distinct("user_id"))
    first_paid = {}
    async for o in db.orders.find({"status": "paid", "total": {"$gt": 0}}, {"user_id": 1, "paid_at": 1, "created_at": 1}):
        t = o.get("paid_at") or o.get("created_at")
        if isinstance(t, datetime):
            u = str(o.get("user_id"))
            first_paid[u] = min(first_paid.get(u, t), t)
    for uid, first in sorted(first_paid.items(), key=lambda x: x[1]):
        if uid in invited or uid in reviewed or now - first < timedelta(days=MIN_DAYS):
            continue
        u = await db.users.find_one({"_id": _oid(uid), "role": "user"})
        if not u or not u.get("email") or str(u["email"]).lower().endswith("@panel.local"):
            continue
        if not await db.services.find_one({"user_id": uid, "status": "active", "is_trial": {"$ne": True},
                                           "account_type": {"$ne": "reseller"}}):
            continue
        out.append(u)
    return out


async def send_invite(u: dict) -> str:
    """Make the invite, email it (marketing), and DM it on Telegram if connected. Returns what happened."""
    db = D["db"]
    uid = str(u["_id"])
    token = secrets.token_urlsafe(18)
    now = datetime.utcnow()
    link = f"{SITE}/review?t={token}"
    await db.cmtv_review_invites.insert_one({"_id": token, "user_id": uid, "created_at": now, "expires_at": now + INVITE_TTL})
    first = html.escape(short_name(u.get("name")).split(" ")[0])
    body = (f"<h2 style=\"margin:0 0 8px\">How's CMTV going?</h2>"
            f"<p>Hi {first}, you've been with us for a while now, and we'd love to hear how it's going.</p>"
            f"<p>It takes 30 seconds: pick a star rating and add a line or two. With your OK we may show it on cmtv.info "
            f"(first name and last initial only), and it really helps other people choose us.</p>"
            f"<p style=\"margin:22px 0\"><a href=\"{link}\" style=\"background:#22e6f2;color:#07101a;padding:12px 22px;"
            f"border-radius:999px;text-decoration:none;font-weight:700\">Leave a quick review</a></p>"
            f"<p style=\"color:#666;font-size:13px\">Something not right? Just reply or open a ticket and we'll fix it.</p>")
    sent = False
    es = await D["get_email_service"]()
    if es and getattr(es, "enabled", False):
        sent = bool(await es.send_email(
            to_email=u["email"], subject="How's CMTV going? (30-second review)",
            html_content=es._wrap_email(body, "Leave a review", u["email"], "marketing"),
            email_type="marketing", template_type="cmtv_review_request", customer_id=uid,
            recipient_name=u.get("name") or ""))
    tg = (u.get("cmtv_telegram") or {}).get("chat_id")
    if tg:
        try:
            import cmtv_telegram_alerts
            await cmtv_telegram_alerts.queue(uid, tg, f"⭐ <b>How's CMTV going, {first}?</b>\n\nA quick star rating helps us a lot "
                                             "(30 seconds).", [[{"text": "Leave a review", "url": link}]], kind="review")
        except Exception as e:
            log.warning(f"review invite telegram failed: {e}")
    await db.cmtv_review_invites.update_one({"_id": token}, {"$set": {"emailed": sent, "telegram": bool(tg)}})
    return "sent" if (sent or tg) else "not_sent"


async def invite_round(now: datetime = None) -> int:
    now = now or datetime.utcnow()
    db = D["db"]
    day_start = now - timedelta(hours=24)
    room = DAILY_CAP - await db.cmtv_review_invites.count_documents({"created_at": {"$gte": day_start}})
    if room <= 0:
        return 0
    n = 0
    for u in (await eligible_customers(now))[:room]:
        try:
            await send_invite(u)
            n += 1
        except Exception as e:
            log.warning(f"review invite failed for {u.get('_id')}: {e}")
    return n


async def _loop():
    while True:
        try:
            cfg = await D["db"].cmtv_config.find_one({"_id": "reviews"}) or {}
            hour = datetime.now(TZ).hour
            if cfg.get("invites_enabled", False) and 11 <= hour < 19:
                n = await invite_round()
                if n:
                    log.info(f"review invites sent: {n}")
        except Exception as e:
            log.warning(f"review invites failed: {e}")
        await asyncio.sleep(3600)


async def startup():
    asyncio.create_task(_loop())


# ---------- routes ----------

def init_routes():
    admin = D["get_current_admin_user"]

    @router.get("/invite/{token}")
    async def invite(token: str):
        db = D["db"]
        inv = await db.cmtv_review_invites.find_one({"_id": token})
        if not inv or inv.get("expires_at", datetime.min) < datetime.utcnow():
            raise HTTPException(404, "This review link has expired.")
        u = await db.users.find_one({"_id": _oid(inv["user_id"])}) or {}
        done = await db.cmtv_reviews.find_one({"user_id": inv["user_id"]})
        return {"name": short_name(u.get("name")), "already": bool(done), "provinces": PROVINCES}

    @router.post("/submit")
    async def submit(data: dict = Body(...)):
        db = D["db"]
        token = str(data.get("token") or "")
        inv = await db.cmtv_review_invites.find_one({"_id": token})
        if not inv or inv.get("expires_at", datetime.min) < datetime.utcnow():
            raise HTTPException(404, "This review link has expired.")
        if await db.cmtv_reviews.find_one({"user_id": inv["user_id"]}):
            raise HTTPException(409, "You've already left a review. Thank you!")
        try:
            rating = int(data.get("rating"))
        except (TypeError, ValueError):
            rating = 0
        if not 1 <= rating <= 5:
            raise HTTPException(400, "Pick 1 to 5 stars.")
        text = re.sub(r"\s+", " ", str(data.get("text") or "")).strip()[:600]
        if len(text) < 3:
            raise HTTPException(400, "Add a few words about your experience.")
        u = await db.users.find_one({"_id": _oid(inv["user_id"])}) or {}
        name = re.sub(r"\s+", " ", str(data.get("display_name") or "")).strip()[:40] or short_name(u.get("name"))
        province = str(data.get("province") or "")
        province = province if province in PROVINCES else ""
        consent = bool(data.get("consent"))
        doc = {"user_id": inv["user_id"], "rating": rating, "text": text, "display_name": name, "province": province,
               "consent": consent, "status": "pending", "created_at": datetime.utcnow(), "invite": token}
        await db.cmtv_reviews.insert_one(doc)
        await db.cmtv_review_invites.update_one({"_id": token}, {"$set": {"used_at": datetime.utcnow()}})
        stars = "★" * rating + "☆" * (5 - rating)
        warn = "⚠️ " if rating <= 3 else ""
        await _notify(f"{warn}⭐ New review {stars} from {u.get('name')} <{u.get('email')}>\n\n“{text}”\n\n"
                      f"{'OK to publish' if consent else 'Private feedback (no consent to publish)'} · "
                      f"Approve or reject in Admin > Reviews: {SITE}/admin/reviews")
        return {"ok": True, "low": rating <= 3}

    @router.get("/public")
    async def public():
        db = D["db"]
        q = {"status": "approved", "consent": True}
        rows = await db.cmtv_reviews.find(q).sort("created_at", -1).limit(12).to_list(12)
        agg = await db.cmtv_reviews.aggregate([{"$match": q}, {"$group": {"_id": None, "n": {"$sum": 1}, "avg": {"$avg": "$rating"}}}]).to_list(1)
        return {"reviews": [_public_review(r) for r in rows], "count": (agg[0]["n"] if agg else 0),
                "average": round(agg[0]["avg"], 1) if agg else None}

    @router.get("/admin")
    async def admin_list(current_user: dict = Depends(admin)):
        db = D["db"]
        out = []
        async for r in db.cmtv_reviews.find({}).sort("created_at", -1).limit(300):
            u = await db.users.find_one({"_id": _oid(r["user_id"])}, {"name": 1, "email": 1}) or {}
            out.append({**_public_review(r), "status": r["status"], "consent": r.get("consent", False),
                        "user_id": r["user_id"], "customer": u.get("name"), "email": u.get("email"),
                        "decided_by": r.get("decided_by")})
        cfg = await db.cmtv_config.find_one({"_id": "reviews"}) or {}
        return {"reviews": out, "invites_sent": await db.cmtv_review_invites.count_documents({}),
                "invites_enabled": cfg.get("invites_enabled", False),
                "waiting": len(await eligible_customers(datetime.utcnow()))}

    @router.post("/admin/{rid}")
    async def decide(rid: str, data: dict = Body(...), current_user: dict = Depends(admin)):
        status = str(data.get("status") or "")
        if status not in ("approved", "rejected", "pending"):
            raise HTTPException(400, "status must be approved, rejected or pending")
        r = await D["db"].cmtv_reviews.find_one({"_id": _oid(rid)})
        if not r:
            raise HTTPException(404, "Review not found")
        if status == "approved" and not r.get("consent"):
            raise HTTPException(400, "The customer didn't agree to publish this one, so it stays private.")
        await D["db"].cmtv_reviews.update_one({"_id": r["_id"]}, {"$set": {
            "status": status, "decided_at": datetime.utcnow(), "decided_by": current_user.get("email") or current_user.get("sub")}})
        return {"ok": True}

    @router.post("/admin-settings")
    async def settings(data: dict = Body(...), current_user: dict = Depends(admin)):
        await D["db"].cmtv_config.update_one({"_id": "reviews"}, {"$set": {"invites_enabled": bool(data.get("invites_enabled"))}}, upsert=True)
        return {"ok": True}
