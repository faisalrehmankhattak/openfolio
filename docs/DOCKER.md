# Docker: local use and Linux hosting

## Local quickstart

Clone the repo, copy `.env.example` to `.env`, fill provider keys/model, and run
`docker compose up --build`. Visit `http://localhost:7860`. The frontend, Python
worker, pinned demo avatar, and native runtime libraries are in one image.
Kokoro voice weights download on first startup and persist in the cache volume.
ElevenLabs avoids that voice download. Startup makes small real provider checks.
The default Compose stack also starts a local coturn relay. All its published
listeners are bound to 127.0.0.1; its fixed development secret is not suitable
for a public relay. It enables audio through Docker NAT without public TURN
credentials. Ports 3478 and 49160–49200 must be free locally. The default demo
is for a browser on the Docker host; a phone cannot use these loopback addresses.

Use Docker Compose >= 2.24.4 for the hosting override. The default port is 7860;
`OPENFOLIO_PORT` changes the local published HTTP port, but you must add the new
exact browser origin to `DEV_ORIGINS` too. Do not change `PORT` in Compose: the
container healthcheck and default publication expect its internal port 7860.

## Host on a Linux VM

1. Install Docker Engine and Compose. Point a domain A/AAAA record at the VM.
2. Copy `.env.example` to `.env` and fill the provider settings.
3. Add `OPENFOLIO_DOMAIN=agent.example.com` and
   `DEV_ORIGINS=https://agent.example.com` to `.env`. Add external portfolio
   origins to `allowed_origins` in the persona JSON.
4. Allow inbound TCP 80/443. Keep TCP 7860 blocked from the public internet:
   only the trusted Caddy proxy should reach it. Caddy forwards the visitor IP;
   the override sets `TRUST_PROXY=1`.
5. Run:

```sh
docker compose -f compose.yaml -f compose.host.yaml up --build -d
```

Caddy obtains/renews TLS certificates. The worker shares the Linux host network
so Docker does not insert another NAT in its WebRTC path. Direct WebRTC still
requires reachable UDP ICE candidates: a cloud NAT/firewall can prevent that.
Use TURN for reliable cross-network calls, particularly corporate/mobile users.
The HTTP proxy does not carry WebRTC audio. Avoid multiple worker replicas;
connection/session state is currently process-local. Restarting ends active calls.

## TURN for reliable media

Use an external coturn-compatible service supporting TURN REST credentials.
Configure its shared secret in the server environment:

```dotenv
TURN_URLS=turn:turn.example.com:3478?transport=udp,turns:turn.example.com:5349?transport=tcp
TURN_SHARED_SECRET=replace-with-your-turn-server-shared-secret
```

The TURN server must use the identical secret with `use-auth-secret`, a realm,
a valid external address, reachable listener/relay ports, and TLS certificates
if using `turns:`. It is a separate service; no public TURN server is bundled.
If the worker and browser need different addresses for the same TURN service,
set `TURN_SERVER_URLS` to the address reachable by the worker. The default local
stack uses `turn:turn:3478?transport=tcp` internally and localhost externally.
For public hosting, leave it empty to use `TURN_URLS` for both peers.

The worker and browser receive separate one-hour credentials generated when
connections are requested. The shared secret is never returned to a browser.
The ICE endpoint is origin-checked when an Origin header is present and
rate-limited; origin checking is not authentication. Monitor TURN bandwidth and
set relay quotas on the TURN service.

`ICE_SERVERS` optionally configures worker-side STUN/TURN entries separately.
Static credentials in that variable are never copied to the browser. If your
managed TURN service only issues static credentials, use them on the worker;
ensure its relay can reach browser candidates and test restrictive networks.
The short-lived browser TURN path requires a REST shared-secret service.

For Docker Desktop, use the default Compose file with its bundled local TURN
relay. The Linux hosting override disables that relay and its development
credentials. Host networking is
an alternative on supported Desktop versions after explicitly enabling it;
the provided hosting override targets Linux and also starts Caddy. It is not a
portable Docker Desktop networking toggle. Test voice from another network
before publishing a deployment as ready.

## Diagnostics

```sh
docker compose logs -f openfolio
curl -f http://localhost:7860/livez
curl -f http://localhost:7860/healthz
docker compose exec openfolio /app/worker/.venv/bin/openfolio-doctor
```

Readiness checks configuration and the providers tested at startup. It is not a
continuous paid check. `OPENFOLIO_SKIP_CHECKS=1` is intended for offline tests,
not deployment verification. A green readiness response does not test microphone,
audio playback, lipsync, or the ICE/media path. Test a real call separately.

Ollama on your host: a container's localhost is the container. Docker Desktop
provides `host.docker.internal`; use that in `LLM_BASE_URL` and set a dummy
`LLM_API_KEY` for unauthenticated local servers. Local Whisper requires building
with its optional dependency; the supplied image includes Deepgram and Kokoro/
ElevenLabs. Don't set `STT_PROVIDER=whisper` on the standard image.

## Persistence and custom files

Compose mounts `./personas` at `/app/personas` and named volumes at `/app/data`
and `/home/openfolio/.cache`. Back up the data volume for saved messages. To
use custom avatars, add a read-only mount at `/app/avatars` containing the files
referenced by your personas (include `demo.glb` if you retain the example).

For an arbitrary container platform, set `OPENFOLIO_ROOT=/app` (image default),
pass environment variables, mount persistent storage at `/app/data`, and route
the platform's HTTP port. `PORT` is respected by the entrypoint and healthcheck.
WebRTC still requires working ICE/TURN. ARM64 and AMD64 dependency compatibility
must be checked on the architectures you intend to release.

## Offline integration verification

```sh
docker build -t openfolio:local .
./scripts/docker-smoke.sh
(cd worker && uv sync --group dev)
./scripts/docker-webrtc-smoke.sh
```

The second smoke test uses an isolated Compose project and an echo/synthetic-audio
fixture instead of the real bot. It verifies ICE, a data-channel roundtrip, and
received audio frames across Docker's network boundary without provider calls.
It removes only its own test containers and volumes. It does not test STT, LLM,
TTS, browser microphone permissions, or perceived lip-sync quality.
