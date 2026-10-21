/** Cards the persona puts on screen when it calls a tool. */
import { h, safeHref } from "./dom";

type Project = { name: string; org?: string; period?: string; summary: string; metric?: string; url?: string };
type Role = { company: string; title: string; period: string; summary: string };
type Link = { label: string; url: string };

function link(label: string, url: string | null | undefined) {
  const href = safeHref(url);
  return href ? h("a", { href, target: "_blank", rel: "noopener noreferrer" }, label) : h("span", {}, label);
}

export function renderCard(card: string, data: any): HTMLElement | null {
  switch (card) {
    case "projects":
      return h(
        "section",
        { class: "card", "aria-label": "Projects" },
        h("h3", {}, "Projects"),
        ...(data.projects as Project[]).map((p) =>
          h(
            "article",
            { class: "item" },
            h("div", { class: "item-head" }, p.url ? link(p.name, p.url) : h("strong", {}, p.name), p.org ? h("span", { class: "muted" }, ` · ${p.org}`) : null),
            p.metric ? h("div", { class: "metric" }, p.metric) : null,
            h("p", {}, p.summary),
          ),
        ),
      );
    case "experience":
      return h(
        "section",
        { class: "card", "aria-label": "Experience" },
        h("h3", {}, "Experience"),
        ...(data.roles as Role[]).map((r) =>
          h(
            "article",
            { class: "item" },
            h("div", { class: "item-head" }, h("strong", {}, r.company), h("span", { class: "muted" }, ` · ${r.period}`)),
            h("div", { class: "muted" }, r.title),
            h("p", {}, r.summary),
          ),
        ),
        data.education?.length ? h("h4", {}, "Education") : null,
        ...((data.education as string[]) || []).map((e) => h("p", { class: "muted" }, e)),
      );
    case "skills":
      return h(
        "section",
        { class: "card", "aria-label": "Skills" },
        h("h3", {}, "Skills"),
        ...Object.entries(data.skills as Record<string, string[]>).map(([group, items]) =>
          h("div", { class: "item" }, h("h4", {}, group), h("div", { class: "chips" }, ...items.map((s) => h("span", { class: "chip" }, s)))),
        ),
      );
    case "contact":
      return h(
        "section",
        { class: "card", "aria-label": "Contact" },
        h("h3", {}, "Reach the real me"),
        data.email ? h("p", {}, link(data.email, `mailto:${data.email}`)) : null,
        data.booking_url ? h("p", {}, link("Book a call", data.booking_url)) : null,
        h("div", { class: "chips" }, ...(data.links as Link[]).map((l) => h("span", { class: "chip" }, link(l.label, l.url)))),
      );
    case "message_sent":
      return h("section", { class: "card ok" }, h("strong", {}, "Message sent"), h("p", {}, `Thanks ${data.name || ""}, it's on its way.`));
    default:
      return null;
  }
}
