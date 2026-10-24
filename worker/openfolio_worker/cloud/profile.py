"""A member's persona: handle rules, defaults, cloud limits, safety flags and the Persona that goes live.

The stored JSON is a Persona without id and allowed_origins; both are added when it is loaded, so a
member can never point their persona at another id or another site.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ..guard import looks_like_injection
from ..persona import Persona

HANDLE_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,28}[a-z0-9])$")
# Paths and words that must never become someone's public page or persona id.
RESERVED_HANDLES = frozenset(
    [
        "about",
        "account",
        "admin",
        "api",
        "app",
        "apps",
        "assets",
        "avatars",
        "billing",
        "blog",
        "cloud",
        "contact",
        "dashboard",
        "demo",
        "docs",
        "embed",
        "favicon",
        "feedback",
        "healthz",
        "help",
        "home",
        "invite",
        "join",
        "livez",
        "login",
        "logout",
        "mail",
        "me",
        "new",
        "news",
        "null",
        "openfolio",
        "p",
        "pricing",
        "privacy",
        "profile",
        "register",
        "reset",
        "robots",
        "root",
        "security",
        "settings",
        "signin",
        "signout",
        "signup",
        "sitemap",
        "static",
        "status",
        "studio",
        "support",
        "system",
        "team",
        "terms",
        "test",
        "undefined",
        "user",
        "users",
        "v1",
        "webhooks",
        "well-known",
        "www",
        "you",
    ]
)
DEFAULT_QUESTIONS = (
    ("Me", "Who are you, in a nutshell?"),
    ("Projects", "What are you proudest of building?"),
    ("Skills", "What are your strongest skills?"),
    ("Contact", "How can I get in touch?"),
)
KOKORO_VOICES = (
    ("af_heart", "Heart · American, warm"),
    ("af_bella", "Bella · American, bright"),
    ("am_michael", "Michael · American, calm"),
    ("am_fenrir", "Fenrir · American, deep"),
    ("bf_emma", "Emma · British, clear"),
    ("bm_george", "George · British, steady"),
)

# Cloud limits on top of the Persona model, so one member's profile stays a profile.
TEXT_LIMITS = {
    "name": 80,
    "first_name": 40,
    "pronouns": 30,
    "title": 120,
    "tagline": 200,
    "about": 2500,
}
LIST_LIMITS = {
    "highlights": (10, 300),
    "education": (10, 200),
    "awards": (10, 200),
    "guardrails": (12, 300),
}
ROW_LIMITS = {
    "experience": (15, {"company": 120, "title": 120, "period": 60, "summary": 700}),
    "projects": (12, {"name": 120, "org": 100, "period": 60, "summary": 700, "metric": 200, "url": 300}),
    "links": (10, {"label": 60, "url": 300}),
    "quick_questions": (6, {"label": 24, "question": 200}),
}
SKILL_GROUPS, SKILLS_PER_GROUP, SKILL_CHARS = 8, 25, 60


def handle_problem(handle: str, taken: set[str] | frozenset[str] = frozenset()) -> str | None:
    """A friendly reason the handle can't be used, or None."""
    if not HANDLE_RE.fullmatch(handle):
        return "Use 3 to 30 lowercase letters, numbers or hyphens, starting and ending with a letter or number."
    if handle in RESERVED_HANDLES or handle in taken:
        return "That handle is taken. Try another."
    return None


def origins_for(handle: str, public_url: str) -> list[str]:
    """Where a member's persona may run. Hook: a later stage adds their verified custom domains here."""
    del handle  # used once verified domains exist
    return [public_url]


def avatar_for(body: str, avatars_dir: Path, photo: str | None = None) -> dict[str, Any]:
    """The stock 3D avatar for a body type. A female mesh is used when the server has one."""
    female = body == "F" and (avatars_dir / "demo-female.glb").exists()
    return {
        "kind": "mesh",
        "url": "avatars/demo-female.glb" if female else "avatars/demo.glb?v=male-1",
        "body": "F" if body == "F" else "M",
        "image": None if body == "F" else "avatars/demo-portrait.jpg",
        "photo": photo,
    }


def photo_path(handle: str, file_id: int) -> str:
    return f"p/{handle}/photo-{file_id}.jpg"


def default_data(name: str, avatars_dir: Path) -> dict[str, Any]:
    clean = " ".join(name.split())[:80]
    return {
        "name": clean,
        "first_name": clean.split()[0] if clean else "",
        "title": "",
        "tagline": "",
        "about": "",
        "quick_questions": [{"label": label, "question": q} for label, q in DEFAULT_QUESTIONS],
        "avatar": avatar_for("M", avatars_dir),
    }


def to_persona(handle: str, data: dict[str, Any], public_url: str) -> Persona:
    """The Persona the widget, the prompt and the bot use. Raises ValidationError."""
    clean = {k: v for k, v in data.items() if k not in ("id", "allowed_origins", "$schema", "schema_")}
    return Persona.model_validate({**clean, "id": handle, "allowed_origins": origins_for(handle, public_url)})


def storable(persona: Persona) -> dict[str, Any]:
    return persona.model_dump(mode="json", exclude={"id", "allowed_origins", "schema_"})


def check_limits(data: dict[str, Any]) -> dict[str, str]:
    """Errors keyed by form field name, for limits the Persona model doesn't have."""
    errors: dict[str, str] = {}
    for key, limit in TEXT_LIMITS.items():
        if len(str(data.get(key) or "")) > limit:
            errors[key] = f"Keep this under {limit} characters."
    for key, (count, chars) in LIST_LIMITS.items():
        items = data.get(key) or []
        if len(items) > count:
            errors[key] = f"Add up to {count} lines."
        elif any(len(item) > chars for item in items):
            errors[key] = f"Keep each line under {chars} characters."
    for key, (count, fields) in ROW_LIMITS.items():
        rows = data.get(key) or []
        group = "quick" if key == "quick_questions" else key
        if len(rows) > count:
            errors[group] = f"Add up to {count}."
        for i, row in enumerate(rows):
            for name, chars in fields.items():
                if len(str(row.get(name) or "")) > chars:
                    errors[f"{group}-{i}-{name}"] = f"Keep this under {chars} characters."
    skills = data.get("skills") or {}
    if len(skills) > SKILL_GROUPS:
        errors["skills"] = f"Add up to {SKILL_GROUPS} groups."
    for i, (group, items) in enumerate(skills.items()):
        if len(group) > SKILL_CHARS:
            errors[f"skills-{i}-group"] = f"Keep this under {SKILL_CHARS} characters."
        if len(items) > SKILLS_PER_GROUP or any(len(s) > SKILL_CHARS for s in items):
            errors[f"skills-{i}-items"] = f"Up to {SKILLS_PER_GROUP} skills, each under {SKILL_CHARS} characters."
    return errors


_FRIENDLY = {
    "url_parsing": "Use a full web address, such as https://example.com.",
    "url_scheme": "Use a web address starting with https:// or http://.",
    "url_type": "Use a full web address, such as https://example.com.",
    "url_syntax_violation": "Use a full web address, such as https://example.com.",
    "missing": "This is required.",
    "string_too_short": "This is required.",
}


def _field_key(loc: tuple[int | str, ...]) -> str:
    parts = [str(p) for p in loc]
    if parts and parts[0] == "quick_questions":
        parts[0] = "quick"
    if parts and parts[0] == "avatar":
        return "body"
    if parts and parts[0] == "voice":
        return "voice"
    return "-".join(parts[:3])


def persona_errors(e: ValidationError) -> dict[str, str]:
    errors: dict[str, str] = {}
    for err in e.errors():
        key = _field_key(tuple(err["loc"]))
        if err["type"] == "string_pattern_mismatch" and key == "email":
            message = "Enter a valid email address."
        elif err["type"] in ("string_too_long", "too_long"):
            limit = (err.get("ctx") or {}).get("max_length")
            message = (
                f"Keep this under {limit} characters." if err["type"] == "string_too_long" else f"Add up to {limit}."
            )
        else:
            message = _FRIENDLY.get(err["type"], "Please check this field.")
        errors.setdefault(key, message)
    return errors


def _walk(value: Any, path: str) -> list[tuple[str, str]]:
    if isinstance(value, str):
        return [(path, value)]
    if isinstance(value, dict):
        return [hit for k, v in value.items() for hit in _walk(v, f"{path} › {k}" if path else str(k))]
    if isinstance(value, list):
        return [hit for i, v in enumerate(value) for hit in _walk(v, f"{path} {i + 1}")]
    return []


_FLAGGED_FIELDS = (
    "name",
    "first_name",
    "pronouns",
    "title",
    "tagline",
    "about",
    "highlights",
    "experience",
    "projects",
    "skills",
    "education",
    "awards",
    "links",
    "quick_questions",
    "guardrails",
)


def find_flags(data: dict[str, Any], source: str) -> list[dict[str, str]]:
    """Text that reads like an instruction to an AI (guard.py's screen), for the member and the reviewer."""
    flags = []
    for key in _FLAGGED_FIELDS:
        for path, text in _walk(data.get(key), key.replace("_", " ")):
            if looks_like_injection(text):
                flags.append({"field": path, "excerpt": " ".join(text.split())[:140], "source": source})
    return flags[:20]


def missing_for_review(data: dict[str, Any]) -> list[str]:
    """What a profile needs before the owner can review it."""
    missing = []
    for key, label in (("name", "your name"), ("title", "a title"), ("tagline", "a tagline"), ("about", "an about")):
        if not str(data.get(key) or "").strip():
            missing.append(label)
    if not (data.get("avatar") or {}).get("photo"):
        missing.append("a photo")
    if not data.get("experience") and not data.get("projects"):
        missing.append("at least one role or project")
    return missing


def current_employer(data: dict[str, Any]) -> str | None:
    """The company of a role marked as current, for worksFor in the public page's structured data."""
    for role in data.get("experience") or []:
        if re.search(r"\b(present|current|now|today)\b", str(role.get("period", "")), re.IGNORECASE):
            return str(role.get("company") or "") or None
    return None
