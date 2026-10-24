/**
 * app.js: loaded by embed.js when a visitor opens the widget.
 *
 * Voice runs over WebRTC to the Openfolio server (Pipecat). The face is drawn
 * here: TalkingHead renders the head and HeadAudio lip-syncs it from the
 * incoming voice, so the server never sends video.
 */
import { type BotOutputData, PipecatClient, type RTVIMessage, type TranscriptData } from "@pipecat-ai/client-js";
import { SmallWebRTCTransport } from "@pipecat-ai/small-webrtc-transport";
import { renderCard } from "./cards";
import { h } from "./dom";
import { icon } from "./icons";
import { LocalMediaManager } from "./media";
import { PANEL_CSS } from "./styles";
import { explainConnectError, explainProviderError, isHangUp, isLocal, isSeriousError, lastSentences } from "./text";
import type { EndReason, Head, MountOptions, PersonaInfo, ServerMessage } from "./types";
import { ARKIT_VISEME_FALLBACKS } from "./visemes";

export type { MountOptions } from "./types";

type CallState = "idle" | "connecting" | "listening" | "thinking" | "speaking" | "ready";

// Head-and-shoulders framing for a tall portrait panel (TalkingHead "upper" view).
const CAMERA = { y: 0.1, distance: -0.6 };
const SPEECH_GAIN = 3;
// The server ignores typed messages closer than 1.5 s apart; a quick double-send waits instead of being lost.
const TYPED_GAP_MS = 1600;
const CONNECT_TIMEOUT_MS = 20_000;

const END_HINTS: Record<EndReason | "", string> = {
  idle: "The call ended because it went quiet. Ask anything to start again.",
  turn_limit: "That's the end of this call. Start a new one anytime.",
  voice_command: "Call ended. Ask anything to start again.",
  "": "Call ended. Ask anything to start again.",
};

function isServerMessage(m: unknown): m is ServerMessage {
  const type = (m as { type?: unknown } | null)?.type;
  return type === "openfolio.card" || type === "openfolio.ended";
}

export async function mount(root: ShadowRoot, opts: MountOptions): Promise<void> {
  // Every listener on objects that outlive the panel is removed when it closes.
  const life = new AbortController();
  const style = h("style", {}, PANEL_CSS);
  const panel = h("div", { class: `panel ${opts.mode}`, role: "dialog", "aria-label": "Talk to an AI version" });
  root.append(style, panel);

  const personaUrl = `${opts.server}/v1/personas/${encodeURIComponent(opts.persona)}`;
  let info: PersonaInfo;
  try {
    const res = await fetch(personaUrl);
    if (!res.ok) throw new Error(`persona ${res.status}`);
    info = (await res.json()) as PersonaInfo;
  } catch (err) {
    panel.append(h("div", { class: "fallback" }, h("p", {}, "This assistant isn't available right now.")));
    console.error("[openfolio]", err);
    return;
  }
  const first = info.first_name;
  const showDetails = isLocal(opts.server) || isLocal(location.href);
  let chatOpen = false;
  let textOnly = false;

  // ---- layout ---------------------------------------------------------------
  const headEl = h("div", { class: "head", "aria-hidden": "true" });
  const loading = h("div", { class: "loading" }, "Getting ready");
  const subText = h("span", { class: "text" }, info.title);
  const subDot = h("span", { class: "dot", hidden: true });
  const sub = h("div", { class: "sub" }, subDot, subText);
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

  const initial = first.slice(0, 1).toUpperCase();
  const chatLog = h("div", { class: "sheet-body", role: "log", "aria-live": "polite" });
  const welcome = h(
    "div",
    { class: "welcome" },
    h(
      "div",
      { class: "welcome-inner" },
      h("div", { class: "mono", "data-initial": initial, "aria-hidden": "true" }),
      h("h2", {}, `Ask ${first} anything`),
      info.tagline ? h("p", {}, info.tagline) : null,
      h(
        "div",
        { class: "starters" },
        ...info.quick_questions.map((q) =>
          h(
            "button",
            { type: "button", onclick: () => void ask(q.question) },
            h("b", {}, q.label),
            h("span", {}, q.question),
          ),
        ),
      ),
    ),
  );
  const quick = h(
    "div",
    { class: "quick", hidden: true },
    ...info.quick_questions.map((q) =>
      h("button", { type: "button", title: q.question, onclick: () => void ask(q.question) }, q.label),
    ),
  );
  const typing = h(
    "div",
    { class: "typing", "data-initial": initial },
    h("span", { class: "sr" }, `${first} is typing`),
    h("span", { class: "dots", "aria-hidden": "true" }, h("i"), h("i"), h("i")),
  );
  const startBtn = h("button", { class: "start", type: "button" }, icon("mic"), h("span", {}, `Talk to ${first}`));
  const startLabel = startBtn.lastChild as HTMLSpanElement;
  const micBtn = h("button", { class: "mic", type: "button", hidden: true, "aria-label": "Mute microphone" });
  const endBtn = h(
    "button",
    { class: "side end", type: "button", "aria-label": "End call", hidden: true },
    icon("end"),
  );
  const chatEndBtn = h("button", { class: "chat-end", type: "button", hidden: true }, "End chat");
  const voiceSwitch = h(
    "button",
    { class: "side voice-switch", type: "button", "aria-label": "Switch to voice", title: "Switch to voice" },
    icon("mic"),
  );
  const chatSwitch = h(
    "button",
    { class: "side", type: "button", "aria-label": "Switch to chat", title: "Switch to chat" },
    icon("keyboard"),
  );
  const input = h("input", {
    type: "text",
    placeholder: `Ask ${first} anything`,
    "aria-label": "Your question",
    maxlength: "500",
    enterkeyhint: "send",
  });
  const sendBtn = h("button", { class: "side send", type: "submit", "aria-label": "Send", disabled: true }, icon("up"));
  // An empty input disables Send, which also blocks Enter (implicit submission skips a disabled default button).
  const syncSend = (): void => {
    sendBtn.disabled = !input.value.trim();
  };
  input.addEventListener("input", syncSend);
  const typeRow = h(
    "form",
    {
      class: "typebar",
      hidden: true,
      onsubmit: (e: Event) => {
        e.preventDefault();
        void ask(input.value);
      },
    },
    voiceSwitch,
    input,
    sendBtn,
  );
  const chatFoot = h(
    "div",
    { class: "chat-foot" },
    h("span", {}, `AI version of ${first}. It can make mistakes.`),
    chatEndBtn,
  );
  const chatPane = h(
    "section",
    { class: "chat-pane", "aria-label": "Chat" },
    welcome,
    chatLog,
    quick,
    typeRow,
    chatFoot,
  );
  const controls = h(
    "div",
    { class: "controls" },
    h("div", { class: "left" }, chatSwitch),
    h("div", { class: "center" }, startBtn, micBtn),
    h("div", { class: "right" }, endBtn),
  );
  const foot = h("div", { class: "foot" }, `AI version of ${first}. It can make mistakes.`);
  const lower = h("div", { class: "lower" }, notice, captions, suggest);
  panel.append(headEl, loading, top, lower, chatPane, h("div", { class: "bar" }, controls, foot));

  function setChat(open: boolean): void {
    chatOpen = open;
    (open ? chatPane : lower).prepend(notice);
    panel.classList.toggle("chat-open", open);
    typeRow.hidden = !open;
    if (open) {
      textOnly = true;
      updateAudioMode();
      if (client && !muted) {
        muted = true;
        client.enableMic(false);
        setMicLook();
      }
      input.focus();
      chatLog.scrollTop = chatLog.scrollHeight;
    }
    if (state === "listening" || state === "ready") setState("ready");
  }

  // ---- transcript and captions ---------------------------------------------
  type Turn = { el: HTMLElement; text: HTMLElement; segments: Map<string, string> };
  let botTurn: Turn | null = null;
  let streaming = false;
  let streamBuf = "";
  let lastQuestion = "";
  // Cards usually arrive before the reply text; the text is placed above them so each answer reads text first.
  let turnCards: HTMLElement[] = [];

  /** Runs a change to the log and keeps the newest message in view, unless the visitor scrolled up to read. */
  function follow(change: () => void, force = false): void {
    const stick = force || chatLog.scrollHeight - chatLog.scrollTop - chatLog.clientHeight < 72;
    change();
    if (stick) chatLog.scrollTop = chatLog.scrollHeight;
  }

  // The typing dots always stay last, so new entries go above them.
  function addToLog(el: HTMLElement): void {
    if (!welcome.hidden) {
      welcome.hidden = true;
      quick.hidden = false;
      chatPane.classList.add("started");
    }
    follow(() => chatLog.insertBefore(el, typing.isConnected ? typing : null));
  }

  function logNote(text: string): void {
    addToLog(h("p", { class: "line note" }, text));
  }

  function botLine(): Turn {
    const text = h("span", { class: "txt" });
    const el = h("p", { class: "line bot", "data-initial": initial }, h("span", { class: "sr" }, `${first}: `), text);
    const firstCard = turnCards.find((c) => c.isConnected);
    turnCards = [];
    if (firstCard) follow(() => chatLog.insertBefore(el, firstCard));
    else addToLog(el);
    return { el, text, segments: new Map() };
  }

  function showTyping(): void {
    follow(() => chatLog.append(typing), true);
  }

  function hideTyping(): void {
    typing.remove();
  }

  function stopCaret(): void {
    for (const el of chatLog.querySelectorAll(".streaming")) el.classList.remove("streaming");
  }

  function showHint(text: string): void {
    capUser.textContent = "";
    capBot.className = "cap-bot hint";
    capBot.textContent = text;
  }

  function setCaption(text: string): void {
    capBot.classList.remove("hint", "error");
    capBot.textContent = text;
  }

  function hideNotice(): void {
    notice.hidden = true;
    notice.replaceChildren();
  }

  // Errors become a short notice in plain words; raw details only on the owner's machine.
  function showNotice(title: string, body: string, details?: string, canRetry = false): void {
    hideTyping();
    const dismiss = h(
      "button",
      { class: "x", type: "button", "aria-label": "Dismiss", onclick: hideNotice },
      icon("close"),
    );
    const links = h("div", { class: "links" });
    if (canRetry && lastQuestion) {
      const question = lastQuestion;
      links.append(
        h(
          "button",
          {
            type: "button",
            onclick: () => {
              hideNotice();
              void ask(question);
            },
          },
          "Try again",
        ),
      );
    }
    const detailsEl = details ? h("div", { class: "details", hidden: true }, details) : null;
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
      dismiss,
      h("div", { class: "body" }, body),
    );
    if (links.childElementCount) notice.append(links);
    if (detailsEl) notice.append(detailsEl);
    notice.hidden = false;
    capBot.textContent = "";
    capUser.textContent = "";
  }

  function userSaid(text: string, final: boolean): void {
    capUser.textContent = text;
    if (!final) return;
    addToLog(h("p", { class: "line user" }, h("span", { class: "sr" }, "You: "), text));
    botTurn = null;
    turnCards = [];
    if (!muted && isHangUp(text)) void hangUp();
  }

  // Pipecat reports a sentence several times (queued, then spoken) under one
  // segment id; keep one entry per segment.
  function botSaid(text: string, segmentId?: string | number): void {
    if (streaming) return;
    hideTyping();
    botTurn ??= botLine();
    const turn = botTurn;
    turn.segments.set(segmentId === undefined ? `t:${text}` : `s:${segmentId}`, text);
    const sentences = [...turn.segments.values()];
    follow(() => {
      turn.text.textContent = sentences.join(" ");
    });
    setCaption(sentences.slice(-2).join(" "));
  }

  // Captions follow the model's text as it streams, ahead of the voice.
  function streamStart(): void {
    stopCaret();
    streaming = false;
    streamBuf = "";
    botTurn = null;
    capBot.classList.remove("in");
    void capBot.offsetWidth; // restart the entry animation
    capBot.classList.add("in");
  }

  function streamText(chunk: string): void {
    streaming = true;
    streamBuf += chunk;
    hideTyping();
    botTurn ??= botLine();
    const turn = botTurn;
    follow(() => {
      turn.text.textContent = streamBuf;
      turn.el.classList.add("streaming");
    });
    setCaption(lastSentences(streamBuf));
  }

  function onServerMessage(m: unknown): void {
    if (!isServerMessage(m)) return;
    if (m.type === "openfolio.ended") {
      endedReason = m.reason;
      return;
    }
    const card = renderCard(m, first);
    if (!card) return;
    const el = h("section", { class: `chat-card ${card.kind}` }, h("h3", {}, card.title), card.body);
    if (!botTurn) turnCards.push(el);
    addToLog(el);
  }

  // ---- face -----------------------------------------------------------------
  let head: Head | null = null;

  async function loadFace(): Promise<Head> {
    const [{ TalkingHead }, { HeadAudio }] = await Promise.all([
      import("@met4citizen/talkinghead"),
      import("@met4citizen/headaudio/dist/headaudio.min.mjs"),
    ]);
    const th = new TalkingHead(headEl, {
      ttsEndpoint: "N/A",
      lipsyncModules: [],
      cameraView: "upper",
      cameraY: CAMERA.y,
      cameraDistance: CAMERA.distance,
      cameraRotateEnable: false,
      mixerGainSpeech: SPEECH_GAIN,
      avatarMood: "neutral",
    });
    th.mtExtras.push(...ARKIT_VISEME_FALLBACKS);
    const avatarUrl = new URL(info.avatar.url, `${opts.server}/`).href;
    await th.showAvatar(
      { url: avatarUrl, body: info.avatar.body, avatarMood: "neutral", lipsyncLang: "en" },
      (ev: ProgressEvent) => {
        if (ev.lengthComputable) loading.textContent = `Getting ready ${Math.round((ev.loaded / ev.total) * 100)}%`;
      },
    );

    // Lip-sync from the audio itself, so every voice provider works the same way.
    await th.audioCtx.audioWorklet.addModule(`${opts.assetBase}headworklet.min.mjs`);
    const lips = new HeadAudio(th.audioCtx);
    await lips.loadModel(`${opts.assetBase}model-en-mixed.bin`);
    th.audioSpeechGainNode.connect(lips);
    lips.onvalue = (key, value) => Object.assign(th.mtAvatar[key], { newvalue: value, needsUpdate: true });
    th.opt.update = lips.update.bind(lips);
    let lastEnded = 0;
    lips.onended = () => {
      lastEnded = Date.now();
    };
    lips.onstarted = () => {
      if (Date.now() - lastEnded > 150) th.lookAtCamera(500);
    };
    document.addEventListener(
      "visibilitychange",
      () => {
        if (document.visibilityState === "visible") {
          th.start();
          lips.start();
        } else {
          lips.stop();
          th.stop();
        }
      },
      { signal: life.signal },
    );
    if (showDetails) Object.assign(window, { __openfolioHead: th }); // camera tuning in development
    head = th;
    updateAudioMode();
    return th;
  }

  void loadFace()
    .catch((err: unknown) => {
      console.warn("[openfolio] 3D face unavailable, using voice only", err);
      headEl.replaceChildren(h("div", { class: "fallback" }, h("span", {}, first.slice(0, 1))));
      return null;
    })
    .then((face) => {
      loading.remove();
      headEl.classList.add("ready");
      if (face) attachPendingAudio(face);
    });

  // ---- call state -----------------------------------------------------------
  let state: CallState = "idle";
  const STATE_WORDS: Record<Exclude<CallState, "idle" | "ready">, string> = {
    connecting: "Connecting",
    listening: "Listening",
    thinking: "Thinking",
    speaking: "Speaking",
  };

  function setState(requested: CallState): void {
    const next = (requested === "listening" && muted) || (requested === "speaking" && textOnly) ? "ready" : requested;
    state = next;
    const live = next !== "idle" && next !== "connecting";
    sub.className = `sub${live ? " live" : ""}${next === "speaking" ? " speaking" : ""}`;
    subDot.hidden = !live;
    subText.textContent =
      next === "idle"
        ? info.title
        : next === "ready"
          ? chatOpen
            ? "Chat ready"
            : "Microphone off"
          : STATE_WORDS[next];
    startBtn.hidden = live && !(muted && !chatOpen);
    startBtn.disabled = next === "connecting";
    startLabel.textContent = next === "connecting" ? "Connecting" : live && muted ? "Resume voice" : `Talk to ${first}`;
    micBtn.hidden = !live || (muted && !chatOpen);
    endBtn.hidden = !live;
    chatEndBtn.hidden = !live;
    for (const b of suggest.querySelectorAll("button")) b.disabled = next === "connecting";
  }

  // ---- mic level ring -------------------------------------------------------
  let stopLevel: (() => void) | null = null;

  function watchMicLevel(track: MediaStreamTrack): void {
    stopLevel?.();
    const ownCtx = head ? null : new AudioContext();
    const ctx = head?.audioCtx ?? (ownCtx as AudioContext);
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 512;
    const source = ctx.createMediaStreamSource(new MediaStream([track]));
    source.connect(analyser);
    const buf = new Uint8Array(analyser.fftSize);
    let raf = 0;
    const tick = (): void => {
      analyser.getByteTimeDomainData(buf);
      let sum = 0;
      for (const v of buf) sum += ((v - 128) / 128) ** 2;
      const rms = Math.sqrt(sum / buf.length);
      micBtn.style.setProperty("--level", String(1 + Math.min(rms * 4, 0.45)));
      raf = requestAnimationFrame(tick);
    };
    tick();
    stopLevel = () => {
      cancelAnimationFrame(raf);
      source.disconnect();
      void ownCtx?.close();
    };
  }

  // ---- conversation ---------------------------------------------------------
  let client: PipecatClient | null = null;
  let generation = 0;
  let connecting: Promise<void> | null = null;
  let playEl: HTMLAudioElement | null = null;
  let botStream: MediaStream | null = null;
  let onFace = false;
  let muted = false;
  let endedReason: EndReason | "" = "";
  let lastSentAt = 0;

  // The voice plays through the face (which lip-syncs it) once it is ready,
  // and through a plain audio element until then.
  function updateAudioMode(): void {
    if (head) head.audioSpeechGainNode.gain.value = textOnly ? 0 : SPEECH_GAIN;
    if (playEl) playEl.muted = onFace || textOnly;
  }

  function routeBotAudio(stream: MediaStream): void {
    botStream = stream;
    onFace = false;
    playEl = new Audio();
    playEl.srcObject = stream;
    playEl.autoplay = true;
    updateAudioMode();
    if (head?.audioCtx.state === "running") moveAudioToFace(head);
  }

  function moveAudioToFace(face: Head): void {
    if (!botStream || onFace) return;
    face.audioCtx.createMediaStreamSource(botStream).connect(face.audioAnalyzerNode);
    // Chrome only feeds a remote track to Web Audio while an element plays it, so mute rather than remove.
    if (playEl) playEl.muted = true;
    onFace = true;
  }

  function attachPendingAudio(face: Head): void {
    if (!botStream) return;
    face.start();
    void face.audioCtx.resume().then(() => {
      if (face.audioCtx.state === "running") moveAudioToFace(face);
    });
  }

  // Browsers start audio only after a user gesture: any tap in the panel unlocks it.
  panel.addEventListener("pointerdown", () => {
    const face = head;
    if (face && face.audioCtx.state !== "running") void face.audioCtx.resume().then(() => moveAudioToFace(face));
  });

  /** Also the server's admission check: busy, rate-limited and blocked calls are refused here, before WebRTC starts. */
  async function fetchIceServers(): Promise<RTCIceServer[]> {
    const res = await fetch(`${personaUrl}/ice-servers`);
    if (!res.ok) throw new Error(`Connection settings refused (${res.status})`);
    return ((await res.json()) as { iceServers: RTCIceServer[] }).iceServers;
  }

  function createClient(withMic: boolean, iceServers: RTCIceServer[], gen: number): PipecatClient {
    // Own media manager: the default one loads a script from Daily's CDN.
    const media = new LocalMediaManager();
    const transport = new SmallWebRTCTransport({ mediaManager: media as never, iceServers });
    // A call started by typing has no mic track; turning the mic on later swaps one in.
    media.onLocalTrack = async (track) => {
      const sender = (
        transport as unknown as { getAudioTransceiver?: () => RTCRtpTransceiver | undefined }
      ).getAudioTransceiver?.()?.sender;
      await sender?.replaceTrack(track);
    };
    return new PipecatClient({
      transport,
      enableMic: withMic,
      enableCam: false,
      callbacks: {
        onDeviceError: () => {
          muted = true;
          setMicLook();
          if (client) setState("ready");
          showNotice("Microphone unavailable", "Allow microphone access to talk, or switch to Chat to type.");
        },
        onTrackStarted: (track, participant) => {
          if (track.kind !== "audio") return;
          if (participant?.local) watchMicLevel(track);
          else routeBotAudio(new MediaStream([track]));
        },
        onUserStartedSpeaking: () => setState("listening"),
        onUserStoppedSpeaking: () => setState("thinking"),
        onBotStartedSpeaking: () => setState("speaking"),
        onBotStoppedSpeaking: () => setState(muted ? "ready" : "listening"),
        onBotLlmStarted: streamStart,
        onBotLlmStopped: () => {
          stopCaret();
          if (muted) setState("ready");
        },
        onBotLlmText: (d) => {
          if (d.text) streamText(d.text);
        },
        onUserTranscript: (d: TranscriptData) => {
          const text = d.text.trim();
          if (text) userSaid(text, d.final);
        },
        onBotOutput: (
          d: BotOutputData & { segment_id?: string | number; spoken_progress?: Record<string, string> },
        ) => {
          if ((d.text_type ?? d.aggregated_by) !== "sentence") return;
          const p = d.spoken_progress;
          const full = (p ? `${p.accumulated_text ?? ""}${p.remaining_text ?? ""}` : d.text).trim();
          if (full) botSaid(full, d.segment_id);
        },
        onServerMessage,
        onError: (e: RTVIMessage) => {
          const data = (e.data ?? {}) as { message?: string; error?: string; fatal?: boolean };
          const raw = String(data.message || data.error || "");
          console.warn("[openfolio]", e);
          if (!isSeriousError(raw, Boolean(data.fatal))) return;
          if (showDetails) logNote(`Error: ${raw}`);
          const { title, body } = explainProviderError(raw);
          showNotice(
            title,
            showDetails ? body : "Something went wrong on our side. Try again in a moment.",
            showDetails ? raw : undefined,
            true,
          );
        },
        onDisconnected: () => {
          if (gen !== generation) return;
          const reason = endedReason;
          teardown();
          showHint(END_HINTS[reason]);
          logNote(reason === "idle" ? "Call ended because it went quiet" : "Call ended");
        },
      },
    });
  }

  /** Ask for the microphone up front so a blocked prompt shows a clear notice instead of a stuck call. */
  async function micAllowed(): Promise<boolean> {
    try {
      const probe = await navigator.mediaDevices.getUserMedia({ audio: true });
      for (const t of probe.getTracks()) t.stop();
      return true;
    } catch (err) {
      console.warn("[openfolio] microphone unavailable", err);
      const blocked = (err as Error).name === "NotAllowedError";
      showNotice(
        blocked ? "Microphone is blocked" : "No microphone found",
        blocked
          ? "Allow microphone access in your browser's site settings, or tap the keyboard to type instead."
          : "Connect a microphone, or tap the keyboard to type instead.",
      );
      return false;
    }
  }

  async function connect(withMic: boolean): Promise<void> {
    if (client) return;
    if (connecting) return connecting;
    const gen = generation;
    connecting = (async () => {
      setState("connecting");
      endedReason = "";
      if (head) {
        head.start();
        if (head.audioCtx.state !== "running") await head.audioCtx.resume().catch(() => undefined);
      }
      if (withMic && !(await micAllowed())) {
        setState("idle");
        return;
      }
      let iceServers: RTCIceServer[];
      try {
        iceServers = await fetchIceServers();
      } catch (err) {
        if (gen !== generation) return;
        console.error("[openfolio]", err);
        const raw = String((err as Error | undefined)?.message ?? err);
        const { title, body } = explainConnectError(raw);
        setState("idle");
        showNotice(title, body, showDetails ? raw : undefined);
        return;
      }
      muted = !withMic;
      const c = createClient(withMic, iceServers, gen);
      try {
        // WebRTC retries failed offers silently; give up with a clear notice instead of spinning.
        let timer = 0;
        const timeout = new Promise<never>((_, reject) => {
          timer = window.setTimeout(() => reject(new Error("Connection timed out")), CONNECT_TIMEOUT_MS);
        });
        try {
          await Promise.race([
            c.connect({ webrtcRequestParams: { endpoint: `${personaUrl}/offer${withMic ? "" : "?greet=0"}` } }),
            timeout,
          ]);
        } finally {
          clearTimeout(timer);
        }
        if (gen !== generation) {
          await c.disconnect();
          return;
        }
        client = c;
        if (chatOpen) {
          muted = true;
          textOnly = true;
          c.enableMic(false);
          updateAudioMode();
        }
        setMicLook();
        setState("listening");
      } catch (err) {
        await c.disconnect().catch(() => undefined);
        if (gen !== generation) return;
        console.error("[openfolio]", err);
        const raw = String((err as Error | undefined)?.message ?? err ?? "");
        const { title, body } = explainConnectError(raw);
        setState("idle");
        showNotice(title, body, showDetails ? raw : undefined);
      }
    })();
    try {
      await connecting;
    } finally {
      connecting = null;
    }
  }

  function setMicLook(): void {
    micBtn.classList.toggle("muted", muted);
    micBtn.setAttribute("aria-label", muted ? "Turn on microphone" : "Mute microphone");
    micBtn.replaceChildren(h("span", { class: "ring" }), icon(muted ? "micOff" : "mic"));
  }

  function teardown(): void {
    generation++;
    client = null;
    stopLevel?.();
    stopLevel = null;
    playEl?.pause();
    playEl = null;
    botStream = null;
    onFace = false;
    streaming = false;
    hideTyping();
    stopCaret();
    setState("idle");
  }

  async function hangUp(): Promise<void> {
    const c = client;
    teardown();
    showHint("Call ended. Tap Talk to start again.");
    await c?.disconnect().catch(() => undefined);
  }

  async function ask(text: string): Promise<void> {
    const q = text.trim();
    if (!q) return;
    setChat(true);
    lastQuestion = q;
    hideNotice();
    // A starter or chip click leaves an unsent draft alone.
    if (input.value.trim() === q) input.value = "";
    syncSend();
    userSaid(q, true);
    showTyping();
    // Typing never asks for the microphone; the mic button adds voice later.
    if (!client) await connect(false);
    if (!client) return;
    const wait = lastSentAt + TYPED_GAP_MS - Date.now();
    if (wait > 0) await new Promise((resolve) => setTimeout(resolve, wait));
    lastSentAt = Date.now();
    if (!client) return;
    setState("thinking");
    try {
      await client.sendText(q, { run_immediately: true, audio_response: !chatOpen });
    } catch {
      setState(client ? "ready" : "idle");
      showNotice("Message wasn't sent", "Check your connection and try again.", undefined, true);
    }
  }

  function close(): void {
    // Remove the panel first so a slow disconnect never keeps it on screen.
    life.abort();
    head?.stop();
    style.remove();
    panel.remove();
    opts.onClose?.();
    void hangUp();
  }

  // ---- controls -------------------------------------------------------------
  startBtn.addEventListener("click", () => {
    hideNotice();
    textOnly = false;
    updateAudioMode();
    if (!client) {
      void connect(true);
      return;
    }
    muted = false;
    client.enableMic(true);
    setMicLook();
    setState("listening");
  });
  micBtn.addEventListener("click", () => {
    muted = !muted;
    if (!muted) {
      textOnly = false;
      updateAudioMode();
    }
    client?.enableMic(!muted);
    setMicLook();
    setState(muted ? "ready" : "listening");
  });
  voiceSwitch.addEventListener("click", () => {
    setChat(false);
    (startBtn.hidden ? micBtn : startBtn).focus();
  });
  chatSwitch.addEventListener("click", () => setChat(true));
  endBtn.addEventListener("click", () => void hangUp());
  chatEndBtn.addEventListener("click", () => void hangUp());
  closeBtn.addEventListener("click", close);
  if (opts.mode === "bubble") {
    panel.addEventListener("keydown", (e) => {
      if (e.key === "Escape") close();
    });
  }

  setMicLook();
  setState("idle");
  if (opts.start === "chat") setChat(true);
  else if (opts.mode === "bubble") startBtn.focus();
}
