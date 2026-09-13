import assert from "node:assert/strict";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const uiRoot = join(root, "mocks/ui");
const output = join(root, ".fdai/visual-review/chat-current");
const require = createRequire(join(root, "console/package.json"));
const { chromium } = require("playwright");
const origin = "http://127.0.0.1:5373";
const routes = [
  "deck",
  "deck-sources",
  "deck-sources-v2",
  "incident-conversation",
  "conversation-response-patterns",
  "chat-home-variants",
];

async function openChat(page, name, sequence) {
  await page.goto(`${origin}/?chat-current=${sequence}#mocks/ui/${name}.html`, { waitUntil: "load" });
  await page.waitForFunction(expected => {
    const frame = document.querySelector("#preview-frame");
    return frame?.contentDocument?.readyState === "complete"
      && frame.contentWindow.location.pathname === `/mocks/ui/${expected}.html`;
  }, name);
  const frame = await (await page.locator("#preview-frame").elementHandle()).contentFrame();
  if (name === "deck-sources") {
    await frame.evaluate(() => {
      window.SPEED = 0.01;
      document.getElementById("gs-replay").click();
    });
    await frame.locator(".gs-grounded").waitFor({ state: "visible", timeout: 10000 });
    await frame.locator(".gs-followups").waitFor({ state: "visible", timeout: 10000 });
  }
  await frame.evaluate(() => new Promise(resolveFrame =>
    requestAnimationFrame(() => requestAnimationFrame(resolveFrame))));
  return frame;
}

function measureChat(viewportWidth) {
  const visible = element => {
    if (!element.checkVisibility({ checkVisibilityCSS: true, checkOpacity: true })) return false;
    const box = element.getBoundingClientRect();
    const style = getComputedStyle(element);
    return box.width > 0 && box.height > 0
      && style.clipPath !== "inset(50%)"
      && style.clip !== "rect(0px, 0px, 0px, 0px)"
      && !element.closest('[hidden], [aria-hidden="true"], .cs-sr-only, .sr-only');
  };
  const text = [...document.querySelectorAll("body *")].filter(element =>
    visible(element)
    && !element.matches("script, style, svg, svg *, option")
    && [...element.childNodes].some(node => node.nodeType === Node.TEXT_NODE && node.textContent.trim()));
  const label = element =>
    (element.getAttribute("aria-label") || element.textContent || "").trim().replace(/\s+/g, " ").slice(0, 100);
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
    const foregroundLuminance = luminance(color(getComputedStyle(element).color));
    const backgroundLuminance = luminance(background);
    const ratio = (Math.max(foregroundLuminance, backgroundLuminance) + 0.05)
      / (Math.min(foregroundLuminance, backgroundLuminance) + 0.05);
    return ratio < 4.48 ? [{ label: label(element), ratio: Number(ratio.toFixed(2)) }] : [];
  });
  const controls = [...document.querySelectorAll(
    "button, input:not([type=hidden]), textarea, select, summary, [role=button]",
  )].filter(visible);
  const minimum = viewportWidth <= 520 ? 44 : 28;
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
    undersizedControls: controls.filter(element => {
      const box = element.getBoundingClientRect();
      return box.width < minimum || box.height < minimum;
    }).map(element => {
      const box = element.getBoundingClientRect();
      return { label: label(element), width: Math.round(box.width), height: Math.round(box.height) };
    }),
    nestedInteractive: document.querySelectorAll(
      "a a, a button, a input, a select, button a, button button, button input, button select",
    ).length,
    inaccessibleTables: [...document.querySelectorAll("table")].filter(visible).filter(table =>
      !table.querySelector("caption")
      && !table.getAttribute("aria-label")
      && !table.getAttribute("aria-labelledby")).length,
    unscopedHeaders: [...document.querySelectorAll("table")].filter(visible)
      .flatMap(table => [...table.querySelectorAll("th")])
      .filter(header => !header.getAttribute("scope")).length,
  };
}

function assertMeasurement(measurement, route, state) {
  assert.equal(measurement.theme, "clear-neutral", `${route}: ${state} theme`);
  assert.equal(measurement.colorMode, state === "dark" ? "dark" : "light", `${route}: ${state} mode`);
  assert.equal(measurement.darkSurface, state === "dark", `${route}: ${state} surface`);
  assert.equal(measurement.h1Count, 1, `${route}: ${state} h1`);
  assert.equal(measurement.documentFits, true, `${route}: ${state} document`);
  assert.equal(measurement.mainFits, true, `${route}: ${state} main`);
  assert.deepEqual(measurement.smallText, [], `${route}: ${state} text`);
  assert.deepEqual(measurement.lowContrast, [], `${route}: ${state} contrast`);
  assert.deepEqual(measurement.unnamedControls, [], `${route}: ${state} names`);
  assert.deepEqual(measurement.undersizedControls, [], `${route}: ${state} targets`);
  assert.equal(measurement.nestedInteractive, 0, `${route}: ${state} nested interaction`);
  assert.equal(measurement.inaccessibleTables, 0, `${route}: ${state} table names`);
  assert.equal(measurement.unscopedHeaders, 0, `${route}: ${state} table headers`);
}

test("chat mock sources use the current shared contract", async () => {
  const master = await readFile(join(root, "index.html"), "utf8");
  for (const route of routes) {
    const source = await readFile(join(uiRoot, `${route}.html`), "utf8");
    assert.match(master, new RegExp(`data-page="mocks/ui/${route}\\.html"`), route);
    assert.match(source, /data-chat-theme="clear-neutral"/, route);
    assert.match(source, /data-chat-surface="current"/, route);
    assert.match(source, /chat-current\.css\?v=11/, route);
    assert.doesNotMatch(source, /https:\/\/fonts\.(?:googleapis|gstatic)\.com/, route);
    const buttons = [...source.matchAll(/<button\b[^>]*>/g)].map(match => match[0]);
    assert.equal(buttons.every(button => /\btype="(?:button|submit|reset)"/.test(button)), true, route);
    assert.equal((source.match(/<table\b/g) || []).length, (source.match(/<caption\b/g) || []).length,
      `${route}: captions`);
    const headers = [...source.matchAll(/<th\b[^>]*>/g)].map(match => match[0]);
    assert.equal(headers.every(header => /\bscope="col"/.test(header)), true, `${route}: header scopes`);
  }
  const sources = await readFile(join(uiRoot, "deck-sources.html"), "utf8");
  assert.match(sources, /var pill = el\("button", "gs-grounded"\)/);
  assert.match(sources, /pill\.setAttribute\("aria-expanded", "false"\)/);
  assert.match(sources, /<textarea class="gs-input"[^>]*readonly>/);
  assert.match(sources, /<button class="gs-send" type="button" disabled>Preview only/);
});

test("chat surfaces pass desktop Light and Dark states", { timeout: 120000 }, async () => {
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
    let sequence = 0;
    for (const route of routes) {
      const frame = await openChat(page, route, ++sequence);
      const light = await frame.evaluate(measureChat, 1440);
      assertMeasurement(light, route, "light");
      await page.screenshot({
        path: join(output, `${route}-desktop-light.png`),
        animations: "disabled",
      });
      await frame.evaluate(() => {
        document.body.dataset.theme = "dark";
      });
      await frame.waitForTimeout(350);
      const dark = await frame.evaluate(measureChat, 1440);
      assertMeasurement(dark, route, "dark");
      await page.screenshot({
        path: join(output, `${route}-desktop-dark.png`),
        animations: "disabled",
      });
      results.push({ route, light, dark });
    }
    await writeFile(join(output, "desktop-measurements.json"), JSON.stringify(results, null, 2) + "\n");
    await context.close();
  } finally {
    await browser.close();
  }
});

test("chat interactions preserve evidence and authority boundaries", { timeout: 60000 }, async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const context = await browser.newContext({
      viewport: { width: 1440, height: 900 },
      reducedMotion: "reduce",
    });
    await context.route("**/*", route => new URL(route.request().url()).origin === origin
      ? route.continue() : route.abort("blockedbyclient"));
    const page = await context.newPage();

    let frame = await openChat(page, "deck-sources", 1);
    const grounded = frame.locator(".gs-grounded");
    assert.equal(await grounded.getAttribute("aria-expanded"), "false");
    await grounded.click();
    assert.equal(await grounded.getAttribute("aria-expanded"), "true");
    assert.equal(await frame.locator("#gs-retrieval-trace").isVisible(), true);
    await grounded.click();
    assert.equal(await frame.locator("#gs-retrieval-trace").isVisible(), false);
    assert.equal(await frame.locator(".gs-send").isDisabled(), true);

    frame = await openChat(page, "deck-sources-v2", 2);
    const previewControls = frame.locator("#ex-preview-controls");
    if (!(await previewControls.evaluate(element => element.open))) {
      await previewControls.locator(":scope > summary").click();
    }
    const switcher = frame.locator(".ex-pattern-switcher");
    if (!(await switcher.evaluate(element => element.open))) {
      await switcher.locator(":scope > summary").click();
    }
    await frame.locator('[data-response-pattern="clarification"]').click();
    assert.equal(await frame.locator('[data-response-pattern="clarification"]').getAttribute("aria-pressed"), "true");
    assert.match(await frame.locator("#ex-pattern-body").innerText(), /Select the database to assess/);
    assert.match(await frame.locator("main").innerText(), /No live execution/);

    frame = await openChat(page, "chat-home-variants", 3);
    await frame.locator('[data-variant="c"]').click();
    assert.equal(await frame.locator('[data-variant="c"]').getAttribute("aria-selected"), "true");
    assert.equal(await frame.locator("#variant-c").isVisible(), true);

    frame = await openChat(page, "incident-conversation", 4);
    assert.match(await frame.locator(".ic-answer").innerText(), /Current status unknown/);
    assert.equal(await frame.getByRole("button", { name: /execute|approve|remediate/i }).count(), 0);
    await context.close();
  } finally {
    await browser.close();
  }
});

test("chat surfaces reflow at constrained and mobile widths", { timeout: 120000 }, async () => {
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
      let sequence = 0;
      for (const route of routes) {
        const frame = await openChat(page, route, `${viewport.name}-${++sequence}`);
        const measurement = await frame.evaluate(measureChat, viewport.width);
        assertMeasurement(measurement, route, "light");
        if (route === "deck-sources") {
          assert.equal(await frame.locator(".gs-body").evaluate(element =>
            getComputedStyle(element).gridTemplateColumns.split(" ").length), 1);
        }
        await page.screenshot({
          path: join(output, `${route}-${viewport.name}.png`),
          animations: "disabled",
        });
        results.push({ viewport: viewport.name, route, ...measurement });
      }
      await context.close();
    }
    await writeFile(join(output, "responsive-measurements.json"),
      JSON.stringify(results, null, 2) + "\n");
  } finally {
    await browser.close();
  }
});
