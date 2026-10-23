/**
 * embed.js — the only file a site includes.
 *
 *   <script src="https://YOUR-SERVER/embed/embed.js" data-persona="faisal" async></script>
 *
 * It stays tiny: it defines <openfolio-agent>, draws a launcher, and loads the
 * real app (3D head, voice, chat) only when a visitor opens it, so the host
 * page never pays for what nobody uses.
 */

declare const __OPENFOLIO_BUILD__: string;

type Mode = "bubble" | "inline";

const script = document.currentScript as HTMLScriptElement | null;
const scriptUrl = script?.src ? new URL(script.src) : null;
// Where the app chunks live: next to this file.
const assetBase = scriptUrl ? new URL(".", scriptUrl).href : "";
// Default server: the origin that served this script.
const defaultServer = scriptUrl ? scriptUrl.origin : location.origin;

const LAUNCHER_CSS = `
:host { all: initial;
  font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
:host([mode="bubble"]) { position: fixed; right: 20px; bottom: 20px; z-index: 2147483000; }
:host([mode="inline"]) { display: block; width: 100%; height: 640px; }
.of-launch { display: flex; align-items: center; gap: 12px; border: 0; cursor: pointer;
  background: var(--of-accent, #17202b); color: #fff; border-radius: 999px; padding: 7px 20px 7px 7px;
  box-shadow: 0 14px 40px rgba(23,32,43,.3); font: 650 15px/1 ui-sans-serif, system-ui, -apple-system, sans-serif; }
.of-launch:hover { transform: translateY(-1px); }
.of-launch:focus-visible { outline: 3px solid #128a6a; outline-offset: 3px; }
.of-badge { position: relative; width: 42px; height: 42px; border-radius: 50%; background: radial-gradient(circle at 50% 35%, #dce3ea, #b7c3cf);
  color: #17202b; display: grid; place-items: center; font-size: 12px; font-weight: 750; }
.of-badge::after { content: ""; position: absolute; right: 0; bottom: 1px; width: 11px; height: 11px; border-radius: 50%;
  background: #128a6a; box-shadow: 0 0 0 2px var(--of-accent, #17202b); }
@media (prefers-reduced-motion: reduce) { .of-launch:hover { transform: none; } }
.of-loading { padding: 16px; color: #666; font: 14px inherit; }
`;

class OpenfolioAgent extends HTMLElement {
  private opened = false;

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
    const name = this.getAttribute("label") || "Talk to me";
    const button = document.createElement("button");
    button.className = "of-launch";
    button.setAttribute("aria-label", `${name} (AI)`);
    const dot = document.createElement("span");
    dot.className = "of-badge";
    dot.textContent = "AI";
    const text = document.createElement("span");
    text.textContent = name;
    button.append(dot, text);
    button.addEventListener("click", () => void this.open());
    root.append(button);
  }

  get mode(): Mode {
    return this.getAttribute("mode") === "inline" ? "inline" : "bubble";
  }

  async open() {
    if (this.opened) return;
    this.opened = true;
    const root = this.shadowRoot!;
    const launcher = root.querySelector(".of-launch") as HTMLElement | null;
    if (launcher) launcher.style.display = "none";
    const loading = document.createElement("div");
    loading.className = "of-loading";
    loading.textContent = "Loading…";
    root.append(loading);
    try {
      const base = this.getAttribute("assets") || assetBase;
      const app = await import(/* @vite-ignore */ `${base}app.js?v=${__OPENFOLIO_BUILD__}`);
      loading.remove();
      app.mount(root, {
        persona: this.getAttribute("persona") || "",
        server: (this.getAttribute("server") || defaultServer).replace(/\/$/, ""),
        assetBase: base,
        mode: this.mode,
        onClose: () => {
          this.opened = false;
          if (launcher) launcher.style.display = "";
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

// Script-tag mode: <script data-persona="..."> adds a floating bubble by itself.
if (script?.dataset.persona && !document.querySelector("openfolio-agent")) {
  const el = document.createElement("openfolio-agent");
  el.setAttribute("persona", script.dataset.persona);
  if (script.dataset.server) el.setAttribute("server", script.dataset.server);
  if (script.dataset.label) el.setAttribute("label", script.dataset.label);
  const add = () => document.body.append(el);
  if (document.body) add();
  else document.addEventListener("DOMContentLoaded", add);
}
