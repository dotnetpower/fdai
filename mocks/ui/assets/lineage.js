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
    { id: "cluster-resource", title: "example-cluster", sub: "Resource / kubernetes-cluster", kind: "ontology", x: 762, y: 68, status: "Instance / revision 42", detail: "A synthetic Resource instance using the canonical Resource ObjectType. Its cloud inventory provenance remains distinct from the Pod's runtime observation.", owner: "Huginn", version: "Resource@1.0.0 / rev 42", origin: "cloud-inventory", objectType: "Resource", properties: { id: "sample-cluster-01", type: "kubernetes-cluster", name: "example-cluster" } },
    { id: "pod-resource", title: "example-api", sub: "Resource / kubernetes.pod", kind: "ontology", x: 762, y: 172, status: "Instance / revision 18", detail: "A UID-grounded synthetic Pod Resource, not an ObjectType declaration. The Observation relationship identifies its measured target; it does not assert causation.", owner: "Huginn", version: "Resource@1.0.0 / rev 18", origin: "kubernetes-api", objectType: "Resource", properties: { id: "sample-pod-01", type: "kubernetes.pod", name: "example-api", "properties.restart_count": 3 } },
    { id: "memory-observation", title: "Memory working set", sub: "Observation / sample-m9", kind: "ontology", x: 762, y: 328, status: "708 MiB / recorded", detail: "An immutable synthetic Observation linked to the Pod through observation_targets_resource. Qualification does not turn this stored observation into a second independent source.", owner: "Huginn", version: "Observation@1.0.0 / rev 1", origin: "prometheus", objectType: "Observation", properties: { id: "sample-observation-m9", target_ref: "sample-pod-01", metric: "memory_working_set_bytes", value: 742391808, unit: "bytes", observed_at: "2026-09-20T10:42:00Z", evidence_ref: "sample-metric-window-m9", source_revision: "sample-m9" } },
    { id: "rule-instance", title: "Memory pressure rule", sub: "Rule / sample.pod.memory", kind: "ontology", x: 762, y: 484, status: "Catalog projection", detail: "A synthetic Rule instance projected from reviewed catalog criteria. The original catalog remains authoritative; this read model grants no execution authority.", owner: "Mimir", version: "Rule@1.0.0 / rev 7", origin: "catalog", objectType: "Rule", properties: { id: "sample.pod.memory", version: "1.0.0", severity: "medium", resource_type: "kubernetes.pod" } },
    { id: "forseti", title: "Forseti", sub: "Evaluate / sample-f04", kind: "agent", x: 1054, y: 224, status: "Held / missing evidence", detail: "Forseti joins qualified evidence, exact Resource instances and the reviewed Rule projection. This case does not establish cause or authorize a remediation.", owner: "Forseti", version: "run / sample-f04", origin: "derived", agent: "forseti", held: true },
    { id: "decision", title: "Decision record", sub: "sample-case-024", kind: "outcome", x: 1054, y: 432, status: "Hold / no dispatch", detail: "The decision retains its original cutoff and exact input versions. Approval, execution and independent effect verification have not occurred.", owner: "Forseti", version: "decision / sample-d1", origin: "derived", held: true },
    { id: "saga", title: "Saga", sub: "Audit / sample-a21", kind: "agent", x: 1054, y: 588, status: "Recorded", detail: "The audit record preserves the held outcome and evidence gap. Audit persistence does not change the decision or add execution authority.", owner: "Saga", version: "audit / sample-a21", origin: "audit", agent: "saga" }
  ];
  const edges = [
    ["arg", "inventory", "observed"], ["aks", "pod", "observed"], ["prom", "metric", "observed"], ["logs", "log-window", "required"],
    ["rules", "policy", "defines"], ["docs", "excerpt", "cites"], ["inventory", "huginn", "consumed"], ["pod", "huginn", "consumed"],
    ["metric", "huginn", "consumed"], ["log-window", "heimdall", "required"], ["heimdall", "forseti", "consumed"],
    ["huginn", "cluster-resource", "projected"], ["huginn", "pod-resource", "projected"], ["huginn", "memory-observation", "normalized"],
    ["memory-observation", "heimdall", "qualified"], ["memory-observation", "pod-resource", "observation_targets_resource"],
    ["cluster-resource", "forseti", "consumed"], ["pod-resource", "forseti", "consumed"], ["policy", "rule-instance", "projected"],
    ["rule-instance", "forseti", "evaluated against"], ["excerpt", "forseti", "cited"], ["forseti", "decision", "produced"], ["decision", "saga", "audited"]
  ];
  const extraSources = [
    ["Azure Monitor Metrics", "Observed data", "Native metric queries", "Not used in this case"],
    ["Activity Log / change feeds", "Change evidence", "Azure, GitHub, Azure DevOps", "Not used in this case"],
    ["Cost / recovery observations", "Observed data", "Cost window / recovery state", "Not used in this case"],
    ["Approval / standing authority", "Authorization evidence", "Human scope and validity", "Not requested"],
    ["Independent outcome", "Effect evidence", "Observer readback", "No execution"],
    ["Historical cases", "Reference knowledge", "Versioned case evidence", "Not used in this case"]
  ];
  let selected = "forseti", focused = false, zoom = 1, view = "graph";
  const lookup = new Map(nodes.map(node => [node.id, node]));
  const byId = id => document.getElementById(id);
  const escape = value => String(value).replace(/[&<>"']/g, character => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[character]));
  const isComplete = () => byId("lineageScenario").value === "complete";
  function status(node) {
    if (!isComplete()) return node.status;
    return ({ logs: "Recorded", "log-window": "Coverage: complete", heimdall: "Qualified / attempt 2", forseti: "Evaluated / shadow only", decision: "Review / no dispatch" })[node.id] || node.status;
  }
  function neighbors(id) {
    return new Set([id, ...edges.filter(edge => edge[0] === id || edge[1] === id).flatMap(edge => edge.slice(0, 2))]);
  }
  function render() {
    const query = byId("lineageSearch").value.trim().toLowerCase();
    const related = neighbors(selected);
    const matches = nodes.filter(node => `${node.title} ${node.sub} ${node.owner} ${node.objectType || ""} ${node.properties?.id || ""}`.toLowerCase().includes(query));
    const visible = new Set((focused ? matches.filter(node => related.has(node.id)) : matches).map(node => node.id));
    byId("lineageNodes").innerHTML = nodes.filter(node => visible.has(node.id)).map(node => {
      const image = node.agent ? `../../../console/public/agent-icons/${node.agent}.svg` : node.icon && node.icon !== "kubernetes.svg" ? `../../../tools/architecture-diagrams/assets/azure/${node.icon}` : "";
      return `<button type="button" class="ln-node ${node.missing && !isComplete() ? "is-missing" : ""} ${node.held && !isComplete() ? "is-held" : ""}" data-node="${node.id}" data-kind="${node.kind}" style="left:${node.x}px;top:${node.y}px" aria-pressed="${selected === node.id}"><span class="ln-node-heading">${image ? `<img src="${image}" alt="" />` : ""}<strong>${escape(node.title)}</strong></span><small>${escape(node.sub)}</small><span class="ln-node-state">${escape(status(node))}</span></button>`;
    }).join("");
    byId("lineageEdges").querySelectorAll(".ln-edge").forEach(edge => edge.remove());
    const shownEdges = edges.filter(edge => visible.has(edge[0]) && visible.has(edge[1]));
    shownEdges.forEach(([from, to, relation]) => {
      const source = lookup.get(from), target = lookup.get(to);
      const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      const sameColumn = source.x === target.x;
      const forward = target.x > source.x, downward = target.y > source.y;
      const startX = source.x + (sameColumn ? 97 : forward ? 194 : 0), startY = source.y + (sameColumn ? downward ? 78 : 0 : 39);
      const endX = target.x + (sameColumn ? 97 : forward ? 0 : 194), endY = target.y + (sameColumn ? downward ? 0 : 78 : 39);
      const bend = Math.max(32, Math.abs(endX - startX) * .45) * (forward ? 1 : -1);
      const lift = startY === endY ? 12 : 0;
      const verticalBend = Math.abs(endY - startY) * .35 * (downward ? 1 : -1);
      let curve = sameColumn
        ? `M${startX} ${startY} C${startX + 28} ${startY + verticalBend} ${endX + 28} ${endY - verticalBend} ${endX} ${endY}`
        : `M${startX} ${startY} C${startX + bend} ${startY - lift} ${endX - bend} ${endY + lift} ${endX} ${endY}`;
      if (from === "excerpt") curve = `M${startX} ${startY} C640 651 892 651 978 619 C1024 602 1010 ${endY} ${endX} ${endY}`;
      if (from === "heimdall" && to === "forseti") curve = `M${startX} ${startY} C730 312 736 280 866 280 C984 280 1004 ${endY} ${endX} ${endY}`;
      path.setAttribute("d", curve);
      path.dataset.from = from;
      path.dataset.to = to;
      path.dataset.relation = relation;
      path.setAttribute("class", `ln-edge ${relation === "observation_targets_resource" ? "is-ontology" : ""} ${relation === "required" && !isComplete() ? "is-missing" : ""} ${from === selected || to === selected ? "is-selected" : ""}`);
      byId("lineageEdges").append(path);
    });
    byId("lineageEmpty").hidden = visible.size > 0;
    byId("lineageCanvasSize").hidden = visible.size === 0;
    byId("lineageCount").textContent = `${visible.size} records / ${shownEdges.length} connections / ${isComplete() ? "no missing inputs" : "1 missing input"}`;
    byId("caseState").textContent = isComplete() ? "Evaluated - shadow review only" : "Held - missing log evidence";
    renderInspector();
    renderSources(query);
  }
  function renderInspector() {
    const node = lookup.get(selected);
    const incoming = edges.filter(edge => edge[1] === selected);
    const outgoing = edges.filter(edge => edge[0] === selected);
    const relationButtons = (items, index) => items.map(edge => `<button type="button" data-select="${edge[index]}">${escape(lookup.get(edge[index]).title)}<small> / ${escape(edge[2] === "required" && isComplete() ? "consumed" : edge[2])}</small></button>`).join("") || "<span>No recorded connections</span>";
    const detail = isComplete() && ["logs", "log-window", "heimdall", "forseti", "decision"].includes(node.id) ? "This alternate synthetic snapshot includes the required log window. Evaluation is shadow-only; no approval, dispatch or effect-verification record is implied." : node.detail;
    const properties = node.properties ? `<h3>Instance properties</h3><dl class="ln-properties">${Object.entries(node.properties).map(([key, value]) => `<div><dt>${escape(key)}</dt><dd>${escape(value)}</dd></div>`).join("")}</dl>` : "";
    byId("lineageInspector").innerHTML = `<div class="ln-inspector-intro"><span class="ln-record-kind">${escape(node.objectType ? `${node.objectType.toUpperCase()} / ONTOLOGY INSTANCE` : `${node.kind.toUpperCase()} / SELECTED RECORD`)}</span><h2>${escape(node.title)}</h2><strong class="${(node.missing || node.held) && !isComplete() ? "ln-warning" : "ln-success"}">${escape(status(node))}</strong><p>${escape(detail)}</p></div><div><dl><div><dt>Accountable agent</dt><dd>${escape(node.owner)}</dd></div><div><dt>Exact record version</dt><dd><code>${escape(node.version)}</code></dd></div><div><dt>Origin family</dt><dd>${escape(node.origin)}</dd></div><div><dt>Cutoff</dt><dd>2026-09-20 10:42:00 UTC</dd></div></dl>${properties}<div class="ln-record-note">Synthetic evidence<br />Execution authority: none</div></div><div><h3>Incoming connections <small>${incoming.length}</small></h3><div class="ln-related">${relationButtons(incoming, 0)}</div><h3>Outgoing connections <small>${outgoing.length}</small></h3><div class="ln-related">${relationButtons(outgoing, 1)}</div><button type="button" class="ln-focus" id="lineageFocus" aria-pressed="${focused}">${focused ? "Show all records" : "Focus on this record"}</button></div>`;
  }
  function renderSources(query) {
    const sources = nodes.filter(node => node.x === 24).map(node => [node.title, node.kind === "normative" ? "Rules / knowledge" : "Observed data", node.sub, status(node), node.id]);
    const rows = [...sources, ...extraSources].filter(source => source.join(" ").toLowerCase().includes(query));
    byId("lineageSources").innerHTML = `<h2>Source register <small>${rows.length}</small></h2>` + (rows.length ? rows.map(([title, kind, scope, state, id]) => `<article class="ln-source-row"><div>${id ? `<button type="button" data-select="${id}">${escape(title)}</button>` : `<strong>${escape(title)}</strong>`}</div><span>${escape(kind)}</span><span>${escape(scope)}</span><span>${escape(state)}</span></article>`).join("") : "<p>No matching sources.</p>");
  }
  function select(id) { selected = id; byId("lineageSearch").value = ""; setView("graph"); render(); }
  function setView(next) { view = next; byId("lineageLayout").hidden = view !== "graph"; byId("lineageSources").hidden = view !== "sources"; document.querySelectorAll("[data-view]").forEach(button => button.setAttribute("aria-pressed", String(button.dataset.view === view))); }
  document.addEventListener("click", event => {
    const button = event.target.closest("button");
    if (!button) return;
    if (button.dataset.node) { selected = button.dataset.node; render(); document.querySelector(`[data-node="${selected}"]`)?.focus({ preventScroll: true }); }
    if (button.dataset.select) { select(button.dataset.select); document.querySelector(`[data-node="${selected}"]`)?.focus(); }
    if (button.dataset.view) setView(button.dataset.view);
    if (button.id === "lineageFocus") { focused = !focused; render(); byId("lineageFocus").focus(); }
    if (button.id === "lineageReset") { focused = false; byId("lineageSearch").value = ""; zoom = 1; updateZoom(); render(); }
    if (button.id === "lineageZoomIn" || button.id === "lineageZoomOut") { zoom = Math.max(.75, Math.min(1.5, zoom + (button.id === "lineageZoomIn" ? .125 : -.125))); updateZoom(); }
  });
  function updateZoom() { byId("lineageCanvas").style.transform = `scale(${zoom})`; byId("lineageCanvasSize").style.width = `${1272 * zoom}px`; byId("lineageCanvasSize").style.height = `${692 * zoom}px`; byId("lineageZoom").value = `${Math.round(zoom * 100)}%`; }
  byId("lineageSearch").addEventListener("input", render);
  byId("lineageScenario").addEventListener("change", render);
  render();
}());
