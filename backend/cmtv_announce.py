"""Customer updates in the "App updates" Telegram topic (CMTV local addition 2026-09-30).

The owner wants customers told about every customer-relevant new feature or good change, across all products (Nuvio,
CMTVGhost, web player, billing website, TV service). Admin > Notices "Post a customer update": product + title + a few
lines -> one formatted post in the App updates topic of the CMTV User Support group (topic set in Admin > Nuvio > App,
cmtv_config {_id: "nuvio_app_announce"}), sent by the support bot; logged in `cmtv_announcements`.
Nuvio app releases can also post their changelog from the Nuvio App tab (cmtv_nuvio.post_changelog).

2026-10-02 (the owner): ONE changelog a day. Customer-relevant changes are queued during the day (`cmtv_changelog`,
Admin > Notices "Tonight's changelog", or queue_add() from scripts) and posted together at 7:00 pm Toronto time; nothing
queued = no post. Items added after the post go into the next day's. Admin can remove items before 7 pm or post early.
"""
import asyncio
import logging
from datetime import datetime, timedelta
from html import escape
from zoneinfo import ZoneInfo

import httpx
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/cmtv/announce", tags=["cmtv-announce"])
D = {}

PRODUCTS = {
    "general": "✨ CMTV", "tv": "📡 TV service", "ghost": "👻 CMTVGhost", "nuvio": "🎬 Nuvio",
    "webplayer": "🌐 Web player", "website": "🧾 CMTV website", "addons": "➕ Add-ons",
}
TZ = ZoneInfo("America/Toronto")
POST_HOUR = 19   # 7:00 pm Toronto


def init(**deps):
    D.update(deps)


def post_text(product: str, title: str, body: str) -> str:
    lines = []
    for raw in (body or "").splitlines():
        t = raw.strip()
        if not t:
            continue
        lines.append("• " + escape(t[2:].strip()) if t.startswith(("- ", "* ", "• ")) else escape(t))
    head = f"{PRODUCTS.get(product, PRODUCTS['general'])} · <b>{escape(title.strip())}</b>"
    return head + ("\n\n" + "\n".join(lines) if lines else "")


async def send(text: str) -> int:
    """Post to the App updates topic; returns the message id (raises ValueError with a readable reason)"""
    cfg = await D["db"].cmtv_config.find_one({"_id": "nuvio_app_announce"}) or {}
    if not cfg.get("chat_id") or not cfg.get("thread_id"):
        raise ValueError("no App updates topic set yet (Admin > Nuvio > App)")
    import cmtv_status
    token = cmtv_status._support_env().get("BOT_TOKEN")
    if not token:
        raise ValueError("the support bot's settings couldn't be read")
    msg = {"chat_id": cfg["chat_id"], "message_thread_id": int(cfg["thread_id"]), "text": text, "parse_mode": "HTML",
           "disable_web_page_preview": True}
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(f"https://api.telegram.org/bot{token}/sendMessage", json=msg)
        j = r.json() if r.content else {}
    except httpx.HTTPError as e:
        raise ValueError(f"couldn't reach Telegram ({type(e).__name__})")
    if not j.get("ok"):
        raise ValueError(f"Telegram said: {j.get('description') or r.status_code}")
    return j["result"]["message_id"]


# ---------------------------------------------------------------- daily changelog (2026-10-02)
def _now_local():
    return datetime.now(TZ)


def next_post_at(now=None):
    now = now or _now_local()
    at = now.replace(hour=POST_HOUR, minute=0, second=0, microsecond=0)
    return at if now < at else at + timedelta(days=1)


async def queued():
    return [a async for a in D["db"].cmtv_changelog.find({"status": "queued"}).sort("added_at", 1)]


def changelog_text(items, day=None) -> str:
    day = day or _now_local()
    out = [f"🆕 <b>What's new at CMTV</b> · {day.strftime('%B')} {day.day}"]
    for key, label in PRODUCTS.items():
        lines = [i["line"] for i in items if i.get("product") == key]
        if lines:
            out.append(f"\n<b>{label}</b>\n" + "\n".join("• " + escape(x, quote=False) for x in lines))
    return "\n".join(out)


async def queue_add(product: str, line: str, by: str = "admin") -> str:
    if product not in PRODUCTS:
        raise ValueError("Unknown product")
    line = " ".join((line or "").split())
    if line.startswith(("- ", "• ", "* ")):
        line = line[2:]
    if not line or len(line) > 300:
        raise ValueError("One line of up to 300 characters is needed")
    r = await D["db"].cmtv_changelog.insert_one({"product": product, "line": line, "status": "queued",
                                                 "added_by": by, "added_at": datetime.utcnow()})
    return str(r.inserted_id)


async def post_daily(by: str = "7 pm daily changelog"):
    """Post everything queued as one message. None if nothing is queued (no post)."""
    items = await queued()
    if not items:
        return None
    text = changelog_text(items)
    mid = await send(text)
    now = datetime.utcnow()
    await D["db"].cmtv_changelog.update_many({"_id": {"$in": [i["_id"] for i in items]}},
                                            {"$set": {"status": "posted", "posted_at": now, "message_id": mid}})
    await D["db"].cmtv_announcements.insert_one({"product": "daily", "title": f"Daily changelog ({len(items)} item{'s' if len(items) != 1 else ''})",
                                                 "body": "\n".join(i["line"] for i in items), "text": text, "message_id": mid,
                                                 "by": by, "at": now})
    logger.info(f"Daily changelog posted: {len(items)} items, message {mid}")
    return mid


async def _daily_loop():
    await asyncio.sleep(60)
    tries = 0
    while True:
        try:
            now = _now_local()
            today = now.strftime("%Y-%m-%d")
            st = await D["db"].cmtv_config.find_one({"_id": "changelog_state"}) or {}
            if now.hour >= POST_HOUR and st.get("last_day") != today:
                try:
                    mid = await post_daily()
                    await D["db"].cmtv_config.update_one({"_id": "changelog_state"}, {"$set": {
                        "last_day": today, "last_message_id": mid, "checked_at": datetime.utcnow(), "last_error": None}}, upsert=True)
                    tries = 0
                    if mid is None:
                        logger.info("Daily changelog: nothing queued today, no post")
                except Exception as e:
                    tries += 1
                    logger.warning(f"Daily changelog post failed (try {tries}): {e}")
                    await D["db"].cmtv_config.update_one({"_id": "changelog_state"}, {"$set": {"last_error": str(e)[:200]}}, upsert=True)
                    if tries >= 5:   # give up for today; the items stay queued for tomorrow
                        await D["db"].cmtv_config.update_one({"_id": "changelog_state"}, {"$set": {"last_day": today}}, upsert=True)
                        tries = 0
                        try:
                            import cmtv_notify
                            await cmtv_notify.ops(f"⚠️ <b>Daily changelog not posted</b>\n{escape(str(e)[:200])}\nThe items stay queued for tomorrow (Admin › Notices).", "billing")
                        except Exception:
                            pass
        except Exception as e:
            logger.warning(f"Daily changelog loop: {e}")
        await asyncio.sleep(120)


def start():
    if not D.get("daily_task"):
        D["daily_task"] = asyncio.get_event_loop().create_task(_daily_loop())


def init_routes():
    admin = D["get_current_admin_user"]

    def _check(body):
        product, title = body.get("product") or "general", (body.get("title") or "").strip()
        if product not in PRODUCTS:
            raise HTTPException(400, "Unknown product")
        if not title or len(title) > 120:
            raise HTTPException(400, "A title (up to 120 characters) is needed")
        if len(body.get("body") or "") > 2500:
            raise HTTPException(400, "Too long (2,500 characters max)")
        return product, title, body.get("body") or ""

    @router.get("/products")
    async def products(current_user: dict = Depends(admin)):
        return [{"key": k, "label": v} for k, v in PRODUCTS.items()]

    @router.post("/preview")
    async def preview(body: dict, current_user: dict = Depends(admin)):
        return {"text": post_text(*_check(body))}

    @router.post("/post")
    async def post(body: dict, current_user: dict = Depends(admin)):
        product, title, text_body = _check(body)
        text = post_text(product, title, text_body)
        try:
            mid = await send(text)
        except ValueError as e:
            raise HTTPException(502, str(e))
        await D["db"].cmtv_announcements.insert_one({"product": product, "title": title, "body": text_body, "text": text,
                                                     "message_id": mid, "by": current_user.get("email"), "at": datetime.utcnow()})
        logger.info(f"Customer update posted to Telegram: {product} / {title}")
        return {"message_id": mid}

    @router.get("/log")
    async def log(current_user: dict = Depends(admin)):
        return [{"product": a["product"], "title": a["title"], "at": a["at"], "by": a.get("by")}
                async for a in D["db"].cmtv_announcements.find({}).sort("at", -1).limit(20)]

    # 2026-10-02: the daily 7 pm changelog
    @router.get("/queue")
    async def queue(current_user: dict = Depends(admin)):
        items = await queued()
        st = await D["db"].cmtv_config.find_one({"_id": "changelog_state"}) or {}
        return {"items": [{"id": str(i["_id"]), "product": i["product"], "label": PRODUCTS.get(i["product"], ""), "line": i["line"],
                           "added_at": i["added_at"], "added_by": i.get("added_by")} for i in items],
                "preview": changelog_text(items) if items else None,
                "next_post_at": next_post_at().isoformat(), "last_error": st.get("last_error")}

    @router.post("/queue")
    async def queue_post(body: dict, current_user: dict = Depends(admin)):
        try:
            return {"id": await queue_add(body.get("product") or "general", body.get("line") or "", current_user.get("email", "admin"))}
        except ValueError as e:
            raise HTTPException(400, str(e))

    @router.post("/queue/{item_id}/remove")
    async def queue_remove(item_id: str, current_user: dict = Depends(admin)):
        if not ObjectId.is_valid(item_id):
            raise HTTPException(404, "Not found")
        r = await D["db"].cmtv_changelog.update_one({"_id": ObjectId(item_id), "status": "queued"},
                                                   {"$set": {"status": "removed", "removed_by": current_user.get("email"), "removed_at": datetime.utcnow()}})
        if not r.matched_count:
            raise HTTPException(404, "Not in the queue")
        return {"ok": True}

    @router.post("/queue/post-now")
    async def queue_post_now(current_user: dict = Depends(admin)):
        try:
            mid = await post_daily(by=current_user.get("email", "admin"))
        except ValueError as e:
            raise HTTPException(502, str(e))
        if mid is None:
            raise HTTPException(400, "Nothing is queued")
        return {"message_id": mid}
