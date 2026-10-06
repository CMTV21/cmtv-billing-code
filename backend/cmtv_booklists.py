"""Top audiobooks: the New York Times bestseller lists (CMTV local addition 2026-10-06; the owner: ReadMeABook's "Popular"
is Audible's own list, "slop", not real bestsellers). Billing shows the NYT lists on /audiobooks/top with a "Request it"
button per book that opens the request site's search for that title (customers choose; nothing is requested or
downloaded automatically).
- Key: the owner's free NYT Books API key in cmtv_config {_id: "nyt"}.key (never returned; the admin sees the last 4).
- Lists: Audio Fiction + Audio Nonfiction (NYT monthly audio lists) and Combined Print & E-Book Fiction / Nonfiction
  (weekly). Fetched when the key is saved and then whenever the copy is 3+ days old (hourly check; the API allows
  5 calls a minute, so 13 s between calls). Stored in cmtv_booklists {_id: list name, ...}.
GET /api/cmtv/booklists (public) -> {ready, lists: [...]}; GET/POST /api/cmtv/booklists/admin (key box).
"""
import asyncio
import json
import logging
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

from fastapi import APIRouter, Body, Depends, HTTPException

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/cmtv/booklists", tags=["cmtv-booklists"])
D = {}
LISTS = [("audio-fiction", "Audio fiction", "monthly"), ("audio-nonfiction", "Audio nonfiction", "monthly"),
         ("combined-print-and-e-book-fiction", "Fiction", "weekly"), ("combined-print-and-e-book-nonfiction", "Nonfiction", "weekly")]
STALE = timedelta(days=3)
REQUESTS = "https://requests.cmtv.info/search?q="
SMALL = {"a", "an", "and", "as", "at", "but", "by", "for", "in", "of", "on", "or", "the", "to", "with"}


def init(**deps):
    D.update(deps)


def title_case(s):
    """NYT titles are in capitals: 'THE WOMEN' -> 'The Women'."""
    words = str(s or "").lower().split()
    return " ".join(w if (i and w in SMALL) else (w[:1].upper() + w[1:]) for i, w in enumerate(words))


def _get(path, key):
    url = f"https://api.nytimes.com/svc/books/v3/{path}?" + urllib.parse.urlencode({"api-key": key})
    req = urllib.request.Request(url, headers={"User-Agent": "CMTV"})
    return json.loads(urllib.request.urlopen(req, timeout=25).read() or b"{}")


def fetch_all(key):
    """[(list id, doc)] for every list; raises on a bad key (first call)."""
    out = []
    for i, (lid, label, how) in enumerate(LISTS):
        if i:
            time.sleep(13)
        r = _get(f"lists/current/{lid}.json", key).get("results") or {}
        books = []
        for b in r.get("books") or []:
            t, a = title_case(b.get("title")), b.get("author") or ""
            books.append({"rank": b.get("rank"), "title": t, "author": a, "description": b.get("description") or "",
                          "cover": b.get("book_image"), "weeks": b.get("weeks_on_list") or 0, "isbn": b.get("primary_isbn13"),
                          "request": REQUESTS + urllib.parse.quote(f"{t} {a}".strip())})
        out.append((lid, {"label": label, "how": how, "display_name": r.get("display_name") or label,
                          "published_date": r.get("published_date"), "books": books[:15], "fetched_at": datetime.utcnow()}))
    return out


async def _key():
    return ((await D["db"].cmtv_config.find_one({"_id": "nyt"})) or {}).get("key") or ""


async def refresh(force=False):
    key = await _key()
    if not key:
        return 0
    newest = await D["db"].cmtv_booklists.find_one({}, sort=[("fetched_at", -1)])
    if not force and newest and datetime.utcnow() - newest["fetched_at"] < STALE:
        return 0
    rows = await asyncio.to_thread(fetch_all, key)
    for lid, doc in rows:
        await D["db"].cmtv_booklists.update_one({"_id": lid}, {"$set": doc}, upsert=True)
    logger.info(f"NYT bestseller lists refreshed: {[(l, len(d['books'])) for l, d in rows]}")
    return len(rows)


async def _loop():
    await asyncio.sleep(200)
    while True:
        try:
            await refresh()
        except Exception as e:
            logger.warning(f"NYT lists refresh failed: {e}")
        await asyncio.sleep(3600)


async def startup():
    asyncio.create_task(_loop())


def init_routes():
    admin = D["get_current_admin_user"]

    @router.get("")
    async def public_lists():
        docs = {d["_id"]: d async for d in D["db"].cmtv_booklists.find({})}
        lists = [{"id": lid, **{k: v for k, v in docs[lid].items() if k not in ("_id", "fetched_at")}} for lid, _, _ in LISTS if lid in docs]
        return {"ready": bool(lists), "lists": lists}

    @router.get("/admin")
    async def admin_status(current_user: dict = Depends(admin)):
        k = await _key()
        newest = await D["db"].cmtv_booklists.find_one({}, sort=[("fetched_at", -1)])
        return {"has_key": bool(k), "key_end": k[-4:] if k else "", "fetched_at": (newest or {}).get("fetched_at"),
                "lists": {d["_id"]: len(d.get("books") or []) async for d in D["db"].cmtv_booklists.find({})}}

    @router.post("/admin/key")
    async def set_key(data: dict = Body(...), current_user: dict = Depends(admin)):
        k = str(data.get("key") or "").strip()
        if not k or len(k) > 100 or any(c.isspace() for c in k):
            raise HTTPException(400, "Paste just the key (no spaces).")
        try:
            r = await asyncio.to_thread(_get, "lists/current/audio-fiction.json", k)
            if not (r.get("results") or {}).get("books"):
                raise ValueError("no books")
        except Exception as e:
            raise HTTPException(400, f"The NYT didn't accept that key ({str(e)[:80]}). Check it's a Books API key.")
        await D["db"].cmtv_config.update_one({"_id": "nyt"}, {"$set": {"key": k, "set_at": datetime.utcnow(),
                                                                       "set_by": current_user.get("sub")}}, upsert=True)
        asyncio.create_task(refresh(force=True))   # ~40 s (the API allows 5 calls a minute)
        return {"ok": True, "key_end": k[-4:]}
