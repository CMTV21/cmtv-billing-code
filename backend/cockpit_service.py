"""Cockpit panel accounts for billing (CMTV local addition 2026-09-24).

Manual products with a `cockpit_module` ('nuvio' = Stremio, 'vpn' = CMTVpn) get their customer account created and
renewed in the Cockpit panel automatically. The database writes happen in cockpit_helper.py, run as www-data so the
SQLite files keep Cockpit's ownership; this module generates credentials, works out dates and calls the helper.
"""
import asyncio
import json
import logging
import secrets
from datetime import datetime, timezone
from asyncio.subprocess import PIPE

import bcrypt
from dateutil.relativedelta import relativedelta

logger = logging.getLogger(__name__)

HELPER = "/opt/backend/cockpit_helper.py"
MODULES = {"nuvio": "Stremio", "vpn": "CMTVpn", "audiobooks": "Audiobooks", "nuviocloud": "Nuvio"}
# CMTV local change 2026-09-29: "nuviocloud" = accounts on CMTV's own Nuvio server (cmtv_nuvio.py, nuvio.cmtv.info)
# CMTV local change 2026-09-25: "audiobooks" isn't Cockpit. It goes to abadmin on the Asus server
# (https://abadmin.cmtv.info/api/billing/..., token in .env as ABADMIN_TOKEN), which creates the Audiobookshelf and
# ReadMeABook users and switches them off after their expiry date. Same request/answer shapes as the Cockpit helper.
# No look-alike characters (0/O, 1/l/I), since customers type these on TV remotes
_USER_CHARS = "abcdefghjkmnpqrstuvwxyz23456789"
_PASS_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789"


async def _abadmin(request: dict) -> dict:
    """The Cockpit helper's actions (get / create / extend) for audiobooks, through abadmin's billing API"""
    import os
    import httpx
    base, token = os.environ.get("ABADMIN_URL", "").rstrip("/"), os.environ.get("ABADMIN_TOKEN", "")
    if not base or not token:
        return {"success": False, "error": "abadmin isn't set up in billing (ABADMIN_URL / ABADMIN_TOKEN in .env)"}
    headers = {"Authorization": f"Bearer {token}", "User-Agent": "cmtv-billing"}
    user, action = request.get("username", ""), request.get("action")
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            if action == "get":
                r = await c.get(f"{base}/api/billing/users/{user}", headers=headers)
            elif action == "create":
                r = await c.post(f"{base}/api/billing/users", headers=headers, json={
                    "username": user, "password": request["password"], "expiry_date": request["expires"],
                    "notes": request.get("notes") or "Created by billing"})
            elif action == "extend":
                r = await c.post(f"{base}/api/billing/users/{user}/extend", headers=headers, json={
                    "expiry_date": request["expires"], "password": request.get("password") or ""})
            else:
                return {"success": False, "error": f"unknown action {action!r}"}
    except httpx.HTTPError as e:
        return {"success": False, "error": f"couldn't reach abadmin: {type(e).__name__}"}
    try:
        body = r.json()
    except ValueError:
        body = {}
    if r.status_code == 409:
        return {"success": False, "error": "already exists"}
    if r.status_code >= 400:
        return {"success": False, "error": f"abadmin {r.status_code}: {body.get('detail') or r.text[:200]}"}
    if body.get("warning"):
        logger.warning(f"abadmin {action} {user}: {body['warning']}")
    if action == "get":
        return {"success": True, "exists": bool(body.get("exists")), "expires": body.get("expiry_date") or ""}
    return {"success": True, "expires": body.get("expiry_date") or request.get("expires"), "warning": body.get("warning", "")}


async def _call(request: dict) -> dict:
    """Run cockpit_helper.py as www-data with one JSON request; always returns a dict with 'success'"""
    if request.get("module") == "audiobooks":
        return await _abadmin(request)
    if request.get("module") == "nuviocloud":   # CMTV local change 2026-09-29
        import cmtv_nuvio
        return await cmtv_nuvio.handle(request)
    try:
        proc = await asyncio.create_subprocess_exec(
            "runuser", "-u", "www-data", "--", "/usr/bin/python3", HELPER, stdin=PIPE, stdout=PIPE, stderr=PIPE)
        out, err = await asyncio.wait_for(proc.communicate(json.dumps(request).encode()), timeout=30)
    except Exception as e:
        return {"success": False, "error": f"couldn't run the Cockpit helper: {type(e).__name__}: {e}"}
    try:
        return json.loads(out.decode().strip().splitlines()[-1])
    except Exception:
        return {"success": False, "error": f"Cockpit helper gave no result: {(err or out).decode(errors='replace')[:300]}"}


def _random(chars: str, length: int) -> str:
    return "".join(secrets.choice(chars) for _ in range(length))


def _add_term(start, months: int = 0, days: int = 0):
    return start + relativedelta(months=months, days=days)


def expiry_datetime(day: str) -> datetime:
    """'2026-10-24' -> 2026-10-24 23:59:59 (UTC, naive, as billing stores dates): the moment Cockpit ends access"""
    return datetime.strptime(day, "%Y-%m-%d").replace(hour=23, minute=59, second=59)


async def create_account(module: str, months: int = 1, days: int = 0) -> dict:
    """New Cockpit account valid for the term from today. Returns success, username, password, expires (YYYY-MM-DD)"""
    if module not in MODULES:
        return {"success": False, "error": f"unknown Cockpit module {module!r}"}
    expires = _add_term(datetime.now(timezone.utc).date(), months, days).strftime("%Y-%m-%d")
    for _ in range(5):
        username = _random(_USER_CHARS, 9)
        password = _random(_PASS_CHARS, 10)
        request = {"module": module, "action": "create", "username": username, "password": password, "expires": expires}
        if module == "nuvio":
            # Cockpit is PHP: password_verify() reads bcrypt as $2y$ ($2b$ is the same algorithm, different label)
            request["password_hash"] = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=10)).decode().replace("$2b$", "$2y$", 1)
        result = await _call(request)
        if result.get("success"):
            return {**result, "username": username, "password": password}
        if "already exists" not in (result.get("error") or ""):
            return result
    return {"success": False, "error": "couldn't find a free username after 5 tries"}


async def extend_account(module: str, username: str, months: int = 1, days: int = 0, password: str = "") -> dict:
    """Add the term to an existing Cockpit account, counted from its current expiry (or today, if already expired).
    password: only used for audiobooks, to re-create a lapsed requests-app login (2026-09-25)."""
    if module not in MODULES:
        return {"success": False, "error": f"unknown Cockpit module {module!r}"}
    current = await _call({"module": module, "action": "get", "username": username})
    if not current.get("success"):
        return current
    if not current.get("exists"):
        return {"success": False, "error": f"account {username!r} no longer exists in Cockpit ({MODULES[module]})"}
    today = datetime.now(timezone.utc).date()
    try:
        base = max(today, datetime.strptime(current.get("expires") or "", "%Y-%m-%d").date())
    except ValueError:
        base = today
    expires = _add_term(base, months, days).strftime("%Y-%m-%d")
    return await _call({"module": module, "action": "extend", "username": username, "expires": expires, "password": password})
