"""Search engines and AI assistants: structured data, crawler files and the answer pages.

GET /robots.txt, /sitemap.xml        what may be crawled, and every public URL
GET /llms.txt, /llms-full.txt        product facts for AI assistants (llmstxt.org format)
GET /.well-known/security.txt        how to report a vulnerability (RFC 9116)
GET /site.webmanifest, /favicon.ico  app icons
GET /guides/ai-portfolio, /guides/portfolio-for-recruiters, /compare

base.html renders each page's title, description, canonical URL and social tags. Facts that both
people and machines read (the FAQ, the product summary) are defined here once, so a page and its
JSON-LD can never disagree.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from loguru import logger

from . import profiles
from .github import StarCount, compact_count
from .web import STATIC_DIR, TEMPLATES_DIR, CloudContext

SITE_NAME = "Openfolio"
TAGLINE = "Your portfolio, alive."
PROMISE = "A modern portfolio for everyone: a 3D AI version of you that talks to recruiters by voice or chat."
SUMMARY = (
    "Openfolio is an open-source AI portfolio builder. It gives you a 3D AI version of yourself that answers "
    "recruiters' and visitors' questions about your work by voice or chat, using only what you wrote."
)
FOUNDER = "Faisal Rehman"
CONTENT_DATE = "2026-10-24"  # bump when the guides change, so sitemap lastmod stays honest
OG_IMAGE = "/cloud/static/og-image.png"
OG_IMAGE_ALT = "Openfolio: your portfolio, alive. A 3D AI version of you that talks to recruiters."
YEAR_SECONDS = 365 * 86_400

# Named so the policy is explicit; robots.txt gives each its own group because a crawler that finds
# a group with its name ignores the "*" group entirely.
CRAWLERS = (
    "Googlebot",
    "Bingbot",
    "GPTBot",
    "OAI-SearchBot",
    "ChatGPT-User",
    "ClaudeBot",
    "Claude-User",
    "PerplexityBot",
    "Google-Extended",
    "Applebot-Extended",
)
PRIVATE_PATHS = ("/admin", "/studio", "/join", "/login", "/invite", "/cloud/", "/v1/")
# Inside /cloud/: stylesheets for rendering and the og-image for link previews must stay fetchable.
PUBLIC_ASSET_PATHS = ("/cloud/static/",)


@dataclass(frozen=True)
class Article:
    path: str
    template: str
    title: str  # the <title>: short enough for search results
    headline: str
    description: str
    crumb: str


@dataclass(frozen=True)
class Faq:
    question: str
    answer: str


ARTICLES = (
    Article(
        path="/guides/ai-portfolio",
        template="guide_ai_portfolio.html",
        title="What is an AI portfolio? How to build one · Openfolio",
        headline="What is an AI portfolio, and how do you build one?",
        description=(
            "An AI portfolio is a portfolio website with an AI version of you that answers visitors' questions "
            "about your work. What it is, when it helps, and how to build one in five steps."
        ),
        crumb="What is an AI portfolio",
    ),
    Article(
        path="/guides/portfolio-for-recruiters",
        template="guide_recruiters.html",
        title="A portfolio recruiters can interview · Openfolio",
        headline="A portfolio recruiters can interview: how to make your work easy to evaluate",
        description=(
            "What recruiters look for in a portfolio, the questions they ask first, and how an AI twin lets them "
            "interview you any time, by voice or chat, from your own words."
        ),
        crumb="Portfolio for recruiters",
    ),
    Article(
        path="/compare",
        template="compare.html",
        title="AI portfolio vs static portfolio site vs chatbot · Openfolio",
        headline="AI portfolio vs static portfolio site vs generic chatbot",
        description=(
            "How an AI portfolio like Openfolio compares with a static portfolio site and a generic chatbot widget: "
            "answers, voice, accuracy, disclosure, setup and cost."
        ),
        crumb="Compare",
    ),
)

FAQ = (
    Faq(
        "What is Openfolio?",
        "Openfolio is an open-source AI portfolio builder. It gives you a 3D AI version of yourself that answers "
        "recruiters' and visitors' questions about your work by voice or chat, using only what you wrote. "
        "Openfolio Cloud is the hosted version, now in an invite-only beta.",
    ),
    Faq(
        "Who is Openfolio for?",
        "Anyone whose work speaks for them: students, engineers, designers, freelancers and career switchers. "
        "If people visit your portfolio to decide whether to talk to you, your AI twin can answer their first "
        "questions at any hour.",
    ),
    Faq(
        "How do recruiters use it?",
        "A recruiter opens your portfolio, taps Talk or Chat and interviews your AI twin about your projects, "
        "experience and skills. It answers from your own material, says when it doesn't know, and can take a "
        "message for the real you.",
    ),
    Faq(
        "Will my AI twin make things up?",
        "It is built not to. Its facts come only from the profile you write and review, and its instructions forbid "
        "inventing employers, dates, numbers or commitments. When a question isn't covered, it says it doesn't know "
        "and points to you. AI can still make mistakes, so review your profile and test it before you share it.",
    ),
    Faq(
        "Does it pretend to be me?",
        "No. The button, the panel and its first answer all say it's an AI version of you, and it says so again "
        "whenever someone asks whether it's human.",
    ),
    Faq(
        "How much does it cost?",
        "Openfolio Cloud is free during the beta. People who join the waitlist during the beta become founding "
        "members with free monthly credits. The open-source version is free to run yourself; you pay only your "
        "own AI providers, or nothing with local models.",
    ),
    Faq(
        "Can I add it to the portfolio I already have?",
        "Yes. Paste one script tag into any website, or share a link. It loads only when a visitor opens it, "
        "so it doesn't slow your page down.",
    ),
    Faq(
        "Is Openfolio open source?",
        "Yes. The code is on GitHub under the Apache-2.0 license, so you can read it, change it and run it on your "
        "own server without a GPU. Contributors whose pull requests are merged earn extra Cloud credits.",
    ),
    Faq(
        "What happens to visitors' conversations?",
        "To answer, messages are processed by the speech, language and voice providers that run the service. "
        "Openfolio doesn't save recordings or transcripts, and visitors get no cookies or trackers.",
    ),
    Faq(
        "How do I get access?",
        "Join the waitlist on this page. We let people in a few at a time and read every request ourselves; "
        "if it's a fit, you get a personal invite link by email.",
    ),
)


def static_pages() -> list[str]:
    """Public, indexable paths in the order they should appear in the sitemap."""
    return ["/", *(a.path for a in ARTICLES), "/privacy", "/terms"]


def _absolute(url: str, public_url: str) -> str | None:
    """Sitemaps may list only this site's own URLs."""
    if url.startswith("/") and not url.startswith("//"):
        return public_url + url
    if url.startswith(public_url + "/"):
        return url
    return None


class Seo:
    """Helpers that templates reach as `seo`: the FAQ, the star count and JSON-LD documents."""

    def __init__(self, ctx: CloudContext, stars: StarCount) -> None:
        self.ctx = ctx
        self._stars = stars

    @property
    def faq(self) -> tuple[Faq, ...]:
        return FAQ

    @property
    def articles(self) -> tuple[Article, ...]:
        return ARTICLES

    @property
    def content_date(self) -> str:
        return CONTENT_DATE

    def stars(self) -> str | None:
        count = self._stars.current()
        return compact_count(count) if count is not None else None

    def _ids(self) -> tuple[str, str, str]:
        home = self.ctx.cloud.public_url + "/"
        return home, home + "#organization", home + "#website"

    def _organization(self) -> dict[str, Any]:
        home, org_id, _ = self._ids()
        same_as = [self.ctx.cloud.github_url]
        if self.ctx.cloud.product_hunt_url:
            same_as.append(self.ctx.cloud.product_hunt_url)
        org: dict[str, Any] = {
            "@type": "Organization",
            "@id": org_id,
            "name": SITE_NAME,
            "url": home,
            "logo": self.ctx.cloud.public_url + "/cloud/static/icon-512.png",
            "slogan": TAGLINE,
            "founder": {"@type": "Person", "name": FOUNDER},
            "sameAs": same_as,
        }
        if self.ctx.contact_email:
            org["email"] = self.ctx.contact_email
        return org

    def landing_jsonld(self) -> dict[str, Any]:
        """Organization, WebSite, SoftwareApplication and FAQPage, as one @graph."""
        home, org_id, site_id = self._ids()
        url = self.ctx.cloud.public_url
        app = {
            "@type": "SoftwareApplication",
            "@id": home + "#app",
            "name": "Openfolio Cloud",
            "alternateName": "Openfolio AI portfolio builder",
            "description": f"{PROMISE} {SUMMARY}",
            "url": home,
            "image": url + OG_IMAGE,
            "applicationCategory": "BusinessApplication",
            "applicationSubCategory": "AI portfolio builder",
            "operatingSystem": "Web",
            "isAccessibleForFree": True,
            "offers": {
                "@type": "Offer",
                "price": "0",
                "priceCurrency": "USD",
                "description": "Free during the invite-only beta",
                "availability": "https://schema.org/LimitedAvailability",
            },
            "featureList": [
                "3D AI avatar that talks by voice or chat",
                "Answers only from the owner's own profile",
                "Always labelled as AI",
                "Embeds on any website with one script tag",
                "Open source under Apache-2.0",
            ],
            "license": "https://www.apache.org/licenses/LICENSE-2.0",
            "codeRepository": self.ctx.cloud.github_url,
            "publisher": {"@id": org_id},
        }
        website = {
            "@type": "WebSite",
            "@id": site_id,
            "url": home,
            "name": SITE_NAME,
            "description": PROMISE,
            "inLanguage": "en",
            "publisher": {"@id": org_id},
        }
        faq = {
            "@type": "FAQPage",
            "@id": home + "#faq",
            "mainEntity": [
                {"@type": "Question", "name": f.question, "acceptedAnswer": {"@type": "Answer", "text": f.answer}}
                for f in FAQ
            ],
        }
        return {"@context": "https://schema.org", "@graph": [self._organization(), website, app, faq]}

    def article_jsonld(self, path: str) -> dict[str, Any]:
        """Article plus breadcrumbs for a guide page."""
        article = next(a for a in ARTICLES if a.path == path)
        home, org_id, _ = self._ids()
        url = self.ctx.cloud.public_url + path
        return {
            "@context": "https://schema.org",
            "@graph": [
                {
                    "@type": "Article",
                    "@id": url + "#article",
                    "headline": article.headline,
                    "description": article.description,
                    "url": url,
                    "mainEntityOfPage": url,
                    "image": self.ctx.cloud.public_url + OG_IMAGE,
                    "datePublished": CONTENT_DATE,
                    "dateModified": CONTENT_DATE,
                    "inLanguage": "en",
                    "author": {"@type": "Person", "name": FOUNDER},
                    "publisher": {"@id": org_id},
                },
                {
                    "@type": "BreadcrumbList",
                    "itemListElement": [
                        {"@type": "ListItem", "position": 1, "name": SITE_NAME, "item": home},
                        {"@type": "ListItem", "position": 2, "name": article.crumb, "item": url},
                    ],
                },
                self._organization(),
            ],
        }


def text_templates() -> Environment:
    # Plain-text files only, served as text/plain with nosniff: HTML escaping would corrupt them.
    return Environment(
        loader=FileSystemLoader(TEMPLATES_DIR / "text"),
        autoescape=False,  # noqa: S701
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def seo_router(ctx: CloudContext, seo: Seo) -> APIRouter:
    router = APIRouter(include_in_schema=False)
    text = text_templates()
    cached = {"Cache-Control": "public, max-age=3600"}

    def plain(template: str, **context: Any) -> Response:
        body = text.get_template(template).render(
            public_url=ctx.cloud.public_url,
            github_url=ctx.cloud.github_url,
            contact_email=ctx.contact_email,
            faq=FAQ,
            articles=ARTICLES,
            promise=PROMISE,
            summary=SUMMARY,
            tagline=TAGLINE,
            **context,
        )
        return Response(body, media_type="text/plain; charset=utf-8", headers=cached)

    @router.get("/robots.txt")
    async def robots() -> Response:
        return plain("robots.txt", crawlers=CRAWLERS, private=PRIVATE_PATHS, assets=PUBLIC_ASSET_PATHS)

    @router.get("/llms.txt")
    async def llms() -> Response:
        return plain("llms.txt")

    @router.get("/llms-full.txt")
    async def llms_full() -> Response:
        return plain("llms-full.txt")

    @router.get("/.well-known/security.txt")
    async def security_txt() -> Response:
        # Computed per request, so the file never goes stale while the site is up.
        expires = datetime.fromtimestamp(ctx.now() + YEAR_SECONDS, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        return plain("security.txt", expires=expires)

    @router.get("/sitemap.xml")
    async def sitemap() -> Response:
        public_url = ctx.cloud.public_url
        urls = [{"loc": public_url + path, "lastmod": CONTENT_DATE} for path in static_pages()]
        try:
            extra = await asyncio.to_thread(profiles.public_profile_urls)
        except Exception:
            # A failing profile query must not take the static pages out of the sitemap.
            logger.exception("public_profile_urls failed; sitemap lists static pages only")
            extra = []
        seen = {u["loc"] for u in urls}
        for raw in extra:
            loc = _absolute(raw, public_url)
            if loc and loc not in seen:
                seen.add(loc)
                urls.append({"loc": loc, "lastmod": ""})
        body = ctx.templates.get_template("sitemap.xml").render(urls=urls)
        return Response(body, media_type="application/xml", headers=cached)

    @router.get("/site.webmanifest")
    async def manifest() -> JSONResponse:
        icons = [
            {"src": f"/cloud/static/icon-{size}.png", "sizes": f"{size}x{size}", "type": "image/png", "purpose": p}
            for size in (192, 512)
            for p in ("any", "maskable")
        ]
        body = {
            "name": "Openfolio Cloud",
            "short_name": SITE_NAME,
            "description": PROMISE,
            "start_url": "/",
            "scope": "/",
            "display": "standalone",
            "background_color": "#f6f7f9",
            "theme_color": "#17202b",
            "icons": icons,
        }
        headers = {"Cache-Control": "public, max-age=86400"}
        return JSONResponse(body, media_type="application/manifest+json", headers=headers)

    @router.get("/favicon.ico")
    async def favicon() -> FileResponse:
        # Browsers and crawlers ask for it even when the pages link the SVG icon.
        return FileResponse(
            STATIC_DIR / "favicon.ico", media_type="image/x-icon", headers={"Cache-Control": "public, max-age=604800"}
        )

    def article_route(article: Article) -> None:
        async def page(request: Request) -> Response:
            return ctx.render(request, article.template, article=article, jsonld=seo.article_jsonld(article.path))

        router.add_api_route(article.path, page, methods=["GET"])

    for article in ARTICLES:
        article_route(article)
    return router


def install(app: FastAPI, ctx: CloudContext) -> Seo:
    """Register the crawler files and guides, and give every template the `seo` helpers."""
    seo = Seo(ctx, StarCount(ctx.cloud.github_repo, ctx.transport))
    ctx.templates.globals.update(seo=seo, product_hunt_url=ctx.cloud.product_hunt_url)
    app.include_router(seo_router(ctx, seo))
    return seo
