/** Presentation-scale architecture primitives with measurable node and edge identities. */

/** Render one component or external-system node inside an architecture diagram. */
export function archNode(id, label, title, detail = "", options = {}) {
  const {
    tone = "neutral",
    status = "",
    classes = "",
    primary = false,
    footer = "",
  } = options;
  return `
    <section class="ta-arch-node ${classes}" data-ta-node="${id}" data-tone="${tone}">
      ${label ? `<small>${label}</small>` : ""}
      <strong${primary ? " data-ta-primary" : ""}>${title}</strong>
      ${detail ? `<span>${detail}</span>` : ""}
      ${status ? `<em data-status="${status}">${status}</em>` : ""}
      ${footer ? `<b>${footer}</b>` : ""}
    </section>`;
}

/** Render one directional, typed connection between nodes in the same CSS grid. */
export function archLink(from, to, options = {}) {
  const {
    kind = "event",
    direction = "right",
    label = "",
    classes = "",
  } = options;
  return `
    <i class="ta-arch-link ta-link-${kind} ${classes}"
       data-ta-link data-ta-from="${from}" data-ta-to="${to}"
       data-ta-direction="${direction}" aria-hidden="true">
      ${label ? `<span>${label}</span>` : ""}
    </i>`;
}

/** Render a labeled architecture boundary without implying runtime authority. */
export function archBoundary(label, title, body, options = {}) {
  const {
    id = "",
    classes = "",
    status = "",
    tone = "neutral",
  } = options;
  return `
    <section class="ta-arch-boundary ${classes}"${id ? ` data-ta-node="${id}"` : ""} data-tone="${tone}">
      <header><small>${label}</small><strong>${title}</strong>${status ? `<em data-status="${status}">${status}</em>` : ""}</header>
      <div>${body}</div>
    </section>`;
}

/** Render a non-color-only connection legend for one diagram. */
export function archLegend(items) {
  return `<div class="ta-arch-legend" aria-label="Connection legend">${items.map(({ kind, label }) => `<span><i class="ta-legend-line ta-link-${kind}" aria-hidden="true"></i>${label}</span>`).join("")}</div>`;
}
