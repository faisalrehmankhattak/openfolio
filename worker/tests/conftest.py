import os
from dataclasses import replace
from pathlib import Path

import pytest

# Tests never read the developer's .env and never call real providers.
os.environ["OPENFOLIO_ENV_FILE"] = os.devnull
os.environ["OPENFOLIO_SKIP_CHECKS"] = "1"
for key in ("LLM_API_KEY", "OPENAI_API_KEY", "DEEPGRAM_API_KEY", "LLM_MODEL", "LLM_BASE_URL", "TRUST_PROXY"):
    os.environ.pop(key, None)

from openfolio_worker.config import Settings, load_settings  # noqa: E402
from openfolio_worker.persona import Persona, load_personas  # noqa: E402

PERSONAS = Path(__file__).resolve().parents[2] / "personas"
ORIGIN = {"origin": "https://faisalrehmanktk.com"}


@pytest.fixture
def settings() -> Settings:
    """A fully configured server that never reaches a provider."""
    return replace(load_settings(), deepgram_api_key="x", llm_api_key="x", llm_model="m")


@pytest.fixture
def persona() -> Persona:
    return load_personas(PERSONAS)["faisal"]
