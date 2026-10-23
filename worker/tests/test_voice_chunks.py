import asyncio

from openfolio_worker.voice_chunks import MAX_WORDS, ClauseAggregator


def _chunks(*tokens: str) -> list[str]:
    async def run() -> list[str]:
        agg = ClauseAggregator()
        out = []
        for token in tokens:
            out += [a.text async for a in agg.aggregate(token)]
        if rest := await agg.flush():
            out.append(rest.text)
        return out

    return asyncio.run(run())


def test_splits_at_clauses_and_sentences():
    assert _chunks("I'm the AI version of Faisal, ", "and I build agents. ", "Ask me anything.") == [
        "I'm the AI version of Faisal,",
        "and I build agents.",
        "Ask me anything.",
    ]


def test_short_lead_ins_and_numbers_stay_whole():
    assert _chunks("Yes, it processed 1,000 pages a day.") == ["Yes, it processed 1,000 pages a day."]


def test_abbreviations_are_not_split():
    assert _chunks("I worked with Dr. Smith on routing.") == ["I worked with Dr. Smith on routing."]


def test_long_clause_is_capped():
    chunks = _chunks(" ".join(f"w{i}" for i in range(20)) + ".")
    assert len(chunks) == 2
    assert len(chunks[0].split()) == MAX_WORDS
