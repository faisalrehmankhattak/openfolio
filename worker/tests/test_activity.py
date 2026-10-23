from openfolio_worker.activity import ConversationActivity
from pipecat.frames.frames import (
    BotStartedSpeakingFrame, BotStoppedSpeakingFrame,
    LLMFullResponseStartFrame, LLMFullResponseEndFrame,
    LLMMessagesAppendFrame, InterruptionFrame,
)


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
