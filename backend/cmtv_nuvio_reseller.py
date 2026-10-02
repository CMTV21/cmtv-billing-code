"""Nuvio for resellers (CMTV local addition 2026-10-01, the owner's decisions).

Approved resellers (users.cmtv_nuvio_reseller, switched on in Admin > Resellers) make and run Nuvio accounts on CMTV's own
Nuvio server from Reseller tools > Nuvio, paid with Nuvio credits held in billing:
  1 credit = one account for one month with 2 devices; +1 credit a month for 3-4 devices; +1 credit a month for 4K.
  Credits: $1.00 each (cmtv_reseller_credits tiers "nuvio"), bought through the normal credit slider/checkout
  (product with cmtv_nuvio_credits: true); provision_order_services calls provision_credits().
  Free trials: 48 h, HD, 2 devices, at most 10 per 7 days. Resellers may delete their accounts. No caps.
Accounts carry reseller_id (owner), pool ("retail" = CMTV's current Premiumize add-ons, "reseller" = the reseller
Premiumize set; cmtv_nuvio.audience), uhd, trial. A reseller starts on the retail pool; their first PAID credit purchase
moves them (and their accounts) to the reseller pool when reseller add-ons exist (else an Ops note asks the owner to add them).
Collections: cmtv_nuvio_credits {_id: user id, balance}, cmtv_nuvio_credit_log (every change, never edited).
"""
import logging
import math
import re
import secrets
from datetime import date, datetime, timedelta

from bson import ObjectId
from dateutil.relativedelta import relativedelta
from fastapi import APIRouter, Body, Depends, HTTPException

import cmtv_nuvio as N

log = logging.getLogger("server")
router = APIRouter(prefix="/api/cmtv/nuvio-reseller", tags=["cmtv-nuvio-reseller"])
D = {}
DEFAULTS = {"trial_days": 2, "trials_per_week": 10, "free_credits": 10}
MONTHS = (1, 3, 6, 12)


def init(**deps):
    D.update(deps)
    try:   # called from server.py's async startup: start the hourly Premiumize usage watch
        import asyncio
        asyncio.get_event_loop().create_task(_premiumize_loop())
    except Exception as e:
        log.warning(f"Premiumize watch not started: {e}")


# ---------------------------------------------------------------- Premiumize usage watch (2026-10-01)
# Instead of caps (the owner): billing reads each Premiumize account's fair-use use from Premiumize's official API
# (GET https://www.premiumize.me/api/account/info?apikey=...: limit_used 0..1, premium_until) hourly and posts a silent
# Ops note at 75% and 90% (once each per cycle; a cycle restarts when use drops back under 50%).
# Keys: cmtv_config {_id: "premiumize"} {accounts: {retail|reseller: {key, label}}}; never sent back whole.
PM_URL = "https://www.premiumize.me/api/account/info"
PM_LEVELS = (0.75, 0.90)


async def premiumize_info(key: str) -> dict:
    import httpx
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(PM_URL, params={"apikey": key})
    d = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if d.get("status") != "success":
        raise ValueError(d.get("message") or f"Premiumize said {r.status_code}")
    return {"limit_used": float(d.get("limit_used") or 0), "premium_until": d.get("premium_until"),
            "space_used": d.get("space_used")}


async def premiumize_check() -> dict:
    cfg = await _db().cmtv_config.find_one({"_id": "premiumize"}) or {}
    out = {}
    for name, a in (cfg.get("accounts") or {}).items():
        if not a.get("key"):
            continue
        try:
            info = await premiumize_info(a["key"])
        except Exception as e:
            out[name] = {"error": str(e)[:120]}
            await _db().cmtv_config.update_one({"_id": "premiumize"}, {"$set": {f"accounts.{name}.last_error": str(e)[:120],
                                                                               f"accounts.{name}.checked_at": datetime.utcnow()}})
            continue
        used, alerted = info["limit_used"], list(a.get("alerted") or [])
        if used < 0.5:
            alerted = []   # a new fair-use period
        for lvl in PM_LEVELS:
            if used >= lvl and lvl not in alerted:
                alerted.append(lvl)
                try:
                    import cmtv_notify
                    await cmtv_notify.ops(f"📊 Premiumize ({a.get('label') or name}): <b>{used:.0%}</b> of the fair-use allowance used. "
                                          + ("Consider buying bonus points soon." if lvl < 0.9 else "Buy bonus points now, or streams will slow down."),
                                          "critical" if lvl >= 0.9 else "billing", silent=True)
                except Exception as e:
                    log.warning(f"Premiumize alert not sent: {e}")
        await _db().cmtv_config.update_one({"_id": "premiumize"}, {"$set": {
            f"accounts.{name}.limit_used": used, f"accounts.{name}.premium_until": info["premium_until"],
            f"accounts.{name}.checked_at": datetime.utcnow(), f"accounts.{name}.alerted": alerted,
            f"accounts.{name}.last_error": None}})
        out[name] = {"limit_used": used}
    return out


async def _premiumize_loop():
    import asyncio
    await asyncio.sleep(180)
    while True:
        try:
            await premiumize_check()
        except Exception as e:
            log.warning(f"Premiumize check failed: {e}")
        await asyncio.sleep(3600)


def _db():
    return D["db"]


def _oid(v):
    return ObjectId(v) if ObjectId.is_valid(str(v)) else None


async def settings() -> dict:
    doc = await _db().cmtv_config.find_one({"_id": "nuvio_reseller"}) or {}
    return {**DEFAULTS, **{k: v for k, v in doc.items() if k in DEFAULTS}}


UHD_EXTRA = 2   # CMTV local change 2026-10-02: 4K = 3 credits a month in total (was +1), the owner's price


def per_month(devices: int, uhd: bool) -> int:
    return 1 + (1 if devices > 2 else 0) + (UHD_EXTRA if uhd else 0)


def months_left(expires: str) -> int:
    try:
        days = (datetime.strptime(expires, "%Y-%m-%d").date() - date.today()).days
    except (TypeError, ValueError):
        return 0
    return max(0, math.ceil(days / 30.44))


# ---------------------------------------------------------------- balance (atomic, logged)
async def balance(uid: str) -> int:
    doc = await _db().cmtv_nuvio_credits.find_one({"_id": uid}) or {}
    return int(doc.get("balance") or 0)


async def change(uid: str, delta: int, kind: str, reason: str, by: str = "", account: str = "", order_id: str = "") -> int:
    """delta < 0 only succeeds if the balance covers it (never below 0, safe with two clicks at once)."""
    if delta < 0:
        doc = await _db().cmtv_nuvio_credits.find_one_and_update(
            {"_id": uid, "balance": {"$gte": -delta}}, {"$inc": {"balance": delta}, "$set": {"updated_at": datetime.utcnow()}},
            return_document=True)
        if not doc:
            raise HTTPException(402, f"Not enough Nuvio credits: this needs {-delta}, you have {await balance(uid)}.")
    else:
        doc = await _db().cmtv_nuvio_credits.find_one_and_update(
            {"_id": uid}, {"$inc": {"balance": delta}, "$set": {"updated_at": datetime.utcnow()}}, upsert=True, return_document=True)
    await _db().cmtv_nuvio_credit_log.insert_one({"user_id": uid, "delta": delta, "kind": kind, "reason": reason, "by": by,
                                                  "account": account, "order_id": order_id, "balance_after": doc["balance"],
                                                  "at": datetime.utcnow()})
    return int(doc["balance"])


async def _is_reseller(uid: str) -> bool:
    u = await _db().users.find_one({"_id": _oid(uid)}, {"cmtv_nuvio_reseller": 1})
    return bool((u or {}).get("cmtv_nuvio_reseller"))


async def _pool(uid: str) -> str:
    u = await _db().users.find_one({"_id": _oid(uid)}, {"cmtv_nuvio_pool": 1}) or {}
    return u.get("cmtv_nuvio_pool") or "retail"


async def _reseller_addons_ready() -> bool:
    return any(a.get("enabled", True) and a.get("audience") == "reseller" for a in await N.addon_config())


async def set_pool(uid: str, pool: str, by: str) -> int:
    """Move a reseller (and every account they own) to the retail or reseller add-on set"""
    await _db().users.update_one({"_id": _oid(uid)}, {"$set": {"cmtv_nuvio_pool": pool, "cmtv_nuvio_pool_at": datetime.utcnow()}})
    n = 0
    async for acc in _db().cmtv_nuvio_accounts.find({"reseller_id": uid, "deleted": {"$ne": True}}):
        await _db().cmtv_nuvio_accounts.update_one({"_id": acc["_id"]}, {"$set": {"pool": pool}})
        N._cache_drop(acc["_id"])
        try:
            await N.push_addons({**acc, "pool": pool})
            n += 1
        except Exception as e:
            log.warning(f"Nuvio reseller pool move {acc['_id']}: {e}")
    log.info(f"Nuvio reseller {uid} -> pool {pool} by {by} ({n} accounts)")
    return n


async def ensure_service(uid: str, user: dict, order_id=None, product_id="", balance_now=None):
    """The reseller's "Nuvio reseller" service in billing: opens Reseller tools / the Reseller tab / brand settings for a
    Nuvio-only reseller, shows the balance on the dashboard, and (with order_id) lets the order check see a purchase."""
    now = datetime.utcnow()
    bal = await balance(uid) if balance_now is None else balance_now
    st = {"product_name": "Nuvio reseller credits", "account_type": "reseller", "panel_type": "manual",
          "panel_name": "CMTV Nuvio server", "reseller_credits": bal, "status": "active", "expiry_date": None, "updated_at": now}
    if order_id:
        st["order_id"] = order_id
    if product_id:
        st["product_id"] = product_id
    await _db().services.update_one(
        {"user_id": uid, "cockpit_module": "nuvio_reseller"},
        {"$set": st, "$setOnInsert": {"user_id": uid, "cockpit_module": "nuvio_reseller", "start_date": now, "created_at": now,
                                      "username": (user or {}).get("email") or uid}}, upsert=True)


# ---------------------------------------------------------------- buying credits (from provision_order_services)
async def provision_credits(order_id: str, order: dict, user: dict, item: dict, product: dict, email_service=None):
    uid = str(order["user_id"])
    credits = int(float(item.get("credits") or product.get("reseller_credits") or 0))
    if credits <= 0:
        raise ValueError("no credit amount on the order item")
    if await _db().cmtv_nuvio_credit_log.find_one({"order_id": order_id, "kind": "purchase"}):
        log.info(f"Nuvio credits for order {order_id} already added")
        return
    bal = await change(uid, credits, "purchase", f"Bought {credits} credits", by="checkout", order_id=order_id)
    await ensure_service(uid, user, order_id=order_id, product_id=str(product.get("_id", "")), balance_now=bal)
    # the owner's rule: on CMTV's own Premiumize until the reseller pays for credits, then the reseller set
    if await _pool(uid) != "reseller":
        if await _reseller_addons_ready():
            await set_pool(uid, "reseller", "first paid credits")
        else:
            try:
                import cmtv_notify
                await cmtv_notify.ops(f"🎬 Nuvio reseller <b>{user.get('name') or user.get('email')}</b> bought {credits} credits. "
                                      "Their accounts still use your own Premiumize add-ons: add the reseller add-ons "
                                      "(Admin > Nuvio > Add-ons, For: Resellers' customers), then switch them in Admin > Resellers.",
                                      "billing", silent=True)
            except Exception as e:
                log.warning(f"Nuvio reseller ops note failed: {e}")
    if email_service and not str(user.get("email") or "").endswith("@panel.local"):
        try:
            await email_service.send_credits_added(customer_email=user["email"], customer_name=user.get("name", ""),
                                                   username="Nuvio (Reseller tools > Nuvio)", credits=credits, customer_id=uid)
        except Exception as e:
            log.warning(f"Nuvio credits email failed: {e}")


# ---------------------------------------------------------------- routes
def _new_expiry(current: str, months: int) -> str:
    if months not in MONTHS:
        raise HTTPException(400, "Choose 1, 3, 6 or 12 months")
    try:
        base = max(date.today(), datetime.strptime(current or "", "%Y-%m-%d").date())
    except ValueError:
        base = date.today()
    return (base + relativedelta(months=months)).strftime("%Y-%m-%d")


def _clean_password(p: str) -> str:
    p = (p or "").strip() or N._rand(N._PASS_CHARS, 10)
    if len(p) < 4:
        raise HTTPException(400, "Password: at least 4 characters")
    return p


def _row(acc: dict, summary: dict) -> dict:
    sm = summary.get(acc.get("nuvio_id"), {})
    return {"username": acc["_id"], "login": N.shown_login(acc), "password": acc.get("password", ""), "expires": acc.get("expires"),
            "status": acc.get("status", "active"), "live": N.is_live(acc), "trial": bool(acc.get("trial")), "uhd": N.wants_4k(acc),
            "max_devices": acc.get("max_devices") or 2, "devices": sm.get("devices", 0), "last_seen": sm.get("last_seen"),
            "notes": acc.get("notes", ""), "per_month": per_month(acc.get("max_devices") or 2, N.wants_4k(acc))}


def init_routes():
    current = D["get_current_user"]
    admin = D["get_current_admin_user"]

    async def me(current_user: dict = Depends(current)) -> str:
        uid = str(current_user.get("sub") or current_user.get("_id") or current_user.get("id"))
        if not await _is_reseller(uid):
            raise HTTPException(403, "Nuvio reselling isn't switched on for your account. Message us to get started.")
        return uid

    async def own(uid: str, username: str) -> dict:
        acc = await N.get_account(username)
        if not acc or str(acc.get("reseller_id")) != uid:
            raise HTTPException(404, "Not one of your accounts")
        return acc

    async def trials_this_week(uid: str) -> int:
        return await _db().cmtv_nuvio_credit_log.count_documents({"user_id": uid, "kind": "trial",
                                                                  "at": {"$gte": datetime.utcnow() - timedelta(days=7)}})

    @router.get("/access")
    async def access(current_user: dict = Depends(current)):
        uid = str(current_user.get("sub"))
        return {"enabled": await _is_reseller(uid)}

    @router.get("/mine")
    async def mine(uid: str = Depends(me)):
        st = await settings()
        accs = [a async for a in _db().cmtv_nuvio_accounts.find({"reseller_id": uid, "deleted": {"$ne": True}}).sort("created_at", -1)]
        summary = {}
        if accs:
            try:
                code, summary = await N.nv("POST", "/rest/v1/rpc/cmtv_summary", {"p_users": [a["nuvio_id"] for a in accs]})
                summary = summary if code == 200 and isinstance(summary, dict) else {}
            except Exception:
                summary = {}
        return {"balance": await balance(uid), "trials_left": max(0, st["trials_per_week"] - await trials_this_week(uid)),
                "trial_days": st["trial_days"], "accounts": [_row(a, summary) for a in accs],
                "rules": {"base": 1, "extra_devices": 1, "uhd": UHD_EXTRA, "months": list(MONTHS)}}

    @router.get("/log")
    async def history(uid: str = Depends(me)):
        rows = [r async for r in _db().cmtv_nuvio_credit_log.find({"user_id": uid}, {"_id": 0}).sort("at", -1).limit(100)]
        return {"log": rows}

    async def _make(uid: str, body: dict, *, trial: bool) -> dict:
        typed = (body.get("username") or "").strip() or N._rand(N._USER_CHARS, 9)
        password = _clean_password(body.get("password"))
        st = await settings()
        if trial:
            if await trials_this_week(uid) >= st["trials_per_week"]:
                raise HTTPException(429, f"You've used your {st['trials_per_week']} free trials for this week.")
            months, devices, uhd, cost = 0, 2, False, 0
            expires = (date.today() + timedelta(days=int(st["trial_days"]))).strftime("%Y-%m-%d")
        else:
            months, devices, uhd = int(body.get("months") or 0), int(body.get("devices") or 2), bool(body.get("uhd"))
            if not 1 <= devices <= 4:
                raise HTTPException(400, "1 to 4 devices")
            expires = _new_expiry("", months)
            cost = months * per_month(devices, uhd)
        if await N.get_account(typed) or await _db().cmtv_nuvio_accounts.find_one({"_id": N.login_id(typed)}):
            raise HTTPException(409, "That username is taken, try another")
        if cost:
            await change(uid, -cost, "create", f"New account {typed} ({months} mo{', 4K' if uhd else ''}, {devices} devices)", by=uid, account=typed)
        try:
            acc = await N.create_account(typed, password, expires, notes=(body.get("notes") or "")[:120])
        except N.NuvioError as e:
            if cost:
                await change(uid, cost, "refund", f"Refund: {typed} couldn't be created", by="system", account=typed)
            raise HTTPException(409 if "already" in str(e) else 502, str(e))
        extra = {"reseller_id": uid, "pool": await _pool(uid), "uhd": uhd, "trial": trial, "max_devices": devices}
        await _db().cmtv_nuvio_accounts.update_one({"_id": acc["_id"]}, {"$set": extra})
        acc.update(extra)
        try:
            await N.set_max_devices(acc, devices)
            await N.push_addons(acc)   # again, now with this reseller's add-ons and 4K setting
        except Exception as e:
            log.warning(f"Nuvio reseller account {acc['_id']} set-up: {e}")
        if trial:
            await _db().cmtv_nuvio_credit_log.insert_one({"user_id": uid, "delta": 0, "kind": "trial", "reason": f"Free trial {typed}",
                                                          "by": uid, "account": acc["_id"], "balance_after": await balance(uid),
                                                          "at": datetime.utcnow()})
        return {"username": acc["_id"], "login": typed, "password": password, "expires": expires, "cost": cost,
                "balance": await balance(uid)}

    @router.post("/accounts")
    async def create(body: dict = Body(...), uid: str = Depends(me)):
        return await _make(uid, body, trial=False)

    @router.post("/trials")
    async def trial(body: dict = Body(default={}), uid: str = Depends(me)):
        return await _make(uid, body or {}, trial=True)

    @router.post("/accounts/{username}/extend")
    async def extend(username: str, body: dict = Body(...), uid: str = Depends(me)):
        acc = await own(uid, username)
        months = int(body.get("months") or 0)
        # a trial being kept: from today (its end is days away), with the devices/4K chosen now
        devices = int(body.get("devices") or acc.get("max_devices") or 2) if acc.get("trial") else (acc.get("max_devices") or 2)
        uhd = bool(body.get("uhd")) if acc.get("trial") else N.wants_4k(acc)
        expires = _new_expiry("" if acc.get("trial") else acc.get("expires"), months)
        cost = months * per_month(devices, uhd)
        await change(uid, -cost, "extend", f"Extend {acc['_id']} {months} mo", by=uid, account=acc["_id"])
        upd = {"trial": False, "uhd": uhd, "max_devices": devices} if acc.get("trial") else {}
        if upd:
            await _db().cmtv_nuvio_accounts.update_one({"_id": acc["_id"]}, {"$set": upd})
            try:
                await N.set_max_devices({**acc, **upd}, devices)
            except Exception as e:
                log.warning(f"Nuvio reseller devices {acc['_id']}: {e}")
        await N.set_expiry(acc["_id"], expires)
        return {"expires": expires, "cost": cost, "balance": await balance(uid)}

    @router.post("/accounts/{username}/uhd")
    async def uhd(username: str, body: dict = Body(...), uid: str = Depends(me)):
        acc = await own(uid, username)
        on = bool(body.get("on"))
        if on == N.wants_4k(acc):
            return {"uhd": on, "cost": 0, "balance": await balance(uid)}
        if acc.get("trial") and on:
            raise HTTPException(400, "Trials are HD. Extend the account first, then turn 4K on.")
        cost = months_left(acc.get("expires")) * UHD_EXTRA if on else 0   # UHD_EXTRA credits per remaining month; turning off refunds nothing
        if cost:
            await change(uid, -cost, "uhd", f"4K on for {acc['_id']} ({cost} month{'s' if cost > 1 else ''} left)", by=uid, account=acc["_id"])
        try:
            await N.set_uhd(acc, on)
        except N.NuvioError as e:
            if cost:
                await change(uid, cost, "refund", f"Refund: 4K couldn't be switched on for {acc['_id']}", by="system", account=acc["_id"])
            raise HTTPException(502, f"Nuvio server: {e}")
        return {"uhd": on, "cost": cost, "balance": await balance(uid)}

    @router.post("/accounts/{username}/devices")
    async def devices_limit(username: str, body: dict = Body(...), uid: str = Depends(me)):
        acc = await own(uid, username)
        n, old = int(body.get("devices") or 0), acc.get("max_devices") or 2
        if not 1 <= n <= 4:
            raise HTTPException(400, "1 to 4 devices")
        cost = months_left(acc.get("expires")) if (n > 2 >= old and not acc.get("trial")) else 0
        if n > 2 and acc.get("trial"):
            raise HTTPException(400, "Trials have 2 devices. Extend the account first.")
        if cost:
            await change(uid, -cost, "devices", f"{n} devices for {acc['_id']} ({cost} month{'s' if cost > 1 else ''} left)", by=uid, account=acc["_id"])
        try:
            await N.set_max_devices(acc, n)
        except N.NuvioError as e:
            if cost:
                await change(uid, cost, "refund", f"Refund: devices not changed for {acc['_id']}", by="system", account=acc["_id"])
            raise HTTPException(502, f"Nuvio server: {e}")
        return {"max_devices": n, "cost": cost, "balance": await balance(uid)}

    @router.post("/accounts/{username}/password")
    async def password(username: str, body: dict = Body(default={}), uid: str = Depends(me)):
        acc = await own(uid, username)
        p = _clean_password((body or {}).get("password"))
        try:
            await N.set_password(acc, p)
        except N.NuvioError as e:
            raise HTTPException(502, f"Nuvio server: {e}")
        return {"password": p}

    @router.post("/accounts/{username}/status")
    async def status(username: str, body: dict = Body(...), uid: str = Depends(me)):
        acc = await own(uid, username)
        await N.set_status(acc, bool(body.get("off")))
        return {"status": "off" if body.get("off") else "active"}

    @router.get("/accounts/{username}/devices")
    async def devices(username: str, uid: str = Depends(me)):
        acc = await own(uid, username)
        try:
            return {"devices": await N.list_devices(acc), "max_devices": acc.get("max_devices") or 2}
        except N.NuvioError as e:
            raise HTTPException(502, f"Nuvio server: {e}")

    @router.post("/accounts/{username}/sign-out")
    async def sign_out(username: str, body: dict = Body(default={}), uid: str = Depends(me)):
        acc = await own(uid, username)
        try:
            return {"signed_out": await N.sign_out(acc, (body or {}).get("session_id"))}
        except N.NuvioError as e:
            raise HTTPException(502, f"Nuvio server: {e}")

    @router.post("/accounts/{username}/delete")
    async def delete(username: str, body: dict = Body(...), uid: str = Depends(me)):
        acc = await own(uid, username)
        if N.login_id(body.get("confirm") or "") != acc["_id"]:
            raise HTTPException(400, "Type the username to confirm")
        try:
            await N.delete_account(acc, by=f"reseller {uid}")
        except N.NuvioError as e:
            raise HTTPException(502, f"Nuvio server: {e}")
        await _db().cmtv_nuvio_credit_log.insert_one({"user_id": uid, "delta": 0, "kind": "delete", "reason": f"Deleted {acc['_id']}",
                                                      "by": uid, "account": acc["_id"], "balance_after": await balance(uid),
                                                      "at": datetime.utcnow()})
        return {"deleted": acc["_id"]}

    # ---- admin
    @router.get("/admin")
    async def admin_list(current_user: dict = Depends(admin)):
        out = []
        async for u in _db().users.find({"cmtv_nuvio_reseller": True}, {"name": 1, "email": 1, "cmtv_nuvio_pool": 1}):
            uid = str(u["_id"])
            out.append({"user_id": uid, "name": u.get("name"), "email": u.get("email"), "pool": u.get("cmtv_nuvio_pool") or "retail",
                        "balance": await balance(uid),
                        "accounts": await _db().cmtv_nuvio_accounts.count_documents({"reseller_id": uid, "deleted": {"$ne": True}}),
                        "trials": await _db().cmtv_nuvio_accounts.count_documents({"reseller_id": uid, "trial": True, "deleted": {"$ne": True}})})
        return {"resellers": out, "reseller_addons_ready": await _reseller_addons_ready(), "settings": await settings()}

    @router.post("/admin/enable")
    async def admin_enable(body: dict = Body(...), current_user: dict = Depends(admin)):
        """{email | user_id, on, free_credits?}: switch Nuvio reselling on/off; free credits the first time it's switched on"""
        if body.get("user_id"):
            u = await _db().users.find_one({"_id": _oid(body["user_id"])})
        else:
            email = str(body.get("email") or "").strip()
            us = await _db().users.find({"email": {"$regex": f"^{re.escape(email)}$", "$options": "i"}, "role": {"$ne": "merged"}}).to_list(3)
            if len(us) > 1:
                raise HTTPException(409, "More than one account has that email")
            u = us[0] if us else None
        if not u:
            raise HTTPException(404, "No customer account with that email. They need to sign up first.")
        uid, on = str(u["_id"]), bool(body.get("on", True))
        first = on and not u.get("cmtv_nuvio_reseller_at")
        await _db().users.update_one({"_id": u["_id"]}, {"$set": {"cmtv_nuvio_reseller": on,
                                                                   **({"cmtv_nuvio_reseller_at": datetime.utcnow()} if first else {})}})
        given = 0
        if first:
            given = int(body.get("free_credits", (await settings())["free_credits"]) or 0)
            if given > 0:
                await change(uid, given, "gift", "Welcome credits", by=current_user.get("email", "admin"))
        if on:
            await ensure_service(uid, u)
        else:   # switched off: the tools close; accounts keep running until their end dates
            await _db().services.update_many({"user_id": uid, "cockpit_module": "nuvio_reseller"}, {"$set": {"status": "suspended"}})
        return {"user_id": uid, "name": u.get("name"), "email": u.get("email"), "on": on, "free_credits": given,
                "balance": await balance(uid)}

    @router.post("/admin/credit")
    async def admin_credit(body: dict = Body(...), current_user: dict = Depends(admin)):
        uid, delta = str(body.get("user_id") or ""), int(body.get("delta") or 0)
        reason = str(body.get("reason") or "").strip()[:200]
        if not delta or not reason:
            raise HTTPException(400, "Enter an amount and a reason")
        return {"balance": await change(uid, delta, "admin", reason, by=current_user.get("email", "admin"))}

    @router.get("/admin/premiumize")
    async def pm_get(current_user: dict = Depends(admin)):
        cfg = await _db().cmtv_config.find_one({"_id": "premiumize"}) or {}
        out = {}
        for name in ("retail", "reseller"):
            a = (cfg.get("accounts") or {}).get(name) or {}
            out[name] = {"label": a.get("label") or ("Your customers" if name == "retail" else "Resellers' customers"),
                         "key_end": (a.get("key") or "")[-4:], "set": bool(a.get("key")), "limit_used": a.get("limit_used"),
                         "premium_until": a.get("premium_until"), "checked_at": a.get("checked_at"), "error": a.get("last_error")}
        return {"accounts": out, "levels": list(PM_LEVELS)}

    @router.post("/admin/premiumize")
    async def pm_set(body: dict = Body(...), current_user: dict = Depends(admin)):
        """{account: retail|reseller, key ('' removes it)}: checked with Premiumize before it's saved"""
        name, key = body.get("account"), str(body.get("key") or "").strip()
        if name not in ("retail", "reseller"):
            raise HTTPException(400, "retail or reseller")
        if key:
            if not re.match(r"^[A-Za-z0-9]{8,64}$", key):
                raise HTTPException(400, "That doesn't look like a Premiumize API key")
            try:
                await premiumize_info(key)
            except Exception as e:
                raise HTTPException(400, f"Premiumize didn't accept that key: {e}")
        await _db().cmtv_config.update_one({"_id": "premiumize"}, {"$set": {f"accounts.{name}.key": key,
                                                                           f"accounts.{name}.alerted": []}}, upsert=True)
        await premiumize_check()
        return await pm_get(current_user)

    @router.post("/admin/pool")
    async def admin_pool(body: dict = Body(...), current_user: dict = Depends(admin)):
        pool = body.get("pool")
        if pool not in ("retail", "reseller"):
            raise HTTPException(400, "retail or reseller")
        return {"moved": await set_pool(str(body.get("user_id")), pool, current_user.get("email", "admin"))}
