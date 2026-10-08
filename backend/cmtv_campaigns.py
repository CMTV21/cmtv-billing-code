"""Campaign emails (CMTV local addition 2026-10-08, for the holiday emails and later campaigns: January referral push,
monthly news). Admin > Growth > Campaigns (/admin/campaigns).
- A campaign (cmtv_campaigns) = name, subject, preheader, heading, body blocks, audience, status
  draft / scheduled / sending / paused / sent / cancelled. Never deleted: "retired" hides it.
- Audiences are worked out when the send starts (and in the dry run):
  active_paying = real email, an active non-trial non-reseller service, at least one paid order (> $0, not "test");
  lapsed = paid before, nothing active now (not even on the panel, i.e. renewed outside billing).
  Always left out: unsubscribed from offers (email_unsubscribes, the same opt-out the come-back / review / survey emails
  honour), staff/admin, merged/placeholder (@panel.local) accounts, demo and test accounts, resellers (unless the campaign
  includes them) and the owner's own addresses (config exclude_emails).
- Personal fields in the text: {{first_name}} {{plan}} {{end_date}} {{renew_until}} {{last_plan}} {{dashboard_link}}
  {{plans_link}}. A block whose field is missing for that customer uses its fallback text, or is left out (never "None").
  renew_until = the plan's end date (or today if later) + 12 months + the holiday bonus months while cmtv_promo runs.
- The email = cmtv_gifts._shell (navy header, logo, strip) + a plain-text part + an unsubscribe link in the footer
  (CASL). The link is signed (/api/cmtv/campaigns/unsubscribe?t=...) and opens a page with an Unsubscribe button, so mail
  scanners that open links don't unsubscribe anyone. GET /api/unsubscribe?email= (the link in the older marketing emails,
  which only had a POST route and showed an error) now opens the same page.
- Sending: one loop in the backend. A scheduled campaign whose time has come gets its recipients written to
  cmtv_campaign_sends (unique per campaign + user, so nobody gets it twice), then one email every THROTTLE seconds, only
  10:00-20:00 Toronto (outside that it waits for the next morning). Each send is claimed before it goes out; a restart
  mid-send marks that one "interrupted" (not resent). requires_promo campaigns pause if the holiday sale isn't running.
  Ops Billing gets a note when a campaign starts and finishes.
Config: cmtv_config {_id: "campaigns"}: exclude_emails, throttle_seconds, unsub_key (made at startup, never shown).
"""
import asyncio
import base64
import hashlib
import hmac
import html
import logging
import re
import secrets
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from bson import ObjectId
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pymongo.errors import DuplicateKeyError

import cmtv_lines as L

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/cmtv/campaigns", tags=["cmtv-campaigns"])
legacy_router = APIRouter(tags=["cmtv-campaigns"])   # GET /api/unsubscribe for the older emails' links
D = {}
TZ = ZoneInfo("America/Toronto")
SITE = "https://billing.cmtv.info"
WINDOW = (10, 20)            # send hours, Toronto (10:00-19:59)
THROTTLE = 4.0               # seconds between emails (config throttle_seconds)
AUDIENCES = {"active_paying": "Active paying customers", "lapsed": "Past customers (nothing active now)"}
STATUSES = ("draft", "scheduled", "sending", "paused", "sent", "cancelled")
BLOCK_TYPES = ("p", "card", "heading", "list", "button", "note", "spacer")
FIELDS = ("first_name", "plan", "end_date", "renew_until", "last_plan", "dashboard_link", "plans_link")
TV = ("aether", "xtream", "xuione", "nxtdash", "onestream")
SAMPLE = {"first_name": "Sam", "plan": "CCTV, 2 devices", "end_date": "January 14, 2027", "renew_until": "April 14, 2028",
          "last_plan": "CCTV", "dashboard_link": f"{SITE}/dashboard", "plans_link": f"{SITE}/?tab=all"}
_wake = asyncio.Event()


def init(**deps):
    D.update(deps)


def _db():
    return D["db"]


def _oid(v):
    return ObjectId(v) if ObjectId.is_valid(str(v)) else None


def _dt(v):
    """A stored date as naive UTC (Mongo gives naive UTC; some old records hold ISO strings)."""
    if isinstance(v, str) and v:
        try:
            v = datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            return None
    if isinstance(v, datetime):
        return v if v.tzinfo is None else v.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
    return None


def _utc_naive(aware):
    return aware.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)


def _local(naive_utc):
    return naive_utc.replace(tzinfo=ZoneInfo("UTC")).astimezone(TZ)


def in_window(now=None):
    h = _local(now or datetime.utcnow()).hour
    return WINDOW[0] <= h < WINDOW[1]


def next_window_start(now=None):
    loc = _local(now or datetime.utcnow())
    start = loc.replace(hour=WINDOW[0], minute=0, second=0, microsecond=0)
    if loc.hour >= WINDOW[0]:
        start += timedelta(days=1)
    return _utc_naive(start)


async def config():
    doc = await _db().cmtv_config.find_one({"_id": "campaigns"}) or {}
    return {"exclude_emails": [str(e).strip().lower() for e in doc.get("exclude_emails") or [] if str(e).strip()],
            "throttle_seconds": float(doc.get("throttle_seconds") or THROTTLE), "unsub_key": doc.get("unsub_key") or ""}


async def startup():
    db = _db()
    await db.cmtv_config.update_one({"_id": "campaigns"}, {"$setOnInsert": {"unsub_key": secrets.token_hex(32),
                                    "exclude_emails": [], "throttle_seconds": THROTTLE}}, upsert=True)
    await db.cmtv_campaign_sends.create_index([("campaign_id", 1), ("user_id", 1)], unique=True)
    await db.cmtv_campaign_sends.create_index([("campaign_id", 1), ("status", 1)])
    await db.cmtv_campaigns.create_index([("status", 1), ("send_at", 1)])
    n = await recover_interrupted()
    if n:
        logger.warning(f"CMTV campaigns: {n} send(s) were cut off by a restart (marked interrupted, not resent)")
    asyncio.create_task(_loop())


async def recover_interrupted():
    """A send claimed before a restart may or may not have gone out: never resend it (no double emails)."""
    r = await _db().cmtv_campaign_sends.update_many(
        {"status": "sending"}, {"$set": {"status": "failed", "reason": "interrupted by a restart (not resent, so nobody gets it twice)",
                                         "done_at": datetime.utcnow()}})
    return r.modified_count


# ---------- unsubscribe (CASL) ----------

def _b64(s):
    return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")


def _unb64(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4)).decode()


def _sig(key, email):
    return hmac.new(key.encode(), email.lower().encode(), hashlib.sha256).hexdigest()[:24]


def unsub_token(key, email):
    return f"{_b64(email)}.{_sig(key, email)}"


def read_token(key, token):
    try:
        b, sig = str(token).rsplit(".", 1)
        email = _unb64(b)
    except Exception:
        return None
    return email if key and hmac.compare_digest(sig, _sig(key, email)) else None


async def unsub_link(email):
    return f"{SITE}/api/cmtv/campaigns/unsubscribe?t={unsub_token((await config())['unsub_key'], email)}"


async def unsubscribed_set():
    out = set()
    async for u in _db().email_unsubscribes.find({"unsubscribed_from": {"$in": ["all", "marketing", None]}}, {"email": 1}):
        out.add(str(u.get("email") or "").strip().lower())
    return out


async def is_unsubscribed(email):
    e = str(email or "").strip()
    return bool(await _db().email_unsubscribes.find_one({"email": {"$regex": f"^{re.escape(e)}$", "$options": "i"},
                                                         "unsubscribed_from": {"$in": ["all", "marketing", None]}}))


async def do_unsubscribe(email, how):
    db = _db()
    e = str(email or "").strip()
    if not e or await is_unsubscribed(e):
        return
    u = await db.users.find_one({"email": {"$regex": f"^{re.escape(e)}$", "$options": "i"}}, {"_id": 1})
    await db.email_unsubscribes.update_one({"email": e}, {"$set": {
        "email": e, "customer_id": str(u["_id"]) if u else None, "unsubscribed_from": "marketing",
        "reason": how, "reason_text": None, "unsubscribed_at": datetime.utcnow(), "ip_address": None}}, upsert=True)
    logger.info("CMTV campaigns: someone unsubscribed from offers")


def _page(title, msg, form_action=None, email=""):
    btn = (f'<form method="post" action="{html.escape(form_action)}" style="margin:22px 0 4px">'
           f'<button type="submit" style="background:#5533ff;background-image:linear-gradient(135deg,#00d4ff,#5533ff 55%,#cc00ff);'
           f'color:#fff;border:0;border-radius:8px;padding:13px 26px;font:bold 15px Arial,sans-serif;cursor:pointer">'
           f'Unsubscribe</button></form>') if form_action else ""
    who = f'<p style="color:#8b96b3;font-size:13px">{html.escape(email)}</p>' if email else ""
    return HTMLResponse(f"""<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>{html.escape(title)} | CMTV</title></head>
<body style="margin:0;background:#0a0e1a;font-family:Arial,Helvetica,sans-serif;color:#e6eaf5">
<div style="max-width:480px;margin:0 auto;padding:56px 22px">
<img src="https://pub-082b63f75b76409f80ab3f95b2ab0a23.r2.dev/CMTV-Logo.jpg" alt="CMTV" height="36" style="height:36px">
<div style="height:3px;margin:22px 0 28px;background:linear-gradient(90deg,#00d4ff,#5533ff,#cc00ff)"></div>
<h1 style="font-size:24px;margin:0 0 12px">{html.escape(title)}</h1>
<p style="font-size:15px;line-height:1.6;color:#c7d2ee">{msg}</p>{who}{btn}
<p style="font-size:13px;line-height:1.6;color:#8b96b3;margin-top:28px">You'll still get emails about your account and
orders (receipts, setup details, renewal reminders). Changed your mind? Message us on
<a href="https://t.me/+Kw9rjQKInL02ZDBh" style="color:#00d4ff">Telegram</a> or at
<a href="mailto:cmtv@pm.me" style="color:#00d4ff">cmtv@pm.me</a>.</p>
<p style="margin-top:22px"><a href="{SITE}" style="color:#00d4ff;font-size:14px">billing.cmtv.info</a></p></div></body></html>""")


ASK = "Stop getting offers and news from CMTV by email?"
DONE = "Done. You won't get offers or news from CMTV by email any more."


# ---------- audiences ----------

def _real_email(e):
    e = str(e or "").strip().lower()
    return "@" in e and not e.endswith("@panel.local")


def _test_account(u):
    e = str(u.get("email") or "").lower()
    local = e.split("@")[0]
    return bool(u.get("cmtv_test")) or local.startswith("test") or "cmtv_test" in e or e.endswith("@example.com")


def _trial(s):
    return L.trial_marked(s)   # CMTV local change 2026-10-08: shared rule in cmtv_lines


def _reseller_svc(s):
    return s.get("account_type") == "reseller" or "reseller" in str(s.get("product_name") or "").lower()


def _live(s, now):
    if s.get("status") != "active":
        return False
    exp = _dt(s.get("expiry_date"))
    return exp is None or exp > now


TRIAL_MAX = L.TRIAL_MAX


def _counts(s, now):
    """A paid-looking service. Billing keeps the trial name/flag when a trial line is later paid for and extended
    (e.g. "Imperium 48 hour Trial" running until 2027), so a "trial" longer than 8 days counts as paid.
    CMTV local change 2026-10-08: the rule now lives in cmtv_lines (shared with the other modules)."""
    if s.get("cmtv_demo") or _reseller_svc(s):
        return False
    return L.is_paid_line(s, now)


def server_of(s):
    pt, name = s.get("panel_type"), str(s.get("product_name") or "").lower()
    if "amethyst" in name:
        return "Amethyst"
    if pt == "onestream" or "extreme" in name:
        return "Extreme"
    if pt in ("aether", "nxtdash") or "imperium" in name:
        return "Imperium"
    if pt in ("xtream", "xuione"):
        return "CCTV"
    return None


async def _line_active_on_panel(s, now):
    name = s.get("xtream_username") or s.get("username") or ""
    if not name or s.get("panel_type") not in TV:
        return False
    iu = await _db().imported_users.find_one({"username": {"$regex": f"^{re.escape(name)}$", "$options": "i"},
                                              "account_type": {"$ne": "reseller"}})
    if not iu or str(iu.get("status") or "").lower() != "active":
        return False
    exp = _dt(iu.get("expiry_date"))
    return exp is None or exp > now


async def audience(camp, now=None):
    """{"recipients": [{"user", "services"}], "skipped": [{"email", "name", "reason"}]} for camp["audience"]."""
    db = _db()
    now = now or datetime.utcnow()
    kind = camp.get("audience")
    if kind not in AUDIENCES:
        raise HTTPException(400, "Unknown audience")
    cfg = await config()
    paid = set()
    async for o in db.orders.find({"status": "paid", "total": {"$gt": 0}, "payment_method": {"$ne": "test"}}, {"user_id": 1}):
        if o.get("user_id"):
            paid.add(str(o["user_id"]))
    svcs, resellers = {}, set()
    # unbilled = customers who pay outside billing (mostly panel-only accounts renewed on the panel): no paid order here
    q = {} if camp.get("include_unbilled") else {"user_id": {"$in": list(paid) + [_oid(x) for x in paid if _oid(x)]}}
    async for s in db.services.find(q):
        uid = str(s.get("user_id"))
        svcs.setdefault(uid, []).append(s)
        if _reseller_svc(s):
            resellers.add(uid)
    cands = set(paid)
    if camp.get("include_unbilled"):
        cands |= {uid for uid, ss in svcs.items() if any(_counts(s, now) for s in ss)}
    unsub = await unsubscribed_set()
    excluded = set(cfg["exclude_emails"])
    out, skipped = [], []
    for uid in sorted(cands):
        mine = [s for s in svcs.get(uid, []) if not s.get("cmtv_demo")]
        live_paid = [s for s in mine if _live(s, now) and _counts(s, now)]
        if kind == "active_paying" and not live_paid:
            continue
        if kind == "lapsed":
            # nothing live at all (a running trial counts as "here"), paid before, and not renewed on the panel
            if any(_live(s, now) and not _reseller_svc(s) for s in mine) or not any(_counts(s, now) for s in mine):
                continue
            renewed = False
            for s in mine:
                if not _reseller_svc(s) and await _line_active_on_panel(s, now):
                    renewed = True
                    break
            if renewed:
                continue
        u = await db.users.find_one({"_id": _oid(uid)}) if _oid(uid) else None
        if not u:
            continue
        email = str(u.get("email") or "").strip()
        reason = None
        if u.get("role") in ("admin", "staff"):
            reason = "staff / admin account"
        elif u.get("role") != "user":
            reason = f"account is {u.get('role') or 'not a customer'}"
        elif not _real_email(email):
            reason = "no real email (panel-only account)"
        elif u.get("cmtv_demo"):
            reason = "demo account"
        elif _test_account(u):
            reason = "test account"
        elif email.lower() in excluded:
            reason = "on the don't-email list (owner's own)"
        elif uid in resellers and not camp.get("include_resellers"):
            reason = "reseller"
        elif email.lower() in unsub:
            reason = "unsubscribed from offers"
        if reason:
            skipped.append({"user_id": uid, "email": email, "name": u.get("name") or "", "reason": reason})
            continue
        out.append({"user": u, "services": mine})
    return {"recipients": out, "skipped": skipped}


# ---------- personal fields + rendering ----------

def _nice(d):
    return f"{d:%B} {d.day}, {d.year}"


def add_months(d, n):
    y, m = divmod(d.month - 1 + n, 12)
    y, m = d.year + y, m + 1
    last = [31, 29 if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
    return d.replace(year=y, month=m, day=min(d.day, last))


def first_name(u):
    raw = str(u.get("name") or "").strip()
    first = raw.split(" ")[0] if raw else ""
    # panel-made accounts are named after the line ("NVBPeGQzj"): not a name
    if not first or first == str(u.get("panel_username") or "") or re.search(r"\d|@|_", first) or len(first) > 20:
        return "there"
    return first[:1].upper() + first[1:]


async def promo_months(assume=False, now=None):
    """Bonus months to count in renew_until: while the holiday sale runs (or, for previews/tests, as if it does)."""
    try:
        import cmtv_promo
        cfg = await cmtv_promo.config()
        st = cmtv_promo.state(cfg, now.replace(tzinfo=ZoneInfo("UTC")) if now else None)
        if st["active"]:
            return st["months"], True
        return (st["months"] if assume else 0), False
    except Exception as e:
        logger.warning(f"CMTV campaigns: promo state unavailable ({e})")
        return 0, False


def personal(u, services, bonus=0, now=None):
    now = now or datetime.utcnow()
    f = {"first_name": first_name(u), "dashboard_link": f"{SITE}/dashboard", "plans_link": f"{SITE}/?tab=all"}
    tv_live = sorted((s for s in services if s.get("panel_type") in TV and _live(s, now) and _counts(s, now)
                      and _dt(s.get("expiry_date"))), key=lambda s: _dt(s.get("expiry_date")))
    if tv_live:
        s = tv_live[0]
        srv, n = server_of(s), int(s.get("max_connections") or 0)
        if srv:
            f["plan"] = f"{srv}, {n} device{'s' if n != 1 else ''}" if n else srv
        end = _local(_dt(s["expiry_date"])).date()
        f["end_date"] = _nice(end)
        f["renew_until"] = _nice(add_months(max(end, _local(now).date()), 12 + int(bonus or 0)))
    ended = sorted((s for s in services if s.get("panel_type") in TV and _counts(s, now) and server_of(s)),
                   key=lambda s: _dt(s.get("expiry_date")) or datetime.min, reverse=True)
    if ended:
        f["last_plan"] = server_of(ended[0])
    return f


TAG = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")


def _fill(text, fields):
    """Plain text with {{tags}} filled; None when a tag has no value."""
    missing = [t for t in TAG.findall(text or "") if not fields.get(t)]
    if missing:
        return None
    return TAG.sub(lambda m: str(fields.get(m.group(1))), text or "")


def _rich(text, fields):
    """Escaped HTML with **bold** and {{tags}}; None when a tag has no value."""
    if any(not fields.get(t) for t in TAG.findall(text or "")):
        return None
    esc = html.escape(text or "")
    esc = re.sub(r"\*\*(.+?)\*\*", r'<strong style="color:#0a0e1a;">\1</strong>', esc)
    esc = esc.replace("\n", "<br>")
    return TAG.sub(lambda m: html.escape(str(fields.get(m.group(1)))), esc)


def _plain(text):
    return re.sub(r"\*\*(.+?)\*\*", r"\1", text or "")


def _pick(b, key, fields, rich=True):
    """The block's text (or its fallback) with fields filled; None = leave the block out."""
    fn = _rich if rich else _fill
    v = fn(b.get(key) or "", fields)
    if v is None and b.get("fallback"):
        v = fn(b["fallback"], fields)
    return v


def _rich_on_dark(text, fields):
    v = _rich(text, fields)
    return None if v is None else v.replace('style="color:#0a0e1a;"', 'style="color:#ffffff;"')


def render(camp, fields, unsub_url):
    """(subject, html page, plain text). Blocks whose fields are missing are left out."""
    from cmtv_gifts import _shell, _button, _section, STRIP, FONT, P
    parts, text = [], []
    for b in camp.get("blocks") or []:
        t = b.get("type")
        if t == "p" or t == "note":
            v = _pick(b, "text", fields)
            if v is None or not v.strip():
                continue
            style = P if t == "p" else f"margin:0 0 14px; font-size:12px; line-height:1.5; color:#9ca3af; {FONT}"
            parts.append(f'<p style="{style}">{v}</p>')
            text.append(_plain(_pick(b, "text", fields, rich=False) or ""))
        elif t == "card":
            title = _rich_on_dark(b.get("title") or "", fields)
            body = _rich_on_dark(b.get("text") or "", fields)
            if title is None or body is None:
                continue
            sub = html.escape(b.get("subtitle") or "")
            sub = f' <span style="font-size:13px; color:#8b96b3; font-weight:normal;">{sub}</span>' if sub else ""
            emoji = html.escape(b.get("emoji") or "")
            parts.append(f"""
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#0a0e1a; border-radius:10px; margin:0 0 14px; overflow:hidden;">
  <tr><td>{STRIP}</td></tr>
  <tr><td style="padding:18px 22px;">
    <div style="font-size:18px; font-weight:bold; color:#ffffff; {FONT}">{emoji + ' ' if emoji else ''}{title}{sub}</div>
    <div style="margin-top:6px; font-size:14px; line-height:1.6; color:#c7d2ee; {FONT}">{body}</div>
  </td></tr>
</table>""")
            text.append(f"{_plain(_fill(b.get('title') or '', fields))}{' ' + b['subtitle'] if b.get('subtitle') else ''}\n"
                        f"{_plain(_fill(b.get('text') or '', fields))}")
        elif t == "heading":
            v = _rich(b.get("text") or "", fields)
            if not v:
                continue
            parts.append('<div style="height:8px"></div>' + _section(v))
            text.append(_plain(_fill(b.get("text") or "", fields)).upper())
        elif t == "list":
            items = [(_rich(i, fields), _fill(i, fields)) for i in str(b.get("text") or "").split("\n") if i.strip()]
            items = [(h, p) for h, p in items if h]
            if not items:
                continue
            li = f"margin:0 0 6px; font-size:15px; line-height:1.6; color:#374151; {FONT}"
            parts.append('<ul style="margin:0 0 22px; padding-left:20px;">' + "".join(f'<li style="{li}">{h}</li>' for h, _ in items) + "</ul>")
            text.append("\n".join(f"- {_plain(p)}" for _, p in items))
        elif t == "button":
            label, href = _fill(b.get("label") or "", fields), _fill(b.get("href") or "", fields)
            if not label or not href or not re.match(r"^https://", href):
                continue
            parts.append(_button(html.escape(href, quote=True), html.escape(label)))
            text.append(f"{label}: {href}")
        elif t == "spacer":
            parts.append('<div style="height:8px"></div>')
    heading = _rich(camp.get("heading") or "", fields) or html.escape(camp.get("name") or "")
    page = _shell(_fill(camp.get("preheader") or "", fields) or "", heading, "".join(parts))
    foot = (f'<p style="margin:10px 0 0; font-size:11px; line-height:1.5; color:#8b96b3; {FONT}">You\'re getting this because '
            f'you\'re a CMTV customer. <a href="{html.escape(unsub_url, quote=True)}" style="color:#8b96b3; text-decoration:underline;">'
            f'Unsubscribe from offers and news</a>.</p>\n')
    anchor = "  </td></tr>\n</table>\n</td></tr>\n</table>"
    i = page.rfind(anchor)
    page = page[:i] + foot + page[i:] if i >= 0 else page + foot
    page = ('<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{html.escape(camp.get("subject") or "")}</title></head>'
            f'<body style="margin:0; padding:0; background-color:#eef1f5;">{page}</body></html>')
    subject = _fill(camp.get("subject") or "", fields) or camp.get("name") or "CMTV"
    plain = (f"{_plain(_fill(camp.get('heading') or '', fields) or '')}\n\n" + "\n\n".join(x for x in text if x) +
             f"\n\nBest regards,\nThe CMTV Team\nbilling.cmtv.info · cmtv@pm.me · Telegram https://t.me/+Kw9rjQKInL02ZDBh"
             f"\n\nUnsubscribe from offers and news: {unsub_url}")
    return subject, page, plain


# ---------- sending ----------

def _check_campaign(c):
    if not (c.get("subject") or "").strip():
        raise HTTPException(400, "The campaign needs a subject")
    if not c.get("blocks"):
        raise HTTPException(400, "The campaign has no content")
    if c.get("audience") not in AUDIENCES:
        raise HTTPException(400, "Pick an audience")


async def _ops(text):
    try:
        import cmtv_notify
        settings = await D["get_settings"]() if D.get("get_settings") else None
        await cmtv_notify.ops(text, "billing", settings)
    except Exception as e:
        logger.warning(f"CMTV campaigns: Ops note failed ({e})")


async def _ops_critical(text):
    try:
        import cmtv_notify
        settings = await D["get_settings"]() if D.get("get_settings") else None
        await cmtv_notify.ops(text, "critical", settings)
    except Exception as e:
        logger.warning(f"CMTV campaigns: Ops alert failed ({e})")


async def counts(cid):
    out = {k: 0 for k in ("queued", "sending", "sent", "failed", "skipped", "cancelled")}
    async for r in _db().cmtv_campaign_sends.aggregate([{"$match": {"campaign_id": cid}}, {"$group": {"_id": "$status", "n": {"$sum": 1}}}]):
        out[r["_id"]] = r["n"]
    return out


async def start_campaign(c, now=None):
    """Scheduled -> sending: write every recipient once (unique per campaign + user)."""
    db = _db()
    now = now or datetime.utcnow()
    cid = c["_id"]
    if c.get("requires_promo"):
        _, running = await promo_months(now=now)
        if not running:
            await db.cmtv_campaigns.update_one({"_id": cid, "status": "scheduled"}, {"$set": {
                "status": "paused", "pause_reason": "the holiday sale isn't running (Admin > Notices > Holiday bonus months)"}})
            await _ops_critical(f"⏸️ Campaign <b>{html.escape(c.get('name') or '')}</b> did not start: it needs the holiday sale "
                                "to be running and it isn't. Switch the sale on, then press Resume in Admin > Campaigns.")
            return 0
    claimed = await db.cmtv_campaigns.find_one_and_update(
        {"_id": cid, "status": "scheduled"}, {"$set": {"status": "sending", "started_at": now, "pause_reason": None}})
    if not claimed:
        return 0
    try:
        aud = await audience(c, now)
    except Exception as e:
        await db.cmtv_campaigns.update_one({"_id": cid}, {"$set": {"status": "paused", "started_at": None,
                                                                  "pause_reason": f"couldn't work out the recipients: {e}"}})
        await _ops_critical(f"⏸️ Campaign <b>{html.escape(c.get('name') or '')}</b> did not start: {html.escape(str(e))}")
        return 0
    n = 0
    for r in aud["recipients"]:
        u = r["user"]
        try:
            await db.cmtv_campaign_sends.insert_one({
                "_id": f"{cid}:{u['_id']}", "campaign_id": cid, "user_id": str(u["_id"]), "email": u["email"],
                "name": u.get("name") or "", "status": "queued", "queued_at": now})
            n += 1
        except DuplicateKeyError:
            pass
    await db.cmtv_campaigns.update_one({"_id": cid}, {"$set": {"audience_count": len(aud["recipients"]),
                                                              "skipped_at_start": len(aud["skipped"])}})
    when = "" if in_window(now) else f" (outside send hours: starts at {_local(next_window_start(now)):%-I %p} Toronto)"
    await _ops(f"📣 Campaign <b>{html.escape(c.get('name') or '')}</b> started: {n} to send, "
               f"{len(aud['skipped'])} left out{when}.")
    return n


async def send_one(c, now=None):
    """Send the next queued email of campaign c. Returns False when none are left."""
    db = _db()
    now = now or datetime.utcnow()
    cid = c["_id"]
    doc = await db.cmtv_campaign_sends.find_one_and_update(
        {"campaign_id": cid, "status": "queued"}, {"$set": {"status": "sending", "claimed_at": now}},
        sort=[("queued_at", 1), ("_id", 1)])
    if not doc:
        return False
    status, reason = "failed", ""
    try:
        u = await db.users.find_one({"_id": _oid(doc["user_id"])})
        if not u:
            status, reason = "skipped", "account gone"
        elif await is_unsubscribed(u.get("email")):
            status, reason = "skipped", "unsubscribed from offers"
        else:
            services = [s async for s in db.services.find({"user_id": {"$in": [doc["user_id"], _oid(doc["user_id"])]}})]
            bonus, running = await promo_months(now=now)
            if c.get("requires_promo") and not running:
                await db.cmtv_campaign_sends.update_one({"_id": doc["_id"]}, {"$set": {"status": "queued"}})
                await db.cmtv_campaigns.update_one({"_id": cid, "status": "sending"}, {"$set": {
                    "status": "paused", "pause_reason": "the holiday sale ended or was switched off"}})
                await _ops_critical(f"⏸️ Campaign <b>{html.escape(c.get('name') or '')}</b> paused: the holiday sale isn't running.")
                return False
            fields = personal(u, services, bonus, now)
            subject, page, text = render(c, fields, await unsub_link(u["email"]))
            es = await D["get_email_service"]()
            ok = bool(await es.send_email(to_email=u["email"], subject=subject, html_content=page, text_content=text,
                                          email_type="marketing", template_type="cmtv_campaign", customer_id=str(u["_id"]),
                                          recipient_name=u.get("name") or ""))
            status, reason = ("sent", "") if ok else ("failed", "the email service didn't accept it")
    except Exception as e:
        status, reason = "failed", str(e)[:200]
        logger.warning(f"CMTV campaigns: send to {doc.get('email')} failed: {e}")
    await db.cmtv_campaign_sends.update_one({"_id": doc["_id"]}, {"$set": {"status": status, "reason": reason, "done_at": datetime.utcnow()}})
    return True


async def finish_if_done(c):
    db = _db()
    k = await counts(c["_id"])
    if k["queued"] or k["sending"]:
        return False
    r = await db.cmtv_campaigns.update_one({"_id": c["_id"], "status": "sending"},
                                           {"$set": {"status": "sent", "finished_at": datetime.utcnow(), "counts": k}})
    if r.modified_count:
        await _ops(f"✅ Campaign <b>{html.escape(c.get('name') or '')}</b> finished: {k['sent']} sent, {k['failed']} failed, "
                   f"{k['skipped']} skipped.")
    return True


async def tick(now_fn=datetime.utcnow, sleep=asyncio.sleep):
    """One pass: start due campaigns, then send while inside send hours."""
    db = _db()
    async for c in db.cmtv_campaigns.find({"status": "scheduled", "send_at": {"$lte": now_fn()}}):
        await start_campaign(c, now_fn())
    cfg = await config()
    async for c in db.cmtv_campaigns.find({"status": "sending"}).sort("started_at", 1):
        while in_window(now_fn()):
            fresh = await db.cmtv_campaigns.find_one({"_id": c["_id"]})
            if not fresh or fresh.get("status") != "sending":
                break
            if not await send_one(fresh, now_fn()):
                break
            await sleep(cfg["throttle_seconds"])
        fresh = await db.cmtv_campaigns.find_one({"_id": c["_id"]})
        if fresh and fresh.get("status") == "sending":
            await finish_if_done(fresh)


async def _loop():
    await asyncio.sleep(20)
    while True:
        try:
            await tick()
        except Exception as e:
            logger.error(f"CMTV campaigns loop: {e}")
        try:
            await asyncio.wait_for(_wake.wait(), timeout=60)
        except asyncio.TimeoutError:
            pass
        _wake.clear()


# ---------- admin API ----------

EDITABLE = ("name", "subject", "preheader", "heading", "blocks", "audience", "include_resellers", "include_unbilled",
            "requires_promo", "notes")


def clean_blocks(blocks):
    out = []
    for b in (blocks or [])[:60]:
        if not isinstance(b, dict) or b.get("type") not in BLOCK_TYPES:
            continue
        nb = {"type": b["type"]}
        for k in ("text", "fallback", "title", "subtitle", "emoji", "label", "href"):
            if b.get(k) not in (None, ""):
                nb[k] = str(b[k])[:4000]
        out.append(nb)
    return out


def clean(body):
    d = {}
    for k in EDITABLE:
        if k in body:
            v = body[k]
            if k == "blocks":
                v = clean_blocks(v)
            elif k in ("include_resellers", "include_unbilled", "requires_promo"):
                v = bool(v)
            else:
                v = str(v or "")[:300 if k != "notes" else 2000]
            d[k] = v
    if "audience" in d and d["audience"] not in AUDIENCES:
        raise HTTPException(400, "Unknown audience")
    return d


def public(c):
    c = dict(c)
    c["id"] = str(c.pop("_id"))
    for k in ("send_at", "created_at", "updated_at", "started_at", "finished_at"):
        if isinstance(c.get(k), datetime):
            c[k + "_local"] = _local(c[k]).strftime("%Y-%m-%d %H:%M")
            c[k] = c[k].isoformat() + "Z"
    return c


def _sample_row(r):
    u = r["user"]
    return {"user_id": str(u["_id"]), "email": u.get("email"), "name": u.get("name") or ""}


async def get_or_404(cid):
    c = await _db().cmtv_campaigns.find_one({"_id": cid})
    if not c:
        raise HTTPException(404, "Campaign not found")
    return c


async def fields_for(camp, user_id=None):
    """Preview / test fields: a chosen customer's, or the sample "Sam". Previews count the bonus as if the sale runs."""
    bonus, running = await promo_months(assume=bool(camp.get("requires_promo")))
    if user_id:
        u = await _db().users.find_one({"_id": _oid(user_id)})
        if not u:
            raise HTTPException(404, "Customer not found")
        services = [s async for s in _db().services.find({"user_id": {"$in": [user_id, _oid(user_id)]}})]
        return personal(u, services, bonus), u.get("email"), running
    f = dict(SAMPLE)
    end = datetime(2027, 1, 14).date()
    f["renew_until"] = _nice(add_months(end, 12 + bonus))
    return f, None, running


def init_routes():
    admin = D["get_current_admin_user"]

    @router.get("/admin")
    async def list_campaigns(all: int = 0, current_user: dict = Depends(admin)):
        q = {} if all else {"retired": {"$ne": True}}
        rows = []
        async for c in _db().cmtv_campaigns.find(q).sort("created_at", -1):
            p = public(c)
            if c.get("status") in ("sending", "sent", "paused", "cancelled"):
                p["counts"] = await counts(c["_id"])
            rows.append(p)
        cfg = await config()
        bonus, running = await promo_months()
        return {"campaigns": rows, "audiences": AUDIENCES, "fields": FIELDS, "block_types": BLOCK_TYPES,
                "exclude_emails": cfg["exclude_emails"], "throttle_seconds": cfg["throttle_seconds"],
                "window": f"{WINDOW[0]}:00-{WINDOW[1]}:00 Toronto", "in_window": in_window(), "promo_running": running,
                "me": current_user.get("email")}

    @router.post("/admin")
    async def create(body: dict = Body(...), current_user: dict = Depends(admin)):
        d = clean(body)
        now = datetime.utcnow()
        d.update({"_id": str(ObjectId()), "status": "draft", "created_by": current_user.get("email"), "created_at": now,
                  "updated_at": now})
        d.setdefault("name", "New campaign")
        d.setdefault("audience", "active_paying")
        d.setdefault("blocks", [])
        await _db().cmtv_campaigns.insert_one(d)
        return public(d)

    @router.put("/admin/{cid}")
    async def update(cid: str, body: dict = Body(...), current_user: dict = Depends(admin)):
        c = await get_or_404(cid)
        if c.get("status") != "draft":
            raise HTTPException(400, "Only drafts can be edited (unschedule it first)")
        d = clean(body)
        d.update({"updated_at": datetime.utcnow(), "updated_by": current_user.get("email")})
        await _db().cmtv_campaigns.update_one({"_id": cid}, {"$set": d})
        return public(await get_or_404(cid))

    @router.post("/admin/{cid}/copy")
    async def copy(cid: str, current_user: dict = Depends(admin)):
        c = await get_or_404(cid)
        now = datetime.utcnow()
        d = {k: c.get(k) for k in EDITABLE if k in c}
        d.update({"_id": str(ObjectId()), "name": f"{c.get('name') or 'Campaign'} (copy)", "status": "draft",
                  "created_by": current_user.get("email"), "created_at": now, "updated_at": now})
        await _db().cmtv_campaigns.insert_one(d)
        return public(d)

    @router.post("/admin/preview")
    async def preview(body: dict = Body(...), current_user: dict = Depends(admin)):
        """Render unsaved content: {campaign: {...}, user_id?}."""
        camp = clean(body.get("campaign") or {})
        f, email, running = await fields_for(camp, body.get("user_id"))
        subject, page, text = render(camp, f, f"{SITE}/api/cmtv/campaigns/unsubscribe?t=preview")
        return {"subject": subject, "html": page, "text": text, "fields": f, "for": email or "sample customer (Sam)",
                "assumes_sale": bool(camp.get("requires_promo")) and not running}

    @router.post("/admin/{cid}/test")
    async def send_test(cid: str, body: dict = Body({}), current_user: dict = Depends(admin)):
        c = await get_or_404(cid)
        _check_campaign(c)
        to = str(body.get("to") or current_user.get("email") or "").strip()
        if not _real_email(to):
            raise HTTPException(400, "No address to send the test to")
        f, _, running = await fields_for(c, body.get("user_id"))
        subject, page, text = render(c, f, await unsub_link(to))
        es = await D["get_email_service"]()
        ok = bool(await es.send_email(to_email=to, subject=f"[TEST] {subject}", html_content=page, text_content=text,
                                      email_type="transactional", template_type="cmtv_campaign_test", sent_by=current_user.get("email")))
        await _db().cmtv_campaigns.update_one({"_id": cid}, {"$push": {"tests": {"to": to, "at": datetime.utcnow(), "ok": ok}}})
        if not ok:
            raise HTTPException(502, "The email service didn't accept the test")
        return {"ok": True, "to": to, "assumes_sale": bool(c.get("requires_promo")) and not running}

    @router.post("/admin/{cid}/dry-run")
    async def dry_run(cid: str, current_user: dict = Depends(admin)):
        c = await get_or_404(cid)
        aud = await audience(c)
        why = {}
        for s in aud["skipped"]:
            why[s["reason"]] = why.get(s["reason"], 0) + 1
        return {"count": len(aud["recipients"]), "first": [_sample_row(r) for r in aud["recipients"][:20]],
                "skipped": aud["skipped"], "skipped_by_reason": why, "audience": AUDIENCES[c["audience"]],
                "in_window": in_window(), "next_window": _local(next_window_start()).strftime("%Y-%m-%d %H:%M")}

    async def _arm(cid, body, when, current_user):
        c = await get_or_404(cid)
        if c.get("status") != "draft":
            raise HTTPException(400, "Only a draft can be scheduled or sent")
        _check_campaign(c)
        aud = await audience(c)
        n = len(aud["recipients"])
        if str(body.get("confirm") or "").strip() != str(n):
            raise HTTPException(400, f"Type the number of recipients ({n}) to confirm")
        if n == 0:
            raise HTTPException(400, "Nobody to send to")
        await _db().cmtv_campaigns.update_one({"_id": cid, "status": "draft"}, {"$set": {
            "status": "scheduled", "send_at": when, "armed_by": current_user.get("email"), "armed_at": datetime.utcnow(),
            "armed_count": n}})
        _wake.set()
        return public(await get_or_404(cid))

    @router.post("/admin/{cid}/schedule")
    async def schedule(cid: str, body: dict = Body(...), current_user: dict = Depends(admin)):
        try:
            loc = datetime.strptime(str(body.get("send_at") or ""), "%Y-%m-%dT%H:%M").replace(tzinfo=TZ)
        except ValueError:
            raise HTTPException(400, "Pick a date and time (Toronto)")
        when = _utc_naive(loc)
        if when < datetime.utcnow() - timedelta(minutes=1):
            raise HTTPException(400, "That time has passed")
        return await _arm(cid, body, when, current_user)

    @router.post("/admin/{cid}/send-now")
    async def send_now(cid: str, body: dict = Body(...), current_user: dict = Depends(admin)):
        return await _arm(cid, body, datetime.utcnow(), current_user)

    @router.post("/admin/{cid}/unschedule")
    async def unschedule(cid: str, current_user: dict = Depends(admin)):
        r = await _db().cmtv_campaigns.update_one({"_id": cid, "status": {"$in": ["scheduled"]}},
                                                  {"$set": {"status": "draft", "send_at": None}})
        if not r.modified_count:
            raise HTTPException(400, "Only a scheduled campaign that hasn't started can go back to draft")
        return public(await get_or_404(cid))

    @router.post("/admin/{cid}/pause")
    async def pause(cid: str, current_user: dict = Depends(admin)):
        r = await _db().cmtv_campaigns.update_one({"_id": cid, "status": "sending"},
                                                  {"$set": {"status": "paused", "pause_reason": f"paused by {current_user.get('email')}"}})
        if not r.modified_count:
            raise HTTPException(400, "It isn't sending")
        return public(await get_or_404(cid))

    @router.post("/admin/{cid}/resume")
    async def resume(cid: str, current_user: dict = Depends(admin)):
        c = await get_or_404(cid)
        if c.get("status") != "paused":
            raise HTTPException(400, "It isn't paused")
        if c.get("requires_promo") and not (await promo_months())[1]:
            raise HTTPException(400, "The holiday sale isn't running yet: switch it on in Admin > Notices first")
        new = "sending" if c.get("started_at") else "scheduled"
        await _db().cmtv_campaigns.update_one({"_id": cid, "status": "paused"}, {"$set": {"status": new, "pause_reason": None}})
        _wake.set()
        return public(await get_or_404(cid))

    @router.post("/admin/{cid}/cancel")
    async def cancel(cid: str, current_user: dict = Depends(admin)):
        r = await _db().cmtv_campaigns.update_one({"_id": cid, "status": {"$in": ["scheduled", "sending", "paused"]}},
                                                  {"$set": {"status": "cancelled", "cancelled_by": current_user.get("email"),
                                                            "cancelled_at": datetime.utcnow()}})
        if not r.modified_count:
            raise HTTPException(400, "Nothing to cancel")
        await _db().cmtv_campaign_sends.update_many({"campaign_id": cid, "status": "queued"}, {"$set": {"status": "cancelled"}})
        return public(await get_or_404(cid))

    @router.post("/admin/{cid}/retire")
    async def retire(cid: str, body: dict = Body({}), current_user: dict = Depends(admin)):
        c = await get_or_404(cid)
        if c.get("status") in ("scheduled", "sending"):
            raise HTTPException(400, "Cancel or unschedule it first")
        await _db().cmtv_campaigns.update_one({"_id": cid}, {"$set": {"retired": not body.get("undo"), "retired_at": datetime.utcnow()}})
        return {"ok": True}

    @router.get("/admin/{cid}/sends")
    async def sends(cid: str, current_user: dict = Depends(admin)):
        rows = []
        async for s in _db().cmtv_campaign_sends.find({"campaign_id": cid}).sort("queued_at", 1).limit(2000):
            rows.append({"email": s.get("email"), "name": s.get("name"), "status": s.get("status"), "reason": s.get("reason") or "",
                         "done_at": _local(s["done_at"]).strftime("%Y-%m-%d %H:%M") if s.get("done_at") else ""})
        return {"sends": rows, "counts": await counts(cid)}

    @router.put("/admin-config")
    async def set_config(body: dict = Body(...), current_user: dict = Depends(admin)):
        d = {}
        if "exclude_emails" in body:
            raw = body["exclude_emails"]
            items = raw if isinstance(raw, list) else re.split(r"[\s,;]+", str(raw or ""))
            d["exclude_emails"] = sorted({str(e).strip().lower() for e in items if "@" in str(e)})
        if "throttle_seconds" in body:
            d["throttle_seconds"] = min(60.0, max(2.0, float(body["throttle_seconds"] or THROTTLE)))
        await _db().cmtv_config.update_one({"_id": "campaigns"}, {"$set": d}, upsert=True)
        cfg = await config()
        return {"exclude_emails": cfg["exclude_emails"], "throttle_seconds": cfg["throttle_seconds"]}

    # ----- public: unsubscribe -----

    @router.get("/unsubscribe", response_class=HTMLResponse)
    async def unsub_page(t: str = ""):
        email = read_token((await config())["unsub_key"], t)
        if not email:
            return _page("Link not recognised", "This unsubscribe link isn't valid any more. Message us on Telegram or at "
                         "cmtv@pm.me and we'll take you off the list.")
        if await is_unsubscribed(email):
            return _page("You're unsubscribed", DONE, email=email)
        return _page("Unsubscribe", ASK, form_action=f"/api/cmtv/campaigns/unsubscribe?t={t}", email=email)

    @router.post("/unsubscribe", response_class=HTMLResponse)
    async def unsub_do(t: str = ""):
        email = read_token((await config())["unsub_key"], t)
        if not email:
            raise HTTPException(400, "Link not recognised")
        await do_unsubscribe(email, "campaign link")
        return _page("You're unsubscribed", DONE, email=email)

    @legacy_router.get("/api/unsubscribe", response_class=HTMLResponse)
    async def legacy_page(request: Request):
        # the older emails' link: /api/unsubscribe?email=a+b@x.com ("+" arrives as a space)
        email = str(request.query_params.get("email") or "").strip().replace(" ", "+")
        if not _real_email(email):
            return _page("Link not recognised", "Message us on Telegram or at cmtv@pm.me and we'll take you off the list.")
        if await is_unsubscribed(email):
            return _page("You're unsubscribed", DONE, email=email)
        return _page("Unsubscribe", ASK, form_action=f"/api/cmtv/campaigns/unsubscribe-email?t={unsub_token((await config())['unsub_key'], email)}",
                     email=email)

    @router.post("/unsubscribe-email", response_class=HTMLResponse)
    async def legacy_do(t: str = ""):
        email = read_token((await config())["unsub_key"], t)
        if not email:
            raise HTTPException(400, "Link not recognised")
        await do_unsubscribe(email, "older email link")
        return _page("You're unsubscribed", DONE, email=email)
