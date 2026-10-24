"""Member operations shared by the Studio and the owner's admin page.

- refresh_live: rebuild the registry's live personas after anything that changes what is public.
- erase_member: delete a member and everything they own (database rows, files, original request).
- issue_reset: a single-use, one-hour password reset link (only its hash is stored).
- preview_hook: "<handle>~preview" for the signed-in owner (working copy) or the site owner (submission).
"""

from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable

from fastapi import Request
from loguru import logger
from pydantic import ValidationError

from ..persona import Persona
from ..registry import PreviewHook
from .auth import hash_token
from .member_auth import MemberAuth
from .profile import to_persona
from .store import User
from .web import CloudContext

RESET_SECONDS = 3600


async def refresh_live(ctx: CloudContext) -> None:
    rows = await ctx.db.run(ctx.store.live_personas)
    live: dict[str, Persona] = {}
    for handle, data in rows:
        try:
            live[handle] = to_persona(handle, data, ctx.cloud.public_url)
        except ValidationError:
            # Approved data always validated; this only happens if the schema changes under it.
            logger.error(f"Live persona {handle!r} no longer validates; it is offline until edited")
    ctx.registry.replace_live(live)


async def erase_member(ctx: CloudContext, user_id: int) -> User | None:
    user = await ctx.db.run(ctx.store.delete_user, user_id)
    if user is not None:
        ctx.files.remove_all(user_id)
        await refresh_live(ctx)
    return user


async def issue_reset(ctx: CloudContext, user: User) -> str:
    token = secrets.token_urlsafe(32)
    now = ctx.now()
    await ctx.db.run(ctx.store.add_reset, hash_token(token), user.id, now, now + RESET_SECONDS)
    return f"{ctx.cloud.public_url}/login/reset/{token}"


def preview_hook(
    ctx: CloudContext, members: MemberAuth, owner_signed_in: Callable[[Request], Awaitable[bool]]
) -> PreviewHook:
    async def preview(request: Request, handle: str) -> Persona | None:
        # Same-origin only: the widget on the Studio or admin page, never another site.
        if members.foreign_origin(request) or request.headers.get("sec-fetch-site", "same-origin") not in (
            "same-origin",
            "none",
        ):
            return None
        data = None
        signed = await members.current(request)
        if signed is not None and signed.user.handle == handle:
            record = await ctx.db.run(ctx.store.get_persona, signed.user.id)
            data = record.data if record else None
        elif await owner_signed_in(request):
            record = await ctx.db.run(ctx.store.persona_by_handle, handle)
            if record is not None:
                review = await ctx.db.run(ctx.store.open_review_for, record.user_id)
                data = review.data if review else record.data
        if data is None:
            return None
        try:
            return to_persona(handle, data, ctx.cloud.public_url)
        except ValidationError:
            return None

    return preview
