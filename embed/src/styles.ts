/**
 * Openfolio panel: a portrait call, not a chat box.
 * The face fills the panel; speech appears as captions over it; cards and the
 * transcript slide up as sheets; one call bar at the bottom.
 */
export const PANEL_CSS = `
.panel {
  --mist-1: #dce3ea; --mist-2: #b7c3cf; --ink: #17202b; --muted: #5b6776; --paper: #ffffff;
  --live: #128a6a; --danger: #c8443c; --accent: var(--of-accent, #17202b);
  --caption: clamp(17px, 2.2vw + 10px, 21px);
  position: relative; box-sizing: border-box; overflow: hidden; isolation: isolate;
  color: var(--ink); background: radial-gradient(120% 80% at 50% 28%, var(--mist-1) 0%, var(--mist-2) 100%);
  font: 15px/1.45 ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  border-radius: 28px; box-shadow: 0 30px 80px rgba(23, 32, 43, .28), 0 0 0 1px rgba(23, 32, 43, .08);
  -webkit-font-smoothing: antialiased;
}
@media (prefers-color-scheme: dark) {
  .panel { --mist-1: #2b3540; --mist-2: #161d25; --ink: #eef2f6; --muted: #a3afbd; --paper: #1f2731; }
}
.panel *, .panel *::before, .panel *::after { box-sizing: border-box; }
.panel [hidden] { display: none !important; }
.panel.bubble { width: min(420px, calc(100vw - 24px)); height: min(720px, calc(100vh - 40px)); }
.panel.inline { width: 100%; height: 100%; border-radius: 20px; box-shadow: none; }
@media (max-width: 520px) {
  .panel.bubble { position: fixed; inset: 0; width: 100vw; height: 100dvh; border-radius: 0; }
}
@media (prefers-reduced-motion: reduce) { .panel * { animation: none !important; transition: none !important; } }

/* Portrait */
.head { position: absolute; inset: 0 0 96px 0; z-index: 0; }
.fallback { position: absolute; inset: 0; display: grid; place-items: center; }
.fallback span { width: 132px; height: 132px; border-radius: 50%; display: grid; place-items: center;
  background: var(--ink); color: var(--mist-1); font-size: 52px; font-weight: 700; letter-spacing: -.02em; }
.loading { position: absolute; left: 50%; top: 42%; transform: translate(-50%, -50%); z-index: 1;
  color: var(--muted); font-size: 13px; }

/* Top bar */
.top { position: absolute; z-index: 3; inset: 0 0 auto 0; display: flex; align-items: flex-start; gap: 10px;
  padding: 18px 18px 40px; background: linear-gradient(to bottom, color-mix(in srgb, var(--mist-1) 85%, transparent), transparent); }
.who { flex: 1; min-width: 0; }
.name { font-size: 19px; font-weight: 700; letter-spacing: -.015em; line-height: 1.15; }
.state { display: flex; align-items: center; gap: 7px; margin-top: 3px; font-size: 13px; color: var(--muted); }
.state .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--muted); opacity: .5; }
.state.live .dot { background: var(--live); opacity: 1; box-shadow: 0 0 0 4px color-mix(in srgb, var(--live) 22%, transparent); }
.state.speaking .dot { animation: beat 1s ease-in-out infinite; }
@keyframes beat { 50% { transform: scale(1.5); } }
.ai { font-size: 12px; font-weight: 650; padding: 5px 10px; border-radius: 999px; color: var(--ink);
  background: color-mix(in srgb, var(--paper) 70%, transparent); backdrop-filter: blur(8px); white-space: nowrap; }
.iconbtn { width: 36px; height: 36px; border: 0; border-radius: 50%; display: grid; place-items: center; cursor: pointer;
  color: var(--ink); background: color-mix(in srgb, var(--paper) 70%, transparent); backdrop-filter: blur(8px); }
.iconbtn:hover { background: var(--paper); }
.iconbtn svg { width: 18px; height: 18px; }

/* Captions over the portrait */
.lower { position: absolute; z-index: 2; left: 0; right: 0; bottom: 96px; display: flex; flex-direction: column; gap: 12px;
  padding: 72px 0 14px; background: linear-gradient(to top, color-mix(in srgb, var(--mist-2) 94%, transparent) 35%, transparent); }
.captions { padding: 0 22px; pointer-events: none; }
.cap-user { font-size: 13px; color: var(--muted); margin-bottom: 6px; min-height: 1em; }
.cap-bot { font-size: var(--caption); line-height: 1.35; font-weight: 600; letter-spacing: -.01em; min-height: 2.7em;
  display: -webkit-box; -webkit-line-clamp: 4; -webkit-box-orient: vertical; overflow: hidden; text-wrap: pretty; }
.cap-bot.hint { color: var(--muted); font-weight: 500; }
.cap-bot.error { color: var(--danger); font-size: 15px; font-weight: 600; }

/* Suggestions */
.suggest { display: flex; gap: 8px; padding: 0 18px;
  overflow-x: auto; scrollbar-width: none; }
.suggest::-webkit-scrollbar { display: none; }
.suggest button { flex: 0 0 auto; border: 0; cursor: pointer; font: inherit; font-size: 14px; font-weight: 600;
  padding: 9px 15px; border-radius: 999px; color: var(--ink); background: color-mix(in srgb, var(--paper) 78%, transparent);
  backdrop-filter: blur(10px); box-shadow: 0 1px 0 rgba(23, 32, 43, .06); }
.suggest button:hover { background: var(--paper); }
.suggest[hidden] { display: none; }

/* Call bar */
.bar { position: absolute; z-index: 4; left: 0; right: 0; bottom: 0; height: 96px; display: flex; align-items: center;
  justify-content: center; gap: 22px; padding: 0 18px; background: var(--paper); border-top: 1px solid color-mix(in srgb, var(--ink) 8%, transparent); }
.bar .side { width: 48px; height: 48px; border: 0; border-radius: 50%; display: grid; place-items: center; cursor: pointer;
  color: var(--ink); background: color-mix(in srgb, var(--ink) 7%, transparent); }
.bar .side svg { width: 21px; height: 21px; }
.bar .side.end { background: var(--danger); color: #fff; }
.bar .side[hidden] { display: none; }
.mic { position: relative; width: 64px; height: 64px; border: 0; border-radius: 50%; cursor: pointer; display: grid; place-items: center;
  color: #fff; background: var(--accent); }
.mic svg { width: 26px; height: 26px; position: relative; z-index: 1; }
.mic .ring { position: absolute; inset: -6px; border-radius: 50%; border: 3px solid var(--live); opacity: 0;
  transform: scale(var(--level, 1)); transition: transform 80ms linear, opacity 160ms; }
.mic.on { background: var(--live); }
.mic.on .ring { opacity: .55; }
.mic.muted { background: color-mix(in srgb, var(--ink) 12%, transparent); color: var(--ink); }
.mic:disabled { opacity: .5; cursor: progress; }
.start { border: 0; cursor: pointer; display: flex; align-items: center; gap: 10px; height: 56px; padding: 0 26px 0 20px;
  border-radius: 999px; color: #fff; background: var(--accent); font: inherit; font-size: 16px; font-weight: 650; }
.start svg { width: 22px; height: 22px; }
.start:disabled { opacity: .55; cursor: progress; }
.type { position: absolute; inset: 0; display: flex; align-items: center; gap: 10px; padding: 0 16px; background: var(--paper); }
.type[hidden] { display: none; }
.type input { flex: 1; min-width: 0; height: 48px; border: 0; border-radius: 999px; padding: 0 18px; font: inherit; font-size: 15px;
  color: var(--ink); background: color-mix(in srgb, var(--ink) 6%, transparent); }
.type input:focus { outline: 2px solid var(--accent); }
.type .send { background: var(--accent); color: #fff; }

/* Sheets: cards and transcript */
.sheet { position: absolute; z-index: 5; left: 0; right: 0; bottom: 96px; max-height: min(60%, calc(100% - 150px)); display: flex; flex-direction: column;
  background: var(--paper); border-radius: 22px 22px 0 0; box-shadow: 0 -18px 40px rgba(23, 32, 43, .18);
  transform: translateY(calc(100% + 120px)); visibility: hidden;
  transition: transform 320ms cubic-bezier(.2, .8, .2, 1), visibility 0s linear 320ms; }
.sheet.open { transform: translateY(0); visibility: visible; transition: transform 320ms cubic-bezier(.2, .8, .2, 1), visibility 0s; }
.sheet-head { display: flex; align-items: center; justify-content: space-between; padding: 14px 14px 6px 20px; }
.sheet-head h3 { margin: 0; font-size: 16px; letter-spacing: -.01em; }
.sheet-body { overflow: auto; padding: 4px 20px 20px; }
.sheet .iconbtn { background: color-mix(in srgb, var(--ink) 6%, transparent); backdrop-filter: none; }

.rail { display: flex; gap: 12px; overflow-x: auto; scroll-snap-type: x mandatory; margin: 0 -20px; padding: 4px 20px 8px; scrollbar-width: thin; }
.proj { flex: 0 0 78%; scroll-snap-align: start; border-radius: 18px; padding: 16px; display: flex; flex-direction: column; gap: 8px;
  background: linear-gradient(160deg, var(--mist-1), color-mix(in srgb, var(--mist-2) 60%, var(--paper))); color: var(--ink); min-height: 210px; }
.proj .org { font-size: 12.5px; color: var(--muted); }
.proj .title { font-size: 18px; font-weight: 700; letter-spacing: -.015em; line-height: 1.2; }
.proj .result { font-size: 15px; font-weight: 650; line-height: 1.3; color: var(--live); }
.proj p { margin: 0; font-size: 13.5px; color: var(--muted); }
.proj a { margin-top: auto; color: var(--ink); font-weight: 600; font-size: 13.5px; }
.role { padding: 12px 0; border-top: 1px solid color-mix(in srgb, var(--ink) 8%, transparent); }
.role:first-child { border-top: 0; }
.role .co { font-weight: 700; }
.role .when { font-size: 12.5px; color: var(--muted); }
.role p { margin: 4px 0 0; font-size: 13.5px; color: var(--muted); }
.group h4 { margin: 14px 0 8px; font-size: 13px; color: var(--muted); font-weight: 600; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chip { font-size: 13px; padding: 6px 11px; border-radius: 999px; background: color-mix(in srgb, var(--ink) 6%, transparent); }
.actions { display: grid; gap: 8px; }
.action { display: flex; align-items: center; justify-content: space-between; padding: 14px 16px; border-radius: 14px;
  text-decoration: none; color: var(--ink); background: color-mix(in srgb, var(--ink) 5%, transparent); font-weight: 600; }
.action.primary { background: var(--accent); color: #fff; }
.action span { font-weight: 450; color: inherit; opacity: .7; font-size: 13px; }
.done { padding: 8px 0 4px; font-weight: 600; }
.line { margin: 0 0 12px; }
.line.user { color: var(--muted); }
.line.note { font-size: 13px; color: var(--muted); text-align: center; }

.foot { position: absolute; z-index: 4; left: 0; right: 0; bottom: 4px; text-align: center; font-size: 11px; color: var(--muted); pointer-events: none; }
button:focus-visible, a:focus-visible, input:focus-visible { outline: 3px solid var(--live); outline-offset: 2px; }
`;
