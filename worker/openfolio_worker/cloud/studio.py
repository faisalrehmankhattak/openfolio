"""The Studio, where a member builds their AI portfolio. Signed-in members only.

GET  /studio                         -> Setup on the first visit, Profile afterwards
     /studio/setup ...               uploads, pasted text and the AI draft (studio_setup.py)
     /studio/profile                 every persona field (studio_profile.py)
GET  /studio/preview                 the real widget running the working copy (owner only)
GET  /studio/publish                 submit for review, go-live status, page link and embed snippet
POST /studio/publish/submit|withdraw|pause|resume|search
     /studio/account ...             password, data export, deletion (studio_account.py)

Every POST checks the origin and the member's CSRF token. Pages use the strict CSP except the
preview, which runs the widget with the landing page's measured exceptions.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse
from starlette.background import BackgroundTask

from .forms import FormError, read_form
from .member_auth import MemberAuth, SignedIn
from .members import refresh_live
from .profile import missing_for_review
from .store import PersonaRecord
from .web import CloudContext

PRIVATE = {"Cache-Control": "no-store", "X-Robots-Tag": "noindex"}
STATUS_LABELS = {
    "draft": "Draft",
    "pending": "In review",
    "live": "Live",
    "rejected": "Changes requested",
    "paused": "Paused",
}
NAV = (
    ("setup", "Setup", "sparkle"),
    ("profile", "Profile", "user"),
    ("preview", "Preview", "play"),
    ("publish", "Publish", "globe"),
    ("account", "Account", "lock"),
)
MESSAGES = {
    "welcome": "Welcome to the Studio. Start by adding your résumé and a photo.",
    "uploaded": "File added. We read it and kept the text below.",
    "photo": "Photo updated. It's cropped to a square and stripped of location and camera data.",
    "pasted": "Text saved. It's used with your documents when you draft.",
    "deleted": "File deleted.",
    "drafted": "Your AI draft is ready. Check every fact, then save.",
    "saved": "Profile saved.",
    "submitted": "Submitted. We'll review your page shortly.",
    "withdrawn": "Submission withdrawn. You can keep editing.",
    "incomplete": "Add the missing details before submitting.",
    "paused": "Your page is paused. Visitors see nothing until you resume.",
    "resumed": "Your page is live again.",
    "search": "Search setting saved.",
    "password": "Password changed. Other devices are signed out.",
    "draft_running": "A draft is already being written.",
    "draft_limit": "You've drafted several times in a short while. Please try again later.",
    "no_sources": "Add a document or paste some text first.",
}


class Studio:
    def __init__(self, ctx: CloudContext, members: MemberAuth) -> None:
        self.ctx = ctx
        self.members = members
        self.slots = asyncio.Semaphore(2)  # parallel upload parsers

    async def signed_in(self, request: Request) -> SignedIn | Response:
        signed = await self.members.current(request)
        if signed is None:
            return RedirectResponse("/login", status_code=303)
        return signed

    def refuse(self, request: Request, text: str = "This form expired. Reload the page and try again.") -> Response:
        return self.ctx.render(
            request,
            "message.html",
            status=403,
            headers=PRIVATE,
            kind="error",
            heading="Request refused",
            text=text,
            link="/studio",
            link_text="Back to the Studio",
        )

    async def form(
        self, request: Request, signed: SignedIn, *, max_bytes: int = 16_000, max_fields: int = 30
    ) -> dict[str, str] | Response:
        if self.members.foreign_origin(request):
            return self.refuse(request, f"Open the Studio at {self.ctx.cloud.public_url} and try again.")
        try:
            form = await read_form(request, max_bytes=max_bytes, max_fields=max_fields)
        except FormError as e:
            if e.status == 413:
                return self.refuse(request, "That form is too large. Shorten some fields and try again.")
            form = {}
        if not self.members.check_csrf(signed, form.get("csrf")):
            return self.refuse(request)
        return form

    async def record(self, signed: SignedIn) -> PersonaRecord:
        record = await self.ctx.db.run(self.ctx.store.get_persona, signed.user.id)
        assert record is not None  # noqa: S101 - created with the account
        return record

    async def render(
        self,
        request: Request,
        signed: SignedIn,
        template: str,
        section: str,
        *,
        status: int = 200,
        csp: str | None = None,
        record: PersonaRecord | None = None,
        **context: Any,
    ) -> Response:
        record = record or await self.record(signed)
        code = request.query_params.get("m", "")
        return self.ctx.render(
            request,
            template,
            status=status,
            headers=PRIVATE,
            **({"csp": csp} if csp else {}),
            user=signed.user,
            section=section,
            nav=NAV,
            record=record,
            status_label=STATUS_LABELS[record.status],
            csrf=self.members.csrf(signed),
            message=MESSAGES.get(code),
            message_code=code,
            page_url=f"{self.ctx.cloud.public_url}/p/{signed.user.handle}",
            **context,
        )

    def router(self) -> APIRouter:
        from .studio_account import add_account_routes
        from .studio_profile import add_profile_routes
        from .studio_setup import add_setup_routes

        router = APIRouter(include_in_schema=False)
        add_setup_routes(router, self)
        add_profile_routes(router, self)
        add_account_routes(router, self)
        self._add_pages(router)
        return router

    def _add_pages(self, router: APIRouter) -> None:
        ctx, db, store = self.ctx, self.ctx.db, self.ctx.store

        @router.get("/studio")
        async def home(request: Request) -> Response:
            signed = await self.signed_in(request)
            if isinstance(signed, Response):
                return signed
            record = await self.record(signed)
            started = record.drafted_at or str(record.data.get("about") or "").strip()
            return RedirectResponse("/studio/profile" if started else "/studio/setup", status_code=303)

        @router.get("/studio/preview")
        async def preview(request: Request) -> Response:
            signed = await self.signed_in(request)
            if isinstance(signed, Response):
                return signed
            record = await self.record(signed)
            return await self.render(
                request,
                signed,
                "studio_preview.html",
                "preview",
                csp=ctx.widget_csp,
                record=record,
                widget_id=f"{signed.user.handle}~preview",
                missing=missing_for_review(record.data),
                questions=record.data.get("quick_questions") or [],
            )

        @router.get("/studio/publish")
        async def publish(request: Request) -> Response:
            signed = await self.signed_in(request)
            if isinstance(signed, Response):
                return signed
            record = await self.record(signed)
            return await self.render(
                request,
                signed,
                "studio_publish.html",
                "publish",
                record=record,
                missing=missing_for_review(record.data),
                open_review=await db.run(store.open_review_for, signed.user.id),
                latest=await db.run(store.latest_review, signed.user.id),
                embed_snippet=(
                    f'<script src="{ctx.cloud.public_url}/embed/embed.js" '
                    f'data-persona="{signed.user.handle}" async></script>'
                ),
            )

        @router.post("/studio/publish/{action}")
        async def publish_action(request: Request, action: str) -> Response:
            signed = await self.signed_in(request)
            if isinstance(signed, Response):
                return signed
            form = await self.form(request, signed)
            if isinstance(form, Response):
                return form
            user, now, ip_hash = signed.user, ctx.now(), ctx.ip_hash(request)
            record = await self.record(signed)
            done = "/studio/publish?m="
            if action == "submit":
                if missing_for_review(record.data):
                    return RedirectResponse(done + "incomplete", status_code=303)
                await db.run(store.submit, user.id, now)
                await db.run(db.audit, "persona.submitted", now=now, ip_hash=ip_hash, user_id=user.id)
                response = RedirectResponse(done + "submitted", status_code=303)
                if ctx.mailer.notify_email:
                    subject = f"Openfolio Cloud: @{user.handle} submitted a page for review"
                    body = f"Review it at {ctx.cloud.public_url}/admin?tab=reviews\n"
                    response.background = BackgroundTask(ctx.mailer.send, ctx.mailer.notify_email, subject, body)
                return response
            if action == "withdraw":
                await db.run(store.withdraw, user.id, now)
                await db.run(db.audit, "persona.withdrawn", now=now, ip_hash=ip_hash, user_id=user.id)
                return RedirectResponse(done + "withdrawn", status_code=303)
            if action in ("pause", "resume"):
                if await db.run(store.set_paused, user.id, action == "pause", now):
                    await refresh_live(ctx)
                    event = "persona.paused" if action == "pause" else "persona.resumed"
                    await db.run(db.audit, event, now=now, ip_hash=ip_hash, user_id=user.id)
                return RedirectResponse(done + ("paused" if action == "pause" else "resumed"), status_code=303)
            if action == "search":
                await db.run(store.set_show_in_search, user.id, form.get("show_in_search") == "on", now)
                return RedirectResponse(done + "search", status_code=303)
            return self.refuse(request, "Unknown action.")
