import json

import pytest

from openfolio_worker.persona import Persona, PersonaError, build_system_prompt, load_personas

from conftest import PERSONAS


def _raw() -> dict:
    return json.loads((PERSONAS / "demo.json").read_text())


def test_personas_load(persona):
    assert persona.first_name == "Avery"
    assert persona.origins == {"https://example.com"}


def test_prompt_carries_rules_then_facts(persona):
    prompt = build_system_prompt(persona)
    assert "AI version of Avery" in prompt
    assert "fictional demo character" in prompt
    assert "600 scripted conversations" in prompt
    assert prompt.index("# Honesty") < prompt.index("# About Avery")
    assert "- - " not in prompt


def test_public_view_hides_prompt_material(persona):
    view = persona.public_view()
    assert set(view) == {"id", "name", "first_name", "title", "tagline", "avatar", "quick_questions"}
    assert "guardrails" not in json.dumps(view)


@pytest.mark.parametrize(
    "change",
    [
        {"tagline_typo": "x"},
        {"allowed_origins": ["https://example.com/path"]},
        {"allowed_origins": ["ftp://example.com"]},
        {"avatar": {"url": "http://cdn.example.com/a.glb"}},
        {"links": [{"label": "x", "url": "javascript:alert(1)"}]},
        {"email": "not-an-email"},
        {"max_session_seconds": 5},
    ],
)
def test_invalid_persona_rejected(change):
    with pytest.raises(ValueError):  # noqa: PT011
        Persona.model_validate(_raw() | change)


def test_id_must_match_file_name(tmp_path):
    (tmp_path / "other.json").write_text(json.dumps(_raw()))
    with pytest.raises(PersonaError, match="must match the file name"):
        load_personas(tmp_path)


def test_broken_json_names_the_file(tmp_path):
    (tmp_path / "broken.json").write_text("{")
    with pytest.raises(PersonaError, match=r"broken\.json"):
        load_personas(tmp_path)


def test_schema_file_is_current():
    schema = json.loads((PERSONAS.parent / "persona.schema.json").read_text())
    assert schema == Persona.model_json_schema(by_alias=True), "run: uv run openfolio-schema > ../persona.schema.json"
