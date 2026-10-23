import base64
import hashlib
import hmac
import time
from dataclasses import replace

from fastapi.testclient import TestClient

from openfolio_worker.ice import browser_ice_servers
from openfolio_worker.server import create_app


def test_static_worker_credentials_never_reach_browser(settings):
    s = replace(
        settings,
        ice_servers=[
            {
                "urls": ["stun:stun.example:3478", "turn:turn.example:3478"],
                "username": "private",
                "credential": "never-publish",
            }
        ],
        turn_urls=[],
        turn_shared_secret=None,
    )
    r = TestClient(create_app(s)).get("/v1/personas/faisal/ice-servers")
    assert r.status_code == 200
    assert r.json() == {"iceServers": [{"urls": ["stun:stun.example:3478"]}]}
    assert r.headers["cache-control"] == "no-store"
    assert "never-publish" not in r.text


def test_turn_credentials_are_expiring_valid_and_unique(settings):
    s = replace(settings, ice_servers=[], turn_urls=["turn:turn.example:3478"], turn_shared_secret="test-secret")
    one, two = browser_ice_servers(s)[0], browser_ice_servers(s)[0]
    expires = int(one["username"].split(":")[0])
    assert 3590 <= expires - int(time.time()) <= 3600
    expected = base64.b64encode(hmac.new(b"test-secret", one["username"].encode(), hashlib.sha1).digest()).decode()
    assert one["credential"] == expected
    assert one["username"] != two["username"]
    assert "test-secret" not in str(one)
