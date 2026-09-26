"""Admin > Add-ons (CMTV local addition 2026-09-26): Stremio (Cockpit "nuvio") and CMTVpn (Cockpit "vpn") users.

Every Cockpit user with its end date and the billing customer it belongs to (a service with the same cockpit_module
and username), plus extend / switch off / switch on / new password / new account / link. Reads and writes go through
cockpit_helper.py (as www-data, table layout checked first), like automatic provisioning. Changes are copied onto the
linked billing service, so My Services and the expiry reminders stay right.

Switch off: Cockpit only uses status "active" and always enforces the end date, so switching off sets the end date to
yesterday and keeps the real one in cmtv_cockpit_paused; switching on puts it back (or today, if it has passed).
"""
import logging
import re
import secrets
from datetime import date, datetime, timedelta

import bcrypt
from bson import ObjectId
from dateutil.relativedelta import relativedelta
from fastapi import APIRouter, Depends, HTTPException

import cockpit_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/cmtv/addons", tags=["cmtv-addons"])
D = {}
MODULES = {"nuvio": "Stremio", "vpn": "CMTVpn"}
_USER_CHARS = "abcdefghjkmnpqrstuvwxyz23456789"
_PASS_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789"
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_USERNAME = re.compile(r"^[A-Za-z0-9._@-]{3,40}$")


def init(**deps):
    D.update(deps)


def _oid(v):
    return ObjectId(v) if ObjectId.is_valid(str(v)) else None


def _rand(chars, n):
    return "".join(secrets.choice(chars) for _ in range(n))


def _end_of_day(day: str) -> datetime:
    return datetime.strptime(day, "%Y-%m-%d").replace(hour=23, minute=59, second=59)


def _module(m):
    if m not in MODULES:
        raise HTTPException(400, "Unknown add-on (use nuvio or vpn)")
    return m


def _key(module, username):
    return f"{module}:{username.lower()}"


async def _cockpit(req: dict) -> dict:
    res = await cockpit_service._call(req)
    if not res.get("success"):
        raise HTTPException(502, f"Cockpit: {res.get('error') or 'no answer'}")
    return res


def _pw_request(module, password):
    req = {"password": password}
    if module == "nuvio":   # Cockpit is PHP: bcrypt labelled $2y$
        req["password_hash"] = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=10)).decode().replace("$2b$", "$2y$", 1)
    return req


async def _linked(module, username):
    rx = {"$regex": f"^{re.escape(username)}$", "$options": "i"}
    return [s async for s in D["services"].find({"cockpit_module": module, "username": rx})]


async def _sync(module, username, **fields):
    for s in await _linked(module, username):
        await D["services"].update_one({"_id": s["_id"]}, {"$set": {**fields, "updated_at": datetime.utcnow()}})


def _new_expiry(current: str, months: int = 0, expiry_date: str = "") -> str:
    if expiry_date:
        if not _DATE.match(expiry_date):
            raise HTTPException(400, "Date must be YYYY-MM-DD")
        return expiry_date
    if months not in (1, 3, 6, 12, 24):
        raise HTTPException(400, "Choose 1, 3, 6, 12 or 24 months")
    today = date.today()
    try:
        base = max(today, datetime.strptime(current or "", "%Y-%m-%d").date())
    except ValueError:
        base = today
    return (base + relativedelta(months=months)).strftime("%Y-%m-%d")


async def _get(module, username):
    cur = await _cockpit({"module": module, "action": "get", "username": username})
    if not cur.get("exists"):
        raise HTTPException(404, f"{username} isn't in Cockpit ({MODULES[module]})")
    return cur


def init_routes():
    admin = D["get_current_admin_user"]

    @router.get("/users")
    async def list_users(current_user: dict = Depends(admin)):
        paused = {p["_id"]: p async for p in D["db"].cmtv_cockpit_paused.find({})}
        links = {}
        async for s in D["services"].find({"cockpit_module": {"$in": list(MODULES)}}):
            links.setdefault(_key(s["cockpit_module"], str(s.get("username") or "")), []).append(s)
        uids = {s.get("user_id") for ss in links.values() for s in ss}
        custs = {str(u["_id"]): u async for u in D["users"].find({"_id": {"$in": [_oid(i) for i in uids if _oid(i)]}},
                                                                  {"name": 1, "email": 1})}
        out, errors = [], []
        for module, label in MODULES.items():
            res = await cockpit_service._call({"module": module, "action": "list"})
            if not res.get("success"):
                errors.append(f"{label}: {res.get('error')}")
                continue
            for u in res.get("users", []):
                k = _key(module, u["username"])
                ss = links.get(k, [])
                cust = custs.get(ss[0].get("user_id")) if ss else None
                p = paused.get(k)
                out.append({
                    "module": module, "label": label, "username": u["username"], "password": u.get("password") or "",
                    "cockpit_status": u.get("status"), "expiry_date": (p or {}).get("expires") or u.get("expires"),
                    "cockpit_expiry": u.get("expires"), "paused": bool(p),
                    "last_login": datetime.utcfromtimestamp(u["last_login_at"]).strftime("%Y-%m-%d") if u.get("last_login_at") else None,
                    "customer": {"id": str(cust["_id"]), "name": cust.get("name"), "email": cust.get("email")} if cust else None,
                    "services": [{"id": str(s["_id"]), "product_name": s.get("product_name"), "status": s.get("status"),
                                  "is_trial": bool(s.get("is_trial"))} for s in ss],
                })
        # Stremio / CMTVpn services in billing not tied to a Cockpit account (set up by hand)
        pids = {str(p["_id"]): p.get("cockpit_module") async for p in D["products"].find({"cockpit_module": {"$in": list(MODULES)}}, {"cockpit_module": 1})}
        unlinked = []
        async for s in D["services"].find({"product_id": {"$in": list(pids)}, "cockpit_module": {"$nin": list(MODULES)},
                                           "status": {"$nin": ["failed", "cancelled", "terminated"]}}):
            cu = await D["users"].find_one({"_id": _oid(s.get("user_id"))}, {"name": 1, "email": 1})
            unlinked.append({"service_id": str(s["_id"]), "module": pids.get(s.get("product_id")), "product_name": s.get("product_name"),
                             "status": s.get("status"), "expiry_date": s["expiry_date"].strftime("%Y-%m-%d") if isinstance(s.get("expiry_date"), datetime) else None,
                             "customer": {"id": str(cu["_id"]), "name": cu.get("name"), "email": cu.get("email")} if cu else None})
        return {"users": out, "unlinked_services": unlinked, "errors": errors, "today": date.today().isoformat()}

    @router.post("/{module}/users/{username}/extend")
    async def extend(module: str, username: str, data: dict, current_user: dict = Depends(admin)):
        _module(module)
        cur = await _get(module, username)
        p = await D["db"].cmtv_cockpit_paused.find_one({"_id": _key(module, username)})
        new = _new_expiry((p or {}).get("expires") or cur.get("expires"), int(data.get("months") or 0), str(data.get("expiry_date") or ""))
        await _cockpit({"module": module, "action": "extend", "username": username, "expires": new})
        await D["db"].cmtv_cockpit_paused.delete_one({"_id": _key(module, username)})
        await _sync(module, username, expiry_date=_end_of_day(new), status="active")
        logger.info(f"Add-ons: admin {current_user.get('sub')} set {module} {username} to {new}")
        return {"success": True, "expiry_date": new}

    @router.post("/{module}/users/{username}/disable")
    async def disable(module: str, username: str, current_user: dict = Depends(admin)):
        _module(module)
        cur = await _get(module, username)
        k = _key(module, username)
        if await D["db"].cmtv_cockpit_paused.find_one({"_id": k}):
            raise HTTPException(400, "Already switched off")
        yesterday = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
        await D["db"].cmtv_cockpit_paused.insert_one({"_id": k, "module": module, "username": username,
                                                      "expires": cur.get("expires"), "paused_at": datetime.utcnow(),
                                                      "by": current_user.get("sub")})
        try:
            await _cockpit({"module": module, "action": "set_expiry", "username": username, "expires": yesterday})
        except HTTPException:
            await D["db"].cmtv_cockpit_paused.delete_one({"_id": k})
            raise
        await _sync(module, username, status="suspended")
        logger.info(f"Add-ons: admin {current_user.get('sub')} switched off {module} {username} (was until {cur.get('expires')})")
        return {"success": True, "kept_expiry": cur.get("expires")}

    @router.post("/{module}/users/{username}/enable")
    async def enable(module: str, username: str, current_user: dict = Depends(admin)):
        _module(module)
        await _get(module, username)
        k = _key(module, username)
        p = await D["db"].cmtv_cockpit_paused.find_one({"_id": k})
        if not p:
            raise HTTPException(400, "It isn't switched off. Use Extend to add time.")
        restore = max(date.today().strftime("%Y-%m-%d"), p.get("expires") or "")
        await _cockpit({"module": module, "action": "extend", "username": username, "expires": restore})
        await D["db"].cmtv_cockpit_paused.delete_one({"_id": k})
        await _sync(module, username, expiry_date=_end_of_day(restore), status="active")
        return {"success": True, "expiry_date": restore}

    @router.post("/{module}/users/{username}/password")
    async def password(module: str, username: str, data: dict, current_user: dict = Depends(admin)):
        _module(module)
        pw = str(data.get("password") or "") or _rand(_PASS_CHARS, 10)
        if len(pw) < 6:
            raise HTTPException(400, "Password must be at least 6 characters")
        await _cockpit({"module": module, "action": "set_password", "username": username, **_pw_request(module, pw)})
        await _sync(module, username, password=pw, xtream_password=pw)
        return {"success": True, "password": pw}

    @router.post("/{module}/users/{username}/delete")
    async def delete(module: str, username: str, current_user: dict = Depends(admin)):
        """Delete from Cockpit for good (2026-09-26). A full copy is kept in cmtv_deleted_accounts, and the linked
        billing service is marked terminated (kept, so order history stays)."""
        _module(module)
        res = await _cockpit({"module": module, "action": "delete", "username": username})
        await D["db"].cmtv_deleted_accounts.insert_one({
            "kind": "cockpit", "module": module, "username": res["deleted"].get("username") or username,
            "row": res["deleted"], "related": res.get("related") or {},
            "billing_services": [str(s["_id"]) for s in await _linked(module, username)],
            "deleted_at": datetime.utcnow(), "by": current_user.get("sub")})
        await D["db"].cmtv_cockpit_paused.delete_one({"_id": _key(module, username)})
        await _sync(module, username, status="terminated", cockpit_deleted_at=datetime.utcnow())
        logger.info(f"Add-ons: admin {current_user.get('sub')} deleted {module} {username}")
        return {"success": True}

    @router.get("/customers")
    async def customers(q: str = "", current_user: dict = Depends(admin)):
        q = (q or "").strip()[:80]
        if len(q) < 2:
            return []
        rx = {"$regex": re.escape(q), "$options": "i"}
        return [{"id": str(u["_id"]), "name": u.get("name"), "email": u.get("email")} async for u in
                D["users"].find({"role": "user", "$or": [{"name": rx}, {"email": rx}, {"username": rx}]}, {"name": 1, "email": 1}).limit(12)]

    async def _attach(module, username, customer_id, password, expiry, service_id=""):
        """Make (or convert) the customer's billing service for this account, so it shows in My Services"""
        product = await D["products"].find_one({"cockpit_module": module, "is_trial": {"$ne": True}})
        fields = {"cockpit_module": module, "username": username, "xtream_username": username, "account_type": "subscriber",
                  "panel_type": "manual", "panel_name": f"Cockpit ({MODULES[module]})", "status": "active", "updated_at": datetime.utcnow()}
        if password:
            fields.update(password=password, xtream_password=password)
        if expiry:
            fields["expiry_date"] = _end_of_day(expiry)
        if service_id:
            await D["services"].update_one({"_id": _oid(service_id)}, {"$set": fields})
            return service_id
        doc = {"user_id": customer_id, "order_id": None, "product_id": str(product["_id"]) if product else None,
               "product_name": (product or {}).get("name", MODULES[module]), "term_months": 12, "max_connections": 0,
               "is_trial": False, "setup_instructions": (product or {}).get("setup_instructions", ""),
               "start_date": datetime.utcnow(), "created_at": datetime.utcnow(), **fields}
        return str((await D["services"].insert_one(doc)).inserted_id)

    @router.post("/{module}/users")
    async def create(module: str, data: dict, current_user: dict = Depends(admin)):
        _module(module)
        username = str(data.get("username") or "").strip()
        if username and not _USERNAME.match(username):
            raise HTTPException(400, "Username: 3-40 letters, numbers, . _ - or @")
        exp = _new_expiry("", int(data.get("months") or 0), str(data.get("expiry_date") or ""))
        cust = None
        if data.get("customer_id"):
            cust = await D["users"].find_one({"_id": _oid(data["customer_id"])})
            if not cust:
                raise HTTPException(404, "Customer not found")
        pw = _rand(_PASS_CHARS, 10)
        for _ in range(5):
            name = username or _rand(_USER_CHARS, 9)
            res = await cockpit_service._call({"module": module, "action": "create", "username": name, "expires": exp,
                                               **_pw_request(module, pw)})
            if res.get("success"):
                username = name
                break
            if username or "already exists" not in (res.get("error") or ""):
                raise HTTPException(409 if "already exists" in (res.get("error") or "") else 502,
                                    f"Cockpit: {res.get('error')}")
        else:
            raise HTTPException(502, "Couldn't find a free username")
        emailed = False
        if cust:
            await _attach(module, username, str(cust["_id"]), pw, exp)
            if data.get("email_customer"):
                try:
                    es = await D["get_email_service"]()
                    product = await D["products"].find_one({"cockpit_module": module, "is_trial": {"$ne": True}})
                    if es:
                        emailed = bool(await es.send_cockpit_account(
                            customer_email=cust["email"], customer_name=cust.get("name", ""),
                            service_name=(product or {}).get("name", MODULES[module]), username=username, password=pw,
                            expiry_date=exp, setup_instructions=(product or {}).get("setup_instructions", ""),
                            customer_id=str(cust["_id"])))
                except Exception as e:
                    logger.warning(f"Add-ons login email for {username} failed: {e}")
        logger.info(f"Add-ons: admin {current_user.get('sub')} created {module} {username} until {exp}")
        return {"success": True, "username": username, "password": pw, "expiry_date": exp, "emailed": emailed}

    @router.post("/{module}/link")
    async def link(module: str, data: dict, current_user: dict = Depends(admin)):
        """Tie a Cockpit account to a billing customer: convert one of their unlinked services, or add one"""
        _module(module)
        username = str(data.get("username") or "").strip()
        cur = await _get(module, username)
        p = await D["db"].cmtv_cockpit_paused.find_one({"_id": _key(module, username)})
        if data.get("service_id"):
            s = await D["services"].find_one({"_id": _oid(data["service_id"])})
            if not s:
                raise HTTPException(404, "Service not found")
            customer_id = s.get("user_id")
        else:
            customer_id = str(data.get("customer_id") or "")
            if not await D["users"].find_one({"_id": _oid(customer_id)}):
                raise HTTPException(404, "Customer not found")
        pw = ""
        listing = await cockpit_service._call({"module": module, "action": "list"})
        for u in listing.get("users", []):
            if u["username"].lower() == username.lower():
                username, pw = u["username"], u.get("password") or ""
        sid = await _attach(module, username, customer_id, pw, (p or {}).get("expires") or cur.get("expires") or "",
                            str(data.get("service_id") or ""))
        if p:
            await D["services"].update_one({"_id": _oid(sid)}, {"$set": {"status": "suspended"}})
        return {"success": True, "service_id": sid}
