"""Add devices (connection upgrades) to a running TV line, prorated (CMTV local addition 2026-10-04, the owner's request).

Price the customer pays (the owner's rule, shown to the customer step by step):
    (12-month store price for the new number of devices - 12-month store price for their current number)
    x days left / 365, rounded UP to the dollar, minimum $5.
A device count the store doesn't sell (e.g. 3 on CCTV) is priced by straight-line between its neighbours.

What the panel does (both tested for real 2026-10-04 on the owner's own lines, /root/cmtv-scripts/upgrade_test_20261004.py):
  Imperium (Aether): GET {base}/lines/{ref}/upgrade-options -> targets (same length, every line-up) with a prorated credit
    `charge`; POST {base}/lines/{ref}/upgrade {package_id, expected_charge} -> connections changed, END DATE UNCHANGED.
    CMTV21 1 -> 2 connections: charged exactly the quoted 2 credits.
  CCTV (XtreamUI): no API; the reseller "edit line" form (user_reseller.php?id=) with a package that has more connections.
    The panel charges what the form sends as calculated_upgrade_cost = that package's price (it EXTENDS the line by its
    length; we use the 1-month package) + (new - old connection price for the time left, from get_package_pricing at the
    closest of 1/3/6/12/24 months, scaled). Cmarshall21 2 -> 3: 1.5 + 1.0 = 2.5 credits charged, line +1 month.
    So a CCTV upgrade also gives the customer one bonus month (shown to them).
Orders: cart item action_type "upgrade", renewal_service_id = the line, product_id = the store plan with the new device
count; create_order re-prices it on the server (price_for_order). provision() runs from provision_order_services.
"""
import asyncio
import html
import json
import logging
import math
import re
import time
from datetime import datetime, timedelta

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException

log = logging.getLogger("server")
router = APIRouter(prefix="/api/cmtv/upgrades", tags=["cmtv-upgrades"])
D = {}
MIN_PRICE = 5
MIN_DAYS = 7          # less than a week left: renew instead
SITE = "https://billing.cmtv.info"
NAMES = {"xtream": "CCTV", "aether": "Imperium"}


def init(**deps):
    D.update(deps)


def _oid(v):
    return ObjectId(str(v)) if v and ObjectId.is_valid(str(v)) else None


def _exp(v):
    if isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


# ---------------------------------------------------------------- store prices
async def store_table(panel):
    """{connections: (12-month price, product)} for the store's plans on this panel; also every term's product"""
    year, by_term = {}, {}
    async for p in D["db"].products.find({"panel_type": panel, "account_type": "subscriber", "active": True,
                                          "is_trial": {"$ne": True}}):
        n = int(p.get("max_connections") or 0)
        prices = p.get("prices") or {}
        for term, price in prices.items():
            by_term[(n, int(term))] = p
            if str(term) == "12":
                year[n] = (float(price), p)
    return year, by_term


def price12(year, n):
    if n in year:
        return year[n][0]
    lower = max([k for k in year if k < n], default=None)
    upper = min([k for k in year if k > n], default=None)
    if lower is None or upper is None:
        return None
    a, b = year[lower][0], year[upper][0]
    return round(a + (b - a) * (n - lower) / (upper - lower), 2)


def math_for(year, cur, new, days_left):
    a, b = price12(year, new), price12(year, cur)
    if a is None or b is None:
        return None
    diff = round(a - b, 2)
    raw = round(diff * days_left / 365, 2)
    price = max(MIN_PRICE, math.ceil(raw - 1e-9))
    return {"new_year": a, "cur_year": b, "diff_year": diff, "days_left": days_left, "raw": raw,
            "rounded": math.ceil(raw - 1e-9), "minimum": MIN_PRICE, "price": float(price),
            "minimum_applied": math.ceil(raw - 1e-9) < MIN_PRICE}


# ---------------------------------------------------------------- panels
async def _aether():
    from aether_service import AetherService
    p = ((await D["get_settings"]()).get("aether") or {}).get("panels")[0]
    a = AetherService(panel_url=p["panel_url"], api_token=p["api_token"], name=p.get("name", ""))
    await a.me()
    return a, await a._base()


def _line_family(name):
    try:
        import cmtv_lineups
        return cmtv_lineups._name_lineup(name)[0]
    except Exception:
        return None


async def _aether_state(username):
    a, b = await _aether()
    q = await a._request("GET", f"{b}/lines/{a.ref(username)}/upgrade-options")
    cur = q.get("current") or {}
    fam = _line_family(cur.get("package_name"))
    targets = {}
    for t in q.get("targets") or []:
        n = int(t.get("max_connections") or 0)
        if fam and _line_family(t.get("name")) != fam:
            continue
        targets.setdefault(n, t)
    return {"connections": int(cur.get("max_connections") or 0), "ends": _exp(cur.get("exp_date")), "targets": targets,
            "reason": q.get("unavailable_reason") or "", "package_name": cur.get("package_name")}


async def _cctv_session():
    from xtreamui_service import XtreamUIService
    p = ((await D["get_settings"]()).get("xtream") or {}).get("panels")[0]

    def make():
        x = XtreamUIService(panel_url=p["panel_url"], admin_username=p["admin_username"], admin_password=p["admin_password"],
                            ssl_verify=p.get("ssl_verify", False), http_basic_user=p.get("http_basic_user", ""),
                            http_basic_pass=p.get("http_basic_pass", ""), proxy_url=p.get("proxy_url", ""), api_key=p.get("api_key", ""))
        sc = x._get_session_client()
        if not sc.logged_in and not sc.login():
            raise RuntimeError("couldn't sign in to the CCTV panel")
        return sc
    return await asyncio.to_thread(make)


async def _term_of(product_id):
    """The plan length (months) of a service's product, from its single price key (store products hold one price)"""
    p = await D["db"].products.find_one({"_id": _oid(product_id)}) if _oid(product_id) else None
    try:
        return int(next(iter((p or {}).get("prices") or {"12": 0})))
    except (TypeError, ValueError):
        return 12


def _cctv_read(sc, line_id):
    A = getattr(sc, "http_auth", None)
    page = sc.session.get(f"{sc.panel_url}/user_reseller.php", params={"id": line_id}, auth=A, timeout=25).text
    m1 = re.search(r"var currentConnections = (\d+);", page)
    m2 = re.search(r"var expiryTimestamp = (\d+);", page)
    m3 = re.search(r"var isTrial = (\d+);", page)
    if not m1 or not m2:
        raise RuntimeError("the CCTV panel's edit page didn't show this line")
    pk = {}
    sel = re.search(r'<select[^>]*name="package"[^>]*>(.*?)</select>', page, re.S)
    for pid, name in re.findall(r'<option[^>]*value="(\d+)"[^>]*>([^<]+)</option>', sel.group(1) if sel else ""):
        m = re.match(r"\s*(\d+) Connections? 1 Month\b", name)
        if m:
            pk[int(m.group(1))] = int(pid)
    return {"connections": int(m1.group(1)), "ends": datetime.utcfromtimestamp(int(m2.group(1))), "exp_ts": int(m2.group(1)),
            "trial": bool(int(m3.group(1))) if m3 else False, "month_pkg": pk}


def _cctv_cost(sc, line_id, pkg_id, cur, new, exp_ts):
    """Exactly what the panel's edit page computes (user_reseller.php "ANTI-EXPLOIT" block) -> (credits, extension, upgrade)"""
    A = getattr(sc, "http_auth", None)
    d = sc.session.get(f"{sc.panel_url}/api.php", params={"action": "get_package", "package_id": pkg_id, "user_id": line_id},
                       auth=A, timeout=20).json()["data"]
    base = float(d["cost_credits"])
    days = math.ceil((exp_ts - time.time()) / 86400)
    months = round(days / 30)
    if months <= 0:
        return round(base, 2), base, 0.0, d
    closest = min([1, 3, 6, 12, 24], key=lambda x: (abs(months - x), [12, 1, 3, 6, 24].index(x)))
    dur, unit = (1, "years") if closest == 12 else (2, "years") if closest == 24 else (closest, "months")
    pr = sc.session.get(f"{sc.panel_url}/api.php", params={"action": "get_package_pricing", "new_connections": new,
                                                          "old_connections": cur}, auth=A, timeout=20).json()

    def val(c):
        exact = next((k for k in pr["all_packages"] if int(k["max_connections"]) == c and int(k["official_duration"]) == dur
                      and k["official_duration_in"] == unit), None)
        if exact:
            return float(exact["official_credits"])
        anyp = next((k for k in pr["all_packages"] if int(k["max_connections"]) == c), None)
        if not anyp:
            raise RuntimeError(f"no CCTV package with {c} connections")
        m = int(anyp["official_duration"]) * (12 if anyp["official_duration_in"] == "years" else 1)
        return float(anyp["official_credits"]) / m * months
    nv, ov = val(new), val(cur)
    if months != closest:
        nv, ov = nv / closest * months, ov / closest * months
    up = nv - ov
    return round(base + up, 2), base, round(up, 2), d


async def _cctv_balance(sc):
    A = getattr(sc, "http_auth", None)
    d = await asyncio.to_thread(lambda: sc.session.get(f"{sc.panel_url}/api.php", params={"action": "reseller_dashboard"},
                                                       auth=A, timeout=20).json())
    d = d.get("data", d) if isinstance(d, dict) else {}
    return float(str(d.get("credits")).replace(",", ""))


async def _cctv_line_id(svc):
    iu = await D["db"].imported_users.find_one({"panel_type": "xtream", "username": svc_login(svc)}, {"xtream_user_id": 1})
    return (iu or {}).get("xtream_user_id")


def svc_login(svc):
    return svc.get("xtream_username") or svc.get("username") or ""


# ---------------------------------------------------------------- options
async def _service(user_id, sid):
    svc = await D["db"].services.find_one({"_id": _oid(sid), "user_id": str(user_id)}) if _oid(sid) else None
    if not svc:
        raise HTTPException(404, "Service not found")
    return svc


async def options_for(svc):
    panel = svc.get("panel_type")
    out = {"service_id": str(svc["_id"]), "login": svc_login(svc), "panel": NAMES.get(panel, panel), "options": []}
    if panel not in NAMES or svc.get("account_type") == "reseller" or svc.get("is_trial") or svc.get("status") != "active":
        out["reason"] = "Only running TV plans (not trials) can add devices."
        return out
    if panel == "aether":
        st = await _aether_state(svc_login(svc))
    else:
        sc = await _cctv_session()
        lid = await _cctv_line_id(svc)
        if not lid:
            out["reason"] = "We couldn't find this line on the panel. Message support and we'll add devices for you."
            return out
        st = await asyncio.to_thread(_cctv_read, sc, lid)
        if st.get("trial"):
            out["reason"] = "Trials can't add devices. Pick a plan with more devices instead."
            return out
    now = datetime.utcnow()
    ends = st.get("ends")
    days = max(0, (ends - now).days) if ends else 0
    out.update({"current": st["connections"], "ends": ends.isoformat() + "Z" if ends else None, "days_left": days})
    if days < MIN_DAYS:
        out["reason"] = "Your plan ends within a week: renew it with more devices instead."
        return out
    year, by_term = await store_table(panel)
    term = await _term_of(svc.get("product_id"))
    for n in sorted(k for k in year if k > st["connections"]):
        if panel == "aether" and n not in st["targets"]:
            continue
        if panel == "xtream" and n not in st["month_pkg"]:
            continue
        m = math_for(year, st["connections"], n, days)
        if not m:
            continue
        prod = (by_term.get((n, term)) or year[n][1])
        opt = {"connections": n, "price": m["price"], "math": m, "product_id": str(prod["_id"]), "product_name": prod.get("name"),
               "bonus_month": panel == "xtream",
               "new_end": ((ends + timedelta(days=30)) if panel == "xtream" else ends).isoformat() + "Z" if ends else None}
        out["options"].append(opt)
    if not out["options"]:
        out["reason"] = st.get("reason") or "This line already has the most devices we offer."
    return out


async def price_for_order(user_id, product, item):
    """create_order: re-price an upgrade item on the server (the browser's price is never used)."""
    svc = await _service(user_id, getattr(item, "renewal_service_id", None))
    opts = await options_for(svc)
    n = int(product.get("max_connections") or 0)
    opt = next((o for o in opts["options"] if o["connections"] == n), None)
    if not opt:
        raise HTTPException(400, opts.get("reason") or f"This line can't be upgraded to {n} devices right now.")
    name = f"Add devices: {svc_login(svc)} to {n} devices"
    return {"price": opt["price"], "name": name}


# ---------------------------------------------------------------- provisioning
async def provision(order_id, order, user, item):
    """Called by provision_order_services. Raises on failure (recorded as 'Not provisioned' + the Critical alert)."""
    db = D["db"]
    svc = await db.services.find_one({"_id": _oid(item.get("renewal_service_id")), "user_id": order["user_id"]})
    if not svc:
        raise RuntimeError("upgrade: the line isn't on this customer's account")
    target = await db.products.find_one({"_id": _oid(item.get("product_id"))})
    n = int((target or {}).get("max_connections") or 0)
    panel = svc.get("panel_type")
    login = svc_login(svc)
    charged, ext = None, None
    if panel == "aether":
        st = await _aether_state(login)
        if st["connections"] >= n:
            raise RuntimeError(f"upgrade: {login} already has {st['connections']} connections on Imperium")
        t = st["targets"].get(n)
        if not t:
            raise RuntimeError(f"upgrade: Imperium offers no {n}-connection package for {login} ({st.get('reason') or 'no target'})")
        a, b = await _aether()
        bal = await a.get_balance()
        if bal is not None and float(bal) < float(t["charge"]):
            raise RuntimeError(f"LOW CREDITS: your Imperium balance is {bal}, this upgrade needs {t['charge']}")
        r = await a._request("POST", f"{b}/lines/{a.ref(login)}/upgrade",
                             json_data={"package_id": int(t["package_id"]), "expected_charge": t["charge"]},
                             idem_key=f"cmtv-upgrade-{order_id}-{svc['_id']}")
        if int(r.get("max_connections") or 0) != n:
            raise RuntimeError(f"upgrade: Imperium answered without the new connections ({r})")
        charged = float(r.get("charged") or t["charge"])
        new_end = _exp(r.get("exp_date")) or st["ends"]
        extra = {"aether_package_id": int(r.get("package_id") or t["package_id"])}
    elif panel == "xtream":
        sc = await _cctv_session()
        lid = await _cctv_line_id(svc)
        if not lid:
            raise RuntimeError(f"upgrade: {login} not found on the CCTV panel")
        st = await asyncio.to_thread(_cctv_read, sc, lid)
        if st["connections"] >= n:
            raise RuntimeError(f"upgrade: {login} already has {st['connections']} connections on CCTV")
        pkg = st["month_pkg"].get(n)
        if not pkg:
            raise RuntimeError(f"upgrade: no '{n} Connection 1 Month' package on the CCTV panel")
        cost, ext, up, pdata = await asyncio.to_thread(_cctv_cost, sc, lid, pkg, st["connections"], n, st["exp_ts"])
        bal = await _cctv_balance(sc)
        if bal < cost:
            raise RuntimeError(f"LOW CREDITS: your CCTV balance is {bal}, this upgrade needs {cost}")
        prod = await db.products.find_one({"_id": _oid(svc.get("product_id"))})
        bouquets = svc.get("cmtv_bouquets") or [int(b) for b in (prod or target or {}).get("bouquets") or []]
        info = await asyncio.to_thread(sc.get_reseller_info)
        data = {"edit": str(lid), "submit_user": "1", "username": login,
                "password": svc.get("xtream_password") or svc.get("password") or "", "package": str(pkg),
                "member_id": str(info.get("member_id", 0)), "max_connections": str(n), "exp_date": pdata.get("exp_date", ""),
                "reseller_notes": "", "calculated_upgrade_cost": str(cost), "bouquets_selected": json.dumps(bouquets)}
        A = getattr(sc, "http_auth", None)
        await asyncio.to_thread(lambda: sc.session.post(f"{sc.panel_url}/user_reseller.php?id={lid}", data=data, auth=A, timeout=30))
        after = await asyncio.to_thread(_cctv_read, sc, lid)
        if after["connections"] != n:
            raise RuntimeError(f"upgrade: the CCTV panel still shows {after['connections']} connections for {login}")
        charged, new_end = cost, after["ends"]
        extra = {}
    else:
        raise RuntimeError("upgrade: only CCTV and Imperium lines can add devices")

    # the line now matches a bigger plan: renewals are priced for the new device count
    term = await _term_of(svc.get("product_id"))
    _, by_term = await store_table(panel)
    plan = by_term.get((n, term)) or target
    now = datetime.utcnow()
    await db.services.update_one({"_id": svc["_id"]}, {"$set": {
        "max_connections": n, "product_id": str(plan["_id"]), "product_name": plan.get("name"), "expiry_date": new_end,
        "updated_at": now, **extra},
        "$push": {"cmtv_upgrades": {"from": svc.get("max_connections"), "to": n, "order_id": order_id, "credits": charged,
                                    "at": now, "bonus_month": panel == "xtream"}}})
    idx = next((i for i, it in enumerate(order.get("items") or []) if it.get("action_type") == "upgrade"
                and str(it.get("renewal_service_id")) == str(svc["_id"])), None)
    if idx is not None:
        await db.orders.update_one({"_id": _oid(order_id)}, {"$set": {f"items.{idx}.panel_credits": charged}})
    try:
        # same shape as the panel's own entries (the Ops bot checks service_id/user_id/action/reason/created_at)
        await db.lifecycle_logs.insert_one({"service_id": str(svc["_id"]), "user_id": order["user_id"], "action": "upgrade",
                                            "reason": f"Devices {svc.get('max_connections')} -> {n} (order {order_id}, {charged} credits)",
                                            "triggered_by": "system", "old_status": "active", "new_status": "active",
                                            "created_at": now})
    except Exception:
        pass
    log.info(f"Upgrade: {login} ({NAMES[panel]}) to {n} connections, {charged} credits, order {order_id}")
    try:
        import cmtv_notify
        await cmtv_notify.ops(f"➕ <b>Devices added</b>: {html.escape(login)} ({NAMES[panel]}) now {n} devices "
                              f"({charged:g} credits, ${float(item.get('price') or 0):.2f} paid).", kind="billing", silent=True)
    except Exception:
        pass
    try:
        await _email(user, login, NAMES[panel], n, new_end, panel == "xtream", order_id)
    except Exception as e:
        log.warning(f"Upgrade email failed: {type(e).__name__}")


async def _email(user, login, server, n, new_end, bonus, order_id):
    es = await D["get_email_service"]()
    to = str((user or {}).get("email") or "")
    if not es or not getattr(es, "enabled", False) or not to or to.lower().endswith("@panel.local"):
        return
    first = html.escape(str(user.get("name") or "").split(" ")[0] or "there")
    end = new_end.strftime("%B %-d, %Y") if new_end else ""
    body = (f"<h2 style=\"margin:0 0 12px\">Your line now has {n} devices</h2><p>Hi {first},</p>"
            f"<p>Done: your {server} line <b>{html.escape(login)}</b> can now be used on <b>{n} devices at the same time</b>.</p>"
            + (f"<p>As a thank-you, we also added a bonus month: your plan now runs until <b>{end}</b>.</p>" if bonus and end else
               f"<p>Your plan still runs until <b>{end}</b>.</p>" if end else "")
            + "<p>Nothing to change in your apps: sign in on the extra devices with the same username and password.</p>"
            f"<p style=\"margin-top:18px\"><a href=\"{SITE}/dashboard\">Go to your dashboard</a></p>")
    text = (f"Hi {user.get('name') or 'there'},\n\nYour {server} line {login} can now be used on {n} devices at the same time."
            + (f" We also added a bonus month: your plan now runs until {end}." if bonus and end else "")
            + f"\nSign in on the extra devices with the same username and password.\n\n{SITE}/dashboard")
    subject = f"Your line now has {n} devices"
    await es.send_email(to_email=to, subject=subject, html_content=es._wrap_email(body, subject, to, "transactional"),
                        text_content=text, email_type="transactional", order_id=str(order_id), recipient_name=user.get("name") or "")


# ---------------------------------------------------------------- renewals at the line's real size (2026-10-04)
# The owner: "when a customer renews ensure it renews at the new lines". Upgrades through billing move the service to the
# bigger plan at once (provision). This covers lines changed on the panel by hand: the hourly panel sync copies the panel's
# max_connections onto the service; a line with MORE devices than its plan is moved to the same-length store plan with
# that many devices (or the next size up when the store doesn't sell that count). Never moved down.
async def bigger_plan(panel, line, plan_product):
    """The store plan a line with `line` devices should renew at, if `plan_product` (a priced store plan) is too small."""
    if not plan_product or not plan_product.get("prices") or plan_product.get("panel_type") not in NAMES:
        return None
    if plan_product.get("is_trial") or plan_product.get("account_type") != "subscriber":
        return None
    if line <= int(plan_product.get("max_connections") or 0):
        return None
    try:
        term = int(next(iter(plan_product["prices"])))
    except (TypeError, ValueError):
        return None
    _, by_term = await store_table(panel)
    sizes = sorted(n for (n, t) in by_term if t == term and n >= line)
    return by_term[(sizes[0], term)] if sizes else None


async def renewal_plan(user_id, service_id, product):
    """create_order: the plan to charge for renewing this line (None = the one in the cart is right)."""
    svc = await D["db"].services.find_one({"_id": _oid(service_id), "user_id": str(user_id)})
    if not svc or svc.get("panel_type") != (product or {}).get("panel_type"):
        return None
    if svc.get("is_trial"):   # 2026-10-05: keeping a trial login: the customer picks the plan's devices (Imperium trials have 2)
        return None
    return await bigger_plan(svc["panel_type"], int(svc.get("max_connections") or 0), product)


async def reconcile_all():
    """Hourly (after the panel sync): move lines with more devices than their plan to the right plan."""
    db = D["db"]
    changed = []
    async for s in db.services.find({"status": "active", "panel_type": {"$in": list(NAMES)}, "account_type": "subscriber",
                                     "is_trial": {"$ne": True}}, {"product_id": 1, "max_connections": 1, "panel_type": 1,
                                                                  "username": 1, "xtream_username": 1}):
        p = await db.products.find_one({"_id": _oid(s.get("product_id"))}) if _oid(s.get("product_id")) else None
        new = await bigger_plan(s["panel_type"], int(s.get("max_connections") or 0), p)
        if not new:
            continue
        await db.services.update_one({"_id": s["_id"]}, {"$set": {"product_id": str(new["_id"]), "product_name": new.get("name"),
                                                                   "updated_at": datetime.utcnow()},
                                                          "$push": {"cmtv_plan_changes": {"from": str(p["_id"]), "to": str(new["_id"]),
                                                                                          "devices": s.get("max_connections"),
                                                                                          "why": "more devices on the panel", "at": datetime.utcnow()}}})
        changed.append(f"{svc_login(s)}: {p.get('name')} -> {new.get('name')}")
    if changed:
        log.info(f"Renewal plans matched to the panel's device count: {changed}")
        try:
            import cmtv_notify
            await cmtv_notify.ops("📶 <b>Plans updated to match devices on the panel</b> (they'll renew at this size):\n"
                                  + "\n".join(html.escape(c) for c in changed[:20]), kind="billing", silent=True)
        except Exception:
            pass
    return changed


# ---------------------------------------------------------------- routes
def init_routes():
    current = D["get_current_user"]

    @router.get("/options/{sid}")
    async def options(sid: str, current_user: dict = Depends(current)):
        svc = await _service(current_user["sub"], sid)
        try:
            return await options_for(svc)
        except HTTPException:
            raise
        except Exception as e:
            log.warning(f"Upgrade options for {sid}: {type(e).__name__}: {e}")
            raise HTTPException(503, "The panel can't be reached right now. Please try again in a few minutes.")
