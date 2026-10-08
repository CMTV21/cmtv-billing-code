"""Renewal reminder with real options (CMTV local addition 2026-10-05, 2027 marketing plan #1 "keep customers").
Replaces the plain "your service expires soon" email the lifecycle job sends 7, 3 and 1 day before a plan ends
(lifecycle_service.send_expiry_warnings calls send(); on any error it falls back to the developer's email).
Data behind it: ~91% of paying customers kept over 6 months; 11 of the 20 lost were on MONTHLY plans. So each reminder
shows: renew the same plan (its price) / switch to yearly and save X% (same server + devices, "you'd run until ..."; plus the
holiday bonus months while cmtv_promo runs) / auto-renew with PayPal, 10% off / "buffering? Test my line". CMTV+ parts
renew as CMTV+. Branded with cmtv_gifts' email pieces.
"""
import html
import logging
from datetime import datetime, timedelta

from bson import ObjectId

logger = logging.getLogger(__name__)
D = {}
AUTORENEW_PCT = 10


def init(**deps):
    D.update(deps)


def _price(p):
    prices = (p or {}).get("prices") or {}
    if not prices:
        return 0, 0.0
    k = next(iter(prices))
    return int(k), float(prices[k] or 0)


def _date(d):
    return f"{d.strftime('%B')} {d.day}, {d.year}" if d else ""


def _term(n):
    return "year" if n == 12 else "month" if n == 1 else f"{n} months"


async def options(service):
    """{"plan": product, "price", "term", "yearly": {"price","save","until"} | None, "bonus": months, "autorenew": bool}"""
    db = D["db"]
    pid = service.get("product_id")
    product = await db.products.find_one({"_id": ObjectId(pid)}) if pid and ObjectId.is_valid(str(pid)) else None
    if service.get("cmtv_plus"):
        product = await db.products.find_one({"cmtv_plus": True}) or product
    if product and product.get("is_trial") and product.get("cmtv_trial_of") and ObjectId.is_valid(str(product["cmtv_trial_of"])):
        product = await db.products.find_one({"_id": ObjectId(product["cmtv_trial_of"])}) or product
    term, price = _price(product)
    out = {"plan": product, "term": term, "price": price, "yearly": None, "bonus": 0, "autorenew": False}
    if not product or price <= 0:
        return out
    if term and term < 12 and product.get("account_type", "subscriber") == "subscriber" and product.get("panel_type") in ("xtream", "aether"):
        async for y in db.products.find({"panel_type": product.get("panel_type"), "account_type": "subscriber", "is_trial": {"$ne": True},
                                         "max_connections": product.get("max_connections"), "active": True}):
            yt, yp = _price(y)
            if yt == 12 and yp > 0:
                save = round((1 - yp / (price / term * 12)) * 100)
                if save > 0:
                    base = max(service.get("expiry_date") or datetime.utcnow(), datetime.utcnow())
                    out["yearly"] = {"price": yp, "save": save, "until": base + timedelta(days=365), "name": y.get("name")}
                break
    try:
        import cmtv_promo
        st = cmtv_promo.state(await cmtv_promo.config())
        if st["active"] and product.get("panel_type") in ("xtream", "aether"):
            out["bonus"] = st["months"]
            if out["yearly"]:
                out["yearly"]["until"] += timedelta(days=round(st["months"] * 30.4))
    except Exception:
        pass
    try:
        import cmtv_autorenew
        out["autorenew"] = bool((await cmtv_autorenew.config()).get("enabled")) and not service.get("is_trial")
    except Exception:
        pass
    return out


def build(user, service, days, opt):
    from cmtv_gifts import _shell, _button, _section, P, FONT, STRIP, SITE
    first = html.escape((user.get("name") or "").split(" ")[0] or "there")
    name = html.escape(service.get("product_name") or "plan")
    if service.get("cmtv_plus"):
        name = "CMTV+"
    ends = _date(service.get("expiry_date"))
    when = "tomorrow" if days <= 1 else f"in {days} days"
    subject = (f"Last day tomorrow: renew your CMTV to keep watching" if days <= 1
               else f"Your CMTV plan ends {when} ({ends})")
    heading = f"Your plan ends {when}"
    card = lambda title, text, accent="#00d4ff": f"""
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#0a0e1a; border-radius:10px; margin:0 0 12px; overflow:hidden;">
  <tr><td width="4" style="background-color:{accent}; font-size:1px; line-height:1px;">&nbsp;</td>
  <td style="padding:14px 18px;"><div style="font-size:16px; font-weight:bold; color:#ffffff; {FONT}">{title}</div>
  <div style="margin-top:4px; font-size:14px; line-height:1.55; color:#c7d2ee; {FONT}">{text}</div></td></tr>
</table>"""
    parts = [f'<p style="{P}">Hi {first},</p>',
             f'<p style="margin:0 0 22px; font-size:15px; line-height:1.6; color:#374151; {FONT}">Your <strong style="color:#0a0e1a;">{name}</strong> '
             f'ends on <strong style="color:#0a0e1a;">{ends}</strong>. Renew before then and nothing changes: same login, same apps, no setup.</p>',
             _section("Your options")]
    if opt["price"] > 0:
        parts.append(card(f"Renew for {_term(opt['term'])}: ${opt['price']:.0f}", "The quickest way: one tap from your dashboard."))
    if opt["yearly"]:
        y = opt["yearly"]
        extra = f" Right now you also get <b style=\"color:#fff\">{opt['bonus']} months free</b> on a yearly plan." if opt["bonus"] else ""
        parts.append(card(f"Switch to a year: ${y['price']:.0f} <span style=\"color:#86efac;\">(save {y['save']}%)</span>",
                          f"Pay once and forget about it until <b style=\"color:#fff\">{_date(y['until'])}</b>.{extra}", "#cc00ff"))
    if opt["autorenew"] and opt["price"] > 0:
        # CMTV local change 2026-10-08: say the actual price (auto-renew nudge; nobody was using it)
        ar = round(opt["price"] * (100 - AUTORENEW_PCT) / 100, 2)
        parts.append(card(f"Never get cut off: auto-renew, {AUTORENEW_PCT}% off",
                          f"Renews by itself with PayPal the day before it ends, for <b style=\"color:#fff\">${ar:.2f}</b> instead of "
                          f"${opt['price']:.2f} {'every year' if opt['term'] == 12 else 'each time'}. Turn it on with the "
                          "<b style=\"color:#fff\">Auto-renew</b> switch on your dashboard, and off any time.", "#5533ff"))
    parts.append(_button(f"{SITE}/dashboard", "Renew on my dashboard"))
    parts.append(f'<p style="margin:0 0 14px; font-size:13px; line-height:1.6; color:#6b7280; {FONT}">Having any buffering or trouble? '
                 f'Tap <b>Test my line</b> on your dashboard, or reply to this email: we\'d rather fix it than lose you.</p>')
    return subject, _shell(f"Your {name} ends {ends}. Renew in one tap, or switch to a year and save.", heading, "".join(parts))


async def send(service, user, days):
    """Send the reminder; returns True if sent. Raises on error (the caller falls back to the plain email)."""
    email = str(user.get("email") or "")
    if "@" not in email or email.endswith("@panel.local"):
        return False
    opt = await options(service)
    # reseller panels (and anything without a price) keep the developer's plain reminder
    if service.get("account_type") == "reseller" or (opt["plan"] or {}).get("account_type") == "reseller" or opt["price"] <= 0:
        return False
    subject, page = build(user, service, days, opt)
    es = await D["get_email_service"]()
    return await es.send_email(to_email=email, subject=subject, html_content=es._wrap_email(page, subject, email, "transactional"),
                               email_type="transactional", template_type="service_expiry_warning",
                               customer_id=str(user.get("_id") or ""), recipient_name=user.get("name", ""))
