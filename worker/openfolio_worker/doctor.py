"""Checks each provider with a tiny real request, so a broken key or model
name shows up at startup instead of as a silent call.

Run alone with `uv run openfolio-doctor`, or read the results at /healthz.
"""

from __future__ import annotations

import asyncio
import time

import httpx
from loguru import logger

from .config import Settings, llm_extra_params, load_settings


async def check_llm(s: Settings) -> str:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=s.llm_api_key or "not-needed", base_url=s.llm_base_url, timeout=20)
    t0 = time.monotonic()
    # Same shape as a real call: streaming, a developer message, a tool and the
    # same extra fields, so anything a real call would hit fails here first.
    stream = await client.chat.completions.create(
        model=s.llm_model,
        messages=[
            {"role": "developer", "content": "Reply with the single word OK. Do not call any tool."},
            {"role": "user", "content": "ping"},
        ],
        tools=[{"type": "function", "function": {"name": "show_projects", "description": "Show projects.",
                                                 "parameters": {"type": "object", "properties": {}, "required": []}}}],
        stream=True,
        **llm_extra_params(s),
    )
    text = ""
    first = None
    async for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            first = first or time.monotonic() - t0
            text += chunk.choices[0].delta.content
    if not text.strip():
        raise RuntimeError("the model answered with no text")
    extra = llm_extra_params(s)
    note = f" (reasoning_effort={extra['reasoning_effort']})" if extra else ""
    return f"{s.llm_model}{note} answered in {first:.2f}s"


async def check_deepgram(s: Settings) -> str:
    if s.stt_provider != "deepgram":
        return f"skipped ({s.stt_provider})"
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get("https://api.deepgram.com/v1/projects", headers={"Authorization": f"Token {s.deepgram_api_key}"})
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

    t0 = time.monotonic()
    await asyncio.to_thread(warm_up_voice, s)
    return f"Kokoro ready in {time.monotonic() - t0:.1f}s"


async def run_checks(s: Settings) -> dict[str, dict]:
    results: dict[str, dict] = {}
    for name, check in (("llm", check_llm), ("speech_to_text", check_deepgram), ("voice", check_voice)):
        try:
            detail = await check(s)
            results[name] = {"ok": True, "detail": detail}
            logger.info(f"Check {name}: OK, {detail}")
        except Exception as e:
            msg = str(e).strip() or type(e).__name__
            results[name] = {"ok": False, "detail": msg[:500]}
            logger.error(f"Check {name}: FAILED, {msg[:500]}")
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
