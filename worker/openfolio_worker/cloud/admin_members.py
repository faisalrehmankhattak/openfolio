"""The owner's Members and Reviews tabs.

GET  /admin?tab=members                       every member: status, dates, actions
POST /admin/members/{id}/pause|unpause|reset|delete
GET  /admin?tab=reviews                       profiles waiting to go live
GET  /admin/reviews/{id}                      the submitted page, with its AI running (owner only)
POST /admin/reviews/{id}/approve|reject       with an optional note, emailed when SMTP is set

Every action is written to the audit log.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import ValidationError

from .admin import AUDIT_LABELS, AdminAuth, ExtraTab
from .auth import Session
from .mail import reset_email, review_email
from .members import erase_member, issue_reset, refresh_live
from .profile import to_persona
from .public_profile import profile_context
from .store import Decision
from .web import CloudContext

MEMBER_ACTIONS = ("pause", "unpause", "reset", "delete")
REVIEW_ACTIONS = ("approve", "reject")
MAX_NOTE = 1000


class MemberAdmin:
    def __init__(self, ctx: CloudContext, auth: AdminAuth) -> None:
        self.ctx = ctx
        self.auth = auth

    @property
    def tabs(self) -> dict[str, ExtraTab]:
        return {"members": self.members_tab, "reviews": self.reviews_tab}

    async def _page(self, request: Request, session: Session, template: str, **context: Any) -> Response:
        ctx = self.ctx
        response = ctx.render(
            request,
            template,
            counts=await self.auth.tab_counts(),
            flash=self.auth.read_flash(request, session),
            csrf=ctx.keys.csrf_token(session),
            mail_enabled=ctx.mailer.enabled,
            audit=await ctx.db.run(ctx.db.recent_audit, 50),
            audit_labels=AUDIT_LABELS,
            **context,
        )
        self.auth.clear_flash(request, response)
        return response

    async def members_tab(self, request: Request, session: Session) -> Response:
        members = await self.ctx.db.run(self.ctx.store.list_members)
        return await self._page(request, session, "admin_members.html", tab="members", members=members)

    async def reviews_tab(self, request: Request, session: Session) -> Response:
        reviews = await self.ctx.db.run(self.ctx.store.open_reviews)
        return await self._page(request, session, "admin_reviews.html", tab="reviews", reviews=reviews)

    def router(self) -> APIRouter:
        router = APIRouter(include_in_schema=False)
        ctx, auth = self.ctx, self.auth
        db, store = ctx.db, ctx.store

        @router.post("/admin/members/{user_id}/{action}")
        async def member_action(request: Request, user_id: int, action: str) -> Response:
            session = await auth.current_session(request)
            if session is None:
                return auth.to_login()
            form = await auth.checked_form(request, session)
            if isinstance(form, Response):
                return form
            if action not in MEMBER_ACTIONS:
                return auth.refuse(request, 404, "Unknown action.")
            response = RedirectResponse("/admin?tab=members", status_code=303)
            now, ip_hash = ctx.now(), ctx.ip_hash(request)
            user = await db.run(store.get_user, user_id)
            if user is None:
                auth.set_flash(response, session, {"kind": "note", "text": "That member no longer exists."})
                return response
            if action in ("pause", "unpause"):
                await db.run(store.set_user_status, user.id, "paused" if action == "pause" else "active")
                await refresh_live(ctx)
                await db.run(db.audit, f"user.{action}d", now=now, ip_hash=ip_hash, user_id=user.id)
                text = (
                    f"Paused @{user.handle}: their page and AI are offline and they are signed out."
                    if action == "pause"
                    else f"@{user.handle} is active again."
                )
                auth.set_flash(response, session, {"kind": "note", "text": text})
            elif action == "reset":
                link = await issue_reset(ctx, user)
                emailed: bool | None = None
                if ctx.mailer.enabled:
                    emailed = await ctx.mailer.send(user.email, *reset_email(user.name, link))
                await db.run(db.audit, "user.reset.issued", now=now, ip_hash=ip_hash, user_id=user.id)
                auth.set_flash(
                    response,
                    session,
                    {"kind": "reset", "handle": user.handle, "email": user.email, "link": link, "emailed": emailed},
                )
            else:
                await erase_member(ctx, user.id)
                await db.run(db.audit, "user.deleted", now=now, ip_hash=ip_hash, detail="by the owner")
                auth.set_flash(
                    response, session, {"kind": "note", "text": f"Deleted @{user.handle} and all their data."}
                )
            return response

        @router.get("/admin/reviews/{review_id}")
        async def review_preview(request: Request, review_id: int) -> Response:
            session = await auth.current_session(request)
            if session is None:
                return auth.to_login()
            review = await db.run(store.get_review, review_id)
            if review is None:
                return auth.refuse(request, 404, "That submission no longer exists.")
            try:
                persona = to_persona(review.handle, review.data, ctx.cloud.public_url)
            except ValidationError:
                return auth.refuse(request, 409, "That submission doesn't validate any more.")
            context = profile_context(ctx, persona, review.data, show_in_search=False)
            # The public page's template, but the widget runs the submitted copy and the review controls show.
            context.update(
                widget_id=f"{review.handle}~preview",
                preview_note=(
                    f"Submission from @{review.handle}, not public yet. The AI below answers from this version."
                ),
                review=review,
            )
            return ctx.render(
                request,
                "profile_page.html",
                csp=ctx.widget_csp,
                headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex"},
                csrf=ctx.keys.csrf_token(session),
                **context,
            )

        @router.post("/admin/reviews/{review_id}/{action}")
        async def review_action(request: Request, review_id: int, action: str) -> Response:
            session = await auth.current_session(request)
            if session is None:
                return auth.to_login()
            form = await auth.checked_form(request, session)
            if isinstance(form, Response):
                return form
            if action not in REVIEW_ACTIONS:
                return auth.refuse(request, 404, "Unknown action.")
            note = form.get("note", "").replace("\r\n", "\n").strip()[:MAX_NOTE]
            response = RedirectResponse("/admin?tab=reviews", status_code=303)
            now, ip_hash = ctx.now(), ctx.ip_hash(request)
            decision: Decision = "approved" if action == "approve" else "rejected"
            review = await db.run(store.decide, review_id, decision, note, now)
            if review is None:
                auth.set_flash(response, session, {"kind": "note", "text": "That submission was already decided."})
                return response
            await refresh_live(ctx)
            user = await db.run(store.get_user, review.user_id)
            emailed: bool | None = None
            if user and ctx.mailer.enabled:
                page_url = f"{ctx.cloud.public_url}/p/{review.handle}"
                emailed = await ctx.mailer.send(
                    user.email,
                    *review_email(
                        user.name, action == "approve", note, page_url, f"{ctx.cloud.public_url}/studio/publish"
                    ),
                )
            detail = {None: "", True: "emailed", False: "email failed"}[emailed]
            await db.run(
                db.audit, f"review.{decision}", now=now, ip_hash=ip_hash, user_id=review.user_id, detail=detail
            )
            text = (
                f"@{review.handle} is live at /p/{review.handle}."
                if action == "approve"
                else f"Sent @{review.handle}'s page back{' with your note' if note else ''}."
            )
            auth.set_flash(response, session, {"kind": "note", "text": text})
            return response

        return router
