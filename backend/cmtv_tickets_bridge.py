"""Website tickets <-> Telegram (CMTV local addition 2026-09-26).

@Cmtv_support_bot (/opt/cmtv-bots/support, same server) polls this private API to post website tickets into the Admin
Ops > Tickets topic, and answers them when staff reply there. Access: only from 127.0.0.1, with the header
X-Bridge-Token = TICKET_BRIDGE_TOKEN (billing .env; the bot has the same value in its own .env).

Also: `email_ticket_reply` emails the customer when staff answer (template "ticket_reply"). Billing never did this:
website replies only notified the admin, so customers had to check the site.
"""
import hmac
import logging
import os
from datetime import datetime

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/cmtv/tickets-bridge", tags=["cmtv-tickets-bridge"])
D = {}
SITE = "https://billing.cmtv.info"


def init(**deps):
    D.update(deps)


def _oid(v):
    return ObjectId(v) if ObjectId.is_valid(str(v)) else None


def _auth(request: Request):
    """Direct local calls only. Everything through nginx also arrives from 127.0.0.1, but nginx always adds
    X-Real-IP / X-Forwarded-For, so a request carrying them came from outside and is refused even with the token."""
    token = os.environ.get("TICKET_BRIDGE_TOKEN", "")
    client = request.client.host if request.client else ""
    proxied = any(h in request.headers for h in ("x-real-ip", "x-forwarded-for", "cf-connecting-ip"))
    got = request.headers.get("x-bridge-token", "")
    if not token or proxied or client not in ("127.0.0.1", "::1") or not hmac.compare_digest(got.encode(), token.encode()):
        raise HTTPException(403, "Forbidden")


def _iso(dt):
    return dt.isoformat() if isinstance(dt, datetime) else str(dt or "")


async def email_ticket_reply(ticket: dict, message: str):
    """Email the customer that support replied (template "ticket_reply"). Never raises."""
    try:
        user = await D["users"].find_one({"_id": _oid(ticket.get("user_id"))})
        es = await D["get_email_service"]()
        if not user or not user.get("email") or not es or not getattr(es, "enabled", False):
            return False
        tpl = await D["db"].email_templates.find_one({"template_type": "ticket_reply", "is_active": True})
        if not tpl:
            return False
        from html import escape
        tid = str(ticket.get("_id") or ticket.get("id"))
        values = {"customer_name": escape(user.get("name") or "there"), "ticket_id": tid[-8:].upper(),
                  "ticket_subject": escape(ticket.get("subject") or ""),
                  "reply_message": escape(message).replace("\n", "<br>"), "ticket_link": f"{SITE}/tickets"}
        subject, html = tpl.get("subject") or "New reply on your support ticket", tpl.get("html_content") or ""
        for k, v in values.items():
            subject = subject.replace("{{" + k + "}}", v if k != "reply_message" else "")
            html = html.replace("{{" + k + "}}", v)
        return bool(await es.send_email(
            to_email=user["email"], subject=subject,
            html_content=es._wrap_email(html, tpl.get("name", ""), user["email"], "transactional"),
            text_content=f"Hi {user.get('name') or 'there'},\n\nSupport replied to your ticket \"{ticket.get('subject')}\":\n\n"
                         f"{message}\n\nSee the whole conversation at {SITE}/tickets",
            email_type="transactional", template_type="ticket_reply", customer_id=str(user["_id"]),
            recipient_name=user.get("name")))
    except Exception as e:
        logger.warning(f"ticket reply email failed: {e}")
        return False


@router.get("/changes")
async def changes(request: Request, since: str = "", include_open: bool = False):
    """Tickets changed after `since` (ISO). include_open=true also returns every open ticket (first run)."""
    _auth(request)
    q = {}
    try:
        after = datetime.fromisoformat(since) if since else None
    except ValueError:
        raise HTTPException(400, "since must be ISO time")
    if after and include_open:
        q = {"$or": [{"updated_at": {"$gt": after}}, {"status": {"$ne": "closed"}}]}
    elif after:
        q = {"updated_at": {"$gt": after}}
    elif include_open:
        q = {"status": {"$ne": "closed"}}
    out = []
    async for t in D["tickets"].find(q).sort("updated_at", 1).limit(100):
        u = await D["users"].find_one({"_id": _oid(t.get("user_id"))}, {"name": 1, "email": 1, "username": 1})
        out.append({
            "id": str(t["_id"]), "subject": t.get("subject"), "status": t.get("status"), "priority": t.get("priority"),
            "service": t.get("service_name"), "created_at": _iso(t.get("created_at")), "updated_at": _iso(t.get("updated_at")),
            "customer": {"name": (u or {}).get("name"), "email": (u or {}).get("email"), "username": (u or {}).get("username")},
            "messages": [{"i": i, "admin": bool(m.get("is_admin")), "via": m.get("via"), "text": m.get("message") or "",
                          "at": _iso(m.get("created_at"))} for i, m in enumerate(t.get("messages") or [])],
        })
    return {"tickets": out, "now": datetime.utcnow().isoformat()}


@router.get("/catalog")
async def catalog(request: Request):
    """Active plans for the bot's "Plans & prices" / "Free trials" answers (2026-09-26), grouped like the storefront."""
    _auth(request)
    settings = await D["db"].settings.find_one({}) or {}
    groups = {g.get("id"): g.get("name", "") for g in settings.get("product_groups", [])}
    order = [g.get("id") for g in settings.get("product_groups", [])]
    fams = {}
    async for p in D["db"].products.find({"active": True}).sort("display_order", 1):
        gname = groups.get(p.get("group_id"), "")
        n = gname.lower()
        fam = ("trials" if "trial" in n or p.get("is_trial") else "resellers" if "resell" in n or p.get("account_type") == "reseller"
               else "imperium" if "imperium" in n else "cctv" if "cctv" in n else "addons" if "add" in n else "other")
        if fam == "resellers":
            continue
        term, price = next(iter((p.get("prices") or {"1": 0}).items()))
        fams.setdefault(fam, []).append({
            "name": p.get("name"), "price": float(price), "term_months": int(term), "connections": p.get("max_connections"),
            "trial": bool(p.get("is_trial")), "trial_length": f"{p.get('trial_duration')} {p.get('trial_duration_unit')}" if p.get("is_trial") else None,
            "group_order": order.index(p.get("group_id")) if p.get("group_id") in order else 99})
    return {"families": fams, "currency": (settings.get("currency") or "CAD") if isinstance(settings.get("currency"), str) else "CAD"}


@router.post("/{ticket_id}/reply")
async def reply(ticket_id: str, request: Request):
    _auth(request)
    data = await request.json()
    text = str(data.get("text") or "").strip()[:4000]
    if not text:
        raise HTTPException(400, "Empty reply")
    t = await D["tickets"].find_one({"_id": _oid(ticket_id)})
    if not t:
        raise HTTPException(404, "Ticket not found")
    msg = {"message": text, "is_admin": True, "created_at": datetime.utcnow(), "via": "telegram",
           "staff": str(data.get("staff") or "")[:60]}
    status = "in_progress" if t.get("status") in ("open", "closed") else t.get("status")
    await D["tickets"].update_one({"_id": t["_id"]}, {"$push": {"messages": msg},
                                                      "$set": {"status": status, "updated_at": datetime.utcnow()}})
    emailed = await email_ticket_reply(t, text)
    logger.info(f"Ticket {ticket_id}: staff reply from Telegram ({msg['staff'] or 'staff'}), emailed={emailed}")
    return {"success": True, "emailed": emailed, "index": len(t.get("messages") or [])}


@router.post("/{ticket_id}/status")
async def status(ticket_id: str, request: Request):
    _auth(request)
    data = await request.json()
    new = str(data.get("status") or "")
    if new not in ("open", "in_progress", "closed"):
        raise HTTPException(400, "status must be open, in_progress or closed")
    before = await D["tickets"].find_one({"_id": _oid(ticket_id)})
    if not before:
        raise HTTPException(404, "Ticket not found")
    await D["tickets"].update_one({"_id": before["_id"]}, {"$set": {"status": new, "updated_at": datetime.utcnow()}})
    emailed = False
    if new == "closed" and before.get("status") != "closed":   # 2026-09-26: same "ticket closed" email as the website
        try:
            user = await D["users"].find_one({"_id": _oid(before.get("user_id"))})
            es = await D["get_email_service"]()
            if user and user.get("email") and es and getattr(es, "enabled", False):
                emailed = bool(await es.send_ticket_closed(user["email"], user.get("name", ""), ticket_id,
                                                           before.get("subject", ""), customer_id=str(user["_id"])))
        except Exception as e:
            logger.warning(f"ticket closed email failed: {e}")
    logger.info(f"Ticket {ticket_id}: status -> {new} from Telegram ({data.get('staff') or 'staff'}), emailed={emailed}")
    return {"success": True, "emailed": emailed}
