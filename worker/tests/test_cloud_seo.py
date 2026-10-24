import asyncio
import json
import re
from dataclasses import replace
from html import unescape
from xml.etree import ElementTree

import httpx
import pytest

from openfolio_worker.cloud import seo
from openfolio_worker.cloud.github import CACHE_SECONDS, RETRY_SECONDS, StarCount, compact_count
from openfolio_worker.config import ConfigError, load_settings

from cloud_helpers import client_for
from conftest import PUBLIC_URL

PRIVATE = ("/admin", "/studio", "/join", "/login", "/invite", "/cloud/")
SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"


def robots_groups(text: str) -> dict[str, list[str]]:
    """User-agent -> its rule lines, the way crawlers group them."""
    groups: dict[str, list[str]] = {}
    current: list[str] = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if line.lower().startswith("user-agent:"):
            current = groups.setdefault(line.split(":", 1)[1].strip(), [])
        elif line and not line.lower().startswith("sitemap:"):
            current.append(line)
    return groups


def jsonld(html: str) -> list[dict]:
    blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
    return [json.loads(block) for block in blocks]


def head_tags(html: str) -> dict[str, str]:
    title = re.search(r"<title>(.*?)</title>", html, re.S)
    description = re.search(r'<meta name="description" content="([^"]*)"', html)
    canonical = re.search(r'<link rel="canonical" href="([^"]*)"', html)
    return {
        "title": unescape(title.group(1)) if title else "",
        "description": unescape(description.group(1)) if description else "",
        "canonical": canonical.group(1) if canonical else "",
    }


def seo_helpers(client) -> seo.Seo:
    return client.app.state.cloud.templates.globals["seo"]


def test_robots_txt_opens_public_pages_and_closes_private_ones(cloud_settings):
    r = client_for(cloud_settings).get("/robots.txt")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    groups = robots_groups(r.text)
    assert set(seo.CRAWLERS) | {"*"} == set(groups)
    for agent in ("*", "GPTBot", "ClaudeBot", "PerplexityBot", "Google-Extended", "OAI-SearchBot", "Claude-User"):
        rules = groups[agent]
        for path in PRIVATE:
            assert f"Disallow: {path}" in rules, (agent, path)
        assert "Allow: /" in rules
        assert "Allow: /cloud/static/" in rules  # CSS and the og-image stay fetchable
    assert f"Sitemap: {PUBLIC_URL}/sitemap.xml" in r.text


def test_sitemap_is_valid_xml_with_absolute_urls(cloud_settings):
    r = client_for(cloud_settings).get("/sitemap.xml")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/xml")
    root = ElementTree.fromstring(r.content)  # noqa: S314 - our own output
    assert root.tag == f"{SITEMAP_NS}urlset"
    locs = [el.text for el in root.iter(f"{SITEMAP_NS}loc")]
    assert locs == [PUBLIC_URL + path for path in seo.static_pages()]
    assert all(loc.startswith(PUBLIC_URL + "/") for loc in locs)
    assert not any(p in loc for loc in locs for p in PRIVATE)


def test_sitemap_lists_published_profiles(cloud_settings, monkeypatch):
    urls = ["/p/jane", f"{PUBLIC_URL}/p/sam", "https://elsewhere.example/p/x", "//evil.example/p", "/p/jane", "/p/a&b"]
    monkeypatch.setattr(seo.profiles, "public_profile_urls", lambda: urls)
    body = client_for(cloud_settings).get("/sitemap.xml").content
    locs = [el.text for el in ElementTree.fromstring(body).iter(f"{SITEMAP_NS}loc")]  # noqa: S314
    extra = locs[len(seo.static_pages()) :]
    assert extra == [f"{PUBLIC_URL}/p/jane", f"{PUBLIC_URL}/p/sam", f"{PUBLIC_URL}/p/a&b"]  # & is escaped in the XML
    assert b"/p/a&amp;b" in body


def test_sitemap_survives_a_failing_profile_query(cloud_settings, monkeypatch):
    def broken() -> list[str]:
        raise RuntimeError("database is locked")

    monkeypatch.setattr(seo.profiles, "public_profile_urls", broken)
    r = client_for(cloud_settings).get("/sitemap.xml")
    assert r.status_code == 200
    assert r.text.count("<loc>") == len(seo.static_pages())


def test_profiles_stub_lists_nothing_yet():
    from openfolio_worker.cloud.profiles import public_profile_urls

    assert public_profile_urls() == []


def test_llms_txt_follows_the_llmstxt_format(cloud_settings):
    r = client_for(cloud_settings).get("/llms.txt")
    assert r.status_code == 200
    lines = r.text.splitlines()
    assert lines[0] == "# Openfolio"
    assert lines[1] == ""
    assert lines[2].startswith("> ")
    assert "AI portfolio builder" in lines[2]
    sections = [line for line in lines if line.startswith("## ")]
    assert sections[:2] == ["## Product", "## Guides"]
    assert sections[-1] == "## Optional"
    links = [line for line in lines if line.startswith("- ")]
    assert len(links) >= 8
    for line in links:
        assert re.fullmatch(r"- \[[^\]]+\]\((https?://[^)\s]+)\): \S.*", line), line
    for article in seo.ARTICLES:
        assert f"({PUBLIC_URL}{article.path})" in r.text
    assert "&#39;" not in r.text
    assert "&amp;" not in r.text


def test_llms_full_txt_has_the_facts_and_every_faq(cloud_settings):
    text = client_for(cloud_settings).get("/llms-full.txt").text
    assert text.startswith("# Openfolio: AI portfolio builder\n")
    for needle in (
        "Apache-2.0",
        "invite-only beta",
        "free during the invite-only beta",
        "never rewarded",
        "Always labelled AI",
    ):
        assert needle in text
    for item in seo.FAQ:
        assert f"### {item.question}" in text
        assert item.answer in text
    assert "unrelated" in text or "not related" in text  # the older investing app with the same name


def test_security_txt(cloud_settings, persona):
    client = client_for(cloud_settings)
    client.app.state.cloud.clock = lambda: 1_790_000_000  # 2026-09-21
    r = client.get("/.well-known/security.txt")
    assert r.status_code == 200
    assert f"Contact: mailto:{persona.email}" in r.text
    assert "Expires: 2027-09-21T" in r.text
    assert f"Canonical: {PUBLIC_URL}/.well-known/security.txt" in r.text
    fields = [line.split(":", 1)[0] for line in r.text.splitlines() if line and not line.startswith("#")]
    assert fields.count("Expires") == 1  # RFC 9116: exactly one


def test_landing_jsonld_parses_and_matches_the_visible_faq(cloud_settings):
    html = client_for(cloud_settings).get("/").text
    (doc,) = jsonld(html)
    assert doc["@context"] == "https://schema.org"
    by_type = {node["@type"]: node for node in doc["@graph"]}
    assert set(by_type) == {"Organization", "WebSite", "SoftwareApplication", "FAQPage"}
    app = by_type["SoftwareApplication"]
    assert app["operatingSystem"] == "Web"
    assert app["applicationCategory"]
    assert app["isAccessibleForFree"] is True
    assert app["offers"]["price"] == "0"
    assert by_type["Organization"]["url"] == PUBLIC_URL + "/"
    questions = [q["name"] for q in by_type["FAQPage"]["mainEntity"]]
    visible = [unescape(q) for q in re.findall(r"<summary><h3>(.*?)</h3>", html)]
    assert questions == visible == [f.question for f in seo.FAQ]
    for q in by_type["FAQPage"]["mainEntity"]:
        assert q["acceptedAnswer"]["text"] in unescape(html)


def test_jsonld_is_escaped_inside_the_script_tag(cloud_settings, monkeypatch):
    evil = "</script><script>alert(1)</script>"
    monkeypatch.setattr(seo, "FAQ", (seo.Faq(f"Is {evil} safe?", "Yes & <b>no</b>"),))
    html = client_for(cloud_settings).get("/").text
    assert "<script>alert(1)" not in html
    (doc,) = jsonld(html)
    faq = next(node for node in doc["@graph"] if node["@type"] == "FAQPage")
    assert faq["mainEntity"][0]["name"] == f"Is {evil} safe?"  # round-trips exactly
    assert faq["mainEntity"][0]["acceptedAnswer"]["text"] == "Yes & <b>no</b>"


def test_guides_have_article_jsonld(cloud_settings):
    client = client_for(cloud_settings)
    for article in seo.ARTICLES:
        r = client.get(article.path)
        assert r.status_code == 200, article.path
        (doc,) = jsonld(r.text)
        types = [node["@type"] for node in doc["@graph"]]
        assert types[:2] == ["Article", "BreadcrumbList"]
        assert doc["@graph"][0]["headline"] == article.headline
        assert "<h1" in r.text
        assert "Short answer" in r.text
        assert 'property="og:type" content="article"' in r.text
        assert "'unsafe-inline'" not in r.headers["content-security-policy"]  # guides get the strict policy


def test_every_public_page_has_a_unique_title_description_and_canonical(cloud_settings):
    client = client_for(cloud_settings)
    seen_titles, seen_descriptions = set(), set()
    for path in seo.static_pages():
        r = client.get(path)
        assert r.status_code == 200, path
        tags = head_tags(r.text)
        assert tags["canonical"] == PUBLIC_URL + path, path
        assert 10 <= len(tags["title"]) <= 70, (path, tags["title"])
        assert 50 <= len(tags["description"]) <= 200, (path, tags["description"])
        assert tags["title"] not in seen_titles, path
        assert tags["description"] not in seen_descriptions, path
        seen_titles.add(tags["title"])
        seen_descriptions.add(tags["description"])
        assert f'<meta property="og:url" content="{PUBLIC_URL}{path}">' in r.text
        assert 'name="twitter:card" content="summary_large_image"' in r.text
        assert f'content="{PUBLIC_URL}/cloud/static/og-image.png"' in r.text
        assert 'name="robots"' not in r.text
    assert "Openfolio" in head_tags(client.get("/").text)["title"]
    assert "AI portfolio" in head_tags(client.get("/").text)["title"]


def test_landing_canonical_stays_on_the_home_page_after_a_form_error(cloud_settings):
    r = client_for(cloud_settings).post("/cloud/requests", data={"name": "", "consent": "on"})
    assert r.status_code == 400
    assert head_tags(r.text)["canonical"] == PUBLIC_URL + "/"


def test_private_and_utility_pages_are_noindex(cloud_settings):
    client = client_for(cloud_settings)
    for path in ("/cloud/thanks", "/admin/login", "/invite/" + "a" * 43):
        html = client.get(path).text
        assert '<meta name="robots" content="noindex, nofollow">' in html, path
        assert 'rel="canonical"' not in html, path
    missing = client.get("/missing", headers={"accept": "text/html"}).text
    assert 'content="noindex, nofollow"' in missing


def test_landing_copy_says_waitlist_and_never_rewards_stars(cloud_settings):
    html = client_for(cloud_settings).get("/").text
    assert "Join the waitlist" in html
    assert "Request access" not in html
    assert "Star on GitHub" in html
    assert "Founding members" in html
    lowered = html.lower()
    assert "upvote" not in lowered.replace("stars, upvotes or follows", "")
    assert "never earns credits" in lowered


def test_product_hunt_banner_is_off_by_default(cloud_settings):
    html = client_for(cloud_settings).get("/").text
    assert "ph-banner" not in html
    assert "Product Hunt" not in html


def test_product_hunt_banner_when_configured(cloud_settings):
    url = "https://www.producthunt.com/posts/openfolio"
    s = replace(cloud_settings, cloud=replace(cloud_settings.cloud, product_hunt_url=url))
    client = client_for(s)
    html = client.get("/").text
    assert f'<a class="ph-banner" href="{url}"' in html
    banner = html[html.index('class="ph-banner"') : html.index("</a>", html.index('class="ph-banner"'))]
    assert "We're live on Product Hunt — come say hi and share feedback" in unescape(banner)
    assert "upvote" not in banner.lower()
    assert "ph-banner" in client.get("/guides/ai-portfolio").text
    assert "ph-banner" not in client.get("/admin/login").text  # never on private pages
    org = next(n for n in jsonld(html)[0]["@graph"] if n["@type"] == "Organization")
    assert url in org["sameAs"]


@pytest.mark.parametrize(
    ("value", "ok"),
    [
        ("https://www.producthunt.com/posts/openfolio", True),
        ("https://producthunt.com/products/openfolio", True),
        ("http://www.producthunt.com/posts/openfolio", False),
        ("https://producthunt.com.evil.example/x", False),
        ("javascript:alert(1)", False),
    ],
)
def test_product_hunt_url_is_validated(cloud_env, monkeypatch, value, ok):
    monkeypatch.setenv("PRODUCT_HUNT_URL", value)
    if ok:
        assert load_settings().cloud.product_hunt_url == value
    else:
        with pytest.raises(ConfigError, match="PRODUCT_HUNT_URL"):
            load_settings()


@pytest.mark.parametrize(
    ("value", "ok"),
    [("faisalrehmankhattak/openfolio", True), ("a/b.c-d_e", True), ("nope", False), ("a/b/c", False), ("a b/c", False)],
)
def test_github_repo_is_validated(cloud_env, monkeypatch, value, ok):
    monkeypatch.setenv("GITHUB_REPO", value)
    if ok:
        cloud = load_settings().cloud
        assert cloud.github_repo == value
        assert cloud.github_url == f"https://github.com/{value}"
    else:
        with pytest.raises(ConfigError, match="GITHUB_REPO"):
            load_settings()


@pytest.fixture
def cloud_env(monkeypatch):
    from conftest import ADMIN_HASH, SESSION_SECRET

    monkeypatch.setenv("CLOUD_MODE", "1")
    monkeypatch.setenv("PUBLIC_URL", PUBLIC_URL)
    monkeypatch.setenv("SESSION_SECRET", SESSION_SECRET)
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", ADMIN_HASH)


def test_compact_count():
    assert [compact_count(n) for n in (0, 999, 1000, 1234, 9999, 10_500, 123_456)] == [
        "0",
        "999",
        "1k",
        "1.2k",
        "10k",
        "10k",
        "123k",
    ]


def github(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def test_star_count_fetches_caches_and_falls_back():
    calls: list[httpx.Request] = []
    replies = [httpx.Response(200, json={"stargazers_count": 1234}), httpx.Response(503), httpx.Response(200, json={})]

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return replies.pop(0)

    now = [1000.0]
    stars = StarCount("faisalrehmankhattak/openfolio", github(handle), clock=lambda: now[0])

    async def run() -> list[int | None]:
        seen = [stars.current()]  # nothing cached yet: shows nothing, starts a refresh
        await stars._task
        seen.append(stars.current())  # cached
        now[0] += CACHE_SECONDS + 1
        seen.append(stars.current())  # stale: still shows the last count while refreshing
        await stars._task  # GitHub is down
        seen.append(stars.current())
        now[0] += RETRY_SECONDS + 1
        stars.current()
        await stars._task  # a reply without a count
        seen.append(stars.current())
        return seen

    assert asyncio.run(run()) == [None, 1234, 1234, 1234, 1234]
    assert len(calls) == 3
    assert str(calls[0].url) == "https://api.github.com/repos/faisalrehmankhattak/openfolio"
    assert calls[0].headers["user-agent"] == "openfolio-cloud"


def test_star_count_does_nothing_without_a_repo():
    stars = StarCount(None, github(lambda request: pytest.fail("no request expected")))
    assert asyncio.run(stars.fetch()) is None
    assert stars.current() is None


def test_star_count_survives_network_errors():
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out")

    assert asyncio.run(StarCount("a/b", github(boom)).fetch()) is None


def test_landing_shows_the_cached_star_count(cloud_settings):
    s = replace(cloud_settings, cloud=replace(cloud_settings.cloud, github_repo="faisalrehmankhattak/openfolio"))
    client = client_for(s, transport=github(lambda request: httpx.Response(500)))
    assert "gh-count" not in client.get("/").text  # nothing cached and GitHub failing: no count, no error
    stars = seo_helpers(client)._stars
    stars.value, stars._next_fetch = 1234, float("inf")
    html = client.get("/").text
    assert 'aria-label="1.2k stars"' in html
    assert "api.github.com" not in html  # fetched server-side; the page loads nothing from GitHub


def test_manifest_and_icons(cloud_settings):
    client = client_for(cloud_settings)
    manifest = client.get("/site.webmanifest")
    assert manifest.status_code == 200
    assert manifest.headers["content-type"].startswith("application/manifest+json")
    data = manifest.json()
    assert data["start_url"] == "/"
    for icon in data["icons"]:
        assert client.get(icon["src"]).status_code == 200
    assert client.get("/favicon.ico").headers["content-type"] == "image/x-icon"
    html = client.get("/").text
    for href in re.findall(r'<link rel="(?:icon|apple-touch-icon)" href="([^"]+)"', html):
        assert client.get(href).status_code == 200, href
    og = client.get("/cloud/static/og-image.png")
    assert og.status_code == 200
    assert og.content[16:24] == (1200).to_bytes(4, "big") + (630).to_bytes(4, "big")  # PNG IHDR width, height
