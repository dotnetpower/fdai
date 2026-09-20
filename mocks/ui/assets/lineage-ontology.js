(function () {
  "use strict";
  const nodes = [], edges = [];
  const row = index => 80 + index * 108;
  function resource(id, name, type, column, index, parent) {
    const cloud = type === "kubernetes-cluster";
    const subtype = ({ "kubernetes.persistent-volume": "PV", "kubernetes.persistent-volume-claim": "PVC" })[type] || type.replace("kubernetes.", "");
    nodes.push({ id, title: name, sub: `Resource / ${subtype}`, kind: "ontology", x: column, y: row(index), status: "Instance / revision 18", detail: "Synthetic, identity-bound Resource instance. Its subtype is a Resource property, not a separate ObjectType. Relationships are recorded scope and topology, not proof of causation.", owner: "Huginn", version: "Resource@1.0.0 / rev 18", origin: cloud ? "cloud-inventory" : "kubernetes-api", objectType: "Resource", properties: { id: id === "pod-resource" ? "sample-pod-01" : `sample-${id}`, type, name, ...(parent ? { parent_id: `sample-${parent}` } : {}) } });
    edges.push(["resource-type", id, "example instance"]);
    if (parent) edges.push([parent, id, "contains"]);
  }
  resource("cluster-resource", "example-cluster", "kubernetes-cluster", 1008, 0);
  resource("apps-namespace", "example-apps", "kubernetes.namespace", 1008, 1, "cluster-resource");
  resource("platform-namespace", "example-platform", "kubernetes.namespace", 1008, 2, "cluster-resource");
  resource("node-a", "example-node-a", "kubernetes.node", 1008, 3, "cluster-resource");
  resource("node-b", "example-node-b", "kubernetes.node", 1008, 4, "cluster-resource");
  resource("worker-volume", "example-volume", "kubernetes.persistent-volume", 1008, 5, "cluster-resource");
  resource("worker-claim", "example-claim", "kubernetes.persistent-volume-claim", 1008, 6, "platform-namespace");
  resource("api-deployment", "example-api", "kubernetes.deployment", 1254, 0, "apps-namespace");
  resource("api-replicaset", "example-api-rs", "kubernetes.replica-set", 1254, 1, "apps-namespace");
  resource("pod-resource", "example-api-01", "kubernetes.pod", 1254, 2, "apps-namespace");
  resource("api-pod-02", "example-api-02", "kubernetes.pod", 1254, 3, "apps-namespace");
  resource("worker-deployment", "example-worker", "kubernetes.deployment", 1254, 4, "platform-namespace");
  resource("worker-replicaset", "example-worker-rs", "kubernetes.replica-set", 1254, 5, "platform-namespace");
  resource("worker-pod", "example-worker-01", "kubernetes.pod", 1254, 6, "platform-namespace");
  resource("api-service", "example-api-service", "kubernetes.service", 1254, 7, "apps-namespace");
  resource("api-endpoints", "example-api-endpoints", "kubernetes.endpoint-slice", 1254, 8, "apps-namespace");
  function observation(id, title, target, metric, value, unit, index, display) {
    nodes.push({ id, title, sub: `Observation / ${unit}`, kind: "ontology", x: 1500, y: row(index), status: `${display} / recorded`, detail: "Synthetic immutable measurement. The target relationship points to one exact Resource; derived views do not become additional independent evidence.", owner: "Huginn", version: "Observation@1.0.0 / rev 1", origin: "prometheus", objectType: "Observation", properties: { id: id === "memory-observation" ? "sample-observation-m9" : `sample-${id}`, target_ref: nodes.find(node => node.id === target).properties.id, metric, value, unit, observed_at: "2026-09-20T10:42:00Z", evidence_ref: "sample-metric-window-m9", source_revision: "sample-m9" } });
    edges.push(["observation-type", id, "example instance"], [id, target, "observation_targets_resource"]);
  }
  observation("memory-observation", "API 01 memory", "pod-resource", "memory_bytes", 742391808, "bytes", 0, "708 MiB");
  observation("api-02-memory", "API 02 memory", "api-pod-02", "memory_bytes", 402653184, "bytes", 1, "384 MiB");
  observation("worker-cpu", "Worker CPU", "worker-pod", "cpu_utilization", 42, "percent", 2, "42%");
  observation("api-restarts", "API 01 restarts", "pod-resource", "restart_count", 3, "count", 3, "3 restarts");
  observation("node-memory", "Node A memory", "node-a", "memory_utilization", 68, "percent", 4, "68%");
  [
    ["rule-instance", "Memory pressure rule", "sample.pod.memory", "medium"],
    ["restart-rule", "Restart budget rule", "sample.pod.restarts", "high"],
    ["capacity-rule", "Node capacity rule", "sample.node.capacity", "medium"]
  ].forEach(([id, title, ruleId, severity], index) => {
    nodes.push({ id, title, sub: `Rule / ${ruleId}`, kind: "ontology", x: 1500, y: row(index + 6), status: "Catalog projection", detail: "Synthetic rule projection with selected properties. The reviewed catalog remains authoritative; a reference or a match cannot grant execution authority.", owner: "Mimir", version: "Rule@1.0.0 / rev 7", origin: "catalog", objectType: "Rule", properties: { id: ruleId, version: "1.0.0", severity, resource_type: index === 2 ? "kubernetes.node" : "kubernetes.pod" } });
    edges.push(["rule-type", id, "example instance"]);
  });
  [
    ["api-replicaset", "api-deployment", "kubernetes_owned_by"], ["worker-replicaset", "worker-deployment", "kubernetes_owned_by"],
    ["pod-resource", "api-replicaset", "kubernetes_owned_by"], ["api-pod-02", "api-replicaset", "kubernetes_owned_by"], ["worker-pod", "worker-replicaset", "kubernetes_owned_by"],
    ["pod-resource", "node-a", "kubernetes_scheduled_on"], ["api-pod-02", "node-b", "kubernetes_scheduled_on"], ["worker-pod", "node-b", "kubernetes_scheduled_on"],
    ["api-service", "pod-resource", "kubernetes_selects"], ["api-service", "api-pod-02", "kubernetes_selects"], ["api-service", "api-endpoints", "kubernetes_exposes_endpoint_slice"]
  ].forEach(edge => edges.push(edge));
  [
    ["resource-type", "Resource", 160, "Huginn", "16 example instances"],
    ["observation-type", "Observation", 484, "Huginn", "5 example instances"],
    ["rule-type", "Rule", 808, "Mimir", "3 example instances"]
  ].forEach(([id, title, y, owner, sub]) => nodes.push({ id, title, sub, kind: "type", x: 762, y, status: "ObjectType / v1.0.0", detail: "Canonical ObjectType declaration with synthetic example instances on this same canvas. Instance membership is a presentation connection, not data flow or execution authority.", owner, version: `${title}@1.0.0`, origin: "ontology-catalog", objectType: title, properties: { name: title, version: "1.0.0", key: "id", example_count: nodes.filter(node => node.kind === "ontology" && node.objectType === title).length } }));
  edges.push(["observation-type", "resource-type", "observation_targets_resource (schema)"]);
  window.fdaiLineageOntology = { nodes, edges };
}());
