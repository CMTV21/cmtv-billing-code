"""Trial come-back offer (CMTV local addition 2026-09-26).

About 24 hours after a trial ends, a customer who hasn't bought anything gets one email with a personal 15% code:
single use, only for their account, only on their first paid order, valid 7 days, any plan (the discount skips
trials and reseller packs). One email per customer, ever. Runs hourly; emails go out 10:00-20:00 Toronto time.

- Codes are normal coupons (so they show in Admin > Coupons) with extra fields: cmtv_user_id, cmtv_first_order_only,
  cmtv_kind "trial_winback". server.py calls check_order_coupon() in create_order and check_validate() in
  /api/coupon/validate so nobody else can use them. Expired personal codes are moved to coupons_retired.
- Sent log: cmtv_trial_winback (one doc per customer). Email template: email_templates template_type "trial_winback"
  (house style, editable in Admin > Email Templates; scripts/2026-09-26-trial-winback/), plain fallback if missing.
- Settings: cmtv_config _id "trial_winback" {enabled, percent, valid_days, delay_hours} (defaults below).
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

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/cmtv/trial-winback", tags=["cmtv-trial-winback"])
D = {}
TZ = ZoneInfo("America/Toronto")
DEFAULTS = {"enabled": True, "percent": 15, "valid_days": 7, "delay_hours": 24}
CATCH_UP_HOURS = 48          # trials that ended between delay and delay+48h still qualify (covers quiet hours / downtime)
SEND_HOURS = range(10, 20)   # Toronto local hours when emails may go out
KIND = "trial_winback"
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def init(**deps):
    D.update(deps)


def _oid(v):
    return ObjectId(v) if ObjectId.is_valid(str(v)) else None


def _get(item, key):
    return item.get(key) if isinstance(item, dict) else getattr(item, key, None)


async def config():
    doc = await D["db"].cmtv_config.find_one({"_id": "trial_winback"}) or {}
    return {**DEFAULTS, **{k: v for k, v in doc.items() if k != "_id"}}


async def has_paid_order(user_id):
    return bool(await D["orders"].find_one({"user_id": str(user_id), "status": "paid", "total": {"$gt": 0}}, {"_id": 1}))


# ---------------- personal codes at checkout ----------------

async def _personal(code):
    if not code:
        return None
    c = await D["db"].coupons.find_one({"code": str(code).upper()})
    return c if c and c.get("cmtv_user_id") else None


async def check_validate(code, user_id):
    """For /api/coupon/validate: an error message, or None if the code may be used by this (possibly anonymous) user."""
    c = await _personal(code)
    if not c:
        return None
    if not user_id or str(user_id) != c["cmtv_user_id"]:
        return "This code belongs to another account. Sign in to the account it was sent to."
    if c.get("cmtv_first_order_only") and await has_paid_order(user_id):
        return "This code is for your first order only."
    return None


async def check_order_coupon(code, user_id, items, discount):
    """For create_order, after the normal coupon check. Returns (discount, error). Personal codes: owner and first
    order only, and the percentage only counts plans (not trials or reseller packs)."""
    c = await _personal(code)
    if not c:
        return discount, None
    err = await check_validate(code, user_id)
    if err:
        return 0.0, err
    base = 0.0
    for it in items:
        product = await D["products"].find_one({"_id": _oid(_get(it, "product_id"))}, {"is_trial": 1, "account_type": 1})
        if not product or product.get("is_trial") or product.get("account_type") == "reseller" \
                or str(_get(it, "account_type") or "") == "reseller":
            continue
        base += float(_get(it, "price") or 0)
    if base <= 0:
        return 0.0, "This code works on plans (not trials or reseller packages)."
    return round(base * float(c.get("value") or 0) / 100.0, 2), None


# ---------------- finding who gets the email ----------------

async def candidates(cfg, now=None):
    """[(user, trial_service)] due an email now (ignores send hours)."""
    now = now or datetime.utcnow()
    hi = now - timedelta(hours=cfg["delay_hours"])
    lo = hi - timedelta(hours=CATCH_UP_HOURS)
    out, seen = [], set()
    async for s in D["services"].find({"is_trial": True, "expiry_date": {"$gte": lo, "$lte": hi}}).sort("expiry_date", -1):
        uid = str(s.get("user_id") or "")
        if not uid or uid in seen:
            continue
        seen.add(uid)
        if await D["db"].cmtv_trial_winback.find_one({"_id": uid}):
            continue
        u = await D["users"].find_one({"_id": _oid(uid)})
        email = str((u or {}).get("email") or "")
        if not u or u.get("role") != "user" or "@" not in email or email.endswith("@panel.local"):
            continue
        if await has_paid_order(uid):
            continue
        # still has (or has since bought) a real service: not a lapsed trial
        if await D["services"].find_one({"user_id": uid, "is_trial": {"$ne": True}, "status": "active"}, {"_id": 1}):
            continue
        out.append((u, s))
    return out


async def _new_code():
    for _ in range(20):
        code = "BACK15-" + "".join(secrets.choice(ALPHABET) for _ in range(5))
        if not await D["db"].coupons.find_one({"code": code}) and not await D["db"].coupons_retired.find_one({"code": code}):
            return code
    raise RuntimeError("couldn't make a unique code")


def _nice(dt):
    return dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(TZ).strftime("%B %-d, %Y")


async def send_offer(user, trial, cfg):
    """Create the code and email it. Returns the code, or None if the email failed (the code is then retired)."""
    now = datetime.utcnow()
    uid = str(user["_id"])
    es = D["get_email_service"]()
    es = await es if asyncio.iscoroutine(es) else es
    um = getattr(es, "unsubscribe_manager", None)
    if um and not await um.can_send_marketing(user["email"]):
        await D["db"].cmtv_trial_winback.insert_one({"_id": uid, "email": user.get("email"), "code": None,
                                                     "skipped": "unsubscribed from marketing emails", "sent_at": now})
        return None
    code = await _new_code()
    until = now + timedelta(days=cfg["valid_days"])
    coupon = {
        "code": code, "coupon_type": "percentage", "value": float(cfg["percent"]), "min_purchase": 0, "max_uses": 1,
        "used_count": 0, "valid_from": now, "valid_until": until, "applies_to": "all", "product_ids": [],
        "created_at": now, "created_by": "cmtv-trial-winback",
        "cmtv_user_id": uid, "cmtv_first_order_only": True, "cmtv_kind": KIND,
        "cmtv_note": f"Trial come-back offer for {user.get('email')} ({trial.get('product_name', '').strip()})",
    }
    res = await D["db"].coupons.insert_one(coupon)
    ok = False
    try:
        ok = bool(await _email(user, trial, code, cfg, until))
    except Exception as e:
        logger.error(f"trial winback: email to {user.get('email')} failed: {e}")
    if not ok:
        await _retire(await D["db"].coupons.find_one({"_id": res.inserted_id}), "email failed")
        return None
    await D["db"].cmtv_trial_winback.insert_one({
        "_id": uid, "email": user.get("email"), "code": code, "trial_service_id": str(trial["_id"]),
        "trial_name": trial.get("product_name"), "trial_ended": trial.get("expiry_date"), "sent_at": now, "valid_until": until})
    logger.info(f"trial winback: sent {code} to {user.get('email')}")
    return code


async def _email(user, trial, code, cfg, until):
    es = D["get_email_service"]()
    if asyncio.iscoroutine(es):
        es = await es
    if not es:
        return False
    name = (user.get("name") or "").split(" ")[0] or "there"
    trial_name = re.sub(r"\s+", " ", str(trial.get("product_name") or "free trial")).strip()
    shop = f"{es.backend_url}/"
    values = {"customer_name": escape(name), "trial_name": escape(trial_name), "code": code,
              "percent": f"{int(cfg['percent'])}%", "valid_until": _nice(until), "shop_link": shop}
    tpl = await D["db"].email_templates.find_one({"template_type": KIND, "is_active": True})
    if tpl:
        subject, html = tpl.get("subject") or "{{percent}} off your first CMTV plan", tpl["html_content"]
    else:
        subject = "{{percent}} off your first CMTV plan"
        html = ("<p>Hi {{customer_name}},</p><p>Your {{trial_name}} has ended. Come back with {{percent}} off your first plan: "
                "use code <b>{{code}}</b> at checkout by {{valid_until}}.</p><p><a href=\"{{shop_link}}\">Choose a plan</a></p>"
                "<p>The CMTV Team</p>")
    for k, v in values.items():
        html = html.replace("{{" + k + "}}", v)
        subject = subject.replace("{{" + k + "}}", v)
    plain = (f"Hi {name},\n\nYour {trial_name} has ended. Come back with {values['percent']} off your first plan.\n\n"
             f"Your code: {code}\nUse it at checkout by {values['valid_until']}. It works on any plan, for your account only.\n\n"
             f"Choose a plan: {shop}\n\nThe CMTV Team")
    return await es.send_email(
        to_email=user["email"], subject=subject,
        html_content=es._wrap_email(html, (tpl or {}).get("name", "Trial come-back offer"), user["email"], "marketing"),
        text_content=plain, email_type="marketing", template_type=KIND,
        customer_id=str(user["_id"]), recipient_name=user.get("name") or "")


async def _retire(coupon, reason):
    if not coupon:
        return
    await D["db"].coupons_retired.replace_one({"_id": coupon["_id"]}, {
        **coupon, "retired_at": datetime.utcnow(), "retired_reason": reason}, upsert=True)
    await D["db"].coupons.delete_one({"_id": coupon["_id"]})


async def retire_expired_codes():
    """Personal codes a day past their end date leave the Coupons list (kept in coupons_retired)."""
    n = 0
    async for c in D["db"].coupons.find({"cmtv_kind": KIND, "valid_until": {"$lt": datetime.utcnow() - timedelta(days=1)}}):
        await _retire(c, "expired")
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
    await asyncio.sleep(120)
    while True:
        try:
            r = await run_once()
            if r.get("sent"):
                logger.info(f"trial winback: {r}")
        except Exception as e:
            logger.error(f"trial winback loop: {e}")
        await asyncio.sleep(3600)


async def startup():
    await D["db"].coupons.create_index("cmtv_user_id", sparse=True)
    asyncio.create_task(_loop())


# ---------------- admin: what's been sent and what came of it ----------------

def init_routes():
    admin = D["get_current_admin_user"]

    @router.get("/sent")
    async def sent(current_user: dict = Depends(admin)):
        rows = []
        async for r in D["db"].cmtv_trial_winback.find({"code": {"$ne": None}}).sort("sent_at", -1).limit(200):
            used = await D["db"].coupon_usage.find_one({"coupon_code": r["code"]})
            rows.append({"email": r.get("email"), "code": r["code"], "trial": r.get("trial_name"),
                         "sent_at": r["sent_at"].isoformat(), "used": bool(used), "order_id": (used or {}).get("order_id")})
        cfg = await config()
        return {"config": cfg, "sent": rows, "used": sum(1 for r in rows if r["used"])}

    @router.get("/preview")
    async def preview(current_user: dict = Depends(admin)):
        """Who would get the email on the next run (nothing is sent)."""
        return [{"email": u.get("email"), "trial": s.get("product_name"), "trial_ended": s["expiry_date"].isoformat()}
                for u, s in await candidates(await config())]
