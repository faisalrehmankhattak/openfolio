from openfolio_worker.config import Limits
from openfolio_worker.usage import MONTH_FULL, PERSONA_FULL, TODAY_FULL, VISITOR_FULL, UsageLedger

DAY = 1_790_000_000  # 2026-09-21 UTC


def ledger(tmp_path, clock=None, **limits):
    now = clock or [DAY]
    return UsageLedger(tmp_path / "usage.db", Limits(**limits), clock=lambda: now[0]), now


def test_counts_per_server_persona_and_visitor(tmp_path):
    usage, _ = ledger(tmp_path)
    visitor = usage.visitor_key("203.0.113.9")
    usage.add_call("demo", visitor)
    usage.add_seconds("demo", visitor, 90)
    assert usage.total("all", "calls") == 1
    assert usage.total("persona:demo", "seconds") == 90
    assert usage.total(f"visitor:{visitor}", "calls") == 1
    assert usage.total("persona:other", "seconds") == 0


def test_visitor_key_is_salted_and_stable(tmp_path):
    usage, _ = ledger(tmp_path)
    key = usage.visitor_key("203.0.113.9")
    assert "203.0.113.9" not in key
    assert key == usage.visitor_key("203.0.113.9")
    usage.close()
    again, _ = ledger(tmp_path)
    assert again.visitor_key("203.0.113.9") == key  # the salt survives a restart
    assert UsageLedger(tmp_path / "other.db", Limits()).visitor_key("203.0.113.9") != key


def test_costs_follow_the_prices(tmp_path):
    usage, _ = ledger(tmp_path, price_llm_input_per_mtok=1.0, price_llm_output_per_mtok=4.0, price_stt_per_minute=0.01)
    usage.add_llm("demo", None, 1_000_000, 500_000)
    usage.add_seconds("demo", None, 120)
    assert round(usage.total("all", "cost_usd"), 4) == 3.02


def test_the_local_voice_is_free_and_a_paid_voice_is_counted(tmp_path):
    usage, _ = ledger(tmp_path)
    usage.add_tts("demo", None, 10_000)
    assert usage.total("all", "tts_chars") == 0
    usage.paid_voice = True
    usage.add_tts("demo", None, 10_000)
    assert usage.total("all", "tts_chars") == 10_000
    assert round(usage.total("all", "cost_usd"), 4) == 0.5


def test_daily_budget_refuses_new_calls_until_tomorrow(tmp_path):
    usage, now = ledger(tmp_path, daily_budget_usd=1.0, price_llm_output_per_mtok=10.0)
    assert usage.refusal("demo", None) is None
    usage.add_llm("demo", None, 0, 100_000)  # $1.00
    refusal = usage.refusal("demo", None)
    assert refusal is not None
    assert (refusal.status, refusal.message) == (503, TODAY_FULL)
    now[0] += 86_400
    assert usage.refusal("demo", None) is None


def test_monthly_budget_holds_across_days(tmp_path):
    usage, now = ledger(tmp_path, monthly_budget_usd=2.0, daily_budget_usd=0, price_llm_output_per_mtok=10.0)
    usage.add_llm("demo", None, 0, 150_000)
    now[0] += 86_400
    usage.add_llm("demo", None, 0, 50_000)
    assert usage.refusal("demo", None).message == MONTH_FULL
    now[0] += 86_400 * 15  # 2026-10-07: a new month
    assert usage.refusal("demo", None) is None


def test_minute_and_token_caps_hold_even_with_zero_prices(tmp_path):
    usage, _ = ledger(
        tmp_path, daily_max_minutes=2, price_stt_per_minute=0, price_llm_input_per_mtok=0, price_llm_output_per_mtok=0
    )
    usage.add_seconds("demo", None, 119)
    assert usage.refusal("demo", None) is None
    usage.add_seconds("demo", None, 1)
    assert usage.refusal("demo", None).message == TODAY_FULL
    tokens, _ = ledger(
        tmp_path / "t", daily_max_llm_tokens=1000, price_llm_input_per_mtok=0, price_llm_output_per_mtok=0
    )
    tokens.add_llm("demo", None, 600, 400)
    assert tokens.refusal("demo", None).message == TODAY_FULL


def test_one_persona_cannot_use_the_whole_day(tmp_path):
    usage, _ = ledger(tmp_path, persona_minutes_per_day=1)
    usage.add_seconds("busy", None, 60)
    assert usage.refusal("busy", None).message == PERSONA_FULL
    assert usage.refusal("quiet", None) is None


def test_visitor_daily_call_cap(tmp_path):
    usage, _ = ledger(tmp_path, visitor_calls_per_day=2)
    me, other = usage.visitor_key("198.51.100.1"), usage.visitor_key("198.51.100.2")
    usage.add_call("demo", me)
    usage.add_call("demo", me)
    refusal = usage.refusal("demo", me)
    assert refusal is not None
    assert (refusal.status, refusal.message) == (429, VISITOR_FULL)
    assert usage.refusal("demo", other) is None


def test_zero_turns_a_cap_off(tmp_path):
    usage, _ = ledger(
        tmp_path,
        monthly_budget_usd=0,
        daily_budget_usd=0,
        daily_max_minutes=0,
        monthly_max_minutes=0,
        persona_minutes_per_day=0,
    )
    usage.add_seconds("demo", None, 10_000_000)
    assert usage.refusal("demo", None) is None


def test_summary_reports_server_totals_only(tmp_path):
    usage, _ = ledger(tmp_path)
    usage.add_call("demo", usage.visitor_key("203.0.113.9"))
    summary = usage.summary()
    assert summary["day"]["calls"] == 1
    assert summary["month"]["calls"] == 1
    assert "visitor" not in str(summary)
