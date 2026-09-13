/** Theme and contrast regressions for static-mock chart tooltips. */
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const uiRoot = join(root, "mocks/ui");
const require = createRequire(join(root, "console/package.json"));
const { chromium } = require("playwright");
const origin = "http://127.0.0.1:5373";

function channels(color) {
  return (color.match(/[\d.]+/g) || [0, 0, 0]).slice(0, 3).map(Number);
}

function luminance(color) {
  return channels(color).map((value) => {
    const normalized = value / 255;
    return normalized <= 0.04045
      ? normalized / 12.92
      : ((normalized + 0.055) / 1.055) ** 2.4;
  }).reduce((total, value, index) => total + value * [0.2126, 0.7152, 0.0722][index], 0);
}

function contrast(first, second) {
  const a = luminance(first);
  const b = luminance(second);
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}

async function openMock(page, path) {
  await page.goto(`${origin}/?tooltip-theme=${encodeURIComponent(path)}#mocks/ui/${path}`, {
    waitUntil: "load",
  });
  await page.waitForFunction(expected => {
    const frame = document.querySelector("#preview-frame");
    return frame?.contentDocument?.readyState === "complete"
      && frame.contentWindow.location.pathname === `/mocks/ui/${expected}`;
  }, path);
  return (await page.locator("#preview-frame").elementHandle()).contentFrame();
}

async function themeStyles(frame, selector) {
  return frame.locator(selector).first().evaluate((element) => {
    const style = getComputedStyle(element);
    return {
      background: style.backgroundColor,
      color: style.color,
      border: style.borderColor,
      shadow: style.boxShadow,
      theme: document.documentElement.dataset.theme || document.body.dataset.theme || "light",
      token: style.getPropertyValue("--cs-tooltip-bg").trim(),
    };
  });
}

async function waitForDarkTooltip(frame, selector) {
  await frame.waitForFunction((target) => {
    const element = document.querySelector(target);
    return element !== null
      && getComputedStyle(element).backgroundColor === "rgb(32, 35, 38)";
  }, selector);
}

test("all static chart tooltip variants consume shared semantic tokens", async () => {
  const files = await Promise.all([
    readFile(join(root, "ui/calm-slate-tokens.css"), "utf8"),
    readFile(join(uiRoot, "assets/calm-slate.css"), "utf8"),
    readFile(join(uiRoot, "assets/finops-resource-efficiency.css"), "utf8"),
    readFile(join(uiRoot, "assets/dashboard-resources.css"), "utf8"),
    readFile(join(uiRoot, "service-map.html"), "utf8"),
    readFile(join(uiRoot, "deck.html"), "utf8"),
  ]);
  const [tokens, shared, finops, resources, serviceMap, deck] = files;
  for (const token of [
    "--cs-tooltip-bg",
    "--cs-tooltip-text",
    "--cs-tooltip-muted",
    "--cs-tooltip-border",
    "--cs-tooltip-shadow",
  ]) {
    assert.match(tokens, new RegExp(token));
    assert.match(shared, new RegExp(token));
  }
  assert.match(shared, /:root\[data-theme="dark"\],[\s\S]*body\[data-theme="dark"\]/);
  for (const source of [shared, finops, resources, serviceMap, deck]) {
    assert.match(source, /var\(--cs-tooltip-bg,/);
    assert.match(source, /var\(--cs-tooltip-text,/);
    assert.match(source, /var\(--cs-tooltip-border,/);
    assert.match(source, /var\(--cs-tooltip-shadow,/);
  }
  assert.doesNotMatch(shared, /\.cs-(?:chart-mark-tip|live-chart-tooltip)[^}]*background:\s*var\(--cs-navy\)/);
  assert.doesNotMatch(deck, /\.dk-tt[^}]*background:\s*var\(--cs-navy\)/);
});

test("Live chart tooltip follows light and dark themes with readable contrast", { timeout: 30000 }, async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const context = await browser.newContext({
      viewport: { width: 1440, height: 900 },
      reducedMotion: "reduce",
    });
    await context.route("**/*", route => new URL(route.request().url()).origin === origin
      ? route.continue() : route.abort("blockedbyclient"));
    const page = await context.newPage();
    const frame = await openMock(page, "live.html");
    const mark = frame.locator('[data-gate-segment="auto"]');
    await frame.waitForFunction(() =>
      Boolean(document.querySelector('[data-gate-segment="auto"]')?.getAttribute("data-live-chart-tip")));
    await mark.dispatchEvent("pointerenter", { pointerType: "mouse" });
    const tooltip = frame.locator("#live-chart-tooltip");
    assert.equal(await tooltip.isVisible(), true);
    const light = await themeStyles(frame, "#live-chart-tooltip");
    assert.ok(luminance(light.background) > 0.85, JSON.stringify(light));
    assert.ok(contrast(light.background, light.color) >= 4.5, JSON.stringify(light));
    await mark.dispatchEvent("pointerleave", { pointerType: "mouse" });
    assert.equal(await tooltip.isVisible(), false);
    await mark.dispatchEvent("focus");
    assert.equal(await tooltip.isVisible(), true);

    await frame.evaluate(() => {
      document.body.removeAttribute("data-chat-theme");
      document.documentElement.dataset.theme = "dark";
      document.body.dataset.theme = "dark";
    });
    await frame.evaluate(() => new Promise(resolve =>
      requestAnimationFrame(() => requestAnimationFrame(resolve))));
    await waitForDarkTooltip(frame, "#live-chart-tooltip");
    const dark = await themeStyles(frame, "#live-chart-tooltip");
    assert.ok(luminance(dark.background) < 0.05, JSON.stringify(dark));
    assert.ok(contrast(dark.background, dark.color) >= 4.5, JSON.stringify(dark));
    assert.notEqual(dark.background, light.background);
    assert.notEqual(dark.color, light.color);
    await context.close();
  } finally {
    await browser.close();
  }
});

test("Live chart tooltip stays inside the mobile viewport", { timeout: 30000 }, async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const context = await browser.newContext({
      viewport: { width: 390, height: 844 },
      reducedMotion: "reduce",
    });
    await context.route("**/*", route => new URL(route.request().url()).origin === origin
      ? route.continue() : route.abort("blockedbyclient"));
    const page = await context.newPage();
    const frame = await openMock(page, "live.html");
    await frame.waitForFunction(() =>
      Boolean(document.querySelector('[data-gate-segment="auto"]')?.getAttribute("data-live-chart-tip")));
    const mark = frame.locator('[data-gate-segment="auto"]');
    await mark.dispatchEvent("pointerenter", { pointerType: "mouse" });
    const geometry = await frame.locator("#live-chart-tooltip").evaluate((element) => {
      const box = element.getBoundingClientRect();
      return {
        left: box.left,
        right: box.right,
        top: box.top,
        bottom: box.bottom,
        viewportWidth: document.documentElement.clientWidth,
        viewportHeight: document.documentElement.clientHeight,
      };
    });
    assert.ok(geometry.left >= 8, JSON.stringify(geometry));
    assert.ok(geometry.right <= geometry.viewportWidth - 8, JSON.stringify(geometry));
    assert.ok(geometry.top >= 8, JSON.stringify(geometry));
    assert.ok(geometry.bottom <= geometry.viewportHeight - 8, JSON.stringify(geometry));
    await context.close();
  } finally {
    await browser.close();
  }
});

test("route-local chart tooltips share the same theme surfaces", { timeout: 60000 }, async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const context = await browser.newContext({
      viewport: { width: 1440, height: 900 },
      reducedMotion: "reduce",
    });
    await context.route("**/*", route => new URL(route.request().url()).origin === origin
      ? route.continue() : route.abort("blockedbyclient"));
    const page = await context.newPage();
    const probes = [
      ["dashboard-v2.html", "#resource-hover-preview"],
      ["finops-resource-efficiency.html", "#cost-chart-tooltip"],
      ["deck.html", ".dk-tt"],
      ["components.html", ".cs-tooltip-content"],
    ];
    for (const [path, selector] of probes) {
      const frame = await openMock(page, path);
      await frame.locator(selector).first().waitFor({ state: "attached" });
      const light = await themeStyles(frame, selector);
      assert.ok(luminance(light.background) > 0.85, `${path}: ${JSON.stringify(light)}`);
      assert.ok(contrast(light.background, light.color) >= 4.5, `${path}: ${JSON.stringify(light)}`);
      await frame.evaluate(() => {
        document.body.removeAttribute("data-chat-theme");
        document.documentElement.dataset.theme = "dark";
        document.body.dataset.theme = "dark";
      });
      await frame.evaluate(() => new Promise(resolve =>
        requestAnimationFrame(() => requestAnimationFrame(resolve))));
      await waitForDarkTooltip(frame, selector);
      const dark = await themeStyles(frame, selector);
      assert.ok(luminance(dark.background) < 0.05, `${path}: ${JSON.stringify(dark)}`);
      assert.ok(contrast(dark.background, dark.color) >= 4.5, `${path}: ${JSON.stringify(dark)}`);
    }

    const serviceMap = await openMock(page, "service-map.html");
    await serviceMap.evaluate(() => {
      const tooltip = document.createElement("div");
      tooltip.className = "app-tooltip";
      tooltip.textContent = "Theme probe";
      document.body.append(tooltip);
    });
    const light = await themeStyles(serviceMap, ".app-tooltip");
    assert.ok(luminance(light.background) > 0.85, JSON.stringify(light));
    await serviceMap.evaluate(() => {
      document.documentElement.dataset.theme = "dark";
      document.body.dataset.theme = "dark";
    });
    await serviceMap.evaluate(() => new Promise(resolve =>
      requestAnimationFrame(() => requestAnimationFrame(resolve))));
    await waitForDarkTooltip(serviceMap, ".app-tooltip");
    const dark = await themeStyles(serviceMap, ".app-tooltip");
    assert.ok(luminance(dark.background) < 0.05, JSON.stringify(dark));
    assert.ok(contrast(dark.background, dark.color) >= 4.5, JSON.stringify(dark));
    await context.close();
  } finally {
    await browser.close();
  }
});
