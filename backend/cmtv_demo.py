"""Demo accounts are look-only (CMTV local addition 2026-09-28, the user's rule: "everything should be dummy").
An HTTP middleware (registered in server.py) refuses every POST/PUT/PATCH/DELETE under /api/ made with a demo account's
token (users with cmtv_demo: true), so it can't place orders (checkout always creates the billing order before any
payment step), start trials, turn on PayPal auto-renew, open tickets, link Telegram, change its profile or anything else
real. Allowed: signing in/out and its reseller brand settings (/api/cmtv/reseller/brand, /brand/logo), which only change
its own demo guide. GET requests are untouched. The list of demo user ids is re-read from the database every minute.
"""
import logging
import time

from fastapi.responses import JSONResponse

from auth import ALGORITHM, SECRET_KEY, jwt

log = logging.getLogger("server")
D = {}
_cache = {"ids": set(), "at": 0.0}
WRITE = {"POST", "PUT", "PATCH", "DELETE"}
ALLOWED = ("/api/auth/login", "/api/auth/logout", "/api/auth/refresh", "/api/cmtv/reseller/brand")
MESSAGE = "This is a demo account, so nothing real can be bought, created or changed here."


async def demo_ids():
    if time.time() - _cache["at"] > 60 and D.get("db") is not None:
        try:
            _cache["ids"] = {str(u["_id"]) async for u in D["db"].users.find({"cmtv_demo": True}, {"_id": 1})}
            _cache["at"] = time.time()
        except Exception as e:
            log.warning(f"demo guard: could not read demo accounts: {e}")
    return _cache["ids"]


def _sub(request):
    auth = request.headers.get("authorization") or ""
    if not auth.lower().startswith("bearer "):
        return None
    try:
        return str(jwt.decode(auth[7:].strip(), SECRET_KEY, algorithms=[ALGORITHM]).get("sub") or "")
    except Exception:
        return None


async def guard(request, call_next):
    path = request.url.path
    if request.method in WRITE and path.startswith("/api/") and not path.startswith(ALLOWED):
        sub = _sub(request)
        if sub and sub in await demo_ids():
            log.info(f"demo guard: refused {request.method} {path}")
            return JSONResponse({"detail": MESSAGE}, status_code=403)
    return await call_next(request)
