"""Partner services sold through billing (CMTV local addition 2026-10-15, owner: "process the purchase through our billing panel").

First one: the branded Ghost app for resellers. The app itself is made on Ghost's own reseller panel (ghostapk.io/reseller):
the reseller signs up there with CMTV's referral link, choosing manual payment, and the owner approves their panel (one
setup credit). Billing only takes the one-time setup fee; the monthly fee is paid by the reseller to Ghost directly.

A partner product = a manual product with `cmtv_partner` set (e.g. "ghostapp") and account_type "reseller", so only
approved resellers can buy it (create_order's reseller check) and checkout shows no extend / new-line / auto-renew options.
When the order is paid, provision_order_services calls handle() instead of the plain manual-product branch:
- NO service record (it's a one-time setup, nothing to renew) and NOT the "Your Streaming Service is Ready" email
  (it would show "Username N/A, 0 devices");
- one branded email to the customer with the product's setup_instructions (the next steps, incl. the sign-up link);
- one Ops (Billing) note telling the owner to approve the panel once they've signed up.
The Finances ledger files it under server "Ghost app" (cmtv_finance._server_for); its cost comes from the credits table /
cost per credit for that server (1 setup credit per sale, product reseller_credits = 1).
"""
import html
import logging
import re

log = logging.getLogger("cmtv_partner")

LABELS = {"ghostapp": "Branded Ghost app"}


def is_partner(product: dict) -> bool:
    return bool((product or {}).get("cmtv_partner"))


def _steps_html(text: str) -> str:
    """setup_instructions (plain text, one step per line) -> safe HTML with clickable links."""
    from cmtv_gifts import FONT
    out = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        safe = html.escape(line)
        safe = re.sub(r"(https://[^\s<]+)", r'<a href="\1" style="color:#2563eb;">\1</a>', safe)
        out.append(f'<p style="margin:0 0 10px; font-size:15px; line-height:1.6; color:#374151; {FONT}">{safe}</p>')
    return "".join(out)


async def handle(order_id: str, order: dict, user: dict, item: dict, product: dict, email_service) -> None:
    """A paid partner-service item: email the next steps to the customer and tell the owner. Never raises."""
    label = LABELS.get(str(product.get("cmtv_partner")), product.get("name") or "Partner service")
    ref = str(order_id)[:10].upper()
    who = f"{user.get('name') or '(no name)'} ({user.get('email') or '?'})"
    log.info(f"Partner service paid: {label} for {user.get('email')} (order {order_id})")
    # 1. the customer: next steps
    email = (user or {}).get("email") or ""
    if email_service and email and not email.endswith("@panel.local"):
        try:
            from cmtv_gifts import _shell, _button, P, FONT, SITE
            name = html.escape((user.get("name") or "").split(" ")[0] or "there")
            subject = f"Your {label} setup: next steps"
            body = (f'<p style="{P}">Hi {name},</p>'
                    f'<p style="margin:0 0 20px; font-size:15px; line-height:1.6; color:#374151; {FONT}">Thanks! We\'ve received '
                    f'your payment for the <strong style="color:#0a0e1a;">{html.escape(label)}</strong> setup '
                    f'(order {html.escape(ref)}). Here\'s what happens next:</p>'
                    + _steps_html(product.get("setup_instructions") or "")
                    + _button(f"{SITE}/tickets", "Questions? Open a ticket"))
            await email_service.send_email(
                to_email=email, subject=subject,
                html_content=email_service._wrap_email(_shell(f"Payment received for your {label} setup. Next steps inside.",
                                                              f"{html.escape(label)}: next steps", body),
                                                       subject, email, "transactional"),
                email_type="transactional", order_id=order_id, recipient_name=user.get("name", ""))
        except Exception as e:
            log.warning(f"Partner service email failed for order {order_id}: {e}")
    # 2. the owner
    try:
        import cmtv_notify
        await cmtv_notify.ops(
            f"🛠 <b>{html.escape(label)} setup paid</b>\n{html.escape(who)}\nOrder {html.escape(ref)}, "
            f"${float(order.get('total') or 0):.2f}\n\nNext: once they've signed up on ghostapk.io with your referral link "
            "(manual payment), approve their panel there (1 setup credit).", kind="billing")
    except Exception as e:
        log.warning(f"Partner service Ops note failed for order {order_id}: {e}")
