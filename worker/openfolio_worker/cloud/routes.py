"""Openfolio Cloud pages: landing, access requests, privacy, terms and invite links.

GET  /                  landing page with the live demo and the request form
POST /cloud/requests    access request -> 303 /cloud/thanks
GET  /cloud/thanks      the same thank-you page for every accepted (or silently dropped) request
GET  /privacy, /terms   policies
/join, /login, ...      member accounts (accounts.py); /invite/{token} links from stage 1 redirect to /join
/studio/...             the members' Studio (studio.py)
/p/{handle}             live members' public pages (public_profile.py)
/admin/...              the owner's pages (admin.py, admin_members.py)
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable

import httpx
from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger
from starlette.background import BackgroundTask
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..config import Settings
from ..registry import PersonaRegistry
from .accounts import accounts_router
from .admin import AdminAuth, admin_router
from .admin_members import MemberAdmin
from .auth import Keys
from .db import DAY, CloudDB
from .forms import FormError, read_form, validate_request, verify_turnstile
from .mail import Mailer, new_request_email
from .member_auth import MemberAuth
from .members import preview_hook, refresh_live
from .public_profile import public_router as profile_router
from .store import StudioStore
from .studio import Studio
from .uploads import FileStore
from .web import STATIC_DIR, STRICT_CSP, CloudContext

REQUESTS_PER_HOUR = 3
HONEYPOT = "website"
PURGE_INTERVAL_SECONDS = DAY
FORM_FIELDS = ("name", "email", "portfolio_url", "about", "reason")
_NO_STORE = {"Cache-Control": "no-store", "X-Robots-Tag": "noindex"}
_PRIVATE_PREFIXES = ("/admin", "/invite/", "/join/", "/login", "/logout", "/studio")
# API and asset paths keep their JSON errors; people get a page.
_API_PREFIXES = ("/v1/", "/embed/", "/avatars/", "/cloud/static/", "/livez", "/healthz")


def public_router(ctx: CloudContext) -> APIRouter:
    router = APIRouter(include_in_schema=False)
    db = ctx.db

    def landing(
        request: Request,
        *,
        values: dict[str, str] | None = None,
        errors: dict[str, str] | None = None,
        form_error: str | None = None,
        status: int = 200,
    ) -> Response:
        demo = ctx.demo
        return ctx.render(
            request,
            "landing.html",
            status=status,
            csp=ctx.landing_csp,
            demo=demo.public_view() if demo else None,
            turnstile_site_key=ctx.cloud.turnstile_site_key,
            values=values or {},
            errors=errors or {},
            form_error=form_error,
            honeypot=HONEYPOT,
        )

    @router.get("/")
    async def index(request: Request) -> Response:
        return landing(request)

    @router.post("/cloud/requests")
    async def submit(request: Request) -> Response:
        try:
            fields = await read_form(request)
        except FormError as e:
            return ctx.render(
                request,
                "message.html",
                status=e.status,
                kind="error",
                heading="That didn't work",
                text="Please go back and send the form again.",
            )
        if fields.get(HONEYPOT, "").strip():
            return RedirectResponse("/cloud/thanks", status_code=303)  # a bot: pretend, store nothing

        values = {key: fields.get(key, "")[:600] for key in FORM_FIELDS}
        values["consent"] = "on" if fields.get("consent") else ""
        form, errors = validate_request(fields)
        if form is None:
            return landing(request, values=values, errors=errors, status=400)

        ip = ctx.client_ip(request)
        ip_hash, now = ctx.keys.ip_hash(ip), ctx.now()
        if await db.run(db.submissions_since, ip_hash, now - 3600) >= REQUESTS_PER_HOUR:
            text = "You've sent several requests from this network. Please try again in an hour."
            return landing(request, values=values, form_error=text, status=429)
        secret = ctx.cloud.turnstile_secret_key
        if secret and not await verify_turnstile(secret, fields.get("cf-turnstile-response", ""), ip, ctx.transport):
            text = "We couldn't confirm you're a person. Please complete the check and send again."
            return landing(request, values=values, form_error=text, status=400)

        thanks = RedirectResponse("/cloud/thanks", status_code=303)
        if await db.run(db.has_pending, form.email):
            # Same answer as a new request, so the form never reveals who has applied.
            await db.run(db.audit, "request.duplicate", now=now, ip_hash=ip_hash)
            return thanks
        request_id = await db.run(
            db.add_request,
            name=form.name,
            email=form.email,
            portfolio_url=form.portfolio_url,
            about=form.about,
            reason=form.reason,
            ip_hash=ip_hash,
            now=now,
        )
        saved = await db.run(db.get_request, request_id)
        if saved and ctx.mailer.notify_email:
            subject, body = new_request_email(saved, f"{ctx.cloud.public_url}/admin")
            # Sent after the response; Mailer.send logs failures and never raises.
            thanks.background = BackgroundTask(ctx.mailer.send, ctx.mailer.notify_email, subject, body)
        return thanks

    @router.get("/cloud/thanks")
    async def thanks(request: Request) -> Response:
        return ctx.render(request, "thanks.html")

    @router.get("/privacy")
    async def privacy(request: Request) -> Response:
        return ctx.render(request, "privacy.html")

    @router.get("/terms")
    async def terms(request: Request) -> Response:
        return ctx.render(request, "terms.html")

    return router


class CloudService:
    """Runs the retention purge on startup and every 24 hours."""

    def __init__(self, ctx: CloudContext) -> None:
        self.ctx = ctx
        self._task: asyncio.Task[None] | None = None

    async def purge(self) -> tuple[int, int]:
        db = self.ctx.db
        requests, invites = await db.run(db.purge, self.ctx.now())
        if requests or invites:
            detail = f"{requests} rejected requests, {invites} expired invites"
            await db.run(db.audit, "purge", now=self.ctx.now(), detail=detail)
            logger.info(f"Cloud purge removed {detail}")
        return requests, invites

    async def _purge_logged(self) -> None:
        try:
            await self.purge()
        except Exception:
            logger.exception("Cloud purge failed; retrying in 24 hours")

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(PURGE_INTERVAL_SECONDS)
            await self._purge_logged()

    async def start(self) -> None:
        # Finish the first purge before serving, so expired data is never shown after a restart.
        await self._purge_logged()
        await refresh_live(self.ctx)
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self.ctx.db.close()


def install(
    app: FastAPI,
    settings: Settings,
    registry: PersonaRegistry,
    client_ip: Callable[[Request], str],
    transport: httpx.AsyncBaseTransport | None = None,
) -> CloudService:
    """Add the cloud pages to the voice server. Called only when CLOUD_MODE=1."""
    cloud = settings.cloud
    assert cloud is not None  # noqa: S101 - create_app checks this
    db = CloudDB(settings.data_dir / "cloud.db")
    ctx = CloudContext(
        settings=settings,
        cloud=cloud,
        db=db,
        keys=Keys(cloud.session_secret),
        mailer=Mailer(cloud.smtp),
        registry=registry,
        store=StudioStore(db),
        files=FileStore(settings.data_dir),
        client_ip=client_ip,
        transport=transport,
    )
    app.state.cloud = ctx
    admin_auth = AdminAuth(ctx)
    members = MemberAuth(ctx)
    member_admin = MemberAdmin(ctx, admin_auth)
    # Unpublished personas answer only their signed-in owner (or the site owner reviewing them).
    registry.preview = preview_hook(ctx, members, admin_auth.signed_in)
    app.mount("/cloud/static", StaticFiles(directory=STATIC_DIR), name="cloud-static")
    app.include_router(public_router(ctx))
    app.include_router(accounts_router(ctx, members))
    app.include_router(Studio(ctx, members).router())
    app.include_router(profile_router(ctx, members, admin_auth.signed_in))
    app.include_router(admin_router(ctx, admin_auth, member_admin.tabs))
    app.include_router(member_admin.router())

    @app.middleware("http")
    async def cloud_headers(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        response = await call_next(request)
        path = request.url.path
        if response.headers.get("content-type", "").startswith("text/html"):
            # Pages that did not choose a policy (such as error pages) get the strict one.
            response.headers.setdefault("Content-Security-Policy", STRICT_CSP)
            response.headers["X-Frame-Options"] = "DENY"
            if cloud.secure:
                response.headers["Strict-Transport-Security"] = "max-age=31536000"
        if path.startswith(_PRIVATE_PREFIXES):
            response.headers.update(_NO_STORE)
            response.headers["X-Frame-Options"] = "DENY"
            if path.startswith(("/invite/", "/join/", "/login/reset/")):
                # The token is in the URL, so links on these pages must not carry it elsewhere.
                response.headers["Referrer-Policy"] = "no-referrer"
        return response

    async def html_errors(request: Request, exc: Exception) -> Response:
        assert isinstance(exc, StarletteHTTPException)  # noqa: S101 - registered for this type only
        wants_html = "text/html" in request.headers.get("accept", "")
        if exc.status_code == 404 and wants_html and not request.url.path.startswith(_API_PREFIXES):
            return ctx.render(
                request,
                "message.html",
                status=404,
                kind="error",
                heading="Page not found",
                text="This page doesn't exist. It may have moved.",
            )
        return await http_exception_handler(request, exc)

    app.add_exception_handler(StarletteHTTPException, html_errors)
    return CloudService(ctx)
