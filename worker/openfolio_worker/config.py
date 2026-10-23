"""Server settings, read once from the environment (and `.env` in development)."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(os.getenv("OPENFOLIO_ROOT", Path(__file__).resolve().parents[2]))

DEFAULT_ICE = '[{"urls": "stun:stun.l.google.com:19302"}]'
DEFAULT_DEV_ORIGINS = (
    "http://localhost:4173",
    "http://127.0.0.1:4173",
    "http://localhost:7860",
    "http://127.0.0.1:7860",
)
LOCAL_LLM_HOSTS = ("localhost", "127.0.0.1", "host.docker.internal", "ollama")
STT_PROVIDERS = ("deepgram", "whisper")
TTS_PROVIDERS = ("kokoro", "elevenlabs")


class ConfigError(ValueError):
    """An environment variable has a value the server cannot use."""


def _list(name: str) -> list[str]:
    return [v.strip() for v in os.getenv(name, "").split(",") if v.strip()]


def _int(name: str, default: int, minimum: int = 0) -> int:
    raw = os.getenv(name, "").strip() or str(default)
    try:
        value = int(raw)
    except ValueError as e:
        raise ConfigError(f"{name} must be a whole number, got {raw!r}") from e
    if value < minimum:
        raise ConfigError(f"{name} must be at least {minimum}, got {value}")
    return value


def _ice_servers() -> list[dict[str, Any]]:
    raw = os.getenv("ICE_SERVERS") or DEFAULT_ICE
    try:
        servers = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ConfigError(f"ICE_SERVERS is not valid JSON: {e}") from e
    if not isinstance(servers, list) or not all(isinstance(s, dict) and "urls" in s for s in servers):
        raise ConfigError('ICE_SERVERS must be a JSON list of {"urls": ...} objects')
    return servers


def _choice(name: str, default: str, allowed: tuple[str, ...]) -> str:
    value = os.getenv(name, default).strip().lower() or default
    if value not in allowed:
        raise ConfigError(f"{name} must be one of {', '.join(allowed)}, got {value!r}")
    return value


@dataclass(frozen=True)
class Settings:
    personas_dir: Path
    inbox_dir: Path
    embed_dir: Path
    avatars_dir: Path

    stt_provider: str
    tts_provider: str
    llm_base_url: str | None
    llm_model: str
    llm_reasoning_effort: str  # "auto", "off", or a provider value such as "none" / "low"

    deepgram_api_key: str | None
    llm_api_key: str | None
    elevenlabs_api_key: str | None
    elevenlabs_voice_id: str | None
    elevenlabs_model: str
    kokoro_voice: str

    ice_servers: list[dict[str, Any]] = field(default_factory=list)
    dev_origins: list[str] = field(default_factory=list)
    max_sessions: int = 4
    calls_per_ip: int = 6
    trust_proxy: bool = False
    turn_urls: list[str] = field(default_factory=list)
    turn_shared_secret: str | None = None
    turn_server_urls: list[str] = field(default_factory=list)

    @property
    def llm_is_local(self) -> bool:
        url = self.llm_base_url or ""
        return any(re.match(rf"^https?://{re.escape(host)}(:|/|$)", url) for host in LOCAL_LLM_HOSTS)

    def check(self) -> list[str]:
        """Return problems that would stop a call from working."""
        problems = []
        if not self.llm_model:
            problems.append("LLM_MODEL is missing (your provider's fast, cheap model)")
        if self.stt_provider == "deepgram" and not self.deepgram_api_key:
            problems.append("DEEPGRAM_API_KEY is missing (or set STT_PROVIDER=whisper)")
        if not self.llm_api_key and not self.llm_is_local:
            problems.append("LLM_API_KEY is missing (or point LLM_BASE_URL at a local Ollama)")
        if self.tts_provider == "elevenlabs" and not (self.elevenlabs_api_key and self.elevenlabs_voice_id):
            problems.append("ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID are needed (or set TTS_PROVIDER=kokoro)")
        return problems


def llm_extra_params(s: Settings) -> dict[str, str]:
    """Extra request fields for the LLM.

    OpenAI gpt-5.x and gpt-6 models refuse function tools on chat completions
    unless `reasoning_effort` is "none", so "auto" sends that to those models.
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
    load_dotenv(os.getenv("OPENFOLIO_ENV_FILE") or ROOT / ".env")
    return Settings(
        personas_dir=Path(os.getenv("PERSONAS_DIR", ROOT / "personas")),
        inbox_dir=Path(os.getenv("INBOX_DIR", ROOT / "data" / "inbox")),
        embed_dir=Path(os.getenv("EMBED_DIR", ROOT / "embed" / "dist")),
        avatars_dir=Path(os.getenv("AVATARS_DIR", ROOT / "avatars")),
        stt_provider=_choice("STT_PROVIDER", "deepgram", STT_PROVIDERS),
        tts_provider=_choice("TTS_PROVIDER", "kokoro", TTS_PROVIDERS),
        llm_base_url=os.getenv("LLM_BASE_URL") or None,
        llm_model=os.getenv("LLM_MODEL", "").strip(),
        llm_reasoning_effort=os.getenv("LLM_REASONING_EFFORT", "auto").strip().lower(),
        deepgram_api_key=os.getenv("DEEPGRAM_API_KEY") or None,
        llm_api_key=os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or None,
        elevenlabs_api_key=os.getenv("ELEVENLABS_API_KEY") or None,
        elevenlabs_voice_id=os.getenv("ELEVENLABS_VOICE_ID") or None,
        elevenlabs_model=os.getenv("ELEVENLABS_MODEL", "eleven_flash_v2_5"),
        kokoro_voice=os.getenv("KOKORO_VOICE", "am_michael"),
        ice_servers=_ice_servers(),
        dev_origins=_list("DEV_ORIGINS") or list(DEFAULT_DEV_ORIGINS),
        max_sessions=_int("MAX_SESSIONS", 4, minimum=1),
        calls_per_ip=_int("CALLS_PER_IP", 6),
        trust_proxy=os.getenv("TRUST_PROXY", "").strip().lower() in ("1", "true", "yes"),
        turn_urls=_list("TURN_URLS"),
        turn_server_urls=_list("TURN_SERVER_URLS"),
        turn_shared_secret=os.getenv("TURN_SHARED_SECRET") or None,
    )
