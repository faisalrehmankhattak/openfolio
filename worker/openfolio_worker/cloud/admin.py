"""The owner's pages: sign-in, the request queue with approve / reject / delete, and the audit log.

GET  /admin/login, POST /admin/login, POST /admin/logout
GET  /admin?tab=pending|approved|rejected
POST /admin/requests/{id}/approve|reject|delete

Without a valid session every route redirects to the sign-in page. Every POST needs the
session's CSRF token, and requests from another origin are refused before anything else.
"""

from __future__ import annotations

import asyncio
import secrets
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
}


def admin_router(ctx: CloudContext) -> APIRouter:
    router = APIRouter(include_in_schema=False)
    db, keys, cloud = ctx.db, ctx.keys, ctx.cloud
    # The __Host- prefix makes browsers refuse the cookie unless it is Secure, host-only and Path=/.
    session_cookie = "__Host-openfolio_admin" if cloud.secure else "openfolio_admin"
    flash_cookie = "openfolio_flash"

    async def current_session(request: Request) -> Session | None:
        session = keys.read_session(request.cookies.get(session_cookie), now=ctx.clock())
        if session is None or await db.run(db.is_revoked, session.sid):
            return None
        return session

    def to_login() -> RedirectResponse:
        return RedirectResponse("/admin/login", status_code=303)

    def refuse(request: Request, status: int, text: str) -> Response:
        return ctx.render(
            request,
            "message.html",
            status=status,
            kind="error",
            heading="Request refused",
            text=text,
            link="/admin",
            link_text="Back to the admin page",
        )

    def foreign_origin(request: Request) -> bool:
        origin = request.headers.get("origin")
        return origin is not None and origin != cloud.public_url

    async def checked_form(request: Request, session: Session) -> dict[str, str] | Response:
        """The posted form, or a 403 page when the origin or CSRF token is wrong."""
        if foreign_origin(request):
            return refuse(request, 403, f"Open the admin page at {cloud.public_url} and try again.")
        try:
            form = await read_form(request)
        except FormError:
            form = {}  # an unreadable body carries no CSRF token either
        if not keys.check_csrf(session, form.get("csrf")):
            return refuse(request, 403, "This form expired. Reload the admin page and try again.")
        return form

    def set_flash(response: Response, session: Session, data: dict[str, Any]) -> None:
        # Signed, short-lived and bound to the session: the invite link is shown once, then deleted.
        value = keys.sign("flash", {**data, "sid": session.sid, "exp": ctx.now() + FLASH_SECONDS})
        response.set_cookie(
            flash_cookie,
            value,
            max_age=FLASH_SECONDS,
            path="/admin",
            httponly=True,
            samesite="strict",
            secure=cloud.secure,
        )

    def read_flash(request: Request, session: Session) -> dict[str, Any] | None:
        data = keys.unsign("flash", request.cookies.get(flash_cookie))
        if not data or data.get("sid") != session.sid or not isinstance(data.get("exp"), int):
            return None
        return data if data["exp"] >= ctx.now() else None

    def login_page(request: Request, *, status: int = 200, error: str | None = None) -> Response:
        signed_out = request.query_params.get("out") == "1" and error is None
        return ctx.render(request, "admin_login.html", status=status, error=error, signed_out=signed_out)

    @router.get("/admin/login")
    async def login_form(request: Request) -> Response:
        if await current_session(request):
            return RedirectResponse("/admin", status_code=303)
        return login_page(request)

    @router.post("/admin/login")
    async def login(request: Request) -> Response:
        if foreign_origin(request):
            return refuse(request, 403, f"Open the admin page at {cloud.public_url} and try again.")
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
            session_cookie,
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
        session = await current_session(request)
        if session is None:
            return to_login()
        form = await checked_form(request, session)
        if isinstance(form, Response):
            return form
        # Remember the id until it would expire anyway, so a copied cookie stops working now.
        await db.run(db.revoke_session, session.sid, session.issued_at + SESSION_SECONDS)
        await db.run(db.audit, "logout", now=ctx.now(), ip_hash=ctx.ip_hash(request))
        response = RedirectResponse("/admin/login?out=1", status_code=303)
        response.delete_cookie(session_cookie, path="/", httponly=True, samesite="strict", secure=cloud.secure)
        response.delete_cookie(flash_cookie, path="/admin", httponly=True, samesite="strict", secure=cloud.secure)
        return response

    @router.get("/admin")
    async def dashboard(request: Request) -> Response:
        session = await current_session(request)
        if session is None:
            return to_login()
        tab = request.query_params.get("tab", "pending")
        status: Status = tab if tab in STATUSES else "pending"  # type: ignore[assignment]
        counts = await db.run(db.counts)
        rows = await db.run(db.list_requests, status)
        audit = await db.run(db.recent_audit, 50)
        flash = read_flash(request, session)
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
        if request.cookies.get(flash_cookie):
            response.delete_cookie(flash_cookie, path="/admin", httponly=True, samesite="strict", secure=cloud.secure)
        return response

    @router.post("/admin/requests/{request_id}/{action}")
    async def decide(request: Request, request_id: int, action: str) -> Response:
        session = await current_session(request)
        if session is None:
            return to_login()
        form = await checked_form(request, session)
        if isinstance(form, Response):
            return form
        if action not in ACTIONS:
            return refuse(request, 404, "Unknown action.")
        tab = form.get("tab") if form.get("tab") in STATUSES else "pending"
        response = RedirectResponse(f"/admin?tab={tab}", status_code=303)
        now, ip_hash = ctx.now(), ctx.ip_hash(request)
        req = await db.run(db.get_request, request_id)
        if req is None:
            set_flash(response, session, {"kind": "note", "text": "That request no longer exists."})
            return response

        if action == "delete":
            await db.run(db.delete_request, request_id)
            await db.run(db.audit, "request.deleted", now=now, request_id=request_id, ip_hash=ip_hash)
            set_flash(response, session, {"kind": "note", "text": f"Deleted the request from {req.name}."})
        elif action == "reject":
            await db.run(db.reject, request_id, now)
            await db.run(db.audit, "request.rejected", now=now, request_id=request_id, ip_hash=ip_hash)
            set_flash(response, session, {"kind": "note", "text": f"Rejected {req.name}. Nothing is sent to them."})
        else:
            token = secrets.token_urlsafe(32)
            await db.run(db.approve, request_id, hash_token(token), now)
            link = f"{cloud.public_url}/invite/{token}"
            emailed: bool | None = None
            if ctx.mailer.enabled:
                emailed = await ctx.mailer.send(req.email, *invite_email(req.name, link, now + INVITE_SECONDS))
            detail = {None: "email not set up", True: "invite emailed", False: "invite email failed"}[emailed]
            await db.run(db.audit, "request.approved", now=now, request_id=request_id, ip_hash=ip_hash, detail=detail)
            set_flash(
                response,
                session,
                {"kind": "invite", "name": req.name, "email": req.email, "link": link, "emailed": emailed},
            )
            response.headers["location"] = "/admin?tab=approved"
        return response

    return router
