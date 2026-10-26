from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from openfolio_worker.config import load_settings
from openfolio_worker.server import RateLimiter, client_ip, create_app

from conftest import ORIGIN

OFFER = {"sdp": "x", "type": "offer"}


@pytest.fixture
def client(settings):
    return TestClient(create_app(settings))


def test_public_profile(client):
    r = client.get("/v1/personas/demo")
    assert r.status_code == 200
    assert r.json()["first_name"] == "Avery"


def test_unknown_persona_404(client):
    assert client.get("/v1/personas/nobody").status_code == 404


def test_security_headers(client):
    r = client.get("/livez")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "strict-origin-when-cross-origin"


def test_api_docs_are_not_exposed(client):
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_foreign_origin_blocked(client):
    r = client.post("/v1/personas/demo/offer", json=OFFER, headers={"origin": "https://evil.example"})
    assert r.status_code == 403
    assert client.get("/v1/personas/demo/ice-servers", headers={"origin": "https://evil.example"}).status_code == 403


def test_cors_allows_persona_origin(client):
    r = client.options("/v1/personas/demo/offer", headers={**ORIGIN, "access-control-request-method": "POST"})
    assert r.headers["access-control-allow-origin"] == ORIGIN["origin"]


def test_unconfigured_server_refuses_calls():
    c = TestClient(create_app(load_settings()))
    assert c.post("/v1/personas/demo/offer", json=OFFER, headers=ORIGIN).status_code == 503
    # The widget fetches ICE servers first, so it can explain the refusal before WebRTC starts.
    assert c.get("/v1/personas/demo/ice-servers", headers=ORIGIN).status_code == 503


def test_rate_limit_per_ip(settings):
    c = TestClient(create_app(replace(settings, calls_per_ip=0)))
    assert c.post("/v1/personas/demo/offer", json=OFFER, headers=ORIGIN).status_code == 429


@pytest.mark.parametrize(
    ("trust", "expected"),
    [(True, "9.9.9.9"), (False, "10.0.0.1")],
)
def test_forwarded_ip_uses_the_proxy_entry(trust, expected):
    request = SimpleNamespace(headers={"x-forwarded-for": "1.1.1.1, 9.9.9.9"}, client=SimpleNamespace(host="10.0.0.1"))
    assert client_ip(request, trust_proxy=trust) == expected


@pytest.mark.parametrize("body", [b"{}", b"not json", b'{"sdp": "x", "type": "evil"}'])
def test_malformed_offer_is_400(client, body):
    r = client.post("/v1/personas/demo/offer", content=body, headers={**ORIGIN, "content-type": "application/json"})
    assert r.status_code == 400


def test_oversized_offer_rejected_even_when_streamed(client):
    def chunks():
        yield b"{" + b" " * 70_000 + b"}"

    r = client.post("/v1/personas/demo/offer", content=chunks(), headers={**ORIGIN, "content-type": "application/json"})
    assert r.status_code == 413


def test_ice_candidates_for_unknown_connection_404(client):
    r = client.patch("/v1/personas/demo/offer", json={"pc_id": "nope", "candidates": []}, headers=ORIGIN)
    assert r.status_code == 404


def test_readiness_is_not_liveness():
    c = TestClient(create_app(load_settings()))
    assert c.get("/livez").status_code == 200
    r = c.get("/healthz")
    assert r.status_code == 503
    assert r.json()["ok"] is False


def test_rate_limiter_window_and_pruning():
    now = [0.0]
    limiter = RateLimiter(limit=2, window=10, clock=lambda: now[0])
    assert limiter.allow("a")
    assert limiter.allow("a")
    assert not limiter.allow("a")
    now[0] = 11
    assert limiter.allow("a")
    limiter._prune(now=100)
    assert "a" not in limiter._hits
