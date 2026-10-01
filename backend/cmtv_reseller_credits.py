"""Reseller credits in any amount, priced per credit, plus the reseller area and alerts (CMTV local addition 2026-09-28).

A reseller picks 50-1000 credits instead of a fixed 100/250/500/1000 pack. The order item carries `credits` (models.py
OrderItemCreate); create_order (server.py) prices it here, on the server, from the per-credit steps below, and
provision_order_services hands the panel code a copy of the pack product with reseller_credits = the chosen amount, so
every path (new CCTV reseller, CCTV top-up, new Imperium sub-reseller, Imperium top-up) gives exactly that many.
Steps can be changed in cmtv_config {_id: "reseller_pricing"} without a deploy.
Imperium credits come out of CMTV's own Imperium balance, so an online order can't ask for more than CMTV has
(the slider's max shrinks to it; anything bigger: "message us").
  GET  /api/cmtv/reseller/pricing -> {min, max, servers: {cctv|imperium: {label, product_id, tiers, max, available}}}
  GET  /api/cmtv/reseller/mine    -> the signed-in customer's reseller panels with balance (dashboard box)
  GET  /api/cmtv/reseller/admin   -> Admin > Resellers (all resellers, CMTV's Imperium balance, alert levels)
  POST /api/cmtv/reseller/admin/alerts {reseller_low, own_imperium_low}
Hourly job: CCTV reseller balances from the panel (the developer's sync only refreshes subscriber lines), then alerts:
a reseller under `reseller_low` (default 50) gets one email + Telegram (if connected), reset once they're back above;
CMTV's Imperium balance under `own_imperium_low` (default 300) -> Ops Critical, at most once a day.
"""
import asyncio
import html
import logging
from datetime import datetime, timedelta

from bson import ObjectId
from fastapi import APIRouter, Body, Depends, HTTPException

log = logging.getLogger("server")
router = APIRouter(prefix="/api/cmtv/reseller", tags=["cmtv-reseller"])
D = {}
MIN_CREDITS, MAX_CREDITS = 50, 1000
LABEL = {"cctv": "CCTV", "imperium": "Imperium"}
SITE = "https://billing.cmtv.info"
# price per credit from each amount up (the user's prices, 2026-09-28)
DEFAULT_TIERS = {
    "cctv": [{"min": 50, "rate": 3.00}, {"min": 250, "rate": 2.75}, {"min": 500, "rate": 2.50}, {"min": 1000, "rate": 2.25}],
    "imperium": [{"min": 50, "rate": 4.00}, {"min": 250, "rate": 3.80}, {"min": 500, "rate": 3.70}, {"min": 1000, "rate": 3.50}],
}
DEFAULT_ALERTS = {"reseller_low": 50, "own_imperium_low": 300, "own_cctv_low": 100}
_imp = {"balance": None, "at": None}
_cctv = {"balance": None, "at": None}   # 2026-09-29: CMTV's own CCTV balance (CCTV reseller credits come out of it too)


def init(**deps):
    D.update(deps)


def _oid(v):
    return ObjectId(v) if ObjectId.is_valid(str(v)) else None


def server_of(product: dict):
    pt = (product or {}).get("panel_type")
    if pt in ("aether", "nxtdash"):
        return "imperium"
    if pt in ("xtream", "xuione"):
        return "cctv"
    return None


async def tiers_for(server: str):
    cfg = await D["db"].cmtv_config.find_one({"_id": "reseller_pricing"}) or {}
    t = (cfg.get("tiers") or {}).get(server) or DEFAULT_TIERS.get(server) or []
    return sorted(({"min": int(x["min"]), "rate": float(x["rate"])} for x in t), key=lambda x: x["min"])


async def alert_levels():
    cfg = await D["db"].cmtv_config.find_one({"_id": "reseller_alerts"}) or {}
    return {k: float(cfg.get(k, v)) for k, v in DEFAULT_ALERTS.items()}


def rate_for(tiers, credits: int) -> float:
    r = None
    for t in tiers:
        if credits >= t["min"]:
            r = t["rate"]
    if r is None:
        raise ValueError("No price for that amount")
    return r


# ---------- Imperium (Aether) ----------

async def _aether():
    from aether_service import get_aether_service
    panels = ((await D["get_settings"]()).get("aether") or {}).get("panels") or []
    return get_aether_service(panels[0]) if panels else None


async def imperium_balance(max_age: int = 600):
    """CMTV's own Imperium credit balance (cached for max_age seconds). None if the panel can't be reached."""
    if _imp["at"] and (datetime.utcnow() - _imp["at"]).total_seconds() < max_age:
        return _imp["balance"]
    bal = None
    try:
        ae = await _aether()
        bal = await ae.get_balance() if ae else None
    except Exception as e:
        log.warning(f"Imperium balance: {e}")
    _imp.update(balance=bal, at=datetime.utcnow())
    return bal


async def imperium_sub_balances():
    """{username (lower): credits} for all of CMTV's Imperium sub-resellers (one API page is plenty today)."""
    out = {}
    try:
        ae = await _aether()
        if not ae:
            return out
        base = await ae._base()
        page = 1
        while True:
            data = await ae._request("GET", f"{base}/subresellers", params={"page": page, "per_page": 50})
            for it in data.get("items") or []:
                out[str(it.get("username", "")).lower()] = float(it.get("credits_balance") or 0)
            if page * 50 >= int(data.get("total") or 0):
                break
            page += 1
    except Exception as e:
        log.warning(f"Imperium sub-reseller balances: {e}")
    return out


async def custom_price(product: dict, credits: int):
    """(price, item name) for `credits` of this reseller pack's server. Raises ValueError with a customer-readable reason."""
    if (product or {}).get("account_type") != "reseller":
        raise ValueError("Only reseller packs can have a credit amount")
    server = server_of(product)
    if not server:
        raise ValueError("This pack can't be bought in a custom amount")
    if not (MIN_CREDITS <= int(credits) <= MAX_CREDITS):
        raise ValueError(f"Choose between {MIN_CREDITS} and {MAX_CREDITS} credits (message us for more)")
    # 2026-10-01 (the owner): any amount can be bought, whatever CMTV's own balance; provision_order_services checks
    # it with balance_short() and holds the order (not provisioned + Critical alert) when the balance can't cover it
    rate = rate_for(await tiers_for(server), int(credits))
    return round(int(credits) * rate, 2), f"{LABEL[server]} Reseller Credits - {int(credits)} credits"


async def balance_short(product: dict):
    """2026-10-01: None if CMTV's own balance on this pack's server covers its reseller_credits (or can't be read),
    else the reason, for the 'not provisioned' alert. Called before any reseller item goes to the panel."""
    server = server_of(product)
    need = float((product or {}).get("reseller_credits") or 0)
    if not server or need <= 0:
        return None
    bal = await (imperium_balance if server == "imperium" else cctv_balance)(max_age=0)
    if bal is None or need <= bal:
        return None
    return (f"LOW CREDITS: your {LABEL[server]} balance is {bal:g}, this order needs {need:g}. Nothing was sent to the "
            f"panel. The customer was emailed that the credits are on the way. Top up your {LABEL[server]} credits, then "
            f"re-run the order (/root/cmtv-scripts/reprovision_order.py <order id> --apply) or add the credits on the panel by hand.")


async def render(template_type: str, vals: dict):
    """2026-10-01: a CMTV-branded reseller email template (DB email_templates, made by reseller_templates.py, editable in
    Admin > Email Templates) filled with vals (already HTML-safe) -> (subject, complete html page), or None if the
    template is missing / switched off (callers then send their plain fallback)."""
    try:
        tpl = await D["db"].email_templates.find_one({"template_type": template_type, "is_active": True})
    except Exception:
        return None
    if not tpl or not tpl.get("html_content"):
        return None
    page, subject = tpl["html_content"], tpl.get("subject") or ""
    for k, v in vals.items():
        page = page.replace("{{" + k + "}}", str(v))
        subject = subject.replace("{{" + k + "}}", html.unescape(str(v)))
    return subject, page


async def held_email(email_service, user: dict, product: dict, order_id: str) -> bool:
    """2026-10-01 (the owner): a reseller order held by balance_short -> tell the customer their payment went through and
    the credits are on the way (never mentions CMTV's balance). The panel code's own email follows once it's provisioned."""
    to = str((user or {}).get("email") or "")
    if not email_service or not getattr(email_service, "enabled", False) or not to or to.lower().endswith("@panel.local"):
        return False
    label = LABEL.get(server_of(product), "")
    n = int(float(product.get("reseller_credits") or 0))
    first = html.escape(str(user.get("name") or "").split(" ")[0] or "there")
    ref = html.escape(str(order_id)[:8])
    body = (f"<h2 style=\"margin:0 0 12px\">Your {label} credits are on the way</h2>"
            f"<p>Hi {first},</p>"
            f"<p>Thanks, your payment for <b>{n} {label} reseller credits</b> (order #{ref}) came through.</p>"
            f"<p>We're adding them to your reseller panel now. This can take a little while; you'll get another email as "
            f"soon as they're on your panel. There's nothing you need to do.</p>"
            f"<p>Questions? Message us on Telegram (<a href=\"https://t.me/Cmtv_support_bot\">@Cmtv_support_bot</a>) or "
            f"email <a href=\"mailto:cmtv@pm.me\">cmtv@pm.me</a>.</p>"
            f"<p style=\"margin-top:18px\"><a href=\"{SITE}/dashboard\">Go to your dashboard</a></p>")
    text = (f"Hi {user.get('name') or 'there'},\n\nThanks, your payment for {n} {label} reseller credits (order #{str(order_id)[:8]}) "
            f"came through. We're adding them to your reseller panel now. This can take a little while; you'll get another "
            f"email as soon as they're on your panel. There's nothing you need to do.\n\n"
            f"Questions? Telegram @Cmtv_support_bot or cmtv@pm.me\n{SITE}/dashboard")
    subject = f"Your {label} credits are on the way"
    # the CMTV-branded template (Admin > Email Templates); the plain wrapped version above is the fallback
    branded = await render("reseller_credits_on_the_way", {"first_name": first, "credits": str(n), "server": html.escape(label),
                                                           "order_ref": ref, "dashboard_link": f"{SITE}/dashboard"})
    if branded:
        subject, html_full = branded
    else:
        html_full = email_service._wrap_email(body, subject, to, "transactional")
    return await email_service.send_email(to_email=to, subject=subject, html_content=html_full, text_content=text,
                                          email_type="transactional", order_id=str(order_id),
                                          recipient_name=user.get("name") or "")


# ---------- balances ----------

async def cctv_balance(max_age: int = 600):
    """CMTV's own credit balance on the CCTV (XtreamUI) panel, cached. It's what the panel dashboard shows
    (api.php?action=reseller_dashboard -> credits). None if the panel can't be reached. (2026-09-29)"""
    if _cctv["at"] and (datetime.utcnow() - _cctv["at"]).total_seconds() < max_age:
        return _cctv["balance"]
    bal = None
    try:
        panels = ((await D["get_settings"]()).get("xtream") or {}).get("panels") or []
        svc = D["get_xtream_service"](panels[0]) if panels else None
        if svc:
            def _read():
                sc = svc._get_session_client()
                if not sc.logged_in and not sc.login():
                    return None
                r = sc.session.get(f"{sc.panel_url}/api.php?action=reseller_dashboard", auth=sc.http_auth, timeout=15)
                return float(r.json().get("credits"))
            bal = await asyncio.to_thread(_read)
    except Exception as e:
        log.warning(f"CCTV balance: {e}")
    _cctv.update(balance=bal, at=datetime.utcnow())
    return bal

async def refresh_cctv_balances() -> int:
    """Reseller balances on the CCTV (XtreamUI) panels -> imported_users.credits. The developer's automatic sync only
    refreshes subscriber lines, so reseller balances only moved when an admin clicked "sync" (2026-09-28). Updates the
    resellers billing already knows; never creates or removes anything."""
    settings = await D["get_settings"]()
    panels = (settings.get("xtream") or {}).get("panels") or []
    now = datetime.utcnow()
    n = 0
    for i, panel in enumerate(panels):
        svc = D["get_xtream_service"](panel)
        if not svc:
            continue
        res = await asyncio.to_thread(svc.get_subresellers)
        if not res.get("success"):
            log.warning(f"reseller balances: panel {i} said {res.get('error')}")
            continue
        for r in res.get("users") or []:
            name = r.get("username")
            if not name:
                continue
            up = await D["db"].imported_users.update_one(
                {"username": name, "account_type": "reseller", "panel_index": i},
                {"$set": {"credits": float(r.get("credits") or 0), "member_group": r.get("member_group", ""), "last_synced": now}})
            n += up.matched_count
    return n


async def reseller_rows(live_imperium=True, include_demo=False):
    """Every active reseller service with its balance: [{service, server, username, credits, as_of}]
    2026-09-28: the demo reseller account's service (cmtv_demo: true, fake panel login, balance in cmtv_demo_credits) only
    shows on its own dashboard (include_demo), never in Admin > Resellers or the alerts."""
    db = D["db"]
    imp = await imperium_sub_balances() if live_imperium else {}
    rows = []
    q = {"account_type": "reseller", "status": "active"}
    if not include_demo:
        q["cmtv_demo"] = {"$ne": True}
    async for s in db.services.find(q).sort("created_at", 1):
        server = "imperium" if s.get("panel_type") in ("aether", "nxtdash") else "cctv"
        username = s.get("xtream_username") or s.get("username") or ""
        credits, as_of = None, None
        if s.get("cmtv_demo"):
            credits, as_of = float(s.get("cmtv_demo_credits") or 0), datetime.utcnow()
        elif server == "cctv":
            iu = await db.imported_users.find_one({"username": username, "account_type": "reseller"})
            if iu and iu.get("credits") is not None:
                credits, as_of = float(iu["credits"]), iu.get("last_synced")
        elif username.lower() in imp:
            credits, as_of = imp[username.lower()], datetime.utcnow()
        rows.append({"service": s, "server": server, "username": username, "credits": credits, "as_of": as_of})
    return rows


# ---------- alerts ----------

async def _ops(text, kind):
    try:
        import cmtv_notify
        await cmtv_notify.ops(text, kind, await D["get_settings"]())
    except Exception as e:
        log.warning(f"reseller alert (ops) failed: {e}")


async def low_balance_alerts(rows=None):
    """One heads-up per drop below the level (email + Telegram), reset once the balance is back above. Returns how many."""
    db = D["db"]
    levels = await alert_levels()
    low = levels["reseller_low"]
    rows = rows if rows is not None else await reseller_rows()
    sent = 0
    for r in rows:
        s, credits = r["service"], r["credits"]
        if credits is None:
            continue
        if credits >= low:
            if s.get("cmtv_low_alerted_at"):
                await db.services.update_one({"_id": s["_id"]}, {"$unset": {"cmtv_low_alerted_at": ""}})
            continue
        if s.get("cmtv_low_alerted_at"):
            continue
        u = await db.users.find_one({"_id": _oid(s.get("user_id"))}) or {}
        first = html.escape(str(u.get("name") or "").split(" ")[0] or "there")
        label = LABEL[r["server"]]
        amount = f"{credits:g}"
        link = f"{SITE}/dashboard"
        es = await D["get_email_service"]()
        if u.get("email") and not str(u["email"]).lower().endswith("@panel.local") and es and getattr(es, "enabled", False):
            body = (f"<h2 style=\"margin:0 0 8px\">You're down to {amount} credits</h2>"
                    f"<p>Hi {first}, your {label} reseller panel <strong>{html.escape(r['username'])}</strong> has "
                    f"<strong>{amount} credits</strong> left.</p><p>Top up any amount from 50 to 1,000 on your dashboard and the "
                    f"credits go straight onto your panel.</p>"
                    f"<p style=\"margin:22px 0\"><a href=\"{link}\" style=\"background:#22e6f2;color:#07101a;padding:12px 22px;"
                    f"border-radius:999px;text-decoration:none;font-weight:700\">Add credits</a></p>")
            subject, page = f"Your {label} reseller panel: {amount} credits left", None
            branded = await render("cmtv_reseller_low", {"first_name": first, "server": html.escape(label), "credits": amount,
                                                         "username": html.escape(r["username"]), "dashboard_link": link})
            if branded:   # 2026-10-01: CMTV-branded template
                subject, page = branded
            try:
                await es.send_email(to_email=u["email"], subject=subject,
                                    html_content=page or es._wrap_email(body, "Low credits", u["email"], "transactional"),
                                    email_type="transactional", template_type="cmtv_reseller_low", customer_id=str(u["_id"]))
            except Exception as e:
                log.warning(f"low-credit email failed: {e}")
        tg = (u.get("cmtv_telegram") or {}).get("chat_id")
        if tg:
            try:
                import cmtv_telegram_alerts
                await cmtv_telegram_alerts.queue(str(u["_id"]), tg, f"⚠️ <b>Your {label} reseller panel has {amount} credits left</b>\n\n"
                                                 "Top up any amount from 50 to 1,000.",
                                                 [[{"text": "➕ Add credits", "url": link}]], kind="reseller_low")
            except Exception as e:
                log.warning(f"low-credit telegram failed: {e}")
        await _ops(f"ℹ️ Reseller low on credits: {u.get('name') or r['username']} ({label} {r['username']}) has {amount} left. "
                   "They've been sent a top-up reminder.", "billing")
        await db.services.update_one({"_id": s["_id"]}, {"$set": {"cmtv_low_alerted_at": datetime.utcnow()}})
        sent += 1
    return sent


async def own_imperium_alert():
    """CMTV's Imperium balance under the level -> one Critical alert a day while it stays low. Returns True if sent."""
    db = D["db"]
    level = (await alert_levels())["own_imperium_low"]
    bal = await imperium_balance(max_age=0)
    if bal is None or bal >= level:
        return False
    st = await db.cmtv_config.find_one({"_id": "reseller_alerts_state"}) or {}
    last = st.get("own_imperium_alerted_at")
    if last and datetime.utcnow() - last < timedelta(hours=24):
        return False
    await _ops(f"🟠 CMTV's own Imperium balance is {bal:g} credits (alert level {level:g}).\n\nImperium reseller credits and "
               f"sub-reseller top-ups come out of it: customers can buy at most {int(bal)} online until you top it up on the "
               "Imperium panel.", "critical")
    await db.cmtv_config.update_one({"_id": "reseller_alerts_state"}, {"$set": {"own_imperium_alerted_at": datetime.utcnow()}}, upsert=True)
    return True


async def own_cctv_alert():
    """CMTV's CCTV balance under the level -> one Critical alert a day while it stays low (2026-09-29)."""
    db = D["db"]
    level = (await alert_levels())["own_cctv_low"]
    bal = await cctv_balance(max_age=0)
    if bal is None or bal >= level:
        return False
    st = await db.cmtv_config.find_one({"_id": "reseller_alerts_state"}) or {}
    last = st.get("own_cctv_alerted_at")
    if last and datetime.utcnow() - last < timedelta(hours=24):
        return False
    await _ops(f"🟠 CMTV's own CCTV balance is {bal:g} credits (alert level {level:g}).\n\nCCTV reseller credits and new lines "
               f"come out of it: resellers can buy at most {int(bal)} online until you top it up on the CCTV panel.", "critical")
    await db.cmtv_config.update_one({"_id": "reseller_alerts_state"}, {"$set": {"own_cctv_alerted_at": datetime.utcnow()}}, upsert=True)
    return True


async def _balance_loop():
    await asyncio.sleep(120)
    while True:
        try:
            n = await refresh_cctv_balances()
            log.info(f"reseller balances refreshed: {n}")
            await low_balance_alerts()
            await own_imperium_alert()
            await own_cctv_alert()
        except Exception as e:
            log.warning(f"reseller balance refresh failed: {e}")
        await asyncio.sleep(3600)


async def startup():
    asyncio.create_task(_balance_loop())


# ---------- routes ----------

def _iso(v):
    return v.isoformat() + "Z" if isinstance(v, datetime) else None


# ---------- who may buy reseller credits (2026-10-01) ----------
# The owner's rule: reseller credits are far cheaper than subscriptions, so only real resellers may buy them:
# admins, customers who already have an active reseller panel (top-ups), and customers the owner approved in
# Admin > Resellers (users.cmtv_reseller_approved; history in cmtv_reseller_approvals). create_order refuses the rest.
APPLY_URL = "https://cmtv.info/partners/"
NOT_ALLOWED = ("Reseller credits are only for approved CMTV resellers. "
               f"To become one, apply at {APPLY_URL} or message support.")


async def access(uid: str) -> dict:
    db = D["db"]
    u = await db.users.find_one({"_id": _oid(uid)}, {"role": 1, "cmtv_reseller_approved": 1}) or {}
    existing = bool(await db.services.find_one({"user_id": str(uid), "account_type": "reseller", "status": "active"}))
    approved = bool(u.get("cmtv_reseller_approved"))
    return {"allowed": u.get("role") == "admin" or existing or approved, "existing": existing, "approved": approved}


async def may_buy(uid: str) -> bool:
    return (await access(uid))["allowed"]


def init_routes():
    """Routes that need the signed-in customer / admin (dependencies passed in from server.py)"""
    current = D["get_current_user"]
    admin = D["get_current_admin_user"]

    @router.get("/mine")
    async def mine(current_user: dict = Depends(current)):
        """The customer's own reseller panels, with the credit balance (dashboard box)."""
        uid = current_user["sub"]
        rows = [r for r in await reseller_rows(live_imperium=False, include_demo=True) if str(r["service"].get("user_id")) == uid]
        if any(r["server"] == "imperium" for r in rows):
            imp = await imperium_sub_balances()
            for r in rows:
                if r["server"] == "imperium" and r["username"].lower() in imp:
                    r["credits"], r["as_of"] = imp[r["username"].lower()], datetime.utcnow()
        low = (await alert_levels())["reseller_low"]
        # panel-synced reseller records have no panel_url: use the reseller pack's (custom_panel_url) for that server
        pack_url = {}
        async for p in D["db"].products.find({"account_type": "reseller", "custom_panel_url": {"$nin": [None, ""]}}):
            pack_url.setdefault(server_of(p), str(p["custom_panel_url"]).replace("Https://", "https://"))
        out = []
        for r in rows:
            s = r["service"]
            out.append({"id": str(s["_id"]), "server": r["server"], "label": LABEL[r["server"]], "username": r["username"],
                        "password": s.get("xtream_password") or s.get("password") or "",
                        "panel_url": s.get("panel_url") or pack_url.get(r["server"]) or "",
                        "credits": r["credits"], "as_of": _iso(r["as_of"]), "low_level": low,
                        "demo": bool(s.get("cmtv_demo"))})
        return {"panels": out}

    @router.get("/access")
    async def my_access(current_user: dict = Depends(current)):
        """2026-10-01: may this customer buy reseller credits? (the storefront shows the Resellers tab only if so)"""
        return await access(current_user["sub"])

    @router.get("/admin/approved")
    async def admin_approved(current_user: dict = Depends(admin)):
        db = D["db"]
        out = []
        async for u in db.users.find({"cmtv_reseller_approved": True}, {"name": 1, "email": 1, "cmtv_reseller_approved_at": 1}):
            uid = str(u["_id"])
            out.append({"user_id": uid, "name": u.get("name"), "email": u.get("email"),
                        "approved_at": _iso(u.get("cmtv_reseller_approved_at")),
                        "has_panel": bool(await db.services.find_one({"user_id": uid, "account_type": "reseller", "status": "active"}))})
        return {"approved": out, "apply_url": APPLY_URL}

    @router.post("/admin/approve")
    async def admin_approve(data: dict = Body(...), current_user: dict = Depends(admin)):
        """{email | user_id, approved: true|false}: let a customer buy reseller credits (or take that back)."""
        db = D["db"]
        approved = bool(data.get("approved", True))
        email = str(data.get("email") or "").strip()
        if data.get("user_id"):
            users = await db.users.find({"_id": _oid(data["user_id"])}).to_list(2)
        elif email:
            import re
            users = await db.users.find({"email": {"$regex": f"^{re.escape(email)}$", "$options": "i"},
                                         "role": {"$nin": ["merged"]}}).to_list(3)
        else:
            raise HTTPException(status_code=400, detail="Enter the customer's email.")
        if not users:
            raise HTTPException(status_code=404, detail="No customer account with that email. They need to sign up first.")
        if len(users) > 1:
            raise HTTPException(status_code=409, detail="More than one account has that email: open the customer's profile instead.")
        u = users[0]
        now = datetime.utcnow()
        await db.users.update_one({"_id": u["_id"]}, {"$set": {"cmtv_reseller_approved": approved,
                                                                "cmtv_reseller_approved_at": now if approved else None}})
        await db.cmtv_reseller_approvals.insert_one({"user_id": str(u["_id"]), "email": u.get("email"), "approved": approved,
                                                     "by": current_user.get("sub"), "at": now})
        return {"ok": True, "user_id": str(u["_id"]), "name": u.get("name"), "email": u.get("email"), "approved": approved}

    @router.get("/guide")
    async def reseller_guide(current_user: dict = Depends(current)):
        """2026-09-28: the reseller guides (kb_articles with cmtv_audience "resellers", unpublished so the public
        /api/kb and the sitemap leave them out). Only for customers with an active reseller panel, and admins."""
        db = D["db"]
        uid = current_user["sub"]
        u = await db.users.find_one({"_id": _oid(uid)}) or {}
        if u.get("role") != "admin" and not await db.services.find_one(
                {"user_id": uid, "account_type": "reseller", "status": "active"}):
            raise HTTPException(status_code=403, detail="These guides are for CMTV resellers.")
        arts = await db.kb_articles.find({"cmtv_audience": "resellers"}, {"_id": 0}).sort("display_order", 1).to_list(50)
        return {"articles": arts}

    @router.get("/admin")
    async def admin_view(current_user: dict = Depends(admin)):
        db = D["db"]
        rows = await reseller_rows()
        levels = await alert_levels()
        out = []
        for r in rows:
            s = r["service"]
            uid = str(s.get("user_id"))
            u = await db.users.find_one({"_id": _oid(uid)}) or {}
            spent, last_topup, n = 0.0, None, 0
            async for o in db.orders.find({"user_id": uid, "status": "paid"}):
                its = [i for i in o.get("items") or [] if i.get("account_type") == "reseller"]
                if not its:
                    continue
                n += 1
                spent += sum(float(i.get("price") or 0) for i in its)
                t = o.get("paid_at") or o.get("created_at")
                if isinstance(t, datetime) and (last_topup is None or t > last_topup):
                    last_topup = t
            out.append({"service_id": str(s["_id"]), "user_id": uid, "name": u.get("name"), "email": u.get("email"),
                        "server": r["server"], "label": LABEL[r["server"]], "username": r["username"], "credits": r["credits"],
                        "as_of": _iso(r["as_of"]), "low": r["credits"] is not None and r["credits"] < levels["reseller_low"],
                        "spent": round(spent, 2), "orders": n, "last_topup": _iso(last_topup),
                        "placeholder": str(u.get("email", "")).lower().endswith("@panel.local")})
        return {"resellers": out, "levels": levels,
                "own": {"imperium": await imperium_balance(max_age=60), "cctv": await cctv_balance(max_age=60)}}

    @router.post("/admin/alerts")
    async def admin_alerts(data: dict = Body(...), current_user: dict = Depends(admin)):
        upd = {}
        for k in DEFAULT_ALERTS:
            if k in data:
                try:
                    upd[k] = max(0.0, float(data[k]))
                except (TypeError, ValueError):
                    pass
        if upd:
            await D["db"].cmtv_config.update_one({"_id": "reseller_alerts"}, {"$set": upd}, upsert=True)
        return {"levels": await alert_levels()}

    # 2026-09-28: reseller tools (brand, unbranded guide + flyer, notices) live in cmtv_reseller_kit.py, same router
    import cmtv_reseller_kit
    cmtv_reseller_kit.init_routes(router)


@router.get("/pricing")
async def pricing():
    out = {}
    for server in ("cctv", "imperium"):
        # the pack product a custom amount is ordered through: the smallest active pack of that server
        base = None
        async for p in D["db"].products.find({"account_type": "reseller", "active": {"$ne": False}}):
            if server_of(p) == server and (base is None or float(p.get("reseller_credits") or 0) < float(base.get("reseller_credits") or 0)):
                base = p
        if not base:
            continue
        # 2026-10-01: the cap on CMTV's own balance is checked only at checkout (custom_price); this public list
        # no longer reveals the balance (it used to send max = balance, shown as "up to N credits right now")
        out[server] = {"label": LABEL[server], "product_id": str(base["_id"]), "tiers": await tiers_for(server),
                       "max": MAX_CREDITS, "available": True}
    return {"min": MIN_CREDITS, "max": MAX_CREDITS, "servers": out}
