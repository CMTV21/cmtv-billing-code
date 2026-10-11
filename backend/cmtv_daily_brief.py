"""Daily admin dashboard in Telegram (CMTV local addition 2026-10-10, owner: "a bot to deliver me a daily dashboard.
Sales, tickets, things to do").

Every morning at cmtv_config {_id: "daily_brief"}.hour (default 8, Toronto time) one message goes to the Ops group's
Billing topic through the Ops bot (cmtv_notify.ops): yesterday's sales + month to date, new customers / trials, tickets
waiting, a to-do list, panel credit balances. The numbers come from the Admin home (cmtv_admin_overview's /overview, called
directly) and the Finances ledger, so all three agree. Sent once per day (cmtv_config daily_brief.last_sent = local date).
Switches in cmtv_config daily_brief: enabled (default on), hour, send_now (True = send within a minute, then cleared).
"""
import asyncio
import html
import logging
from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

log = logging.getLogger("server")
TZ = ZoneInfo("America/Toronto")
D = {}
SITE = "https://billing.cmtv.info"
FAM = {"cctv": "CCTV", "imperium": "Imperium", "addons": "Add-ons", "other": "Other"}


def init(**deps):
    D.update(deps)


def _m(v):
    return f"${v:,.2f}" if abs(v - round(v)) > 0.004 else f"${v:,.0f}"


def _e(v):
    return html.escape(str(v if v is not None else ""))


async def _overview():
    import cmtv_admin_overview as ov
    fn = next(r.endpoint for r in ov.router.routes if getattr(r, "path", "").endswith("/overview"))
    return await fn(current_user={"sub": "daily-brief", "role": "admin"})


async def build(now_utc: datetime = None) -> str:
    db = D["db"]
    now_utc = now_utc or datetime.utcnow()
    local = now_utc.replace(tzinfo=ZoneInfo("UTC")).astimezone(TZ)
    today = local.replace(hour=0, minute=0, second=0, microsecond=0)
    yday = today - timedelta(days=1)
    y0, y1 = yday.replace(tzinfo=None), today.replace(tzinfo=None)                 # ledger dates are Toronto-local
    yu0 = yday.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)                     # billing stores naive UTC
    yu1 = today.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
    ov = await _overview()
    parts = [f"☀️ <b>CMTV daily dashboard</b> · {local:%a %b} {local.day}"]

    # ---- sales (ledger) ----
    import cmtv_finance
    total, n, new_paying, fams = 0.0, 0, 0, defaultdict(float)
    async for t in cmtv_finance.D["tx"].find({"deleted": {"$ne": True}, "date": {"$gte": y0, "$lt": y1}}):
        amt = float(t.get("amount") or 0)
        if amt <= 0:
            continue
        total, n = total + amt, n + 1
        new_paying += 1 if t.get("new_user") else 0
        import cmtv_admin_overview as cao
        fams[cao.SERVER_FAMILY.get(str(t.get("server") or ""), "other")] += amt
    rev = ov.get("revenue") or {}
    month, prev_same = float(rev.get("month") or 0), float(rev.get("prev_same_point") or 0)
    vs = ""
    if prev_same > 0:
        pct = round((month - prev_same) * 100 / prev_same)
        vs = f" ({'+' if pct >= 0 else ''}{pct}% vs same point last month)"
    split = " · ".join(f"{FAM.get(k, k)} {_m(v)}" for k, v in sorted(fams.items(), key=lambda x: -x[1]))
    parts.append(
        "\n💰 <b>Sales</b>\n"
        f"Yesterday: <b>{_m(total)}</b> from {n} payment{'s' if n != 1 else ''}" + (f"\n{split}" if split else "") +
        f"\n{_e(ov.get('month'))} so far: <b>{_m(month)}</b>{vs}"
        f"\nProfit this month: {_m(float(rev.get('profit_month') or 0))}")

    # ---- customers ----
    signups = await db.users.count_documents({"role": "user", "created_at": {"$gte": yu0, "$lt": yu1},
                                              "email": {"$not": {"$regex": "@panel\\.local$"}}})
    trials = await db.services.count_documents({"is_trial": True, "created_at": {"$gte": yu0, "$lt": yu1}})
    t30 = ((ov.get("trials") or {}).get("d30") or {})
    conv = f"{t30.get('pct')}% ({t30.get('paying')}/{t30.get('trials')})" if t30.get("pct") is not None else "n/a"
    active = ov.get("active") or {}
    act = " · ".join(f"{FAM.get(k, k)} {v}" for k, v in active.items() if v)
    parts.append(
        "\n👥 <b>Customers</b>\n"
        f"New sign-ups: {signups} · trials started: {trials} · new paying: {new_paying}\n"
        f"Trials → paying (30 days): {conv}\n"
        f"Active: <b>{ov.get('active_total', 0)}</b>" + (f" ({act})" if act else ""))

    # ---- support ----
    needs = ov.get("needs") or {}
    waiting = needs.get("tickets_waiting") or []
    opened = await db.tickets.count_documents({"created_at": {"$gte": yu0, "$lt": yu1}})
    lines = [f"\n🎫 <b>Support</b>\nWaiting on you: <b>{len(waiting)}</b> · opened yesterday: {opened}"]
    for t in waiting[:4]:
        lines.append(f"• {_e((t.get('subject') or '(no subject)')[:60])}" + (f" · {_e(t.get('customer'))}" if t.get("customer") else ""))
    if len(waiting) > 4:
        lines.append(f"• +{len(waiting) - 4} more")
    parts.append("\n".join(lines))

    # ---- to do ----
    todo = []
    pend = needs.get("pending_payment") or []
    if pend:
        todo.append(f"💳 {len(pend)} payment{'s' if len(pend) != 1 else ''} to confirm ({_m(sum(float(p.get('total') or 0) for p in pend))})")
    nsu = needs.get("not_set_up") or []
    if nsu:
        todo.append(f"⚠️ {len(nsu)} paid order{'s' if len(nsu) != 1 else ''} not set up")
    if needs.get("dupe_blocks"):
        todo.append(f"🚫 {needs['dupe_blocks']} suspected duplicate{'s' if needs['dupe_blocks'] != 1 else ''} on hold")
    if needs.get("email_failed"):
        todo.append(f"📧 {len(needs['email_failed'])} email{'s' if len(needs['email_failed']) != 1 else ''} failed (7 days)")
    try:
        inbox = await db.cmtv_fin_inbox.count_documents({"status": "open"})
    except Exception:
        inbox = 0
    if inbox:
        todo.append(f"🧾 {inbox} payment{'s' if inbox != 1 else ''} in Needs recording")
    soon = [x for x in (ov.get("expiring") or []) if not x.get("auto_renew")
            and datetime.fromisoformat(x["ends"].rstrip("Z")) <= now_utc + timedelta(days=3)]
    wk = needs.get("ending_week_no_autorenew") or 0
    if wk:
        todo.append(f"⏳ {wk} plan{'s' if wk != 1 else ''} end this week (no auto-renew)" +
                    (f", {len(soon)} in the next 3 days:" if soon else ""))
        for x in soon[:5]:
            ends = datetime.fromisoformat(x["ends"].rstrip("Z")).replace(tzinfo=ZoneInfo("UTC")).astimezone(TZ)
            todo.append(f"   • {_e(x.get('customer'))} · {_e(x.get('service'))} · {ends:%a %b} {ends.day}")
        if len(soon) > 5:
            todo.append(f"   • +{len(soon) - 5} more")
    parts.append("\n✅ <b>To do</b>\n" + ("\n".join(todo) if todo else "Nothing waiting. 🎉"))

    # ---- panel credits ----
    try:
        import cmtv_reseller_credits as rc
        cc, im = await rc.cctv_balance(), await rc.imperium_balance()
        fmt = lambda v: f"{v:,.0f}" if isinstance(v, (int, float)) else "couldn't read"
        parts.append(f"\n🏦 <b>Panel credits</b>\nCCTV: {fmt(cc)} · Imperium: {fmt(im)}")
    except Exception as e:
        log.warning(f"daily brief: credits ({e})")

    parts.append(f'\n<a href="{SITE}/admin">Open Admin</a>')
    return "\n".join(parts)


async def _cfg():
    return await D["db"].cmtv_config.find_one({"_id": "daily_brief"}) or {}


async def send(now_utc: datetime = None) -> bool:
    import cmtv_notify
    text = await build(now_utc)
    return await cmtv_notify.ops(text, kind="billing")


async def tick(now_utc: datetime = None):
    cfg = await _cfg()
    now_utc = now_utc or datetime.utcnow()
    local = now_utc.replace(tzinfo=ZoneInfo("UTC")).astimezone(TZ)
    day = local.date().isoformat()
    if cfg.get("send_now"):
        await D["db"].cmtv_config.update_one({"_id": "daily_brief"}, {"$unset": {"send_now": ""}})
        ok = await send(now_utc)
        log.info(f"daily brief: sent on request ({ok})")
        return
    if cfg.get("enabled") is False or cfg.get("last_sent") == day or local.hour < int(cfg.get("hour", 8)):
        return
    if local.hour > int(cfg.get("hour", 8)) + 3:   # e.g. after a long outage: skip today rather than send at night
        return
    await D["db"].cmtv_config.update_one({"_id": "daily_brief"}, {"$set": {"last_sent": day}}, upsert=True)
    ok = await send(now_utc)
    log.info(f"daily brief: sent for {day} ({ok})")


async def _loop():
    await asyncio.sleep(45)
    while True:
        try:
            await tick()
        except Exception as e:
            log.warning(f"daily brief failed: {type(e).__name__}: {e}")
        await asyncio.sleep(60)


async def startup():
    asyncio.create_task(_loop())
