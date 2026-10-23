# syntax=docker/dockerfile:1
FROM node:22-bookworm-slim AS widget
WORKDIR /build/embed
COPY embed/package*.json ./
RUN npm ci
COPY embed/src/ ./src/
COPY embed/tsconfig.json embed/vite.*.ts ./
RUN npm run typecheck && npm run build

# Bake the pinned male sample into the image; attribution is included below.
FROM debian:bookworm-slim AS avatar
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /avatars && curl -fsSL --retry 3 \
    https://raw.githubusercontent.com/readyplayerme/visage/0eafdd9c4c10db079de2656c3eb59212a2fb7f63/public/male.glb \
    -o /avatars/demo.glb && \
    echo "b06bd9df4d7d71d92774f895be31305cb8ff26f966f4c353beb82d3ccd94bea2  /avatars/demo.glb" | sha256sum -c -

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libsndfile1 espeak-ng libgomp1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY worker/ ./worker/
WORKDIR /app/worker
RUN uv sync --frozen --no-dev --no-editable
WORKDIR /app
COPY personas/ ./personas/
COPY demo/ ./demo/
COPY LICENSE NOTICE ./
COPY avatars/README.md avatars/LICENSE-readyplayerme.txt ./avatars/
COPY --from=avatar /avatars/ ./avatars/
COPY --from=widget /build/embed/dist/ ./embed/dist/
RUN useradd --create-home --uid 10001 openfolio && mkdir -p /app/data/inbox /home/openfolio/.cache && chown -R openfolio:openfolio /app/data /home/openfolio
ENV PYTHONUNBUFFERED=1 OPENFOLIO_ROOT=/app UV_NO_SYNC=1 UV_OFFLINE=1
USER openfolio
WORKDIR /app/worker
EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=5s --start-period=300s --retries=3 CMD /app/worker/.venv/bin/python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.getenv('PORT', '7860') + '/healthz', timeout=4)"
CMD ["sh", "-c", "exec /app/worker/.venv/bin/openfolio-worker --host 0.0.0.0 --port ${PORT:-7860}"]
