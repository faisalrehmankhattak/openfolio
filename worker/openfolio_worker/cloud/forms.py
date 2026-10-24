"""The public access-request form: body parsing, validation and Cloudflare Turnstile."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
from fastapi import Request
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

MAX_FORM_BYTES = 16_000
TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
# Control characters and bidirectional overrides, which can disguise text on the admin page.
_INVISIBLE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f\u200e\u200f\u202a-\u202e\u2066-\u2069]")
_LINE = re.compile(r"[\r\n\t\u2028\u2029]+")

FIELD_ERRORS = {
    "name": "Please enter your name (up to 100 characters).",
    "email": "Please enter a valid email address.",
    "portfolio_url": "Please enter your portfolio's address, starting with https:// or http://.",
    "about": "Please say briefly what you do (up to 120 characters).",
    "reason": "Please keep this under 500 characters.",
    "consent": "Please agree to the privacy notice so we can store your request.",
}


class FormError(Exception):
    """A body that is not a small URL-encoded form."""

    def __init__(self, status: int) -> None:
        self.status = status


async def read_form(request: Request, *, max_bytes: int = MAX_FORM_BYTES, max_fields: int = 30) -> dict[str, str]:
    """Parse a small URL-encoded form. The cap holds even when streamed (uploads use uploads.read_multipart)."""
    if request.headers.get("content-type", "").split(";")[0].strip() != "application/x-www-form-urlencoded":
        raise FormError(415)
    body = b""
    async for chunk in request.stream():
        body += chunk
        if len(body) > max_bytes:
            raise FormError(413)
    try:
        fields = parse_qs(body.decode(), keep_blank_values=True, max_num_fields=max_fields)
    except (UnicodeDecodeError, ValueError) as e:
        raise FormError(400) from e
    return {key: values[0] for key, values in fields.items()}


def _single_line(text: str) -> str:
    return " ".join(_LINE.sub(" ", _INVISIBLE.sub("", text)).split())


class AccessRequestForm(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=3, max_length=254)
    portfolio_url: str = Field(min_length=1, max_length=300)
    about: str = Field(min_length=1, max_length=120)
    reason: str = Field(default="", max_length=500)
    consent: bool

    @field_validator("name", "about", "portfolio_url", mode="before")
    @classmethod
    def _line(cls, value: Any) -> Any:
        return _single_line(value) if isinstance(value, str) else value

    @field_validator("reason", mode="before")
    @classmethod
    def _paragraph(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        text = _INVISIBLE.sub("", value.replace("\r\n", "\n").replace("\r", "\n").replace("\t", " "))
        return re.sub(r"\n{3,}", "\n\n", text).strip()

    @field_validator("email", mode="before")
    @classmethod
    def _email(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        email = value.strip().lower()
        if not EMAIL_RE.fullmatch(email):
            raise ValueError("invalid email")
        return email

    @field_validator("portfolio_url")
    @classmethod
    def _url(cls, value: str) -> str:
        url = value if ":" in value else f"https://{value}"  # "jane.dev" is what people type
        parts = urlsplit(url)
        try:
            parts.port  # noqa: B018 - raises ValueError for a malformed port
        except ValueError as e:
            raise ValueError("invalid port") from e
        host = parts.hostname or ""
        if parts.scheme not in ("http", "https") or "." not in host or parts.username or " " in url:
            raise ValueError("http or https address with a domain")
        return url

    @field_validator("consent", mode="before")
    @classmethod
    def _consent(cls, value: Any) -> bool:
        if value not in ("on", "1", "true", "yes", True):
            raise ValueError("consent required")
        return True


def validate_request(fields: dict[str, str]) -> tuple[AccessRequestForm | None, dict[str, str]]:
    """The parsed form, or a friendly message per field that failed."""
    data = {key: fields.get(key, "") for key in ("name", "email", "portfolio_url", "about", "reason")}
    data["consent"] = fields.get("consent", "")
    try:
        return AccessRequestForm.model_validate(data), {}
    except ValidationError as e:
        failed = {str(err["loc"][0]) for err in e.errors() if err["loc"]}
        return None, {name: FIELD_ERRORS[name] for name in FIELD_ERRORS if name in failed}


async def verify_turnstile(secret: str, token: str, ip: str, transport: httpx.AsyncBaseTransport | None = None) -> bool:
    """Server-side Turnstile check. Fails closed: an unreachable Cloudflare means "try again"."""
    if not token or len(token) > 2048:
        return False
    try:
        async with httpx.AsyncClient(timeout=5, transport=transport) as client:
            r = await client.post(TURNSTILE_VERIFY_URL, data={"secret": secret, "response": token, "remoteip": ip})
        return r.status_code == 200 and r.json().get("success") is True
    except (httpx.HTTPError, ValueError) as e:
        logger.warning(f"Turnstile verification failed ({type(e).__name__})")
        return False
