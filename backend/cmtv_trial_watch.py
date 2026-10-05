"""Is the trial actually being watched? (CMTV local addition 2026-10-05, 2027 marketing plan #4 trials -> paid.)
Found: website TV trials convert ~33%, and 20 of 26 CCTV buyers paid within a day: the decision happens DURING the trial,
and someone who never gets it playing can't decide to buy. So while a CCTV / Imperium trial runs, this checks its live
connections every ~15 minutes (the same panel calls as "Test my line": cmtv_linecheck._cctv / _imperium) and remembers
whether it has ever been watched (cmtv_trial_watch {_id: service id, checks, last_check, watched_at}).
cmtv_trial_nurture uses it: 3 h check-in only for trials not watched yet (+ an Ops note to the owner: "hasn't connected,
a quick 'need a hand?' helps"); the "trial ending" email becomes "keep the same login" (watched) or "didn't get it playing?
we'll help" (never connected). Unknown (not checked yet / panel unreachable) = the normal emails.
"""
import asyncio
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)
D = {}
EVERY = timedelta(minutes=15)


def init(**deps):
    D.update(deps)


async def _live(svc):
    """Devices playing right now on this trial's line, or None if it can't be read."""
    import cmtv_linecheck as L
    login = svc.get("xtream_username") or svc.get("username")
    if not login:
        return None
    try:
        r = await (L._cctv(login) if svc.get("panel_type") == "xtream" else L._imperium(login))
    except Exception as e:
        logger.info(f"trial watch: can't read {login}: {e}")
        return None
    return int(r.get("in_use") or 0) if r.get("found") else None


async def check_round(now=None):
    now = now or datetime.utcnow()
    db = D["db"]
    n = 0
    async for svc in db.services.find({"is_trial": True, "status": "active", "expiry_date": {"$gt": now},
                                       "panel_type": {"$in": ["xtream", "aether"]}}):
        sid = str(svc["_id"])
        w = await db.cmtv_trial_watch.find_one({"_id": sid}) or {}
        if w.get("watched_at") or (w.get("last_check") and now - w["last_check"] < EVERY):
            continue
        live = await _live(svc)
        upd = {"$set": {"last_check": now, "user_id": svc.get("user_id")}, "$inc": {"checks": 1 if live is not None else 0,
                                                                                   "errors": 1 if live is None else 0}}
        if live:
            upd["$set"]["watched_at"] = now
        await db.cmtv_trial_watch.update_one({"_id": sid}, upd, upsert=True)
        n += 1
    return n


async def watched(sid):
    """True = watched at least once; False = checked and never seen playing; None = don't know (no successful check)."""
    w = await D["db"].cmtv_trial_watch.find_one({"_id": str(sid)}) or {}
    if w.get("watched_at"):
        return True
    return False if int(w.get("checks") or 0) > 0 else None


async def alert_owner(user, svc, fam):
    """Ops (Billing): a trial that hasn't connected 3 hours in."""
    try:
        import cmtv_notify
        login = svc.get("xtream_username") or svc.get("username") or ""
        name = user.get("name") or ""
        await cmtv_notify.ops(f"👀 Trial not playing yet: {name} <{user.get('email', '')}> started a {fam} trial about 3 hours ago "
                              f"and hasn't connected (line {login}). A quick 'need a hand?' from you is the best thing right now.",
                              "billing", await D["get_settings"]())
    except Exception as e:
        logger.warning(f"trial watch alert failed: {e}")


async def after_item(order_id, order, item, product):
    """Called by provision_order_services after each item (2026-10-05, tested on both live panels the same day):
    - a TRIAL item: make sure the line it made is marked is_trial (the CCTV path never set it, so CCTV trials got no trial
      messages and weren't watched);
    - a PAID item that extended a trial line ("keep my trial login"): the panel has already turned it into a paid line with
      the plan's devices and end date (CCTV and Imperium both do), so billing's record follows: is_trial False, the paid
      product, its devices. Only when the line now runs 20+ days out (the extension worked)."""
    db = D["db"]
    uid = order.get("user_id")
    if product.get("is_trial"):
        await db.services.update_many({"order_id": order_id, "user_id": uid, "is_trial": {"$ne": True},
                                       "panel_type": {"$in": ["xtream", "aether"]}}, {"$set": {"is_trial": True}})
        return
    rid = item.get("renewal_service_id")
    if not rid or item.get("action_type") not in ("renew", "extend"):
        return
    from bson import ObjectId
    if not ObjectId.is_valid(str(rid)):
        return
    svc = await db.services.find_one({"_id": ObjectId(str(rid)), "user_id": uid})
    if not svc or not svc.get("is_trial") or not svc.get("expiry_date") or svc["expiry_date"] < datetime.utcnow() + timedelta(days=20):
        return
    upd = {"is_trial": False, "product_id": str(product.get("_id") or item.get("product_id")),
           "product_name": product.get("name") or item.get("product_name"), "status": "active",
           "cmtv_trial_converted": {"order_id": order_id, "at": datetime.utcnow()}}
    if product.get("max_connections"):
        upd["max_connections"] = int(product["max_connections"])
    await db.services.update_one({"_id": svc["_id"]}, {"$set": upd})
    logger.info(f"Trial line {svc.get('xtream_username') or svc.get('username')} kept its login: now {upd['product_name']}")


async def _loop():
    await asyncio.sleep(150)
    while True:
        try:
            await check_round()
        except Exception as e:
            logger.warning(f"trial watch loop: {e}")
        await asyncio.sleep(300)


async def startup():
    asyncio.create_task(_loop())
