"""Customer survey (CMTV local addition 2026-09-29; the user's choices: all paying customers, linked answers, $5 credit).
One personal link per customer (/survey?t=<token>), sent once by email (marketing: unsubscribes honoured) and Telegram if
connected. Finishing it adds $5 account credit once (billing's credit service, shown in their credit history).
  GET  /api/cmtv/survey/q/{token}          public (token): the questions + the customer's first name
  POST /api/cmtv/survey/q/{token}          public (token): save answers (can be updated; credit only the first time)
  GET  /api/cmtv/survey/admin              admin: invited/answered, NPS, averages (overall and by server), counts, comments
  POST /api/cmtv/survey/admin/send {dry_run=true}  admin: invite every eligible paying customer not yet invited
Collections: cmtv_survey_invites (_id = token), cmtv_survey_responses (_id = "<survey>:<user>").
"""
import asyncio
import html
import logging
import secrets
from datetime import datetime

from bson import ObjectId
from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException

import cmtv_lines as L

log = logging.getLogger("server")
router = APIRouter(prefix="/api/cmtv/survey", tags=["cmtv-survey"])
D = {}
SURVEY = "2026-10"
SITE = "https://billing.cmtv.info"
REWARD = 5.0

QUESTIONS = [
    {"id": "nps", "type": "nps", "required": True, "text": "How likely are you to recommend CMTV to a friend?"},
    {"id": "stars", "type": "stars", "required": True, "text": "Overall, how happy are you with CMTV?"},
    {"id": "devices", "type": "multi", "text": "Which devices do you watch on?",
     "options": ["Firestick", "Android TV or Google TV box (e.g. ONN)", "Android phone or tablet", "iPhone or iPad", "Smart TV", "PC or Mac"]},
    {"id": "app", "type": "single", "text": "Which app do you use most?",
     "options": ["CMTVGhost", "TiviMate", "MYTVONLINE+", "Web player", "Other"]},
    {"id": "ratings", "type": "grid", "text": "How would you rate these?",
     "items": ["Picture quality (little buffering)", "Live channels", "Sports", "Movies and series", "TV guide", "Support"]},
    {"id": "improve", "type": "multi", "other": True, "text": "What should we add or improve?",
     "options": ["More sports and PPV", "More international channels", "More 4K", "Catch-up and replays", "Kids content",
                 "Better apps", "A music app", "A different server option", "Better pricing", "More updates about the service",
                 "Better guides"]},   # 2026-09-29: the user's list (longer plans / multi-home plan removed)
    {"id": "addons", "type": "addons", "text": "What about our add-ons?", "items": ["Stremio", "CMTVpn", "Audiobooks"],
     "choices": ["I have it", "Interested", "Not interested"]},
    {"id": "leave", "type": "multi", "other": True, "text": "What could make you not renew?",
     "options": ["Price", "Buffering or outages", "Missing channels", "App problems", "Support", "Found another service",
                 "Not watching enough", "Nothing, I'll stay"]},
    {"id": "comment", "type": "text", "text": "Anything else you'd like to tell us?"},
]
Q = {q["id"]: q for q in QUESTIONS}


def init(**deps):
    D.update(deps)


def _oid(v):
    return ObjectId(v) if ObjectId.is_valid(str(v)) else None


def _first(u):
    return (str(u.get("name") or "").split(" ")[0] or "there").strip()


def server_of(s):
    pt, name = s.get("panel_type"), str(s.get("product_name") or "").lower()
    if "amethyst" in name:
        return "Amethyst"
    if pt == "onestream" or "extreme" in name:
        return "Extreme"
    if pt in ("aether", "nxtdash") or "imperium" in name:
        return "Imperium"
    if pt in ("xtream", "xuione"):
        return "CCTV"
    return None


async def servers_for(uid):
    out = set()
    now = datetime.utcnow()
    # CMTV local change 2026-10-08: trial-named lines that were paid for and extended count (shared rule, cmtv_lines)
    async for s in D["db"].services.find({"user_id": uid, "status": "active", "account_type": {"$ne": "reseller"}}):
        if not L.is_paid_line(s, now):
            continue
        sv = server_of(s)
        if sv:
            out.add(sv)
    return sorted(out)


def clean_answers(body: dict) -> dict:
    """Validates answers against QUESTIONS; raises HTTPException(400) with a readable message."""
    a, out = body.get("answers") or {}, {}
    for q in QUESTIONS:
        v = a.get(q["id"])
        t = q["type"]
        if t == "nps":
            if v is None or not isinstance(v, int) or not 0 <= v <= 10:
                raise HTTPException(400, "Please pick a number from 0 to 10 for the first question.")
            out[q["id"]] = v
        elif t == "stars":
            if v is None or not isinstance(v, int) or not 1 <= v <= 5:
                raise HTTPException(400, "Please pick 1 to 5 stars.")
            out[q["id"]] = v
        elif t == "multi":
            picked = [x for x in (v or {}).get("picked", []) if x in q["options"]] if isinstance(v, dict) else []
            other = str((v or {}).get("other") or "").strip()[:200] if isinstance(v, dict) and q.get("other") else ""
            out[q["id"]] = {"picked": picked, "other": other}
        elif t == "single":
            out[q["id"]] = v if v in q["options"] else None
        elif t == "grid":
            out[q["id"]] = {k: int(r) for k, r in (v or {}).items() if k in q["items"] and isinstance(r, int) and 1 <= r <= 5} \
                if isinstance(v, dict) else {}
        elif t == "addons":
            out[q["id"]] = {k: c for k, c in (v or {}).items() if k in q["items"] and c in q["choices"]} if isinstance(v, dict) else {}
        elif t == "text":
            out[q["id"]] = str(v or "").strip()[:1500]
    return out


# ---------- sending ----------

async def eligible():
    """Paying customers: role user, real email, not demo, an active paid non-trial non-reseller service, not yet invited."""
    db = D["db"]
    invited = set(await db.cmtv_survey_invites.distinct("user_id", {"survey": SURVEY}))
    uids, now = set(), datetime.utcnow()
    # CMTV local change 2026-10-08: trial-named lines that were paid for and extended count (shared rule, cmtv_lines)
    async for s in db.services.find({"status": "active", "account_type": {"$ne": "reseller"}, "cmtv_demo": {"$ne": True}},
                                    {"user_id": 1, "product_name": 1, "is_trial": 1, "expiry_date": 1, "created_at": 1}):
        if L.is_paid_line(s, now):
            uids.add(str(s.get("user_id")))
    out = []
    for uid in sorted(uids - invited):
        u = await db.users.find_one({"_id": _oid(uid), "role": "user"})
        mail = str((u or {}).get("email") or "")
        if not u or u.get("cmtv_demo") or "@" not in mail or mail.lower().endswith("@panel.local"):
            continue
        out.append(u)
    return out


async def send_invite(u):
    db = D["db"]
    uid = str(u["_id"])
    token = secrets.token_urlsafe(18)
    link = f"{SITE}/survey?t={token}"
    now = datetime.utcnow()
    await db.cmtv_survey_invites.insert_one({"_id": token, "survey": SURVEY, "user_id": uid, "created_at": now})
    es = await D["get_email_service"]()
    um = getattr(es, "unsubscribe_manager", None)
    emailed = False
    tpl = await db.email_templates.find_one({"template_type": "cmtv_survey", "is_active": True})
    if tpl and es and getattr(es, "enabled", False) and not (um and not await um.can_send_marketing(u["email"])):
        # 2026-09-29: the CMTV website look (template "cmtv_survey", editable in Admin > Email Templates), sent as a
        # complete navy page with its own unsubscribe link (so the plain wrapper's white footer isn't added)
        vals = {"first_name": html.escape(_first(u)), "survey_link": link, "reward": f"${REWARD:.0f}",
                "unsubscribe_link": f"{es.backend_url}/api/unsubscribe?email={u['email']}"}
        page, subject = tpl["html_content"], tpl.get("subject") or "Quick CMTV survey: 2 minutes, {{reward}} credit"
        for k, v in vals.items():
            page, subject = page.replace("{{" + k + "}}", v), subject.replace("{{" + k + "}}", v)
        page = ("<!DOCTYPE html><html><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width\">"
                "<meta name=\"color-scheme\" content=\"dark\"></head>"
                f"<body style=\"margin:0; padding:0; background-color:#0a1020;\">{page}</body></html>")
        text = (f"Hi {_first(u)},\n\nWe're planning what to improve next at CMTV and we'd love your honest opinion. It takes about "
                f"2 minutes, and we'll add ${REWARD:.0f} credit to your account when you finish.\n\nTake the survey: {link}\n\n"
                f"The CMTV Team\n\nUnsubscribe from offers and surveys: {vals['unsubscribe_link']}")
        try:
            emailed = bool(await es.send_email(
                to_email=u["email"], subject=subject, html_content=page, text_content=text,
                email_type="marketing", template_type="cmtv_survey", customer_id=uid, recipient_name=u.get("name") or ""))
        except Exception as e:
            log.warning(f"survey email to {u.get('email')} failed: {e}")
    elif es and getattr(es, "enabled", False) and not (um and not await um.can_send_marketing(u["email"])):
        first = html.escape(_first(u))
        body = (f"<h2 style=\"margin:0 0 8px\">2 minutes, $5 credit</h2>"
                f"<p>Hi {first}, we're planning what to improve next at CMTV and we'd love your honest opinion: what works, "
                f"what doesn't, and what you'd like us to add.</p>"
                f"<p>It takes about 2 minutes. When you finish, we'll add <strong>$5 credit</strong> to your account, "
                f"used automatically on your next renewal.</p>"
                f"<p style=\"margin:22px 0\"><a href=\"{link}\" style=\"background:#22e6f2;color:#07101a;padding:12px 22px;"
                f"border-radius:999px;text-decoration:none;font-weight:700\">Take the survey</a></p>"
                f"<p style=\"color:#666;font-size:13px\">Your answers go to the CMTV team with your account, so we can follow up "
                f"if something isn't right.</p>")
        try:
            emailed = bool(await es.send_email(
                to_email=u["email"], subject="Quick CMTV survey: 2 minutes, $5 credit",
                html_content=es._wrap_email(body, "Customer survey", u["email"], "marketing"),
                email_type="marketing", template_type="cmtv_survey", customer_id=uid, recipient_name=u.get("name") or ""))
        except Exception as e:
            log.warning(f"survey email to {u.get('email')} failed: {e}")
    tg = (u.get("cmtv_telegram") or {}).get("chat_id")
    if tg:
        try:
            import cmtv_telegram_alerts
            await cmtv_telegram_alerts.queue(uid, tg, f"📝 <b>Quick CMTV survey, {html.escape(_first(u))}?</b>\n\n2 minutes, and "
                                             "we'll add $5 credit to your account when you finish.",
                                             [[{"text": "Take the survey", "url": link}]], kind="survey")
        except Exception as e:
            log.warning(f"survey telegram failed: {e}")
    await db.cmtv_survey_invites.update_one({"_id": token}, {"$set": {"emailed": emailed, "telegram": bool(tg)}})
    return emailed or bool(tg)


async def send_all(users):
    ok = 0
    for u in users:
        try:
            ok += 1 if await send_invite(u) else 0
        except Exception as e:
            log.warning(f"survey invite failed: {e}")
        await asyncio.sleep(1.5)   # gentle on the mail server
    log.info(f"survey: invited {ok} of {len(users)}")
    await D["db"].cmtv_config.update_one({"_id": "survey_state"}, {"$set": {"last_send_done": datetime.utcnow(), "last_send_ok": ok}}, upsert=True)


# ---------- results ----------

async def results():
    db = D["db"]
    invited = await db.cmtv_survey_invites.count_documents({"survey": SURVEY})
    rows = [r async for r in db.cmtv_survey_responses.find({"survey": SURVEY}).sort("completed_at", -1)]
    n = len(rows)
    nps_vals = [r["answers"]["nps"] for r in rows]
    promoters, detractors = sum(1 for v in nps_vals if v >= 9), sum(1 for v in nps_vals if v <= 6)
    avg = lambda xs: round(sum(xs) / len(xs), 2) if xs else None  # noqa: E731
    grid_items = Q["ratings"]["items"]
    by_server = {}
    for r in rows:
        for sv in r.get("servers") or ["Other"]:
            by_server.setdefault(sv, []).append(r)
    ratings = {it: {"all": avg([r["answers"]["ratings"][it] for r in rows if it in r["answers"].get("ratings", {})]),
                    **{sv: avg([x["answers"]["ratings"][it] for x in rs if it in x["answers"].get("ratings", {})])
                       for sv, rs in by_server.items()}} for it in grid_items}
    counts = {}
    for qid in ("devices", "improve", "leave"):
        c = {o: 0 for o in Q[qid]["options"]}
        for r in rows:
            for o in r["answers"].get(qid, {}).get("picked", []):
                c[o] = c.get(o, 0) + 1
        counts[qid] = c
    app = {o: sum(1 for r in rows if r["answers"].get("app") == o) for o in Q["app"]["options"]}
    addons = {it: {c: sum(1 for r in rows if r["answers"].get("addons", {}).get(it) == c) for c in Q["addons"]["choices"]}
              for it in Q["addons"]["items"]}
    comments = []
    for r in rows:
        a = r["answers"]
        others = [a.get(q, {}).get("other") for q in ("improve", "leave") if a.get(q, {}).get("other")]
        if a.get("comment") or others:
            comments.append({"user_id": r["user_id"], "name": r.get("name"), "nps": a["nps"], "stars": a["stars"],
                             "comment": a.get("comment", ""), "other": others,
                             "at": r["completed_at"].isoformat() + "Z"})
    unhappy = [{"user_id": r["user_id"], "name": r.get("name"), "nps": r["answers"]["nps"], "stars": r["answers"]["stars"],
                "leave": r["answers"].get("leave", {}).get("picked", [])} for r in rows if r["answers"]["nps"] <= 6]
    state = await db.cmtv_config.find_one({"_id": "survey_state"}) or {}
    return {"survey": SURVEY, "invited": invited, "answered": n, "nps": round((promoters - detractors) * 100 / n) if n else None,
            "promoters": promoters, "detractors": detractors, "stars": avg([r["answers"]["stars"] for r in rows]),
            "ratings": ratings, "servers": sorted(by_server), "counts": counts, "app": app, "addons": addons,
            "comments": comments, "unhappy": unhappy, "credit_given": sum(1 for r in rows if r.get("credit_given")),
            "sending": bool(state.get("last_send_started") and (not state.get("last_send_done")
                                                               or state["last_send_done"] < state["last_send_started"]))}


# ---------- routes ----------

def init_routes():
    admin = D["get_current_admin_user"]

    async def _invite(token):
        inv = await D["db"].cmtv_survey_invites.find_one({"_id": token, "survey": SURVEY})
        if not inv:
            raise HTTPException(404, "This survey link isn't valid. Please use the link from your email.")
        return inv

    @router.get("/score")
    async def public_score():   # 2026-10-02: storefront "4.6 out of 5, based on our customer survey" (no count shown)
        stars = [r["answers"]["stars"] async for r in D["db"].cmtv_survey_responses.find(
            {"completed_at": {"$exists": True}, "answers.stars": {"$gte": 1}}, {"answers.stars": 1})]
        if len(stars) < 5:
            return {"stars": None}
        return {"stars": round(sum(stars) / len(stars), 1)}

    @router.get("/q/{token}")
    async def get_survey(token: str):
        inv = await _invite(token)
        u = await D["db"].users.find_one({"_id": _oid(inv["user_id"])}) or {}
        done = await D["db"].cmtv_survey_responses.find_one({"_id": f"{SURVEY}:{inv['user_id']}"})
        return {"questions": QUESTIONS, "first_name": _first(u), "reward": REWARD, "done": bool(done),
                "answers": (done or {}).get("answers")}

    @router.post("/q/{token}")
    async def answer(token: str, body: dict = Body(...)):
        inv = await _invite(token)
        uid = inv["user_id"]
        answers = clean_answers(body)
        db = D["db"]
        u = await db.users.find_one({"_id": _oid(uid)}) or {}
        key = f"{SURVEY}:{uid}"
        prev = await db.cmtv_survey_responses.find_one({"_id": key})
        now = datetime.utcnow()
        await db.cmtv_survey_responses.update_one({"_id": key}, {"$set": {
            "survey": SURVEY, "user_id": uid, "name": u.get("name") or u.get("email"), "answers": answers,
            "servers": await servers_for(uid), "completed_at": now}, "$setOnInsert": {"first_completed_at": now}}, upsert=True)
        credited = False
        if not (prev or {}).get("credit_given"):
            try:
                await D["credit_service"].add_credits(user_id=uid, amount=REWARD, transaction_type="survey_reward",
                                                      description="Thank you for the CMTV survey", created_by="survey",
                                                      bypass_enabled_check=True)
                await db.cmtv_survey_responses.update_one({"_id": key}, {"$set": {"credit_given": now}})
                credited = True
            except Exception as e:
                log.error(f"survey credit for {uid} failed: {e}")
        if not prev:
            try:
                import cmtv_notify
                await cmtv_notify.ops(f"📝 Survey answered: {u.get('name') or u.get('email')} · {answers['nps']}/10 · "
                                      f"{answers['stars']}★" + (f"\n“{answers['comment'][:300]}”" if answers.get("comment") else ""),
                                      "billing", silent=True)
            except Exception:
                pass
        return {"ok": True, "credited": credited, "reward": REWARD}

    @router.get("/admin")
    async def admin_results(current_user: dict = Depends(admin)):
        return await results()

    @router.post("/admin/send")
    async def admin_send(background_tasks: BackgroundTasks, body: dict = Body(...), current_user: dict = Depends(admin)):
        users = await eligible()
        if body.get("dry_run", True) is not False:
            return {"dry_run": True, "count": len(users), "sample": [u.get("name") or u.get("email") for u in users[:8]]}
        await D["db"].cmtv_config.update_one({"_id": "survey_state"}, {"$set": {"last_send_started": datetime.utcnow(),
                                                                                "last_send_by": current_user.get("sub")}}, upsert=True)
        background_tasks.add_task(send_all, users)
        return {"dry_run": False, "count": len(users)}
