"""Customer dashboard "Help us improve" box (CMTV local addition 2026-10-04, the owner's request):
- Suggestions / feedback: POST /api/cmtv/feedback {kind, text, contact_ok} -> cmtv_feedback + a silent Ops Billing note.
  Admin: GET /api/cmtv/feedback/admin, POST /api/cmtv/feedback/admin/{id} {status: new|read|done} (Admin > Reviews page).
- Leave a review: GET /api/cmtv/feedback/me says whether the customer can review (paid at least once, an active paid
  non-trial service, not reviewed yet); POST /api/cmtv/feedback/review-link makes (or reuses) the same one-time review
  link the emailed invites use (cmtv_review_invites, 60 days; `self: true`), so cmtv_reviews handles the rest.
"""
import html
import re
import secrets
from datetime import datetime, timedelta

from bson import ObjectId
from fastapi import APIRouter, Body, Depends, HTTPException

router = APIRouter(prefix="/api/cmtv/feedback", tags=["cmtv-feedback"])
D = {}
KINDS = {"suggestion": "Suggestion", "problem": "Something isn't working", "other": "Something else"}


def init(**deps):
    D.update(deps)


def _oid(v):
    return ObjectId(str(v)) if v and ObjectId.is_valid(str(v)) else None


def _iso(v):
    return v.isoformat() + "Z" if isinstance(v, datetime) else v


async def review_state(uid):
    db = D["db"]
    if await db.cmtv_reviews.find_one({"user_id": uid}, {"_id": 1}):
        return {"can": False, "already": True}
    paid = await db.orders.find_one({"user_id": uid, "status": "paid", "total": {"$gt": 0}}, {"_id": 1})
    active = await db.services.find_one({"user_id": uid, "status": "active", "is_trial": {"$ne": True},
                                         "account_type": {"$ne": "reseller"}}, {"_id": 1})
    if not paid or not active:
        return {"can": False, "already": False, "reason": "Reviews are for paying customers. Pick a plan first!"}
    return {"can": True, "already": False}


async def ticket_review_link(uid: str):
    """CMTV local change 2026-10-10 (owner): star row in the ticket-closed email. Full one-time review link for a
    paying customer who hasn't reviewed yet (reuses an open invite, like the dashboard button), else None."""
    try:
        db = D["db"]
        if not uid or not (await review_state(uid))["can"]:
            return None
        now = datetime.utcnow()
        inv = await db.cmtv_review_invites.find_one({"user_id": uid, "used_at": {"$exists": False}, "expires_at": {"$gt": now}})
        token = inv["_id"] if inv else secrets.token_urlsafe(18)
        if not inv:
            await db.cmtv_review_invites.insert_one({"_id": token, "user_id": uid, "created_at": now,
                                                    "expires_at": now + timedelta(days=60), "moment": "ticket_closed"})
        return f"https://billing.cmtv.info/review?t={token}"
    except Exception:
        return None


def init_routes():
    current, admin = D["get_current_user"], D["get_current_admin_user"]

    @router.get("/me")
    async def me(current_user: dict = Depends(current)):
        return {"review": await review_state(current_user["sub"])}

    @router.post("/review-link")
    async def review_link(current_user: dict = Depends(current)):
        db, uid = D["db"], current_user["sub"]
        st = await review_state(uid)
        if not st["can"]:
            raise HTTPException(400, "You've already left a review. Thank you!" if st["already"] else st.get("reason"))
        now = datetime.utcnow()
        inv = await db.cmtv_review_invites.find_one({"user_id": uid, "used_at": {"$exists": False}, "expires_at": {"$gt": now}})
        token = inv["_id"] if inv else secrets.token_urlsafe(18)
        if not inv:
            await db.cmtv_review_invites.insert_one({"_id": token, "user_id": uid, "created_at": now,
                                                    "expires_at": now + timedelta(days=60), "self": True})
        return {"link": f"/review?t={token}"}

    @router.post("")
    async def send(data: dict = Body(...), current_user: dict = Depends(current)):
        db, uid = D["db"], current_user["sub"]
        kind = data.get("kind") if data.get("kind") in KINDS else "other"
        text = re.sub(r"[ \t]+", " ", str(data.get("text") or "")).strip()[:1500]
        if len(text) < 3:
            raise HTTPException(400, "Write a few words first.")
        if await db.cmtv_feedback.count_documents({"user_id": uid, "created_at": {"$gte": datetime.utcnow() - timedelta(days=1)}}) >= 5:
            raise HTTPException(429, "Thanks! You've sent a lot today: please try again tomorrow.")
        u = await db.users.find_one({"_id": _oid(uid)}, {"name": 1, "email": 1}) or {}
        await db.cmtv_feedback.insert_one({"user_id": uid, "kind": kind, "text": text, "contact_ok": bool(data.get("contact_ok")),
                                           "status": "new", "created_at": datetime.utcnow()})
        try:
            import cmtv_notify
            await cmtv_notify.ops(f"💡 <b>Customer feedback</b> ({KINDS[kind]}) from {html.escape(u.get('name') or '')}"
                                  f"{' · OK to contact' if data.get('contact_ok') else ''}:\n“{html.escape(text[:600])}”\n"
                                  f"Admin &gt; Reviews &amp; feedback", kind="billing", silent=True)
        except Exception:
            pass
        return {"ok": True}

    @router.get("/admin")
    async def admin_list(current_user: dict = Depends(admin)):
        db = D["db"]
        out = []
        async for f in db.cmtv_feedback.find().sort("created_at", -1).limit(300):
            u = await db.users.find_one({"_id": _oid(f["user_id"])}, {"name": 1, "email": 1}) or {}
            out.append({"id": str(f["_id"]), "kind": KINDS.get(f.get("kind"), "Feedback"), "text": f.get("text"),
                        "contact_ok": f.get("contact_ok"), "status": f.get("status", "new"), "created_at": _iso(f.get("created_at")),
                        "user_id": f["user_id"], "customer": u.get("name"), "email": u.get("email")})
        return {"feedback": out}

    @router.post("/admin/{fid}")
    async def admin_set(fid: str, data: dict = Body(...), current_user: dict = Depends(admin)):
        st = data.get("status")
        if st not in ("new", "read", "done") or not _oid(fid):
            raise HTTPException(400, "Bad request")
        await D["db"].cmtv_feedback.update_one({"_id": _oid(fid)}, {"$set": {"status": st, "updated_at": datetime.utcnow()}})
        return {"ok": True}
