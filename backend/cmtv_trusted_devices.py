"""Admin 2FA: "Remember this device for 30 days" (CMTV local addition 2026-10-01, the user's request).

At the 2FA step an admin can tick "Remember this device". Billing then hands that browser a random device key (shown once,
kept in the browser's localStorage) and stores only its SHA-256 in `cmtv_trusted_devices`. Signing in later from that browser
with the right email + password + key skips the code. The password is always still needed.

A key stops working when: 30 days pass; it's removed in Admin > Settings (2FA box: "Remembered devices"); the admin's password
changes or 2FA is set up again or turned off (each key records a fingerprint of the password hash and the 2FA secret and
must still match). Keys are never deleted, only marked revoked (kept for the record).
"""
import hashlib
import logging
import secrets
from datetime import datetime, timedelta

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/cmtv/trusted-devices", tags=["cmtv-trusted-devices"])
D = {}
DAYS = 30
MAX_PER_USER = 10


def _h(v) -> str:
    return hashlib.sha256(str(v or "").encode()).hexdigest()


def _fingerprint(user: dict) -> str:
    """Changes when the password or the 2FA secret changes (so old keys stop working)"""
    return _h(f"{user.get('password', '')}|{user.get('totp_secret', '')}")[:32]


async def is_trusted(db, user: dict, token: str) -> bool:
    if not token or len(token) < 20 or len(token) > 200:
        return False
    now = datetime.utcnow()
    doc = await db.cmtv_trusted_devices.find_one({"user_id": str(user["_id"]), "token_hash": _h(token), "revoked": {"$ne": True},
                                                  "expires_at": {"$gt": now}})
    if not doc or doc.get("fingerprint") != _fingerprint(user):
        return False
    await db.cmtv_trusted_devices.update_one({"_id": doc["_id"]}, {"$set": {"last_used_at": now}, "$inc": {"uses": 1}})
    logger.info(f"2FA skipped for {user.get('email')}: remembered device ({doc.get('label') or 'browser'})")
    return True


async def issue(db, user: dict, label: str = "") -> str:
    """A new device key for this admin (the newest MAX_PER_USER stay usable)"""
    token = secrets.token_urlsafe(32)
    now = datetime.utcnow()
    await db.cmtv_trusted_devices.insert_one({
        "user_id": str(user["_id"]), "email": user.get("email"), "token_hash": _h(token),
        "fingerprint": _fingerprint(user), "label": str(label or "").strip()[:80] or "Browser",
        "created_at": now, "expires_at": now + timedelta(days=DAYS), "last_used_at": now, "uses": 0, "revoked": False})
    old = [d["_id"] async for d in db.cmtv_trusted_devices.find({"user_id": str(user["_id"]), "revoked": {"$ne": True}})
           .sort("created_at", -1).skip(MAX_PER_USER)]
    if old:
        await db.cmtv_trusted_devices.update_many({"_id": {"$in": old}}, {"$set": {"revoked": True, "revoked_at": now,
                                                                                   "revoked_why": "too many devices"}})
    logger.info(f"2FA: {user.get('email')} chose to remember this device for {DAYS} days")
    return token


async def revoke_all(db, user_id: str, why: str):
    await db.cmtv_trusted_devices.update_many({"user_id": str(user_id), "revoked": {"$ne": True}},
                                              {"$set": {"revoked": True, "revoked_at": datetime.utcnow(), "revoked_why": why}})


def init(**deps):
    D.update(deps)


def init_routes():
    admin = D["get_current_admin_user"]

    @router.get("")
    async def mine(current_user: dict = Depends(admin)):
        now = datetime.utcnow()
        out = []
        async for d in D["db"].cmtv_trusted_devices.find({"user_id": current_user["sub"], "revoked": {"$ne": True},
                                                          "expires_at": {"$gt": now}}).sort("last_used_at", -1):
            out.append({"id": str(d["_id"]), "label": d.get("label"), "created_at": d.get("created_at"),
                        "last_used_at": d.get("last_used_at"), "expires_at": d.get("expires_at"), "uses": d.get("uses", 0)})
        return {"devices": out, "days": DAYS}

    @router.post("/{device_id}/revoke")
    async def revoke(device_id: str, current_user: dict = Depends(admin)):
        res = await D["db"].cmtv_trusted_devices.update_one(
            {"_id": ObjectId(device_id) if ObjectId.is_valid(device_id) else None, "user_id": current_user["sub"]},
            {"$set": {"revoked": True, "revoked_at": datetime.utcnow(), "revoked_why": "removed by the admin"}})
        if not res.matched_count:
            raise HTTPException(status_code=404, detail="Device not found")
        return {"ok": True}

    @router.post("/revoke-all")
    async def revoke_mine(current_user: dict = Depends(admin)):
        await revoke_all(D["db"], current_user["sub"], "removed by the admin (all)")
        return {"ok": True}
