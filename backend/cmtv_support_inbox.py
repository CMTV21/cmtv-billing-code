"""Admin > Support inbox (CMTV local addition 2026-10-04, the owner's request): website tickets AND Telegram support-bot
tickets in one list, with the full conversation, the customer's account beside it, saved replies and reply/close from
the website.

- Website tickets: billing's own `tickets` collection. Replies/status go through the existing admin endpoints
  (/api/admin/tickets/{id}/reply, /status), which email the customer; the support bot mirrors them to Telegram as before.
- Telegram tickets: read straight from the support bot's SQLite (/opt/cmtv-bots/support/data/tickets.db, opened
  READ-ONLY; same VPS). Replies / close / reopen / "need info" made here are queued in `cmtv_tg_ticket_ops`; the bot
  picks them up through the bridge (GET /api/cmtv/tickets-bridge/tg/ticket-ops, POST .../ack), sends them to the customer
  as "CMTV Support", logs them on the ticket and notes them in Admin Ops > Tickets. Nothing is written to the bot's DB here.
- Customer match for a Telegram ticket: a manual link (`cmtv_tg_customer_links`, _id = Telegram user id) > the customer's
  connected Telegram alerts (users.cmtv_telegram.chat_id) > the line username they typed (services.username).
- Saved replies: cmtv_config {_id: "support_canned", items: [{title, text}]}.
"""
import logging
import re
import sqlite3
from datetime import datetime, timedelta

from bson import ObjectId
from fastapi import APIRouter, Body, Depends, HTTPException, Request

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/cmtv/inbox", tags=["cmtv-inbox"])
bridge = APIRouter(prefix="/api/cmtv/tickets-bridge/tg/ticket-ops", tags=["cmtv-inbox-bridge"])
D = {}
BOT_DB = "/opt/cmtv-bots/support/data/tickets.db"

DEFAULT_CANNED = [
    {"title": "Buffering: quick fixes", "text": "Sorry about the buffering! Please try these quick fixes first:\n"
     "1. Check billing.cmtv.info/status to see if your server has a known problem right now.\n"
     "2. Restart your device and your modem/router (unplug for 30 seconds).\n"
     "3. Run a speed test: you need at least 25 Mbps for HD.\n"
     "Full guide: https://billing.cmtv.info/knowledge-base/cmtv-buffering\n"
     "If it still happens, tell us the channel name and the time it buffered and we'll look into it."},
    {"title": "Restart the app", "text": "Please fully close the app and open it again (on a Firestick: Settings > Applications > "
     "Manage Installed Applications > the app > Force stop), then try again. Let us know if it's still not working."},
    {"title": "Renewal link", "text": "You can renew any time from your dashboard: https://billing.cmtv.info/dashboard "
     "(tap Renew on your plan). Sign in with your email, or with your TV app's username and password."},
    {"title": "Reinstall from Downloader", "text": "Please reinstall the app: open the Downloader app, enter code 5883394, "
     "and pick the app from the list. Then sign in again with your username and password."},
    {"title": "Check login details", "text": "Your login details are on your dashboard: https://billing.cmtv.info/dashboard "
     "(Show / Copy on your plan). Please make sure they're typed exactly, capitals included."},
    {"title": "Fixed, please try again", "text": "That should be fixed now. Please close and reopen the app and try again, "
     "and let us know if anything's still not right."},
]


def init(**deps):
    D.update(deps)


def _iso(v):
    if isinstance(v, datetime):
        return v.isoformat() + "Z"
    if isinstance(v, str) and v and not v.endswith("Z") and "+" not in v[10:]:
        return v + "Z"
    return v


def _dt(v):
    if isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def _bot():
    """Read-only connection to the support bot's database (None if it isn't there)."""
    try:
        c = sqlite3.connect(f"file:{BOT_DB}?mode=ro", uri=True, timeout=5)
        c.row_factory = sqlite3.Row
        return c
    except Exception as e:
        log.warning(f"inbox: can't open the bot database ({e})")
        return None


def tnum(tid):
    return f"#T-{int(tid):04d}"


# ------------------------------------------------------------------ normalising both kinds
async def _site_rows():
    db = D["db"]
    users = {}
    out = []
    async for t in db.tickets.find():
        msgs = t.get("messages") or []
        uid = t.get("user_id")
        if uid not in users:
            u = await db.users.find_one({"_id": ObjectId(uid)}, {"name": 1, "email": 1}) if uid and ObjectId.is_valid(uid) else None
            users[uid] = u or {}
        u = users[uid]
        last = msgs[-1] if msgs else {}
        first_admin = next((m for m in msgs if m.get("is_admin")), None)
        closed = t.get("status") == "closed"
        state = "closed" if closed else ("waiting" if last.get("is_admin") else "needs")
        created = _dt(t.get("created_at"))
        out.append({
            "kind": "web", "id": str(t["_id"]), "number": "#W-" + str(t["_id"])[-6:].upper(),
            "subject": t.get("subject") or "(no subject)", "service": t.get("service_name") or "",
            "customer": u.get("name") or "Unknown", "customer_sub": u.get("email") or "", "user_id": uid,
            "state": state, "raw_status": t.get("status"), "priority": t.get("priority"),
            "created_at": _iso(created), "updated_at": _iso(_dt(t.get("updated_at")) or created),
            "last_from": "us" if last.get("is_admin") else "customer", "preview": (last.get("message") or "")[:140],
            "first_reply_mins": round((_dt(first_admin["created_at"]) - created).total_seconds() / 60)
            if first_admin and created and _dt(first_admin.get("created_at")) else None,
        })
    return out


def _tg_rows(include_tests=False):
    c = _bot()
    if not c:
        return []
    out = []
    try:
        evs = {}
        for e in c.execute("SELECT ticket_id, kind, text, created_at FROM events ORDER BY id"):
            evs.setdefault(e["ticket_id"], []).append(e)
        for t in c.execute("SELECT * FROM tickets ORDER BY id"):
            if t["is_test"] and not include_tests:
                continue
            ev = evs.get(t["id"], [])
            talk = [e for e in ev if e["kind"] in ("opened", "customer_msg", "staff_reply")]
            last = talk[-1] if talk else None
            first_staff = next((e for e in ev if e["kind"] == "staff_reply"), None)
            if t["status"] == "resolved":
                state = "closed"
            elif t["status"] == "waiting" or (last and last["kind"] == "staff_reply"):
                state = "waiting"
            else:
                state = "needs"
            created = _dt(t["created_at"])
            subj = " · ".join(x for x in (t["service"], t["issue"]) if x and x != "-") or "Telegram ticket"
            out.append({
                "kind": "tg", "id": str(t["id"]), "number": tnum(t["id"]), "subject": subj, "service": t["service"] or "",
                "customer": t["customer_name"] or "Telegram user",
                "customer_sub": ("@" + t["customer_username"]) if t["customer_username"] else "Telegram",
                "tg_user_id": t["customer_id"], "order_ref": t["order_ref"], "device": t["device"],
                "state": state, "raw_status": t["status"], "claimed_by": t["claimed_by"],
                "created_at": _iso(created), "updated_at": _iso(_dt(t["updated_at"]) or created),
                "last_from": "us" if last and last["kind"] == "staff_reply" else "customer",
                "preview": ((last["text"] if last else t["description"]) or "")[:140],
                "first_reply_mins": round((_dt(first_staff["created_at"]) - created).total_seconds() / 60)
                if first_staff and created else None,
            })
    finally:
        c.close()
    return out


async def _pending_ops():
    """Telegram replies/actions queued here but not yet delivered by the bot (shown in the list right away)."""
    return [o async for o in D["db"].cmtv_tg_ticket_ops.find({"status": "queued"})]


async def all_rows():
    rows = await _site_rows() + _tg_rows()
    for o in await _pending_ops():
        for r in rows:
            if r["kind"] == "tg" and r["id"] == str(o["ticket_id"]):
                r["pending"] = True
                if o["action"] == "reply":
                    r["state"], r["last_from"] = "waiting", "us"
                elif o["action"] == "close":
                    r["state"] = "closed"
                elif o["action"] in ("reopen", "need"):
                    r["state"] = "needs" if o["action"] == "reopen" else "waiting"
    return rows


# ------------------------------------------------------------------ customer card
async def _match_tg_user(tg_id, order_ref):
    db = D["db"]
    link = await db.cmtv_tg_customer_links.find_one({"_id": int(tg_id)})
    if link:
        return link["user_id"], "linked by you"
    u = await db.users.find_one({"cmtv_telegram.chat_id": {"$in": [int(tg_id), str(tg_id)]}}, {"_id": 1})
    if u:
        return str(u["_id"]), "their Telegram alerts"
    ref = (order_ref or "").strip().lstrip("#")
    if ref and re.match(r"^[A-Za-z0-9@._-]{3,40}$", ref):
        s = await db.services.find_one({"$or": [{"username": {"$regex": f"^{re.escape(ref)}$", "$options": "i"}},
                                                {"xtream_username": {"$regex": f"^{re.escape(ref)}$", "$options": "i"}}]},
                                       {"user_id": 1})
        if s:
            return s["user_id"], f"the line username “{ref}”"
        if re.match(r"^[0-9a-f]{6,24}$", ref, re.I):
            o = await db.orders.find_one({"$expr": {"$regexMatch": {"input": {"$toString": "$_id"}, "regex": f"^{ref.lower()}"}}},
                                         {"user_id": 1})
            if o:
                return o["user_id"], f"the order number “{ref}”"
    return None, ""


async def customer_card(user_id):
    db = D["db"]
    if not user_id or not ObjectId.is_valid(str(user_id)):
        return None
    u = await db.users.find_one({"_id": ObjectId(str(user_id))}, {"name": 1, "email": 1, "created_at": 1, "credit_balance": 1,
                                                                   "panel_username": 1, "cmtv_telegram": 1})
    if not u:
        return None
    now = datetime.utcnow()
    svcs = []
    async for s in db.services.find({"user_id": str(user_id), "status": {"$in": ["active", "suspended", "expired"]}}).sort("expiry_date", -1).limit(8):
        exp = _dt(s.get("expiry_date"))
        svcs.append({"product": s.get("product_name"), "username": s.get("username") or s.get("xtream_username"),
                     "status": s.get("status"), "panel": s.get("panel_name") or s.get("panel_type"), "trial": bool(s.get("is_trial")),
                     "expires": _iso(exp), "days_left": (exp - now).days if exp else None,
                     "auto_renew": (s.get("auto_renew") or {}).get("status") == "ACTIVE"})
    orders = [{"id": str(o["_id"]), "total": o.get("total"), "status": o.get("status"), "at": _iso(o.get("created_at")),
               "items": ", ".join(i.get("product_name") or "" for i in o.get("items", []))[:80]}
              async for o in db.orders.find({"user_id": str(user_id)}).sort("_id", -1).limit(3)]
    paid = 0.0
    async for o in db.orders.find({"user_id": str(user_id), "status": "paid"}, {"total": 1}):
        paid += float(o.get("total") or 0)
    email = u.get("email") or ""
    return {"id": str(u["_id"]), "name": u.get("name"), "email": "" if email.endswith("@panel.local") else email,
            "panel_username": u.get("panel_username"), "since": _iso(u.get("created_at")), "credit": u.get("credit_balance") or 0,
            "paid_total": round(paid, 2), "telegram": bool((u.get("cmtv_telegram") or {}).get("chat_id")),
            "services": svcs, "orders": orders}


async def status_issues():
    try:
        import cmtv_status
        return await cmtv_status.public_issues()
    except Exception:
        return []


# ------------------------------------------------------------------ routes
def init_routes():
    admin = D["get_current_admin_user"]

    @router.get("/list")
    async def list_tickets(current_user: dict = Depends(admin)):
        rows = await all_rows()
        rows.sort(key=lambda r: r["updated_at"] or "", reverse=True)
        now = datetime.utcnow()
        needs = [r for r in rows if r["state"] == "needs"]
        recent = [r["first_reply_mins"] for r in rows if r["first_reply_mins"] is not None
                  and (_dt(r["created_at"]) or now) >= now - timedelta(days=30)]
        oldest = min((_dt(r["updated_at"]) for r in needs if _dt(r["updated_at"])), default=None)
        return {"tickets": rows, "issues": await status_issues(), "stats": {
            "needs": len(needs), "waiting": sum(1 for r in rows if r["state"] == "waiting"),
            "closed_7d": sum(1 for r in rows if r["state"] == "closed" and (_dt(r["updated_at"]) or now) >= now - timedelta(days=7)),
            "oldest_needs": _iso(oldest),
            "avg_first_reply_mins": round(sum(recent) / len(recent)) if recent else None,
            "telegram_db": _bot() is not None}}

    @router.get("/ticket/{kind}/{tid}")
    async def ticket(kind: str, tid: str, current_user: dict = Depends(admin)):
        db = D["db"]
        if kind == "web":
            if not ObjectId.is_valid(tid):
                raise HTTPException(404, "Ticket not found")
            t = await db.tickets.find_one({"_id": ObjectId(tid)})
            if not t:
                raise HTTPException(404, "Ticket not found")
            row = next((r for r in await _site_rows() if r["id"] == tid), {})
            msgs = [{"from": "us" if m.get("is_admin") else "customer", "text": m.get("message") or "",
                     "at": _iso(_dt(m.get("created_at"))), "via": m.get("via") or ""} for m in t.get("messages") or []]
            return {"ticket": row, "messages": msgs, "customer": await customer_card(t.get("user_id")),
                    "match": "their website account", "issues": await status_issues()}
        if kind == "tg":
            row = next((r for r in _tg_rows(include_tests=True) if r["id"] == tid), None)
            if not row:
                raise HTTPException(404, "Ticket not found")
            c = _bot()
            msgs = []
            try:
                t = c.execute("SELECT * FROM tickets WHERE id=?", (int(tid),)).fetchone()
                for e in c.execute("SELECT kind, actor, text, created_at FROM events WHERE ticket_id=? ORDER BY id", (int(tid),)):
                    if e["kind"] in ("opened", "customer_msg"):
                        msgs.append({"from": "customer", "text": e["text"] or "", "at": _iso(_dt(e["created_at"]))})
                    elif e["kind"] == "staff_reply":
                        msgs.append({"from": "us", "text": e["text"] or "", "at": _iso(_dt(e["created_at"])), "via": e["actor"] or ""})
                    elif e["kind"] in ("claim", "close", "reopen", "need"):
                        label = {"claim": "picked up", "close": "marked resolved", "reopen": "reopened", "need": "asked for more info"}[e["kind"]]
                        msgs.append({"from": "event", "text": f"{e['actor'] or 'Staff'} {label}", "at": _iso(_dt(e["created_at"]))})
                facts = {k: t[k] for k in ("service", "issue", "device", "order_ref") if t[k] and t[k] != "-"}
            finally:
                c.close()
            for o in await _pending_ops():
                if str(o["ticket_id"]) == tid:
                    msgs.append({"from": "us" if o["action"] == "reply" else "event", "pending": True,
                                 "text": o.get("text") or f"{o['action']} (sending…)", "at": _iso(o["at"])})
            uid, how = await _match_tg_user(row["tg_user_id"], row.get("order_ref"))
            return {"ticket": row, "messages": msgs, "facts": facts, "customer": await customer_card(uid), "match": how,
                    "issues": await status_issues()}
        raise HTTPException(404, "Unknown ticket type")

    async def _queue(tid, action, text, current_user):
        c = _bot()
        if not c:
            raise HTTPException(503, "The support bot's database isn't available")
        try:
            if not c.execute("SELECT 1 FROM tickets WHERE id=?", (int(tid),)).fetchone():
                raise HTTPException(404, "Ticket not found")
        finally:
            c.close()
        admin_user = await D["db"].users.find_one({"_id": ObjectId(current_user["sub"])}, {"name": 1}) if ObjectId.is_valid(current_user.get("sub", "")) else None
        r = await D["db"].cmtv_tg_ticket_ops.insert_one({"ticket_id": int(tid), "action": action, "text": text,
                                                        "by": (admin_user or {}).get("name") or "Admin", "status": "queued",
                                                        "at": datetime.utcnow()})
        return {"ok": True, "id": str(r.inserted_id)}

    @router.post("/tg/{tid}/reply")
    async def tg_reply(tid: str, data: dict = Body(...), current_user: dict = Depends(admin)):
        text = str(data.get("text") or "").strip()
        if not text:
            raise HTTPException(400, "Write a reply first")
        if len(text) > 3500:
            raise HTTPException(400, "That reply is too long for Telegram (3,500 characters max)")
        res = await _queue(tid, "reply", text, current_user)
        if data.get("close"):
            await _queue(tid, "close", "", current_user)
        return res

    @router.post("/tg/{tid}/action")
    async def tg_action(tid: str, data: dict = Body(...), current_user: dict = Depends(admin)):
        action = data.get("action")
        if action not in ("close", "reopen", "need"):
            raise HTTPException(400, "Unknown action")
        return await _queue(tid, action, "", current_user)

    @router.post("/tg/{tid}/link")
    async def tg_link(tid: str, data: dict = Body(...), current_user: dict = Depends(admin)):
        row = next((r for r in _tg_rows(include_tests=True) if r["id"] == tid), None)
        if not row:
            raise HTTPException(404, "Ticket not found")
        q = str(data.get("customer") or "").strip()
        if data.get("unlink"):
            await D["db"].cmtv_tg_customer_links.delete_one({"_id": int(row["tg_user_id"])})
            return {"ok": True}
        db = D["db"]
        u = None
        if ObjectId.is_valid(q):
            u = await db.users.find_one({"_id": ObjectId(q)}, {"_id": 1})
        if not u and q:
            u = await db.users.find_one({"email": {"$regex": f"^{re.escape(q)}$", "$options": "i"}}, {"_id": 1})
        if not u and q:
            s = await db.services.find_one({"username": {"$regex": f"^{re.escape(q)}$", "$options": "i"}}, {"user_id": 1})
            u = {"_id": ObjectId(s["user_id"])} if s and ObjectId.is_valid(s["user_id"]) else None
        if not u:
            raise HTTPException(404, "No customer found with that email or line username")
        await db.cmtv_tg_customer_links.update_one({"_id": int(row["tg_user_id"])}, {"$set": {
            "user_id": str(u["_id"]), "by": current_user.get("sub"), "at": datetime.utcnow()}}, upsert=True)
        return {"ok": True}

    @router.get("/canned")
    async def canned(current_user: dict = Depends(admin)):
        doc = await D["db"].cmtv_config.find_one({"_id": "support_canned"})
        return {"items": (doc or {}).get("items") or DEFAULT_CANNED}

    @router.post("/canned")
    async def save_canned(data: dict = Body(...), current_user: dict = Depends(admin)):
        items = [{"title": str(i.get("title") or "")[:60].strip(), "text": str(i.get("text") or "")[:3000].strip()}
                 for i in (data.get("items") or []) if str(i.get("title") or "").strip() and str(i.get("text") or "").strip()]
        await D["db"].cmtv_config.update_one({"_id": "support_canned"}, {"$set": {"items": items, "updated_at": datetime.utcnow()}},
                                             upsert=True)
        return {"items": items}

    # ---- bot bridge (local calls with the bridge token only, same guard as the other bot bridges)
    from cmtv_telegram_alerts import _bridge_auth

    @bridge.get("")
    async def ops_queue(request: Request):
        _bridge_auth(request)
        ops = [o async for o in D["db"].cmtv_tg_ticket_ops.find({"status": "queued"}).sort("at", 1).limit(20)]
        return {"ops": [{"id": str(o["_id"]), "ticket_id": o["ticket_id"], "action": o["action"], "text": o.get("text") or "",
                         "by": o.get("by") or "Admin"} for o in ops]}

    @bridge.post("/ack")
    async def ops_ack(request: Request, data: dict = Body(...)):
        _bridge_auth(request)
        now = datetime.utcnow()
        for i in data.get("done") or []:
            if ObjectId.is_valid(i):
                await D["db"].cmtv_tg_ticket_ops.update_one({"_id": ObjectId(i)}, {"$set": {"status": "done", "done_at": now}})
        for i, err in (data.get("failed") or {}).items():
            if ObjectId.is_valid(i):
                await D["db"].cmtv_tg_ticket_ops.update_one({"_id": ObjectId(i)}, {"$set": {"status": "failed", "error": str(err)[:300], "done_at": now}})
        return {"ok": True}

    @router.get("/failed")
    async def failed(current_user: dict = Depends(admin)):
        since = datetime.utcnow() - timedelta(days=2)
        return {"failed": [{"ticket_id": o["ticket_id"], "action": o["action"], "error": o.get("error"), "at": _iso(o.get("done_at"))}
                           async for o in D["db"].cmtv_tg_ticket_ops.find({"status": "failed", "done_at": {"$gte": since}})]}


async def needs_count():
    """For the admin sidebar badge."""
    return sum(1 for r in await all_rows() if r["state"] == "needs")
