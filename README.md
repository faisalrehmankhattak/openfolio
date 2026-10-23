# Openfolio

Your portfolio, alive. Visitors talk face to face with a 3D AI version of you, by voice or text, from one line of HTML.

```html
<script src="https://YOUR-SERVER/embed/embed.js" data-persona="faisal" async></script>
```

Openfolio is open source (Apache-2.0). The face is drawn on the visitor's device, so a conversation needs no GPU: the server only sends audio.

## Status: v0.1

Working end to end and tested in a headless browser:

- **Embed.** `embed.js` is 3 KB (1.4 KB gzipped). It adds a launcher and loads the 3D head, voice and chat only when a visitor opens it. Shadow DOM keeps its styles separate from the host site.
- **Voice.** A Pipecat worker runs one pipeline per visitor over WebRTC: speech-to-text, LLM with tools, text-to-speech.
- **Face.** TalkingHead renders a rigged 3D head in three.js. HeadAudio lip-syncs it from the incoming voice in the browser.
- **Cards.** The persona calls tools (`show_projects`, `show_experience`, `show_skills`, `show_contact`, `leave_message`) and the widget shows matching cards in the chat.
- **Guardrails.** Prompt-injection screening, portfolio-only answers, hang-up after 60 seconds of quiet, per-IP call limits, allowed origins, turn and length caps, an "AI version" badge and a first-line disclosure. See [Safeguards](docs/ARCHITECTURE.md#safeguards).
- **Text first.** Typing or tapping a suggestion starts a conversation without asking for the microphone; the mic button adds voice any time.
- **Provider keys stay server-side.** The widget uses your server for AI requests. WebRTC may contact configured STUN/TURN servers for connectivity.

Not built yet: photo-to-3D (LAM), the owner studio, accounts and billing. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

The current face is a **placeholder**: the male Ready Player Me sample from the TalkingHead project. It is replaced by a head built from the owner's selfie in the next milestone.

## Run with Docker (recommended)

You need Docker Engine + Compose, or Docker Desktop. No local Node.js or Python
installation is required. Clone this repository, then:

```sh
cp .env.example .env
# Edit .env: add DEEPGRAM_API_KEY, LLM_API_KEY, and LLM_MODEL.
docker compose up --build
```

Open http://localhost:7860. The image builds the widget and downloads a pinned,
checksum-verified male avatar automatically. Your `.env` is passed at runtime and
is excluded from the image. Startup validates the providers; small checks can
incur provider usage. Kokoro (default) downloads voice weights on first use;
allow several minutes. To use cloud voice instead, set `TTS_PROVIDER=elevenlabs`
and fill in the ElevenLabs key and voice ID. Use the same configuration for
local and hosted instances; your keys stay on the server.

```sh
docker compose up --build -d     # run in the background
docker compose logs -f          # provider checks and startup progress
docker compose down            # stop, preserving saved messages and model cache
```

The persona folder is mounted read-only. Edit `personas/faisal.json` to customize
the supplied demo and restart the service. Add another persona file to serve
another embed ID. The bundled demo uses `faisal` as an example persona; change the script tag's
`data-persona` to your own ID. The demo is a neutral embed test page, not a
personal portfolio. Add the script to your existing portfolio to use the widget. Logs and inbox messages persist in `openfolio-data`;
voice/model caches persist in `openfolio-cache`. Do not use `down -v` unless you
intend to delete those volumes.

**Voice connectivity:** the default Compose file exposes HTTP on loopback. WebRTC
uses a separate media path; loading the page alone does not validate a call.
The default setup includes a TURN relay bound to localhost so browser audio can
cross Docker's network boundary. Its fixed development secret is local-only;
it is disabled by the public-hosting override. The Linux hosting recipe and TURN
configuration are in [Docker hosting](docs/DOCKER.md). HTTPS is required for
microphone access outside localhost. This is a CPU-only image; start with 4 GB
RAM and measure your workload before increasing `MAX_SESSIONS`.

`GET /livez` reports HTTP process liveness; `GET /healthz` returns 503 when
configuration/provider checks fail. A healthy provider check does not prove
WebRTC media connectivity. First builds need internet access for dependencies
and the avatar; first local voice startup also downloads its weights.

## Run it on your Mac without Docker

You need [uv](https://docs.astral.sh/uv/) and Node.js 22.12+ (only to rebuild the widget; the server itself needs no Node).

```sh
cp .env.example .env        # then add your keys (see below)
./scripts/dev.sh            # installs, builds the widget, starts the server
```

Open http://127.0.0.1:7860 and click **Talk to Faisal**.

### Keys

| Setting | What for | Free option |
| --- | --- | --- |
| `DEEPGRAM_API_KEY` | Speech-to-text | `STT_PROVIDER=whisper` runs locally (install with `uv sync --extra whisper`) |
| `LLM_API_KEY`, `LLM_MODEL`, `LLM_BASE_URL` | The brain; any OpenAI-compatible API | Point `LLM_BASE_URL` at a local Ollama |
| `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID` | Premium voice, your cloned voice | `TTS_PROVIDER=kokoro` (default) runs locally on CPU |

When the server starts it tests each provider with a tiny real request and logs the result. To run the same checks on their own:

```sh
cd worker && uv run openfolio-doctor
```

Logs are also written to `data/worker.log`. On your own machine, errors from the AI model or voice show up in the widget's captions.

## Add it to your portfolio

1. Run the server somewhere public (a small CPU VM is enough) behind HTTPS.
2. Add your site's origin to `allowed_origins` in `personas/<you>.json`.
3. Paste the script tag before `</body>`:

```html
<script src="https://YOUR-SERVER/embed/embed.js" data-persona="faisal" data-label="Talk to Faisal" async></script>
```

To place it inside a layout instead of a floating bubble:

```html
<script src="https://YOUR-SERVER/embed/embed.js" async></script>
<openfolio-agent persona="faisal" mode="inline" style="height: 640px"></openfolio-agent>
```

Theme it with CSS variables on the element: `--of-accent`, `--of-ink`, `--of-paper`.

## Make your own persona

Copy `personas/faisal.json` to `personas/<id>.json` and edit it. Everything the AI says about you comes from that file, so it can't invent facts you didn't write. `guardrails` holds extra rules, such as topics to avoid.

## Layout

```
embed/      the widget (TypeScript, Vite): loader.ts -> embed.js, app.ts -> app.js
worker/     the voice server (Python, Pipecat, FastAPI)
personas/   one JSON profile per persona
avatars/    custom avatars; Docker automatically fetches the pinned male placeholder
demo/       a test page served at /
docs/       architecture and decisions
```

## Tests

Build and smoke-test the installed container without API calls:

```sh
docker build -t openfolio:local .
./scripts/docker-smoke.sh openfolio:local
# After installing worker dev dependencies, test real ICE + synthetic audio:
./scripts/docker-webrtc-smoke.sh
```


```sh
cd worker && uv run --group dev pytest
cd embed && npm run typecheck
```

## Licenses

Openfolio's code is Apache-2.0. Dependencies keep their own licenses: Pipecat (BSD-2), TalkingHead and HeadAudio (MIT), three.js (MIT), Kokoro (Apache-2.0). The male placeholder is the official Visage sample; its upstream MIT license is included in `avatars/LICENSE-readyplayerme.txt`.
