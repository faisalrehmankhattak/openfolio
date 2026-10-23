/** Portfolio cards shown in the chat. Text only: content is never parsed as HTML. */
import { h, safeHref } from "./dom";
import { icon } from "./icons";
import type { CardPayload } from "./types";

export type Card = { kind: CardPayload["card"]; title: string; body: HTMLElement };

function external(
  label: string,
  url: string | null | undefined,
  cls = "",
  trailing?: SVGSVGElement,
): HTMLAnchorElement | null {
  const href = safeHref(url);
  if (!href) return null;
  const a = h("a", { href, target: "_blank", rel: "noopener noreferrer", class: cls }, h("b", {}, label));
  if (trailing) a.append(trailing);
  return a;
}

export function renderCard({ card, data }: CardPayload, firstName: string): Card | null {
  switch (card) {
    case "projects":
      return {
        kind: card,
        title: "Projects",
        body: h(
          "div",
          { class: "rail", role: "list" },
          ...data.projects.map((p) =>
            h(
              "article",
              { class: "proj", role: "listitem" },
              p.org ? h("div", { class: "org" }, p.period ? `${p.org} · ${p.period}` : p.org) : null,
              h("div", { class: "title" }, p.name),
              p.metric ? h("div", { class: "result" }, p.metric) : null,
              h("p", {}, p.summary),
              external("View project", p.url, "more", icon("out")),
            ),
          ),
        ),
      };
    case "experience":
      return {
        kind: card,
        title: "Experience",
        body: h(
          "div",
          {},
          h(
            "ol",
            { class: "timeline" },
            ...data.roles.map((r) =>
              h(
                "li",
                {},
                h("div", { class: "co" }, r.company),
                h("div", { class: "role" }, r.title),
                h("div", { class: "when" }, r.period),
                h("p", {}, r.summary),
              ),
            ),
          ),
          data.education.length
            ? h("div", { class: "group edu" }, h("h4", {}, "Education"), ...data.education.map((e) => h("p", {}, e)))
            : null,
        ),
      };
    case "skills":
      return {
        kind: card,
        title: "Skills",
        body: h(
          "div",
          {},
          ...Object.entries(data.skills).map(([group, items]) =>
            h(
              "div",
              { class: "group" },
              h("h4", {}, group),
              h("div", { class: "chips" }, ...items.map((s) => h("span", { class: "chip" }, s))),
            ),
          ),
        ),
      };
    case "contact": {
      const rows: (HTMLElement | null)[] = [];
      if (data.booking_url) rows.push(external("Book a call", data.booking_url, "action primary wide", icon("out")));
      if (data.email) {
        const email = external(
          `Email ${firstName}`,
          `mailto:${data.email}`,
          data.booking_url ? "action wide" : "action primary wide",
          icon("mail"),
        );
        email?.insertBefore(h("span", {}, data.email), email.lastChild);
        rows.push(email);
      }
      for (const l of data.links) rows.push(external(l.label, l.url, "action", icon("out")));
      return { kind: card, title: `Reach the real ${firstName}`, body: h("div", { class: "actions" }, ...rows) };
    }
    case "message_sent":
      return {
        kind: card,
        title: "Message sent",
        body: h(
          "p",
          { class: "done" },
          h("span", { class: "tick" }, icon("check")),
          h("span", {}, `Thanks${data.name ? `, ${data.name}` : ""}. ${firstName} will get your message.`),
        ),
      };
    default:
      return null;
  }
}
