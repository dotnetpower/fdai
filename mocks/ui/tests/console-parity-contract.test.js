const assert = require("node:assert/strict");
const { existsSync, readFileSync, readdirSync } = require("node:fs");
const { basename, join } = require("node:path");
const test = require("node:test");

const repoRoot = join(__dirname, "..", "..", "..");
const uiRoot = join(repoRoot, "mocks", "ui");
const panelRegistry = readFileSync(join(repoRoot, "console", "src", "panels.tsx"), "utf8");
const masterLanding = readFileSync(join(repoRoot, "index.html"), "utf8");
const nestedLanding = readFileSync(join(uiRoot, "index.html"), "utf8");
const navigation = readFileSync(join(uiRoot, "assets", "calm-slate.js"), "utf8");
const parityScript = readFileSync(join(uiRoot, "assets", "console-parity.js"), "utf8");
const parityStyles = readFileSync(join(uiRoot, "assets", "console-parity.css"), "utf8");
const sharedStyles = readFileSync(join(uiRoot, "assets", "calm-slate.css"), "utf8");
const knowledgeGraph = readFileSync(join(uiRoot, "ontology-knowledge-graph.html"), "utf8");
const settingsMocks = [
  "settings.html",
  "settings-models.html",
  "settings-runtime.html",
  "settings-memory.html",
  "settings-iam.html",
  "settings-integrations.html",
  "settings-diagnostics.html",
];

const consoleNav = masterLanding.slice(
  masterLanding.indexOf('<nav class="console-groups"'),
  masterLanding.indexOf("</nav>", masterLanding.indexOf('<nav class="console-groups"')),
);
const consoleMockPaths = Array.from(
  consoleNav.matchAll(/data-page="(mocks\/ui\/[^"]+\.html)"/g),
  (match) => match[1],
);

const filenameAliases = {
  "agents-constellation": "pantheon",
  "hil": "hil-queue",
  "promotion": "promotion-gates",
  "rule-trace": "trace",
  "settings": "settings-general",
};

function consolePanelIds() {
  const core = panelRegistry.slice(
    panelRegistry.indexOf("export const CORE_PANELS"),
    panelRegistry.indexOf("export const EXTRA_PANELS"),
  );
  const ids = Array.from(core.matchAll(/\bid: "([a-z0-9-]+)"/g), (match) => match[1]);
  ids.push("dashboard");
  return ids.sort();
}

function mockPanelIds() {
  return consoleMockPaths.map((path) => {
    const file = basename(path, ".html");
    return filenameAliases[file] || file;
  }).sort();
}

test("master mock navigation mirrors every production Console panel", () => {
  assert.equal(consoleMockPaths.length, 51);
  assert.equal(new Set(consoleMockPaths).size, 51);
  assert.deepEqual(mockPanelIds(), consolePanelIds());
  consoleMockPaths.forEach((path) => {
    assert.ok(existsSync(join(repoRoot, path)), `missing Console mock: ${path}`);
  });
});

test("master navigation exposes every local design mock without duplicate destinations", () => {
  const masterMarkup = masterLanding.slice(0, masterLanding.indexOf("<script>"));
  const paths = Array.from(masterMarkup.matchAll(/data-page="([^"]+)"/g), (match) => match[1]);
  assert.equal(paths.length, 91);
  assert.equal(new Set(paths).size, 91);
  paths.forEach((path) => {
    assert.ok(existsSync(join(repoRoot, path)), `missing design mock: ${path}`);
  });
});

test("nested and direct mock navigation expose the same Console destinations", () => {
  const nestedPaths = Array.from(nestedLanding.matchAll(/data-page="([^"]+\.html)"/g), (match) => match[1]);
  const directNavigationBlock = navigation.slice(
    navigation.indexOf("var navigationGroups ="),
    navigation.indexOf("function currentNavigationContext"),
  );
  const directPaths = Array.from(directNavigationBlock.matchAll(/\["([^"]+\.html)",/g), (match) => match[1]);
  const expected = consoleMockPaths.map((path) => path.replace("mocks/ui/", ""));

  expected.forEach((path) => {
    assert.ok(nestedPaths.includes(path), `nested index missing ${path}`);
    assert.ok(directPaths.includes(path), `direct mock navigation missing ${path}`);
  });
  assert.equal(new Set(directPaths).size, 72);
});

test("every parity wrapper resolves to a rendered specification", () => {
  const wrappers = readdirSync(uiRoot)
    .filter((file) => file.endsWith(".html"))
    .map((file) => [file, readFileSync(join(uiRoot, file), "utf8")])
    .filter(([, html]) => html.includes("data-console-parity-page"));

  assert.equal(wrappers.length, 23);
  wrappers.forEach(([file, html]) => {
    const pageId = html.match(/data-console-page="([^"]+)"/)?.[1];
    assert.ok(pageId, `${file} is missing a Console page id`);
    assert.match(parityScript, new RegExp(`"${pageId.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}": \\{`));
    assert.match(html, /assets\/console-parity\.css/);
    assert.match(html, /assets\/console-parity\.js/);
    assert.match(html, /assets\/calm-slate\.css/);
    assert.match(html, /assets\/calm-slate\.js/);
  });
});

test("twenty shared polish passes cover every Calm Slate mock", () => {
  const passes = Array.from(sharedStyles.matchAll(/\/\* (\d{2})\./g), (match) => match[1]);
  assert.deepEqual(passes.slice(-20), Array.from({ length: 20 }, (_, index) => String(index + 1).padStart(2, "0")));
  assert.match(sharedStyles, /prefers-reduced-motion: reduce/);
  assert.match(sharedStyles, /:focus-visible/);
  assert.match(sharedStyles, /@media print/);
  assert.match(parityStyles, /@media \(max-width: 520px\)/);
  assert.match(parityStyles, /\.cp-table td::before/);
});

test("master navigation can filter all mock families without losing the active route", () => {
  assert.match(masterLanding, /data-nav-search/);
  assert.match(masterLanding, /function filterNavigation\(query\)/);
  assert.match(masterLanding, /if \(!normalized\) revealPageGroup\(currentPage\)/);
  assert.match(masterLanding, /Filter 91 design mocks/);
});

test("knowledge graph renders every generated ontology node kind", () => {
  assert.match(knowledgeGraph, /function_type:\{label:"FunctionType",fill:/);
  assert.match(knowledgeGraph, /interface_type:\{label:"InterfaceType",fill:/);
  assert.match(knowledgeGraph, /nodeStyles\[node\.kind\]\|\|\{fill:"#6e747b"\}/);
});

test("every settings mock uses the production-aligned route surface", () => {
  settingsMocks.forEach((file) => {
    const html = readFileSync(join(uiRoot, file), "utf8");
    assert.match(html, /calm-slate\.css\?v=settings-route-v5/);
    assert.match(html, /calm-slate\.js\?v=settings-route-v5/);
    assert.doesNotMatch(html, /class="cs-btn/);
    if (/<(?:input|select|textarea)\b/.test(html)) {
      assert.match(html, /class="[^"]*cs-control-(?:input|select|textarea)/);
    }
  });
  assert.match(navigation, /var settingsPages = \[/);
  const settingsPagesBlock = navigation.slice(
    navigation.indexOf("var settingsPages ="),
    navigation.indexOf("function createSettingsSurface"),
  );
  assert.equal((settingsPagesBlock.match(/"settings(?:-[a-z]+)*\.html"/g) || []).length, 7);
  assert.match(navigation, /function createSettingsSurface\(\)/);
  assert.doesNotMatch(navigation, /function createSettingsWorkspace\(\)/);
  assert.doesNotMatch(sharedStyles, /\.cs-settings-workspace \{/);
  assert.match(sharedStyles, /\.cs-settings-surface \.cs-settings-content \{[\s\S]*max-width: 1080px/);
  assert.match(sharedStyles, /\.cs-settings-content > \.cs-settings-section:first-of-type/);
  assert.match(sharedStyles, /\.cs-settings-surface \.cs-settings-list \{\s*border-bottom: 0;/);
  assert.match(sharedStyles, /\.cs-settings-card-grid \{/);
  assert.match(sharedStyles, /@container \(max-width: 760px\) \{[\s\S]*\.cs-settings-surface \.cp-table td::before/);
  assert.match(sharedStyles, /\.cs-settings-surface \.cs-settings-content :where\([\s\S]*min-height: 44px/);
});
