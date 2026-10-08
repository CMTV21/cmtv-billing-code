"""Keep billing's copy of each customer line in step with the panels (CMTV local addition 2026-10-08, owner: "confirm all
customer details match"; the audit found what the developer's hourly sync misses).
Called at the end of server.py sync_services_expiry_from_imported_users (hourly, after the panel sync), which already
copies end date / status / devices. This adds:
1. Passwords: when the panel's password differs from the one the customer's dashboard shows (xtream_password, then
   password), billing's copy is set to the panel's (the one that works). The panel sync never copied password changes.
2. Live lines with no billing record: a line that is live on a panel and linked to a customer, but billing has no record of
   that login on that server (e.g. the customer moved CCTV -> Imperium keeping the login: the panel sync sees the line is
   already linked and stops early, so My Services kept only the old cancelled record). The record is added the same way the
   panel sync makes one for a new customer; any old record stays as history. Ops Billing note.
Safety: only panel records refreshed in the last day (last_synced), only customer accounts (role user, not demo), never
resellers, nothing deleted. A reseller's own lines and lines with no linked customer are left to the panel sync.
Re-check any time: /root/cmtv-scripts/audit/audit.py
"""
import logging
import re
from datetime import datetime, timedelta

from bson import ObjectId

logger = logging.getLogger(__name__)
FRESH = timedelta(days=1)
SKIP = ["duplicate", "failed", "removed"]


def _dt(v):
    if isinstance(v, str) and v.strip():
        try:
            return datetime.fromisoformat(v.strip().replace("Z", "").replace(" ", "T")[:19])
        except ValueError:
            return None
    return v if isinstance(v, datetime) else None


def _rx(s):
    return {"$regex": f"^{re.escape(s)}$", "$options": "i"}


def _live(iu, now):
    end = _dt(iu.get("expiry_date"))
    return str(iu.get("status") or "").lower() == "active" and (end is None or end > now)


def _fresh(iu, now):
    seen = _dt(iu.get("last_synced"))
    return bool(seen and seen > now - FRESH)


async def _streaming_url(db, iu):
    t = await db.services.find_one({"panel_type": iu.get("panel_type"), "panel_index": iu.get("panel_index", 0),
                                    "streaming_url": {"$nin": ["", None]}, "status": "active"}, {"streaming_url": 1})
    return (t or {}).get("streaming_url", "")


async def _new_record(db, iu, now):
    pt, pw = iu.get("panel_type"), iu.get("password")
    doc = {"user_id": str(iu["user_id"]), "product_id": "", "product_name": f"{iu.get('panel_name')} - Subscriber",
           "xtream_username": iu["username"], "xtream_password": pw, "username": iu["username"], "password": pw,
           "panel_type": pt, "panel_name": iu.get("panel_name"), "panel_index": iu.get("panel_index", 0), "account_type": "subscriber",
           "max_connections": int(iu.get("max_connections") or 1), "streaming_url": await _streaming_url(db, iu),
           "expiry_date": _dt(iu.get("expiry_date")), "status": "active", "created_at": now, "created_via": "cmtv_line_sync",
           "cmtv_note": "Added by the hourly line check: live on the panel, billing had no record of it on this server."}
    if pt == "aether":
        line_id = iu.get("aether_line_id") or iu.get("xtream_user_id")
        if not line_id:
            return None
        doc.update(aether_line_id=line_id, aether_package_id=iu.get("aether_package_id"))
        pkg = str(iu.get("aether_package_id") or "")
        if pkg:
            p = await db.products.find_one({"panel_type": "aether", "account_type": "subscriber",
                                            "xtream_package_id": {"$in": [pkg] + ([int(pkg)] if pkg.isdigit() else [])}})
            if p:
                doc.update(product_id=str(p["_id"]), product_name=p.get("name"))
    elif iu.get("xtream_user_id"):
        doc["dedicatedip"] = iu["xtream_user_id"]
    return doc


async def reconcile(db, get_settings=None, now=None, dry=False):
    """One pass. Returns {"passwords": n, "added": [logins]}. dry=True: work it out, write nothing."""
    now = now or datetime.utcnow()
    users = {}

    async def customer(uid):
        if uid not in users:
            u = await db.users.find_one({"_id": ObjectId(uid)}, {"role": 1, "cmtv_demo": 1, "email": 1}) if ObjectId.is_valid(uid) else None
            users[uid] = u if u and u.get("role") == "user" and not u.get("cmtv_demo") else None
        return users[uid]

    pw_fixed, added = 0, []
    async for iu in db.imported_users.find({"account_type": {"$ne": "reseller"}, "panel_type": {"$in": ["xtream", "aether"]}}):
        if not iu.get("username") or not _fresh(iu, now) or not _live(iu, now):
            continue
        uid = str(iu.get("user_id") or "")
        if not uid or not await customer(uid):
            continue
        login = iu["username"]
        recs = [s async for s in db.services.find({"$or": [{"xtream_username": _rx(login)}, {"username": _rx(login)}],
                                                   "panel_type": iu.get("panel_type"), "status": {"$nin": SKIP}})]
        if not recs:
            if await db.services.find_one({"$or": [{"xtream_username": _rx(login)}, {"username": _rx(login)}],
                                           "account_type": "reseller"}):
                continue
            doc = await _new_record(db, iu, now)
            if doc:
                if dry:
                    added.append(f"{login} ({iu.get('panel_name')}, to {str(doc['expiry_date'])[:10]})")
                    continue
                await db.services.insert_one(doc)
                await db.lifecycle_logs.insert_one({"service_id": None, "user_id": uid, "action": "reactivate", "actor": "system",
                                                    "reason": f"Line {login} is live on {iu.get('panel_name')}: billing record added",
                                                    "created_at": now})
                added.append(f"{login} ({iu.get('panel_name')}, to {str(doc['expiry_date'])[:10]})")
            continue
        pw = iu.get("password")
        if not pw:
            continue
        for s in recs:
            if str(s.get("user_id")) != uid:
                continue   # owned by another account: needs a person (audit.py lists it)
            shown = s.get("xtream_password") or s.get("password")
            if shown != pw:
                upd = {"xtream_password": pw, "cmtv_password_synced_at": now}
                if s.get("password"):
                    upd["password"] = pw
                if not dry:
                    await db.services.update_one({"_id": s["_id"]}, {"$set": upd})
                pw_fixed += 1
    if dry:
        return {"passwords": pw_fixed, "added": added}
    if pw_fixed or added:
        logger.info(f"CMTV line sync: {pw_fixed} password(s) from the panel, {len(added)} record(s) added")
    if added:
        try:
            import cmtv_notify
            settings = await get_settings() if get_settings else None
            await cmtv_notify.ops("🔗 <b>Line check</b>: billing had no record of these live lines, now added (old records kept):\n"
                                  + "\n".join(f"• {a}" for a in added), "billing", settings, silent=True)
        except Exception as e:
            logger.warning(f"CMTV line sync: Ops note failed: {e}")
    return {"passwords": pw_fixed, "added": added}
