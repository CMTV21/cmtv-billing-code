"""CMTV Updates on the website (CMTV local addition 2026-09-28).

The user posts service news in the "CMTV Updates" Telegram channel; @Cmtv_support_bot already copies each post into the
customer group's Status/Outages topic. Now the bot also hands every post to billing (private bridge, same guard as the
ticket bridge):
  POST /api/cmtv/tickets-bridge/tg/updates        {id, text, reply_to, is_reply, created_at, edited}
  POST /api/cmtv/tickets-bridge/tg/updates/clear  (the bot's /clearstatus)
and the site shows them (components/cmtv/CmtvUpdates.js) on the dashboard, on the Support page and in the new-ticket
form, so customers see "we know, we're on it" before writing in.
  GET /api/cmtv/updates -> every post still in the channel (newest activity first, max 8), with its follow-ups.
The user deletes posts once they no longer apply; Telegram doesn't tell bots about deletions, so the bot checks every
10 min and reports deleted ones (POST .../tg/updates/delete), which hides them here.
A reply whose parent isn't known (backfilled rows) goes under the newest earlier post.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Body, Request

from cmtv_telegram_alerts import _bridge_auth

router = APIRouter(prefix="/api/cmtv/updates", tags=["cmtv-updates"])
bridge = APIRouter(prefix="/api/cmtv/tickets-bridge/tg/updates", tags=["cmtv-updates-bridge"])
D = {}
RECENT = timedelta(hours=48)


def init(**deps):
    D.update(deps)


def _when(v) -> datetime:
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt
    except (TypeError, ValueError):
        return datetime.utcnow()


@bridge.post("")
async def upsert(request: Request, data: dict = Body(...)):
    _bridge_auth(request)
    col = D["db"].cmtv_updates
    mid = int(data["id"])
    text = str(data.get("text") or "").strip()[:4000]
    now = datetime.utcnow()
    if data.get("edited"):
        await col.update_one({"_id": mid}, {"$set": {"text": text, "updated_at": now}})
        return {"ok": True}
    created = _when(data.get("created_at"))
    parent = data.get("reply_to")
    if data.get("is_reply") and not parent:
        prev = await col.find_one({"parent": None, "_id": {"$lt": mid}}, sort=[("_id", -1)])
        parent = prev["_id"] if prev else None
    await col.update_one({"_id": mid}, {"$set": {"text": text, "parent": int(parent) if parent else None,
                                                 "created_at": created, "updated_at": now},
                                        "$setOnInsert": {"hidden": False}}, upsert=True)
    return {"ok": True}


@bridge.post("/clear")
async def clear(request: Request):
    _bridge_auth(request)
    r = await D["db"].cmtv_updates.update_many({"hidden": {"$ne": True}}, {"$set": {"hidden": True, "hidden_at": datetime.utcnow()}})
    return {"ok": True, "hidden": r.modified_count}


@bridge.post("/delete")
async def deleted(request: Request, data: dict = Body(...)):
    """The post was deleted in the channel (the bot's 10-minute check)"""
    _bridge_auth(request)
    await D["db"].cmtv_updates.update_one({"_id": int(data["id"])}, {"$set": {"hidden": True, "deleted_in_channel": True,
                                                                             "hidden_at": datetime.utcnow()}})
    return {"ok": True}


@router.get("")
async def latest():
    col = D["db"].cmtv_updates
    # every post still in the channel (the user deletes the ones that no longer apply)
    tops = await col.find({"parent": None, "hidden": {"$ne": True}, "text": {"$ne": ""}}) \
        .sort("_id", -1).limit(8).to_list(8)
    items = []
    for t in tops:
        reps = await col.find({"parent": t["_id"], "hidden": {"$ne": True}, "text": {"$ne": ""}}).sort("_id", 1).to_list(20)
        last = max([t["created_at"]] + [r["created_at"] for r in reps])
        items.append({"id": t["_id"], "text": t["text"], "at": t["created_at"].isoformat() + "Z",
                      "last_at": last.isoformat() + "Z", "recent": datetime.utcnow() - last < RECENT,
                      "replies": [{"id": r["_id"], "text": r["text"], "at": r["created_at"].isoformat() + "Z"} for r in reps]})
    # newest activity first (a post with a fresh follow-up moves up)
    items.sort(key=lambda x: x["last_at"], reverse=True)
    return {"items": items}
