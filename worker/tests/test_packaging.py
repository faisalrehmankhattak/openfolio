import base64
import hashlib
import hmac
import time
from dataclasses import replace

from fastapi.testclient import TestClient

from openfolio_worker.config import load_settings
from openfolio_worker.ice import browser_ice_servers
from openfolio_worker.server import create_app


def test_unconfigured_readiness_is_not_liveness():
    settings = replace(load_settings(), llm_model="", llm_api_key=None)
    client = TestClient(create_app(settings))
    assert client.get("/livez").status_code == 200
    response = client.get("/healthz")
    assert response.status_code == 503
    assert response.json()["ok"] is False


def test_static_worker_credentials_never_reach_browser():
    settings = replace(load_settings(), ice_servers=[
        {"urls": ["stun:stun.example:3478", "turn:turn.example:3478"],
         "username": "private", "credential": "never-publish"},
    ], turn_urls=[], turn_shared_secret=None)
    client = TestClient(create_app(settings))
    response = client.get("/v1/personas/faisal/ice-servers")
    assert response.status_code == 200
    assert response.json() == {"iceServers": [{"urls": ["stun:stun.example:3478"]}]}
    assert response.headers["cache-control"] == "no-store"
    assert "never-publish" not in response.text


def test_turn_credentials_are_expiring_valid_and_unique():
    settings = replace(load_settings(), ice_servers=[],
                       turn_urls=["turn:turn.example:3478"], turn_shared_secret="test-secret")
    one = browser_ice_servers(settings)[0]
    two = browser_ice_servers(settings)[0]
    expires = int(one["username"].split(":")[0])
    assert 3590 <= expires - int(time.time()) <= 3600
    expected = base64.b64encode(hmac.new(b"test-secret", one["username"].encode(), hashlib.sha1).digest()).decode()
    assert one["credential"] == expected
    assert one["username"] != two["username"]
    assert "test-secret" not in str(one)


def test_ice_endpoint_rejects_foreign_origin():
    client = TestClient(create_app(load_settings()))
    assert client.get("/v1/personas/faisal/ice-servers",
                      headers={"origin": "https://evil.example"}).status_code == 403


def test_explicit_runtime_paths(monkeypatch, tmp_path):
    for name in ("PERSONAS_DIR", "INBOX_DIR", "EMBED_DIR", "AVATARS_DIR"):
        monkeypatch.setenv(name, str(tmp_path / name.lower()))
    settings = load_settings()
    assert settings.personas_dir == tmp_path / "personas_dir"
    assert settings.inbox_dir == tmp_path / "inbox_dir"
    assert settings.embed_dir == tmp_path / "embed_dir"
    assert settings.avatars_dir == tmp_path / "avatars_dir"
