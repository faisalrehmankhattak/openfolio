/** Pure text helpers. No DOM, so they run under `node --test`. */

/** Exact spoken commands only; the server applies the same rule. */
export const HANG_UP =
  /^(?:(?:please|okay|ok)\s+)?(?:end (?:the |this )?call|hang up|disconnect|stop (?:the |this )?call)[.!?]*$/i;

export const isHangUp = (text: string): boolean => HANG_UP.test(text.trim());

export const isLocal = (url: string): boolean => /^https?:\/\/(localhost|127\.0\.0\.1|\[::1\])(:|\/|$)/.test(url);

/** The last `n` sentences, so a caption never grows past a few lines. */
export function lastSentences(text: string, n = 2): string {
  return text
    .trim()
    .split(/(?<=[.!?])\s+/)
    .slice(-n)
    .join(" ");
}

export type Notice = { title: string; body: string };

/** Plain-language explanation of a provider error raised during a call. */
export function explainProviderError(raw: string): Notice {
  if (/does not exist|model_not_found|not have access to (the )?model/i.test(raw))
    return {
      title: "The AI model isn't available",
      body: "The model name in the server settings isn't available on this account.",
    };
  if (/reasoning_effort|function tools/i.test(raw))
    return {
      title: "The AI model rejected the request",
      body: "This model needs different settings to use tools. Update the server and restart it.",
    };
  if (/api key|unauthorized|401|invalid_api_key|authentication/i.test(raw))
    return { title: "The AI key was rejected", body: "Check the API key in the server settings." };
  if (/quota|rate limit|429|billing/i.test(raw))
    return {
      title: "The AI service is over its limit",
      body: "The account has hit a usage or billing limit. Try again later.",
    };
  return { title: "Couldn't get an answer", body: "Something went wrong on the server. Try again in a moment." };
}

/** Errors worth interrupting the visitor for; voice timing warnings are not. */
export const isSeriousError = (raw: string, fatal: boolean): boolean =>
  fatal || /completion|model|api key|auth|quota|rate limit|denied|invalid|reasoning/i.test(raw);

/** Plain-language explanation of a failed connection attempt. */
export function explainConnectError(raw: string): Notice {
  if (/usage limit/i.test(raw))
    return { title: "Taking a break", body: "This assistant has reached its usage limit. Please try again later." };
  if (/call limit/i.test(raw))
    return { title: "Daily limit reached", body: "You've used today's calls. Please come back tomorrow." };
  if (/\b503\b/.test(raw)) return { title: "All lines are busy", body: "Try again in a minute." };
  if (/\b429\b/.test(raw))
    return {
      title: "Too many calls",
      body: "This network started several calls recently. Try again in a few minutes.",
    };
  if (/\b403\b/.test(raw))
    return { title: "Not available on this site", body: "This site isn't allowed to use this assistant." };
  if (/Permission|NotAllowed/i.test(raw))
    return {
      title: "Microphone is blocked",
      body: "Allow microphone access to talk, or tap the keyboard to type instead.",
    };
  return { title: "Couldn't connect", body: "Check your connection and try again." };
}
