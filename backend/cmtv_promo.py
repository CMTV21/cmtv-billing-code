"""Holiday bonus months (CMTV local addition 2026-10-05, the owner's Black Friday pick: "buy a 12-month plan, get 3 months
free" instead of last year's 15% off). Set in Admin > Notices "Holiday bonus months": on/off, first and last day (Toronto),
number of months, the name customers see. It only runs between those days, so it switches itself on and off.
- create_order stamps `bonus_months` on each 12-month CCTV / Imperium subscriber item (new line, renewal or extension; not
  trials, not "add devices", not add-ons) ordered while it runs; anything a browser sends is overwritten. An order placed
  during the sale keeps its bonus even if it's paid (e-Transfer) after the sale ends.
- provision_order_services, after the item's own provisioning: apply_bonus extends THE SAME line with the panel's own
  3-month package for that server + device count (same path as a renewal, line-up kept), once per order item
  (orders.cmtv_bonus_done). If the main item failed, nothing is added. If the bonus fails (e.g. low panel credits), the
  12 months stay and the order is flagged "Holiday bonus +3 months: ..." with the usual alert, so it's added by hand.
- The customer gets a short branded "Your 3 bonus months are on" email. The ledger counts the bonus credits (cmtv_finance).
Config: cmtv_config {_id: "promo"}: enabled, start, end (YYYY-MM-DD), months, label.
"""
import html
import logging
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Body, Depends, HTTPException

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/cmtv/promo", tags=["cmtv-promo"])
D = {}
TZ = ZoneInfo("America/Toronto")
TV = ("aether", "xtream")
DEFAULT = {"enabled": False, "start": None, "end": None, "months": 3, "label": "Black Friday",
           "plus_price": 45}   # 2026-10-05: CMTV+ price with a yearly TV plan during the sale (0 = no CMTV+ offer)


def init(**deps):
    D.update(deps)


async def config():
    doc = await D["db"].cmtv_config.find_one({"_id": "promo"}) or {}
    return {k: doc.get(k, v) for k, v in DEFAULT.items()}


def _day(s, end=False):
    d = datetime.strptime(s, "%Y-%m-%d").date()
    return datetime.combine(d, time(23, 59, 59) if end else time(0, 0), tzinfo=TZ)


def state(cfg, now=None):
    """{"active", "status": off | scheduled | running | ended, "months", "label", "start", "end"}"""
    now = (now or datetime.now(TZ)).astimezone(TZ)
    st = "off"
    if cfg.get("enabled") and cfg.get("start") and cfg.get("end"):
        st = "scheduled" if now < _day(cfg["start"]) else "ended" if now > _day(cfg["end"], True) else "running"
    return {"active": st == "running", "status": st, "months": int(cfg.get("months") or 3), "label": cfg.get("label") or "",
            "start": cfg.get("start"), "end": cfg.get("end"), "plus_price": float(cfg.get("plus_price") or 0)}


def _term(product):
    prices = (product or {}).get("prices") or {}
    return int(next(iter(prices), 0) or 0)


def eligible(product, item):
    return bool(product) and product.get("panel_type") in TV and product.get("account_type", "subscriber") == "subscriber" \
        and not product.get("is_trial") and _term(product) == 12 and getattr(item, "action_type", None) != "upgrade" \
        and getattr(item, "item_type", "service") != "physical"


async def bonus_for(product, item, now=None):
    """Months to stamp on this order item (0 = none)."""
    st = state(await config(), now)
    return st["months"] if st["active"] and eligible(product, item) else 0


async def plus_offer(items, now=None):
    """CMTV+ at the holiday price in an order that has a yearly TV plan during the sale (one per yearly plan). Changes the
    items' price and name; returns how much to take off the order's total. Call after bonus_months is stamped."""
    st = state(await config(), now)
    price = st["plus_price"]
    yearly = sum(1 for i in items if int(getattr(i, "bonus_months", 0) or 0) > 0)
    if not st["active"] or price <= 0 or not yearly:
        return 0.0
    plus_ids = {str(p["_id"]) async for p in D["db"].products.find({"cmtv_plus": True}, {"_id": 1})}
    off = 0.0
    for i in items:
        if yearly and str(getattr(i, "product_id", "")) in plus_ids and not getattr(i, "gift", None) \
                and float(getattr(i, "price", 0) or 0) > price:
            off += float(i.price) - price
            i.price = price
            i.product_name = f"{i.product_name} · {st['label'] or 'holiday'} price"
            yearly -= 1
    return round(off, 2)


# ---------- provisioning ----------

class _NoEmail:
    """Stands in for the email service during the bonus extension (no "service renewed" email; we send our own)."""
    def __getattr__(self, name):
        async def _noop(*a, **k):
            return True
        return _noop


async def _target_service(order_id, order, item, product):
    """The line the item just made or renewed, or None if that didn't work. A line that got its 12 months now runs at least
    11 months out (CCTV renewals don't stamp updated_at, so the end date is the proof)."""
    svcs = D["db"].services
    far = {"$gte": datetime.utcnow() + timedelta(days=330)}
    rid = item.get("renewal_service_id")
    if rid and item.get("action_type") in ("renew", "extend"):
        from bson import ObjectId
        if not ObjectId.is_valid(str(rid)):
            return None
        return await svcs.find_one({"_id": ObjectId(str(rid)), "user_id": order["user_id"], "expiry_date": far})
    # a new line: made by this order on this server (the line-up can swap the product), not already given this bonus
    return await svcs.find_one({"order_id": order_id, "user_id": order["user_id"], "panel_type": product.get("panel_type"),
                                "status": {"$nin": ["failed"]}, "expiry_date": far, "cmtv_bonus.order_id": {"$ne": order_id}},
                               sort=[("created_at", -1)])


async def apply_bonus(order_id, order, user, item, product, settings, run_item, provisioners, lineups=None):
    months = int(item.get("bonus_months") or 0)
    if months <= 0:
        return
    idx = next((k for k, x in enumerate(order.get("items") or []) if x is item), None)
    db = D["db"]
    if idx is not None and await db.orders.find_one({"_id": _oid(order_id), "cmtv_bonus_done": idx}, {"_id": 1}):
        return
    svc = await _target_service(order_id, order, item, product)
    if not svc:
        logger.warning(f"Holiday bonus for order {order_id}: the line itself wasn't set up, so no bonus yet")
        return
    conns = int(product.get("max_connections") or svc.get("max_connections") or 0)
    bp = await db.products.find_one({"panel_type": product.get("panel_type"), "account_type": "subscriber",
                                     "is_trial": {"$ne": True}, "max_connections": conns, f"prices.{months}": {"$exists": True}})
    label = f"Holiday bonus +{months} months"
    if not bp:
        await run_item(label, item, _fail(f"no {months}-month {product.get('panel_type')} package for {conns} devices"))
        return
    bitem = {**item, "product_id": str(bp["_id"]), "product_name": bp.get("name"), "term_months": months, "price": 0,
             "action_type": "extend", "renewal_service_id": str(svc["_id"]), "bouquets": None, "bonus_months": 0}
    if lineups:
        bp = await lineups(bp, bitem)
    fn = provisioners.get(bp.get("panel_type"))
    before = svc.get("expiry_date")
    await run_item(label, bitem, fn(order_id, order, user, bitem, bp, settings, _NoEmail()))
    after = await db.services.find_one({"_id": svc["_id"]})
    if not after or after.get("expiry_date") == before:
        return   # run_item has recorded the failure (order flagged + alert)
    await db.orders.update_one({"_id": _oid(order_id)}, {"$addToSet": {"cmtv_bonus_done": idx if idx is not None else -1}})
    await db.services.update_one({"_id": svc["_id"]}, {"$push": {"cmtv_bonus": {"order_id": order_id, "months": months,
                                                                                "at": datetime.utcnow()}}})
    logger.info(f"Holiday bonus: order {order_id} line {svc.get('username')} +{months} months -> {after.get('expiry_date')}")
    await _email(user, after, months)


async def _fail(why):
    raise RuntimeError(why)


def _oid(x):
    from bson import ObjectId
    return ObjectId(str(x)) if ObjectId.is_valid(str(x)) else x


async def _email(user, svc, months):
    if not (user or {}).get("email"):
        return
    try:
        from cmtv_gifts import _shell, _button, P, FONT, SITE
        cfg = await config()
        exp = svc.get("expiry_date")
        until = f"{exp.strftime('%B')} {exp.day}, {exp.year}" if exp else ""
        name = html.escape((user.get("name") or "").split(" ")[0] or "there")
        plan = html.escape(svc.get("product_name") or "plan")
        tag = html.escape(cfg.get("label") or "Holiday")
        subject = f"Your {months} bonus months are on"
        body = (f'<p style="{P}">Hi {name},</p>'
                f'<p style="margin:0 0 24px; font-size:15px; line-height:1.6; color:#374151; {FONT}">Thanks for choosing a yearly plan! '
                f'As part of our {tag} offer we\'ve added <strong style="color:#0a0e1a;">{months} free months</strong> to your '
                f'{plan}. Same login, nothing to do: it now runs until <strong style="color:#0a0e1a;">{until}</strong>.</p>'
                + _button(f"{SITE}/dashboard", "See it on my dashboard"))
        es = await D["get_email_service"]()
        await es.send_email(to_email=user["email"], subject=subject, html_content=es._wrap_email(
            _shell(f"{months} free months added: your plan now runs until {until}.", f"{months} bonus months added &#127881;", body),
            subject, user["email"], "transactional"), email_type="transactional", recipient_name=user.get("name", ""))
    except Exception as e:
        logger.warning(f"Holiday bonus email failed: {e}")


# ---------- routes ----------

def init_routes():
    admin = D["get_current_admin_user"]

    @router.get("")
    async def public():
        st = state(await config())
        if not st["active"]:
            return {"active": False, "status": "off"}
        plus = await D["db"].products.find_one({"cmtv_plus": True, "active": True}, {"_id": 1, "prices": 1})
        return {**st, "plus_product_id": str(plus["_id"]) if plus and st["plus_price"] > 0 else None,
                "plus_list_price": float(next(iter((plus or {}).get("prices", {}).values()), 0) or 0)}

    @router.get("/admin")
    async def admin_get(current_user: dict = Depends(admin)):
        cfg = await config()
        n = await D["db"].orders.count_documents({"items.bonus_months": {"$gt": 0}})
        done = await D["db"].orders.count_documents({"cmtv_bonus_done.0": {"$exists": True}})
        return {**cfg, **state(cfg), "orders_with_bonus": n, "bonus_added": done}

    @router.post("/admin")
    async def admin_set(data: dict = Body(...), current_user: dict = Depends(admin)):
        cfg = await config()
        for k in ("start", "end"):
            if k in data:
                v = data.get(k) or None
                if v:
                    try:
                        datetime.strptime(v, "%Y-%m-%d")
                    except ValueError:
                        raise HTTPException(400, "Pick the dates again.")
                cfg[k] = v
        if "months" in data:
            m = int(data.get("months") or 0)
            if not 1 <= m <= 12:
                raise HTTPException(400, "Bonus months: 1 to 12.")
            cfg["months"] = m
        if "plus_price" in data:
            try:
                pp = round(float(data.get("plus_price") or 0), 2)
            except (TypeError, ValueError):
                raise HTTPException(400, "CMTV+ price: a number, or 0 for no CMTV+ offer.")
            if not 0 <= pp <= 500:
                raise HTTPException(400, "CMTV+ price: 0 to 500.")
            cfg["plus_price"] = pp
        if "label" in data:
            cfg["label"] = " ".join(str(data.get("label") or "").split())[:40] or "Holiday"
        if "enabled" in data:
            cfg["enabled"] = bool(data["enabled"])
        if cfg["enabled"] and not (cfg.get("start") and cfg.get("end")):
            raise HTTPException(400, "Pick the first and last day before switching it on.")
        if cfg.get("start") and cfg.get("end") and cfg["start"] > cfg["end"]:
            raise HTTPException(400, "The last day must be on or after the first day.")
        await D["db"].cmtv_config.update_one({"_id": "promo"}, {"$set": {**cfg, "updated_at": datetime.utcnow(),
                                                                         "updated_by": current_user.get("sub")}}, upsert=True)
        return {**cfg, **state(cfg)}
