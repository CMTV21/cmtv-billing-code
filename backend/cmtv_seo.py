"""Sitemap for billing.cmtv.info (CMTV local addition 2026-09-27). nginx serves /sitemap.xml from here.

The developer's /api/sitemap.xml builds its links from settings.seo.schema_url (https://cmtv.info, the separate marketing
site) and lists /order/<product id> pages, so every link in it was a 404. This one lists the billing site's own public
pages and every published guide (/knowledge-base/<id>), with the guide's last update date.
"""
from datetime import datetime
from xml.sax.saxutils import escape

from fastapi import APIRouter, Response

router = APIRouter(prefix="/api/cmtv/seo", tags=["cmtv-seo"])
D = {}
SITE = "https://billing.cmtv.info"
PAGES = [("/", "daily", "1.0"), ("/knowledge-base", "weekly", "0.8"), ("/register", "monthly", "0.6"),
         ("/login", "monthly", "0.4"), ("/terms", "monthly", "0.3")]


def init(**deps):
    D.update(deps)


def _date(v):
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, str) and len(v) >= 10:
        return v[:10]
    return None


@router.get("/sitemap.xml")
async def sitemap():
    rows = [(SITE + path, None, freq, prio) for path, freq, prio in PAGES]
    async for a in D["db"].kb_articles.find({"is_published": True}, {"_id": 0, "id": 1, "updated_at": 1, "created_at": 1}).sort("display_order", 1):
        if a.get("id"):
            rows.append((f"{SITE}/knowledge-base/{a['id']}", _date(a.get("updated_at") or a.get("created_at")), "monthly", "0.7"))
    out = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for loc, mod, freq, prio in rows:
        out.append(f"  <url><loc>{escape(loc)}</loc>" + (f"<lastmod>{mod}</lastmod>" if mod else "")
                   + f"<changefreq>{freq}</changefreq><priority>{prio}</priority></url>")
    out.append("</urlset>")
    return Response("\n".join(out), media_type="application/xml")
