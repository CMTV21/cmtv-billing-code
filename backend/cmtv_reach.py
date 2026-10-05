"""Reach panel-only customers (CMTV local addition 2026-10-05, 2027 marketing plan #2: "own your audience").
~128 customers with an active line exist only as <line>@panel.local placeholders: no email, never signed in, they renew
with the owner directly. Billing can't contact them, so this makes it quick for the OWNER to (he has their contact):
- a personal link per customer, https://billing.cmtv.info/hi/<token>: opening it signs them straight into their account
  (no TV password to remember) and sends them to /link-email (add email + website password -> the $5 claim credit);
- Admin > Reach customers: every placeholder with an active line, ending-soon first, "Copy message" (text with the link),
  "Mark sent" (how), and the status updating by itself: Not sent -> Sent -> Opened -> Done (account finished);
- a weekly Ops (Billing) note on Mondays when lines ending within 30 days still haven't been sent their link.
A link only works while the account is still a placeholder; once finished it says "already set up, sign in".
Collection cmtv_reach {_id: user_id, token, created_at, sent_at, sent_via, opened_at, opens}.
"""
import asyncio
import logging
import re
import secrets
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from bson import ObjectId
from fastapi import APIRouter, Body, Depends, HTTPException

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/cmtv/reach", tags=["cmtv-reach"])
D = {}
TZ = ZoneInfo("America/Toronto")
SITE = "https://billing.cmtv.info"
SERVER = {"xtream": "CCTV", "aether": "Imperium", "manual": "Add-on"}
VIA = ["Text", "Telegram", "Facebook", "Email", "In person", "Other"]


def init(**deps):
    D.update(deps)


def _placeholder(u):
    return bool(u) and str(u.get("email") or "").lower().endswith("@panel.local") and u.get("role") == "user"


def _first(u):
    n = str(u.get("name") or "").strip()
    # a name that is just the line username isn't a name
    if not n or re.fullmatch(r"[A-Za-z0-9]{6,14}", n) or n == u.get("panel_username"):
        return ""
    return n.split(" ")[0]


async def _token(uid):
    db = D["db"]
    doc = await db.cmtv_reach.find_one({"_id": uid})
    if doc and doc.get("token"):
        return doc["token"]
    tok = secrets.token_urlsafe(12)
    await db.cmtv_reach.update_one({"_id": uid}, {"$setOnInsert": {"token": tok, "created_at": datetime.utcnow()}}, upsert=True)
    return (await db.cmtv_reach.find_one({"_id": uid}))["token"]


async def _reward():
    doc = await D["db"].cmtv_config.find_one({"_id": "claim_reward"}) or {}
    return float(doc.get("amount") or 5) if doc.get("enabled", True) else 0.0


def message(first, link, reward):
    hi = f"Hi {first}!" if first else "Hi!"
    gift = f" and we'll add ${reward:.0f} credit to your account" if reward else ""
    return (f"{hi} It's CMTV 👋 Could you finish your CMTV account? It takes 30 seconds{gift}. You'll get a reminder before "
            f"your plan ends, can renew online any time, and your logins are always there if you need them. "
            f"Your personal link: {link}")


async def rows():
    db = D["db"]
    now = datetime.utcnow()
    reach = {d["_id"]: d async for d in db.cmtv_reach.find({})}
    reward = await _reward()
    out = []
    users = {str(u["_id"]): u async for u in db.users.find({"email": {"$regex": "@panel\\.local$"}, "role": "user"})}
    by_user = {}
    async for s in db.services.find({"user_id": {"$in": list(users)}, "status": "active"}):
        by_user.setdefault(s["user_id"], []).append(s)
    for uid, svcs in by_user.items():
        u = users[uid]
        svcs.sort(key=lambda s: s.get("expiry_date") or now)
        s = svcs[0]
        tok = await _token(uid)
        link = f"{SITE}/hi/{tok}"
        r = reach.get(uid) or {}
        exp = s.get("expiry_date")
        first = _first(u)
        out.append({
            "user_id": uid, "name": first or "", "line": s.get("xtream_username") or s.get("username") or u.get("panel_username") or "",
            "server": SERVER.get(s.get("panel_type"), s.get("panel_type") or ""), "devices": s.get("max_connections"),
            "ends": exp, "days_left": (exp - now).days if exp else None, "lines": len(svcs),
            "link": link, "message": message(first, link, reward),
            "status": "opened" if r.get("opened_at") else "sent" if r.get("sent_at") else "new",
            "sent_at": r.get("sent_at"), "sent_via": r.get("sent_via"), "opened_at": r.get("opened_at")})
    # finished ones (were reached through a link, or claimed on their own) for the Done tab
    done = []
    async for d in db.cmtv_reach.find({}):
        u = await db.users.find_one({"_id": ObjectId(d["_id"])}) if ObjectId.is_valid(d["_id"]) else None
        if u and not _placeholder(u) and u.get("role") in ("user", "merged"):
            done.append({"user_id": d["_id"], "name": u.get("name") or "", "status": "done", "sent_at": d.get("sent_at"),
                         "sent_via": d.get("sent_via"), "opened_at": d.get("opened_at"), "done_at": u.get("cmtv_claimed_at"),
                         "email": u.get("email") if u.get("role") == "user" else "(joined to their other account)"})
    out.sort(key=lambda x: (x["days_left"] if x["days_left"] is not None else 99999))
    return out, done, reward


async def weekly_note():
    """Mondays: tell the owner how many lines ending within 30 days still haven't been sent their link."""
    out, done, _ = await rows()
    soon = [r for r in out if r["days_left"] is not None and r["days_left"] <= 30 and r["status"] == "new"]
    if not soon:
        return 0
    try:
        import cmtv_notify
        await cmtv_notify.ops(f"📇 {len(soon)} panel-only customer{'s' if len(soon) != 1 else ''} end within 30 days and "
                              f"haven't had their sign-up link yet. Copy their message in Admin > Reach customers "
                              f"({SITE}/admin/reach). {len(done)} finished so far.", "billing", await D["get_settings"]())
    except Exception as e:
        logger.warning(f"reach weekly note failed: {e}")
    return len(soon)


async def _loop():
    await asyncio.sleep(120)
    while True:
        try:
            now = datetime.now(TZ)
            key = now.strftime("%G-W%V")
            cfg = await D["db"].cmtv_config.find_one({"_id": "reach"}) or {}
            if now.weekday() == 0 and now.hour >= 10 and cfg.get("last_week") != key:
                await D["db"].cmtv_config.update_one({"_id": "reach"}, {"$set": {"last_week": key}}, upsert=True)
                await weekly_note()
        except Exception as e:
            logger.warning(f"reach loop: {e}")
        await asyncio.sleep(1800)


async def startup():
    await D["db"].cmtv_reach.create_index("token", unique=True, sparse=True)
    asyncio.create_task(_loop())


def init_routes():
    admin = D["get_current_admin_user"]

    @router.get("/admin")
    async def admin_list(current_user: dict = Depends(admin)):
        out, done, reward = await rows()
        return {"rows": out, "done": done, "reward": reward, "via": VIA, "counts": {
            "active": len(out), "soon": sum(1 for r in out if r["days_left"] is not None and r["days_left"] <= 30),
            "new": sum(r["status"] == "new" for r in out), "sent": sum(r["status"] == "sent" for r in out),
            "opened": sum(r["status"] == "opened" for r in out), "done": len(done)}}

    @router.post("/admin/{uid}/sent")
    async def admin_sent(uid: str, data: dict = Body(default={}), current_user: dict = Depends(admin)):
        if data.get("undo"):
            await D["db"].cmtv_reach.update_one({"_id": uid}, {"$unset": {"sent_at": "", "sent_via": ""}})
            return {"ok": True}
        via = data.get("via") if data.get("via") in VIA else "Other"
        await _token(uid)
        await D["db"].cmtv_reach.update_one({"_id": uid}, {"$set": {"sent_at": datetime.utcnow(), "sent_via": via,
                                                                   "sent_by": current_user.get("sub")}})
        return {"ok": True}

    async def _by_token(token):
        doc = await D["db"].cmtv_reach.find_one({"token": str(token or "")[:40]}) if token else None
        if not doc:
            raise HTTPException(404, "This link isn't valid.")
        u = await D["db"].users.find_one({"_id": ObjectId(doc["_id"])}) if ObjectId.is_valid(doc["_id"]) else None
        return doc, u

    @router.get("/t/{token}")
    async def public_info(token: str):
        doc, u = await _by_token(token)
        if not _placeholder(u):
            return {"done": True}
        s = await D["db"].services.find_one({"user_id": doc["_id"], "status": "active"}, sort=[("expiry_date", 1)]) or {}
        await D["db"].cmtv_reach.update_one({"_id": doc["_id"]}, {"$set": {"opened_at": doc.get("opened_at") or datetime.utcnow()},
                                                                  "$inc": {"opens": 1}})
        return {"done": False, "name": _first(u), "line": s.get("xtream_username") or s.get("username") or u.get("panel_username") or "",
                "server": SERVER.get(s.get("panel_type"), ""), "ends": s.get("expiry_date"), "reward": await _reward()}

    @router.post("/t/{token}/start")
    async def public_start(token: str):
        doc, u = await _by_token(token)
        if not _placeholder(u):
            raise HTTPException(410, "Your account is already set up. Sign in with your email.")
        import cmtv_claim
        access = cmtv_claim.D["create_access_token"]({"sub": str(u["_id"]), "email": u["email"], "role": "user"})
        await D["db"].cmtv_reach.update_one({"_id": doc["_id"]}, {"$set": {"started_at": datetime.utcnow()}})
        logger.info(f"Reach link used for {u.get('panel_username') or u['_id']}")
        return {"access_token": access, "token_type": "bearer", "user": cmtv_claim.user_payload(u)}
