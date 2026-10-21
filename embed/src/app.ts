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

// Head-and-shoulders framing for a tall portrait panel (TalkingHead "upper" view).
const CAMERA = { y: 0.1, distance: -0.6 };

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
  const loading = h("div", { class: "loading" }, "Getting ready");
  const subText = h("span", { class: "text" }, info.title);
  const subDot = h("span", { class: "dot", hidden: true });
  const sub = h("div", { class: "sub" }, subDot, subText);
  const transcriptBtn = h("button", { class: "iconbtn", type: "button", "aria-label": "Show transcript" }, icon("transcript"));
  const closeBtn = h("button", { class: "iconbtn", type: "button", "aria-label": "Close" }, icon("close"));
  const top = h(
    "div",
    { class: "top" },
    h(
      "div",
      { class: "row1" },
      h("div", { class: "name" }, info.name),
      h("span", { class: "ai", title: `This is an AI version of ${first}, answering from ${first}'s portfolio` }, "AI"),
      h("span", { class: "spacer" }),
      transcriptBtn,
      opts.mode === "bubble" ? closeBtn : null,
    ),
    sub,
  );

  const capUser = h("div", { class: "cap-user" });
  const capBot = h("div", { class: "cap-bot hint" }, `Hi, I'm an AI version of ${first}. Ask me about my work.`);
  const notice = h("div", { class: "notice", role: "alert", hidden: true });
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

  const startBtn = h("button", { class: "start", type: "button" }, icon("mic"), h("span", {}, `Talk to ${first}`));
  const micBtn = h("button", { class: "mic", type: "button", hidden: true, "aria-label": "Mute microphone" }, h("span", { class: "ring" }), icon("mic"));
  const typeBtn = h("button", { class: "side", type: "button", "aria-label": "Type a question" }, icon("keyboard"));
  const endBtn = h("button", { class: "side end", type: "button", "aria-label": "End call", hidden: true }, icon("end"));
  const input = h("input", { type: "text", placeholder: `Ask ${first} anything`, "aria-label": "Your question", maxlength: "500", enterkeyhint: "send" });
  const sendBtn = h("button", { class: "side send", type: "submit", "aria-label": "Send" }, icon("send"));
  const backBtn = h("button", { class: "side", type: "button", "aria-label": "Back to voice" }, icon("mic"));
  const typeRow = h(
    "form",
    { class: "typebar", hidden: true, onsubmit: (e: Event) => { e.preventDefault(); void ask(input.value); } },
    backBtn,
    input,
    sendBtn,
  );
  const controls = h(
    "div",
    { class: "controls" },
    h("div", { class: "left" }, typeBtn),
    h("div", { class: "center" }, startBtn, micBtn),
    h("div", { class: "right" }, endBtn),
  );
  const foot = h("div", { class: "foot" }, `AI version of ${first}. It can make mistakes.`);
  const bar = h("div", { class: "bar" }, controls, typeRow, foot);

  const lower = h("div", { class: "lower" }, notice, captions, suggest);
  panel.append(headEl, loading, top, lower, cardSheet.el, logSheet.el, bar);

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
    capUser.textContent = "";
    capBot.className = `cap-bot ${kind}`;
    capBot.textContent = text;
  }
  let lastQuestion = "";
  function hideNotice() {
    notice.hidden = true;
    notice.replaceChildren();
  }
  // Errors become a short card with a plain explanation; the raw provider
  // message is one tap away on the owner's own machine.
  function showNotice(title: string, body: string, details?: string, canRetry = false) {
    const x = h("button", { class: "x", type: "button", "aria-label": "Dismiss" }, icon("close"));
    x.addEventListener("click", hideNotice);
    const links = h("div", { class: "links" });
    const detailsEl = details ? h("div", { class: "details", hidden: true }, details) : null;
    if (canRetry && lastQuestion) {
      const retry = h("button", { type: "button" }, "Try again");
      retry.addEventListener("click", () => { hideNotice(); void ask(lastQuestion); });
      links.append(retry);
    }
    if (detailsEl) {
      const toggle = h("button", { type: "button" }, "Show details");
      toggle.addEventListener("click", () => {
        detailsEl.hidden = !detailsEl.hidden;
        toggle.textContent = detailsEl.hidden ? "Show details" : "Hide details";
      });
      links.append(toggle);
    }
    notice.replaceChildren(
      h("span", { class: "mark", "aria-hidden": "true" }, "!"),
      h("div", { class: "title" }, title),
      x,
      h("div", { class: "body" }, body),
    );
    if (links.childElementCount) notice.append(links);
    if (detailsEl) notice.append(detailsEl);
    notice.hidden = false;
    capBot.textContent = "";
    capUser.textContent = "";
  }
  function explain(raw: string): { title: string; body: string } {
    if (/does not exist|model_not_found|not have access to (the )?model/i.test(raw))
      return { title: "The AI model isn't available", body: "The model name in the server settings isn't available on this account." };
    if (/reasoning_effort|function tools/i.test(raw))
      return { title: "The AI model rejected the request", body: "This model needs different settings to use tools. Update the server and restart it." };
    if (/api key|unauthorized|401|invalid_api_key|authentication/i.test(raw))
      return { title: "The AI key was rejected", body: "Check the API key in the server settings." };
    if (/quota|rate limit|429|billing/i.test(raw))
      return { title: "The AI service is over its limit", body: "The account has hit a usage or billing limit. Try again later." };
    return { title: "Couldn't get an answer", body: "Something went wrong on the server. Try again in a moment." };
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
    if (!streaming) setCaption(sentences.slice(-2).join(" "));
  }

  // Captions follow the model's text as it streams, so an answer starts
  // appearing at once instead of waiting for the voice.
  let streaming = false;
  let streamBuf = "";
  function setCaption(text: string) {
    capBot.classList.remove("hint", "error");
    capBot.textContent = text;
  }
  // A new answer: captions switch to live text only once live text arrives,
  // and otherwise follow the spoken sentences.
  function streamStart() {
    streaming = false;
    streamBuf = "";
    replay(capBot, "in");
  }
  function replay(el: HTMLElement, cls: string) {
    el.classList.remove(cls);
    void el.offsetWidth; // restart the CSS animation
    el.classList.add(cls);
  }
  function streamText(chunk: string) {
    streaming = true;
    streamBuf += chunk;
    // Keep the caption to the last two sentences so it never grows past three lines.
    const parts = streamBuf.trim().split(/(?<=[.!?])\s+/);
    setCaption(parts.slice(-2).join(" "));
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
  const faceReady = loadFace()
    .catch((err) => {
      console.warn("[openfolio] 3D face unavailable, using voice only", err);
      headEl.replaceChildren(h("div", { class: "fallback" }, h("span", {}, first.slice(0, 1))));
      headEl.classList.add("ready");
      return null;
    })
    .then((face) => {
      loading.remove();
      headEl.classList.add("ready");
      if (face) attachPendingAudio(face);
      return face;
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
      cameraY: CAMERA.y,
      cameraDistance: CAMERA.distance,
      cameraRotateEnable: false,
      mixerGainSpeech: 3,
      avatarMood: "neutral",
    });
    const avatarUrl = new URL(info.avatar.url, `${opts.server}/`).href;
    await th.showAvatar({ url: avatarUrl, body: info.avatar.body || "M", avatarMood: "neutral", lipsyncLang: "en" }, (ev: ProgressEvent) => {
      if (ev.lengthComputable) loading.textContent = `Getting ready ${Math.round((ev.loaded / ev.total) * 100)}%`;
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
    if (showDetails) (window as any).__openfolioHead = th; // for tuning the camera in development
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
    sub.className = `sub${live ? " live" : ""}${next === "speaking" ? " speaking" : ""}`;
    subDot.hidden = !live;
    subText.textContent = words[next];
    startBtn.hidden = next !== "idle" && next !== "connecting";
    startBtn.disabled = next === "connecting";
    (startBtn.lastChild as HTMLElement).textContent = next === "connecting" ? "Connecting" : `Talk to ${first}`;
    micBtn.hidden = !live;
    endBtn.hidden = !live;
    // Chips stay in place for the whole call so the captions never jump.
    suggest.querySelectorAll("button").forEach((b) => ((b as HTMLButtonElement).disabled = next === "connecting"));
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
  let botStream: MediaStream | null = null;
  let onFace = false;
  let muted = false;
  let endedReason = "";

  // The voice plays through the face (which lip-syncs it) when the face is
  // ready, and through a plain audio element until then.
  function routeBotAudio(stream: MediaStream) {
    botStream = stream;
    onFace = false;
    playEl = new Audio();
    playEl.srcObject = stream;
    playEl.autoplay = true;
    if (head && head.audioCtx.state === "running") moveAudioToFace(head);
  }
  function moveAudioToFace(face: Head) {
    if (!botStream || onFace) return;
    face.audioCtx.createMediaStreamSource(botStream).connect(face.audioAnalyzerNode);
    // Old Chrome only feeds remote tracks to Web Audio once an element touches them.
    if (playEl) playEl.muted = true;
    onFace = true;
  }
  function attachPendingAudio(face: Head) {
    if (!botStream) return;
    face.start();
    void face.audioCtx.resume().then(() => {
      if (face.audioCtx.state === "running") moveAudioToFace(face);
    });
  }
  // Browsers only start audio on a user gesture: any tap in the panel unlocks it.
  panel.addEventListener("pointerdown", () => {
    if (head && head.audioCtx.state !== "running") void head.audioCtx.resume().then(() => head && moveAudioToFace(head));
  });

  async function connect(withMic: boolean) {
    if (client) return;
    if (connecting) return connecting;
    connecting = (async () => {
      setState("connecting");
      endedReason = "";
      cardSheet.el.classList.remove("open");
      const face = head;
      if (face) {
        face.start();
        if (face.audioCtx.state !== "running") await face.audioCtx.resume().catch(() => {});
      }
      // Our own media manager: the default one loads a script from Daily's CDN.
      const media = new LocalMediaManager();
      const transport = new SmallWebRTCTransport({ mediaManager: media as any });
      // A call started by typing has no mic; turning it on later swaps it in.
      media.onLocalTrack = (track) => (transport as any).getAudioTransceiver?.()?.sender?.replaceTrack(track);
      muted = !withMic;
      const c = new PipecatClient({
        transport,
        enableMic: withMic,
        enableCam: false,
        callbacks: {
          onTrackStarted: (track, participant) => {
            if (track.kind !== "audio") return;
            if (participant?.local) return watchMicLevel(track);
            routeBotAudio(new MediaStream([track]));
          },
          onUserStartedSpeaking: () => setState("listening"),
          onUserStoppedSpeaking: () => setState("thinking"),
          onBotStartedSpeaking: () => setState("speaking"),
          onBotStoppedSpeaking: () => setState("listening"),
          onBotLlmStarted: () => streamStart(),
          onLlmRawText: (d: any) => { if (d?.text) streamText(d.text); },
          onUserTranscript: (d) => { if (d.text.trim()) userSaid(d.text.trim(), d.final); },
          onBotOutput: (d) => {
            const kind = d.text_type ?? d.aggregated_by;
            if (kind !== "sentence") return;
            const p = d.spoken_progress;
            const full = p ? `${p.accumulated_text ?? ""}${p.remaining_text ?? ""}` : d.text;
            if (full.trim()) botSaid(full.trim(), d.segment_id);
          },
          onServerMessage: (m: any) => {
            if (m?.type === "openfolio.card") showCard(m.card, m.data);
            if (m?.type === "openfolio.ended") endedReason = String(m.reason || "");
          },
          onError: (e: any) => {
            const raw = String(e?.data?.message || e?.data?.error || "");
            console.warn("[openfolio]", e);
            // Timing warnings from the voice are not worth interrupting anyone.
            const serious = e?.data?.fatal || /completion|model|api key|auth|quota|rate limit|denied|invalid|reasoning/i.test(raw);
            if (showDetails) logLine(`Error: ${raw}`, "note");
            if (!serious) return;
            const { title, body } = explain(raw);
            showNotice(title, showDetails ? body : "Something went wrong on our side. Try again in a moment.", showDetails ? raw : undefined, true);
          },
          onDisconnected: () => {
            const reason = endedReason;
            teardown();
            if (reason === "idle") showHint("The call ended because it went quiet. Ask anything to start again.");
            else if (reason === "turn_limit") showHint("That's the end of this call. Start a new one anytime.");
            else showHint("Call ended. Ask anything to start again.");
            logLine(reason === "idle" ? "Call ended because it went quiet" : "Call ended", "note");
          },
        },
      });
      try {
        await c.connect({ webrtcRequestParams: { endpoint: `${opts.server}/v1/personas/${encodeURIComponent(opts.persona)}/offer` } });
        client = c;
        setMicLook();
        setState("listening");
      } catch (err: any) {
        console.error("[openfolio]", err);
        const msg = String(err?.message || err || "");
        setState("idle");
        if (/503/.test(msg)) showNotice("All lines are busy", "Try again in a minute.");
        else if (/429/.test(msg)) showNotice("Too many calls", "This network started several calls recently. Try again in a few minutes.");
        else if (/Permission|NotAllowed/i.test(msg)) showNotice("Microphone is blocked", "Allow microphone access to talk, or tap the keyboard to type instead.");
        else showNotice("Couldn't connect", "Check your connection and try again.", showDetails ? msg : undefined);
        try { await c.disconnect(); } catch {}
      } finally {
        connecting = null;
      }
    })();
    return connecting;
  }

  function setMicLook() {
    micBtn.classList.toggle("muted", muted);
    micBtn.setAttribute("aria-label", muted ? "Turn on microphone" : "Mute microphone");
    micBtn.replaceChildren(h("span", { class: "ring" }), icon(muted ? "micOff" : "mic"));
  }

  function teardown() {
    client = null;
    levelStop?.();
    levelStop = null;
    playEl?.pause();
    playEl = null;
    botStream = null;
    onFace = false;
    streaming = false;
    setState("idle");
  }

  async function hangUp() {
    const c = client;
    teardown();
    showHint("Call ended. Tap Talk to start again.");
    try { await c?.disconnect(); } catch {}
  }

  async function ask(text: string) {
    const q = text.trim();
    if (!q) return;
    lastQuestion = q;
    hideNotice();
    input.value = "";
    userSaid(q, true);
    // Typing never asks for the microphone; the mic button turns it on later.
    if (!client) await connect(false);
    if (!client) return;
    setState("thinking");
    await client.sendText(q, { run_immediately: true, audio_response: true });
  }

  // ---- controls -----------------------------------------------------------
  startBtn.addEventListener("click", () => { hideNotice(); void connect(true); });
  endBtn.addEventListener("click", () => void hangUp());
  micBtn.addEventListener("click", () => {
    muted = !muted;
    client?.enableMic(!muted);
    setMicLook();
  });
  typeBtn.disabled = false;
  typeBtn.addEventListener("click", () => {
    typeRow.hidden = false;
    controls.hidden = true;
    input.focus();
  });
  backBtn.addEventListener("click", () => { typeRow.hidden = true; controls.hidden = false; });
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
