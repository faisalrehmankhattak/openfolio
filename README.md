<div align="center">

# Openfolio

**Your portfolio, alive.** Visitors talk face to face with a 3D AI version of you, by voice or text, from one line of HTML.

[![CI](https://github.com/faisalrehmankhattak/openfolio/actions/workflows/ci.yml/badge.svg)](https://github.com/faisalrehmankhattak/openfolio/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776ab)
![TypeScript](https://img.shields.io/badge/TypeScript-strict-3178c6)
![Self-hosted](https://img.shields.io/badge/self--hosted-no%20GPU-0b6a50)

<img src=".github/assets/panel.png" alt="Openfolio widget: a 3D avatar answering questions about the owner's work" width="360">
<img src=".github/assets/chat.png" alt="Chat mode with a project card" width="360">

</div>

```html
<script src="https://YOUR-SERVER/embed/embed.js" data-persona="you" async></script>
```

Openfolio is an open-source **AI avatar widget for portfolio websites**: a talking 3D head that answers recruiters' and visitors' questions about your work, in your words, by voice or chat. It is a self-hosted alternative to closed "AI digital twin" services. The face renders in the visitor's browser, so **the server needs no GPU** and you pay only for speech-to-text, the LLM and the voice (or nothing, with local models).

## Features

- **One script tag.** `embed.js` is 3 KB (1.5 KB gzipped). The 3D head, voice and chat load only when someone opens it. Shadow DOM keeps your site's CSS untouched.
- **Real-time voice.** WebRTC with interruptions, live captions and lip-sync driven by the audio itself, so it works with any voice.
- **Text first.** Typing or tapping a suggested question never asks for the microphone. Voice is one tap away.
- **Grounded answers.** Everything the AI knows comes from one JSON file you write. It says "I don't know" instead of inventing facts.
- **Portfolio cards.** Projects, experience, skills and contact links appear as cards in the chat.
- **Leave a message.** Visitors can leave their name, email and a note; you get a JSONL inbox.
- **Any provider.** Any OpenAI-compatible LLM (OpenAI, Groq, OpenRouter, Ollama, vLLM); Deepgram or local Whisper for speech; Kokoro (free, CPU) or ElevenLabs (your cloned voice).
- **Guardrails built in.** Prompt-injection screening, portfolio-only scope, rate limits, origin checks and an always-visible "AI" disclosure. See [Security](#security).
- **No third-party calls from the browser.** The widget only talks to your server (and your STUN/TURN servers).

## Quick start

You need Docker and a few API keys (or local models).

```sh
git clone https://github.com/faisalrehmankhattak/openfolio && cd openfolio
cp .env.example .env    # add LLM_API_KEY, LLM_MODEL and DEEPGRAM_API_KEY
docker compose up --build
```

Open http://localhost:7860 and click **Talk to Faisal**. The first start downloads the Kokoro voice (a few minutes). `docker compose logs -f` shows a check of each provider; `GET /healthz` returns 503 until all pass.

<details>
<summary>Without Docker (macOS / Linux)</summary>

Requires [uv](https://docs.astral.sh/uv/) and Node.js 22.12+.

```sh
cp .env.example .env
./scripts/dev.sh      # installs, builds the widget, starts on http://127.0.0.1:7860
```

Check your provider settings without starting the server: `cd worker && uv run openfolio-doctor`.
</details>

## Make it yours

1. Copy `personas/faisal.json` to `personas/<you>.json` and set `"id": "<you>"`.
2. Fill in your story: `about`, `highlights`, `experience`, `projects`, `skills`, `links`, `email`.
3. Add rules in `guardrails` (for example "Never discuss salary").
4. List the sites allowed to embed you in `allowed_origins`.
5. Optionally point `avatar.url` at your own GLB ([Ready Player Me](https://readyplayer.me) or any rig with ARKit or Oculus visemes).

Add `"$schema": "../persona.schema.json"` to the file for autocompletion and validation in your editor. Unknown keys and invalid values stop the server with a message naming the file.

## Embed options

```html
<!-- Floating button -->
<script src="https://YOUR-SERVER/embed/embed.js" data-persona="you" data-label="Talk to me" async></script>

<!-- Inline, inside your layout -->
<script src="https://YOUR-SERVER/embed/embed.js" async></script>
<openfolio-agent persona="you" mode="inline" style="height: 640px"></openfolio-agent>
```

| Attribute | Default | Purpose |
| --- | --- | --- |
| `persona` / `data-persona` | required | Persona file name |
| `mode` | `bubble` | `bubble` (floating) or `inline` |
| `label` / `data-label` | `Talk to me` | Launcher text |
| `server` / `data-server` | script origin | API server, if different from the script host |

Theme it with CSS variables on the element: `--of-accent`, `--of-ink`, `--of-paper`. Dark mode follows the visitor's system setting.

## How it works

```
Browser (your site)                          Openfolio server (CPU only)
┌────────────────────────────┐   WebRTC    ┌───────────────────────────────────────────────┐
│ embed.js  → app.js         │  audio +    │ VAD → speech-to-text → guard → cards           │
│ TalkingHead (three.js)     │◀──────────▶ │     → LLM (+ leave_message) → text-to-speech  │
│ HeadAudio lip-sync         │  data chan. │ persona.json → system prompt                   │
└────────────────────────────┘             └───────────────────────────────────────────────┘
```

1. `embed.js` draws the launcher. On open, `app.js` fetches the public profile and loads the 3D head.
2. The first question opens a WebRTC call to `POST /v1/personas/{id}/offer` after origin, capacity and rate checks.
3. A [Pipecat](https://github.com/pipecat-ai/pipecat) pipeline per visitor: speech-to-text, input guard, card matcher, LLM, text-to-speech.
4. The voice comes back as audio; [HeadAudio](https://github.com/met4citizen/HeadAudio) turns it into mouth shapes for [TalkingHead](https://github.com/met4citizen/TalkingHead) in the browser.

| Path | What |
| --- | --- |
| `embed/src/loader.ts` | `embed.js`: the `<openfolio-agent>` element and launcher |
| `embed/src/app.ts` | Panel UI, call state, captions, face and audio routing |
| `embed/src/text.ts` | Pure helpers (hang-up detection, error wording), unit-tested |
| `worker/openfolio_worker/server.py` | HTTP routes, signalling, origin and rate checks |
| `worker/openfolio_worker/bot.py` | Per-visitor pipeline and provider selection |
| `worker/openfolio_worker/persona.py` | Persona schema and system prompt |
| `worker/openfolio_worker/guard.py` | Input cleanup, injection screen, turn limits |

## Security

| Risk | Guard |
| --- | --- |
| Prompt injection ("ignore your instructions", fake `<system>` tags, role-play) | Screened before the model after Unicode normalisation; a match reaches it only as a note to decline |
| Off-topic use (free coding help, essays) | System prompt limits answers to your work; declines in one sentence |
| Invented facts | Facts come only from the persona file; the prompt forbids inventing numbers, dates or commitments |
| Leaking the prompt or rules | The public profile endpoint returns only name, title, avatar and suggested questions |
| Cost abuse | 60 s idle hang-up, `max_session_seconds` cap, 40 turns per call, 300-token answers, typed-message throttle |
| Call flooding | `CALLS_PER_IP` per 10 minutes and `MAX_SESSIONS` concurrent calls |
| Other sites embedding you | Browser `Origin` must be in `allowed_origins` (not authentication; rate limits still apply) |
| Spoofed client IPs | With `TRUST_PROXY=1`, only the address added by your proxy is used |
| Oversized or malformed requests | Bodies capped at 64 KB (even when streamed) and validated |
| XSS from model or persona text | All text is rendered with `textContent`; links are limited to http(s) and mailto |
| TURN credential theft | Browsers get one-hour HMAC credentials; the shared secret never leaves the server |
| Inbox spam | 2 messages per call, validated email, cleaned text |

The injection screen is a regular expression, not a classifier, and the system prompt is the second layer. The labelled corpus in `worker/tests/test_guard_eval.py` measures both missed attacks and false alarms; add any miss you see in your logs.

Found a vulnerability? Please report it privately through [GitHub security advisories](https://github.com/faisalrehmankhattak/openfolio/security/advisories/new) rather than a public issue.

## Configuration

All settings live in `.env` (see [`.env.example`](.env.example)).

| Variable | Default | Purpose |
| --- | --- | --- |
| `LLM_API_KEY`, `LLM_MODEL`, `LLM_BASE_URL` | | Any OpenAI-compatible API. Leave the key empty for a local Ollama |
| `LLM_REASONING_EFFORT` | `auto` | `auto` sends `none` to OpenAI gpt-5.x/gpt-6, which need it for tools |
| `STT_PROVIDER`, `DEEPGRAM_API_KEY` | `deepgram` | Or `whisper` (local, `uv sync --extra whisper`) |
| `TTS_PROVIDER` | `kokoro` | Or `elevenlabs` with `ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_ID` |
| `MAX_SESSIONS` | `4` | Concurrent calls per process |
| `CALLS_PER_IP` | `6` | New calls per IP per 10 minutes (local testing is exempt) |
| `TRUST_PROXY` | `0` | Set to `1` behind a reverse proxy |
| `DEV_ORIGINS` | localhost | Extra exact origins allowed for every persona |
| `TURN_URLS`, `TURN_SHARED_SECRET` | | TURN REST relay for strict networks |
| `ICE_SERVERS` | Google STUN | Worker-side STUN/TURN as JSON; static credentials are never sent to browsers |

Invalid values stop the server with a message naming the variable.

## Deploy

Any Linux VM with 2 vCPU and 4 GB RAM is a good start. The repo includes Caddy for automatic HTTPS (the microphone requires HTTPS outside localhost).

```sh
# .env: OPENFOLIO_DOMAIN=agent.example.com and DEV_ORIGINS=https://agent.example.com
docker compose -f compose.yaml -f compose.host.yaml up --build -d
```

- Open TCP 80/443; keep 7860 closed to the internet.
- WebRTC audio does not go through the HTTP proxy. For visitors on corporate or mobile networks, run a TURN server (for example coturn with `use-auth-secret`) and set `TURN_URLS` and `TURN_SHARED_SECRET`.
- Calls are process-local: run one replica, or use sticky routing on the offer URL.
- `GET /livez` is liveness; `GET /healthz` is readiness (configuration and provider checks).
- Saved messages and logs live in the `openfolio-data` volume. `docker compose down -v` deletes them.
- On Docker Desktop, reach a host Ollama at `http://host.docker.internal:11434/v1`.

`railway.toml` deploys the same image to Railway; any container platform works if you route its `PORT` and provide TURN.

## Development

```sh
cd worker && uv sync --group dev
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest

cd embed && npm ci
npm run check    # Biome lint, strict TypeScript, unit tests
npm run build
```

`./scripts/docker-smoke.sh` checks a built image without API keys; `./scripts/docker-webrtc-smoke.sh` sends real WebRTC media across Docker's network boundary. CI runs all of these on amd64 and arm64.

Browser flows (voice with recorded speech, chat, cards, guardrails, embedding, capacity, keyboard) were verified in Chrome, Firefox and WebKit. Not yet verified: real speakers (echo), Safari on iOS, screen readers and calls across restrictive networks. Please report what you find.

## Roadmap

- Selfie to 3D head (LAM) instead of a stock avatar
- Owner studio: résumé import, voice consent and cloning
- Gaussian-splat face renderer behind the same interface

## Contributing

Issues and pull requests are welcome. Keep changes small, add a test for any behaviour change, and run the development checks above before opening a PR. New guard false positives or misses belong in `worker/tests/test_guard_eval.py`.

## License

[Apache-2.0](LICENSE). The demo avatar is the Ready Player Me Visage sample under MIT; see [NOTICE](NOTICE). Built on [Pipecat](https://github.com/pipecat-ai/pipecat), [TalkingHead](https://github.com/met4citizen/TalkingHead), [HeadAudio](https://github.com/met4citizen/HeadAudio) and [three.js](https://threejs.org).
