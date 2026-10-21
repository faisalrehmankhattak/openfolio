/**
 * app.js — loaded by embed.js when a visitor opens the widget.
 *
 * Voice: Pipecat client over WebRTC to the Openfolio worker.
 * Face: TalkingHead renders the 3D head; HeadAudio turns the incoming voice
 * into mouth shapes in the browser, so the server never sends video.
 */
import { PipecatClient } from "@pipecat-ai/client-js";
import { SmallWebRTCTransport } from "@pipecat-ai/small-webrtc-transport";
import { renderCard } from "./cards";
import { LocalMediaManager } from "./media";
import { h } from "./dom";
import { PANEL_CSS } from "./styles";

export type MountOptions = {
  persona: string;
  server: string;
  assetBase: string;
  mode: "bubble" | "inline";
  onClose?: () => void;
};

type PersonaInfo = {
  id: string;
  name: string;
  first_name: string;
  title: string;
  tagline: string;
  avatar: { kind: string; url: string; body: string };
  quick_questions: { label: string; question: string }[];
};

type Head = {
  audioCtx: AudioContext;
  audioAnalyzerNode: AudioNode;
  start(): void;
  stop(): void;
};

export async function mount(root: ShadowRoot, opts: MountOptions) {
  const style = h("style", {}, PANEL_CSS);
  const panel = h("div", { class: `panel ${opts.mode}`, role: "dialog", "aria-label": "AI assistant" });
  root.append(style, panel);

  let info: PersonaInfo;
  try {
    const res = await fetch(`${opts.server}/v1/personas/${encodeURIComponent(opts.persona)}`);
    if (!res.ok) throw new Error(`persona ${res.status}`);
    info = await res.json();
  } catch (err) {
    panel.append(h("p", { class: "msg note" }, "This assistant isn't available right now."));
    console.error("[openfolio]", err);
    return;
  }

  // ---- layout -------------------------------------------------------------
  const status = h("div", { class: "status", "aria-live": "polite" }, "Loading face…");
  const headEl = h("div", { class: "head" });
  const stage = h("div", { class: "stage" }, headEl, status);
  const log = h("div", { class: "log", "aria-live": "polite" });
  const input = h("input", { type: "text", placeholder: `Ask ${info.first_name} anything…`, "aria-label": "Your message", maxlength: "500" });
  const talk = h("button", { class: "talk", type: "button" }, "Talk");
  const mic = h("button", { class: "mic", type: "button", "aria-pressed": "false", "aria-label": "Mute microphone", hidden: true }, "Mic");
  const suggest = h(
    "div",
    { class: "suggest" },
    ...info.quick_questions.map((q) => h("button", { type: "button", onclick: () => void ask(q.question) }, q.label)),
  );
  const close = h("button", { class: "icon", type: "button", "aria-label": "Close" }, "×");
  panel.append(
    h(
      "header",
      {},
      h("div", { class: "who" }, h("div", { class: "name" }, info.name), h("div", { class: "title" }, info.title)),
      h("span", { class: "badge", title: `This is an AI version of ${info.first_name}` }, "AI version"),
      opts.mode === "bubble" ? close : null,
    ),
    stage,
    log,
    suggest,
    h("form", { class: "controls", onsubmit: (e: Event) => { e.preventDefault(); void ask(input.value); } }, mic, input, talk),
    h("footer", {}, `AI version of ${info.first_name}. It can make mistakes. `, h("a", { href: "https://github.com/openfolio", target: "_blank", rel: "noopener" }, "Openfolio")),
  );
  addNote(`Tap Talk to speak with the AI version of ${info.first_name}, or type below.`);

  // ---- face ---------------------------------------------------------------
  let head: Head | null = null;
  const faceReady = loadFace().catch((err) => {
    console.warn("[openfolio] 3D face unavailable, using voice only", err);
    headEl.replaceChildren(h("div", { class: "fallback" }, h("span", {}, info.first_name.slice(0, 1))));
    return null;
  });

  async function loadFace(): Promise<Head> {
    const [{ TalkingHead }, { HeadAudio }] = await Promise.all([
      import("@met4citizen/talkinghead"),
      // @ts-ignore: the package ships an ES module without types
      import("@met4citizen/headaudio/dist/headaudio.min.mjs"),
    ]);
    const th: any = new TalkingHead(headEl, {
      ttsEndpoint: "N/A",
      lipsyncModules: [],
      cameraView: "head",
      cameraRotateEnable: false,
      mixerGainSpeech: 3,
      avatarMood: "neutral",
    });
    const avatarUrl = new URL(info.avatar.url, `${opts.server}/`).href;
    await th.showAvatar({ url: avatarUrl, body: info.avatar.body || "M", avatarMood: "neutral", lipsyncLang: "en" }, (ev: ProgressEvent) => {
      if (ev.lengthComputable) status.textContent = `Loading face… ${Math.round((ev.loaded / ev.total) * 100)}%`;
    });

    // Audio-driven lip-sync: works with any voice, no timestamps needed.
    await th.audioCtx.audioWorklet.addModule(`${opts.assetBase}headworklet.min.mjs`);
    const lips: any = new HeadAudio(th.audioCtx);
    await lips.loadModel(`${opts.assetBase}model-en-mixed.bin`);
    th.audioSpeechGainNode.connect(lips);
    lips.onvalue = (key: string, value: number) => {
      Object.assign(th.mtAvatar[key], { newvalue: value, needsUpdate: true });
    };
    th.opt.update = lips.update.bind(lips);
    let lastEnded = 0;
    lips.onended = () => (lastEnded = Date.now());
    lips.onstarted = () => {
      if (Date.now() - lastEnded > 150) th.lookAtCamera(500);
    };
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") { th.start(); lips.start(); } else { lips.stop(); th.stop(); }
    });
    status.textContent = "Ready";
    head = th as Head;
    return head;
  }

  // ---- conversation -------------------------------------------------------
  let client: PipecatClient | null = null;
  let connecting: Promise<void> | null = null;
  let botBubble: HTMLElement | null = null;
  let mutedEl: HTMLAudioElement | null = null;

  function addNote(text: string) {
    log.append(h("div", { class: "msg note" }, text));
    log.scrollTop = log.scrollHeight;
  }
  function addUser(text: string) {
    log.append(h("div", { class: "msg user" }, text));
    botBubble = null;
    log.scrollTop = log.scrollHeight;
  }
  // Pipecat reports each sentence several times (queued, then spoken) under one
  // segment id, so the transcript keeps one line per segment and updates it.
  const segments = new Map<string, HTMLElement>();
  function addBot(text: string, segmentId?: string | number) {
    if (!botBubble) {
      botBubble = h("div", { class: "msg bot" });
      log.append(botBubble);
    }
    const key = segmentId === undefined ? `t:${text}` : `s:${segmentId}`;
    let span = segments.get(key);
    if (!span) {
      span = h("span", {});
      if (botBubble.childNodes.length) botBubble.append(" ");
      botBubble.append(span);
      segments.set(key, span);
    }
    span.textContent = text;
    log.scrollTop = log.scrollHeight;
  }
  function showCard(card: string, data: unknown) {
    const el = renderCard(card, data);
    if (!el) return;
    // Cards go into the conversation, so they never cover the face.
    log.append(h("div", { class: "msg cardmsg" }, el));
    botBubble = null;
    log.scrollTop = log.scrollHeight;
  }
  function setLive(live: boolean) {
    talk.textContent = live ? "End" : "Talk";
    talk.classList.toggle("end", live);
    mic.hidden = !live;
    if (live) status.replaceChildren(h("span", { class: "live-dot", "aria-hidden": "true" }), "Live");
    else status.textContent = head ? "Ready" : status.textContent;
  }

  async function connect() {
    if (client) return;
    if (connecting) return connecting;
    connecting = (async () => {
      talk.disabled = true;
      status.textContent = "Connecting…";
      // Must run inside the click: browsers only start audio after a gesture.
      const face = head;
      if (face) {
        face.start();
        if (face.audioCtx.state !== "running") await face.audioCtx.resume().catch(() => {});
      }
      const c = new PipecatClient({
        // Our own media manager: the default one loads a script from Daily's CDN.
        transport: new SmallWebRTCTransport({ mediaManager: new LocalMediaManager() as any }),
        enableMic: true,
        enableCam: false,
        callbacks: {
          onTrackStarted: (track, participant) => {
            if (participant?.local || track.kind !== "audio") return;
            const stream = new MediaStream([track]);
            if (face) {
              // Old Chrome only feeds remote tracks to Web Audio once an element touches them.
              mutedEl = new Audio();
              mutedEl.muted = true;
              mutedEl.srcObject = stream;
              face.audioCtx.createMediaStreamSource(stream).connect(face.audioAnalyzerNode);
            } else {
              mutedEl = new Audio();
              mutedEl.autoplay = true;
              mutedEl.srcObject = stream;
            }
          },
          onUserTranscript: (d) => { if (d.final && d.text.trim()) addUser(d.text); },
          onBotOutput: (d) => {
            const kind = d.text_type ?? d.aggregated_by;
            if (kind !== "sentence") return;
            const p = d.spoken_progress;
            const full = p ? `${p.accumulated_text ?? ""}${p.remaining_text ?? ""}` : d.text;
            if (full.trim()) addBot(full.trim(), d.segment_id);
          },
          onServerMessage: (m: any) => { if (m?.type === "openfolio.card") showCard(m.card, m.data); },
          onDisconnected: () => { teardown(); addNote("Call ended."); },
          onError: (e) => console.warn("[openfolio]", e),
        },
      });
      try {
        await c.connect({ webrtcRequestParams: { endpoint: `${opts.server}/v1/personas/${encodeURIComponent(opts.persona)}/offer` } });
        client = c;
        setLive(true);
      } catch (err: any) {
        console.error("[openfolio]", err);
        addNote(String(err?.message || "").includes("503") ? "All lines are busy. Please try again shortly." : "Couldn't connect. Check your microphone permission and try again.");
        status.textContent = head ? "Ready" : status.textContent;
        try { await c.disconnect(); } catch {}
      } finally {
        talk.disabled = false;
        connecting = null;
      }
    })();
    return connecting;
  }

  function teardown() {
    client = null;
    mutedEl?.pause();
    mutedEl = null;
    setLive(false);
  }

  async function hangUp() {
    const c = client;
    teardown();
    try { await c?.disconnect(); } catch {}
  }

  async function ask(text: string) {
    const q = text.trim();
    if (!q) return;
    input.value = "";
    if (!client) await connect();
    if (!client) return;
    addUser(q);
    await client.sendText(q, { run_immediately: true, audio_response: true });
  }

  // Wait for the face before allowing a call: audio must start inside the
  // visitor's click, and the face has to exist by then to receive it.
  const controls = [talk, input, ...Array.from(suggest.querySelectorAll("button"))] as (HTMLButtonElement | HTMLInputElement)[];
  controls.forEach((c) => (c.disabled = true));
  void faceReady.finally(() => controls.forEach((c) => (c.disabled = false)));

  talk.addEventListener("click", async () => {
    if (client) return hangUp();
    await connect();
  });
  mic.addEventListener("click", () => {
    if (!client) return;
    const muted = mic.getAttribute("aria-pressed") !== "true";
    client.enableMic(!muted);
    mic.setAttribute("aria-pressed", String(muted));
    mic.setAttribute("aria-label", muted ? "Unmute microphone" : "Mute microphone");
  });
  close.addEventListener("click", async () => {
    await hangUp();
    head?.stop();
    style.remove();
    panel.remove();
    opts.onClose?.();
  });
}
