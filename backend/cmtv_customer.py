"""Admin customer profile (CMTV local addition 2026-09-27): everything about one customer on one page.

GET  /api/cmtv/admin/customers/search?q=   name / email / username, or any service login (TV line, Stremio, CMTVpn, Audiobooks)
GET  /api/cmtv/admin/customers/{id}/profile  profile, totals, services, orders, tickets, credit, referrals, emails, activity, notes
POST /api/cmtv/admin/customers/{id}/notes    add an internal note (admin only; customers never see them)
POST /api/cmtv/admin/customers/{id}/notes/{note_id}/delete   retire a note (kept, hidden)
Service actions on the page reuse existing endpoints (suspend/unsuspend TV lines, Cockpit/Audiobooks extend and switch).
"""
import re
from datetime import datetime

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException

router = APIRouter(prefix="/api/cmtv/admin/customers", tags=["cmtv-customer"])
D = {}
ADDON_MODULES = {"nuvio": "Stremio", "vpn": "CMTVpn", "audiobooks": "Audiobooks"}


def init(**deps):
    D.update(deps)


def _oid(v):
    return ObjectId(v) if ObjectId.is_valid(str(v)) else None


def _iso(v):
    return v.isoformat() if isinstance(v, datetime) else v


def _label(order):
    try:
        import cmtv_payments
        return cmtv_payments.order_label(order)
    except Exception:
        return str(order.get("payment_method") or "")


def init_routes():
    admin = D["get_current_admin_user"]

    @router.get("/search")
    async def search(q: str = "", current_user: dict = Depends(admin)):
        q = (q or "").strip()[:80]
        if len(q) < 2:
            return []
        rx = {"$regex": re.escape(q), "$options": "i"}
        found, order = {}, []
        async for u in D["users"].find({"role": "user", "$or": [{"name": rx}, {"email": rx}, {"panel_username": rx}]},
                                       {"name": 1, "email": 1, "panel_username": 1}).limit(15):
            found[str(u["_id"])] = {"id": str(u["_id"]), "name": u.get("name"), "email": u.get("email"), "match": ""}
            order.append(str(u["_id"]))
        async for s in D["services"].find({"$or": [{"username": rx}, {"xtream_username": rx}]},
                                          {"user_id": 1, "username": 1, "xtream_username": 1, "product_name": 1}).limit(15):
            uid = str(s.get("user_id") or "")
            if uid and uid not in found:
                u = await D["users"].find_one({"_id": _oid(uid)}, {"name": 1, "email": 1})
                if u:
                    found[uid] = {"id": uid, "name": u.get("name"), "email": u.get("email"),
                                  "match": f"{s.get('product_name', '')}: {s.get('username') or s.get('xtream_username')}"}
                    order.append(uid)
        return [found[i] for i in order][:15]

    @router.get("/{customer_id}/profile")
    async def profile(customer_id: str, current_user: dict = Depends(admin)):
        user = await D["users"].find_one({"_id": _oid(customer_id)})
        if not user:
            raise HTTPException(404, "Customer not found")
        uid = str(user["_id"])
        settings = await D["get_settings"]()
        groups = {g.get("id"): g.get("name", "") for g in settings.get("product_groups", [])}
        products = {str(p["_id"]): p async for p in D["products"].find({}, {"name": 1, "group_id": 1})}
        import cmtv_admin_overview as ov
        now = datetime.utcnow()

        services = []
        async for s in D["services"].find({"user_id": uid}).sort("created_at", -1):
            exp = s.get("expiry_date")
            fam = ov._family(products.get(str(s.get("product_id"))), groups, s.get("product_name", ""),
                             s.get("panel_type", ""), s.get("cockpit_module", ""))
            ar = s.get("auto_renew") or {}
            services.append({
                "id": str(s["_id"]), "product_name": (s.get("product_name") or "").strip(), "family": fam,
                "panel_type": s.get("panel_type"), "panel_name": s.get("panel_name"),
                "cockpit_module": s.get("cockpit_module"), "addon": ADDON_MODULES.get(s.get("cockpit_module") or ""),
                "username": s.get("username") or s.get("xtream_username"),
                "password": s.get("xtream_password") or s.get("password"),
                "connections": s.get("max_connections"), "status": s.get("status"), "is_trial": bool(s.get("is_trial")),
                "account_type": s.get("account_type"), "start": _iso(s.get("start_date") or s.get("created_at")),
                "expiry": _iso(exp), "days_left": (exp - now).days if isinstance(exp, datetime) else None,
                "auto_renew": ar.get("status") == "ACTIVE", "order_id": s.get("order_id")})
        order_rank = {"active": 0, "suspended": 1, "expired": 2}
        services.sort(key=lambda x: (order_rank.get(x["status"], 3), x["days_left"] if x["days_left"] is not None else 99999))

        orders, paid_total, paid_count, first_paid, last_paid = [], 0.0, 0, None, None
        async for o in D["orders"].find({"user_id": uid}).sort("created_at", -1):
            if o.get("status") == "paid" and float(o.get("total") or 0) > 0:
                paid_total += float(o.get("total") or 0)
                paid_count += 1
                t = o.get("paid_at") or o.get("created_at")
                first_paid = t if first_paid is None or (t and t < first_paid) else first_paid
                last_paid = t if last_paid is None or (t and t > last_paid) else last_paid
            if len(orders) < 30:
                orders.append({"id": str(o["_id"]), "created_at": _iso(o.get("created_at")), "paid_at": _iso(o.get("paid_at")),
                               "items": ", ".join((i.get("product_name") or "").strip() for i in o.get("items") or []),
                               "total": float(o.get("total") or 0), "status": o.get("status"), "method": _label(o),
                               "provisioning": o.get("provisioning_status"), "coupon": o.get("coupon_code"),
                               "discount": float(o.get("discount_amount") or 0), "credits_used": float(o.get("credits_used") or 0)})

        tickets = []
        async for t in D["db"].tickets.find({"user_id": uid}).sort("updated_at", -1).limit(12):
            msgs = t.get("messages") or []
            tickets.append({"id": str(t["_id"]), "subject": t.get("subject"), "status": t.get("status"),
                            "updated_at": _iso(t.get("updated_at") or t.get("created_at")), "messages": len(msgs),
                            "waiting_on_us": bool(msgs) and not msgs[-1].get("is_admin") and t.get("status") != "closed"})

        credit = [{"amount": float(c.get("amount") or 0), "type": c.get("transaction_type"), "description": c.get("description"),
                   "at": _iso(c.get("created_at"))}
                  async for c in D["db"].credit_transactions.find({"user_id": uid}).sort("created_at", -1).limit(10)]

        referred = []
        async for r in D["db"].referrals.find({"referrer_id": uid}).sort("created_at", -1):
            referred.append({"email": r.get("referred_email"), "status": r.get("status"), "at": _iso(r.get("created_at"))})
        past = await D["db"].cmtv_referral_history.count_documents({"user_id": uid, "deleted": {"$ne": True}})
        try:
            import cmtv_referral
            tier = await cmtv_referral.status(uid)
        except Exception:
            tier = None
        referred_by = None
        if user.get("referred_by"):
            rb = await D["users"].find_one({"$or": [{"_id": _oid(user["referred_by"])}, {"referral_code": user["referred_by"]}]},
                                           {"name": 1, "email": 1})
            referred_by = {"id": str(rb["_id"]), "name": rb.get("name"), "email": rb.get("email")} if rb else {"code": user["referred_by"]}

        emails = [{"subject": e.get("subject"), "status": e.get("status"), "type": e.get("template_type") or e.get("email_type"),
                   "error": (e.get("error_message") or "")[:120], "at": _iso(e.get("created_at"))}
                  async for e in D["db"].email_logs.find({"customer_id": uid}, {"html_content": 0, "text_content": 0})
                  .sort("created_at", -1).limit(15)]

        activity = []
        svc_names = {s["id"]: s["product_name"] for s in services}
        async for l in D["db"].lifecycle_logs.find({"user_id": uid}).sort("created_at", -1).limit(25):
            activity.append({"at": _iso(l.get("created_at")), "kind": "service", "text":
                             f"{(l.get('action') or '').replace('_', ' ')}: {svc_names.get(str(l.get('service_id')), 'a service')}"
                             + (f" ({l.get('reason')})" if l.get("reason") else "")})
        for o in orders[:15]:
            activity.append({"at": o["paid_at"] or o["created_at"], "kind": "order",
                             "text": f"order {o['status']}: {o['items']} ${o['total']:.2f}" + (f" by {o['method']}" if o['status'] == 'paid' else "")})
        for t in tickets[:8]:
            activity.append({"at": t["updated_at"], "kind": "ticket", "text": f"ticket ({t['status']}): {t['subject']}"})
        wb = await D["db"].cmtv_trial_winback.find_one({"_id": uid})
        if wb and wb.get("code"):
            activity.append({"at": _iso(wb.get("sent_at")), "kind": "email", "text": f"sent the trial come-back offer ({wb['code']})"})
        activity = sorted([a for a in activity if a["at"]], key=lambda a: a["at"], reverse=True)[:40]

        notes = [{"id": str(n["_id"]), "text": n.get("text"), "at": _iso(n.get("created_at")), "by": n.get("by_name")}
                 async for n in D["db"].cmtv_customer_notes.find({"user_id": uid, "deleted": {"$ne": True}}).sort("created_at", -1)]

        email = user.get("email") or ""
        return {
            "customer": {"id": uid, "name": user.get("name"), "email": email, "username": user.get("panel_username"),
                         "created_at": _iso(user.get("created_at")), "created_via": user.get("created_via"),
                         "email_verified": bool(user.get("email_verified")), "real_email": "@" in email and not email.endswith("@panel.local"),
                         "credit_balance": float(user.get("credit_balance") or 0), "referral_code": user.get("referral_code"),
                         "referred_by": referred_by},
            "totals": {"paid_total": round(paid_total, 2), "paid_orders": paid_count, "first_paid": _iso(first_paid),
                       "last_paid": _iso(last_paid), "active_services": sum(1 for s in services if s["status"] == "active" and not s["is_trial"]),
                       "open_tickets": sum(1 for t in tickets if t["status"] != "closed")},
            "services": services, "orders": orders, "tickets": tickets, "credit": credit,
            "referrals": {"tier": tier, "referred": referred, "past_count": past},
            "emails": emails, "activity": activity, "notes": notes,
        }

    @router.post("/{customer_id}/notes")
    async def add_note(customer_id: str, data: dict, current_user: dict = Depends(admin)):
        text = str(data.get("text") or "").strip()[:2000]
        if not text:
            raise HTTPException(400, "Write something first")
        if not await D["users"].find_one({"_id": _oid(customer_id)}, {"_id": 1}):
            raise HTTPException(404, "Customer not found")
        me = await D["users"].find_one({"_id": _oid(current_user.get("sub"))}, {"name": 1})
        r = await D["db"].cmtv_customer_notes.insert_one({"user_id": customer_id, "text": text, "created_at": datetime.utcnow(),
                                                          "by": current_user.get("sub"), "by_name": (me or {}).get("name")})
        return {"id": str(r.inserted_id)}

    @router.post("/{customer_id}/notes/{note_id}/delete")
    async def delete_note(customer_id: str, note_id: str, current_user: dict = Depends(admin)):
        r = await D["db"].cmtv_customer_notes.update_one({"_id": _oid(note_id), "user_id": customer_id},
                                                         {"$set": {"deleted": True, "deleted_at": datetime.utcnow()}})
        return {"success": bool(r.matched_count)}
