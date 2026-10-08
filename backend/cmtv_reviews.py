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
2026-10-05 (2027 marketing plan #3): invites use CMTV's branded email look, and customers who didn't review get ONE more
ask at a happy moment (happy_round): 2-7 days after they renew, or 1-7 days after a support ticket of theirs is closed.
Never more than 2 invites per customer, the second at least 60 days after the first, and not within the survey gap.
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

import cmtv_lines as L

log = logging.getLogger("server")
router = APIRouter(prefix="/api/cmtv/reviews", tags=["cmtv-reviews"])
D = {}
SITE = "https://billing.cmtv.info"
TZ = ZoneInfo("America/Toronto")
DAILY_CAP = 10
MIN_DAYS = 30
SURVEY_GAP_DAYS = 30   # 2026-10-05 (owner): no review invite this soon after the survey
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
    # 2026-10-05 (owner): not within 30 days of the survey (sent it, answered it, or we replied); they get it later
    gap = now - timedelta(days=SURVEY_GAP_DAYS)
    recent_survey = set(await db.cmtv_survey_invites.distinct("user_id", {"$or": [{"created_at": {"$gte": gap}}, {"sent_at": {"$gte": gap}}]}))
    recent_survey |= set(await db.cmtv_survey_responses.distinct("user_id", {"$or": [
        {"completed_at": {"$gte": gap}}, {"first_completed_at": {"$gte": gap}}, {"followup.replies.at": {"$gte": gap}}]}))
    first_paid = {}
    async for o in db.orders.find({"status": "paid", "total": {"$gt": 0}}, {"user_id": 1, "paid_at": 1, "created_at": 1}):
        t = o.get("paid_at") or o.get("created_at")
        if isinstance(t, datetime):
            u = str(o.get("user_id"))
            first_paid[u] = min(first_paid.get(u, t), t)
    for uid, first in sorted(first_paid.items(), key=lambda x: x[1]):
        if uid in invited or uid in reviewed or uid in recent_survey or now - first < timedelta(days=MIN_DAYS):
            continue
        u = await db.users.find_one({"_id": _oid(uid), "role": "user"})
        if not u or not u.get("email") or str(u["email"]).lower().endswith("@panel.local"):
            continue
        # CMTV local change 2026-10-08: paid = shared rule (cmtv_lines): trial-named lines paid for and extended count,
        # unflagged "... TRIAL" lines don't
        if not [s async for s in db.services.find({"user_id": uid, "status": "active", "account_type": {"$ne": "reseller"}},
                                                  {"is_trial": 1, "product_name": 1, "expiry_date": 1, "created_at": 1})
                if L.is_paid_line(s, now)]:
            continue
        out.append(u)
    return out


MOMENTS = {   # 2026-10-05: (subject, heading, opening line) for each kind of ask
    None: ("How's CMTV going? (30-second review)", "How's CMTV going?",
           "you've been with us for a while now, and we'd love to hear how it's going."),
    "renewal": ("Thanks for renewing! Got 30 seconds?", "Thanks for staying with us",
                "thanks for renewing your CMTV plan. If you're enjoying it, a quick review would mean a lot to us."),
    "ticket": ("Glad we could help: got 30 seconds?", "Glad we could help",
               "we hope everything is working well again after your support ticket. If we looked after you, a quick review "
               "would mean a lot to us."),
}


def invite_email(first, link, moment=None):
    """(subject, html) of a review invite, in CMTV's branded email look (cmtv_gifts pieces)."""
    from cmtv_gifts import _shell, _button, P, FONT
    subject, heading, opening = MOMENTS.get(moment) or MOMENTS[None]
    body = (f'<p style="{P}">Hi {first}, {opening}</p>'
            f'<p style="margin:0 0 22px; font-size:15px; line-height:1.6; color:#374151; {FONT}">It takes 30 seconds: pick a star rating and add '
            "a line or two. With your OK we may show it on cmtv.info (first name and last initial only), and it really helps "
            "other people choose us.</p>"
            + _button(link, "&#11088; Leave a quick review")
            + f'<p style="margin:0 0 14px; font-size:13px; line-height:1.6; color:#6b7280; {FONT}">Something not right? Just reply or '
              "open a ticket and we'll fix it.</p>")
    return subject, _shell(f"{heading}. A quick star rating helps us a lot (30 seconds).", f"{heading} &#11088;", body)


async def send_invite(u: dict, moment: str = None) -> str:
    """Make the invite, email it (marketing), and DM it on Telegram if connected. Returns what happened."""
    db = D["db"]
    uid = str(u["_id"])
    token = secrets.token_urlsafe(18)
    now = datetime.utcnow()
    link = f"{SITE}/review?t={token}"
    await db.cmtv_review_invites.insert_one({"_id": token, "user_id": uid, "created_at": now, "expires_at": now + INVITE_TTL,
                                             "moment": moment})
    first = html.escape(short_name(u.get("name")).split(" ")[0])
    subject, body = invite_email(first or "there", link, moment)
    sent = False
    es = await D["get_email_service"]()
    if es and getattr(es, "enabled", False):
        sent = bool(await es.send_email(
            to_email=u["email"], subject=subject,
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


async def happy_candidates(now: datetime):
    """[(user, moment)]: customers who didn't review, at a happy moment (renewed 2-7 days ago / ticket closed 1-7 days ago),
    with fewer than 2 invites, the last one 60+ days ago, and not within the survey gap. 2026-10-05."""
    db = D["db"]
    reviewed = set(await db.cmtv_reviews.distinct("user_id"))
    gap = now - timedelta(days=SURVEY_GAP_DAYS)
    survey = set(await db.cmtv_survey_invites.distinct("user_id", {"$or": [{"created_at": {"$gte": gap}}, {"sent_at": {"$gte": gap}}]}))
    survey |= set(await db.cmtv_survey_responses.distinct("user_id", {"$or": [
        {"completed_at": {"$gte": gap}}, {"first_completed_at": {"$gte": gap}}, {"followup.replies.at": {"$gte": gap}}]}))
    moments = {}
    async for t in db.tickets.find({"status": "closed", "updated_at": {"$gte": now - timedelta(days=7), "$lt": now - timedelta(days=1)}},
                                   {"user_id": 1}):
        moments.setdefault(str(t.get("user_id")), "ticket")
    async for o in db.orders.find({"status": "paid", "total": {"$gt": 0}, "paid_at": {"$gte": now - timedelta(days=7), "$lt": now - timedelta(days=2)}},
                                  {"user_id": 1, "paid_at": 1, "items": 1}):
        uid = str(o.get("user_id"))
        renew = any(i.get("action_type") in ("renew", "extend") for i in o.get("items") or []) or \
            await db.orders.find_one({"user_id": o.get("user_id"), "status": "paid", "total": {"$gt": 0}, "paid_at": {"$lt": o["paid_at"]}}, {"_id": 1})
        if renew:
            moments.setdefault(uid, "renewal")
    out = []
    for uid, moment in moments.items():
        if uid in reviewed or uid in survey or not _oid(uid):
            continue
        invs = await db.cmtv_review_invites.find({"user_id": uid}).sort("created_at", -1).to_list(5)
        if len(invs) >= 2 or (invs and invs[0]["created_at"] > now - timedelta(days=60)):
            continue
        u = await db.users.find_one({"_id": _oid(uid), "role": "user"})
        if not u or not u.get("email") or str(u["email"]).lower().endswith("@panel.local") or u.get("cmtv_demo"):
            continue
        out.append((u, moment))
    return out


async def happy_round(now: datetime = None) -> int:
    now = now or datetime.utcnow()
    room = DAILY_CAP - await D["db"].cmtv_review_invites.count_documents({"created_at": {"$gte": now - timedelta(hours=24)}})
    n = 0
    for u, moment in (await happy_candidates(now))[:max(room, 0)]:
        try:
            await send_invite(u, moment)
            n += 1
        except Exception as e:
            log.warning(f"happy-moment review invite failed for {u.get('_id')}: {e}")
    return n


async def _loop():
    while True:
        try:
            cfg = await D["db"].cmtv_config.find_one({"_id": "reviews"}) or {}
            hour = datetime.now(TZ).hour
            if cfg.get("invites_enabled", False) and 11 <= hour < 19:
                n = await invite_round()
                n += await happy_round()   # 2026-10-05: second ask at a happy moment
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
