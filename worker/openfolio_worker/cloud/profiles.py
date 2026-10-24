"""Public profile pages: the seam between profiles and the sitemap.

seo.py lists every URL from public_profile_urls() in /sitemap.xml, calling it with no arguments
from a worker thread. install() binds the cloud database and PUBLIC_URL here at startup, and
profile_urls.py runs the query, so the sitemap and the pages agree on what is public.
"""

from __future__ import annotations

from .db import CloudDB
from .profile_urls import public_profile_urls as _listed

# One server, one database: a dict instead of a module global keeps the binding replaceable in tests.
_bound: dict[str, tuple[CloudDB, str]] = {}


def bind(db: CloudDB, public_url: str) -> None:
    _bound["cloud"] = (db, public_url)


def unbind(db: CloudDB) -> None:
    if _bound.get("cloud", (None, ""))[0] is db:
        _bound.pop("cloud", None)


def public_profile_urls() -> list[str]:
    """Absolute URLs of every live profile whose member left "show in search" on, for sitemap.xml.

    Drafts, submissions under review, paused and deleted profiles are never listed. Synchronous
    (one indexed query); returns [] when the cloud pages aren't installed.
    """
    bound = _bound.get("cloud")
    if bound is None:
        return []
    db, public_url = bound
    return [url.loc for url in _listed(db, public_url)]
