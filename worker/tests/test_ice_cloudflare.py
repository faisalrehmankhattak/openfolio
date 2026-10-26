import asyncio
import json
import re
from dataclasses import replace

import httpx
import pytest
from fastapi.testclient import TestClient
from loguru import logger

from openfolio_worker.ice import IceProvider, without_port_53
from openfolio_worker.server import create_app

from conftest import ORIGIN

TOKEN = "cf-api-token-never-leaves-the-server"
STUN = {"urls": "stun:stun.l.google.com:19302"}
CLOUDFLARE = {
    "iceServers": [
        {"urls": ["stun:stun.cloudflare.com:3478", "stun:stun.cloudflare.com:53"]},
        {
            "urls": [
                "turn:turn.cloudflare.com:3478?transport=udp",
                "turn:turn.cloudflare.com:53?transport=udp",
                "turn:turn.cloudflare.com:3478?transport=tcp",
                "turns:turn.cloudflare.com:5349?transport=tcp",
                "turns:turn.cloudflare.com:443?transport=tcp",
            ],
            "username": "cf-user",
            "credential": "cf-credential",
        },
    ]
}


class FakeCloudflare:
    def __init__(self, status: int = 201, body: object = CLOUDFLARE, error: Exception | None = None) -> None:
        self.status, self.body, self.error = status, body, error
        self.requests: list[httpx.Request] = []
        self.transport = httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.error:
            raise self.error
        return httpx.Response(self.status, json=self.body)


@pytest.fixture
def cf_settings(settings):
    return replace(
        settings,
        ice_servers=[STUN],
        turn_provider="cloudflare",
        cloudflare_turn_key_id="key123",
        cloudflare_turn_api_token=TOKEN,
    )


@pytest.fixture
def logs():
    lines: list[str] = []
    sink = logger.add(lambda m: lines.append(str(m)), level="DEBUG")
    yield lines
    logger.remove(sink)


def test_browser_gets_cloudflare_servers_without_port_53(cf_settings):
    cf = FakeCloudflare()
    r = TestClient(create_app(cf_settings, transport=cf.transport)).get("/v1/personas/demo/ice-servers", headers=ORIGIN)
    assert r.status_code == 200
    servers = r.json()["iceServers"]
    urls = [u for s in servers for u in s["urls"]]
    assert "turn:turn.cloudflare.com:3478?transport=udp" in urls
    assert not [u for u in urls if re.search(r":53(\?|$)", u)]
    assert "turns:turn.cloudflare.com:5349?transport=tcp" in urls
    assert {"username": "cf-user", "credential": "cf-credential"}.items() <= servers[1].items()
    assert TOKEN not in r.text

    (sent,) = cf.requests
    assert sent.method == "POST"
    assert str(sent.url) == "https://rtc.live.cloudflare.com/v1/turn/keys/key123/credentials/generate-ice-servers"
    assert sent.headers["authorization"] == f"Bearer {TOKEN}"
    assert json.loads(sent.content) == {"ttl": 3600}


def test_credentials_are_cached_for_five_minutes(cf_settings):
    now = [0.0]
    cf = FakeCloudflare()
    ice = IceProvider(cf_settings, cf.transport, clock=lambda: now[0])
    asyncio.run(ice.browser())
    asyncio.run(ice.browser())
    asyncio.run(ice.worker())
    assert len(cf.requests) == 1
    now[0] = 301
    asyncio.run(ice.browser())
    assert len(cf.requests) == 2


def test_worker_side_gets_the_relay(cf_settings):
    ice = IceProvider(cf_settings, FakeCloudflare().transport)
    servers = asyncio.run(ice.worker())
    assert servers[0] == STUN
    assert any(s.get("credential") == "cf-credential" for s in servers)


@pytest.mark.parametrize(
    "cf",
    [
        FakeCloudflare(status=500, body={"errors": [TOKEN]}),
        FakeCloudflare(status=201, body={"iceServers": []}),
        FakeCloudflare(status=201, body=["not", "an", "object"]),
        FakeCloudflare(error=httpx.ConnectTimeout("timed out")),
    ],
)
def test_failure_falls_back_to_stun_only(cf_settings, cf, logs):
    now = [0.0]
    ice = IceProvider(cf_settings, cf.transport, clock=lambda: now[0])
    assert asyncio.run(ice.browser()) == [{"urls": ["stun:stun.l.google.com:19302"]}]
    assert asyncio.run(ice.worker()) == [STUN]
    assert any("STUN only" in line for line in logs)
    assert not any(TOKEN in line for line in logs)
    calls = len(cf.requests)
    asyncio.run(ice.browser())
    assert len(cf.requests) == calls  # a failure is remembered briefly, so visitors don't each wait 5 s
    now[0] = 31
    asyncio.run(ice.browser())
    assert len(cf.requests) == calls + 1


def test_offer_gives_the_worker_cloudflare_relay(cf_settings, monkeypatch):
    seen = []
    monkeypatch.setattr(
        "openfolio_worker.server.SmallWebRTCRequestHandler.update_ice_servers",
        lambda self, servers: seen.append(servers),
    )

    async def answer(self, request, webrtc_connection_callback):
        return {"sdp": "answer", "type": "answer", "pc_id": "pc"}

    monkeypatch.setattr("openfolio_worker.server.SmallWebRTCRequestHandler.handle_web_request", answer)
    client = TestClient(create_app(cf_settings, transport=FakeCloudflare().transport))
    r = client.post("/v1/personas/demo/offer", json={"sdp": "x", "type": "offer"}, headers=ORIGIN)
    assert r.status_code == 200
    (servers,) = seen
    assert any(
        s.credential == "cf-credential" and "turn:turn.cloudflare.com:3478?transport=udp" in s.urls for s in servers
    )


def test_port_53_filter_keeps_other_entries():
    assert without_port_53({"urls": "turn:t.example:53?transport=udp"}) == []
    assert without_port_53([{"urls": ["stun:[2001:db8::1]:53", "stun:[2001:db8::1]:3478"]}]) == [
        {"urls": ["stun:[2001:db8::1]:3478"]}
    ]
    assert without_port_53([{"urls": "turn:t.example:5349", "credential": 5}]) == [{"urls": ["turn:t.example:5349"]}]
