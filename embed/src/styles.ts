/**
 * Openfolio panel: a portrait call, not a chat box.
 *
 * Layout spec (8 px grid, 16 px insets):
 *   header   top 0, padding 16, row 1 = name + AI pill | icons, row 2 = one line (title or live status)
 *   face     fills the panel above the bar
 *   lower    one stack anchored 16 px above the bar: notice, captions, chips (never overlap)
 *   bar      104 px: [side 48] [primary] [side 48] centred on a 3-column grid, footer line 10 px from the bottom
 *   sheets   slide up from the bar, max 60% of the panel
 *
 * Colours, WCAG contrast on --paper / --mist-1: ink 16.4 / 13.3, muted 6.9 / 5.6, live 6.6 / 5.3, danger 6.6 / 5.3; white on live 6.6.
 */
export const PANEL_CSS = `
.panel {
  --mist-1: #e3e8ee; --mist-2: #c3ccd6; --ink: #17202b; --muted: #4f5b69; --paper: #ffffff; --line: rgba(23, 32, 43, .1);
  --live: #0b6a50; --danger: #b42318; --danger-soft: #fdecea; --accent: var(--of-accent, #17202b);
  --bar: 104px; --inset: 16px;
  position: relative; box-sizing: border-box; overflow: hidden; isolation: isolate;
  color: var(--ink); background: radial-gradient(120% 75% at 50% 30%, var(--mist-1) 0%, var(--mist-2) 100%);
  font: 15px/1.45 ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  border-radius: 24px; box-shadow: 0 24px 64px rgba(23, 32, 43, .26), 0 0 0 1px rgba(23, 32, 43, .08);
  -webkit-font-smoothing: antialiased;
}
@media (prefers-color-scheme: dark) {
  .panel { --mist-1: #2a333d; --mist-2: #151b22; --ink: #eef2f6; --muted: #aeb8c4; --paper: #1d242c; --line: rgba(255, 255, 255, .1);
    --live: #4cc79f; --danger: #ff8a7a; --danger-soft: #3a2422; }
}
:where(.panel) *, :where(.panel) *::before, :where(.panel) *::after { box-sizing: border-box; }
.panel [hidden] { display: none !important; }
:where(.panel) button { font: inherit; color: inherit; -webkit-tap-highlight-color: transparent; }
.panel.bubble { width: min(400px, calc(100vw - 24px)); height: min(700px, calc(100vh - 40px)); }
.panel.inline { width: 100%; height: 100%; border-radius: 20px; box-shadow: 0 0 0 1px var(--line); }
@media (max-width: 520px) {
  .panel.bubble { position: fixed; inset: 0; width: 100vw; height: 100dvh; border-radius: 0; box-shadow: none; }
  .panel { --bar: calc(104px + env(safe-area-inset-bottom)); }
}
@media (prefers-reduced-motion: reduce) { .panel *, .panel *::before { animation: none !important; transition: none !important; } }

/* Motion: one opening move, then only motion that answers an action */
.panel { animation: of-open 280ms cubic-bezier(.2, .8, .2, 1) both; transform-origin: 100% 100%; }
.panel.inline { animation: none; }
@keyframes of-open { from { opacity: 0; transform: translateY(14px) scale(.97); } }
.cap-bot.in { animation: of-in 220ms ease-out both; }
@keyframes of-in { from { opacity: 0; transform: translateY(4px); } }
.start, .mic, .side, .suggest button, .iconbtn { transition: transform 120ms ease, background-color 160ms ease, box-shadow 160ms ease; }
.start:active, .mic:active, .side:active, .suggest button:active, .iconbtn:active { transform: scale(.96); }

/* Face */
.head { position: absolute; inset: 0 0 var(--bar) 0; z-index: 0; opacity: 0; transition: opacity 500ms ease; }
.head.ready { opacity: 1; }
.loading::before { content: ""; display: block; width: 88px; height: 88px; margin: 0 auto 12px; border-radius: 50%;
  background: color-mix(in srgb, var(--ink) 8%, transparent); animation: of-pulse 1.4s ease-in-out infinite; }
@keyframes of-pulse { 50% { opacity: .45; } }
.fallback { position: absolute; inset: 0 0 var(--bar) 0; display: grid; place-items: center; }
.fallback span { width: 128px; height: 128px; border-radius: 50%; display: grid; place-items: center;
  background: var(--ink); color: var(--mist-1); font-size: 48px; font-weight: 700; }
.loading { position: absolute; z-index: 1; left: 0; right: 0; top: 44%; text-align: center; font-size: 13px; color: var(--muted); }

/* Header */
.top { position: absolute; z-index: 3; inset: 0 0 auto 0; padding: var(--inset) var(--inset) 32px;
  background: linear-gradient(to bottom, var(--mist-1) 0%, color-mix(in srgb, var(--mist-1) 80%, transparent) 55%, transparent 100%); }
.row1 { display: flex; align-items: center; gap: 8px; height: 36px; }
.name { font-size: 18px; font-weight: 700; letter-spacing: -.015em; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; }
.ai { flex: none; height: 22px; padding: 0 8px; border-radius: 6px; display: inline-flex; align-items: center;
  font-size: 11.5px; font-weight: 650; color: var(--muted); background: color-mix(in srgb, var(--ink) 7%, transparent); }
.spacer { flex: 1; }
.iconbtn { flex: none; width: 36px; height: 36px; border: 0; border-radius: 50%; display: grid; place-items: center; cursor: pointer;
  color: var(--ink); background: color-mix(in srgb, var(--paper) 72%, transparent); }
.iconbtn:hover { background: var(--paper); }
.iconbtn svg { width: 18px; height: 18px; }
.sub { display: flex; align-items: center; gap: 8px; height: 20px; font-size: 13px; color: var(--muted);
  white-space: nowrap; overflow: hidden; }
.sub .text { overflow: hidden; text-overflow: ellipsis; }
.sub .dot { flex: none; width: 8px; height: 8px; border-radius: 50%; background: var(--live); }
.sub.live { color: var(--live); font-weight: 600; }
.sub.speaking .dot { animation: beat 1s ease-in-out infinite; }
@keyframes beat { 50% { opacity: .35; } }

/* Lower stack: notice, captions, chips */
.lower { position: absolute; z-index: 2; left: 0; right: 0; bottom: var(--bar); display: flex; flex-direction: column; gap: 12px;
  padding: 56px 0 var(--inset);
  background: linear-gradient(to top, var(--mist-1) 0%, color-mix(in srgb, var(--mist-1) 88%, transparent) 55%, transparent 100%); }
.captions { padding: 0 var(--inset); }
.cap-user { font-size: 13px; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.cap-user:empty { display: none; }
.cap-bot { margin-top: 4px; font-size: 18px; line-height: 1.38; font-weight: 600; letter-spacing: -.01em; color: var(--ink);
  display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; text-wrap: pretty; }
.cap-bot.hint { font-size: 16px; font-weight: 500; color: var(--muted); }
.cap-bot:empty { display: none; }

.notice { margin: 0 var(--inset); display: grid; grid-template-columns: 24px 1fr 28px; gap: 4px 10px; align-items: start;
  padding: 12px 10px 12px 12px; border-radius: 14px; background: var(--paper); box-shadow: 0 6px 20px rgba(23, 32, 43, .12); }
.notice .mark { width: 24px; height: 24px; border-radius: 50%; display: grid; place-items: center;
  background: var(--danger-soft); color: var(--danger); font-weight: 800; font-size: 14px; }
.notice .title { font-size: 14px; font-weight: 650; line-height: 24px; }
.notice .body { grid-column: 2; font-size: 13px; color: var(--muted); }
.notice .details { grid-column: 2 / 4; margin-top: 4px; padding: 8px 10px; border-radius: 8px; font-size: 12px; line-height: 1.4;
  color: var(--muted); background: color-mix(in srgb, var(--ink) 5%, transparent); overflow-wrap: anywhere; max-height: 96px; overflow: auto; }
.notice .links { grid-column: 2; display: flex; gap: 16px; margin-top: 2px; }
.notice .links button { border: 0; background: none; padding: 0; cursor: pointer; font-size: 13px; font-weight: 650; color: var(--ink);
  text-decoration: underline; text-underline-offset: 3px; }
.notice .x { grid-column: 3; grid-row: 1; width: 28px; height: 28px; border: 0; border-radius: 50%; background: none; cursor: pointer;
  display: grid; place-items: center; color: var(--muted); }
.notice .x svg { width: 16px; height: 16px; }

.suggest { display: flex; gap: 8px; padding: 0 var(--inset); overflow-x: auto; scrollbar-width: none;
  -webkit-mask-image: linear-gradient(to right, #000 calc(100% - 24px), transparent); mask-image: linear-gradient(to right, #000 calc(100% - 24px), transparent); }
.suggest::-webkit-scrollbar { display: none; }
.suggest button { flex: none; height: 36px; padding: 0 14px; border: 0; border-radius: 999px; cursor: pointer;
  font-size: 14px; font-weight: 600; color: var(--ink); background: var(--paper); box-shadow: 0 1px 2px rgba(23, 32, 43, .08); }
.suggest button:hover { box-shadow: 0 0 0 1.5px var(--ink); }
.suggest button:disabled { opacity: .5; cursor: progress; }

/* Call bar */
.bar { position: absolute; z-index: 4; left: 0; right: 0; bottom: 0; height: var(--bar); background: var(--paper);
  border-top: 1px solid var(--line); }
.controls { position: absolute; left: 0; right: 0; top: 12px; height: 64px; display: grid; grid-template-columns: 1fr auto 1fr; align-items: center; }
.controls .left { justify-self: end; margin-right: 20px; }
.controls .right { justify-self: start; margin-left: 20px; }
.side { width: 48px; height: 48px; border: 0; border-radius: 50%; display: grid; place-items: center; cursor: pointer;
  background: color-mix(in srgb, var(--ink) 7%, transparent); }
.side:hover { background: color-mix(in srgb, var(--ink) 12%, transparent); }
.side svg { width: 20px; height: 20px; }
.side.end { background: var(--danger); color: #fff; }
.side.end:hover { filter: brightness(1.08); }
.side:disabled { opacity: .45; cursor: progress; }
.start { height: 52px; padding: 0 24px 0 20px; border: 0; border-radius: 999px; cursor: pointer; display: flex; align-items: center; gap: 10px;
  color: #fff; background: var(--accent); font-size: 16px; font-weight: 650; white-space: nowrap; }
.start svg { width: 20px; height: 20px; }
.start:disabled { opacity: .55; cursor: progress; }
.mic { position: relative; width: 64px; height: 64px; border: 0; border-radius: 50%; cursor: pointer; display: grid; place-items: center;
  color: #fff; background: var(--live); }
.mic svg { position: relative; z-index: 1; width: 24px; height: 24px; }
.mic .ring { position: absolute; inset: -5px; border-radius: 50%; border: 2px solid var(--live); opacity: .5;
  transform: scale(var(--level, 1)); transition: transform 80ms linear; }
.mic.muted { background: color-mix(in srgb, var(--ink) 12%, transparent); color: var(--ink); }
.mic.muted .ring { opacity: 0; }
.typebar { position: absolute; left: 12px; right: 12px; top: 18px; height: 52px; display: flex; align-items: center; gap: 8px; }
.typebar input { flex: 1; min-width: 0; height: 48px; border: 0; border-radius: 999px; padding: 0 18px; font: inherit; font-size: 16px;
  color: var(--ink); background: color-mix(in srgb, var(--ink) 6%, transparent); }
.typebar input::placeholder { color: var(--muted); }
.typebar input:focus { outline: 2px solid var(--ink); outline-offset: 0; }
.typebar .send { background: var(--accent); color: #fff; }
.foot { position: absolute; left: var(--inset); right: var(--inset); bottom: calc(10px + env(safe-area-inset-bottom)); text-align: center;
  font-size: 11.5px; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

/* Sheets: cards and transcript */
.sheet { position: absolute; z-index: 5; left: 0; right: 0; bottom: var(--bar); max-height: min(60%, calc(100% - 140px));
  display: flex; flex-direction: column; background: var(--paper); border-radius: 20px 20px 0 0; box-shadow: 0 -12px 32px rgba(23, 32, 43, .16);
  transform: translateY(calc(100% + 120px)); visibility: hidden;
  transition: transform 300ms cubic-bezier(.2, .8, .2, 1), visibility 0s linear 300ms; }
.sheet.open { transform: translateY(0); visibility: visible; transition: transform 300ms cubic-bezier(.2, .8, .2, 1), visibility 0s; }
.sheet-head { flex: none; display: flex; align-items: center; justify-content: space-between; height: 56px; padding: 0 12px 0 var(--inset); }
.sheet-head h3 { margin: 0; font-size: 16px; font-weight: 700; letter-spacing: -.01em; }
.sheet .iconbtn { background: color-mix(in srgb, var(--ink) 6%, transparent); }
.sheet-body { overflow: auto; padding: 0 var(--inset) var(--inset); }

.rail { display: flex; gap: 12px; overflow-x: auto; scroll-snap-type: x mandatory; margin: 0 calc(-1 * var(--inset));
  padding: 0 var(--inset) 4px; scroll-padding: 0 var(--inset); scrollbar-width: none; }
.rail::-webkit-scrollbar { display: none; }
.proj { flex: 0 0 82%; scroll-snap-align: start; border-radius: 16px; padding: 16px; display: flex; flex-direction: column; gap: 6px;
  background: var(--mist-1); min-height: 200px; }
.proj .org { font-size: 12.5px; color: var(--muted); }
.proj .title { font-size: 17px; font-weight: 700; letter-spacing: -.015em; line-height: 1.25; }
.proj .result { font-size: 14.5px; font-weight: 650; line-height: 1.35; color: var(--live); }
.proj p { margin: 2px 0 0; font-size: 13.5px; color: var(--muted); }
.proj a { margin-top: auto; padding-top: 8px; color: var(--ink); font-weight: 650; font-size: 13.5px; text-underline-offset: 3px; }
.count { margin-top: 10px; font-size: 12.5px; color: var(--muted); text-align: center; }
.role { padding: 12px 0; border-top: 1px solid var(--line); }
.role:first-child { border-top: 0; padding-top: 0; }
.role .co { font-weight: 700; }
.role .when { font-size: 13px; color: var(--muted); }
.role p { margin: 4px 0 0; font-size: 13.5px; color: var(--muted); }
.group h4 { margin: 0 0 8px; font-size: 13px; font-weight: 650; color: var(--muted); }
.group + .group { margin-top: 16px; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chip { height: 30px; display: inline-flex; align-items: center; padding: 0 11px; border-radius: 999px; font-size: 13px; background: var(--mist-1); }
.actions { display: grid; gap: 8px; }
.action { display: flex; align-items: center; justify-content: space-between; gap: 12px; min-height: 52px; padding: 0 16px; border-radius: 14px;
  text-decoration: none; color: var(--ink); background: var(--mist-1); font-weight: 650; }
.action.primary { background: var(--accent); color: #fff; }
.action span { font-weight: 450; font-size: 13px; opacity: .75; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.done { margin: 0; font-weight: 600; }
.line { margin: 0 0 10px; font-size: 14px; }
.line.user { color: var(--muted); }
.line.note { font-size: 12.5px; color: var(--muted); text-align: center; }
.empty { color: var(--muted); font-size: 14px; }

button:focus-visible, a:focus-visible { outline: 2px solid var(--ink); outline-offset: 2px; }

/* One compact panel with explicit voice and chat modes. */
.chat-pane { display: none; }
.chat-open .head, .chat-open .loading, .chat-open .lower, .chat-open .bar { visibility: hidden; }
.chat-open .top { background: var(--paper); padding-bottom: 12px; }
.chat-open .chat-pane { position: absolute; inset: 88px 0 0; display: flex; flex-direction: column; background: var(--paper); }
.chat-pane .sheet-body { flex: 1; min-height: 0; padding: 16px; overflow-wrap: anywhere; }
.chat-pane .notice { flex: none; margin-top: 8px; }
.chat-pane .typebar { position: static; flex: none; margin: 12px; padding: 3px; border-radius: 999px; background: color-mix(in srgb, var(--ink) 6%, transparent); }
.chat-pane .typebar input { background: none; padding: 0 6px; }
.chat-pane .typebar .side { flex: none; width: 42px; height: 42px; }
.chat-pane .typebar:focus-within { outline: 2px solid var(--ink); }
.chat-pane .typebar input:focus { outline: none; }
.chat-end { align-self: center; border: 0; background: none; color: var(--danger) !important; padding: 0 16px 14px; font-size: 12px !important; cursor: pointer; }
.chat-pane .line { padding: 12px 14px; border-radius: 14px; background: var(--mist-1); white-space: pre-wrap; }
.chat-pane .line.user { margin-left: 24px; background: var(--accent); color: white; }
.chat-pane .line.note { background: none; }
.chat-card { border: 1px solid var(--line); border-radius: 16px; padding: 14px; margin: 12px 0; }
.chat-card h3 { margin: 0 0 12px; font-size: 15px; }
.chat-card .rail { display: grid; margin: 0; padding: 0; gap: 10px; }
.chat-card .proj { min-height: auto; }
`;
