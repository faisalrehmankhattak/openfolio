/** Inline SVG icons (stroke style, 24px grid). Built with DOM APIs, no innerHTML. */
const PATHS: Record<string, string[]> = {
  mic: ["M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3z", "M19 11a7 7 0 0 1-14 0", "M12 18v3"],
  micOff: [
    "M15 9.3V6a3 3 0 0 0-5.7-1.3",
    "M9 9v3a3 3 0 0 0 5.1 2.1",
    "M19 11a7 7 0 0 1-1.2 3.9",
    "M5 11a7 7 0 0 0 10.8 5.9",
    "M12 18v3",
    "M3 3l18 18",
  ],
  keyboard: ["M3 7h18v10H3z", "M7 11h.01M11 11h.01M15 11h.01M7 14h10"],
  end: ["M3.5 14.5c4.7-4.2 12.3-4.2 17 0l-2 2.5-3.2-1.3v-2.4a10 10 0 0 0-6.6 0v2.4L5.5 17z"],
  close: ["M6 6l12 12", "M18 6L6 18"],
  down: ["M6 9l6 6 6-6"],
  send: ["M5 12h13", "M13 6l6 6-6 6"],
  transcript: ["M5 6h14", "M5 11h14", "M5 16h9"],
};

const NS = "http://www.w3.org/2000/svg";

export function icon(name: keyof typeof PATHS | string): SVGSVGElement {
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "2");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.setAttribute("aria-hidden", "true");
  for (const d of PATHS[name] ?? []) {
    const p = document.createElementNS(NS, "path");
    p.setAttribute("d", d);
    svg.append(p);
  }
  return svg;
}
