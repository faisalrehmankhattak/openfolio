"""HTTP and WebRTC signalling server.

GET   /v1/personas/{id}               public profile shown before a call ("{handle}~preview": owner-only draft)
GET   /v1/personas/{id}/ice-servers   STUN/TURN settings for the browser
POST  /v1/personas/{id}/offer         WebRTC offer -> answer; starts a conversation
PATCH /v1/personas/{id}/offer         trickled ICE candidates
GET   /livez, /healthz                liveness and readiness
GET   /embed/*, /avatars/*, /         widget, avatar files, demo page
With CLOUD_MODE=1, / is the Openfolio Cloud landing page and cloud/routes.py adds its pages.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import time
import uuid
from collections import defaultdict, deque
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger
from pipecat.transports.smallwebrtc.connection import IceServer, SmallWebRTCConnection
from pipecat.transports.smallwebrtc.request_handler import (
    IceCandidate,
    SmallWebRTCPatchRequest,
    SmallWebRTCRequest,
    SmallWebRTCRequestHandler,
)
from pydantic import BaseModel, Field, ValidationError

from .bot import run_conversation
from .config import ROOT, Settings, load_settings
from .doctor import run_checks
from .ice import IceProvider
from .persona import Persona, load_persona_dirs
from .registry import PREVIEW_SUFFIX, PersonaRegistry

if TYPE_CHECKING:
    from .cloud.routes import CloudService

MAX_BODY_BYTES = 64_000
RATE_WINDOW_SECONDS = 600
LOCAL_IPS = ("127.0.0.1", "::1")
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), geolocation=()",
}


class OfferBody(BaseModel):
    sdp: str = Field(max_length=MAX_BODY_BYTES)
    type: str = Field(pattern="^(offer|answer)$")
    pc_id: str | None = Field(default=None, max_length=128)
    restart_pc: bool | None = None


class CandidateBody(BaseModel):
    candidate: str = Field(max_length=1024)
    sdp_mid: str | None = Field(default=None, max_length=64)
    sdp_mline_index: int = Field(ge=0, le=64)


class PatchBody(BaseModel):
    pc_id: str = Field(max_length=128)
    candidates: list[CandidateBody] = Field(default=[], max_length=64)


class RateLimiter:
    """Sliding-window counter per key. Empty windows are dropped, so memory stays bounded."""

    def __init__(self, limit: int, window: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.limit = limit
        self.window = window
        self._clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = self._clock()
        hits = self._hits[key]
        while hits and now - hits[0] > self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            return False
        hits.append(now)
        if len(self._hits) > 10_000:
            self._prune(now)
        return True

    def _prune(self, now: float) -> None:
        for key in [k for k, v in self._hits.items() if not v or now - v[-1] > self.window]:
            del self._hits[key]


def client_ip(request: Request, trust_proxy: bool) -> str:
    if trust_proxy and (forwarded := request.headers.get("x-forwarded-for")):
        # The proxy appends the address it saw; earlier entries are client-controlled.
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


async def read_json(request: Request, model: type[BaseModel]) -> Any:
    """Parse a small JSON body. The size cap holds even without a Content-Length header."""
    body = b""
    async for chunk in request.stream():
        body += chunk
        if len(body) > MAX_BODY_BYTES:
            raise HTTPException(413, "Request too large")
    try:
        return model.model_validate_json(body)
    except ValidationError as e:
        raise HTTPException(400, "Malformed signalling request") from e


def create_app(settings: Settings | None = None, *, transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    """Build the server. transport replaces the network for outbound HTTP (Cloudflare) in tests."""
    settings = settings or load_settings()
    registry = PersonaRegistry(load_persona_dirs(settings.personas_dir, settings.private_personas_dir))
    handler = SmallWebRTCRequestHandler(ice_servers=[IceServer(**s) for s in settings.ice_servers] or None)
    ice = IceProvider(settings, transport)
    active: dict[str, asyncio.Task[None]] = {}
    checks: dict[str, dict[str, Any]] = {}
    call_limit = RateLimiter(settings.calls_per_ip, RATE_WINDOW_SECONDS)
    ice_limit = RateLimiter(max(settings.calls_per_ip * 4, 1), RATE_WINDOW_SECONDS)
    dev_origins = set(settings.dev_origins)
    if settings.cloud:
        # The landing page runs the live demo of every persona from the cloud's own origin.
        dev_origins.add(settings.cloud.public_url)
    cloud_service: CloudService | None = None

    def ip(request: Request) -> str:
        return client_ip(request, settings.trust_proxy)

    async def get_persona(request: Request, persona_id: str) -> tuple[Persona, bool]:
        """The persona and whether it is a private preview (never cached, never shared)."""
        if persona_id.endswith(PREVIEW_SUFFIX) and registry.preview:
            if preview := await registry.preview(request, persona_id.removesuffix(PREVIEW_SUFFIX)):
                return preview, True
        elif persona := registry.get(persona_id):
            return persona, False
        raise HTTPException(404, "Unknown persona")

    def check_origin(request: Request, persona: Persona) -> None:
        # Browsers always send Origin on cross-site requests. This stops other sites
        # from embedding a persona; it is not authentication, so rate limits still apply.
        origin = request.headers.get("origin")
        if origin and origin not in persona.origins and origin not in dev_origins:
            raise HTTPException(403, "This site is not allowed to embed this persona")

    def is_local_test(request: Request) -> bool:
        return ip(request) in LOCAL_IPS and request.headers.get("origin", "") in dev_origins

    def check_capacity() -> None:
        if problems := settings.check():
            raise HTTPException(503, "Server is not configured: " + "; ".join(problems))
        if len(active) >= settings.max_sessions:
            raise HTTPException(503, "All lines are busy. Try again in a minute.")

    def is_known_connection(pc_id: str | None) -> bool:
        # Pipecat has no public lookup; renegotiation must not count as a new call.
        return bool(pc_id) and pc_id in handler._pcs_map

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        for problem in settings.check():
            logger.warning(f"Config: {problem}")
        logger.info(f"Loaded personas: {', '.join(registry.files) or 'none'}")
        if os.getenv("OPENFOLIO_SKIP_CHECKS") != "1":
            checks.update(await run_checks(settings))
        if not all(c["ok"] for c in checks.values()):
            logger.error("Provider checks failed; calls are refused until they pass. See GET /healthz.")
        if cloud_service:
            await cloud_service.start()
        yield
        if cloud_service:
            await cloud_service.stop()
        for task in active.values():
            task.cancel()
        await handler.close()  # type: ignore[no-untyped-call]

    app = FastAPI(title="Openfolio", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    # Cloud personas run on PUBLIC_URL, which is already in dev_origins.
    allowed = set(dev_origins) | registry.origins()
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=sorted(allowed),
        allow_methods=["GET", "POST", "PATCH"],
        allow_headers=["content-type"],
        max_age=600,
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)  # a route may choose a stricter value
        return response

    @app.get("/livez")
    async def livez() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/healthz")
    async def healthz() -> JSONResponse:
        problems = settings.check()
        ok = not problems and all(c["ok"] for c in checks.values())
        body = {"ok": ok, "active_sessions": len(active), "config_problems": problems, "checks": checks}
        return JSONResponse(body, status_code=200 if ok else 503)

    @app.get("/v1/personas/{persona_id}")
    async def persona_info(persona_id: str, request: Request) -> JSONResponse:
        # Fetched by the launcher on every page view of the host site.
        persona, private = await get_persona(request, persona_id)
        if private:
            cache = "private, no-store"
        else:  # a member's page can be paused, so their profile is cached only briefly
            cache = "public, max-age=15" if registry.is_dynamic(persona_id) else "public, max-age=300"
        return JSONResponse(persona.public_view(), headers={"Cache-Control": cache})

    @app.get("/v1/personas/{persona_id}/ice-servers")
    async def ice_servers(persona_id: str, request: Request) -> JSONResponse:
        check_origin(request, (await get_persona(request, persona_id))[0])
        # Fetched right before every call, so the widget can explain a refusal before WebRTC starts retrying.
        check_capacity()
        if not is_local_test(request) and not ice_limit.allow(ip(request)):
            raise HTTPException(429, "Too many requests. Try again in a few minutes.")
        return JSONResponse({"iceServers": await ice.browser()}, headers={"Cache-Control": "no-store"})

    @app.post("/v1/personas/{persona_id}/offer")
    async def offer(persona_id: str, request: Request) -> Any:
        persona, _ = await get_persona(request, persona_id)
        check_origin(request, persona)
        body: OfferBody = await read_json(request, OfferBody)
        # A call started by typing already carries a question; a greeting would race it.
        greet = request.query_params.get("greet") != "0"

        if not is_known_connection(body.pc_id):
            check_capacity()
            if not is_local_test(request) and not call_limit.allow(ip(request)):
                raise HTTPException(429, "Too many calls from this network. Try again in a few minutes.")

        async def on_connection(connection: SmallWebRTCConnection) -> None:
            session_id = uuid.uuid4().hex[:12]

            async def run() -> None:
                try:
                    await run_conversation(connection, persona, settings, session_id, greet=greet)
                except Exception:
                    logger.exception(f"[{session_id}] conversation failed")
                finally:
                    active.pop(session_id, None)

            active[session_id] = asyncio.create_task(run())

        # Fresh TURN credentials for the worker side of every connection; without inbound UDP
        # (Railway) the server's media can only arrive through the relay.
        handler.update_ice_servers([IceServer(**s) for s in await ice.worker()] or None)
        request_ = SmallWebRTCRequest(sdp=body.sdp, type=body.type, pc_id=body.pc_id, restart_pc=body.restart_pc)
        return await handler.handle_web_request(request=request_, webrtc_connection_callback=on_connection)

    @app.patch("/v1/personas/{persona_id}/offer")
    async def ice_candidate(persona_id: str, request: Request) -> dict[str, str]:
        check_origin(request, (await get_persona(request, persona_id))[0])
        body: PatchBody = await read_json(request, PatchBody)
        if not is_known_connection(body.pc_id):
            raise HTTPException(404, "Unknown connection")
        candidates = [IceCandidate(**c.model_dump()) for c in body.candidates]
        await handler.handle_patch_request(SmallWebRTCPatchRequest(pc_id=body.pc_id, candidates=candidates))
        return {"status": "success"}

    if settings.embed_dir.exists():
        app.mount("/embed", StaticFiles(directory=settings.embed_dir), name="embed")
    else:
        logger.warning(f"No widget build at {settings.embed_dir}; run `npm run build` in embed/")
    if settings.avatars_dir.exists():
        app.mount("/avatars", StaticFiles(directory=settings.avatars_dir), name="avatars")

    if settings.cloud:
        from .cloud.routes import install  # self-hosted servers never load the cloud pages

        cloud_service = install(app, settings, registry, ip, transport)
        return app

    demo = ROOT / "demo" / "index.html"

    @app.get("/", include_in_schema=False, response_model=None)
    async def index() -> FileResponse | dict[str, str]:
        return FileResponse(demo) if demo.exists() else {"service": "openfolio"}

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Openfolio voice worker")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7860)
    args = parser.parse_args()

    import uvicorn

    settings = load_settings()  # reads .env, so DATA_DIR from there applies to the log too
    log_dir = Path(os.getenv("LOG_DIR") or settings.data_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    logger.add(log_dir / "worker.log", level="INFO", rotation="5 MB", retention=3, enqueue=True)
    uvicorn.run(create_app(settings), host=args.host, port=args.port, proxy_headers=False)


if __name__ == "__main__":
    main()
