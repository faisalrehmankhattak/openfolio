from pathlib import Path

from openfolio_worker.persona import build_system_prompt, load_personas

PERSONAS = Path(__file__).resolve().parents[2] / "personas"


def test_personas_load_and_ids_match_files():
    personas = load_personas(PERSONAS)
    assert "faisal" in personas


def test_prompt_carries_rules_and_facts():
    p = load_personas(PERSONAS)["faisal"]
    prompt = build_system_prompt(p)
    assert "AI version of Faisal" in prompt
    assert "Never name restaurant brands" in prompt
    assert "low 70s to over 90%" in prompt
    assert "- - " not in prompt


def test_public_view_hides_prompt_material():
    view = load_personas(PERSONAS)["faisal"].public_view()
    assert set(view) == {"id", "name", "first_name", "title", "tagline", "avatar", "quick_questions"}


def test_reasoning_effort_auto():
    from dataclasses import replace

    from openfolio_worker.config import llm_extra_params, load_settings

    s = load_settings()
    assert llm_extra_params(replace(s, llm_model="gpt-6-luna", llm_base_url=None, llm_reasoning_effort="auto")) == {"reasoning_effort": "none"}
    assert llm_extra_params(replace(s, llm_model="gpt-5.6", llm_base_url=None, llm_reasoning_effort="auto")) == {"reasoning_effort": "none"}
    assert llm_extra_params(replace(s, llm_model="gpt-4.1-mini", llm_base_url=None, llm_reasoning_effort="auto")) == {}
    assert llm_extra_params(replace(s, llm_model="gpt-6-luna", llm_base_url="https://api.groq.com/openai/v1", llm_reasoning_effort="auto")) == {}
    assert llm_extra_params(replace(s, llm_model="x", llm_reasoning_effort="off")) == {}
    assert llm_extra_params(replace(s, llm_model="x", llm_reasoning_effort="low")) == {"reasoning_effort": "low"}
