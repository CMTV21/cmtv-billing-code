"""Admin > Customers, phone-first (CMTV local addition 2026-10-05; the owner: the developer's customer table "isn't mobile
friendly"). One search across name, email and every service login (TV line, Nuvio / Stremio, CMTVpn, Audiobooks), quick
filters, and a card per customer with their main service, status and end date. The developer's page stays at
/admin/customers-classic (it has Add customer and Delete).
GET /api/cmtv/admin/customers-list?q=&filter=all|active|soon|ended|trials|panel|new&limit=
"""
import re
from datetime import datetime, timedelta

from bson import ObjectId
from fastapi import APIRouter, Depends

import cmtv_lines as L

router = APIRouter(prefix="/api/cmtv/admin/customers-list", tags=["cmtv-customers-list"])
D = {}
# CMTV local change 2026-10-08: nxtdash is the old Imperium panel (was labelled "Amethyst")
SERVER = {"xtream": "CCTV", "aether": "Imperium", "nxtdash": "Imperium (old panel)", "onestream": "OneStream", "manual": "Add-on"}
MODULE = {"nuviocloud": "Nuvio", "nuvio": "Stremio", "vpn": "CMTVpn", "audiobooks": "Audiobooks", "nuvio_reseller": "Nuvio reseller"}
FILTERS = ["all", "active", "soon", "ended", "trials", "panel", "new"]


def init(**deps):
    D.update(deps)


def _dt(v):
    """Some older service records keep the end date as text."""
    if isinstance(v, datetime):
        return v
    if isinstance(v, str) and v.strip():
        try:
            return datetime.fromisoformat(v.strip().replace("Z", "").replace(" ", "T")[:19])
        except ValueError:
            return None
    return None


TV = ("xtream", "aether", "nxtdash", "onestream")


def _card(u, svcs, now, panel_view=None):
    for s in svcs:
        s["expiry_date"] = _dt(s.get("expiry_date"))
    email = str(u.get("email") or "")
    panel = email.lower().endswith("@panel.local")
    live = [s for s in svcs if s.get("status") == "active" and s.get("expiry_date") and s["expiry_date"] > now]
    # CMTV local change 2026-10-08: shared trial rule (cmtv_lines): a trial line paid for and extended is not "Trial"
    paid_live = [s for s in live if L.is_paid_line(s, now)]
    main = min(paid_live or live, key=lambda s: s["expiry_date"]) if (paid_live or live) else \
        (max(svcs, key=lambda s: s.get("expiry_date") or datetime.min) if svcs else None)
    days = (main["expiry_date"] - now).days if main and main.get("expiry_date") else None
    if paid_live:
        state = "active"
    elif live:
        state = "trial"
    elif svcs:
        state = "ended"
    else:
        state = "none"
    label = None
    if main:
        label = MODULE.get(main.get("cockpit_module")) or SERVER.get(main.get("panel_type"), main.get("panel_type") or "")
    # 2026-10-08 (owner: "search a customer, click the server they have and extend them"): every TV line on the card, live
    # or ended in the last 60 days, with the panel's end date when it's later than billing's (renewed on the panel)
    lines = []
    for s in svcs:
        if s.get("panel_type") not in TV or s.get("account_type") == "reseller" or s.get("status") in ("cancelled", "removed"):
            continue
        login = s.get("xtream_username") or s.get("username") or ""
        iu = (panel_view or {}).get((login.lower(), s.get("panel_type")))
        end, pend = s.get("expiry_date"), _dt((iu or {}).get("expiry_date"))
        if pend and (not end or pend > end):
            end = pend
        if end and end < now - timedelta(days=60):
            continue
        lines.append({"service_id": str(s["_id"]), "server": "Imperium (old panel)" if s.get("panel_type") == "nxtdash" else SERVER.get(s.get("panel_type")),
                      "login": login, "ends": end, "days_left": (end - now).days if end else None, "trial": L.is_trial_line(s, now),
                      "devices": int(s.get("max_connections") or 0) or None,
                      "can_extend": s.get("panel_type") in ("xtream", "aether") and bool(login),
                      "why_not": "old Imperium record: needs moving to the new panel first" if s.get("panel_type") == "nxtdash" else
                                 "" if s.get("panel_type") in ("xtream", "aether") else "this server can't be extended here"})
    lines.sort(key=lambda x: (x["ends"] is None, x["ends"] or now))
    return {"id": str(u["_id"]), "name": u.get("name") or "", "email": "" if panel else email, "panel_only": panel, "lines": lines,
            "login": (main or {}).get("xtream_username") or (main or {}).get("username") or u.get("panel_username") or "",
            "state": state, "server": label, "plan": (main or {}).get("product_name"), "ends": (main or {}).get("expiry_date"),
            "days_left": days, "services": len(svcs), "live_services": len(live), "created_at": u.get("created_at"),
            "credit": float(u.get("credit_balance") or 0)}


def init_routes():
    admin = D["get_current_admin_user"]

    @router.get("")
    async def customers(q: str = "", filter: str = "all", limit: int = 40, current_user: dict = Depends(admin)):
        db = D["db"]
        now = datetime.utcnow()
        q = (q or "").strip()[:80]
        uq = {"role": "user", "cmtv_demo": {"$ne": True}}
        ids = None
        if len(q) >= 2:
            rx = {"$regex": re.escape(q), "$options": "i"}
            ids = {str(u["_id"]) async for u in db.users.find({**uq, "$or": [{"name": rx}, {"email": rx}, {"panel_username": rx}]}, {"_id": 1})}
            async for s in db.services.find({"$or": [{"username": rx}, {"xtream_username": rx}]}, {"user_id": 1}):
                ids.add(str(s.get("user_id")))
        users = [u async for u in db.users.find({**uq, **({"_id": {"$in": [ObjectId(i) for i in ids if ObjectId.is_valid(i)]}} if ids is not None else {})},
                                                {"name": 1, "email": 1, "panel_username": 1, "created_at": 1, "credit_balance": 1})]
        by_user = {}
        async for s in db.services.find({"user_id": {"$in": [str(u["_id"]) for u in users]}, "status": {"$nin": ["failed", "duplicate"]}},
                                        {"user_id": 1, "status": 1, "expiry_date": 1, "is_trial": 1, "panel_type": 1, "cockpit_module": 1,
                                         "product_name": 1, "username": 1, "xtream_username": 1, "account_type": 1, "max_connections": 1,
                                         "created_at": 1}):
            by_user.setdefault(str(s["user_id"]), []).append(s)
        pv = {}   # 2026-10-08: the panels' view of each line (hourly panel sync)
        async for iu in db.imported_users.find({"account_type": {"$ne": "reseller"}}, {"username": 1, "panel_type": 1, "expiry_date": 1}):
            pv[(str(iu.get("username") or "").lower(), iu.get("panel_type"))] = iu
        cards = [_card(u, by_user.get(str(u["_id"]), []), now, pv) for u in users]
        week = now - timedelta(days=7)
        test = {
            "all": lambda c: True,
            "active": lambda c: c["state"] == "active",
            "soon": lambda c: c["state"] == "active" and c["days_left"] is not None and c["days_left"] <= 14,
            "ended": lambda c: c["state"] == "ended",
            "trials": lambda c: c["state"] == "trial",
            "panel": lambda c: c["panel_only"],
            "new": lambda c: bool(c["created_at"]) and c["created_at"] >= week,
        }
        counts = {f: sum(1 for c in cards if test[f](c)) for f in FILTERS}
        f = filter if filter in test else "all"
        shown = [c for c in cards if test[f](c)]
        if f == "soon":
            shown.sort(key=lambda c: c["days_left"])
        elif f == "new" or not q:
            shown.sort(key=lambda c: c["created_at"] or datetime.min, reverse=True)
        return {"counts": counts, "total": len(shown), "rows": shown[:max(10, min(int(limit or 40), 500))]}
