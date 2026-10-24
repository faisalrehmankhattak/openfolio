import io
from dataclasses import replace

import pytest

from openfolio_worker.cloud import auth
from openfolio_worker.config import ConfigError, load_settings

from conftest import ADMIN_HASH, SESSION_SECRET

CLOUD_ENV = {
    "CLOUD_MODE": "1",
    "SESSION_SECRET": SESSION_SECRET,
    "ADMIN_PASSWORD_HASH": ADMIN_HASH,
    "PUBLIC_URL": "https://openfolio.up.railway.app",
}


@pytest.fixture
def cloud_env(monkeypatch):
    for key, value in CLOUD_ENV.items():
        monkeypatch.setenv(key, value)
    return monkeypatch


def test_cloud_mode_is_off_by_default():
    assert load_settings().cloud is None


def test_cloud_mode_settings(cloud_env):
    cloud = load_settings().cloud
    assert cloud is not None
    assert cloud.public_url == "https://openfolio.up.railway.app"
    assert cloud.secure
    assert cloud.smtp is None
    assert SESSION_SECRET not in repr(cloud)  # secrets stay out of logs and tracebacks


@pytest.mark.parametrize("name", ["SESSION_SECRET", "ADMIN_PASSWORD_HASH", "PUBLIC_URL"])
def test_missing_cloud_variable_is_named(cloud_env, name):
    cloud_env.delenv(name)
    with pytest.raises(ConfigError, match=name):
        load_settings()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("SESSION_SECRET", "too-short"),
        ("ADMIN_PASSWORD_HASH", "plain-text-password"),
        ("ADMIN_PASSWORD_HASH", "scrypt$3$8$1$c2FsdHNhbHQ$aGFzaGhhc2hoYXNoaGFzaA"),
        ("PUBLIC_URL", "http://openfolio.example.com"),
        ("PUBLIC_URL", "https://openfolio.example.com/app"),
        ("PUBLIC_URL", "ftp://openfolio.example.com"),
        ("TURNSTILE_SITE_KEY", "only-one-of-the-pair"),
        ("SMTP_HOST", "smtp.example.com"),  # without SMTP_FROM or SMTP_USER
        ("NOTIFY_EMAIL", "not-an-email"),
    ],
)
def test_invalid_cloud_values_are_named(cloud_env, name, value):
    cloud_env.setenv(name, value)
    if name == "NOTIFY_EMAIL":
        cloud_env.setenv("SMTP_HOST", "smtp.example.com")
        cloud_env.setenv("SMTP_FROM", "owner@example.com")
    with pytest.raises(ConfigError, match=name):
        load_settings()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("http://localhost:7872", "http://localhost:7872"),
        ("http://127.0.0.1:7872/", "http://127.0.0.1:7872"),
        ("https://Openfolio.example.com/", "https://Openfolio.example.com"),
    ],
)
def test_public_url_forms(cloud_env, raw, expected):
    cloud_env.setenv("PUBLIC_URL", raw)
    assert load_settings().cloud.public_url == expected


def test_smtp_settings(cloud_env):
    for key, value in {
        "SMTP_HOST": "smtp.gmail.com",
        "SMTP_USER": "owner@example.com",
        "SMTP_PASSWORD": "app-password",
        "NOTIFY_EMAIL": "owner@example.com",
    }.items():
        cloud_env.setenv(key, value)
    smtp = load_settings().cloud.smtp
    assert (smtp.host, smtp.port, smtp.sender, smtp.notify_email) == (
        "smtp.gmail.com",
        587,
        "owner@example.com",
        "owner@example.com",
    )
    assert "app-password" not in repr(smtp)


@pytest.mark.parametrize("missing", ["CLOUDFLARE_TURN_KEY_ID", "CLOUDFLARE_TURN_API_TOKEN"])
def test_cloudflare_turn_needs_both_variables(monkeypatch, missing):
    monkeypatch.setenv("TURN_PROVIDER", "cloudflare")
    monkeypatch.setenv("CLOUDFLARE_TURN_KEY_ID", "abc123")
    monkeypatch.setenv("CLOUDFLARE_TURN_API_TOKEN", "token")
    monkeypatch.delenv(missing)
    with pytest.raises(ConfigError, match=missing):
        load_settings()


def test_data_dir_moves_the_inbox(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    s = load_settings()
    assert s.data_dir == tmp_path
    assert s.inbox_dir == tmp_path / "inbox"


def test_admin_hash_cli(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("a long enough password\n"))
    auth.main()
    printed = capsys.readouterr().out.strip()
    assert printed.startswith("scrypt$32768$8$1$")
    assert auth.verify_password("a long enough password", printed)
    assert not auth.verify_password("a long enough passwore", printed)


def test_admin_hash_cli_rejects_short_passwords(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("short\n"))
    with pytest.raises(SystemExit):
        auth.main()


def test_cloud_settings_are_frozen(cloud_settings):
    with pytest.raises(AttributeError):
        cloud_settings.cloud.public_url = "https://evil.example"  # type: ignore[misc]
    assert replace(cloud_settings, cloud=None).cloud is None
