"""Studio profile editor: every persona field the widget and the prompt use.

GET/POST /studio/profile   validated with the Persona model plus cloud limits, with per-field errors
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse

from .member_auth import SignedIn
from .profile import KOKORO_VOICES, find_flags
from .profile_form import data_to_form, form_to_data, validate

if TYPE_CHECKING:
    from .store import PersonaRecord
    from .studio import Studio

MAX_PROFILE_BYTES = 256_000  # URL-encoded: a long profile in a non-Latin script is still well under this
MAX_PROFILE_FIELDS = 600


def add_profile_routes(router: APIRouter, studio: Studio) -> None:
    ctx = studio.ctx
    db, store = ctx.db, ctx.store
    kokoro = ctx.settings.tts_provider == "kokoro"

    async def page(
        request: Request,
        signed: SignedIn,
        record: PersonaRecord,
        data: dict[str, Any],
        errors: dict[str, str],
        status: int = 200,
    ) -> Response:
        photo = (data.get("avatar") or {}).get("photo")
        return await studio.render(
            request,
            signed,
            "studio_profile.html",
            "profile",
            status=status,
            record=record,
            form=data_to_form(data),
            errors=errors,
            flags=record.flags,
            photo_url=f"/{photo}" if photo else None,
            voices=KOKORO_VOICES if kokoro else (),
        )

    @router.get("/studio/profile")
    async def profile(request: Request) -> Response:
        signed = await studio.signed_in(request)
        if isinstance(signed, Response):
            return signed
        record = await studio.record(signed)
        return await page(request, signed, record, record.data, {})

    @router.post("/studio/profile")
    async def save(request: Request) -> Response:
        signed = await studio.signed_in(request)
        if isinstance(signed, Response):
            return signed
        form = await studio.form(request, signed, max_bytes=MAX_PROFILE_BYTES, max_fields=MAX_PROFILE_FIELDS)
        if isinstance(form, Response):
            return form
        record = await studio.record(signed)
        data = form_to_data(form, record.data, kokoro=kokoro, avatars_dir=ctx.settings.avatars_dir)
        stored, errors = validate(signed.user.handle, data, ctx.cloud.public_url)
        if stored is None:
            return await page(request, signed, record, data, errors, status=400)
        flags = find_flags(stored, "edit")
        now = ctx.now()
        await db.run(store.save_persona, signed.user.id, stored, flags, now)
        await db.run(db.audit, "persona.saved", now=now, ip_hash=ctx.ip_hash(request), user_id=signed.user.id)
        return RedirectResponse("/studio/profile?m=saved", status_code=303)
