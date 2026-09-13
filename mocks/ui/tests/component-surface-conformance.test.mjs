import assert from "node:assert/strict";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const uiRoot = join(root, "mocks/ui");
const output = join(root, ".fdai/visual-review/component-surface-conformance");
const master = await readFile(join(root, "index.html"), "utf8");
const require = createRequire(join(root, "console/package.json"));
const { chromium } = require("playwright");
const origin = "http://127.0.0.1:5373";
const viewportFilter = process.env.COMPONENT_CONFORMANCE_VIEWPORT || "";
const targetGroups = ["overview", "operations", "agents", "governance", "knowledge", "evidence", "settings"];
const expectedCounts = {
  overview: 8,
  operations: 14,
  agents: 3,
  governance: 11,
  knowledge: 5,
  evidence: 9,
  settings: 7,
};
const deprecatedAliases = ["cs-btn", "cs-input", "cs-select", "cs-segmented", "cs-switch"];

function targetRoutes() {
  const routes = [];
  for (const match of master.split("<script>")[0]
    .matchAll(/<section class="nav-group" data-nav-section="([^"]+)">([\s\S]*?)<\/section>/g)) {
    const [, group, markup] = match;
    if (!targetGroups.includes(group)) continue;
    const groupRoutes = [...markup.matchAll(/data-page="([^"]+)"\s+data-title="([^"]+)"/g)]
      .map(([, path, title]) => ({ group, path, title }));
    assert.equal(groupRoutes.length, expectedCounts[group], group);
    routes.push(...groupRoutes);
  }
  return routes;
}

const routes = targetRoutes();
const representativePaths = new Set(targetGroups.map(group =>
  routes.find(route => route.group === group)?.path));

function measureSurface(viewportWidth) {
  const visible = element => {
    if (!element.checkVisibility({ checkVisibilityCSS: true, checkOpacity: true })) return false;
    const box = element.getBoundingClientRect();
    const style = getComputedStyle(element);
    return box.width > 0 && box.height > 0
      && style.clipPath !== "inset(50%)"
      && style.clip !== "rect(0px, 0px, 0px, 0px)"
      && !element.closest('[hidden], [aria-hidden="true"], .cs-sr-only, .sr-only');
  };
  const label = element =>
    (element.getAttribute("aria-label") || element.textContent || "")
      .trim().replace(/\s+/g, " ").slice(0, 100);
  const text = [...document.querySelectorAll("body *")].filter(element =>
    visible(element)
    && !element.matches("script, style, svg, svg *, option")
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
      const style = getComputedStyle(current);
      if (style.backgroundImage !== "none") return null;
      const layer = color(style.backgroundColor);
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
  const lowContrast = text.flatMap(element => {
    const background = backgroundFor(element);
    if (!background) return [];
    const foreground = color(getComputedStyle(element).color);
    const a = luminance(foreground);
    const b = luminance(background);
    const ratio = (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
    return ratio < 4.48 ? [{
      label: label(element),
      tag: element.tagName.toLowerCase(),
      class: typeof element.className === "string" ? element.className : "",
      parent: typeof element.parentElement?.className === "string" ? element.parentElement.className : "",
      color: getComputedStyle(element).color,
      background: background.map(channel => Math.round(channel)),
      ratio: Number(ratio.toFixed(2)),
    }] : [];
  });
  const controls = [...document.querySelectorAll(
    "button, input:not([type=hidden]), select, textarea, summary, [role=button]",
  )].filter(visible);
  const actionLinks = [...document.querySelectorAll(
    'a.cs-control-button, a.cs-page-button, a[class*="button"], a[aria-label]:not([aria-label=""]), [role=tab]',
  )].filter(visible);
  const targetBox = element => {
    if (element.matches('input[type="checkbox"], input[type="radio"]')) {
      return element.closest("label")?.getBoundingClientRect() || element.getBoundingClientRect();
    }
    if (element.closest(".cs-combobox-control")) {
      return element.closest(".cs-combobox-control").getBoundingClientRect();
    }
    return element.getBoundingClientRect();
  };
  const minimumTarget = viewportWidth <= 520 ? 44 : 28;
  const undersizedTargets = [...controls, ...actionLinks].filter((element, index, all) =>
    all.indexOf(element) === index).filter(element => {
    const box = targetBox(element);
    return box.width < minimumTarget || box.height < minimumTarget;
  });
  const tables = [...document.querySelectorAll("table")].filter(visible);
  const all = [...document.querySelectorAll("body *")].filter(visible);
  const overflow = all.filter(element => {
    const box = element.getBoundingClientRect();
    if (element.closest("svg, canvas, .cs-sr-only, .sr-only")) return false;
    if (box.left >= -1 && box.right <= document.documentElement.clientWidth + 1) return false;
    let parent = element.parentElement;
    while (parent && parent !== document.body) {
      if (["auto", "scroll", "hidden", "clip"].includes(getComputedStyle(parent).overflowX)) return false;
      parent = parent.parentElement;
    }
    return true;
  });
  const clipped = text.filter(element => {
    const style = getComputedStyle(element);
    return ["hidden", "clip"].includes(style.overflowX)
      && element.scrollWidth > element.clientWidth + 2
      && style.textOverflow !== "ellipsis";
  });
  return {
    theme: document.body.dataset.chatTheme || "",
    colorMode: document.body.dataset.theme || "light",
    darkSurface: luminance(color(getComputedStyle(document.body).backgroundColor)) < 0.2,
    h1Count: document.querySelectorAll("h1").length,
    documentFits: document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    mainFits: !document.querySelector("main")
      || document.querySelector("main").scrollWidth <= document.querySelector("main").clientWidth,
    smallText: text.filter(element => {
      const size = parseFloat(getComputedStyle(element).fontSize);
      return size > 0 && size < 12;
    }).map(label),
    lowContrast,
    unnamedControls: controls.filter(element =>
      !element.getAttribute("aria-label")
      && !element.getAttribute("aria-labelledby")
      && !element.labels?.length
      && !element.textContent.trim()
      && !element.getAttribute("title")).map(label),
    undersizedTargets: undersizedTargets.map(element => {
      const box = targetBox(element);
      return { label: label(element), width: Math.round(box.width), height: Math.round(box.height) };
    }),
    nestedInteractive: document.querySelectorAll(
      "a a, a button, a input, a select, button a, button button, button input, button select",
    ).length,
    inaccessibleTables: tables.filter(table =>
      !table.querySelector("caption")
      && !table.getAttribute("aria-label")
      && !table.getAttribute("aria-labelledby")).length,
    unscopedHeaders: tables.flatMap(table => [...table.querySelectorAll("th")])
      .filter(header => !header.getAttribute("scope")).length,
    overflow: overflow.map(label),
    clipped: clipped.map(label),
    brokenImages: [...document.images].filter(image =>
      visible(image) && image.complete && !image.naturalWidth).map(image => image.getAttribute("src")),
  };
}

test("target mock sources use the current shared component contract", async () => {
  assert.equal(routes.length, 57);
  assert.equal(new Set(routes.map(route => route.path)).size, 57);
  for (const route of routes) {
    const source = await readFile(join(root, route.path), "utf8");
    const classTokens = [...source.matchAll(/class="([^"]+)"/g)]
      .flatMap(match => match[1].split(/\s+/));
    assert.match(source, /assets\/calm-slate\.css\?v=/, route.path);
    assert.match(source, /data-chat-theme="clear-neutral"|data-console-parity-page/, route.path);
    assert.match(source, /<main\b/, route.path);
    deprecatedAliases.forEach(alias =>
      assert.equal(classTokens.includes(alias), false, `${route.path}: ${alias}`));
    const buttons = [...source.matchAll(/<button\b[^>]*>/g)].map(match => match[0]);
    assert.equal(buttons.every(button => /\btype="(?:button|submit|reset)"/.test(button)), true, route.path);
  }
});

test("all target mocks conform at desktop, constrained, and mobile widths", { timeout: 240000 }, async () => {
  await mkdir(output, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const results = [];
  const failures = [];
  try {
    for (const viewport of [
      { name: "desktop", width: 1440, height: 900 },
      { name: "dark", width: 1440, height: 900, dark: true },
      { name: "constrained", width: 993, height: 641 },
      { name: "mobile", width: 390, height: 844 },
    ].filter(viewport => !viewportFilter || viewport.name === viewportFilter)) {
      const context = await browser.newContext({
        viewport: { width: viewport.width, height: viewport.height },
        reducedMotion: "reduce",
      });
      await context.route("**/*", route => new URL(route.request().url()).origin === origin
        ? route.continue() : route.abort("blockedbyclient"));
      const page = await context.newPage();
      page.setDefaultTimeout(10000);
      let sequence = 0;
      for (const route of routes) {
        sequence += 1;
        const errors = [];
        page.on("pageerror", error => errors.push(error.message));
        await page.goto(
          `${origin}/?component-conformance=${viewport.name}-${sequence}#${route.path}`,
          { waitUntil: "load" },
        );
        await page.waitForFunction(expected => {
          const frame = document.querySelector("#preview-frame");
          return frame?.contentDocument?.readyState === "complete"
            && frame.contentWindow.location.pathname === `/${expected}`;
        }, route.path);
        const frame = await (await page.locator("#preview-frame").elementHandle()).contentFrame();
        await frame.evaluate(() => new Promise(resolveFrame =>
          requestAnimationFrame(() => requestAnimationFrame(resolveFrame))));
        if (viewport.dark) {
          await frame.evaluate(() => {
            document.body.dataset.theme = "dark";
          });
          await frame.waitForTimeout(350);
        }
        await frame.waitForTimeout(50);
        const measurement = await frame.evaluate(measureSurface, viewport.width);
        const violations = {};
        if (measurement.theme !== "clear-neutral") violations.theme = measurement.theme;
        if (measurement.colorMode !== (viewport.dark ? "dark" : "light")) {
          violations.colorMode = measurement.colorMode;
        }
        if (measurement.darkSurface !== Boolean(viewport.dark)) {
          violations.darkSurface = measurement.darkSurface;
        }
        if (measurement.h1Count !== 1) violations.h1Count = measurement.h1Count;
        if (!measurement.documentFits) violations.documentFits = false;
        if (!measurement.mainFits) violations.mainFits = false;
        for (const key of [
          "smallText",
          "lowContrast",
          "unnamedControls",
          "undersizedTargets",
          "overflow",
          "clipped",
          "brokenImages",
        ]) {
          if (measurement[key].length) violations[key] = measurement[key];
        }
        if (measurement.nestedInteractive) violations.nestedInteractive = measurement.nestedInteractive;
        if (measurement.inaccessibleTables) violations.inaccessibleTables = measurement.inaccessibleTables;
        if (measurement.unscopedHeaders) violations.unscopedHeaders = measurement.unscopedHeaders;
        if (errors.length) violations.errors = errors;
        if (Object.keys(violations).length) {
          failures.push({ viewport: viewport.name, path: route.path, violations });
        }
        results.push({ viewport: viewport.name, ...route, ...measurement, violations });
        if (representativePaths.has(route.path)) {
          await page.screenshot({
            path: join(output, `${viewport.name}-${route.group}.png`),
            animations: "disabled",
          });
        }
        page.removeAllListeners("pageerror");
      }
      await context.close();
    }
    await writeFile(join(output, "measurements.json"), JSON.stringify({
      scope: targetGroups,
      routeCount: routes.length,
      viewports: ["1440x900 light", "1440x900 dark", "993x641 light", "390x844 light"],
      dataMode: "synthetic local preview",
      results,
    }, null, 2) + "\n");
    assert.deepEqual(failures, []);
  } finally {
    await browser.close();
  }
});
