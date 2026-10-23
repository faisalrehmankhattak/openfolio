"""Shorter text pieces for the local voice, so speech starts before a whole sentence is synthesized."""

from __future__ import annotations

from pipecat.utils.text.base_text_aggregator import Aggregation, TextType
from pipecat.utils.text.simple_text_aggregator import SimpleTextAggregator, _LookaheadState

CLAUSE_MARKS = ",;:"
MIN_WORDS = 3  # shorter fragments lose natural intonation
MAX_WORDS = 12  # caps synthesis time when the model writes a long clause without punctuation


class ClauseAggregator(SimpleTextAggregator):
    """Cuts streamed LLM text at clause boundaries as well as at sentence ends.

    Kokoro on a CPU is only ~1.3x faster than real time and plays nothing until a piece is
    finished: a 17-word sentence waits ~4.6 s for its first audio, a 5-word clause ~1.3 s.
    """

    async def _check_sentence_with_lookahead(self, char: str) -> Aggregation | None:
        if result := await super()._check_sentence_with_lookahead(char):
            return result
        # Cut only at a space, so "1,000" stays whole, and never while a possible sentence end is pending.
        if not char.isspace() or self._lookahead_state is not _LookaheadState.IDLE:
            return None
        text = self._text.strip()
        words = len(text.split())
        if (text[-1:] in CLAUSE_MARKS and words >= MIN_WORDS) or words >= MAX_WORDS:
            self._text = ""
            return Aggregation(text=text, type=TextType.SENTENCE)
        return None
