"""Public profile pages for live members: /p/{handle}, its Markdown twin and the photo.

GET /p/{handle}                  portfolio page with the AI twin embedded (live, unpaused members only)
GET /p/{handle}.md               the same facts as plain Markdown, for AI crawlers and assistants
GET /p/{handle}/photo-{id}.jpg   the approved photo (also shown to the owner and the site owner beforehand)

The page is a search and AI-search surface: title and description from the persona, a canonical
URL, Open Graph and Twitter tags, and JSON-LD (ProfilePage + Person) rendered with Jinja's tojson,
which escapes <, > and &, so a name such as "</script>" stays inert.
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import ValidationError

from ..persona import Persona
from .member_auth import MemberAuth
from .profile import HANDLE_RE, current_employer, photo_path, to_persona
from .web import CloudContext

_PHOTO = re.compile(r"photo-(\d{1,12})\.jpg")
DESCRIPTION_CHARS = 160


def _description(persona: Persona) -> str:
    text = f"{persona.title}. {persona.tagline}" if persona.tagline else persona.title
    text = " ".join(text.split())
    return text if len(text) <= DESCRIPTION_CHARS else text[: DESCRIPTION_CHARS - 1].rsplit(" ", 1)[0] + "…"


def structured_data(ctx: CloudContext, persona: Persona, data: dict[str, Any], page_url: str) -> dict[str, Any]:
    person: dict[str, Any] = {
        "@type": "Person",
        "name": persona.name,
        "url": page_url,
        "description": persona.tagline or persona.title,
    }
    if persona.title:
        person["jobTitle"] = persona.title
    if persona.avatar.photo:
        person["image"] = f"{ctx.cloud.public_url}/{persona.avatar.photo}"
    if persona.links:
        person["sameAs"] = [str(link.url) for link in persona.links]
    skills = [skill for items in persona.skills.values() for skill in items]
    if skills:
        person["knowsAbout"] = skills[:40]
    if employer := current_employer(data):
        person["worksFor"] = {"@type": "Organization", "name": employer}
    return {
        "@context": "https://schema.org",
        "@type": "ProfilePage",
        "url": page_url,
        "name": f"{persona.name} · {persona.title}" if persona.title else persona.name,
        "mainEntity": person,
    }


def profile_context(
    ctx: CloudContext, persona: Persona, data: dict[str, Any], *, show_in_search: bool
) -> dict[str, Any]:
    page_url = f"{ctx.cloud.public_url}/p/{persona.id}"
    photo = f"/{persona.avatar.photo}" if persona.avatar.photo else None
    return {
        "persona": persona,
        "page_url": page_url,
        "photo_url": photo,
        "photo_abs": f"{ctx.cloud.public_url}{photo}" if photo else None,
        "description": _description(persona),
        "ld": structured_data(ctx, persona, data, page_url),
        "show_in_search": show_in_search,
        "employer": current_employer(data),
        "widget_id": persona.id,
        "preview_note": None,
        "review": None,
    }


def markdown(persona: Persona, page_url: str) -> str:
    """A plain-text twin of the page. Markdown is not HTML: nothing here is ever rendered as markup."""
    out = [f"# {persona.name}", "", f"{persona.title}" + (f" · {persona.tagline}" if persona.tagline else ""), ""]
    out += ["## About", "", persona.about, ""] if persona.about else []
    if persona.highlights:
        out += ["## Highlights", "", *[f"- {h}" for h in persona.highlights], ""]
    if persona.experience:
        out += ["## Experience", ""]
        out += [f"- **{r.title}**, {r.company} ({r.period}): {r.summary}" for r in persona.experience] + [""]
    if persona.projects:
        out += ["## Projects", ""]
        for p in persona.projects:
            where = ", ".join(x for x in (p.org, p.period) if x)
            line = f"- **{p.name}**" + (f" ({where})" if where else "") + f": {p.summary}"
            line += f" Result: {p.metric}." if p.metric else ""
            out.append(line + (f" <{p.url}>" if p.url else ""))
        out.append("")
    if persona.skills:
        out += ["## Skills", "", *[f"- {group}: {', '.join(items)}" for group, items in persona.skills.items()], ""]
    if persona.education:
        out += ["## Education", "", *[f"- {e}" for e in persona.education], ""]
    if persona.awards:
        out += ["## Recognition", "", *[f"- {a}" for a in persona.awards], ""]
    if persona.links:
        out += ["## Links", "", *[f"- {link.label}: <{link.url}>" for link in persona.links], ""]
    out += [
        "## Talk to my AI version",
        "",
        f"An AI version of {persona.first_name} answers questions about this profile by voice or chat at <{page_url}>.",
        "It is labelled as AI and answers only from the facts above.",
        "",
    ]
    return "\n".join(out)


def public_router(ctx: CloudContext, members: MemberAuth, owner_signed_in: Any) -> APIRouter:
    router = APIRouter(include_in_schema=False)
    db, store = ctx.db, ctx.store

    async def live(handle: str) -> tuple[Persona, dict[str, Any], bool] | None:
        if not HANDLE_RE.fullmatch(handle):
            return None
        record = await db.run(store.visible_persona, handle)
        if record is None or record.live_data is None:
            return None
        try:
            return to_persona(handle, record.live_data, ctx.cloud.public_url), record.live_data, record.show_in_search
        except ValidationError:
            return None

    def not_found(request: Request) -> Response:
        return ctx.render(
            request,
            "message.html",
            status=404,
            kind="error",
            heading="Page not found",
            text="This profile doesn't exist or isn't public right now.",
            headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex"},
        )

    @router.get("/p/{name}")
    async def profile(request: Request, name: str) -> Response:
        handle = name.removesuffix(".md")
        found = await live(handle)
        if found is None:
            return not_found(request)
        persona, data, listed = found
        page_url = f"{ctx.cloud.public_url}/p/{handle}"
        headers = {"Cache-Control": "public, max-age=60"}
        if not listed:
            headers["X-Robots-Tag"] = "noindex"
        if name.endswith(".md"):
            return PlainTextResponse(
                markdown(persona, page_url), media_type="text/markdown; charset=utf-8", headers=headers
            )
        context = profile_context(ctx, persona, data, show_in_search=listed)
        return ctx.render(request, "profile_page.html", csp=ctx.widget_csp, headers=headers, csrf="", **context)

    @router.get("/p/{handle}/{asset}")
    async def photo(request: Request, handle: str, asset: str) -> Response:
        m = _PHOTO.fullmatch(asset)
        if not m or not HANDLE_RE.fullmatch(handle):
            return not_found(request)
        file_id, wanted = int(m.group(1)), photo_path(handle, int(m.group(1)))
        record = await db.run(store.persona_by_handle, handle)
        if record is None:
            return not_found(request)
        public = False
        visible = await db.run(store.visible_persona, handle)
        if visible and visible.live_data and (visible.live_data.get("avatar") or {}).get("photo") == wanted:
            public = True
        elif not await _may_preview(request, record.user_id, handle):
            return not_found(request)
        stored = await db.run(store.get_file, record.user_id, file_id)
        if stored is None or stored.kind != "photo":
            return not_found(request)
        path = ctx.files.path(record.user_id, stored.stored_name)
        if not path.exists():
            return not_found(request)
        cache = "public, max-age=3600" if public else "private, no-store"
        return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": cache})

    async def _may_preview(request: Request, user_id: int, handle: str) -> bool:
        signed = await members.current(request)
        if signed is not None and signed.user.id == user_id:
            return True
        return bool(await owner_signed_in(request))

    return router
