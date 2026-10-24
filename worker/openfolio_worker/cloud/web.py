"""Shared pieces of the cloud pages: the request context, templates and security headers."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from fastapi import Request
from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from ..config import CloudSettings, Settings
from ..persona import Persona
from ..registry import PersonaRegistry
from .auth import Keys
from .db import CloudDB
from .mail import Mailer
from .store import StudioStore
from .uploads import FileStore

HERE = Path(__file__).resolve().parent
TEMPLATES_DIR = HERE / "templates"
STATIC_DIR = HERE / "static"
TURNSTILE_ORIGIN = "https://challenges.cloudflare.com"

# Every cloud page except the landing page: no inline code, nothing from other origins.
STRICT_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; "
    "font-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)


def landing_csp(turnstile: bool) -> str:
    """STRICT_CSP plus the two things the live widget needs, measured in Chrome with the demo running.

    - style-src 'unsafe-inline': the widget styles its shadow DOM with <style> elements made at runtime.
    - connect-src blob:: TalkingHead fetches the avatar's embedded textures through blob: URLs.
    No eval or wasm-unsafe-eval is needed. Turnstile, when on, adds its script and iframe origin.
    """
    script = f"'self' {TURNSTILE_ORIGIN}" if turnstile else "'self'"
    frame = TURNSTILE_ORIGIN if turnstile else "'none'"
    return (
        f"default-src 'self'; script-src {script}; style-src 'self' 'unsafe-inline'; img-src 'self'; "
        f"media-src 'self'; connect-src 'self' blob:; worker-src 'self'; frame-src {frame}; font-src 'self'; "
        "object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    )


def _when(ts: int | None) -> str:
    if ts is None:
        return ""
    return datetime.fromtimestamp(ts, UTC).strftime("%d %b %Y, %H:%M UTC")


def _iso(ts: int | None) -> str:
    return "" if ts is None else datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ago(ts: int | None, now: int) -> str:
    if ts is None:
        return ""
    seconds = max(0, now - ts)
    for unit, size in (("day", 86_400), ("hour", 3600), ("minute", 60)):
        if seconds >= size:
            count = seconds // size
            return f"{count} {unit}{'s' if count != 1 else ''} ago"
    return "just now"


def safe_url(url: str | None) -> str | None:
    """Only http(s) links are rendered as links; anything else is shown as plain text."""
    if not url:
        return None
    return url if urlsplit(url).scheme in ("http", "https") else None


def asset_url(url: str | None) -> str:
    """Persona files are relative to the server root; absolute URLs pass through."""
    if not url:
        return ""
    return url if "://" in url else "/" + url.lstrip("/")


def _size(n: int) -> str:
    if n >= 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} MB"
    return f"{max(1, round(n / 1024))} KB"


def _asset_version() -> str:
    digest = hashlib.sha256()
    for path in sorted(STATIC_DIR.glob("*")):
        digest.update(path.read_bytes())
    return digest.hexdigest()[:10]


def make_templates() -> Environment:
    env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        autoescape=select_autoescape(default=True, default_for_string=True),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters.update(when=_when, iso=_iso, ago=_ago, safe_url=safe_url, asset=asset_url, size=_size)
    env.globals["asset_version"] = _asset_version()
    return env


@dataclass
class CloudContext:
    settings: Settings
    cloud: CloudSettings
    db: CloudDB
    keys: Keys
    mailer: Mailer
    registry: PersonaRegistry
    store: StudioStore
    files: FileStore
    client_ip: Callable[[Request], str]
    transport: httpx.AsyncBaseTransport | None = None
    clock: Callable[[], float] = time.time
    templates: Environment = field(default_factory=make_templates)

    def now(self) -> int:
        return int(self.clock())

    def ip_hash(self, request: Request) -> str:
        return self.keys.ip_hash(self.client_ip(request))

    @property
    def demo(self) -> Persona | None:
        return self.registry.files.get(self.cloud.demo_persona)

    @property
    def contact_email(self) -> str | None:
        return (self.demo.email if self.demo else None) or self.mailer.notify_email

    @property
    def landing_csp(self) -> str:
        return landing_csp(bool(self.cloud.turnstile_site_key))

    @property
    def widget_csp(self) -> str:
        """Pages that run the widget (Studio preview, public profiles): the landing page's exceptions only."""
        return landing_csp(False)

    def render(
        self,
        request: Request,
        template: str,
        *,
        status: int = 200,
        csp: str = STRICT_CSP,
        headers: dict[str, str] | None = None,
        **context: Any,
    ) -> HTMLResponse:
        html = self.templates.get_template(template).render(
            path=request.url.path,
            now=self.now(),
            public_url=self.cloud.public_url,
            contact_email=self.contact_email,
            github_url=self.cloud.github_url,
            **context,
        )
        return HTMLResponse(html, status_code=status, headers={"Content-Security-Policy": csp, **(headers or {})})
