"""Every persona the server can answer as: files from the personas directory plus, in cloud mode,
the members' live personas from the database.

File personas are loaded once at startup. Cloud personas are swapped in whenever a member's
profile goes live, changes, pauses or is deleted (cloud/studio_service.py refreshes them), so
/v1/personas, /offer and the bot always see the approved version. Unpublished drafts are never in
the registry: they are reachable only through the preview hook, which checks the owner's session.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Request

from .persona import Persona

# "<handle>~preview" asks for a working copy (owner) or a submitted one (the site owner reviewing it).
# "~" is never part of a persona id, so a preview can't be confused with a published persona.
PREVIEW_SUFFIX = "~preview"

PreviewHook = Callable[[Request, str], Awaitable[Persona | None]]


class PersonaRegistry:
    def __init__(self, files: dict[str, Persona]) -> None:
        self.files: dict[str, Persona] = dict(files)
        self._live: dict[str, Persona] = {}
        self.preview: PreviewHook | None = None

    def get(self, persona_id: str) -> Persona | None:
        # File personas win: their ids are reserved handles, so a member can never shadow one.
        return self.files.get(persona_id) or self._live.get(persona_id)

    def is_dynamic(self, persona_id: str) -> bool:
        return persona_id not in self.files and persona_id in self._live

    def replace_live(self, personas: dict[str, Persona]) -> None:
        """Swap in the full set of live cloud personas (one assignment, so readers never see half a set)."""
        self._live = {pid: p for pid, p in personas.items() if pid not in self.files}

    @property
    def live_ids(self) -> list[str]:
        return sorted(self._live)

    def origins(self) -> set[str]:
        """Every origin some persona may be embedded on."""
        found: set[str] = set()
        for p in (*self.files.values(), *self._live.values()):
            found |= p.origins
        return found
