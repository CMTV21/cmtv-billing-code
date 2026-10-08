"""Extend a TV line from the customer profile (CMTV local addition 2026-10-05, the owner's request).
Admin > Customers > profile > a CCTV / Imperium line > +1 mo / +3 mo / +6 mo / +1 yr. Uses billing's own renewal path
(provision_xtream_service / provision_aether_service with an "extend" item, the same as a customer renewal; tested on both
live panels 2026-10-05), with the panel package for that server + the line's device count + the months chosen, so the
panel charges its normal credits. Line-ups are kept (cmtv_lineups.apply). A trial line becomes a paid line (after_item).
Optional: the payment (amount + method) goes into Finances (cmtv_finance.add_manual, with the panel credits); a free
extension is recorded as $0 with its credit cost. Optional "service renewed" email. Always: a note on the profile.
GET  /api/cmtv/admin/extend/{service_id}/options -> the plans available for that line
POST /api/cmtv/admin/extend/{service_id} {months, amount, method, email, note}
"""
import logging
import re
from datetime import datetime

from bson import ObjectId
from fastapi import APIRouter, Body, Depends, HTTPException

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/cmtv/admin/extend", tags=["cmtv-admin-extend"])
D = {}
MONTHS = [1, 3, 6, 12]
SERVER = {"xtream": "CCTV", "aether": "Imperium"}


def init(**deps):
    D.update(deps)


async def _line(service_id):
    db = D["db"]
    svc = await db.services.find_one({"_id": ObjectId(service_id)}) if ObjectId.is_valid(service_id) else None
    if svc and svc.get("panel_type") == "nxtdash":
        raise HTTPException(409, "Billing still has this line on the old Imperium panel (NXT Dash). It needs moving to the new "
                                 "Imperium panel first, then it can be extended here.")
    if not svc or svc.get("panel_type") not in SERVER or not (svc.get("xtream_username") or svc.get("username")):
        raise HTTPException(404, "Only CCTV and Imperium lines can be extended here.")
    return svc


# 2026-10-08 (owner: "search a customer, click the server they have and extend them"): the extend panel shows the end
# date now and after each choice. The panel's own view of the line (imported_users, refreshed by the hourly panel sync)
# wins when billing's copy is older, e.g. after a renewal done on the panel itself.
def _dt(v):
    if isinstance(v, str) and v.strip():
        try:
            v = datetime.fromisoformat(v.strip().replace("Z", "").replace(" ", "T")[:19])
        except ValueError:
            return None
    return v if isinstance(v, datetime) else None


def add_months(d, n):
    y, m = divmod(d.month - 1 + n, 12)
    y, m = d.year + y, m + 1
    last = [31, 29 if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
    return d.replace(year=y, month=m, day=min(d.day, last))


async def panel_view(svc):
    """The panel's record of this line (imported_users), or None."""
    login = svc.get("xtream_username") or svc.get("username") or ""
    if not login:
        return None
    return await D["db"].imported_users.find_one({"username": {"$regex": f"^{re.escape(login)}$", "$options": "i"},
                                                  "panel_type": svc.get("panel_type"), "account_type": {"$ne": "reseller"}})


def current_end(svc, iu):
    """(end date now, where it came from): the later of billing's and the panel's dates."""
    b, p = _dt(svc.get("expiry_date")), _dt((iu or {}).get("expiry_date"))
    if p and (not b or p > b):
        return p, "panel"
    return b, "billing"


async def _plan(svc, months):
    conns = int(svc.get("max_connections") or 1)
    return await D["db"].products.find_one({"panel_type": svc["panel_type"], "account_type": "subscriber", "is_trial": {"$ne": True},
                                            "max_connections": conns, f"prices.{months}": {"$exists": True}, "active": True})


def init_routes():
    admin = D["get_current_admin_user"]

    @router.get("/{service_id}/options")
    async def options(service_id: str, current_user: dict = Depends(admin)):
        svc = await _line(service_id)
        out = []
        for m in MONTHS:
            p = await _plan(svc, m)
            if p:
                out.append({"months": m, "product": p.get("name"), "price": float((p.get("prices") or {}).get(str(m)) or 0)})
        user = await D["db"].users.find_one({"_id": ObjectId(svc["user_id"])}, {"email": 1, "name": 1}) if ObjectId.is_valid(str(svc.get("user_id"))) else None
        email = str((user or {}).get("email") or "")
        # 2026-10-08: end date now + after each choice (renewals add time on top of what's left; an ended line starts today)
        iu = await panel_view(svc)
        end, src = current_end(svc, iu)
        now = datetime.utcnow()
        base = end if end and end > now else now
        for o in out:
            o["new_end"] = add_months(base, o["months"]).isoformat() + "Z"
        return {"server": SERVER[svc["panel_type"]], "devices": int(svc.get("max_connections") or 1), "options": out,
                "can_email": "@" in email and not email.endswith("@panel.local"),
                "login": svc.get("xtream_username") or svc.get("username"), "customer": (user or {}).get("name") or "",
                "status": (iu or {}).get("status") or svc.get("status"), "ends": end.isoformat() + "Z" if end else None,
                "ends_from": src, "ended": bool(end and end <= now)}

    @router.post("/{service_id}")
    async def extend(service_id: str, data: dict = Body(...), current_user: dict = Depends(admin)):
        db = D["db"]
        svc = await _line(service_id)
        months = int(data.get("months") or 0)
        if months not in MONTHS:
            raise HTTPException(400, "Pick 1, 3, 6 or 12 months.")
        try:
            amount = round(float(data.get("amount") or 0), 2)
        except (TypeError, ValueError):
            raise HTTPException(400, "The amount is a number (0 for free).")
        if amount < 0:
            raise HTTPException(400, "The amount can't be negative.")
        product = await _plan(svc, months)
        if not product:
            raise HTTPException(400, f"No {months}-month {SERVER[svc['panel_type']]} plan for {svc.get('max_connections') or 1} devices.")
        uid = str(svc.get("user_id") or "")
        user = await db.users.find_one({"_id": ObjectId(uid)}) if ObjectId.is_valid(uid) else None
        if not user:
            raise HTTPException(400, "This line has no customer account.")
        login = svc.get("xtream_username") or svc.get("username")
        item = {"product_id": str(product["_id"]), "product_name": product.get("name"), "term_months": months, "price": amount,
                "account_type": "subscriber", "action_type": "extend", "renewal_service_id": str(svc["_id"]), "bouquets": None}
        if svc["panel_type"] == "aether" and D.get("lineups_apply"):
            product = await D["lineups_apply"](product, item)   # keep the line's line-up
        email = str(user.get("email") or "")
        es = await D["get_email_service"]() if data.get("email") and "@" in email and not email.endswith("@panel.local") else None
        oid = ObjectId()
        order = {"_id": oid, "user_id": uid, "items": [item], "cmtv_admin_extend": True}
        before = svc.get("expiry_date")
        await D["provisioners"][svc["panel_type"]](str(oid), order, user, item, product, await D["get_settings"](), es)
        after = await db.services.find_one({"_id": svc["_id"]})
        if not after or after.get("expiry_date") == before or (before and after.get("expiry_date") and after["expiry_date"] <= before):
            raise HTTPException(502, "The panel didn't extend the line. Check the panel credits, then try again.")
        try:
            import cmtv_trial_watch
            await cmtv_trial_watch.after_item(str(oid), order, item, product)
        except Exception as e:
            logger.warning(f"admin extend: trial bookkeeping failed: {e}")
        # 2026-10-08: "Cash" is offered in the extend panel; Finances knows e-Transfer / PayPal / Other, so Cash goes in as
        # Other with "Cash" in the notes
        method = str(data.get("method") or "Other")
        how = f"paid ${amount:.2f} by {method}" if amount > 0 else "free"
        if method not in ("e-Transfer", "PayPal"):
            data = {**data, "method": "Other"}
        try:
            import cmtv_finance
            cfg = await cmtv_finance.config()
            credits = cmtv_finance.credits_for(cfg, SERVER[svc["panel_type"]], svc.get("max_connections") or 1, months)
            await cmtv_finance.add_manual({"server": SERVER[svc["panel_type"]], "amount": amount,
                                           "customer": user.get("name") or email, "method": data.get("method") or "Other",
                                           "credits": credits or 0, "notes": f"Admin extend +{months} mo, line {login} ({how})"},
                                          {"email": current_user.get("email") or "admin"},
                                          {"user_id": uid, "admin_extend": True, "service_id": str(svc["_id"]),
                                           "needs_review": credits is None})
        except Exception as e:
            logger.warning(f"admin extend: finance record failed: {e}")
        note = " ".join(str(data.get("note") or "").split())[:200]
        exp = after.get("expiry_date")
        await db.cmtv_customer_notes.insert_one({"user_id": uid, "deleted": False, "created_at": datetime.utcnow(),
                                                 "by": current_user.get("email") or "admin",
                                                 "text": f"Extended {login} +{months} month{'s' if months > 1 else ''} ({product.get('name')}), {how}. "
                                                         f"Now ends {exp.strftime('%Y-%m-%d') if exp else '?'}." + (f" {note}" if note else "")})
        logger.info(f"Admin extend: {login} +{months} mo ({how}) -> {exp}")
        return {"ok": True, "new_expiry": exp, "product": product.get("name"), "emailed": bool(es)}
