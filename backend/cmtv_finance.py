"""CMTV finances: one ledger for all income, costs and profit (CMTV local addition 2026-09-25).

Replaces the "CMTV Financials.xlsx" workflow (history imported once by scripts/import_finances.py):
- fin_transactions: every payment. source = "import" (the spreadsheet, up to 2026-09-30), "billing" (paid billing
  orders from the cut-over date, added automatically), or "manual" (recorded in Admin > Finances).
- fin_expenses: running costs by category.
- fin_config (one doc): cost per credit per server (with dates), credits per plan, PayPal fee, cut-over date.
The maths follows the spreadsheet: fee = round(amount*3.49% + 0.49, 2) for PayPal; cost = credits * cost per credit;
profit = amount - cost - fee; a month's costs = credit costs + PayPal fees + expenses (the Dashboard sheet's definition).
Rows are never hard-deleted: "deleted" rows are kept with deleted=True and ignored everywhere.
"""
import asyncio
import io
import logging
from datetime import datetime, timedelta
from typing import Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/cmtv/finance", tags=["cmtv-finance"])
D = {}

METHODS = ["e-Transfer", "PayPal", "Other"]
EXPENSE_CATEGORIES = ["Hosting", "Telecom", "Software", "Platform", "Marketing", "Equipment", "Other"]
DEFAULT_CONFIG = {
    "_id": "config",
    "cutover": datetime(2026, 10, 1),
    "paypal_fee": {"pct": 0.0349, "fixed": 0.49},
    # cost per credit; a server can have several rates, each from a date (latest one on or before the payment date wins)
    "rates": [
        {"server": "CCTV", "cost_per_credit": 1.0, "from": None},
        {"server": "CCTV", "cost_per_credit": 1.25, "from": datetime(2026, 4, 1)},
        {"server": "Amethyst", "cost_per_credit": 3.5, "from": None},
        {"server": "OK4", "cost_per_credit": 6.0, "from": None},
        {"server": "Extreme", "cost_per_credit": 1.0, "from": None},
        {"server": "Stremio", "cost_per_credit": 0.0, "from": None},
        {"server": "VPN365", "cost_per_credit": 1.8, "from": None},
        {"server": "Imperium", "cost_per_credit": 3.0, "from": None},
        {"server": "Onetime", "cost_per_credit": 0.0, "from": None},
        {"server": "ABS", "cost_per_credit": 0.0, "from": None},
        {"server": "CMTVpn", "cost_per_credit": 0.0, "from": None},
        {"server": "CMTV+", "cost_per_credit": 0.0, "from": None},
    ],
    # credits a plan uses: (server, connections, months) -> credits. From the user's pricing sheet, 2026-09-25.
    "credits": (
        [{"server": "CCTV", "connections": c, "months": m, "credits": v} for c, row in {
            1: {1: 0.5, 3: 1.5, 6: 3, 12: 6}, 2: {1: 1, 3: 3, 6: 6, 12: 12},
            4: {1: 2, 3: 4, 6: 8, 12: 16}, 6: {1: 3, 3: 6, 6: 12, 12: 24}}.items() for m, v in row.items()]
        + [{"server": "Imperium", "connections": c, "months": m, "credits": v} for c, row in {
            1: {1: 1, 3: 3, 6: 6, 12: 12}, 2: {1: 2, 3: 4, 6: 8, 12: 14}, 3: {1: 3, 3: 6, 6: 10, 12: 16},
            4: {1: 4, 3: 8, 6: 12, 12: 18}, 5: {1: 5, 3: 10, 6: 14, 12: 20}}.items() for m, v in row.items()]
    ),
}


def init(**deps):
    D.update(deps)
    db = deps["db"]
    D["tx"], D["exp"], D["cfg"] = db.fin_transactions, db.fin_expenses, db.fin_config


async def startup():
    await D["tx"].create_index("date")
    await D["tx"].create_index("order_id", unique=True, partialFilterExpression={"order_id": {"$type": "string"}})
    await D["exp"].create_index("date")
    if not await D["cfg"].find_one({"_id": "config"}):
        await D["cfg"].insert_one(DEFAULT_CONFIG)
    asyncio.create_task(_sync_loop())


async def config():
    return await D["cfg"].find_one({"_id": "config"}) or DEFAULT_CONFIG


# ---------------- maths (mirrors the spreadsheet) ----------------

def cost_per_credit(cfg, server, when):
    best, best_from = 0.0, None
    for r in cfg.get("rates", []):
        if r["server"].lower() != str(server).lower():
            continue
        f = r.get("from")
        if (f is None or f <= when) and (best_from is None or (f or datetime.min) >= best_from):
            best, best_from = float(r["cost_per_credit"]), (f or datetime.min)
    return best


def paypal_fee(cfg, method, amount):
    if method != "PayPal" or not amount:
        return 0.0
    p = cfg.get("paypal_fee") or {}
    return round(amount * float(p.get("pct", 0.0349)) + float(p.get("fixed", 0.49)), 2)


def complete(cfg, row):
    """Fill cost_per_credit, paypal_fee, total_cost and profit for a new/edited row"""
    amount = float(row.get("amount") or 0)
    credits = float(row.get("credits") or 0)
    cpc = row.get("cost_per_credit")
    cpc = cost_per_credit(cfg, row["server"], row["date"]) if cpc in (None, "") else float(cpc)
    fee = paypal_fee(cfg, row.get("method"), amount)
    total = round(credits * cpc, 2)
    row.update(amount=amount, credits=credits, cost_per_credit=cpc, paypal_fee=fee, total_cost=total,
               profit=round(amount - total - fee, 2))
    return row


def credits_for(cfg, server, connections, months):
    for c in cfg.get("credits", []):
        if c["server"] == server and int(c["connections"]) == int(connections or 0) and int(c["months"]) == int(months or 0):
            return float(c["credits"])
    return None


# ---------------- billing orders -> ledger ----------------

def _server_for(product, group_names):
    """Ledger 'server' for a billing product (the spreadsheet's names)"""
    name = str((product or {}).get("name", "")).strip().lower()
    group = str(group_names.get((product or {}).get("group_id"), "")).lower()
    for key, server in (("audiobook", "ABS"), ("cmtvpn", "CMTVpn"), ("cmtv+", "CMTV+"), ("stremio", "Stremio")):
        if key in name:
            return server
    if "imperium" in name or "imperium" in group or (product or {}).get("panel_type") == "aether":
        return "Imperium"
    return "CCTV"


def _method_for(order):
    m = str(order.get("payment_method") or "").lower()
    if m.startswith("paypal"):
        return "PayPal"
    if m in ("emt", "e-transfer", "etransfer", "interac"):
        return "e-Transfer"
    if m == "manual" and not order.get("payment_method_recorded"):
        return "e-Transfer"   # before 2026-09-25 every non-PayPal order said "manual"; nearly all were e-Transfers
    import cmtv_payments   # the recorded method's name (GhostPay, Manual, Cash, ...) - 2026-09-25
    return cmtv_payments.order_label(order)


async def sync_billing_orders():
    """Add paid billing orders from the cut-over date that aren't in the ledger yet. Safe to run any time."""
    cfg = await config()
    settings = await D["get_settings"]()
    groups = {g.get("id"): g.get("name") for g in settings.get("product_groups", [])}
    added, review = 0, 0
    async for o in D["orders"].find({"status": "paid", "paid_at": {"$gte": cfg["cutover"]}, "total": {"$gt": 0}}):
        oid = str(o["_id"])
        if await D["tx"].find_one({"order_id": oid}):
            continue
        user = await D["users"].find_one({"_id": ObjectId(o["user_id"])}) if ObjectId.is_valid(str(o.get("user_id"))) else None
        first_paid = await D["orders"].find_one({"user_id": o["user_id"], "status": "paid"}, sort=[("paid_at", 1)])
        credits, note = 0.0, []
        server = None
        for it in o.get("items", []):
            p = await D["products"].find_one({"_id": ObjectId(it["product_id"])}) if ObjectId.is_valid(str(it.get("product_id"))) else None
            server = server or _server_for(p, groups)
            months = int(it.get("term_months") or 1)
            if (p or {}).get("account_type") == "reseller":
                c = float((p or {}).get("reseller_credits") or 0)
            else:
                c = credits_for(cfg, _server_for(p, groups), (p or {}).get("max_connections"), months)
            if c is None and cost_per_credit(cfg, _server_for(p, groups), o.get("paid_at") or datetime.utcnow()) == 0:
                c = 0.0   # own services (Stremio, CMTVpn, CMTV+, audiobooks) don't use paid credits
            if c is None:
                c = 0.0
                note.append(f"credits unknown for {it.get('product_name')}")
            credits += c
        row = complete(cfg, {
            "date": o.get("paid_at"), "server": server or "CCTV",
            "customer": (user or {}).get("name") or (user or {}).get("email") or "",
            "customer_email": (user or {}).get("email", ""), "user_id": o.get("user_id"),
            "new_user": bool(first_paid and first_paid["_id"] == o["_id"]),
            "amount": float(o.get("total") or 0), "method": _method_for(o), "credits": credits,
            "notes": "; ".join([i.get("product_name", "") for i in o.get("items", [])] + note),
            "source": "billing", "order_id": oid, "auto_renewal": bool(o.get("auto_renewal")),
            "needs_review": bool(note), "created_at": datetime.utcnow(),
        })
        try:
            await D["tx"].insert_one(row)
            added += 1
            review += bool(note)
        except Exception:   # duplicate order_id from a parallel run
            pass
    if added:
        logger.info(f"finance: {added} billing orders added to the ledger ({review} need a credits check)")
    return {"added": added, "needs_review": review}


async def _sync_loop():
    await asyncio.sleep(30)
    while True:
        try:
            await sync_billing_orders()
        except Exception as e:
            logger.error(f"finance sync failed: {type(e).__name__}: {e}")
        await asyncio.sleep(600)


# ---------------- summary ----------------

def _month_start(d):
    return d.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _add_months(d, n):
    y, m = divmod(d.month - 1 + n, 12)
    return d.replace(year=d.year + y, month=m + 1, day=1)


async def _totals(start, end):
    live = {"date": {"$gte": start, "$lt": end}, "deleted": {"$ne": True}}
    t = await D["tx"].aggregate([{"$match": live}, {"$group": {
        "_id": None, "revenue": {"$sum": "$amount"}, "credit_cost": {"$sum": "$total_cost"},
        "fees": {"$sum": "$paypal_fee"}, "new_users": {"$sum": {"$cond": ["$new_user", 1, 0]}}, "count": {"$sum": 1}}}]).to_list(1)
    e = await D["exp"].aggregate([{"$match": live}, {"$group": {"_id": None, "total": {"$sum": "$amount"}}}]).to_list(1)
    t = t[0] if t else {"revenue": 0, "credit_cost": 0, "fees": 0, "new_users": 0, "count": 0}
    expenses = e[0]["total"] if e else 0.0
    costs = t["credit_cost"] + t["fees"] + expenses
    return {"revenue": round(t["revenue"], 2), "credit_cost": round(t["credit_cost"], 2), "fees": round(t["fees"], 2),
            "expenses": round(expenses, 2), "costs": round(costs, 2), "profit": round(t["revenue"] - costs, 2),
            "new_users": t["new_users"], "payments": t["count"]}


async def summary(month: Optional[str] = None):
    now = datetime.utcnow()
    m0 = datetime.strptime(month, "%Y-%m") if month else _month_start(now)
    m1 = _add_months(m0, 1)
    prev = _add_months(m0, -1)
    y0 = m0.replace(month=1)
    out = {
        "month": m0.strftime("%Y-%m"),
        "mtd": await _totals(m0, m1), "prev": await _totals(prev, m0), "ytd": await _totals(y0, m1),
        "all": await _totals(datetime(2000, 1, 1), datetime(2100, 1, 1)),
        "months": [],
    }
    for i in range(11, -1, -1):
        s = _add_months(m0, -i)
        tot = await _totals(s, _add_months(s, 1))
        out["months"].append({"month": s.strftime("%Y-%m"), **tot})
    by_server = await D["tx"].aggregate([{"$match": {"deleted": {"$ne": True}}}, {"$group": {
        "_id": "$server", "revenue": {"$sum": "$amount"}, "cost": {"$sum": "$total_cost"}, "fees": {"$sum": "$paypal_fee"},
        "count": {"$sum": 1}}}, {"$sort": {"revenue": -1}}]).to_list(100)
    out["servers"] = [{"server": s["_id"], "revenue": round(s["revenue"], 2), "cost": round(s["cost"] + s["fees"], 2),
                       "margin": round((s["revenue"] - s["cost"] - s["fees"]) / s["revenue"], 4) if s["revenue"] else None,
                       "payments": s["count"]} for s in by_server]
    cats = await D["exp"].aggregate([{"$match": {"deleted": {"$ne": True}}}, {"$group": {
        "_id": "$category", "total": {"$sum": "$amount"}}}, {"$sort": {"total": -1}}]).to_list(50)
    out["expense_categories"] = [{"category": c["_id"], "total": round(c["total"], 2)} for c in cats]
    # what only billing knows
    soon = now + timedelta(days=30)
    active = D["services"].find({"status": "active", "user_id": {"$nin": [None, ""]}}, {"expiry_date": 1, "panel_type": 1, "auto_renew": 1})
    n_active = due = 0
    async for s in active:
        n_active += 1
        e = s.get("expiry_date")
        if isinstance(e, str):
            try:
                e = datetime.fromisoformat(e.replace("Z", "").split(".")[0])
            except ValueError:
                e = None
        if isinstance(e, datetime) and now <= e <= soon:
            due += 1
    out["billing"] = {
        "active_services": n_active, "due_30d": due,
        "auto_renew": await D["services"].count_documents({"auto_renew.status": "ACTIVE"}),
        "paying_customers": len(await D["orders"].distinct("user_id", {"status": "paid"})),
        "needs_review": await D["tx"].count_documents({"needs_review": True, "deleted": {"$ne": True}}),
    }
    return out


# ---------------- export ----------------

async def export_xlsx():
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    wb = Workbook()
    ws = wb.active
    ws.title = "Transaction Log"
    head = ["Date", "Server", "New User", "Amount Received", "Payment Method", "PayPal Fee", "Credits Used",
            "Cost per Credit", "Total Cost", "Total Profit", "Notes", "Source"]
    ws.append(head)
    async for t in D["tx"].find({"deleted": {"$ne": True}}).sort("date", 1):
        ws.append([t["date"], t.get("server"), "yes" if t.get("new_user") else "no", t.get("amount"), t.get("method") or "",
                   t.get("paypal_fee") or None, t.get("credits"), t.get("cost_per_credit"), t.get("total_cost"), t.get("profit"),
                   t.get("customer") if t.get("source") != "import" else (t.get("customer") or t.get("notes")), t.get("source")])
    e = wb.create_sheet("Expenses")
    e.append(["Date", "Category", "Description", "Amount", "Notes"])
    async for x in D["exp"].find({"deleted": {"$ne": True}}).sort("date", 1):
        e.append([x["date"], x.get("category"), x.get("description"), x.get("amount"), x.get("notes")])
    for sheet in (ws, e):
        for c in sheet[1]:
            c.font = Font(name="Arial", bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", fgColor="1F2A44")
        for row in sheet.iter_rows(min_row=2):
            for c in row:
                c.font = Font(name="Arial")
                if isinstance(c.value, datetime):
                    c.number_format = "yyyy-mm-dd"
        sheet.freeze_panes = "A2"
        for col in sheet.columns:
            sheet.column_dimensions[col[0].column_letter].width = 16
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


# ---------------- API (admin only) ----------------

def _clean_date(v):
    try:
        return datetime.strptime(str(v)[:10], "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Enter the date as YYYY-MM-DD")


def _row_out(r):
    r["id"] = str(r.pop("_id"))
    return r


def init_routes():
    admin = D["get_current_admin_user"]

    @router.get("/summary")
    async def api_summary(month: Optional[str] = None, user=Depends(admin)):
        return await summary(month)

    @router.get("/config")
    async def api_config(user=Depends(admin)):
        c = await config()
        servers = sorted({r["server"] for r in c.get("rates", [])})
        return {"cutover": c["cutover"], "paypal_fee": c["paypal_fee"], "rates": c["rates"], "credits": c["credits"],
                "servers": servers, "methods": METHODS, "expense_categories": EXPENSE_CATEGORIES}

    @router.put("/config/rate")
    async def api_set_rate(data: dict, user=Depends(admin)):
        """Change a server's cost per credit from a date onward (earlier payments keep their old rate)"""
        server = str(data.get("server") or "").strip()
        if not server:
            raise HTTPException(status_code=400, detail="Server is required")
        rate = {"server": server, "cost_per_credit": float(data.get("cost_per_credit") or 0),
                "from": _clean_date(data["from"]) if data.get("from") else None}
        await D["cfg"].update_one({"_id": "config"}, {"$push": {"rates": rate}})
        return {"ok": True}

    @router.get("/transactions")
    async def api_transactions(month: Optional[str] = None, q: str = "", source: str = "", user=Depends(admin)):
        f = {"deleted": {"$ne": True}}
        if month:
            m0 = datetime.strptime(month, "%Y-%m")
            f["date"] = {"$gte": m0, "$lt": _add_months(m0, 1)}
        if source:
            f["source"] = source
        if q:
            import re
            rx = {"$regex": re.escape(q.strip()[:80]), "$options": "i"}
            f["$or"] = [{"customer": rx}, {"notes": rx}, {"server": rx}]
        rows = await D["tx"].find(f).sort("date", -1).to_list(1000)
        return [_row_out(r) for r in rows]

    @router.post("/transactions")
    async def api_add_transaction(data: dict, user=Depends(admin)):
        cfg = await config()
        server = str(data.get("server") or "").strip()
        if not server:
            raise HTTPException(status_code=400, detail="Choose a server")
        try:
            amount = float(data.get("amount"))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Enter the amount received")
        row = complete(cfg, {
            "date": _clean_date(data.get("date")), "server": server, "customer": str(data.get("customer") or "").strip(),
            "new_user": bool(data.get("new_user")), "amount": amount,
            "method": data.get("method") if data.get("method") in METHODS else "Other",
            "credits": data.get("credits") or 0, "cost_per_credit": data.get("cost_per_credit"),
            "notes": str(data.get("notes") or "").strip(), "source": "manual",
            "created_at": datetime.utcnow(), "created_by": user.get("email"),
        })
        res = await D["tx"].insert_one(row)
        return _row_out(await D["tx"].find_one({"_id": res.inserted_id}))

    @router.put("/transactions/{tx_id}")
    async def api_edit_transaction(tx_id: str, data: dict, user=Depends(admin)):
        old = await D["tx"].find_one({"_id": ObjectId(tx_id)}) if ObjectId.is_valid(tx_id) else None
        if not old:
            raise HTTPException(status_code=404, detail="Payment not found")
        cfg = await config()
        row = {k: old[k] for k in ("date", "server", "customer", "new_user", "amount", "method", "credits", "notes") if k in old}
        for k in ("server", "customer", "notes", "method"):
            if k in data:
                row[k] = str(data[k] or "").strip()
        if "date" in data:
            row["date"] = _clean_date(data["date"])
        if "amount" in data:
            row["amount"] = float(data["amount"] or 0)
        if "credits" in data:
            row["credits"] = float(data["credits"] or 0)
        if "new_user" in data:
            row["new_user"] = bool(data["new_user"])
        row["cost_per_credit"] = data.get("cost_per_credit")
        complete(cfg, row)
        row.update(needs_review=False, updated_at=datetime.utcnow(), updated_by=user.get("email"))
        await D["tx"].update_one({"_id": old["_id"]}, {"$set": row})
        return _row_out(await D["tx"].find_one({"_id": old["_id"]}))

    @router.delete("/transactions/{tx_id}")
    async def api_remove_transaction(tx_id: str, user=Depends(admin)):
        res = await D["tx"].update_one({"_id": ObjectId(tx_id)} if ObjectId.is_valid(tx_id) else {"_id": None},
                                       {"$set": {"deleted": True, "deleted_at": datetime.utcnow(), "deleted_by": user.get("email")}})
        if not res.matched_count:
            raise HTTPException(status_code=404, detail="Payment not found")
        return {"ok": True}

    @router.get("/expenses")
    async def api_expenses(user=Depends(admin)):
        return [_row_out(r) for r in await D["exp"].find({"deleted": {"$ne": True}}).sort("date", -1).to_list(2000)]

    @router.post("/expenses")
    async def api_add_expense(data: dict, user=Depends(admin)):
        try:
            amount = float(data.get("amount"))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Enter the amount")
        row = {"date": _clean_date(data.get("date")),
               "category": data.get("category") if data.get("category") in EXPENSE_CATEGORIES else "Other",
               "description": str(data.get("description") or "").strip(), "amount": round(amount, 2),
               "notes": str(data.get("notes") or "").strip(), "source": "manual",
               "created_at": datetime.utcnow(), "created_by": user.get("email")}
        res = await D["exp"].insert_one(row)
        return _row_out(await D["exp"].find_one({"_id": res.inserted_id}))

    @router.delete("/expenses/{exp_id}")
    async def api_remove_expense(exp_id: str, user=Depends(admin)):
        res = await D["exp"].update_one({"_id": ObjectId(exp_id)} if ObjectId.is_valid(exp_id) else {"_id": None},
                                        {"$set": {"deleted": True, "deleted_at": datetime.utcnow(), "deleted_by": user.get("email")}})
        if not res.matched_count:
            raise HTTPException(status_code=404, detail="Expense not found")
        return {"ok": True}

    @router.post("/sync")
    async def api_sync(user=Depends(admin)):
        return await sync_billing_orders()

    @router.get("/export")
    async def api_export(user=Depends(admin)):
        buf = await export_xlsx()
        name = f"CMTV-finances-{datetime.utcnow():%Y-%m-%d}.xlsx"
        return StreamingResponse(buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                 headers={"Content-Disposition": f'attachment; filename="{name}"'})
