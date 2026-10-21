"""Tools the persona can call. Each one puts a card on the visitor's screen.

A tool pushes an RTVI server message that the widget renders as a card, then
returns a short result so the model knows the card is showing and can talk
about it instead of reading it out.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from loguru import logger
from pipecat.processors.frameworks.rtvi.frames import RTVIServerMessageFrame
from pipecat.services.llm_service import FunctionCallParams

import re

from .guard import clean
from .persona import Persona

EMAIL = re.compile(r"[^@\s]{1,64}@[^@\s]{1,190}\.[A-Za-z]{2,24}")


@dataclass
class SessionResources:
    """Shared with every tool call through PipelineWorker(app_resources=...)."""

    persona: Persona
    inbox_dir: Path
    session_id: str
    messages_left: int = 2  # leave_message calls allowed per conversation


async def _show(params: FunctionCallParams, card: str, data: dict) -> None:
    await params.llm.push_frame(
        RTVIServerMessageFrame(data={"type": "openfolio.card", "card": card, "data": data})
    )


async def show_projects(params: FunctionCallParams):
    """Show the owner's projects on screen as cards. Use when the visitor asks about projects or work."""
    res: SessionResources = params.app_resources
    projects = [p.model_dump() for p in res.persona.projects]
    await _show(params, "projects", {"projects": projects})
    await params.result_callback({"shown": [p["name"] for p in projects]})


async def show_experience(params: FunctionCallParams):
    """Show the owner's work history on screen. Use for questions about experience, roles or the resume."""
    res: SessionResources = params.app_resources
    roles = [r.model_dump() for r in res.persona.experience]
    await _show(params, "experience", {"roles": roles, "education": res.persona.education})
    await params.result_callback({"shown": len(roles)})


async def show_skills(params: FunctionCallParams):
    """Show the owner's skills on screen, grouped by area."""
    res: SessionResources = params.app_resources
    await _show(params, "skills", {"skills": res.persona.skills})
    await params.result_callback({"shown": list(res.persona.skills)})


async def show_contact(params: FunctionCallParams):
    """Show how to reach the real owner: email, links and a booking link if there is one."""
    p: Persona = params.app_resources.persona
    data = {
        "email": p.email,
        "links": [link.model_dump() for link in p.links],
        "booking_url": str(p.booking_url) if p.booking_url else None,
    }
    await _show(params, "contact", data)
    await params.result_callback({"shown": True, "can_book": bool(p.booking_url)})


async def leave_message(
    params: FunctionCallParams, visitor_name: str, visitor_email: str, message: str
):
    """Pass a message from the visitor to the real owner. Ask for their name, email and message first.

    Args:
        visitor_name: The visitor's name.
        visitor_email: An email address the owner can reply to.
        message: What the visitor wants the owner to know.
    """
    res: SessionResources = params.app_resources
    if res.messages_left <= 0:
        await params.result_callback({"saved": False, "reason": "this conversation already sent its messages"})
        return
    visitor_name, visitor_email, message = clean(visitor_name)[:100], clean(visitor_email)[:200], clean(message)[:1500]
    if not EMAIL.fullmatch(visitor_email) or not message:
        await params.result_callback({"saved": False, "reason": "need a valid email address and a message"})
        return
    res.messages_left -= 1
    res.inbox_dir.mkdir(parents=True, exist_ok=True)
    entry = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "persona": res.persona.id,
        "session": res.session_id,
        "name": visitor_name[:200],
        "email": visitor_email[:200],
        "message": message,
    }
    with (res.inbox_dir / f"{res.persona.id}.jsonl").open("a") as f:
        f.write(json.dumps(entry) + "\n")
    logger.info(f"Saved a message for {res.persona.id} from {visitor_email}")
    await _show(params, "message_sent", {"name": visitor_name})
    await params.result_callback({"saved": True})


ALL_TOOLS = [show_projects, show_experience, show_skills, show_contact, leave_message]
