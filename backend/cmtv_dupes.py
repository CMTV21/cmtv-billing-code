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
7. (2026-10-10, owner) Suspected duplicates -> Critical alert + hold on new sign-ups / free trials (see "holds" below).
"""
import asyncio
import html
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
_DEV_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
_domains = {"set": set(), "loaded": None}

MSG_THROWAWAY = "Please use a permanent email address. Temporary inbox services can't be used for a CMTV account."
MSG_SAME_INBOX = ("An account already exists for this email address (Gmail ignores dots and anything after a +). "
                  "Sign in, or use Forgot password.")
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
    ip, dev = client_ip(request), device_id(request)
    cfg = await _cfg()
    if cfg.get("trial_check") is False:
        return
    await check_hold(request, user_id, "free trial")   # 2026-10-10: on hold -> no trial
    allow = set(cfg.get("allow_ips") or [])
    ors = []
    if ip and ip not in allow:
        ors.append({"ip": ip})
    if dev:
        ors.append({"device": dev})
    # 2026-10-10 (gamebattles: refused twice, then a VPN + a private window got the trial on the same account): also
    # every connection and browser THIS account used in the last 90 days
    async for f in D["db"].cmtv_fingerprints.find({"user_id": str(user_id), "at": {"$gte": datetime.utcnow() - timedelta(days=TRIAL_DAYS)}},
                                                 {"ip": 1, "device": 1}):
        if f.get("ip") and f["ip"] not in allow and {"ip": f["ip"]} not in ors:
            ors.append({"ip": f["ip"]})
        if f.get("device") and {"device": f["device"]} not in ors:
            ors.append({"device": f["device"]})
    if not ors:
        return
    hit = await D["db"].cmtv_trial_marks.find_one({
        "product_id": str(product["_id"]), "user_id": {"$ne": str(user_id)},
        "at": {"$gte": datetime.utcnow() - timedelta(days=TRIAL_DAYS)}, "$or": ors})
    if not hit:
        hit = await _trial_by_seen_account(user_id, product, ors)
    if not hit:   # 2026-10-10: refused before for this trial = refused again, from anywhere
        r = await D["db"].cmtv_trial_refusals.find_one({"user_id": str(user_id), "product_id": str(product["_id"])})
        if r:
            hit = {"user_id": r.get("other_user_id"), "device": r.get("device"), "ip": r.get("ip")}
    if hit:
        _devs = {o["device"] for o in ors if "device" in o}
        how = "device" if hit.get("device") and hit.get("device") in _devs else "internet connection"
        await D["db"].cmtv_trial_refusals.insert_one({"user_id": str(user_id), "product_id": str(product["_id"]),
                                                      "product_name": product.get("name"), "other_user_id": hit["user_id"],
                                                      "match": how, "ip": ip, "device": dev, "at": datetime.utcnow()})
        log.info(f"dupes: trial {product.get('name')} refused for {user_id}: same {how} as {hit['user_id']}")
        # 2026-10-10 (owner): was a silent Billing note; now a Critical alert + hold (once per account)
        await suspect(user_id, request, [hit.get("user_id")], "browser" if how == "device" else how,
                      f"free trial re-used: {product.get('name')}")
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
    return {"groups": res, "trial_refusals": refusals, "referral_holds": holds, "blocks": await blocks_list(),
            "blocklist": {"updated_at": _o(dom.get("updated_at")), "count": len(_domains["set"])},
            "fingerprints_since": _o(await _first_print())}


async def _first_print():
    f = await D["db"].cmtv_fingerprints.find_one({}, sort=[("at", 1)])
    return f["at"] if f else None


def init_routes():
    admin = D["get_current_admin_user"]

    @router.get("/admin/groups")
    async def admin_groups(current_user: dict = Depends(admin)):
        return await groups()

    @router.post("/admin/blocks/{bid}")   # 2026-10-10: lift a hold (clear) or keep it (reviewed)
    async def block_action(bid: str, data: dict = Body(...), current_user: dict = Depends(admin)):
        action, oid = data.get("action"), _o_id(bid)
        if not oid or action not in ("clear", "keep"):
            raise HTTPException(400, "Unknown action")
        now, by = datetime.utcnow(), current_user.get("sub")
        upd = {"reviewed": True, "decided_at": now, "decided_by": by, "decision": action}
        if action == "clear":
            upd["status"] = "cleared"
        r = await D["db"].cmtv_dupe_blocks.update_one({"_id": oid}, {"$set": upd})
        if not r.matched_count:
            raise HTTPException(404, "Not found")
        return {"ok": True}

    @router.post("/admin/allow-ip")
    async def allow_ip(data: dict = Body(...), current_user: dict = Depends(admin)):
        ip = str(data.get("ip") or "").strip()
        if not ip:
            raise HTTPException(400, "IP needed")
        op = "$addToSet" if data.get("allow", True) else "$pull"
        await D["db"].cmtv_config.update_one({"_id": "dupes"}, {op: {"allow_ips": ip}}, upsert=True)
        return {"ok": True}


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
    await db.cmtv_dupe_blocks.create_index([("status", 1), ("created_at", -1)])   # 2026-10-10
    asyncio.create_task(_loop())


# ------------------------------------------------------------------ holds (CMTV local change 2026-10-10, owner)
# A suspected duplicate (a new account on the same browser, or on the same internet connection in the last 90 days, as
# another customer account; or a free trial re-used) sends ONE Critical alert and puts that connection + browser (and the
# account) on hold: no new sign-ups and no free trials from them until the admin lifts it in Admin > Possible duplicates.
# Signing in and paying are never blocked (households share connections). IPv6 holds cover the whole /64 (home
# connections rotate the rest). Holds don't expire. cmtv_dupe_blocks {user_id, other_user_ids, match, what, ip_keys,
# devices, status blocked|cleared, reviewed, hits, created_at, decided_at, decided_by}.
MSG_HOLD = ("We need to check something before we can set this up. Message us at @Cmtv_support_bot "
            "and we'll sort it out quickly.")
IP_MATCH_DAYS = 90


def ip_key(ip: str) -> str:
    ip = (ip or "").strip()
    if ":" in ip:
        try:
            import ipaddress
            return str(ipaddress.ip_network(ip + "/64", strict=False))
        except ValueError:
            return ip
    return ip


async def held(request: Request, user_id=None):
    """The active hold matching this visitor's connection or browser (or this account), else None."""
    allow = set((await _cfg()).get("allow_ips") or [])
    ip, dev = client_ip(request), device_id(request)
    ors = []
    if ip and ip not in allow:
        ors.append({"ip_keys": ip_key(ip)})
    if dev:
        ors.append({"devices": dev})
    if user_id:
        ors.append({"user_id": str(user_id)})
    if not ors:
        return None
    return await D["db"].cmtv_dupe_blocks.find_one({"status": "blocked", "$or": ors})


async def check_hold(request: Request, user_id=None, what: str = "sign-up"):
    """Raise 403 (MSG_HOLD) if this visitor or account is on hold."""
    if (await _cfg()).get("holds") is False:
        return
    b = await held(request, user_id)
    if b:
        await D["db"].cmtv_dupe_blocks.update_one({"_id": b["_id"]}, {"$inc": {"hits": 1},
                                                                    "$set": {"last_hit": datetime.utcnow(), "last_hit_what": what}})
        log.info(f"dupes: {what} refused (on hold {b['_id']})")
        raise HTTPException(403, MSG_HOLD)


async def _who(uid):
    u = await D["db"].users.find_one({"_id": _o_id(uid)}, {"name": 1, "email": 1}) or {}
    return f"{html.escape(u.get('name') or '(no name)')} ({html.escape(u.get('email') or '?')})"


def _o_id(v):
    try:
        return ObjectId(str(v))
    except Exception:
        return None


async def suspect(user_id, request: Request, others, how: str, what: str):
    """Put this connection + browser + account on hold and send ONE Critical alert. Never raises."""
    try:
        db = D["db"]
        if (await _cfg()).get("holds") is False:
            return
        if await db.cmtv_dupe_blocks.find_one({"status": "blocked", "user_id": str(user_id)}):
            return   # already on hold: one alert per account
        allow = set((await _cfg()).get("allow_ips") or [])
        ip, dev = client_ip(request), device_id(request)
        others = sorted({str(o) for o in others if o and str(o) != str(user_id)})
        doc = {"user_id": str(user_id), "other_user_ids": others, "match": how, "what": what,
               "ip_keys": [ip_key(ip)] if ip and ip not in allow else [], "devices": [dev] if dev else [],
               "status": "blocked", "reviewed": False, "hits": 0, "created_at": datetime.utcnow()}
        await db.cmtv_dupe_blocks.insert_one(doc)
        lines = [f"• {await _who(o)}" for o in others[:4]]
        olist = "\n".join(lines) + (f"\n• +{len(others) - 4} more" if len(others) > 4 else "")
        import cmtv_notify
        await cmtv_notify.ops(
            f"🚨 <b>Suspected duplicate account</b> ({html.escape(what)})\n\n{await _who(user_id)}\n"
            f"Same {html.escape(how)} as:\n{olist}\n\n"
            "New sign-ups and free trials from this connection and browser are ON HOLD until you check it: "
            "Admin › Possible duplicates.", kind="critical")
    except Exception as e:
        log.warning(f"dupes: suspect failed ({type(e).__name__}: {e})")


async def signup_check(user_id, request: Request):
    """After a website sign-up: another customer account seen on the same browser (365 days) or the same connection
    (90 days) -> suspect. Never raises."""
    try:
        db = D["db"]
        allow = set((await _cfg()).get("allow_ips") or [])
        ip, dev = client_ip(request), device_id(request)
        ors = []
        if dev:
            ors.append({"device": dev})
        if ip and ip not in allow:
            ors.append({"ip": ip, "at": {"$gte": datetime.utcnow() - timedelta(days=IP_MATCH_DAYS)}})
        if not ors:
            return
        seen = {}
        async for f in db.cmtv_fingerprints.find({"user_id": {"$ne": str(user_id)}, "$or": ors}, {"user_id": 1, "device": 1}):
            if dev and f.get("device") == dev:
                seen[str(f["user_id"])] = "browser"
            else:
                seen.setdefault(str(f["user_id"]), "internet connection")
        if not seen:
            return
        customers = {str(u["_id"]) async for u in db.users.find(
            {"_id": {"$in": [i for i in map(_o_id, seen) if i]}, "role": "user"}, {"_id": 1})}
        others = [i for i in seen if i in customers]
        if not others:
            return
        how = "browser" if any(seen[i] == "browser" for i in others) else "internet connection"
        await suspect(user_id, request, others, how, "new sign-up")
    except Exception as e:
        log.warning(f"dupes: signup_check failed ({type(e).__name__}: {e})")


async def waiting_count() -> int:
    return await D["db"].cmtv_dupe_blocks.count_documents({"status": "blocked", "reviewed": {"$ne": True}})


async def blocks_list():
    out = []
    async for b in D["db"].cmtv_dupe_blocks.find({"$or": [{"status": "blocked"}, {
            "decided_at": {"$gte": datetime.utcnow() - timedelta(days=30)}}]}).sort("created_at", -1).limit(40):
        ids = [b["user_id"]] + list(b.get("other_user_ids") or [])
        users = {str(u["_id"]): u async for u in D["db"].users.find({"_id": {"$in": [i for i in map(_o_id, ids) if i]}},
                                                                     {"name": 1, "email": 1})}
        person = lambda i: {"id": i, "name": (users.get(i) or {}).get("name") or "", "email": (users.get(i) or {}).get("email") or ""}
        out.append({"id": str(b["_id"]), "status": b.get("status"), "reviewed": bool(b.get("reviewed")),
                    "match": b.get("match"), "what": b.get("what"), "hits": b.get("hits", 0),
                    "created_at": _o(b.get("created_at")), "decided_at": _o(b.get("decided_at")),
                    "person": person(b["user_id"]), "others": [person(i) for i in b.get("other_user_ids") or []]})
    return out
