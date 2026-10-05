"""Sports schedule (CMTV local addition 2026-10-04, the owner's pick: "what's on tonight" page + Telegram post).
Stage 1 (this file today): the owner's TheSportsDB key, stored in cmtv_config {_id: "sports"}.key (never returned; the
admin sees only the last 4 characters) and a test call showing what the key can see for the main leagues.
The free test key (123) returns nothing for NHL/NFL/NBA/MLB/UFC/EPL (checked 2026-10-04), so the page and the daily post
are built once the owner's key is in.
"""
import json
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Body, Depends, HTTPException

router = APIRouter(prefix="/api/cmtv/sports", tags=["cmtv-sports"])
D = {}
TZ = ZoneInfo("America/Toronto")
LEAGUES = ["NHL", "NFL", "NBA", "MLB", "MLS", "Canadian Football League", "UFC", "English Premier League",
           "UEFA Champions League", "Formula 1"]


def init(**deps):
    D.update(deps)


def _get(url, key=None):
    req = urllib.request.Request(url, headers={"User-Agent": "CMTV", **({"X-API-KEY": key} if key else {})})
    return json.loads(urllib.request.urlopen(req, timeout=20).read() or b"{}")


async def _key():
    return ((await D["db"].cmtv_config.find_one({"_id": "sports"})) or {}).get("key") or ""


def probe(key):
    """What the key sees: v1 day schedule for each main league over the last 3 days (one league with games is enough)."""
    import asyncio  # noqa: F401  (runs in a thread)
    out = {}
    days = [(datetime.now(TZ) - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(3)]
    for l in LEAGUES:
        n = 0
        for d in days:
            try:
                r = _get(f"https://www.thesportsdb.com/api/v1/json/{urllib.parse.quote(key)}/eventsday.php?" +
                         urllib.parse.urlencode({"d": d, "l": l}))
                n += len(r.get("events") or [])
            except Exception:
                pass
        out[l] = n
    return out


def init_routes():
    admin = D["get_current_admin_user"]

    @router.get("/admin")
    async def status(current_user: dict = Depends(admin)):
        doc = await D["db"].cmtv_config.find_one({"_id": "sports"}) or {}
        k = doc.get("key") or ""
        return {"has_key": bool(k), "key_end": k[-4:] if k else "", "probe": doc.get("probe"), "probed_at": doc.get("probed_at")}

    @router.post("/admin/key")
    async def set_key(data: dict = Body(...), current_user: dict = Depends(admin)):
        import asyncio
        k = str(data.get("key") or "").strip()
        if not k or len(k) > 80 or any(c.isspace() for c in k):
            raise HTTPException(400, "Paste just the key (no spaces).")
        p = await asyncio.to_thread(probe, k)
        await D["db"].cmtv_config.update_one({"_id": "sports"}, {"$set": {"key": k, "probe": p, "probed_at": datetime.utcnow(),
                                                                          "set_by": current_user.get("sub")}}, upsert=True)
        return {"ok": True, "probe": p, "key_end": k[-4:]}
