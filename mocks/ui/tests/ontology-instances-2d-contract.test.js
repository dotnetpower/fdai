const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const test = require("node:test");

const uiRoot = join(__dirname, "..");
const html = readFileSync(join(uiRoot, "ontology-instances-2d.html"), "utf8");
const nestedIndex = readFileSync(join(uiRoot, "index.html"), "utf8");
const rootIndex = readFileSync(join(uiRoot, "..", "..", "index.html"), "utf8");

test("instance mock is a flat rectangular operational graph", () => {
  assert.match(html, /flat and two-dimensional/);
  assert.match(html, /nodeWidth = 176, nodeHeight = 68/);
  assert.match(html, /class:\"oi-node /);
  assert.match(html, /12 synthetic Resources/);
  assert.match(html, /14 relationships/);
  assert.doesNotMatch(html, /architecture-map|isometric-camera|webgl/i);
});

test("instance mock uses Azure icons without colored edge accents", () => {
  ["container-apps.svg", "event-hubs.svg", "postgresql.svg", "storage-account.svg", "virtual-network.svg", "private-endpoint.svg", "key-vault.svg", "container-registry.svg", "monitor.svg"].forEach((icon) => {
    assert.match(html, new RegExp(icon.replace(".", "\\.")));
  });
  assert.match(html, /tools\/architecture-diagrams\/assets\/azure/);
  assert.doesNotMatch(html, /oi-kind|grid-template-columns:8px minmax/);
  assert.doesNotMatch(html, /border-left:[2-9]px/);
});

test("instance mock links every Resource to a state and event timeline", () => {
  assert.match(html, /id="oi-timeline"/);
  assert.match(html, /id="oi-timeline-detail"/);
  assert.match(html, /State and event history/);
  assert.match(html, /function renderTimeline\(\)/);
  assert.match(html, /function segmentLabel\(value,width\)/);
  assert.match(html, /class=\"oi-state-segment/);
  assert.match(html, /class=\"oi-event-marker/);
  assert.match(html, /button\.onmouseenter=show/);
  assert.match(html, /button\.onfocus=show/);
  assert.equal((html.match(/^        "[a-z-]+":\[/gm) || []).length, 12);
});

test("instance mock exposes bounded navigation and evidence views", () => {
  ["overview", "relations", "events", "sources"].forEach((panel) => {
    assert.match(html, new RegExp(`data-panel=\\"${panel}\\"`));
  });
  assert.match(html, /id="oi-search"/);
  assert.match(html, /id="oi-select"/);
  assert.match(html, /id="oi-show-all"/);
  assert.match(html, /id="oi-focus"/);
  assert.match(html, /depth 1 &middot; bidirectional &middot; no mutation authority/);
});

test("instance mock is registered in both mock indexes", () => {
  assert.match(nestedIndex, /data-page="ontology-instances-2d\.html"/);
  assert.match(rootIndex, /data-page="mocks\/ui\/ontology-instances-2d\.html"/);
  assert.match(rootIndex, /Console navigation<\/h3><span class="count">51 pages<\/span>/);
  assert.match(rootIndex, /Governance<\/span><span class="count">11<\/span>/);
  assert.match(rootIndex, /Design studies<\/span><span class="count">22 pages<\/span>/);
});

test("instance mock keeps synthetic data customer-agnostic", () => {
  assert.doesNotMatch(html, /ca-fdai|rg-fdai|MngEnv|onmicrosoft/i);
  assert.doesNotMatch(html, /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i);
});

test("instance mock uses unique element ids", () => {
  const ids = Array.from(html.matchAll(/\sid="([^"]+)"/g), (match) => match[1]);
  const duplicates = ids.filter((id, index) => ids.indexOf(id) !== index);
  assert.deepEqual(Array.from(new Set(duplicates)), []);
});
