"""Browser ICE configuration. Static worker TURN credentials are never published."""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
import uuid
from typing import Any

from .config import Settings

TURN_CREDENTIAL_TTL = 3600


def turn_credentials(secret: str, ttl: int = TURN_CREDENTIAL_TTL) -> tuple[str, str]:
    """Short-lived TURN REST credentials (coturn `use-auth-secret`), unique per request."""
    username = f"{int(time.time()) + ttl}:{uuid.uuid4().hex}"
    digest = hmac.new(secret.encode(), username.encode(), hashlib.sha1).digest()
    return username, base64.b64encode(digest).decode()


def browser_ice_servers(settings: Settings) -> list[dict[str, Any]]:
    servers: list[dict[str, Any]] = []
    for server in settings.ice_servers:
        urls = server.get("urls", [])
        urls = [urls] if isinstance(urls, str) else urls
        if stun := [url for url in urls if url.startswith(("stun:", "stuns:"))]:
            servers.append({"urls": stun})
    if settings.turn_urls and settings.turn_shared_secret:
        username, credential = turn_credentials(settings.turn_shared_secret)
        servers.append({"urls": settings.turn_urls, "username": username, "credential": credential})
    return servers
