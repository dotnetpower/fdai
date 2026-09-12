/** Repository-authored, static visual grammar. Symbols never imply a measured status. */
const symbols = {
  target: '<circle cx="16" cy="16" r="11"/><circle cx="16" cy="16" r="6"/><circle cx="16" cy="16" r="1"/>',
  data: '<ellipse cx="16" cy="7" rx="11" ry="4"/><path d="M5 7v18c0 5 22 5 22 0V7M5 16c0 5 22 5 22 0"/>',
  context: '<rect x="12" y="3" width="8" height="7" rx="1"/><rect x="3" y="22" width="8" height="7" rx="1"/><rect x="21" y="22" width="8" height="7" rx="1"/><path d="M16 10v6M7 22v-6h18v6"/>',
  ai: '<rect x="8" y="8" width="16" height="16" rx="4"/><path d="M12 3v5m8-5v5M12 24v5m8-5v5M3 12h5m-5 8h5m16-8h5m-5 8h5M12 13h8m-8 6h5"/>',
  people: '<circle cx="11" cy="10" r="5"/><path d="M2 28v-3a9 9 0 0 1 18 0v3M21 5a5 5 0 0 1 0 10m2 4a8 8 0 0 1 7 9"/>',
  shield: '<path d="m16 3 11 4v9c0 7-11 13-11 13S5 23 5 16V7l11-4Zm-6 12 4 4 8-8"/>',
  change: '<path d="M5 8h20l-5-5m5 5-5 5M27 24H7l5-5m-5 5 5 5"/>',
  document: '<path d="M7 3h12l7 7v19H7V3Zm12 0v8h7M11 17h11m-11 6h8"/>',
  clock: '<circle cx="16" cy="16" r="12"/><path d="M16 8v9l6 3"/>',
  search: '<circle cx="13" cy="13" r="9"/><path d="m20 20 9 9M9 13h8m-4-4v8"/>',
  check: '<circle cx="16" cy="16" r="12"/><path d="m9 16 5 5 10-11"/>',
  hold: '<circle cx="16" cy="16" r="12"/><path d="M12 10v12m8-12v12"/>',
  cost: '<path d="M4 28h25M7 24V14h5v10m4 0V8h5v16m4 0V3h5v21"/>',
  compare: '<path d="M4 4h24v24H4V4Zm12 0v24M8 10h4m-4 7h4m8-7h4m-4 7h4"/>',
  cycle: '<path d="M27 12A12 12 0 0 0 6 7l-3 5m0-8v8h8M5 20a12 12 0 0 0 21 5l3-5m0 8v-8h-8"/>',
  link: '<path d="m13 19 6-6M12 23l-3 3a6 6 0 0 1-8-8l7-7a6 6 0 0 1 8 0m0 10a6 6 0 0 0 8 0l7-7a6 6 0 0 0-8-8l-3 3"/>',
};

/** Decorative monoline icon; adjacent authored text supplies its complete meaning. */
export function icon(name) {
  if (!(name in symbols)) throw new Error(`Unknown readiness symbol: ${name}`);
  return `<svg class="rm-symbol" viewBox="0 0 32 32" aria-hidden="true">${symbols[name]}</svg>`;
}

/** A named node in one local diagram; no identifiers or states leave the presentation. */
export function node(id, label, title, detail, symbol, placement = "") {
  return `<article class="rm-node" data-rm-node="${id}"${placement ? ` style="${placement}"` : ""}>${icon(symbol)}<small>${label}</small><h3>${title}</h3><p>${detail}</p></article>`;
}

/** Grid connectors expose their real endpoints and orientation for browser measurement. */
export function edge(from, to, direction = "right", placement = "") {
  return `<div class="rm-link" data-rm-from="${from}" data-rm-to="${to}" data-rm-direction="${direction}"${placement ? ` style="${placement}"` : ""}><i aria-hidden="true"></i></div>`;
}

/** Several source records converge on one bounded evidence purpose. */
export function convergence(items, target) {
  return `<div class="rm-graph rm-convergence" style="--rows:${items.length}">${items.map(([label, title, detail, symbol], index) =>
    node(`source-${index}`, label, title, detail, symbol, `grid-row:${index + 1};grid-column:1`) +
    edge(`source-${index}`, "bundle", "right", `grid-row:${index + 1};grid-column:2`),
  ).join("")}${node("bundle", ...target, `grid-column:3;grid-row:1 / span ${items.length}`)}</div>`;
}

/** Six perspectives share an assessment subject; the lines do not grant authority. */
export function dimensionMap(items) {
  return `<div class="rm-graph rm-dimension-map">${items.map(([label, title, detail, symbol], index) => {
    const row = index % 3 + 1;
    const right = index >= 3;
    return node(`dimension-${index}`, label, title, detail, symbol, `grid-column:${right ? 5 : 1};grid-row:${row}`) +
      edge(`dimension-${index}`, "decision", right ? "left" : "right", `grid-column:${right ? 4 : 2};grid-row:${row}`);
  }).join("")}${node("decision", "ASSESSMENT SUBJECT", "One Operational Decision", "Review six capabilities\nusing the same scope and evidence", "target", "grid-column:3;grid-row:1 / 4")}</div>`;
}

/** Four versioned review steps share a clockwise cycle, not a workflow execution path. */
export function reviewCycle(steps) {
  return `<div class="rm-graph rm-review-cycle">${node("detect", ...steps[0], "grid-column:1;grid-row:1")}
    ${edge("detect", "pin", "right", "grid-column:2;grid-row:1")}
    ${node("pin", ...steps[1], "grid-column:3;grid-row:1")}
    ${edge("pin", "compare", "down", "grid-column:3;grid-row:2")}
    ${node("compare", ...steps[2], "grid-column:3;grid-row:3")}
    ${edge("compare", "review", "left", "grid-column:2;grid-row:3")}
    ${node("review", ...steps[3], "grid-column:1;grid-row:3")}
    ${edge("review", "detect", "up", "grid-column:1;grid-row:2")}
    <span class="rm-cycle-label">New Review for Every Change</span></div>`;
}

/** Discrete category positions have no implied numeric distance, score, or missing-value zero. */
export function maturityPosition(level) {
  if (level === null) return '<div class="rm-category-axis is-unassessed" data-level="unassessed"><span>Unassessed / Evidence Requested</span></div>';
  return `<div class="rm-category-axis" data-level="${level}" aria-label="Current assessment ${level}">${[1, 2, 3, 4, 5].map(index =>
    `<span class="${`M${index}` === level ? "is-current" : "is-empty"}" data-category="M${index}">${`M${index}` === level ? level : '<i aria-hidden="true"></i>'}</span>`,
  ).join("")}</div>`;
}

/** Proportions encode the proposed meeting minutes only, with exact SVG path lengths. */
export function agendaRing(agenda) {
  const total = agenda.reduce((sum, item) => sum + item.minutes, 0);
  let elapsed = 0;
  return `<div class="rm-agenda-ring" role="img" aria-label="Proposed ${total}-minute workshop: ${agenda.map(item => `${item.activity} ${item.minutes} minutes`).join(", ")}">
    <svg viewBox="0 0 240 240" aria-hidden="true">${agenda.map((item, index) => {
      const arc = `<circle cx="120" cy="120" r="96" pathLength="${total}" stroke-dasharray="${item.minutes} ${total - item.minutes}" stroke-dashoffset="${-elapsed}" data-rm-minutes="${item.minutes}" style="--agenda-index:${index}"/>`;
      elapsed += item.minutes;
      return arc;
    }).join("")}</svg><div><strong>${total}</strong><span>minutes / proposal</span></div></div>`;
}
