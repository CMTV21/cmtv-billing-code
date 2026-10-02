"""CMTV admin alerts through the Ops bot (CMTV local addition 2026-09-26).

The user switched off the billing panel's own Telegram notifications and uses the Ops bot instead, so CMTV alerts
(paid order not set up, PayPal auto-renew, referral tier reached) go through the Ops bot, like
/opt/cmtv-overlay/notify.sh: token and chat from /opt/cmtv-bots/ops/.env (read on each send, never logged), into the
Ops group topics Billing (routine) and Critical (problems). Topic numbers: settings.cmtv_telegram_topics, else below.
"""
import logging

import httpx
import re

logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)   # request URLs contain the bot token
OPS_ENV = "/opt/cmtv-bots/ops/.env"
TOPICS = {"billing": 4964, "critical": 4962}


def _ops_env():
    vals = {}
    try:
        with open(OPS_ENV) as f:
            for line in f:
                if "=" in line and not line.lstrip().startswith("#"):
                    k, v = line.split("=", 1)
                    vals[k.strip()] = v.strip().strip("'\"")
    except OSError as e:
        logger.warning(f"CMTV alert: can't read the Ops bot settings ({e})")
    return vals.get("BOT_TOKEN", ""), vals.get("OPS_CHAT_ID", "")


async def ops(text: str, kind: str = "critical", settings: dict = None, silent: bool = False) -> bool:
    """Send an alert to the Ops group. kind: "critical" (problems) or "billing" (routine). Never raises.
    silent (2026-09-29): posted without a notification sound (Uptime Kuma status posts)."""
    token, chat = _ops_env()
    if not token or not chat:
        logger.warning("CMTV alert not sent: Ops bot token or chat missing")
        return False
    topic = ((settings or {}).get("cmtv_telegram_topics") or {}).get(kind) or TOPICS.get(kind)
    msg = {"chat_id": chat, "text": text[:4000], "disable_web_page_preview": True}
    # CMTV local change 2026-10-02: alerts written with <b>/<i>/<a> were shown as raw tags (no parse_mode was sent).
    # Send them as HTML; if Telegram can't read it (e.g. a stray "<" in a name), send the same text without the tags.
    html = bool(re.search(r"</?(b|i|u|a|code|pre)\b", text))
    if html:
        msg["parse_mode"] = "HTML"
    if silent:
        msg["disable_notification"] = True
    if topic:
        msg["message_thread_id"] = int(topic)
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(f"https://api.telegram.org/bot{token}/sendMessage", json=msg)
            if html and r.status_code == 400 and "parse" in (r.text or "").lower():
                msg.pop("parse_mode", None)
                msg["text"] = re.sub(r"<[^>]+>", "", text)[:4000].replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
                r = await c.post(f"https://api.telegram.org/bot{token}/sendMessage", json=msg)
        if r.status_code != 200 or not r.json().get("ok"):
            logger.warning(f"CMTV alert: Telegram said {r.status_code} {r.json().get('description', '') if r.content else ''}")
            return False
        return True
    except Exception as e:
        logger.warning(f"CMTV alert: Telegram failed ({type(e).__name__})")
        return False
