/** Shared presentation primitives for the value-prioritization workshop. */
export const sources = {
  constitution: "docs/roadmap/architecture/fdai-constitution.md",
  deterministic: "docs/user-guide/concepts/deterministic-first.md",
  execution: "docs/roadmap/decisioning/execution-model.md",
  metrics: "docs/roadmap/architecture/goals-and-metrics.md",
  ontology: "docs/roadmap/architecture/operating-ontology.md",
  planning: "docs/roadmap/decisioning/operational-planning.md",
  readiness: "docs/roadmap/operations/operational-readiness.md",
  outcomes: "docs/roadmap/architecture/outcome-assurance.md",
};

const sourceLabels = {
  constitution: "FDAI Constitution",
  deterministic: "Deterministic First",
  execution: "Execution Model",
  metrics: "Goals & Metrics",
  ontology: "Operating Ontology",
  planning: "Operational Planning",
  readiness: "Operational Readiness",
  outcomes: "Outcome Assurance",
};

export const chapters = [
  "Selection criteria",
  "Execution eligibility",
  "Value proof",
  "Portfolio decision",
  "First execution",
];

const stateLabels = {
  CONTRACT: "FDAI design standard",
  DECISION: "Decision",
  EXAMPLE: "Illustrative example / not operational evidence",
  GUIDE: "Workshop guide",
  PROPOSAL: "Workshop proposal",
  STATUS: "Current implementation and open evidence",
};

/** Render readable source labels while retaining exact repository paths in metadata. */
export function evidenceLine(keys) {
  const paths = keys.map((key) => sources[key]);
  const labels = keys.map((key) => sourceLabels[key]);
  return `<small class="vp-source" title="${paths.join(" | ")}">Evidence: ${labels.join(" / ")}</small>`;
}

/** Build one decision-oriented body slide with a single visual and explicit takeaway. */
export function slide({ index, id, chapter, state, title, lead, body, takeaway, evidence }) {
  const number = String(index).padStart(2, "0");
  return {
    eyebrow: `${number} / ${chapters[chapter - 1]}`,
    title,
    lead,
    layout: `briefing-value-${id} deck-value-prioritization`,
    priority: { id, chapter, state, sources: evidence.map((key) => sources[key]) },
    content: `
      <div class="vp-meta">
        <span class="vp-state" data-state="${state}">${stateLabels[state]}</span>
        <span class="vp-progress" aria-label="Chapter ${chapter} of 5">${chapters.map((name, position) => `<i class="${position + 1 === chapter ? "is-current" : ""}"><b>0${position + 1}</b>${name}</i>`).join("")}</span>
      </div>
      <section class="vp-visual vp-${id}" aria-label="${title}">${body}</section>
      <p class="vp-takeaway"><span>Decision principle</span>${takeaway}</p>
      ${evidenceLine(evidence)}`,
  };
}

/** Render one labelled decision field without implying runtime input or authority. */
export function field(label, value, detail = "") {
  return `<div class="vp-field"><dt>${label}</dt><dd>${value}${detail ? `<small>${detail}</small>` : ""}</dd></div>`;
}
