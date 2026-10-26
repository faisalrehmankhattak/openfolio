"""Feeds one call's usage into the ledger (usage.py) while the call runs."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from pipecat.frames.frames import Frame, MetricsFrame
from pipecat.metrics.metrics import LLMUsageMetricsData, TTSUsageMetricsData
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from .usage import UsageLedger


class CallMeter(FrameProcessor):
    """Sits after text-to-speech, where both the model's and the voice's usage reports pass."""

    def __init__(self, usage: UsageLedger, persona_id: str, visitor: str | None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._usage = usage
        self._persona = persona_id
        self._visitor = visitor

    def record(self, frame: MetricsFrame) -> None:
        for data in frame.data:
            if isinstance(data, LLMUsageMetricsData):
                tokens = data.value
                self._usage.add_llm(self._persona, self._visitor, tokens.prompt_tokens, tokens.completion_tokens)
            elif isinstance(data, TTSUsageMetricsData):
                self._usage.add_tts(self._persona, self._visitor, data.value)

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, MetricsFrame):
            self.record(frame)
        await self.push_frame(frame, direction)


class CallClock:
    """Adds call time in slices, so the caps see a long call before it ends."""

    def __init__(
        self, usage: UsageLedger, persona_id: str, visitor: str | None, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._usage = usage
        self._persona = persona_id
        self._visitor = visitor
        self._clock = clock
        self._last = clock()

    def flush(self) -> None:
        now = self._clock()
        self._usage.add_seconds(self._persona, self._visitor, now - self._last)
        self._last = now
