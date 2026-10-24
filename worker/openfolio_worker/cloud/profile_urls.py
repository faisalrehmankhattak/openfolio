"""Public profile URLs, for the sitemap (the growth stage builds sitemap.xml from this).

Only live profiles of active members who left "show in search" on are listed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from .db import CloudDB
from .store import StudioStore


@dataclass(frozen=True)
class ProfileUrl:
    loc: str  # absolute URL of the profile page
    lastmod: str  # W3C date (YYYY-MM-DD), when it last went live
    markdown: str  # the plain-text twin for AI crawlers


def public_profile_urls(db: CloudDB, public_url: str) -> list[ProfileUrl]:
    """Synchronous: call it through db.run from async code."""
    return [
        ProfileUrl(
            loc=f"{public_url}/p/{p.handle}",
            lastmod=datetime.fromtimestamp(p.updated_at, UTC).strftime("%Y-%m-%d"),
            markdown=f"{public_url}/p/{p.handle}.md",
        )
        for p in StudioStore(db).listed_profiles()
    ]
