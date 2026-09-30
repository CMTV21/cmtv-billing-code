"""Nuvio accounts on CMTV's own Nuvio server (CMTV local addition 2026-09-29).

The server is the official Nuvio self-host kit at /opt/nuvio-server (https://nuvio.cmtv.info; CMTV additions in
/opt/nuvio-server-cmtv). Billing talks to it directly on the VPS (http://127.0.0.1:8090 with Host nuvio.cmtv.info;
Cloudflare blocks script user agents on the public name). Settings in /opt/backend/.env: NUVIO_ANON_KEY (public),
NUVIO_SERVICE_KEY (admin), NUVIO_JWT_SECRET (to act as one account for the sync_* functions). Never log them.

- Accounts: username + password for the customer; on the server the login is <username>@nuvio.cmtv.info (the CMTV app
  adds the ending). Billing keeps the end date and status in cmtv_nuvio_accounts; the server has no end dates.
- Provisioning: products with cockpit_module "nuviocloud" go through server.py's provision_cockpit_service, which calls
  cockpit_service._call -> handle() here (actions get / create / extend, the same shapes as the Cockpit helper).
- Add-ons: the real add-on links (AIOStreams etc., holding the debrid key) are only in cmtv_config {_id: "nuvio_addons"}.
  Each account gets personal links https://billing.cmtv.info/nv/<token>/<addon>/manifest.json; the relay below looks
  up the account, refuses streams when it's switched off or past its end date (history and profiles stay), forwards
  everything else to the real add-on, and notes which internet connections ask for streams (sharing alert).
- Devices: 4 per account, enforced on the server (cmtv_hooks.password_hook); billing lists and signs out devices.
"""
import asyncio
import logging
import os
import re
import secrets
import time
from datetime import date, datetime, timedelta

import httpx
import jwt
from dateutil.relativedelta import relativedelta
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/cmtv/nuvio", tags=["cmtv-nuvio"])
relay = APIRouter(prefix="/api/cmtv/nv", tags=["cmtv-nuvio-relay"])
D = {}

MODULE = "nuviocloud"
LABEL = "Nuvio"
EMAIL_DOMAIN = "nuvio.cmtv.info"
ADDON_BASE = os.environ.get("NUVIO_ADDON_BASE", "https://billing.cmtv.info/nv")
SHARE_IPS = 3            # this many different internet connections asking for streams within SHARE_WINDOW -> alert
SHARE_WINDOW = timedelta(hours=3)
DEFAULT_MAX_DEVICES = 4
_USER_CHARS = "abcdefghjkmnpqrstuvwxyz23456789"
_PASS_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789"
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_USERNAME = re.compile(r"^[a-z0-9][a-z0-9._-]{2,31}$")
_ENDED_STREAM = {"streams": [{
    "name": "CMTV", "title": "Your CMTV subscription has ended.\nRenew at billing.cmtv.info to keep watching.",
    "externalUrl": "https://billing.cmtv.info/dashboard"}]}


def init(**deps):
    D.update(deps)


def _db():
    return D["db"]


def _rand(chars, n):
    return "".join(secrets.choice(chars) for _ in range(n))


def email_for(username: str) -> str:
    return f"{username.lower()}@{EMAIL_DOMAIN}"


def _today() -> str:
    return date.today().strftime("%Y-%m-%d")


def _end_of_day(day: str) -> datetime:
    return datetime.strptime(day, "%Y-%m-%d").replace(hour=23, minute=59, second=59)


def is_live(acc: dict) -> bool:
    """Streams allowed: switched on and the end date not passed"""
    return bool(acc) and acc.get("status", "active") == "active" and (acc.get("expires") or "") >= _today()


# ---------------------------------------------------------------- the Nuvio server
def _settings():
    s = {"url": os.environ.get("NUVIO_LOCAL_URL", "http://127.0.0.1:8090").rstrip("/"),
         "host": os.environ.get("NUVIO_HOST", EMAIL_DOMAIN),
         "anon": os.environ.get("NUVIO_ANON_KEY", ""), "service": os.environ.get("NUVIO_SERVICE_KEY", ""),
         "jwt": os.environ.get("NUVIO_JWT_SECRET", "")}
    if not (s["anon"] and s["service"] and s["jwt"]):
        raise NuvioError("the Nuvio server isn't set up in billing (NUVIO_* in .env)")
    return s


class NuvioError(Exception):
    pass


def _user_token(s, uid: str) -> str:
    now = int(time.time())
    return jwt.encode({"sub": uid, "role": "authenticated", "aud": "authenticated", "iat": now, "exp": now + 300},
                      s["jwt"], algorithm="HS256")


async def nv(method: str, path: str, body=None, *, as_user: str = "", timeout: int = 30):
    """One call to the Nuvio server. Default = admin (service key); as_user = act as that account. -> (status, data)"""
    s = _settings()
    bearer = _user_token(s, as_user) if as_user else s["service"]
    headers = {"Host": s["host"], "X-Forwarded-Proto": "https", "apikey": s["anon"] if as_user else s["service"],
               "Authorization": f"Bearer {bearer}", "Content-Type": "application/json", "User-Agent": "cmtv-billing"}
    client = D.get("nv_http")
    try:
        if client:
            r = await client.request(method, s["url"] + path, json=body, headers=headers, timeout=timeout)
        else:
            async with httpx.AsyncClient(timeout=timeout) as c:
                r = await c.request(method, s["url"] + path, json=body, headers=headers)
    except httpx.HTTPError as e:
        raise NuvioError(f"couldn't reach the Nuvio server ({type(e).__name__})")
    try:
        data = r.json() if r.content else None
    except ValueError:
        data = r.text[:300]
    return r.status_code, data


def _err(data) -> str:
    if isinstance(data, dict):
        return str(data.get("msg") or data.get("message") or data.get("error_description") or data.get("error") or data)[:200]
    return str(data)[:200]


# ---------------------------------------------------------------- add-ons
async def addon_config() -> list:
    doc = await _db().cmtv_config.find_one({"_id": "nuvio_addons"}) or {}
    return doc.get("addons") or []


def personal_url(token: str, slug: str) -> str:
    return f"{ADDON_BASE}/{token}/{slug}/manifest.json"


CMTV_SLUG = "cmtv"   # 2026-09-30: billing's own built-in add-on ("CMTV" row: your plan, renew, get help)


async def push_addons(acc: dict) -> int:
    """Put the managed add-ons (personal links) on the account's main profile, keeping add-ons the customer added
    themselves. Other profiles share the main profile's add-ons (uses_primary_addons). The CMTV add-on goes last while
    the plan is live and first once it has ended (so "Renew" is the first thing they see)."""
    managed = [a for a in await addon_config() if a.get("enabled", True)]
    st, current = await nv("GET", f"/rest/v1/addons?select=url,name,enabled,sort_order&user_id=eq.{acc['nuvio_id']}"
                                  f"&profile_id=eq.1&order=sort_order")
    if st != 200:
        raise NuvioError(f"reading add-ons failed ({st}: {_err(current)})")
    own = [a for a in (current or []) if not str(a.get("url", "")).startswith(ADDON_BASE + "/")]
    ours = [{"url": personal_url(acc["token"], a["slug"]), "name": a["name"]} for a in managed]
    cmtv = {"url": personal_url(acc["token"], CMTV_SLUG), "name": "CMTV"}
    # 2026-09-30: always first, so the CMTV row is the top row of the home screen (the owner: "buried at the bottom")
    ordered = [cmtv] + ours + own
    rows = [{"url": a["url"], "name": a.get("name") or "", "enabled": a.get("enabled", True), "sort_order": i}
            for i, a in enumerate(ordered)]
    st, data = await nv("POST", "/rest/v1/rpc/sync_push_addons", {"p_profile_id": 1, "p_addons": rows}, as_user=acc["nuvio_id"])
    if st not in (200, 204):
        raise NuvioError(f"pushing add-ons failed ({st}: {_err(data)})")
    await _db().cmtv_nuvio_accounts.update_one({"_id": acc["_id"]}, {"$set": {
        "addons_pushed_at": datetime.utcnow(), "addons_pushed_live": is_live(acc)}})
    return len(managed)


async def _repush(username: str):
    """After a status/end-date change: move the CMTV row (best effort)"""
    acc = await get_account(username)
    if acc:
        try:
            await push_addons(acc)
        except Exception as e:
            logger.warning(f"Nuvio {username}: add-ons not re-sent after a change: {e}")


# ---------------------------------------------------------------- accounts
async def get_account(username: str):
    return await _db().cmtv_nuvio_accounts.find_one({"_id": (username or "").lower(), "deleted": {"$ne": True}})


async def create_account(username: str, password: str, expires: str, notes: str = "") -> dict:
    username = username.lower()
    if not _USERNAME.match(username):
        raise NuvioError("usernames are 3-32 letters/numbers (. _ - allowed)")
    if await _db().cmtv_nuvio_accounts.find_one({"_id": username}):   # deleted ones keep their name retired
        raise NuvioError("already exists")
    st, u = await nv("POST", "/auth/v1/admin/users", {
        "email": email_for(username), "password": password, "email_confirm": True,
        "app_metadata": {"cmtv_username": username}, "user_metadata": {"name": username}})
    if st == 422 and "already" in _err(u).lower():
        raise NuvioError("already exists")
    if st not in (200, 201) or not isinstance(u, dict) or not u.get("id"):
        raise NuvioError(f"creating the account failed ({st}: {_err(u)})")
    acc = {"_id": username, "username": username, "nuvio_id": u["id"], "email": email_for(username), "password": password,
           "expires": expires, "status": "active", "token": secrets.token_urlsafe(18), "notes": notes,
           "created_at": datetime.utcnow(), "updated_at": datetime.utcnow()}
    await _db().cmtv_nuvio_accounts.insert_one(acc)
    try:
        st, data = await nv("POST", "/rest/v1/rpc/sync_push_profiles", {"p_client_max_profiles": 6, "p_profiles": [
            {"profile_index": 1, "name": "Main", "avatar_color_hex": "#1E88E5", "uses_primary_addons": True}]}, as_user=u["id"])
        if st not in (200, 204):
            logger.warning(f"Nuvio {username}: main profile not set up ({st}: {_err(data)})")
        await push_addons(acc)
    except NuvioError as e:   # the account works; add-ons can be pushed again from Admin > Nuvio
        logger.warning(f"Nuvio {username}: set-up after creation incomplete: {e}")
    logger.info(f"Nuvio account created: {username} (until {expires})")
    return acc


async def set_expiry(username: str, expires: str) -> dict:
    await _db().cmtv_nuvio_accounts.update_one({"_id": username.lower()},
                                              {"$set": {"expires": expires, "status": "active", "updated_at": datetime.utcnow()}})
    _cache_drop(username)
    await _repush(username)   # 2026-09-30: CMTV row back to the end after a renewal
    return await get_account(username)


async def handle(request: dict) -> dict:
    """cockpit_service._call for module "nuviocloud": same request/answer shapes as the Cockpit helper"""
    action, username = request.get("action"), (request.get("username") or "").lower()
    try:
        if action == "get":
            acc = await get_account(username)
            return {"success": True, "exists": bool(acc), "expires": (acc or {}).get("expires", "")}
        if action == "create":
            acc = await create_account(username, request["password"], request["expires"], request.get("notes", ""))
            return {"success": True, "expires": acc["expires"], "id": acc["nuvio_id"]}
        if action == "extend":
            if not await get_account(username):
                return {"success": False, "error": f"account {username!r} isn't on the Nuvio server"}
            acc = await set_expiry(username, request["expires"])
            return {"success": True, "expires": acc["expires"]}
        return {"success": False, "error": f"unknown action {action!r}"}
    except NuvioError as e:
        return {"success": False, "error": str(e)}


async def _linked(username: str):
    rx = {"$regex": f"^{re.escape(username)}$", "$options": "i"}
    return [s async for s in D["services"].find({"cockpit_module": MODULE, "username": rx})]


async def _sync_services(username: str, **fields):
    for s in await _linked(username):
        await D["services"].update_one({"_id": s["_id"]}, {"$set": {**fields, "updated_at": datetime.utcnow()}})


# ---------------------------------------------------------------- relay (the add-on links customers get)
_acc_cache = {}     # token -> (fetched_at, account)
_addon_cache = {"at": 0, "by_slug": {}}
_hit_seen = {}      # (token, ip) -> last logged


def _cache_drop(username: str):
    for t, (_, a) in list(_acc_cache.items()):
        if a and a.get("_id") == username.lower():
            _acc_cache.pop(t, None)


async def _account_by_token(token: str):
    hit = _acc_cache.get(token)
    if hit and time.time() - hit[0] < 60:
        return hit[1]
    acc = await _db().cmtv_nuvio_accounts.find_one({"token": token})
    _acc_cache[token] = (time.time(), acc)
    return acc


async def _addon(slug: str):
    if time.time() - _addon_cache["at"] > 60:
        _addon_cache["by_slug"] = {a["slug"]: a for a in await addon_config()}
        _addon_cache["at"] = time.time()
    return _addon_cache["by_slug"].get(slug)


def _client_ip(request: Request) -> str:
    return (request.headers.get("cf-connecting-ip") or request.headers.get("x-real-ip")
            or (request.client.host if request.client else "") or "")[:64]


async def _note_stream(acc: dict, ip: str):
    key, now = (acc["token"], ip), time.time()
    if not ip or now - _hit_seen.get(key, 0) < 600:
        return
    _hit_seen[key] = now
    await _db().cmtv_nuvio_hits.insert_one({"username": acc["_id"], "ip": ip, "at": datetime.utcnow()})


def _upstream_base(addon_url: str):
    """-> (base ending in "/", the add-on's own query). Some add-ons put a tag after manifest.json (Binge Cat:
    ?bcv=3); it's sent along on every request to that add-on (CMTV 2026-09-29)."""
    path, _, query = addon_url.partition("?")
    base = path[: -len("manifest.json")] if path.endswith("manifest.json") else path.rstrip("/") + "/"
    return base, query


async def _relay_get(url: str):
    if not D.get("relay_http"):
        D["relay_http"] = httpx.AsyncClient(timeout=45, follow_redirects=True, headers={"User-Agent": "CMTV-relay"},
                                            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20))
    return await D["relay_http"].get(url)


# nginx passes /nv/... to the backend untouched (no URI rewrite), so encoded ids/searches reach the add-on exactly as
# the app sent them; /api/cmtv/nv/... works too.
short_relay = APIRouter(prefix="/nv", tags=["cmtv-nuvio-relay"])


# ---------------------------------------------------------------- the built-in CMTV add-on (2026-09-30)
# A "CMTV" row on every account's home screen, personal to it: "Your plan" (end date or ended), "Renew" (QR to billing
# with their renewal in the cart) and "Get help" (QR to the support bot). Pictures are drawn here (Pillow + qrcode).
SUPPORT_URL = "https://t.me/Cmtv_support_bot"
SUPPORT_EMAIL = "cmtv@pm.me"
_img_cache = {}   # (token, kind, shape, state) -> png bytes
_FONT_PATHS = ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")


def _font(size: int, bold: bool = True):
    from PIL import ImageFont
    for p in (_FONT_PATHS if bold else _FONT_PATHS[::-1]):
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default(size=size)


async def _cmtv_info(acc: dict) -> dict:
    svc = (await _linked(acc["_id"]) or [None])[0]
    exp = acc.get("expires") or ""
    try:
        exp_txt = datetime.strptime(exp, "%Y-%m-%d").strftime("%b %-d, %Y")
    except ValueError:
        exp_txt = exp
    live = is_live(acc)
    return {"live": live, "expires": exp_txt, "off": acc.get("status") == "off",
            "renew_url": f"https://billing.cmtv.info/dashboard?renew={svc['_id']}" if svc else "https://billing.cmtv.info/?tab=addons",
            "state": f"{int(live)}:{exp}:{acc.get('status')}:{bool(svc)}"}


def _draw(kind: str, shape: str, info: dict, username: str) -> bytes:
    """background (16:9, text + QR) = the tile in the row (the app shows rows landscape); backdrop (16:9, no text)
    = the big picture behind the app's own title on the detail/hero view; poster (2:3) kept for other apps"""
    import io
    import qrcode
    from PIL import Image, ImageDraw
    w, h = (600, 900) if shape == "poster" else (1280, 720)
    im = Image.new("RGB", (w, h), (10, 16, 32))
    d = ImageDraw.Draw(im)
    if shape == "backdrop":   # smooth shade, darkest on the left where the app puts its text
        for x in range(w):
            t = x / w
            d.line([(x, 0), (x, h)], fill=(int(10 + 4 * t), int(16 + 16 * t), int(32 + 34 * t)))
    for i, c in enumerate([(34, 230, 242), (46, 139, 255), (139, 92, 246), (236, 72, 153)]):   # the CMTV colour line
        d.rectangle([i * w // 4, 0, (i + 1) * w // 4, 8], fill=c)
    if shape == "backdrop":
        # the app draws its title, text and logo over the left side: keep that plain, big QR on the right
        url = {"renew": info["renew_url"], "help": SUPPORT_URL}.get(kind)
        if url:
            q = qrcode.QRCode(border=2, box_size=10)
            q.add_data(url)
            q.make(fit=True)
            img = q.make_image(fill_color="black", back_color="white").convert("RGB").resize((400, 400))
            im.paste(img, (w - 460, 150))
            cap = "Scan to renew" if kind == "renew" else "Scan to message us"
            d.text((w - 260, 585), cap, font=_font(30), fill=(34, 230, 242), anchor="mm")
        out = io.BytesIO()
        im.save(out, "PNG", optimize=True)
        return out.getvalue()
    try:
        logo = Image.open("/opt/frontend/public/cmtv/cmtv-logo.png").convert("RGBA")
        side = 110 if shape == "poster" else 96
        im.paste(logo.resize((side, side)), (40, 40), logo.resize((side, side)))
    except Exception:
        pass
    ended = not info["live"]
    title = {"plan": "Your plan", "renew": "Renew", "help": "Get help"}[kind]
    if kind == "plan":
        line = "Switched off" if info["off"] else ("Ended " + info["expires"] if ended else "Active until " + info["expires"])
        sub = "Renew to keep watching" if ended else f"Signed in as {username}"
        qr_url = None
    elif kind == "renew":
        line, sub, qr_url = "Scan with your phone", "billing.cmtv.info", info["renew_url"]
    else:
        line, sub, qr_url = "Scan to message us", f"Telegram · {SUPPORT_EMAIL}", SUPPORT_URL
    colour = (255, 120, 140) if (kind == "plan" and ended) else (34, 230, 242)
    if shape == "poster":
        d.text((40, 190), title, font=_font(64), fill=(233, 237, 248))
        d.text((40, 275), line, font=_font(30), fill=colour)
        d.text((40, 318), sub, font=_font(26, False), fill=(160, 170, 195))
        box = (100, 400, 500, 800)
    else:
        d.text((60, 190), title, font=_font(84), fill=(233, 237, 248))
        d.text((60, 300), line, font=_font(40), fill=colour)
        d.text((60, 356), sub, font=_font(32, False), fill=(160, 170, 195))
        box = (820, 200, 1200, 580)
    if qr_url:
        q = qrcode.QRCode(border=2, box_size=10)
        q.add_data(qr_url)
        q.make(fit=True)
        img = q.make_image(fill_color="black", back_color="white").convert("RGB").resize((box[2] - box[0], box[3] - box[1]))
        im.paste(img, box[:2])
    elif kind == "plan":
        d.rounded_rectangle(box, radius=30, outline=colour, width=6)
        d.text(((box[0] + box[2]) // 2, (box[1] + box[3]) // 2), "!" if ended else "OK", font=_font(120), fill=colour, anchor="mm")
    out = io.BytesIO()
    im.save(out, "PNG", optimize=True)
    return out.getvalue()


async def _cmtv_addon(acc: dict, token: str, rest: str):
    cors = {"Access-Control-Allow-Origin": "*"}
    base = f"{ADDON_BASE}/{token}/{CMTV_SLUG}"
    info = await _cmtv_info(acc)
    ver = hashlib_md5(info["state"])
    items = [("plan", "Your plan"), ("renew", "Renew your plan"), ("help", "Get help")]
    if not info["live"]:
        items = [items[1], items[0], items[2]]

    def meta(kind, name):
        desc = {"plan": ("Your CMTV plan has ended. Renew to keep watching: scan the Renew tile with your phone."
                         if not info["live"] else f"Your CMTV plan is active until {info['expires']}."),
                "renew": f"Scan the code with your phone to renew, or go to billing.cmtv.info and sign in. "
                         f"Your plan {'ended' if not info['live'] else 'runs until'} {info['expires']}.",
                "help": f"Questions or problems? Scan the code to message CMTV Support on Telegram, or email {SUPPORT_EMAIL}."}[kind]
        # 2026-09-30 after the owner's TV test: wide tile with the text + QR, plain backdrop behind the app's own title,
        # no genre/year labels ("Movie • CMTV • CMTV")
        return {"id": f"cmtv:{kind}", "type": "movie", "name": name, "description": desc, "posterShape": "landscape",
                "poster": f"{base}/img/{kind}-background-{ver}.png", "background": f"{base}/img/{kind}-backdrop-{ver}.png",
                "logo": "https://billing.cmtv.info/cmtv/cmtv-logo.png"}
    if rest == "manifest.json":
        return JSONResponse({"id": "info.cmtv.account", "version": "1.0.0", "name": "CMTV",
                             "description": "Your CMTV plan, renewals and support.", "logo": "https://billing.cmtv.info/cmtv/cmtv-logo.png",
                             "resources": ["catalog", "meta", "stream"], "types": ["movie"], "idPrefixes": ["cmtv:"],
                             "catalogs": [{"type": "movie", "id": "cmtv-account", "name": "CMTV · Your account"}],
                             "behaviorHints": {"configurable": False, "configurationRequired": False}},
                            headers={**cors, "Cache-Control": "max-age=3600"})
    if rest.startswith("catalog/movie/cmtv-account"):
        return JSONResponse({"metas": [meta(k, n) for k, n in items]}, headers={**cors, "Cache-Control": "no-store"})
    m = re.match(r"^(meta|stream)/movie/cmtv(?::|%3A)(plan|renew|help)\.json$", rest)
    if m:
        kind = m.group(2)
        if m.group(1) == "meta":
            return JSONResponse({"meta": meta(kind, dict(items)[kind])}, headers={**cors, "Cache-Control": "no-store"})
        url = info["renew_url"] if kind != "help" else SUPPORT_URL
        return JSONResponse({"streams": [{"name": "CMTV", "title": ("Renew at billing.cmtv.info" if kind != "help" else
                             f"CMTV Support: Telegram or {SUPPORT_EMAIL}"), "externalUrl": url}]}, headers={**cors, "Cache-Control": "no-store"})
    m = re.match(r"^img/(plan|renew|help)-(poster|background|backdrop)-[0-9a-f]+\.png$", rest)
    if m:
        key = (token, m.group(1), m.group(2), info["state"])
        png = _img_cache.get(key)
        if not png:
            png = await asyncio.to_thread(_draw, m.group(1), m.group(2), info, acc["_id"])
            if len(_img_cache) > 500:
                _img_cache.clear()
            _img_cache[key] = png
        return Response(content=png, media_type="image/png", headers={**cors, "Cache-Control": "max-age=3600"})
    if rest.startswith(("meta/", "stream/", "catalog/", "subtitles/")):
        return JSONResponse({"metas": []} if rest.startswith("catalog/") else {"streams": []} if rest.startswith("stream/")
                            else {"subtitles": []} if rest.startswith("subtitles/") else {"meta": None}, headers=cors)
    return JSONResponse({"error": "not found"}, status_code=404, headers=cors)


def hashlib_md5(s: str) -> str:
    import hashlib
    return hashlib.md5(s.encode()).hexdigest()[:10]


@short_relay.get("/{token}/{slug}/{rest:path}")
@relay.get("/{token}/{slug}/{rest:path}")
async def relay_get(token: str, slug: str, rest: str, request: Request):
    raw = (request.scope.get("raw_path") or b"").decode("latin-1")
    marker = f"/{token}/{slug}/"
    rest = raw.split(marker, 1)[1] if marker in raw else rest
    cors = {"Access-Control-Allow-Origin": "*"}
    acc = await _account_by_token(token)
    if slug == CMTV_SLUG:
        if not acc:
            return JSONResponse({"error": "not found"}, status_code=404, headers=cors)
        return await _cmtv_addon(acc, token, rest)
    addon = await _addon(slug)
    if not acc or not addon or not addon.get("enabled", True):
        return JSONResponse({"error": "not found"}, status_code=404, headers=cors)
    is_stream = rest.startswith("stream/")
    if is_stream:
        if not is_live(acc):
            info = await _cmtv_info(acc)   # 2026-09-30: their own renew link + where the Renew code is
            ended = {"streams": [{"name": "CMTV", "externalUrl": info["renew_url"], "title":
                     "Your CMTV subscription has ended.\nRenew: open the CMTV row on your home screen and scan the Renew code,\n"
                     "or sign in at billing.cmtv.info. Need help? Scan Get help in the same row."}]}
            return JSONResponse(ended, headers={**cors, "Cache-Control": "no-store"})
        try:
            await _note_stream(acc, _client_ip(request))
        except Exception as e:
            logger.warning(f"Nuvio relay: couldn't note a stream request: {e}")
    if rest.startswith("subtitles/") and not is_live(acc):
        return JSONResponse({"subtitles": []}, headers=cors)
    base, addon_query = _upstream_base(addon["url"])
    query = "&".join(q for q in (addon_query, request.scope.get("query_string", b"").decode("latin-1")) if q)
    url = base + rest + (("?" + query) if query else "")
    try:
        r = await _relay_get(url)
    except httpx.HTTPError as e:
        logger.warning(f"Nuvio relay: {addon['name']} unreachable ({type(e).__name__})")
        if is_stream:
            return JSONResponse({"streams": []}, headers={**cors, "Cache-Control": "no-store"})
        return JSONResponse({"error": "add-on unreachable"}, status_code=502, headers=cors)
    headers = {**cors, "Cache-Control": "no-store" if is_stream else r.headers.get("cache-control", "max-age=300")}
    ctype = r.headers.get("content-type", "application/json")
    if rest == "manifest.json" and r.status_code == 200:
        try:
            m = r.json()
            # hide the add-on's own settings page (its address carries the real configuration)
            m["behaviorHints"] = {**(m.get("behaviorHints") or {}), "configurable": False, "configurationRequired": False}
            for k in ("logo", "background"):
                if isinstance(m.get(k), str) and m[k].startswith(base):
                    m[k] = f"{ADDON_BASE}/{token}/{slug}/" + m[k][len(base):]
            return JSONResponse(m, headers=headers)
        except ValueError:
            pass
    content = r.content
    if not is_stream and b"json" in ctype.encode() and base.encode() in content:
        content = content.replace(base.encode(), f"{ADDON_BASE}/{token}/{slug}/".encode())
    return Response(content=content, status_code=r.status_code, media_type=ctype.split(";")[0], headers=headers)


# ---------------------------------------------------------------- sharing alert (hourly)
async def share_check():
    since = datetime.utcnow() - SHARE_WINDOW
    pipeline = [{"$match": {"at": {"$gte": since}}},
                {"$group": {"_id": "$username", "ips": {"$addToSet": "$ip"}}},
                {"$match": {f"ips.{SHARE_IPS - 1}": {"$exists": True}}}]
    found = []
    async for row in _db().cmtv_nuvio_hits.aggregate(pipeline):
        username, ips = row["_id"], row["ips"]
        state = await _db().cmtv_nuvio_share.find_one({"_id": username}) or {}
        if state.get("alerted_at") and datetime.utcnow() - state["alerted_at"] < timedelta(hours=24):
            continue
        await _db().cmtv_nuvio_share.update_one({"_id": username}, {"$set": {"alerted_at": datetime.utcnow(), "ips": ips},
                                                                  "$inc": {"count": 1}}, upsert=True)
        found.append(username)
        who = ""
        svc = (await _linked(username) or [None])[0]
        if svc:
            u = await D["users"].find_one({"_id": _oid(svc.get("user_id"))}, {"name": 1, "email": 1})
            who = f" ({(u or {}).get('name') or ''} {(u or {}).get('email') or ''})".rstrip(" ()")
        try:
            import cmtv_notify
            await cmtv_notify.ops(f"👀 Nuvio: <b>{username}</b>{who} asked for streams from {len(ips)} different internet "
                                  f"connections in the last {int(SHARE_WINDOW.total_seconds() // 3600)} h. Possibly shared. "
                                  f"Admin > Nuvio shows the account.", "billing", silent=True)
        except Exception as e:
            logger.warning(f"Nuvio share alert not sent: {e}")
    return found


def _oid(v):
    from bson import ObjectId
    return ObjectId(v) if ObjectId.is_valid(str(v)) else None


async def repair_addons() -> list:
    """Hourly (CMTV 2026-09-29): the app lets customers remove add-ons, and ours look like any other there (the owner's
    own test removed them while tidying up). Put back any managed add-on missing from a live account's main profile;
    the customer's own add-ons are kept (push_addons)."""
    managed = [a for a in await addon_config() if a.get("enabled", True)]
    fixed = []
    async for acc in _db().cmtv_nuvio_accounts.find({"deleted": {"$ne": True}}):
        live = is_live(acc)
        # 2026-09-30: ended accounts are checked too, so their CMTV row moves to the top when the end date passes
        if not live and acc.get("addons_pushed_live") is False:
            continue
        want = {personal_url(acc["token"], a["slug"]) for a in managed} | {personal_url(acc["token"], CMTV_SLUG)}
        st, rows = await nv("GET", f"/rest/v1/addons?select=url&user_id=eq.{acc['nuvio_id']}&profile_id=eq.1&order=sort_order")
        if st != 200:
            continue
        cmtv_first = bool(rows) and rows[0].get("url") == personal_url(acc["token"], CMTV_SLUG)
        if (want - {r.get("url") for r in rows or []}) or acc.get("addons_pushed_live") != live or not cmtv_first:
            await push_addons(acc)
            await _db().cmtv_nuvio_accounts.update_one({"_id": acc["_id"]}, {"$inc": {"addons_repaired": 1},
                                                                            "$set": {"addons_repaired_at": datetime.utcnow()}})
            fixed.append(acc["_id"])
        await asyncio.sleep(0.1)
    if fixed:
        logger.info(f"Nuvio: put missing add-ons back on {len(fixed)} account(s): {', '.join(fixed[:10])}")
    return fixed


async def _loop():
    await asyncio.sleep(120)
    while True:
        for job in (share_check, repair_addons):
            try:
                await job()
            except Exception as e:
                logger.error(f"Nuvio {job.__name__} failed: {e}")
        await asyncio.sleep(3600)


async def startup():
    db = _db()
    await db.cmtv_nuvio_accounts.create_index("token", unique=True)
    await db.cmtv_nuvio_hits.create_index("at", expireAfterSeconds=3 * 24 * 3600)
    await db.cmtv_nuvio_hits.create_index([("username", 1), ("at", -1)])
    asyncio.create_task(_loop())


# ---------------------------------------------------------------- app updates (2026-09-29)
# Our app build (info.cmtv.nuvio, rev 3+) asks billing instead of GitHub for updates, in GitHub's release format:
# GET /api/cmtv/app-updates/repos/cmtv/nuvio-tv/releases/latest (+ /releases for its "beta" channel). Only a build the
# owner publishes in Admin > Nuvio > App is offered; its APKs are copied to PUB_DIR, served by nginx at /app-files/.
updates = APIRouter(prefix="/api/cmtv/app-updates", tags=["cmtv-nuvio-updates"])
APP_OUT = os.environ.get("NUVIO_APP_OUT", "/opt/nuvio-build/out")
APP_PUB = os.environ.get("NUVIO_APP_PUB", "/var/www/cmtv-app/nuvio")
APP_FILES_URL = os.environ.get("NUVIO_APP_FILES_URL", "https://billing.cmtv.info/app-files/nuvio")
SOURCE_URL = "https://github.com/CMTV21/Nuvio-tv-cmtv"
_BUILD = re.compile(r"^Nuvio-CMTV-(?P<v>\d+\.\d+\.\d+-cmtv\.\d+)-(?P<abi>arm64-v8a|armeabi-v7a|x86_64|x86|universal)\.apk$")


def app_builds() -> dict:
    """{version: {abi: {name, size, built_at}}} from the build folder"""
    out = {}
    if os.path.isdir(APP_OUT):
        for name in os.listdir(APP_OUT):
            m = _BUILD.match(name)
            if m:
                st = os.stat(os.path.join(APP_OUT, name))
                out.setdefault(m["v"], {})[m["abi"]] = {"name": name, "size": st.st_size,
                                                       "built_at": datetime.utcfromtimestamp(st.st_mtime)}
    return out


def _version_key(v: str):
    m = re.match(r"(\d+)\.(\d+)\.(\d+)-cmtv\.(\d+)", v)
    return tuple(int(x) for x in m.groups()) if m else (0, 0, 0, 0)


async def published_release():
    return await _db().cmtv_config.find_one({"_id": "nuvio_app_release"})


def _release_json(rel: dict) -> dict:
    return {"tag_name": rel["tag"], "name": rel.get("name") or f"Nuvio for CMTV {rel['tag']}", "body": rel.get("notes") or "",
            "draft": False, "prerelease": False, "html_url": SOURCE_URL,
            "assets": [{"name": a["name"], "browser_download_url": a["url"], "size": a["size"],
                        "content_type": "application/vnd.android.package-archive"} for a in rel.get("assets", [])]}


@updates.get("/repos/{owner}/{repo}/releases/latest")
async def update_latest(owner: str, repo: str):
    rel = await published_release()
    if not rel or (owner, repo) != ("cmtv", "nuvio-tv"):
        return JSONResponse({"message": "Not Found"}, status_code=404)
    return JSONResponse(_release_json(rel), headers={"Cache-Control": "no-store"})


@updates.get("/repos/{owner}/{repo}/releases")
async def update_list(owner: str, repo: str):
    rel = await published_release()
    if (owner, repo) != ("cmtv", "nuvio-tv"):
        return JSONResponse({"message": "Not Found"}, status_code=404)
    return JSONResponse([_release_json(rel)] if rel else [], headers={"Cache-Control": "no-store"})


def _publish_files(version: str, files: dict) -> list:
    import hashlib
    import shutil
    dest = os.path.join(APP_PUB, version)
    os.makedirs(dest, exist_ok=True)
    assets = []
    for abi, f in sorted(files.items()):
        src, dst = os.path.join(APP_OUT, f["name"]), os.path.join(dest, f["name"])
        if not os.path.exists(dst) or os.path.getsize(dst) != f["size"]:
            shutil.copyfile(src, dst + ".part")
            os.replace(dst + ".part", dst)
        h = hashlib.sha256()
        with open(dst, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        assets.append({"abi": abi, "name": f["name"], "size": f["size"], "sha256": h.hexdigest(),
                       "url": f"{APP_FILES_URL}/{version}/{f['name']}"})
    return assets


# ---------------------------------------------------------------- admin
def _new_expiry(current: str, months: int = 0, expiry_date: str = "") -> str:
    if expiry_date:
        if not _DATE.match(expiry_date):
            raise HTTPException(400, "Date must be YYYY-MM-DD")
        return expiry_date
    if months not in (1, 3, 6, 12, 24):
        raise HTTPException(400, "Choose 1, 3, 6, 12 or 24 months")
    try:
        base = max(date.today(), datetime.strptime(current or "", "%Y-%m-%d").date())
    except ValueError:
        base = date.today()
    return (base + relativedelta(months=months)).strftime("%Y-%m-%d")


async def _must(username: str) -> dict:
    acc = await get_account(username)
    if not acc:
        raise HTTPException(404, f"{username} isn't on the Nuvio server")
    return acc


def _http(e: NuvioError):
    return HTTPException(502, f"Nuvio server: {e}")


def _slug(name: str, taken: set) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", (name or "addon").lower()).strip("-")[:20] or "addon"
    slug = base
    while slug in taken:
        slug = f"{base}-{secrets.token_hex(2)}"
    return slug


def init_routes():
    admin = D["get_current_admin_user"]
    customer = D["get_current_user"]

    # ---- the customer's own devices (dashboard, 2026-09-29): only accounts linked to one of their services
    async def _own(username: str, current_user: dict) -> dict:
        rx = {"$regex": f"^{re.escape(username)}$", "$options": "i"}
        svc = await D["services"].find_one({"user_id": str(current_user.get("_id") or current_user.get("id")),
                                             "cockpit_module": MODULE, "username": rx})
        acc = await get_account(username) if svc else None
        if not acc:
            raise HTTPException(404, "Not your account")
        return acc

    @router.get("/mine/{username}/devices")
    async def my_devices(username: str, current_user: dict = Depends(customer)):
        acc = await _own(username, current_user)
        try:
            st, data = await nv("POST", "/rest/v1/rpc/cmtv_devices", {"p_user": acc["nuvio_id"]})
        except NuvioError:
            raise HTTPException(502, "Couldn't reach the Nuvio server, try again in a minute")
        keep = ("session_id", "signed_in_at", "last_used_at", "counts", "app", "platform", "device")
        devices = [{k: d.get(k) for k in keep} for d in (data if st == 200 and isinstance(data, list) else [])]
        return {"devices": devices, "max_devices": acc.get("max_devices") or DEFAULT_MAX_DEVICES,
                "in_use": sum(1 for d in devices if d.get("counts"))}

    @router.post("/mine/{username}/devices/sign-out")
    async def my_sign_out(username: str, body: dict, current_user: dict = Depends(customer)):
        acc = await _own(username, current_user)
        if not body.get("session_id"):
            raise HTTPException(400, "Choose a device")
        try:
            st, n = await nv("POST", "/rest/v1/rpc/cmtv_sign_out", {"p_user": acc["nuvio_id"], "p_session": body["session_id"]})
        except NuvioError:
            raise HTTPException(502, "Couldn't reach the Nuvio server, try again in a minute")
        if st != 200:
            raise HTTPException(502, "That didn't work, try again in a minute")
        return {"signed_out": n}

    @router.get("/addons")
    async def get_addons(current_user: dict = Depends(admin)):
        return {"addons": await addon_config(), "base": ADDON_BASE}

    @router.put("/addons")
    async def put_addons(body: dict, current_user: dict = Depends(admin)):
        """[{slug?, name, url, enabled}] in the order customers should see them. A slug never changes once made
        (customers' links contain it); a removed add-on's links stop working."""
        old = {a["slug"]: a for a in await addon_config()}
        taken, out = set(), []
        for a in body.get("addons") or []:
            name, url = (a.get("name") or "").strip()[:60], (a.get("url") or "").strip()
            if not name or not re.match(r"^https://[^\s?#]+/manifest\.json(\?[^\s#]*)?$", url):
                raise HTTPException(400, f"{name or 'An add-on'}: the link must start with https:// and contain /manifest.json")
            slug = a.get("slug") if a.get("slug") in old else _slug(name, set(old) | taken)
            taken.add(slug)
            out.append({"slug": slug, "name": name, "url": url, "enabled": bool(a.get("enabled", True))})
        await _db().cmtv_config.update_one({"_id": "nuvio_addons"}, {"$set": {
            "addons": out, "updated_at": datetime.utcnow(), "updated_by": current_user.get("email")}}, upsert=True)
        _addon_cache["at"] = 0
        return {"addons": out}

    @router.post("/addons/push-all")
    async def push_all(current_user: dict = Depends(admin)):
        accs = [a async for a in _db().cmtv_nuvio_accounts.find({"deleted": {"$ne": True}})]

        async def run():
            done = failed = 0
            for a in accs:
                try:
                    await push_addons(a)
                    done += 1
                except Exception as e:
                    failed += 1
                    logger.warning(f"Nuvio push add-ons {a['_id']}: {e}")
                await asyncio.sleep(0.2)
            logger.info(f"Nuvio push add-ons to all: {done} done, {failed} failed")
        asyncio.create_task(run())
        return {"started": True, "accounts": len(accs)}

    @router.get("/accounts")
    async def list_accounts(current_user: dict = Depends(admin)):
        accs = [a async for a in _db().cmtv_nuvio_accounts.find({"deleted": {"$ne": True}}).sort("created_at", -1)]
        summary = {}
        if accs:
            try:
                st, summary = await nv("POST", "/rest/v1/rpc/cmtv_summary", {"p_users": [a["nuvio_id"] for a in accs]})
                summary = summary if st == 200 and isinstance(summary, dict) else {}
            except NuvioError:
                summary = {}
        owners = {}
        async for s in D["services"].find({"cockpit_module": MODULE}):
            owners.setdefault((s.get("username") or "").lower(), s)
        users = {}
        ids = [_oid(s.get("user_id")) for s in owners.values() if _oid(s.get("user_id"))]
        async for u in D["users"].find({"_id": {"$in": ids}}, {"name": 1, "email": 1}):
            users[str(u["_id"])] = u
        shares = {x["_id"]: x async for x in _db().cmtv_nuvio_share.find({})}
        out = []
        for a in accs:
            svc = owners.get(a["_id"])
            u = users.get(str((svc or {}).get("user_id"))) if svc else None
            sm = summary.get(a["nuvio_id"], {})
            sh = shares.get(a["_id"])
            out.append({"username": a["_id"], "expires": a.get("expires"), "status": a.get("status", "active"),
                        "live": is_live(a), "max_devices": a.get("max_devices") or DEFAULT_MAX_DEVICES,
                        "devices": sm.get("devices", 0), "last_seen": sm.get("last_seen"), "profiles": sm.get("profiles", 0),
                        "watched": sm.get("watched", 0), "in_progress": sm.get("in_progress", 0),
                        "notes": a.get("notes", ""), "created_at": a.get("created_at"),
                        "customer": {"id": str(u["_id"]), "name": u.get("name"), "email": u.get("email")} if u else None,
                        "service_id": str(svc["_id"]) if svc else None,
                        "share_alert": {"at": sh.get("alerted_at"), "ips": len(sh.get("ips") or []), "count": sh.get("count", 0)} if sh else None})
        return {"accounts": out, "server_ok": bool(summary) or not accs}

    @router.get("/accounts/{username}/password")
    async def show_password(username: str, current_user: dict = Depends(admin)):
        return {"password": (await _must(username)).get("password", "")}

    @router.post("/accounts")
    async def admin_create(body: dict, current_user: dict = Depends(admin)):
        """New account (optionally for a customer: billing service + login email)"""
        username = (body.get("username") or "").strip().lower() or _rand(_USER_CHARS, 9)
        password = (body.get("password") or "").strip() or _rand(_PASS_CHARS, 10)
        if len(password) < 4:
            raise HTTPException(400, "Password: at least 4 characters")
        expires = _new_expiry("", int(body.get("months") or 0), body.get("expiry_date") or "")
        try:
            await create_account(username, password, expires, notes=(body.get("notes") or "")[:200])
        except NuvioError as e:
            raise HTTPException(409 if "already" in str(e) else 502, str(e))
        service_id = None
        if body.get("user_id"):
            user = await D["users"].find_one({"_id": _oid(body["user_id"])})
            if not user:
                raise HTTPException(404, "Customer not found (the account was made without one)")
            product = await D["products"].find_one({"cockpit_module": MODULE, "is_trial": {"$ne": True}}) or {}
            res = await D["services"].insert_one({
                "user_id": str(user["_id"]), "order_id": None, "product_id": str(product.get("_id", "")),
                "product_name": product.get("name", "Nuvio"), "account_type": "subscriber", "panel_type": "manual",
                "panel_name": "CMTV Nuvio server", "cockpit_module": MODULE, "username": username, "password": password,
                "xtream_username": username, "xtream_password": password, "term_months": 12, "max_connections": 0,
                "setup_instructions": product.get("setup_instructions", ""), "start_date": datetime.utcnow(),
                "expiry_date": _end_of_day(expires), "status": "active", "created_at": datetime.utcnow(),
                "cmtv_note": f"Made in Admin > Nuvio by {current_user.get('email')}"})
            service_id = str(res.inserted_id)
            if body.get("send_email") and not (user.get("email") or "").endswith("@panel.local"):
                try:
                    es = await D["get_email_service"]()
                    await es.send_cockpit_account(customer_email=user["email"], customer_name=user.get("name", ""),
                                                  service_name=product.get("name", "Nuvio"), username=username,
                                                  password=password, expiry_date=expires,
                                                  setup_instructions=product.get("setup_instructions", ""),
                                                  customer_id=str(user["_id"]))
                except Exception as e:
                    logger.warning(f"Nuvio login email for {username} failed: {e}")
        return {"username": username, "password": password, "expires": expires, "service_id": service_id}

    @router.post("/accounts/{username}/extend")
    async def extend(username: str, body: dict, current_user: dict = Depends(admin)):
        acc = await _must(username)
        expires = _new_expiry(acc.get("expires"), int(body.get("months") or 0), body.get("expiry_date") or "")
        await set_expiry(username, expires)
        await _sync_services(username, expiry_date=_end_of_day(expires), status="active")
        return {"expires": expires}

    @router.post("/accounts/{username}/disable")
    async def disable(username: str, current_user: dict = Depends(admin)):
        await _must(username)
        await _db().cmtv_nuvio_accounts.update_one({"_id": username.lower()}, {"$set": {
            "status": "off", "switched_off_at": datetime.utcnow(), "updated_at": datetime.utcnow()}})
        _cache_drop(username)
        await _sync_services(username, status="suspended")
        await _repush(username)
        return {"status": "off"}

    @router.post("/accounts/{username}/enable")
    async def enable(username: str, current_user: dict = Depends(admin)):
        acc = await _must(username)
        await _db().cmtv_nuvio_accounts.update_one({"_id": username.lower()}, {"$set": {"status": "active", "updated_at": datetime.utcnow()}})
        _cache_drop(username)
        await _repush(username)
        await _sync_services(username, status="active" if (acc.get("expires") or "") >= _today() else "expired")
        return {"status": "active", "live": (acc.get("expires") or "") >= _today()}

    @router.post("/accounts/{username}/password")
    async def new_password(username: str, body: dict, current_user: dict = Depends(admin)):
        acc = await _must(username)
        password = (body.get("password") or "").strip() or _rand(_PASS_CHARS, 10)
        if len(password) < 4:
            raise HTTPException(400, "Password: at least 4 characters")
        try:
            st, data = await nv("PUT", f"/auth/v1/admin/users/{acc['nuvio_id']}", {"password": password})
        except NuvioError as e:
            raise _http(e)
        if st != 200:
            raise HTTPException(502, f"Nuvio server: {_err(data)}")
        await _db().cmtv_nuvio_accounts.update_one({"_id": acc["_id"]}, {"$set": {"password": password, "updated_at": datetime.utcnow()}})
        await _sync_services(username, password=password, xtream_password=password)
        return {"password": password}

    @router.get("/accounts/{username}/devices")
    async def devices(username: str, current_user: dict = Depends(admin)):
        acc = await _must(username)
        try:
            st, data = await nv("POST", "/rest/v1/rpc/cmtv_devices", {"p_user": acc["nuvio_id"]})
        except NuvioError as e:
            raise _http(e)
        hits = [h async for h in _db().cmtv_nuvio_hits.find({"username": acc["_id"]}).sort("at", -1).limit(50)]
        places = {}
        for h in hits:
            places.setdefault(h["ip"], h["at"])
        return {"devices": data if st == 200 else [], "max_devices": acc.get("max_devices") or DEFAULT_MAX_DEVICES,
                "connections": [{"ip": ip, "last": at} for ip, at in places.items()]}

    @router.post("/accounts/{username}/devices/sign-out")
    async def sign_out(username: str, body: dict, current_user: dict = Depends(admin)):
        acc = await _must(username)
        try:
            st, n = await nv("POST", "/rest/v1/rpc/cmtv_sign_out", {"p_user": acc["nuvio_id"], "p_session": body.get("session_id")})
        except NuvioError as e:
            raise _http(e)
        if st != 200:
            raise HTTPException(502, f"Nuvio server: {_err(n)}")
        return {"signed_out": n}

    @router.post("/accounts/{username}/max-devices")
    async def max_devices(username: str, body: dict, current_user: dict = Depends(admin)):
        acc = await _must(username)
        n = int(body.get("max_devices") or DEFAULT_MAX_DEVICES)
        if not 1 <= n <= 10:
            raise HTTPException(400, "1 to 10 devices")
        try:
            st, data = await nv("PUT", f"/auth/v1/admin/users/{acc['nuvio_id']}", {"app_metadata": {"cmtv_max_devices": n}})
        except NuvioError as e:
            raise _http(e)
        if st != 200:
            raise HTTPException(502, f"Nuvio server: {_err(data)}")
        await _db().cmtv_nuvio_accounts.update_one({"_id": acc["_id"]}, {"$set": {"max_devices": n}})
        return {"max_devices": n}

    @router.post("/accounts/{username}/push-addons")
    async def push_one(username: str, current_user: dict = Depends(admin)):
        acc = await _must(username)
        try:
            return {"addons": await push_addons(acc)}
        except NuvioError as e:
            raise _http(e)

    @router.post("/accounts/{username}/new-links")
    async def new_links(username: str, current_user: dict = Depends(admin)):
        """New personal add-on links (the old ones stop working), e.g. after they were shared"""
        acc = await _must(username)
        token = secrets.token_urlsafe(18)
        await _db().cmtv_nuvio_accounts.update_one({"_id": acc["_id"]}, {"$set": {"token": token, "token_changed_at": datetime.utcnow()}})
        _cache_drop(username)
        try:
            await push_addons({**acc, "token": token})
        except NuvioError as e:
            raise _http(e)
        return {"ok": True}

    @router.post("/accounts/{username}/delete")
    async def delete(username: str, body: dict, current_user: dict = Depends(admin)):
        """Wipe (profiles, add-ons, history) and remove the account on the server. Billing keeps a copy."""
        acc = await _must(username)
        if (body.get("confirm") or "").lower() != acc["_id"]:
            raise HTTPException(400, "Type the username to confirm")
        try:
            st, profiles = await nv("POST", "/rest/v1/rpc/sync_pull_profiles", {}, as_user=acc["nuvio_id"])
            for p in (profiles if st == 200 and isinstance(profiles, list) else []):
                await nv("POST", "/rest/v1/rpc/sync_delete_profile_data", {"p_profile_id": p.get("profile_index")}, as_user=acc["nuvio_id"])
            await nv("POST", "/rest/v1/rpc/cmtv_sign_out", {"p_user": acc["nuvio_id"], "p_session": None})
            st, data = await nv("DELETE", f"/auth/v1/admin/users/{acc['nuvio_id']}")
        except NuvioError as e:
            raise _http(e)
        if st not in (200, 204, 404):
            raise HTTPException(502, f"Nuvio server: {_err(data)}")
        services = await _linked(acc["_id"])
        await _db().cmtv_deleted_accounts.insert_one({"kind": "nuvio", "module": MODULE, "username": acc["_id"], "row": acc,
                                                      "billing_services": services, "by": current_user.get("email"),
                                                      "at": datetime.utcnow()})
        await _db().cmtv_nuvio_accounts.update_one({"_id": acc["_id"]}, {"$set": {
            "deleted": True, "status": "off", "deleted_at": datetime.utcnow(), "token": "deleted-" + secrets.token_hex(8)}})
        _cache_drop(username)
        await _sync_services(acc["_id"], status="terminated", cockpit_deleted_at=datetime.utcnow())
        return {"deleted": acc["_id"]}

    @router.get("/app")
    async def app_status(current_user: dict = Depends(admin)):
        rel = await published_release()
        builds = app_builds()
        return {"published": rel, "builds": [
            {"version": v, "abis": sorted(files), "size": max(f["size"] for f in files.values()),
             "built_at": max(f["built_at"] for f in files.values()), "published": bool(rel and rel["tag"] == v),
             "updater": _version_key(v) >= (1, 0, 0, 3)}
            for v, files in sorted(builds.items(), key=lambda kv: _version_key(kv[0]), reverse=True)]}

    @router.post("/app/publish")
    async def app_publish(body: dict, current_user: dict = Depends(admin)):
        """Offer this build to every CMTV Nuvio app (and give its download links). Publishing an older build is a
        rollback for new installs; apps already on a newer version stay on it."""
        version = (body.get("version") or "").strip()
        files = app_builds().get(version)
        if not files:
            raise HTTPException(404, "That build isn't in the build folder")
        assets = await asyncio.to_thread(_publish_files, version, files)
        old = await published_release()
        doc = {"tag": version, "name": f"Nuvio for CMTV {version}", "notes": (body.get("notes") or "").strip()[:2000],
               "assets": assets, "published_at": datetime.utcnow(), "published_by": current_user.get("email")}
        if old:
            await _db().cmtv_config.update_one({"_id": "nuvio_app_release_history"}, {"$push": {"releases": {
                k: v for k, v in old.items() if k != "_id"}}}, upsert=True)
        await _db().cmtv_config.replace_one({"_id": "nuvio_app_release"}, {"_id": "nuvio_app_release", **doc}, upsert=True)
        logger.info(f"Nuvio app {version} published by {current_user.get('email')}")
        return {k: v for k, v in doc.items()}

    @router.get("/share-alerts")
    async def share_alerts(current_user: dict = Depends(admin)):
        return {"alerts": [{"username": x["_id"], "at": x.get("alerted_at"), "ips": len(x.get("ips") or []),
                            "count": x.get("count", 0)} async for x in _db().cmtv_nuvio_share.find({}).sort("alerted_at", -1)]}
