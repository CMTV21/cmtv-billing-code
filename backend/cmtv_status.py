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
"""
import hmac
import logging
import os
from datetime import datetime, timedelta

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


async def public_issues(now=None):
    now = now or datetime.utcnow()
    names = await monitor_map()
    out = []
    async for m in D["db"].cmtv_status_monitors.find({"status": "down", "_id": {"$in": list(names)}}):
        since = m.get("since")
        if isinstance(since, datetime) and now - since >= timedelta(minutes=PUBLIC_AFTER_MIN):
            out.append({"service": names[m["_id"]], "since": _iso(since)})
    return sorted(out, key=lambda x: x["since"])


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
