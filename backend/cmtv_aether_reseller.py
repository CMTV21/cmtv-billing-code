"""Imperium (Aether, bestpanel.xyz) reseller packs -> sub-resellers (CMTV local addition 2026-09-27).

The developer's provision_aether_service only creates subscriber lines ("only subscriber lines can be provisioned via
the API"), so a paid Imperium reseller pack was never set up. Our Aether account can now create sub-resellers (the
provider enabled subresellers.create; the billing token needs the subresellers:create scope). Aether API (reseller):
  POST /api/v1/reseller/subresellers     {username, password, initial_grant}  -> {user_id}   (Idempotency-Key required)
  POST /api/v1/reseller/credits/transfer {to_user_id, amount}                                 (Idempotency-Key required)
  GET  /api/v1/reseller/subresellers?search=  -> {items: [{id, username, credits_balance, ...}], limits}
Amounts are decimal strings; initial_grant / transfer come out of CMTV's own Imperium credit balance (min 50 each);
password needs 8+ characters incl. one capital letter.

New pack: creates the sub-reseller with the username/password the customer picked at checkout (a password that doesn't
meet the panel's rules is replaced by a generated one, which the email shows), saves a service (panel_type aether,
account_type reseller) for the order and sends the reseller_activated email. "Add credits to my existing panel": transfers
the credits to the customer's own sub-reseller (it must be a billing service of theirs), bumps the service and sends a
short email. The same idempotency key per order/item means a retry never creates or pays twice.
"""
import logging
import secrets
import string
from datetime import datetime

from aether_service import AetherError

logger = logging.getLogger("server")


def _password_ok(p: str) -> bool:
    return len(p) >= 8 and any(c.isupper() for c in p)


def _new_password() -> str:
    alphabet = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789"
    while True:
        p = "".join(secrets.choice(alphabet) for _ in range(12))
        if any(c.isupper() for c in p) and any(c.isdigit() for c in p):
            return p


def _amount(credits) -> str:
    return f"{float(credits):g}"


async def _find_sub(ae, base: str, username: str):
    page = 1
    while True:
        data = await ae._request("GET", f"{base}/subresellers", params={"search": username, "page": page, "per_page": 50})
        for it in data.get("items") or []:
            if str(it.get("username", "")).lower() == username.lower():
                return it
        if page * 50 >= int(data.get("total") or 0):
            return None
        page += 1


async def _enough_credits(ae, credits: float) -> bool:
    balance = await ae.get_balance()
    if balance is not None and balance < credits:
        logger.error(f"Imperium reseller: CMTV's Imperium account has {balance:g} credits, {credits:g} needed. "
                     f"Top up the CMTV account on the Imperium panel, then re-run provisioning for this order")
        return False
    return True


async def provision(*, ae, order_id: str, order: dict, user: dict, item: dict, product: dict, panel_index: int,
                    panel_name: str, services, email_service, generate_username):
    credits = float(product.get("reseller_credits") or 0)
    if credits <= 0:
        logger.error(f"Imperium reseller: product '{product.get('name')}' has no reseller_credits")
        return
    creds = order.get("reseller_credentials") or {}
    username = str(creds.get("username") or "").strip()
    password = str(creds.get("password") or "")
    panel_url = product.get("custom_panel_url") or "https://bestpanel.xyz"
    try:
        base = await ae._base()

        if creds.get("add_credits_to_existing"):
            query = {"user_id": order["user_id"], "panel_type": "aether", "account_type": "reseller", "status": "active"}
            if username:
                query["username"] = username
            existing = await services.find_one(query)
            if not existing:
                logger.error(f"Imperium reseller top-up: this customer has no Imperium reseller panel "
                             f"{'named ' + repr(username) + ' ' if username else ''}in billing. Add the credits by hand")
                return
            sub = await _find_sub(ae, base, existing["username"])
            if not sub:
                logger.error(f"Imperium reseller top-up: sub-reseller {existing['username']} not found on the Imperium panel")
                return
            if not await _enough_credits(ae, credits):
                return
            await ae._request("POST", f"{base}/credits/transfer",
                              json_data={"to_user_id": int(sub["id"]), "amount": _amount(credits)},
                              idem_key=f"cmtv-{order_id}-{item.get('product_id', '')}-topup")
            now = datetime.utcnow()
            await services.update_one({"_id": existing["_id"]}, {
                "$inc": {"reseller_credits": credits},
                "$set": {"updated_at": now},
                "$push": {"cmtv_credit_topups": {"order_id": order_id, "credits": credits, "at": now}},
            })
            # lets provision_order_services' outcome check see which service this item changed
            item["renewal_service_id"] = str(existing["_id"])
            logger.info(f"Imperium reseller top-up: {credits:g} credits -> {existing['username']}")
            if email_service:
                try:   # 2026-10-01: the same CMTV-branded "credits added" email as CCTV top-ups (DB template credits_added)
                    if await email_service.send_credits_added(customer_email=user["email"], customer_name=user.get("name", ""),
                                                              username=existing["username"], credits=f"{credits:g}",
                                                              customer_id=order["user_id"]):
                        return
                except Exception as e:
                    logger.warning(f"Imperium reseller top-up email (template) failed: {e}")
                try:
                    body = (f"<h2>Credits added</h2><p>Hi {user.get('name', '')},</p>"
                            f"<p><strong>{credits:g} credits</strong> have been added to your Imperium reseller panel "
                            f"<strong>{existing['username']}</strong>.</p><p>Panel: <a href=\"{panel_url}\">{panel_url}</a></p>")
                    await email_service.send_email(
                        to_email=user["email"], subject=f"{credits:g} credits added to your reseller panel",
                        html_content=email_service._wrap_email(body, "Credits added", user["email"], "transactional"),
                        email_type="transactional", customer_id=order["user_id"])
                except Exception as e:
                    logger.warning(f"Imperium reseller top-up email failed: {e}")
            return

        if credits < 50:
            logger.error(f"Imperium reseller: {credits:g} credits is below the panel's minimum opening credit (50)")
            return
        if not username:
            username = generate_username()
        generated_password = not _password_ok(password)
        if generated_password:
            password = _new_password()
        if not await _enough_credits(ae, credits):
            return
        res = await ae._request("POST", f"{base}/subresellers",
                                json_data={"username": username, "password": password, "initial_grant": _amount(credits)},
                                idem_key=f"cmtv-{order_id}-{item.get('product_id', '')}-subreseller")
        now = datetime.utcnow()
        await services.insert_one({
            "user_id": order["user_id"], "order_id": order_id,
            "product_id": item.get("product_id"), "product_name": item.get("product_name") or product.get("name"),
            "account_type": "reseller", "panel_type": "aether", "panel_index": panel_index, "panel_name": panel_name,
            "username": username, "password": password, "xtream_username": username, "xtream_password": password,
            "panel_user_id": res.get("user_id"), "reseller_credits": credits, "panel_url": panel_url,
            "status": "active", "start_date": now, "created_at": now,
            "cmtv_note": "Imperium sub-reseller (cmtv_aether_reseller.py)",
        })
        logger.info(f"Imperium sub-reseller created: {username} (panel user {res.get('user_id')}) with {credits:g} credits")
        if email_service:
            try:
                await email_service.send_reseller_activated(
                    customer_email=user["email"], customer_name=user.get("name", "Customer"),
                    service_name=item.get("product_name") or product.get("name"), username=username, password=password,
                    panel_url=panel_url, credits=int(credits), expiry_date="No expiry", customer_id=order["user_id"])
            except Exception as e:
                logger.warning(f"Imperium reseller email failed: {e}")
    except AetherError as e:
        logger.error(f"Imperium reseller: the panel refused [{e.code}]: {e.message}")
