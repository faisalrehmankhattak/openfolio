/** Cards the persona puts on screen when it calls a tool. Text only, never raw HTML. */
import { h, safeHref } from "./dom";

type Project = { name: string; org?: string; period?: string; summary: string; metric?: string; url?: string };
type Role = { company: string; title: string; period: string; summary: string };
type Link = { label: string; url: string };

export type Card = { title: string; body: HTMLElement };

function ext(label: string, url: string | null | undefined, cls = "") {
  const href = safeHref(url);
  return href ? h("a", { href, target: "_blank", rel: "noopener noreferrer", class: cls }, label) : null;
}

export function renderCard(card: string, data: any, firstName: string): Card | null {
  switch (card) {
    case "projects":
      return {
        title: "Projects",
        body: h(
          "div",
          { class: "rail", role: "list" },
          ...(data.projects as Project[]).map((p) =>
            h(
              "article",
              { class: "proj", role: "listitem" },
              p.org ? h("div", { class: "org" }, p.period ? `${p.org}, ${p.period}` : p.org) : null,
              h("div", { class: "title" }, p.name),
              p.metric ? h("div", { class: "result" }, p.metric) : null,
              h("p", {}, p.summary),
              ext("Open project", p.url),
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
          ...(data.roles as Role[]).map((r) =>
            h("div", { class: "role" }, h("div", { class: "co" }, r.company), h("div", { class: "when" }, `${r.title}, ${r.period}`), h("p", {}, r.summary)),
          ),
          data.education?.length
            ? h("div", { class: "group" }, h("h4", {}, "Education"), ...(data.education as string[]).map((e) => h("p", { class: "line" }, e)))
            : null,
        ),
      };
    case "skills":
      return {
        title: "Skills",
        body: h(
          "div",
          {},
          ...Object.entries(data.skills as Record<string, string[]>).map(([group, items]) =>
            h("div", { class: "group" }, h("h4", {}, group), h("div", { class: "chips" }, ...items.map((s) => h("span", { class: "chip" }, s)))),
          ),
        ),
      };
    case "contact": {
      const rows: (HTMLElement | null)[] = [];
      if (data.booking_url) rows.push(ext("Book a call", data.booking_url, "action primary"));
      if (data.email) {
        const a = ext(`Email ${firstName}`, `mailto:${data.email}`, `action ${data.booking_url ? "" : "primary"}`);
        a?.append(h("span", {}, data.email));
        rows.push(a);
      }
      for (const l of data.links as Link[]) rows.push(ext(l.label, l.url, "action"));
      return { title: `Reach the real ${firstName}`, body: h("div", { class: "actions" }, ...rows) };
    }
    case "message_sent":
      return {
        title: "Message sent",
        body: h("p", { class: "done" }, `Thanks${data.name ? `, ${data.name}` : ""}. ${firstName} will get your message.`),
      };
    default:
      return null;
  }
}
