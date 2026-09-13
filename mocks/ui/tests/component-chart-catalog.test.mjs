import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  CHART_CATALOGS,
  DATADOG_CONTAINERS,
  DATADOG_DELIVERY_SURFACES,
  DATADOG_INTERACTIONS,
  DATADOG_PRODUCT_SURFACES,
  DATADOG_WIDGETS,
  FDAI_CHART_SURFACES,
} from "../assets/component-chart-catalog.mjs";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const uiRoot = join(root, "mocks/ui");
const components = await readFile(join(uiRoot, "components.html"), "utf8");
const catalogStyles = await readFile(join(uiRoot, "assets/component-chart-catalog.css"), "utf8");
const datadogResearch = await readFile(join(root, "docs/internals/datadog-visualization-surface.md"), "utf8");

function markdownSection(start, end) {
  const startIndex = datadogResearch.indexOf(start);
  const endIndex = datadogResearch.indexOf(end, startIndex);
  assert.ok(startIndex >= 0, start);
  assert.ok(endIndex > startIndex, end);
  return datadogResearch.slice(startIndex, endIndex);
}

function boldNames(markdown) {
  return [...markdown.matchAll(/\*\*([^*]+)\*\*/g)].map(match => match[1]);
}

function names(entries) {
  return entries.map(entry => entry.name);
}

function assertSameNames(actual, expected, label) {
  assert.deepEqual([...actual].sort(), [...expected].sort(), label);
}

test("Datadog research entries are completely represented in the chart catalog", () => {
  const widgetSection = markdownSection("## 2. Complete widget catalog", "## 3. Product-native");
  const widgetNames = [...widgetSection.matchAll(/^\| \*\*([^*]+)\*\*/gm)].map(match => match[1]);
  const productNames = boldNames(markdownSection("## 3. Product-native", "## 4. Cross-cutting"));
  const interactionNames = boldNames(markdownSection("## 4. Cross-cutting", "## 5. Delivery"));
  const deliveryNames = boldNames(markdownSection("## 5. Delivery", "## 6. FDAI"));
  const containerNames = boldNames(markdownSection("## 1. Top-level containers", "## 2. Complete widget catalog"))
    .filter(name => ["Dashboard", "Notebook", "Timeboard", "Screenboard"].includes(name));

  assert.equal(widgetNames.length, 39);
  assert.equal(productNames.length, 61);
  assert.equal(interactionNames.length, 10);
  assert.equal(deliveryNames.length, 7);
  assert.equal(containerNames.length, 4);
  assertSameNames(names(DATADOG_WIDGETS), widgetNames, "dashboard widgets");
  assertSameNames(names(DATADOG_PRODUCT_SURFACES), productNames, "product-native surfaces");
  assertSameNames(names(DATADOG_INTERACTIONS), interactionNames, "composition primitives");
  assertSameNames(names(DATADOG_DELIVERY_SURFACES), deliveryNames, "delivery surfaces");
  assertSameNames(names(DATADOG_CONTAINERS), containerNames, "containers");
  assert.equal(DATADOG_WIDGETS.find(entry => entry.name === "Run Workflow")?.status,
    "Reference only - no Console action");
});

test("FDAI chart catalog covers every chart-bearing static mock family", () => {
  assert.equal(FDAI_CHART_SURFACES.length, 19);
  const linkedRoutes = new Set(FDAI_CHART_SURFACES.flatMap(entry =>
    entry.routes.map(([, href]) => href.split("#")[0])));
  [
    "agent-activity.html",
    "agents.html",
    "architecture.html",
    "cost-governance.html",
    "dashboard-v2.html",
    "finops-resource-efficiency.html",
    "incidents.html",
    "live.html",
    "llm-cost.html",
    "ontology-instances-2d.html",
    "ontology-knowledge-graph.html",
    "ontology-map.html",
    "ontology.html",
    "operating-outcomes.html",
    "provision.html",
    "rule-trace.html",
    "trust-routing.html",
  ].forEach(route => assert.equal(linkedRoutes.has(route), true, route));
  [
    "timeseries",
    "bar",
    "distribution",
    "donut",
    "scatter",
    "heatmap",
    "waterfall",
    "timeline",
    "funnel",
    "sankey",
    "treemap",
    "flame",
    "split",
    "topology",
    "network",
    "org",
    "knowledge",
    "instance",
    "diagram",
  ].forEach(kind => assert.equal(FDAI_CHART_SURFACES.some(entry => entry.kind === kind), true, kind));
});

test("catalog totals and Gallery mounting points remain exact", () => {
  const dynamicTotal = CHART_CATALOGS.reduce((total, catalog) => total + catalog.entries.length, 0);
  assert.equal(dynamicTotal, 140);
  assert.match(components, /data-gallery-count-label="190 visualization entries"/);
  assert.match(components, /<details class="cs-chart-family" id="chart-family" open>/);
  assert.match(components, /component-chart-catalog\.css\?v=2/);
  assert.match(components, /component-chart-catalog\.mjs\?v=2/);
  CHART_CATALOGS.forEach(catalog => {
    assert.match(components, new RegExp(`data-chart-catalog="${catalog.id}"`));
    assert.match(components, new RegExp(`data-chart-catalog-count="${catalog.id}"`));
    assert.equal(new Set(names(catalog.entries)).size, catalog.entries.length, catalog.id);
  });
  assert.match(components, /190 entries across FDAI surfaces, Datadog research, and Tremor variants/);
});

test("catalog layout preserves current responsive and accessibility contracts", () => {
  assert.match(catalogStyles, /\.cg-chart-catalog-grid \{[^}]*grid-template-columns: repeat\(3,/);
  assert.match(catalogStyles, /@media \(max-width: 720px\)[\s\S]*\.cg-chart-catalog-grid,[\s\S]*grid-template-columns: minmax\(0, 1fr\)/);
  assert.match(catalogStyles, /@media \(forced-colors: active\)/);
  assert.match(catalogStyles, /\.cg-chart-entry > footer a \{[\s\S]*color: var\(--cs-steel\)/);
  assert.match(catalogStyles, /\.cg-chart-mini \{[\s\S]*min-height: 112px/);
  assert.match(components, /aria-live="polite" data-chart-catalog-result/);
  assert.match(components, /data-chart-catalog-empty hidden/);
});
