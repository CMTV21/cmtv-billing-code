"""Admin home "command centre" data (CMTV local addition 2026-09-26): one call, GET /api/cmtv/admin/overview.

Money comes from the Finances ledger (fin_transactions, the same numbers as Admin > Finances, including offline
payments); services, tickets, customers and orders come from billing's own records. Days and months follow Toronto time. Service type (CCTV / Imperium / Add-ons) comes from the
product's group name, like the storefront, with the panel type or Cockpit module as the fallback.
"""
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from bson import ObjectId
from fastapi import APIRouter, Depends

import cmtv_lines as L

router = APIRouter(prefix="/api/cmtv/admin", tags=["cmtv-admin"])
D = {}
TZ = ZoneInfo("America/Toronto")


def init(**deps):
    D.update(deps)


def _oid(v):
    return ObjectId(v) if ObjectId.is_valid(str(v)) else None


def _local(dt):
    """billing stores naive UTC"""
    return dt.replace(tzinfo=timezone.utc).astimezone(TZ) if isinstance(dt, datetime) else None


def _family_of_group(name):
    n = str(name or "").lower()
    if "trial" in n: return "trials"
    if "resell" in n: return "resellers"
    if "imperium" in n: return "imperium"
    if "cctv" in n: return "cctv"
    if re.search(r"add-?on", n): return "addons"
    return "other"


def _family(product, groups, name="", panel_type="", module=""):
    fam = _family_of_group(groups.get((product or {}).get("group_id"), ""))
    if fam in ("trials", "other"):
        text = f"{name} {(product or {}).get('name', '')}".lower()
        if module or re.search(r"stremio|vpn|audiobook|cmtv\+", text): return "addons"
        if panel_type == "aether" or "imperium" in text: return "imperium"
        if panel_type in ("xtream", "xuione", "nxtdash", "onestream") or re.search(r"cctv|connection", text): return "cctv"
    return fam


# Finances ledger "server" -> the page's service type
SERVER_FAMILY = {"CCTV": "cctv", "Imperium": "imperium", "Stremio": "addons", "CMTVpn": "addons", "CMTV+": "addons",
                 "ABS": "addons", "VPN365": "addons"}
OFFLINE = {"manual", "emt", "zelle", "cashapp", "venmo", "wise"}   # payments the admin confirms by hand


def _first_price(p):
    term, price = next(iter(((p or {}).get("prices") or {"1": 0}).items()))
    return max(1, int(term)), float(price)


def _label(order):
    try:
        import cmtv_payments
        return cmtv_payments.order_label(order)
    except Exception:
        return str(order.get("payment_method") or "")


def init_routes():
    admin = D["get_current_admin_user"]

    @router.get("/overview")
    async def overview(current_user: dict = Depends(admin)):
        orders, services, users, tickets = D["orders"], D["services"], D["users"], D["tickets"]
        settings = await D["get_settings"]()
        groups = {g.get("id"): g.get("name", "") for g in settings.get("product_groups", [])}
        products = {str(p["_id"]): p async for p in D["products"].find({})}
        now_utc = datetime.utcnow()
        now = _local(now_utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        prev_month_start = (month_start - timedelta(days=1)).replace(day=1)
        elapsed = now - month_start
        names = {}

        async def who(uid):
            if uid not in names:
                u = await users.find_one({"_id": _oid(uid)}, {"name": 1, "email": 1})
                names[uid] = {"name": (u or {}).get("name") or "Unknown", "email": (u or {}).get("email")}
            return names[uid]

        # ---- revenue: the Finances ledger (all income, incl. offline payments), so this page and Finances agree ----
        ledger_from = (prev_month_start - timedelta(days=2)).replace(tzinfo=None)
        if ledger_from > (now - timedelta(days=32)).replace(tzinfo=None):
            ledger_from = (now - timedelta(days=32)).replace(tzinfo=None)
        daily = defaultdict(float)
        month_total = prev_same = prev_full = 0.0
        by_family = defaultdict(float)
        by_method = defaultdict(float)
        same_point = (prev_month_start + elapsed).replace(tzinfo=None)
        import cmtv_finance
        async for r in cmtv_finance.D["tx"].find({"deleted": {"$ne": True}, "date": {"$gte": ledger_from}}):
            amt = float(r.get("amount") or 0)
            t = r.get("date")
            if not isinstance(t, datetime) or amt <= 0:
                continue
            daily[t.date().isoformat()] += amt
            if t >= month_start.replace(tzinfo=None):
                month_total += amt
                by_method[r.get("method") or "Not recorded"] += amt
                by_family[SERVER_FAMILY.get(str(r.get("server") or ""), "other")] += amt
            elif t >= prev_month_start.replace(tzinfo=None):
                prev_full += amt
                if t < same_point:
                    prev_same += amt
        try:   # same maths as Admin > Finances (credits x rate, PayPal fees, expenses)
            fin = await cmtv_finance._totals(month_start.replace(tzinfo=None), (month_start + timedelta(days=32)).replace(day=1, tzinfo=None))
        except Exception:
            fin = {}
        billing_month = 0.0
        async for o in orders.find({"status": "paid", "payment_method": {"$ne": "test"}, "total": {"$gt": 0},
                                    "paid_at": {"$gte": month_start.astimezone(timezone.utc).replace(tzinfo=None)}}):
            billing_month += float(o.get("total") or 0)
        today = now.date()
        last30 = [{"date": (today - timedelta(days=29 - k)).isoformat(),
                   "revenue": round(daily.get((today - timedelta(days=29 - k)).isoformat(), 0.0), 2)} for k in range(30)]
        cum, running = [], 0.0
        d = month_start.date()
        while d <= today:
            running += daily.get(d.isoformat(), 0.0)
            cum.append(round(running, 2))
            d += timedelta(days=1)

        # ---- services ----
        active_by_family = defaultdict(int)
        recurring, auto_on = 0.0, 0
        expiring = []
        week_no_ar = 0
        async for s in services.find({"status": "active"}):
            p = products.get(str(s.get("product_id")))
            # CMTV local change 2026-10-08: a trial line paid for and extended counts as paid (shared rule, cmtv_lines)
            is_trial = L.is_trial_line(s, now_utc, p)
            if s.get("account_type") == "reseller" or is_trial:
                continue
            fam = _family(p, groups, s.get("product_name", ""), s.get("panel_type", ""), s.get("cockpit_module", ""))
            active_by_family[fam if fam in ("cctv", "imperium", "addons") else "other"] += 1
            term, price = _first_price(p)
            if price > 0:
                recurring += price / term
            ar = (s.get("auto_renew") or {}).get("status") == "ACTIVE"
            auto_on += 1 if ar else 0
            exp = s.get("expiry_date")
            if isinstance(exp, datetime) and now_utc <= exp <= now_utc + timedelta(days=14):
                if exp <= now_utc + timedelta(days=7) and not ar:
                    week_no_ar += 1
                c = await who(s.get("user_id"))
                expiring.append({"customer": c["name"], "email": c["email"], "service": s.get("product_name"), "family": fam,
                                 "ends": exp.isoformat() + "Z", "auto_renew": ar, "user_id": s.get("user_id")})
        expiring.sort(key=lambda e: e["ends"])

        # ---- customers ----
        users_q = {"role": "user", "created_via": {"$ne": "panel_sync"}}   # real sign-ups, not imported panel accounts
        new30 = await users.count_documents({**users_q, "created_at": {"$gte": now_utc - timedelta(days=30)}})
        prev30 = await users.count_documents({**users_q, "created_at": {"$gte": now_utc - timedelta(days=60), "$lt": now_utc - timedelta(days=30)}})
        referred30 = await users.count_documents({**users_q, "created_at": {"$gte": now_utc - timedelta(days=30)},
                                                  "referred_by": {"$nin": [None, ""]}})
        first_paid = orders.aggregate([{"$match": {"status": "paid", "payment_method": {"$ne": "test"}, "total": {"$gt": 0}}},
                                       {"$group": {"_id": "$user_id", "first": {"$min": "$paid_at"}}},
                                       {"$match": {"first": {"$gte": now_utc - timedelta(days=30)}}}, {"$count": "n"}])
        new_paying30 = ((await first_paid.to_list(1)) or [{"n": 0}])[0]["n"]

        # ---- needs you ----
        not_set_up = []
        async for o in orders.find({"status": "paid", "provisioning_status": {"$in": ["failed", "partial"]},
                                    "cmtv_setup_resolved": {"$ne": True},
                                    "paid_at": {"$gte": now_utc - timedelta(days=30)}}).sort("paid_at", -1).limit(5):
            c = await who(o.get("user_id"))
            not_set_up.append({"id": str(o["_id"]), "customer": c["name"], "user_id": o.get("user_id"), "items": ", ".join(i.get("product_name", "") for i in o.get("items") or []),
                               "reason": ((o.get("provisioning_errors") or [""])[0] or "")[:140]})
        pending = []
        async for o in orders.find({"status": "pending", "total": {"$gt": 0}, "payment_method": {"$in": list(OFFLINE)},
                                    "created_at": {"$gte": now_utc - timedelta(days=14)}}).sort("created_at", 1):
            c = await who(o.get("user_id"))
            pending.append({"id": str(o["_id"]), "customer": c["name"], "total": float(o.get("total") or 0), "method": _label(o),
                            "days": max(0, (now_utc - o["created_at"]).days) if isinstance(o.get("created_at"), datetime) else None})
        waiting = []
        async for t in tickets.find({"status": {"$ne": "closed"}}).sort("updated_at", 1):
            msgs = t.get("messages") or []
            if msgs and not msgs[-1].get("is_admin"):
                at = msgs[-1].get("created_at")
                waiting.append({"id": str(t["_id"]), "subject": t.get("subject"),
                                "hours": int((now_utc - at).total_seconds() // 3600) if isinstance(at, datetime) else None})
        # 2026-10-04: Telegram support-bot tickets waiting on us count too (Support inbox, cmtv_support_inbox.py)
        try:
            import cmtv_support_inbox
            for r in cmtv_support_inbox._tg_rows():
                if r["state"] == "needs":
                    at = cmtv_support_inbox._dt(r["updated_at"])
                    waiting.append({"id": "tg:" + r["id"], "subject": f"{r['number']} {r['subject']} (Telegram)",
                                    "hours": int((now_utc - at).total_seconds() // 3600) if at else None})
            waiting.sort(key=lambda w: -(w["hours"] if w["hours"] is not None else -1))
        except Exception:
            pass

        # emails that failed to send in the last 7 days (2026-09-26: the log only records sent/failed from today)
        email_failed = []
        async for e in D["orders"].database.email_logs.find(
                {"status": "failed", "created_at": {"$gte": now_utc - timedelta(days=7)}},
                {"recipient_email": 1, "subject": 1, "error_message": 1, "created_at": 1}).sort("created_at", -1).limit(20):
            email_failed.append({"to": e.get("recipient_email"), "subject": (e.get("subject") or "")[:90],
                                 "error": (e.get("error_message") or "")[:140],
                                 "at": e["created_at"].isoformat() + "Z" if isinstance(e.get("created_at"), datetime) else None})

        # ---- trials -> paying, and the come-back offer (2026-09-27) ----
        async def trial_conversion(days):
            since = now_utc - timedelta(days=days)
            first = {}
            async for s in services.find({"is_trial": True, "created_at": {"$gte": since}}, {"user_id": 1, "created_at": 1}):
                uid = str(s.get("user_id") or "")
                if uid and (uid not in first or s["created_at"] < first[uid]):
                    first[uid] = s["created_at"]
            converted = 0
            for uid, t in first.items():
                if await orders.find_one({"user_id": uid, "status": "paid", "total": {"$gt": 0}, "created_at": {"$gt": t}}, {"_id": 1}):
                    converted += 1
            return {"days": days, "trials": len(first), "paying": converted,
                    "pct": round(converted * 100 / len(first)) if first else None}
        wb_sent = wb_used = 0
        wb_revenue = 0.0
        async for w in orders.database.cmtv_trial_winback.find({"code": {"$ne": None}}, {"code": 1}):
            wb_sent += 1
            use = await orders.database.coupon_usage.find_one({"coupon_code": w["code"]}, {"order_id": 1})
            if use:
                o = await orders.find_one({"_id": ObjectId(use["order_id"])} if ObjectId.is_valid(str(use.get("order_id"))) else {"_id": None},
                                          {"status": 1, "total": 1})
                if o and o.get("status") == "paid":
                    wb_used += 1
                    wb_revenue += float(o.get("total") or 0)
        trials = {"d30": await trial_conversion(30), "d90": await trial_conversion(90),
                  "winback": {"sent": wb_sent, "used": wb_used, "revenue": round(wb_revenue, 2)}}

        # ---- recent orders ----
        recent = []
        async for o in orders.find({"status": {"$ne": "cancelled"}}).sort("created_at", -1).limit(8):
            c = await who(o.get("user_id"))
            recent.append({"id": str(o["_id"]), "customer": c["name"], "user_id": o.get("user_id"), "items": ", ".join(i.get("product_name", "") for i in o.get("items") or []),
                           "method": _label(o), "total": float(o.get("total") or 0), "status": o.get("status"),
                           "provisioning": o.get("provisioning_status"), "created_at": o["created_at"].isoformat() + "Z" if isinstance(o.get("created_at"), datetime) else None})

        return {
            "now": now.isoformat(), "month": month_start.strftime("%B"),
            "revenue": {"month": round(month_total, 2), "prev_same_point": round(prev_same, 2), "prev_month": round(prev_full, 2),
                        "month_cumulative": cum, "last30": last30, "billing_orders_month": round(billing_month, 2),
                        "profit_month": round(float(fin.get("profit") or 0), 2), "costs_month": round(float(fin.get("costs") or 0), 2)},
            "by_family": {k: round(v, 2) for k, v in by_family.items() if v > 0},
            "by_method": sorted(({"method": k, "total": round(v, 2)} for k, v in by_method.items()), key=lambda x: -x["total"]),
            "active": dict(active_by_family), "active_total": sum(active_by_family.values()),
            "recurring_month": round(recurring, 2), "auto_renew_on": auto_on,
            "customers": {"new30": new30, "prev30": prev30, "referred30": referred30, "new_paying30": new_paying30},
            "needs": {"not_set_up": not_set_up, "pending_payment": pending, "tickets_waiting": waiting,
                      "ending_week_no_autorenew": week_no_ar, "email_failed": email_failed},
            "expiring": expiring[:40], "expiring_count": len(expiring), "recent_orders": recent, "trials": trials,
        }

    @router.post("/orders/{order_id}/setup-resolved")
    async def setup_resolved(order_id: str, current_user: dict = Depends(admin)):
        """'Mark fixed' on a paid order that didn't set up (e.g. the admin set it up by hand): hides it from Needs you."""
        r = await D["orders"].update_one({"_id": _oid(order_id)}, {"$set": {
            "cmtv_setup_resolved": True, "cmtv_setup_resolved_at": datetime.utcnow(), "cmtv_setup_resolved_by": current_user.get("sub")}})
        return {"success": bool(r.matched_count)}
