/**
 * app.js — loaded by embed.js when a visitor opens the widget.
 *
 * A portrait call: the 3D face fills the panel, speech appears as captions,
 * cards and the transcript slide up as sheets.
 *
 * Voice: Pipecat client over WebRTC to the Openfolio worker.
 * Face: TalkingHead renders the head; HeadAudio lip-syncs it from the incoming
 * voice in the browser, so the server never sends video.
 */
import { PipecatClient } from "@pipecat-ai/client-js";
import { SmallWebRTCTransport } from "@pipecat-ai/small-webrtc-transport";
import { renderCard } from "./cards";
import { h } from "./dom";
import { icon } from "./icons";
import { LocalMediaManager } from "./media";
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

type Head = { audioCtx: AudioContext; audioAnalyzerNode: AudioNode; start(): void; stop(): void };
type CallState = "idle" | "connecting" | "listening" | "thinking" | "speaking";

const isLocal = (url: string) => /^https?:\/\/(localhost|127\.0\.0\.1|\[::1\])(:|\/|$)/.test(url);

export async function mount(root: ShadowRoot, opts: MountOptions) {
  const style = h("style", {}, PANEL_CSS);
  const panel = h("div", { class: `panel ${opts.mode}`, role: "dialog", "aria-label": "Talk to an AI version" });
  root.append(style, panel);

  let info: PersonaInfo;
  try {
    const res = await fetch(`${opts.server}/v1/personas/${encodeURIComponent(opts.persona)}`);
    if (!res.ok) throw new Error(`persona ${res.status}`);
    info = await res.json();
  } catch (err) {
    panel.append(h("div", { class: "fallback" }, h("p", {}, "This assistant isn't available right now.")));
    console.error("[openfolio]", err);
    return;
  }
  const first = info.first_name;
  const showDetails = isLocal(opts.server) || isLocal(location.href);

  // ---- layout -------------------------------------------------------------
  const headEl = h("div", { class: "head", "aria-hidden": "true" });
  const loading = h("div", { class: "loading" }, "Loading face");
  const stateEl = h("div", { class: "state" }, h("span", { class: "dot" }), h("span", {}, info.title));
  const transcriptBtn = h("button", { class: "iconbtn", type: "button", "aria-label": "Show transcript" }, icon("transcript"));
  const closeBtn = h("button", { class: "iconbtn", type: "button", "aria-label": "Close" }, icon("close"));
  const top = h(
    "div",
    { class: "top" },
    h("div", { class: "who" }, h("div", { class: "name" }, info.name), stateEl),
    h("span", { class: "ai", title: `This is an AI version of ${first}, answering from ${first}'s portfolio` }, "AI version"),
    transcriptBtn,
    opts.mode === "bubble" ? closeBtn : null,
  );

  const capUser = h("div", { class: "cap-user" });
  const capBot = h("div", { class: "cap-bot hint" }, `Ask me anything about my work. I'm an AI version of ${first}.`);
  const captions = h("div", { class: "captions", "aria-live": "polite" }, capUser, capBot);

  const suggest = h(
    "div",
    { class: "suggest" },
    ...info.quick_questions.map((q) => h("button", { type: "button", onclick: () => void ask(q.question) }, q.label)),
  );

  // Card sheet and transcript sheet share one look.
  function makeSheet(label: string) {
    const title = h("h3", {}, label);
    const body = h("div", { class: "sheet-body" });
    const close = h("button", { class: "iconbtn", type: "button", "aria-label": `Close ${label.toLowerCase()}` }, icon("down"));
    const el = h("section", { class: "sheet", "aria-label": label }, h("div", { class: "sheet-head" }, title, close), body);
    close.addEventListener("click", () => el.classList.remove("open"));
    return { el, title, body };
  }
  const cardSheet = makeSheet("Card");
  const logSheet = makeSheet("Transcript");

  const startBtn = h("button", { class: "start", type: "button", disabled: true }, icon("mic"), h("span", {}, `Talk to ${first}`));
  const micBtn = h("button", { class: "mic", type: "button", hidden: true, "aria-label": "Mute microphone" }, h("span", { class: "ring" }), icon("mic"));
  const typeBtn = h("button", { class: "side", type: "button", "aria-label": "Type a question", disabled: true }, icon("keyboard"));
  const endBtn = h("button", { class: "side end", type: "button", "aria-label": "End call", hidden: true }, icon("end"));
  const input = h("input", { type: "text", placeholder: `Ask ${first} anything`, "aria-label": "Your question", maxlength: "500", enterkeyhint: "send" });
  const sendBtn = h("button", { class: "side send", type: "submit", "aria-label": "Send" }, icon("send"));
  const backBtn = h("button", { class: "side", type: "button", "aria-label": "Back to voice" }, icon("mic"));
  const typeRow = h(
    "form",
    { class: "type", hidden: true, onsubmit: (e: Event) => { e.preventDefault(); void ask(input.value); } },
    backBtn,
    input,
    sendBtn,
  );
  const bar = h("div", { class: "bar" }, typeBtn, startBtn, micBtn, endBtn, typeRow);
  const foot = h("div", { class: "foot" }, `An AI version of ${first}, answering from ${first}'s portfolio`);

  const lower = h("div", { class: "lower" }, captions, suggest);
  panel.append(headEl, loading, top, lower, cardSheet.el, logSheet.el, bar, foot);

  // ---- transcript + captions ---------------------------------------------
  type Turn = { el: HTMLElement; segments: Map<string, string> };
  let botTurn: Turn | null = null;

  function logLine(text: string, kind: "user" | "bot" | "note") {
    const el = h("p", { class: `line ${kind}` }, text);
    logSheet.body.append(el);
    logSheet.body.scrollTop = logSheet.body.scrollHeight;
    return el;
  }
  function showHint(text: string, kind: "hint" | "error" = "hint") {
    capBot.className = `cap-bot ${kind}`;
    capBot.textContent = text;
  }
  function userSaid(text: string, final: boolean) {
    capUser.textContent = text;
    if (final) {
      logLine(`You: ${text}`, "user");
      botTurn = null;
    }
  }
  // Pipecat reports each sentence several times (queued, then spoken) under one
  // segment id; keep one entry per segment and show the latest sentences.
  function botSaid(text: string, segmentId?: string | number) {
    if (!botTurn) botTurn = { el: logLine("", "bot"), segments: new Map() };
    botTurn.segments.set(segmentId === undefined ? `t:${text}` : `s:${segmentId}`, text);
    const sentences = [...botTurn.segments.values()];
    botTurn.el.textContent = `${first}: ${sentences.join(" ")}`;
    capBot.className = "cap-bot";
    capBot.textContent = sentences.slice(-2).join(" ");
  }

  function showCard(card: string, data: unknown) {
    const c = renderCard(card, data, first);
    if (!c) return;
    cardSheet.title.textContent = c.title;
    cardSheet.body.replaceChildren(c.body);
    logSheet.el.classList.remove("open");
    cardSheet.el.classList.add("open");
  }
  transcriptBtn.addEventListener("click", () => {
    cardSheet.el.classList.remove("open");
    logSheet.el.classList.toggle("open");
  });

  // ---- face ---------------------------------------------------------------
  let head: Head | null = null;
  let faceDone = false;
  const faceReady = loadFace()
    .catch((err) => {
      console.warn("[openfolio] 3D face unavailable, using voice only", err);
      headEl.replaceChildren(h("div", { class: "fallback" }, h("span", {}, first.slice(0, 1))));
      return null;
    })
    .finally(() => {
      loading.remove();
      faceDone = true;
      startBtn.disabled = state !== "idle";
      typeBtn.disabled = false;
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
      cameraView: "upper",
      cameraRotateEnable: false,
      mixerGainSpeech: 3,
      avatarMood: "neutral",
    });
    const avatarUrl = new URL(info.avatar.url, `${opts.server}/`).href;
    await th.showAvatar({ url: avatarUrl, body: info.avatar.body || "M", avatarMood: "neutral", lipsyncLang: "en" }, (ev: ProgressEvent) => {
      if (ev.lengthComputable) loading.textContent = `Loading face ${Math.round((ev.loaded / ev.total) * 100)}%`;
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
    head = th as Head;
    return head;
  }

  // ---- call state ---------------------------------------------------------
  let state: CallState = "idle";
  function setState(next: CallState) {
    state = next;
    const live = next !== "idle" && next !== "connecting";
    const words: Record<CallState, string> = {
      idle: info.title,
      connecting: "Connecting",
      listening: "Listening",
      thinking: "Thinking",
      speaking: "Speaking",
    };
    stateEl.className = `state${live ? " live" : ""}${next === "speaking" ? " speaking" : ""}`;
    (stateEl.lastChild as HTMLElement).textContent = words[next];
    startBtn.hidden = next !== "idle" && next !== "connecting";
    startBtn.disabled = next === "connecting" || !faceDone;
    micBtn.hidden = !live;
    endBtn.hidden = !live;
    suggest.hidden = live && state !== "listening";
  }

  // ---- mic level ring -----------------------------------------------------
  let levelStop: (() => void) | null = null;
  function watchMicLevel(track: MediaStreamTrack) {
    levelStop?.();
    const ctx = head?.audioCtx ?? new AudioContext();
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 512;
    ctx.createMediaStreamSource(new MediaStream([track])).connect(analyser);
    const buf = new Uint8Array(analyser.fftSize);
    let raf = 0;
    const tick = () => {
      analyser.getByteTimeDomainData(buf);
      let sum = 0;
      for (const v of buf) sum += ((v - 128) / 128) ** 2;
      const rms = Math.sqrt(sum / buf.length);
      micBtn.style.setProperty("--level", String(1 + Math.min(rms * 4, 0.45)));
      raf = requestAnimationFrame(tick);
    };
    tick();
    levelStop = () => { cancelAnimationFrame(raf); analyser.disconnect(); };
  }

  // ---- conversation -------------------------------------------------------
  let client: PipecatClient | null = null;
  let connecting: Promise<void> | null = null;
  let playEl: HTMLAudioElement | null = null;
  let muted = false;

  async function connect() {
    if (client) return;
    if (connecting) return connecting;
    connecting = (async () => {
      setState("connecting");
      cardSheet.el.classList.remove("open");
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
            if (track.kind !== "audio") return;
            if (participant?.local) return watchMicLevel(track);
            const stream = new MediaStream([track]);
            playEl = new Audio();
            playEl.srcObject = stream;
            if (face) {
              // Old Chrome only feeds remote tracks to Web Audio once an element touches them.
              playEl.muted = true;
              face.audioCtx.createMediaStreamSource(stream).connect(face.audioAnalyzerNode);
            } else {
              playEl.autoplay = true;
            }
          },
          onUserStartedSpeaking: () => setState("listening"),
          onUserStoppedSpeaking: () => setState("thinking"),
          onBotStartedSpeaking: () => setState("speaking"),
          onBotStoppedSpeaking: () => setState("listening"),
          onUserTranscript: (d) => { if (d.text.trim()) userSaid(d.text.trim(), d.final); },
          onBotOutput: (d) => {
            const kind = d.text_type ?? d.aggregated_by;
            if (kind !== "sentence") return;
            const p = d.spoken_progress;
            const full = p ? `${p.accumulated_text ?? ""}${p.remaining_text ?? ""}` : d.text;
            if (full.trim()) botSaid(full.trim(), d.segment_id);
          },
          onServerMessage: (m: any) => { if (m?.type === "openfolio.card") showCard(m.card, m.data); },
          onError: (e: any) => {
            const raw = String(e?.data?.message || e?.data?.error || "");
            console.warn("[openfolio]", e);
            // Provider errors usually wrap a readable message: show just that.
            const detail = (raw.match(/'message':\s*'([^']+)'/) || raw.match(/"message":\s*"([^"]+)"/) || [])[1] || raw;
            // Timing warnings from the voice are not worth interrupting anyone.
            const serious = e?.data?.fatal || /completion|model|api key|auth|quota|rate limit|denied|invalid/i.test(raw);
            if (showDetails) logLine(`Error: ${detail}`, "note");
            if (!serious) return;
            showHint(showDetails ? `Server error: ${detail.slice(0, 420)}` : "Something went wrong on our side. Try again in a moment.", "error");
          },
          onDisconnected: () => {
            teardown();
            logLine("Call ended", "note");
          },
        },
      });
      try {
        await c.connect({ webrtcRequestParams: { endpoint: `${opts.server}/v1/personas/${encodeURIComponent(opts.persona)}/offer` } });
        client = c;
        if (muted) c.enableMic(false);
        setState("listening");
      } catch (err: any) {
        console.error("[openfolio]", err);
        const msg = String(err?.message || err || "");
        setState("idle");
        if (/503/.test(msg)) showHint("All lines are busy. Try again in a minute.", "error");
        else if (/Permission|NotAllowed/i.test(msg)) showHint("Allow microphone access to talk, or type your question instead.", "error");
        else showHint(showDetails && msg ? `Couldn't connect: ${msg}` : "Couldn't connect. Check your connection and try again.", "error");
        try { await c.disconnect(); } catch {}
      } finally {
        connecting = null;
      }
    })();
    return connecting;
  }

  function teardown() {
    client = null;
    levelStop?.();
    levelStop = null;
    playEl?.pause();
    playEl = null;
    setState("idle");
  }

  async function hangUp() {
    const c = client;
    teardown();
    showHint("Call ended. Tap to talk again whenever you like.");
    try { await c?.disconnect(); } catch {}
  }

  async function ask(text: string) {
    const q = text.trim();
    if (!q || !faceDone) return;
    input.value = "";
    if (!client) await connect();
    if (!client) return;
    userSaid(q, true);
    setState("thinking");
    await client.sendText(q, { run_immediately: true, audio_response: true });
  }

  // ---- controls -----------------------------------------------------------
  startBtn.addEventListener("click", () => void connect());
  endBtn.addEventListener("click", () => void hangUp());
  micBtn.addEventListener("click", () => {
    muted = !muted;
    client?.enableMic(!muted);
    micBtn.classList.toggle("muted", muted);
    micBtn.classList.toggle("on", !muted);
    micBtn.setAttribute("aria-label", muted ? "Unmute microphone" : "Mute microphone");
    micBtn.replaceChildren(h("span", { class: "ring" }), icon(muted ? "micOff" : "mic"));
  });
  micBtn.classList.add("on");
  typeBtn.addEventListener("click", () => {
    typeRow.hidden = false;
    input.focus();
  });
  backBtn.addEventListener("click", () => (typeRow.hidden = true));
  closeBtn.addEventListener("click", async () => {
    await hangUp();
    head?.stop();
    style.remove();
    panel.remove();
    opts.onClose?.();
  });

  void faceReady;
  setState("idle");
}
