import asyncio

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    InterruptionFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMMessagesAppendFrame,
    UserStartedSpeakingFrame,
)

from openfolio_worker.activity import ConversationActivity


def test_long_speech_does_not_timeout_and_gets_full_idle_window_afterwards():
    now = [0.0]
    activity = ConversationActivity(clock=lambda: now[0])
    activity.record(BotStartedSpeakingFrame())
    now[0] = 125
    assert not activity.is_idle(60)
    activity.record(BotStoppedSpeakingFrame())
    now[0] = 184
    assert not activity.is_idle(60)
    now[0] = 185
    assert activity.is_idle(60)


def test_generation_and_typed_messages_count_as_activity():
    now = [0.0]
    activity = ConversationActivity(clock=lambda: now[0])
    activity.record(LLMFullResponseStartFrame())
    now[0] = 90
    assert not activity.is_idle(60)
    activity.record(LLMFullResponseEndFrame())
    now[0] = 120
    activity.record(LLMMessagesAppendFrame(messages=[]))
    now[0] = 179
    assert not activity.is_idle(60)
    now[0] = 180
    assert activity.is_idle(60)


def test_interruption_clears_busy_state():
    now = [0.0]
    activity = ConversationActivity(clock=lambda: now[0])
    activity.record(BotStartedSpeakingFrame())
    activity.record(InterruptionFrame())
    now[0] = 60
    assert activity.is_idle(60)


def test_seconds_until_idle_counts_down_from_last_activity():
    now = [0.0]
    activity = ConversationActivity(clock=lambda: now[0])
    now[0] = 10
    assert activity.seconds_until_idle(15) == 5
    now[0] = 20
    assert activity.seconds_until_idle(15) == 0
    activity.record(LLMFullResponseStartFrame())
    assert activity.seconds_until_idle(15) is None


def _settle(activity: ConversationActivity, now: list[float], seconds: float, busy_until: float | None = None) -> bool:
    async def fake_sleep(delay: float) -> None:
        now[0] += delay
        if busy_until is not None and now[0] >= busy_until and activity.bot_speaking:
            activity.record(BotStoppedSpeakingFrame())

    return asyncio.run(activity.settle_idle(seconds, sleep=fake_sleep))


def test_settle_idle_waits_for_the_exact_deadline():
    now = [0.0]
    activity = ConversationActivity(clock=lambda: now[0])
    now[0] = 10
    assert _settle(activity, now, 15)
    assert now[0] == 15


def test_settle_idle_counts_from_when_the_bot_stops_speaking():
    now = [0.0]
    activity = ConversationActivity(clock=lambda: now[0])
    activity.record(BotStartedSpeakingFrame())
    assert _settle(activity, now, 15, busy_until=3)
    assert now[0] == 18  # not a whole extra window


def test_settle_idle_gives_up_while_the_conversation_continues():
    now = [0.0]
    activity = ConversationActivity(clock=lambda: now[0])
    activity.record(UserStartedSpeakingFrame())
    assert not _settle(activity, now, 15)
