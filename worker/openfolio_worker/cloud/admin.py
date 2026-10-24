"""The owner's pages: sign-in, the request queue with approve / reject / delete, and the audit log.

GET  /admin/login, POST /admin/login, POST /admin/logout
GET  /admin?tab=pending|approved|rejected      access requests (this module)
GET  /admin?tab=members|reviews                members and go-live reviews (admin_members.py)
POST /admin/requests/{id}/approve|reject|delete

Without a valid session every route redirects to the sign-in page. Every POST needs the
session's CSRF token, and requests from another origin are refused before anything else.
"""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse

from .auth import SESSION_SECONDS, Session, hash_token, verify_password
from .db import INVITE_SECONDS, STATUSES, Status
from .forms import FormError, read_form
from .mail import invite_email
from .web import CloudContext

LOGIN_WINDOW_SECONDS = 15 * 60
MAX_FAILED_LOGINS = 5
FLASH_SECONDS = 120
LOGIN_ERROR = "That password didn't work."
LOCKED_ERROR = "Too many attempts. Please wait 15 minutes and try again."
ACTIONS = ("approve", "reject", "delete")
AUDIT_LABELS = {
    "request.created": "New request",
    "request.duplicate": "Repeat request (ignored)",
    "request.approved": "Approved",
    "request.rejected": "Rejected",
    "request.deleted": "Deleted",
    "login": "Signed in",
    "login.failed": "Failed sign-in",
    "logout": "Signed out",
    "purge": "Retention purge",
    "user.created": "Member joined",
    "user.login": "Member signed in",
    "user.login.failed": "Member sign-in failed",
    "user.logout": "Member signed out",
    "user.password.changed": "Member changed password",
    "user.password.reset": "Member reset password",
    "user.reset.requested": "Reset link requested",
    "user.reset.issued": "Reset link issued",
    "user.paused": "Member paused",
    "user.unpaused": "Member unpaused",
    "user.deleted": "Member deleted",
    "file.uploaded": "File uploaded",
    "file.rejected": "Upload refused",
    "file.deleted": "File deleted",
    "draft.created": "AI draft",
    "draft.failed": "AI draft failed",
    "persona.saved": "Profile saved",
    "persona.submitted": "Submitted for review",
    "persona.withdrawn": "Review withdrawn",
    "persona.paused": "Page paused",
    "persona.resumed": "Page resumed",
    "review.approved": "Page approved",
    "review.rejected": "Page sent back",
    "data.exported": "Data exported",
}
ExtraTab = Callable[[Request, Session], Awaitable[Response]]


class AdminAuth:
    """The owner's session, CSRF checks and one-time flash messages, shared by every admin module."""

    flash_cookie = "openfolio_flash"

    def __init__(self, ctx: CloudContext) -> None:
        self.ctx = ctx
        # The __Host- prefix makes browsers refuse the cookie unless it is Secure, host-only and Path=/.
        self.session_cookie = "__Host-openfolio_admin" if ctx.cloud.secure else "openfolio_admin"

    async def current_session(self, request: Request) -> Session | None:
        session = self.ctx.keys.read_session(request.cookies.get(self.session_cookie), now=self.ctx.clock())
        if session is None or await self.ctx.db.run(self.ctx.db.is_revoked, session.sid):
            return None
        return session

    async def signed_in(self, request: Request) -> bool:
        return await self.current_session(request) is not None

    @staticmethod
    def to_login() -> RedirectResponse:
        return RedirectResponse("/admin/login", status_code=303)

    def refuse(self, request: Request, status: int, text: str) -> Response:
        return self.ctx.render(
            request,
            "message.html",
            status=status,
            kind="error",
            heading="Request refused",
            text=text,
            link="/admin",
            link_text="Back to the admin page",
        )

    def foreign_origin(self, request: Request) -> bool:
        origin = request.headers.get("origin")
        return origin is not None and origin != self.ctx.cloud.public_url

    async def checked_form(self, request: Request, session: Session) -> dict[str, str] | Response:
        """The posted form, or a 403 page when the origin or CSRF token is wrong."""
        if self.foreign_origin(request):
            return self.refuse(request, 403, f"Open the admin page at {self.ctx.cloud.public_url} and try again.")
        try:
            form = await read_form(request)
        except FormError:
            form = {}  # an unreadable body carries no CSRF token either
        if not self.ctx.keys.check_csrf(session, form.get("csrf")):
            return self.refuse(request, 403, "This form expired. Reload the admin page and try again.")
        return form

    def set_flash(self, response: Response, session: Session, data: dict[str, Any]) -> None:
        # Signed, short-lived and bound to the session: an invite or reset link is shown once, then deleted.
        value = self.ctx.keys.sign("flash", {**data, "sid": session.sid, "exp": self.ctx.now() + FLASH_SECONDS})
        response.set_cookie(
            self.flash_cookie,
            value,
            max_age=FLASH_SECONDS,
            path="/admin",
            httponly=True,
            samesite="strict",
            secure=self.ctx.cloud.secure,
        )

    def read_flash(self, request: Request, session: Session) -> dict[str, Any] | None:
        data = self.ctx.keys.unsign("flash", request.cookies.get(self.flash_cookie))
        if not data or data.get("sid") != session.sid or not isinstance(data.get("exp"), int):
            return None
        return data if data["exp"] >= self.ctx.now() else None

    def clear_flash(self, request: Request, response: Response) -> None:
        if request.cookies.get(self.flash_cookie):
            response.delete_cookie(
                self.flash_cookie, path="/admin", httponly=True, samesite="strict", secure=self.ctx.cloud.secure
            )

    async def tab_counts(self) -> dict[str, int]:
        db, store = self.ctx.db, self.ctx.store
        counts = {str(status): n for status, n in (await db.run(db.counts)).items()}
        counts["members"] = await db.run(store.member_count)
        counts["reviews"] = await db.run(store.review_count)
        return counts


def admin_router(ctx: CloudContext, auth: AdminAuth, extra_tabs: dict[str, ExtraTab] | None = None) -> APIRouter:
    router = APIRouter(include_in_schema=False)
    db, keys, cloud = ctx.db, ctx.keys, ctx.cloud
    tabs = extra_tabs or {}

    def login_page(request: Request, *, status: int = 200, error: str | None = None) -> Response:
        signed_out = request.query_params.get("out") == "1" and error is None
        return ctx.render(request, "admin_login.html", status=status, error=error, signed_out=signed_out)

    @router.get("/admin/login")
    async def login_form(request: Request) -> Response:
        if await auth.current_session(request):
            return RedirectResponse("/admin", status_code=303)
        return login_page(request)

    @router.post("/admin/login")
    async def login(request: Request) -> Response:
        if auth.foreign_origin(request):
            return auth.refuse(request, 403, f"Open the admin page at {cloud.public_url} and try again.")
        ip_hash, now = ctx.ip_hash(request), ctx.now()
        if await db.run(db.failed_logins_since, ip_hash, now - LOGIN_WINDOW_SECONDS) >= MAX_FAILED_LOGINS:
            return login_page(request, status=429, error=LOCKED_ERROR)
        try:
            password = (await read_form(request)).get("password", "")[:1024]
        except FormError:
            password = ""
        # scrypt is deliberately slow (tens of milliseconds): keep it off the event loop.
        if not password or not await asyncio.to_thread(verify_password, password, cloud.admin_password_hash):
            await db.run(db.audit, "login.failed", now=now, ip_hash=ip_hash)
            return login_page(request, status=401, error=LOGIN_ERROR)
        cookie, _ = keys.new_session(now)
        await db.run(db.audit, "login", now=now, ip_hash=ip_hash)
        response = RedirectResponse("/admin", status_code=303)
        response.set_cookie(
            auth.session_cookie,
            cookie,
            max_age=SESSION_SECONDS,
            path="/",
            httponly=True,
            samesite="strict",
            secure=cloud.secure,
        )
        return response

    @router.post("/admin/logout")
    async def logout(request: Request) -> Response:
        session = await auth.current_session(request)
        if session is None:
            return auth.to_login()
        form = await auth.checked_form(request, session)
        if isinstance(form, Response):
            return form
        # Remember the id until it would expire anyway, so a copied cookie stops working now.
        await db.run(db.revoke_session, session.sid, session.issued_at + SESSION_SECONDS)
        await db.run(db.audit, "logout", now=ctx.now(), ip_hash=ctx.ip_hash(request))
        response = RedirectResponse("/admin/login?out=1", status_code=303)
        response.delete_cookie(auth.session_cookie, path="/", httponly=True, samesite="strict", secure=cloud.secure)
        response.delete_cookie(auth.flash_cookie, path="/admin", httponly=True, samesite="strict", secure=cloud.secure)
        return response

    @router.get("/admin")
    async def dashboard(request: Request) -> Response:
        session = await auth.current_session(request)
        if session is None:
            return auth.to_login()
        tab = request.query_params.get("tab", "pending")
        if tab in tabs:
            return await tabs[tab](request, session)
        status: Status = tab if tab in STATUSES else "pending"  # type: ignore[assignment]
        counts = await auth.tab_counts()
        rows = await db.run(db.list_requests, status)
        audit = await db.run(db.recent_audit, 50)
        flash = auth.read_flash(request, session)
        response = ctx.render(
            request,
            "admin.html",
            tab=status,
            counts=counts,
            rows=rows,
            audit=audit,
            audit_labels=AUDIT_LABELS,
            flash=flash,
            csrf=keys.csrf_token(session),
            mail_enabled=ctx.mailer.enabled,
        )
        auth.clear_flash(request, response)
        return response

    @router.post("/admin/requests/{request_id}/{action}")
    async def decide(request: Request, request_id: int, action: str) -> Response:
        session = await auth.current_session(request)
        if session is None:
            return auth.to_login()
        form = await auth.checked_form(request, session)
        if isinstance(form, Response):
            return form
        if action not in ACTIONS:
            return auth.refuse(request, 404, "Unknown action.")
        tab = form.get("tab") if form.get("tab") in STATUSES else "pending"
        response = RedirectResponse(f"/admin?tab={tab}", status_code=303)
        now, ip_hash = ctx.now(), ctx.ip_hash(request)
        req = await db.run(db.get_request, request_id)
        if req is None:
            auth.set_flash(response, session, {"kind": "note", "text": "That request no longer exists."})
            return response

        if action == "delete":
            await db.run(db.delete_request, request_id)
            await db.run(db.audit, "request.deleted", now=now, request_id=request_id, ip_hash=ip_hash)
            auth.set_flash(response, session, {"kind": "note", "text": f"Deleted the request from {req.name}."})
        elif action == "reject":
            await db.run(db.reject, request_id, now)
            await db.run(db.audit, "request.rejected", now=now, request_id=request_id, ip_hash=ip_hash)
            auth.set_flash(
                response, session, {"kind": "note", "text": f"Rejected {req.name}. Nothing is sent to them."}
            )
        else:
            token = secrets.token_urlsafe(32)
            await db.run(db.approve, request_id, hash_token(token), now)
            link = f"{cloud.public_url}/join/{token}"
            emailed: bool | None = None
            if ctx.mailer.enabled:
                emailed = await ctx.mailer.send(req.email, *invite_email(req.name, link, now + INVITE_SECONDS))
            detail = {None: "email not set up", True: "invite emailed", False: "invite email failed"}[emailed]
            await db.run(db.audit, "request.approved", now=now, request_id=request_id, ip_hash=ip_hash, detail=detail)
            auth.set_flash(
                response,
                session,
                {"kind": "invite", "name": req.name, "email": req.email, "link": link, "emailed": emailed},
            )
            response.headers["location"] = "/admin?tab=approved"
        return response

    return router
