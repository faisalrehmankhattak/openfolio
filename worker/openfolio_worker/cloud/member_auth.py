"""Member sign-in: a session cookie separate from the owner's, CSRF tokens and same-origin checks.

The cookie holds a signed random session id; the database keeps only its SHA-256, with a 7-day
expiry, so a session can be revoked (sign-out, password change, pause, deletion) and a copy of the
database signs nobody in. Forms shown before sign-in (join, login, password reset) use a
double-submit token bound to a random cookie, so another site can't post them either.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass

from fastapi import Request, Response

from .db import DAY
from .store import User
from .web import CloudContext

SESSION_SECONDS = 7 * DAY
FORM_COOKIE_SECONDS = DAY


def sid_hash(sid: str) -> str:
    return hashlib.sha256(sid.encode()).hexdigest()


@dataclass(frozen=True)
class SignedIn:
    user: User
    sid: str

    @property
    def sid_hash(self) -> str:
        return sid_hash(self.sid)


class MemberAuth:
    def __init__(self, ctx: CloudContext) -> None:
        self.ctx = ctx
        secure = ctx.cloud.secure
        # __Host- makes browsers insist on Secure, host-only and Path=/ (only possible over https).
        self.cookie = "__Host-openfolio_session" if secure else "openfolio_session"
        self.form_cookie = "__Host-openfolio_form" if secure else "openfolio_form"

    async def current(self, request: Request) -> SignedIn | None:
        payload = self.ctx.keys.unsign("member-session", request.cookies.get(self.cookie))
        sid = payload.get("sid") if payload else None
        if not isinstance(sid, str) or not 16 <= len(sid) <= 64:
            return None
        db, store, now = self.ctx.db, self.ctx.store, self.ctx.now()
        user = await db.run(store.session_user, sid_hash(sid), now)
        if user is None:
            return None
        await db.run(store.touch, user.id, now)
        return SignedIn(user=user, sid=sid)

    async def sign_in(self, response: Response, user: User) -> str:
        sid = secrets.token_urlsafe(24)
        now = self.ctx.now()
        await self.ctx.db.run(self.ctx.store.add_session, sid_hash(sid), user.id, now, now + SESSION_SECONDS)
        response.set_cookie(
            self.cookie,
            self.ctx.keys.sign("member-session", {"sid": sid}),
            max_age=SESSION_SECONDS,
            path="/",
            httponly=True,
            samesite="lax",  # links from the invite and reset emails arrive signed in
            secure=self.ctx.cloud.secure,
        )
        return sid

    def clear(self, response: Response) -> None:
        response.delete_cookie(self.cookie, path="/", httponly=True, samesite="lax", secure=self.ctx.cloud.secure)

    async def sign_out(self, response: Response, signed: SignedIn) -> None:
        await self.ctx.db.run(self.ctx.store.delete_session, signed.sid_hash)
        self.clear(response)

    # CSRF

    def csrf(self, signed: SignedIn) -> str:
        return self.ctx.keys.token_for("member-csrf", signed.sid)

    def check_csrf(self, signed: SignedIn, token: str | None) -> bool:
        return self.ctx.keys.check_token("member-csrf", signed.sid, token)

    def foreign_origin(self, request: Request) -> bool:
        origin = request.headers.get("origin")
        return origin is not None and origin != self.ctx.cloud.public_url

    def form_token(self, request: Request) -> tuple[str, str | None]:
        """(token for a signed-out form, new cookie value to set or None when the cookie exists)."""
        value = request.cookies.get(self.form_cookie)
        fresh = None
        if not value or not 16 <= len(value) <= 64:
            value = fresh = secrets.token_urlsafe(24)
        return self.ctx.keys.token_for("form-csrf", value), fresh

    def set_form_cookie(self, response: Response, value: str | None) -> None:
        if value:
            response.set_cookie(
                self.form_cookie,
                value,
                max_age=FORM_COOKIE_SECONDS,
                path="/",
                httponly=True,
                samesite="lax",
                secure=self.ctx.cloud.secure,
            )

    def check_form_token(self, request: Request, token: str | None) -> bool:
        value = request.cookies.get(self.form_cookie) or ""
        return self.ctx.keys.check_token("form-csrf", value, token)
