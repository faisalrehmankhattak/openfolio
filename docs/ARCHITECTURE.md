# Architecture

The full decision document, with the cost model, SWOT and roadmap, lives here:
https://claude.ai/artifact/AEQBfQNEi7K22C31KjhAwj

## The one idea

The server never renders video. It sends the voice; the visitor's device draws and animates the face. That makes the face free per minute, so only speech-to-text, the LLM and the voice cost money.

## How a conversation flows

1. The host page loads `embed.js` (3 KB). Nothing else loads until a visitor opens the widget.
2. On open, `app.js` fetches the public persona profile (`GET /v1/personas/{id}`) and loads the 3D head.
3. On **Talk** (or a typed question), the Pipecat client opens WebRTC to `POST /v1/personas/{id}/offer`. The server checks the page's origin against the persona's `allowed_origins`, checks capacity, and starts a pipeline for this visitor.
4. Pipeline: Silero VAD and turn-taking → speech-to-text → LLM with the persona prompt and tools → text-to-speech → WebRTC audio back.
5. In the browser, the bot's audio track feeds TalkingHead's audio graph. HeadAudio turns it into mouth shapes in real time.
6. Tool calls send `openfolio.card` server messages; the widget renders them as cards in the chat.
7. The call ends when the visitor leaves, ends it, or reaches `max_session_seconds`.

## Code map

| Path | What |
| --- | --- |
| `embed/src/loader.ts` | `embed.js`: defines `<openfolio-agent>`, the launcher, lazy-loads the app |
| `embed/src/app.ts` | Panel UI, Pipecat client, TalkingHead + HeadAudio, transcript |
| `embed/src/media.ts` | Microphone handling without the default Daily CDN dependency |
| `embed/src/cards.ts` | Card rendering (text only, never raw HTML) |
| `worker/openfolio_worker/server.py` | HTTP routes, WebRTC signalling, origin and capacity checks |
| `worker/openfolio_worker/bot.py` | The per-visitor Pipecat pipeline and provider selection |
| `worker/openfolio_worker/persona.py` | Persona schema and the system prompt built from it |
| `worker/openfolio_worker/tools.py` | Tools that show cards and take messages |

## Decisions made while building v0.1

- **Own media manager.** `SmallWebRTCTransport`'s default media manager builds a Daily call object, which downloads a script from Daily's CDN. That breaks self-hosting and privacy, so `media.ts` uses `getUserMedia` directly. The browser test confirms zero requests leave the host.
- **Shared Kokoro model.** Pipecat loads the Kokoro model (about 300 MB) in every service constructor. The worker loads it once per process and warms it at startup.
- **Lip-sync in the browser from audio (HeadAudio)**, not from TTS timestamps, so every voice provider works the same way. ElevenLabs word timings can make it sharper later.
- **Cards in the transcript**, not over the face, so the face stays visible on phones.
- **Placeholder avatar is CC0** (MakeHuman via TalkingHead), textures compressed to WebP: 37 MB → 18 MB, rig and 66 blendshapes intact.

## Known limits

- Kokoro on a slow CPU takes several seconds to start speaking; measured 4.5 s on a small cloud VM. Check on your Mac; use ElevenLabs where latency matters.
- Echo cancellation with bot audio played through Web Audio must be checked on real speakers. Headphones avoid the issue.
- `@daily-co/daily-js` is still bundled (unused) through the transport package; it adds size, not network calls.
- One worker process handles `MAX_SESSIONS` calls; scale by adding processes behind a load balancer with sticky routing on the offer URL.

## Next

1. Week 1 tests on your phone: LAM head from your selfie, Audio2Expression on CPU, real reply latency.
2. Owner studio: selfie capture, resume import into a persona file, voice consent.
3. Gaussian renderer (LAM WebRender) as a second face renderer behind the same interface.
