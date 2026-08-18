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
  assert.match(masterLanding, /<h3>Console navigation<\/h3><span class="count">42 pages<\/span>/);
  assert.match(masterLanding, /<span class="nav-group-label">Labs<\/span><span class="count">10<\/span>/);
});

test("master navigation keeps one quiet, collapsible hierarchy", () => {
  assert.match(masterLanding, /--nav-w: 248px/);
  assert.match(masterLanding, /src="console\/public\/brand\/fdai-logo\.png"/);
  assert.equal((masterLanding.match(/<button class="nav-group-head"/g) || []).length, 8);
  assert.equal((masterLanding.match(/<button class="fam is-/g) || []).length, 4);
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
