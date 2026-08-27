const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const test = require("node:test");

const uiRoot = join(__dirname, "..");
const navigation = readFileSync(join(uiRoot, "assets", "calm-slate.js"), "utf8");
const landing = readFileSync(join(uiRoot, "index.html"), "utf8");
const masterLanding = readFileSync(join(uiRoot, "..", "..", "index.html"), "utf8");
const components = readFileSync(join(uiRoot, "components.html"), "utf8");
const stylesheet = readFileSync(join(uiRoot, "assets", "calm-slate.css"), "utf8");
const typography = readFileSync(join(uiRoot, "typography.html"), "utf8");

test("typography has direct, kit, and master navigation entries", () => {
  assert.match(navigation, /\["typography\.html", "Typography", "is-steel"\]/);
  assert.match(landing, /data-page="typography\.html"[^>]*data-title="Typography"/);
  assert.match(masterLanding, /data-page="mocks\/ui\/typography\.html"[^>]*data-title="Typography"/);
  assert.match(masterLanding, /<h3>Console navigation<\/h3><span class="count">51 pages<\/span>/);
  assert.match(masterLanding, /<span class="nav-group-label">Labs<\/span><span class="count">1<\/span>/);
});

test("direct mock URLs canonicalize through the master hash router", () => {
  assert.match(navigation, /window\.location\.pathname\.match\(\/\^\\\/\(mocks\\\/ui\\\/\.\+\\\.html\)\$\/\)/);
  assert.match(navigation, /window\.self === window\.top && directMockMatch/);
  assert.match(navigation, /directSection \? "::" \+ directSection : ""/);
  assert.match(navigation, /window\.location\.replace\(canonicalUrl\)/);
});

test("master navigation keeps one quiet, collapsible hierarchy", () => {
  assert.match(masterLanding, /--nav-w: 248px/);
  assert.match(masterLanding, /src="console\/public\/brand\/fdai-logo\.png"/);
  assert.equal((masterLanding.match(/<button class="nav-group-head"/g) || []).length, 7);
  assert.equal((masterLanding.match(/<button class="fam is-/g) || []).length, 5);
  assert.doesNotMatch(masterLanding, /<button[^>]*>[^<]*<h[1-6]>/);
  assert.match(masterLanding, /\.side \.nav-group a \.dot \{ visibility: hidden; \}/);
  assert.match(masterLanding, /\.side \.nav-group a\.is-active \.dot \{ visibility: visible; \}/);
  assert.match(masterLanding, /function revealPageGroup\(page\)/);
  assert.match(masterLanding, /function setFamilyExpanded\(family, expanded\)/);
});

test("typography page renders every shared semantic role", () => {
  [
    "page-title",
    "page-subtitle",
    "lead",
    "section-title",
    "panel-title",
    "body",
    "compact",
    "label",
    "caption",
  ].forEach((role) => assert.match(typography, new RegExp(`cs-type-${role}`)));

  assert.match(typography, /동일한 위계는 영어와 한국어에서 모두 읽기 쉬워야 합니다/);
  assert.match(typography, /database\.enable-point-in-time-recovery\.for-example-workload/);
  assert.doesNotMatch(typography, /style="[^"]*font-size/);
});

test("component gallery exposes a quiet category index", () => {
  assert.match(components, /<body class="cs-components-page">/);
  assert.equal((components.match(/class="cs-gallery-index"/g) || []).length, 1);
  ["display", "controls", "navigation", "feedback", "data-views", "advanced", "typography"]
    .forEach((id) => assert.match(components, new RegExp(`id="${id}"`)));
  Object.entries({
    display: "KPI cards",
    controls: "Buttons &amp; forms",
    navigation: "Navigation &amp; filters",
    feedback: "Feedback &amp; overlays",
    "data-views": "Charts &amp; structured summaries",
    advanced: "Select menus &amp; combobox",
    typography: "Typography &amp; content hierarchy",
  }).forEach(([id, heading]) => {
    const start = components.indexOf(`<section class="cs-section" id="${id}"`);
    const end = components.indexOf("</section>", start);
    const section = components.slice(start, end);
    const headingStart = section.indexOf("<h2");
    const headingTextStart = section.indexOf(">", headingStart) + 1;
    const headingEnd = section.indexOf("</h2>", headingTextStart);
    assert.ok(start >= 0);
    assert.equal(section.slice(headingTextStart, headingEnd), heading);
  });
  assert.match(components, /<span class="cs-badge-num"[^>]*>01<\/span>/);
  assert.match(components, /<span class="cs-badge-num"[^>]*>23<\/span>/);
  assert.match(stylesheet, /\.cs-components-page \.cs-badge-num \{[^}]*background: transparent/);
  assert.match(stylesheet, /\.cs-gallery-toolbar \{[^}]*position: sticky/);
  assert.match(stylesheet, /\.cs-gallery-index a\[aria-current="location"\]/);
  assert.match(components, /data-cs-component-search/);
  assert.doesNotMatch(components, /href="#"/);
  assert.match(components, /function syncActiveCategory\(\)/);
});

test("component gallery keeps the remediated interaction and accessibility contracts", () => {
  assert.equal((components.match(/<section class="cs-section" id="[^"]+" aria-labelledby="[^"]+">/g) || []).length, 23);
  assert.doesNotMatch(components, /class="cs-alert-bar/);
  assert.ok((components.match(/<button\b[^>]*>/g) || []).every((button) => /\btype="button"/.test(button)));
  assert.ok((components.match(/<th\b[^>]*>/g) || []).every((heading) => /\bscope="col"/.test(heading)));
  assert.match(components, /data-cs-theme-toggle/);
  assert.match(components, /class="cs-gallery-synthetic">Synthetic samples/);
  assert.match(components, /class="cs-interaction-matrix"/);
  assert.match(components, /type: "fdai:mock-section"/);
  assert.match(stylesheet, /semantic-type-v2/);
  assert.match(stylesheet, /small, code, dt, dd, th, time, kbd, svg text/);
  assert.match(stylesheet, /\.cs-components-page \.cs-heading-link \{[^}]*width: 44px;[^}]*height: 44px/);
  assert.equal((components.match(/data-cs-chart-inspect/g) || []).length, 4);
  assert.match(navigation, /event\.target\.closest\("\[data-cs-chart-inspect\]"\)/);
  assert.match(navigation, /var chartMarks = "\[data-chart-mark\], \.cs-heatmap-cell\[title\]"/);
  assert.match(navigation, /document\.querySelectorAll\(chartMarks\)/);
  assert.match(navigation, /showChartMarkTooltip\(mark, label\)/);
  assert.match(navigation, /mark\.classList\.contains\("cs-family-series-slice"\).*mark\.classList\.contains\("cs-composition-slice"\)/);
  assert.match(navigation, /classList\.toggle\("is-left", useLeft\)/);
  assert.match(navigation, /!fitsRight && !fitsLeft/);
  assert.match(navigation, /classList\.add\("is-clamped"\)/);
  assert.match(navigation, /document\.addEventListener\("focusin"/);
  assert.match(navigation, /lastTrigger = focusReturn \|\| trigger/);
  assert.match(stylesheet, /\.cs-chart-mark-tip \{[^}]*position: fixed/);
  assert.doesNotMatch(navigation, /querySelectorAll\("\.js-chartable"\)/);
});

test("component gallery exposes a bounded Resource autocomplete specimen", () => {
  const start = components.indexOf('id="resource-autocomplete"');
  const end = components.indexOf('class="cs-combobox-empty"', start);
  const specimen = components.slice(start, end);

  assert.ok(start >= 0);
  assert.match(components, /data-cs-combobox-limit="10"/);
  assert.equal((specimen.match(/class="cs-combobox-option"/g) || []).length, 10);
  assert.equal((specimen.match(/class="cs-combobox-option"[^>]*hidden/g) || []).length, 0);
  assert.match(components, /Shows at most ten matches/);
  assert.match(navigation, /visible >= limit/);
  assert.match(navigation, /aria-activedescendant/);
  assert.match(stylesheet, /\.cs-autocomplete-demo \.cs-combobox-list \{ max-height: 360px; \}/);
});

test("chart specimens retain their precision-first visual contracts", () => {
  const start = components.indexOf('<section class="cs-section" id="data-views"');
  const end = components.indexOf("</section>", start);
  const charts = components.slice(start, end);
  const catalogMatch = charts.match(/<script type="application\/json" id="tremor-chart-catalog">([\s\S]*?)<\/script>/);
  assert.ok(catalogMatch);
  const catalog = JSON.parse(catalogMatch[1]);

  assert.equal((charts.match(/class="cs-chart-card js-chartable"/g) || []).length, 4);
  assert.match(charts, /class="cs-chart-reference"/);
  assert.match(charts, /Peak 36/);
  assert.match(charts, /Median 27/);
  assert.match(charts, /class="cs-chart-distribution-bar"/);
  assert.doesNotMatch(charts, /cs-chart-donut/);
  assert.match(charts, /data-chart-num-cols="\[1,2,3,4,5,6,7\]"/);
  assert.match(charts, /class="cs-heatmap-cell is-4 is-peak"/);
  assert.match(stylesheet, /\.cs-chart-bar-baseline \{[^}]*left: var\(--baseline\)/);
  assert.match(stylesheet, /\.cs-heatmap-cell\.is-peak/);
  ["#3b82f6", "#10b981", "#8b5cf6", "#f59e0b", "#6b7280", "#06b6d4", "#ec4899", "#84cc16", "#d946ef"]
    .forEach((hex) => assert.match(stylesheet, new RegExp(hex)));
  assert.match(stylesheet, /\[data-chart-mark\]:focus-visible/);
  assert.equal((charts.match(/class="cs-chart-foot"/g) || []).length, 4);
  assert.equal((charts.match(/class="cs-chart-family-card"/g) || []).length, 6);
  assert.equal((charts.match(/class="cs-chart-composition-card/g) || []).length, 7);
  assert.equal(catalog.length, 33);
  assert.equal(new Set(catalog.map((entry) => entry.name)).size, 33);
  assert.equal(catalog[0].name, "Area Chart");
  assert.equal(catalog.at(-1).name, "Bar List");
  assert.match(charts, /data-cs-tremor-catalog/);
  assert.match(navigation, /function renderTremorCatalog\(\)/);
  assert.match(navigation, /function catalogVisual\(entry\)/);
  assert.match(stylesheet, /\.cs-chart-catalog-grid/);
  assert.match(stylesheet, /\.cs-catalog-visual svg \.is-line\.is-blue/);
  [
    "Portfolio value", "Evidence volume", "Today's queries", "Total expenses by category",
    "Training load", "Log monitoring", "Uptime summary",
  ].forEach((label) => assert.match(charts, new RegExp(label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))));
  assert.match(charts, /\$328,505\.10/);
  assert.match(charts, /Sep 10\. ETF Shares Vital: \$7,649\. Vitainvest Core: \$10,139\.2\. iShares Tech Growth: \$11,143\.8/);
  assert.match(stylesheet, /\.cs-chart-composition-card\.is-wide/);
  assert.match(stylesheet, /\.cs-composition-slice:hover::before/);
  assert.match(stylesheet, /svg \.is-area\.is-blue \{ fill: var\(--tremor-blue\)/);
  assert.doesNotMatch(stylesheet, /\.cs-chart-composition-card svg \.is-blue \{ fill:/);
  assert.equal((charts.match(/class="cs-family-series-slice"/g) || []).length, 7);
  assert.ok((charts.match(/data-chart-mark/g) || []).length >= 44);
  assert.match(charts, /Thursday\. Observed: 31\. Baseline: 22\. Forecast: 25/);
  assert.match(stylesheet, /\.cs-family-series-slice:hover::before/);
  assert.match(stylesheet, /\.cs-chart-mark-tip\.is-side\.is-left/);
  assert.match(stylesheet, /\.cs-chart-mark-tip\.is-side\.is-clamped/);
  ["Area &amp; line", "Bar &amp; combo", "Donut &amp; pie", "Spark charts", "Progress", "Tracker &amp; scatter"]
    .forEach((label) => assert.match(charts, new RegExp(label)));
});

test("both mock shells preserve exact component section routes", () => {
  [landing, masterLanding].forEach((shell) => {
    assert.match(shell, /type !== ['"]fdai:mock-section['"]/);
    assert.match(shell, /aria-current/);
    assert.match(shell, /::/);
  });
  assert.match(masterLanding, /class="skip-link" href="#preview"/);
  assert.match(masterLanding, /data-nav-toggle/);
});
