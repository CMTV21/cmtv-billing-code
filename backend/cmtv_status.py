"""Service status from Uptime Kuma (CMTV local addition 2026-09-29).
Uptime Kuma (on the Asus) sends a webhook to POST /api/cmtv/status/kuma on every monitor change (header X-Kuma-Token =
KUMA_WEBHOOK_TOKEN in /opt/backend/.env). Billing keeps each monitor's state; customers see a banner (dashboard, Support,
new-ticket form, cmtv.info) only for monitors mapped to a customer-facing service, and only once it has been down for
PUBLIC_AFTER_MIN minutes (a one-check blip never shows). No IPs or error messages ever leave the admin API.
  POST /api/cmtv/status/kuma                  Kuma webhook (token)
  GET  /api/cmtv/status                       public: {"issues": [{service, since}]}
  GET  /api/cmtv/status/admin                 admin: every monitor + the last 60 changes
  POST /api/cmtv/status/admin/clear {monitor} admin: mark a stuck monitor as up
Map monitors to public names in cmtv_config {_id: "status_monitors", map: {kuma monitor name: public service name}}.
Collections: cmtv_status_monitors (_id = monitor name), cmtv_status_events.
2026-09-29: also posts SILENTLY (no notification sound) to the Ops Critical topic (all monitors) and, for customer
services, the customer group's Status/Outages topic + the CMTV Updates channel; recovery replies to those posts
(announce(), every minute). Kuma's own Telegram alert now only covers the "Billing" monitor (billing can't report itself).
"""
import asyncio
import html
import hmac
import logging
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Body, Depends, Header, HTTPException

log = logging.getLogger("server")
router = APIRouter(prefix="/api/cmtv/status", tags=["cmtv-status"])
D = {}
PUBLIC_AFTER_MIN = 3
DEFAULT_MAP = {"CCTV": "CCTV", "Extreme": "Extreme", "Amethyst": "Amethyst", "Imperium": "Imperium",
               "Audiobookshelf": "Audiobooks"}


def init(**deps):
    D.update(deps)


def _iso(v):
    return v.isoformat() + "Z" if isinstance(v, datetime) else None


async def monitor_map():
    doc = await D["db"].cmtv_config.find_one({"_id": "status_monitors"}) or {}
    return doc.get("map") or DEFAULT_MAP


async def record(name: str, up: bool, msg: str = "", at: datetime = None):
    """Store one change from Kuma. Returns True if the state changed."""
    db = D["db"]
    now = at or datetime.utcnow()
    cur = await db.cmtv_status_monitors.find_one({"_id": name}) or {}
    status = "up" if up else "down"
    changed = cur.get("status") != status
    upd = {"status": status, "last_msg": (msg or "")[:300], "last_seen": now}
    if changed:
        upd["since"] = now
    await db.cmtv_status_monitors.update_one({"_id": name}, {"$set": upd}, upsert=True)
    if changed:
        await db.cmtv_status_events.insert_one({"monitor": name, "status": status, "msg": (msg or "")[:300], "at": now})
    return changed


async def kuma_blind():
    """2026-09-29: most monitors down at once = almost certainly Kuma's own connection (it runs on a home server),
    not every service failing together. Then nothing goes public; only Ops Critical hears about it."""
    total = await D["db"].cmtv_status_monitors.count_documents({})
    down = await D["db"].cmtv_status_monitors.count_documents({"status": "down"})
    return total >= 4 and down >= max(4, (total * 6 + 9) // 10)   # 4+ and at least 60%


async def public_issues(now=None):
    now = now or datetime.utcnow()
    if await kuma_blind():
        return []
    names = await monitor_map()
    out = []
    async for m in D["db"].cmtv_status_monitors.find({"status": "down", "_id": {"$in": list(names)}}):
        since = m.get("since")
        if isinstance(since, datetime) and now - since >= timedelta(minutes=PUBLIC_AFTER_MIN):
            out.append({"service": names[m["_id"]], "since": _iso(since)})
    return sorted(out, key=lambda x: x["since"])


# ---------- silent Telegram posts (2026-09-29, the user's choice: no notification sound, Kuma's own alert replaced) ----------
# Once a monitor has been down PUBLIC_AFTER_MIN minutes: Ops group Critical topic (every monitor, with Kuma's message) and,
# for customer services, the customer group's Status/Outages topic + the CMTV Updates channel (via the support bot, which
# already posts there). On recovery, "back to normal" is posted as a reply to each of those posts.
SUPPORT_ENV = "/opt/cmtv-bots/support/.env"
TZ = ZoneInfo("America/Toronto")
logging.getLogger("httpx").setLevel(logging.WARNING)   # request URLs contain bot tokens


def _support_env():
    vals = {}
    try:
        with open(SUPPORT_ENV) as f:
            for line in f:
                if "=" in line and not line.lstrip().startswith("#"):
                    k, v = line.split("=", 1)
                    vals[k.strip()] = v.strip().strip("'\"")
    except OSError as e:
        log.warning(f"status: can't read the support bot settings ({e})")
    return vals


async def _send(token, chat, text, thread=None, reply_to=None):
    """Silent Telegram message; returns its message_id or None. Never raises."""
    msg = {"chat_id": chat, "text": text, "parse_mode": "HTML", "disable_notification": True, "disable_web_page_preview": True}
    if thread:
        msg["message_thread_id"] = int(thread)
    if reply_to:
        msg["reply_parameters"] = {"message_id": int(reply_to), "allow_sending_without_reply": True}
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(f"https://api.telegram.org/bot{token}/sendMessage", json=msg)
        j = r.json() if r.content else {}
        if not j.get("ok"):
            log.warning(f"status: Telegram said {r.status_code} {j.get('description', '')}")
            return None
        return j["result"]["message_id"]
    except Exception as e:
        log.warning(f"status: Telegram failed ({type(e).__name__})")
        return None


def _local(dt):
    return dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(TZ).strftime("%-I:%M %p")


def _mins(a, b):
    m = max(1, int((b - a).total_seconds() // 60))
    return f"{m} min" if m < 90 else f"{m // 60} h {m % 60} min"


async def announce(now=None):
    """Post new outages (down PUBLIC_AFTER_MIN+ minutes) and recoveries of announced ones. Returns what was posted."""
    import cmtv_notify
    db = D["db"]
    now = now or datetime.utcnow()
    names = await monitor_map()
    env = _support_env()
    token, chat, thread, channel = env.get("BOT_TOKEN"), env.get("CMTV_CHAT_ID"), env.get("CMTV_STATUS_THREAD_ID"), env.get("UPDATES_CHANNEL_ID")
    posted = []
    blind = await kuma_blind()
    state = await db.cmtv_config.find_one({"_id": "status_state"}) or {}
    if blind and not state.get("blind_since"):
        await cmtv_notify.ops("🟠 Uptime Kuma sees most of its monitors down at the same time. That's almost certainly Kuma's own "
                              "connection (it runs on the home server), not every service at once, so nothing is being posted to "
                              "customers. Check the Asus / home internet.", "critical", silent=True)
        await db.cmtv_config.update_one({"_id": "status_state"}, {"$set": {"blind_since": now}}, upsert=True)
    elif not blind and state.get("blind_since"):
        await cmtv_notify.ops("🟢 Uptime Kuma is seeing normally again.", "critical", silent=True)
        await db.cmtv_config.update_one({"_id": "status_state"}, {"$unset": {"blind_since": ""}})
    async for m in db.cmtv_status_monitors.find({}):
        name, public = m["_id"], names.get(m["_id"])
        since = m.get("since")
        if m.get("status") == "down" and not m.get("announced_at") and isinstance(since, datetime) \
                and now - since >= timedelta(minutes=PUBLIC_AFTER_MIN):
            ids = {}
            if blind:   # covered by the single "Kuma can't see" note above; nothing public
                await db.cmtv_status_monitors.update_one({"_id": name}, {"$set": {"announced_at": now, "announced_ids": {}, "quiet": True}})
                continue
            await cmtv_notify.ops(f"🔴 {name} is down (since {_local(since)} ET).\nUptime Kuma: {m.get('last_msg') or '-'}",
                                  "critical", silent=True)
            if public and token:
                text = (f"⚠️ <b>{html.escape(public)}</b>: we've detected a problem since {_local(since)} ET and we're working on it. "
                        "We'll post here when it's back.")
                if chat and thread:
                    ids["group"] = await _send(token, chat, text, thread=thread)
                if channel:
                    ids["channel"] = await _send(token, channel, text)
            await db.cmtv_status_monitors.update_one({"_id": name}, {"$set": {"announced_at": now, "announced_ids": ids}})
            posted.append(("down", name))
        elif m.get("status") == "up" and m.get("announced_at"):
            down_since = await db.cmtv_status_events.find_one({"monitor": name, "status": "down", "at": {"$lte": m.get("since") or now}},
                                                              sort=[("at", -1)])
            took = _mins(down_since["at"], m.get("since") or now) if down_since else None
            ids = m.get("announced_ids") or {}
            if m.get("quiet"):   # it went down while Kuma couldn't see: nothing was posted, so nothing to clear
                await db.cmtv_status_monitors.update_one({"_id": name}, {"$unset": {"announced_at": "", "announced_ids": "", "quiet": ""}})
                continue
            await cmtv_notify.ops(f"🟢 {name} is back up{f' after {took}' if took else ''}.", "critical", silent=True)
            if public and token and any(ids.values()):
                text = f"✅ <b>{html.escape(public)}</b> is back to normal{f' (down for {took})' if took else ''}. Thanks for your patience."
                if chat and thread:
                    await _send(token, chat, text, thread=thread, reply_to=ids.get("group"))
                if channel:
                    await _send(token, channel, text, reply_to=ids.get("channel"))
            await db.cmtv_status_monitors.update_one({"_id": name}, {"$unset": {"announced_at": "", "announced_ids": ""}})
            posted.append(("up", name))
    return posted


async def _loop():
    await asyncio.sleep(60)
    while True:
        try:
            done = await announce()
            if done:
                log.info(f"status: posted {done}")
        except Exception as e:
            log.warning(f"status announce failed: {e}")
        await asyncio.sleep(60)


async def startup():
    asyncio.create_task(_loop())


def init_routes():
    admin = D["get_current_admin_user"]

    @router.post("/kuma", include_in_schema=False)
    async def kuma(body: dict = Body(...), x_kuma_token: str = Header(default="")):
        want = os.environ.get("KUMA_WEBHOOK_TOKEN", "")
        if not want or not hmac.compare_digest(x_kuma_token or "", want):
            raise HTTPException(403, "Forbidden")
        mon, hb = body.get("monitor") or {}, body.get("heartbeat") or {}
        if not mon or not hb:   # Kuma's "Test" button sends only a message
            log.info("status: Kuma test message received")
            return {"ok": True, "test": True}
        name = str(mon.get("name") or "").strip()[:80]
        if not name:
            raise HTTPException(400, "No monitor name")
        up = int(hb.get("status", 1)) == 1   # Kuma: 0 down, 1 up, 2 pending, 3 maintenance
        if int(hb.get("status", 1)) in (2, 3):
            return {"ok": True, "ignored": "pending/maintenance"}
        changed = await record(name, up, str(hb.get("msg") or body.get("msg") or ""))
        log.info(f"status: {name} {'up' if up else 'DOWN'}{' (changed)' if changed else ''}")
        return {"ok": True, "changed": changed}

    @router.get("")
    async def public_status():
        return {"issues": await public_issues()}

    @router.get("/admin")
    async def admin_status(current_user: dict = Depends(admin)):
        names = await monitor_map()
        mons = [{"monitor": m["_id"], "public": names.get(m["_id"]), "status": m.get("status"), "since": _iso(m.get("since")),
                 "last_seen": _iso(m.get("last_seen")), "msg": m.get("last_msg")}
                async for m in D["db"].cmtv_status_monitors.find().sort("_id", 1)]
        events = [{"monitor": e["monitor"], "status": e["status"], "at": _iso(e["at"]), "msg": e.get("msg")}
                  async for e in D["db"].cmtv_status_events.find().sort("at", -1).limit(60)]
        return {"monitors": mons, "events": events, "public_after_min": PUBLIC_AFTER_MIN, "issues": await public_issues()}

    @router.post("/admin/clear")
    async def admin_clear(body: dict = Body(...), current_user: dict = Depends(admin)):
        name = str(body.get("monitor") or "")
        if not await D["db"].cmtv_status_monitors.find_one({"_id": name}):
            raise HTTPException(404, "No such monitor")
        await record(name, True, "cleared by admin")
        return {"ok": True}
