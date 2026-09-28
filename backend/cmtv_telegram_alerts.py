"""Telegram alerts for customers (CMTV local addition 2026-09-28).

A customer connects Telegram from the dashboard ("Get alerts on Telegram", components/cmtv/TelegramAlerts.js):
POST /api/cmtv/telegram/link makes a one-time token (30 min) and returns https://t.me/Cmtv_support_bot?start=link_<token>.
Tapping Start there makes @Cmtv_support_bot call the private bridge POST /api/cmtv/tickets-bridge/tg/link (local calls
with X-Bridge-Token only, same guard as cmtv_tickets_bridge), which saves users.cmtv_telegram
{chat_id, username, name, linked_at, prefs {renewals, notices}}. /stop in the bot (or Disconnect on the dashboard) unlinks.

Messages go into cmtv_tg_outbox; the bot collects them every ~15 s (GET /tg/outbox), sends them and reports back
(POST /tg/outbox/ack). A customer who blocked the bot is unlinked automatically. The bot token never leaves the bot.
- Renewal reminders (hourly job, sent 10:00-20:00 Toronto): 3 days and 1 day before a paid service ends, not when PayPal
  auto-renew is on; button "Renew now" -> /dashboard?renew=<service id> (puts the renewal in the cart). Once per
  service + end date + stage (cmtv_tg_sent).
- Service notices: admin POST /api/cmtv/telegram/admin/notice {family, text, dry_run} -> every connected customer with
  an active service in that family (cctv / imperium / extreme / amethyst / stremio / cmtvpn / audiobooks / all) who
  has notices on.
"""
import asyncio
import hmac
import html
import logging
import os
import secrets
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from bson import ObjectId
from fastapi import APIRouter, Body, Depends, HTTPException, Request

log = logging.getLogger("server")
router = APIRouter(prefix="/api/cmtv/telegram", tags=["cmtv-telegram"])
bridge = APIRouter(prefix="/api/cmtv/tickets-bridge/tg", tags=["cmtv-telegram-bridge"])
D = {}
BOT = "Cmtv_support_bot"
SITE = "https://billing.cmtv.info"
TZ = ZoneInfo("America/Toronto")
LINK_TTL = timedelta(minutes=30)
STAGES = [(3, "3d"), (1, "1d")]
FAMILIES = ["cctv", "imperium", "extreme", "amethyst", "stremio", "cmtvpn", "audiobooks"]
DEFAULT_PREFS = {"renewals": True, "notices": True}


def init(**deps):
    D.update(deps)


def _oid(v):
    return ObjectId(v) if ObjectId.is_valid(str(v)) else None


def family_of(s: dict) -> str:
    mod = s.get("cockpit_module")
    if mod:
        return {"nuvio": "stremio", "vpn": "cmtvpn"}.get(mod, mod)
    name = str(s.get("product_name") or "").lower()
    if "amethyst" in name:
        return "amethyst"
    if s.get("panel_type") == "onestream" or "extreme" in name:
        return "extreme"
    if s.get("panel_type") in ("aether", "nxtdash") or "imperium" in name:
        return "imperium"
    if s.get("panel_type") in ("xtream", "xuione"):
        return "cctv"
    return "other"


def _bridge_auth(request: Request):
    """Same rule as cmtv_tickets_bridge: direct local calls with the shared token; anything through nginx is refused"""
    token = os.environ.get("TICKET_BRIDGE_TOKEN", "")
    client = request.client.host if request.client else ""
    proxied = any(h in request.headers for h in ("x-real-ip", "x-forwarded-for", "cf-connecting-ip"))
    got = request.headers.get("x-bridge-token", "")
    if not token or proxied or client not in ("127.0.0.1", "::1") or not hmac.compare_digest(got.encode(), token.encode()):
        raise HTTPException(403, "Forbidden")


async def queue(user_id: str, chat_id, text: str, buttons=None, kind: str = "info"):
    await D["db"].cmtv_tg_outbox.insert_one({"user_id": user_id, "chat_id": int(chat_id), "text": text,
                                             "buttons": buttons or [], "kind": kind, "status": "queued",
                                             "created_at": datetime.utcnow()})


def _public(u: dict) -> dict:
    t = u.get("cmtv_telegram") or {}
    return {"linked": bool(t.get("chat_id")), "username": t.get("username"), "name": t.get("name"),
            "linked_at": t.get("linked_at"), "prefs": {**DEFAULT_PREFS, **(t.get("prefs") or {})}, "bot": BOT}


# ---------- customer ----------

def init_routes():
    current = D["get_current_user"]
    admin = D["get_current_admin_user"]

    @router.get("/me")
    async def me(current_user: dict = Depends(current)):
        u = await D["db"].users.find_one({"_id": _oid(current_user["sub"])}) or {}
        return _public(u)

    @router.post("/link")
    async def make_link(current_user: dict = Depends(current)):
        token = secrets.token_urlsafe(18)
        await D["db"].cmtv_tg_links.insert_one({"_id": token, "user_id": current_user["sub"],
                                                "expires_at": datetime.utcnow() + LINK_TTL})
        return {"url": f"https://t.me/{BOT}?start=link_{token}", "expires_in": int(LINK_TTL.total_seconds())}

    @router.post("/prefs")
    async def prefs(data: dict = Body(...), current_user: dict = Depends(current)):
        upd = {f"cmtv_telegram.prefs.{k}": bool(data[k]) for k in DEFAULT_PREFS if k in data}
        if upd:
            await D["db"].users.update_one({"_id": _oid(current_user["sub"]), "cmtv_telegram.chat_id": {"$exists": True}},
                                           {"$set": upd})
        u = await D["db"].users.find_one({"_id": _oid(current_user["sub"])}) or {}
        return _public(u)

    @router.post("/unlink")
    async def unlink(current_user: dict = Depends(current)):
        u = await D["db"].users.find_one({"_id": _oid(current_user["sub"])}) or {}
        chat = (u.get("cmtv_telegram") or {}).get("chat_id")
        await D["db"].users.update_one({"_id": u.get("_id")}, {"$unset": {"cmtv_telegram": ""}})
        if chat:
            await queue(current_user["sub"], chat, "🔕 Telegram alerts are off for your CMTV account. "
                        "Connect again any time from your dashboard.", kind="unlinked")
        return _public({})

    # ---------- admin: service notices ----------

    @router.post("/admin/notice")
    async def notice(data: dict = Body(...), current_user: dict = Depends(admin)):
        family = str(data.get("family") or "").lower()
        text = str(data.get("text") or "").strip()
        if family not in FAMILIES + ["all"]:
            raise HTTPException(400, f"family must be one of: {', '.join(FAMILIES + ['all'])}")
        if not text or len(text) > 1500:
            raise HTTPException(400, "Write a message (up to 1500 characters)")
        people = await recipients(family)
        if not data.get("dry_run", True):
            label = "everyone" if family == "all" else family.upper() if family in ("cctv",) else family.title()
            body = f"📣 <b>CMTV service notice</b> ({html.escape(label)})\n\n{html.escape(text)}"
            for uid, chat in people:
                await queue(uid, chat, body, kind="notice")
            await D["db"].cmtv_tg_notices.insert_one({"family": family, "text": text, "count": len(people),
                                                      "by": current_user.get("email") or current_user.get("sub"),
                                                      "at": datetime.utcnow()})
        return {"recipients": len(people), "sent": not data.get("dry_run", True)}

    @router.get("/admin/stats")
    async def stats(current_user: dict = Depends(admin)):
        db = D["db"]
        linked = await db.users.count_documents({"cmtv_telegram.chat_id": {"$exists": True}})
        per = {f: len(await recipients(f)) for f in FAMILIES}
        last = await db.cmtv_tg_notices.find({}, {"_id": 0}).sort("at", -1).limit(5).to_list(5)
        return {"linked": linked, "by_family": per, "recent_notices": last}


async def recipients(family: str):
    """(user_id, chat_id) for connected customers with notices on and an active service in the family"""
    out = []
    async for u in D["db"].users.find({"cmtv_telegram.chat_id": {"$exists": True}}):
        t = u.get("cmtv_telegram") or {}
        if not {**DEFAULT_PREFS, **(t.get("prefs") or {})}.get("notices"):
            continue
        uid = str(u["_id"])
        if family != "all":
            found = False
            async for s in D["db"].services.find({"user_id": uid, "status": "active"}):
                if family_of(s) == family:
                    found = True
                    break
            if not found:
                continue
        elif not await D["db"].services.count_documents({"user_id": uid, "status": "active"}):
            continue
        out.append((uid, t["chat_id"]))
    return out


# ---------- the bot's private bridge ----------

@bridge.post("/link")
async def bridge_link(request: Request, data: dict = Body(...)):
    _bridge_auth(request)
    token = str(data.get("token") or "")
    db = D["db"]
    row = await db.cmtv_tg_links.find_one_and_delete({"_id": token})
    if not row or row.get("expires_at", datetime.min) < datetime.utcnow():
        return {"ok": False, "reason": "expired"}
    u = await db.users.find_one({"_id": _oid(row["user_id"])})
    if not u:
        return {"ok": False, "reason": "expired"}
    await db.users.update_one({"_id": u["_id"]}, {"$set": {"cmtv_telegram": {
        "chat_id": int(data["chat_id"]), "username": data.get("username") or "", "name": data.get("name") or "",
        "linked_at": datetime.utcnow(), "prefs": {**DEFAULT_PREFS, **((u.get("cmtv_telegram") or {}).get("prefs") or {})}}}})
    first = (u.get("name") or "").split(" ")[0]
    return {"ok": True, "name": first or u.get("name") or ""}


@bridge.post("/unlink")
async def bridge_unlink(request: Request, data: dict = Body(...)):
    _bridge_auth(request)
    r = await D["db"].users.update_many({"cmtv_telegram.chat_id": int(data["chat_id"])}, {"$unset": {"cmtv_telegram": ""}})
    return {"ok": True, "accounts": r.modified_count}


@bridge.get("/outbox")
async def bridge_outbox(request: Request):
    _bridge_auth(request)
    items = []
    async for m in D["db"].cmtv_tg_outbox.find({"status": "queued"}).sort("created_at", 1).limit(25):
        items.append({"id": str(m["_id"]), "chat_id": m["chat_id"], "text": m["text"], "buttons": m.get("buttons") or []})
    return {"messages": items}


@bridge.post("/outbox/ack")
async def bridge_ack(request: Request, data: dict = Body(...)):
    _bridge_auth(request)
    db = D["db"]
    now = datetime.utcnow()
    for mid in data.get("sent") or []:
        await db.cmtv_tg_outbox.update_one({"_id": _oid(mid)}, {"$set": {"status": "sent", "sent_at": now}})
    for mid, err in (data.get("failed") or {}).items():
        m = await db.cmtv_tg_outbox.find_one_and_update({"_id": _oid(mid)}, {"$set": {"status": "failed", "error": str(err)[:200], "sent_at": now}})
        # blocked the bot / deleted the chat: stop sending to it
        if m and any(w in str(err).lower() for w in ("blocked", "chat not found", "user is deactivated", "forbidden")):
            await db.users.update_many({"cmtv_telegram.chat_id": m["chat_id"]}, {"$unset": {"cmtv_telegram": ""}})
    return {"ok": True}


# ---------- renewal reminders ----------

def _day(dt) -> str:
    return dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(TZ).strftime("%a %b %-d")


async def renewal_reminders(now: datetime = None):
    """Queue 3-day and 1-day reminders. Returns how many were queued."""
    now = now or datetime.utcnow()
    db = D["db"]
    queued = 0
    async for u in db.users.find({"cmtv_telegram.chat_id": {"$exists": True}}):
        t = u["cmtv_telegram"]
        if not {**DEFAULT_PREFS, **(t.get("prefs") or {})}.get("renewals"):
            continue
        uid = str(u["_id"])
        async for s in db.services.find({"user_id": uid, "status": "active", "is_trial": {"$ne": True},
                                         "account_type": {"$ne": "reseller"},
                                         "expiry_date": {"$gt": now, "$lte": now + timedelta(days=3)}}):
            if (s.get("auto_renew") or {}).get("status") == "ACTIVE":
                continue
            left = s["expiry_date"] - now
            stage = next((code for days, code in sorted(STAGES) if left <= timedelta(days=days)), None)
            if not stage:
                continue
            key = f"{s['_id']}:{s['expiry_date'].date().isoformat()}:{stage}"
            if await db.cmtv_tg_sent.find_one({"_id": key}):
                continue
            login = s.get("xtream_username") or s.get("username") or ""
            days = (s["expiry_date"].replace(tzinfo=ZoneInfo("UTC")).astimezone(TZ).date()
                    - now.replace(tzinfo=ZoneInfo("UTC")).astimezone(TZ).date()).days
            when = "today" if days <= 0 else "tomorrow" if days == 1 else f"on {_day(s['expiry_date'])}"
            text = (f"⏰ <b>{html.escape(s.get('product_name') or 'Your service')}</b> ends {when}"
                    + (f"\nLogin: <code>{html.escape(login)}</code>" if login else "")
                    + "\n\nRenew now and your login stays the same.")
            await queue(uid, t["chat_id"], text, [[{"text": "🔄 Renew now", "url": f"{SITE}/dashboard?renew={s['_id']}"}]], kind="renewal")
            await db.cmtv_tg_sent.insert_one({"_id": key, "at": now})
            queued += 1
    return queued


async def _loop():
    while True:
        try:
            hour = datetime.now(TZ).hour
            if 10 <= hour < 20:
                n = await renewal_reminders()
                if n:
                    log.info(f"Telegram renewal reminders queued: {n}")
            await D["db"].cmtv_tg_links.delete_many({"expires_at": {"$lt": datetime.utcnow()}})
        except Exception as e:
            log.warning(f"Telegram reminders failed: {e}")
        await asyncio.sleep(3600)


async def startup():
    asyncio.create_task(_loop())
