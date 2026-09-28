"""'Email me these steps' on the setup guides (CMTV local addition 2026-09-28).

POST /api/cmtv/kb/email-guide {article_id, service_id}: emails the signed-in customer (their own address only) the
published guide plus the login of one of THEIR services (the one shown in the guide's "Your details" card,
components/cmtv/GuideLogin.js). 5 per hour per customer (cmtv_kb_emails). The guide markup is the same light markup the
page renders: "## " heading, "1. " steps (with "- " bullets under a step), "- " bullets, **bold**, "> Tip:"/"> Important:",
[image:url] / [video:url], bare https:// links.
"""
import html
import re
from datetime import datetime, timedelta

from bson import ObjectId
from fastapi import APIRouter, Body, Depends, HTTPException

router = APIRouter(prefix="/api/cmtv/kb", tags=["cmtv-kb"])
D = {}
PER_HOUR = 5
ADDON = {"cmtv-stremio": "nuvio", "cmtv-cmtvpn": "vpn", "cmtv-audiobooks": "audiobooks"}


def init(**deps):
    D.update(deps)


def server_of(s: dict):
    """Same rules as serverOf() in GuideLogin.js"""
    name = str(s.get("product_name") or "").lower()
    url = re.sub(r"^https?://", lambda m: m.group(0).lower(), str(s.get("streaming_url") or ""), flags=re.I).rstrip("/")
    if "amethyst" in name:
        return "Amethyst", url or "http://amethystc.live"
    if s.get("panel_type") == "onestream" or "extreme" in name:
        return "Extreme", url or "https://tv.extremeiptv.net"
    if s.get("panel_type") in ("aether", "nxtdash") or "imperium" in name:
        return "Imperium", url or "https://imperium.esq"
    return "CCTV", url or "https://portal.cmtv.info"


def _inline(text: str) -> str:
    t = html.escape(text)
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    return re.sub(r"(https?://[^\s<)]+[^\s<).,])", r'<a href="\1" style="color:#0e7490">\1</a>', t)


def render(content: str) -> str:
    """Same rules as renderContent() in CmtvKnowledgeBasePage.js: collect blocks, then write email-safe HTML"""
    blocks, lst = [], None

    def flush():
        nonlocal lst
        if lst:
            blocks.append(lst)
            lst = None

    for raw in str(content or "").replace("\r", "").split("\n"):
        line = raw.strip()
        media = re.match(r"^\[(image|video):(.+)\]$", line)
        step = re.match(r"^(\d+)[.)]\s*(.+)$", line)
        bullet = re.match(r"^[-•]\s*(.+)$", line)
        if not line:
            flush()
        elif media:
            flush()
            blocks.append({"t": media.group(1), "src": media.group(2).strip()})
        elif line.startswith("## "):
            flush()
            blocks.append({"t": "h", "text": line[3:]})
        elif line.startswith("> "):
            flush()
            body = line[2:]
            blocks.append({"t": "callout", "warn": body.lower().startswith("important:"),
                           "text": re.sub(r"^(tip|important):\s*", "", body, flags=re.I)})
        elif step:
            if not lst or lst["t"] != "ol":
                flush()
                lst = {"t": "ol", "start": int(step.group(1)), "items": []}
            lst["items"].append({"text": step.group(2), "sub": []})
        elif bullet:
            if lst and lst["t"] == "ol" and lst["items"]:
                lst["items"][-1]["sub"].append(bullet.group(1))   # bullets under a numbered step belong to it
            else:
                if not lst or lst["t"] != "ul":
                    flush()
                    lst = {"t": "ul", "items": []}
                lst["items"].append({"text": bullet.group(1), "sub": []})
        else:
            flush()
            blocks.append({"t": "p", "text": line})
    flush()

    out = []
    for b in blocks:
        if b["t"] == "h":
            out.append(f'<h3 style="margin:18px 0 6px">{_inline(b["text"])}</h3>')
        elif b["t"] == "p":
            out.append(f"<p>{_inline(b['text'])}</p>")
        elif b["t"] == "image":
            out.append(f'<p><img src="{html.escape(b["src"])}" alt="" style="max-width:100%;border-radius:8px"></p>')
        elif b["t"] == "video":
            out.append(f'<p><a href="{html.escape(b["src"])}">Watch the video</a></p>')
        elif b["t"] == "callout":
            color = "#b45309" if b["warn"] else "#0e7490"
            out.append(f'<p style="border-left:3px solid {color};padding:6px 10px;background:#f5f7fb">'
                       f'<strong style="color:{color}">{"Important" if b["warn"] else "Tip"}:</strong> {_inline(b["text"])}</p>')
        else:
            items = "".join(
                f'<li style="margin:4px 0">{_inline(it["text"])}'
                + (f'<ul style="padding-left:18px">{"".join(f"<li>{_inline(x)}</li>" for x in it["sub"])}</ul>' if it["sub"] else "")
                + "</li>" for it in b["items"])
            start = f' start="{b["start"]}"' if b["t"] == "ol" else ""
            out.append(f'<{b["t"]}{start} style="padding-left:22px">{items}</{b["t"]}>')
    return "".join(out)


def details_html(s: dict, article_id: str) -> str:
    user = s.get("xtream_username") or s.get("username") or ""
    pw = s.get("xtream_password") or s.get("password") or ""
    rows = []
    if article_id not in ADDON:
        name, url = server_of(s)
        rows += [("Server", name), ("Server address", url)]
    rows += [("Username", user), ("Password", pw)]
    if s.get("max_connections") and article_id not in ADDON:
        rows.append(("Devices at once", str(s["max_connections"])))
    cells = "".join(f'<tr><td style="padding:6px 12px 6px 0;color:#555">{html.escape(k)}</td>'
                    f'<td style="padding:6px 0;font-family:monospace;font-size:15px"><strong>{html.escape(str(v))}</strong></td></tr>'
                    for k, v in rows)
    return (f'<div style="border:1px solid #d6dbe8;border-radius:10px;padding:12px 16px;margin:12px 0 18px;background:#f8fafc">'
            f'<p style="margin:0 0 6px"><strong>Your details</strong> · {html.escape(str(s.get("product_name") or ""))}</p>'
            f'<table style="border-collapse:collapse">{cells}</table>'
            f'<p style="margin:8px 0 0;font-size:12px;color:#777">Keep this private: it\'s the login for your service.</p></div>')


def init_routes():
    current = D["get_current_user"]

    @router.post("/email-guide")
    async def email_guide(data: dict = Body(...), current_user: dict = Depends(current)):
        uid = current_user["sub"]
        article_id = str(data.get("article_id") or "")
        service_id = str(data.get("service_id") or "")
        db = D["db"]
        since = datetime.utcnow() - timedelta(hours=1)
        if await db.cmtv_kb_emails.count_documents({"user_id": uid, "at": {"$gte": since}}) >= PER_HOUR:
            raise HTTPException(status_code=429, detail="You've sent a few already. Try again in an hour.")
        article = await db.kb_articles.find_one({"id": article_id, "is_published": True}, {"_id": 0})
        if not article:
            raise HTTPException(status_code=404, detail="Guide not found")
        if not ObjectId.is_valid(service_id):
            raise HTTPException(status_code=400, detail="Choose a service")
        s = await db.services.find_one({"_id": ObjectId(service_id), "user_id": uid})
        if not s:
            raise HTTPException(status_code=404, detail="Service not found")
        user = await db.users.find_one({"_id": ObjectId(uid)})
        if not user or not user.get("email") or str(user["email"]).lower().endswith("@panel.local"):
            raise HTTPException(status_code=400, detail="Add an email address to your account first")
        es = await D["get_email_service"]()
        if not es or not getattr(es, "enabled", True):
            raise HTTPException(status_code=503, detail="Email isn't available right now")
        title = article.get("title") or "Setup guide"
        link = f"https://billing.cmtv.info/knowledge-base/{article_id}"
        body = (f"<h2 style=\"margin:0 0 4px\">{html.escape(title)}</h2>"
                f"<p style=\"margin:0 0 8px\">Hi {html.escape(str(user.get('name') or ''))}, here are the steps you asked for.</p>"
                + details_html(s, article_id) + render(article.get("content") or "")
                + f'<p style="margin-top:18px">Open this guide online: <a href="{link}">{link}</a></p>')
        ok = await es.send_email(to_email=user["email"], subject=f"Your setup steps: {title}",
                                 html_content=es._wrap_email(body, title, user["email"], "transactional"),
                                 email_type="transactional", customer_id=uid)
        await db.cmtv_kb_emails.insert_one({"user_id": uid, "article_id": article_id, "service_id": service_id,
                                            "at": datetime.utcnow(), "sent": bool(ok)})
        if not ok:
            raise HTTPException(status_code=502, detail="Could not send the email. Try again in a minute.")
        return {"ok": True}
