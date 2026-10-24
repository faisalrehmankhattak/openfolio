from dataclasses import replace

import httpx
import pytest
from fastapi.testclient import TestClient

from openfolio_worker.config import CloudSettings
from openfolio_worker.server import create_app

from cloud_helpers import VALID, client_for, rows, submit

CLOUD_PATHS = ["/privacy", "/terms", "/admin", "/admin/login", "/cloud/thanks", "/invite/" + "a" * 43]


def test_cloud_mode_off_keeps_the_demo_and_hides_cloud_routes(settings):
    client = TestClient(create_app(settings))
    r = client.get("/")
    assert r.status_code == 200
    assert "Any portfolio, now with a face and a voice." in r.text
    for path in CLOUD_PATHS:
        assert client.get(path).status_code == 404, path
    assert client.post("/cloud/requests", data=VALID).status_code == 404
    assert client.get("/cloud/static/cloud.css").status_code == 404
    assert not (settings.data_dir / "cloud.db").exists()


def test_landing_page(cloud_settings):
    r = client_for(cloud_settings).get("/")
    assert r.status_code == 200
    html = r.text
    assert "Your portfolio, <span" in html
    assert '<script src="/embed/embed.js" data-persona="faisal"' in html
    assert 'action="/cloud/requests#request"' in html
    assert 'href="/privacy"' in html
    assert 'href="/terms"' in html
    assert "github.com/faisalrehmankhattak/openfolio" in html
    assert "cf-turnstile" not in html
    assert "challenges.cloudflare.com" not in html
    assert "<script>" not in html  # no inline scripts: the CSP allows none
    assert client_for(cloud_settings).get("/cloud/static/cloud.css").status_code == 200


def test_security_headers(cloud_settings):
    client = client_for(cloud_settings)
    landing = client.get("/")
    csp = landing.headers["content-security-policy"]
    assert "frame-ancestors 'none'" in csp
    assert "script-src 'self';" in csp
    assert "object-src 'none'" in csp
    assert "unsafe-eval" not in csp
    assert landing.headers["x-frame-options"] == "DENY"
    assert landing.headers["x-content-type-options"] == "nosniff"
    assert landing.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "strict-transport-security" not in landing.headers  # http://127.0.0.1 in tests
    privacy = client.get("/privacy").headers["content-security-policy"]
    assert "'unsafe-inline'" not in privacy
    assert "blob:" not in privacy


def test_hsts_when_public_url_is_https(cloud_settings):
    s = replace(cloud_settings, cloud=replace(cloud_settings.cloud, public_url="https://of.example.com"))
    assert client_for(s).get("/privacy").headers["strict-transport-security"] == "max-age=31536000"


def test_valid_request_is_stored(cloud_settings):
    r = submit(client_for(cloud_settings), portfolio_url="jane.dev")
    assert r.status_code == 303
    assert r.headers["location"] == "/cloud/thanks"
    ((name, email, url, about, reason, status, ip_hash),) = rows(
        cloud_settings, "SELECT name, email, portfolio_url, about, reason, status, ip_hash FROM access_requests"
    )
    assert (name, email, url, about, status) == (
        "Jane Doe",
        "jane@example.com",
        "https://jane.dev",
        "Product designer",
        "pending",
    )
    assert reason == VALID["reason"]
    assert len(ip_hash) == 32
    raw = (cloud_settings.data_dir / "cloud.db").read_bytes() + (cloud_settings.data_dir / "cloud.db-wal").read_bytes()
    assert b"testclient" not in raw  # the client address itself is never stored
    assert "We read every request ourselves" in client_for(cloud_settings).get("/cloud/thanks").text


def test_honeypot_pretends_and_stores_nothing(cloud_settings):
    r = submit(client_for(cloud_settings), website="https://spam.example")
    assert (r.status_code, r.headers["location"]) == (303, "/cloud/thanks")
    assert rows(cloud_settings, "SELECT COUNT(*) FROM access_requests") == [(0,)]
    assert rows(cloud_settings, "SELECT COUNT(*) FROM audit_log") == [(0,)]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("email", "not-an-email", "valid email address"),
        ("email", "a@b", "valid email address"),
        ("portfolio_url", "javascript:alert(1)", "starting with https://"),
        ("portfolio_url", "ftp://files.example.com", "starting with https://"),
        ("portfolio_url", "https://localhost", "starting with https://"),
        ("name", "", "enter your name"),
        ("name", "x" * 101, "enter your name"),
        ("about", "", "what you do"),
        ("reason", "x" * 501, "under 500 characters"),
        ("consent", "", "privacy notice so we can store"),
    ],
)
def test_invalid_input_rerenders_the_form(cloud_settings, field, value, message):
    r = submit(client_for(cloud_settings), **{field: value})
    assert r.status_code == 400
    assert message in r.text
    assert f'id="{field}-error"' in r.text
    assert 'aria-invalid="true"' in r.text
    if field != "name":
        assert 'value="Jane Doe"' in r.text  # the visitor's other answers are kept
    assert rows(cloud_settings, "SELECT COUNT(*) FROM access_requests") == [(0,)]


def test_rerendered_values_are_escaped(cloud_settings):
    r = submit(client_for(cloud_settings), name='"><script>alert(1)</script>', email="bad")
    assert r.status_code == 400
    assert "<script>alert(1)" not in r.text
    assert "&#34;&gt;&lt;script&gt;" in r.text


def test_rate_limit_per_network(cloud_settings):
    client = client_for(cloud_settings)
    for i in range(3):
        assert submit(client, email=f"person{i}@example.com").status_code == 303
    r = submit(client, email="person4@example.com")
    assert r.status_code == 429
    assert "try again in an hour" in r.text
    assert rows(cloud_settings, "SELECT COUNT(*) FROM access_requests") == [(3,)]


def test_duplicate_pending_email_gets_the_same_answer(cloud_settings):
    client = client_for(cloud_settings)
    first, second = submit(client), submit(client, email="JANE@example.com", name="Someone else")
    assert first.status_code == second.status_code == 303
    assert first.headers["location"] == second.headers["location"] == "/cloud/thanks"
    assert rows(cloud_settings, "SELECT COUNT(*) FROM access_requests") == [(1,)]
    assert rows(cloud_settings, "SELECT action FROM audit_log ORDER BY id") == [
        ("request.created",),
        ("request.duplicate",),
    ]


@pytest.mark.parametrize(("success", "stored"), [(True, 1), (False, 0)])
def test_turnstile_is_verified_server_side(cloud_settings, success, stored):
    calls = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"success": success})

    cloud = replace(cloud_settings.cloud, turnstile_site_key="site-key", turnstile_secret_key="secret-key")
    client = client_for(replace(cloud_settings, cloud=cloud), transport=httpx.MockTransport(handle))
    page = client.get("/")
    assert 'data-sitekey="site-key"' in page.text
    assert "https://challenges.cloudflare.com" in page.headers["content-security-policy"]
    assert "secret-key" not in page.text

    r = submit(client, **{"cf-turnstile-response": "browser-token"})
    assert r.status_code == (303 if success else 400)
    (call,) = calls
    assert str(call.url) == "https://challenges.cloudflare.com/turnstile/v0/siteverify"
    body = call.content.decode()
    assert "secret=secret-key" in body
    assert "response=browser-token" in body
    assert rows(cloud_settings, "SELECT COUNT(*) FROM access_requests") == [(stored,)]


def test_turnstile_is_not_called_without_a_secret(cloud_settings):
    calls = []
    transport = httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(500))
    assert submit(client_for(cloud_settings, transport=transport)).status_code == 303
    assert calls == []


def test_form_body_limits(cloud_settings):
    client = client_for(cloud_settings)
    assert client.post("/cloud/requests", json=VALID).status_code == 415
    big = client.post(
        "/cloud/requests",
        content=b"name=" + b"x" * 20_000,
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert big.status_code == 413


def test_privacy_and_terms(cloud_settings, persona):
    client = client_for(cloud_settings)
    privacy = client.get("/privacy").text
    for text in ("Beta.", "hash", "90 days", "30 days", "README", persona.email):
        assert text in privacy
    terms = client.get("/terms").text
    assert "Beta." in terms
    assert persona.email in terms


def test_public_url_may_run_every_persona(cloud_settings):
    origin = {"origin": cloud_settings.cloud.public_url}
    client = client_for(cloud_settings)
    assert client.get("/v1/personas/faisal/ice-servers", headers=origin).status_code == 200
    preflight = client.options("/v1/personas/faisal/offer", headers={**origin, "access-control-request-method": "POST"})
    assert preflight.headers["access-control-allow-origin"] == origin["origin"]
    other = {"origin": "https://evil.example"}
    assert client.get("/v1/personas/faisal/ice-servers", headers=other).status_code == 403


def test_not_found_pages(cloud_settings):
    client = client_for(cloud_settings)
    page = client.get("/missing", headers={"accept": "text/html"})
    assert page.status_code == 404
    assert "Page not found" in page.text
    api = client.get("/v1/personas/nobody", headers={"accept": "text/html"})
    assert api.status_code == 404
    assert api.json() == {"detail": "Unknown persona"}


def test_demo_section_hidden_without_the_demo_persona(cloud_settings):
    s = replace(cloud_settings, cloud=CloudSettings(**{**cloud_settings.cloud.__dict__, "demo_persona": "nobody"}))
    html = client_for(s).get("/").text
    assert 'src="/embed/embed.js"' not in html
    assert "data-demo" not in html
