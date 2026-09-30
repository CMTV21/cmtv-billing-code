"""Customer updates in the "App updates" Telegram topic (CMTV local addition 2026-09-30).

The owner wants customers told about every customer-relevant new feature or good change, across all products (Nuvio,
CMTVGhost, web player, billing website, TV service). Admin > Notices "Post a customer update": product + title + a few
lines -> one formatted post in the App updates topic of the CMTV User Support group (topic set in Admin > Nuvio > App,
cmtv_config {_id: "nuvio_app_announce"}), sent by the support bot; logged in `cmtv_announcements`.
Nuvio app releases can also post their changelog from the Nuvio App tab (cmtv_nuvio.post_changelog).
"""
import logging
from datetime import datetime
from html import escape

import httpx
from fastapi import APIRouter, Depends, HTTPException

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/cmtv/announce", tags=["cmtv-announce"])
D = {}

PRODUCTS = {
    "general": "✨ CMTV", "tv": "📡 TV service", "ghost": "👻 CMTVGhost", "nuvio": "🎬 Nuvio",
    "webplayer": "🌐 Web player", "website": "🧾 CMTV website", "addons": "➕ Add-ons",
}


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
