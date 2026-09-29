"""CMTVGhost login codes for existing CCTV lines (CMTV local addition 2026-09-29).
The developer's update (3991516) gets a line's GhostAPK pin ("CMTVGhost code") from the CCTV (XtreamUI) panel when billing
CREATES a line, and stores it as service.ghostapk_code. Lines made before that, or made directly on the panel, have none.
This fills them in: hourly (first run 3 minutes after start), every active CCTV subscriber line without a code is looked up
on the panel (api.php?action=get_label_data, read-only there); a line with no pin yet is re-tried after 6 hours.
The dashboard (CmtvDashboardPage) and the developer's Services page show the code.
"""
import asyncio
import logging
from datetime import datetime, timedelta

log = logging.getLogger("server")
D = {}
RETRY_AFTER = timedelta(hours=6)


def init(**deps):
    D.update(deps)


async def fill_missing(limit: int = 300) -> dict:
    db = D["db"]
    panels = ((await D["get_settings"]()).get("xtream") or {}).get("panels") or []
    if not panels:
        return {"checked": 0, "found": 0}
    now = datetime.utcnow()
    q = {"status": "active", "panel_type": {"$in": ["xtream", "xuione"]}, "account_type": {"$ne": "reseller"},
         "ghostapk_code": {"$in": [None, ""]}, "cmtv_demo": {"$ne": True},
         "$or": [{"cmtv_ghostapk_checked_at": {"$exists": False}}, {"cmtv_ghostapk_checked_at": {"$lt": now - RETRY_AFTER}}]}
    todo = [s async for s in db.services.find(q).limit(limit)]
    if not todo:
        return {"checked": 0, "found": 0}
    by_panel, found = {}, 0
    for s in todo:
        by_panel.setdefault(int(s.get("panel_index") or 0), []).append(s)
    for idx, rows in by_panel.items():
        svc = D["get_xtream_service"](panels[idx] if idx < len(panels) else panels[0])
        if not svc or not await asyncio.to_thread(svc._session_login):
            log.warning(f"CMTVGhost codes: couldn't sign in to CCTV panel {idx}")
            continue
        for s in rows:
            user, pw = s.get("xtream_username") or s.get("username"), s.get("xtream_password") or s.get("password")
            code = ""
            if user and pw:
                code = await asyncio.to_thread(svc.get_ghostapk_code, user, pw, False)
            upd = {"cmtv_ghostapk_checked_at": datetime.utcnow()}
            if code:
                upd["ghostapk_code"] = code
                found += 1
            await db.services.update_one({"_id": s["_id"]}, {"$set": upd})
            await asyncio.sleep(0.3)   # gentle on the panel
    log.info(f"CMTVGhost codes: checked {len(todo)} line(s), found {found}")
    return {"checked": len(todo), "found": found}


async def _loop():
    await asyncio.sleep(180)
    while True:
        try:
            await fill_missing()
        except Exception as e:
            log.warning(f"CMTVGhost codes: {e}")
        await asyncio.sleep(3600)


async def startup():
    asyncio.create_task(_loop())
