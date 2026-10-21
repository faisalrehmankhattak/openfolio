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
- **Guardrails.** Persona-specific allowed origins, a cap on concurrent calls, a per-call time limit, an "AI version" badge and a first-line disclosure.
- **No third-party calls from the browser.** The widget talks only to your server.

Not built yet: photo-to-3D (LAM), the owner studio, accounts and billing. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

The current face is a **placeholder**: a CC0 MakeHuman model from the TalkingHead project. It is replaced by a head built from the owner's selfie in the next milestone.

## Run it on your Mac

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
avatars/    avatar files (not committed; scripts/fetch-demo-avatar.sh gets the placeholder)
demo/       a test page served at /
docs/       architecture and decisions
```

## Tests

```sh
cd worker && uv run --group dev pytest
cd embed && npm run typecheck
```

## Licenses

Openfolio's code is Apache-2.0. Dependencies keep their own licenses: Pipecat (BSD-2), TalkingHead and HeadAudio (MIT), three.js (MIT), Kokoro (Apache-2.0). The placeholder avatar is CC0.
