const freezeEntries = (rows, source, defaultStatus) => Object.freeze(rows.map((row) => Object.freeze({
  name: row[0],
  group: row[1],
  kind: row[2],
  source,
  status: row[3] || defaultStatus,
})));

export const FDAI_CHART_SURFACES = Object.freeze([
  {
    name: "Trend / line / area series",
    group: "Metrics over time",
    kind: "timeseries",
    purpose: "Compare verified values, baselines, forecasts, and cumulative change over time.",
    surfaces: "Operating outcomes, LLM cost, live operations",
    routes: [["Operating outcomes", "operating-outcomes.html"], ["LLM cost", "llm-cost.html"], ["Live", "live.html"]],
  },
  {
    name: "Comparison / category bars",
    group: "Categorical comparison",
    kind: "bar",
    purpose: "Compare exact values across domains, tiers, opportunities, and token classes.",
    surfaces: "Dashboard, cost governance, LLM cost",
    routes: [["Dashboard", "dashboard-v2.html"], ["Cost governance", "cost-governance.html"], ["LLM cost", "llm-cost.html"]],
  },
  {
    name: "Distribution / composition bars",
    group: "Part-to-whole",
    kind: "distribution",
    purpose: "Show a bounded composition while retaining exact counts and percentages.",
    surfaces: "Live decision mix, cost composition",
    routes: [["Live", "live.html"], ["Cost governance", "cost-governance.html"]],
  },
  {
    name: "Donut / pie / progress / gauge",
    group: "Bounded status",
    kind: "donut",
    purpose: "Show one bounded proportion or progress state with an explicit denominator.",
    surfaces: "Live tier mix, provisioning progress, efficiency gauges",
    routes: [["Live", "live.html"], ["Provisioning", "provision.html"], ["Resource efficiency", "finops-resource-efficiency.html"]],
  },
  {
    name: "Scatter plot",
    group: "Correlation",
    kind: "scatter",
    purpose: "Place resources against two measured dimensions without implying causation.",
    surfaces: "FinOps resource efficiency",
    routes: [["Resource efficiency", "finops-resource-efficiency.html"]],
  },
  {
    name: "Density / retention / host matrix",
    group: "Two-dimensional density",
    kind: "heatmap",
    purpose: "Expose density, cohort, and fleet patterns in labeled cells with exact-value alternatives.",
    surfaces: "Process reports and Gallery evidence-density specimen",
    routes: [["Gallery chart family", "#chart-family"]],
  },
  {
    name: "Trace waterfall",
    group: "Ordered duration",
    kind: "waterfall",
    purpose: "Show parent-child spans, elapsed time, and handoff latency on one ordered axis.",
    surfaces: "Rule trace, model trace, agent activity",
    routes: [["Rule trace", "rule-trace.html"], ["Agent activity", "agent-activity.html"]],
  },
  {
    name: "Agent / incident timeline",
    group: "Ordered events",
    kind: "timeline",
    purpose: "Show state transitions, accountable agents, notifications, and responses in event order.",
    surfaces: "Incidents, agent activity, provisioning",
    routes: [["Incidents", "incidents.html"], ["Agent activity", "agent-activity.html"], ["Provisioning", "provision.html"]],
  },
  {
    name: "Decision funnel",
    group: "Stage conversion",
    kind: "funnel",
    purpose: "Show how candidates narrow through deterministic rules, review, and approval gates.",
    surfaces: "Cost governance and resource efficiency",
    routes: [["Cost governance", "cost-governance.html"], ["Resource efficiency", "finops-resource-efficiency.html"]],
  },
  {
    name: "Sankey flow",
    group: "Directional flow",
    kind: "sankey",
    purpose: "Show volume moving between typed states without hiding dropped or unmeasured paths.",
    surfaces: "FinOps resource efficiency",
    routes: [["Resource efficiency", "finops-resource-efficiency.html"]],
  },
  {
    name: "Treemap",
    group: "Hierarchical composition",
    kind: "treemap",
    purpose: "Compare area-weighted cost or capacity within a bounded hierarchy.",
    surfaces: "FinOps resource efficiency",
    routes: [["Resource efficiency", "finops-resource-efficiency.html"]],
  },
  {
    name: "Flame graph",
    group: "Stacked duration",
    kind: "flame",
    purpose: "Show nested execution cost and hot paths while preserving frame labels.",
    surfaces: "FinOps resource efficiency and process reports",
    routes: [["Resource efficiency", "finops-resource-efficiency.html"]],
  },
  {
    name: "Split graph",
    group: "Small multiples",
    kind: "split",
    purpose: "Repeat one comparable query by bounded group without mixing scales.",
    surfaces: "FinOps resource efficiency and process reports",
    routes: [["Resource efficiency", "finops-resource-efficiency.html"]],
  },
  {
    name: "Service / resource topology",
    group: "Dependency graph",
    kind: "topology",
    purpose: "Show dependency direction, selected nodes, health, and blast-radius context.",
    surfaces: "Ontology map, dashboard resource map, trust routing",
    routes: [["Ontology map", "ontology-map.html"], ["Dashboard", "dashboard-v2.html"], ["Trust routing", "trust-routing.html"]],
  },
  {
    name: "Architecture / network map",
    group: "System map",
    kind: "network",
    purpose: "Show bounded architecture layers and network relationships with labeled nodes.",
    surfaces: "Architecture and dashboard",
    routes: [["Architecture", "architecture.html"], ["Dashboard", "dashboard-v2.html"]],
  },
  {
    name: "Agent organization chart",
    group: "Accountability graph",
    kind: "org",
    purpose: "Show fixed agent roles and reporting relationships without implying execution authority.",
    surfaces: "Agents and Pantheon",
    routes: [["Agents", "agents.html"]],
  },
  {
    name: "Ontology semantic / knowledge graph",
    group: "Semantic graph",
    kind: "knowledge",
    purpose: "Explore typed entities, relationships, evidence, and provenance.",
    surfaces: "Ontology and knowledge graph",
    routes: [["Ontology", "ontology.html"], ["Knowledge graph", "ontology-knowledge-graph.html"]],
  },
  {
    name: "Operational instance graph",
    group: "Time-aware graph",
    kind: "instance",
    purpose: "Relate recorded resource instances, effective time, and operational evidence.",
    surfaces: "Ontology instances",
    routes: [["Ontology instances", "ontology-instances-2d.html"]],
  },
  {
    name: "Declarative Mermaid diagram",
    group: "Documented diagram",
    kind: "diagram",
    purpose: "Render a labeled architecture or process diagram with loading and error states.",
    surfaces: "Ontology documentation and Console diagrams",
    routes: [["Ontology", "ontology.html"]],
  },
].map((entry) => Object.freeze({ ...entry, source: "fdai", status: "Rendered in FDAI" })));

export const DATADOG_CONTAINERS = freezeEntries([
  ["Dashboard", "Containers", "dashboard"],
  ["Notebook", "Containers", "notebook"],
  ["Timeboard", "Historical containers", "timeboard"],
  ["Screenboard", "Historical containers", "screenboard"],
], "datadog-containers", "Reference");

export const DATADOG_WIDGETS = freezeEntries([
  ["Timeseries", "Graphs", "timeseries"],
  ["Bar Chart", "Graphs", "bar"],
  ["Query Value", "Graphs", "metric"],
  ["Change", "Graphs", "change"],
  ["Top List", "Graphs", "top-list"],
  ["Table", "Graphs", "table"],
  ["Distribution", "Graphs", "histogram"],
  ["Heatmap", "Graphs", "heatmap"],
  ["Pie Chart", "Graphs", "donut"],
  ["Scatter Plot", "Graphs", "scatter"],
  ["Point Plot", "Graphs", "point"],
  ["Treemap", "Graphs", "treemap"],
  ["Geomap", "Graphs", "geomap"],
  ["Wildcard", "Graphs", "vega"],
  ["Funnel", "Product analytics", "funnel"],
  ["Sankey", "Product analytics", "sankey"],
  ["Retention", "Product analytics", "retention"],
  ["Hostmap", "Architecture", "hostmap"],
  ["Topology Map", "Architecture", "topology"],
  ["Service Summary", "Architecture", "service-summary"],
  ["Cloudcraft Diagram", "Architecture", "diagram"],
  ["List", "Lists and streams", "list"],
  ["Alert Graph", "Alerting and response", "alert"],
  ["Alert Value", "Alerting and response", "metric"],
  ["Check Status", "Alerting and response", "status"],
  ["Monitor Summary", "Alerting and response", "monitor"],
  ["Run Workflow", "Alerting and response", "action", "Reference only - no Console action"],
  ["SLO Summary", "Performance and reliability", "slo"],
  ["SLO (list)", "Performance and reliability", "slo-list"],
  ["Profiling Flame Graph", "Performance and reliability", "flame"],
  ["Cost Summary", "Cloud cost", "cost"],
  ["Budget Summary", "Cloud cost", "budget"],
  ["Free Text", "Annotations and embeds", "text"],
  ["Notes and Links", "Annotations and embeds", "notes"],
  ["Image", "Annotations and embeds", "image"],
  ["Iframe", "Annotations and embeds", "embed"],
  ["Group", "Group and composition", "group"],
  ["Powerpack", "Group and composition", "bundle"],
  ["Split Graph", "Group and composition", "split"],
], "datadog-widgets", "Datadog reference");

export const DATADOG_PRODUCT_SURFACES = freezeEntries([
  ["Service page", "APM / Tracing", "service-summary"],
  ["Service Map", "APM / Tracing", "topology"],
  ["Trace waterfall", "APM / Tracing", "waterfall"],
  ["Span flame graph", "APM / Tracing", "flame"],
  ["Continuous Profiler flame graph", "APM / Tracing", "flame"],
  ["Catalog", "APM / Tracing", "topology"],
  ["Error Tracking", "APM / Tracing", "timeline"],
  ["Deployment Tracking", "APM / Tracing", "point"],
  ["Log Explorer", "Logs", "histogram"],
  ["Patterns", "Logs", "top-list"],
  ["Transactions", "Logs", "timeline"],
  ["Analytics", "Logs", "bar"],
  ["Live Tail", "Logs", "list"],
  ["Sensitive Data Scanner findings", "Logs", "status"],
  ["Session Explorer", "RUM", "table"],
  ["Session Replay", "RUM", "replay"],
  ["Heatmaps", "RUM", "heatmap"],
  ["Funnels", "RUM", "funnel"],
  ["Retention", "RUM", "retention"],
  ["Core Web Vitals dashboards", "RUM", "distribution"],
  ["Error tracking", "RUM", "timeline"],
  ["Test result waterfall", "Synthetics", "waterfall"],
  ["Browser test step screenshots", "Synthetics", "screenshot"],
  ["Global uptime map", "Synthetics", "geomap"],
  ["API test latency timeseries", "Synthetics", "timeseries"],
  ["Network Performance Monitoring flow map", "Network", "sankey"],
  ["Cloud Network Monitoring topology", "Network", "network"],
  ["Network Path Analysis", "Network", "path"],
  ["DNS Monitoring", "Network", "matrix"],
  ["Host Map", "Infrastructure", "hostmap"],
  ["Container Map", "Infrastructure", "hostmap"],
  ["Kubernetes Resource Utilization / Explorer", "Infrastructure", "treemap"],
  ["Live Processes", "Infrastructure", "table"],
  ["Live Containers", "Infrastructure", "table"],
  ["Serverless view", "Infrastructure", "service-summary"],
  ["Query samples", "Database monitoring", "table"],
  ["Explain plan viewer", "Database monitoring", "topology"],
  ["Wait event breakdown", "Database monitoring", "area"],
  ["Query metrics", "Database monitoring", "heatmap"],
  ["Signals Explorer", "Security", "list"],
  ["Investigator graph", "Security", "knowledge"],
  ["Threat Map / Attack Map", "Security", "geomap"],
  ["Compliance posture", "Security", "matrix"],
  ["Vulnerability dashboards", "Security", "table"],
  ["Pipeline execution graph", "CI visibility", "topology"],
  ["Flaky test dashboards", "CI visibility", "timeline"],
  ["Test session replay", "CI visibility", "replay"],
  ["Cost Explorer", "Cloud cost", "cost"],
  ["Recommendations", "Cloud cost", "top-list"],
  ["Cost anomaly detection", "Cloud cost", "anomaly"],
  ["Stream topology", "Data streams", "sankey"],
  ["Lag timeseries per partition", "Data streams", "timeseries"],
  ["DORA metric tiles", "Software delivery", "metric"],
  ["Deployment table", "Software delivery", "table"],
  ["Incident timeline", "Incident management", "timeline"],
  ["Impact map", "Incident management", "topology"],
  ["Postmortem view", "Incident management", "notebook"],
  ["Workflow execution graph", "Workflow automation", "topology"],
  ["App Builder", "Workflow automation", "app"],
  ["Watchdog Insights", "Watchdog / Bits AI", "anomaly"],
  ["Bits AI", "Watchdog / Bits AI", "chat"],
], "datadog-products", "Product surface reference");

export const DATADOG_INTERACTIONS = freezeEntries([
  ["Formulas & Functions", "Composition and interactivity", "formula"],
  ["Template variables", "Composition and interactivity", "filter"],
  ["Widget-scoped time overrides", "Composition and interactivity", "time"],
  ["Event overlays / change overlays", "Composition and interactivity", "overlay"],
  ["Comparison series", "Composition and interactivity", "comparison"],
  ["Conditional formatting", "Composition and interactivity", "conditional"],
  ["Dashboard links & widget-to-widget filtering", "Composition and interactivity", "drilldown"],
  ["Tabs", "Composition and interactivity", "tabs"],
  ["Global time picker", "Composition and interactivity", "time"],
  ["Wildcard / Vega", "Composition and interactivity", "vega"],
], "datadog-interactions", "Interaction reference");

export const DATADOG_DELIVERY_SURFACES = freezeEntries([
  ["Public sharing", "Delivery and sharing", "share"],
  ["Embedded graphs", "Delivery and sharing", "embed"],
  ["Scheduled reports", "Delivery and sharing", "report"],
  ["Mobile App", "Delivery and sharing", "mobile"],
  ["TV Mode", "Delivery and sharing", "tv"],
  ["Slack / Teams unfurls", "Delivery and sharing", "unfurl"],
  ["API render endpoints", "Delivery and sharing", "api"],
], "datadog-delivery", "Delivery reference");

export const CHART_CATALOGS = Object.freeze([
  {
    id: "fdai",
    title: "FDAI chart surfaces",
    description: "Every distinct visualization family rendered by the current Console or a static design mock.",
    entries: FDAI_CHART_SURFACES,
  },
  {
    id: "datadog-widgets",
    title: "Datadog dashboard widgets",
    description: "All 39 first-party dashboard and notebook widget types in the repository survey.",
    entries: DATADOG_WIDGETS,
  },
  {
    id: "datadog-products",
    title: "Datadog product-native surfaces",
    description: "All dedicated product visualization surfaces recorded in the repository survey.",
    entries: DATADOG_PRODUCT_SURFACES,
  },
  {
    id: "datadog-containers",
    title: "Datadog containers",
    description: "Current and historical containers that organize visualization content.",
    entries: DATADOG_CONTAINERS,
  },
  {
    id: "datadog-interactions",
    title: "Datadog composition primitives",
    description: "Cross-cutting behaviors that change how a visualization is queried, compared, and explored.",
    entries: DATADOG_INTERACTIONS,
  },
  {
    id: "datadog-delivery",
    title: "Datadog delivery surfaces",
    description: "Places where rendered visualizations leave the primary browser dashboard.",
    entries: DATADOG_DELIVERY_SURFACES,
  },
]);

const groupPurpose = Object.freeze({
  "APM / Tracing": "Inspect service behavior, traces, spans, and deployments.",
  Logs: "Search, cluster, compare, and stream log evidence.",
  RUM: "Analyze real-user sessions, performance, errors, and journeys.",
  Synthetics: "Inspect test steps, location health, and request timing.",
  Network: "Trace traffic, paths, topology, latency, and loss.",
  Infrastructure: "Compare fleet, container, cluster, process, and serverless state.",
  "Database monitoring": "Inspect query behavior, plans, waits, and density.",
  Security: "Correlate signals, entities, posture, and vulnerability evidence.",
  "CI visibility": "Trace pipeline and test reliability over time.",
  "Cloud cost": "Compare spend, budgets, anomalies, and recommendations.",
  "Data streams": "Trace producer-to-consumer flow and lag.",
  "Software delivery": "Compare DORA outcomes and deployment health.",
  "Incident management": "Explain incident progression, impact, and postmortem evidence.",
  "Workflow automation": "Describe workflow structure without granting Console execution authority.",
  "Watchdog / Bits AI": "Present anomaly and conversational findings as bounded evidence.",
});

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, character => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[character]);
}

function seriesVisual(extraClass = "") {
  return `<svg class="cg-mini-series ${extraClass}" viewBox="0 0 220 96" aria-hidden="true">
    <path class="is-grid" d="M6 18H214 M6 48H214 M6 82H214" />
    <path class="is-area" d="M6 74L42 58L78 65L112 32L148 46L182 20L214 36L214 84L6 84Z" />
    <path class="is-line" d="M6 74L42 58L78 65L112 32L148 46L182 20L214 36" />
    <path class="is-reference" d="M6 69L42 64L78 55L112 57L148 40L182 44L214 29" />
  </svg>`;
}

function barVisual() {
  return '<div class="cg-mini-bars" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i><i></i></div>';
}

function gridVisual() {
  return `<div class="cg-mini-grid" aria-hidden="true">${"<i></i>".repeat(24)}</div>`;
}

function graphVisual(kind) {
  if (kind === "network") {
    return `<svg class="cg-mini-graph is-network" viewBox="0 0 220 96" aria-hidden="true">
      <path d="M34 22H98M122 22H186M34 74H98M122 74H186M46 30L98 66M174 30L122 66" />
      <rect x="12" y="12" width="44" height="20" rx="4" /><rect x="88" y="12" width="44" height="20" rx="4" />
      <rect x="164" y="12" width="44" height="20" rx="4" /><rect x="50" y="64" width="60" height="20" rx="4" />
      <rect x="112" y="64" width="60" height="20" rx="4" />
    </svg>`;
  }
  if (kind === "org") {
    return `<svg class="cg-mini-graph is-org" viewBox="0 0 220 96" aria-hidden="true">
      <path d="M110 30V48M38 48H182M38 48V66M86 48V66M134 48V66M182 48V66" />
      <rect x="82" y="10" width="56" height="20" rx="4" /><rect x="14" y="66" width="48" height="18" rx="4" />
      <rect x="62" y="66" width="48" height="18" rx="4" /><rect x="110" y="66" width="48" height="18" rx="4" />
      <rect x="158" y="66" width="48" height="18" rx="4" />
    </svg>`;
  }
  if (kind === "instance") {
    return `<svg class="cg-mini-graph is-instance" viewBox="0 0 220 96" aria-hidden="true">
      <path class="is-time" d="M18 80H204" /><path d="M38 26L96 50L156 22M96 50L178 66" />
      <circle cx="38" cy="26" r="9" /><circle cx="96" cy="50" r="11" /><circle cx="156" cy="22" r="9" /><circle cx="178" cy="66" r="9" />
      <path class="is-tick" d="M38 76V84M96 76V84M156 76V84" />
    </svg>`;
  }
  if (kind === "diagram") {
    return `<svg class="cg-mini-graph is-diagram" viewBox="0 0 220 96" aria-hidden="true">
      <path d="M68 28H94M126 28H152M110 38V58" />
      <rect x="12" y="16" width="56" height="24" rx="4" /><rect x="82" y="16" width="56" height="24" rx="4" />
      <rect x="152" y="16" width="56" height="24" rx="4" /><rect x="80" y="58" width="60" height="24" rx="4" />
    </svg>`;
  }
  return `<svg class="cg-mini-graph is-${escapeHtml(kind)}" viewBox="0 0 220 96" aria-hidden="true">
    <path d="M32 48L82 22L132 46L188 20M82 22L102 78L132 46L172 76M32 48L102 78" />
    <circle cx="32" cy="48" r="9" /><circle cx="82" cy="22" r="11" /><circle cx="132" cy="46" r="10" />
    <circle cx="188" cy="20" r="8" /><circle cx="102" cy="78" r="9" /><circle cx="172" cy="76" r="8" />
  </svg>`;
}

function visualMarkup(entry) {
  const kind = entry.kind;
  let body;
  if (["timeseries", "area", "alert", "cost", "retention", "anomaly", "comparison", "overlay"].includes(kind)) {
    body = seriesVisual(`is-${kind}`);
  } else if (["bar", "histogram", "distribution", "top-list", "budget", "point"].includes(kind)) {
    body = barVisual();
  } else if (["metric", "change", "status", "service-summary", "monitor", "dora"].includes(kind)) {
    body = '<div class="cg-mini-metric" aria-hidden="true"><strong>99.95%</strong><span>+4.8 pts</span><i></i></div>';
  } else if (["donut", "slo", "slo-list"].includes(kind)) {
    body = '<div class="cg-mini-radial" aria-hidden="true"><i></i><strong>84%</strong></div>';
  } else if (["scatter"].includes(kind)) {
    body = '<div class="cg-mini-scatter" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i><i></i></div>';
  } else if (["heatmap", "hostmap", "matrix", "conditional"].includes(kind)) {
    body = gridVisual();
  } else if (["waterfall", "timeline", "path"].includes(kind)) {
    body = '<div class="cg-mini-waterfall" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i></div>';
  } else if (kind === "funnel") {
    body = '<div class="cg-mini-funnel" aria-hidden="true"><i></i><i></i><i></i><i></i></div>';
  } else if (kind === "sankey") {
    body = '<div class="cg-mini-sankey" aria-hidden="true"><i></i><i></i><i></i><i></i><b></b><b></b><b></b></div>';
  } else if (kind === "treemap") {
    body = '<div class="cg-mini-treemap" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i></div>';
  } else if (kind === "flame") {
    body = '<div class="cg-mini-flame" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i><i></i></div>';
  } else if (kind === "split") {
    body = `<div class="cg-mini-split" aria-hidden="true">${seriesVisual()}${seriesVisual()}${seriesVisual()}</div>`;
  } else if (["topology", "network", "org", "knowledge", "instance", "diagram"].includes(kind)) {
    body = graphVisual(kind);
  } else if (kind === "geomap") {
    body = '<div class="cg-mini-map" aria-hidden="true"><i></i><i></i><i></i><b></b><b></b><b></b></div>';
  } else if (["table", "list"].includes(kind)) {
    body = '<div class="cg-mini-list" aria-hidden="true"><i></i><i></i><i></i><i></i></div>';
  } else if (["replay", "screenshot", "image", "embed", "mobile", "tv", "unfurl"].includes(kind)) {
    body = '<div class="cg-mini-frame" aria-hidden="true"><i></i><span></span><b></b></div>';
  } else if (["notebook", "text", "notes", "report"].includes(kind)) {
    body = '<div class="cg-mini-document" aria-hidden="true"><strong></strong><i></i><i></i><i></i></div>';
  } else if (["dashboard", "timeboard", "screenboard", "group", "bundle", "app", "tabs"].includes(kind)) {
    body = '<div class="cg-mini-dashboard" aria-hidden="true"><i></i><i></i><i></i><i></i></div>';
  } else if (kind === "action") {
    body = '<div class="cg-mini-action" aria-hidden="true"><span>Reference only</span><i></i></div>';
  } else if (kind === "chat") {
    body = '<div class="cg-mini-chat" aria-hidden="true"><i></i><i></i><i></i></div>';
  } else {
    body = '<div class="cg-mini-generic" aria-hidden="true"><i></i><i></i><i></i></div>';
  }
  return `<div class="cg-chart-mini is-${escapeHtml(kind)}" role="img" aria-label="${escapeHtml(entry.name)} synthetic visualization specimen">${body}</div>`;
}

function purposeFor(entry) {
  if (entry.purpose) return entry.purpose;
  if (groupPurpose[entry.group]) return groupPurpose[entry.group];
  if (entry.source === "datadog-widgets") return `Reference shape for the Datadog ${entry.name} widget.`;
  if (entry.source === "datadog-interactions") return `Reference behavior for composing and exploring verified chart data.`;
  if (entry.source === "datadog-delivery") return `Reference delivery form for a rendered visualization.`;
  return `Reference container for organizing related visualization evidence.`;
}

function routeMarkup(entry) {
  if (!entry.routes?.length) return '<span>Repository Datadog survey</span>';
  return entry.routes.map(([label, href]) =>
    `<a href="${escapeHtml(href)}">${escapeHtml(label)}</a>`).join("");
}

function renderEntry(entry, index) {
  const searchable = [entry.name, entry.group, entry.source, entry.status, entry.surfaces || "", purposeFor(entry)]
    .join(" ")
    .toLocaleLowerCase();
  return `<article class="cg-chart-entry" data-chart-entry data-chart-source="${escapeHtml(entry.source)}" data-chart-search="${escapeHtml(searchable)}">
    <header><span>${escapeHtml(entry.group)}</span><small>${escapeHtml(entry.status)}</small></header>
    <h4><span>${String(index + 1).padStart(2, "0")}</span>${escapeHtml(entry.name)}</h4>
    ${visualMarkup(entry)}
    <p>${escapeHtml(purposeFor(entry))}</p>
    <footer>${routeMarkup(entry)}</footer>
  </article>`;
}

export function renderComponentChartCatalog(root = document) {
  const catalogRoot = root.querySelector("[data-chart-catalog-root]");
  if (!catalogRoot) return;

  CHART_CATALOGS.forEach(catalog => {
    const target = catalogRoot.querySelector(`[data-chart-catalog="${catalog.id}"]`);
    const count = catalogRoot.querySelector(`[data-chart-catalog-count="${catalog.id}"]`);
    if (!target || !count) return;
    target.innerHTML = catalog.entries.map(renderEntry).join("");
    count.textContent = String(catalog.entries.length);
  });

  const dynamicTotal = CHART_CATALOGS.reduce((total, catalog) => total + catalog.entries.length, 0);
  const specimenTotal = dynamicTotal + 50;
  catalogRoot.querySelectorAll("[data-chart-catalog-total]").forEach(node => {
    node.textContent = String(dynamicTotal);
  });
  catalogRoot.querySelectorAll("[data-chart-specimen-total]").forEach(node => {
    node.textContent = String(specimenTotal);
  });

  const search = catalogRoot.querySelector("[data-chart-catalog-search]");
  const source = catalogRoot.querySelector("[data-chart-catalog-source]");
  const clear = catalogRoot.querySelector("[data-chart-catalog-clear]");
  const result = catalogRoot.querySelector("[data-chart-catalog-result]");
  const empty = catalogRoot.querySelector("[data-chart-catalog-empty]");
  const cards = Array.from(catalogRoot.querySelectorAll("[data-chart-entry]"));
  const sections = Array.from(catalogRoot.querySelectorAll("[data-chart-catalog-section]"));

  function applyFilter() {
    const query = search.value.trim().toLocaleLowerCase();
    let visible = 0;
    cards.forEach(card => {
      const matchesSource = source.value === "all" || card.dataset.chartSource === source.value;
      const matchesQuery = !query || card.dataset.chartSearch.includes(query);
      card.hidden = !(matchesSource && matchesQuery);
      if (!card.hidden) visible += 1;
    });
    sections.forEach(section => {
      section.hidden = !section.querySelector("[data-chart-entry]:not([hidden])");
    });
    result.value = `${visible} of ${cards.length} catalog entries`;
    empty.hidden = visible !== 0;
    clear.disabled = !query && source.value === "all";
  }

  search.addEventListener("input", applyFilter);
  source.addEventListener("change", applyFilter);
  clear.addEventListener("click", () => {
    search.value = "";
    source.value = "all";
    applyFilter();
    search.focus();
  });
  applyFilter();
  catalogRoot.dataset.chartCatalogReady = "true";
}

if (typeof document !== "undefined") {
  renderComponentChartCatalog(document);
}
