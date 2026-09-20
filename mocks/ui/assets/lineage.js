(function () {
  "use strict";
  const nodes = [
    { id: "arg", title: "Azure Resource Graph", sub: "Cloud inventory", kind: "source", x: 24, y: 68, status: "Recorded", detail: "Cloud-side cluster identity and configuration. This source does not observe Pod runtime state.", owner: "Huginn", version: "inventory / sample-g42", origin: "cloud-inventory" },
    { id: "aks", title: "Kubernetes API", sub: "AKS Observer / Connector", kind: "source", x: 24, y: 172, status: "Recorded", detail: "The Observer collects and delivers a UID-bound snapshot. Delivery acknowledgment is not graph publication or effect verification.", owner: "Huginn", version: "observer / sample-s18", origin: "kubernetes-api", icon: "kubernetes.svg" },
    { id: "prom", title: "Prometheus", sub: "Memory working set", kind: "source", x: 24, y: 276, status: "Recorded", detail: "A bounded metric window for the selected workload. Metric observations and Kubernetes object state remain distinct inputs.", owner: "Heimdall", version: "query / sample-v3", origin: "prometheus" },
    { id: "logs", title: "Log Analytics", sub: "Container log evidence", kind: "source", x: 24, y: 380, status: "Unavailable", detail: "The selected log window is unavailable. A missing query result is not proof that no relevant logs exist.", owner: "Heimdall", version: "query / sample-v2", origin: "log-analytics", missing: true, icon: "monitor.svg" },
    { id: "rules", title: "Rule catalog", sub: "Reviewed AKS rule set", kind: "normative", x: 24, y: 484, status: "Version pinned", detail: "Reviewed criteria supply judgment inputs, not observations or execution authority. Collection and activation are separate records.", owner: "Mimir", version: "rules / sample-v7", origin: "catalog" },
    { id: "docs", title: "Runbook", sub: "Memory investigation", kind: "normative", x: 24, y: 588, status: "Reference only", detail: "A versioned document excerpt provides reference knowledge. It cannot substitute for current measurements or grant permission.", owner: "Muninn", version: "document / sample-v4", origin: "document" },
    { id: "inventory", title: "Cluster identity", sub: "Resource / sample-g42", kind: "evidence", x: 270, y: 68, status: "Scope matched", detail: "The retained cloud observation supplies the cluster identity used to qualify runtime scope.", owner: "Huginn", version: "mapping / sample-v2", origin: "cloud-inventory" },
    { id: "pod", title: "Pod observation", sub: "example-api / UID pinned", kind: "evidence", x: 270, y: 172, status: "Restart count: 3", detail: "A versioned Pod observation retains identity, restart count and recorded status. It is not itself a root-cause conclusion.", owner: "Huginn", version: "snapshot / sample-s18", origin: "kubernetes-api" },
    { id: "metric", title: "Memory window", sub: "10:37-10:42 UTC", kind: "evidence", x: 270, y: 276, status: "Coverage: complete", detail: "The window is complete in this synthetic case. A derived value retains its original Prometheus source rather than becoming independent evidence.", owner: "Heimdall", version: "window / sample-m9", origin: "prometheus" },
    { id: "log-window", title: "Log window", sub: "10:37-10:42 UTC", kind: "evidence", x: 270, y: 380, status: "Required / unavailable", detail: "The required log input is explicitly unresolved. Dashed connections show requirements, not consumed evidence.", owner: "Heimdall", version: "window / sample-l6", origin: "log-analytics", missing: true },
    { id: "policy", title: "Evaluation criteria", sub: "Rules + ontology mapping", kind: "normative", x: 270, y: 484, status: "Exact versions retained", detail: "Pinned rule and property-semantics versions define how evidence is evaluated. They do not assert the current state of the workload.", owner: "Forseti", version: "criteria / sample-v7", origin: "catalog" },
    { id: "excerpt", title: "Runbook excerpt", sub: "Section 3 / sample-v4", kind: "normative", x: 270, y: 588, status: "Advisory", detail: "The source document and excerpt version remain linked so an explanation can cite the actual retained material.", owner: "Muninn", version: "excerpt / sample-e3", origin: "document" },
    { id: "huginn", title: "Huginn", sub: "Normalize / sample-h12", kind: "agent", x: 516, y: 120, status: "Completed / attempt 1", detail: "This execution normalizes cloud, Kubernetes and metric inputs into versioned Resource and Observation instances. Identity matching does not make their collection times atomic.", owner: "Huginn", version: "run / sample-h12", origin: "derived", agent: "huginn" },
    { id: "heimdall", title: "Heimdall", sub: "Qualify / sample-e08", kind: "agent", x: 516, y: 328, status: "Partial / attempt 2", detail: "The same logical qualification run has two delivery attempts. Available metrics are retained; unavailable logs remain a gap, not a zero result.", owner: "Heimdall", version: "run / sample-e08", origin: "derived", agent: "heimdall", held: true },
    ...window.fdaiLineageOntology.nodes,
    { id: "forseti", title: "Forseti", sub: "Evaluate / sample-f04", kind: "agent", x: 1792, y: 224, status: "Held / missing evidence", detail: "Forseti joins qualified evidence, exact Resource instances and the reviewed Rule projection. This case does not establish cause or authorize a remediation.", owner: "Forseti", version: "run / sample-f04", origin: "derived", agent: "forseti", held: true },
    { id: "decision", title: "Decision record", sub: "sample-case-024", kind: "outcome", x: 1792, y: 432, status: "Hold / no dispatch", detail: "The decision retains its original cutoff and exact input versions. Approval, execution and independent effect verification have not occurred.", owner: "Forseti", version: "decision / sample-d1", origin: "derived", held: true },
    { id: "saga", title: "Saga", sub: "Audit / sample-a21", kind: "agent", x: 1792, y: 588, status: "Recorded", detail: "The audit record preserves the held outcome and evidence gap. Audit persistence does not change the decision or add execution authority.", owner: "Saga", version: "audit / sample-a21", origin: "audit", agent: "saga" }
  ];
  const edges = [
    ["arg", "inventory", "observed"], ["aks", "pod", "observed"], ["prom", "metric", "observed"], ["logs", "log-window", "required"],
    ["rules", "policy", "defines"], ["docs", "excerpt", "cites"], ["inventory", "huginn", "consumed"], ["pod", "huginn", "consumed"],
    ["metric", "huginn", "consumed"], ["log-window", "heimdall", "required"], ["heimdall", "forseti", "consumed"],
    ["huginn", "resource-type", "supplies instances"], ["huginn", "observation-type", "supplies instances"],
    ["memory-observation", "heimdall", "qualified"],
    ["cluster-resource", "forseti", "consumed"], ["pod-resource", "forseti", "consumed"], ["policy", "rule-type", "supplies catalog projection"],
    ["rule-instance", "forseti", "evaluated against"], ["excerpt", "forseti", "cited"], ["forseti", "decision", "produced"], ["decision", "saga", "audited"],
    ...window.fdaiLineageOntology.edges
  ];
  const extraSources = [
    ["Azure Monitor Metrics", "Observed data", "Native metric queries", "Not used in this case"],
    ["Activity Log / change feeds", "Change evidence", "Azure, GitHub, Azure DevOps", "Not used in this case"],
    ["Cost / recovery observations", "Observed data", "Cost window / recovery state", "Not used in this case"],
    ["Approval / standing authority", "Authorization evidence", "Human scope and validity", "Not requested"],
    ["Independent outcome", "Effect evidence", "Observer readback", "No execution"],
    ["Historical cases", "Reference knowledge", "Versioned case evidence", "Not used in this case"]
  ];
  const canvasWidth = 2010, canvasHeight = 1060;
  let expandedGroup = null;
  let graph = window.fdaiLineageOntology.buildResourceTypeGraph(nodes, edges);
  let selected = graph.membership.get("pod-resource"), focused = false, zoom = 1, view = "graph", fitted = true;
  let lookup = new Map(graph.nodes.map(node => [node.id, node]));
  const originals = new Map(nodes.map(node => [node.id, node]));
  const curves = new Map();
  const previewStateKey = "fdai:lineage-preview:workspace-v1";
  const byId = id => document.getElementById(id);
  const escape = value => String(value).replace(/[&<>"']/g, character => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[character]));
  function icon(name) {
    return `<svg class="ln-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${window.fdaiLineageIcons[name].map(([tag, attributes]) => `<${tag} ${Object.entries(attributes).map(([key, value]) => `${key}="${escape(value)}"`).join(" ")}></${tag}>`).join("")}</svg>`;
  }
  const kindIcons = { source: "Database", evidence: "FileText", normative: "BookOpen", type: "Layers", "resource-group": "Boxes", ontology: "Box", outcome: "ShieldCheck" };
  function nodeSymbol(node) {
    if (node.agent) return `<img class="ln-icon" src="../../../console/public/agent-icons/${node.agent}.svg" alt="" />`;
    const azureSource = { arg: "resource-graph", aks: "kubernetes-services", logs: "monitor" }[node.id];
    const resourceType = node.resourceType || node.properties?.type;
    const azureResource = resourceType === "kubernetes-cluster" ? "kubernetes-services" : null;
    const azureIcon = azureSource || azureResource || (node.title === "Azure Monitor Metrics" ? "monitor" : null);
    if (azureIcon) return `<img class="ln-icon" src="../../../tools/architecture-diagrams/assets/azure/${azureIcon}.svg" alt="" />`;
    return icon(node.objectType === "Observation" && node.kind === "ontology" ? "Activity" : kindIcons[node.kind] || "Box");
  }
  byId("lineageSearchIcon").innerHTML = icon("Search");
  byId("lineageSearchClear").innerHTML = icon("X");
  function highlighted(value) {
    const query = byId("lineageSearch").value.trim();
    const position = query ? value.toLowerCase().indexOf(query.toLowerCase()) : -1;
    return position < 0 ? escape(value) : `${escape(value.slice(0, position))}<mark>${escape(value.slice(position, position + query.length))}</mark>${escape(value.slice(position + query.length))}`;
  }
  function searchCount() {
    const count = view === "graph" ? byId("lineageNodes").children.length : byId("lineageSources").querySelectorAll(".ln-source-row").length;
    byId("lineageMatchCount").textContent = `${count} matching ${view === "graph" ? "records" : "sources"}`;
    byId("lineageSearchClear").hidden = !byId("lineageSearch").value;
  }
  Object.entries({ lineageReset: ["RotateCcw", "Reset filters and collapse instances"], lineageFit: ["Maximize", "Fit complete graph"], lineageZoomOut: ["ZoomOut", "Zoom out"], lineageZoomIn: ["ZoomIn", "Zoom in"], lineageCenter: ["LocateFixed", "Center selected record"], lineageMapToggle: ["Map", "Toggle graph navigator"], lineageInspectorToggle: ["PanelRightClose", "Hide record details"], lineageCanvasMode: ["Maximize", "Expand canvas"] }).forEach(([id, [name, label]]) => {
    const button = byId(id);
    button.innerHTML = icon(name); button.setAttribute("aria-label", label); button.title = label; button.classList.add("ln-icon-button");
  });
  const isComplete = () => byId("lineageScenario").value === "complete";
  function selectedEdge(edge) {
    const direction = byId("lineageDirection").value;
    return (direction !== "incoming" && edge[0] === selected) || (direction !== "outgoing" && edge[1] === selected);
  }
  const hasGap = node => node.kind === "resource-group" ? node.held : node.evidenceState ? node.evidenceState !== "current" : (node.missing || node.held) && !isComplete();
  function status(node) {
    if (node.evidenceState) return `Evidence: ${node.evidenceState}`;
    if (!isComplete()) return node.status;
    return ({ logs: "Recorded", "log-window": "Coverage: complete", heimdall: "Qualified / attempt 2", forseti: "Evaluated / shadow only", decision: "Review / no dispatch" })[node.id] || node.status;
  }
  function neighbors(id) {
    const direction = byId("lineageDirection").value;
    return new Set([id, ...graph.edges.filter(edge => (direction !== "incoming" && edge[0] === id) || (direction !== "outgoing" && edge[1] === id)).flatMap(edge => edge.slice(0, 2))]);
  }
  function rebuild() {
    graph = window.fdaiLineageOntology.buildResourceTypeGraph(nodes, edges, expandedGroup);
    lookup = new Map(graph.nodes.map(node => [node.id, node]));
    curves.clear();
    if (!lookup.has(selected)) selected = graph.membership.get(selected) || "resource-type";
  }
  function connectionCurve(from, to) {
    const key = `${from}:${to}`;
    if (curves.has(key)) return curves.get(key);
    const source = lookup.get(from), target = lookup.get(to);
    const sameColumn = source.x === target.x, forward = target.x > source.x;
    const direction = forward ? 1 : -1;
    const start = [source.x + (sameColumn || forward ? 194 : 0), source.y + 39];
    const end = [target.x + (sameColumn || !forward ? 194 : 0), target.y + 39];
    const bend = Math.max(32, Math.abs(end[0] - start[0]) * .45) * direction;
    const direct = sameColumn
      ? [[start, [start[0] + 48, start[1]], [end[0] + 48, end[1]], end]]
      : [[start, [start[0] + bend, start[1] - 6], [end[0] - bend, end[1] + 6], end]];
    const obstacles = graph.nodes.filter(node => node.id !== from && node.id !== to);
    function clear(segments) {
      return segments.every(points => {
        const steps = Math.max(16, Math.ceil(points.slice(1).reduce((total, point, index) => total + Math.hypot(point[0] - points[index][0], point[1] - points[index][1]), 0) / 8));
        for (let step = 1; step < steps; step++) {
          const fraction = step / steps, remaining = 1 - fraction;
          const weights = [remaining ** 3, 3 * remaining ** 2 * fraction, 3 * remaining * fraction ** 2, fraction ** 3];
          const horizontal = points.reduce((sum, point, index) => sum + point[0] * weights[index], 0);
          const vertical = points.reduce((sum, point, index) => sum + point[1] * weights[index], 0);
          if (obstacles.some(node => horizontal > node.x - 4 && horizontal < node.x + 198 && vertical > node.y - 4 && vertical < node.y + 82)) return false;
        }
        return true;
      });
    }
    let segments = direct;
    if (!clear(segments)) {
      const lanes = [48, 1040, ...Array.from({ length: 9 }, (_, index) => 172 + index * 108)].sort((left, right) => Math.abs(left - (start[1] + end[1]) / 2) - Math.abs(right - (start[1] + end[1]) / 2));
      for (const lane of lanes) {
        const sourceCorridor = start[0] + 24 * direction, targetCorridor = end[0] - 24 * direction;
        const first = [sourceCorridor + 10 * direction, lane], last = [targetCorridor - 10 * direction, lane];
        const candidate = [[start, [sourceCorridor, start[1]], [sourceCorridor, lane], first], [first, [first[0] + (last[0] - first[0]) / 3, lane], [last[0] - (last[0] - first[0]) / 3, lane], last], [last, [targetCorridor, lane], [targetCorridor, end[1]], end]];
        if (clear(candidate)) { segments = candidate; break; }
      }
    }
    const curve = `M${start.join(" ")} ` + segments.map(points => `C${points.slice(1).map(point => point.join(" ")).join(" ")}`).join(" ");
    curves.set(key, curve);
    return curve;
  }
  function render() {
    const query = byId("lineageSearch").value.trim().toLowerCase();
    const related = neighbors(selected);
    const matches = graph.nodes.filter(node => `${node.title} ${node.sub} ${node.owner} ${node.origin} ${node.version} ${node.objectType || ""} ${node.properties?.id || ""} ${node.members?.map(member => `${member.title} ${member.properties.id}`).join(" ") || ""}`.toLowerCase().includes(query));
    const visible = new Set((focused ? matches.filter(node => related.has(node.id)) : matches).map(node => node.id));
    byId("lineageNodes").innerHTML = graph.nodes.filter(node => visible.has(node.id)).map(node => {
      const symbol = nodeSymbol(node);
      const title = node.id === "arg" ? "Resource Graph" : node.title;
      return `<button type="button" class="ln-node ${node.missing && !isComplete() ? "is-missing" : ""} ${hasGap(node) ? "is-held" : ""}" data-node="${node.id}" data-kind="${node.kind}" ${node.resourceType ? `data-resource-type="${node.resourceType}"` : ""} style="left:${node.x}px;top:${node.y}px" aria-pressed="${selected === node.id}" aria-label="${escape(`${node.title}, ${node.kind === "resource-group" ? "ResourceType" : node.kind}, ${status(node)}`)}" title="${escape(node.title)}"><span class="ln-node-heading">${symbol}<strong>${highlighted(title)}${node.members ? ` (${node.members.length})` : ""}</strong></span><span class="ln-node-body"><small>${escape(node.kind === "resource-group" ? "ResourceType / sample scope" : node.sub)}</small><span class="ln-node-state">${escape(status(node))}</span></span></button>`;
    }).join("");
    byId("lineageEdges").querySelectorAll(".ln-edge").forEach(edge => edge.remove());
    const shownEdges = graph.edges.filter(edge => visible.has(edge[0]) && visible.has(edge[1]));
    shownEdges.forEach(([from, to, relation, records, aggregated]) => {
      const source = lookup.get(from), target = lookup.get(to);
      const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      path.setAttribute("d", connectionCurve(from, to));
      path.dataset.from = from;
      path.dataset.to = to;
      path.dataset.relation = relation;
      path.dataset.count = String(records.length);
      path.dataset.aggregated = String(aggregated);
      const membership = relation === "example instance" || relation === "resource type";
      path.setAttribute("class", `ln-edge ${membership ? "is-membership" : source.objectType && target.objectType ? "is-ontology" : ""} ${aggregated ? "is-aggregate" : ""} ${relation === "required" && !isComplete() ? "is-missing" : ""} ${selectedEdge([from, to]) ? "is-selected" : "is-muted"}`);
      byId("lineageEdges").append(path);
    });
    byId("lineageEmpty").hidden = visible.size > 0;
    byId("lineageCanvasSize").hidden = visible.size === 0;
    document.querySelector(".ln-map-dock").hidden = visible.size === 0;
    const visibleGroups = graph.groups.filter(group => visible.has(group.id));
    const visibleInstances = graph.nodes.filter(node => visible.has(node.id) && node.kind === "ontology" && node.objectType === "Resource");
    byId("lineageCount").textContent = `${visibleGroups.length} ResourceTypes / ${visibleGroups.reduce((sum, group) => sum + group.members.length, 0)} represented Resources / ${visibleInstances.length} expanded / ${shownEdges.length} connections`;
    byId("caseState").textContent = isComplete() ? "Evaluated - shadow review only" : "Held - missing log evidence";
    byId("lineageCompactState").textContent = isComplete() ? "Shadow review" : "Held";
    const selectedRecord = lookup.get(selected);
    byId("lineageSelection").innerHTML = `${nodeSymbol(selectedRecord)}<strong>${escape(selectedRecord.title)}</strong><span>${graph.edges.filter(edge => edge[1] === selected).length} inputs / ${graph.edges.filter(edge => edge[0] === selected).length} outputs</span>`;
    byId("lineageRecordPicker").innerHTML = graph.nodes.filter(node => visible.has(node.id)).map(node => `<option value="${node.id}">${escape(node.title)}${node.members ? ` (${node.members.length})` : ""}</option>`).join("");
    byId("lineageRecordPicker").value = selected;
    byId("lineageRecordPicker").disabled = visible.size === 0;
    renderInspector();
    renderSources(query);
    searchCount();
    byId("lineageMiniature").innerHTML = graph.nodes.filter(node => visible.has(node.id)).map(node => `<rect class="ln-mini-node ${node.id === selected ? "is-selected" : ""}" data-palette="${node.kind}" x="${node.x}" y="${node.y}" width="194" height="78" rx="12" />`).join("") + '<rect id="lineageMapWindow" fill="#285c8614" stroke="#285c86" stroke-width="10" />';
    updateMap();
  }
  function renderInspector() {
    const node = lookup.get(selected);
    const incoming = graph.edges.filter(edge => edge[1] === selected);
    const outgoing = graph.edges.filter(edge => edge[0] === selected);
    const relationButtons = (items, index) => items.map(edge => `<div><button type="button" data-select="${edge[index]}">${escape(lookup.get(edge[index]).title)}<small> / ${escape(edge[2] === "required" && isComplete() ? "consumed" : edge[2])}${edge[4] ? ` / ${edge[3].length} recorded` : ""}</small></button>${edge[4] ? `<details class="ln-edge-records"><summary>Original references (${edge[3].length})</summary><ul>${edge[3].map(([from, to, relation]) => `<li>${escape(originals.get(from).title)} - ${escape(relation)} - ${escape(originals.get(to).title)}<br /><code>${escape(originals.get(from).properties?.id || from)} / ${escape(originals.get(to).properties?.id || to)}</code></li>`).join("")}</ul></details>` : ""}</div>`).join("") || "<span>No recorded connections</span>";
    const detail = isComplete() && ["logs", "log-window", "heimdall", "forseti", "decision"].includes(node.id) ? "This alternate synthetic snapshot includes the required log window. Evaluation is shadow-only; no approval, dispatch or effect-verification record is implied." : node.detail;
    const properties = node.properties ? `<details class="ln-property-details"><summary>${node.kind === "type" ? "Type declaration" : "Selected properties"}<span>${Object.keys(node.properties).length}</span></summary><dl class="ln-properties">${Object.entries(node.properties).map(([key, value]) => `<div><dt>${escape(key.replaceAll("_", " "))}</dt><dd>${escape(value)}</dd></div>`).join("")}</dl></details>` : "";
    const health = node.health ? `<section class="ln-health" aria-label="Evidence state breakdown"><h3>Evidence state</h3><dl>${Object.entries(node.health).map(([state, count]) => `<div data-health="${state}"><dt>${icon(({ current: "Check", stale: "Clock", conflicting: "TriangleAlert", unknown: "CircleHelp" })[state])}${escape(state)}</dt><dd>${count}</dd></div>`).join("")}</dl></section>` : "";
    const groupId = node.members ? node.id : graph.membership.get(node.id);
    const expansion = groupId ? `<button type="button" class="ln-focus ln-expand" data-expand="${groupId}" aria-expanded="${expandedGroup === groupId}">${icon(expandedGroup === groupId ? "Minimize" : "Boxes")}${expandedGroup === groupId ? "Collapse instances" : `Expand ${lookup.get(groupId).members.length} instances`}</button>` : "";
    const inspector = byId("lineageInspector");
    const changed = inspector.dataset.selection !== selected;
    inspector.innerHTML = `<div class="ln-inspector-intro"><span class="ln-record-kind">${escape(node.kind === "resource-group" ? "RESOURCE TYPE / SCOPED AGGREGATE" : node.kind === "type" ? "OBJECT TYPE / DECLARATION" : node.objectType ? `${node.objectType.toUpperCase()} / ONTOLOGY INSTANCE` : `${node.kind.toUpperCase()} / SELECTED RECORD`)}</span><h2>${nodeSymbol(node)} ${escape(node.title)}</h2><strong class="${hasGap(node) ? "ln-warning" : "ln-success"}">${escape(status(node))}</strong>${health}${expansion}<p>${escape(detail)}</p></div><div class="ln-record-metadata"><dl><div><dt>Owner</dt><dd>${escape(node.owner)}</dd></div><div><dt>Version</dt><dd><code>${escape(node.version)}</code></dd></div><div><dt>Source</dt><dd>${escape(node.origin)}</dd></div><div><dt>Cutoff</dt><dd>20 Sep 2026 / 10:42 UTC</dd></div></dl>${properties}<div class="ln-record-note">Synthetic evidence / No execution authority</div></div><div class="ln-record-connections"><h3>${icon("ArrowLeft")} Incoming <small>${incoming.length}</small></h3><div class="ln-related">${relationButtons(incoming, 0)}</div><h3>${icon("ArrowRight")} Outgoing <small>${outgoing.length}</small></h3><div class="ln-related">${relationButtons(outgoing, 1)}</div><button type="button" class="ln-focus" id="lineageFocus" aria-pressed="${focused}">${icon("Scan")}${focused ? "Show all records" : "Focus on this record"}</button></div>`;
    inspector.dataset.selection = selected;
    if (changed) inspector.scrollTop = 0;
  }
  function renderSources(query) {
    const sources = nodes.filter(node => node.x === 24).map(node => [node.title, node.kind === "normative" ? "Rules / knowledge" : "Observed data", node.sub, status(node), node.id]);
    const rows = [...sources, ...extraSources].filter(source => source.join(" ").toLowerCase().includes(query));
    byId("lineageSources").innerHTML = `<h2>Source register <small>${rows.length}</small></h2>` + (rows.length ? rows.map(([title, kind, scope, state, id]) => `<article class="ln-source-row"><div>${id ? `<button type="button" data-select="${id}">${nodeSymbol(originals.get(id))} ${escape(title)}</button>` : `<strong>${nodeSymbol({ title, kind: "source" })} ${escape(title)}</strong>`}</div><span>${escape(kind)}</span><span>${escape(scope)}</span><span>${escape(state)}</span></article>`).join("") : "<p>No matching sources.</p>");
  }
  function select(id) { selected = id; byId("lineageSearch").value = ""; setView("graph"); render(); }
  function setView(next) { view = next; byId("lineageLayout").hidden = view !== "graph"; byId("lineageSources").hidden = view !== "sources"; document.querySelectorAll("[data-view]").forEach(button => button.setAttribute("aria-pressed", String(button.dataset.view === view))); searchCount(); }
  document.addEventListener("click", event => {
    const button = event.target.closest("button");
    if (!button) return;
    if (button.dataset.node) { selected = button.dataset.node; render(); document.querySelector(`[data-node="${selected}"]`)?.focus({ preventScroll: true }); }
    if (button.dataset.select) { select(button.dataset.select); document.querySelector(`[data-node="${selected}"]`)?.focus(); }
    if (button.dataset.view) setView(button.dataset.view);
    if (button.id === "lineageInspectorToggle") {
      const inspector = byId("lineageInspector");
      inspector.hidden = !inspector.hidden;
      byId("lineageLayout").classList.toggle("is-inspector-hidden", inspector.hidden);
      button.setAttribute("aria-expanded", String(!inspector.hidden));
      button.setAttribute("aria-label", inspector.hidden ? "Show record details" : "Hide record details"); button.title = button.getAttribute("aria-label");
      button.innerHTML = icon(inspector.hidden ? "PanelRightOpen" : "PanelRightClose");
      if (fitted) fitGraph();
    }
    if (button.id === "lineageCanvasMode") {
      const expanded = document.body.classList.toggle("is-canvas-mode");
      button.setAttribute("aria-pressed", String(expanded));
      button.setAttribute("aria-label", expanded ? "Restore workspace" : "Expand canvas"); button.title = button.getAttribute("aria-label");
      button.innerHTML = icon(expanded ? "Minimize" : "Maximize");
      document.querySelector(".ln-canvas-badge").hidden = !expanded;
      fitGraph();
    }
    if (["lineageSearchClear", "lineageEmptyClear"].includes(button.id)) { byId("lineageSearch").value = ""; render(); byId("lineageSearch").focus(); }
    if (button.dataset.expand) { expandedGroup = expandedGroup === button.dataset.expand ? null : button.dataset.expand; focused = false; byId("lineageSearch").value = ""; rebuild(); render(); byId("lineageInspector").querySelector("[data-expand]")?.focus({ preventScroll: true }); }
    if (button.id === "lineageFocus") { focused = !focused; render(); byId("lineageFocus").focus(); }
    if (button.id === "lineageReset") { focused = false; expandedGroup = null; byId("lineageSearch").value = ""; byId("lineageDirection").value = "both"; rebuild(); render(); fitGraph(); }
    if (button.id === "lineageFit") fitGraph();
    if (button.id === "lineageCenter") {
      const node = lookup.get(selected);
      changeZoom(Math.max(.85, zoom));
      byId("lineageViewport").scrollLeft = (node.x + 97) * zoom - byId("lineageViewport").clientWidth / 2;
      byId("lineageViewport").scrollTop = (node.y + 39) * zoom - byId("lineageViewport").clientHeight / 2;
      updateMap();
    }
    if (button.id === "lineageMapToggle") { const map = byId("lineageMap"); map.hidden = !map.hidden; button.setAttribute("aria-expanded", String(!map.hidden)); }
    if (button.id === "lineageMap" && event.detail === 0) {
      byId("lineageViewport").scrollLeft = canvasWidth * zoom / 2 - byId("lineageViewport").clientWidth / 2;
      byId("lineageViewport").scrollTop = canvasHeight * zoom / 2 - byId("lineageViewport").clientHeight / 2;
      updateMap();
    }
    if (button.id === "lineageActual") changeZoom(1);
    if (button.id === "lineageZoomIn" || button.id === "lineageZoomOut") changeZoom(zoom + (button.id === "lineageZoomIn" ? .125 : -.125));
    savePreview();
  });
  function savePreview() {
    const viewport = byId("lineageViewport");
    try {
      sessionStorage.setItem(previewStateKey, JSON.stringify({ version: 1, selected, expandedGroup, direction: byId("lineageDirection").value, zoom, fitted, left: viewport.scrollLeft, top: viewport.scrollTop, view }));
    } catch { byId("lineageMatchCount").textContent = "Workspace state is not retained in this browser"; }
  }
  function restorePreview() {
    try {
      const saved = JSON.parse(sessionStorage.getItem(previewStateKey) || "null");
      if (!saved || saved.version !== 1 || !["graph", "sources"].includes(saved.view) || !["both", "incoming", "outgoing"].includes(saved.direction)) return;
      if (![saved.zoom, saved.left, saved.top].every(Number.isFinite) || saved.zoom < .1 || saved.zoom > 2.5 || saved.left < 0 || saved.top < 0 || typeof saved.fitted !== "boolean") return;
      if (saved.expandedGroup !== null && !graph.groups.some(group => group.id === saved.expandedGroup)) return;
      if (!lookup.has(saved.selected) && !originals.has(saved.selected)) return;
      expandedGroup = saved.expandedGroup; rebuild();
      selected = lookup.has(saved.selected) ? saved.selected : graph.membership.get(saved.selected) || "resource-type";
      byId("lineageDirection").value = saved.direction;
      render();
      if (saved.fitted) fitGraph();
      else { changeZoom(saved.zoom); byId("lineageViewport").scrollLeft = saved.left; byId("lineageViewport").scrollTop = saved.top; updateMap(); }
      setView(saved.view);
    } catch { byId("lineageMatchCount").textContent = "Workspace state could not be restored; showing the default preview"; }
  }
  function updateMap() {
    const viewport = byId("lineageViewport"), rectangle = byId("lineageMapWindow");
    if (!rectangle) return;
    Object.entries({ x: viewport.scrollLeft / zoom, y: viewport.scrollTop / zoom, width: Math.min(canvasWidth, viewport.clientWidth / zoom), height: Math.min(canvasHeight, viewport.clientHeight / zoom) }).forEach(([key, value]) => rectangle.setAttribute(key, value));
  }
  function updateZoom() { byId("lineageCanvas").style.transform = `scale(${zoom})`; byId("lineageCanvasSize").style.width = `${canvasWidth * zoom}px`; byId("lineageCanvasSize").style.height = `${canvasHeight * zoom}px`; byId("lineageZoom").value = `${Math.round(zoom * 100)}%`; byId("lineageCanvas").classList.toggle("is-overview", zoom < .6); updateMap(); }
  function changeZoom(next, anchorX, anchorY) {
    const viewport = byId("lineageViewport");
    const horizontal = anchorX ?? viewport.clientWidth / 2, vertical = anchorY ?? viewport.clientHeight / 2;
    const worldX = (viewport.scrollLeft + horizontal) / zoom, worldY = (viewport.scrollTop + vertical) / zoom;
    zoom = Math.max(.1, Math.min(2.5, next)); fitted = false; updateZoom();
    viewport.scrollLeft = worldX * zoom - horizontal; viewport.scrollTop = worldY * zoom - vertical;
  }
  function fitGraph() {
    const viewport = byId("lineageViewport");
    zoom = Math.min(1, (viewport.clientWidth - 16) / canvasWidth, (viewport.clientHeight - 16) / canvasHeight);
    fitted = true; updateZoom(); viewport.scrollLeft = 0; viewport.scrollTop = 0;
  }
  const viewport = byId("lineageViewport");
  viewport.addEventListener("scroll", () => { updateMap(); savePreview(); }, { passive: true });
  const navigator = byId("lineageMap");
  let navigatorPointer = null;
  function moveNavigator(event) {
    const transform = byId("lineageMiniature").getScreenCTM();
    if (!transform) return;
    const point = new DOMPoint(event.clientX, event.clientY).matrixTransform(transform.inverse());
    viewport.scrollLeft = point.x * zoom - viewport.clientWidth / 2;
    viewport.scrollTop = point.y * zoom - viewport.clientHeight / 2;
    updateMap();
  }
  navigator.addEventListener("pointerdown", event => {
    if (!event.isPrimary || event.button !== 0 || navigatorPointer !== null) return;
    event.preventDefault();
    navigator.focus({ preventScroll: true });
    navigatorPointer = event.pointerId;
    navigator.setPointerCapture(event.pointerId);
    navigator.classList.add("is-dragging");
    moveNavigator(event);
  });
  navigator.addEventListener("pointermove", event => { if (event.pointerId === navigatorPointer) moveNavigator(event); });
  function stopNavigator(event) {
    if (event.pointerId !== navigatorPointer) return;
    navigatorPointer = null;
    navigator.classList.remove("is-dragging");
    if (navigator.hasPointerCapture(event.pointerId)) navigator.releasePointerCapture(event.pointerId);
    savePreview();
  }
  navigator.addEventListener("pointerup", stopNavigator);
  navigator.addEventListener("pointercancel", stopNavigator);
  navigator.addEventListener("lostpointercapture", stopNavigator);
  let drag = null;
  viewport.addEventListener("pointerdown", event => {
    if (event.pointerType === "touch" || event.button !== 0 || event.target.closest("button")) return;
    drag = { x: event.clientX, y: event.clientY, left: viewport.scrollLeft, top: viewport.scrollTop };
    viewport.setPointerCapture(event.pointerId); viewport.classList.add("is-dragging");
  });
  viewport.addEventListener("pointermove", event => { if (drag) { viewport.scrollLeft = drag.left + drag.x - event.clientX; viewport.scrollTop = drag.top + drag.y - event.clientY; } });
  const stopDrag = () => { drag = null; viewport.classList.remove("is-dragging"); };
  viewport.addEventListener("pointerup", stopDrag); viewport.addEventListener("pointercancel", stopDrag);
  viewport.addEventListener("wheel", event => {
    if (!event.deltaY || event.shiftKey) return;
    event.preventDefault(); const bounds = viewport.getBoundingClientRect();
    const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? viewport.clientHeight : 1;
    const delta = Math.max(-240, Math.min(240, event.deltaY * unit));
    changeZoom(zoom * Math.exp(-delta * .002), event.clientX - bounds.left, event.clientY - bounds.top);
    savePreview();
  }, { passive: false });
  viewport.addEventListener("keydown", event => {
    const button = event.target.closest("[data-node]");
    if (button && ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)) {
      event.preventDefault();
      const current = lookup.get(button.dataset.node);
      const candidates = [...byId("lineageNodes").querySelectorAll("[data-node]")].map(element => lookup.get(element.dataset.node)).filter(node => {
        return ({ ArrowLeft: node.x < current.x, ArrowRight: node.x > current.x, ArrowUp: node.y < current.y, ArrowDown: node.y > current.y })[event.key];
      });
      const horizontal = ["ArrowLeft", "ArrowRight"].includes(event.key);
      const distance = node => Math.abs(node.x - current.x) * (horizontal ? 1 : 4) + Math.abs(node.y - current.y) * (horizontal ? 4 : 1);
      candidates.sort((left, right) => distance(left) - distance(right));
      if (candidates[0]) { selected = candidates[0].id; render(); document.querySelector(`[data-node="${selected}"]`).focus(); }
      return;
    }
    if (event.target !== viewport) return;
    if (["+", "=", "-", "0"].includes(event.key)) { event.preventDefault(); if (event.key === "0") fitGraph(); else changeZoom(zoom + (event.key === "-" ? -.125 : .125)); }
  });
  new ResizeObserver(() => { if (fitted && view === "graph") fitGraph(); }).observe(viewport);
  byId("lineageSearch").addEventListener("input", render);
  byId("lineageSearch").addEventListener("keydown", event => {
    if (event.key === "Escape") { event.preventDefault(); byId("lineageSearch").value = ""; render(); }
    if (event.key === "Enter" && view === "graph") {
      const match = byId("lineageNodes").querySelector("[data-node]");
      if (match) { event.preventDefault(); select(match.dataset.node); document.querySelector(`[data-node="${selected}"]`)?.focus(); }
    }
  });
  byId("lineageScenario").addEventListener("change", render);
  byId("lineageDirection").addEventListener("change", () => { render(); savePreview(); });
  byId("lineageRecordPicker").addEventListener("change", event => { select(event.target.value); byId("lineageCenter").click(); });
  const compactViewport = matchMedia("(max-width: 740px)");
  byId("lineageCaseDetails").open = !compactViewport.matches;
  compactViewport.addEventListener("change", event => { byId("lineageCaseDetails").open = !event.matches; });
  render();
  fitGraph();
  restorePreview();
  window.addEventListener("pagehide", savePreview);
}());
