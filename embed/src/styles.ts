export const PANEL_CSS = `
.panel { --bg: var(--of-paper, #fff); --ink: var(--of-ink, #14161a); --muted: #5d6470; --line: #e3e6eb;
  --accent: var(--of-accent, #2f6fed); --soft: #f4f6f9;
  box-sizing: border-box; display: flex; flex-direction: column; background: var(--bg); color: var(--ink);
  font: 14px/1.45 ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  border: 1px solid var(--line); border-radius: 18px; overflow: hidden; box-shadow: 0 18px 60px rgba(0,0,0,.22); }
@media (prefers-color-scheme: dark) {
  .panel { --bg: #15171b; --ink: #eef0f3; --muted: #a2a9b4; --line: #2a2e35; --soft: #1e2127; }
}
.panel *, .panel *::before, .panel *::after { box-sizing: border-box; }
.panel.bubble { width: min(400px, calc(100vw - 24px)); height: min(680px, calc(100vh - 40px)); }
.panel.inline { width: 100%; height: 100%; box-shadow: none; }
@media (max-width: 520px) {
  .panel.bubble { position: fixed; inset: 0; width: 100vw; height: 100dvh; border-radius: 0; border: 0; }
}
header { display: flex; align-items: center; gap: 10px; padding: 12px 14px; border-bottom: 1px solid var(--line); }
header .who { flex: 1; min-width: 0; }
header .name { font-weight: 650; }
header .title { color: var(--muted); font-size: 12.5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.badge { font-size: 11px; font-weight: 650; padding: 3px 8px; border-radius: 999px; background: var(--soft); color: var(--muted); }
.icon { border: 0; background: transparent; color: var(--muted); cursor: pointer; font-size: 18px; padding: 6px; border-radius: 8px; }
.icon:hover { background: var(--soft); }
.stage { position: relative; overflow: hidden; flex: 0 0 46%; min-height: 200px; background: radial-gradient(circle at 50% 35%, var(--soft), var(--bg) 70%); }
.stage .head { position: absolute; inset: 0; }
.stage .fallback { position: absolute; inset: 0; display: grid; place-items: center; }
.stage .fallback span { width: 96px; height: 96px; border-radius: 50%; background: var(--accent); color: #fff;
  display: grid; place-items: center; font-size: 34px; font-weight: 700; }
.stage .status { position: absolute; z-index: 2; left: 12px; top: 10px; white-space: nowrap; line-height: 1.4; font-size: 12px; color: var(--muted);
  background: var(--bg); padding: 3px 9px; border-radius: 999px; border: 1px solid var(--line); }
.stage .status .live-dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; background: #3ccf6e; margin-right: 6px; }
.card { background: var(--bg); border: 1px solid var(--line); border-radius: 14px; padding: 12px 14px; box-shadow: 0 6px 24px rgba(0,0,0,.12); }
.card h3 { margin: 0 0 8px; font-size: 14px; }
.card h4 { margin: 8px 0 4px; font-size: 12.5px; color: var(--muted); font-weight: 600; }
.card p { margin: 4px 0; }
.card .item { padding: 8px 0; border-top: 1px solid var(--line); }
.card .item:first-of-type { border-top: 0; }
.card .metric { color: var(--accent); font-weight: 600; font-size: 12.5px; }
.card.ok { border-color: #3ccf6e; }
.card a { color: var(--accent); }
.muted { color: var(--muted); }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chip { font-size: 12px; padding: 4px 9px; border-radius: 999px; background: var(--soft); border: 1px solid var(--line); }
.log { flex: 1; overflow: auto; padding: 10px 14px; display: flex; flex-direction: column; gap: 8px; }
.msg { max-width: 88%; padding: 8px 11px; border-radius: 14px; }
.msg.bot { background: var(--soft); align-self: flex-start; border-bottom-left-radius: 4px; }
.msg.user { background: var(--accent); color: #fff; align-self: flex-end; border-bottom-right-radius: 4px; }
.msg.cardmsg { max-width: 100%; width: 100%; padding: 0; }
.msg.cardmsg .card { box-shadow: none; }
.msg.note { align-self: center; color: var(--muted); font-size: 12.5px; background: transparent; text-align: center; }
.suggest { display: flex; gap: 6px; padding: 0 14px 8px; overflow-x: auto; }
.suggest button { flex: 0 0 auto; border: 1px solid var(--line); background: var(--bg); color: var(--ink);
  border-radius: 999px; padding: 6px 12px; cursor: pointer; font: inherit; font-size: 12.5px; }
.suggest button:hover { border-color: var(--accent); }
.controls { display: flex; gap: 8px; padding: 10px 12px; border-top: 1px solid var(--line); align-items: center; }
.controls input { flex: 1; min-width: 0; border: 1px solid var(--line); background: var(--bg); color: var(--ink);
  border-radius: 999px; padding: 9px 13px; font: inherit; }
.controls input:focus { outline: 2px solid var(--accent); border-color: transparent; }
.talk { border: 0; border-radius: 999px; padding: 9px 16px; font: 650 14px/1 inherit; cursor: pointer;
  background: var(--accent); color: #fff; white-space: nowrap; }
.talk.end { background: #d64545; }
.talk:disabled { opacity: .6; cursor: default; }
.mic { border: 1px solid var(--line); background: var(--bg); color: var(--ink); border-radius: 999px; padding: 8px 11px; cursor: pointer; }
.mic[aria-pressed="true"] { background: #d64545; color: #fff; border-color: #d64545; }
footer { text-align: center; font-size: 11px; color: var(--muted); padding: 0 0 8px; }
footer a { color: inherit; }
button:focus-visible { outline: 3px solid var(--accent); outline-offset: 2px; }
`;
