/**
 * embed.js: the only file a site includes.
 *
 *   <script src="https://YOUR-SERVER/embed/embed.js" data-persona="you" async></script>
 *
 * Defines <openfolio-agent>: a portrait launcher with a short greeting. The 3D head, voice and chat load only when opened.
 */
import type { Mode, PersonaInfo, Start } from "./types";

declare const __OPENFOLIO_BUILD__: string;

const script = document.currentScript as HTMLScriptElement | null;
const scriptUrl = script?.src ? new URL(script.src) : null;
const assetBase = scriptUrl ? new URL(".", scriptUrl).href : "";
// Chunks are served next to this file, by the server that served it.
const defaultServer = scriptUrl ? scriptUrl.origin : location.origin;
const TEASER_DELAY_MS = 1200;

const ICONS = {
  mic: "M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3zM19 11a7 7 0 0 1-14 0M12 18v3",
  chat: "M5 5h14a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H9l-4 4V6a1 1 0 0 1 1-1z",
  close: "M6 6l12 12M18 6L6 18",
};

// The host page's styles can reach the host element, so every visible element sets its own font and colours.
const LAUNCHER_CSS = `
:host { all: initial; }
:host([mode="bubble"]) { position: fixed; right: 20px; bottom: 20px; z-index: 2147483000; }
:host([mode="inline"]) { display: block; width: 100%; height: 640px; }
.of-root { display: flex; flex-direction: column-reverse; align-items: flex-end; gap: 12px; color: #17202b;
  font: 400 14px/1.4 ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; -webkit-font-smoothing: antialiased; }
.of-root[hidden], .of-teaser[hidden] { display: none; }
.of-launch { position: relative; width: 68px; height: 68px; padding: 0; border: 0; border-radius: 50%; cursor: pointer; font: inherit; color: #17202b;
  background: conic-gradient(from 210deg, var(--of-accent, #17202b), #128a6a, #4cc79f, var(--of-accent, #17202b));
  box-shadow: 0 12px 32px rgba(23, 32, 43, .28); transition: transform 180ms cubic-bezier(.2, .8, .2, 1), box-shadow 180ms ease;
  animation: of-glow 4s ease-in-out infinite; }
.of-launch:hover { transform: translateY(-2px) scale(1.04); box-shadow: 0 16px 40px rgba(23, 32, 43, .34); }
.of-launch:focus-visible { outline: 3px solid #128a6a; outline-offset: 4px; }
.of-face { position: absolute; inset: 3px; border-radius: 50%; overflow: hidden; display: grid; place-items: center;
  background: radial-gradient(circle at 50% 35%, #e3e8ee, #b7c3cf); font-size: 26px; font-weight: 700; }
.of-face img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; display: block; }
/* Photo and AI avatar trade places, with a light sweep at each change: the real person and their AI version. */
.of-face.blend .of-ai { opacity: 0; animation: of-morph 9s ease-in-out 2s infinite; }
.of-face.blend::after { content: ""; position: absolute; inset: 0; pointer-events: none; translate: -120% 0;
  background: linear-gradient(115deg, transparent 35%, rgba(255, 255, 255, .6) 50%, transparent 65%); animation: of-sweep 9s ease-in-out 2s infinite; }
.of-ring { position: absolute; inset: -5px; border-radius: 50%; border: 2px solid #128a6a; opacity: 0; pointer-events: none;
  animation: of-ping 3.2s cubic-bezier(0, 0, .2, 1) 1.5s infinite; }
.of-tag { position: absolute; left: -6px; top: -2px; height: 20px; padding: 0 6px; border-radius: 6px; background: #17202b; color: #fff;
  font-size: 10.5px; font-weight: 750; line-height: 20px; letter-spacing: .04em; box-shadow: 0 0 0 2px #fff; }
.of-live { position: absolute; right: 3px; bottom: 4px; width: 14px; height: 14px; border-radius: 50%; background: #22c55e; box-shadow: 0 0 0 3px #fff; }
.of-launch::before { content: attr(data-name); position: absolute; right: calc(100% + 12px); top: 50%; translate: 0 -50%; white-space: nowrap;
  padding: 8px 12px; border-radius: 999px; background: #17202b; color: #fff; font-size: 13px; font-weight: 650; line-height: 1;
  opacity: 0; pointer-events: none; transition: opacity 150ms ease; }
.of-launch:hover::before, .of-launch:focus-visible::before { opacity: 1; }
.of-root.teasing .of-launch::before { display: none; }
.of-teaser { position: relative; width: min(296px, calc(100vw - 40px)); padding: 14px 16px; border-radius: 18px 18px 6px 18px;
  background: #fff; color: #17202b; box-shadow: 0 18px 48px rgba(23, 32, 43, .22), 0 0 0 1px rgba(23, 32, 43, .06);
  transform-origin: 100% 100%; animation: of-pop 380ms cubic-bezier(.2, .9, .3, 1.2) both; }
.of-hi { margin: 0 26px 3px 0; font-size: 15px; font-weight: 700; line-height: 1.3; letter-spacing: -.01em; }
.of-sub { margin: 0; color: #4f5b69; font-size: 13.5px; }
.of-actions { display: flex; gap: 8px; margin-top: 12px; }
.of-actions button { flex: 1; height: 38px; border: 0; border-radius: 999px; display: inline-flex; align-items: center; justify-content: center;
  gap: 7px; cursor: pointer; font: inherit; font-size: 14px; font-weight: 650; transition: filter 150ms ease, transform 120ms ease; }
.of-actions button:hover { filter: brightness(1.08); }
.of-actions button:active, .of-launch:active { transform: scale(.96); }
.of-talk { background: var(--of-accent, #17202b); color: #fff; }
.of-chat { background: rgba(23, 32, 43, .07); color: #17202b; }
.of-x { position: absolute; top: 8px; right: 8px; width: 28px; height: 28px; border: 0; border-radius: 50%; padding: 0; background: none;
  color: #4f5b69; cursor: pointer; display: grid; place-items: center; }
.of-x:hover { background: rgba(23, 32, 43, .06); }
.of-root svg { width: 16px; height: 16px; flex: none; }
.of-root button:focus-visible { outline: 2px solid #128a6a; outline-offset: 2px; }
.of-loading { padding: 16px; color: #4f5b69; font: 14px ui-sans-serif, system-ui, sans-serif; }
@keyframes of-ping { 0% { transform: scale(1); opacity: .6; } 70%, 100% { transform: scale(1.3); opacity: 0; } }
/* Glow instead of movement: a moving button is harder to click and never settles for automation tools. */
@keyframes of-glow { 0%, 100% { box-shadow: 0 12px 32px rgba(23, 32, 43, .28); } 50% { box-shadow: 0 12px 32px rgba(23, 32, 43, .28), 0 0 0 6px rgba(18, 138, 106, .18); } }
@keyframes of-morph { 0%, 38% { opacity: 0; filter: blur(3px); } 50%, 82% { opacity: 1; filter: blur(0); } 94%, 100% { opacity: 0; filter: blur(3px); } }
@keyframes of-sweep { 0%, 36% { translate: -120% 0; opacity: 1; } 50% { translate: 120% 0; opacity: 1; } 51%, 80% { translate: 120% 0; opacity: 0; }
  81% { translate: -120% 0; opacity: 0; } 82% { translate: -120% 0; opacity: 1; } 96%, 100% { translate: 120% 0; opacity: 1; } }
@keyframes of-pop { from { opacity: 0; transform: translateY(8px) scale(.94); } }
@media (prefers-color-scheme: dark) {
  .of-teaser { background: #1d242c; color: #eef2f6; box-shadow: 0 18px 48px rgba(0, 0, 0, .5), 0 0 0 1px rgba(255, 255, 255, .08); }
  .of-sub, .of-x { color: #aeb8c4; }
  .of-talk { background: #f3f5f7; color: #17202b; }
  .of-chat { background: rgba(255, 255, 255, .1); color: #eef2f6; }
  .of-x:hover { background: rgba(255, 255, 255, .08); }
}
@media (max-width: 520px) {
  :host([mode="bubble"]) { right: 14px; bottom: 14px; }
  .of-launch { width: 60px; height: 60px; }
}
@media (prefers-reduced-motion: reduce) {
  .of-launch, .of-teaser, .of-face.blend .of-ai, .of-face.blend::after { animation: none; transition: none; }
  .of-ring { display: none; }
}
`;

function el<K extends keyof HTMLElementTagNameMap>(tag: K, cls: string, text = ""): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  node.className = cls;
  if (text) node.textContent = text;
  return node;
}

function svg(path: string): SVGSVGElement {
  const ns = "http://www.w3.org/2000/svg";
  const s = document.createElementNS(ns, "svg");
  for (const [k, v] of Object.entries({
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    "stroke-width": "2",
    "stroke-linecap": "round",
    "stroke-linejoin": "round",
    "aria-hidden": "true",
  })) {
    s.setAttribute(k, v);
  }
  const p = document.createElementNS(ns, "path");
  p.setAttribute("d", path);
  s.append(p);
  return s;
}

function storageGet(key: string): string | null {
  try {
    return sessionStorage.getItem(key);
  } catch {
    return null; // storage is blocked in some private modes
  }
}

function storageSet(key: string, value: string): void {
  try {
    sessionStorage.setItem(key, value);
  } catch {
    // the teaser just shows again next time
  }
}

class OpenfolioAgent extends HTMLElement {
  private opened = false;
  private launcherRoot: HTMLElement | null = null;
  private launcher: HTMLButtonElement | null = null;
  private teaser: HTMLElement | null = null;

  connectedCallback() {
    if (this.shadowRoot) return;
    const root = this.attachShadow({ mode: "open" });
    const style = document.createElement("style");
    style.textContent = LAUNCHER_CSS;
    root.append(style);
    if (!this.getAttribute("mode")) this.setAttribute("mode", "bubble");

    if (this.mode === "inline") {
      void this.open();
      return;
    }
    const label = this.getAttribute("label") || "Talk to me";
    const wrap = el("div", "of-root");
    const button = el("button", "of-launch");
    button.type = "button";
    button.setAttribute("aria-label", `${label} (AI)`);
    button.dataset.name = label;
    const face = el("span", "of-face", "AI");
    face.setAttribute("aria-hidden", "true");
    const ring = el("span", "of-ring");
    ring.setAttribute("aria-hidden", "true");
    const tag = el("span", "of-tag", "AI");
    tag.setAttribute("aria-hidden", "true");
    const live = el("span", "of-live");
    live.setAttribute("aria-hidden", "true");
    button.append(ring, face, tag, live);
    button.addEventListener("click", () => void this.open("voice"));

    const teaser = el("div", "of-teaser");
    teaser.setAttribute("role", "group");
    teaser.setAttribute("aria-label", "Greeting from the AI assistant");
    teaser.hidden = true;
    const hi = el("p", "of-hi", label);
    const custom = this.getAttribute("teaser");
    const sub = el("p", "of-sub", custom && custom !== "off" ? custom : "Ask me about my work, by voice or chat.");
    const close = el("button", "of-x");
    close.type = "button";
    close.setAttribute("aria-label", "Dismiss greeting");
    close.append(svg(ICONS.close));
    close.addEventListener("click", () => {
      this.hideTeaser();
      button.focus();
    });
    const talk = el("button", "of-talk");
    talk.type = "button";
    talk.append(svg(ICONS.mic), "Talk");
    talk.addEventListener("click", () => void this.open("voice"));
    const chat = el("button", "of-chat");
    chat.type = "button";
    chat.append(svg(ICONS.chat), "Chat");
    chat.addEventListener("click", () => void this.open("chat"));
    const actions = el("div", "of-actions");
    actions.append(talk, chat);
    teaser.append(close, hi, sub, actions);

    // The button comes first so it is the first tab stop; column-reverse draws the greeting above it.
    wrap.append(button, teaser);
    root.append(wrap);
    this.launcherRoot = wrap;
    this.launcher = button;
    this.teaser = teaser;

    void this.loadProfile(face, hi, button, label);
    if (custom !== "off" && !storageGet(this.teaserKey)) {
      setTimeout(() => {
        if (!this.opened && !storageGet(this.teaserKey)) {
          teaser.hidden = false;
          wrap.classList.add("teasing");
        }
      }, TEASER_DELAY_MS);
    }
  }

  get mode(): Mode {
    return this.getAttribute("mode") === "inline" ? "inline" : "bubble";
  }

  private get server(): string {
    return (this.getAttribute("server") || defaultServer).replace(/\/$/, "");
  }

  private get teaserKey(): string {
    return `openfolio:teaser:${this.getAttribute("persona") || ""}`;
  }

  private hideTeaser(): void {
    storageSet(this.teaserKey, "dismissed");
    if (this.teaser) this.teaser.hidden = true;
    this.launcherRoot?.classList.remove("teasing");
  }

  /** Name and portrait from the public profile; the launcher works without them. */
  private async loadProfile(
    face: HTMLElement,
    hi: HTMLElement,
    button: HTMLButtonElement,
    label: string,
  ): Promise<void> {
    try {
      const res = await fetch(`${this.server}/v1/personas/${encodeURIComponent(this.getAttribute("persona") || "")}`);
      if (!res.ok) return;
      const info = (await res.json()) as Pick<PersonaInfo, "first_name" | "avatar">;
      hi.textContent = `Hi, I'm the AI version of ${info.first_name}.`;
      if (!this.getAttribute("label")) {
        button.dataset.name = `Talk to ${info.first_name}`;
        button.setAttribute("aria-label", `Talk to ${info.first_name} (AI)`);
      }
      face.textContent = info.first_name.slice(0, 1) || label.slice(0, 1);
      // Real photo underneath, AI avatar portrait on top; either one alone is shown as is.
      const urls = [info.avatar.photo, info.avatar.image].filter((u): u is string => Boolean(u));
      const loaded = await Promise.all(urls.map((u) => this.loadImage(u)));
      const imgs = loaded.filter((img): img is HTMLImageElement => img !== null);
      if (!imgs.length) return;
      if (imgs.length === 2) {
        imgs[1].className = "of-ai";
        face.classList.add("blend");
      }
      face.replaceChildren(...imgs);
    } catch {
      // another site's page may not be allowed to read the profile; the plain launcher still works
    }
  }

  private loadImage(url: string): Promise<HTMLImageElement | null> {
    return new Promise((resolve) => {
      const img = document.createElement("img");
      img.alt = "";
      img.decoding = "async";
      img.addEventListener("load", () => resolve(img));
      img.addEventListener("error", () => resolve(null));
      img.src = new URL(url, `${this.server}/`).href;
    });
  }

  async open(start: Start = "voice") {
    if (this.opened) return;
    this.opened = true;
    const root = this.shadowRoot;
    if (!root) return;
    if (this.teaser && !this.teaser.hidden) this.hideTeaser();
    if (this.launcherRoot) this.launcherRoot.hidden = true;
    const loading = el("div", "of-loading", "Loading…");
    root.append(loading);
    try {
      const base = this.getAttribute("assets") || assetBase;
      const app = await import(/* @vite-ignore */ `${base}app.js?v=${__OPENFOLIO_BUILD__}`);
      loading.remove();
      app.mount(root, {
        persona: this.getAttribute("persona") || "",
        server: this.server,
        assetBase: base,
        mode: this.mode,
        start,
        onClose: () => {
          this.opened = false;
          if (this.launcherRoot) this.launcherRoot.hidden = false;
          this.launcher?.focus(); // keyboard users land back where they started
        },
      });
    } catch (err) {
      loading.textContent = "Couldn't load the assistant. Please refresh and try again.";
      console.error("[openfolio]", err);
      this.opened = false;
    }
  }
}

if (!customElements.get("openfolio-agent")) {
  customElements.define("openfolio-agent", OpenfolioAgent);
}

// Script-tag mode: <script data-persona="..."> adds a floating launcher by itself.
if (script?.dataset.persona && !document.querySelector("openfolio-agent")) {
  const agent = document.createElement("openfolio-agent");
  agent.setAttribute("persona", script.dataset.persona);
  for (const key of ["server", "label", "teaser"] as const) {
    const value = script.dataset[key];
    if (value) agent.setAttribute(key, value);
  }
  const add = () => document.body.append(agent);
  if (document.body) add();
  else document.addEventListener("DOMContentLoaded", add);
}
