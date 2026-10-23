"""Browser ICE configuration. Never publish the worker's static TURN credentials."""
from __future__ import annotations

import base64
import hashlib
import hmac
import time
import uuid

from .config import Settings


def browser_ice_servers(settings: Settings) -> list[dict]:
    servers = []
    for server in settings.ice_servers:
        urls = server.get("urls", [])
        urls = [urls] if isinstance(urls, str) else urls
        stun = [url for url in urls if url.startswith(("stun:", "stuns:"))]
        if stun:
            servers.append({"urls": stun})
    if settings.turn_urls and settings.turn_shared_secret:
        # coturn's TURN REST convention: expire after one hour, unique per request.
        username = f"{int(time.time()) + 3600}:{uuid.uuid4().hex}"
        credential = base64.b64encode(hmac.new(
            settings.turn_shared_secret.encode(), username.encode(), hashlib.sha1
        ).digest()).decode()
        servers.append({"urls": settings.turn_urls, "username": username, "credential": credential})
    return servers
