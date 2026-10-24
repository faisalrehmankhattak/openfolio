"""Public profile pages: the seam between profiles and the sitemap.

seo.py lists every URL from public_profile_urls() in /sitemap.xml. The profile pages themselves
are built separately; until then there are no public profiles to list.
"""

from __future__ import annotations


def public_profile_urls() -> list[str]:
    """Return the URLs of every published profile, for sitemap.xml.

    Each item is an absolute URL on PUBLIC_URL or a path starting with "/". Include only profiles
    their owners have published; drafts, paused and deleted profiles must never be listed, because
    search engines and AI assistants would keep showing them. Called on every sitemap request, so
    keep it to one cheap query.
    """
    return []
