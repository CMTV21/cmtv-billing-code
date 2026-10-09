"""Duplicate-account protection (CMTV local addition 2026-10-04, the owner's OK: #1 #2 #3 #5 #6 of the proposal).

1. Throwaway email services can't sign up (public blocklist github.com/disposable-email-domains, refreshed weekly,
   + cmtv_config {_id: "dupes"}.extra_domains).
2. Gmail ignores dots and "+anything": j.o.e+tv@gmail.com is joe@gmail.com ("+tag" is dropped for every domain). Sign-up
   and email changes refuse an address that is the same inbox as another account (compared on the fly).
3. Sign-ups, logins and trial orders record the visitor's IP (X-Real-IP from nginx, Cloudflare's real IP) and a random
   device id the website keeps in the browser (header X-CMTV-Device). cmtv_fingerprints, kept 365 days (TTL index).
   One free trial per product per home/device per 90 days: a trial whose IP or device was used for the same trial by
   ANOTHER account in that time is refused (cmtv_trial_marks). Admins can allow an IP (cmtv_config dupes.allow_ips).
5. No referral reward when the referred account and the referrer share an IP or device (checked at sign-up and again
   before the reward at the first paid order); held referrals are logged in cmtv_referral_holds + a silent Ops note.
6. Admin > Customers > Possible duplicates: GET /api/cmtv/dupes/admin/groups.
7. 2026-10-09 (gamebattles kept making trial accounts): bans (cmtv_bans {kind: ip|device|user, value}). Banning an account
   bans it plus every IP and device it was seen on (last 365 days); a banned IP / device can't sign up or take a free trial,
   and a banned account can't take a trial. The ban follows the person: each time a banned account signs in or is seen
   from a new IP or device, that one is banned too (auto-added IPs expire after 30 days). Paid orders and signing in still work (a ban never blocks money).
   Admins can't ban an allowed IP (allow_ips), and shared connections (mobile data, CGNAT) can hit innocent people,
   so the refusal message points to support and every refusal is counted on the ban + an Ops note.
   Reverting: cmtv_config dupes.bans = false (the switch on the admin page) turns every ban check off at once without a
   deploy, keeping the list. Every ban / unban is logged with the bans it touched (cmtv_ban_log) and can be undone from
   the page. Nothing existing is changed by this feature (bans live only in cmtv_bans / cmtv_ban_log), so rolling the
   code back to before 2026-10-09 is safe: those two collections are then simply unused.
"""
import asyncio
import logging
import re
from datetime import datetime, timedelta

import httpx
from bson import ObjectId
from fastapi import APIRouter, Body, Depends, HTTPException, Request

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/cmtv/dupes", tags=["cmtv-dupes"])
D = {}

BLOCKLIST_URL = ("https://raw.githubusercontent.com/disposable-email-domains/disposable-email-domains/"
                 "main/disposable_email_blocklist.conf")
TRIAL_DAYS = 90
KEEP_DAYS = 365
AUTO_IP_DAYS = 30
_DEV_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
_domains = {"set": set(), "loaded": None}

MSG_THROWAWAY = "Please use a permanent email address. Temporary inbox services can't be used for a CMTV account."
MSG_SAME_INBOX = ("An account already exists for this email address (Gmail ignores dots and anything after a +). "
                  "Sign in, or use Forgot password.")
MSG_BANNED = ("New accounts and free trials aren't available from this device or internet connection. "
              "If that isn't right, message us at @Cmtv_support_bot and we'll sort it out.")
MSG_TRIAL = ("A free trial of this service has already been used from this home or device. "
             "If that isn't right, message us at @Cmtv_support_bot and we'll sort it out.")


def init(**deps):
    D.update(deps)


# ------------------------------------------------------------------ helpers
def norm_email(email: str) -> str:
    e = (email or "").strip().lower()
    name, _, dom = e.partition("@")
    if not dom:
        return e
    name = name.split("+", 1)[0]
    if dom in ("gmail.com", "googlemail.com"):
        name, dom = name.replace(".", ""), "gmail.com"
    return f"{name}@{dom}"


def client_ip(request: Request) -> str:
    ip = (request.headers.get("x-real-ip") or (request.client.host if request.client else "") or "").strip()
    return ip[:64]


def device_id(request: Request) -> str:
    d = (request.headers.get("x-cmtv-device") or "").strip()
    return d if _DEV_RE.match(d) else ""


async def _cfg():
    return await D["db"].cmtv_config.find_one({"_id": "dupes"}) or {}


async def load_domains(force=False):
    """The blocklist from the db copy; refreshed from GitHub weekly (or when forced)."""
    db = D["db"]
    doc = await db.cmtv_config.find_one({"_id": "disposable_domains"}) or {}
    stale = not doc.get("updated_at") or doc["updated_at"] < datetime.utcnow() - timedelta(days=7)
    if force or stale:
        try:
            async with httpx.AsyncClient(timeout=30) as c:
                r = await c.get(BLOCKLIST_URL)
            lines = [l.strip().lower() for l in r.text.splitlines() if l.strip() and not l.startswith("#")]
            if r.status_code == 200 and len(lines) > 1000:   # sanity: never replace the list with an error page
                await db.cmtv_config.update_one({"_id": "disposable_domains"}, {"$set": {
                    "domains": lines, "updated_at": datetime.utcnow(), "source": BLOCKLIST_URL}}, upsert=True)
                doc = {"domains": lines, "updated_at": datetime.utcnow()}
                log.info(f"dupes: disposable-domain list refreshed ({len(lines)} domains)")
            else:
                log.warning(f"dupes: blocklist download gave {r.status_code} / {len(lines)} lines, kept the old list")
        except Exception as e:
            log.warning(f"dupes: blocklist download failed ({type(e).__name__}), kept the old list")
    _domains["set"] = set(doc.get("domains") or [])
    _domains["loaded"] = datetime.utcnow()


async def is_throwaway(email: str) -> bool:
    if not _domains["loaded"] or _domains["loaded"] < datetime.utcnow() - timedelta(hours=6):
        await load_domains()
    dom = (email or "").strip().lower().rpartition("@")[2]
    extra = set((await _cfg()).get("extra_domains") or [])
    parts = dom.split(".")
    # subdomains of a listed domain count too (x.yopmail.com)
    return any(".".join(parts[i:]) in _domains["set"] | extra for i in range(len(parts) - 1))


async def check_email(email: str, exclude_user_id=None):
    """#1 + #2 for a customer choosing an email (sign-up, email change, finishing a panel account). Raises 400."""
    if await is_throwaway(email):
        raise HTTPException(400, MSG_THROWAWAY)
    n, low = norm_email(email), (email or "").strip().lower()
    dom = n.rpartition("@")[2]
    doms = ["gmail.com", "googlemail.com"] if dom == "gmail.com" else [dom]
    q = {"email": {"$regex": "@(" + "|".join(re.escape(d) for d in doms) + ")$", "$options": "i"},
         "role": {"$nin": ["merged"]}}
    if exclude_user_id is not None:
        q["_id"] = {"$ne": ObjectId(str(exclude_user_id))}
    async for u in D["db"].users.find(q, {"email": 1}):
        other = (u.get("email") or "").strip().lower()
        # the exact address (any capitals) is email_in_use's job; here: a different spelling of the same inbox
        if other != low and norm_email(other) == n:
            raise HTTPException(400, MSG_SAME_INBOX)


async def record(user_id, kind: str, request: Request, extra: dict = None):
    """Remember where an account was used from. Never raises (it must not break sign-in)."""
    try:
        ip, dev = client_ip(request), device_id(request)
        if not ip and not dev:
            return
        await D["db"].cmtv_fingerprints.insert_one({"user_id": str(user_id), "kind": kind, "ip": ip, "device": dev,
                                                     "at": datetime.utcnow(), **(extra or {})})
        await _follow_ban(user_id, ip, dev)
    except Exception as e:
        log.warning(f"dupes: record failed ({type(e).__name__})")


async def _prints(user_id):
    since = datetime.utcnow() - timedelta(days=KEEP_DAYS)
    ips, devs = set(), set()
    async for f in D["db"].cmtv_fingerprints.find({"user_id": str(user_id), "at": {"$gte": since}}, {"ip": 1, "device": 1}):
        if f.get("ip"):
            ips.add(f["ip"])
        if f.get("device"):
            devs.add(f["device"])
    return ips, devs


# ------------------------------------------------------------------ #3 trials
async def check_trial(user_id: str, product: dict, request: Request):
    """Raise 400 if this trial was used from the same IP or device by another account in the last 90 days."""
    if not product or not product.get("is_trial"):
        return
    await check_banned(request, user_id, f"free trial: {product.get('name') or 'trial'}")
    ip, dev = client_ip(request), device_id(request)
    cfg = await _cfg()
    if cfg.get("trial_check") is False:
        return
    ors = []
    if ip and ip not in set(cfg.get("allow_ips") or []):
        ors.append({"ip": ip})
    if dev:
        ors.append({"device": dev})
    if not ors:
        return
    hit = await D["db"].cmtv_trial_marks.find_one({
        "product_id": str(product["_id"]), "user_id": {"$ne": str(user_id)},
        "at": {"$gte": datetime.utcnow() - timedelta(days=TRIAL_DAYS)}, "$or": ors})
    if not hit:
        hit = await _trial_by_seen_account(user_id, product, ors)
    if hit:
        how = "device" if dev and hit.get("device") == dev else "internet connection"
        await D["db"].cmtv_trial_refusals.insert_one({"user_id": str(user_id), "product_id": str(product["_id"]),
                                                      "product_name": product.get("name"), "other_user_id": hit["user_id"],
                                                      "match": how, "ip": ip, "device": dev, "at": datetime.utcnow()})
        log.info(f"dupes: trial {product.get('name')} refused for {user_id}: same {how} as {hit['user_id']}")
        try:
            import cmtv_notify
            await cmtv_notify.ops(f"🚫 <b>Trial refused</b>: {product.get('name')}, same {how} as another account that had it "
                                  f"in the last {TRIAL_DAYS} days. Admin &gt; Customers &gt; Possible duplicates.", kind="billing", silent=True)
        except Exception:
            pass
        raise HTTPException(400, MSG_TRIAL)


async def _trial_by_seen_account(user_id: str, product: dict, ors: list):
    """2026-10-05 (gamebattles1 came back as a 4th account): trial marks only exist since 2026-10-04, so trials taken before
    that were invisible to the check. Also refuse when ANOTHER account seen on this device / connection (cmtv_fingerprints,
    last 90 days) has an order for this trial in the last 90 days. Returns a mark-like {user_id, device, ip} or None."""
    db = D["db"]
    since = datetime.utcnow() - timedelta(days=TRIAL_DAYS)
    seen = {}
    async for f in db.cmtv_fingerprints.find({"$or": ors, "user_id": {"$ne": str(user_id)}, "at": {"$gte": since}},
                                              {"user_id": 1, "device": 1, "ip": 1}):
        seen.setdefault(str(f.get("user_id")), f)
    if not seen:
        return None
    o = await db.orders.find_one({"user_id": {"$in": list(seen)}, "status": {"$in": ["paid", "pending"]},
                                  "created_at": {"$gte": since}, "items.product_id": str(product["_id"])}, {"user_id": 1})
    if not o:
        return None
    f = seen.get(str(o["user_id"])) or {}
    return {"user_id": str(o["user_id"]), "device": f.get("device"), "ip": f.get("ip")}


async def mark_trial(user_id: str, product: dict, request: Request, order_id: str = ""):
    try:
        ip, dev = client_ip(request), device_id(request)
        await D["db"].cmtv_trial_marks.insert_one({"user_id": str(user_id), "product_id": str(product["_id"]),
                                                   "product_name": product.get("name"), "ip": ip, "device": dev,
                                                   "order_id": order_id, "at": datetime.utcnow()})
        await record(user_id, "trial", request, {"product_name": product.get("name")})
    except Exception as e:
        log.warning(f"dupes: mark_trial failed ({type(e).__name__})")


# ------------------------------------------------------------------ #5 referrals
async def referral_same_home(referred_user_id: str) -> str:
    """'' if fine, else why the referral reward should be held (same IP / same device as the referrer)."""
    db = D["db"]
    u = await db.users.find_one({"_id": ObjectId(str(referred_user_id))}, {"referred_by": 1, "email": 1})
    if not u or not u.get("referred_by"):
        return ""
    ref = await db.users.find_one({"referral_code": {"$regex": f"^{re.escape(u['referred_by'])}$", "$options": "i"}}, {"_id": 1})
    if not ref:
        return ""
    if str(ref["_id"]) == str(referred_user_id):
        return "own referral code"
    a_ip, a_dev = await _prints(referred_user_id)
    b_ip, b_dev = await _prints(ref["_id"])
    allow = set((await _cfg()).get("allow_ips") or [])
    if a_dev & b_dev:
        return "same device as the referrer"
    if (a_ip & b_ip) - allow:
        return "same internet connection as the referrer"
    return ""


async def hold_referral(referred_user_id: str, reason: str, stage: str):
    db = D["db"]
    if await db.cmtv_referral_holds.find_one({"user_id": str(referred_user_id), "stage": stage}):
        return
    u = await db.users.find_one({"_id": ObjectId(str(referred_user_id))}, {"name": 1, "email": 1, "referred_by": 1})
    await db.cmtv_referral_holds.insert_one({"user_id": str(referred_user_id), "stage": stage, "reason": reason,
                                             "referred_by": (u or {}).get("referred_by"), "at": datetime.utcnow()})
    try:
        import cmtv_notify
        from html import escape
        await cmtv_notify.ops(f"🔁 <b>Referral reward held</b> ({stage}): {escape((u or {}).get('name') or '')} used code "
                              f"{escape((u or {}).get('referred_by') or '')}, {reason}. If it's genuine, award it in Admin &gt; Referrals.",
                              kind="billing", silent=True)
    except Exception:
        pass


# ------------------------------------------------------------------ #7 bans
async def _add_ban(kind: str, value: str, reason: str, source_user_id: str = "", by: str = "", added: list = None) -> bool:
    """True when it's new. IPs added automatically expire after AUTO_IP_DAYS (TTL on expires_at): home IPs change and
    mobile-data IPs are shared, so an old one would end up blocking someone else."""
    if not value:
        return False
    doc = {"kind": kind, "value": value, "reason": reason, "user_id": str(source_user_id or ""), "by": by,
           "hits": 0, "at": datetime.utcnow()}
    if kind == "ip" and by == "auto":
        doc["expires_at"] = datetime.utcnow() + timedelta(days=AUTO_IP_DAYS)
    r = await D["db"].cmtv_bans.update_one({"kind": kind, "value": value}, {"$setOnInsert": doc}, upsert=True)
    if r.upserted_id is not None and added is not None:
        added.append({"kind": kind, "value": value})
    return r.upserted_id is not None


async def bans_on() -> bool:
    return (await _cfg()).get("bans") is not False


async def _log(action: str, by: str, **extra):
    await D["db"].cmtv_ban_log.insert_one({"action": action, "by": by, "at": datetime.utcnow(), **extra})


async def _follow_ban(user_id, ip: str, dev: str):
    """A banned account seen from a new IP / device: ban that too."""
    if not await bans_on() or not await D["db"].cmtv_bans.find_one({"kind": "user", "value": str(user_id)}, {"_id": 1}):
        return
    allow = set((await _cfg()).get("allow_ips") or [])
    if ip and ip not in allow:
        await _add_ban("ip", ip, "seen on a banned account", user_id, "auto")
    await _add_ban("device", dev, "seen on a banned account", user_id, "auto")


async def ban_user(user_id: str, reason: str = "", by: str = "", added: list = None) -> dict:
    """Ban an account and every IP / device it was seen on. added collects the bans that are new (for the log)."""
    allow = set((await _cfg()).get("allow_ips") or [])
    ips, devs = await _prints(user_id)
    n = {"ip": 0, "device": 0, "skipped_allowed_ips": len(ips & allow)}
    await _add_ban("user", str(user_id), reason, user_id, by, added)
    for ip in ips - allow:
        n["ip"] += await _add_ban("ip", ip, reason, user_id, by, added)
    for dev in devs:
        n["device"] += await _add_ban("device", dev, reason, user_id, by, added)
    log.info(f"dupes: account {user_id} banned by {by}: {n}")
    return n


async def check_banned(request: Request, user_id: str = "", what: str = "sign-up"):
    """Raise 403 when this account, IP or device is banned. what: 'sign-up' or the trial's name."""
    cfg = await _cfg()
    if cfg.get("bans") is False:   # the off switch
        return
    ip, dev = client_ip(request), device_id(request)
    ors = []
    if ip and ip not in set(cfg.get("allow_ips") or []):
        ors.append({"kind": "ip", "value": ip})
    if dev:
        ors.append({"kind": "device", "value": dev})
    if user_id:
        ors.append({"kind": "user", "value": str(user_id)})
    if not ors:
        return
    db = D["db"]
    hit = await db.cmtv_bans.find_one({"$or": ors})
    if not hit:
        return
    await db.cmtv_bans.update_one({"_id": hit["_id"]}, {"$inc": {"hits": 1}, "$set": {"last_hit_at": datetime.utcnow(), "last_hit": what}})
    if user_id and hit["kind"] == "device":   # an account used on a banned device is the same person: the ban follows it
        await _add_ban("user", str(user_id), "used on a banned device", hit.get("user_id"), "auto")   # (not for a shared IP)
    log.info(f"dupes: {what} refused, banned {hit['kind']} (user {user_id or '-'})")
    try:
        import cmtv_notify
        from html import escape
        await cmtv_notify.ops(f"⛔ <b>Banned visitor refused</b>: {escape(what)} (banned {hit['kind']}). "
                              f"Admin &gt; Customers &gt; Possible duplicates.", kind="billing", silent=True)
    except Exception:
        pass
    raise HTTPException(403, MSG_BANNED)


async def list_bans():
    db = D["db"]
    rows = [r async for r in db.cmtv_bans.find().sort("at", -1).limit(500)]
    ids = {r.get("user_id") for r in rows if r.get("user_id")} | {r["value"] for r in rows if r["kind"] == "user"}
    users = {str(u["_id"]): u async for u in db.users.find({"_id": {"$in": [ObjectId(i) for i in ids if ObjectId.is_valid(i)]}},
                                                          {"name": 1, "email": 1})}
    out = []
    for r in rows:
        u = users.get(r["value"] if r["kind"] == "user" else r.get("user_id") or "") or {}
        out.append({"id": str(r["_id"]), "kind": r["kind"], "value": r["value"], "reason": r.get("reason") or "",
                    "user_id": r["value"] if r["kind"] == "user" else r.get("user_id") or "",
                    "name": u.get("name") or "", "email": u.get("email") or "", "by": r.get("by") or "",
                    "hits": r.get("hits", 0), "at": _o(r.get("at")), "last_hit_at": _o(r.get("last_hit_at")),
                    "expires_at": _o(r.get("expires_at"))})
    return out


async def ban_log(limit: int = 20):
    out = []
    async for r in D["db"].cmtv_ban_log.find().sort("at", -1).limit(limit):
        out.append({"id": str(r["_id"]), "action": r["action"], "by": r.get("by") or "", "at": _o(r.get("at")),
                    "accounts": r.get("accounts") or [], "ip": r.get("ip") or "", "on": r.get("on"),
                    "count": len(r.get("bans") or []), "undone_at": _o(r.get("undone_at")), "undone_by": r.get("undone_by") or ""})
    return out


async def undo(log_id: str, by: str) -> dict:
    """Put the bans back how they were before one logged action."""
    db = D["db"]
    e = await db.cmtv_ban_log.find_one({"_id": ObjectId(log_id)})
    if not e:
        raise HTTPException(404, "That change isn't in the log.")
    if e.get("undone_at"):
        raise HTTPException(400, "That change was already undone.")
    n = 0
    if e["action"] == "ban":
        # what this ban added, plus anything banned automatically because of these accounts since
        ors = [{"kind": b["kind"], "value": b["value"]} for b in e.get("bans") or []]
        ors += [{"user_id": a["id"], "by": "auto"} for a in e.get("accounts") or []]
        if ors:
            n = (await db.cmtv_bans.delete_many({"$or": ors})).deleted_count
    elif e["action"] == "unban":
        now = datetime.utcnow()
        for b in e.get("bans") or []:
            if b.get("expires_at") and b["expires_at"] < now:
                continue
            b = {k: v for k, v in b.items() if k != "_id"}
            r = await db.cmtv_bans.update_one({"kind": b["kind"], "value": b["value"]}, {"$setOnInsert": b}, upsert=True)
            n += r.upserted_id is not None
    elif e["action"] == "switch":
        await db.cmtv_config.update_one({"_id": "dupes"}, {"$set": {"bans": not e.get("on")}}, upsert=True)
    else:
        raise HTTPException(400, "That change can't be undone.")
    await db.cmtv_ban_log.update_one({"_id": e["_id"]}, {"$set": {"undone_at": datetime.utcnow(), "undone_by": by}})
    log.info(f"dupes: {e['action']} {log_id} undone by {by} ({n} bans)")
    return {"ok": True, "changed": n}


async def _find_user(who: str):
    """An account id, an exact email, or a name / email containing the text (only when exactly one matches)."""
    db = D["db"]
    if ObjectId.is_valid(who):
        u = await db.users.find_one({"_id": ObjectId(who)}, {"name": 1, "email": 1, "role": 1})
        if u:
            return u
    u = await db.users.find_one({"email": {"$regex": f"^{re.escape(who)}$", "$options": "i"}}, {"name": 1, "email": 1, "role": 1})
    if u:
        return u
    rx = {"$regex": re.escape(who), "$options": "i"}
    found = [u async for u in db.users.find({"$or": [{"email": rx}, {"name": rx}], "role": "user"},
                                            {"name": 1, "email": 1, "role": 1}).limit(11)]
    if len(found) == 1:
        return found[0]
    if not found:
        raise HTTPException(404, f"No customer account matches '{who}'.")
    names = ", ".join(f"{u.get('name') or ''} <{u.get('email')}>" for u in found[:10])
    raise HTTPException(400, f"{len(found)}{'+' if len(found) > 10 else ''} accounts match '{who}': {names}. "
                             "Use the full email address.")


# ------------------------------------------------------------------ #6 admin list
def _o(v):
    return v.isoformat() + "Z" if isinstance(v, datetime) else v


async def groups():
    db = D["db"]
    since = datetime.utcnow() - timedelta(days=KEEP_DAYS)
    allow = set((await _cfg()).get("allow_ips") or [])
    by = {"device": {}, "ip": {}}
    async for f in db.cmtv_fingerprints.find({"at": {"$gte": since}}, {"user_id": 1, "ip": 1, "device": 1}):
        if f.get("device"):
            by["device"].setdefault(f["device"], set()).add(f["user_id"])
        if f.get("ip") and f["ip"] not in allow:
            by["ip"].setdefault(f["ip"], set()).add(f["user_id"])
    out = []
    for kind, m in by.items():
        for key, users in m.items():
            if len(users) > 1:
                out.append({"match": kind, "key": key, "user_ids": sorted(users)})
    norm = {}
    async for u in db.users.find({"role": "user", "email": {"$not": re.compile(r"@panel\.local$")}}, {"email": 1}):
        norm.setdefault(norm_email(u.get("email")), []).append(str(u["_id"]))
    for key, ids in norm.items():
        if len(ids) > 1:
            out.append({"match": "inbox", "key": key, "user_ids": sorted(ids)})
    # the same set of accounts found by several matches = one group
    merged = {}
    for g in out:
        k = tuple(g["user_ids"])
        merged.setdefault(k, {"user_ids": list(k), "matches": []})["matches"].append(g["match"])
    ids = {i for g in merged.values() for i in g["user_ids"]}
    users = {str(u["_id"]): u async for u in db.users.find({"_id": {"$in": [ObjectId(i) for i in ids if ObjectId.is_valid(i)]}},
                                                          {"name": 1, "email": 1, "created_at": 1, "role": 1})}
    trials, paid = {}, {}
    async for s in db.services.find({"user_id": {"$in": list(ids)}, "is_trial": True}, {"user_id": 1}):
        trials[s["user_id"]] = trials.get(s["user_id"], 0) + 1
    async for o in db.orders.find({"user_id": {"$in": list(ids)}, "status": "paid", "total": {"$gt": 0}}, {"user_id": 1, "total": 1}):
        paid[o["user_id"]] = round(paid.get(o["user_id"], 0) + float(o.get("total") or 0), 2)
    res = []
    for g in merged.values():
        people = [{"id": i, "name": (users.get(i) or {}).get("name") or "", "email": (users.get(i) or {}).get("email") or "",
                   "role": (users.get(i) or {}).get("role"), "created_at": _o((users.get(i) or {}).get("created_at")),
                   "trials": trials.get(i, 0), "paid": paid.get(i, 0)} for i in g["user_ids"]]
        people = [p for p in people if p["role"] in ("user", None)]
        if len(people) < 2:
            continue
        res.append({"matches": sorted(set(g["matches"])), "people": people,
                    "trials": sum(p["trials"] for p in people), "paid": round(sum(p["paid"] for p in people), 2)})
    res.sort(key=lambda g: (-g["trials"], g["paid"]))
    refusals = [{k: _o(v) for k, v in r.items() if k not in ("_id", "ip", "device")}
                async for r in db.cmtv_trial_refusals.find().sort("at", -1).limit(20)]
    holds = [{k: _o(v) for k, v in r.items() if k != "_id"} async for r in db.cmtv_referral_holds.find().sort("at", -1).limit(20)]
    dom = await db.cmtv_config.find_one({"_id": "disposable_domains"}, {"updated_at": 1, "domains": {"$slice": 0}}) or {}
    return {"groups": res, "trial_refusals": refusals, "referral_holds": holds,
            "blocklist": {"updated_at": _o(dom.get("updated_at")), "count": len(_domains["set"])},
            "bans": await list_bans(), "bans_on": await bans_on(), "ban_log": await ban_log(),
            "fingerprints_since": _o(await _first_print())}


async def _first_print():
    f = await D["db"].cmtv_fingerprints.find_one({}, sort=[("at", 1)])
    return f["at"] if f else None


def init_routes():
    admin = D["get_current_admin_user"]

    @router.get("/admin/groups")
    async def admin_groups(current_user: dict = Depends(admin)):
        return await groups()

    @router.post("/admin/allow-ip")
    async def allow_ip(data: dict = Body(...), current_user: dict = Depends(admin)):
        ip = str(data.get("ip") or "").strip()
        if not ip:
            raise HTTPException(400, "IP needed")
        op = "$addToSet" if data.get("allow", True) else "$pull"
        await D["db"].cmtv_config.update_one({"_id": "dupes"}, {op: {"allow_ips": ip}}, upsert=True)
        return {"ok": True}

    @router.post("/admin/ban")
    async def ban(data: dict = Body(...), current_user: dict = Depends(admin)):
        """{who: account id / email / name} bans the account + its IPs and devices; {user_ids: [...]} several accounts
        (a duplicates group); {ip: "1.2.3.4"} one connection. Optional reason."""
        reason = str(data.get("reason") or "").strip()[:200] or "repeat free trials"
        by = current_user.get("email") or str(current_user.get("sub") or "")
        ip = str(data.get("ip") or "").strip()[:64]
        if ip:
            if ip in set((await _cfg()).get("allow_ips") or []):
                raise HTTPException(400, "That IP is on the allowed list. Remove it from there first.")
            added = []
            await _add_ban("ip", ip, reason, "", by, added)
            if added:
                await _log("ban", by, ip=ip, reason=reason, bans=added, accounts=[])
            return {"ok": True, "ip": len(added), "device": 0, "accounts": []}
        ids = [str(i) for i in (data.get("user_ids") or []) if ObjectId.is_valid(str(i))]
        who = str(data.get("who") or "").strip()
        if who:
            ids.append(str((await _find_user(who))["_id"]))
        if not ids:
            raise HTTPException(400, "Give an account (email, name or id) or an IP.")
        tot, accounts, added = {"ip": 0, "device": 0, "skipped_allowed_ips": 0}, [], []
        for uid in dict.fromkeys(ids):
            u = await D["db"].users.find_one({"_id": ObjectId(uid)}, {"name": 1, "email": 1, "role": 1})
            if not u:
                continue
            if u.get("role") not in ("user", None):
                raise HTTPException(400, f"{u.get('email')} is a staff account and can't be banned.")
            for k, v in (await ban_user(uid, reason, by, added)).items():
                tot[k] += v
            accounts.append({"id": uid, "name": u.get("name") or "", "email": u.get("email") or ""})
        if added:
            await _log("ban", by, reason=reason, bans=added, accounts=accounts)
        return {"ok": True, **tot, "accounts": accounts}

    @router.post("/admin/unban")
    async def unban(data: dict = Body(...), current_user: dict = Depends(admin)):
        """{id: ban id} lifts one ban; {user_id} lifts an account's ban and every IP / device banned because of it.
        The removed bans are kept in the log so the unban can be undone."""
        db = D["db"]
        if data.get("user_id"):
            q = {"$or": [{"kind": "user", "value": str(data["user_id"])}, {"user_id": str(data["user_id"])}]}
        elif ObjectId.is_valid(str(data.get("id") or "")):
            q = {"_id": ObjectId(str(data["id"]))}
        else:
            raise HTTPException(400, "Which ban?")
        gone = [b async for b in db.cmtv_bans.find(q)]
        if gone:
            await db.cmtv_bans.delete_many({"_id": {"$in": [b["_id"] for b in gone]}})
            ids = {b["value"] if b["kind"] == "user" else b.get("user_id") for b in gone} - {"", None}
            users = {str(u["_id"]): u async for u in db.users.find(
                {"_id": {"$in": [ObjectId(i) for i in ids if ObjectId.is_valid(i)]}}, {"name": 1, "email": 1})}
            await _log("unban", current_user.get("email") or "", bans=gone,
                       ip=next((b["value"] for b in gone if b["kind"] == "ip" and len(gone) == 1), ""),
                       accounts=[{"id": i, "name": (users.get(i) or {}).get("name") or "", "email": (users.get(i) or {}).get("email") or ""}
                                 for i in ids])
        return {"ok": True, "removed": len(gone)}

    @router.post("/admin/bans-switch")
    async def bans_switch(data: dict = Body(...), current_user: dict = Depends(admin)):
        """{on: false} turns every ban check off (the list is kept); {on: true} turns them back on."""
        on = bool(data.get("on"))
        await D["db"].cmtv_config.update_one({"_id": "dupes"}, {"$set": {"bans": on}}, upsert=True)
        await _log("switch", current_user.get("email") or "", on=on)
        return {"ok": True, "on": on}

    @router.post("/admin/ban-undo")
    async def ban_undo(data: dict = Body(...), current_user: dict = Depends(admin)):
        if not ObjectId.is_valid(str(data.get("id") or "")):
            raise HTTPException(400, "Which change?")
        return await undo(str(data["id"]), current_user.get("email") or "")


# ------------------------------------------------------------------ startup
async def _loop():
    await asyncio.sleep(30)
    while True:
        try:
            await load_domains()
        except Exception as e:
            log.warning(f"dupes: list refresh failed ({e})")
        await asyncio.sleep(24 * 3600)


async def startup():
    db = D["db"]
    await db.cmtv_fingerprints.create_index("at", expireAfterSeconds=KEEP_DAYS * 86400)
    await db.cmtv_fingerprints.create_index("user_id")
    await db.cmtv_trial_marks.create_index([("product_id", 1), ("at", -1)])
    await db.cmtv_trial_marks.create_index("at", expireAfterSeconds=KEEP_DAYS * 86400)
    await db.cmtv_bans.create_index([("kind", 1), ("value", 1)], unique=True)
    await db.cmtv_bans.create_index("expires_at", expireAfterSeconds=0)
    await db.cmtv_ban_log.create_index("at")
    asyncio.create_task(_loop())
