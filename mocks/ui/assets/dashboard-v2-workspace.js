// Preserve the existing map interactions; add production's provisioning and provenance surfaces.
(() => {
  const byId = (id) => document.getElementById(id);
  function syncRecordedFacts() {
    const snapshot = window.FdaiDashboardV2Snapshot;
    if (!snapshot) return;
    byId("count-provisioning").textContent = snapshot.resources.filter((resource) =>
      resource.provisioning !== "unknown").length;
    const result = window.FdaiDashboardV2Query;
    const grouped = document.querySelector('[data-resource-view="groups"]').getAttribute("aria-pressed") === "true";
    byId("resource-count").textContent = `${grouped ? result.groups.length + " groups" : result.records.length + " resources"} shown / ${result.matchCount} match filters / ${snapshot.resources.length} received${window.FdaiDashboardV2SummaryFilter ? " / " + window.FdaiDashboardV2SummaryFilter + " evidence filter" : ""}`;
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
  document.addEventListener("click", () => queueMicrotask(syncRecordedFacts));
  document.addEventListener("input", () => queueMicrotask(syncRecordedFacts));
  document.addEventListener("change", () => queueMicrotask(syncRecordedFacts));
  new ResizeObserver(() => queueMicrotask(syncRecordedFacts)).observe(document.querySelector(".dr-resource-panel"));
  document.addEventListener("click", (event) => {
    if (event.target.closest("#resource-reset, [data-resource-lens], #resource-scope-reset")) window.FdaiDashboardV2SummaryFilter = null;
  }, true);
  byId("resource-refresh").addEventListener("click", () => {
    byId("resource-example-state").dispatchEvent(new Event("change", { bubbles: true }));
    byId("resource-refresh-status").textContent = "Same frozen fixture reloaded. No runtime request.";
  });
  document.querySelectorAll(".dr-summary > div").forEach((item, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "ow-row-action";
    button.textContent = "Inspect records";
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
  syncRecordedFacts();
})();
