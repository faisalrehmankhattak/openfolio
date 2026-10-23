"""Server settings, read once from the environment (.env in development)."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(os.getenv("OPENFOLIO_ROOT", Path(__file__).resolve().parents[2]))


def _list(name: str) -> list[str]:
    return [v.strip() for v in os.getenv(name, "").split(",") if v.strip()]


@dataclass(frozen=True)
class Settings:
    personas_dir: Path
    inbox_dir: Path
    embed_dir: Path
    avatars_dir: Path

    stt_provider: str  # deepgram | whisper
    tts_provider: str  # elevenlabs | kokoro
    llm_base_url: str | None
    llm_model: str
    llm_reasoning_effort: str  # "auto", "off", or a value such as "none" / "low"

    deepgram_api_key: str | None
    llm_api_key: str | None
    elevenlabs_api_key: str | None
    elevenlabs_voice_id: str | None
    elevenlabs_model: str
    kokoro_voice: str

    ice_servers: list[dict] = field(default_factory=list)
    dev_origins: list[str] = field(default_factory=list)
    max_sessions: int = 4
    turn_urls: list[str] = field(default_factory=list)
    turn_shared_secret: str | None = None
    turn_server_urls: list[str] = field(default_factory=list)

    def check(self) -> list[str]:
        """Return problems that would stop a call from working."""
        problems = []
        if not self.llm_model:
            problems.append("LLM_MODEL is missing (your provider's fast, cheap model)")
        if self.stt_provider == "deepgram" and not self.deepgram_api_key:
            problems.append("DEEPGRAM_API_KEY is missing (or set STT_PROVIDER=whisper)")
        if not self.llm_api_key and not (self.llm_base_url or "").startswith("http://localhost"):
            problems.append("LLM_API_KEY is missing (or point LLM_BASE_URL at a local Ollama)")
        if self.tts_provider == "elevenlabs" and not (self.elevenlabs_api_key and self.elevenlabs_voice_id):
            problems.append("ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID are needed (or set TTS_PROVIDER=kokoro)")
        return problems


def llm_extra_params(s: Settings) -> dict:
    """Extra request fields for the LLM.

    OpenAI's newer reasoning models (gpt-5.x, gpt-6) refuse function tools on
    /v1/chat/completions unless reasoning_effort is "none". A voice persona
    wants fast answers anyway, so "auto" sends "none" to those models.
    """
    effort = s.llm_reasoning_effort
    if effort in ("", "off"):
        return {}
    if effort == "auto":
        is_openai = not s.llm_base_url or "api.openai.com" in s.llm_base_url
        if is_openai and re.match(r"^gpt-(5\.\d|6)", s.llm_model):
            return {"reasoning_effort": "none"}
        return {}
    return {"reasoning_effort": effort}


def load_settings() -> Settings:
    load_dotenv(ROOT / ".env")
    ice = json.loads(os.getenv("ICE_SERVERS", '[{"urls": "stun:stun.l.google.com:19302"}]'))
    return Settings(
        personas_dir=Path(os.getenv("PERSONAS_DIR", ROOT / "personas")),
        inbox_dir=Path(os.getenv("INBOX_DIR", ROOT / "data" / "inbox")),
        embed_dir=Path(os.getenv("EMBED_DIR", ROOT / "embed" / "dist")),
        avatars_dir=Path(os.getenv("AVATARS_DIR", ROOT / "avatars")),
        stt_provider=os.getenv("STT_PROVIDER", "deepgram"),
        tts_provider=os.getenv("TTS_PROVIDER", "kokoro"),
        llm_base_url=os.getenv("LLM_BASE_URL") or None,
        llm_model=os.getenv("LLM_MODEL", ""),
        llm_reasoning_effort=os.getenv("LLM_REASONING_EFFORT", "auto").strip().lower(),
        deepgram_api_key=os.getenv("DEEPGRAM_API_KEY"),
        llm_api_key=os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY"),
        elevenlabs_api_key=os.getenv("ELEVENLABS_API_KEY"),
        elevenlabs_voice_id=os.getenv("ELEVENLABS_VOICE_ID"),
        elevenlabs_model=os.getenv("ELEVENLABS_MODEL", "eleven_flash_v2_5"),
        kokoro_voice=os.getenv("KOKORO_VOICE", "am_michael"),
        ice_servers=ice,
        dev_origins=_list("DEV_ORIGINS") or ["http://localhost:4173", "http://127.0.0.1:4173", "http://localhost:7860", "http://127.0.0.1:7860"],
        max_sessions=int(os.getenv("MAX_SESSIONS", "4")),
        turn_urls=_list("TURN_URLS"),
        turn_server_urls=_list("TURN_SERVER_URLS"),
        turn_shared_secret=os.getenv("TURN_SHARED_SECRET") or None,
    )
