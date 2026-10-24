"""Studio setup: documents, pasted text, the photo and the AI draft.

POST /studio/files                 one file (multipart); the slot field says "document" or "photo"
GET  /studio/files/{id}            the owner's own file (attachment; photos inline)
POST /studio/files/{id}/delete
POST /studio/text                  pasted text, kept as a text document
POST /studio/draft                 start the AI draft in the background
GET  /studio/draft/status          JSON progress for the setup page

Draft jobs live in this process's memory, which is right for the single replica Openfolio Cloud
runs on. The audit log records "draft.started" before a job runs, so after a restart (or on another
replica) a draft that never finished shows as interrupted, with a button to run it again, instead
of spinning forever. Running several replicas would need a shared job store.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from fastapi import APIRouter, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from loguru import logger
from starlette.datastructures import UploadFile

from .drafting import DraftError, Source, draft_profile
from .member_auth import SignedIn
from .profile import find_flags, photo_path
from .profile_form import validate
from .uploads import (
    MAX_FILES,
    MAX_TOTAL_BYTES,
    TEXT,
    Slot,
    UploadError,
    check_file,
    clean_filename,
    detect,
    process,
    read_multipart,
)

if TYPE_CHECKING:
    from .studio import Studio

PASTE_MAX_CHARS = 40_000
DRAFTS_PER_HOUR = 6  # counted from "draft.started", so failed drafts count too (each one is an LLM call)
DRAFTS_PER_DAY = 20
INTERRUPTED_SECONDS = 3600  # how long a draft lost in a restart is reported before it's forgotten
DRAFT_EVENTS = ("draft.started", "draft.created", "draft.failed")
INTERRUPTED = {
    "state": "interrupted",
    "step": "",
    "label": "",
    "error": "The draft was interrupted because the server restarted. Your documents are safe; run it again.",
}
UPLOADS_PER_HOUR = 40
STEPS = {
    "reading": "Reading your documents",
    "drafting": "Writing your draft",
    "checking": "Checking facts, links and safety",
    "done": "Done",
}
DRAFT_KEYS = (
    "name",
    "first_name",
    "pronouns",
    "title",
    "tagline",
    "about",
    "highlights",
    "experience",
    "projects",
    "skills",
    "education",
    "awards",
    "links",
    "email",
    "quick_questions",
)


@dataclass
class DraftJob:
    state: Literal["running", "done", "failed"] = "running"
    step: str = "reading"
    error: str | None = None
    started: float = field(default_factory=time.monotonic)
    task: asyncio.Task[None] | None = None

    def view(self) -> dict[str, str | None]:
        return {"state": self.state, "step": self.step, "label": STEPS.get(self.step, ""), "error": self.error}


def _prune_invalid(data: dict[str, object], errors: dict[str, str]) -> None:
    """Drop the pieces of an AI draft that fail validation (an odd URL, say) instead of losing the draft."""
    for key in errors:
        parts = key.split("-")
        group = {"quick": "quick_questions"}.get(parts[0], parts[0])
        value = data.get(group)
        if len(parts) == 3 and isinstance(value, list) and parts[1].isdigit() and int(parts[1]) < len(value):
            row = value[int(parts[1])]
            if isinstance(row, dict):
                row[parts[2]] = None if parts[2] in ("url", "org", "period", "metric") else row.get(parts[2])
                if parts[2] == "url" and group == "links":
                    value.pop(int(parts[1]))
        elif group in ("email", "booking_url", "pronouns"):
            data[group] = None


def add_setup_routes(router: APIRouter, studio: Studio) -> None:
    ctx = studio.ctx
    db, store, files = ctx.db, ctx.store, ctx.files
    jobs: dict[int, DraftJob] = {}

    async def setup_page(
        request: Request, signed: SignedIn, *, status: int = 200, error: str | None = None
    ) -> Response:
        user = signed.user
        documents = await db.run(store.list_files, user.id, "document")
        photos = await db.run(store.list_files, user.id, "photo")
        record = await studio.record(signed)
        current = (record.data.get("avatar") or {}).get("photo")
        photo = next((f for f in photos if photo_path(user.handle, f.id) == current), None)
        count, used = await db.run(store.usage, user.id)
        job = await job_view(user.id)
        return await studio.render(
            request,
            signed,
            "studio_setup.html",
            "setup",
            status=status,
            record=record,
            documents=documents,
            photo=photo,
            photo_url=f"/{current}" if photo and current else None,
            usage={"count": count, "bytes": used, "max_files": MAX_FILES, "max_bytes": MAX_TOTAL_BYTES},
            job=job,
            error=error,
        )

    async def job_view(user_id: int) -> dict[str, str | None] | None:
        """This process's job, or "interrupted" when the log shows a draft that started and never ended."""
        job = jobs.get(user_id)
        if job is not None:
            return job.view()
        last = await db.run(db.last_action, user_id, DRAFT_EVENTS)
        if last and last[0] == "draft.started" and ctx.now() - last[1] < INTERRUPTED_SECONDS:
            return dict(INTERRUPTED)
        return None

    @router.get("/studio/setup")
    async def setup(request: Request) -> Response:
        signed = await studio.signed_in(request)
        if isinstance(signed, Response):
            return signed
        return await setup_page(request, signed)

    @router.post("/studio/files")
    async def upload(request: Request) -> Response:
        signed = await studio.signed_in(request)
        if isinstance(signed, Response):
            return signed
        if studio.members.foreign_origin(request):
            return studio.refuse(request, f"Open the Studio at {ctx.cloud.public_url} and try again.")
        user, now, ip_hash = signed.user, ctx.now(), ctx.ip_hash(request)
        try:
            form = await read_multipart(request)
        except UploadError as e:
            await db.run(db.audit, "file.rejected", now=now, ip_hash=ip_hash, user_id=user.id, detail=e.code)
            return await setup_page(request, signed, status=413 if "large" in e.code else 400, error=e.message)
        if not studio.members.check_csrf(signed, str(form.get("csrf") or "")):
            return studio.refuse(request)
        slot: Slot = "photo" if form.get("slot") == "photo" else "document"
        upload = form.get("file")
        if not isinstance(upload, UploadFile):
            return await setup_page(request, signed, status=400, error="Choose a file first.")
        if await db.run(db.actions_since, "file.uploaded", now - 3600, user_id=user.id) >= UPLOADS_PER_HOUR:
            return await setup_page(request, signed, status=429, error="That's a lot of uploads. Try again in an hour.")
        data = await upload.read()
        try:
            file_type = check_file(detect(data[:8192]), slot, len(data), await db.run(store.usage, user.id))
            accepted = await process(files, user.id, file_type, data, slots=studio.slots)
        except UploadError as e:
            await db.run(db.audit, "file.rejected", now=now, ip_hash=ip_hash, user_id=user.id, detail=e.code)
            return await setup_page(request, signed, status=413 if "large" in e.code else 400, error=e.message)
        file_id = await db.run(
            store.add_file,
            user_id=user.id,
            kind=slot,
            stored_name=accepted.stored_name,
            original_name=clean_filename(upload.filename),
            mime="image/jpeg" if slot == "photo" else file_type.mime,
            size=accepted.size,
            text=accepted.text,
            now=now,
        )
        await db.run(db.audit, "file.uploaded", now=now, ip_hash=ip_hash, user_id=user.id, detail=file_type.label)
        if slot == "photo":
            await use_photo(signed, file_id)
            return RedirectResponse("/studio/setup?m=photo#photo", status_code=303)
        return RedirectResponse("/studio/setup?m=uploaded#documents", status_code=303)

    async def use_photo(signed: SignedIn, file_id: int) -> None:
        """Point the working copy at the new photo and delete photos no version uses any more."""
        user, now = signed.user, ctx.now()
        record = await studio.record(signed)
        data = dict(record.data)
        data["avatar"] = {**(data.get("avatar") or {}), "photo": photo_path(user.handle, file_id)}
        await db.run(store.save_persona, user.id, data, record.flags, now)
        live_photo = ((record.live_data or {}).get("avatar") or {}).get("photo")
        for old in await db.run(store.list_files, user.id, "photo"):
            if old.id != file_id and photo_path(user.handle, old.id) != live_photo:
                await db.run(store.delete_file, user.id, old.id)
                files.remove(user.id, old.stored_name)

    @router.get("/studio/files/{file_id}")
    async def download(request: Request, file_id: int) -> Response:
        signed = await studio.signed_in(request)
        if isinstance(signed, Response):
            return signed
        stored = await db.run(store.get_file, signed.user.id, file_id)  # scoped to the member: no IDOR
        if stored is None:
            return JSONResponse({"detail": "Not found"}, status_code=404)
        path = files.path(signed.user.id, stored.stored_name)
        if not path.exists():
            return JSONResponse({"detail": "Not found"}, status_code=404)
        headers = {"Cache-Control": "private, no-store", "Content-Security-Policy": "default-src 'none'; sandbox"}
        return FileResponse(
            path,
            media_type=stored.mime,
            filename=stored.original_name,
            content_disposition_type="inline" if stored.kind == "photo" else "attachment",
            headers=headers,
        )

    @router.post("/studio/files/{file_id}/delete")
    async def delete_file(request: Request, file_id: int) -> Response:
        signed = await studio.signed_in(request)
        if isinstance(signed, Response):
            return signed
        form = await studio.form(request, signed)
        if isinstance(form, Response):
            return form
        user = signed.user
        record = await studio.record(signed)
        stored = await db.run(store.get_file, user.id, file_id)
        if stored is not None:
            live_photo = ((record.live_data or {}).get("avatar") or {}).get("photo")
            if stored.kind == "photo" and photo_path(user.handle, stored.id) == live_photo:
                return await setup_page(
                    request, signed, status=409, error="This photo is on your live page. Upload a new one instead."
                )
            await db.run(store.delete_file, user.id, file_id)
            files.remove(user.id, stored.stored_name)
            if stored.kind == "photo" and (record.data.get("avatar") or {}).get("photo") == photo_path(
                user.handle, file_id
            ):
                data = dict(record.data)
                data["avatar"] = {**(data.get("avatar") or {}), "photo": None}
                await db.run(store.save_persona, user.id, data, record.flags, ctx.now())
            await db.run(db.audit, "file.deleted", now=ctx.now(), ip_hash=ctx.ip_hash(request), user_id=user.id)
        return RedirectResponse("/studio/setup?m=deleted#documents", status_code=303)

    @router.post("/studio/text")
    async def paste(request: Request) -> Response:
        signed = await studio.signed_in(request)
        if isinstance(signed, Response):
            return signed
        form = await studio.form(request, signed, max_bytes=PASTE_MAX_CHARS * 9 + 4096)
        if isinstance(form, Response):
            return form
        text = form.get("text", "").strip()
        if not text:
            return await setup_page(request, signed, status=400, error="Paste some text first.")
        data = text[:PASTE_MAX_CHARS].encode()
        try:
            check_file(TEXT, "document", len(data), await db.run(store.usage, signed.user.id))
            accepted = await process(files, signed.user.id, TEXT, data, slots=studio.slots)
        except UploadError as e:
            return await setup_page(request, signed, status=400, error=e.message)
        now = ctx.now()
        await db.run(
            store.add_file,
            user_id=signed.user.id,
            kind="document",
            stored_name=accepted.stored_name,
            original_name="Pasted text",
            mime="text/plain",
            size=accepted.size,
            text=accepted.text,
            now=now,
        )
        await db.run(
            db.audit, "file.uploaded", now=now, ip_hash=ctx.ip_hash(request), user_id=signed.user.id, detail="pasted"
        )
        return RedirectResponse("/studio/setup?m=pasted#documents", status_code=303)

    async def run_draft(job: DraftJob, signed: SignedIn, sources: list[Source], ip_hash: str) -> None:
        user = signed.user
        try:
            job.step = "drafting"
            fields = await draft_profile(ctx.settings, sources, ctx.transport)
            job.step = "checking"
            record = await studio.record(signed)
            merged = {**record.data, **{k: fields[k] for k in DRAFT_KEYS if k in fields}}
            stored, errors = validate(user.handle, merged, ctx.cloud.public_url)
            if errors:
                _prune_invalid(merged, errors)
                stored, errors = validate(user.handle, merged, ctx.cloud.public_url)
            if stored is None:
                logger.warning(f"Draft for user {user.id} failed validation: {sorted(errors)}")
                raise DraftError("The AI's draft didn't pass our checks. Please try again.")
            flags = find_flags(stored, "ai")
            await db.run(store.save_persona, user.id, stored, flags, ctx.now(), drafted=True)
            detail = f"{sum(len(s.text) for s in sources)} chars, {len(flags)} flags"
            await db.run(db.audit, "draft.created", now=ctx.now(), ip_hash=ip_hash, user_id=user.id, detail=detail)
            job.step, job.state = "done", "done"
        except DraftError as e:
            job.state, job.error = "failed", str(e)
            await db.run(db.audit, "draft.failed", now=ctx.now(), ip_hash=ip_hash, user_id=user.id)
        except Exception:
            logger.exception(f"Draft for user {user.id} crashed")
            job.state, job.error = "failed", "Something went wrong while drafting. Please try again."
            await db.run(db.audit, "draft.failed", now=ctx.now(), ip_hash=ip_hash, user_id=user.id, detail="crash")

    @router.post("/studio/draft")
    async def start_draft(request: Request) -> Response:
        signed = await studio.signed_in(request)
        if isinstance(signed, Response):
            return signed
        form = await studio.form(request, signed)
        if isinstance(form, Response):
            return form
        user, now = signed.user, ctx.now()
        current = jobs.get(user.id)
        if current and current.state == "running":
            return RedirectResponse("/studio/setup?m=draft_running", status_code=303)
        recent_hour = await db.run(db.actions_since, "draft.started", now - 3600, user_id=user.id)
        recent_day = await db.run(db.actions_since, "draft.started", now - 86_400, user_id=user.id)
        if recent_hour >= DRAFTS_PER_HOUR or recent_day >= DRAFTS_PER_DAY:
            return RedirectResponse("/studio/setup?m=draft_limit", status_code=303)
        documents = await db.run(store.list_files, user.id, "document")
        sources = [Source(f.original_name, f.text) for f in documents if f.text.strip()]
        if not sources:
            return RedirectResponse("/studio/setup?m=no_sources", status_code=303)
        ip_hash = ctx.ip_hash(request)
        await db.run(db.audit, "draft.started", now=now, ip_hash=ip_hash, user_id=user.id)
        job = DraftJob()
        jobs[user.id] = job
        job.task = asyncio.create_task(run_draft(job, signed, sources, ip_hash))
        return RedirectResponse("/studio/setup#draft", status_code=303)

    @router.get("/studio/draft/status")
    async def draft_status(request: Request) -> Response:
        signed = await studio.signed_in(request)
        if isinstance(signed, Response):
            return JSONResponse({"state": "signed_out"}, status_code=401)
        job = await job_view(signed.user.id)
        return JSONResponse(job or {"state": "none"}, headers={"Cache-Control": "no-store"})
