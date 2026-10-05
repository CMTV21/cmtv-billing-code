"""Dashboard "Test my line" (CMTV local addition 2026-10-04, the owner's pick from the ideas list).
GET /api/cmtv/linecheck/{service_id} (the customer's own TV line) answers in plain words, from live data:
  1. the plan: running until when, or ended (-> renew)
  2. the line on the server: Imperium API line (enabled / banned / end date); CCTV reseller line list (exact username match)
  3. the server itself: Uptime Kuma via cmtv_status.public_issues (CCTV / Imperium / Extreme / Amethyst)
  4. devices in use right now vs allowed: Imperium GET {base}/lines/{ref}/connections (live sessions);
     CCTV table_search row (column 9 = active connections, 10 = max)
Nothing is changed anywhere. 10 checks per customer per 10 minutes (cmtv_linechecks, also the log).
"""
import asyncio
import re
import time
from datetime import datetime, timedelta

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException

router = APIRouter(prefix="/api/cmtv/linecheck", tags=["cmtv-linecheck"])
D = {}
SERVER = {"aether": "Imperium", "xtream": "CCTV", "onestream": "Extreme"}


def init(**deps):
    D.update(deps)


def _day(dt):
    return dt.strftime("%b %-d, %Y") if dt else ""


def _exp(v):
    if isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


async def _imperium(login):
    from aether_service import AetherService
    p = ((await D["get_settings"]()).get("aether") or {}).get("panels")[0]
    a = AetherService(panel_url=p["panel_url"], api_token=p["api_token"])
    await a.me()
    b = await a._base()
    line = await a.get_line(login)
    l = line.get("line") or line if isinstance(line, dict) else {}
    if not l or not l.get("username"):
        return {"found": False}
    conns = await a._request("GET", f"{b}/lines/{a.ref(login)}/connections")
    live = [c for c in (conns.get("items") or []) if c.get("status", "active") == "active"]
    return {"found": True, "enabled": bool(l.get("enabled")) and not l.get("banned"), "ends": _exp(l.get("exp_date")),
            "max": int(l.get("max_connections") or 0), "in_use": len(live),
            "watching": [c.get("stream_title") for c in live if c.get("stream_title")][:4]}


async def _cctv(login):
    from xtreamui_service import XtreamUIService
    p = ((await D["get_settings"]()).get("xtream") or {}).get("panels")[0]

    def read():
        x = XtreamUIService(panel_url=p["panel_url"], admin_username=p["admin_username"], admin_password=p["admin_password"],
                            ssl_verify=p.get("ssl_verify", False), http_basic_user=p.get("http_basic_user", ""),
                            http_basic_pass=p.get("http_basic_pass", ""), proxy_url=p.get("proxy_url", ""), api_key=p.get("api_key", ""))
        sc = x._get_session_client()
        if not sc.logged_in and not sc.login():
            raise RuntimeError("panel sign-in failed")
        # 2026-10-04: by the panel's line id (billing's imported_users.xtream_user_id). The panel's search also matches
        # notes/owner columns, so a username search can return someone else's line.
        A = getattr(sc, "http_auth", None)
        page = sc.session.get(f"{sc.panel_url}/user_reseller.php", params={"id": lid}, auth=A, timeout=20).text
        m1 = re.search(r"var currentConnections = (\d+);", page)
        m2 = re.search(r"var expiryTimestamp = (\d+);", page)
        if not m1:
            return {"found": False}
        live = sc.session.get(f"{sc.panel_url}/table_search.php", auth=A, timeout=20,
                              params={"draw": "1", "start": "0", "length": "50", "id": "live_connections", "user_id": str(lid),
                                      "_": str(int(time.time() * 1000))}).json()
        return {"found": True, "max": int(m1.group(1)), "in_use": int(live.get("recordsTotal") or 0),
                "ends": datetime.utcfromtimestamp(int(m2.group(1))) if m2 else None,
                "enabled": (iu or {}).get("status", "active") not in ("disabled", "banned", "suspended")}
    iu = await D["db"].imported_users.find_one({"panel_type": "xtream", "username": login}, {"xtream_user_id": 1, "status": 1})
    lid = (iu or {}).get("xtream_user_id")
    if not lid:
        return {"found": False}
    return await asyncio.to_thread(read)


def init_routes():
    current = D["get_current_user"]

    @router.get("/{sid}")
    async def check(sid: str, current_user: dict = Depends(current)):
        db, uid = D["db"], current_user["sub"]
        svc = await db.services.find_one({"_id": ObjectId(sid), "user_id": uid}) if ObjectId.is_valid(sid) else None
        if not svc:
            raise HTTPException(404, "Service not found")
        now = datetime.utcnow()
        if await db.cmtv_linechecks.count_documents({"user_id": uid, "at": {"$gte": now - timedelta(minutes=10)}}) >= 10:
            raise HTTPException(429, "You've run a lot of checks: please wait a few minutes and try again.")
        login = svc.get("xtream_username") or svc.get("username") or ""
        panel = svc.get("panel_type")
        server = SERVER.get(panel, "your server")
        checks, actions = [], []

        # 1. the plan in billing
        ends = _exp(svc.get("expiry_date"))
        if svc.get("status") != "active" or (ends and ends < now):
            checks.append({"ok": False, "title": "Your plan has ended",
                           "detail": f"It ended {_day(ends)}. Renew and it works again on the same login." if ends else "Renew to keep watching."})
            actions.append("renew")
        else:
            days = (ends - now).days if ends else None
            checks.append({"ok": True, "title": "Your plan is active",
                           "detail": f"Runs until {_day(ends)} ({days} days left)." if ends else "No end date set."})

        # 2 + 4. the line on the panel, devices in use right now
        live = None
        try:
            live = await (_imperium(login) if panel == "aether" else _cctv(login) if panel == "xtream" else asyncio.sleep(0, None))
        except Exception:
            live = None
        if live is None:
            checks.append({"ok": None, "title": "Couldn't reach the server's control panel",
                           "detail": "That's on our side and doesn't mean your line is down. Try again in a few minutes."})
        elif not live.get("found"):
            checks.append({"ok": False, "title": f"We couldn't find your line on {server}",
                           "detail": "Message support with your username and we'll check it."})
            actions.append("support")
        else:
            if live.get("enabled") is False:
                checks.append({"ok": False, "title": "Your line is switched off on the server",
                               "detail": "This usually means a payment or account issue. Message support and we'll sort it out."})
                actions.append("support")
            else:
                checks.append({"ok": True, "title": f"Your line is switched on at {server}",
                               "detail": f"The server shows it running until {_day(live['ends'])}." if live.get("ends") else ""})
            mx, used = int(live.get("max") or 0), int(live.get("in_use") or 0)
            if mx:
                if used >= mx:
                    checks.append({"ok": False, "title": f"All {mx} device{'s' if mx != 1 else ''} are in use right now",
                                   "detail": "A new device can't start until one stops. Close the app on a device you're not "
                                             "using (fully, not just the screen), or add devices to your plan."
                                             + (f" Watching now: {', '.join(live['watching'])}." if live.get("watching") else "")})
                    actions.append("devices")
                else:
                    checks.append({"ok": True, "title": f"{used} of {mx} device{'s' if mx != 1 else ''} in use right now",
                                   "detail": "You have room to watch on another device." if used < mx else ""})

        # 3. the server itself
        try:
            import cmtv_status
            issues = [i for i in await cmtv_status.public_issues() if i.get("service") == server]
        except Exception:
            issues = []
        if issues:
            since = _exp(issues[0].get("since"))
            checks.append({"ok": False, "title": f"{server} is having a problem right now",
                           "detail": (f"Since {since.strftime('%-I:%M %p')} UTC. " if since else "") + "We're on it: it should come back by itself."})
            actions.append("status")
        elif panel in SERVER:
            checks.append({"ok": True, "title": f"{server} is running normally", "detail": ""})

        bad = [c for c in checks if c["ok"] is False]
        verdict = ("Found something: see below." if bad else
                   "Your line looks fine. If it still isn't playing, it's most likely the device or the internet connection: try the quick fixes.")
        if not bad:
            actions.append("fixes")
        await db.cmtv_linechecks.insert_one({"user_id": uid, "service_id": sid, "at": now, "ok": not bad,
                                             "problems": [c["title"] for c in bad]})
        return {"verdict": verdict, "ok": not bad, "checks": checks, "actions": list(dict.fromkeys(actions)), "login": login,
                "server": server}
