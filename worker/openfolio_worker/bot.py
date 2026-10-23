"""One conversation: the Pipecat pipeline for a single visitor.

    mic -> VAD/turns -> speech-to-text -> guard -> cards -> LLM -> text-to-speech -> speaker

The face is animated in the browser from the audio, so the server needs no GPU.
"""

from __future__ import annotations

import asyncio
from typing import Any

from loguru import logger
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import (
    BotSpeakingFrame,
    InterimTranscriptionFrame,
    LLMMessagesAppendFrame,
    LLMRunFrame,
    TranscriptionFrame,
    UserSpeakingFrame,
    UserStartedSpeakingFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker, ProcessorUnusablePolicy
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair, LLMUserAggregatorParams
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.services.stt_service import STTService
from pipecat.services.tts_service import TTSService
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
from pipecat.workers.runner import WorkerRunner

from .activity import ConversationActivity
from .cards import PortfolioCards
from .config import Settings, llm_extra_params
from .guard import VisitorGuard, ended
from .persona import Persona, build_system_prompt
from .tools import SessionResources, leave_message
from .voice_chunks import ClauseAggregator

MAX_ANSWER_TOKENS = 300  # spoken answers are short; this also caps the cost of one reply

# Frames that reset Pipecat's idle timer. ConversationActivity double-checks before hanging up.
IDLE_RESET_FRAMES = (
    BotSpeakingFrame,
    InterimTranscriptionFrame,
    TranscriptionFrame,
    UserSpeakingFrame,
    UserStartedSpeakingFrame,
    LLMMessagesAppendFrame,
)


def make_stt(s: Settings) -> STTService:
    if s.stt_provider == "whisper":
        from pipecat.services.whisper.stt import WhisperSTTService

        return WhisperSTTService()
    from pipecat.services.deepgram.stt import DeepgramSTTService

    return DeepgramSTTService(api_key=s.deepgram_api_key or "")


def _share_kokoro_model() -> None:
    """Load the ~300 MB Kokoro model once per process instead of on every call."""
    import pipecat.services.kokoro.tts as kokoro_tts

    if getattr(kokoro_tts, "_openfolio_shared", False):
        return
    original = kokoro_tts.Kokoro  # type: ignore[attr-defined]
    cache: dict[tuple[str, str], Any] = {}

    def shared(model_path: str, voices_path: str) -> Any:
        key = (model_path, voices_path)
        if key not in cache:
            cache[key] = original(model_path, voices_path)
        return cache[key]

    kokoro_tts.Kokoro = shared  # type: ignore[attr-defined,assignment]
    kokoro_tts._openfolio_shared = True  # type: ignore[attr-defined]


def warm_up_voice(s: Settings) -> None:
    """Load and exercise the local voice before the first visitor arrives."""
    if s.tts_provider != "kokoro":
        return
    from pipecat.services.kokoro.tts import KokoroTTSService

    _share_kokoro_model()
    service = KokoroTTSService(settings=KokoroTTSService.Settings(voice=s.kokoro_voice))
    service._kokoro.create("Ready.", voice=s.kokoro_voice, speed=1.0, lang="en-us")


def make_tts(s: Settings, persona: Persona) -> TTSService:
    if (persona.voice.provider or s.tts_provider) == "elevenlabs":
        from pipecat.services.elevenlabs.tts import ElevenLabsTTSService

        return ElevenLabsTTSService(
            api_key=s.elevenlabs_api_key or "",
            settings=ElevenLabsTTSService.Settings(
                voice=persona.voice.voice_id or s.elevenlabs_voice_id, model=s.elevenlabs_model
            ),
        )
    from pipecat.services.kokoro.tts import KokoroTTSService

    _share_kokoro_model()
    tts = KokoroTTSService(settings=KokoroTTSService.Settings(voice=persona.voice.voice_id or s.kokoro_voice))
    # Pipecat 1.13 has no option for this; streaming voices such as ElevenLabs keep sentence pieces.
    tts._text_aggregator = ClauseAggregator(language=tts._text_aggregator.language)  # type: ignore[no-untyped-call]
    return tts


def make_llm(s: Settings, persona: Persona) -> OpenAILLMService:
    """Any OpenAI-compatible endpoint: OpenAI, Groq, OpenRouter, Ollama, vLLM."""
    return OpenAILLMService(
        api_key=s.llm_api_key or "not-needed",
        base_url=s.llm_base_url,
        settings=OpenAILLMService.Settings(
            model=s.llm_model,
            system_instruction=build_system_prompt(persona),
            max_completion_tokens=MAX_ANSWER_TOKENS,
            extra=llm_extra_params(s),
        ),
    )


async def run_conversation(
    connection: SmallWebRTCConnection, persona: Persona, settings: Settings, session_id: str
) -> None:
    transport = SmallWebRTCTransport(
        webrtc_connection=connection,
        params=TransportParams(audio_in_enabled=True, audio_out_enabled=True),
    )
    context = LLMContext(tools=[leave_message])
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context, user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer())
    )
    pipeline = Pipeline(
        [
            transport.input(),
            make_stt(settings),
            VisitorGuard(persona.first_name, session_id),
            PortfolioCards(persona),
            user_aggregator,
            make_llm(settings, persona),
            make_tts(settings, persona),
            transport.output(),
            assistant_aggregator,
        ]
    )

    activity = ConversationActivity()
    worker = PipelineWorker(
        pipeline,
        observers=[activity],
        params=PipelineParams(enable_metrics=True, enable_usage_metrics=True),
        app_resources=SessionResources(persona=persona, inbox_dir=settings.inbox_dir, session_id=session_id),
        processor_unusable_policy=ProcessorUnusablePolicy.END,
        idle_timeout_secs=persona.idle_seconds,
        idle_timeout_frames=IDLE_RESET_FRAMES,
        cancel_on_idle_timeout=False,
    )
    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(worker)

    @transport.event_handler("on_client_connected")
    async def on_client_connected(_transport: Any, _client: Any) -> None:
        logger.info(f"[{session_id}] visitor connected to {persona.id}")
        context.add_message(
            {
                "role": "developer",
                "content": f"Greet the visitor in one or two sentences. Say you are the AI version of "
                f"{persona.first_name} and ask what they would like to know.",
            }
        )
        await worker.queue_frames([LLMRunFrame()])

    @worker.event_handler("on_idle_timeout")
    async def on_idle_timeout(_worker: Any) -> None:
        # Pipecat checks once per window; finishing at the exact deadline keeps silence from lasting two windows.
        if wait := activity.seconds_until_idle(persona.idle_seconds):
            await asyncio.sleep(wait)
        if not activity.is_idle(persona.idle_seconds):
            return
        logger.info(f"[{session_id}] no activity for {persona.idle_seconds}s; hanging up")
        await worker.queue_frames([ended("idle")])
        await asyncio.sleep(0.5)  # let the message reach the browser before the connection closes
        await runner.cancel()

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(_transport: Any, _client: Any) -> None:
        logger.info(f"[{session_id}] visitor left")
        await runner.cancel()

    try:
        await asyncio.wait_for(runner.run(), timeout=persona.max_session_seconds)
    except TimeoutError:
        logger.info(f"[{session_id}] reached the {persona.max_session_seconds}s limit")
        await runner.cancel()
