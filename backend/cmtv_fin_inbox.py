"""Finances > Needs recording (CMTV local addition 2026-09-30).

About half of CMTV's sales never go through billing (customers pay by e-Transfer and the line is renewed straight on the
panel). The spreadsheet caught them because the owner typed them in. Now billing notices them and suggests a ledger row;
nothing is added to the ledger until the owner clicks Record (they can change every field first) or Not a sale.

Suggestions (cmtv_fin_inbox, status open / recorded / dismissed):
- panel_renewal: a line's end date on its panel jumped forward 20+ days (imported_users, refreshed by the hourly panel
  sync) and no paid billing order from that line's owner in the last 3 days paid for it. Months = the jump, snapped to
  1/3/6/12; credits from the credits table; amount = the store price for that plan (editable).
- panel_new: a line billing never sold (no billing service with an order for it) appeared with 20+ days left, not a trial.
- etransfer: an Interac e-Transfer email that matched no pending order (cmtv_etransfers result "no_match"). Exact amount
  and sender. Paired with an open panel suggestion when the sender's name matches the customer (either order of arrival).
Line end dates last seen are kept in cmtv_line_seen; the first scan only records them (no suggestions for the past).
Runs from cmtv_finance's 10-minute loop. New suggestions get one silent Ops Billing note per scan.
"""
import logging
import re
from datetime import datetime, timedelta

from bson import ObjectId
from fastapi import Depends, HTTPException

import cmtv_finance as F

logger = logging.getLogger(__name__)
PANELS = ["xtream", "aether", "xuione", "onestream", "nxtdash"]
JUMP_DAYS = 20          # smaller moves are corrections or bonus days, not a sale
BILLING_WINDOW = timedelta(days=3)


def _db():
    return F.D["db"]


def server_for_line(line: dict) -> str:
    name = str(line.get("panel_name") or "").lower()
    for key, server in (("amethyst", "Amethyst"), ("extreme", "Extreme"), ("imperium", "Imperium"), ("cctv", "CCTV")):
        if key in name:
            return server
    return {"aether": "Imperium", "nxtdash": "Imperium", "onestream": "Extreme", "xuione": "Amethyst"}.get(line.get("panel_type"), "CCTV")


def snap_months(days: float) -> int:
    m = days / 30.44
    best = min((1, 3, 6, 12), key=lambda t: abs(t - m))
    return best if abs(best - m) <= max(0.35, best * 0.2) else max(1, round(m))


def _conns(v) -> int:
    try:
        return int(re.sub(r"[^0-9]", "", str(v)) or 0)
    except ValueError:
        return 0


def _words(name):
    return [w for w in re.sub(r"[^a-z\s]", " ", (name or "").lower()).split() if w]


def names_match(a, b) -> bool:
    x, y = _words(a), _words(b)
    return len(x) >= 2 and len(y) >= 2 and x[0] == y[0] and x[-1] == y[-1]


async def _store_prices(cfg):
    return {(r["server"], r["connections"], r["months"]): r["price"] for r in await F.margins(cfg) if r.get("price")}


async def _owner(line):
    """(service, user) billing has for this line, if any"""
    db = _db()
    q = {"xtream_username": line["username"], "status": {"$nin": ["duplicate"]}}
    if line.get("panel_type"):
        q["panel_type"] = line["panel_type"]
    svc = await db.services.find_one(q, sort=[("status", 1)])
    user = None
    if svc and ObjectId.is_valid(str(svc.get("user_id"))):
        user = await db.users.find_one({"_id": ObjectId(svc["user_id"])})
    return svc, user


def _customer(user, line):
    if user and user.get("name") and "@panel.local" not in str(user.get("email", "")):
        return user["name"]
    if user and user.get("email") and "@panel.local" not in user["email"]:
        return user["email"]
    return line["username"]


async def _billing_paid_recently(user_id, now) -> bool:
    if not user_id:
        return False
    return bool(await _db().orders.find_one({"user_id": user_id, "status": "paid", "total": {"$gt": 0},
                                             "paid_at": {"$gte": now - BILLING_WINDOW}}))


async def scan_lines(now=None):
    """Compare every panel line's end date with the last scan; returns the suggestions made"""
    db = _db()
    now = now or datetime.utcnow()
    baseline = await db.cmtv_line_seen.count_documents({}) == 0
    cfg = await F.config()
    prices = await _store_prices(cfg)
    made = []
    async for line in db.imported_users.find({"account_type": {"$ne": "reseller"}, "panel_type": {"$in": PANELS},
                                              "username": {"$nin": [None, ""]}}):
        key = f"{line.get('panel_type')}|{line.get('panel_name') or ''}|{str(line['username']).lower()}"
        exp = line.get("expiry_date") if isinstance(line.get("expiry_date"), datetime) else None
        seen = await db.cmtv_line_seen.find_one({"_id": key})
        await db.cmtv_line_seen.update_one({"_id": key}, {"$set": {"expiry": exp, "at": now}, "$setOnInsert": {"first_seen": now}},
                                           upsert=True)
        if baseline or exp is None or line.get("is_trial"):
            continue
        old = (seen or {}).get("expiry")
        if seen is not None and old is not None:
            start = max(old, now)
            if exp - old < timedelta(days=JUMP_DAYS) or exp - start < timedelta(days=JUMP_DAYS):
                continue
            kind, days = "panel_renewal", (exp - start).total_seconds() / 86400
        elif seen is None:
            if exp - now < timedelta(days=JUMP_DAYS):
                continue   # trials and short test lines
            kind, days = "panel_new", (exp - now).total_seconds() / 86400
        else:
            continue
        svc, user = await _owner(line)
        uid = str(user["_id"]) if user else None
        if kind == "panel_new" and svc and svc.get("order_id"):
            continue   # billing sold it
        if await _billing_paid_recently(uid, now):
            continue   # billing's own order paid for it (already in the ledger)
        if ((svc or {}).get("auto_renew") or {}).get("status") == "ACTIVE":
            continue   # PayPal auto-renew makes a billing order
        server = server_for_line(line)
        months, conns = snap_months(days), _conns(line.get("max_connections"))
        credits = F.credits_for(cfg, server, conns, months)
        price = prices.get((server, conns, months))
        doc = {"kind": kind, "status": "open", "created_at": now, "date": now.replace(hour=0, minute=0, second=0, microsecond=0),
               "username": line["username"], "panel_type": line.get("panel_type"), "panel_name": line.get("panel_name"),
               "server": server, "old_expiry": old if kind == "panel_renewal" else None, "new_expiry": exp,
               "months": months, "connections": conns, "credits": credits, "credits_known": credits is not None,
               "amount": price, "amount_from": "store price" if price else None, "method": "e-Transfer",
               "customer": _customer(user, line), "user_id": uid, "new_user": kind == "panel_new",
               "line_key": key}
        if await db.cmtv_fin_inbox.find_one({"line_key": key, "new_expiry": exp}):
            continue
        res = await db.cmtv_fin_inbox.insert_one(doc)
        doc["_id"] = res.inserted_id
        await _pair(doc)
        made.append(doc)
    return made


async def scan_etransfers(now=None):
    """e-Transfer emails that matched no pending order -> suggestions (paired with a panel one when the name matches)"""
    db = _db()
    now = now or datetime.utcnow()
    made = []
    async for t in db.cmtv_etransfers.find({"result": "no_match"}):
        ref = str(t["_id"])
        base = ref[4:] if ref.startswith("dep:") else ref
        if ref.startswith("dep:") and await db.cmtv_etransfers.find_one({"_id": base}):
            continue   # the "sent you money" email for the same e-Transfer is the one we use
        if await db.cmtv_fin_inbox.find_one({"etransfer_ref": base}):
            continue
        when = t.get("received_at") or now
        doc = {"kind": "etransfer", "status": "open", "created_at": now, "date": when.replace(hour=0, minute=0, second=0, microsecond=0),
               "amount": float(t.get("amount") or 0), "amount_from": "e-Transfer", "method": "e-Transfer",
               "sender": t.get("name"), "sender_email": t.get("reply_to") or None, "customer": t.get("name"), "etransfer_ref": base, "server": None, "credits": None,
               "months": None, "connections": None, "message": t.get("message"), "new_user": False}
        if await _pair(doc, insert=True):
            continue
        res = await db.cmtv_fin_inbox.insert_one(doc)
        doc["_id"] = res.inserted_id
        made.append(doc)
    return made


async def _pair(doc, insert=False):
    """Join a panel suggestion and an e-Transfer suggestion for the same person (within 4 days). Returns True if joined."""
    db = _db()
    win = {"$gte": doc["date"] - timedelta(days=4), "$lte": doc["date"] + timedelta(days=4)}
    if doc["kind"] == "etransfer":
        async for p in db.cmtv_fin_inbox.find({"status": "open", "kind": {"$in": ["panel_renewal", "panel_new"]},
                                               "etransfer_ref": {"$exists": False}, "date": win}):
            if names_match(doc["sender"], p.get("customer")) or await _known_payer(doc["sender"], p):
                await db.cmtv_fin_inbox.update_one({"_id": p["_id"]}, {"$set": {
                    "amount": doc["amount"], "amount_from": "e-Transfer", "method": "e-Transfer", "sender": doc["sender"],
                    "sender_email": doc.get("sender_email"), "etransfer_ref": doc["etransfer_ref"], "message": doc.get("message")}})
                return True
        return False
    async for e in db.cmtv_fin_inbox.find({"status": "open", "kind": "etransfer", "date": win}):
        if names_match(e.get("sender"), doc.get("customer")) or await _known_payer(e.get("sender"), doc):
            await _join(doc, e)
            return True
    return False


# CMTV local change 2026-10-08 (owner: add the customer's email when their e-Transfer comes in). Panel-only accounts are
# named after their login, so the sender's name never matched them: the owner can pair an e-Transfer with a line by hand,
# billing remembers that payer name on the account (cmtv_payer_names) and pairs the next one by itself, and Record can add
# the e-Transfer's email (Interac Reply-To) to a panel-only account.
async def _join(panel, e):
    """Put e-Transfer suggestion `e` onto panel suggestion `panel`; `e` becomes merged."""
    db = _db()
    await db.cmtv_fin_inbox.update_one({"_id": panel["_id"]}, {"$set": {
        "amount": e["amount"], "amount_from": "e-Transfer", "method": "e-Transfer", "sender": e.get("sender"),
        "sender_email": e.get("sender_email"), "etransfer_ref": e.get("etransfer_ref"), "message": e.get("message")}})
    await db.cmtv_fin_inbox.update_one({"_id": e["_id"]}, {"$set": {"status": "merged", "merged_into": panel["_id"]}})


def _norm(name):
    return " ".join(_words(name))


async def _known_payer(sender, panel):
    """True if this sender name already paid for this line's account before (learned when the owner recorded it)."""
    uid = panel.get("user_id")
    if not sender or not uid or not ObjectId.is_valid(str(uid)):
        return False
    u = await _db().users.find_one({"_id": ObjectId(uid)}, {"cmtv_payer_names": 1})
    return _norm(sender) in (u or {}).get("cmtv_payer_names", [])


def _panel_only(u):
    return bool(u) and u.get("role") == "user" and str(u.get("email") or "").lower().endswith("@panel.local")


async def learn_and_add_email(d, add_email, by):
    """After Record: remember the payer name; optionally put the e-Transfer email on a panel-only account.
    Returns a short message for the admin (or None)."""
    db = _db()
    uid = d.get("user_id")
    u = await db.users.find_one({"_id": ObjectId(uid)}) if uid and ObjectId.is_valid(str(uid)) else None
    if not u:
        return None
    if d.get("sender"):
        await db.users.update_one({"_id": u["_id"]}, {"$addToSet": {"cmtv_payer_names": _norm(d["sender"])}})
    email = str(d.get("sender_email") or "").strip().lower()
    if not (add_email and email and "@" in email and _panel_only(u)):
        return None
    other = await db.users.find_one({"email": {"$regex": f"^{re.escape(email)}$", "$options": "i"}})
    if other:
        return (f"{email} already has an account ({other.get('name') or email}): open this customer's profile and use "
                "Move to an existing customer.")
    upd = {"email": email, "email_verified": False, "cmtv_placeholder_email": u.get("email"), "cmtv_email_added_at": datetime.utcnow(),
           "cmtv_email_added_from": "e-Transfer", "cmtv_email_added_by": by}
    if d.get("sender") and (not u.get("name") or str(u.get("name")).lower() == str(u.get("panel_username") or d.get("username") or "").lower()):
        upd["name"] = " ".join(w.capitalize() for w in str(d["sender"]).split())
    await db.users.update_one({"_id": u["_id"]}, {"$set": upd})
    await db.cmtv_customer_notes.insert_one({"user_id": str(u["_id"]), "created_at": datetime.utcnow(), "by": by, "by_name": "Finances",
                                             "text": f"Email {email} added from their e-Transfer ({d.get('sender')}). Was {u.get('email')}.",
                                             "deleted": False})
    return f"Added {email} to {upd.get('name') or u.get('name') or 'the account'}."


def _label(d):
    if d["kind"] == "etransfer":
        return f"e-Transfer ${d['amount']:,.2f} from {d.get('sender')}"
    what = "renewed on the panel" if d["kind"] == "panel_renewal" else "new line on the panel"
    return f"{d.get('customer')}: {d['server']} {what}, {d.get('months')} mo"


async def scan():
    made = (await scan_lines()) + (await scan_etransfers())
    if made:
        logger.info(f"finance inbox: {len(made)} new sale(s) to record")
        try:
            import cmtv_notify
            lines = "\n".join("• " + _label(d) for d in made[:15]) + (f"\n… and {len(made) - 15} more" if len(made) > 15 else "")
            await cmtv_notify.ops(f"🧾 <b>To record in Finances</b> ({len(made)})\n{lines}\n\nAdmin > Finances > Needs recording",
                                  "billing", silent=True)
        except Exception as e:
            logger.warning(f"finance inbox note not sent ({type(e).__name__})")
    return made


def _out(d):
    d = dict(d)
    d["id"] = str(d.pop("_id"))
    for k in ("merged_into", "tx_id"):
        if k in d:
            d[k] = str(d[k])
    return d


def add_routes(router, admin):
    db = _db

    @router.get("/inbox")
    async def api_inbox(user=Depends(admin)):
        open_ = await db().cmtv_fin_inbox.find({"status": "open"}).sort("date", -1).to_list(500)
        done = await db().cmtv_fin_inbox.find({"status": {"$in": ["recorded", "dismissed"]}}).sort("handled_at", -1).to_list(15)
        out = [_out(d) for d in open_]
        for d in out:   # 2026-10-08: is the line's account panel-only (no real email yet)?
            uid = d.get("user_id")
            u = await db().users.find_one({"_id": ObjectId(uid)}, {"email": 1, "role": 1}) if uid and ObjectId.is_valid(str(uid)) else None
            d["panel_only"] = _panel_only(u)
        return {"open": out, "recent": [_out(d) for d in done]}

    @router.post("/inbox/{item_id}/pair")
    async def api_pair(item_id: str, data: dict, user=Depends(admin)):
        """2026-10-08: the owner says which open e-Transfer paid for this panel line."""
        p = await db().cmtv_fin_inbox.find_one({"_id": ObjectId(item_id), "status": "open"}) if ObjectId.is_valid(item_id) else None
        eid = str((data or {}).get("etransfer_id") or "")
        e = await db().cmtv_fin_inbox.find_one({"_id": ObjectId(eid), "status": "open", "kind": "etransfer"}) if ObjectId.is_valid(eid) else None
        if not p or p["kind"] == "etransfer" or p.get("etransfer_ref") or not e:
            raise HTTPException(status_code=404, detail="Already handled")
        await _join(p, e)
        return {"ok": True}

    @router.post("/inbox/{item_id}/record")
    async def api_record(item_id: str, data: dict, user=Depends(admin)):
        d = await db().cmtv_fin_inbox.find_one({"_id": ObjectId(item_id)}) if ObjectId.is_valid(item_id) else None
        if not d or d["status"] != "open":
            raise HTTPException(status_code=404, detail="Already handled")
        row = await F.add_manual(data, user, extra={"inbox_id": str(d["_id"]), "inbox_kind": d["kind"],
                                                     "user_id": d.get("user_id"), "etransfer_ref": d.get("etransfer_ref")})
        await db().cmtv_fin_inbox.update_one({"_id": d["_id"], "status": "open"}, {"$set": {
            "status": "recorded", "tx_id": ObjectId(row["id"]), "handled_at": datetime.utcnow(), "handled_by": user.get("email")}})
        try:   # 2026-10-08: remember the payer name; add their e-Transfer email to a panel-only account when asked
            row["email_note"] = await learn_and_add_email(d, bool((data or {}).get("add_email")), user.get("email"))
        except Exception as e:
            logger.warning(f"finance inbox: email/payer update failed: {e}")
        return row

    @router.post("/inbox/{item_id}/dismiss")
    async def api_dismiss(item_id: str, data: dict, user=Depends(admin)):
        res = await db().cmtv_fin_inbox.update_one(
            {"_id": ObjectId(item_id) if ObjectId.is_valid(item_id) else None, "status": "open"},
            {"$set": {"status": "dismissed", "reason": str((data or {}).get("reason") or "").strip()[:200],
                      "handled_at": datetime.utcnow(), "handled_by": user.get("email")}})
        if not res.matched_count:
            raise HTTPException(status_code=404, detail="Already handled")
        return {"ok": True}

    @router.post("/inbox/{item_id}/reopen")
    async def api_reopen(item_id: str, user=Depends(admin)):
        res = await db().cmtv_fin_inbox.update_one(
            {"_id": ObjectId(item_id) if ObjectId.is_valid(item_id) else None, "status": "dismissed"},
            {"$set": {"status": "open"}, "$unset": {"handled_at": "", "handled_by": "", "reason": ""}})
        if not res.matched_count:
            raise HTTPException(status_code=404, detail="Only a dismissed item can be reopened")
        return {"ok": True}

    @router.post("/inbox/scan")
    async def api_scan(user=Depends(admin)):
        made = await scan()
        return {"new": len(made)}
