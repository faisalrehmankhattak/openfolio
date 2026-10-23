# Voice / Chat verification

Verified locally on 2026-10-23 at http://localhost:7860/ using the real backend and configured providers.

| Scenario | Result | Evidence |
| --- | --- | --- |
| Initial widget opens in Voice | Pass | Avatar, call controls, Voice tab selected |
| Chat replaces Voice | Pass | Avatar and voice controls hidden; full-width chat and composer visible |
| Blank or whitespace submission | Pass | No connection or conversation turn created |
| Draft survives tab switching | Pass | Exact unsent draft retained |
| Real text question | Pass | Generated response and project/skill/contact cards rendered in Chat |
| Switching during connection | Pass | Chat finishes with microphone off and Chat ready status |
| History and cards survive switching | Pass | Existing conversation retained |
| Return to Voice | Pass | Microphone off; explicit Resume voice action |
| Resume voice | Pass | Microphone acquired; Listening and Mute microphone controls appeared |
| Mute | Pass | Microphone off status and Resume voice control |
| End session in Chat | Pass | Session ended; new question reconnects |
| End call in Voice | Pass | Idle state restored |
| Close and reopen | Pass | Launcher works and a fresh widget opens |
| Desktop layout | Pass | 1100 × 850 viewport; panel remains 400 × 700, composer inside panel |
| Mobile layout | Pass | 390 × 844 viewport; single full-screen mode, composer visible |
| Spoken hang-up routing | Pass, automated | Exact commands end the session before reaching the model; ordinary questions do not |
| Backend regressions | Pass | 19 tests |
| TypeScript and production build | Pass | typecheck and both Vite builds |

Added safeguards for microphone acquisition errors, send failures, cancellation during connection, and stale disconnect callbacks. These failure paths were reviewed and compiled, but were not all injected in the browser.

Still requires manual or separate environment testing: real speech recognition and spoken hang-up through a physical microphone; denied or revoked microphone permission; network loss and recovery; provider outages/quotas; idle and maximum-duration expiry under the new modes; inline embedding across host sites; Safari/Firefox; mobile virtual keyboard, physical devices, screen readers, and keyboard-only operation. This is representative coverage, not proof of every possible scenario.

History persists while switching modes and ending/restarting sessions within the open widget. Closing/reopening or reloading starts a fresh widget; history is not stored across page reloads.
