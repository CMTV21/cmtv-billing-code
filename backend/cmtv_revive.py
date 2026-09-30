"""Services billing ended by itself, but renewed on the panel since -> active again (CMTV local addition 2026-09-30).

Billing's lifecycle job suspends a service when its end date passes ("Service expired") and cancels it after 30 days
suspended ("Suspended for 30+ days"). Many customers renew on the panel instead, so billing kept showing them as
ended. The developer's sync_services_expiry_from_imported_users() (hourly, after the panel sync) copies panel dates onto
active/expired/suspended services but never un-suspends, and never looks at cancelled ones.

revive() runs straight after it. A suspended or cancelled service goes back to active only when ALL hold:
- billing itself ended it: the latest lifecycle entry (expiry warnings ignored) is the system's "Service expired"
  suspension, or the system's 30-day cancel (never a suspension/cancel made by a person);
- its panel line (find_imported_for_service: same panel, never a reseller row) is enabled with a future end date;
- the customer has no other live service for the same line (no duplicates).
It sets status active + the panel's end date, keeps the history (cmtv_revived_*), writes a lifecycle entry and posts one
silent note to Ops Billing. Nothing else changes (no emails to customers).
"""
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)
LIVE = ["active", "suspended", "expired"]


def _dt(v):
    if isinstance(v, datetime):
        return v.replace(tzinfo=None)
    if isinstance(v, str):
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            return None
    return None


async def _ended_by_billing(db, service) -> bool:
    logs = [l async for l in db.lifecycle_logs.find(
        {"service_id": str(service["_id"]), "action": {"$not": {"$regex": "^expiry_warning"}}}).sort("created_at", -1).limit(1)]
    if not logs:
        return False
    last = logs[0]
    if last.get("triggered_by") != "system":
        return False
    if service.get("status") == "suspended":
        return last.get("action") == "suspend" and last.get("reason") == "Service expired"
    return last.get("action") == "cancel" and str(last.get("reason", "")).startswith("Suspended for")


async def revive(db, find_imported, dry_run: bool = False) -> list:
    now = datetime.utcnow()
    done = []
    async for s in db.services.find({"status": {"$in": ["suspended", "cancelled"]}, "xtream_username": {"$nin": ["", None]}}):
        imported = await find_imported(s)
        if not imported or imported.get("status") != "active":
            continue
        panel_end = _dt(imported.get("expiry_date"))
        unlimited = panel_end is None and bool(imported.get("expiry_unlimited"))
        if not unlimited and (panel_end is None or panel_end <= now + timedelta(days=1)):  # a day's margin: no flip-flop on the last day
            continue
        if not await _ended_by_billing(db, s):
            continue
        twin = {"_id": {"$ne": s["_id"]}, "xtream_username": s["xtream_username"], "status": {"$in": LIVE}}
        if s.get("panel_type"):
            twin["panel_type"] = s["panel_type"]
        if await db.services.find_one(twin):
            continue
        row = {"id": str(s["_id"]), "username": s["xtream_username"], "was": s.get("status"),
               "panel_end": "no end date" if unlimited else panel_end.strftime("%Y-%m-%d")}
        done.append(row)
        if dry_run:
            continue
        await db.services.update_one({"_id": s["_id"], "status": s.get("status")}, {"$set": {
            "status": "active", "expiry_date": None if unlimited else panel_end, "suspended_at": None,
            "cmtv_revived_at": now, "cmtv_revived_from": s.get("status"), "expiry_synced_at": now}})
        await db.lifecycle_logs.insert_one({
            "service_id": str(s["_id"]), "user_id": s.get("user_id"), "action": "reactivate",
            "reason": f"Renewed on the panel (ends {row['panel_end']})", "triggered_by": "system",
            "old_status": s.get("status"), "new_status": "active", "created_at": now})
    if done and not dry_run:
        logger.info(f"CMTV revive: {len(done)} services ended by billing but renewed on the panel set back to active")
        try:
            import cmtv_notify
            names = ", ".join(r["username"] for r in done[:40]) + (f" and {len(done) - 40} more" if len(done) > 40 else "")
            await cmtv_notify.ops(f"🔄 {len(done)} service(s) billing showed as ended were renewed on the panel, "
                                  f"now active again in billing: {names}", "billing", silent=True)
        except Exception as e:
            logger.warning(f"CMTV revive: Ops note not sent ({type(e).__name__})")
    return done
