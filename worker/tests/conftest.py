import os
import tempfile
from dataclasses import replace
from pathlib import Path

import pytest

# Tests never read the developer's .env, never call real providers and never write to the repo's data/.
os.environ["OPENFOLIO_ENV_FILE"] = os.devnull
os.environ["OPENFOLIO_SKIP_CHECKS"] = "1"
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="openfolio-test-")
for key in (
    "LLM_API_KEY",
    "OPENAI_API_KEY",
    "DEEPGRAM_API_KEY",
    "LLM_MODEL",
    "LLM_BASE_URL",
    "TRUST_PROXY",
    "INBOX_DIR",
    "CLOUD_MODE",
    "SESSION_SECRET",
    "ADMIN_PASSWORD_HASH",
    "PUBLIC_URL",
    "CLOUD_DEMO_PERSONA",
    "TURNSTILE_SITE_KEY",
    "TURNSTILE_SECRET_KEY",
    "TURN_PROVIDER",
    "CLOUDFLARE_TURN_KEY_ID",
    "CLOUDFLARE_TURN_API_TOKEN",
    "SMTP_HOST",
    "SMTP_PORT",
    "SMTP_USER",
    "SMTP_PASSWORD",
    "SMTP_FROM",
    "NOTIFY_EMAIL",
    "PRODUCT_HUNT_URL",
    "GITHUB_REPO",
):
    os.environ.pop(key, None)

from openfolio_worker.cloud.auth import hash_password  # noqa: E402
from openfolio_worker.config import CloudSettings, Settings, load_settings  # noqa: E402
from openfolio_worker.persona import Persona, load_personas  # noqa: E402

PERSONAS = Path(__file__).resolve().parents[2] / "personas"
ORIGIN = {"origin": "https://example.com"}
CONTACT_EMAIL = "owner@example.org"  # the cloud owner, not the fictional demo persona
PUBLIC_URL = "http://127.0.0.1:7872"
ADMIN_PASSWORD = "correct horse battery staple"
ADMIN_HASH = hash_password(ADMIN_PASSWORD, n=2**10)  # cheap scrypt parameters keep the suite fast
SESSION_SECRET = "test-session-secret-" + "x" * 32


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """A fully configured server that never reaches a provider, with its own usage totals."""
    return replace(load_settings(), deepgram_api_key="x", llm_api_key="x", llm_model="m", data_dir=tmp_path)


@pytest.fixture
def cloud_settings(settings: Settings, tmp_path: Path) -> Settings:
    """CLOUD_MODE on, with a temporary DATA_DIR."""
    cloud = CloudSettings(
        public_url=PUBLIC_URL,
        session_secret=SESSION_SECRET,
        admin_password_hash=ADMIN_HASH,
        contact_email=CONTACT_EMAIL,
    )
    return replace(settings, data_dir=tmp_path, inbox_dir=tmp_path / "inbox", cloud=cloud)


@pytest.fixture(autouse=True)
def _cheap_member_passwords(monkeypatch: pytest.MonkeyPatch) -> None:
    """Members' passwords use cheap scrypt parameters in tests, like the owner's."""

    def cheap(password: str) -> str:
        return hash_password(password, n=2**10)

    monkeypatch.setattr("openfolio_worker.cloud.accounts.hash_password", cheap)
    monkeypatch.setattr("openfolio_worker.cloud.studio_account.hash_password", cheap)


@pytest.fixture
def persona() -> Persona:
    return load_personas(PERSONAS)["demo"]
