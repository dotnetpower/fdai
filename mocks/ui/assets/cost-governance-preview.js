import { bindWorkspaceTabs } from "./settings-workspace-tabs.js";

const root = document.querySelector("[data-overview-tabs]");
bindWorkspaceTabs(root, {
  tabAttribute: "data-overview-tab", panelAttribute: "data-overview-panel",
  openAttribute: "data-open-overview", errorSelector: "[data-overview-error]",
  defaultTab: "overview",
  aliases: { "cost-resource-table": "resource-efficiency", "cost-case-list": "optimization-cases", "cost-effect-list": "outcomes" },
});

// Independent example recommendations; no candidate is promoted into an authorized case.
const candidates = [
  { id: "example-compute", name: "Example compute", type: "Virtual machine", utilization: 12, savings: 240, problem: "Low recorded utilization", solution: "Review capacity against workload demand", confidence: "0.82", source: "example-advisor", observed: "2026-07-22T14:00:00Z" },
  { id: "example-database", name: "Example database", type: "PostgreSQL", utilization: 35, savings: 80, problem: "Capacity review suggested", solution: "Inspect sustained demand before proposing a change", confidence: "0.76", source: "example-advisor", observed: "2026-07-22T14:00:00Z" },
  { id: "example-storage", name: "Example storage", type: "Storage account", utilization: null, savings: null, problem: "Cost baseline missing", solution: "Obtain the missing baseline before evaluation", confidence: null, source: "example-advisor", observed: null },
];
const byId = (id) => document.getElementById(id);
let selectedId = candidates[0].id;

function renderCandidates() {
  const query = byId("cost-search").value.trim().toLowerCase();
  const shown = candidates.filter((row) =>
    `${row.name} ${row.type} ${row.problem} ${row.solution}`.toLowerCase().includes(query));
  byId("cost-candidate-rows").replaceChildren(...shown.map((row) => {
    const tr = document.createElement("tr");
    const name = document.createElement("td");
    const button = document.createElement("button");
    button.type = "button"; button.className = "ow-row-action";
    button.textContent = row.name; button.dataset.costCandidate = row.id;
    button.setAttribute("aria-pressed", String(row.id === selectedId));
    name.append(button); tr.append(name);
    for (const value of [row.type, row.utilization === null ? "Unavailable" : `${row.utilization}%`, row.savings === null ? "Unavailable" : `$${row.savings} USD`]) {
      const cell = document.createElement("td"); cell.textContent = value; tr.append(cell);
    }
    return tr;
  }));
  byId("cost-row-count").textContent = shown.length ? `${shown.length} of 3 candidate rows / Full local fixture` : "No candidate matches. This does not establish absence outside this fixture.";
  const row = candidates.find((item) => item.id === selectedId);
  byId("cost-inspector").innerHTML = `<h2>${row.name}</h2><p class="ow-note">${row.problem}</p>
    ${shown.some((item) => item.id === selectedId) ? "" : '<p class="ow-note">Selected candidate is outside the current filter. Its identity has not changed.</p>'}
    <dl><div><dt>Resource type</dt><dd>${row.type}</dd></div><div><dt>Utilization</dt><dd>${row.utilization === null ? "Unavailable" : row.utilization + "%"}</dd></div><div><dt>Monthly opportunity</dt><dd>${row.savings === null ? "Unavailable" : "$" + row.savings + " USD"}</dd></div><div><dt>Confidence</dt><dd>${row.confidence ?? "Unavailable"}</dd></div><div><dt>Disposition</dt><dd>Recommendation only</dd></div></dl>
    <h3>Suggested review</h3><p class="ow-note">${row.solution}</p>
    <div class="cg-evidence-rows"><span>Source: ${row.source} / Synthetic</span><span>Observed: ${row.observed ?? "Not recorded"}</span><span>Freshness: ${row.observed ? "Frozen example, not current" : "Unknown"}</span><span>Approval: not projected / Effect: not verified</span></div>
    <details class="ow-disclosure"><summary>Evidence record</summary><pre></pre></details>
    <p><a href="audit.html?correlation=${row.id}">Open correlated audit</a></p>`;
  byId("cost-inspector").querySelector("pre").textContent = JSON.stringify({ ...row, synthetic: true, execution_authority: false }, null, 2);
  document.querySelectorAll(".cg-point").forEach((point) => point.setAttribute("aria-pressed", String(point.dataset.costCandidate === selectedId)));
}

document.addEventListener("click", (event) => {
  const trigger = event.target.closest("[data-cost-candidate], [data-open-cost-candidate]");
  if (!trigger) return;
  selectedId = trigger.dataset.costCandidate || trigger.dataset.openCostCandidate;
  if (trigger.hasAttribute("data-open-cost-candidate")) {
    byId("cost-search").value = "";
    document.querySelector('[data-overview-tab="resource-efficiency"]').click();
  }
  renderCandidates();
});
byId("cost-search").addEventListener("input", renderCandidates);
byId("cost-budget").addEventListener("change", (event) => {
  const main = event.target.value === "main";
  byId("budget-current").textContent = main ? "$4,500" : "$1,500";
  byId("budget-forecast").textContent = main ? "$5,700" : "Unavailable";
  byId("budget-share").textContent = main ? "75%" : "60%";
  byId("budget-total").textContent = main ? "of $6,000" : "of $2,500";
});
byId("cost-scenario").addEventListener("change", (event) => {
  const value = event.target.value;
  const ready = value === "available" || value === "partial";
  byId("cost-data").hidden = !ready;
  byId("cost-read-state").hidden = ready;
  byId("cost-coverage").textContent = {
    available: "Complete fixture / 6 observations",
    partial: "Incomplete / 6 retained observations / Full total unknown",
    empty: "Empty projection / No cost total established",
    unavailable: "Source unavailable",
    denied: "Access required",
    error: "Read error / No result established",
    loading: "Loading specimen / No request sent",
  }[value];
  if (ready) return;
  const messages = {
    empty: ["No cost records", "The source returned an empty projection. No spend or savings total can be established."],
    unavailable: ["Cost source unavailable", "Connect the owning runtime capability. Missing evidence is not zero spend."],
    denied: ["Access required", "The current role cannot read this projection. Browser selection never grants access."],
    error: ["Cost projection could not be read", "No result is established. This is a simulated error; no request was sent."],
    loading: ["Loading cost projection", "Paused loading specimen, not a live request."],
  };
  const [title, message] = messages[value];
  byId("cost-read-state").innerHTML = `<section class="ow-gap" role="${value === "error" ? "alert" : "status"}" ${value === "loading" ? 'aria-busy="true"' : ""}><h2>${title}</h2><p>${message}</p>${value === "loading" ? '<div class="ow-skeleton" aria-hidden="true"><span></span><span></span><span></span></div>' : ""}${value === "denied" || value === "unavailable" ? '<a href="settings-runtime.html">Review runtime configuration</a>' : ""}</section>`;
});
renderCandidates();
