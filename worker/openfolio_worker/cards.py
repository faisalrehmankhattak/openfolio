"""Publish local portfolio cards without an extra language-model round trip."""
import re
from pipecat.frames.frames import LLMMessagesAppendFrame, TranscriptionFrame
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
from pipecat.processors.frameworks.rtvi.frames import RTVIServerMessageFrame


def card_for(text):
    for card, pattern in (
        ("contact", r"\b(contact|reach|email|hire|hiring|book|linkedin)\b"),
        ("projects", r"\b(projects?|built|building|portfolio|voicebite|countify)\b"),
        ("skills", r"\b(skills?|stack|technologies|tools|expertise)\b"),
        ("experience", r"\b(experience|resume|cv|career|education|roles?|work history)\b"),
    ):
        if re.search(pattern, text, re.I):
            return card
    return None


class PortfolioCards(FrameProcessor):
    def __init__(self, persona):
        super().__init__()
        self.persona = persona

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        text = ""
        if direction == FrameDirection.DOWNSTREAM:
            if isinstance(frame, TranscriptionFrame):
                text = frame.text
            elif isinstance(frame, LLMMessagesAppendFrame):
                text = " ".join(str(m.get("content", "")) for m in frame.messages
                                if isinstance(m, dict) and m.get("role") == "user")
        card = card_for(text)
        p = self.persona
        if card:
            data = {
                "projects": {"projects": [v.model_dump() for v in p.projects]},
                "experience": {"roles": [v.model_dump() for v in p.experience], "education": p.education},
                "skills": {"skills": p.skills},
                "contact": {"email": p.email, "links": [v.model_dump() for v in p.links],
                            "booking_url": str(p.booking_url) if p.booking_url else None},
            }[card]
            await self.push_frame(RTVIServerMessageFrame(data={"type": "openfolio.card", "card": card, "data": data}))
        await self.push_frame(frame, direction)
