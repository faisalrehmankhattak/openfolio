"""HTTP + WebRTC signalling server.

Routes
  GET   /v1/personas/{id}          public profile the widget shows before a call
  POST  /v1/personas/{id}/offer    WebRTC offer -> answer, starts a conversation
  PATCH /v1/personas/{id}/offer    trickled ICE candidates
  GET   /embed/*                   the built widget (embed.js and its chunks)
  GET   /avatars/*                 avatar files
  GET   /                          a demo page with the widget on it
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
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

from .bot import run_conversation
from .doctor import run_checks
from .config import ROOT, Settings, load_settings
from .persona import Persona, load_personas


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    personas = load_personas(settings.personas_dir)
    handler = SmallWebRTCRequestHandler(
        ice_servers=[IceServer(**s) for s in settings.ice_servers] or None
    )
    active: dict[str, asyncio.Task] = {}
    checks: dict[str, dict] = {}
    calls_by_ip: dict[str, deque] = defaultdict(deque)
    CALLS_PER_WINDOW, WINDOW_SECONDS = int(os.getenv("CALLS_PER_IP", "6")), 600
    trust_proxy = os.getenv("TRUST_PROXY") == "1"

    def client_ip(request: Request) -> str:
        # Behind a reverse proxy, set TRUST_PROXY=1 so the real visitor IP is used.
        if trust_proxy and (fwd := request.headers.get("x-forwarded-for")):
            return fwd.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    def allow_new_call(ip: str) -> bool:
        now = time.monotonic()
        q = calls_by_ip[ip]
        while q and now - q[0] > WINDOW_SECONDS:
            q.popleft()
        if len(q) >= CALLS_PER_WINDOW:
            return False
        q.append(now)
        return True

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        for problem in settings.check():
            logger.warning(f"Config: {problem}")
        logger.info(f"Loaded personas: {', '.join(personas) or 'none'}")
        # Test every provider with a tiny real request (and warm up the voice),
        # so a bad key or model name shows up here, not as a silent call.
        if os.getenv("OPENFOLIO_SKIP_CHECKS") != "1":
            checks.update(await run_checks(settings))
        if not all(c["ok"] for c in checks.values()):
            logger.error("Some checks failed; calls will not work until they pass. See above or GET /healthz.")
        yield
        for task in active.values():
            task.cancel()
        await handler.close()

    app = FastAPI(title="Openfolio worker", lifespan=lifespan)

    allowed = set(settings.dev_origins)
    for p in personas.values():
        allowed.update(p.allowed_origins)
    # Avatar files are large; compress them in development. A CDN does this in production.
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=sorted(allowed),
        allow_methods=["GET", "POST", "PATCH"],
        allow_headers=["*"],
    )

    def get_persona(persona_id: str) -> Persona:
        persona = personas.get(persona_id)
        if not persona:
            raise HTTPException(404, "Unknown persona")
        return persona

    def check_origin(request: Request, persona: Persona) -> None:
        # Stops other sites from embedding a persona and spending its minutes.
        # Browsers always send Origin on cross-site POSTs; same-origin dev pages
        # and server-to-server tools may omit it.
        origin = request.headers.get("origin")
        if origin and origin not in persona.allowed_origins and origin not in settings.dev_origins:
            raise HTTPException(403, f"{origin} is not allowed to embed this persona")

    @app.get("/healthz")
    async def healthz():
        problems = settings.check()
        ok = not problems and all(c["ok"] for c in checks.values())
        return {"ok": ok, "active_sessions": len(active), "config_problems": problems, "checks": checks}

    @app.get("/v1/personas/{persona_id}")
    async def persona_info(persona_id: str):
        return get_persona(persona_id).public_view()

    @app.post("/v1/personas/{persona_id}/offer")
    async def offer(persona_id: str, request: Request):
        persona = get_persona(persona_id)
        check_origin(request, persona)
        if int(request.headers.get("content-length") or 0) > 64_000:
            raise HTTPException(413, "Request too large")
        body = await request.json()
        webrtc_request = SmallWebRTCRequest.from_dict(
            {k: body[k] for k in ("sdp", "type", "pc_id", "restart_pc", "requestData", "request_data") if k in body}
        )

        is_new = not webrtc_request.pc_id or webrtc_request.pc_id not in handler._pcs_map
        if is_new:
            if problems := settings.check():
                raise HTTPException(503, "Server is not configured: " + "; ".join(problems))
            if len(active) >= settings.max_sessions:
                raise HTTPException(503, "All lines are busy, try again in a minute")
            ip = client_ip(request)
            # Testing on your own machine (a local page talking to a local server) is not limited.
            local_test = ip in ("127.0.0.1", "::1") and request.headers.get("origin", "") in settings.dev_origins
            if not local_test and not allow_new_call(ip):
                raise HTTPException(429, "Too many calls from this network. Try again in a few minutes.")

        async def on_connection(connection: SmallWebRTCConnection):
            session_id = uuid.uuid4().hex[:12]

            async def run():
                try:
                    await run_conversation(connection, persona, settings, session_id)
                except Exception:
                    logger.exception(f"[{session_id}] conversation failed")
                finally:
                    active.pop(session_id, None)

            active[session_id] = asyncio.create_task(run())

        return await handler.handle_web_request(
            request=webrtc_request, webrtc_connection_callback=on_connection
        )

    @app.patch("/v1/personas/{persona_id}/offer")
    async def ice_candidate(persona_id: str, request: Request):
        get_persona(persona_id)
        check_origin(request, get_persona(persona_id))
        if int(request.headers.get("content-length") or 0) > 64_000:
            raise HTTPException(413, "Request too large")
        body = await request.json()
        await handler.handle_patch_request(
            SmallWebRTCPatchRequest(
                pc_id=body["pc_id"],
                candidates=[IceCandidate(**c) for c in body.get("candidates", [])],
            )
        )
        return {"status": "success"}

    if settings.embed_dir.exists():
        app.mount("/embed", StaticFiles(directory=settings.embed_dir), name="embed")
    else:
        logger.warning(f"No widget build at {settings.embed_dir}; run `npm run build` in embed/")
    if settings.avatars_dir.exists():
        app.mount("/avatars", StaticFiles(directory=settings.avatars_dir), name="avatars")

    demo = ROOT / "demo" / "index.html"

    @app.get("/", include_in_schema=False)
    async def index():
        if demo.exists():
            return FileResponse(demo)
        return JSONResponse({"service": "openfolio-worker"})

    return app


def main() -> None:
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(description="Openfolio voice worker")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7860)
    args = parser.parse_args()
    # Keep a log file next to the code so problems can be read after the fact.
    log_dir = ROOT / "data"
    log_dir.mkdir(exist_ok=True)
    logger.add(log_dir / "worker.log", level="INFO", rotation="5 MB", retention=3, enqueue=True)
    uvicorn.run(create_app(), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
