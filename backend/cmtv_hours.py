"""Support hours (CMTV local addition 2026-10-05, the owner's request after a new customer's e-Transfer at 10:22 pm waited
until 1:43 am). Regular hours 8 am - 9 pm Eastern every day, set in Admin > Notices (cmtv_config {_id: "hours"}), with an
"Away" switch for days off (back at opening time on the chosen date).
Used by: checkout (e-Transfer), the new-ticket window, Tickets + Status pages, and the e-Transfer order email (sent when an
e-Transfer order is placed: how to pay, the order id to put in the message, and when it will be set up).
"""
import html
import logging
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Body, Depends, HTTPException

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/cmtv/hours", tags=["cmtv-hours"])
D = {}
TZ = ZoneInfo("America/Toronto")
DEFAULT = {"open": "08:00", "close": "21:00", "away_until": None, "away_note": ""}


def init(**deps):
    D.update(deps)


async def config():
    doc = await D["db"].cmtv_config.find_one({"_id": "hours"}) or {}
    return {k: doc.get(k, v) for k, v in DEFAULT.items()}


def _t(s):
    h, m = (int(x) for x in s.split(":"))
    return time(h, m)


def clock(t):
    """time(8, 0) -> '8 am', time(21, 30) -> '9:30 pm'"""
    h = t.hour % 12 or 12
    return f"{h}{'' if t.minute == 0 else f':{t.minute:02d}'} {'am' if t.hour < 12 else 'pm'}"


def _next_open(local, op, cl):
    """First moment at or after `local` that is inside regular hours."""
    if op <= local.time() < cl:
        return local
    day = local.date() if local.time() < op else local.date() + timedelta(days=1)
    return datetime.combine(day, op, tzinfo=TZ)


def _when(dt, now):
    """'8 am Eastern today' / 'tomorrow' / 'on Wednesday, Oct 7'"""
    d = (dt.date() - now.date()).days
    day = "today" if d == 0 else "tomorrow" if d == 1 else f"on {dt.strftime('%A, %b')} {dt.day}"
    return f"{clock(dt.time())} Eastern {day}"


def status(cfg, now=None):
    now = (now or datetime.now(timezone.utc)).astimezone(TZ)
    op, cl = _t(cfg["open"]), _t(cfg["close"])
    away_until = cfg.get("away_until")
    away = False
    start = now
    if away_until:
        au = datetime.combine(datetime.strptime(away_until, "%Y-%m-%d").date(), op, tzinfo=TZ)
        if now < au:
            away, start = True, au
    open_now = not away and op <= now.time() < cl
    nxt = now if open_now else _next_open(start, op, cl)
    return {
        "open_now": open_now,
        "away": away,
        "away_note": (cfg.get("away_note") or "") if away else "",
        "hours": f"{clock(op)} – {clock(cl)} Eastern",
        "open": cfg["open"], "close": cfg["close"], "away_until": away_until,
        "next_open": nxt.astimezone(timezone.utc).isoformat(),
        "next_open_text": "" if open_now else _when(nxt, now),
    }


async def current():
    return status(await config())


def init_routes():
    admin = D["get_current_admin_user"]

    @router.get("")
    async def public_status():
        return await current()

    @router.get("/admin")
    async def admin_get(current_user: dict = Depends(admin)):
        return await current()

    @router.post("/admin")
    async def admin_set(data: dict = Body(...), current_user: dict = Depends(admin)):
        cfg = await config()
        for k in ("open", "close"):
            if k in data:
                try:
                    _t(str(data[k]))
                except Exception:
                    raise HTTPException(400, "Times look like 08:00 or 21:00.")
                cfg[k] = str(data[k])[:5]
        if _t(cfg["open"]) >= _t(cfg["close"]):
            raise HTTPException(400, "Opening time must be before closing time.")
        if "away_until" in data:
            a = data.get("away_until") or None
            if a:
                try:
                    if datetime.strptime(a, "%Y-%m-%d").date() <= datetime.now(TZ).date():
                        raise ValueError
                except ValueError:
                    raise HTTPException(400, "Pick a 'back on' date after today.")
            cfg["away_until"] = a
            cfg["away_note"] = " ".join(str(data.get("away_note") or "").split())[:160] if a else ""
        await D["db"].cmtv_config.update_one({"_id": "hours"}, {"$set": {**cfg, "updated_at": datetime.utcnow(),
                                                                         "updated_by": current_user.get("sub")}}, upsert=True)
        return status(cfg)


async def send_emt_pending(order_id, user, total, instructions):
    """Email after an e-Transfer order is placed: how to pay, the order id for the message, and when it will be set up."""
    try:
        if not (user or {}).get("email"):
            return
        st = await current()
        name = html.escape((user.get("name") or "there").split()[0])
        steps = html.escape(instructions or "Reply to this email and we'll send the e-Transfer details.").replace("\n", "<br>")
        if st["open_now"]:
            when = (f"We confirm e-Transfers by hand between {st['hours']}. We're online now, so your service will be set "
                    f"up soon after your e-Transfer arrives.")
        else:
            away = f" ({html.escape(st['away_note'])})" if st["away_note"] else ""
            when = (f"We confirm e-Transfers by hand between {st['hours']}. We're offline right now{away}, so your service "
                    f"will be set up by about <b>{st['next_open_text']}</b>. Want it working now? Pay by PayPal on the "
                    f"checkout page instead and it's set up instantly.")
        body = f"""
<h2>Thanks for your order, {name}!</h2>
<p>Here's how to pay for order <b>#{order_id}</b>.</p>
<div style="background:#f3f6fb;border-radius:8px;padding:16px 18px;margin:16px 0">
  <p style="margin:0 0 8px"><b>Amount:</b> ${total:.2f} CAD</p>
  <p style="margin:0 0 8px"><b>Put this in the e-Transfer message:</b> <span style="font-family:monospace">{order_id}</span></p>
  <p style="margin:0">{steps}</p>
</div>
<p>{when}</p>
<p>You'll get another email with your login details once it's ready.</p>
"""
        es = await D["get_email_service"]()
        await es.send_email(to_email=user["email"], subject=f"How to pay for your CMTV order (${total:.2f})",
                            html_content=es._wrap_email(body, "Your CMTV order", user["email"], "transactional"),
                            email_type="transactional", order_id=order_id, recipient_name=user.get("name"))
    except Exception as e:
        logger.warning(f"CMTV hours: e-Transfer order email failed for {order_id}: {e}")
