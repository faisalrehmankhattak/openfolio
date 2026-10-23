import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from openfolio_worker.tools import SessionResources, leave_message


def _call(res, **kwargs):
    params = SimpleNamespace(
        app_resources=res, result_callback=AsyncMock(), llm=SimpleNamespace(push_frame=AsyncMock())
    )
    asyncio.run(leave_message(params, **kwargs))
    return params.result_callback.call_args.args[0], params


def test_message_is_saved_cleaned_and_confirmed(persona, tmp_path):
    res = SessionResources(persona=persona, inbox_dir=tmp_path, session_id="s1")
    result, params = _call(res, visitor_name="Ada\x00", visitor_email="ada@example.com", message="Let's talk")
    assert result == {"saved": True}
    entry = json.loads((tmp_path / "faisal.jsonl").read_text())
    assert entry["name"] == "Ada"
    assert entry["message"] == "Let's talk"
    assert params.llm.push_frame.call_args.args[0].data["card"] == "message_sent"


def test_invalid_email_is_refused(persona, tmp_path):
    res = SessionResources(persona=persona, inbox_dir=tmp_path, session_id="s1")
    result, _ = _call(res, visitor_name="Ada", visitor_email="nope", message="hi")
    assert result["saved"] is False
    assert not (tmp_path / "faisal.jsonl").exists()


def test_messages_per_call_are_capped(persona, tmp_path):
    res = SessionResources(persona=persona, inbox_dir=tmp_path, session_id="s1")
    for _ in range(2):
        _call(res, visitor_name="A", visitor_email="a@example.com", message="hi")
    result, _ = _call(res, visitor_name="A", visitor_email="a@example.com", message="hi")
    assert result["saved"] is False
    assert len((tmp_path / "faisal.jsonl").read_text().splitlines()) == 2
