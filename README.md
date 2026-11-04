<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="worker/openfolio_worker/cloud/static/wordmark-white.svg">
  <img src="worker/openfolio_worker/cloud/static/wordmark.svg" alt="Openfolio" height="56">
</picture>

### The open-source AI portfolio builder: a 3D AI version of you that talks to recruiters by voice or chat.

[![CI](https://github.com/faisalrehmankhattak/openfolio/actions/workflows/ci.yml/badge.svg)](https://github.com/faisalrehmankhattak/openfolio/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776ab)
![TypeScript](https://img.shields.io/badge/TypeScript-strict-3178c6)
![Self-hosted](https://img.shields.io/badge/self--hosted-no%20GPU-0b6a50)
[![PRs welcome: earn Cloud credits](https://img.shields.io/badge/PRs%20welcome-earn%20Cloud%20credits-128a6a)](CONTRIBUTING.md)

**[Try it on Openfolio Cloud](https://YOUR-OPENFOLIO-CLOUD-URL)** · [Run it yourself](#quick-start) · [Contribute and earn credits](#contribute-and-earn-credits)

</div>

**Your portfolio, alive.** Openfolio is a modern portfolio for everyone: recruiters and visitors talk face to face with a 3D AI version of you, by voice or text, and it answers only from what you wrote. Add it to any site with one line of HTML, or share a link.

```html
<script src="https://YOUR-SERVER/embed/embed.js" data-persona="you" async></script>
```

It is an open-source **AI avatar widget for portfolio websites** and a self-hosted alternative to closed "AI digital twin" services. The face renders in the visitor's browser, so **the server needs no GPU** and you pay only for speech-to-text, the LLM and the voice (or nothing, with local models). **Openfolio Cloud** is the hosted version, in an invite-only beta.

> Openfolio is not related to an earlier investing app that used the same name.

## Who it's for

Students and new grads, engineers, designers, freelancers and career switchers: anyone whose portfolio decides whether someone gets in touch. **Recruiters** can interview the AI twin at any time, and leave a message for the real person.

## Features

- **One script tag.** `embed.js` is 11 KB (4 KB gzipped). The 3D head, voice and chat load only when someone opens it. Shadow DOM keeps your site's CSS untouched.
- **A launcher people notice.** Your photo blends into your AI avatar on a round button, with a short greeting that offers Talk or Chat.
- **Real-time voice.** WebRTC with interruptions, live captions and lip-sync driven by the audio itself, so it works with any voice.
- **Text first.** Typing or tapping a suggested question never asks for the microphone. Voice is one tap away.
- **Grounded answers.** Everything the AI knows comes from one JSON file you write. It says "I don't know" instead of inventing facts.
- **Always labelled AI.** The button, the panel and the first answer say it's an AI version of you.
- **Portfolio cards.** Projects, experience, skills and contact links appear as cards in the chat.
- **Leave a message.** Visitors can leave their name, email and a note; you get a JSONL inbox.
- **Any provider.** Any OpenAI-compatible LLM (OpenAI, Groq, OpenRouter, Ollama, vLLM); Deepgram or local Whisper for speech; Kokoro (free, CPU) or ElevenLabs (your cloned voice).
- **Guardrails built in.** Prompt-injection screening, portfolio-only scope, rate limits and origin checks. See [Security](#security).
- **No third-party calls from the browser.** The widget only talks to your server (and your STUN/TURN servers).

## Contribute and earn credits

Openfolio is built in the open, and contributors get rewarded for real work:

- **Merged pull requests earn Openfolio Cloud credits**, on top of the free monthly credits that founding members (everyone who joins the waitlist during the beta) receive. Code, tests, docs and translations all count.
- Good places to start: [`good first issue`](https://github.com/faisalrehmankhattak/openfolio/labels/good%20first%20issue) labels, the prompt-injection corpus in `worker/tests/test_guard_eval.py`, and testing voice on browsers and networks we haven't covered.
- Stars are always appreciated but never rewarded: no credits or perks for stars, follows or upvotes.

Read [CONTRIBUTING.md](CONTRIBUTING.md) for setup, checks and pull request rules, and our [Code of Conduct](CODE_OF_CONDUCT.md).

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

1. Copy `personas/demo.json` (Avery Quinn, a fictional demo person) to `personas/<you>.json` and set `"id": "<you>"`. Everything in `personas/` except the demo is git-ignored, so your profile stays private.
2. Fill in your story: `about`, `highlights`, `experience`, `projects`, `skills`, `links`, `email`.
3. Add rules in `guardrails` (for example "Never discuss salary").
4. List the sites allowed to embed you in `allowed_origins`.
5. Optionally point `avatar.url` at your own GLB ([Ready Player Me](https://readyplayer.me) or any rig with ARKit or Oculus visemes).
6. Set `avatar.photo` to a square photo of you and `avatar.image` to a portrait of your avatar; the launcher blends the two. Either one alone also works.

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
| `worker/openfolio_worker/cloud/` | Openfolio Cloud: landing page, waitlist, admin, invites; `seo.py` for search engines and AI assistants |

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

Found a vulnerability? Please report it privately as described in [SECURITY.md](SECURITY.md) (through [GitHub security advisories](https://github.com/faisalrehmankhattak/openfolio/security/advisories/new)), not in a public issue.

## Cost limits

Openfolio meters every call and every Studio draft, and stops before your bill grows. Defaults keep a public demo near **$50 a month**:

| Cap | Default | Setting |
|---|---|---|
| Monthly budget | $50 | `MONTHLY_BUDGET_USD` |
| Daily budget | a fifteenth of the monthly budget | `DAILY_BUDGET_USD` |
| One call | 10 minutes, 30 replies | `SESSION_MAX_MINUTES`, `SESSION_MAX_REPLIES` |
| One visitor | 10 calls a day | `VISITOR_CALLS_PER_DAY` |
| One persona | 120 call minutes a day | `PERSONA_MINUTES_PER_DAY` |
| Whole server | 240 min a day, 3,000 a month | `DAILY_MAX_MINUTES`, `MONTHLY_MAX_MINUTES` |
| Model tokens | 2M a day, 30M a month | `DAILY_MAX_LLM_TOKENS`, `MONTHLY_MAX_LLM_TOKENS` |
| Paid voice characters | 100k a day, 1M a month | `DAILY_MAX_TTS_CHARS`, `MONTHLY_MAX_TTS_CHARS` |

- Spending is an estimate from the `PRICE_*` settings; set them to your providers' prices. The minute and token caps hold even if a price is wrong.
- At a cap, new calls are refused with a clear message and calls in progress end politely. Calls already running can overshoot by at most `MAX_SESSIONS` × `SESSION_MAX_MINUTES`.
- Totals are kept per UTC day in `DATA_DIR/usage.db` and survive restarts. Visitors are counted by a salted hash, never their IP address.
- Check spending with `uv run openfolio-usage`; `/healthz` reports `usage_limit` while calls are being refused.

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

The same server can run Openfolio Cloud, the hosted, invite-only version. `CLOUD_MODE=1` turns `/` into a landing page with the live demo and a waitlist form, and adds an owner-only admin page. Without it the server behaves as described above.

1. A visitor joins the waitlist: name, email, portfolio, what they do and, optionally, why. A hidden honeypot field, 3 requests per network per hour, one pending request per email and, when configured, [Cloudflare Turnstile](https://developers.cloudflare.com/turnstile/) keep spam out. Every outcome shows the same thank-you page.
2. You get an email (optional SMTP) and review the request at `/admin`.
3. **Approve** creates a personal, single-use invite link that expires after 7 days. Only its SHA-256 hash is stored. It is emailed when SMTP is set and always shown once with a Copy button. **Reject** revokes any open invite; **Delete** erases the request and its invites. Every action goes to an audit log on the same page.
4. The invite link opens `/join/{token}`, where the person picks a handle and a password and lands in the Studio (below).

Requests live in SQLite at `DATA_DIR/cloud.db`. IP addresses are stored only as hashes salted with `SESSION_SECRET`. Rejected requests are deleted after 90 days and unused invites 30 days after they expire, at startup and every 24 hours. The admin session is an HMAC-signed, HttpOnly, `SameSite=Strict` cookie (12 hours), every admin form carries a CSRF token, and 5 failed sign-ins from one network lock it out for 15 minutes.

| Variable | Purpose |
| --- | --- |
| `CLOUD_MODE` | `1` turns the cloud pages on |
| `PUBLIC_URL` | The site's origin, such as `https://openfolio.up.railway.app` (https; `http://localhost` for development). Used in links, and allowed to run every persona so the demo works |
| `SESSION_SECRET` | At least 32 random characters (`openssl rand -base64 48`). Signs sessions and salts IP hashes |
| `ADMIN_PASSWORD_HASH` | Your admin password as an scrypt hash: `cd worker && uv run openfolio-admin-hash` |
| `CLOUD_DEMO_PERSONA` | Persona in the landing page demo (default `demo`, the fictional Avery Quinn) |
| `CONTACT_EMAIL` | Contact address on the privacy page and in security.txt (defaults to `NOTIFY_EMAIL`) |
| `TURNSTILE_SITE_KEY`, `TURNSTILE_SECRET_KEY` | Optional bot check on the form; set both |
| `GITHUB_REPO` | Optional `owner/name`; shows the repository's live star count, fetched server-side and cached for an hour |
| `PRODUCT_HUNT_URL` | Optional Product Hunt link; shows a "we're live" banner on public pages while set |
| `SMTP_HOST`, `SMTP_PORT` (587), `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `NOTIFY_EMAIL` | Optional email: new requests go to `NOTIFY_EMAIL`, approvals send the invite. STARTTLS; Gmail works with `smtp.gmail.com` and an app password |

For search engines and AI assistants, the cloud serves `/robots.txt` (public pages open to Googlebot, Bingbot, GPTBot, ClaudeBot, PerplexityBot and others; admin, invite and form paths closed), `/sitemap.xml`, `/llms.txt` and `/llms-full.txt` ([llmstxt.org](https://llmstxt.org) format), `/.well-known/security.txt`, JSON-LD on every public page, and three guides: `/guides/ai-portfolio`, `/guides/portfolio-for-recruiters` and `/compare`.

Cloud pages send a Content Security Policy with only `'self'`, no inline scripts and `frame-ancestors 'none'`, plus `X-Frame-Options: DENY`; admin and invite pages are `no-store`. The landing page runs the live widget, so its policy also allows inline `<style>` elements (the widget styles its shadow DOM at runtime) and `blob:` fetches (the 3D head loads its textures through blob URLs), and Turnstile's origin when it is on. No `eval` is allowed anywhere.

### Studio

Approved members build their page and AI version in the Studio at `/studio`:

1. **Setup**: upload a résumé, a LinkedIn "Save to PDF" export or a portfolio document (or paste text), plus a photo.
2. **Draft**: the configured LLM drafts the profile from those documents only, in the background (Setup shows progress). Text that reads like instructions to an AI is flagged for the member and the owner.
3. **Profile**: the member checks and edits every field. **Preview** runs the real widget on the saved copy, visible only to them (`/v1/personas/{handle}~preview`).
4. **Publish**: submitting sends the page to the owner's **Reviews** tab. The owner opens it, tries its AI, then approves or sends it back with a note (emailed when SMTP is set). Approved pages go live at `/p/{handle}` with JSON-LD, a Markdown twin at `/p/{handle}.md` and the sitemap; later edits go through review again while the approved version stays live. Members can pause their page or hide it from search engines.
5. **Account**: change the password, download everything as a zip, or delete the account. Deletion erases the profile, the files on disk, sessions, reset links and the original access request. The owner can pause, reset or delete members from the **Members** tab.

Uploads: PDF up to 10 MB and 30 pages, Word `.docx` 5 MB, text 200 KB, photos (JPEG, PNG, WebP) 5 MB; 10 files and 30 MB per member, and 12 MB per request, enforced while the body streams in. Types are checked by their magic bytes, not the name. PDF, DOCX and image parsing runs in a child process with CPU, memory, file-size and process limits, photos are re-encoded without EXIF (no location data) and cropped to 512 px, and a photo is public only once the page is live. Member sessions are HttpOnly, `SameSite=Lax` cookies stored hashed; every form carries a CSRF token and an origin check.

Two limits to know: draft jobs are tracked in memory, so run **one replica** (`railway.toml` does); a restart marks a running draft as interrupted and the member drafts again. The parser's memory cap (`RLIMIT_AS`) is not enforced on macOS, so local development relies on the time limit; the Linux Docker image enforces both.

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

Issues and pull requests are welcome, and merged pull requests earn Openfolio Cloud credits (see [Contribute and earn credits](#contribute-and-earn-credits)). Keep changes small, add a test for any behaviour change, and run the development checks above before opening a PR. New guard false positives or misses belong in `worker/tests/test_guard_eval.py`. Details are in [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[Apache-2.0](LICENSE). The demo avatar is the Ready Player Me Visage sample under MIT; see [NOTICE](NOTICE). Built on [Pipecat](https://github.com/pipecat-ai/pipecat), [TalkingHead](https://github.com/met4citizen/TalkingHead), [HeadAudio](https://github.com/met4citizen/HeadAudio) and [three.js](https://threejs.org).
