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

- **One script tag.** `embed.js` is 11 KB (4 KB gzipped). The 3D head, voice and chat load only when someone opens it. Shadow DOM keeps your site's CSS untouched.
- **A launcher people notice.** Your photo blends into your AI avatar on a round button, with a short greeting that offers Talk or Chat.
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

Open http://localhost:7860 and click the avatar in the corner. The first start downloads the Kokoro voice (a few minutes). `docker compose logs -f` shows a check of each provider; `GET /healthz` returns 503 until all pass.

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
6. Set `avatar.photo` to a square photo of you and `avatar.image` to a portrait of your avatar; the launcher blends the two. Either one alone also works.

Add `"$schema": "../persona.schema.json"` to the file for autocompletion and validation in your editor. Unknown keys and invalid values stop the server with a message naming the file.

## Embed options

<img src=".github/assets/launcher.png" alt="Launcher: a photo blending into the AI avatar, with a greeting offering Talk or Chat" width="328">

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
| `label` / `data-label` | `Talk to me` | Launcher name, shown on hover |
| `teaser` / `data-teaser` | built-in greeting | Greeting text, or `off` to hide it |
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
| TURN credential theft | Browsers get one-hour credentials; the coturn secret and Cloudflare API token never leave the server |
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
| `TURN_PROVIDER` | `coturn` | `coturn` (the two variables below) or `cloudflare` |
| `TURN_URLS`, `TURN_SHARED_SECRET` | | coturn TURN REST relay for strict networks |
| `CLOUDFLARE_TURN_KEY_ID`, `CLOUDFLARE_TURN_API_TOKEN` | | [Cloudflare Realtime TURN](https://developers.cloudflare.com/realtime/turn/) key, for `TURN_PROVIDER=cloudflare`. One-hour credentials, reused for up to 5 minutes; port 53 URLs are dropped; if Cloudflare fails, calls fall back to STUN |
| `ICE_SERVERS` | Google STUN | Worker-side STUN/TURN as JSON; static credentials are never sent to browsers |
| `DATA_DIR` | `data/` | Runtime data: the message inbox, logs and (cloud mode) `cloud.db`. Use `/data` with a volume on Railway |

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

`railway.toml` deploys the same image to Railway (see the checklist below); any container platform works if you route its `PORT` and provide TURN.

## Openfolio Cloud (invite-only beta)

The same server can run Openfolio Cloud, the hosted, invite-only version. `CLOUD_MODE=1` turns `/` into a landing page with the live demo and a request form, and adds an owner-only admin page. Without it the server behaves as described above.

1. A visitor fills in the request form: name, email, portfolio, what they do and, optionally, why. A hidden honeypot field, 3 requests per network per hour, one pending request per email and, when configured, [Cloudflare Turnstile](https://developers.cloudflare.com/turnstile/) keep spam out. Every outcome shows the same thank-you page.
2. You get an email (optional SMTP) and review the request at `/admin`.
3. **Approve** creates a personal, single-use invite link that expires after 7 days. Only its SHA-256 hash is stored. It is emailed when SMTP is set and always shown once with a Copy button. **Reject** revokes any open invite; **Delete** erases the request and its invites. Every action goes to an audit log on the same page.
4. The invite link confirms the approval. Stage 2 (the Studio, where approved people build their AI version) will accept it.

Requests live in SQLite at `DATA_DIR/cloud.db`. IP addresses are stored only as hashes salted with `SESSION_SECRET`. Rejected requests are deleted after 90 days and unused invites 30 days after they expire, at startup and every 24 hours. The admin session is an HMAC-signed, HttpOnly, `SameSite=Strict` cookie (12 hours), every admin form carries a CSRF token, and 5 failed sign-ins from one network lock it out for 15 minutes.

| Variable | Purpose |
| --- | --- |
| `CLOUD_MODE` | `1` turns the cloud pages on |
| `PUBLIC_URL` | The site's origin, such as `https://openfolio.up.railway.app` (https; `http://localhost` for development). Used in links, and allowed to run every persona so the demo works |
| `SESSION_SECRET` | At least 32 random characters (`openssl rand -base64 48`). Signs sessions and salts IP hashes |
| `ADMIN_PASSWORD_HASH` | Your admin password as an scrypt hash: `cd worker && uv run openfolio-admin-hash` |
| `CLOUD_DEMO_PERSONA` | Persona in the landing page demo (default `faisal`) |
| `TURNSTILE_SITE_KEY`, `TURNSTILE_SECRET_KEY` | Optional bot check on the form; set both |
| `SMTP_HOST`, `SMTP_PORT` (587), `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `NOTIFY_EMAIL` | Optional email: new requests go to `NOTIFY_EMAIL`, approvals send the invite. STARTTLS; Gmail works with `smtp.gmail.com` and an app password |

Cloud pages send a Content Security Policy with only `'self'`, no inline scripts and `frame-ancestors 'none'`, plus `X-Frame-Options: DENY`; admin and invite pages are `no-store`. The landing page runs the live widget, so its policy also allows inline `<style>` elements (the widget styles its shadow DOM at runtime) and `blob:` fetches (the 3D head loads its textures through blob URLs), and Turnstile's origin when it is on. No `eval` is allowed anywhere.

### Deploy to Railway

Railway runs the Dockerfile as one container behind HTTPS. It has no inbound UDP, so call audio must go through a TURN relay; Openfolio uses Cloudflare Realtime TURN for both the browser and the server side of each call.

1. Create a service from this repository. `railway.toml` builds the Dockerfile, runs one replica and checks `/livez`.
2. Add a volume mounted at `/data`. Railway mounts volumes as root while the image runs as an unprivileged user, so also set `RAILWAY_RUN_UID=0`.
3. Generate a domain (Settings, Networking) and use it for `PUBLIC_URL`.
4. Create the admin hash on your machine: `cd worker && uv run openfolio-admin-hash` (it reads the password from stdin; use 12 characters or more).
5. Set the variables: `CLOUD_MODE=1`, `PUBLIC_URL`, `SESSION_SECRET`, `ADMIN_PASSWORD_HASH`, `DATA_DIR=/data`, `TRUST_PROXY=1`, `TURN_PROVIDER=cloudflare`, `CLOUDFLARE_TURN_KEY_ID`, `CLOUDFLARE_TURN_API_TOKEN`, your LLM, speech and voice keys, and optionally SMTP and Turnstile.
6. Deploy, open `/admin`, sign in, and send yourself a test request from the landing page.

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
