"""Referral campaigns (CMTV local addition 2026-10-05, 2027 marketing plan #3: two referral pushes a year).
Normal referral rewards live in the developer's settings.referral {referrer_reward (credit when the friend's first order
of minimum_purchase+ is paid; the amount is fixed when the friend SIGNS UP), referred_reward (credit to the friend at sign-up)}.
A campaign (Admin > Notices "Referral campaign": first/last day Toronto, the two amounts, a name) raises them for those
days: on the first day the loop saves the normal amounts and writes the campaign ones; after the last day (or when switched
off) it puts the saved ones back. So friends who sign up during the campaign get the campaign amounts.
Also GET /api/cmtv/refboost (public): the amounts right now + the campaign, for the dashboard's referral card.
Config: cmtv_config {_id: "referral_boost", enabled, start, end, referrer, referred, label, applied, saved}.
NOTE: while a campaign is applied, change the normal amounts here (they're restored from "saved"), not in Settings.
"""
import asyncio
import logging
from datetime import datetime, time
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Body, Depends, HTTPException

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/cmtv/refboost", tags=["cmtv-refboost"])
D = {}
TZ = ZoneInfo("America/Toronto")
DEFAULT = {"enabled": False, "start": None, "end": None, "referrer": 25.0, "referred": 10.0, "label": "Bring a friend"}


def init(**deps):
    D.update(deps)


async def config():
    doc = await D["db"].cmtv_config.find_one({"_id": "referral_boost"}) or {}
    return {**DEFAULT, **{k: v for k, v in doc.items() if k != "_id"}}


def status(cfg, now=None):
    now = (now or datetime.now(TZ)).astimezone(TZ)
    if not (cfg.get("enabled") and cfg.get("start") and cfg.get("end")):
        return "off"
    a = datetime.combine(datetime.strptime(cfg["start"], "%Y-%m-%d").date(), time(0, 0), tzinfo=TZ)
    b = datetime.combine(datetime.strptime(cfg["end"], "%Y-%m-%d").date(), time(23, 59, 59), tzinfo=TZ)
    return "scheduled" if now < a else "ended" if now > b else "running"


async def tick(now=None):
    """Apply or undo the campaign amounts. Returns "applied" / "restored" / None."""
    db = D["db"]
    cfg = await config()
    st = status(cfg, now)
    s = await db.settings.find_one({}) or {}
    ref = s.get("referral") or {}
    if st == "running" and not cfg.get("applied"):
        saved = {"referrer_reward": float(ref.get("referrer_reward", 15)), "referred_reward": float(ref.get("referred_reward", 5))}
        await db.settings.update_one({"_id": s["_id"]}, {"$set": {"referral.referrer_reward": float(cfg["referrer"]),
                                                                  "referral.referred_reward": float(cfg["referred"])}})
        await db.cmtv_config.update_one({"_id": "referral_boost"}, {"$set": {"applied": True, "saved": saved,
                                                                             "applied_at": datetime.utcnow()}}, upsert=True)
        logger.info(f"Referral campaign on: ${cfg['referrer']}/${cfg['referred']} (normal {saved})")
        return "applied"
    if st != "running" and cfg.get("applied"):
        saved = cfg.get("saved") or {}
        await db.settings.update_one({"_id": s["_id"]}, {"$set": {
            "referral.referrer_reward": float(saved.get("referrer_reward", 15)),
            "referral.referred_reward": float(saved.get("referred_reward", 5))}})
        await db.cmtv_config.update_one({"_id": "referral_boost"}, {"$set": {"applied": False, "restored_at": datetime.utcnow()}})
        logger.info(f"Referral campaign off: back to {saved}")
        return "restored"
    return None


async def _loop():
    await asyncio.sleep(90)
    while True:
        try:
            await tick()
        except Exception as e:
            logger.warning(f"referral campaign loop: {e}")
        await asyncio.sleep(600)


async def startup():
    asyncio.create_task(_loop())


async def offer():
    cfg = await config()
    ref = ((await D["db"].settings.find_one({})) or {}).get("referral") or {}
    st = status(cfg)
    return {"enabled": bool(ref.get("enabled", True)), "referrer": float(ref.get("referrer_reward", 0) or 0),
            "referred": float(ref.get("referred_reward", 0) or 0), "minimum": float(ref.get("minimum_purchase", 0) or 0),
            "campaign": {"label": cfg.get("label"), "end": cfg.get("end")} if st == "running" and cfg.get("applied") else None}


def init_routes():
    admin = D["get_current_admin_user"]

    @router.get("")
    async def public_offer():
        return await offer()

    @router.get("/admin")
    async def admin_get(current_user: dict = Depends(admin)):
        cfg = await config()
        ref = ((await D["db"].settings.find_one({})) or {}).get("referral") or {}
        normal = cfg.get("saved") if cfg.get("applied") else {"referrer_reward": ref.get("referrer_reward"), "referred_reward": ref.get("referred_reward")}
        n = await D["db"].referrals.count_documents({"created_at": {"$gte": datetime.strptime(cfg["start"], "%Y-%m-%d")}}) if cfg.get("start") else 0
        return {**{k: cfg.get(k) for k in DEFAULT}, "status": status(cfg), "applied": bool(cfg.get("applied")), "normal": normal,
                "signups_since_start": n}

    @router.post("/admin")
    async def admin_set(data: dict = Body(...), current_user: dict = Depends(admin)):
        cfg = await config()
        upd = {}
        for k in ("start", "end"):
            if k in data:
                v = data.get(k) or None
                if v:
                    try:
                        datetime.strptime(v, "%Y-%m-%d")
                    except ValueError:
                        raise HTTPException(400, "Pick the dates again.")
                upd[k] = v
        for k in ("referrer", "referred"):
            if k in data:
                try:
                    v = round(float(data[k]), 2)
                except (TypeError, ValueError):
                    raise HTTPException(400, "Amounts are numbers.")
                if not 0 <= v <= 200:
                    raise HTTPException(400, "Amounts: $0 to $200.")
                upd[k] = v
        if "label" in data:
            upd["label"] = " ".join(str(data.get("label") or "").split())[:40] or "Bring a friend"
        if "enabled" in data:
            upd["enabled"] = bool(data["enabled"])
        new = {**cfg, **upd}
        if new.get("enabled") and not (new.get("start") and new.get("end")):
            raise HTTPException(400, "Pick the first and last day before switching it on.")
        if new.get("start") and new.get("end") and new["start"] > new["end"]:
            raise HTTPException(400, "The last day must be on or after the first day.")
        await D["db"].cmtv_config.update_one({"_id": "referral_boost"}, {"$set": {**upd, "updated_at": datetime.utcnow(),
                                                                                 "updated_by": current_user.get("sub")}}, upsert=True)
        if new.get("applied") and status(new) == "running" and any(k in upd for k in ("referrer", "referred")):
            # campaign already running with new amounts: write them now (the normal amounts stay saved for later)
            s = await D["db"].settings.find_one({})
            await D["db"].settings.update_one({"_id": s["_id"]}, {"$set": {"referral.referrer_reward": float(new["referrer"]),
                                                                           "referral.referred_reward": float(new["referred"])}})
        await tick()
        return await admin_get(current_user)
