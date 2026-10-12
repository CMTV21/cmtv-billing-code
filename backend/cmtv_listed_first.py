"""Imperium "listed first" (CMTV local addition 2026-10-12; the owner: customers pick, Canada First by default).

The Imperium (Aether) panel added category profiles: which country's channel groups come first in the playlist.
  GET   /api/v1/reseller/category-profiles      -> [{id, name}]  (2026-10-12: 2 UK First, 3 AU First, 4 Italy First,
                                                   5 Canada First); 0 = the panel's Default order
  PATCH /api/v1/reseller/lines/username:<u>     {"category_profile_id": N}  -> applies at once (tested on a test line)
  every line reports category_profile_id / category_profile_name.
Billing:
  GET  /api/cmtv/imperium/listed-first               -> {options: [{id, name}], default_id}  (public; cached 1 h)
  GET  /api/cmtv/imperium/listed-first/{service_id}  -> the line's current choice, read from the panel (owner only)
  POST /api/cmtv/imperium/listed-first/{service_id}  {profile_id}  -> change it (owner of the line, or an admin)
  Order items may carry `listed_first` (profile id). after_provision(): every NEW Imperium line (paid or trial) gets the
  chosen profile, or Canada First when none was chosen. Renewals never touch it. Existing lines stay as they are
  (owner 2026-10-12) until the customer changes it. The choice is stored on service.cmtv_listed_first {id, name, at}.
  A failure never breaks provisioning: the line keeps the panel's Default order and Ops gets a note.
"""
import logging
import time
from datetime import datetime

from bson import ObjectId
from fastapi import APIRouter, Body, Depends, HTTPException

log = logging.getLogger("server")
router = APIRouter(prefix="/api/cmtv/imperium", tags=["cmtv-listed-first"])
D = {}
DEFAULT_NAME = "Canada First"
_cache = {"at": 0.0, "items": None}


def _oid(v):
    return ObjectId(v) if ObjectId.is_valid(str(v)) else None


async def _panel(index=0):
    from aether_service import get_aether_service
    panels = ((await D["get_settings"]()).get("aether") or {}).get("panels") or []
    if not panels:
        return None
    try:
        i = int(index or 0)
    except (TypeError, ValueError):
        i = 0
    return get_aether_service(panels[i if 0 <= i < len(panels) else 0])


async def profiles():
    """[{id, name}] from the panel (cached 1 h; the last good list is kept in cmtv_config when the panel is down)."""
    if _cache["items"] is not None and time.time() - _cache["at"] < 3600:
        return _cache["items"]
    items = None
    try:
        ae = await _panel()
        if ae:
            data = await ae._request("GET", f"{await ae._base()}/category-profiles", params={"per_page": 100})
            items = [{"id": int(p["id"]), "name": str(p["name"])} for p in (data.get("items") or []) if p.get("id") is not None]
    except Exception as e:
        log.warning(f"listed-first: couldn't read Imperium category profiles: {e}")
    if items:
        _cache.update(at=time.time(), items=items)
        await D["db"].cmtv_config.update_one({"_id": "listed_first"}, {"$set": {"profiles": items, "at": datetime.utcnow()}},
                                             upsert=True)
        return items
    saved = await D["db"].cmtv_config.find_one({"_id": "listed_first"}) or {}
    return saved.get("profiles") or []


def options_of(items):
    """Canada First first (the default), then the rest by name, then the panel's Default order (0)."""
    rest = sorted((p for p in items if p["name"] != DEFAULT_NAME), key=lambda p: p["name"])
    first = [p for p in items if p["name"] == DEFAULT_NAME]
    return first + rest + [{"id": 0, "name": "Default"}]


def default_id(items):
    return next((p["id"] for p in items if p["name"] == DEFAULT_NAME), 0)


def valid(items, pid):
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return None
    return pid if pid == 0 or any(p["id"] == pid for p in items) else None


def _name(items, pid):
    return "Default" if not pid else next((p["name"] for p in items if p["id"] == pid), f"#{pid}")


async def set_line(svc: dict, pid: int, items=None) -> dict:
    """Apply profile pid to the service's Imperium line and remember it. {"success", "name"} or {"success": False, "error"}."""
    items = items if items is not None else await profiles()
    user = svc.get("username") or svc.get("xtream_username")
    if not user:
        return {"success": False, "error": "this line has no username yet"}
    try:
        from aether_service import AetherService
        ae = await _panel(svc.get("panel_index"))
        await ae._request("PATCH", f"{await ae._base()}/lines/{AetherService.ref(user)}", json_data={"category_profile_id": int(pid)})
    except Exception as e:
        log.warning(f"listed-first: setting {pid} on {user} failed: {e}")
        return {"success": False, "error": str(getattr(e, "message", e))[:200]}
    name = _name(items, pid)
    await D["db"].services.update_one({"_id": svc["_id"]}, {"$set": {"cmtv_listed_first": {"id": int(pid), "name": name,
                                                                                         "at": datetime.utcnow()}}})
    log.info(f"listed-first: {user} -> {name}")
    return {"success": True, "id": int(pid), "name": name}


async def after_provision(order_id: str, order: dict):
    """New Imperium lines from this order get the chosen profile (or Canada First). Never raises."""
    try:
        new_items = [it for it in (order.get("items") or []) if not it.get("renewal_service_id")]
        if not new_items:
            return
        svcs = [s async for s in D["db"].services.find({"order_id": order_id, "panel_type": "aether",
                                                         "cmtv_listed_first": {"$exists": False},
                                                         "status": {"$nin": ["failed", "cancelled"]}})]
        if not svcs:
            return
        items = await profiles()
        if not items:
            log.warning(f"listed-first: no profile list for order {order_id}; lines keep the panel's Default order")
            return
        for s in svcs:
            it = next((i for i in new_items if str(i.get("product_id")) == str(s.get("product_id"))), new_items[0])
            pid = valid(items, it.get("listed_first"))
            pid = default_id(items) if pid is None else pid
            if not pid:   # Default chosen: nothing to send, just remember it
                await D["db"].services.update_one({"_id": s["_id"]}, {"$set": {"cmtv_listed_first": {"id": 0, "name": "Default",
                                                                                                     "at": datetime.utcnow()}}})
                continue
            r = await set_line(s, pid, items)
            if not r["success"]:
                try:
                    import cmtv_notify
                    await cmtv_notify.ops(f"⚠️ Imperium 'listed first' not set on new line {s.get('username')} "
                                          f"(order {order_id[:10]}): {r['error']}. The line works; it keeps the Default order.",
                                          kind="billing")
                except Exception:
                    pass
    except Exception as e:
        log.warning(f"listed-first after_provision failed for {order_id}: {e}")


def init(**deps):
    """deps: db, get_settings, get_current_user"""
    D.update(deps)
    current = deps["get_current_user"]

    @router.get("/listed-first")
    async def list_options():
        items = await profiles()
        return {"options": options_of(items), "default_id": default_id(items)}

    async def _own(service_id, user):
        svc = await D["db"].services.find_one({"_id": _oid(service_id)}) if _oid(service_id) else None
        is_admin = user.get("role") in ("admin", "staff")
        if not svc or (svc.get("user_id") != user.get("sub") and not is_admin):
            raise HTTPException(404, "Service not found")
        if svc.get("panel_type") != "aether":
            raise HTTPException(400, "This is only for Imperium lines")
        return svc

    @router.get("/listed-first/{service_id}")
    async def current_choice(service_id: str, current_user: dict = Depends(current)):
        svc = await _own(service_id, current_user)
        items = await profiles()
        pid = (svc.get("cmtv_listed_first") or {}).get("id")
        try:   # the panel is the truth (the owner may change it there)
            ae = await _panel(svc.get("panel_index"))
            line = (await ae.get_line(svc.get("username") or svc.get("xtream_username"))).get("line") or {}
            if "category_profile_id" in line:
                pid = int(line.get("category_profile_id") or 0)
        except Exception as e:
            log.info(f"listed-first: panel read failed for {service_id}: {e}")
        pid = pid or 0
        return {"id": pid, "name": _name(items, pid), "options": options_of(items)}

    @router.post("/listed-first/{service_id}")
    async def change(service_id: str, data: dict = Body(...), current_user: dict = Depends(current)):
        svc = await _own(service_id, current_user)
        if svc.get("status") not in ("active", "suspended", "expired"):
            raise HTTPException(400, "This line isn't set up yet")
        items = await profiles()
        pid = valid(items, (data or {}).get("profile_id"))
        if pid is None:
            raise HTTPException(400, "Unknown choice")
        r = await set_line(svc, pid, items)
        if not r["success"]:
            raise HTTPException(502, "Imperium didn't accept the change right now. Please try again in a minute.")
        return r
