"""Panel-only customers finishing their website account (CMTV local addition 2026-09-28).
Customers you set up by hand only exist in billing as "<line>@panel.local" placeholder accounts made by the panel sync.
They can already sign in with their TV line's username + password (server.py login; now case-insensitive, and the
current line password works even if it changed since the account was made). This finishes the job:
  POST /api/cmtv/claim/link {email, new_password, name?, existing_password?}   (signed in, placeholder accounts only)
    - email free: it becomes the account's email (verification email sent), new_password becomes the website password.
    - email already has a customer account: {needs_existing_password} first; with that account's password, the
      placeholder is JOINED into it (every reference to the placeholder in every collection moves over; the placeholder
      is retired as role "merged", never deleted; a copy is kept in cmtv_account_merges) and a sign-in for it is returned.
Ops Billing gets a note either way. Wrong existing passwords: 5 per placeholder per hour.
2026-10-02 (the owner): REWARD of $5 account credit, once per TV line (placeholder), for lines finished from REWARD_SINCE
on: a new email gets it once it's confirmed (reward_loop checks every 10 min: cmtv_claim_reward_pending + email_verified),
joining an existing account gets it right away. Log cmtv_claim_rewards {_id: placeholder id, user_id, amount, at}.
Switch: cmtv_config {_id: "claim_reward", enabled (default true), amount}.
"""
import asyncio
import hmac
import logging
import re
import secrets
from datetime import datetime, timedelta

from bson import ObjectId
from fastapi import APIRouter, Body, Depends, HTTPException

log = logging.getLogger("server")
router = APIRouter(prefix="/api/cmtv/claim", tags=["cmtv-claim"])
D = {}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
REWARD_SINCE = datetime(2026, 10, 2)
REWARD_DEFAULT = 5.0


def init(**deps):
    D.update(deps)


def is_placeholder(u: dict) -> bool:
    return bool(u) and u.get("role") == "user" and str(u.get("email") or "").lower().endswith("@panel.local")


def _oid(v):
    return ObjectId(v) if ObjectId.is_valid(str(v)) else None


def _mask(email):
    name, _, dom = email.partition("@")
    return (name[:2] + "***@" + dom) if dom else email


async def line_password_ok(user: dict, password: str) -> bool:
    """True if `password` is the current password of one of this account's TV lines (panel sync or service record)."""
    uid = str(user["_id"])
    db = D["db"]
    async for iu in db.imported_users.find({"user_id": uid}, {"password": 1}):
        if iu.get("password") and hmac.compare_digest(str(iu["password"]), password):
            return True
    async for s in db.services.find({"user_id": uid, "status": {"$ne": "duplicate"}}, {"xtream_password": 1, "password": 1}):
        for k in ("xtream_password", "password"):
            if s.get(k) and hmac.compare_digest(str(s[k]), password):
                return True
    return False


def user_payload(u: dict) -> dict:
    """Same shape as the login response's "user"."""
    has_real = bool(u.get("email")) and not str(u["email"]).lower().endswith("@panel.local")
    return {"id": str(u["_id"]), "email": u.get("email", ""), "name": u.get("name") or u.get("panel_username", ""),
            "role": u.get("role", "user"), "email_verified": u.get("email_verified", False),
            "totp_enabled": u.get("totp_enabled", False), "panel_username": u.get("panel_username", ""),
            "needs_email_link": not has_real, "permissions": u.get("permissions", [])}


async def move_everything(from_id: str, to_id: str) -> dict:
    """Point every top-level reference to from_id (string or ObjectId) at to_id, in every collection except users."""
    db = D["db"]
    moved = {}
    for coll in await db.list_collection_names():
        if coll == "users" or coll.startswith("system."):
            continue
        fields = set()
        async for doc in db[coll].find({}).limit(200):
            fields.update(k for k, v in doc.items() if k != "_id" and isinstance(v, (str, ObjectId)))
        for f in fields:
            r = await db[coll].update_many({f: {"$in": [from_id, _oid(from_id)]}}, {"$set": {f: to_id}})
            if r.modified_count:
                moved[f"{coll}.{f}"] = r.modified_count
    return moved


async def _ops(text):
    try:
        import cmtv_notify
        await cmtv_notify.ops(text, "billing", await D["get_settings"]())
    except Exception as e:
        log.warning(f"claim ops note failed: {e}")


async def _send_verification(user: dict, email: str):
    token = secrets.token_urlsafe(32)
    await D["db"].users.update_one({"_id": user["_id"]}, {"$set": {"verification_token": token}})
    try:
        es = await D["get_email_service"]()
        if es:
            url = f"{D['site_url']}/api/verify-email?redirect=true&token={token}"
            await es.send_email_verification(email, user.get("name") or user.get("panel_username") or "Customer", url,
                                             customer_id=str(user["_id"]))
    except Exception as e:
        log.warning(f"claim: verification email failed: {e}")


async def reward_config():
    doc = await D["db"].cmtv_config.find_one({"_id": "claim_reward"}) or {}
    return bool(doc.get("enabled", True)), float(doc.get("amount") or REWARD_DEFAULT)


async def give_reward(placeholder_id: str, to_user_id: str) -> bool:
    """$5 once per TV line; True if credited now."""
    db = D["db"]
    on, amount = await reward_config()
    if not on or await db.cmtv_claim_rewards.find_one({"_id": placeholder_id}):
        return False
    await db.cmtv_claim_rewards.insert_one({"_id": placeholder_id, "user_id": to_user_id, "amount": amount, "at": datetime.utcnow()})
    try:
        await D["credit_service"].add_credits(user_id=to_user_id, amount=amount, transaction_type="claim_reward",
                                              description="Thanks for finishing your CMTV account", created_by="claim",
                                              bypass_enabled_check=True)
    except Exception as e:
        await db.cmtv_claim_rewards.delete_one({"_id": placeholder_id})   # try again next time
        log.error(f"claim reward for {to_user_id} failed: {e}")
        return False
    await db.users.update_one({"_id": _oid(to_user_id)}, {"$unset": {"cmtv_claim_reward_pending": ""}})
    return True


async def reward_loop():
    await asyncio.sleep(120)
    while True:
        try:
            async for u in D["db"].users.find({"cmtv_claim_reward_pending": True, "email_verified": True}, {"_id": 1, "email": 1}):
                if await give_reward(str(u["_id"]), str(u["_id"])):
                    await _ops(f"💵 $5 claim credit added: {u.get('email')} confirmed their email.")
        except Exception as e:
            log.warning(f"claim reward loop: {e}")
        await asyncio.sleep(600)


def start():
    if not D.get("task"):
        D["task"] = asyncio.get_event_loop().create_task(reward_loop())


def init_routes():
    current = D["get_current_user"]

    @router.get("/offer")
    async def offer():   # 2026-10-02: public: is the claim credit on, and how much (the sign-in / finish pages show it)
        on, amount = await reward_config()
        return {"enabled": on, "amount": amount}

    @router.post("/link")
    async def link(body: dict = Body(...), current_user: dict = Depends(current)):
        db = D["db"]
        me = await db.users.find_one({"_id": _oid(current_user["sub"])})
        if not is_placeholder(me):
            raise HTTPException(400, "Your account already has an email address.")
        email = str(body.get("email") or "").strip().lower()
        if not EMAIL_RE.match(email) or email.endswith("@panel.local"):
            raise HTTPException(400, "Enter a valid email address.")
        other = await D["find_user_by_email"](email)
        if other and str(other["_id"]) != str(me["_id"]):
            if other.get("role") != "user":
                raise HTTPException(400, "That email can't be used for a customer account. Please message us.")
            existing_pw = str(body.get("existing_password") or "")
            if not existing_pw:
                return {"needs_existing_password": True, "email": _mask(email)}
            since = datetime.utcnow() - timedelta(hours=1)
            if await db.cmtv_claim_attempts.count_documents({"user_id": str(me["_id"]), "at": {"$gte": since}}) >= 5:
                raise HTTPException(429, "Too many tries. Please wait an hour or message us.")
            if not D["verify_password"](existing_pw, other.get("password") or ""):
                await db.cmtv_claim_attempts.insert_one({"user_id": str(me["_id"]), "at": datetime.utcnow()})
                raise HTTPException(400, "That isn't the password for that account. Try again, or use \"Forgot password\" on the sign-in page.")
            # join the placeholder into the existing account
            me_id, keep_id = str(me["_id"]), str(other["_id"])
            moved = await move_everything(me_id, keep_id)
            now = datetime.utcnow()
            await db.cmtv_account_merges.insert_one({"keep": keep_id, "retired": me_id, "retired_doc": me, "moved": moved,
                                                     "at": now, "via": "claim"})
            await db.users.update_one({"_id": me["_id"]}, {
                "$set": {"email": f"merged-{me_id}@panel.local", "role": "merged",
                         "password": D["hash_password"](secrets.token_urlsafe(24)), "merged_into": keep_id, "merged_at": now,
                         "merged_original_email": me.get("email"), "merged_original_panel_username": me.get("panel_username")},
                "$unset": {"panel_username": ""}})
            if me.get("panel_username") and not other.get("panel_username"):
                await db.users.update_one({"_id": other["_id"]}, {"$set": {"panel_username": me["panel_username"]}})
            other = await db.users.find_one({"_id": other["_id"]})
            rewarded = await give_reward(me_id, keep_id)   # 2026-10-02
            await _ops(("💵 " if rewarded else "") + f"🔗 Customer joined their accounts: TV line {me.get('panel_username')} is now on {other.get('email')} "
                       f"({other.get('name') or ''}).")
            token = D["create_access_token"]({"sub": keep_id, "email": other["email"], "role": "user"})
            return {"joined": True, "rewarded": rewarded, "access_token": token, "user": user_payload(other)}

        new_pw = str(body.get("new_password") or "")
        if len(new_pw) < 6:
            raise HTTPException(400, "Choose a website password of at least 6 characters.")
        name = str(body.get("name") or "").strip()[:80]
        upd = {"email": email, "email_verified": False, "password": D["hash_password"](new_pw),
               "cmtv_claimed_at": datetime.utcnow(), "cmtv_placeholder_email": me.get("email")}
        if (await reward_config())[0] and not await db.cmtv_claim_rewards.find_one({"_id": str(me["_id"])}):
            upd["cmtv_claim_reward_pending"] = True   # 2026-10-02: $5 once the email is confirmed
        if name:
            upd["name"] = name
        await db.users.update_one({"_id": me["_id"]}, {"$set": upd})
        me = await db.users.find_one({"_id": me["_id"]})
        await _send_verification(me, email)
        await _ops(f"✅ Customer finished their website account: TV line {me.get('panel_username')} -> {email}"
                   + (f" ({name})" if name else "") + ".")
        token = D["create_access_token"]({"sub": str(me["_id"]), "email": email, "role": "user"})
        return {"linked": True, "access_token": token, "user": user_payload(me)}
