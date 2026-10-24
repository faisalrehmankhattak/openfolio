"""Member uploads: streaming size caps, type detection from magic bytes, quotas and private storage.

The file name and Content-Type a browser sends are never trusted: the first bytes decide what a
file is, and the parser for that type (in the sandbox) decides whether it is valid. Photos are
re-encoded, so the stored copy is a fresh JPEG with no metadata; documents are stored as uploaded
and are only ever served back to their owner as an attachment.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import secrets
import shutil
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from fastapi import Request
from starlette.datastructures import FormData
from starlette.types import Message, Receive

from . import sandbox

MB = 1024 * 1024
REQUEST_MAX_BYTES = 12 * MB  # whole multipart body, enforced while it streams in
MAX_FILES = 10
MAX_TOTAL_BYTES = 30 * MB
Slot = Literal["document", "photo"]


@dataclass(frozen=True)
class FileType:
    parser: str  # sandbox kind
    slot: Slot
    mime: str
    ext: str
    label: str
    max_bytes: int


PDF = FileType("pdf", "document", "application/pdf", "pdf", "PDF", 10 * MB)
DOCX = FileType(
    "docx",
    "document",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "docx",
    "Word",
    5 * MB,
)
TEXT = FileType("text", "document", "text/plain", "txt", "text", 200 * 1024)
JPEG = FileType("photo", "photo", "image/jpeg", "jpg", "JPEG", 5 * MB)
PNG = FileType("photo", "photo", "image/png", "png", "PNG", 5 * MB)
WEBP = FileType("photo", "photo", "image/webp", "webp", "WebP", 5 * MB)

# Formats people might try that we refuse outright (checked before the text fallback).
_REFUSED = (b"GIF8", b"\xd0\xcf\x11\xe0", b"MZ", b"\x7fELF", b"\xca\xfe\xba\xbe", b"\x1f\x8b", b"Rar!", b"7z\xbc\xaf")

MESSAGES = {
    "empty": "That file is empty.",
    "too_large": "That file is too large.",
    "request_too_large": "Uploads are limited to 12 MB.",
    "unsupported": (
        "That file type isn't supported. Use a PDF, Word (.docx) or text file, or a JPEG, PNG or WebP photo."
    ),
    "wrong_slot_photo": "That's a photo. Add it under Photo instead.",
    "wrong_slot_document": "That's a document. Add it under Documents instead.",
    "quota_files": f"You can keep up to {MAX_FILES} files. Delete one to add another.",
    "quota_bytes": "You've used your 30 MB of storage. Delete a file to add another.",
    "pdf_malformed": "We couldn't read that PDF. Try exporting it again.",
    "pdf_encrypted": "That PDF is password-protected. Remove the password and upload it again.",
    "pdf_pages": "PDFs can have up to 30 pages.",
    "docx_malformed": "We couldn't read that Word file. Try saving it again as .docx.",
    "docx_not_word": "That file isn't a Word document (.docx).",
    "docx_encrypted": "That Word file is password-protected.",
    "docx_entries": "That Word file has too many parts to read safely.",
    "zip_bomb": "That file expands to more than 25 MB, so we can't read it safely.",
    "text_encoding": "Text files must be UTF-8.",
    "text_binary": "That doesn't look like a text file.",
    "image_type": "Photos must be JPEG, PNG or WebP.",
    "image_pixels": "That photo has too many pixels (the limit is 40 megapixels).",
    "image_small": "That photo is too small. Use one at least 64 pixels wide.",
    "image_malformed": "We couldn't read that photo.",
    "timeout": "That file took too long to read. Try a simpler export.",
    "too_complex": "That file is too complex to read safely.",
    "no_text": "We couldn't find any text in that file. If it's a scan, paste the text instead.",
}


class UploadError(Exception):
    def __init__(self, code: str, detail: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail

    @property
    def message(self) -> str:
        return self.detail or MESSAGES.get(self.code, MESSAGES["too_complex"])


def detect(head: bytes) -> FileType | None:
    """The type of a file from its first bytes; None for anything unsupported."""
    if head.startswith(b"%PDF-"):
        return PDF
    if head.startswith(b"PK\x03\x04"):
        return DOCX  # any ZIP; the parser checks that it really is a Word document
    if head.startswith(b"\xff\xd8\xff"):
        return JPEG
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return PNG
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return WEBP
    if head.startswith(_REFUSED) or b"\x00" in head[:4096]:
        return None
    try:
        head[:4096].decode("utf-8")
    except UnicodeDecodeError as e:
        # A multi-byte character cut at the boundary is still text.
        if e.start < len(head[:4096]) - 3:
            return None
    return TEXT


def check_file(file_type: FileType | None, slot: Slot, size: int, usage: tuple[int, int]) -> FileType:
    """Size, slot and quota rules for a detected file; raises UploadError."""
    if size == 0:
        raise UploadError("empty")
    if file_type is None:
        raise UploadError("unsupported")
    if file_type.slot != slot:
        raise UploadError(f"wrong_slot_{file_type.slot}")
    if size > file_type.max_bytes:
        limit = f"{file_type.max_bytes // MB} MB" if file_type.max_bytes >= MB else f"{file_type.max_bytes // 1024} KB"
        raise UploadError("too_large", f"{file_type.label} files can be up to {limit}.")
    count, total = usage
    if count >= MAX_FILES:
        raise UploadError("quota_files")
    if total + size > MAX_TOTAL_BYTES:
        raise UploadError("quota_bytes")
    return file_type


class BodyTooLarge(Exception):
    pass


class _CappedReceive:
    """Counts body bytes as they arrive and stops the stream once it passes the limit."""

    def __init__(self, receive: Receive, limit: int) -> None:
        self.receive = receive
        self.limit = limit
        self.seen = 0
        self.exceeded = False

    async def __call__(self) -> Message:
        message = await self.receive()
        if message["type"] == "http.request":
            self.seen += len(message.get("body", b""))
            if self.seen > self.limit:
                self.exceeded = True  # remembered, in case the parser wraps the exception
                raise BodyTooLarge
        return message


async def read_multipart(request: Request, *, max_bytes: int = REQUEST_MAX_BYTES) -> FormData:
    """Parse a multipart form with one file. The byte cap holds while streaming, before parsing finishes."""
    if not request.headers.get("content-type", "").startswith("multipart/form-data"):
        raise UploadError("unsupported", "Please upload the file with the form on this page.")
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > max_bytes:
        raise UploadError("request_too_large")
    receive = _CappedReceive(request.receive, max_bytes)
    capped = Request(request.scope, receive)
    try:
        return await capped.form(max_files=1, max_fields=8, max_part_size=64 * 1024)
    except Exception as e:  # BodyTooLarge, or Starlette's MultiPartException / HTTPException for broken bodies
        if receive.exceeded:
            raise UploadError("request_too_large") from e
        raise UploadError("unsupported", "That upload was incomplete. Please try again.") from e


def clean_filename(name: str | None) -> str:
    """A display name: no path, no control or bidi characters, at most 120 characters."""
    base = re.split(r"[\\/]", name or "")[-1]
    base = "".join(ch for ch in unicodedata.normalize("NFC", base) if unicodedata.category(ch)[0] != "C")
    return base.strip()[:120] or "upload"


class FileStore:
    """Files on disk under DATA_DIR/users/<id>/ with random names the member never chooses."""

    _NAME = re.compile(r"[0-9a-f]{32}\.(pdf|docx|txt|jpg)")

    def __init__(self, data_dir: Path) -> None:
        self.root = data_dir / "users"

    def folder(self, user_id: int) -> Path:
        path = self.root / str(int(user_id))
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        return path

    def path(self, user_id: int, stored_name: str) -> Path:
        if not self._NAME.fullmatch(stored_name):
            raise ValueError("bad stored name")
        return self.root / str(int(user_id)) / stored_name

    @staticmethod
    def new_name(ext: str) -> str:
        return f"{secrets.token_hex(16)}.{ext}"

    def remove(self, user_id: int, stored_name: str) -> None:
        with contextlib.suppress(FileNotFoundError, ValueError):
            self.path(user_id, stored_name).unlink()

    def remove_all(self, user_id: int) -> None:
        shutil.rmtree(self.root / str(int(user_id)), ignore_errors=True)


@dataclass(frozen=True)
class Accepted:
    file_type: FileType
    stored_name: str
    size: int
    text: str


async def process(
    files: FileStore,
    user_id: int,
    file_type: FileType,
    data: bytes,
    *,
    slots: asyncio.Semaphore | None = None,
    seconds: float = sandbox.TIMEOUT_SECONDS,
) -> Accepted:
    """Run the sandboxed parser and keep the result: the re-encoded photo, or the document and its text."""
    folder = files.folder(user_id)
    if file_type.slot == "photo":
        raw = folder / f".in-{secrets.token_hex(8)}"
        name = files.new_name("jpg")
        out = folder / name
        raw.write_bytes(data)
        try:
            await sandbox.run("photo", raw, out, seconds=seconds, slots=slots)
        except sandbox.SandboxError as e:
            out.unlink(missing_ok=True)
            raise UploadError(e.code) from e
        finally:
            raw.unlink(missing_ok=True)  # the original, with its metadata, is never kept
        return Accepted(file_type, name, out.stat().st_size, "")
    name = files.new_name(file_type.ext)
    path = folder / name
    path.write_bytes(data)
    try:
        result = await sandbox.run(file_type.parser, path, seconds=seconds, slots=slots)
    except sandbox.SandboxError as e:
        path.unlink(missing_ok=True)
        raise UploadError(e.code) from e
    text = str(result.get("text", ""))
    if not text.strip():
        path.unlink(missing_ok=True)
        raise UploadError("no_text")
    return Accepted(file_type, name, len(data), text)
