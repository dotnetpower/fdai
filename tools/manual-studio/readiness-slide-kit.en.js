/** Author static readiness teaching material; no assessment or execution runs here. */
import { icon } from "./readiness-diagrams.en.js";

export const sources = {
  constitution: "docs/roadmap/architecture/fdai-constitution.md",
  governance: "docs/roadmap/architecture/data-governance.md",
  ontology: "docs/roadmap/architecture/operating-ontology.md",
  ingestion: "docs/roadmap/interfaces/document-ingestion.md",
  llm: "docs/roadmap/architecture/llm-strategy.md",
  metrics: "docs/roadmap/architecture/goals-and-metrics.md",
};

const sourceLabels = {
  constitution: "FDAI Constitution",
  governance: "Data Governance",
  ontology: "Operating Ontology",
  ingestion: "Document Ingestion",
  llm: "LLM Strategy",
  metrics: "Goals & Metrics",
};

export const chapters = [
  "Questions and Scope", "Data Readiness", "AI Validation and Operations", "Evidence-Based Maturity", "Decisions for the Next 30 Days",
];

const stateLabels = {
  GUIDE: "Diagnostic Perspective",
  PROPOSAL: "Workshop Proposal",
  EXAMPLE: "Illustrative Example / Not Operational Evidence",
  CONTRACT: "FDAI Design Standard",
  STATUS: "Implementation vs. Operational Evidence",
};

/** Keep readable source names on the slide and exact owner paths in metadata. */
export function evidenceLine(keys) {
  return `<small class="rm-source" title="${keys.map(key => sources[key]).join(" | ")}">Evidence: ${keys.map(key => sourceLabels[key]).join(" / ")}</small>`;
}

/** Each body slide answers one question with a visual, takeaway, and scoped evidence. */
export function slide({ id, chapter, title, lead, visual, body, takeaway, evidence, state = "GUIDE" }) {
  return {
    eyebrow: `${String(chapter).padStart(2, "0")} / ${chapters[chapter - 1]}`,
    title,
    lead,
    layout: `briefing-readiness-${id} deck-readiness-maturity`,
    readiness: { id, chapter, visual, state, sources: evidence.map(key => sources[key]) },
    content: `<div class="rm-meta"><span class="rm-state" data-state="${state}">${stateLabels[state]}</span><span class="rm-chapter-markers" aria-label="Chapter ${chapter} of 5">${chapters.map((_, index) => `<i class="${index + 1 === chapter ? "is-current" : ""}" aria-hidden="true"></i>`).join("")}</span></div>
      <section class="rm-visual rm-${visual}" aria-label="${title}">${body}</section>
      <p class="rm-takeaway"><span>Key Point</span>${takeaway}</p>
      ${evidenceLine(evidence)}`,
  };
}

/** Unboxed propositions; the owning visual controls their reading order and geometry. */
export function entry(label, title, detail) {
  return `<article class="rm-entry"><small>${label}</small><h3>${title}</h3><p>${detail}</p></article>`;
}

/** Semantic comparison tables contain trusted repository-authored text only. */
export function table(headers, rows, className = "") {
  return `<table class="rm-table ${className}"><thead><tr>${headers.map(heading => `<th scope="col">${heading}</th>`).join("")}</tr></thead>
    <tbody>${rows.map(([heading, ...cells]) => `<tr><th scope="row">${heading}</th>${cells.map(cell => `<td>${cell}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
}

/** Connected nodes and measurable edges share one grid, including labeled relationship gaps. */
export function path(steps, links = []) {
  const gap = links.length ? "180px" : "42px";
  const columns = steps.map(() => "minmax(0, 1fr)").join(` ${gap} `);
  return `<div class="rm-path" style="grid-template-columns:${columns}">${steps.map((step, index) => {
    const node = `<article class="rm-node" data-rm-node="n${index}">${step[3] ? icon(step[3]) : ""}<small>${step[0]}</small><h3>${step[1]}</h3><p>${step[2]}</p></article>`;
    if (index === steps.length - 1) return node;
    return `${node}<div class="rm-link" data-rm-from="n${index}" data-rm-to="n${index + 1}">${links[index] ? `<span>${links[index]}</span>` : ""}<i aria-hidden="true"></i></div>`;
  }).join("")}</div>`;
}

/** A filled record stays descriptive; it is not a form, approval, or generated runtime state. */
export function record(fields, className = "") {
  return `<dl class="rm-record ${className}">${fields.map(([label, value]) => `<div><dt>${label}</dt><dd>${value}</dd></div>`).join("")}</dl>`;
}
