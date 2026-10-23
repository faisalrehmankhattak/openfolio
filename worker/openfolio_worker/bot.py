"""One conversation: the Pipecat pipeline for a single visitor.

    mic -> VAD/turns -> speech-to-text -> LLM + tools -> text-to-speech -> speaker

The face is not rendered here. The browser animates it from the audio it
receives, so a conversation needs no GPU.
"""

from __future__ import annotations

import asyncio

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
from pipecat.processors.frameworks.rtvi.frames import RTVIServerMessageFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker, ProcessorUnusablePolicy
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
from pipecat.workers.runner import WorkerRunner

from .config import Settings, llm_extra_params
from .activity import ConversationActivity
from .cards import PortfolioCards
from .persona import Persona, build_system_prompt
from .guard import VisitorGuard
from .tools import leave_message, SessionResources


def make_stt(s: Settings):
    if s.stt_provider == "whisper":
        from pipecat.services.whisper.stt import WhisperSTTService

        return WhisperSTTService()
    from pipecat.services.deepgram.stt import DeepgramSTTService

    return DeepgramSTTService(api_key=s.deepgram_api_key)


def _share_kokoro_model() -> None:
    """Load the Kokoro model once per process instead of once per call.

    Pipecat's KokoroTTSService builds a new kokoro_onnx.Kokoro (about 300 MB)
    in every constructor, which blocks the event loop at the start of each call.
    """
    import pipecat.services.kokoro.tts as kokoro_tts

    if getattr(kokoro_tts, "_openfolio_shared", False):
        return
    original = kokoro_tts.Kokoro
    cache: dict[tuple[str, str], object] = {}

    def shared(model_path: str, voices_path: str):
        key = (model_path, voices_path)
        if key not in cache:
            cache[key] = original(model_path, voices_path)
        return cache[key]

    kokoro_tts.Kokoro = shared
    kokoro_tts._openfolio_shared = True


def warm_up_voice(s: Settings) -> None:
    """Load and exercise the free voice before the first visitor arrives."""
    if s.tts_provider != "kokoro":
        return
    from pipecat.services.kokoro.tts import KokoroTTSService

    _share_kokoro_model()
    service = KokoroTTSService(settings=KokoroTTSService.Settings(voice=s.kokoro_voice))
    service._kokoro.create("Ready.", voice=s.kokoro_voice, speed=1.0, lang="en-us")


def make_tts(s: Settings, persona: Persona):
    provider = persona.voice.provider or s.tts_provider
    if provider == "elevenlabs":
        from pipecat.services.elevenlabs.tts import ElevenLabsTTSService

        return ElevenLabsTTSService(
            api_key=s.elevenlabs_api_key,
            settings=ElevenLabsTTSService.Settings(
                voice=persona.voice.voice_id or s.elevenlabs_voice_id,
                model=s.elevenlabs_model,
            ),
        )
    from pipecat.services.kokoro.tts import KokoroTTSService

    _share_kokoro_model()
    return KokoroTTSService(
        settings=KokoroTTSService.Settings(voice=persona.voice.voice_id or s.kokoro_voice)
    )


def make_llm(s: Settings, persona: Persona) -> OpenAILLMService:
    # Any OpenAI-compatible endpoint works: OpenAI, Groq, OpenRouter, Ollama, vLLM.
    return OpenAILLMService(
        api_key=s.llm_api_key or "not-needed",
        base_url=s.llm_base_url,
        settings=OpenAILLMService.Settings(
            model=s.llm_model,
            system_instruction=build_system_prompt(persona),
            # Spoken answers are short; this also caps what one request can cost.
            max_completion_tokens=300,
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

    stt = make_stt(settings)
    llm = make_llm(settings, persona)
    tts = make_tts(settings, persona)

    context = LLMContext(tools=[leave_message])
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer()),
    )

    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            VisitorGuard(persona.first_name, session_id),
            PortfolioCards(persona),
            user_aggregator,
            llm,
            tts,
            transport.output(),
            assistant_aggregator,
        ]
    )

    activity = ConversationActivity()
    worker = PipelineWorker(
        pipeline,
        observers=[activity],
        params=PipelineParams(enable_metrics=True, enable_usage_metrics=True),
        app_resources=SessionResources(
            persona=persona, inbox_dir=settings.inbox_dir, session_id=session_id
        ),
        processor_unusable_policy=ProcessorUnusablePolicy.END,
        # Hang up after this long with nobody speaking or typing. The bot's own
        # speech counts as activity, so the clock starts when it finishes.
        idle_timeout_secs=persona.idle_seconds,
        idle_timeout_frames=(
            BotSpeakingFrame,
            InterimTranscriptionFrame,
            TranscriptionFrame,
            UserSpeakingFrame,
            UserStartedSpeakingFrame,
            LLMMessagesAppendFrame,
        ),
        cancel_on_idle_timeout=False,
    )
    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(worker)

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info(f"[{session_id}] visitor connected to {persona.id}")
        context.add_message(
            {
                "role": "developer",
                "content": "Greet the visitor in one or two sentences. Say you are the AI version of "
                f"{persona.first_name} and ask what they would like to know.",
            }
        )
        await worker.queue_frames([LLMRunFrame()])

    @worker.event_handler("on_idle_timeout")
    async def on_idle_timeout(worker):
        if not activity.is_idle(persona.idle_seconds):
            return
        logger.info(f"[{session_id}] no activity for {persona.idle_seconds}s; hanging up")
        await worker.queue_frames([RTVIServerMessageFrame(data={"type": "openfolio.ended", "reason": "idle"})])
        await asyncio.sleep(0.5)  # let the message reach the browser
        await runner.cancel()

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info(f"[{session_id}] visitor left")
        await runner.cancel()

    try:
        # Hard cap on call length, so one open tab can't spend the owner's minutes.
        await asyncio.wait_for(runner.run(), timeout=persona.max_session_seconds)
    except asyncio.TimeoutError:
        logger.info(f"[{session_id}] reached the {persona.max_session_seconds}s limit")
        await runner.cancel()
