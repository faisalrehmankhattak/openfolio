"""Tracks real conversation activity so the idle timer never cuts off an answer."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

from pipecat.frames.frames import (
    BotSpeakingFrame,
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    Frame,
    InterimTranscriptionFrame,
    InterruptionFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMMessagesAppendFrame,
    LLMTextFrame,
    TranscriptionFrame,
    UserSpeakingFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.observers.base_observer import BaseObserver, FramePushed

# Frames that prove someone is still there without changing who is busy.
ACTIVITY_FRAMES = (
    BotSpeakingFrame,
    UserSpeakingFrame,
    LLMTextFrame,
    TranscriptionFrame,
    InterimTranscriptionFrame,
    LLMMessagesAppendFrame,
)


class ConversationActivity(BaseObserver):
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        super().__init__(observe_every_push=False)
        self._clock = clock
        self.last_activity = clock()
        self.bot_speaking = False
        self.generating = False
        self.user_speaking = False

    def record(self, frame: Frame) -> None:
        match frame:
            case BotStartedSpeakingFrame():
                self.bot_speaking = True
            case BotStoppedSpeakingFrame():
                self.bot_speaking = False
            case LLMFullResponseStartFrame():
                self.generating = True
            case LLMFullResponseEndFrame():
                self.generating = False
            case UserStartedSpeakingFrame():
                self.user_speaking = True
            case UserStoppedSpeakingFrame():
                self.user_speaking = False
            case InterruptionFrame():
                self.bot_speaking = self.generating = False
            case _ if not isinstance(frame, ACTIVITY_FRAMES):
                return
        self.last_activity = self._clock()

    def seconds_until_idle(self, seconds: float) -> float | None:
        """Time left before the call counts as idle; None while someone is speaking or an answer is generating."""
        if self.bot_speaking or self.generating or self.user_speaking:
            return None
        return max(0.0, seconds - (self._clock() - self.last_activity))

    def is_idle(self, seconds: float) -> bool:
        return self.seconds_until_idle(seconds) == 0

    async def settle_idle(
        self, seconds: float, step: float = 1.0, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
    ) -> bool:
        """Wait for the exact idle deadline after Pipecat reports a quiet window.

        Pipecat only checks once per window, so a call that was still busy at that moment would
        otherwise stay open for a second full window. Gives up if someone is still busy after one
        more window; the next window's check takes over from there.
        """
        start = self._clock()
        while (wait := self.seconds_until_idle(seconds)) != 0:
            elapsed = self._clock() - start
            if (wait is None and elapsed >= seconds) or elapsed >= 2 * seconds:
                return False
            await sleep(step if wait is None else min(wait, step))
        return True

    async def on_push_frame(self, data: FramePushed) -> None:
        self.record(data.frame)
