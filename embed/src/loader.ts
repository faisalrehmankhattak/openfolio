/**
 * embed.js — the only file a site includes.
 *
 *   <script src="https://YOUR-SERVER/embed/embed.js" data-persona="faisal" async></script>
 *
 * It stays tiny: it defines <openfolio-agent>, draws a launcher, and loads the
 * real app (3D head, voice, chat) only when a visitor opens it, so the host
 * page never pays for what nobody uses.
 */

type Mode = "bubble" | "inline";

const script = document.currentScript as HTMLScriptElement | null;
const scriptUrl = script?.src ? new URL(script.src) : null;
// Where the app chunks live: next to this file.
const assetBase = scriptUrl ? new URL(".", scriptUrl).href : "";
// Default server: the origin that served this script.
const defaultServer = scriptUrl ? scriptUrl.origin : location.origin;

const LAUNCHER_CSS = `
:host { all: initial; --of-accent: #2f6fed; --of-ink: #14161a; --of-paper: #ffffff;
  font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
:host([mode="bubble"]) { position: fixed; right: 20px; bottom: 20px; z-index: 2147483000; }
:host([mode="inline"]) { display: block; width: 100%; height: 640px; }
.launch { display: flex; align-items: center; gap: 10px; border: 0; cursor: pointer;
  background: var(--of-ink); color: #fff; border-radius: 999px; padding: 8px 18px 8px 8px;
  box-shadow: 0 8px 28px rgba(0,0,0,.22); font: 600 14px/1 inherit; }
.launch:focus-visible { outline: 3px solid var(--of-accent); outline-offset: 3px; }
.dot { width: 40px; height: 40px; border-radius: 50%; background: var(--of-accent);
  display: grid; place-items: center; font-size: 15px; }
.live { width: 8px; height: 8px; border-radius: 50%; background: #3ccf6e; }
.loading { padding: 16px; color: #666; font: 14px inherit; }
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
    button.className = "launch";
    button.setAttribute("aria-label", `${name} (AI)`);
    const dot = document.createElement("span");
    dot.className = "dot";
    dot.textContent = "AI";
    const text = document.createElement("span");
    text.textContent = name;
    const live = document.createElement("span");
    live.className = "live";
    button.append(dot, text, live);
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
    const launcher = root.querySelector(".launch") as HTMLElement | null;
    if (launcher) launcher.style.display = "none";
    const loading = document.createElement("div");
    loading.className = "loading";
    loading.textContent = "Loading…";
    root.append(loading);
    try {
      const base = this.getAttribute("assets") || assetBase;
      const app = await import(/* @vite-ignore */ `${base}app.js`);
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
