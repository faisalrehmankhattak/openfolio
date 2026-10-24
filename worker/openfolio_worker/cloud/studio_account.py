"""Studio account: change password, download all my data, delete my account.

POST /studio/account/password    current + new password; signs out every other session
GET  /studio/account/export      a zip with data.json and every uploaded file
POST /studio/account/delete      erase everything (confirm by retyping the handle)
"""

from __future__ import annotations

import asyncio
import io
import json
import zipfile
from typing import TYPE_CHECKING

from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse

from .accounts import password_problem
from .auth import hash_password, verify_password
from .members import erase_member

if TYPE_CHECKING:
    from .studio import Studio


def add_account_routes(router: APIRouter, studio: Studio) -> None:
    ctx = studio.ctx
    db, store, files = ctx.db, ctx.store, ctx.files

    @router.get("/studio/account")
    async def account(request: Request) -> Response:
        signed = await studio.signed_in(request)
        if isinstance(signed, Response):
            return signed
        sessions = await db.run(store.session_count, signed.user.id, ctx.now())
        return await studio.render(request, signed, "studio_account.html", "account", errors={}, sessions=sessions)

    @router.post("/studio/account/password")
    async def change_password(request: Request) -> Response:
        signed = await studio.signed_in(request)
        if isinstance(signed, Response):
            return signed
        form = await studio.form(request, signed)
        if isinstance(form, Response):
            return form
        current, new = form.get("current", "")[:1024], form.get("password", "")
        errors: dict[str, str] = {}
        if not current or not await asyncio.to_thread(verify_password, current, signed.user.password_hash):
            errors["current"] = "That isn't your current password."
        if problem := password_problem(new):
            errors["password"] = problem
        if errors:
            sessions = await db.run(store.session_count, signed.user.id, ctx.now())
            return await studio.render(
                request, signed, "studio_account.html", "account", status=400, errors=errors, sessions=sessions
            )
        await db.run(
            store.set_password,
            signed.user.id,
            await asyncio.to_thread(hash_password, new),
            keep_session=signed.sid_hash,
        )
        await db.run(
            db.audit, "user.password.changed", now=ctx.now(), ip_hash=ctx.ip_hash(request), user_id=signed.user.id
        )
        return RedirectResponse("/studio/account?m=password", status_code=303)

    @router.get("/studio/account/export")
    async def export(request: Request) -> Response:
        signed = await studio.signed_in(request)
        if isinstance(signed, Response):
            return signed
        user = signed.user
        data = await db.run(store.export, user.id)
        stored = await db.run(store.list_files, user.id)

        def build() -> bytes:
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("data.json", json.dumps(data, ensure_ascii=False, indent=2))
                for f in stored:
                    path = files.path(user.id, f.stored_name)
                    if path.exists():
                        zf.write(path, f"files/{f.id}-{f.stored_name}")
            return buffer.getvalue()

        body = await asyncio.to_thread(build)
        await db.run(db.audit, "data.exported", now=ctx.now(), ip_hash=ctx.ip_hash(request), user_id=user.id)
        return Response(
            body,
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="openfolio-{user.handle}.zip"',
                "Cache-Control": "private, no-store",
            },
        )

    @router.post("/studio/account/delete")
    async def delete(request: Request) -> Response:
        signed = await studio.signed_in(request)
        if isinstance(signed, Response):
            return signed
        form = await studio.form(request, signed)
        if isinstance(form, Response):
            return form
        if form.get("confirm", "").strip().lower() != signed.user.handle:
            sessions = await db.run(store.session_count, signed.user.id, ctx.now())
            errors = {"confirm": f"Type {signed.user.handle} to confirm."}
            return await studio.render(
                request, signed, "studio_account.html", "account", status=400, errors=errors, sessions=sessions
            )
        await erase_member(ctx, signed.user.id)
        await db.run(db.audit, "user.deleted", now=ctx.now(), ip_hash=ctx.ip_hash(request), detail="by the member")
        response = RedirectResponse("/login?m=deleted", status_code=303)
        studio.members.clear(response)
        return response
