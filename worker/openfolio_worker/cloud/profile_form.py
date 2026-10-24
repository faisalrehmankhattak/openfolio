"""The Profile form: posted fields to persona data and back.

Repeating groups use names such as "projects-2-url". Blank rows are dropped and the rest are
renumbered, so errors from validation (keyed by the stored index) always match the re-rendered form.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .profile import KOKORO_VOICES, avatar_for, check_limits, persona_errors, storable, to_persona

GROUPS: dict[str, tuple[str, ...]] = {
    "experience": ("company", "title", "period", "summary"),
    "projects": ("name", "org", "period", "summary", "metric", "url"),
    "skills": ("group", "items"),
    "links": ("label", "url"),
    "quick": ("label", "question"),
}
LINES = ("highlights", "education", "awards", "guardrails")
TEXT = ("name", "first_name", "pronouns", "title", "tagline", "about", "email", "booking_url")
SPARE_ROWS = {"experience": 1, "projects": 1, "skills": 1, "links": 2, "quick": 1}
MAX_INDEX = 40
_ROW_KEY = re.compile(r"^(experience|projects|skills|links|quick)-(\d{1,2})-([a-z]+)$")
_URL_FIELDS = {"url", "booking_url"}


def _line(value: str) -> str:
    return " ".join(value.split())


def _paragraph(value: str) -> str:
    text = value.replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"\n{3,}", "\n\n", "\n".join(line.rstrip() for line in text.split("\n"))).strip()


def _url(value: str) -> str | None:
    value = value.strip()
    if not value:
        return None
    # People type "github.com/jane"; anything with another scheme is left for validation to refuse.
    if "://" not in value and ":" not in value.split("/")[0] and "." in value:
        return f"https://{value}"
    return value


def rows(fields: dict[str, str], group: str) -> list[dict[str, str]]:
    found: dict[int, dict[str, str]] = {}
    for key, value in fields.items():
        m = _ROW_KEY.match(key)
        if m and m.group(1) == group and m.group(3) in GROUPS[group] and int(m.group(2)) < MAX_INDEX:
            found.setdefault(int(m.group(2)), {})[m.group(3)] = value
    ordered = [found[i] for i in sorted(found)]
    return [row for row in ordered if any(v.strip() for v in row.values())]


def form_to_data(fields: dict[str, str], base: dict[str, Any], *, kokoro: bool, avatars_dir: Path) -> dict[str, Any]:
    """Build persona data from the posted form. The avatar files and anything not on the form are kept."""
    data: dict[str, Any] = {k: v for k, v in base.items() if k not in (*TEXT, *LINES, "experience", "projects")}
    for key in TEXT:
        raw = fields.get(key, "")
        value = _paragraph(raw) if key == "about" else _line(raw)
        if key == "booking_url":
            data[key] = _url(value)
        elif key in ("pronouns", "email"):
            data[key] = value or None
        else:
            data[key] = value
    if not data["first_name"] and data["name"]:
        data["first_name"] = data["name"].split()[0]
    for key in LINES:
        data[key] = [_line(x) for x in fields.get(key, "").splitlines() if x.strip()]
    data["experience"] = [{k: _line(r.get(k, "")) for k in GROUPS["experience"]} for r in rows(fields, "experience")]
    data["projects"] = [
        {
            "name": _line(r.get("name", "")),
            "org": _line(r.get("org", "")) or None,
            "period": _line(r.get("period", "")) or None,
            "summary": _line(r.get("summary", "")),
            "metric": _line(r.get("metric", "")) or None,
            "url": _url(r.get("url", "")),
        }
        for r in rows(fields, "projects")
    ]
    skills: dict[str, list[str]] = {}
    for r in rows(fields, "skills"):
        group = _line(r.get("group", "")) or "Skills"
        items = [_line(s) for s in r.get("items", "").split(",") if s.strip()]
        skills.setdefault(group, []).extend(items)
    data["skills"] = skills
    data["links"] = [
        {"label": _line(r.get("label", "")), "url": _url(r.get("url", "")) or ""} for r in rows(fields, "links")
    ]
    data["quick_questions"] = [
        {"label": _line(r.get("label", "")), "question": _line(r.get("question", ""))} for r in rows(fields, "quick")
    ]
    avatar = dict(base.get("avatar") or {})
    body = "F" if fields.get("body") == "F" else "M"
    if avatar.get("body") != body or not avatar.get("url"):
        avatar = {**avatar, **{k: v for k, v in avatar_for(body, avatars_dir).items() if k != "photo"}}
    data["avatar"] = avatar
    voice = fields.get("voice", "")
    data["voice"] = {"provider": "kokoro", "voice_id": voice} if kokoro and voice in dict(KOKORO_VOICES) else {}
    return data


def validate(handle: str, data: dict[str, Any], public_url: str) -> tuple[dict[str, Any] | None, dict[str, str]]:
    """(normalised data to store, {}) or (None, errors keyed by form field)."""
    errors = check_limits(data)
    if not str(data.get("name") or "").strip():
        errors["name"] = "Please enter your name."
    try:
        persona = to_persona(handle, data, public_url)
    except ValidationError as e:
        return None, {**persona_errors(e), **errors}
    if errors:
        return None, errors
    return storable(persona), {}


def data_to_form(data: dict[str, Any]) -> dict[str, Any]:
    """Values for the template, with spare blank rows in each repeating group."""
    skills = data.get("skills") or {}
    groups: dict[str, list[dict[str, str]]] = {
        "experience": [{k: str(r.get(k) or "") for k in GROUPS["experience"]} for r in data.get("experience") or []],
        "projects": [{k: str(r.get(k) or "") for k in GROUPS["projects"]} for r in data.get("projects") or []],
        "skills": [{"group": g, "items": ", ".join(items)} for g, items in skills.items()],
        "links": [
            {"label": str(r.get("label") or ""), "url": str(r.get("url") or "")} for r in data.get("links") or []
        ],
        "quick": [
            {"label": str(r.get("label") or ""), "question": str(r.get("question") or "")}
            for r in data.get("quick_questions") or []
        ],
    }
    for group, spare in SPARE_ROWS.items():
        groups[group] += [dict.fromkeys(GROUPS[group], "") for _ in range(spare)]
    return {
        **{key: str(data.get(key) or "") for key in TEXT},
        **{key: "\n".join(data.get(key) or []) for key in LINES},
        **groups,
        "body": (data.get("avatar") or {}).get("body", "M"),
        "voice": (data.get("voice") or {}).get("voice_id") or "",
    }
