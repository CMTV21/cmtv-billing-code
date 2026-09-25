"""Admin > Audiobooks (CMTV local addition 2026-09-25).

Billing's page for every audiobook user. The accounts live in Audiobookshelf + ReadMeABook on the Asus server and are
managed by abadmin, whose billing API (https://abadmin.cmtv.info/api/billing/..., ABADMIN_URL / ABADMIN_TOKEN in .env)
this module calls. Billing adds who the account belongs to: a service with cockpit_module "audiobooks" and the same
username (the automatic Audiobooks products create those). Changes made here are copied onto that service too
(expiry, status, password), so My Services stays right.
"""
import logging
import os
import re
import secrets
from datetime import date, datetime, timedelta

import httpx
from bson import ObjectId
from dateutil.relativedelta import relativedelta
from fastapi import APIRouter, Depends, HTTPException

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/cmtv/audiobooks", tags=["cmtv-audiobooks"])
D = {}
MODULE = "audiobooks"
_USER_CHARS = "abcdefghjkmnpqrstuvwxyz23456789"
_PASS_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789"
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def init(**deps):
    D.update(deps)


def _oid(v):
    return ObjectId(v) if ObjectId.is_valid(str(v)) else None


def _rand(chars, n):
    return "".join(secrets.choice(chars) for _ in range(n))


def _end_of_day(day: str) -> datetime:
    return datetime.strptime(day, "%Y-%m-%d").replace(hour=23, minute=59, second=59)


async def _ab(method: str, path: str, json=None, params=None):
    base, token = os.environ.get("ABADMIN_URL", "").rstrip("/"), os.environ.get("ABADMIN_TOKEN", "")
    if not base or not token:
        raise HTTPException(503, "abadmin isn't set up (ABADMIN_URL / ABADMIN_TOKEN)")
    try:
        async with httpx.AsyncClient(timeout=40) as c:
            r = await c.request(method, f"{base}{path}", json=json, params=params,
                                headers={"Authorization": f"Bearer {token}", "User-Agent": "cmtv-billing"})
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Couldn't reach the audiobook server ({type(e).__name__})")
    try:
        body = r.json()
    except ValueError:
        body = {}
    if r.status_code >= 400:
        raise HTTPException(r.status_code if r.status_code < 500 else 502, body.get("detail") or f"abadmin error {r.status_code}")
    return body


async def _linked(username: str):
    """Billing services linked to this audiobook account"""
    rx = {"$regex": f"^{re.escape(username)}$", "$options": "i"}
    return [s async for s in D["services"].find({"cockpit_module": MODULE, "username": rx})]


async def _sync_services(username: str, **fields):
    for s in await _linked(username):
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


def init_routes():
    admin = D["get_current_admin_user"]

    @router.get("/users")
    async def list_users(current_user: dict = Depends(admin)):
        data = await _ab("GET", "/api/billing/users")
        # who each account belongs to in billing
        links = {}
        async for s in D["services"].find({"cockpit_module": MODULE}):
            links.setdefault(str(s.get("username") or "").lower(), []).append(s)
        uids = {s.get("user_id") for ss in links.values() for s in ss}
        users = {str(u["_id"]): u async for u in D["users"].find({"_id": {"$in": [_oid(i) for i in uids if _oid(i)]}},
                                                                   {"name": 1, "email": 1})}
        out = []
        for u in data.get("users", []):
            ss = links.get(u["username"].lower(), [])
            cust = users.get(ss[0].get("user_id")) if ss else None
            out.append({**u, "customer": {"id": str(cust["_id"]), "name": cust.get("name"), "email": cust.get("email")} if cust else None,
                        "services": [{"id": str(s["_id"]), "product_name": s.get("product_name"), "status": s.get("status"),
                                      "is_trial": bool(s.get("is_trial"))} for s in ss]})
        # audiobook services in billing that aren't linked to an account yet (set up by hand before 2026-09-25)
        pids = [str(p["_id"]) async for p in D["products"].find({"$or": [
            {"cockpit_module": MODULE}, {"name": {"$regex": "audiobook", "$options": "i"}}]}, {"_id": 1})]
        unlinked = []
        async for s in D["services"].find({"product_id": {"$in": pids}, "cockpit_module": {"$ne": MODULE},
                                           "status": {"$nin": ["failed", "cancelled", "terminated"]}}):
            cu = await D["users"].find_one({"_id": _oid(s.get("user_id"))}, {"name": 1, "email": 1})
            unlinked.append({"service_id": str(s["_id"]), "product_name": s.get("product_name"), "status": s.get("status"),
                             "created_at": s.get("created_at"), "expiry_date": s.get("expiry_date"),
                             "customer": {"id": str(cu["_id"]), "name": cu.get("name"), "email": cu.get("email")} if cu else None})
        return {"users": out, "unmanaged": data.get("unmanaged", []), "unlinked_services": unlinked,
                "error": data.get("error", ""), "today": date.today().isoformat()}

    @router.get("/activity")
    async def activity(current_user: dict = Depends(admin)):
        return await _ab("GET", "/api/billing/audit", params={"limit": 80})

    @router.post("/users/{username}/extend")
    async def extend(username: str, data: dict, current_user: dict = Depends(admin)):
        cur = await _ab("GET", f"/api/billing/users/{username}")
        if not cur.get("exists"):
            raise HTTPException(404, "User not found")
        new = _new_expiry(cur.get("expiry_date"), int(data.get("months") or 0), str(data.get("expiry_date") or ""))
        svc = (await _linked(username) or [{}])[0]
        res = await _ab("POST", f"/api/billing/users/{username}/extend", json={"expiry_date": new, "password": svc.get("password") or ""})
        await _sync_services(username, expiry_date=_end_of_day(new), status="active")
        logger.info(f"Audiobooks: admin {current_user.get('sub')} set {username} to {new}")
        return res

    @router.post("/users/{username}/disable")
    async def disable(username: str, current_user: dict = Depends(admin)):
        res = await _ab("POST", f"/api/billing/users/{username}/disable")
        await _sync_services(username, status="suspended")
        return res

    @router.post("/users/{username}/enable")
    async def enable(username: str, current_user: dict = Depends(admin)):
        svc = (await _linked(username) or [{}])[0]
        res = await _ab("POST", f"/api/billing/users/{username}/enable", json={"password": svc.get("password") or ""})
        await _sync_services(username, status="active")
        return res

    @router.post("/users/{username}/password")
    async def password(username: str, data: dict, current_user: dict = Depends(admin)):
        pw = str(data.get("password") or "") or _rand(_PASS_CHARS, 10)
        if len(pw) < 8:
            raise HTTPException(400, "Password must be at least 8 characters")
        res = await _ab("POST", f"/api/billing/users/{username}/password", json={"password": pw})
        await _sync_services(username, password=pw, xtream_password=pw)
        return {**res, "password": pw}

    @router.post("/import")
    async def import_user(data: dict, current_user: dict = Depends(admin)):
        exp = str(data.get("expiry_date") or "")
        if not exp and data.get("months"):
            exp = _new_expiry("", int(data["months"]))
        return await _ab("POST", "/api/billing/import", json={"username": data.get("username"), "expiry_date": exp})

    @router.get("/customers")
    async def customers(q: str = "", current_user: dict = Depends(admin)):
        q = (q or "").strip()[:80]
        if len(q) < 2:
            return []
        rx = {"$regex": re.escape(q), "$options": "i"}
        return [{"id": str(u["_id"]), "name": u.get("name"), "email": u.get("email")} async for u in
                D["users"].find({"role": "user", "$or": [{"name": rx}, {"email": rx}, {"username": rx}]}, {"name": 1, "email": 1}).limit(12)]

    async def _attach(username: str, customer_id: str, password: str, expiry: str, service_id: str = ""):
        """Make (or convert) the customer's billing service for this account, so it shows in My Services"""
        product = await D["products"].find_one({"cockpit_module": MODULE, "is_trial": {"$ne": True}})
        fields = {"cockpit_module": MODULE, "username": username, "xtream_username": username, "account_type": "subscriber",
                  "panel_type": "manual", "panel_name": "abadmin (Audiobooks)", "status": "active", "updated_at": datetime.utcnow()}
        if password:
            fields.update(password=password, xtream_password=password)
        if expiry:
            fields["expiry_date"] = _end_of_day(expiry)
        if service_id:
            await D["services"].update_one({"_id": _oid(service_id)}, {"$set": fields})
            return service_id
        doc = {"user_id": customer_id, "order_id": None, "product_id": str(product["_id"]) if product else None,
               "product_name": (product or {}).get("name", "CMTV Audiobooks"), "term_months": 12, "max_connections": 0,
               "is_trial": False, "setup_instructions": (product or {}).get("setup_instructions", ""),
               "start_date": datetime.utcnow(), "created_at": datetime.utcnow(), **fields}
        r = await D["services"].insert_one(doc)
        return str(r.inserted_id)

    @router.post("/users")
    async def create(data: dict, current_user: dict = Depends(admin)):
        username = str(data.get("username") or "").strip().lower() or _rand(_USER_CHARS, 9)
        pw = _rand(_PASS_CHARS, 10)
        exp = _new_expiry("", int(data.get("months") or 0), str(data.get("expiry_date") or ""))
        cust = None
        if data.get("customer_id"):
            cust = await D["users"].find_one({"_id": _oid(data["customer_id"])})
            if not cust:
                raise HTTPException(404, "Customer not found")
        res = await _ab("POST", "/api/billing/users", json={"username": username, "password": pw, "expiry_date": exp,
                                                            "display_name": (cust or {}).get("name") or username,
                                                            "notes": f"Created in billing by admin" + (f" for {cust.get('email')}" if cust else "")})
        emailed = False
        if cust:
            await _attach(username, str(cust["_id"]), pw, exp)
            if data.get("email_customer"):
                try:
                    es = await D["get_email_service"]()
                    product = await D["products"].find_one({"cockpit_module": MODULE, "is_trial": {"$ne": True}})
                    if es:
                        emailed = bool(await es.send_cockpit_account(
                            customer_email=cust["email"], customer_name=cust.get("name", ""),
                            service_name=(product or {}).get("name", "CMTV Audiobooks"), username=username, password=pw,
                            expiry_date=exp, setup_instructions=(product or {}).get("setup_instructions", ""),
                            customer_id=str(cust["_id"])))
                except Exception as e:
                    logger.warning(f"Audiobooks login email for {username} failed: {e}")
        return {**res, "password": pw, "emailed": emailed}

    @router.post("/link")
    async def link(data: dict, current_user: dict = Depends(admin)):
        """Tie an account to a billing customer: convert one of their unlinked audiobook services, or add one"""
        username = str(data.get("username") or "").strip()
        cur = await _ab("GET", f"/api/billing/users/{username}")
        if not cur.get("exists"):
            raise HTTPException(404, "That audiobook account isn't managed yet (import it first)")
        if data.get("service_id"):
            s = await D["services"].find_one({"_id": _oid(data["service_id"])})
            if not s:
                raise HTTPException(404, "Service not found")
            customer_id = s.get("user_id")
        else:
            customer_id = str(data.get("customer_id") or "")
            if not await D["users"].find_one({"_id": _oid(customer_id)}):
                raise HTTPException(404, "Customer not found")
        sid = await _attach(cur["username"], customer_id, "", cur.get("expiry_date") or "", str(data.get("service_id") or ""))
        return {"success": True, "service_id": sid}
