"""Free-trial check-in + "keep watching" (CMTV local addition 2026-10-02, the owner's OK; email + Telegram if linked).

Only 24% of trial users ended up paying, and most failed trials are setup problems. For every running trial service
(services.is_trial, status active), the customer gets at most two messages:
  1. check-in   CHECKIN_AFTER into the trial (3 h for TV trials, 1 day for 7-day add-on trials): is it working? setup
                steps for that service + a link to their dashboard (their login and setup steps are there).
  2. ending     when ENDING_LEFT of the trial is left (6 h / 12 h / 1 day): keep watching, cheapest per-month price on
                a 12-month plan, a button to that service's plans.
Skipped: customers who already paid for something since the trial started, non-customers (role != user), placeholder
emails, unsubscribed emails (marketing); a stage whose moment passed while the trial ended is skipped. Messages go out
09:00-21:00 Toronto only. Email = DB templates cmtv_trial_checkin / cmtv_trial_ending (customer_templates.py, Admin >
Email Templates); Telegram through cmtv_telegram_alerts.queue. Log: cmtv_trial_nurture {_id: service id, checkin_at,
ending_at, ...}. Runs every 10 minutes from server.py startup (start()). GET /api/cmtv/trial-nurture/recent (admin).
The 15% come-back offer after the trial (cmtv_trial_winback) is separate and unchanged.
"""
import asyncio
import html
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from bson import ObjectId
from fastapi import APIRouter, Depends

import cmtv_lines as L

log = logging.getLogger("server")
router = APIRouter(prefix="/api/cmtv/trial-nurture", tags=["cmtv-trial-nurture"])
D = {}
SITE = "https://billing.cmtv.info"
TZ = ZoneInfo("America/Toronto")
SEND_HOURS = range(9, 21)
DOWNLOADER = "5883394"


def init(**deps):
    D.update(deps)


def _oid(v):
    return ObjectId(v) if ObjectId.is_valid(str(v)) else None


def _first(u):
    return (str(u.get("name") or "").split(" ")[0] or "there").strip()


def family(svc):
    pt = svc.get("panel_type")
    if pt == "xtream":
        return "CCTV"
    if pt in ("aether", "nxtdash"):
        return "Imperium"
    name = str(svc.get("product_name") or "")
    for k in ("Nuvio", "Stremio", "CMTVpn", "Audiobooks"):
        if k.lower() in name.lower():
            return k
    return name.replace("7-Day Trial", "").strip() or "CMTV"


def timing(svc):
    """(check-in after, ending when this much is left) for this trial's length"""
    start, end = svc.get("start_date") or svc.get("created_at"), svc.get("expiry_date")
    length = (end - start) if isinstance(start, datetime) and isinstance(end, datetime) else timedelta(hours=24)
    if length <= timedelta(hours=30):
        return timedelta(hours=3), timedelta(hours=6)
    if length <= timedelta(hours=60):
        return timedelta(hours=3), timedelta(hours=12)
    return timedelta(days=1), timedelta(days=1)


def steps_html(fam):
    tick = '<tr><td style="padding:6px 0; font-size:14px; line-height:1.5; color:#c9d2e3;"><span style="color:#22e6f2; font-weight:bold;">&#10003;</span>&nbsp; {}</td></tr>'
    if fam in ("CCTV", "Imperium"):
        rows = [f"<strong>Firestick or Android TV:</strong> open the Downloader app, enter <strong>{DOWNLOADER}</strong> and install TiviMate or CMTVGhost",
                "<strong>Android phone or tablet:</strong> CMTVGhost (same Downloader page)",
                "<strong>iPhone or iPad:</strong> MYTVONLINE+ from the App Store",
                "<strong>Computer:</strong> the Web Player at webplayer.cmtv.info, nothing to install",
                f"Sign in with your <strong>{fam}</strong> username and password from your dashboard"]
    elif fam == "Nuvio":
        rows = [f"<strong>Firestick or Android TV:</strong> open Downloader, enter <strong>{DOWNLOADER}</strong> and install Nuvio",
                "Open Nuvio, choose <strong>Sign in</strong> and enter the login from your dashboard",
                "Your movies and series are on the home screen: pick one and press Play"]
    else:
        rows = ["Your login and step-by-step setup are on your dashboard, under the service"]
    return ('    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:24px;">'
            + "".join(tick.format(r) for r in rows) + "</table>")


async def plan_info(svc, fam):
    """(link to the plans, cheapest per-month price on a 12-month plan as text or None)"""
    db = D["db"]
    if fam in ("CCTV", "Imperium"):
        pts = ["xtream"] if fam == "CCTV" else ["aether", "nxtdash"]
        best = None
        async for p in db.products.find({"active": True, "panel_type": {"$in": pts}, "account_type": "subscriber"},
                                        {"prices": 1, "is_trial": 1, "name": 1}):
            if p.get("is_trial") or "trial" in str(p.get("name", "")).lower():
                continue
            yr = (p.get("prices") or {}).get("12")
            if yr:
                best = min(best or 1e9, float(yr) / 12)
        return f"{SITE}/?tab={fam.lower()}", (f"${best:.2f}" if best else None)
    prod = await db.products.find_one({"_id": _oid(svc.get("product_id"))}, {"cmtv_trial_of": 1})
    paid = await db.products.find_one({"_id": _oid((prod or {}).get("cmtv_trial_of"))}, {"prices": 1})
    yr = ((paid or {}).get("prices") or {}).get("12")
    link = f"{SITE}/?add={paid['_id']}" if paid else f"{SITE}/?tab=addons"
    return link, (f"${float(yr) / 12:.2f}" if yr else None)


def _when(dt):
    loc = dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(TZ)
    return loc.strftime("%A at ") + loc.strftime("%I:%M %p").lstrip("0") + " ET"


async def _paid_since(uid, since):
    return bool(await D["db"].orders.find_one({"user_id": uid, "status": "paid", "total": {"$gt": 0},
                                               "created_at": {"$gte": since}}, {"_id": 1}))


async def _send(u, svc, stage, fam, variant=None):
    """variant (2026-10-05, cmtv_trial_watch): "ending_watched" (glad you're enjoying it -> plans) / "ending_stuck" (we'll help
    you set it up -> their dashboard's setup steps). A missing variant template falls back to the stage's own.
    NOTE: TV trials can't keep their login yet (no cmtv_trial_of on the CCTV / Imperium trial products), so no
    "same login" promise for them."""
    import cmtv_reseller_credits as RC
    uid = str(u["_id"])
    es = await D["get_email_service"]()
    um = getattr(es, "unsubscribe_manager", None) if es else None
    email = str(u.get("email") or "")
    plan_link, price = await plan_info(svc, fam)
    if variant == "ending_stuck":
        plan_link = f"{SITE}/dashboard"
    vals = {"first_name": html.escape(_first(u)), "service": html.escape(fam), "ends": _when(svc["expiry_date"]),
            "steps": steps_html(fam), "setup_link": f"{SITE}/dashboard", "plan_link": plan_link,
            "from_price": price or "a few dollars",
            "unsubscribe_link": f"{getattr(es, 'backend_url', SITE)}/api/unsubscribe?email={email}"}
    emailed = False
    ok_email = (es and getattr(es, "enabled", False) and "@" in email and not email.endswith("@panel.local")
                and not (um and not await um.can_send_marketing(email)))
    if ok_email:
        r = (await RC.render(f"cmtv_trial_{variant}", vals) if variant else None) or await RC.render(f"cmtv_trial_{stage}", vals)
        if r:
            subject, page = r
            page = ("<!DOCTYPE html><html><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width\">"
                    "<meta name=\"color-scheme\" content=\"dark\"></head>"
                    f"<body style=\"margin:0; padding:0; background-color:#0a1020;\">{page}</body></html>")
            text = (f"Hi {_first(u)},\n\nYour free {fam} trial ends {vals['ends']}.\n\n"
                    + (f"Setup steps and your login: {SITE}/dashboard\n" if stage == "checkin" else f"Choose a plan: {plan_link}\n")
                    + f"\nHelp: https://t.me/Cmtv_support_bot\n\nThe CMTV Team\n\nUnsubscribe: {vals['unsubscribe_link']}")
            try:
                emailed = bool(await es.send_email(to_email=email, subject=subject, html_content=page, text_content=text,
                                                   email_type="marketing", template_type=f"cmtv_trial_{stage}",
                                                   customer_id=uid, recipient_name=u.get("name") or ""))
            except Exception as e:
                log.warning(f"trial {stage} email to {email} failed: {e}")
    tg = (u.get("cmtv_telegram") or {}).get("chat_id")
    if tg:
        try:
            import cmtv_telegram_alerts
            if stage == "checkin":
                text = (f"👋 <b>How's your {html.escape(fam)} trial going, {html.escape(_first(u))}?</b>\n\nYour login and setup steps "
                        f"are on your dashboard. Stuck? Message us here and we'll get you watching.")
                buttons = [[{"text": "Open my setup steps", "url": f"{SITE}/dashboard"}]]
            elif variant == "ending_watched":
                text = (f"⏳ <b>Glad you're enjoying {html.escape(fam)}!</b>\n\nYour trial ends {vals['ends']}. Choose a plan to keep "
                        f"watching" + (f", from {price} a month on a 12-month plan." if price else "."))
                buttons = [[{"text": "Choose my plan", "url": plan_link}]]
            elif variant == "ending_stuck":
                text = (f"⏳ <b>Your {html.escape(fam)} trial ends {vals['ends']}</b>\n\nDidn't get it playing yet? Message us "
                        f"here and we'll set it up with you, usually in a few minutes.")
                buttons = [[{"text": "Open my setup steps", "url": plan_link}]]
            else:
                text = (f"⏳ <b>Your {html.escape(fam)} trial ends {vals['ends']}</b>\n\nChoose a plan to keep watching"
                        + (f", from {price} a month on a 12-month plan." if price else "."))
                buttons = [[{"text": "Choose my plan", "url": plan_link}]]
            await cmtv_telegram_alerts.queue(uid, tg, text, buttons, kind=f"trial_{stage}")
        except Exception as e:
            log.warning(f"trial {stage} telegram failed: {e}")
    return emailed, bool(tg)


async def enabled() -> bool:
    """cmtv_config {_id: "trial_nurture", enabled}: off until the owner has seen the emails (2026-10-02)"""
    doc = await D["db"].cmtv_config.find_one({"_id": "trial_nurture"}) or {}
    return bool(doc.get("enabled"))


async def run_once(now=None, dry_run=False):
    db = D["db"]
    now = now or datetime.utcnow()
    if not dry_run and not await enabled():
        return []
    local = now.replace(tzinfo=ZoneInfo("UTC")).astimezone(TZ)
    if local.hour not in SEND_HOURS and not dry_run:
        return []
    done = []
    async for svc in db.services.find({"is_trial": True, "status": "active", "expiry_date": {"$gt": now}}):
        start = svc.get("start_date") or svc.get("created_at")
        if not isinstance(start, datetime):
            continue
        if L.is_paid_line(svc, now):
            continue   # CMTV local change 2026-10-08: a trial line that was paid for and extended (shared rule, cmtv_lines)
        sid, uid = str(svc["_id"]), str(svc.get("user_id") or "")
        logd = await db.cmtv_trial_nurture.find_one({"_id": sid}) or {}
        after, left = timing(svc)
        stage = None
        if not logd.get("ending_at") and svc["expiry_date"] - now <= left:
            stage = "ending"
        elif not logd.get("checkin_at") and not logd.get("ending_at") and now - start >= after:
            stage = "checkin"
        if not stage:
            continue
        u = await db.users.find_one({"_id": _oid(uid)})
        if not u or u.get("role") != "user" or await _paid_since(uid, start):
            await db.cmtv_trial_nurture.update_one({"_id": sid}, {"$set": {f"{stage}_at": now, f"{stage}_skipped": "paid or not a customer"}}, upsert=True)
            continue
        fam = family(svc)
        # 2026-10-05: follow what the customer actually did (cmtv_trial_watch: True / False / None = don't know)
        w, variant = None, None
        if fam in ("CCTV", "Imperium"):
            try:
                import cmtv_trial_watch
                w = await cmtv_trial_watch.watched(sid)
            except Exception:
                w = None
        if stage == "checkin" and w is True:
            await db.cmtv_trial_nurture.update_one({"_id": sid}, {"$set": {"checkin_at": now, "checkin_skipped": "already watching"}}, upsert=True)
            continue
        if stage == "ending" and w is not None:
            variant = "ending_watched" if w else "ending_stuck"
        if dry_run:
            done.append((u.get("email"), fam, variant or stage))
            continue
        emailed, tg = await _send(u, svc, stage, fam, variant)
        if stage == "checkin" and w is False:
            await cmtv_trial_watch.alert_owner(u, svc, fam)
        await db.cmtv_trial_nurture.update_one({"_id": sid}, {"$set": {
            f"{stage}_at": now, f"{stage}_email": emailed, f"{stage}_telegram": tg, "user_id": uid, "family": fam,
            f"{stage}_variant": variant, "watched": w}}, upsert=True)
        done.append((u.get("email"), fam, stage))
    if done and not dry_run:
        log.info(f"trial messages sent: {done}")
    return done


async def _loop():
    await asyncio.sleep(90)
    while True:
        try:
            await run_once()
        except Exception as e:
            log.warning(f"trial nurture: {e}")
        await asyncio.sleep(600)


def start():
    if not D.get("task"):
        D["task"] = asyncio.get_event_loop().create_task(_loop())


def init_routes():
    admin = D["get_current_admin_user"]

    @router.get("/recent")
    async def recent(current_user: dict = Depends(admin)):
        out = []
        async for x in D["db"].cmtv_trial_nurture.find().sort([("checkin_at", -1)]).limit(50):
            out.append({k: (v.isoformat() + "Z" if isinstance(v, datetime) else v) for k, v in x.items()})
        return out
