"""Pay for your order: the exact e-Transfer / Wise details, and automatic Wise payment matching (CMTV local addition
2026-10-09; owner: "after a person chooses e-Transfer give them all the exact details to use ... I get too many questions
afterward", and Wise as a second option to PayPal for international customers).

Details: cmtv_config {_id: "pay_details"}: emt_email, wise_tag, wise_email, wise_name, wise_bank {CAD, USD, EUR, GBP: text the
owner pastes from Wise}, wise_profile_id (the CMTV business profile). Admin > Payment details edits them.
  GET  /api/cmtv/pay/order/{order_id}   the signed-in customer's own order (or an admin): amount + exact details for its method
  GET  /api/cmtv/pay/admin/details      admin: the details;  POST same path: save them
Order email: send_pending(order_id, user, total, method) for e-Transfer and Wise orders (one email, every detail + a button to
the /pay page). Replaces cmtv_hours.send_emt_pending at order time (server.py create_order).
Wise watcher (every minute since 2026-10-09; was 5 minutes): reads the business profile's balance statements with the token in Admin > Settings > Payment
gateways > Wise (read-only is enough). An incoming payment received after the watcher first ran, whose reference has a pending
order's number (its first 6-24 characters) and whose amount covers the order (CAD, or another currency at Wise's rate with 3%
leeway) -> the same steps as Admin > Orders > Mark paid (payment method Wise: paid email, alerts, setup) + Ops Billing note.
Anything else -> Ops Billing note to check by hand. Log: cmtv_wise_payments (_id = Wise reference number; never twice).
"""
import asyncio
import html
import logging
import re
from datetime import datetime, timedelta

from bson import ObjectId
from fastapi import APIRouter, Body, Depends, HTTPException
from pymongo.errors import DuplicateKeyError

log = logging.getLogger("server")
router = APIRouter(prefix="/api/cmtv/pay", tags=["cmtv-pay"])
D = {}
SITE = "https://billing.cmtv.info"
WISE = "https://api.wise.com"
BUSINESS_PROFILE = "144918505"   # the CMTV business profile on Wise (checked 2026-10-09)
CURRENCIES = ("CAD", "USD", "EUR", "GBP")
DEFAULTS = {"emt_email": "cmtvpayments@pm.me", "wise_tag": "", "wise_email": "", "wise_name": "CMTV", "wise_link": "",
            "wise_bank": {c: "" for c in CURRENCIES}, "wise_profile_id": BUSINESS_PROFILE}
LEEWAY = 0.97
HEX = re.compile(r"[0-9a-fA-F]{6,24}")
EMT_QUESTION = "What is my CMTV order number?"


def init(**deps):
    D.update(deps)


def _oid(v):
    return ObjectId(v) if ObjectId.is_valid(str(v)) else None


def ref_code(order_id) -> str:
    """The short order number customers put in a Wise reference (some bank routes allow only ~10-18 characters)."""
    return str(order_id)[:10].upper()


async def details():
    doc = await D["db"].cmtv_config.find_one({"_id": "pay_details"}) or {}
    out = {**DEFAULTS, **{k: v for k, v in doc.items() if k in DEFAULTS}}
    out["wise_bank"] = {c: str((doc.get("wise_bank") or {}).get(c) or "") for c in CURRENCIES}
    return out


def _wise_ready(dt):
    return bool(dt["wise_tag"] or dt["wise_email"] or dt["wise_link"] or any(dt["wise_bank"].values()))


async def view(order, dt=None):
    """What the /pay page and the order email show for this order."""
    dt = dt or await details()
    oid = str(order["_id"])
    out = {"order_id": oid, "status": order.get("status"), "method": order.get("payment_method"),
           "total": round(float(order.get("total") or 0), 2), "currency": "CAD",
           "items": [i.get("product_name") for i in order.get("items") or []]}
    if out["method"] == "emt":
        out["emt"] = {"send_to": dt["emt_email"], "amount": out["total"], "question": EMT_QUESTION, "answer": oid, "message": oid}
    if out["method"] == "wise":
        out["wise"] = {"tag": dt["wise_tag"], "email": dt["wise_email"], "name": dt["wise_name"], "reference": ref_code(oid),
                       "link": dt["wise_link"],   # 2026-10-09: the Wise "get paid" link (button + QR on the pay page)
                       "amount": out["total"], "bank": {c: v for c, v in dt["wise_bank"].items() if v}, "ready": _wise_ready(dt)}
    try:
        import cmtv_hours
        st = await cmtv_hours.current()
        out["hours"] = {"open_now": st.get("open_now"), "hours": st.get("hours"), "next_open_text": st.get("next_open_text"),
                        "away_note": st.get("away_note")}
    except Exception:
        out["hours"] = None
    return out


# ---------------- order email ----------------

def _email(v, name):
    from cmtv_gifts import _shell, _section, _button, P, FONT, STRIP
    first = html.escape((name or "there").split()[0])
    row = lambda k, val, mono=False: (
        f'<tr><td style="padding:11px 0; font-size:13px; color:#8b96b3; border-bottom:1px solid #1d2740; width:40%; {FONT}">{k}</td>'
        f'<td style="padding:11px 0; font-size:{"16" if mono else "15"}px; color:#ffffff; border-bottom:1px solid #1d2740; font-weight:bold; '
        f'{"font-family:Consolas, Menlo, monospace; letter-spacing:1px; word-break:break-all;" if mono else FONT}">{val}</td></tr>')
    box = lambda rows: (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#0a0e1a; '
                        f'border-radius:8px; margin-bottom:24px; overflow:hidden;"><tr><td>{STRIP}</td></tr><tr><td style="padding:14px 22px 18px;">'
                        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0">{rows}</table></td></tr></table>')
    p = lambda t: f'<p style="margin:0 0 16px; font-size:15px; line-height:1.6; color:#374151; {FONT}">{t}</p>'
    amount = f"${v['total']:.2f} CAD"
    if v["method"] == "emt":
        e = v["emt"]
        subject = f"Pay for your CMTV order: e-Transfer {amount}"
        body = (f'<p style="{P}">Hi {first},</p>' + p("Thanks for your order! Send an Interac e-Transfer with exactly these details:")
                + box(row("Send to", html.escape(e["send_to"])) + row("Amount", amount)
                      + row("Security question", html.escape(e["question"])) + row("Answer", html.escape(e["answer"]), True)
                      + row("Message", html.escape(e["message"]), True))
                + p("If your bank doesn't ask for a security question, skip it. The answer and the message are both your order number."))
        pre = f"Send {amount} by e-Transfer to {e['send_to']}. Answer and message: {e['answer']}."
    else:
        w = v["wise"]
        rows = row("Amount", amount) + row("Reference", html.escape(w["reference"]), True)
        if w["tag"]:
            rows += row("Wise users: send to", html.escape(w["tag"]))
        if w["email"]:
            rows += row("or Wise email", html.escape(w["email"]))
        if w.get("link"):
            rows += row("or tap", f'<a href="{html.escape(w["link"])}" style="color:#22e6f2;">Pay in the Wise app</a>')
        subject = f"Pay for your CMTV order: Wise {amount}"
        body = (f'<p style="{P}">Hi {first},</p>' + p("Thanks for your order! Pay with Wise using exactly these details:") + box(rows))
        if w["bank"]:
            body += _section("No Wise account? Pay from your own bank")
            for cur, txt in w["bank"].items():
                body += p(f"<b>{cur}</b><br>" + html.escape(txt).replace("\n", "<br>"))
            body += p(f"Use the same reference <b>{html.escape(w['reference'])}</b>. If you pay in another currency, send the "
                      f"equivalent of {amount}.")
        body += p("Your order is set up automatically as soon as the payment reaches us (Wise transfers usually take minutes, "
                  "bank transfers up to 1-2 business days).")
        pre = f"Pay {amount} with Wise, reference {w['reference']}."
    h = v.get("hours")
    if v["method"] == "emt" and h:
        when = (f"We're online now ({html.escape(h['hours'] or '')}), so you'll be set up soon after your e-Transfer arrives." if h["open_now"]
                else f"We confirm e-Transfers {html.escape(h['hours'] or '')}. We're offline right now, so you'll be set up by about "
                     f"<b>{html.escape(h.get('next_open_text') or 'our next opening')}</b>.")
        body += _section("When it's ready") + p(when)
    body += _button(f"{SITE}/pay/{v['order_id']}", "Open my payment details") + p("You'll get your login details by email as soon as it's set up.")
    return subject, _shell(pre, "Thanks for your order!", body)


async def send_pending(order_id, user, total, method):
    """One email after an e-Transfer or Wise order is placed: every exact detail + a link to the /pay page."""
    try:
        if not (user or {}).get("email") or str(user["email"]).endswith("@panel.local"):
            return
        o = await D["orders"].find_one({"_id": _oid(order_id)})
        if not o:
            return
        v = await view(o)
        if method == "wise" and not v["wise"]["ready"]:
            return
        subject, body = _email(v, user.get("name"))
        es = await D["get_email_service"]()
        await es.send_email(to_email=user["email"], subject=subject, html_content=es._wrap_email(body, subject, user["email"], "transactional"),
                            email_type="transactional", order_id=str(order_id), recipient_name=user.get("name"),
                            template_type=f"cmtv_pay_{method}")
    except Exception as e:
        log.warning(f"CMTV pay: order email failed for {order_id}: {e}")


# ---------------- Wise watcher ----------------

async def _wise(path, params=None):
    import httpx
    tok = str(((await D["get_settings"]()).get("wise") or {}).get("api_token") or "").strip()
    if not tok:
        return None
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(WISE + path, params=params, headers={"Authorization": f"Bearer {tok}"})
    if r.status_code != 200:
        raise RuntimeError(f"Wise {path.split('?')[0]} answered {r.status_code}")
    return r.json()


async def _rate(cur):
    if cur == "CAD":
        return 1.0
    r = await _wise("/v1/rates", {"source": cur, "target": "CAD"})
    return float(r[0]["rate"]) if r else None


async def _ops(text, kind="billing"):
    try:
        import cmtv_notify
        await cmtv_notify.ops(text, kind, await D["get_settings"](), silent=kind == "billing")
    except Exception as e:
        log.warning(f"CMTV pay: Ops note failed: {e}")


async def match(tx_text, amount, currency, now=None):
    """(order, why) for an incoming Wise payment: a pending order whose number is in the reference and whose total it covers."""
    codes = {c.lower() for c in HEX.findall(tx_text or "")}
    if not codes:
        return None, "no order number in the reference"
    now = now or datetime.utcnow()
    found = []
    async for o in D["orders"].find({"status": "pending", "total": {"$gt": 0}, "created_at": {"$gte": now - timedelta(days=45)}}):
        oid = str(o["_id"])
        if any(oid.startswith(c) for c in codes):
            found.append(o)
    if len(found) != 1:
        return None, "no pending order with that number" if not found else "more than one order matches"
    o = found[0]
    rate = await _rate(currency)
    if rate is None:
        return None, f"no exchange rate for {currency}"
    cad = amount * rate
    need = float(o.get("total") or 0)
    if cad + 0.01 < (need if currency == "CAD" else need * LEEWAY):
        return None, f"amount {amount:.2f} {currency} (about ${cad:.2f} CAD) is short of ${need:.2f}"
    return o, f"{amount:.2f} {currency}" + ("" if currency == "CAD" else f" (about ${cad:.2f} CAD)")


async def handle(tx, now=None):
    """One incoming Wise payment (a statement transaction). Returns the result string."""
    db = D["db"]
    now = now or datetime.utcnow()
    det = tx.get("details") or {}
    ref = str(tx.get("referenceNumber") or "")
    amount = float((tx.get("amount") or {}).get("value") or 0)
    cur = str((tx.get("amount") or {}).get("currency") or "")
    text = " ".join(str(x) for x in (det.get("paymentReference"), det.get("description")) if x)
    sender = det.get("senderName") or ""
    try:
        await db.cmtv_wise_payments.insert_one({"_id": ref, "amount": amount, "currency": cur, "sender": sender, "reference": text,
                                                "date": tx.get("date"), "seen_at": now, "result": "checking"})
    except DuplicateKeyError:
        return "seen"
    o, why = await match(text, amount, cur, now)
    if not o:
        await db.cmtv_wise_payments.update_one({"_id": ref}, {"$set": {"result": "no_match", "why": why}})
        await _ops(f"💶 <b>Wise payment to check</b>: {amount:.2f} {html.escape(cur)} from {html.escape(sender or 'unknown')}\n"
                   f"Reference: {html.escape(text or '(none)')}\nNot matched: {html.escape(why)}.\nMark the order paid in Admin > Orders, "
                   "or record it in Finances.")
        return "no_match"
    oid = str(o["_id"])
    await D["orders"].update_one({"_id": o["_id"]}, {"$set": {"cmtv_wise": {"reference": ref, "amount": amount, "currency": cur,
                                                                            "sender": sender, "received_at": now}}})
    try:
        await D["mark_paid"](oid)
        result = "paid"
    except Exception as e:
        result = "mark_paid_failed"
        log.error(f"CMTV pay: Wise payment {ref} matched order {oid} but marking it paid failed: {e}")
    await db.cmtv_wise_payments.update_one({"_id": ref}, {"$set": {"result": result, "order_id": oid, "why": why}})
    u = await D["users"].find_one({"_id": _oid(o.get("user_id"))}, {"name": 1, "email": 1}) or {}
    if result == "paid":
        await _ops(f"✅ <b>Wise payment matched</b>: {html.escape(why)} from {html.escape(sender or 'unknown')}\n"
                   f"Order #{oid[:8]} · {html.escape(u.get('name') or '')} &lt;{html.escape(u.get('email') or '')}&gt;: marked paid, setting up.")
    else:
        await _ops(f"⚠️ <b>Wise payment matched but not marked paid</b>: order #{oid[:8]} ({html.escape(why)}). Mark it paid in Admin > Orders.",
                   "critical")
    return result


async def check_wise(now=None):
    """One pass over the business profile's balances: new incoming payments since the watcher started."""
    db = D["db"]
    now = now or datetime.utcnow()
    cfg = await db.cmtv_config.find_one({"_id": "wise_watch"}) or {}
    if not cfg.get("since"):
        await db.cmtv_config.update_one({"_id": "wise_watch"}, {"$set": {"since": now}}, upsert=True)
        return []   # first run: start from now (never older payments)
    since = cfg["since"]
    pid = (await details())["wise_profile_id"] or BUSINESS_PROFILE
    balances = await _wise(f"/v4/profiles/{pid}/balances", {"types": "STANDARD"})
    if balances is None:
        return []
    start = max(since, now - timedelta(days=3))
    out = []
    for b in balances:
        st = await _wise(f"/v1/profiles/{pid}/balance-statements/{b['id']}/statement.json",
                         {"currency": b.get("currency"), "intervalStart": start.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                          "intervalEnd": now.strftime("%Y-%m-%dT%H:%M:%S.000Z"), "type": "COMPACT"})
        for tx in (st or {}).get("transactions") or []:
            if str(tx.get("type") or "").upper() != "CREDIT" or float((tx.get("amount") or {}).get("value") or 0) <= 0:
                continue
            if (tx.get("details") or {}).get("type") in ("CONVERSION", "BALANCE_CASHBACK", "BALANCE_INTEREST"):
                continue   # money moved between our own balances, cashback, interest
            out.append(await handle(tx, now))
    return out


async def _loop():
    await asyncio.sleep(60)
    last_alert = None
    while True:
        try:
            if ((await D["get_settings"]()).get("wise") or {}).get("enabled"):
                res = [r for r in await check_wise() if r != "seen"]
                if res:
                    log.info(f"CMTV pay: Wise payments {res}")
        except Exception as e:
            log.warning(f"CMTV pay: Wise check failed: {e}")
            if not last_alert or datetime.utcnow() - last_alert > timedelta(hours=24):
                last_alert = datetime.utcnow()
                await _ops(f"⚠️ <b>Wise check failing</b>: {html.escape(str(e))[:200]}. Wise payments aren't being matched; check the "
                           "token in Admin > Settings > Payment gateways > Wise.", "critical")
        await asyncio.sleep(60)   # 2026-10-09 (owner): every minute (was 5); 5 small read-only calls


def start():
    if not D.get("task"):
        D["task"] = asyncio.get_event_loop().create_task(_loop())


# ---------------- routes ----------------

def init_routes():
    current, admin = D["get_current_user"], D["get_current_admin_user"]

    @router.get("/order/{order_id}")
    async def pay_view(order_id: str, current_user: dict = Depends(current)):
        o = await D["orders"].find_one({"_id": _oid(order_id)}) if _oid(order_id) else None
        if not o or (str(o.get("user_id")) != str(current_user.get("sub")) and current_user.get("role") not in ("admin", "staff")):
            raise HTTPException(404, "Order not found")
        return await view(o)

    @router.get("/admin/details")
    async def get_details(current_user: dict = Depends(admin)):
        return await details()

    @router.post("/admin/details")
    async def save_details(body: dict = Body(...), current_user: dict = Depends(admin)):
        clean = lambda v, n=200: " ".join(str(v or "").split())[:n]
        doc = {"emt_email": clean(body.get("emt_email"), 120).lower(), "wise_tag": clean(body.get("wise_tag"), 60),
               "wise_email": clean(body.get("wise_email"), 120).lower(), "wise_name": clean(body.get("wise_name"), 80) or "CMTV",
               "wise_link": clean(body.get("wise_link"), 300),
               "wise_bank": {c: str((body.get("wise_bank") or {}).get(c) or "").strip()[:600] for c in CURRENCIES},
               "updated_at": datetime.utcnow(), "updated_by": current_user.get("email")}
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", doc["emt_email"]):
            raise HTTPException(400, "Enter the e-Transfer email address")
        if doc["wise_link"] and not re.match(r"^https://([a-z0-9-]+\.)*wise\.com/", doc["wise_link"], re.I):
            raise HTTPException(400, "The Wise link should start with https://wise.com/")
        await D["db"].cmtv_config.update_one({"_id": "pay_details"}, {"$set": doc}, upsert=True)
        return await details()
