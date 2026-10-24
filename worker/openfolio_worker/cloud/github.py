"""The repository's GitHub star count, fetched server-side so the landing page loads nothing from other origins."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

import httpx
from loguru import logger

API_URL = "https://api.github.com/repos/{repo}"
TIMEOUT_SECONDS = 5
CACHE_SECONDS = 3600
RETRY_SECONDS = 600  # after a failure: sooner than an hour, but never on every page view


def compact_count(value: int) -> str:
    """1234 -> "1.2k", the way GitHub shows counts."""
    if value < 1000:
        return str(value)
    if value < 10_000:
        return f"{value / 1000:.1f}".rstrip("0").rstrip(".") + "k"
    return f"{value // 1000}k"


class StarCount:
    """Stale-while-revalidate: pages never wait for GitHub, and a refresh runs in the background.

    Without GITHUB_REPO it does nothing. On failure it keeps the last good count (or none at all).
    """

    def __init__(
        self,
        repo: str | None,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.repo = repo
        self.value: int | None = None
        self._transport = transport
        self._clock = clock
        self._next_fetch = 0.0
        self._task: asyncio.Task[None] | None = None

    async def fetch(self) -> int | None:
        """One API request; None on any failure."""
        if not self.repo:
            return None
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "openfolio-cloud"}
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS, transport=self._transport) as client:
                r = await client.get(API_URL.format(repo=self.repo), headers=headers)
            if r.status_code != 200:
                raise ValueError(f"HTTP {r.status_code}")
            data = r.json()
            count = data.get("stargazers_count") if isinstance(data, dict) else None
            if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                raise ValueError("no star count in the response")
        except (httpx.HTTPError, ValueError) as e:
            logger.info(f"GitHub star count unavailable ({type(e).__name__}: {e})")
            return None
        return count

    async def refresh(self) -> None:
        count = await self.fetch()
        if count is not None:
            self.value = count
        self._next_fetch = self._clock() + (CACHE_SECONDS if count is not None else RETRY_SECONDS)

    def current(self) -> int | None:
        """The cached count, or None. Starts one background refresh when the cache is stale."""
        if not self.repo or self._clock() < self._next_fetch or (self._task and not self._task.done()):
            return self.value
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # rendered outside the event loop: just show what we have
            return self.value
        self._next_fetch = self._clock() + RETRY_SECONDS
        self._task = loop.create_task(self.refresh())
        return self.value
