"""PayPal auto-renew for CMTV (CMTV local addition 2026-09-25).

How it works
- A customer turns auto-renew on for a service (My Services) or ticks "Renew automatically" when paying with PayPal
  at checkout. Either way it becomes a PayPal *subscription* on a PayPal *plan* that matches the product's price and
  term (plans are created on first use and cached in `cmtv_paypal_plans`).
    * From My Services the subscription starts the day before the service expires, so nobody pays twice.
    * From checkout the first period is charged straight away and pays for that order.
- Every PayPal charge (webhook PAYMENT.SALE.COMPLETED, or the checkout approval itself) is verified with PayPal's API
  (the webhook body is never trusted) and processed once per billing cycle (unique key in `cmtv_paypal_payments`):
  the first checkout cycle marks the order paid; every other cycle creates a paid renewal order for the service and
  runs the normal provisioning (which extends the line and alerts on failure).
- Cancelled / suspended / failed-payment events update the service and alert the admin.

Subscription custom_id: "svc:<service id>" (from My Services) or "ord:<order id>" (from checkout).
"""
import logging
import time
from datetime import datetime, timedelta

import httpx
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pymongo.errors import DuplicateKeyError

logger = logging.getLogger(__name__)
# httpx logs every request URL at INFO, and Telegram URLs contain the bot token; keep only warnings and errors
logging.getLogger("httpx").setLevel(logging.WARNING)
router = APIRouter(prefix="/api/cmtv/autorenew", tags=["cmtv-autorenew"])
NETWORK_ERROR = 599   # pp_request's status when PayPal couldn't be reached
D = {}  # dependencies from server.py (see init)
SUB_EVENTS = ("BILLING.SUBSCRIPTION.",)
_token = {"value": None, "expires": 0.0}


def init(**deps):
    """Called once by server.py with its collections and helpers"""
    D.update(deps)
    db = deps["db"]
    D["plans"] = db.cmtv_paypal_plans
    D["payments"] = db.cmtv_paypal_payments


async def ensure_indexes():
    await D["payments"].create_index("key", unique=True)
    await D["plans"].create_index("key", unique=True)


def current_user_dep():
    return D["get_current_user"]


# ---------------- PayPal API ----------------

async def _pp():
    settings = await D["get_settings"]()
    pp = settings.get("paypal", {}) or {}
    if not (pp.get("enabled") and pp.get("client_id") and pp.get("secret")):
        raise HTTPException(status_code=400, detail="PayPal isn't set up")
    base = "https://api-m.paypal.com" if pp.get("mode") == "live" else "https://api-m.sandbox.paypal.com"
    if not _token["value"] or _token["expires"] < time.time() + 60:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(f"{base}/v1/oauth2/token", auth=(pp["client_id"], pp["secret"]), data={"grant_type": "client_credentials"})
        if r.status_code != 200:
            raise HTTPException(status_code=502, detail="Couldn't connect to PayPal")
        j = r.json()
        _token.update(value=j["access_token"], expires=time.time() + int(j.get("expires_in", 3000)))
    return base, {"Authorization": f"Bearer {_token['value']}", "Content-Type": "application/json"}, settings


async def pp_request(method, path, json=None, params=None):
    """(status, body). Never raises for network trouble: returns NETWORK_ERROR so callers can answer cleanly or retry."""
    try:
        base, headers, _ = await _pp()
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.request(method, f"{base}{path}", headers=headers, json=json, params=params)
    except httpx.HTTPError as e:
        logger.error(f"PayPal {method} {path}: couldn't reach PayPal ({type(e).__name__})")
        return NETWORK_ERROR, {}
    body = r.json() if r.content and r.headers.get("content-type", "").startswith("application/json") else {}
    if r.status_code >= 400:
        logger.error(f"PayPal {method} {path} -> {r.status_code}: {str(body)[:400]}")
    return r.status_code, body


# ---------------- plans ----------------

def _first_price(product):
    term, price = next(iter((product.get("prices") or {"1": 0}).items()))
    return max(1, int(term)), float(price)


def eligible(product):
    """Plans that can auto-renew: priced, not a trial, not a reseller package or bundle"""
    if not product or product.get("is_trial") or product.get("is_bundle") or product.get("account_type") == "reseller":
        return False
    term, price = _first_price(product)
    return price > 0 and 1 <= term <= 12


async def get_plan(product):
    """PayPal plan for this product's current price and term (created on first use)"""
    settings = await D["get_settings"]()
    currency = str(settings.get("currency") or "USD").upper()
    term, price = _first_price(product)
    key = f"{product['_id']}|{term}|{price:.2f}|{currency}"
    cached = await D["plans"].find_one({"key": key})
    if cached:
        return cached
    catalog = settings.get("cmtv_paypal_product_id")
    if not catalog:
        status, body = await pp_request("POST", "/v1/catalogs/products", json={
            "name": (settings.get("branding", {}) or {}).get("site_name") or "CMTV", "type": "SERVICE", "category": "SOFTWARE",
            "description": "Streaming service subscriptions"})
        if status not in (200, 201):
            raise HTTPException(status_code=502, detail="Couldn't set up auto-renew with PayPal")
        catalog = body["id"]
        await D["settings_collection"].update_one({}, {"$set": {"cmtv_paypal_product_id": catalog}})
    status, body = await pp_request("POST", "/v1/billing/plans", json={
        "product_id": catalog,
        "name": f"{product.get('name', 'Plan')}"[:127],
        "description": f"{product.get('name', 'Plan')}, renews every {term} month{'s' if term > 1 else ''}"[:127],
        "status": "ACTIVE",
        "billing_cycles": [{
            "frequency": {"interval_unit": "MONTH", "interval_count": term},
            "tenure_type": "REGULAR", "sequence": 1, "total_cycles": 0,
            "pricing_scheme": {"fixed_price": {"value": f"{price:.2f}", "currency_code": currency}},
        }],
        "payment_preferences": {"auto_bill_outstanding": True, "payment_failure_threshold": 2},
    })
    if status not in (200, 201):
        raise HTTPException(status_code=502, detail="Couldn't set up auto-renew with PayPal")
    doc = {"key": key, "plan_id": body["id"], "product_id": str(product["_id"]), "product_name": product.get("name"),
           "term_months": term, "price": price, "currency": currency, "created_at": datetime.utcnow()}
    try:
        await D["plans"].insert_one(doc)
    except DuplicateKeyError:
        doc = await D["plans"].find_one({"key": key})
    logger.info(f"PayPal plan {doc['plan_id']} for {product.get('name')} ({term} mo, {price:.2f} {currency})")
    return doc


# ---------------- helpers ----------------

def _oid(v):
    return ObjectId(v) if ObjectId.is_valid(str(v)) else None


def _to_dt(v):
    if isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v).replace("Z", "").split(".")[0])
    except ValueError:
        return None


async def _notify_admin(text, kind="critical"):
    """Telegram through the billing panel's own notification settings (always sent, not tied to an event switch).
    kind: "critical" (problems) or "billing" (routine), mapped to Ops group topics by settings.cmtv_telegram_topics."""
    try:
        settings = await D["get_settings"]()
        tg = (settings.get("notifications", {}) or {}).get("telegram", {}) or {}
        if tg.get("enabled") and tg.get("bot_token") and tg.get("chat_id"):
            msg = {"chat_id": tg["chat_id"], "text": text[:4000]}
            topic = (settings.get("cmtv_telegram_topics") or {}).get(kind)
            if topic:
                msg["message_thread_id"] = int(topic)
            async with httpx.AsyncClient(timeout=10) as c:
                await c.post(f"https://api.telegram.org/bot{tg['bot_token']}/sendMessage", json=msg)
    except Exception as e:
        logger.warning(f"auto-renew admin alert failed: {e}")


def _cycles_completed(sub):
    for ce in (sub.get("billing_info") or {}).get("cycle_executions") or []:
        if ce.get("tenure_type") == "REGULAR":
            return int(ce.get("cycles_completed") or 0)
    return 0


async def _set_service_autorenew(service_id, sub_id, status, plan):
    await D["services"].update_one({"_id": _oid(service_id)}, {"$set": {"auto_renew": {
        "provider": "paypal", "subscription_id": sub_id, "status": status, "plan_id": plan.get("plan_id") if plan else None,
        "price": plan.get("price") if plan else None, "term_months": plan.get("term_months") if plan else None,
        "currency": plan.get("currency") if plan else None, "updated_at": datetime.utcnow()}}})


async def _create_invoice(order_id, user_id, total, paid=True):
    settings = await D["get_settings"]()
    inv = settings.get("invoice", {}) or {}
    nxt = inv.get("next_number", 1001)
    number = f"{inv.get('invoice_prefix', 'INV')}-{str(nxt).zfill(inv.get('number_padding', 4))}"
    await D["settings_collection"].update_one({}, {"$set": {"invoice.next_number": nxt + 1}}, upsert=True)
    now = datetime.utcnow()
    await D["invoices"].insert_one({"order_id": order_id, "user_id": user_id, "invoice_number": number, "total": total,
                                    "status": "paid" if paid else "unpaid", "due_date": now, "paid_date": now if paid else None,
                                    "pdf_path": None, "created_at": now, "payment_method": "paypal_autorenew"})


# ---------------- payments (the heart of it) ----------------

async def process_payment(sub_id, sale_id=None):
    """Handle one PayPal charge for a subscription, verified with PayPal. Safe to call more than once per charge."""
    status, sub = await pp_request("GET", f"/v1/billing/subscriptions/{sub_id}")
    if status == NETWORK_ERROR:
        return {"ok": False, "why": "PayPal unreachable", "retry": True}
    if status != 200:
        return {"ok": False, "why": "subscription not found at PayPal"}
    plan = await D["plans"].find_one({"plan_id": sub.get("plan_id")})
    if not plan:
        logger.warning(f"auto-renew: subscription {sub_id} uses plan {sub.get('plan_id')} that billing didn't create; ignored")
        return {"ok": False, "why": "unknown plan"}
    cycle = _cycles_completed(sub)
    if cycle < 1:
        return {"ok": False, "why": "no payment yet", "pending": True}

    # Confirm the money actually arrived
    if sale_id:
        s_status, sale = await pp_request("GET", f"/v1/payments/sale/{sale_id}")
        if s_status == NETWORK_ERROR:
            return {"ok": False, "why": "PayPal unreachable", "retry": True}
        amount = ((sale.get("amount") or {}).get("total")) if s_status == 200 else None
        currency = ((sale.get("amount") or {}).get("currency")) if s_status == 200 else None
        good = s_status == 200 and str(sale.get("state", "")).lower() == "completed" and sale.get("billing_agreement_id") == sub_id
    else:
        last = (sub.get("billing_info") or {}).get("last_payment") or {}
        amount, currency = (last.get("amount") or {}).get("value"), (last.get("amount") or {}).get("currency_code")
        good = str(sub.get("status")) == "ACTIVE"
    try:
        amount = float(amount or 0)
    except (TypeError, ValueError):
        amount = 0.0
    if not good or amount + 0.01 < float(plan["price"]) or str(currency or "").upper() != plan["currency"]:
        logger.error(f"auto-renew: payment for {sub_id} (sale {sale_id}) not verified: {amount} {currency}, plan {plan['price']} {plan['currency']}")
        return {"ok": False, "why": "payment not verified"}

    # One run per billing cycle, whichever path (webhook or checkout approval) gets here first
    try:
        await D["payments"].insert_one({"key": f"{sub_id}:{cycle}", "subscription_id": sub_id, "cycle": cycle, "sale_id": sale_id,
                                        "amount": amount, "currency": currency, "created_at": datetime.utcnow()})
    except DuplicateKeyError:
        if sale_id:
            await D["payments"].update_one({"key": f"{sub_id}:{cycle}", "sale_id": None}, {"$set": {"sale_id": sale_id}})
        return {"ok": True, "duplicate": True}

    kind, _, ref = str(sub.get("custom_id") or "").partition(":")
    service = await D["services"].find_one({"auto_renew.subscription_id": sub_id})
    if not service and kind == "svc":
        service = await D["services"].find_one({"_id": _oid(ref)})

    if kind == "ord" and cycle == 1 and not service:
        return await _pay_checkout_order(ref, sub_id, sale_id, plan, amount)
    if not service and kind == "ord":
        service = await D["services"].find_one({"order_id": ref, "status": {"$ne": "failed"}})
    if not service:
        await _notify_admin(f"⚠️ PayPal auto-renew payment received but no matching service.\nSubscription {sub_id}, "
                            f"{amount:.2f} {currency}, cycle {cycle}. Check it in PayPal and extend by hand.")
        return {"ok": False, "why": "no service"}
    return await _renew_service(service, sub_id, sale_id, plan, amount, cycle)


async def _pay_checkout_order(order_id, sub_id, sale_id, plan, amount):
    order = await D["orders"].find_one({"_id": _oid(order_id)})
    items = (order or {}).get("items") or []
    if not order or len(items) != 1 or items[0].get("product_id") != plan["product_id"]:
        await _notify_admin(f"⚠️ PayPal auto-renew first payment doesn't match its order {order_id} (subscription {sub_id}). Check by hand.")
        return {"ok": False, "why": "order mismatch"}
    if order.get("status") != "paid":
        await D["orders"].update_one({"_id": order["_id"]}, {"$set": {
            "status": "paid", "paid_at": datetime.utcnow(), "payment_method": "paypal_autorenew",
            "payment_id": sale_id or f"{sub_id}:1", "paypal_subscription_id": sub_id}})
        await D["invoices"].update_one({"order_id": order_id}, {"$set": {"status": "paid", "paid_date": datetime.utcnow()}})
        user = await D["users"].find_one({"_id": _oid(order["user_id"])})
        await D["provision_order_services"](order_id, await D["orders"].find_one({"_id": order["_id"]}), user)
    # Link the subscription to the service the order created (or renewed)
    svc = None
    if items[0].get("renewal_service_id"):
        svc = await D["services"].find_one({"_id": _oid(items[0]["renewal_service_id"])})
    if not svc:
        svc = await D["services"].find_one({"order_id": order_id, "status": {"$ne": "failed"}})
    if svc:
        await _set_service_autorenew(str(svc["_id"]), sub_id, "ACTIVE", plan)
    else:
        await _notify_admin(f"⚠️ PayPal auto-renew: order {order_id} was paid but no service was created to link it to "
                            f"(subscription {sub_id}). Future renewals need checking by hand.")
    return {"ok": True, "paid_order": order_id}


async def _renew_service(service, sub_id, sale_id, plan, amount, cycle):
    product = await D["products"].find_one({"_id": _oid(plan["product_id"])})
    now = datetime.utcnow()
    order_doc = {
        "user_id": service["user_id"],
        "items": [{"product_id": plan["product_id"], "product_name": (product or {}).get("name") or plan.get("product_name"),
                   "term_months": plan["term_months"], "price": plan["price"], "account_type": service.get("account_type", "subscriber"),
                   "action_type": "extend", "renewal_service_id": str(service["_id"])}],
        "subtotal": amount, "discount_amount": 0.0, "coupon_code": None, "credits_used": 0.0, "total": amount,
        "status": "paid", "payment_method": "paypal_autorenew", "payment_id": sale_id or f"{sub_id}:{cycle}",
        "paypal_subscription_id": sub_id, "created_at": now, "paid_at": now, "auto_renewal": True,
    }
    res = await D["orders"].insert_one(order_doc)
    order_id = str(res.inserted_id)
    await _create_invoice(order_id, service["user_id"], amount)
    if (service.get("auto_renew") or {}).get("status") != "ACTIVE":
        await _set_service_autorenew(str(service["_id"]), sub_id, "ACTIVE", plan)
    user = await D["users"].find_one({"_id": _oid(service["user_id"])})
    await D["provision_order_services"](order_id, await D["orders"].find_one({"_id": res.inserted_id}), user)
    after = await D["orders"].find_one({"_id": res.inserted_id})
    if after.get("provisioning_status") == "ok":
        await _notify_admin(f"🔁 Auto-renewed with PayPal: {order_doc['items'][0]['product_name']} for "
                            f"{(user or {}).get('name', '')} <{(user or {}).get('email', '')}>, {amount:.2f} {plan['currency']}.", kind="billing")
    return {"ok": True, "renewal_order": order_id}


# ---------------- webhook ----------------

def is_subscription_event(event):
    et = str(event.get("event_type", ""))
    res = event.get("resource") or {}
    return et.startswith(SUB_EVENTS) or (et.startswith("PAYMENT.SALE.") and bool(res.get("billing_agreement_id")))


async def handle_webhook(event):
    """Runs in the background. Only ids are taken from the body; everything else is re-read from PayPal."""
    et = str(event.get("event_type", ""))
    res = event.get("resource") or {}
    try:
        if et == "PAYMENT.SALE.COMPLETED":
            import asyncio
            result = {}
            for attempt in range(5):   # a brief PayPal outage mustn't lose a renewal: ~0, 30s, 1m, 2m, 4m
                result = await process_payment(res.get("billing_agreement_id"), sale_id=res.get("id"))
                if not result.get("retry"):
                    break
                await asyncio.sleep(30 * (2 ** attempt) if attempt else 30)
            logger.info(f"auto-renew webhook {et}: {result}")
            if result.get("retry"):
                await _notify_admin(f"⚠️ PayPal auto-renew: couldn't reach PayPal to confirm payment {res.get('id')} for "
                                    f"subscription {res.get('billing_agreement_id')} after 5 tries. Check it and extend by hand.")
            return
        sub_id = res.get("id") if et.startswith("BILLING.SUBSCRIPTION.") else res.get("billing_agreement_id")
        if not sub_id:
            return
        status, sub = await pp_request("GET", f"/v1/billing/subscriptions/{sub_id}")
        if status != 200:
            return
        real = str(sub.get("status", ""))
        svc = await D["services"].find_one({"auto_renew.subscription_id": sub_id})
        if svc:
            await D["services"].update_one({"_id": svc["_id"]}, {"$set": {"auto_renew.status": real, "auto_renew.updated_at": datetime.utcnow()}})
        who = ""
        if svc:
            u = await D["users"].find_one({"_id": _oid(svc["user_id"])}) or {}
            who = f"{svc.get('product_name', '')} for {u.get('name', '')} <{u.get('email', '')}>"
        if et == "BILLING.SUBSCRIPTION.PAYMENT.FAILED" or et in ("PAYMENT.SALE.DENIED", "PAYMENT.SALE.REVERSED"):
            await _notify_admin(f"⚠️ PayPal auto-renew payment failed ({et}): {who or sub_id}. PayPal will retry; "
                                f"the customer's reminders keep going out.")
        elif real in ("CANCELLED", "SUSPENDED", "EXPIRED") and et in (
                "BILLING.SUBSCRIPTION.CANCELLED", "BILLING.SUBSCRIPTION.SUSPENDED", "BILLING.SUBSCRIPTION.EXPIRED"):
            await _notify_admin(f"ℹ️ PayPal auto-renew {real.lower()}: {who or sub_id}.", kind="billing")
        elif et == "BILLING.SUBSCRIPTION.ACTIVATED":
            kind, _, ref = str(sub.get("custom_id") or "").partition(":")
            if kind == "svc" and not svc:
                plan = await D["plans"].find_one({"plan_id": sub.get("plan_id")})
                if plan:
                    await _set_service_autorenew(ref, sub_id, real, plan)
    except Exception as e:
        logger.error(f"auto-renew webhook {et} failed: {type(e).__name__}: {e}")


# ---------------- customer endpoints ----------------

async def _own_service(service_id, user_id):
    svc = await D["services"].find_one({"_id": _oid(service_id), "user_id": user_id})
    if not svc:
        raise HTTPException(status_code=404, detail="Service not found")
    return svc


@router.get("/config")
async def config():
    s = await D["get_settings"]()
    return {"enabled": bool((s.get("paypal") or {}).get("enabled")), "currency": s.get("currency", "USD")}


async def _poll_first_payment(sub_id, tries=8, wait=40):
    """Safety net for checkout: if PayPal's webhook is slow or missing, pick up the first payment ourselves"""
    import asyncio
    for _ in range(tries):
        await asyncio.sleep(wait)
        result = await process_payment(sub_id)
        if not result.get("pending"):
            return


def init_routes():
    """Register the endpoints that need server.py's auth dependency (call after init, before include_router)"""
    get_user = D["get_current_user"]

    @router.post("/start")
    async def start_for_service(data: dict, current_user: dict = Depends(get_user)):
        """Begin auto-renew for an existing service; returns the PayPal approval link"""
        svc = await _own_service(data.get("service_id"), current_user["sub"])
        prev = svc.get("auto_renew") or {}
        if prev.get("status") in ("ACTIVE", "APPROVED"):
            raise HTTPException(status_code=400, detail="Auto-renew is already on for this service")
        if prev.get("status") == "APPROVAL_PENDING" and prev.get("subscription_id"):
            # A previous attempt wasn't finished in PayPal. If it was approved after all, keep it; otherwise start fresh.
            s_status, old = await pp_request("GET", f"/v1/billing/subscriptions/{prev['subscription_id']}")
            if s_status == 200 and old.get("status") in ("ACTIVE", "APPROVED"):
                await _set_service_autorenew(str(svc["_id"]), prev["subscription_id"], old["status"],
                                             await D["plans"].find_one({"plan_id": old.get("plan_id")}))
                raise HTTPException(status_code=400, detail="Auto-renew is already on for this service")
        if svc.get("status") not in ("active", "expired", "suspended"):
            raise HTTPException(status_code=400, detail="This service can't auto-renew")
        product = await D["products"].find_one({"_id": _oid(svc.get("product_id"))})
        if not eligible(product):
            raise HTTPException(status_code=400, detail="This plan can't auto-renew. Please renew it as usual.")
        plan = await get_plan(product)
        expiry = _to_dt(svc.get("expiry_date"))
        start_at = max(datetime.utcnow() + timedelta(minutes=15), (expiry - timedelta(days=1)) if expiry else datetime.utcnow())
        origin = str(data.get("origin") or "").rstrip("/") or "https://billing.cmtv.info"
        site = ((await D["get_settings"]()).get("branding", {}) or {}).get("site_name") or "CMTV"
        status, body = await pp_request("POST", "/v1/billing/subscriptions", json={
            "plan_id": plan["plan_id"], "custom_id": f"svc:{svc['_id']}",
            "start_time": start_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "application_context": {"brand_name": site[:127], "user_action": "SUBSCRIBE_NOW", "shipping_preference": "NO_SHIPPING",
                                    "return_url": f"{origin}/services?autorenew=return&service_id={svc['_id']}",
                                    "cancel_url": f"{origin}/services?autorenew=cancelled"},
        })
        link = next((l["href"] for l in body.get("links", []) if l.get("rel") == "approve"), None) if status in (200, 201) else None
        if not link:
            raise HTTPException(status_code=502, detail="PayPal couldn't start auto-renew. Please try again.")
        await _set_service_autorenew(str(svc["_id"]), body["id"], "APPROVAL_PENDING", plan)
        return {"approve_url": link, "first_charge": start_at.strftime("%Y-%m-%d"), "price": plan["price"], "currency": plan["currency"]}

    @router.post("/confirm")
    async def confirm(data: dict, current_user: dict = Depends(get_user)):
        """Customer is back from PayPal: record the subscription if PayPal says it's approved"""
        svc = await _own_service(data.get("service_id"), current_user["sub"])
        sub_id = data.get("subscription_id") or (svc.get("auto_renew") or {}).get("subscription_id")
        status, sub = await pp_request("GET", f"/v1/billing/subscriptions/{sub_id}") if sub_id else (404, {})
        if status != 200 or sub.get("custom_id") != f"svc:{svc['_id']}":
            raise HTTPException(status_code=400, detail="Couldn't confirm auto-renew with PayPal")
        plan = await D["plans"].find_one({"plan_id": sub.get("plan_id")})
        await _set_service_autorenew(str(svc["_id"]), sub_id, sub.get("status"), plan)
        return {"status": sub.get("status"), "next_billing": (sub.get("billing_info") or {}).get("next_billing_time") or sub.get("start_time")}

    @router.post("/cancel")
    async def cancel(data: dict, current_user: dict = Depends(get_user)):
        svc = await _own_service(data.get("service_id"), current_user["sub"])
        sub_id = (svc.get("auto_renew") or {}).get("subscription_id")
        if not sub_id:
            raise HTTPException(status_code=400, detail="Auto-renew isn't on for this service")
        status, sub = await pp_request("GET", f"/v1/billing/subscriptions/{sub_id}")
        if status == 200 and sub.get("status") in ("ACTIVE", "SUSPENDED", "APPROVED"):
            c_status, _ = await pp_request("POST", f"/v1/billing/subscriptions/{sub_id}/cancel", json={"reason": "Turned off by the customer"})
            if c_status not in (200, 204):
                raise HTTPException(status_code=502, detail="PayPal couldn't turn off auto-renew. Please try again.")
        await D["services"].update_one({"_id": svc["_id"]}, {"$set": {"auto_renew.status": "CANCELLED", "auto_renew.updated_at": datetime.utcnow()}})
        return {"status": "CANCELLED"}

    @router.post("/checkout-plan")
    async def checkout_plan(data: dict, current_user: dict = Depends(get_user)):
        """For the checkout PayPal button: the plan to subscribe to for this (pending, single-item) order"""
        order = await D["orders"].find_one({"_id": _oid(data.get("order_id")), "user_id": current_user["sub"]})
        if not order or order.get("status") != "pending" or len(order.get("items") or []) != 1:
            raise HTTPException(status_code=400, detail="This order can't be set to renew automatically")
        product = await D["products"].find_one({"_id": _oid(order["items"][0].get("product_id"))})
        if not eligible(product):
            raise HTTPException(status_code=400, detail="This plan can't renew automatically")
        plan = await get_plan(product)
        if abs(float(order.get("total") or 0) - plan["price"]) > 0.009:
            raise HTTPException(status_code=400, detail="Auto-renew isn't available with a coupon or credits")
        return {"plan_id": plan["plan_id"], "custom_id": f"ord:{order['_id']}"}

    @router.post("/checkout-approved")
    async def checkout_approved(data: dict, background_tasks: BackgroundTasks, current_user: dict = Depends(get_user)):
        """Customer approved the subscription at checkout. Pays the order as soon as PayPal shows the first payment."""
        order = await D["orders"].find_one({"_id": _oid(data.get("order_id")), "user_id": current_user["sub"]})
        sub_id = data.get("subscription_id")
        if not order or not sub_id:
            raise HTTPException(status_code=404, detail="Order not found")
        status, sub = await pp_request("GET", f"/v1/billing/subscriptions/{sub_id}")
        if status != 200 or sub.get("custom_id") != f"ord:{order['_id']}":
            raise HTTPException(status_code=400, detail="This PayPal subscription doesn't match the order")
        await D["orders"].update_one({"_id": order["_id"]}, {"$set": {"paypal_subscription_id": sub_id}})
        if _cycles_completed(sub) >= 1:
            background_tasks.add_task(process_payment, sub_id)
            return {"status": "paid"}
        background_tasks.add_task(_poll_first_payment, sub_id)   # the PAYMENT.SALE.COMPLETED webhook normally wins
        return {"status": "processing"}
