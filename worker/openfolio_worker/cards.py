"""Portfolio cards: chosen locally from the visitor's words, so no extra LLM round trip."""

from __future__ import annotations

import re
from typing import Any, Literal

from pipecat.frames.frames import Frame, LLMMessagesAppendFrame, TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.processors.frameworks.rtvi.frames import RTVIServerMessageFrame

from .persona import Persona

CardKind = Literal["contact", "projects", "skills", "experience", "message_sent"]

# Checked in order: "how do I hire you" is a contact question before a work one.
_PATTERNS: tuple[tuple[CardKind, str], ...] = (
    ("contact", r"contact|reach|email|hire|hiring|book|linkedin"),
    ("projects", r"projects?|built|building|portfolio"),
    ("skills", r"skills?|stack|technologies|tools|expertise"),
    ("experience", r"experience|resume|cv|career|education|roles?|work history"),
)


def card_for(text: str, persona: Persona | None = None) -> CardKind | None:
    """Pick the card that answers a question, if any. Naming a project shows the projects card."""
    for card, pattern in _PATTERNS:
        if re.search(rf"\b(?:{pattern})\b", text, re.IGNORECASE):
            return card
    if persona and any(re.search(rf"\b{re.escape(p.name)}\b", text, re.IGNORECASE) for p in persona.projects):
        return "projects"
    return None


def card_data(persona: Persona, card: CardKind) -> dict[str, Any]:
    p = persona
    match card:
        case "projects":
            return {"projects": [x.model_dump(mode="json") for x in p.projects]}
        case "experience":
            return {"roles": [x.model_dump(mode="json") for x in p.experience], "education": p.education}
        case "skills":
            return {"skills": p.skills}
        case "contact":
            return {
                "email": p.email,
                "links": [x.model_dump(mode="json") for x in p.links],
                "booking_url": str(p.booking_url) if p.booking_url else None,
            }
        case "message_sent":
            return {}


def card_frame(card: CardKind, data: dict[str, Any]) -> RTVIServerMessageFrame:
    return RTVIServerMessageFrame(data={"type": "openfolio.card", "card": card, "data": data})


def _visitor_text(frame: Frame) -> str:
    if isinstance(frame, TranscriptionFrame):
        return str(frame.text)
    if isinstance(frame, LLMMessagesAppendFrame):
        return " ".join(
            str(m.get("content", "")) for m in frame.messages if isinstance(m, dict) and m.get("role") == "user"
        )
    return ""


class PortfolioCards(FrameProcessor):
    """Sends a card to the widget when a visitor's question matches one."""

    def __init__(self, persona: Persona, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._persona = persona

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        text = _visitor_text(frame) if direction == FrameDirection.DOWNSTREAM else ""
        if text and (card := card_for(text, self._persona)):
            await self.push_frame(card_frame(card, card_data(self._persona, card)))
        await self.push_frame(frame, direction)
