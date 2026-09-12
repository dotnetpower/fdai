// Preserve the existing map interactions; add production's provisioning and provenance surfaces.
(() => {
  const byId = (id) => document.getElementById(id);
  const root = document.querySelector(".dashboard-v2");
  const { formatCount } = window.FdaiDashboardViews;
  function syncRecordedFacts() {
    const snapshot = window.FdaiDashboardV2Snapshot;
    if (!snapshot) return;
    byId("count-provisioning").textContent = formatCount(snapshot.resources.filter((resource) =>
      resource.provisioning !== "unknown").length);
    const result = window.FdaiDashboardV2Query;
    const grouped = document.querySelector('[data-resource-view="groups"]').getAttribute("aria-pressed") === "true";
    byId("resource-count").textContent = `${grouped ? formatCount(result.groups.length) + " groups" : formatCount(result.records.length) + " resources"} shown / ${formatCount(result.matchCount)} match filters / ${formatCount(snapshot.resources.length)} received${window.FdaiDashboardV2SummaryFilter ? " / " + window.FdaiDashboardV2SummaryFilter + " evidence filter" : ""}`;
    const activeLens = document.querySelector('[data-resource-lens][aria-pressed="true"]');
    if (activeLens?.dataset.resourceLens === "provisioning") {
      byId("resource-lens-note").textContent = "Provisioning describes a recorded control-plane operation, not power, availability, or verified effect. Missing provisioning evidence remains unknown.";
    }
    if (byId("resource-selection").hidden) return;
    const evidence = JSON.parse(byId("resource-selected-evidence").textContent);
    const resource = snapshot.byId.get(evidence.resource);
    if (!resource) return;
    byId("resource-selected-evidence").textContent = JSON.stringify({
      ...evidence, recorded_provisioning: resource.provisioning === "unknown" ? null : resource.provisioning,
      provisioning_source: resource.provisioning === "unknown" ? null : "example-recorded-state",
      provisioning_observed_at: resource.provisioning === "unknown" ? null : "2026-09-05T11:59:00+09:00",
      presented_provisioning: window.FdaiDashboardData.statusKey(resource, "provisioning", snapshot),
    }, null, 2);
    byId("resource-ontology-link").href = "ontology-instances-2d.html?instance=" + encodeURIComponent(resource.id);
    const facts = byId("resource-selected-facts");
    if (!facts.querySelector("[data-provisioning-fact]")) {
      const row = document.createElement("div");
      row.dataset.provisioningFact = "";
      const label = document.createElement("dt");
      label.textContent = "Provisioning / source";
      const value = document.createElement("dd");
      const state = window.FdaiDashboardData.statusKey(resource, "provisioning", snapshot);
      value.textContent = `${window.FdaiDashboardData.definitions.provisioning[state][0]} / ${resource.provisioning === "unknown" ? "Source not recorded" : "example-recorded-state"}`;
      row.append(label, value);
      facts.prepend(row);
    }
  }
  root.addEventListener("fdai-preview-state-change", syncRecordedFacts);
  document.addEventListener("click", (event) => {
    if (event.target.closest("#resource-reset, [data-resource-lens], #resource-scope-reset")) window.FdaiDashboardV2SummaryFilter = null;
  }, true);
  byId("resource-refresh").addEventListener("click", () => {
    byId("resource-example-state").dispatchEvent(new Event("change", { bubbles: true }));
    byId("resource-refresh-status").textContent = "Same frozen fixture reloaded. No runtime request.";
  });
  const summaries = [
    ["received", "Inspect received resources"],
    ["known", "Inspect known operating states"],
    ["unknown", "Inspect unknown operating states"],
    ["provisioning", "Inspect recorded provisioning evidence"],
  ];
  document.querySelectorAll(".dr-summary > div").forEach((item, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.id = "resource-inspect-" + summaries[index][0];
    button.className = "cs-control-button is-quiet rd-summary-action";
    button.textContent = "Inspect";
    button.setAttribute("aria-label", summaries[index][1]);
    button.addEventListener("click", () => {
      byId("resource-reset").click();
      document.querySelector(`[data-resource-lens="${index === 3 ? "provisioning" : "operation"}"]`).click();
      if (index === 1 || index === 3) window.FdaiDashboardV2SummaryFilter = index === 3 ? "provisioning" : "known";
      document.querySelector('[data-resource-view="list"]').click();
      if (index === 2) document.querySelector('[data-state-key="unknown"]').click();
      byId("resource-refresh-status").textContent = index === 1 ? "Showing known operating states only." : index === 3 ? "Showing resources with a recorded provisioning fact. Stale facts still display unknown." : "";
    });
    item.append(button);
  });
  for (const kind of ["view", "lens", "density"]) {
    root.querySelectorAll(`[data-resource-${kind}]`).forEach(button => {
      if (!button.id) button.id = `resource-${kind}-${button.getAttribute("data-resource-" + kind)}`;
    });
  }
  root.querySelectorAll("details[id][data-preview-persist] > summary").forEach(summary => {
    if (!summary.id) summary.id = summary.parentElement.id + "-toggle";
  });
  const examples = byId("resource-example-controls");
  document.addEventListener("pointerdown", event => {
    if (examples.open && !examples.contains(event.target)) examples.open = false;
  });
  document.addEventListener("keydown", event => {
    if (event.key !== "Escape" || !examples.open || event.defaultPrevented) return;
    examples.open = false;
    if (examples.contains(document.activeElement)) examples.querySelector("summary").focus({ preventScroll: true });
    event.preventDefault();
  });
  syncRecordedFacts();
})();
