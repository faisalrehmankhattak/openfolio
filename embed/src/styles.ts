/**
 * Openfolio panel: a portrait call, not a chat box.
 *
 * Layout spec (8 px grid, 16 px insets):
 *   header   top 0, padding 16, row 1 = name + AI pill | icons, row 2 = one line (title or live status)
 *   face     fills the panel above the bar
 *   lower    one stack anchored 16 px above the bar: notice, captions, chips (never overlap)
 *   bar      104 px: [side 48] [primary] [side 48] centred on a 3-column grid, footer line 10 px from the bottom
 *   chat     header (84 px, fades out below), log or welcome, quick chips, input pill, footer line
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
@media (prefers-reduced-motion: reduce) { .panel *, .panel *::before, .panel *::after { animation: none !important; transition: none !important; } }

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
.foot { position: absolute; left: var(--inset); right: var(--inset); bottom: calc(10px + env(safe-area-inset-bottom)); text-align: center;
  font-size: 11.5px; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

button:focus-visible, a:focus-visible { outline: 2px solid var(--ink); outline-offset: 2px; }

/* Chat mode: the same panel with the face hidden. Voice mode above is unaffected. */
.chat-pane { display: none;
  --chat-accent: var(--accent); --soft: color-mix(in srgb, var(--ink) 6%, transparent);
  --surface: color-mix(in srgb, var(--ink) 3.5%, var(--paper)); }
/* The default accent is near-black, which would vanish on the dark paper. */
@media (prefers-color-scheme: dark) { .chat-pane { --chat-accent: var(--of-accent, #4a5a6c); } }
.chat-open .head, .chat-open .loading, .chat-open .lower, .chat-open .bar { visibility: hidden; }
.chat-open .top { background: var(--paper); padding-bottom: 12px; }
.chat-open .top::after { content: ""; position: absolute; left: 0; right: 0; top: 100%; height: 20px; pointer-events: none;
  background: linear-gradient(var(--paper), color-mix(in srgb, var(--paper) 0%, transparent)); }
.chat-open .chat-pane { position: absolute; inset: 84px 0 0; display: flex; flex-direction: column; background: var(--paper); }
.chat-pane .notice { flex: none; position: relative; z-index: 4; margin-top: 8px; }
.sr { position: absolute; width: 1px; height: 1px; margin: -1px; padding: 0; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0; }

/* Welcome, before the first message */
.welcome { flex: 1; min-height: 0; overflow-y: auto; display: flex; padding: 16px 20px 8px; }
.welcome-inner { margin: auto 0; width: 100%; text-align: center; }
.mono { width: 56px; height: 56px; margin: 0 auto 14px; border-radius: 50%; display: grid; place-items: center;
  background: var(--chat-accent); color: #fff; font-size: 23px; font-weight: 700;
  box-shadow: 0 0 0 6px color-mix(in srgb, var(--chat-accent) 10%, transparent); }
/* The empty alt text keeps the decorative initial out of the accessibility tree; older engines use the first declaration. */
.mono::before, .line.bot::before, .typing::before { content: attr(data-initial); content: attr(data-initial) / ""; }
.welcome h2 { margin: 0; font-size: 20px; font-weight: 700; letter-spacing: -.02em; line-height: 1.3; }
.welcome p { margin: 6px auto 0; max-width: 34ch; font-size: 14px; line-height: 1.5; color: var(--muted); text-wrap: balance; }
.starters { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 24px; text-align: left; }
.starters button { display: flex; flex-direction: column; justify-content: flex-start; gap: 4px; text-align: left; min-height: 78px; padding: 12px 12px 12px 14px;
  border: 1px solid var(--line); border-radius: 14px; background: var(--paper); cursor: pointer;
  transition: background-color 160ms ease, border-color 160ms ease, transform 120ms ease; }
.starters button:hover { background: var(--surface); border-color: color-mix(in srgb, var(--ink) 18%, transparent); }
.starters button:active { transform: scale(.98); }
.starters b { display: flex; align-items: center; gap: 7px; font-size: 13.5px; font-weight: 650; }
.starters b::before { content: ""; flex: none; width: 7px; height: 7px; border-radius: 50%; background: var(--tint); }
.starters span { font-size: 12.5px; line-height: 1.4; color: var(--muted); }
.starters button:last-child:nth-child(odd) { grid-column: 1 / -1; min-height: 0; }
.starters button:nth-child(5n+1), .quick button:nth-child(5n+1) { --tint: #0d9488; }
.starters button:nth-child(5n+2), .quick button:nth-child(5n+2) { --tint: #16a34a; }
.starters button:nth-child(5n+3), .quick button:nth-child(5n+3) { --tint: #7c3aed; }
.starters button:nth-child(5n+4), .quick button:nth-child(5n+4) { --tint: #e11d48; }
.starters button:nth-child(5n+5), .quick button:nth-child(5n+5) { --tint: #d97706; }

/* Messages: the visitor in accent pills on the right, the bot as plain text beside its monogram */
.chat-pane .sheet-body { flex: 1; min-height: 0; overflow-x: hidden; overflow-y: auto; overscroll-behavior: contain;
  padding: 18px 16px 8px; overflow-wrap: anywhere; }
.chat-pane:not(.started) .sheet-body { flex: none; padding: 0; }
.line { position: relative; margin: 0; white-space: pre-wrap; }
.line.user { width: fit-content; max-width: 80%; margin: 18px 0 14px auto; padding: 9px 15px; border-radius: 20px 20px 6px 20px;
  background: var(--chat-accent); color: #fff; font-size: 15px; line-height: 1.45; }
.line.user:first-child { margin-top: 2px; }
.line.bot { min-height: 28px; margin: 0 0 12px; padding: 3px 0 0 38px; font-size: 15px; line-height: 1.55; color: var(--ink); text-wrap: pretty; }
.line.bot::before, .typing::before { position: absolute; left: 0; top: 0; width: 28px; height: 28px; border-radius: 50%;
  display: grid; place-items: center; background: var(--chat-accent); color: #fff; font-size: 12.5px; font-weight: 700; line-height: 1; }
/* A reply can arrive in several model runs (opener, then the answer after a tool call): one avatar per reply. */
.line.bot + .line.bot::before { visibility: hidden; }
.line.bot.streaming .txt::after { content: ""; display: inline-block; width: 2px; height: 1.05em; margin-left: 3px; vertical-align: -.16em;
  border-radius: 1px; background: currentColor; animation: of-caret 1s steps(1) infinite; }
@keyframes of-caret { 50% { opacity: 0; } }
.line.note { display: flex; align-items: center; gap: 10px; margin: 16px 0; font-size: 12px; color: var(--muted); text-align: center; white-space: normal; }
.line.note::before, .line.note::after { content: ""; flex: 1; height: 1px; background: var(--line); }
.typing { position: relative; height: 28px; margin: 0 0 12px; padding-left: 38px; }
.typing .dots { display: inline-flex; align-items: center; gap: 4px; height: 28px; padding: 0 11px; border-radius: 14px; background: var(--soft); }
.typing i { width: 6px; height: 6px; border-radius: 50%; background: var(--muted); animation: of-bounce 1.1s ease-in-out infinite; }
.typing i:nth-child(2) { animation-delay: .15s; }
.typing i:nth-child(3) { animation-delay: .3s; }
@keyframes of-bounce { 0%, 60%, 100% { transform: none; opacity: .4; } 30% { transform: translateY(-4px); opacity: .9; } }
.chat-pane .line, .chat-card, .typing { animation: of-rise 220ms cubic-bezier(.2, .8, .2, 1) both; }
@keyframes of-rise { from { opacity: 0; transform: translateY(6px); } }

/* Cards: aligned with the bot's text column */
.chat-card { margin: 2px 0 16px 38px; }
.chat-card h3 { margin: 0 0 8px; font-size: 11px; font-weight: 650; letter-spacing: .08em; text-transform: uppercase; color: var(--muted); }
.chat-card.experience > :last-child, .chat-card.skills > :last-child, .chat-card.message_sent > :last-child {
  padding: 12px 14px; border: 1px solid var(--line); border-radius: 14px; background: var(--surface); }
.chat-card a b { font-weight: inherit; }
.rail { display: flex; gap: 10px; overflow-x: auto; scroll-snap-type: x mandatory; overscroll-behavior-x: contain;
  margin-right: -16px; padding: 0 16px 2px 0; scrollbar-width: none;
  -webkit-mask-image: linear-gradient(to right, #000 calc(100% - 44px), transparent); mask-image: linear-gradient(to right, #000 calc(100% - 44px), transparent); }
.rail::-webkit-scrollbar { display: none; }
.proj { flex: 0 0 78%; scroll-snap-align: start; display: flex; flex-direction: column; gap: 4px; padding: 14px;
  border: 1px solid var(--line); border-radius: 14px; background: var(--surface); }
.proj .org { font-size: 11.5px; color: var(--muted); }
.proj .title { font-size: 15px; font-weight: 700; letter-spacing: -.01em; line-height: 1.3; }
.proj .result { font-size: 12.5px; font-weight: 600; line-height: 1.4; color: var(--live); }
.proj p { margin: 2px 0 0; font-size: 13px; line-height: 1.45; color: var(--muted); }
.proj .more { align-self: flex-start; margin-top: auto; padding-top: 8px; display: inline-flex; align-items: center; gap: 4px;
  font-size: 13px; font-weight: 650; color: var(--ink); text-decoration: none; }
.proj .more:hover b { text-decoration: underline; text-underline-offset: 3px; }
.proj .more svg { width: 14px; height: 14px; }
.timeline { list-style: none; margin: 0; padding: 0; }
.timeline li { position: relative; padding: 0 0 14px 20px; }
.timeline li:last-child { padding-bottom: 0; }
.timeline li::before { content: ""; position: absolute; left: 0; top: 5px; width: 9px; height: 9px; border-radius: 50%;
  border: 2px solid var(--chat-accent); background: var(--surface); }
.timeline li:first-child::before { background: var(--chat-accent); }
.timeline li::after { content: ""; position: absolute; left: 4px; top: 18px; bottom: -3px; width: 1px; background: color-mix(in srgb, var(--ink) 16%, transparent); }
.timeline li:last-child::after { display: none; }
.timeline .co { font-size: 14px; font-weight: 650; line-height: 1.35; }
.timeline .role { font-size: 13px; line-height: 1.4; }
.timeline .when { margin-top: 1px; font-size: 12px; color: var(--muted); }
.timeline p { margin: 4px 0 0; font-size: 13px; line-height: 1.45; color: var(--muted); }
.group h4 { margin: 0 0 6px; font-size: 12px; font-weight: 650; color: var(--muted); }
.group + .group { margin-top: 12px; }
.edu { margin-top: 14px; padding-top: 12px; border-top: 1px solid var(--line); }
.edu p { margin: 0; font-size: 13px; line-height: 1.45; }
.edu p + p { margin-top: 4px; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chip { display: inline-flex; align-items: center; height: 26px; padding: 0 10px; border-radius: 999px; font-size: 12.5px;
  background: var(--paper); border: 1px solid var(--line); }
.actions { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.action.wide { grid-column: 1 / -1; }
.action { display: flex; align-items: center; gap: 10px; min-height: 44px; padding: 0 14px; border: 1px solid var(--line); border-radius: 12px;
  color: var(--ink); background: var(--surface); text-decoration: none; font-size: 14px; font-weight: 650;
  transition: background-color 160ms ease, filter 160ms ease; }
.action:hover { background: color-mix(in srgb, var(--ink) 7%, var(--paper)); }
.action b { flex: none; }
.action span { flex: 1; min-width: 0; font-size: 12.5px; font-weight: 450; color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.action svg { flex: none; width: 16px; height: 16px; margin-left: auto; opacity: .7; }
.action.primary { border-color: transparent; background: var(--chat-accent); color: #fff; }
.action.primary span { color: inherit; opacity: .75; }
.action.primary:hover { filter: brightness(1.12); }
.done { margin: 0; display: flex; align-items: center; gap: 10px; font-size: 14px; font-weight: 550; }
.done .tick { flex: none; width: 24px; height: 24px; border-radius: 50%; display: grid; place-items: center;
  color: var(--live); background: color-mix(in srgb, var(--live) 14%, transparent); }
.done svg { width: 14px; height: 14px; }

/* Quick questions, input and footer */
.quick { flex: none; display: flex; gap: 6px; padding: 6px 16px; overflow-x: auto; scrollbar-width: none;
  -webkit-mask-image: linear-gradient(to right, transparent, #000 12px, #000 calc(100% - 28px), transparent);
  mask-image: linear-gradient(to right, transparent, #000 12px, #000 calc(100% - 28px), transparent); }
.quick::-webkit-scrollbar { display: none; }
.quick button { flex: none; height: 30px; padding: 0 12px; border-radius: 999px; cursor: pointer; font-size: 13px; font-weight: 600;
  border: 1px solid color-mix(in srgb, var(--tint) 24%, transparent); color: color-mix(in srgb, var(--tint) 66%, var(--ink));
  background: color-mix(in srgb, var(--tint) 9%, var(--paper)); transition: background-color 160ms ease, transform 120ms ease; }
.quick button:hover { background: color-mix(in srgb, var(--tint) 16%, var(--paper)); }
.quick button:active { transform: scale(.96); }
.chat-pane .typebar { flex: none; display: flex; align-items: center; gap: 4px; margin: 4px 12px 0; padding: 4px;
  border: 1px solid transparent; border-radius: 999px; background: var(--soft);
  transition: background-color 160ms ease, border-color 160ms ease, box-shadow 160ms ease; }
.chat-pane:not(.started) .typebar { margin-top: 8px; }
.chat-pane .typebar:focus-within { background: var(--paper); border-color: color-mix(in srgb, var(--ink) 16%, transparent);
  box-shadow: 0 0 0 4px color-mix(in srgb, var(--ink) 5%, transparent), 0 2px 10px rgba(23, 32, 43, .06); }
.chat-pane .typebar input { flex: 1; min-width: 0; height: 42px; border: 0; padding: 0 6px; background: none;
  font: inherit; font-size: 16px; color: var(--ink); }
.chat-pane .typebar input::placeholder { color: var(--muted); }
.chat-pane .typebar input:focus { outline: none; }
.chat-pane .typebar .side { flex: none; width: 42px; height: 42px; }
.chat-pane .voice-switch { background: none; color: var(--muted); }
.chat-pane .voice-switch:hover { background: color-mix(in srgb, var(--ink) 8%, transparent); color: var(--ink); }
.chat-pane .send { background: var(--chat-accent); color: #fff; }
.chat-pane .send:not(:disabled):hover { filter: brightness(1.12); }
.chat-pane .send:disabled { opacity: .28; cursor: default; }
.chat-pane .send svg { width: 20px; height: 20px; }
.chat-foot { flex: none; display: flex; justify-content: center; align-items: baseline; gap: 8px;
  padding: 8px 16px calc(10px + env(safe-area-inset-bottom)); font-size: 11.5px; color: var(--muted); white-space: nowrap; }
.chat-foot span { min-width: 0; overflow: hidden; text-overflow: ellipsis; }
.chat-end { flex: none; padding: 0; border: 0; background: none; cursor: pointer; font-size: 11.5px; font-weight: 650; color: var(--ink);
  text-decoration: underline; text-decoration-color: color-mix(in srgb, var(--ink) 30%, transparent); text-underline-offset: 2px; }
.chat-end:hover { text-decoration-color: currentColor; }
`;
