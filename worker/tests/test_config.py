from dataclasses import replace

import pytest

from openfolio_worker.config import ConfigError, llm_extra_params, load_settings


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("MAX_SESSIONS", "lots"),
        ("MAX_SESSIONS", "0"),
        ("CALLS_PER_IP", "-1"),
        ("ICE_SERVERS", "not json"),
        ("ICE_SERVERS", '{"urls": "stun:x"}'),
        ("STT_PROVIDER", "siri"),
        ("TTS_PROVIDER", "espeak"),
    ],
)
def test_bad_values_fail_with_a_named_variable(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ConfigError, match=name):
        load_settings()


def test_unconfigured_server_lists_every_problem():
    problems = load_settings().check()
    assert any("LLM_MODEL" in p for p in problems)
    assert any("DEEPGRAM_API_KEY" in p for p in problems)
    assert any("LLM_API_KEY" in p for p in problems)


@pytest.mark.parametrize(
    "url",
    ["http://localhost:11434/v1", "http://127.0.0.1:11434/v1", "http://host.docker.internal:11434/v1"],
)
def test_local_llm_needs_no_key(settings, url):
    s = replace(settings, llm_api_key=None, llm_base_url=url)
    assert s.llm_is_local
    assert s.check() == []


def test_lookalike_host_is_not_local(settings):
    assert not replace(settings, llm_base_url="http://localhost.evil.example/v1").llm_is_local


@pytest.mark.parametrize(
    ("model", "base_url", "effort", "expected"),
    [
        ("gpt-6-luna", None, "auto", {"reasoning_effort": "none"}),
        ("gpt-5.6", None, "auto", {"reasoning_effort": "none"}),
        ("gpt-4.1-mini", None, "auto", {}),
        ("gpt-6-luna", "https://api.groq.com/openai/v1", "auto", {}),
        ("x", None, "off", {}),
        ("x", None, "low", {"reasoning_effort": "low"}),
    ],
)
def test_reasoning_effort(settings, model, base_url, effort, expected):
    s = replace(settings, llm_model=model, llm_base_url=base_url, llm_reasoning_effort=effort)
    assert llm_extra_params(s) == expected


def test_explicit_runtime_paths(monkeypatch, tmp_path):
    for name in ("PERSONAS_DIR", "INBOX_DIR", "EMBED_DIR", "AVATARS_DIR"):
        monkeypatch.setenv(name, str(tmp_path / name.lower()))
    s = load_settings()
    assert s.personas_dir == tmp_path / "personas_dir"
    assert s.inbox_dir == tmp_path / "inbox_dir"
    assert s.embed_dir == tmp_path / "embed_dir"
    assert s.avatars_dir == tmp_path / "avatars_dir"
