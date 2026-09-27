"""Admin > Analytics (CMTV local addition 2026-09-27; replaces the developer's page, whose chart was empty and whose churn/MRR
figures were misleading). GET /api/cmtv/analytics?months=12

History (revenue, profit, service mix, payment methods, new customers, providers, expenses, top customers) comes from the
Finances ledger (fin_transactions / fin_expenses, back to 2025-04), so it matches Admin > Finances and includes offline
payments. The present (active subscriptions, renewals coming up) comes from billing services. No churn / renewal-rate
figures: many renewals happen outside billing (e-Transfer), so those numbers would be wrong.
"""
from collections import defaultdict
from datetime import datetime, timedelta

from bson import ObjectId
from fastapi import APIRouter, Depends

router = APIRouter(prefix="/api/cmtv/analytics", tags=["cmtv-analytics"])
D = {}
FAMILIES = ["cctv", "imperium", "addons", "other"]


def init(**deps):
    D.update(deps)


def _month_start(d):
    return d.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _add_months(d, n):
    y, m = divmod(d.month - 1 + n, 12)
    return d.replace(year=d.year + y, month=m + 1, day=1)


def _first_price(p):
    term, price = next(iter(((p or {}).get("prices") or {"1": 0}).items()))
    return max(1, int(term)), float(price)


def init_routes():
    admin = D["get_current_admin_user"]

    @router.get("")
    async def analytics(months: int = 12, current_user: dict = Depends(admin)):
        import cmtv_finance
        import cmtv_admin_overview as ov
        months = max(3, min(int(months or 12), 36))
        now = datetime.utcnow()
        m_end = _add_months(_month_start(now), 1)
        m_start = _add_months(m_end, -months)
        tx_col, exp_col = cmtv_finance.D["tx"], cmtv_finance.D["exp"]

        # ---- monthly history from the ledger ----
        keys = [_add_months(m_start, i).strftime("%Y-%m") for i in range(months)]
        rows = {k: {"month": k, **{f: 0.0 for f in FAMILIES}, "revenue": 0.0, "new_customers": 0, "payments": 0} for k in keys}
        methods, providers, customers = defaultdict(float), {}, {}
        async for t in tx_col.find({"deleted": {"$ne": True}, "date": {"$gte": m_start, "$lt": m_end}}):
            if not isinstance(t.get("date"), datetime):
                continue
            k, amt = t["date"].strftime("%Y-%m"), float(t.get("amount") or 0)
            r = rows.get(k)
            if not r:
                continue
            fam = ov.SERVER_FAMILY.get(str(t.get("server") or ""), "other")
            r[fam] += amt
            r["revenue"] += amt
            r["payments"] += 1
            r["new_customers"] += 1 if t.get("new_user") else 0
            methods[t.get("method") or "Not recorded"] += amt
            srv = str(t.get("server") or "Other")
            p = providers.setdefault(srv, {"server": srv, "family": fam, "revenue": 0.0, "cost": 0.0, "payments": 0})
            p["revenue"] += amt
            p["cost"] += float(t.get("total_cost") or 0) + float(t.get("paypal_fee") or 0)
            p["payments"] += 1
            name = (t.get("customer") or "").strip()
            if name:
                c = customers.setdefault(name.lower(), {"name": name, "total": 0.0, "payments": 0, "last": None})
                c["total"] += amt
                c["payments"] += 1
                c["last"] = max(c["last"] or t["date"], t["date"])
        for k in keys:   # profit per month exactly as Admin > Finances works it out (credits, PayPal fees, expenses)
            s = datetime.strptime(k, "%Y-%m")
            tot = await cmtv_finance._totals(s, _add_months(s, 1))
            rows[k].update(profit=tot["profit"], costs=tot["costs"], expenses=tot["expenses"])
        monthly = []
        for k in keys:
            r = rows[k]
            monthly.append({**{f: round(r[f], 2) for f in FAMILIES}, "month": k, "revenue": round(r["revenue"], 2),
                            "profit": round(r["profit"], 2), "costs": round(r["costs"], 2), "expenses": round(r["expenses"], 2),
                            "new_customers": r["new_customers"], "payments": r["payments"],
                            "partial": k == now.strftime("%Y-%m")})

        expenses = defaultdict(float)
        async for e in exp_col.find({"deleted": {"$ne": True}, "date": {"$gte": m_start, "$lt": m_end}}):
            expenses[e.get("category") or "Other"] += float(e.get("amount") or 0)

        # ---- the present, from billing ----
        settings = await D["get_settings"]()
        groups = {g.get("id"): g.get("name", "") for g in settings.get("product_groups", [])}
        products = {str(p["_id"]): p async for p in D["products"].find({})}
        active = defaultdict(int)
        by_term = defaultdict(int)
        weeks = [{"week": (now + timedelta(days=7 * i)).strftime("%Y-%m-%d"), **{f: 0 for f in FAMILIES}, "count": 0, "value": 0.0}
                 for i in range(13)]
        due90 = {"count": 0, "value": 0.0, "auto_renew": 0}
        async for s in D["services"].find({"status": "active"}):
            p = products.get(str(s.get("product_id")))
            if s.get("account_type") == "reseller" or s.get("is_trial") or (p or {}).get("is_trial"):
                continue
            fam = ov._family(p, groups, s.get("product_name", ""), s.get("panel_type", ""), s.get("cockpit_module", ""))
            fam = fam if fam in FAMILIES else "other"
            active[fam] += 1
            term, price = _first_price(p)
            if not (p and p.get("prices")) or price <= 0:
                by_term["Not set (imported)"] += 1   # lines copied in from the panels have no priced product
            else:
                by_term[{1: "1 month", 3: "3 months", 6: "6 months", 12: "12 months"}.get(term, f"{term} months")] += 1
            exp = s.get("expiry_date")
            if isinstance(exp, datetime) and now <= exp < now + timedelta(days=91):
                i = min(12, (exp - now).days // 7)
                weeks[i][fam] += 1
                weeks[i]["count"] += 1
                weeks[i]["value"] += price
                due90["count"] += 1
                due90["value"] += price
                due90["auto_renew"] += 1 if (s.get("auto_renew") or {}).get("status") == "ACTIVE" else 0
        for w in weeks:
            w["value"] = round(w["value"], 2)

        # ---- headline numbers ----
        full = [m for m in monthly if not m["partial"]]
        last3 = full[-3:]
        rev = sum(m["revenue"] for m in monthly)
        profit = sum(m["profit"] for m in monthly)
        prev_start = _add_months(m_start, -months)
        prev = await cmtv_finance._totals(prev_start, m_start)
        # only compare with the period before when the ledger covers all of it (it starts 2025-04)
        first = await tx_col.find_one({"deleted": {"$ne": True}, "date": {"$type": "date"}}, sort=[("date", 1)])
        if not first or first["date"] >= _add_months(prev_start, 1):
            prev["revenue"] = None
        top = sorted(customers.values(), key=lambda c: -c["total"])[:12]
        return {
            "months": months, "from": keys[0], "to": keys[-1],
            "kpis": {"revenue": round(rev, 2), "profit": round(profit, 2), "margin": round(profit * 100 / rev, 1) if rev else None,
                     "prev_revenue": prev["revenue"], "avg_month": round(sum(m["revenue"] for m in last3) / len(last3), 2) if last3 else None,
                     "new_customers": sum(m["new_customers"] for m in monthly), "payments": sum(m["payments"] for m in monthly),
                     "avg_payment": round(rev / max(1, sum(m["payments"] for m in monthly)), 2),
                     "active": sum(active.values()), "due90": {**due90, "value": round(due90["value"], 2)}},
            "monthly": monthly,
            "methods": sorted(({"method": k, "total": round(v, 2)} for k, v in methods.items()), key=lambda x: -x["total"]),
            "providers": sorted(({**p, "revenue": round(p["revenue"], 2), "cost": round(p["cost"], 2),
                                  "profit": round(p["revenue"] - p["cost"], 2),
                                  "margin": round((p["revenue"] - p["cost"]) * 100 / p["revenue"], 1) if p["revenue"] else None}
                                 for p in providers.values()), key=lambda x: -x["revenue"]),
            "expenses": sorted(({"category": k, "total": round(v, 2)} for k, v in expenses.items()), key=lambda x: -x["total"]),
            "top_customers": [{"name": c["name"], "total": round(c["total"], 2), "payments": c["payments"],
                               "last": c["last"].strftime("%Y-%m-%d") if c["last"] else None} for c in top],
            "active": dict(active), "by_term": dict(by_term), "renewals": weeks,
        }
