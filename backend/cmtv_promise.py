"""'We fix it or make it right' (CMTV local addition 2026-10-11, owner's request).

1. Outage credit. When CCTV or Imperium was down for min_hours+ (default 6) per Uptime Kuma (cmtv_status_events; an
   outage that started together with 3+ other monitors = Kuma's own connection, ignored), every customer with a paid line
   on that server at the time gets `amount` (default $5) account credit, once per outage. A batch is made when the
   outage ENDS and waits for the admin (Admin > Notices > Outage credits, and an Ops Billing note) unless auto_approve
   is on: a monitor fault (like Extreme's old check) must never pay out by itself. On approval: credit_service credit
   (type outage_credit) + one email to customers with a real email and a Telegram note to linked ones; panel-only
   customers get the credit silently (it waits on their account). Resellers, trials, test and merged accounts are left out.
   Collection cmtv_outage_credits {_id "<monitor>:<down iso>", monitor, server, down_at, up_at, minutes, status
   pending|approved|skipped|done, users[], amount, credited[], emailed, telegram, decided_*}.
2. Buffering? Try the other server. GET /api/cmtv/promise/switch-trial: for a signed-in customer with an active paid
   CCTV (or Imperium) line who never had the other server's trial, the other server's free trial (the normal trial
   product: Imperium 48 h / CCTV 24 h), shown on the dashboard service card. Ordered through the normal checkout,
   so every usual trial rule (one per panel, duplicate checks, holds) still applies.
Config cmtv_config {_id: "promise", outage_enabled, amount, min_hours, auto_approve, switch_enabled}.
"""
import asyncio
import html
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from bson import ObjectId
from fastapi import APIRouter, Body, Depends, HTTPException

import cmtv_lines as L

log = logging.getLogger("server")
router = APIRouter(prefix="/api/cmtv/promise", tags=["cmtv-promise"])
D = {}
TZ = ZoneInfo("America/Toronto")
SITE = "https://billing.cmtv.info"
MONITORS = {"CCTV": ("CCTV", "xtream"), "Imperium": ("Imperium", "aether")}   # Kuma monitor -> (public name, panel_type)
OTHER = {"xtream": ("aether", "Imperium"), "aether": ("xtream", "CCTV")}
DEFAULTS = {"outage_enabled": True, "amount": 5.0, "min_hours": 6.0, "auto_approve": False, "switch_enabled": True}
LOOKBACK = timedelta(days=7)


def init(**deps):
    D.update(deps)


def _oid(v):
    return ObjectId(str(v)) if ObjectId.is_valid(str(v)) else None


def _iso(v):
    return v.isoformat() + "Z" if isinstance(v, datetime) else v


def _local(dt):
    return dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(TZ)


async def config():
    doc = await D["db"].cmtv_config.find_one({"_id": "promise"}) or {}
    return {k: doc.get(k, v) for k, v in DEFAULTS.items()}


# ------------------------------------------------------------------ outages
async def outages(now=None):
    """Ended outages of CCTV / Imperium in the last 7 days: [(monitor, down_at, up_at)], Kuma-blind starts left out."""
    db = D["db"]
    now = now or datetime.utcnow()
    since = now - LOOKBACK - timedelta(days=1)
    downs_all = [e["at"] async for e in db.cmtv_status_events.find({"status": "down", "at": {"$gte": since}}, {"at": 1})]
    out = []
    for mon in MONITORS:
        down_at = None
        async for e in db.cmtv_status_events.find({"monitor": mon, "at": {"$gte": since}}).sort("at", 1):
            if e["status"] == "down" and down_at is None:
                down_at = e["at"]
            elif e["status"] == "up" and down_at is not None:
                if e["at"] >= now - LOOKBACK:
                    blind = sum(1 for t in downs_all if abs((t - down_at).total_seconds()) <= 120) >= 4
                    if not blind:
                        out.append((mon, down_at, e["at"]))
                down_at = None
    return out


async def affected(panel_type, down_at, now=None):
    """User ids with a paid (non-trial, non-reseller) line on that server that was running when the outage began."""
    db = D["db"]
    uids = set()
    async for s in db.services.find({"panel_type": panel_type, "account_type": {"$ne": "reseller"},
                                     "status": {"$nin": ["failed", "duplicate", "removed", "pending"]},
                                     "expiry_date": {"$gte": down_at}, "created_at": {"$lte": down_at}},
                                    {"user_id": 1, "is_trial": 1, "product_name": 1, "expiry_date": 1, "created_at": 1}):
        if s.get("user_id") and L.is_paid_line(s, now):
            uids.add(str(s["user_id"]))
    keep = []
    async for u in db.users.find({"_id": {"$in": [i for i in map(_oid, uids) if i]}}, {"role": 1, "cmtv_test": 1}):
        if u.get("role") == "user" and not u.get("cmtv_test"):
            keep.append(str(u["_id"]))
    return sorted(keep)


async def _ops(text, silent=False):
    try:
        import cmtv_notify
        await cmtv_notify.ops(text, kind="billing", silent=silent)
    except Exception as e:
        log.warning(f"promise: ops note failed ({e})")


async def scan(now=None):
    """Make a batch for each new qualifying outage. Returns the new batch ids."""
    cfg = await config()
    if not cfg["outage_enabled"]:
        return []
    db = D["db"]
    made = []
    for mon, down_at, up_at in await outages(now):
        minutes = int((up_at - down_at).total_seconds() // 60)
        if minutes < cfg["min_hours"] * 60:
            continue
        bid = f"{mon}:{down_at.isoformat()}"
        if await db.cmtv_outage_credits.find_one({"_id": bid}, {"_id": 1}):
            continue
        server, ptype = MONITORS[mon]
        users = await affected(ptype, down_at, now)
        amount = float(cfg["amount"])
        await db.cmtv_outage_credits.insert_one({
            "_id": bid, "monitor": mon, "server": server, "down_at": down_at, "up_at": up_at, "minutes": minutes,
            "users": users, "amount": amount, "status": "pending", "credited": [], "emailed": 0, "telegram": 0,
            "created_at": datetime.utcnow()})
        made.append(bid)
        when = f"{_local(down_at):%b} {_local(down_at).day}, {_local(down_at):%-I:%M %p} to {_local(up_at):%-I:%M %p} ET"
        if cfg["auto_approve"]:
            await approve(bid, "auto")
            await _ops(f"🧾 <b>Outage credit sent</b>: {server} was down {minutes // 60} h {minutes % 60} min ({when}). "
                       f"{len(users)} customers got ${amount:g} (${amount * len(users):,.0f}).")
        else:
            await _ops(f"🧾 <b>Outage credit waiting for you</b>: {server} was down {minutes // 60} h {minutes % 60} min "
                       f"({when}). {len(users)} customers qualify for ${amount:g} = ${amount * len(users):,.0f}. "
                       f"Approve or skip in Admin › Notices › Outage credits.")
    return made


def _email(first, server, hours, day, amount):
    from cmtv_gifts import _shell, _button, P
    body = (f'<p style="{P}">Hi {first}, {server} was down for about {hours} hours on {day}. That isn\'t the service you pay '
            f"for, so we've added <b>${amount:g} credit</b> to your CMTV account.</p>"
            f'<p style="{P}">It\'s there whenever you renew or buy anything on billing.cmtv.info: you can use it at checkout.</p>'
            + _button(f"{SITE}/dashboard", "See my account")
            + f'<p style="{P}">Sorry for the trouble, and thanks for sticking with us.</p>')
    subject = f"Sorry about the {server} outage: ${amount:g} is on your account"
    return subject, _shell(f"We've added ${amount:g} credit to your account for the {server} outage.", "Sorry about that", body)


async def approve(bid, by):
    """Credit everyone in the batch (once each), then notify the reachable ones in the background."""
    db = D["db"]
    b = await db.cmtv_outage_credits.find_one_and_update({"_id": bid, "status": "pending"},
                                                          {"$set": {"status": "approved", "decided_at": datetime.utcnow(), "decided_by": by}})
    if not b:
        raise HTTPException(409, "That outage credit was already decided.")
    hours = max(1, round(b["minutes"] / 60))
    day = f"{_local(b['down_at']):%B} {_local(b['down_at']).day}"
    desc = f"Outage credit: {b['server']} down about {hours} h on {day}"
    cs = D["credit_service"]
    for uid in b["users"]:
        if uid in (b.get("credited") or []):
            continue
        try:
            await cs.add_credits(user_id=uid, amount=float(b["amount"]), transaction_type="outage_credit",
                                 description=desc, created_by="outage_credit", bypass_enabled_check=True)
            await db.cmtv_outage_credits.update_one({"_id": bid}, {"$addToSet": {"credited": uid}})
        except Exception as e:
            log.error(f"outage credit {bid} for {uid} failed: {e}")
    asyncio.create_task(_notify(bid, hours, day))
    return True


async def _notify(bid, hours, day):
    db = D["db"]
    b = await db.cmtv_outage_credits.find_one({"_id": bid})
    emailed = tg = 0
    try:
        es = await D["get_email_service"]()
    except Exception:
        es = None
    for uid in b.get("credited") or []:
        u = await db.users.find_one({"_id": _oid(uid)}, {"name": 1, "email": 1, "cmtv_telegram": 1})
        if not u:
            continue
        first = html.escape(((u.get("name") or "").split(" ") or [""])[0] or "there")
        email = str(u.get("email") or "")
        if es and getattr(es, "enabled", False) and "@" in email and not email.lower().endswith("@panel.local"):
            try:
                subject, page = _email(first, b["server"], hours, day, b["amount"])
                if await es.send_email(to_email=email, subject=subject, html_content=es._wrap_email(page, subject, email, "transactional"),
                                       email_type="transactional", template_type="cmtv_outage_credit", customer_id=uid,
                                       recipient_name=u.get("name") or ""):
                    emailed += 1
            except Exception as e:
                log.warning(f"outage credit email {uid}: {e}")
            await asyncio.sleep(1.5)
        chat = (u.get("cmtv_telegram") or {}).get("chat_id")
        if chat:
            try:
                import cmtv_telegram_alerts
                await cmtv_telegram_alerts.queue(uid, chat, f"🙏 <b>Sorry about the {b['server']} outage</b> on {day}. We've added "
                                                 f"${b['amount']:g} credit to your CMTV account for your next renewal.",
                                                 [[{"text": "See my account", "url": f"{SITE}/dashboard"}]], kind="outage_credit")
                tg += 1
            except Exception as e:
                log.warning(f"outage credit telegram {uid}: {e}")
    await db.cmtv_outage_credits.update_one({"_id": bid}, {"$set": {"status": "done", "emailed": emailed, "telegram": tg,
                                                                    "done_at": datetime.utcnow()}})
    await _ops(f"🧾 Outage credit done ({b['server']}, {day}): {len(b.get('credited') or [])} credited, {emailed} emailed, "
               f"{tg} on Telegram.", silent=True)


# ------------------------------------------------------------------ switch trial
async def switch_offers(uid):
    db = D["db"]
    cfg = await config()
    if not cfg["switch_enabled"] or await db.cmtv_dupe_blocks.find_one({"user_id": uid, "status": "blocked"}):
        return []
    now = datetime.utcnow()
    have = {}
    async for s in db.services.find({"user_id": uid, "status": "active", "account_type": {"$ne": "reseller"},
                                     "panel_type": {"$in": list(OTHER)}},
                                    {"panel_type": 1, "is_trial": 1, "product_name": 1, "expiry_date": 1, "created_at": 1}):
        have.setdefault(s["panel_type"], []).append(s)
    out = []
    for ptype, lines in have.items():
        if not any(L.is_paid_line(s, now) for s in lines):
            continue
        other, label = OTHER[ptype]
        if other in have:
            continue
        trial = await db.products.find_one({"is_trial": True, "panel_type": other, "is_active": {"$ne": False}},
                                           {"name": 1, "duration_hours": 1, "trial_hours": 1})
        if not trial:
            continue
        used = await db.services.find_one({"user_id": uid, "panel_type": other, "$or": [
            {"is_trial": True}, {"product_name": {"$regex": "trial", "$options": "i"}}]}, {"_id": 1}) \
            or await db.orders.find_one({"user_id": uid, "items.product_id": str(trial["_id"])}, {"_id": 1})
        if used:
            continue
        hours = 48 if other == "aether" else 24
        out.append({"for_panel": ptype, "from": OTHER[other][1], "to": label, "product_id": str(trial["_id"]), "hours": hours})
    return out


# ------------------------------------------------------------------ routes + loop
def init_routes():
    admin, current = D["get_current_admin_user"], D["get_current_user"]

    @router.get("/public")   # 2026-10-11: the outage promise shown on the status page
    async def public():
        c = await config()
        return {"outage": {"enabled": bool(c["outage_enabled"]), "amount": c["amount"], "min_hours": c["min_hours"]}}

    @router.get("/switch-trial")
    async def my_switch_trial(current_user: dict = Depends(current)):
        return {"offers": await switch_offers(str(current_user.get("sub")))}

    @router.get("/admin")
    async def admin_view(current_user: dict = Depends(admin)):
        rows = []
        async for b in D["db"].cmtv_outage_credits.find({}).sort("down_at", -1).limit(20):
            rows.append({"id": b["_id"], "server": b["server"], "down_at": _iso(b["down_at"]), "up_at": _iso(b["up_at"]),
                         "minutes": b["minutes"], "customers": len(b.get("users") or []), "amount": b["amount"],
                         "status": b["status"], "credited": len(b.get("credited") or []), "emailed": b.get("emailed", 0),
                         "telegram": b.get("telegram", 0)})
        return {"config": await config(), "batches": rows}

    @router.post("/admin/config")
    async def admin_config(data: dict = Body(...), current_user: dict = Depends(admin)):
        upd = {}
        for k in ("outage_enabled", "auto_approve", "switch_enabled"):
            if k in data:
                upd[k] = bool(data[k])
        if "amount" in data:
            a = float(data["amount"])
            if not 0 < a <= 50:
                raise HTTPException(400, "Credit must be between $0 and $50")
            upd["amount"] = a
        if "min_hours" in data:
            h = float(data["min_hours"])
            if not 1 <= h <= 72:
                raise HTTPException(400, "Hours must be between 1 and 72")
            upd["min_hours"] = h
        await D["db"].cmtv_config.update_one({"_id": "promise"}, {"$set": upd}, upsert=True)
        return {"config": await config()}

    @router.post("/admin/batches/{bid:path}")
    async def admin_decide(bid: str, data: dict = Body(...), current_user: dict = Depends(admin)):
        action = data.get("action")
        if action == "approve":
            await approve(bid, current_user.get("sub"))
        elif action == "skip":
            r = await D["db"].cmtv_outage_credits.update_one({"_id": bid, "status": "pending"}, {"$set": {
                "status": "skipped", "decided_at": datetime.utcnow(), "decided_by": current_user.get("sub")}})
            if not r.matched_count:
                raise HTTPException(409, "That outage credit was already decided.")
        else:
            raise HTTPException(400, "Unknown action")
        return {"ok": True}


async def _loop():
    await asyncio.sleep(90)
    while True:
        try:
            await scan()
        except Exception as e:
            log.warning(f"promise: scan failed ({type(e).__name__}: {e})")
        await asyncio.sleep(600)


async def startup():
    await D["db"].cmtv_outage_credits.create_index("down_at")
    asyncio.create_task(_loop())
