/** Static presentation helpers. Meaning, evidence, and authority stay separate. */
export const sources = {
  constitution: "docs/roadmap/architecture/fdai-constitution.md",
  ontology: "docs/roadmap/architecture/operating-ontology.md",
  platform: "docs/roadmap/architecture/operating-ontology-platform.md",
  structural: "docs/roadmap/architecture/ontology-structural-model.md",
  metamodel: "docs/roadmap/architecture/operating-ontology-metamodel.md",
  governance: "docs/roadmap/architecture/data-governance.md",
  llm: "docs/roadmap/architecture/llm-strategy.md",
  action: "docs/roadmap/decisioning/action-ontology.md",
  agentLoop: "docs/roadmap/architecture/architecture-review/ontology-agent-loop.md",
  learning: "docs/roadmap/rules-and-detection/operational-learning-ontology.md",
  distillation: "docs/roadmap/rules-and-detection/document-ontology-distillation.md",
  behavior: "docs/roadmap/interfaces/behavior-knowledge.md",
};

export const references = {
  aristotle: "Stanford Encyclopedia of Philosophy: Aristotle's Metaphysics",
  logic: "Stanford Encyclopedia of Philosophy: Logic and Ontology",
  gruber: "Thomas R. Gruber (1993): Toward Principles for the Design of Ontologies Used for Knowledge Sharing",
  rdf: "W3C Recommendation: RDF 1.1 Concepts and Abstract Syntax",
  owl: "W3C Recommendation: OWL 2 Web Ontology Language Overview",
};

const statusLabels = {
  FOUNDATION: "Foundation", HISTORY: "History", PRINCIPLE: "Principle", PROBLEM: "Problem",
  BOUNDARY: "Boundary", CURRENT: "Current implementation", GAP: "In progress", ILLUSTRATIVE: "Example", DECISION: "Next step",
};
const sourceLabels = new Map([
  [sources.constitution, "FDAI Constitution"], [sources.ontology, "Operating Ontology"],
  [sources.platform, "Ontology Platform"], [sources.structural, "Structural Model"],
  [sources.metamodel, "Metamodel"], [sources.governance, "Data Governance"],
  [sources.llm, "LLM Strategy"], [sources.action, "Action Ontology"],
  [sources.agentLoop, "Ontology Agent Loop"], [sources.learning, "Operational Learning"],
  [sources.distillation, "Document Distillation"], [sources.behavior, "Behavior Knowledge"],
  [references.aristotle, "SEP: Aristotle"], [references.logic, "SEP: Logic and Ontology"],
  [references.gruber, "Gruber, 1993"], [references.rdf, "W3C RDF 1.1"], [references.owl, "W3C OWL 2"],
]);

/** Display a short citation while retaining full source paths in its tooltip. */
export function evidenceLine(items, label) {
  const [primary, ...additional] = items;
  const compact = additional.map((item) => item.startsWith("docs/") ? item.split("/").at(-1) : item);
  return `<small class="ontology-evidence-source" title="${items.join(" | ")}">Evidence: ${label ?? [primary, ...compact].join(" | ")}</small>`;
}

/** Build one teaching slide with a single visual and one explicit takeaway. */
export function slide({ state, chapter, title, lead, layout, body, takeaway, evidence }) {
  return {
    eyebrow: chapter,
    title,
    lead,
    layout: `ontology-${layout} ontology-editorial`,
    content: `<span class="oe-state" data-state="${state}">${statusLabels[state]}</span>
      <section class="oe-visual oe-${layout}" aria-label="${title}">${body}</section>
      <p class="oe-takeaway">${takeaway}</p>
      ${evidenceLine(evidence, evidence.map(item => sourceLabels.get(item) ?? item).join(" | "))}`,
  };
}

/** An unboxed, labeled proposition; the owning layout determines its arrangement. */
export function entry(label, title, detail) {
  return `<article class="oe-entry"><small>${label}</small><strong>${title}</strong><p>${detail}</p></article>`;
}

/** A bounded illustrative sequence with connectors touching adjacent node boxes. */
export function flow(steps) {
  const columns = steps.map(() => "minmax(0, 1fr)").join(" 36px ");
  return `<div class="oe-flow" style="grid-template-columns:${columns}">${steps.map(
    step => entry(...step),
  ).join('<i class="oe-edge" aria-hidden="true"></i>')}</div>`;
}

/** Semantic comparison table, authored as trusted repository content only. */
export function table(headers, rows) {
  return `<table class="oe-table"><thead><tr>${headers.map(h => `<th scope="col">${h}</th>`).join("")}</tr></thead>
    <tbody>${rows.map(([heading, ...cells]) => `<tr><th scope="row">${heading}</th>${cells.map(c => `<td>${c}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
}
