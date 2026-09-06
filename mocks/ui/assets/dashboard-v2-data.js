// Extend the existing mock query adapter with independently authored provisioning evidence.
(() => {
  const base = window.FdaiDashboardData;
  base.definitions.provisioning = {
    succeeded: ["Succeeded", "positive", "+"],
    updating: ["Updating", "attention", "~"],
    failed: ["Failed", "negative", "X"],
    unknown: ["Unknown", "unknown", "?"],
  };
  const provisioning = { "app-web-01": "succeeded", "app-vm-02": "updating", "data-db-01": "failed" };
  window.FdaiDashboardData = Object.freeze({
    ...base,
    query(snapshot, state) {
      const filter = window.FdaiDashboardV2SummaryFilter;
      const resources = filter ? snapshot.resources.filter((resource) => {
        if (filter === "provisioning") return resource.provisioning !== "unknown";
        return !["unknown", "na"].includes(base.statusKey(resource, "operation", snapshot));
      }) : snapshot.resources;
      const result = base.query({ ...snapshot, resources }, state);
      window.FdaiDashboardV2Query = result;
      return result;
    },
    createSnapshot(size, mode) {
      window.FdaiDashboardV2SummaryFilter = null;
      const original = base.createSnapshot(size, mode);
      const resources = original.resources.map((resource) => Object.freeze({
        ...resource,
        provisioning: provisioning[resource.id] || "unknown",
      }));
      const snapshot = Object.freeze({
        ...original, resources: Object.freeze(resources),
        byId: new Map(resources.map((resource) => [resource.id, resource])),
      });
      window.FdaiDashboardV2Snapshot = snapshot;
      return snapshot;
    },
  });
})();
