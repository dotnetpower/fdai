/** Explicit Resource preview state and keyboard continuity; only the committed mock origin is allowed. */
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const require = createRequire(join(root, "console/package.json"));
const { chromium } = require("playwright");
const origin = "http://127.0.0.1:5373";
const resourcePage = "mocks/ui/dashboard-v2.html";

async function openResource(t) {
  const browser = await chromium.launch({ headless: true });
  const errors = [];
  t.after(async () => {
    try { assert.deepEqual(errors, []); }
    finally { await browser.close(); }
  });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 }, reducedMotion: "reduce",
  });
  await context.route("**/*", route => new URL(route.request().url()).origin === origin
    ? route.continue() : route.abort("blockedbyclient"));
  await context.addInitScript(() => {
    const focus = HTMLElement.prototype.focus;
    window.previewFocusCalls = [];
    HTMLElement.prototype.focus = function (...args) {
      window.previewFocusCalls.push({ id: this.id, tag: this.tagName });
      return focus.apply(this, args);
    };
  });
  const page = await context.newPage();
  page.setDefaultTimeout(6000);
  page.on("pageerror", error => errors.push(error.message));
  await page.goto(`${origin}/#${resourcePage}`);
  const frame = await (await page.locator("#preview-frame").elementHandle()).contentFrame();
  await frame.waitForLoadState("load");
  await frame.waitForFunction(() => document.getElementById("resource-main")?.fdaiPreviewState);
  return { page, frame };
}

async function viewState(frame) {
  return frame.evaluate(() => document.getElementById("resource-main").fdaiPreviewState.capture());
}

async function resourceFrame(page) {
  const frame = await (await page.locator("#preview-frame").elementHandle()).contentFrame();
  await frame.waitForLoadState("load");
  return frame;
}

async function savedState(page, expected) {
  await page.waitForFunction(value => JSON.stringify(history.state?.fdaiMockView?.pageState) === value,
    JSON.stringify(expected));
}

async function returnFromOntology(page, frame, expected, preserveFocus = false) {
  const link = frame.locator("#resource-ontology-link");
  if (preserveFocus) await link.evaluate(node => node.click());
  else { await link.focus(); await link.press("Enter"); }
  await frame.waitForFunction(() => location.pathname.endsWith("/ontology-instances-2d.html"));
  assert.equal(new URL(frame.url()).searchParams.get("instance"), expected.selected);
  await page.goBack();
  await frame.waitForFunction(value => {
    const adapter = document.getElementById("resource-main")?.fdaiPreviewState;
    return adapter && JSON.stringify(adapter.capture()) === value;
  }, JSON.stringify(expected));
  await frame.evaluate(() => new Promise(resolve => requestAnimationFrame(resolve)));
  const evidence = await frame.locator("#resource-selected-evidence").textContent();
  assert.equal(JSON.parse(evidence).resource, expected.selected);
  assert.equal(JSON.parse(evidence).execution_authority, false);
  assert.ok(Object.hasOwn(JSON.parse(evidence), "presented_provisioning"));
  assert.equal(await frame.locator("[data-provisioning-fact]").count(), 1);
  assert.ok((await link.getAttribute("href")).endsWith(encodeURIComponent(expected.selected)));
  assert.equal(await frame.locator("#resource-inspector-jump").isVisible(), true);
  if (!preserveFocus) assert.equal(await link.evaluate(node => document.activeElement === node), true);
}

test("Resource scope, scenario, lens, pagination and pinned identity survive ontology back", { timeout: 45000 }, async t => {
  const { page, frame } = await openResource(t);
  await page.evaluate(() => history.replaceState({ ...history.state, unrelated: "preserve-me" }, "", location.href));
  await frame.locator("#resource-example-controls > summary").click();
  await frame.locator("#resource-example-size").selectOption("10000");
  await frame.locator("#resource-example-state").selectOption("partial");
  await frame.locator("#resource-example-state").press("Escape");
  await frame.locator("#resource-cell-app-vm-02").click();
  await frame.locator('[data-resource-lens="observation"]').click();
  await frame.locator('[data-resource-view="list"]').click();
  await frame.locator("#resource-subscription").selectOption("subscription-2");
  await frame.locator("#resource-type").click();
  await frame.locator("#resource-type").fill("Virtual machine");
  await frame.locator("#resource-type-option-vm").click();
  await frame.locator("#resource-search").fill("vm");
  await frame.locator('[data-state-key="ready"]').click();
  await frame.locator("#resource-next").click();
  await frame.locator("#resource-evidence > summary").click();
  const expected = await viewState(frame);
  assert.deepEqual({
    size: expected.size, scenario: expected.scenario, selected: expected.selected,
    subscription: expected.subscription, type: expected.type, query: expected.query,
    lens: expected.lens, view: expected.view, density: expected.density, status: expected.status, page: expected.page,
  }, {
    size: 10000, scenario: "partial", selected: "app-vm-02",
    subscription: "subscription-2", type: "vm", query: "vm",
    lens: "observation", view: "list", density: "dense", status: "ready", page: 1,
  });
  assert.equal(await frame.locator("#resource-selection-filtered").isVisible(), true);
  await returnFromOntology(page, frame, expected);
  assert.equal(await frame.locator("#resource-evidence").evaluate(node => node.open), true);
  assert.equal(await page.evaluate(() => history.state.unrelated), "preserve-me");
  assert.equal(await frame.locator("#resource-type").inputValue(), "Virtual machine");
  assert.match(await frame.locator("#resource-page-label").textContent(), /Page 2/);
  assert.equal(new URL(page.url()).hash, "#" + resourcePage);

  await frame.locator("#resource-group").selectOption("platform-11");
  await frame.locator('[data-resource-view="groups"]').click();
  const grouped = await viewState(frame);
  assert.equal(grouped.group, "platform-11");
  await returnFromOntology(page, frame, grouped);
  assert.equal(await frame.locator("#resource-group").inputValue(), "platform-11");
  assert.equal(await frame.locator('[data-resource-view="groups"]').getAttribute("aria-pressed"), "true");
});

test("Summary Inspect filters restore synchronously and clear on reset, lens and fixture reload", { timeout: 40000 }, async t => {
  const { page, frame } = await openResource(t);
  const labels = await frame.locator(".rd-summary-action").evaluateAll(nodes => nodes.map(node => ({
    id: node.id, name: node.getAttribute("aria-label"), shared: node.matches(".cs-control-button.is-quiet"),
  })));
  assert.equal(new Set(labels.map(item => item.id)).size, 4);
  assert.equal(new Set(labels.map(item => item.name)).size, 4);
  assert.ok(labels.every(item => item.shared && item.name.startsWith("Inspect ")));
  for (const kind of ["known", "provisioning"]) {
    await frame.locator("#resource-inspect-" + kind).click();
    await frame.locator("#resource-list-app-web-01").click();
    const expected = await viewState(frame);
    assert.equal(expected.summaryFilter, kind);
    await returnFromOntology(page, frame, expected);
    assert.match(await frame.locator("#resource-count").textContent(), new RegExp(kind + " evidence filter"));
    await frame.locator("#resource-reset").click();
    assert.equal((await viewState(frame)).summaryFilter, null);
    assert.equal((await viewState(frame)).selected, "app-web-01");
  }
  await frame.locator("#resource-inspect-known").click();
  await frame.locator('[data-resource-lens="availability"]').click();
  assert.equal((await viewState(frame)).summaryFilter, null);
  await frame.locator("#resource-inspect-provisioning").click();
  await frame.locator("#resource-example-controls > summary").click();
  await frame.locator("#resource-refresh").click();
  const refreshed = await viewState(frame);
  assert.equal(refreshed.summaryFilter, null);
  assert.equal(refreshed.selected, null);
  assert.equal(refreshed.lens, "operation");
  assert.equal(await frame.locator("#resource-inspector-jump").isVisible(), false);
});

test("Stable IDs restore keyboard focus beyond legacy index limits and on a search control", { timeout: 40000 }, async t => {
  const { page, frame } = await openResource(t);
  await frame.locator("#resource-example-controls > summary").click();
  await frame.locator("#resource-example-size").selectOption("10000");
  await frame.locator("#resource-example-size").press("Escape");
  const first = frame.locator(".dr-cell").first();
  await first.focus();
  await first.press("End");
  const focused = await frame.evaluate(() => ({
    id: document.activeElement.id,
    index: [...document.getElementById("resource-main").querySelectorAll("a[href],button,summary")]
      .indexOf(document.activeElement),
  }));
  assert.ok(focused.index >= 256, JSON.stringify(focused));
  await frame.locator("#" + focused.id).press("Enter");
  await returnFromOntology(page, frame, await viewState(frame), true);
  assert.equal(await frame.evaluate(() => document.activeElement.id), focused.id);
  assert.equal(await page.evaluate(() => history.state.fdaiMockView.focus.id), focused.id);
  assert.equal(await frame.locator(".dr-cell[tabindex='0']").count(), 1);

  await frame.locator("#resource-next").click();
  const paged = await viewState(frame);
  assert.equal(paged.page, 1);
  assert.equal(await frame.locator("#resource-selection-paged").isVisible(), true);
  await returnFromOntology(page, frame, paged);
  assert.equal(await frame.locator("#resource-selection-paged").isVisible(), true);

  await frame.locator("#resource-search").fill("no-matching-example");
  await returnFromOntology(page, frame, await viewState(frame), true);
  assert.equal(await frame.evaluate(() => document.activeElement.id), "resource-search");
  assert.equal(await frame.locator("#resource-search").inputValue(), "no-matching-example");
  assert.equal(await frame.locator("#resource-selection-filtered").isVisible(), true);
});

test("Fresh entries are isolated and every scenario reload restores without script autofocus", { timeout: 60000 }, async t => {
  const { page, frame: initialFrame } = await openResource(t);
  let frame = initialFrame;
  const defaults = await viewState(frame);
  await frame.locator("#resource-cell-app-web-01").click();
  await frame.locator("#resource-search").fill("web");
  await savedState(page, await viewState(frame));
  await page.reload();
  frame = await resourceFrame(page);
  await frame.waitForFunction(() => document.getElementById("resource-main")?.fdaiPreviewState?.capture().selected === "app-web-01");
  await frame.evaluate(() => new Promise(resolve => requestAnimationFrame(resolve)));
  assert.deepEqual(await frame.evaluate(() => window.previewFocusCalls), []);
  await frame.locator("#resource-ontology-link").click();
  await frame.waitForFunction(() => location.pathname.endsWith("/ontology-instances-2d.html"));
  await page.locator('.rail-button[data-nav-target="overview"]').click();
  await page.locator(`.side a[data-page="${resourcePage}"]`).click();
  await frame.waitForFunction(() => document.getElementById("resource-main")?.fdaiPreviewState?.capture().selected === null);
  assert.deepEqual(await viewState(frame), defaults);
  assert.equal(await frame.locator("#resource-evidence").evaluate(node => node.open), false);

  for (const scenario of ["complete", "partial", "stale", "loading", "error", "empty"]) {
    const examples = frame.locator("#resource-example-controls");
    if (!await examples.evaluate(node => node.open)) await examples.locator("summary").click();
    await frame.locator("#resource-example-size").selectOption("100");
    await frame.locator("#resource-example-state").selectOption(scenario);
    const expected = await viewState(frame);
    await savedState(page, expected);
    await page.reload();
    frame = await resourceFrame(page);
    await frame.waitForFunction(value => {
      const adapter = document.getElementById("resource-main")?.fdaiPreviewState;
      return adapter && JSON.stringify(adapter.capture()) === value;
    }, JSON.stringify(expected));
    await frame.evaluate(() => new Promise(resolve => requestAnimationFrame(resolve)));
    assert.deepEqual(await frame.evaluate(() => window.previewFocusCalls), [], scenario);
    assert.equal(await frame.locator("#resource-example-controls").evaluate(node => node.open), true);
    assert.equal(await frame.evaluate(() => document.activeElement.id === "resource-main"), false);
    assert.equal(await frame.locator("#resource-data").isVisible(), !["loading", "error"].includes(scenario));
  }
});

test("Resource history rejects incompatible bounded payloads without scraping other inputs", { timeout: 40000 }, async t => {
  const { page, frame: initialFrame } = await openResource(t);
  let frame = initialFrame;
  const warnings = [];
  page.on("console", message => { if (message.type() === "warning") warnings.push(message.text()); });
  const rejected = await frame.evaluate(() => {
    const adapter = document.getElementById("resource-main").fdaiPreviewState;
    const before = adapter.capture();
    const generation = window.FdaiDashboardV2Snapshot;
    const patches = [
      { version: 2 }, { size: 25 }, { scenario: "live" }, { lens: "__proto__" },
      { view: "other" }, { density: "other" }, { type: "other" }, { subscription: "missing" },
      { group: "missing" }, { size: 10000, subscription: "subscription-2", group: "application" },
      { status: "succeeded" }, { status: ["running"] }, { selected: "resource-10001", size: 100 },
      { query: "x".repeat(201) }, { page: -1 }, { page: 10000 }, { summaryFilter: "other" },
      { unexpected: "not-allowed" },
    ];
    return patches.map(patch => ({
      accepted: adapter.restore({ ...before, ...patch }),
      unchanged: JSON.stringify(adapter.capture()) === JSON.stringify(before) &&
        generation === window.FdaiDashboardV2Snapshot,
    }));
  });
  assert.ok(rejected.every(item => !item.accepted && item.unchanged), JSON.stringify(rejected));
  assert.equal(warnings.filter(text => text === "Ignoring incompatible resource preview state.").length, rejected.length);
  await frame.evaluate(() => {
    const input = document.createElement("input");
    input.id = "unowned-input";
    input.type = "password";
    Object.defineProperty(input, "value", { get() { throw new Error("Unowned value was read"); } });
    document.getElementById("resource-main").appendChild(input);
  });
  await frame.locator("#resource-search").fill("x".repeat(200));
  await savedState(page, await viewState(frame));
  const saved = await page.evaluate(() => history.state.fdaiMockView.pageState);
  assert.equal(saved.query.length, 200);
  assert.ok(Buffer.byteLength(JSON.stringify(saved)) <= 2048);
  assert.deepEqual(Object.keys(saved).sort(), [
    "density", "group", "lens", "page", "query", "scenario", "selected",
    "size", "status", "subscription", "summaryFilter", "type", "version", "view",
  ]);
  for (const kind of ["oversized", "cyclic"]) {
    await page.evaluate(kind => {
      const state = history.state;
      const value = kind === "oversized" ? { query: "x".repeat(2049) } : {};
      if (kind === "cyclic") value.self = value;
      history.replaceState({ ...state, unrelated: "preserve-me",
        fdaiMockView: { ...state.fdaiMockView, pageState: value } }, "", location.href);
    }, kind);
    await page.reload();
    frame = await resourceFrame(page);
    await frame.waitForFunction(() => document.getElementById("resource-main")?.fdaiPreviewState?.capture().query === "");
    assert.equal(await page.evaluate(() => history.state.unrelated), "preserve-me");
    assert.equal((await viewState(frame)).size, 24);
  }
  assert.ok(warnings.includes("Ignoring incompatible preview presentation state."));
});

test("Example controls dismiss on Escape and outside pointer without stealing outside focus", { timeout: 20000 }, async t => {
  const { frame } = await openResource(t);
  const summary = frame.locator("#resource-example-controls > summary");
  await summary.focus();
  await summary.press("Enter");
  await frame.locator("#resource-example-size").focus();
  await frame.locator("#resource-example-size").press("Escape");
  assert.equal(await frame.locator("#resource-example-controls").evaluate(node => node.open), false);
  assert.equal(await summary.evaluate(node => document.activeElement === node), true);
  await summary.press("Enter");
  await frame.locator("#resource-search").click();
  assert.equal(await frame.locator("#resource-example-controls").evaluate(node => node.open), false);
  assert.equal(await frame.evaluate(() => document.activeElement.id), "resource-search");
});
