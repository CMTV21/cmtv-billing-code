"""Admin > Orders, refreshed (CMTV local addition 2026-10-04, the owner: hard to use on a phone, not intuitive).
One call returns every order with its customer, what each item did (new line / extend which line / add-on), the lines it
created, the money breakdown and provisioning state, in a few batched queries (the developer's /api/admin/orders looks
the customer up once per order). Actions stay on the existing endpoints: mark-paid, cancel, delete
(/api/admin/orders/{id}/...) and "Mark fixed" (/api/cmtv/admin/orders/{id}/setup-resolved).
"""
from datetime import datetime

from bson import ObjectId
from fastapi import APIRouter, Depends

router = APIRouter(prefix="/api/cmtv/admin/orders", tags=["cmtv-admin-orders"])
D = {}


def init(**deps):
    D.update(deps)


def _oids(ids):
    return [ObjectId(i) for i in ids if i and ObjectId.is_valid(str(i))]


def init_routes():
    admin = D["get_current_admin_user"]

    @router.get("/list")
    async def list_orders(current_user: dict = Depends(admin)):
        db = D["db"]
        orders = [o async for o in db.orders.find().sort("created_at", -1)]
        uids = {o.get("user_id") for o in orders}
        users = {str(u["_id"]): u async for u in db.users.find({"_id": {"$in": _oids(uids)}},
                                                                {"name": 1, "email": 1, "panel_username": 1})}
        oids = [str(o["_id"]) for o in orders]
        made = {}
        async for s in db.services.find({"order_id": {"$in": oids}},
                                        {"order_id": 1, "username": 1, "xtream_username": 1, "status": 1, "product_name": 1,
                                         "expiry_date": 1, "is_trial": 1}):
            made.setdefault(s["order_id"], []).append({
                "id": str(s["_id"]), "username": s.get("username") or s.get("xtream_username") or "",
                "status": s.get("status"), "product": s.get("product_name"), "expires": s.get("expiry_date"),
                "trial": bool(s.get("is_trial"))})
        ren_ids = {i.get("renewal_service_id") for o in orders for i in o.get("items") or [] if i.get("renewal_service_id")}
        renewed = {str(s["_id"]): (s.get("username") or s.get("xtream_username") or "")
                   async for s in db.services.find({"_id": {"$in": _oids(ren_ids)}}, {"username": 1, "xtream_username": 1})}
        out = []
        for o in orders:
            u = users.get(o.get("user_id")) or {}
            email = u.get("email") or ""
            items = []
            for i in o.get("items") or []:
                ext = i.get("action_type") in ("extend", "renew") and i.get("renewal_service_id")
                items.append({"name": i.get("product_name") or "", "price": i.get("price"), "term_months": i.get("term_months"),
                              "kind": "extend" if ext else ("addon" if i.get("account_type") not in ("subscriber", "reseller") else
                                                            "reseller" if i.get("account_type") == "reseller" else "new"),
                              "extends": renewed.get(i.get("renewal_service_id")) if ext else None,
                              "lineup": i.get("lineup"), "groups": len(i.get("bouquets") or []) or None,
                              "credits": i.get("credits"), "quantity": i.get("quantity")})
            emt = o.get("cmtv_emt") or {}
            out.append({
                "id": str(o["_id"]), "number": str(o["_id"])[:8], "status": o.get("status"),
                "created_at": o.get("created_at"), "paid_at": o.get("paid_at"),
                "total": float(o.get("total") or 0), "subtotal": o.get("subtotal"),
                "discount": float(o.get("discount_amount") or 0), "discount_source": o.get("discount_source"),
                "coupon": o.get("coupon_code"), "credits_used": float(o.get("credits_used") or 0),
                "referral_tier": o.get("referral_tier"), "shipping": o.get("shipping_cost"),
                "payment_method": o.get("payment_method"), "payment_method_recorded": o.get("payment_method_recorded"),
                "payment_id": o.get("payment_id"), "auto_renewal": bool(o.get("auto_renewal")),
                "provisioning_status": o.get("provisioning_status"), "provisioning_errors": o.get("provisioning_errors") or [],
                "setup_resolved": bool(o.get("cmtv_setup_resolved")),
                "emt": {"trusted": emt.get("trusted"), "reason": emt.get("reason"), "deposited": bool(emt.get("deposited_at"))} if emt else None,
                "customer": {"id": o.get("user_id"), "name": u.get("name") or "Unknown",
                             "email": "" if email.endswith("@panel.local") else email, "line": u.get("panel_username") or ""},
                "items": items, "services": made.get(str(o["_id"]), []),
            })
        return {"orders": out, "now": datetime.utcnow()}
