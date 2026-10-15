"""Assign add-on accounts to customers (CMTV local addition 2026-10-15, owner: "allow me to assign addon users to
existing customers").

Admin > Stremio / CMTVpn / Audiobooks / Nuvio:
- an account with NO customer can be assigned to one: the customer gets a billing service for that login, so it shows on
  their dashboard and gets renewal reminders (cmtv_addons / cmtv_audiobooks `link`, cmtv_nuvio `assign`);
- an account that HAS a customer can be moved to another one: its billing service(s) change owner (move()). The login,
  password and end date don't change. Each moved service keeps the history in cmtv_owner_history.
Both leave an automatic note on the customers' profiles. Nothing is emailed to the customer.
A whole TV-only (panel-only) account with all its lines is better moved with the profile's "Move to an existing customer".

Customer search for those pages (find_customers): name, email, website username, the TV login of panel-only accounts
(panel_username) and any service login, so a TV-only customer can be found by their line username.
"""
import re
from datetime import datetime

from bson import ObjectId


def _oid(v):
    return ObjectId(str(v)) if ObjectId.is_valid(str(v)) else None


async def find_customers(db, q: str, limit: int = 12) -> list:
    q = (q or "").strip()[:80]
    if len(q) < 2:
        return []
    rx = {"$regex": re.escape(q), "$options": "i"}
    owners = set()
    async for s in db.services.find({"$or": [{"username": rx}, {"xtream_username": rx}]}, {"user_id": 1}).limit(50):
        if _oid(s.get("user_id")):
            owners.add(_oid(s["user_id"]))
    out = []
    async for u in db.users.find({"role": "user", "$or": [{"name": rx}, {"email": rx}, {"username": rx}, {"panel_username": rx},
                                                          {"_id": {"$in": list(owners)}}]},
                                 {"name": 1, "email": 1, "panel_username": 1}).limit(limit):
        email = u.get("email") or ""
        tv_only = email.lower().endswith("@panel.local")
        out.append({"id": str(u["_id"]), "name": u.get("name") or u.get("panel_username") or "(no name)",
                    "email": f"TV-only account ({u.get('panel_username') or email.split('@')[0]})" if tv_only else email,
                    "tv_only": tv_only})
    return out


async def customer(db, customer_id):
    """The customer account to assign to (role user), or None."""
    oid = _oid(customer_id)
    u = await db.users.find_one({"_id": oid}) if oid else None
    return u if u and u.get("role") == "user" else None


def _who(u) -> str:
    return f"{u.get('name') or '(no name)'} ({u.get('email') or '?'})"


def _by(current_user) -> str:
    return str((current_user or {}).get("email") or (current_user or {}).get("sub") or "admin")


async def note(db, user_id, text: str, current_user=None):
    await db.cmtv_customer_notes.insert_one({"user_id": str(user_id), "text": text, "created_at": datetime.utcnow(),
                                             "by": _by(current_user), "by_name": "Add-on assign", "auto": True})


def why_not(services: list) -> str:
    """'' if these services may change owner, else the reason (golive-check 2026-10-15):
    - PayPal auto-renew: the subscription belongs to the old customer's PayPal, and renewal orders follow the service's
      owner, so after a move the old customer would pay for the new owner's account;
    - CMTV+ parts: cmtv_plus finds the parts to extend by the customer, so moving one part splits the bundle."""
    for s in services:
        if str((s.get("auto_renew") or {}).get("status") or "").upper() == "ACTIVE":
            return ("This account renews automatically with its current customer's PayPal. Turn auto-renew off first "
                    "(their dashboard, or PayPal), then move it.")
        if s.get("cmtv_plus"):
            return ("This account is part of a CMTV+ bundle. Move the whole customer instead (profile: Move to an existing "
                    "customer), or ask before splitting the bundle.")
    return ""


async def move(db, services: list, new_customer_id, what: str, current_user=None) -> list:
    """Move an add-on account's billing services to another customer. Returns the moved service ids.
    Raises ValueError (message for the admin) when the customer isn't a customer or why_not() refuses."""
    new = await customer(db, new_customer_id)
    if not new:
        raise ValueError("Customer not found")
    reason = why_not([s for s in services if str(s.get("user_id")) != str(new["_id"])])
    if reason:
        raise ValueError(reason)
    now, moved, olds = datetime.utcnow(), [], set()
    for s in services:
        if str(s.get("user_id")) == str(new["_id"]):
            continue
        olds.add(str(s.get("user_id")))
        await db.services.update_one({"_id": s["_id"]}, {
            "$set": {"user_id": str(new["_id"]), "updated_at": now},
            "$push": {"cmtv_owner_history": {"from": s.get("user_id"), "to": str(new["_id"]), "at": now, "by": _by(current_user)}}})
        moved.append(str(s["_id"]))
    if moved:
        names = []
        for o in olds:
            old = await db.users.find_one({"_id": _oid(o)}, {"name": 1, "email": 1}) if _oid(o) else None
            names.append(_who(old) if old else o)
            if old:
                await note(db, o, f"{what} moved to {_who(new)}.", current_user)
        await note(db, new["_id"], f"{what} moved here from {', '.join(names) or 'another account'}.", current_user)
    return moved


def nuvio_service(acc: dict, prod: dict, customer_id: str, shown: str, module: str, now=None) -> dict:
    """The billing service for an existing Nuvio account given to a customer (same fields as the 2026-09-30 link
    script, /root/cmtv-scripts/nuvio/link_nuvio.py). Status from the account: off -> suspended, ended -> expired."""
    now = now or datetime.utcnow()
    prod = prod or {}
    exp = str(acc.get("expires") or "")[:10]
    off = acc.get("status") == "off"
    live = not off and exp >= now.strftime("%Y-%m-%d")
    doc = {"user_id": str(customer_id), "order_id": None, "product_id": str(prod["_id"]) if prod.get("_id") else None,
           "product_name": prod.get("name", "Nuvio"), "account_type": "subscriber", "panel_type": "manual",
           "panel_name": "CMTV Nuvio server", "cockpit_module": module, "cockpit_account_id": acc.get("nuvio_id"),
           "username": shown, "password": acc.get("password"), "xtream_username": shown, "xtream_password": acc.get("password"),
           "term_months": 12, "max_connections": prod.get("max_connections") or 0, "is_trial": bool(acc.get("trial")),
           "setup_instructions": prod.get("setup_instructions", ""), "start_date": now,
           "status": "active" if live else ("suspended" if off else "expired"),
           "created_at": now, "created_via": "cmtv_assign", "cmtv_note": f"Assigned {now:%Y-%m-%d} by admin (existing Nuvio account)"}
    if exp:
        doc["expiry_date"] = datetime.strptime(exp, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
    return doc
