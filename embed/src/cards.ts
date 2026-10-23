/** Portfolio cards shown in the Chat tab. Text only: content is never parsed as HTML. */
import { h, safeHref } from "./dom";
import type { CardPayload } from "./types";

export type Card = { title: string; body: HTMLElement };

function external(label: string, url: string | null | undefined, cls = ""): HTMLAnchorElement | null {
  const href = safeHref(url);
  return href ? h("a", { href, target: "_blank", rel: "noopener noreferrer", class: cls }, label) : null;
}

export function renderCard({ card, data }: CardPayload, firstName: string): Card | null {
  switch (card) {
    case "projects":
      return {
        title: "Projects",
        body: h(
          "div",
          { class: "rail", role: "list" },
          ...data.projects.map((p) =>
            h(
              "article",
              { class: "proj", role: "listitem" },
              p.org ? h("div", { class: "org" }, p.period ? `${p.org}, ${p.period}` : p.org) : null,
              h("div", { class: "title" }, p.name),
              p.metric ? h("div", { class: "result" }, p.metric) : null,
              h("p", {}, p.summary),
              external("View project", p.url),
            ),
          ),
        ),
      };
    case "experience":
      return {
        title: "Experience",
        body: h(
          "div",
          {},
          ...data.roles.map((r) =>
            h(
              "div",
              { class: "role" },
              h("div", { class: "co" }, r.company),
              h("div", { class: "when" }, `${r.title}, ${r.period}`),
              h("p", {}, r.summary),
            ),
          ),
          data.education.length
            ? h(
                "div",
                { class: "group" },
                h("h4", {}, "Education"),
                ...data.education.map((e) => h("p", { class: "line" }, e)),
              )
            : null,
        ),
      };
    case "skills":
      return {
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
      if (data.booking_url) rows.push(external("Book a call", data.booking_url, "action primary"));
      if (data.email) {
        const email = external(
          `Email ${firstName}`,
          `mailto:${data.email}`,
          data.booking_url ? "action" : "action primary",
        );
        email?.append(h("span", {}, data.email));
        rows.push(email);
      }
      for (const l of data.links) rows.push(external(l.label, l.url, "action"));
      return { title: `Reach the real ${firstName}`, body: h("div", { class: "actions" }, ...rows) };
    }
    case "message_sent":
      return {
        title: "Message sent",
        body: h(
          "p",
          { class: "done" },
          `Thanks${data.name ? `, ${data.name}` : ""}. ${firstName} will get your message.`,
        ),
      };
    default:
      return null;
  }
}
