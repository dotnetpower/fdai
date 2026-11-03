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
  const sampleScope = "example-subscription / example-cluster";
  nodes.filter(node => node.kind === "ontology" && node.objectType === "Resource").forEach(node => {
    node.scope = sampleScope;
    node.evidenceState = ({ "api-pod-02": "stale", "worker-pod": "unknown", "node-b": "conflicting" })[node.id] || "current";
  });
  function buildResourceTypeGraph(sourceNodes, sourceEdges, expandedGroup = null) {
    const resources = sourceNodes.filter(node => node.kind === "ontology" && node.objectType === "Resource");
    const groups = new Map(), membership = new Map();
    resources.forEach(node => {
      const key = JSON.stringify([node.scope, node.properties.type]);
      if (!groups.has(key)) {
        const index = groups.size;
        const title = ({ "kubernetes-cluster": "AKS cluster", "kubernetes.namespace": "Namespace", "kubernetes.node": "Node", "kubernetes.persistent-volume": "Persistent volume", "kubernetes.persistent-volume-claim": "Volume claim", "kubernetes.deployment": "Deployment", "kubernetes.replica-set": "ReplicaSet", "kubernetes.pod": "Pod", "kubernetes.service": "Service", "kubernetes.endpoint-slice": "EndpointSlice" })[node.properties.type] || node.properties.type;
        groups.set(key, { id: `resource-group-${index}`, title, sub: node.properties.type, kind: "resource-group", x: 1008 + Math.floor(index / 5) * 246, y: row(index % 5), status: "", detail: "Recorded Resources grouped by exact ResourceType and scope. Aggregate connections summarize retained relationships; they do not prove an all-to-all connection or an end-to-end instance path.", owner: node.owner, version: "", origin: "", objectType: "Resource", scope: node.scope, resourceType: node.properties.type, members: [], health: { current: 0, stale: 0, conflicting: 0, unknown: 0 } });
      }
      const group = groups.get(key);
      group.members.push(node);
      group.health[node.evidenceState || "unknown"] += 1;
      membership.set(node.id, group.id);
    });
    const groupNodes = [...groups.values()];
    groupNodes.forEach(group => {
      const gaps = group.health.stale + group.health.conflicting + group.health.unknown;
      group.status = `${group.members.length} recorded / ${gaps ? `${gaps} evidence gaps` : "current"}`;
      group.held = gaps > 0;
      group.version = [...new Set(group.members.map(node => node.version))].join(", ");
      group.origin = [...new Set(group.members.map(node => node.origin))].join(", ");
      group.properties = { object_type: "Resource", resource_type: group.resourceType, scope: group.scope, recorded_count: group.members.length, current: group.health.current, stale: group.health.stale, conflicting: group.health.conflicting, unknown: group.health.unknown, coverage: "Illustrative sample only; subscription completeness unverified" };
    });
    const resourceIds = new Set(resources.map(node => node.id));
    const expanded = groupNodes.find(group => group.id === expandedGroup);
    const expandedIds = new Set(expanded?.members.map(node => node.id) || []);
    const projectedNodes = [...sourceNodes.filter(node => !resourceIds.has(node.id)), ...groupNodes];
    if (expanded) expanded.members.forEach((node, index) => projectedNodes.push({ ...node, x: 1008 + index % 2 * 246, y: 728 + Math.floor(index / 2) * 108 }));
    const projectedEdges = new Map();
    sourceEdges.forEach(([from, to, relation]) => {
      if (from === "resource-type" && resourceIds.has(to) && relation === "example instance") return;
      const source = expandedIds.has(from) ? from : membership.get(from) || from;
      const target = expandedIds.has(to) ? to : membership.get(to) || to;
      const key = JSON.stringify([source, target, relation]);
      if (!projectedEdges.has(key)) projectedEdges.set(key, [source, target, relation, [], source !== from || target !== to]);
      projectedEdges.get(key)[3].push([from, to, relation]);
    });
    const resultEdges = [...projectedEdges.values(), ...groupNodes.map(group => ["resource-type", group.id, "resource type", [], false])];
    if (expanded) expanded.members.forEach(node => resultEdges.push([expanded.id, node.id, "example instance", [], false]));
    return { nodes: projectedNodes, edges: resultEdges, groups: groupNodes, membership };
  }
  // Relationship classes over the recorded edge labels. Derivation edges carry "which recorded input fed which
  // record"; membership edges only connect a declaration or aggregate to its instances; topology and cross-cluster
  // edges are recorded scope, never a derivation step. Labels outside these lists classify as null.
  const RELATION_CLASSES = Object.freeze({
    derivation: Object.freeze(["observed", "required", "defines", "cites", "consumed", "qualified", "supplies instances", "supplies catalog projection", "evaluated against", "cited", "produced", "audited"]),
    membership: Object.freeze(["example instance", "resource type"]),
    topology: Object.freeze(["contains", "kubernetes_owned_by", "kubernetes_scheduled_on", "kubernetes_selects", "kubernetes_exposes_endpoint_slice"]),
    crossCluster: Object.freeze(["observation_targets_resource", "observation_targets_resource (schema)"])
  });
  const relationClass = relation => Object.keys(RELATION_CLASSES).find(name => RELATION_CLASSES[name].includes(relation)) || null;
  // Clusters group projected resource-group and ontology nodes by (objectType, scope). The input array and its nodes are
  // not modified; members are node ids. When a cluster contains ResourceType aggregates they are the authority for
  // `recorded` and `health` (expanded instances are already counted there); otherwise each instance counts once and
  // health stays null because Observation and Rule records carry no evidenceState.
  function buildClusters(projectedNodes) {
    const clusters = new Map(), positions = new Map();
    projectedNodes.forEach(node => {
      if ((node.kind !== "resource-group" && node.kind !== "ontology") || !node.objectType) return;
      const scope = node.scope ?? "";
      const key = scope ? `${node.objectType}/${scope}` : node.objectType;
      if (!clusters.has(key)) { clusters.set(key, { key, objectType: node.objectType, scope: scope || null, members: [], recorded: 0, health: null, groups: 0, instances: 0 }); positions.set(key, [node.x, node.y]); }
      const cluster = clusters.get(key);
      cluster.members.push(node.id);
      positions.set(key, [Math.min(positions.get(key)[0], node.x), Math.min(positions.get(key)[1], node.y)]);
      if (node.kind === "resource-group") {
        cluster.groups += 1;
        cluster.health = cluster.health || { current: 0, stale: 0, conflicting: 0, unknown: 0 };
        Object.keys(cluster.health).forEach(state => { cluster.health[state] += node.health?.[state] || 0; });
      } else cluster.instances += 1;
    });
    return [...clusters.values()].map(cluster => {
      const recorded = cluster.groups ? Object.values(cluster.health).reduce((sum, count) => sum + count, 0) : cluster.instances;
      return { key: cluster.key, objectType: cluster.objectType, scope: cluster.scope, members: cluster.members, recorded, health: cluster.health, groups: cluster.groups, instances: cluster.instances };
    }).sort((left, right) => positions.get(left.key)[0] - positions.get(right.key)[0] || positions.get(left.key)[1] - positions.get(right.key)[1]);
  }
  // Derivation path of one node over a projected graph: upstream closure follows derivation and membership edges
  // against their stored direction (instance <- aggregate <- declaration <- agent <- input <- source); downstream closure
  // follows derivation edges only (instance -> judge -> decision -> audit). Topology and cross-cluster edges are never
  // part of a path. Edges are never rewired or reversed; the result is a subset of recorded relationships, not a causal
  // or authority claim. Stages are read from the fixed column coordinates.
  function derivationPath(graph, nodeId) {
    const byId = new Map(graph.nodes.map(node => [node.id, node]));
    const stageOf = node => ({ 24: "source", 270: "input", 516: "agent", 762: "type", 1792: "decision" })[node.x] || "instance";
    const edgeKey = edge => JSON.stringify([edge[0], edge[1], edge[2]]);
    function closure(classes, backwards) {
      const seen = new Set(), queue = [nodeId], keys = [];
      seen.add(nodeId);
      while (queue.length) {
        const current = queue.shift();
        graph.edges.forEach(edge => {
          const cls = relationClass(edge[2]);
          const allowed = classes.includes(cls) || (!backwards && current === nodeId && edge[2] === "example instance" && byId.get(nodeId)?.kind === "resource-group");
          if (!allowed) return;
          const [near, far] = backwards ? [edge[1], edge[0]] : [edge[0], edge[1]];
          if (near !== current || !byId.has(far)) return;
          const key = edgeKey(edge);
          if (!keys.includes(key)) keys.push(key);
          if (!seen.has(far)) { seen.add(far); queue.push(far); }
        });
      }
      seen.delete(nodeId);
      return { keys, nodes: seen };
    }
    const empty = { origin: nodeId, upstream: [], downstream: [], stages: new Map(), reachesDecision: false, unavailableInputs: 0 };
    if (!byId.has(nodeId)) return empty;
    const upstream = closure(["derivation", "membership"], true), downstream = closure(["derivation"], false);
    const stages = new Map([[nodeId, stageOf(byId.get(nodeId))]]);
    [...upstream.nodes, ...downstream.nodes].forEach(id => stages.set(id, stageOf(byId.get(id))));
    const pathEdges = graph.edges.filter(edge => upstream.keys.includes(edgeKey(edge)) || downstream.keys.includes(edgeKey(edge)));
    return {
      origin: nodeId,
      upstream: upstream.keys,
      downstream: downstream.keys,
      stages,
      reachesDecision: [...downstream.nodes].some(id => byId.get(id).kind === "outcome"),
      unavailableInputs: pathEdges.filter(edge => edge[2] === "required" && byId.get(edge[0])?.missing === true).length
    };
  }
  window.fdaiLineageOntology = { nodes, edges, RELATION_CLASSES, relationClass, buildResourceTypeGraph, buildClusters, derivationPath };
}());
