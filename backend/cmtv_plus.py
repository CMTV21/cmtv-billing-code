"""CMTV+ automatic setup (CMTV local addition 2026-10-05; before this CMTV+ was set up by hand).
CMTV+ = Nuvio (or Stremio, the customer's pick) + CMTVpn + CMTV Audiobooks for one yearly price. The CMTV+ product is
marked `cmtv_plus: True`. Buying OR renewing CMTV+ makes sure the customer has all three, each with the plan's months:
- a part the customer already has (paid, trial or ended, same login) is EXTENDED: no second account;
- a missing part is CREATED (login email as usual).
Each part runs through the normal provision_cockpit_service (Cockpit / CMTV Nuvio server / abadmin), so failures are
reported per part ("CMTV+: CMTVpn: ...") and the order shows Not provisioned / partial like any other.
The part services get `cmtv_plus: True` (+ product = the paid part, is_trial False), so the dashboard shows them as
"Part of CMTV+" and their Renew button renews CMTV+ (all three) instead of each part at its own price.
Stremio instead of Nuvio: the cart item says "Stremio" (checkout drop-down: "CMTV+ (with Stremio)"), or on a renewal the
customer's CMTV+ already has Stremio and no Nuvio.
"""
import logging
import re
from datetime import datetime

from bson import ObjectId

logger = logging.getLogger(__name__)
D = {}
PARTS = ["nuviocloud", "vpn", "audiobooks"]
STREMIO = "nuvio"   # Cockpit's Nuvio module is the classic Stremio add-on
NAMES = {"nuviocloud": "Nuvio", "nuvio": "Stremio", "vpn": "CMTVpn", "audiobooks": "CMTV Audiobooks"}
GONE = ["deleted", "cancelled", "terminated", "failed", "removed"]


def init(**deps):
    D.update(deps)
    if "cockpit" not in D:   # the add-on connector (Cockpit / CMTV Nuvio server / abadmin), to check a login still exists
        import cockpit_service
        D["cockpit"] = cockpit_service


async def part_product(module):
    """The paid yearly product for a part (not a trial, not a reseller pack)."""
    best = None
    async for p in D["db"].products.find({"cockpit_module": module, "is_trial": {"$ne": True},
                                         "account_type": {"$ne": "reseller"}, "cmtv_gift": {"$ne": True}}):
        if (p.get("prices") or {}).get("12") is None:
            continue
        if best is None or (p.get("active") and not best.get("active")):
            best = p
    return best


async def existing(user_id, module):
    """The customer's own account for this part (same login gets extended), newest expiry first. 2026-10-05 (owner's test:
    a billing Audiobooks service whose account was gone from the server): each candidate is looked up on its server first;
    one that no longer exists there is retired (status "removed", kept) and the next is tried, so a fresh account gets made.
    If the server can't be reached the candidate is kept: extending then fails and is reported (never a duplicate)."""
    cur = D["db"].services.find(
        {"user_id": user_id, "cockpit_module": module, "username": {"$nin": [None, ""]}, "status": {"$nin": GONE}},
        sort=[("cmtv_plus", -1), ("expiry_date", -1)])
    async for svc in cur:
        if D.get("cockpit"):
            try:
                r = await D["cockpit"]._call({"module": module, "action": "get", "username": svc["username"]})
            except Exception as e:
                r = {"success": False, "error": str(e)}
            if r.get("success") and not r.get("exists"):
                await D["db"].services.update_one({"_id": svc["_id"]}, {"$set": {
                    "status": "removed", "cmtv_removed_at": datetime.utcnow(), "cmtv_status_before": svc.get("status"),
                    "cmtv_removed_reason": "the account no longer exists on its server (found during CMTV+ setup)"}})
                logger.info(f"CMTV+: {module} login {svc['username']} no longer exists, retired its service; trying the next")
                continue
        return svc
    return None


async def wants_stremio(user_id, item):
    if "stremio" in str(item.get("product_name") or "").lower():
        return True
    has = lambda m: D["db"].services.find_one({"user_id": user_id, "cockpit_module": m, "cmtv_plus": True,
                                               "status": {"$nin": GONE}}, {"_id": 1})
    return bool(await has(STREMIO)) and not await has("nuviocloud")


async def plan(user_id, item):
    """[(module, part product, existing service or None)] for this CMTV+ item. Missing products -> part product None."""
    modules = [STREMIO if m == "nuviocloud" and await wants_stremio(user_id, item) else m for m in PARTS]
    return [(m, await part_product(m), await existing(user_id, m)) for m in modules]


async def provision(order_id, order, user, item, settings, email_service, run_item, provision_cockpit_service):
    """Called from provision_order_services for a CMTV+ item (product.cmtv_plus). The parts' own emails are switched off
    (email_service=None) and ONE "Welcome to CMTV+" / "CMTV+ renewed" email lists all three (2026-10-05, owner's request)."""
    uid = order["user_id"]
    months = max(1, int(item.get("term_months") or 12))
    bundle_id = str(item.get("product_id") or "")
    results = []   # (name, product, service doc or None, "new" | "extended" | "pending", was already CMTV+)
    for module, product, svc in await plan(uid, item):
        name = NAMES.get(module, module)
        if not product:
            await run_item(f"CMTV+: {name}", {**item, "renewal_service_id": None},
                           _fail(f"no paid {name} product with a 12-month price (Admin > Products)"))
            results.append((name, None, None, "pending", False))
            continue
        name = product.get("name") or name
        part = {"product_id": str(product["_id"]), "product_name": name, "term_months": months,
                "price": 0, "account_type": "subscriber",
                "action_type": "extend" if svc else "create_new", "renewal_service_id": str(svc["_id"]) if svc else None}
        before = datetime.utcnow()
        await run_item(f"CMTV+: {name}", part,
                       provision_cockpit_service(order_id, order, user, part, product, settings, None))
        # tag the part only if it worked: the extended one (renewal sets updated_at) or the one just created for this order
        q = {"_id": svc["_id"], "updated_at": {"$gte": before}} if svc else \
            {"user_id": uid, "order_id": order_id, "cockpit_module": module, "created_at": {"$gte": before}}
        done = await D["db"].services.find_one_and_update(q, {"$set": {
            "cmtv_plus": True, "cmtv_plus_product_id": bundle_id, "cmtv_plus_order_id": order_id,
            "product_id": str(product["_id"]), "product_name": name, "is_trial": False}}, return_document=True)
        state = "pending" if not done else "extended" if svc else "new"
        results.append((name, product, done, state, bool(svc and svc.get("cmtv_plus"))))
        logger.info(f"CMTV+ order {order_id}: {name} {state}")
    if email_service and user.get("email"):
        try:
            subject, body = welcome_email(user, results)
            await email_service.send_email(to_email=user["email"], subject=subject,
                                           html_content=email_service._wrap_email(body, subject, user["email"], "transactional"),
                                           email_type="transactional", order_id=order_id, customer_id=uid,
                                           recipient_name=user.get("name", ""))
        except Exception as e:
            logger.warning(f"CMTV+ welcome email failed for order {order_id}: {e}")


def _date(d):
    return f"{d.strftime('%B')} {d.day}, {d.year}" if d else ""


def welcome_email(user, results):
    """(subject, html) for one CMTV+ order: every part with its login, the date it runs to, and how to set it up."""
    import html
    from cmtv_gifts import _shell, _section, _button, P, FONT, STRIP, SITE   # CMTV's branded email pieces
    renewal = all(state == "extended" and was for _, _, _, state, was in results)
    ok = [r for r in results if r[3] != "pending"]
    ends = min((r[2].get("expiry_date") for r in ok if r[2].get("expiry_date")), default=None)
    first = html.escape((user.get("name") or "").split(" ")[0] or "there")
    if renewal:
        heading, subject = "Your CMTV+ is renewed &#127881;", f"Your CMTV+ is renewed until {_date(ends)}"
        intro = f"Thanks for renewing! All three parts of CMTV+ keep the same logins and now run until at least <strong style=\"color:#0a0e1a;\">{_date(ends)}</strong>."
    else:
        heading, subject = "Welcome to CMTV+ &#127881;", "Welcome to CMTV+: your logins are inside"
        intro = ("Your CMTV+ is ready: movies &amp; series, a private VPN and audiobooks, all for one yearly price. "
                 "Here's everything you need for each one.")
    row = lambda k, v, mono=False: (
        f'<tr><td style="padding:9px 0; font-size:13px; color:#8b96b3; border-bottom:1px solid #1d2740; width:38%; {FONT}">{k}</td>'
        f'<td style="padding:9px 0; font-size:14px; color:#ffffff; border-bottom:1px solid #1d2740; font-weight:bold; '
        f'{"font-family:Consolas, Menlo, monospace; letter-spacing:1px;" if mono else FONT}">{v}</td></tr>')
    parts = ""
    for name, product, svc, state, _ in results:
        n = html.escape(name)
        if state == "pending":
            parts += (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border:1px dashed #cbd5e1; border-radius:10px; margin:0 0 18px;">'
                      f'<tr><td style="padding:16px 20px; font-size:15px; color:#374151; {FONT}"><strong style="color:#0a0e1a;">{n}</strong>: '
                      "we're finishing setting this one up. You'll get its login by email shortly.</td></tr></table>")
            continue
        tag = "Same login as before, extended" if state == "extended" else "New login"
        steps = html.escape((product or {}).get("setup_instructions") or "").strip().replace("\n", "<br>")
        steps = re.sub(r"(https?://[^\s<]+[^\s<.,;:!?)])", r'<a href="\1" style="color:#00d4ff;">\1</a>', steps)   # 2026-10-05: app links
        parts += f"""
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#0a0e1a; border-radius:10px; margin:0 0 18px; overflow:hidden;">
  <tr><td>{STRIP}</td></tr>
  <tr><td style="padding:18px 22px 20px;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
      <td style="font-size:18px; font-weight:bold; color:#ffffff; {FONT}">{n}</td>
      <td align="right" style="font-size:12px; color:#00d4ff; {FONT}">{tag}</td></tr></table>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-top:8px;">
      {row("Username", html.escape(svc.get("username") or ""), True)}{row("Password", html.escape(svc.get("password") or ""), True)}
      {row("Active until", _date(svc.get("expiry_date")))}
    </table>
    {f'<div style="margin-top:12px; font-size:13px; line-height:1.6; color:#c7d2ee; {FONT}"><span style="color:#8b96b3;">How to set it up</span><br>{steps}</div>' if steps else ''}
  </td></tr>
</table>"""
    body = (f'<p style="{P}">Hi {first},</p><p style="margin:0 0 24px; font-size:15px; line-height:1.6; color:#374151; {FONT}">{intro}</p>'
            + _section("Your CMTV+ logins") + '<p style="margin:0 0 14px; font-size:12px; line-height:1.5; color:#9ca3af;">'
            "Keep these details safe and don't share them.</p>" + parts
            + _button(f"{SITE}/dashboard", "Open my dashboard")
            + f'<p style="margin:0 0 14px; font-size:13px; line-height:1.6; color:#6b7280; {FONT}">One renewal keeps all three going: '
              "tap <b>Renew CMTV+</b> on your dashboard when it's time. Questions? Reply to this email or message us on Telegram.</p>")
    return subject, _shell(subject, heading, body)


async def _fail(why):
    raise RuntimeError(why)
