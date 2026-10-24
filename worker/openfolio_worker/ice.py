"""ICE (STUN/TURN) configuration for browsers and for the worker side of each call.

Two TURN providers:
- coturn: TURN REST credentials signed with TURN_SHARED_SECRET (coturn "use-auth-secret").
- cloudflare: Cloudflare Realtime TURN. Needed on hosts without inbound UDP (such as Railway),
  where the server's own media has to go through the relay as well.
Static worker TURN credentials in ICE_SERVERS and the Cloudflare API token never reach a browser.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import time
import uuid
from collections.abc import Callable
from typing import Any

import httpx
from loguru import logger

from .config import Settings

TURN_CREDENTIAL_TTL = 3600
CLOUDFLARE_URL = "https://rtc.live.cloudflare.com/v1/turn/keys/{key_id}/credentials/generate-ice-servers"
CLOUDFLARE_TIMEOUT_SECONDS = 5
# Credentials live an hour. Reusing a set for at most five minutes keeps page views off the API,
# and every call (max_session_seconds is at most 30 minutes) still ends long before they expire.
CLOUDFLARE_CACHE_SECONDS = 300
CLOUDFLARE_RETRY_SECONDS = 30  # after a failure, don't make every visitor wait for another timeout
_PORT = re.compile(r"^(?:stuns?|turns?):(?:\[[^\]]*\]|[^:?]*):(\d+)")


def turn_credentials(secret: str, ttl: int = TURN_CREDENTIAL_TTL) -> tuple[str, str]:
    """Short-lived TURN REST credentials (coturn "use-auth-secret"), unique per request."""
    username = f"{int(time.time()) + ttl}:{uuid.uuid4().hex}"
    digest = hmac.new(secret.encode(), username.encode(), hashlib.sha1).digest()
    return username, base64.b64encode(digest).decode()


def _urls(server: dict[str, Any]) -> list[str]:
    urls = server.get("urls", [])
    return [urls] if isinstance(urls, str) else [u for u in urls if isinstance(u, str)]


def stun_servers(settings: Settings) -> list[dict[str, Any]]:
    """Only the STUN entries of ICE_SERVERS: these never carry credentials."""
    servers = []
    for server in settings.ice_servers:
        if stun := [url for url in _urls(server) if url.startswith(("stun:", "stuns:"))]:
            servers.append({"urls": stun})
    return servers


def browser_ice_servers(settings: Settings) -> list[dict[str, Any]]:
    """STUN plus coturn REST credentials when configured."""
    servers = stun_servers(settings)
    if settings.turn_urls and settings.turn_shared_secret:
        username, credential = turn_credentials(settings.turn_shared_secret)
        servers.append({"urls": settings.turn_urls, "username": username, "credential": credential})
    return servers


def without_port_53(servers: Any) -> list[dict[str, Any]]:
    """Keep well-formed entries and drop URLs on port 53, which browsers block."""
    if isinstance(servers, dict):
        servers = [servers]
    if not isinstance(servers, list):
        return []
    kept = []
    for server in servers:
        if not isinstance(server, dict):
            continue
        urls = [u for u in _urls(server) if (m := _PORT.match(u)) is None or m.group(1) != "53"]
        if not urls:
            continue
        entry: dict[str, Any] = {"urls": urls}
        for key in ("username", "credential"):
            if isinstance(server.get(key), str):
                entry[key] = server[key]
        kept.append(entry)
    return kept


class IceProvider:
    """ICE servers for browsers (GET .../ice-servers) and for the worker side of each new call."""

    def __init__(
        self,
        settings: Settings,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings
        self._transport = transport
        self._clock = clock
        self._cached: list[dict[str, Any]] = []
        self._cached_until = 0.0

    @property
    def cloudflare(self) -> bool:
        return self.settings.turn_provider == "cloudflare"

    async def browser(self) -> list[dict[str, Any]]:
        if not self.cloudflare:
            return browser_ice_servers(self.settings)
        # STUN-only fallback: most networks still connect, and the error is in the log.
        return await self._cloudflare_servers() or stun_servers(self.settings)

    async def worker(self) -> list[dict[str, Any]]:
        if self.cloudflare:
            relay = [s for s in await self._cloudflare_servers() if "credential" in s]
        else:
            relay = [s for s in browser_ice_servers(self.settings) if "credential" in s]
            if self.settings.turn_server_urls:
                relay = [{**s, "urls": self.settings.turn_server_urls} for s in relay]
        return self.settings.ice_servers + relay

    async def _cloudflare_servers(self) -> list[dict[str, Any]]:
        now = self._clock()
        if now < self._cached_until:
            return self._cached
        servers = await self._fetch_cloudflare()
        self._cached = servers
        self._cached_until = now + (CLOUDFLARE_CACHE_SECONDS if servers else CLOUDFLARE_RETRY_SECONDS)
        return servers

    async def _fetch_cloudflare(self) -> list[dict[str, Any]]:
        url = CLOUDFLARE_URL.format(key_id=self.settings.cloudflare_turn_key_id)
        headers = {"Authorization": f"Bearer {self.settings.cloudflare_turn_api_token}"}
        try:
            async with httpx.AsyncClient(timeout=CLOUDFLARE_TIMEOUT_SECONDS, transport=self._transport) as client:
                r = await client.post(url, headers=headers, json={"ttl": TURN_CREDENTIAL_TTL})
            if r.status_code not in (200, 201):
                # Status only: the body or the request could echo the token.
                logger.error(f"Cloudflare TURN returned HTTP {r.status_code}; calls fall back to STUN only")
                return []
            servers = without_port_53(r.json().get("iceServers"))
        except (httpx.HTTPError, ValueError, AttributeError) as e:
            logger.error(f"Cloudflare TURN request failed ({type(e).__name__}); calls fall back to STUN only")
            return []
        if not any("credential" in s for s in servers):
            logger.error("Cloudflare TURN returned no relay servers; calls fall back to STUN only")
            return []
        return servers
