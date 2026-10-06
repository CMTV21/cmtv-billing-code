"""Sports schedule (CMTV local addition 2026-10-04, the owner's pick: "what's on tonight" page + Telegram post).
Stage 1 (2026-10-04): the owner's TheSportsDB key in cmtv_config {_id: "sports"}.key (never returned; the admin sees only
the last 4 characters) + a test call per league.
Stage 2 (2026-10-05, key added): the public /sports page "What's on tonight". Leagues are looked up by ID (by name the CFL
returned nothing: TheSportsDB calls it "CFL"). A Toronto day = games whose start (UTC strTimestamp) falls on that local
date, so two UTC days are fetched. Cached per day in cmtv_sports_cache (30 min for today/tomorrow).
GET /api/cmtv/sports/schedule?day=today|tomorrow (public) -> {ready, day, date, leagues: [{id, name, emoji, games: [...]}]}
The daily Telegram post is not switched on yet: it needs the owner's choice of group / topic.
"""
import asyncio
import json
import logging
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Body, Depends, HTTPException

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/cmtv/sports", tags=["cmtv-sports"])
D = {}
TZ = ZoneInfo("America/Toronto")
# (TheSportsDB league id, name shown, emoji)
LEAGUES = [(4380, "NHL", "🏒"), (4391, "NFL", "🏈"), (4387, "NBA", "🏀"), (4424, "MLB", "⚾"), (4405, "CFL", "🏈"),
           (4346, "MLS", "⚽"), (4328, "Premier League", "⚽"), (4480, "Champions League", "⚽"), (4443, "UFC", "🥊"),
           (4370, "Formula 1", "🏎️")]
FRESH = timedelta(minutes=30)


def init(**deps):
    D.update(deps)


def _get(url, key=None):
    req = urllib.request.Request(url, headers={"User-Agent": "CMTV", **({"X-API-KEY": key} if key else {})})
    return json.loads(urllib.request.urlopen(req, timeout=20).read() or b"{}")


async def _key():
    return ((await D["db"].cmtv_config.find_one({"_id": "sports"})) or {}).get("key") or ""


def _day_events(key, utc_day, league_id):
    url = f"https://www.thesportsdb.com/api/v1/json/{urllib.parse.quote(key)}/eventsday.php?" + \
        urllib.parse.urlencode({"d": utc_day, "l": league_id})
    return _get(url).get("events") or []


def probe(key):
    """What the key sees: games per league over the last 3 days."""
    out = {}
    days = [(datetime.now(TZ) - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(3)]
    for lid, name, _ in LEAGUES:
        n = 0
        for d in days:
            try:
                n += len(_day_events(key, d, lid))
            except Exception:
                pass
        out[name] = n
    return out


def _start(e):
    ts = e.get("strTimestamp")
    if ts:
        try:
            return datetime.fromisoformat(ts.replace("Z", "")[:19]).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    if e.get("dateEvent") and e.get("strTime"):
        try:
            return datetime.fromisoformat(f"{e['dateEvent']}T{e['strTime'][:8]}").replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def _game(e, start):
    local = start.astimezone(TZ)
    hs, as_ = e.get("intHomeScore"), e.get("intAwayScore")
    status = str(e.get("strStatus") or "").strip()
    done = status.lower() in ("match finished", "ft", "aet", "ap", "finished", "final")
    return {"id": e.get("idEvent"), "event": e.get("strEvent"), "home": e.get("strHomeTeam"), "away": e.get("strAwayTeam"),
            "home_badge": e.get("strHomeTeamBadge"), "away_badge": e.get("strAwayTeamBadge"),
            "start": start.isoformat(), "time": local.strftime("%I:%M %p").lstrip("0"),
            "score": f"{as_}–{hs}" if hs not in (None, "") and as_ not in (None, "") else None,
            "status": "final" if done else ("live" if status and status.lower() not in ("ns", "not started", "") else "upcoming"),
            "venue": e.get("strVenue"), "tv": e.get("strTVStation")}


async def schedule(local_day):
    """{ready, date, leagues} for a Toronto date (date object)."""
    key = await _key()
    if not key:
        return {"ready": False}
    db = D["db"]
    did = local_day.isoformat()
    cached = await db.cmtv_sports_cache.find_one({"_id": did})
    today = datetime.now(TZ).date()
    if cached and (local_day < today or datetime.utcnow() - cached["fetched_at"] < FRESH):
        return {"ready": True, "date": did, "leagues": cached["leagues"]}
    utc_days = sorted({local_day.isoformat(), (local_day + timedelta(days=1)).isoformat()})

    def fetch():
        out = []
        for lid, name, emoji in LEAGUES:
            games, seen = [], set()
            for d in utc_days:
                try:
                    evs = _day_events(key, d, lid)
                except Exception as ex:
                    logger.info(f"sports: {name} {d}: {ex}")
                    evs = []
                for e in evs:
                    st = _start(e)
                    if not st or st.astimezone(TZ).date() != local_day or e.get("idEvent") in seen:
                        continue
                    seen.add(e.get("idEvent"))
                    games.append(_game(e, st))
            games.sort(key=lambda g: g["start"])
            if games:
                out.append({"id": lid, "name": name, "emoji": emoji, "games": games})
        return out
    leagues = await asyncio.to_thread(fetch)
    await db.cmtv_sports_cache.update_one({"_id": did}, {"$set": {"leagues": leagues, "fetched_at": datetime.utcnow()}}, upsert=True)
    return {"ready": True, "date": did, "leagues": leagues}


def init_routes():
    admin = D["get_current_admin_user"]

    @router.get("/schedule")
    async def public_schedule(day: str = "today"):
        today = datetime.now(TZ).date()
        d = today + timedelta(days=1) if day == "tomorrow" else today
        try:
            out = await schedule(d)
        except Exception as e:
            logger.warning(f"sports schedule failed: {e}")
            out = {"ready": True, "date": d.isoformat(), "leagues": [], "error": True}
        return {**out, "day": "tomorrow" if day == "tomorrow" else "today"}

    @router.get("/admin")
    async def status(current_user: dict = Depends(admin)):
        doc = await D["db"].cmtv_config.find_one({"_id": "sports"}) or {}
        k = doc.get("key") or ""
        return {"has_key": bool(k), "key_end": k[-4:] if k else "", "probe": doc.get("probe"), "probed_at": doc.get("probed_at")}

    @router.post("/admin/key")
    async def set_key(data: dict = Body(...), current_user: dict = Depends(admin)):
        k = str(data.get("key") or "").strip()
        if not k or len(k) > 80 or any(c.isspace() for c in k):
            raise HTTPException(400, "Paste just the key (no spaces).")
        p = await asyncio.to_thread(probe, k)
        await D["db"].cmtv_config.update_one({"_id": "sports"}, {"$set": {"key": k, "probe": p, "probed_at": datetime.utcnow(),
                                                                          "set_by": current_user.get("sub")}}, upsert=True)
        await D["db"].cmtv_sports_cache.delete_many({})
        return {"ok": True, "probe": p, "key_end": k[-4:]}
