"""Member accounts: joining with an invite, signing in and out, and password resets.

GET/POST /join/{token}          create an account (consumes the invite)
GET/POST /login, POST /logout   member sign-in, separate from the owner's /admin sign-in
GET/POST /login/forgot          email a reset link (when SMTP is set); the same answer for every address
GET/POST /login/reset/{token}   choose a new password; signs out every session

Every form needs a CSRF token and a same-origin request. Sign-in failures share one message and
lock a network out after five attempts in 15 minutes, like the owner's sign-in.
"""

from __future__ import annotations

import asyncio
import re
import unicodedata
from functools import cache
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse
from starlette.background import BackgroundTask

from .admin import LOCKED_ERROR, LOGIN_WINDOW_SECONDS, MAX_FAILED_LOGINS
from .auth import MIN_PASSWORD_LENGTH, hash_password, hash_token, verify_password
from .db import AccessRequest
from .forms import EMAIL_RE, FormError, read_form
from .mail import reset_email
from .member_auth import MemberAuth
from .members import issue_reset
from .profile import default_data, handle_problem
from .store import SignupError
from .web import CloudContext

TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{20,128}")
MAX_PASSWORD = 1024
RESETS_PER_HOUR = 5
LOGIN_ERROR = "That email and password don't match."
PAUSED_ERROR = "Your account is paused. Please contact the site owner."
EXPIRED_FORM = "This form expired. Please go back, reload the page and try again."
# "same-origin", not "no-referrer": under no-referrer browsers send "Origin: null" with the page's own form
# POST, which the origin check refuses. same-origin still keeps tokens in the URL away from other sites.
REFERRER_POLICY = "same-origin"
PRIVATE = {"Cache-Control": "no-store", "X-Robots-Tag": "noindex", "Referrer-Policy": REFERRER_POLICY}


@cache
def _dummy_hash() -> str:
    # Checked when no account matches, so a wrong email takes as long as a wrong password.
    return hash_password("openfolio-timing-guard")


def suggest_handle(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name).strip("-")[:30].strip("-")
    return slug if len(slug) >= 3 else ""


def password_problem(password: str) -> str | None:
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Use at least {MIN_PASSWORD_LENGTH} characters."
    if len(password) > MAX_PASSWORD:
        return "That password is too long."
    return None


def accounts_router(ctx: CloudContext, members: MemberAuth) -> APIRouter:
    router = APIRouter(include_in_schema=False)
    db, store = ctx.db, ctx.store

    def page(request: Request, template: str, *, status: int = 200, **context: Any) -> Response:
        token, fresh = members.form_token(request)
        response = ctx.render(request, template, status=status, headers=PRIVATE, form_token=token, **context)
        members.set_form_cookie(response, fresh)
        return response

    def refuse(request: Request, text: str = EXPIRED_FORM) -> Response:
        return ctx.render(
            request,
            "message.html",
            status=403,
            headers=PRIVATE,
            kind="error",
            heading="Request refused",
            text=text,
            link="/login",
            link_text="Go to sign-in",
        )

    async def posted(request: Request, max_bytes: int = 16_000) -> dict[str, str] | Response:
        """The form of a signed-out page, or a refusal for another origin or a missing token."""
        if members.foreign_origin(request):
            return refuse(request, f"Open {ctx.cloud.public_url} and try again.")
        try:
            form = await read_form(request, max_bytes=max_bytes)
        except FormError:
            form = {}
        if not members.check_form_token(request, form.get("form_token")):
            return refuse(request)
        return form

    async def invite_for(token: str) -> AccessRequest | None:
        if not TOKEN_RE.fullmatch(token):
            return None
        return await db.run(db.valid_invite, hash_token(token), ctx.now())

    def invalid_invite(request: Request) -> Response:
        return ctx.render(request, "invite.html", status=404, headers=PRIVATE, valid=False, first_name="")

    # Joining

    @router.get("/invite/{token}")
    async def old_invite_link(token: str) -> Response:
        # Stage 1 emailed /invite/ links; they now open the sign-up page.
        safe = token if TOKEN_RE.fullmatch(token) else "invalid"
        return RedirectResponse(f"/join/{safe}", status_code=303, headers=PRIVATE)

    @router.get("/join/{token}")
    async def join_form(request: Request, token: str) -> Response:
        approved = await invite_for(token)
        if approved is None:
            return invalid_invite(request)
        return page(
            request,
            "join.html",
            email=approved.email,
            first_name=approved.name.split()[0] if approved.name.split() else "",
            values={"handle": suggest_handle(approved.name)},
            errors={},
        )

    @router.post("/join/{token}")
    async def join(request: Request, token: str) -> Response:
        form = await posted(request)
        if isinstance(form, Response):
            return form
        approved = await invite_for(token)
        if approved is None:
            return invalid_invite(request)
        handle = form.get("handle", "").strip().lower()[:64]
        password = form.get("password", "")
        errors: dict[str, str] = {}
        if problem := handle_problem(handle, frozenset(ctx.registry.files)):
            errors["handle"] = problem
        elif await db.run(store.handle_taken, handle):
            errors["handle"] = "That handle is taken. Try another."
        if problem := password_problem(password):
            errors["password"] = problem
        first = approved.name.split()[0] if approved.name.split() else ""

        def again(status: int = 400) -> Response:
            return page(
                request,
                "join.html",
                status=status,
                email=approved.email,
                first_name=first,
                values={"handle": handle},
                errors=errors,
            )

        if errors:
            return again()
        password_hash = await asyncio.to_thread(hash_password, password)
        now = ctx.now()
        try:
            user = await db.run(
                store.create_user,
                token_hash=hash_token(token),
                handle=handle,
                password_hash=password_hash,
                persona_data=default_data(approved.name, ctx.settings.avatars_dir),
                now=now,
            )
        except SignupError as e:
            if e.reason == "invite":
                return invalid_invite(request)
            errors[e.reason] = (
                "That handle is taken. Try another."
                if e.reason == "handle"
                else "An account with this email already exists. Sign in instead."
            )
            return again(409)
        await db.run(db.audit, "user.created", now=now, ip_hash=ctx.ip_hash(request), user_id=user.id)
        response = RedirectResponse("/studio/setup?m=welcome", status_code=303)
        await members.sign_in(response, user)
        return response

    # Signing in and out

    @router.get("/login")
    async def login_form(request: Request) -> Response:
        if await members.current(request):
            return RedirectResponse("/studio", status_code=303)
        notice = {
            "out": "You're signed out.",
            "reset": "Your password is changed. Sign in with the new one.",
            "deleted": "Your account and all its data are deleted.",
        }
        return page(
            request,
            "login.html",
            error=None,
            notice=notice.get(request.query_params.get("m", "")),
            email="",
        )

    @router.post("/login")
    async def login(request: Request) -> Response:
        if members.foreign_origin(request):
            return refuse(request, f"Open {ctx.cloud.public_url} and try again.")
        ip_hash, now = ctx.ip_hash(request), ctx.now()
        if (
            await db.run(db.failed_logins_since, ip_hash, now - LOGIN_WINDOW_SECONDS, prefix="user.")
            >= MAX_FAILED_LOGINS
        ):
            return page(request, "login.html", status=429, error=LOCKED_ERROR, notice=None, email="")
        form = await posted(request)
        if isinstance(form, Response):
            return form
        email = form.get("email", "").strip().lower()[:254]
        password = form.get("password", "")[:MAX_PASSWORD]
        user = await db.run(store.user_by_email, email) if EMAIL_RE.fullmatch(email) else None
        encoded = user.password_hash if user else _dummy_hash()
        ok = bool(password) and await asyncio.to_thread(verify_password, password, encoded)
        if not ok or user is None:
            await db.run(db.audit, "user.login.failed", now=now, ip_hash=ip_hash)
            return page(request, "login.html", status=401, error=LOGIN_ERROR, notice=None, email=email)
        if user.status != "active":
            return page(request, "login.html", status=403, error=PAUSED_ERROR, notice=None, email=email)
        await db.run(db.audit, "user.login", now=now, ip_hash=ip_hash, user_id=user.id)
        response = RedirectResponse("/studio", status_code=303)
        await members.sign_in(response, user)
        return response

    @router.post("/logout")
    async def logout(request: Request) -> Response:
        signed = await members.current(request)
        response = RedirectResponse("/login?m=out", status_code=303)
        if signed is None:
            members.clear(response)
            return response
        if members.foreign_origin(request):
            return refuse(request)
        try:
            form = await read_form(request)
        except FormError:
            form = {}
        if not members.check_csrf(signed, form.get("csrf")):
            return refuse(request)
        await members.sign_out(response, signed)
        await db.run(db.audit, "user.logout", now=ctx.now(), ip_hash=ctx.ip_hash(request), user_id=signed.user.id)
        return response

    # Password reset

    @router.get("/login/forgot")
    async def forgot_form(request: Request) -> Response:
        return page(request, "forgot.html", sent=request.query_params.get("sent") == "1", mail=ctx.mailer.enabled)

    @router.post("/login/forgot")
    async def forgot(request: Request) -> Response:
        form = await posted(request)
        if isinstance(form, Response):
            return form
        done = RedirectResponse("/login/forgot?sent=1", status_code=303)
        ip_hash, now = ctx.ip_hash(request), ctx.now()
        if not ctx.mailer.enabled:
            return done
        if await db.run(db.actions_since, "user.reset.requested", now - 3600, ip_hash=ip_hash) >= RESETS_PER_HOUR:
            return done  # same answer, so the limit can't be used to probe addresses either
        await db.run(db.audit, "user.reset.requested", now=now, ip_hash=ip_hash)
        email = form.get("email", "").strip().lower()[:254]
        user = await db.run(store.user_by_email, email) if EMAIL_RE.fullmatch(email) else None
        if user is not None and user.status == "active":
            link = await issue_reset(ctx, user)
            done.background = BackgroundTask(ctx.mailer.send, user.email, *reset_email(user.name, link))
        return done

    @router.get("/login/reset/{token}")
    async def reset_form(request: Request, token: str) -> Response:
        valid = bool(TOKEN_RE.fullmatch(token)) and (
            await db.run(store.valid_reset, hash_token(token), ctx.now()) is not None
        )
        return page(request, "reset.html", status=200 if valid else 404, valid=valid, errors={})

    @router.post("/login/reset/{token}")
    async def reset(request: Request, token: str) -> Response:
        form = await posted(request)
        if isinstance(form, Response):
            return form
        password = form.get("password", "")
        if problem := password_problem(password):
            return page(request, "reset.html", status=400, valid=True, errors={"password": problem})
        password_hash = await asyncio.to_thread(hash_password, password)
        user = (
            await db.run(store.use_reset, hash_token(token), password_hash, ctx.now())
            if TOKEN_RE.fullmatch(token)
            else None
        )
        if user is None:
            return page(request, "reset.html", status=404, valid=False, errors={})
        await db.run(db.audit, "user.password.reset", now=ctx.now(), ip_hash=ctx.ip_hash(request), user_id=user.id)
        response = RedirectResponse("/login?m=reset", status_code=303)
        members.clear(response)
        return response

    return router
