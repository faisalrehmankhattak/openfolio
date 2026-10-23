"""Provider checks: one tiny real request each, so a bad key fails at startup, not mid-call.

Run alone with `uv run openfolio-doctor`; results are also served at /healthz.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from loguru import logger

from .config import Settings, llm_extra_params, load_settings

Check = Callable[[Settings], Awaitable[str]]


async def check_llm(s: Settings) -> str:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=s.llm_api_key or "not-needed", base_url=s.llm_base_url, timeout=20)
    extra = llm_extra_params(s)
    started = time.monotonic()
    # Same shape as a real call (streaming, developer role, a tool, extra fields).
    stream = await client.chat.completions.create(  # type: ignore[call-overload]
        model=s.llm_model,
        messages=[
            {"role": "developer", "content": "Reply with the single word OK. Do not call any tool."},
            {"role": "user", "content": "ping"},
        ],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "leave_message",
                    "description": "Leave a message.",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                },
            }
        ],
        stream=True,
        **extra,
    )
    text, first_token = "", 0.0
    async for chunk in stream:
        if chunk.choices and (delta := chunk.choices[0].delta.content):
            first_token = first_token or time.monotonic() - started
            text += delta
    if not text.strip():
        raise RuntimeError("the model answered with no text")
    note = f" (reasoning_effort={extra['reasoning_effort']})" if extra else ""
    return f"{s.llm_model}{note} answered in {first_token:.2f}s"


async def check_speech_to_text(s: Settings) -> str:
    if s.stt_provider != "deepgram":
        return f"skipped ({s.stt_provider})"
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(
            "https://api.deepgram.com/v1/projects", headers={"Authorization": f"Token {s.deepgram_api_key}"}
        )
    if r.status_code != 200:
        raise RuntimeError(f"Deepgram rejected the key (HTTP {r.status_code})")
    return "key accepted"


async def check_voice(s: Settings) -> str:
    if s.tts_provider == "elevenlabs":
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(
                f"https://api.elevenlabs.io/v1/voices/{s.elevenlabs_voice_id}",
                headers={"xi-api-key": s.elevenlabs_api_key or ""},
            )
        if r.status_code != 200:
            raise RuntimeError(f"ElevenLabs rejected the key or voice ID (HTTP {r.status_code})")
        return f"ElevenLabs voice '{r.json().get('name', '?')}' found"
    from .bot import warm_up_voice

    started = time.monotonic()
    await asyncio.to_thread(warm_up_voice, s)
    return f"Kokoro ready in {time.monotonic() - started:.1f}s"


CHECKS: dict[str, Check] = {"llm": check_llm, "speech_to_text": check_speech_to_text, "voice": check_voice}


async def run_checks(s: Settings) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for name, check in CHECKS.items():
        try:
            detail = await check(s)
            results[name] = {"ok": True, "detail": detail}
            logger.info(f"Check {name}: OK, {detail}")
        except Exception as e:
            message = (str(e).strip() or type(e).__name__)[:500]
            results[name] = {"ok": False, "detail": message}
            logger.error(f"Check {name}: FAILED, {message}")
    return results


def main() -> None:
    s = load_settings()
    for problem in s.check():
        print(f"Config: {problem}")
    results = asyncio.run(run_checks(s))
    for name, r in results.items():
        print(f"{'OK  ' if r['ok'] else 'FAIL'} {name}: {r['detail']}")
    raise SystemExit(0 if all(r["ok"] for r in results.values()) else 1)


if __name__ == "__main__":
    main()
