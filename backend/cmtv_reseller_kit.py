"""Reseller tools (CMTV local addition 2026-09-28): the reseller's own brand, an unbranded setup guide + flyer for their
customers, and notices from CMTV to all resellers. Routes are added to cmtv_reseller_credits.router (prefix
/api/cmtv/reseller) by its init_routes(), so server.py needs no change; they share its D (db, email service, ...).
  GET  /tools                -> the reseller's brand settings, guide link, defaults, recent notices   (resellers)
  PUT  /brand                -> save brand settings (a stable link slug is made on the first save)  (resellers)
  GET  /notices              -> notices of the last 30 days                                          (resellers)
  POST /admin/notice {text, dry_run=true} -> email + Telegram (if connected) to every active reseller  (admin)
  GET  /admin/notices        -> the last 20 notices sent                                             (admin)
  GET  /g/{slug}, /g/{slug}/flyer -> public HTML without any CMTV name (nginx maps /g/ here)
  POST /apply                -> partner application from cmtv.info/partners (public; Ops Billing note)
  GET  /admin/applications   -> the last 50 applications                                            (admin)
Collections: cmtv_reseller_brands {_id: user id, slug, name, contact, color, tv_app, downloader, phone_app, phone_link,
servers [{name, url}], facts cctv|imperium|none}, cmtv_reseller_notices.
"""
import html
import logging
import re
import secrets
from datetime import datetime, timedelta

import io
import os

from fastapi import Body, Depends, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse

import cmtv_reseller_credits as RC

log = logging.getLogger("server")
D = RC.D
FACTS = {"cctv": ("11,000", "20,000", "6,000"), "imperium": ("40,000", "30,000", "8,000")}
DEFAULT_URL = {"cctv": "https://portal.cmtv.info", "imperium": "https://imperium.esq"}
LOGO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads", "reseller-logos")   # served at /api/uploads/
LOGO_MAX_BYTES = 2 * 1024 * 1024
URL_RE = re.compile(r"^https?://[A-Za-z0-9.-]+(:\d{1,5})?/?$")
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
e = html.escape


async def _reseller_services(uid):
    return [s async for s in D["db"].services.find({"user_id": uid, "account_type": "reseller", "status": "active"})]


def _server(s):
    return "imperium" if s.get("panel_type") in ("aether", "nxtdash") else "cctv"


async def _require_reseller(user):
    svcs = await _reseller_services(user["sub"])
    if not svcs:
        raise HTTPException(status_code=403, detail="Reseller tools are for CMTV resellers.")
    return svcs


def _defaults(svcs, u):
    servers = sorted({_server(s) for s in svcs})
    return {"slug": None, "name": "", "contact": "", "color": "#2f80ed", "tv_app": "TiviMate", "downloader": "",
            "phone_app": "", "phone_link": "", "servers": [{"name": "", "url": DEFAULT_URL[x]} for x in servers],
            "facts": servers[0] if len(servers) == 1 else "none"}


def _clean(body: dict) -> dict:
    """Validates the brand form; raises HTTPException(400) with a readable reason."""
    def s(k, n):
        return str(body.get(k) or "").strip()[:n]
    out = {"name": s("name", 40), "contact": s("contact", 120), "color": s("color", 7) or "#2f80ed",
           "tv_app": s("tv_app", 30) or "TiviMate", "downloader": s("downloader", 10), "phone_app": s("phone_app", 30),
           "phone_link": s("phone_link", 300), "facts": s("facts", 10) or "none"}
    if len(out["name"]) < 2:
        raise HTTPException(400, "Enter your business name (2 to 40 characters).")
    if not COLOR_RE.match(out["color"]):
        raise HTTPException(400, "Colour must look like #2f80ed.")
    if out["downloader"] and not out["downloader"].isdigit():
        raise HTTPException(400, "The Downloader code is numbers only.")
    if out["phone_link"] and not re.match(r"^https://\S+$", out["phone_link"]):
        raise HTTPException(400, "The phone app link must start with https://")
    if out["phone_link"] and not out["phone_app"]:
        raise HTTPException(400, "Give the phone app a name.")
    if out["facts"] not in ("cctv", "imperium", "none"):
        out["facts"] = "none"
    servers = []
    for x in (body.get("servers") or [])[:3]:
        name, url = str(x.get("name") or "").strip()[:30], str(x.get("url") or "").strip().rstrip("/")[:120]
        if not url:
            continue
        if not URL_RE.match(url):
            raise HTTPException(400, f"Server address \"{url}\" should look like https://tv.example.com or http://tv.example.com:8080")
        servers.append({"name": name, "url": url})
    if not servers:
        raise HTTPException(400, "Add at least one server address.")
    out["servers"] = servers
    return out


def save_logo(uid: str, data: bytes) -> str:
    """Any PNG/JPEG/WebP/GIF -> re-encoded PNG (max 600 px, first frame), so nothing but plain pixels is ever served."""
    from PIL import Image
    if len(data) > LOGO_MAX_BYTES:
        raise HTTPException(400, "That image is over 2 MB. Please use a smaller one.")
    try:
        img = Image.open(io.BytesIO(data))
        if img.format not in ("PNG", "JPEG", "WEBP", "GIF"):
            raise ValueError(img.format)
        img.seek(0)
        img = img.convert("RGBA")
        img.thumbnail((600, 600))
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(400, "Use a PNG, JPG or WebP image.")
    os.makedirs(LOGO_DIR, exist_ok=True)
    name = f"{uid}-{secrets.token_hex(4)}.png"
    img.save(os.path.join(LOGO_DIR, name), "PNG", optimize=True)
    return f"/api/uploads/reseller-logos/{name}"


def _slugify(name):
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:20] or "guide"
    return f"{base}-{secrets.token_hex(2)}"


def _notice_out(n):
    return {"id": str(n["_id"]), "text": n.get("text", ""), "created_at": RC._iso(n.get("created_at"))}


# ---------- public pages (no CMTV name anywhere) ----------

CSS = """
:root{--a:%(color)s}*{box-sizing:border-box}body{margin:0;font:16px/1.55 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
color:#1c2230;background:#f3f5f9}.wrap{max-width:760px;margin:0 auto;padding:24px 16px 48px}
header{background:var(--a);color:#fff;padding:28px 16px}header .in{max-width:760px;margin:0 auto;display:flex;align-items:center;gap:16px}
.logo{height:64px;max-width:160px;object-fit:contain;background:#fff;border-radius:12px;padding:6px}header h1{margin:0;font-size:28px}
header p{margin:6px 0 0;opacity:.9}.tabs{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 16px}.tabs button{border:2px solid var(--a);
background:#fff;color:#1c2230;border-radius:999px;padding:8px 14px;font:inherit;font-weight:600;cursor:pointer}
.tabs button.on{background:var(--a);color:#fff}.card{background:#fff;border-radius:14px;padding:20px 22px;margin:0 0 16px;
box-shadow:0 1px 3px rgba(0,0,0,.08)}h2{margin:0 0 10px;font-size:21px}h3{margin:18px 0 6px;font-size:17px}ol,ul{padding-left:22px}
li{margin:4px 0}.srv{display:flex;flex-wrap:wrap;align-items:center;gap:8px;background:#eef2f8;border-radius:10px;padding:10px 12px;margin:6px 0}
.srv code{font-size:17px;font-weight:700;word-break:break-all}.srv small{color:#5a6475}.srv button{margin-left:auto;border:0;
background:var(--a);color:#fff;border-radius:8px;padding:6px 12px;font:inherit;cursor:pointer}.tip{border-left:4px solid var(--a);
background:#f7f9fc;padding:8px 12px;border-radius:6px;margin:12px 0}.help{text-align:center;color:#3a4252}.help b{display:block;font-size:18px}
.print{display:block;margin:8px auto 0;background:none;border:0;color:#5a6475;text-decoration:underline;cursor:pointer;font:inherit}
@media print{.tabs,.print,.srv button{display:none}.dev{display:block!important;break-inside:avoid}header{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
"""


def _page(b, title, body, extra_css=""):
    color = b.get("color") if COLOR_RE.match(b.get("color") or "") else "#2f80ed"
    return HTMLResponse(
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        f"<meta name=\"robots\" content=\"noindex,nofollow\"><title>{e(title)}</title><meta property=\"og:title\" content=\"{e(title)}\">"
        "<link rel=\"icon\" href=\"data:,\">"
        f"<style>{CSS % {'color': color}}{extra_css}</style></head><body>{body}</body></html>",
        headers={"Cache-Control": "no-cache", "X-Robots-Tag": "noindex"})


def _logo(b, cls):
    url = b.get("logo") or ""
    if not re.match(r"^/api/uploads/reseller-logos/[A-Za-z0-9-]+\.png$", url):
        return ""
    return f"<img class=\"{cls}\" src=\"{url}\" alt=\"\">"


def _servers_html(b):
    rows = []
    for x in b["servers"]:
        label = f"<small>{e(x['name'])}</small>" if x.get("name") else ""
        rows.append(f"<div class=\"srv\">{label}<code>{e(x['url'])}</code>"
                    f"<button type=\"button\" data-copy=\"{e(x['url'])}\">Copy</button></div>")
    intro = "Server address:" if len(b["servers"]) == 1 else f"Server address (use the one {e(b['name'])} told you):"
    return f"<p>{intro}</p>{''.join(rows)}"


def _signin(b, app, xtream_word="Xtream Codes"):
    return (f"<h3>Sign in</h3><ol><li>Open <b>{e(app)}</b> and add a playlist (or a new service).</li>"
            f"<li>If it asks for the type, choose <b>{xtream_word}</b>.</li><li>Enter the server address, then your "
            f"<b>username</b> and <b>password</b> from {e(b['name'])}.</li></ol>{_servers_html(b)}"
            "<p class=\"tip\">No channels after signing in? The login was typed incorrectly. Check capital letters and spaces, "
            "and enter it again.</p>")


def guide_html(b):
    name, app = b["name"], b.get("tv_app") or "TiviMate"
    code = b.get("downloader")
    get_app = (f"<li>Open <b>Downloader</b>, enter the code <b>{e(code)}</b> and press <b>Go</b>.</li>"
               f"<li>Install <b>{e(app)}</b>. Allow the install if you're asked.</li>") if code else \
              (f"<li>Open <b>Downloader</b> and enter the code {e(name)} gives you for <b>{e(app)}</b>.</li>"
               "<li>Install it. Allow the install if you're asked.</li>")
    devices = [("tv", "Firestick & Android TV",
                "<h2>Firestick, Android TV &amp; Google TV</h2><h3>1. Install Downloader</h3><ol>"
                "<li><b>Firestick:</b> search for <b>Downloader</b> (by AFTVnews) on the home screen and install it. It's free.</li>"
                "<li>Then go to <b>Settings &gt; My Fire TV &gt; Developer Options &gt; Install unknown apps</b> and turn it on for "
                "Downloader. No Developer Options? Go to <b>Settings &gt; My Fire TV &gt; About</b> and click the device name 7 times.</li>"
                "<li><b>Android TV / Google TV (e.g. ONN 4K):</b> install <b>Downloader</b> from the Google Play Store. Allow it to "
                "install apps the first time it asks.</li></ol>"
                f"<h3>2. Install {e(app)}</h3><ol>{get_app}</ol>" + _signin(b, app))]
    if b.get("phone_app") and b.get("phone_link"):
        devices.append(("phone", "Android phone & tablet",
                        f"<h2>Android phone &amp; tablet</h2><h3>Install {e(b['phone_app'])}</h3><ol>"
                        f"<li>On your phone, open <a href=\"{e(b['phone_link'])}\">{e(b['phone_link'])}</a> and download the app.</li>"
                        "<li>Your phone asks to allow installing apps from your browser: allow it, then install.</li></ol>"
                        + _signin(b, b["phone_app"])))
    devices.append(("ios", "iPhone & iPad",
                    "<h2>iPhone &amp; iPad</h2><h3>Install MYTVONLINE+</h3><ol><li>Install <b>MYTVONLINE+</b> from the App Store. "
                    "It's free.</li><li>Open it and tap <b>Add a new service</b>.</li></ol>"
                    + _signin(b, "MYTVONLINE+", "Xtream Codes API")
                    + f"<p>Tap <b>Connect</b>, name it \"{e(name)}\" and save.</p>"))
    tabs = "".join(f"<button type=\"button\" data-t=\"{k}\"{' class=on' if i == 0 else ''}>{e(label)}</button>"
                   for i, (k, label, _) in enumerate(devices))
    secs = "".join(f"<section class=\"card dev\" id=\"d-{k}\"{'' if i == 0 else ' hidden'}>{body}</section>"
                   for i, (k, _, body) in enumerate(devices))
    contact = f"<b>Need help?</b>Contact {e(name)}: {e(b['contact'])}" if b.get("contact") else f"<b>Need help?</b>Contact {e(name)}."
    js = ("<script>document.querySelectorAll('[data-t]').forEach(function(t){t.onclick=function(){"
          "document.querySelectorAll('[data-t]').forEach(function(x){x.classList.toggle('on',x===t)});"
          "document.querySelectorAll('.dev').forEach(function(s){s.hidden=s.id!=='d-'+t.dataset.t})}});"
          "document.querySelectorAll('[data-copy]').forEach(function(bt){bt.onclick=function(){"
          "navigator.clipboard.writeText(bt.dataset.copy).then(function(){bt.textContent='Copied'})}});</script>")
    body = (f"<header><div class=\"in\">{_logo(b, 'logo')}<div><h1>{e(name)}</h1><p>Set up your TV service in a few minutes</p></div></div></header>"
            f"<main class=\"wrap\"><p>Pick your device:</p><div class=\"tabs\">{tabs}</div>{secs}"
            f"<div class=\"card help\">{contact}</div><button type=\"button\" class=\"print\" onclick=\"window.print()\">"
            f"Print these steps</button></main>{js}")
    return _page(b, f"{name}: setup guide", body)


FLYER_CSS = """
.fly{max-width:760px;margin:24px auto;background:#101522;color:#fff;border-radius:18px;overflow:hidden}
.fly .top{background:var(--a);padding:34px 32px}.fly .logo{height:84px;max-width:220px;margin:0 0 14px;display:block}.fly h1{margin:0;font-size:40px}.fly .top p{margin:8px 0 0;font-size:20px}
.fly .mid{padding:26px 32px}.nums{display:flex;gap:14px;flex-wrap:wrap;margin:0 0 18px}.nums div{flex:1;min-width:150px;
background:#1b2335;border-radius:12px;padding:14px}.nums b{display:block;font-size:30px;color:var(--a)}.fly ul{font-size:18px}
.fly .foot{border-top:1px solid #2a3450;padding:20px 32px;font-size:20px}.fly .foot b{color:var(--a)}
@media print{body{background:#fff}.fly{margin:0;-webkit-print-color-adjust:exact;print-color-adjust:exact}}
"""


def flyer_html(b):
    f = FACTS.get(b.get("facts"))
    nums = (f"<div class=\"nums\"><div><b>{f[0]}+</b>live channels</div><div><b>{f[1]}+</b>movies</div>"
            f"<div><b>{f[2]}+</b>series</div></div>") if f else ""
    contact = f"<div class=\"foot\">Get started: <b>{e(b['contact'])}</b></div>" if b.get("contact") else ""
    body = (f"<div class=\"fly\"><div class=\"top\">{_logo(b, 'logo')}<h1>{e(b['name'])}</h1><p>Live TV, movies &amp; series on every screen</p></div>"
            f"<div class=\"mid\">{nums}<ul><li>Canadian &amp; US channels, sports and PPV</li><li>Firestick, Android TV, Google TV, "
            "phones and tablets</li><li>Set up in minutes, with step-by-step help</li></ul></div>"
            f"{contact}</div><button type=\"button\" class=\"print\" onclick=\"window.print()\">Print this flyer</button>")
    return _page(b, b["name"], body, FLYER_CSS)


# ---------- notices ----------

async def send_notice(text: str, by: str, dry_run: bool = True):
    db = D["db"]
    users = {}
    async for s in db.services.find({"account_type": "reseller", "status": "active", "cmtv_demo": {"$ne": True}}):
        uid = str(s.get("user_id"))
        if uid not in users:
            users[uid] = await db.users.find_one({"_id": RC._oid(uid)}) or {}
    real = {k: u for k, u in users.items() if u}
    names = [u.get("name") or u.get("email") for u in real.values()]
    if dry_run:
        return {"dry_run": True, "resellers": len(real), "names": names}
    es = await D["get_email_service"]()
    emailed = tg = 0
    safe = e(text).replace("\n", "<br>")
    for uid, u in real.items():
        mail = str(u.get("email") or "")
        if mail and not mail.lower().endswith("@panel.local") and es and getattr(es, "enabled", False):
            try:
                body = (f"<h2 style=\"margin:0 0 8px\">Notice for resellers</h2><p>{safe}</p>"
                        f"<p style=\"margin:22px 0\"><a href=\"{RC.SITE}/reseller\" style=\"background:#22e6f2;color:#07101a;"
                        "padding:12px 22px;border-radius:999px;text-decoration:none;font-weight:700\">Reseller tools</a></p>")
                branded = await RC.render("cmtv_reseller_notice", {"notice": safe, "tools_link": f"{RC.SITE}/reseller"})
                subject, page = branded or ("CMTV reseller notice", None)   # 2026-10-01: CMTV-branded template
                ok = await es.send_email(to_email=mail, subject=subject,
                                         html_content=page or es._wrap_email(body, "Reseller notice", mail, "transactional"),
                                         email_type="transactional", template_type="cmtv_reseller_notice", customer_id=uid)
                emailed += 1 if ok else 0
            except Exception as ex:
                log.warning(f"reseller notice email failed: {ex}")
        chat = (u.get("cmtv_telegram") or {}).get("chat_id")
        if chat:
            try:
                import cmtv_telegram_alerts
                await cmtv_telegram_alerts.queue(uid, chat, f"📣 <b>Notice for resellers</b>\n\n{e(text)}", None, kind="reseller_notice")
                tg += 1
            except Exception as ex:
                log.warning(f"reseller notice telegram failed: {ex}")
    doc = {"text": text, "created_at": datetime.utcnow(), "by": by, "resellers": len(real), "emailed": emailed, "telegram": tg}
    await db.cmtv_reseller_notices.insert_one(doc)
    return {"dry_run": False, "resellers": len(real), "emailed": emailed, "telegram": tg}


# ---------- routes ----------

def init_routes(router):
    current = D["get_current_user"]
    admin = D["get_current_admin_user"]

    async def recent_notices(days=30, limit=5):
        since = datetime.utcnow() - timedelta(days=days)
        return [_notice_out(n) async for n in D["db"].cmtv_reseller_notices.find({"created_at": {"$gte": since}})
                .sort("created_at", -1).limit(limit)]

    @router.get("/tools")
    async def tools(current_user: dict = Depends(current)):
        svcs = await _require_reseller(current_user)
        u = await D["db"].users.find_one({"_id": RC._oid(current_user["sub"])}) or {}
        saved = await D["db"].cmtv_reseller_brands.find_one({"_id": current_user["sub"]}) or {}
        brand = {**_defaults(svcs, u), **{k: v for k, v in saved.items() if k not in ("_id", "updated_at")}}
        return {"brand": brand, "saved": bool(saved), "servers": sorted({_server(s) for s in svcs}),
                "guide_url": f"{RC.SITE}/g/{brand['slug']}" if brand.get("slug") else None,
                "flyer_url": f"{RC.SITE}/g/{brand['slug']}/flyer" if brand.get("slug") else None,
                "facts": {k: list(v) for k, v in FACTS.items()}, "notices": await recent_notices()}

    @router.put("/brand")
    async def save_brand(body: dict = Body(...), current_user: dict = Depends(current)):
        await _require_reseller(current_user)
        uid = current_user["sub"]
        data = _clean(body)
        old = await D["db"].cmtv_reseller_brands.find_one({"_id": uid}) or {}
        slug = old.get("slug") or _slugify(data["name"])
        await D["db"].cmtv_reseller_brands.update_one(
            {"_id": uid}, {"$set": {**data, "slug": slug, "updated_at": datetime.utcnow()}}, upsert=True)
        return {"ok": True, "slug": slug}

    @router.post("/brand/logo")
    async def upload_logo(file: UploadFile = File(...), current_user: dict = Depends(current)):
        await _require_reseller(current_user)
        uid = current_user["sub"]
        url = save_logo(uid, await file.read(LOGO_MAX_BYTES + 1))
        await D["db"].cmtv_reseller_brands.update_one({"_id": uid}, {"$set": {"logo": url, "updated_at": datetime.utcnow()}}, upsert=True)
        return {"logo": url}

    @router.delete("/brand/logo")
    async def remove_logo(current_user: dict = Depends(current)):
        await _require_reseller(current_user)
        await D["db"].cmtv_reseller_brands.update_one({"_id": current_user["sub"]}, {"$unset": {"logo": ""}})
        return {"logo": None}

    @router.get("/notices")
    async def notices(current_user: dict = Depends(current)):
        if not await _reseller_services(current_user["sub"]):
            return {"notices": []}
        return {"notices": await recent_notices()}

    @router.post("/admin/notice")
    async def admin_notice(body: dict = Body(...), current_user: dict = Depends(admin)):
        text = str(body.get("text") or "").strip()
        if not 5 <= len(text) <= 1000:
            raise HTTPException(400, "Write between 5 and 1,000 characters.")
        return await send_notice(text, current_user.get("sub"), dry_run=body.get("dry_run", True) is not False)

    @router.get("/admin/notices")
    async def admin_notices(current_user: dict = Depends(admin)):
        out = []
        async for n in D["db"].cmtv_reseller_notices.find().sort("created_at", -1).limit(20):
            out.append({**_notice_out(n), "resellers": n.get("resellers"), "emailed": n.get("emailed"), "telegram": n.get("telegram")})
        return {"notices": out}

    @router.post("/apply")
    async def partner_apply(body: dict = Body(...)):
        """Partner application from cmtv.info/partners (relayed by the site's worker /api/apply). Saved + Ops Billing note.
        Before 2026-09-28 the form posted to api.cmtv.info (405) and showed "received" anyway, so applications were lost."""
        if str(body.get("website") or "").strip():   # hidden field only bots fill in
            return {"ok": True}
        f = lambda k, n: str(body.get(k) or "").strip()[:n]  # noqa: E731
        doc = {"first_name": f("first_name", 40), "last_name": f("last_name", 40), "email": f("email", 120).lower(),
               "telegram": f("telegram", 60), "interest": f("interest", 300), "message": f("message", 2000)}
        if not doc["first_name"] or not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", doc["email"]):
            raise HTTPException(400, "Enter your first name and a valid email.")
        db, now = D["db"], datetime.utcnow()
        if await db.cmtv_partner_applications.find_one({"email": doc["email"], "created_at": {"$gte": now - timedelta(hours=1)}}):
            return {"ok": True}
        if await db.cmtv_partner_applications.count_documents({"created_at": {"$gte": now - timedelta(days=1)}}) >= 30:
            raise HTTPException(429, "Too many applications today. Please message us on Telegram.")
        await db.cmtv_partner_applications.insert_one({**doc, "created_at": now, "status": "new"})
        who = f"{doc['first_name']} {doc['last_name']}".strip()
        await RC._ops(f"🤝 New partner application: {who} ({doc['email']}"
                      + (f", Telegram {doc['telegram']}" if doc["telegram"] else "") + ")\n"
                      + (f"Interested in: {doc['interest']}\n" if doc["interest"] else "")
                      + (f"\n{doc['message'][:800]}" if doc["message"] else "")
                      + "\n\nAdmin > Resellers has the list.", "billing")
        return {"ok": True}

    @router.get("/admin/applications")
    async def admin_applications(current_user: dict = Depends(admin)):
        out = []
        async for a in D["db"].cmtv_partner_applications.find().sort("created_at", -1).limit(50):
            out.append({**{k: a.get(k, "") for k in ("first_name", "last_name", "email", "telegram", "interest", "message")},
                        "id": str(a["_id"]), "created_at": RC._iso(a.get("created_at"))})
        return {"applications": out}

    async def _brand(slug):
        b = await D["db"].cmtv_reseller_brands.find_one({"slug": slug})
        # only while the reseller still has an active panel
        if not b or not await _reseller_services(b["_id"]):
            raise HTTPException(404, "Not found")
        return b

    @router.get("/g/{slug}", response_class=HTMLResponse, include_in_schema=False)
    async def public_guide(slug: str):
        return guide_html(await _brand(slug))

    @router.get("/g/{slug}/flyer", response_class=HTMLResponse, include_in_schema=False)
    async def public_flyer(slug: str):
        return flyer_html(await _brand(slug))
