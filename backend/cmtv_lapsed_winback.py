"""Come-back offer for lapsed paying customers (CMTV local addition 2026-09-28; the user's rules).
14 days after a paid TV line ended, the customer gets one email with a personal 15% code (single use, their account only,
valid 7 days, plans only). ONCE PER CUSTOMER, EVER (so letting a plan lapse to wait for the email only works once).
Not sent when: the line is still active on the panel (renewed outside billing), they have any other active paid service,
they're a trial-only customer (that's cmtv_trial_winback), no real email, or they unsubscribed from marketing emails.
Hourly, 10:00-20:00 Toronto. Codes are personal coupons (cmtv_user_id), checked at checkout by cmtv_trial_winback's
check_order_coupon / check_validate (owner only; not first-order-only). Log: cmtv_lapsed_winback (_id = user id).
Settings: cmtv_config _id "lapsed_winback" {enabled, percent, valid_days, delay_days}.
Admin: GET /api/cmtv/lapsed-winback/preview (who'd get it next run), /sent.
"""
import asyncio
import logging
import re
import secrets
from datetime import datetime, timedelta
from html import escape
from zoneinfo import ZoneInfo

from bson import ObjectId
from fastapi import APIRouter, Depends

import cmtv_trial_winback as TW

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/cmtv/lapsed-winback", tags=["cmtv-lapsed-winback"])
D = {}
TZ = ZoneInfo("America/Toronto")
DEFAULTS = {"enabled": True, "percent": 15, "valid_days": 7, "delay_days": 14}
CATCH_UP_HOURS = 48
SEND_HOURS = range(10, 20)
KIND = "lapsed_winback"


def init(**deps):
    D.update(deps)


def _oid(v):
    return ObjectId(v) if ObjectId.is_valid(str(v)) else None


def _dt(v):
    if isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v).replace("Z", "")[:19])
    except Exception:
        return None


async def config():
    doc = await D["db"].cmtv_config.find_one({"_id": "lapsed_winback"}) or {}
    return {**DEFAULTS, **{k: v for k, v in doc.items() if k != "_id"}}


def _paid_tv(s):
    return not s.get("is_trial") and s.get("account_type", "subscriber") != "reseller" and s.get("panel_type") not in (None, "", "manual") \
        and not s.get("cmtv_demo")


async def _line_active_on_panel(s, now):
    name = s.get("xtream_username") or s.get("username") or ""
    if not name:
        return False
    iu = await D["db"].imported_users.find_one({"username": {"$regex": f"^{re.escape(name)}$", "$options": "i"},
                                                "account_type": {"$ne": "reseller"}})
    if not iu or str(iu.get("status") or "").lower() != "active":
        return False
    exp = _dt(iu.get("expiry_date"))
    return exp is None or exp > now


async def candidates(cfg, now=None):
    """[(user, lapsed_service)] due the email now (ignores send hours)."""
    db = D["db"]
    now = now or datetime.utcnow()
    hi = now - timedelta(days=cfg["delay_days"])
    lo = hi - timedelta(hours=CATCH_UP_HOURS)
    out, seen = [], set()
    async for s in db.services.find({"expiry_date": {"$gte": lo, "$lte": hi}, "status": {"$nin": ["duplicate", "failed"]}}).sort("expiry_date", -1):
        if not _paid_tv(s):
            continue
        uid = str(s.get("user_id") or "")
        if not uid or uid in seen:
            continue
        seen.add(uid)
        if await db.cmtv_lapsed_winback.find_one({"_id": uid}):
            continue   # once per customer, ever
        u = await db.users.find_one({"_id": _oid(uid)})
        email = str((u or {}).get("email") or "")
        if not u or u.get("role") != "user" or u.get("cmtv_demo") or "@" not in email or email.lower().endswith("@panel.local"):
            continue
        if (s.get("auto_renew") or {}).get("status") == "ACTIVE":
            continue
        # still a customer: this line renewed on the panel, or any other paid service is active
        if await _line_active_on_panel(s, now):
            continue
        still = False
        async for o in db.services.find({"user_id": uid, "status": "active"}):
            if _paid_tv(o) or (o.get("panel_type") == "manual" and not o.get("is_trial")):
                exp = _dt(o.get("expiry_date"))
                if exp is None or exp > now:
                    still = True
                    break
        if still:
            continue
        out.append((u, s))
    return out


async def _new_code(pct):
    for _ in range(20):
        code = f"RETURN{int(pct)}-" + "".join(secrets.choice(TW.ALPHABET) for _ in range(5))
        if not await D["db"].coupons.find_one({"code": code}) and not await D["db"].coupons_retired.find_one({"code": code}):
            return code
    raise RuntimeError("couldn't make a unique code")


async def _email(user, svc, code, cfg, until):
    es = await D["get_email_service"]()
    if not es:
        return False
    name = (user.get("name") or "").split(" ")[0] or "there"
    plan = re.sub(r"\s+", " ", str(svc.get("product_name") or "your plan")).strip()
    shop = f"{es.backend_url}/"
    pct = f"{int(cfg['percent'])}%"
    when = TW._nice(until)
    html = (f"<h2 style=\"margin:0 0 8px\">We miss you, {escape(name)}</h2>"
            f"<p>Your {escape(plan)} ended a couple of weeks ago. If you'd like to come back, here's <strong>{pct} off</strong> "
            f"your next plan.</p>"
            f"<p style=\"font-size:22px;letter-spacing:2px;margin:18px 0\"><strong>{code}</strong></p>"
            f"<p>Use it at checkout by {when}. It works once, on any plan, for your account only.</p>"
            f"<p style=\"margin:22px 0\"><a href=\"{shop}\" style=\"background:#22e6f2;color:#07101a;padding:12px 22px;"
            f"border-radius:999px;text-decoration:none;font-weight:700\">Choose a plan</a></p>"
            f"<p>Already renewed another way? Then ignore this, and thanks for staying with us.</p>")
    plain = (f"Hi {name},\n\nYour {plan} ended a couple of weeks ago. Come back with {pct} off your next plan.\n\n"
             f"Your code: {code}\nUse it at checkout by {when}. It works once, on any plan, for your account only.\n\n"
             f"Choose a plan: {shop}\n\nAlready renewed another way? Then ignore this.\n\nThe CMTV Team")
    return await es.send_email(
        to_email=user["email"], subject=f"{pct} off to come back to CMTV",
        html_content=es._wrap_email(html, "Come-back offer", user["email"], "marketing"),
        text_content=plain, email_type="marketing", template_type=KIND,
        customer_id=str(user["_id"]), recipient_name=user.get("name") or "")


async def send_offer(user, svc, cfg):
    now = datetime.utcnow()
    uid = str(user["_id"])
    es = await D["get_email_service"]()
    um = getattr(es, "unsubscribe_manager", None)
    if um and not await um.can_send_marketing(user["email"]):
        await D["db"].cmtv_lapsed_winback.insert_one({"_id": uid, "email": user.get("email"), "code": None,
                                                      "skipped": "unsubscribed from marketing emails", "sent_at": now})
        return None
    code = await _new_code(cfg["percent"])
    until = now + timedelta(days=cfg["valid_days"])
    res = await D["db"].coupons.insert_one({
        "code": code, "active": True, "coupon_type": "percentage", "value": float(cfg["percent"]), "min_purchase": 0, "max_uses": 1,
        "used_count": 0, "valid_from": now, "valid_until": until, "applies_to": "all", "product_ids": [],
        "created_at": now, "created_by": "cmtv-lapsed-winback",
        "cmtv_user_id": uid, "cmtv_first_order_only": False, "cmtv_kind": KIND,
        "cmtv_note": f"Come-back offer for {user.get('email')} ({str(svc.get('product_name') or '').strip()} ended)"})
    ok = False
    try:
        ok = bool(await _email(user, svc, code, cfg, until))
    except Exception as e:
        logger.error(f"lapsed winback: email to {user.get('email')} failed: {e}")
    if not ok:
        await TW._retire(await D["db"].coupons.find_one({"_id": res.inserted_id}), "email failed")
        return None
    await D["db"].cmtv_lapsed_winback.insert_one({
        "_id": uid, "email": user.get("email"), "code": code, "service_id": str(svc["_id"]), "plan": svc.get("product_name"),
        "ended": svc.get("expiry_date"), "sent_at": now, "valid_until": until})
    logger.info(f"lapsed winback: sent {code} to {user.get('email')}")
    return code


async def retire_expired_codes():
    n = 0
    async for c in D["db"].coupons.find({"cmtv_kind": KIND, "valid_until": {"$lt": datetime.utcnow() - timedelta(days=1)}}):
        await TW._retire(c, "expired")
        n += 1
    return n


async def run_once(force_hours=False):
    cfg = await config()
    await retire_expired_codes()
    if not cfg["enabled"]:
        return {"sent": 0, "skipped": "disabled"}
    if not force_hours and datetime.now(TZ).hour not in SEND_HOURS:
        return {"sent": 0, "skipped": "quiet hours"}
    sent = 0
    for u, s in await candidates(cfg):
        if await send_offer(u, s, cfg):
            sent += 1
    return {"sent": sent}


async def _loop():
    await asyncio.sleep(300)
    while True:
        try:
            r = await run_once()
            if r.get("sent"):
                logger.info(f"lapsed winback: {r}")
        except Exception as e:
            logger.error(f"lapsed winback loop: {e}")
        await asyncio.sleep(3600)


async def startup():
    asyncio.create_task(_loop())


def init_routes():
    admin = D["get_current_admin_user"]

    @router.get("/preview")
    async def preview(current_user: dict = Depends(admin)):
        return [{"email": u.get("email"), "plan": s.get("product_name"), "ended": str(s.get("expiry_date"))}
                for u, s in await candidates(await config())]

    @router.get("/sent")
    async def sent(current_user: dict = Depends(admin)):
        rows = []
        async for r in D["db"].cmtv_lapsed_winback.find({"code": {"$ne": None}}).sort("sent_at", -1).limit(200):
            used = await D["db"].coupon_usage.find_one({"coupon_code": r["code"]})
            rows.append({"email": r.get("email"), "code": r["code"], "plan": r.get("plan"), "sent_at": r["sent_at"].isoformat(),
                         "used": bool(used), "order_id": (used or {}).get("order_id")})
        return {"config": await config(), "sent": rows, "used": sum(1 for r in rows if r["used"])}
