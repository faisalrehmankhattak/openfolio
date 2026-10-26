from pipecat.frames.frames import MetricsFrame
from pipecat.metrics.metrics import LLMTokenUsage, LLMUsageMetricsData, TTSUsageMetricsData

from openfolio_worker.call_meter import CallClock, CallMeter
from openfolio_worker.config import Limits
from openfolio_worker.guard import MAX_TURNS, VisitorGuard
from openfolio_worker.usage import UsageLedger


def ledger(tmp_path, **limits):
    return UsageLedger(tmp_path / "usage.db", Limits(**limits), paid_voice=True)


def test_meter_records_model_and_voice_usage(tmp_path):
    usage = ledger(tmp_path)
    meter = CallMeter(usage, "demo", "v1")
    tokens = LLMTokenUsage(prompt_tokens=1200, completion_tokens=80, total_tokens=1280)
    meter.record(MetricsFrame(data=[LLMUsageMetricsData(processor="llm", value=tokens)]))
    meter.record(MetricsFrame(data=[TTSUsageMetricsData(processor="tts", value=140)]))
    assert usage.total("all", "llm_in") == 1200
    assert usage.total("persona:demo", "llm_out") == 80
    assert usage.total("visitor:v1", "tts_chars") == 140
    assert usage.total("all", "cost_usd") > 0


def test_clock_adds_call_time_in_slices(tmp_path):
    usage = ledger(tmp_path)
    now = [100.0]
    clock = CallClock(usage, "demo", None, clock=lambda: now[0])
    now[0] += 30
    clock.flush()
    now[0] += 12
    clock.flush()
    assert usage.total("all", "seconds") == 42


def test_reply_cap_never_exceeds_the_built_in_ceiling():
    assert VisitorGuard("Avery", "s", max_turns=5)._max_turns == 5
    assert VisitorGuard("Avery", "s", max_turns=10_000)._max_turns == MAX_TURNS
