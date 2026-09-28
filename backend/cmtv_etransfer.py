"""Interac e-Transfer notifications -> billing (CMTV local addition 2026-09-28).

The user keeps Autodeposit off, so an e-Transfer arrives as a Proton email ("Interac e-Transfer: <NAME> sent you
$<AMOUNT>. Claim your deposit!", from notify@payments.interac.ca) and is deposited by hand later. A Proton filter
forwards ONLY those emails to a private Cloudflare Email Routing address; a Cloudflare Email Worker POSTs the raw email
here (POST /api/cmtv/etransfer/inbound, header X-Inbound-Token = ETRANSFER_INBOUND_TOKEN in /opt/backend/.env).

The email has no customer message (Interac shows it only when depositing), so it's matched on:
  pending order paid by e-Transfer / manual, total == the amount, created in the last 14 days, and
  sender name == customer name (first + last word, ignoring middle names/initials) or Interac's Reply-To == their email.
Exactly one match + a RETURNING customer (at least one earlier paid order with a total > 0) -> provisioned now
("trusted"); the order stays pending until the user deposits it and marks it paid in Admin > Orders (the provisioning
lock stops that from provisioning twice). Anything else -> Telegram (Billing topic) with the likely order to check.
Each e-Transfer is handled once (cmtv_etransfers, _id = Interac reference number). An order set up on trust that is
still pending after 48 h -> one Critical alert.
"""
import asyncio
import email
import hmac
import html as htmlmod
import logging
import os
import re
from datetime import datetime, timedelta
from email import policy
from email.utils import parseaddr

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api/cmtv/etransfer", tags=["cmtv-etransfer"])
D = {}
log = logging.getLogger("server")

INTERAC_DOMAIN = "payments.interac.ca"
SUBJECT = re.compile(r"Interac e-Transfer:\s*(?P<name>.+?)\s+sent you\s+\$(?P<amount>[\d,]+\.\d{2})", re.I)
WINDOW_DAYS = 14
TRUST_ALERT_HOURS = 48
SITE = "https://billing.cmtv.info"


def init(**deps):
    D.update(deps)


# ---------- parsing ----------

def _text(msg) -> str:
    part = msg.get_body(preferencelist=("html", "plain"))
    if part is None:
        return ""
    raw = part.get_content()
    raw = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    return re.sub(r"\s+", " ", htmlmod.unescape(raw)).strip()


def parse(raw: str) -> dict:
    """Pull the facts out of an Interac notification. Works on the original or a forwarded copy."""
    msg = email.message_from_string(raw, policy=policy.default)
    subject = re.sub(r"^(\s*(fwd?|tr)\s*:\s*)+", "", str(msg.get("Subject") or ""), flags=re.I)
    text = _text(msg)
    m = SUBJECT.search(subject)
    name = m.group("name").strip() if m else None
    amount = float(m.group("amount").replace(",", "")) if m else None
    if name is None:
        mm = re.search(r"Sent From:\s*(.+?)\s+Amount:", text)
        name = mm.group(1).strip() if mm else None
    if amount is None:
        mm = re.search(r"Amount:\s*\$([\d,]+\.\d{2})", text)
        amount = float(mm.group(1).replace(",", "")) if mm else None
    ref = str(msg.get("X-Paymentkey") or "").strip()
    if not ref:
        mm = re.search(r"Reference Number:\s*([A-Za-z0-9]{6,})", text)
        ref = mm.group(1) if mm else ""
    auth = " ".join(str(h) for h in (msg.get_all("Authentication-Results") or []))
    # the sender's message, when they wrote one (customers are asked to put their order ID in it)
    mm = re.search(r"Message:\s*(.{1,400}?)\s*(?=Reference Number:|Sent From:|Amount:|Date:|FAQ|This is a secure|$)", text)
    message = mm.group(1).strip() if mm else ""
    # customers type the order ID at different lengths (e.g. "6ab42bb66a68"): any 6-24 hex characters = its start
    order_refs = sorted({t.lower() for t in re.findall(r"(?<![0-9a-zA-Z])[0-9a-fA-F]{6,24}(?![0-9a-zA-Z])", message)
                         if re.search(r"[0-9]", t) and re.search(r"[a-fA-F]", t)})
    low = f"{subject} {text}".lower()
    # "... sent you $X. Claim your deposit!" (money waiting) or the confirmation after it is deposited
    if re.search(r"has been deposited|was deposited|you've deposited|you deposited|into your account at", low):
        kind = "deposited"
    elif "claim your deposit" in low or "deposit funds" in low or " sent you " in subject.lower():
        kind = "claim"
    else:
        kind = None
    return {
        "from": parseaddr(str(msg.get("From") or ""))[1].lower(),
        "reply_to": parseaddr(str(msg.get("Reply-To") or ""))[1].lower(),
        "subject": subject[:200],
        "name": name,
        "amount": amount,
        "reference": ref,
        "notification_id": str(msg.get("X-Payment-Notification") or ""),
        "message": message[:300],
        "order_refs": order_refs,
        "kind": kind,
        "dkim_interac": bool(re.search(r"dkim=pass[^;]*header\.d=payments\.interac\.ca", auth)),
    }


# ---------- matching ----------

def _words(name: str) -> list:
    return [w for w in re.sub(r"[^a-z\s]", " ", (name or "").lower()).split() if w]


def names_match(sender: str, customer: str) -> bool:
    a, b = _words(sender), _words(customer)
    return len(a) >= 2 and len(b) >= 2 and a[0] == b[0] and a[-1] == b[-1]


async def candidates(facts: dict):
    """Pending e-Transfer/manual orders for this amount whose customer matches the sender."""
    orders, users = D["orders"], D["users"]
    since = datetime.utcnow() - timedelta(days=WINDOW_DAYS)
    amount = facts["amount"]
    out, same_amount = [], []
    # 1. an order ID in the customer's message wins, if the amount covers that order
    if facts.get("order_refs"):
        async for o in orders.find({"status": "pending", "payment_method": {"$in": ["emt", "manual"]},
                                    "created_at": {"$gte": since}}):
            oid = str(o["_id"]).lower()
            if any(oid == r or oid.startswith(r) for r in facts["order_refs"]) and float(o.get("total") or 0) <= amount + 0.005:
                u = await users.find_one({"_id": D["oid"](o["user_id"])})
                if u:
                    out.append((o, u, "order ID in the message"))
        if len(out) == 1:
            return out, []
        out = []
    # 2. otherwise: same amount + the sender's name or email
    async for o in orders.find({"status": "pending", "payment_method": {"$in": ["emt", "manual"]},
                                "created_at": {"$gte": since},
                                "total": {"$gte": amount - 0.005, "$lte": amount + 0.005}}).sort("created_at", 1):
        u = await users.find_one({"_id": D["oid"](o["user_id"])})
        if not u:
            continue
        same_amount.append((o, u))
        by_name = names_match(facts["name"] or "", u.get("name") or "")
        by_email = bool(facts["reply_to"]) and facts["reply_to"] == str(u.get("email") or "").lower()
        if by_name or by_email:
            out.append((o, u, "name" if by_name else "email"))
    return out, same_amount


async def returning_customer(user_id: str, before) -> bool:
    return await D["orders"].count_documents({"user_id": user_id, "status": "paid", "total": {"$gt": 0},
                                              "created_at": {"$lt": before}}) > 0


def _money(v) -> str:
    return f"${float(v):,.2f}"


def _order_line(o, u) -> str:
    items = ", ".join(i.get("product_name", "") for i in o.get("items", []))
    return (f"Order #{str(o['_id'])[:8]} · {u.get('name')} &lt;{u.get('email')}&gt;\n{htmlmod.escape(items)}\n"
            f"{SITE}/admin/orders")


async def handle(facts: dict) -> dict:
    """Decide what to do with one parsed Interac notification. Returns what happened."""
    col = D["etransfers"]
    key = facts["reference"] or facts["notification_id"]
    if key and facts.get("kind") == "deposited":
        key = "dep:" + key   # the deposit confirmation is a second, separate email for the same e-Transfer
    if not key or facts["amount"] is None or not facts["name"]:
        await _notify(f"💸 <b>e-Transfer email I couldn't read</b>\n\nSubject: {htmlmod.escape(facts.get('subject') or '')}\n"
                      "Check it in Proton and match it by hand.")
        return {"result": "unreadable"}
    if await col.find_one({"_id": key}):
        return {"result": "duplicate", "reference": key}
    doc = {"_id": key, "received_at": datetime.utcnow(), **{k: facts.get(k) for k in
           ("name", "amount", "reply_to", "subject", "notification_id", "dkim_interac", "message")}}
    try:
        await col.insert_one(doc)
    except Exception:   # a second copy arrived at the same moment
        return {"result": "duplicate", "reference": key}

    head = f"💸 <b>e-Transfer {_money(facts['amount'])}</b> from {htmlmod.escape(facts['name'])}"
    if facts.get("message"):
        head += f"\nMessage: “{htmlmod.escape(facts['message'])}”"
    matches, same_amount = await candidates(facts)
    result, order_id = "review", None

    if len(matches) == 1:
        o, u, how = matches[0]
        order_id = str(o["_id"])
        deposited = facts.get("kind") == "deposited"
        returning = await returning_customer(o["user_id"], o["created_at"])
        next_step = ("It's in your bank: mark the order paid in Admin > Orders." if deposited
                     else "Deposit it in your bank, then mark the order paid in Admin > Orders.")
        if o.get("provisioning"):
            # already set up (on trust when the "sent you money" email came, or by hand)
            await D["orders"].update_one({"_id": o["_id"]}, {"$set": {"cmtv_emt.deposited_at": datetime.utcnow()}}
                                         if deposited else {"$set": {"cmtv_emt.seen_again_at": datetime.utcnow()}})
            await _notify(f"{head}\n\n💰 <b>{'Deposited' if deposited else 'Received'}</b>, service already set up\n"
                          f"{_order_line(o, u)}\n\n{next_step}")
            result = "already_set_up"
        elif returning or (deposited and facts.get("dkim_interac")):
            reason = "returning customer" if returning else "money deposited, Interac signature checked"
            now = datetime.utcnow()
            await D["orders"].update_one({"_id": o["_id"]}, {"$set": {"cmtv_emt": {
                "reference": key, "sender": facts["name"], "amount": facts["amount"], "matched_by": how,
                "received_at": now, "trusted": True, "reason": reason, "provisioned_on_trust_at": now,
                **({"deposited_at": now} if deposited else {})}}})
            await D["provision"](order_id, o, u)
            o2 = await D["orders"].find_one({"_id": o["_id"]}, {"provisioning_status": 1})
            status = (o2 or {}).get("provisioning_status")
            result = "provisioned" if status == "ok" else f"provision_{status or 'unknown'}"
            await _notify(f"{head}\n\n✅ <b>Set up automatically</b> ({reason}, matched by {how})\n"
                          f"{_order_line(o, u)}\n\n{next_step}"
                          + ("" if status == "ok" else f"\n\n⚠️ Setup result: {status}. Check the order."))
        else:
            await D["orders"].update_one({"_id": o["_id"]}, {"$set": {"cmtv_emt": {
                "reference": key, "sender": facts["name"], "amount": facts["amount"], "matched_by": how,
                "received_at": datetime.utcnow(), "trusted": False}}})
            await _notify(f"{head}\n\n👀 <b>Matches a first-time customer</b> (by {how}). Check it and mark paid:\n"
                          f"{_order_line(o, u)}")
            result = "review_new_customer"
    elif len(matches) > 1:
        lines = "\n\n".join(_order_line(o, u) for o, u, _ in matches[:5])
        await _notify(f"{head}\n\n❓ <b>Matches {len(matches)} pending orders</b>. Pick the right one and mark it paid:\n\n{lines}")
        result = "review_several"
    elif same_amount:
        lines = "\n\n".join(_order_line(o, u) for o, u in same_amount[:5])
        await _notify(f"{head}\n\n❓ <b>No customer with that name</b>, but pending orders have that amount:\n\n{lines}")
        result = "review_name_differs"
    else:
        await _notify(f"{head}\n\n❓ <b>No pending e-Transfer order for that amount</b> in the last {WINDOW_DAYS} days.\n"
                      "It may be a renewal done outside billing, or a different amount.")
        result = "no_match"

    await col.update_one({"_id": key}, {"$set": {"result": result, "order_id": order_id}})
    log.info(f"e-Transfer {key} {facts['amount']} from {facts['name']}: {result} {order_id or ''}")
    return {"result": result, "reference": key, "order_id": order_id}


def _plain(text: str) -> str:
    """cmtv_notify.ops sends plain text: drop the <b> marks and undo the escaping"""
    return htmlmod.unescape(re.sub(r"</?b>", "", text))


async def _notify(text: str):
    try:
        import cmtv_notify
        await cmtv_notify.ops(_plain(text), "billing", await D["get_settings"]())
    except Exception as e:
        log.warning(f"e-Transfer Telegram failed: {e}")


# ---------- 48 h check ----------

async def check_unconfirmed():
    cutoff = datetime.utcnow() - timedelta(hours=TRUST_ALERT_HOURS)
    async for o in D["orders"].find({"status": "pending", "cmtv_emt.trusted": True,
                                     "cmtv_emt.provisioned_on_trust_at": {"$lt": cutoff},
                                     "cmtv_emt.alerted_at": {"$exists": False}}):
        u = await D["users"].find_one({"_id": D["oid"](o["user_id"])}) or {}
        try:
            import cmtv_notify
            await cmtv_notify.ops(_plain(
                f"⏰ <b>e-Transfer set up on trust, still not marked paid after {TRUST_ALERT_HOURS} h</b>\n\n"
                f"{_money(o.get('total') or 0)} from {htmlmod.escape(o['cmtv_emt'].get('sender') or '')} "
                f"(ref {o['cmtv_emt'].get('reference')})\n{_order_line(o, u)}\n\n"
                "Deposit it and mark the order paid, or suspend the line if the money never came."),
                "critical", await D["get_settings"]())
        except Exception as e:
            log.warning(f"e-Transfer 48h alert failed: {e}")
            continue
        await D["orders"].update_one({"_id": o["_id"]}, {"$set": {"cmtv_emt.alerted_at": datetime.utcnow()}})


async def _loop():
    while True:
        try:
            await check_unconfirmed()
        except Exception as e:
            log.warning(f"e-Transfer check failed: {e}")
        await asyncio.sleep(3600)


async def startup():
    asyncio.create_task(_loop())


# ---------- the inbound endpoint (called by the Cloudflare Email Worker) ----------

@router.post("/inbound")
async def inbound(request: Request):
    token = os.environ.get("ETRANSFER_INBOUND_TOKEN", "")
    given = request.headers.get("X-Inbound-Token", "")
    if not token or not hmac.compare_digest(token, given):
        raise HTTPException(status_code=403, detail="forbidden")
    body = await request.json()
    raw = str(body.get("raw") or "")
    if not raw or len(raw) > 3_000_000:
        raise HTTPException(status_code=400, detail="no email")
    facts = parse(raw)
    if not facts["from"].endswith("@" + INTERAC_DOMAIN) and not facts["from"].endswith("." + INTERAC_DOMAIN):
        log.info(f"e-Transfer inbound: ignored an email from {facts['from']}")
        return {"result": "ignored_not_interac"}
    if not facts["kind"]:
        return {"result": "ignored_not_a_transfer"}
    return await handle(facts)
