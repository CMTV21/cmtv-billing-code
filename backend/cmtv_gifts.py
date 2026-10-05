"""Gift cards (CMTV local addition 2026-10-05, the owner's pick for the holidays; hidden until launch ~Nov 20).
- A gift card is bought through the normal checkout (PayPal / e-Transfer / ...) as the hidden product {cmtv_gift: True}
  (created here at startup, inactive so it never shows in the store). The cart item carries `gift`: amount ($10-$500,
  whole dollars), to_name, to_email (empty = the buyer gives it themselves), from_name, message, deliver_on (YYYY-MM-DD,
  empty = now). A gift order holds only gift cards: no coupons, no tier discount, no account credit (credit -> code loophole).
- When the order is paid, provision_order_services calls issue(): one code per item (cmtv_gifts collection), email to the
  recipient now or at 8 am Toronto on deliver_on (loop every 10 min), and a receipt with the code to the buyer.
- Redeem at /redeem (signed in): the amount goes on the account as credit (credit_service, type "gift_card"), usable at
  checkout on anything. Codes never expire. 10 tries per hour per account.
- Give-and-get (off until switched on in Admin > Gift cards): buyer gets $10 credit on a $50+ card, $20 on $100+.
- Admin > Gift cards: switch on/off, list, resend, void (retired, never deleted), and issue a free card (giveaways).
Config: cmtv_config {_id: "gifts", enabled, give_get}. Codes CMTV-XXXX-XXXX-XXXX without I/L/O/0/1 (easy to read out).
"""
import asyncio
import html
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Body, Depends, HTTPException

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/cmtv/gifts", tags=["cmtv-gifts"])
D = {}
TZ = ZoneInfo("America/Toronto")
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
AMOUNTS = [25, 50, 100]
MIN_AMOUNT, MAX_AMOUNT = 10, 500
DELIVER_HOUR = 8
SITE = "https://billing.cmtv.info"
LIVE = ("issued", "scheduled", "sent")   # can still be redeemed


def init(**deps):
    D.update(deps)


async def config():
    doc = await D["db"].cmtv_config.find_one({"_id": "gifts"}) or {}
    return {"enabled": bool(doc.get("enabled")), "give_get": bool(doc.get("give_get"))}


async def product_id():
    p = await D["db"].products.find_one({"cmtv_gift": True}, {"_id": 1})
    return str(p["_id"]) if p else None


async def startup():
    db = D["db"]
    if not await db.products.find_one({"cmtv_gift": True}, {"_id": 1}):
        await db.products.insert_one({
            "name": "CMTV Gift Card", "description": "A CMTV gift card: the amount goes on the recipient's account as credit.",
            "account_type": "manual", "panel_type": "manual", "prices": {"1": 25.0}, "active": False, "cmtv_gift": True,
            "bouquets": [], "max_connections": 0, "reseller_credits": 0, "trial_days": 0, "created_at": datetime.utcnow()})
        logger.info("CMTV gifts: hidden gift card product created")
    await db.cmtv_gifts.create_index("code", unique=True)
    await db.cmtv_gifts.create_index([("status", 1), ("deliver_on", 1)])
    await db.cmtv_gifts.create_index("buyer_id")
    await db.cmtv_gift_tries.create_index("at", expireAfterSeconds=3600)
    asyncio.create_task(_loop())


# ---------- checkout ----------

def _today():
    return datetime.now(TZ).date()


def clean_gift(g):
    """The gift details from the cart, checked. Returns (price, item name, gift dict); ValueError with a customer message."""
    g = g if isinstance(g, dict) else {}
    try:
        amount = float(g.get("amount"))
    except (TypeError, ValueError):
        raise ValueError("Pick a gift card amount.")
    if amount != int(amount) or not MIN_AMOUNT <= amount <= MAX_AMOUNT:
        raise ValueError(f"Gift cards are ${MIN_AMOUNT} to ${MAX_AMOUNT}, in whole dollars.")
    one = lambda k, n: " ".join(str(g.get(k) or "").split())[:n]
    to_name, from_name = one("to_name", 60), one("from_name", 60)
    to_email = str(g.get("to_email") or "").strip().lower()[:120]
    message = str(g.get("message") or "").strip()[:300]
    if not from_name:
        raise ValueError("Add who the gift card is from.")
    if to_email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", to_email):
        raise ValueError("That recipient email doesn't look right.")
    deliver_on = str(g.get("deliver_on") or "").strip() or None
    if deliver_on:
        if not to_email:
            raise ValueError("Add the recipient's email to schedule the gift card.")
        try:
            d = datetime.strptime(deliver_on, "%Y-%m-%d").date()
        except ValueError:
            raise ValueError("Pick a delivery date.")
        if d <= _today():
            deliver_on = None   # today or earlier = send now
        elif d > _today() + timedelta(days=366):
            raise ValueError("Pick a delivery date within a year.")
    amount = int(amount)
    name = f"CMTV Gift Card ${amount}" + (f" for {to_name}" if to_name else "")
    return float(amount), name, {"amount": amount, "to_name": to_name, "to_email": to_email, "from_name": from_name,
                                 "message": message, "deliver_on": deliver_on}


async def check_order(order_data, current_user):
    """Gift-card rules for a whole order (called by create_order when any item is a gift card)."""
    cfg = await config()
    if not cfg["enabled"] and current_user.get("role") != "admin":
        raise ValueError("Gift cards aren't available yet.")
    if len(order_data.items) > 1 and any(not getattr(i, "gift", None) for i in order_data.items):
        raise ValueError("Gift cards are checked out on their own. Please buy your other items in a separate order.")
    if order_data.coupon_code:
        raise ValueError("Coupons can't be used on gift cards.")
    if float(order_data.use_credits or 0) > 0:
        raise ValueError("Account credit can't be used to buy gift cards.")


# ---------- issue + deliver ----------

def _new_code():
    return "CMTV-" + "-".join("".join(secrets.choice(ALPHABET) for _ in range(4)) for _ in range(3))


def norm_code(s):
    s = re.sub(r"[^A-Z0-9]", "", str(s or "").upper())
    s = s[4:] if s.startswith("CMTV") and len(s) == 16 else s
    return "CMTV-" + "-".join(s[i:i + 4] for i in (0, 4, 8)) if len(s) == 12 else ""


def mask(code):
    return code[:5] + "••••-••••-" + code[-4:]


async def _insert(doc):
    for _ in range(5):
        doc["code"] = _new_code()
        try:
            await D["db"].cmtv_gifts.insert_one(doc)
            return doc
        except Exception as e:   # duplicate code: try another
            if "duplicate" not in str(e).lower():
                raise
    raise RuntimeError("could not make a unique gift code")


async def issue(order_id, order, user, item, index):
    """Make the gift card for one paid order item (once), email it / schedule it, receipt to the buyer, give-and-get."""
    db = D["db"]
    if await db.cmtv_gifts.find_one({"order_id": order_id, "item_index": index}, {"_id": 1}):
        return
    g = item.get("gift") or {}
    doc = await _insert({
        "order_id": order_id, "item_index": index, "amount": float(g.get("amount") or item.get("price") or 0),
        "buyer_id": order.get("user_id"), "buyer_email": user.get("email"), "buyer_name": user.get("name"),
        "from_name": g.get("from_name") or user.get("name") or "", "to_name": g.get("to_name") or "",
        "to_email": g.get("to_email") or "", "message": g.get("message") or "", "deliver_on": g.get("deliver_on"),
        "status": "scheduled" if g.get("deliver_on") and g.get("to_email") else "issued",
        "created_at": datetime.utcnow()})
    if doc["to_email"] and doc["status"] == "issued":
        await deliver(doc)
    await _receipt(doc)
    cfg = await config()
    bonus = 20 if doc["amount"] >= 100 else 10 if doc["amount"] >= 50 else 0
    if cfg["give_get"] and bonus and D.get("credit_service"):
        try:
            await D["credit_service"].add_credits(doc["buyer_id"], bonus, "gift_bonus",
                                                  f"Thank-you credit for a ${doc['amount']:.0f} gift card", order_id=order_id,
                                                  bypass_enabled_check=True)
            await db.cmtv_gifts.update_one({"_id": doc["_id"]}, {"$set": {"buyer_bonus": bonus}})
        except Exception as e:
            logger.warning(f"CMTV gifts: give-and-get credit failed for {order_id}: {e}")


async def admin_issue(data, admin_user):
    amount = float(data.get("amount") or 0)
    if amount != int(amount) or not 1 <= amount <= MAX_AMOUNT:
        raise ValueError(f"Amount: $1 to ${MAX_AMOUNT}, whole dollars.")
    _, _, g = clean_gift({**data, "amount": max(amount, MIN_AMOUNT), "from_name": data.get("from_name") or "CMTV"})
    doc = await _insert({
        "order_id": None, "amount": amount, "buyer_id": None, "buyer_email": None, "buyer_name": None,
        "issued_by": admin_user.get("sub"), "note": " ".join(str(data.get("note") or "").split())[:160],
        "from_name": g["from_name"], "to_name": g["to_name"], "to_email": g["to_email"], "message": g["message"],
        "deliver_on": g["deliver_on"], "status": "scheduled" if g["deliver_on"] else "issued", "created_at": datetime.utcnow()})
    if doc["to_email"] and doc["status"] == "issued":
        await deliver(doc)
    return doc


# Emails use CMTV's email look (the "service_activated" template, 2026-10-05 the owner: "branded, like our site"): grey page,
# white card, navy header with the logo and the cyan / blue / purple strip, navy footer with Telegram + email.
LOGO = "https://pub-082b63f75b76409f80ab3f95b2ab0a23.r2.dev/CMTV-Logo.jpg"
FONT = "font-family:Arial, Helvetica, sans-serif;"
P = f"margin:0 0 14px; font-size:15px; line-height:1.6; color:#374151; {FONT}"
STRIP = ('<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>'
         '<td width="33.3%" height="3" style="background-color:#00d4ff; line-height:3px; font-size:1px;">&nbsp;</td>'
         '<td width="33.3%" height="3" style="background-color:#5533ff; line-height:3px; font-size:1px;">&nbsp;</td>'
         '<td width="33.4%" height="3" style="background-color:#cc00ff; line-height:3px; font-size:1px;">&nbsp;</td></tr></table>')


def _shell(preheader, heading, body):
    return f"""<div style="display:none; max-height:0; overflow:hidden; mso-hide:all; font-size:1px; line-height:1px; color:#eef1f5; opacity:0;">{html.escape(preheader)}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#eef1f5; padding:40px 0; {FONT}">
<tr><td align="center">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:600px; width:100%; background-color:#ffffff; border-radius:10px; overflow:hidden; border:1px solid #e2e5eb;">
  <tr><td style="background-color:#0a0e1a; padding:28px 32px 0;">
    <img src="{LOGO}" alt="CMTV" height="36" style="display:block; height:36px; width:auto; border:0; margin-bottom:24px; color:#ffffff; font-size:22px; font-weight:bold; {FONT}">
    {STRIP}
  </td></tr>
  <tr><td style="padding:36px 32px 8px;">
    <h1 style="margin:0 0 20px; font-size:24px; line-height:1.3; color:#0a0e1a; {FONT}">{heading}</h1>
    {body}
    <p style="margin:20px 0 32px; font-size:14px; line-height:1.6; color:#374151; {FONT}">Best regards,<br><strong>The CMTV Team</strong></p>
  </td></tr>
  <tr><td style="padding:24px 32px; background-color:#0a0e1a;">
    <p style="margin:0 0 6px; font-size:12px; color:#8b96b3; {FONT}">&copy; {datetime.now(TZ).year} CMTV. All rights reserved.</p>
    <p style="margin:0; font-size:12px; color:#8b96b3; {FONT}">
      <a href="https://t.me/+Kw9rjQKInL02ZDBh" style="color:#00d4ff; text-decoration:none;">Telegram</a>
      &nbsp;&middot;&nbsp;<a href="mailto:cmtv@pm.me" style="color:#00d4ff; text-decoration:none;">cmtv@pm.me</a>
      &nbsp;&middot;&nbsp;<a href="{SITE}" style="color:#00d4ff; text-decoration:none;">billing.cmtv.info</a>
    </p>
  </td></tr>
</table>
</td></tr>
</table>"""


def _card(doc):
    """The gift card itself: a navy card with the CMTV strip, the amount, who it's for and the code."""
    to = html.escape(doc.get("to_name") or "")
    frm = html.escape(doc.get("from_name") or "")
    who = " &nbsp;&middot;&nbsp; ".join(x for x in (f"For {to}" if to else "", f"From {frm}" if frm else "") if x)
    return f"""
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#0a0e1a; border-radius:12px; margin:8px 0 24px; overflow:hidden;">
  <tr><td>{STRIP}</td></tr>
  <tr><td style="padding:24px 26px 26px; {FONT}">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
      <td style="font-size:12px; letter-spacing:2px; text-transform:uppercase; color:#8b96b3; {FONT}">CMTV gift card</td>
      <td align="right" style="font-size:20px;">&#127873;</td>
    </tr></table>
    <div style="font-size:48px; font-weight:bold; line-height:1.1; color:#ffffff; margin:10px 0 4px; {FONT}">${doc['amount']:.0f}</div>
    {f'<div style="font-size:14px; color:#c7d2ee; {FONT}">{who}</div>' if who else ''}
    <div style="margin-top:20px; font-size:12px; color:#8b96b3; {FONT}">Gift card code</div>
    <div style="margin-top:6px; background-color:#141d33; border:1px dashed #00d4ff; border-radius:8px; padding:13px 10px; text-align:center;
      font-family:Consolas, Menlo, 'Courier New', monospace; font-size:22px; font-weight:bold; letter-spacing:2px; color:#ffffff;">{doc['code']}</div>
  </td></tr>
</table>"""


def _message(doc):
    msg = html.escape(doc.get("message") or "").replace("\n", "<br>")
    if not msg:
        return ""
    return f"""
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 24px;"><tr>
  <td width="4" style="background-color:#5533ff; border-radius:2px; font-size:1px; line-height:1px;">&nbsp;</td>
  <td style="padding:4px 0 4px 14px; font-size:15px; line-height:1.6; color:#374151; font-style:italic; {FONT}">&ldquo;{msg}&rdquo;
    <div style="font-style:normal; color:#9ca3af; font-size:13px; margin-top:4px;">&ndash; {html.escape(doc.get('from_name') or '')}</div></td>
</tr></table>"""


def _button(href, label):
    return f"""
<table role="presentation" cellpadding="0" cellspacing="0" style="margin:0 0 28px;"><tr>
  <td style="background-color:#5533ff; background-image:linear-gradient(135deg,#00d4ff,#5533ff 55%,#cc00ff); border-radius:8px;">
    <a href="{href}" style="display:inline-block; padding:14px 28px; font-size:15px; font-weight:bold; color:#ffffff; text-decoration:none; {FONT}">{label}</a>
  </td></tr></table>"""


def _section(title):
    return f"""
<table role="presentation" cellpadding="0" cellspacing="0" style="margin-bottom:10px;"><tr>
  <td width="4" style="background-color:#00d4ff; border-radius:2px; font-size:1px; line-height:1px;">&nbsp;</td>
  <td style="padding-left:12px; font-size:16px; font-weight:bold; color:#0a0e1a; line-height:1; {FONT}">{title}</td>
</tr></table>"""


def _how():
    li = f"margin:0 0 8px; font-size:15px; line-height:1.6; color:#374151; {FONT}"
    return _section("How to use it") + f"""
<ol style="margin:0 0 18px; padding-left:22px;">
  <li style="{li}">Sign in at <a href="{SITE}" style="color:#5533ff;">billing.cmtv.info</a>, or create a free account.</li>
  <li style="{li}">Open <b>Redeem a gift card</b> and enter the code above.</li>
  <li style="{li}">The amount goes on your account as credit. Use it at checkout on any plan or add-on.</li>
</ol>
<p style="margin:0 0 14px; font-size:12px; line-height:1.5; color:#9ca3af; {FONT}">Gift cards never expire. Questions? Reply to this email or message us on Telegram.</p>"""


async def _send(to, subject, html_body, order_id=None, name=None):
    es = await D["get_email_service"]()
    return await es.send_email(to_email=to, subject=subject, html_content=es._wrap_email(html_body, subject, to, "transactional"),
                               email_type="transactional", order_id=order_id, recipient_name=name)


async def deliver(doc):
    """Email the gift card to its recipient now."""
    frm = html.escape(doc.get("from_name") or "Someone")
    hi = html.escape((doc.get("to_name") or "").split(" ")[0] or "there")
    amt = f"${doc['amount']:.0f}"
    body = (f'<p style="{P}">Hi {hi},</p>'
            f'<p style="margin:0 0 24px; font-size:15px; line-height:1.6; color:#374151; {FONT}"><strong style="color:#0a0e1a;">{frm}</strong> '
            f'sent you a <strong style="color:#0a0e1a;">{amt} CMTV gift card</strong>. Spend it on live TV, movies and series, or any add-on.</p>'
            + _card(doc) + _message(doc) + _button(f"{SITE}/redeem?code={doc['code']}", "Redeem your gift card") + _how())
    try:
        await _send(doc["to_email"], f"{doc.get('from_name') or 'Someone'} sent you a {amt} CMTV gift card",
                    _shell(f"{doc.get('from_name') or 'Someone'} sent you a {amt} CMTV gift card. Your code is inside.",
                           "You've got a gift! &#127873;", body), doc.get("order_id"), doc.get("to_name"))
        await D["db"].cmtv_gifts.update_one({"_id": doc["_id"], "status": {"$in": ["issued", "scheduled"]}},
                                            {"$set": {"status": "sent", "sent_at": datetime.utcnow()}, "$unset": {"send_error": ""}})
        return True
    except Exception as e:
        logger.warning(f"CMTV gifts: delivery to {doc.get('to_email')} failed: {e}")
        await D["db"].cmtv_gifts.update_one({"_id": doc["_id"]}, {"$set": {"send_error": str(e)[:200]}})
        return False


def _nice_date(s):
    d = datetime.strptime(s, "%Y-%m-%d")
    return f"{d.strftime('%A, %B')} {d.day}"


async def _receipt(doc):
    if not doc.get("buyer_email"):
        return
    to = html.escape(doc.get("to_name") or doc.get("to_email") or "")
    em = html.escape(doc.get("to_email") or "")
    b = 'style="color:#0a0e1a;"'
    if doc["status"] == "scheduled":
        what = f"It will be emailed to <strong {b}>{to}</strong> ({em}) on <strong {b}>{_nice_date(doc['deliver_on'])}</strong> at about 8 am Eastern."
    elif doc.get("to_email"):
        what = f"We've emailed it to <strong {b}>{to}</strong> ({em}). They'll find the code and how to use it inside."
    else:
        what = ("Here's the code to give them. Print this email or forward it: they redeem it at "
                f'<a href="{SITE}/redeem" style="color:#5533ff;">billing.cmtv.info/redeem</a>.')
    hi = html.escape((doc.get("buyer_name") or "").split(" ")[0] or "there")
    body = (f'<p style="{P}">Hi {hi},</p><p style="margin:0 0 24px; font-size:15px; line-height:1.6; color:#374151; {FONT}">'
            f'Thanks for giving CMTV! {what}</p>' + _card(doc) + _message(doc)
            + f'<p style="margin:0 0 14px; font-size:12px; line-height:1.5; color:#9ca3af; {FONT}">Keep this email: the code works once, '
              "never expires, and the amount goes on the account of whoever redeems it. If it goes missing, reply and we'll help.</p>")
    try:
        await _send(doc["buyer_email"], f"Your ${doc['amount']:.0f} CMTV gift card",
                    _shell(f"Your ${doc['amount']:.0f} CMTV gift card for {doc.get('to_name') or doc.get('to_email') or 'someone special'}.",
                           "Your gift card is ready &#127873;", body), doc.get("order_id"), doc.get("buyer_name"))
    except Exception as e:
        logger.warning(f"CMTV gifts: receipt to {doc.get('buyer_email')} failed: {e}")


async def deliver_due():
    """Scheduled cards whose day has come (from 8 am Toronto). Returns how many were sent."""
    now = datetime.now(TZ)
    if now.hour < DELIVER_HOUR:
        return 0
    n = 0
    async for doc in D["db"].cmtv_gifts.find({"status": "scheduled", "deliver_on": {"$lte": now.strftime("%Y-%m-%d")}}):
        n += bool(await deliver(doc))
    return n


async def _loop():
    await asyncio.sleep(60)
    while True:
        try:
            await deliver_due()
        except Exception as e:
            logger.warning(f"CMTV gifts loop: {e}")
        await asyncio.sleep(600)


# ---------- redeem ----------

async def redeem(user_id, raw_code):
    db = D["db"]
    if await db.cmtv_gift_tries.count_documents({"user_id": user_id}) >= 10:
        raise HTTPException(429, "Too many tries. Please wait an hour and try again, or contact support.")
    await db.cmtv_gift_tries.insert_one({"user_id": user_id, "at": datetime.utcnow()})
    code = norm_code(raw_code)
    doc = await db.cmtv_gifts.find_one({"code": code}) if code else None
    if not doc:
        raise HTTPException(400, "That code wasn't found. Check it and try again (it looks like CMTV-ABCD-EFGH-JKMN).")
    if doc["status"] == "redeemed":
        raise HTTPException(400, "This gift card has already been redeemed.")
    if doc["status"] not in LIVE:
        raise HTTPException(400, "This gift card can't be used. Please contact support.")
    claimed = await db.cmtv_gifts.find_one_and_update(
        {"_id": doc["_id"], "status": {"$in": list(LIVE)}},
        {"$set": {"status": "redeemed", "redeemed_by": user_id, "redeemed_at": datetime.utcnow(), "status_before": doc["status"]}})
    if not claimed:
        raise HTTPException(400, "This gift card has already been redeemed.")
    try:
        balance = await D["credit_service"].add_credits(user_id, float(doc["amount"]), "gift_card",
                                                        f"Gift card {mask(code)}", order_id=doc.get("order_id"),
                                                        bypass_enabled_check=True)
    except Exception as e:
        await db.cmtv_gifts.update_one({"_id": doc["_id"]}, {"$set": {"status": doc["status"]},
                                                             "$unset": {"redeemed_by": "", "redeemed_at": ""}})
        logger.error(f"CMTV gifts: credit failed for {code}: {e}")
        raise HTTPException(500, "Something went wrong adding the credit. Your code still works: please try again.")
    await db.cmtv_gift_tries.delete_many({"user_id": user_id})
    return {"ok": True, "amount": float(doc["amount"]), "balance": balance, "from_name": doc.get("from_name") or ""}


# ---------- routes ----------

def _public(doc, admin=False):
    out = {k: doc.get(k) for k in ("amount", "to_name", "to_email", "from_name", "message", "deliver_on", "status",
                                   "order_id", "buyer_bonus", "send_error")}
    out.update({"id": str(doc["_id"]), "code": doc["code"],
                "created_at": doc.get("created_at"), "sent_at": doc.get("sent_at"), "redeemed_at": doc.get("redeemed_at")})
    if admin:
        out.update({k: doc.get(k) for k in ("buyer_name", "buyer_email", "buyer_id", "redeemed_by", "issued_by", "note",
                                            "voided_at")})
    return out


def init_routes():
    user_dep, admin = D["get_current_user"], D["get_current_admin_user"]

    @router.get("/config")
    async def public_config():
        cfg = await config()
        return {"enabled": cfg["enabled"], "give_get": cfg["give_get"], "amounts": AMOUNTS, "min": MIN_AMOUNT,
                "max": MAX_AMOUNT, "product_id": await product_id()}

    @router.get("/mine")
    async def mine(current_user: dict = Depends(user_dep)):
        uid = current_user["sub"]
        bought = [_public(d) async for d in D["db"].cmtv_gifts.find({"buyer_id": uid}).sort("created_at", -1).limit(50)]
        got = [{"amount": d["amount"], "from_name": d.get("from_name"), "redeemed_at": d.get("redeemed_at")}
               async for d in D["db"].cmtv_gifts.find({"redeemed_by": uid}).sort("redeemed_at", -1).limit(20)]
        return {"bought": bought, "redeemed": got}

    @router.post("/redeem")
    async def redeem_route(data: dict = Body(...), current_user: dict = Depends(user_dep)):
        return await redeem(current_user["sub"], data.get("code"))

    @router.get("/admin")
    async def admin_list(current_user: dict = Depends(admin)):
        rows = [_public(d, True) async for d in D["db"].cmtv_gifts.find({}).sort("created_at", -1).limit(500)]
        uids = {r[k] for r in rows for k in ("buyer_id", "redeemed_by") if r.get(k)}
        from bson import ObjectId
        names = {}
        async for u in D["db"].users.find({"_id": {"$in": [ObjectId(u) for u in uids if ObjectId.is_valid(u)]}}, {"name": 1, "email": 1}):
            names[str(u["_id"])] = u.get("name") or u.get("email")
        for r in rows:
            r["redeemed_by_name"] = names.get(r.get("redeemed_by") or "", "")
        sold = [r for r in rows if r.get("order_id")]
        return {"config": await config(), "rows": rows, "totals": {
            "sold": len(sold), "sold_value": sum(r["amount"] for r in sold),
            "outstanding": sum(r["amount"] for r in rows if r["status"] in LIVE),
            "redeemed": sum(r["amount"] for r in rows if r["status"] == "redeemed"),
            "scheduled": sum(1 for r in rows if r["status"] == "scheduled")}}

    @router.post("/admin/config")
    async def admin_config(data: dict = Body(...), current_user: dict = Depends(admin)):
        upd = {k: bool(data[k]) for k in ("enabled", "give_get") if k in data}
        await D["db"].cmtv_config.update_one({"_id": "gifts"}, {"$set": {**upd, "updated_at": datetime.utcnow(),
                                                                         "updated_by": current_user.get("sub")}}, upsert=True)
        return await config()

    @router.post("/admin/issue")
    async def admin_issue_route(data: dict = Body(...), current_user: dict = Depends(admin)):
        try:
            return _public(await admin_issue(data, current_user), True)
        except ValueError as e:
            raise HTTPException(400, str(e))

    async def _get(gid):
        from bson import ObjectId
        doc = await D["db"].cmtv_gifts.find_one({"_id": ObjectId(gid)}) if ObjectId.is_valid(gid) else None
        if not doc:
            raise HTTPException(404, "Gift card not found")
        return doc

    @router.post("/admin/{gid}/resend")
    async def admin_resend(gid: str, data: dict = Body(default={}), current_user: dict = Depends(admin)):
        doc = await _get(gid)
        if doc["status"] not in LIVE:
            raise HTTPException(400, "Only unused gift cards can be resent.")
        new_email = str(data.get("to_email") or "").strip().lower()
        if new_email:
            if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", new_email):
                raise HTTPException(400, "That email doesn't look right.")
            await D["db"].cmtv_gifts.update_one({"_id": doc["_id"]}, {"$set": {"to_email": new_email}})
            doc["to_email"] = new_email
        if not doc.get("to_email"):
            raise HTTPException(400, "Add the recipient's email first.")
        if not await deliver(doc):
            raise HTTPException(500, "The email couldn't be sent. Check the email settings.")
        return {"ok": True}

    @router.post("/admin/{gid}/void")
    async def admin_void(gid: str, current_user: dict = Depends(admin)):
        doc = await _get(gid)
        if doc["status"] not in LIVE:
            raise HTTPException(400, "Only unused gift cards can be voided.")
        await D["db"].cmtv_gifts.update_one({"_id": doc["_id"], "status": {"$in": list(LIVE)}},
                                            {"$set": {"status": "void", "voided_at": datetime.utcnow(),
                                                      "voided_by": current_user.get("sub"), "status_before": doc["status"]}})
        return {"ok": True}
