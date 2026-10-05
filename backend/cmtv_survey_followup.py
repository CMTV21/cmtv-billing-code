"""Survey follow-up (CMTV local addition 2026-10-05, the owner: "a list on the survey page that I click responded and make
it possible to respond back quickly from the panel"). Admin > Customers > Survey > Responses:
- every answer (unhappy 0-6 first), with a Responded tick (cmtv_survey_responses.followup.done);
- Reply: the owner's message goes to the customer as a branded email ("Thanks for your feedback"), quoting their comment,
  and the response is marked responded; each reply is kept in followup.replies.
Placeholder accounts (@panel.local, no email) can only be ticked.
"""
import html
import logging
from datetime import datetime

from bson import ObjectId
from fastapi import APIRouter, Body, Depends, HTTPException

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/cmtv/survey/admin/followup", tags=["cmtv-survey"])
D = {}


def init(**deps):
    D.update(deps)


def _emailable(e):
    e = str(e or "")
    return "@" in e and not e.endswith("@panel.local")


def _oid(v):
    return ObjectId(str(v)) if ObjectId.is_valid(str(v)) else None


def _rid(v):
    """A survey response's _id: "<survey>:<user id>" text (not an ObjectId) - 2026-10-05 fix, the tick said 404"""
    return ObjectId(str(v)) if ObjectId.is_valid(str(v)) else str(v)


def reply_email(first, text, comment):
    from cmtv_gifts import _shell, P, FONT
    msg = html.escape(text.strip()).replace("\n", "<br>")
    quote = ""
    if comment:
        quote = (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 20px;"><tr>'
                 f'<td width="4" style="background-color:#5533ff; border-radius:2px; font-size:1px; line-height:1px;">&nbsp;</td>'
                 f'<td style="padding:4px 0 4px 14px; font-size:14px; line-height:1.6; color:#6b7280; font-style:italic; {FONT}">'
                 f'You wrote: &ldquo;{html.escape(comment)}&rdquo;</td></tr></table>')
    body = (f'<p style="{P}">Hi {html.escape(first or "there")},</p>'
            f'<p style="margin:0 0 20px; font-size:15px; line-height:1.6; color:#374151; {FONT}">{msg}</p>' + quote
            + f'<p style="margin:0 0 14px; font-size:13px; line-height:1.6; color:#6b7280; {FONT}">Just reply to this email if you '
              "want to tell us more.</p>")
    return _shell("A reply to your CMTV survey", "Thanks for your feedback", body)


def init_routes():
    admin = D["get_current_admin_user"]

    @router.get("")
    async def responses(current_user: dict = Depends(admin)):
        db = D["db"]
        rows = await db.cmtv_survey_responses.find({"answers": {"$exists": True}}).to_list(2000)
        users = {str(u["_id"]): u async for u in db.users.find(
            {"_id": {"$in": [o for o in (_oid(r.get("user_id")) for r in rows) if o]}}, {"name": 1, "email": 1})}
        out = []
        for r in rows:
            a = r.get("answers") or {}
            u = users.get(str(r.get("user_id")), {})
            f = r.get("followup") or {}
            nps = a.get("nps")
            out.append({
                "id": str(r["_id"]), "user_id": r.get("user_id"), "name": u.get("name") or r.get("name") or "",
                "email": u.get("email") if _emailable(u.get("email")) else "", "servers": r.get("servers") or [],
                "at": r.get("completed_at") or r.get("first_completed_at"), "nps": nps, "stars": a.get("stars"),
                "comment": (a.get("comment") or "").strip(), "leave": a.get("leave") or [], "improve": a.get("improve") or [],
                "ratings": a.get("ratings") or {}, "unhappy": nps is not None and int(nps) <= 6,
                "done": bool(f.get("done")), "done_at": f.get("done_at"), "replies": f.get("replies") or []})
        out.sort(key=lambda x: (x["done"], not x["unhappy"], -(x["at"].timestamp() if x["at"] else 0)))
        return {"rows": out, "to_reply": sum(not x["done"] for x in out)}

    @router.post("/{rid}/done")
    async def mark(rid: str, data: dict = Body(default={}), current_user: dict = Depends(admin)):
        done = bool(data.get("done", True))
        r = await D["db"].cmtv_survey_responses.update_one({"_id": _rid(rid)}, {"$set": {
            "followup.done": done, "followup.done_at": datetime.utcnow() if done else None,
            "followup.done_by": current_user.get("sub")}})
        if not r.matched_count:
            raise HTTPException(404, "Response not found")
        return {"ok": True, "done": done}

    @router.post("/{rid}/reply")
    async def reply(rid: str, data: dict = Body(...), current_user: dict = Depends(admin)):
        text = str(data.get("text") or "").strip()
        if not 2 <= len(text) <= 3000:
            raise HTTPException(400, "Write a message first.")
        db = D["db"]
        r = await db.cmtv_survey_responses.find_one({"_id": _rid(rid)})
        if not r:
            raise HTTPException(404, "Response not found")
        u = await db.users.find_one({"_id": _oid(r.get("user_id"))}, {"name": 1, "email": 1}) or {}
        if not _emailable(u.get("email")):
            raise HTTPException(400, "This customer has no email address. Reach them another way, then tick Responded.")
        first = (u.get("name") or r.get("name") or "").split(" ")[0]
        page = reply_email(first, text, ((r.get("answers") or {}).get("comment") or "").strip())
        es = await D["get_email_service"]()
        subject = "A reply to your CMTV survey"
        ok = await es.send_email(to_email=u["email"], subject=subject, html_content=es._wrap_email(page, subject, u["email"], "transactional"),
                                 email_type="transactional", customer_id=str(r.get("user_id")), recipient_name=u.get("name", ""))
        if ok is False:
            raise HTTPException(500, "The email couldn't be sent. Check the email settings.")
        now = datetime.utcnow()
        await db.cmtv_survey_responses.update_one({"_id": r["_id"]}, {
            "$set": {"followup.done": True, "followup.done_at": now, "followup.done_by": current_user.get("sub")},
            "$push": {"followup.replies": {"text": text, "at": now, "by": current_user.get("sub"), "to": u["email"]}}})
        logger.info(f"Survey reply sent to {u['email']}")
        return {"ok": True}
