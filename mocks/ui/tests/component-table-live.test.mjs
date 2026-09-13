import assert from "node:assert/strict";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const uiRoot = join(root, "mocks/ui");
const output = join(root, ".fdai/visual-review/component-table-live-current");
const components = await readFile(join(uiRoot, "components.html"), "utf8");
const live = await readFile(join(uiRoot, "live.html"), "utf8");
const liveScript = await readFile(join(uiRoot, "assets/live.js"), "utf8");
const styles = await readFile(join(uiRoot, "assets/component-operational-patterns.css"), "utf8");
const registry = JSON.parse(await readFile(join(uiRoot, "assets/component-registry.json"), "utf8"));
const require = createRequire(join(root, "console/package.json"));
const { chromium } = require("playwright");
const origin = "http://127.0.0.1:5373";

function sectionMarkup(id, nextId) {
  const start = components.indexOf(`<section class="cs-section" id="${id}"`);
  const end = nextId
    ? components.indexOf(`<section class="cs-section" id="${nextId}"`, start)
    : components.indexOf("</main>", start);
  assert.ok(start >= 0, id);
  assert.ok(end > start, nextId || "main");
  return components.slice(start, end);
}

async function openView(page, id) {
  await page.goto(`${origin}/?component-pattern=${id}#mocks/ui/components.html::${id}`, {
    waitUntil: "load",
  });
  await page.waitForFunction(expected => {
    const frame = document.querySelector("#preview-frame");
    return frame?.contentDocument?.body?.classList.contains("is-gallery-ready")
      && frame.contentDocument.getElementById(expected)?.checkVisibility();
  }, id);
  return (await page.locator("#preview-frame").elementHandle()).contentFrame();
}

function measureSurface(selector) {
  const root = document.querySelector(selector);
  const visible = element => element.checkVisibility({ checkVisibilityCSS: true, checkOpacity: true })
    && !element.closest('[hidden], [aria-hidden="true"], .cs-sr-only, .sr-only');
  const text = [...root.querySelectorAll("*")].filter(element =>
    visible(element)
    && !element.matches("script, style, svg, svg *")
    && [...element.childNodes].some(node => node.nodeType === Node.TEXT_NODE && node.textContent.trim()));
  const color = value => {
    const values = (value.match(/[\d.]+/g) || []).map(Number);
    const channels = value.startsWith("color(srgb ")
      ? values.slice(0, 3).map(channel => channel * 255)
      : values.slice(0, 3);
    return [...channels, values[3] ?? 1];
  };
  const luminance = value => value.slice(0, 3).map(channel => {
    const normalized = channel / 255;
    return normalized <= 0.04045 ? normalized / 12.92
      : ((normalized + 0.055) / 1.055) ** 2.4;
  }).reduce((sum, channel, index) => sum + channel * [0.2126, 0.7152, 0.0722][index], 0);
  const backgroundFor = element => {
    const layers = [];
    let current = element;
    while (current) {
      const layer = color(getComputedStyle(current).backgroundColor);
      if (layer.length >= 4 && layer[3] > 0) layers.push(layer);
      if (layer[3] === 1) break;
      current = current.parentElement;
    }
    let result = layers.at(-1)?.slice(0, 3) || [255, 255, 255];
    for (let index = layers.length - 2; index >= 0; index -= 1) {
      const layer = layers[index];
      result = layer.slice(0, 3).map((channel, channelIndex) =>
        channel * layer[3] + result[channelIndex] * (1 - layer[3]));
    }
    return result;
  };
  const lowContrast = text.filter(element => {
    const style = getComputedStyle(element);
    const foregroundLuminance = luminance(color(style.color));
    const backgroundLuminance = luminance(backgroundFor(element));
    const ratio = (Math.max(foregroundLuminance, backgroundLuminance) + 0.05)
      / (Math.min(foregroundLuminance, backgroundLuminance) + 0.05);
    return ratio < 4.48;
  });
  const controls = [...root.querySelectorAll("a[href], button, input, select, [role=button]")]
    .filter(visible);
  return {
    documentFits: document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    surfaceFits: root.scrollWidth <= root.clientWidth,
    smallText: text.filter(element => {
      const size = parseFloat(getComputedStyle(element).fontSize);
      return size > 0 && size < 12;
    }).map(element => element.textContent.trim()),
    lowContrast: lowContrast.map(element => element.textContent.trim()),
    unnamedControls: controls.filter(element =>
      !element.getAttribute("aria-label")
      && !element.getAttribute("aria-labelledby")
      && !element.textContent.trim()).length,
    clippedText: text.filter(element => {
      const style = getComputedStyle(element);
      return ["hidden", "clip"].includes(style.overflowX)
        && element.scrollWidth > element.clientWidth + 2
        && style.textOverflow !== "ellipsis";
    }).map(element => element.textContent.trim()),
  };
}

test("table and Live card source contracts remain complete", () => {
  const table = sectionMarkup("table", "alerts");
  const liveCards = sectionMarkup("live-operational-cards");
  const tableBody = table.slice(table.indexOf("<tbody>"), table.indexOf("</tbody>"));
  const queueBody = liveCards.slice(liveCards.indexOf("<tbody>"), liveCards.indexOf("</tbody>"));

  assert.match(components, /component-operational-patterns\.css\?v=5/);
  assert.equal((tableBody.match(/<tr/g) || []).length, 4);
  assert.equal((table.match(/<th scope="col"/g) || []).length, 6);
  assert.equal((tableBody.match(/data-label=/g) || []).length, 24);
  assert.equal((tableBody.match(/class="cg-table-action"/g) || []).length, 4);
  assert.equal((table.match(/<time datetime=/g) || []).length, 4);
  assert.equal((table.match(/class="cg-table-state-grid"/g) || []).length, 1);
  assert.match(table, /Filtered empty/);
  assert.match(table, /Source unavailable/);

  [
    "cs-live-status-rail",
    "cs-live-health",
    "cs-live-attention",
    "cs-live-kpi",
    "cs-gate-viz",
    "cs-tier-plot",
    "cs-tile",
    "cs-live-queue",
  ].forEach(className => {
    assert.match(live + liveScript, new RegExp(className), `Live source: ${className}`);
    assert.match(liveCards, new RegExp(className), `Gallery specimen: ${className}`);
  });
  assert.equal((liveCards.match(/class="cs-live-kpi"/g) || []).length, 3);
  assert.equal((liveCards.match(/class="cs-tile cg-live-tile"/g) || []).length, 6);
  assert.equal((queueBody.match(/<tr/g) || []).length, 2);
  [
    "Route",
    "Shadow recorded",
    "Preview verified",
    "Approval required",
    "Denied",
    "Execution failed",
  ].forEach(state => assert.match(liveCards, new RegExp(`>${state}<`), state));

  const spec = registry.components.find(component => component.id === "live-operational-cards");
  assert.equal(registry.version, 12);
  assert.equal(spec?.view, "live-cards");
  assert.equal(spec?.routes[0]?.href, "live.html");
  assert.match(spec?.do_not || "", /execution command/);
  assert.match(styles, /@media \(max-width: 820px\)/);
  assert.match(styles, /@media \(max-width: 520px\)/);
  assert.match(styles, /@media \(forced-colors: active\)/);
});

test("table and Live card specimens pass the desktop visual contract", { timeout: 60000 }, async () => {
  await mkdir(output, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const results = [];
  try {
    const context = await browser.newContext({
      viewport: { width: 1440, height: 900 },
      reducedMotion: "reduce",
    });
    await context.route("**/*", route => new URL(route.request().url()).origin === origin
      ? route.continue() : route.abort("blockedbyclient"));
    const page = await context.newPage();

    const tableFrame = await openView(page, "table");
    const tableMeasurement = await tableFrame.evaluate(measureSurface, "#table");
    Object.entries(tableMeasurement).forEach(([key, value]) => {
      if (Array.isArray(value)) assert.deepEqual(value, [], `table ${key}`);
      else if (typeof value === "boolean") assert.equal(value, true, `table ${key}`);
      else assert.equal(value, 0, `table ${key}`);
    });
    assert.equal(await tableFrame.locator(".cg-data-table tbody tr").count(), 4);
    assert.equal(await tableFrame.locator(".cg-data-table th[scope=col]").count(), 6);
    await page.screenshot({
      path: join(output, "table-desktop-light.png"),
      animations: "disabled",
    });
    const tableAction = tableFrame.locator(".cg-table-action").first();
    await tableAction.focus();
    assert.notEqual(await tableAction.evaluate(element => getComputedStyle(element).outlineStyle), "none");
    await tableFrame.locator("[data-cs-theme-toggle]").click();
    await tableFrame.waitForFunction(() => document.body.dataset.theme === "dark");
    await tableFrame.waitForTimeout(350);
    const tableDark = await tableFrame.evaluate(measureSurface, "#table");
    assert.deepEqual(tableDark.lowContrast, []);
    assert.deepEqual(tableDark.smallText, []);
    assert.equal(tableDark.documentFits, true);
    assert.equal(tableDark.surfaceFits, true);
    await page.screenshot({
      path: join(output, "table-desktop-dark.png"),
      animations: "disabled",
    });

    const liveFrame = await openView(page, "live-operational-cards");
    const liveMeasurement = await liveFrame.evaluate(measureSurface, "#live-operational-cards");
    Object.entries(liveMeasurement).forEach(([key, value]) => {
      if (Array.isArray(value)) assert.deepEqual(value, [], `Live cards ${key}`);
      else if (typeof value === "boolean") assert.equal(value, true, `Live cards ${key}`);
      else assert.equal(value, 0, `Live cards ${key}`);
    });
    assert.equal(await liveFrame.locator(".cs-live-kpi").count(), 3);
    assert.equal(await liveFrame.locator(".cg-live-tile").count(), 6);
    assert.equal(await liveFrame.locator(".cg-live-queue tbody tr").count(), 2);
    await page.screenshot({
      path: join(output, "live-cards-desktop-light.png"),
      animations: "disabled",
    });
    const tile = liveFrame.locator(".cg-live-tile").first();
    await tile.focus();
    assert.notEqual(await tile.evaluate(element => getComputedStyle(element).outlineStyle), "none");

    await liveFrame.locator("[data-cs-theme-toggle]").click();
    await liveFrame.waitForFunction(() => document.body.dataset.theme === "dark");
    await liveFrame.waitForFunction(() =>
      getComputedStyle(document.querySelector(".cg-live-tile")).backgroundColor === "rgb(29, 32, 35)");
    await liveFrame.waitForTimeout(350);
    const liveDark = await liveFrame.evaluate(measureSurface, "#live-operational-cards");
    assert.deepEqual(liveDark.lowContrast, []);
    assert.deepEqual(liveDark.smallText, []);
    assert.equal(liveDark.documentFits, true);
    assert.equal(liveDark.surfaceFits, true);
    await page.screenshot({
      path: join(output, "live-cards-desktop-dark.png"),
      animations: "disabled",
    });
    results.push({ view: "table", ...tableMeasurement }, { view: "table-dark", ...tableDark },
      { view: "live-cards", ...liveMeasurement },
      { view: "live-cards-dark", ...liveDark });
    await writeFile(join(output, "desktop-measurements.json"), JSON.stringify(results, null, 2) + "\n");
    await context.close();
  } finally {
    await browser.close();
  }
});

test("table and Live card specimens reflow at constrained and mobile widths", { timeout: 60000 }, async () => {
  await mkdir(output, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const results = [];
  try {
    for (const viewport of [
      { name: "constrained", width: 993, height: 641 },
      { name: "mobile", width: 390, height: 844 },
    ]) {
      const context = await browser.newContext({
        viewport: { width: viewport.width, height: viewport.height },
        reducedMotion: "reduce",
      });
      await context.route("**/*", route => new URL(route.request().url()).origin === origin
        ? route.continue() : route.abort("blockedbyclient"));
      const page = await context.newPage();

      const tableFrame = await openView(page, "table");
      const tableMeasurement = await tableFrame.evaluate(measureSurface, "#table");
      assert.equal(tableMeasurement.documentFits, true, `${viewport.name} table document`);
      assert.equal(tableMeasurement.surfaceFits, true, `${viewport.name} table surface`);
      assert.deepEqual(tableMeasurement.smallText, [], `${viewport.name} table text`);
      assert.equal(await tableFrame.locator(".cg-data-table tbody tr").first().evaluate(element =>
        getComputedStyle(element).display), "grid");
      const tableColumns = await tableFrame.locator(".cg-data-table tbody tr").first().evaluate(element =>
        getComputedStyle(element).gridTemplateColumns.split(" ").length);
      assert.equal(tableColumns, viewport.name === "mobile" ? 1 : 2);
      if (viewport.name === "mobile") {
        const shortTableActions = await tableFrame.locator(".cg-table-action").evaluateAll(elements =>
          elements.filter(element =>
            element.getBoundingClientRect().width < 44
            || element.getBoundingClientRect().height < 44).length);
        assert.equal(shortTableActions, 0);
      }
      await page.screenshot({
        path: join(output, `table-${viewport.name}.png`),
        animations: "disabled",
      });

      const liveFrame = await openView(page, "live-operational-cards");
      const liveMeasurement = await liveFrame.evaluate(measureSurface, "#live-operational-cards");
      assert.equal(liveMeasurement.documentFits, true, `${viewport.name} Live document`);
      assert.equal(liveMeasurement.surfaceFits, true, `${viewport.name} Live surface`);
      assert.deepEqual(liveMeasurement.smallText, [], `${viewport.name} Live text`);
      const layout = await liveFrame.evaluate(() => ({
        kpiColumns: getComputedStyle(document.querySelector(".cg-live-kpis")).gridTemplateColumns.split(" ").length,
        tileColumns: getComputedStyle(document.querySelector(".cg-live-work-grid")).gridTemplateColumns.split(" ").length,
        queueColumns: getComputedStyle(document.querySelector(".cg-live-queue tbody tr"))
          .gridTemplateColumns.split(" ").length,
        activeSubviewVisible: (() => {
          const navigation = document.querySelector("[data-gallery-subindex]");
          const active = navigation.querySelector('[aria-current="page"]');
          const navigationBox = navigation.getBoundingClientRect();
          const activeBox = active.getBoundingClientRect();
          return activeBox.left >= navigationBox.left - 1 && activeBox.right <= navigationBox.right + 1;
        })(),
        shortTargets: [...document.querySelectorAll(
          "#live-operational-cards a[href], #live-operational-cards button",
        )].filter(element => element.checkVisibility() && element.getBoundingClientRect().height < 44)
          .map(element => element.textContent.trim()),
      }));
      assert.equal(layout.kpiColumns, viewport.name === "mobile" ? 1 : 2, `${viewport.name} KPI columns`);
      assert.equal(layout.tileColumns, viewport.name === "mobile" ? 1 : 2, `${viewport.name} tile columns`);
      assert.equal(layout.queueColumns, viewport.name === "mobile" ? 1 : 2, `${viewport.name} queue columns`);
      assert.equal(layout.activeSubviewVisible, true, `${viewport.name} active subview`);
      if (viewport.name === "mobile") assert.deepEqual(layout.shortTargets, []);
      await page.screenshot({
        path: join(output, `live-cards-${viewport.name}.png`),
        animations: "disabled",
      });
      results.push({ viewport, table: tableMeasurement, live: liveMeasurement, layout });
      await context.close();
    }
    await writeFile(join(output, "responsive-measurements.json"), JSON.stringify(results, null, 2) + "\n");
  } finally {
    await browser.close();
  }
});
