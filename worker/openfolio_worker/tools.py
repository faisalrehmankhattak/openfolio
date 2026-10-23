"""The one tool the persona can call: pass a visitor's message to the owner."""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger
from pipecat.services.llm_service import FunctionCallParams

from .cards import card_frame
from .guard import clean
from .persona import Persona

EMAIL = re.compile(r"[^@\s]{1,64}@[^@\s]{1,190}\.[A-Za-z]{2,24}")
MESSAGES_PER_CALL = 2


@dataclass
class SessionResources:
    """Shared with every tool call through `PipelineWorker(app_resources=...)`."""

    persona: Persona
    inbox_dir: Path
    session_id: str
    messages_left: int = MESSAGES_PER_CALL


def _append(path: Path, entry: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


async def leave_message(params: FunctionCallParams, visitor_name: str, visitor_email: str, message: str) -> None:
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
    name, email, text = clean(visitor_name)[:100], clean(visitor_email)[:200], clean(message)[:1500]
    if not EMAIL.fullmatch(email) or not text:
        await params.result_callback({"saved": False, "reason": "need a valid email address and a message"})
        return

    res.messages_left -= 1
    entry = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "persona": res.persona.id,
        "session": res.session_id,
        "name": name,
        "email": email,
        "message": text,
    }
    await asyncio.to_thread(_append, res.inbox_dir / f"{res.persona.id}.jsonl", entry)
    logger.info(f"[{res.session_id}] saved a visitor message for {res.persona.id}")
    await params.llm.push_frame(card_frame("message_sent", {"name": name}))
    await params.result_callback({"saved": True})
