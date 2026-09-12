/** Resource mock presentation, state honesty and accessible bounded interaction checks. */
import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const require = createRequire(join(root, "console/package.json"));
const { chromium } = require("playwright");
const origin = "http://127.0.0.1:5373";

test("Resource workspace keeps scope, maps, filters and evidence coherent across supported states", {
  timeout: 120000,
}, async () => {
  const browser = await chromium.launch({ headless: true });
  const output = join(root, ".fdai/visual-review/resource-workspace-checks");
  const stages = [];
  let completed = false;
  await mkdir(output, { recursive: true });
  try {
    const context = await browser.newContext({
      viewport: { width: 1440, height: 900 }, reducedMotion: "reduce",
    });
    await context.route("**/*", route => new URL(route.request().url()).origin === origin
      ? route.continue() : route.abort("blockedbyclient"));
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    page.setDefaultTimeout(8000);
    await page.goto(`${origin}/#mocks/ui/dashboard-v2.html`);
    const frame = await (await page.locator("#preview-frame").elementHandle()).contentFrame();
    await frame.waitForLoadState("load");
    await frame.waitForFunction(() => window.FdaiDashboardV2Snapshot?.resources.length === 24 &&
      document.querySelectorAll(".dr-cell").length === 24);

    const defaultState = await frame.evaluate(() => {
      const count = id => Number(document.getElementById(id).textContent);
      const lastCell = [...document.querySelectorAll(".dr-cell")].at(-1).getBoundingClientRect();
      return {
        received: count("count-resources"), known: count("count-known"), unknown: count("count-unknown"),
        notApplicable: count("count-na"), provisioning: count("count-provisioning"),
        rootFits: document.documentElement.scrollWidth <= document.documentElement.clientWidth,
        scopeUnboxed: getComputedStyle(document.querySelector(".rd-snapshot")).backgroundColor === "rgba(0, 0, 0, 0)",
        mapHeaderUnboxed: getComputedStyle(document.querySelector(".dr-resource-panel")).backgroundColor === "rgba(0, 0, 0, 0)",
        summaryCards: [...document.querySelectorAll(".dr-summary > div")]
          .every(el => getComputedStyle(el).backgroundColor === "rgb(255, 255, 255)"),
        allInitialCellsAboveFold: lastCell.bottom <= innerHeight,
        supplementaryClosed: !document.getElementById("resource-supplement").open,
        noTimedNotice: document.querySelectorAll(".de-toast").length === 0,
      };
    });
    assert.equal(defaultState.received, 24);
    assert.equal(defaultState.known + defaultState.unknown + defaultState.notApplicable, defaultState.received);
    assert.equal(defaultState.provisioning, 3);
    for (const key of ["rootFits", "scopeUnboxed", "mapHeaderUnboxed", "summaryCards", "allInitialCellsAboveFold", "supplementaryClosed", "noTimedNotice"]) {
      assert.equal(defaultState[key], true, JSON.stringify(defaultState));
    }
    stages.push({ name: "default-desktop", ...defaultState });
    await page.screenshot({ path: join(output, "desktop.png"), animations: "disabled" });

    const skip = frame.getByRole("link", { name: "Skip to resource dashboard" });
    await skip.focus();
    await skip.press("Enter");
    await frame.waitForFunction(() => document.activeElement.id === "resource-main");
    const cells = frame.locator(".dr-cell");
    await cells.first().focus();
    await frame.locator("#resource-hover-preview").waitFor({ state: "visible" });
    assert.equal(await frame.locator("#resource-hover-preview dt").count(), 4);
    assert.match(await frame.locator("#resource-hover-preview").textContent(), /Provisioning/);
    await cells.first().press("Escape");
    assert.equal(await frame.locator("#resource-hover-preview").isVisible(), false);
    await cells.first().press("ArrowRight");
    assert.equal(await cells.nth(1).evaluate(el => document.activeElement === el), true);
    await cells.nth(1).press("Enter");
    assert.equal(await frame.locator("#resource-inspector").isVisible(), true);
    assert.equal(await frame.locator("#resource-inspector-jump").isVisible(), true);
    await frame.locator("#resource-evidence > summary").click();
    const selectedEvidence = JSON.parse(await frame.locator("#resource-selected-evidence").textContent());
    assert.equal(selectedEvidence.synthetic, true);
    assert.equal(selectedEvidence.execution_authority, false);
    await page.screenshot({ path: join(output, "selected-resource.png"), animations: "disabled" });
    await frame.locator("#resource-search").fill("no-matching-example");
    assert.equal(await frame.locator("#resource-empty").isVisible(), true);
    assert.equal(await frame.locator("#resource-selection-filtered").isVisible(), true);
    assert.equal(JSON.parse(await frame.locator("#resource-selected-evidence").textContent()).resource, selectedEvidence.resource);
    await frame.locator("#resource-reset").click();
    await frame.locator("#resource-selection-clear").click();
    stages.push({ name: "keyboard-selection-and-filtered-identity", selected: selectedEvidence.resource });

    for (const view of ["groups", "honeycomb", "list"]) {
      await frame.locator(`[data-resource-view="${view}"]`).click();
      assert.equal(await frame.locator(`[data-resource-view="${view}"]`).getAttribute("aria-pressed"), "true");
    }
    for (const lens of ["operation", "provisioning", "availability", "observation"]) {
      await frame.locator(`[data-resource-lens="${lens}"]`).click();
      assert.equal(await frame.locator(`[data-resource-lens="${lens}"]`).getAttribute("aria-pressed"), "true");
      assert.equal(await frame.locator("#resource-lens-note").textContent().then(text => text.length > 0), true);
    }
    assert.equal(await frame.locator('[data-resource-lens][aria-pressed="true"]').evaluate(el =>
      getComputedStyle(el, "::after").borderBottomWidth), "2px");
    const typeInput = frame.locator("#resource-type");
    await typeInput.click();
    await typeInput.fill("zz-no-such-resource-type");
    assert.match(await frame.locator("#resource-type-results").textContent(), /No matching types/);
    await typeInput.press("Escape");
    assert.equal(await typeInput.getAttribute("aria-expanded"), "false");
    await typeInput.click();
    await typeInput.fill("가상");
    assert.ok(await frame.locator("#resource-type-options [role=option]").count() > 0);
    await typeInput.press("ArrowDown");
    await typeInput.press("Enter");
    assert.equal(await typeInput.getAttribute("aria-expanded"), "false");
    await frame.locator("#resource-reset").click();
    stages.push({ name: "view-lens-and-typeahead" });

    const example = frame.locator("#resource-example-controls");
    const exampleToggle = frame.locator("#resource-example-controls > summary");
    await exampleToggle.click();
    for (const mode of ["partial", "stale", "loading", "error", "empty", "complete"]) {
      await frame.locator("#resource-example-state").selectOption(mode);
      const result = await frame.evaluate(() => ({
        mode: window.FdaiDashboardV2Snapshot.mode,
        received: window.FdaiDashboardV2Snapshot.resources.length,
        known: Number(document.getElementById("count-known").textContent),
        unknown: Number(document.getElementById("count-unknown").textContent),
        na: Number(document.getElementById("count-na").textContent),
        dataHidden: document.getElementById("resource-data").hidden,
        readStateVisible: !document.getElementById("resource-read-state").hidden,
        status: document.getElementById("resource-snapshot-status").textContent,
      }));
      assert.equal(result.mode, mode);
      if (["loading", "error"].includes(mode)) {
        assert.equal(result.dataHidden, true);
        assert.equal(result.readStateVisible, true);
      } else {
        assert.equal(result.dataHidden, false);
        assert.equal(result.known + result.unknown + result.na, result.received);
      }
      if (mode === "partial") assert.equal(result.received, 18);
      if (mode === "stale") assert.equal(result.known, 0);
      if (mode === "empty") assert.equal(result.received, 0);
      stages.push({ name: "fixture-state", ...result });
    }
    for (const size of ["100", "1000", "10000"]) {
      await frame.locator("#resource-example-size").selectOption(size);
      const result = await frame.evaluate(() => ({
        received: window.FdaiDashboardV2Snapshot.resources.length,
        rendered: document.querySelectorAll(".dr-cell").length,
        limit: window.FdaiDashboardV2Query.limit,
      }));
      assert.equal(result.received, Number(size));
      assert.equal(await frame.locator("#count-resources").textContent(), Number(size).toLocaleString("en-US"));
      assert.ok(result.rendered > 0 && result.rendered <= result.limit && result.rendered <= 476);
      stages.push({ name: "bounded-size", ...result });
    }
    await frame.locator("#resource-example-size").selectOption("24");
    await frame.locator("#resource-refresh").click();
    assert.match(await frame.locator("#resource-refresh-status").textContent(), /No runtime request/);
    await frame.locator("#resource-refresh").press("Escape");
    assert.equal(await example.evaluate(el => el.open), false);
    assert.equal(await exampleToggle.evaluate(el => document.activeElement === el), true);
    await exampleToggle.click();
    await frame.locator("#resource-scope-name").click();
    assert.equal(await example.evaluate(el => el.open), false);
    await exampleToggle.click();
    await frame.locator("#resource-example-state").selectOption("error");
    await frame.locator("#resource-example-state").press("Escape");
    await frame.locator("#resource-example-restore").click();
    assert.equal(await frame.locator("#resource-data").isVisible(), true);
    assert.equal(await frame.locator("#resource-read-state").isVisible(), false);
    assert.equal(await frame.evaluate(() => document.activeElement.id), "resource-map-title");
    assert.match(await frame.locator("#resource-selection-status").textContent(), /No runtime request/);
    stages.push({ name: "example-control-dismissal-and-local-reload" });

    const navToggle = page.getByRole("button", { name: "Toggle design navigation", exact: true });
    await navToggle.click();
    for (const viewport of [{ width: 993, height: 641 }, { width: 390, height: 844 }, { width: 372, height: 824 }]) {
      await page.setViewportSize(viewport);
      const layout = await frame.evaluate(() => ({
        width: innerWidth,
        rootFits: document.documentElement.scrollWidth <= document.documentElement.clientWidth,
        effectiveDensity: document.querySelector('[data-resource-density][aria-pressed="true"]').dataset.resourceDensity,
        targets: [...document.querySelectorAll("main button,main select,main summary, .rd-page-actions > a")]
          .filter(el => el.checkVisibility() && !el.closest("[hidden]"))
          .map(el => ({ name: el.getAttribute("aria-label") || el.textContent.trim(), width: el.getBoundingClientRect().width, height: el.getBoundingClientRect().height })),
      }));
      assert.equal(layout.rootFits, true, JSON.stringify(layout));
      if (viewport.width <= 390) {
        assert.equal(layout.effectiveDensity, "comfortable");
        assert.deepEqual(layout.targets.filter(el => el.width < 44 || el.height < 44), []);
      }
      if (viewport.width === 390) {
        await frame.locator("#resource-main").evaluate(el => el.scrollIntoView({ block: "start", behavior: "instant" }));
        await page.screenshot({ path: join(output, "mobile.png"), animations: "disabled" });
      }
      await frame.locator("#resource-supplement > summary").click();
      assert.equal(await frame.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth), true);
      await frame.locator("#resource-supplement > summary").click();
      stages.push({ name: "responsive", ...layout });
    }
    await page.setViewportSize({ width: 1440, height: 900 });
    const originalFonts = await frame.locator("main,main *").evaluateAll(elements => {
      const styles = elements.map(el => el.style.cssText);
      const sizes = elements.map(el => parseFloat(getComputedStyle(el).fontSize));
      elements.forEach((el, index) => {
        if (!el.closest("svg")) el.style.setProperty("font-size", `${sizes[index] * 2}px`, "important");
      });
      return styles;
    });
    const enlarged = await frame.evaluate(() => ({
      rootFits: document.documentElement.scrollWidth <= document.documentElement.clientWidth,
      clippedControls: [...document.querySelectorAll("main button,main a,main p,main dd")]
        .filter(el => el.checkVisibility() && el.scrollWidth > el.clientWidth + 2)
        .map(el => el.id || el.className),
    }));
    assert.equal(enlarged.rootFits, true, JSON.stringify(enlarged));
    assert.deepEqual(enlarged.clippedControls, []);
    await frame.locator("main,main *").evaluateAll((elements, styles) => {
      elements.forEach((el, index) => { el.style.cssText = styles[index]; });
    }, originalFonts);
    stages.push({ name: "200-percent-text-resize", ...enlarged });
    await frame.addStyleTag({ content: "main * { line-height:1.5!important;letter-spacing:.12em!important;word-spacing:.16em!important } main p {margin-bottom:2em!important}" });
    assert.equal(await frame.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth), true);
    await page.emulateMedia({ forcedColors: "active", reducedMotion: "reduce" });
    await frame.locator('[data-resource-view="honeycomb"]').focus();
    await frame.locator('[data-resource-view="honeycomb"]').press("Tab");
    await page.keyboard.press("Shift+Tab");
    assert.equal(await frame.locator('[data-resource-view="honeycomb"]').evaluate(el => getComputedStyle(el).outlineStyle), "solid");
    stages.push({ name: "text-spacing-forced-colors-and-keyboard-focus" });
    assert.deepEqual(errors, []);
    completed = true;
  } finally {
    await writeFile(join(output, "checks.json"), JSON.stringify({
      completed, scope: "static-resource-dashboard", stages,
      limitations: ["No live inventory or human assistive-technology certification."],
    }, null, 2) + "\n");
    await browser.close();
  }
});
