import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { mkdir, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const { chromium } = createRequire(join(root, "console/package.json"))("playwright");
const origin = "http://127.0.0.1:5373";
const pages = ["operating-outcomes", "control-assurance", "verticals", "trust-routing", "cost-governance", "llm-cost"];

async function setup(t) {
  const browser = await chromium.launch({ headless: true });
  const errors = [];
  t.after(async () => {
    try { assert.deepEqual(errors, []); } finally { await browser.close(); }
  });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, reducedMotion: "reduce" });
  await context.route("**/*", route => new URL(route.request().url()).origin === origin ? route.continue() : route.abort());
  const page = await context.newPage();
  page.setDefaultTimeout(6000);
  page.on("pageerror", error => errors.push(error.message));
  let entry = 0;
  async function open(name, suffix = "") {
    await page.goto(`${origin}/?review=${++entry}#mocks/ui/${name}.html${suffix}`);
    await page.waitForFunction(name => {
      const frame = document.querySelector("#preview-frame");
      return frame?.contentDocument?.readyState === "complete" &&
        frame.contentWindow.location.pathname === `/mocks/ui/${name}.html`;
    }, name);
    const frame = await (await page.locator("#preview-frame").elementHandle()).contentFrame();
    await frame.waitForLoadState("load");
    return frame;
  }
  return { page, context, open };
}

async function geometry(frame) {
  return frame.evaluate(() => {
    const main = document.querySelector("main");
    return {
      overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1 || main.scrollWidth > main.clientWidth + 1,
      header: getComputedStyle(document.querySelector(".oq-page-header")).backgroundColor,
      grid: [...document.querySelectorAll(".cs-metric-grid")].map(el => getComputedStyle(el).display),
      missingNames: [...main.querySelectorAll("button")].filter(el => !el.textContent.trim() && !el.getAttribute("aria-label")).length,
      outside: [...main.querySelectorAll("*")].filter(el => el.checkVisibility() && el.getBoundingClientRect().right > innerWidth + 1)
        .slice(0, 8).map(el => [el.tagName, el.className, el.textContent.slice(0, 80)]),
      spilling: [...main.querySelectorAll("*")].filter(el => el.checkVisibility() && el.scrollWidth > el.clientWidth + 1 && getComputedStyle(el).overflowX === "visible")
        .slice(0, 12).map(el => [el.tagName, el.className, el.clientWidth, el.scrollWidth, el.textContent.slice(0, 50)]),
    };
  });
}

test("Overview desktop: registered tabs, content anchors, guard dialogs and recovery", { timeout: 90000 }, async t => {
  const { open, page } = await setup(t);
  let frame = await open("operating-outcomes");
  for (const id of ["auto-resolution", "human-touchpoints", "mttr", "change-lead-time", "cost-per-resolved-event"]) {
    await frame.locator(`[data-overview-tab="${id}"]`).click();
    assert.equal(await frame.locator(`[data-overview-panel="${id}"]`).isVisible(), true);
    assert.equal(await frame.locator('[data-overview-tab][aria-selected="true"]').count(), 1);
  }
  await frame.locator('[aria-selected="true"]').press("Home");
  assert.equal(await frame.locator('[data-overview-tab="auto-resolution"]').getAttribute("aria-selected"), "true");
  await frame.locator('[aria-selected="true"]').press("ArrowRight");
  assert.equal(await frame.locator('[data-overview-tab="human-touchpoints"]').getAttribute("aria-selected"), "true");
  await frame.evaluate(() => { location.hash = "not-a-view"; });
  await frame.locator("[data-overview-error]").waitFor({ state: "visible" });
  await frame.locator(".oq-skip-link").focus();
  await frame.locator(".oq-skip-link").press("Enter");
  await frame.locator("#auto-resolution").waitFor({ state: "visible" });
  assert.equal(await frame.locator("main").evaluate(el => el === document.activeElement), true);
  await frame.locator("#auto-resolution .oq-inspect").click();
  await frame.getByRole("dialog").waitFor();
  assert.match(await frame.getByRole("dialog").innerText(), /65/);
  await page.keyboard.press("Escape");
  assert.equal(await frame.getByRole("dialog").isVisible(), false);
  assert.equal(await frame.locator("#auto-resolution .oq-inspect").evaluate(el => el === document.activeElement), true);

  frame = await open("control-assurance");
  for (const key of ["rollback", "fpr", "fnr", "cfr"]) {
    await frame.locator("[data-guard-filter]").selectOption(key);
    assert.equal(await frame.locator("[data-guard-key]:visible").count(), 1);
    await frame.locator(`[data-guard-key="${key}"] .oq-inspect`).click();
    await frame.getByRole("dialog").waitFor();
    assert.match(await frame.getByRole("dialog").innerText(), /Current|Baseline|Threshold/);
    await page.keyboard.press("Escape");
  }
  frame = await open("control-assurance", "?guard=unknown");
  assert.equal(await frame.locator("[data-guard-empty]").isVisible(), true);
  await frame.locator("[data-guard-filter]").selectOption("");
  assert.equal(await frame.locator("[data-guard-key]:visible").count(), 4);
  assert.match(await frame.locator("main").innerText(), /Posture unknown/);
  await frame.locator("[data-guard-filter]").selectOption("rollback");
  await frame.locator('a[href^="promotion.html"]').first().click();
  await frame.waitForFunction(() => location.pathname.endsWith("/promotion.html"));
  await page.goBack();
  await frame.waitForFunction(() => document.querySelector("[data-guard-filter]")?.value === "rollback");
  assert.equal(await frame.locator("[data-guard-key]:visible").count(), 1);

  frame = await open("trust-routing");
  for (const id of ["t0", "t1", "t2"]) {
    await frame.locator(`.ov-tier[href="#${id}"]`).click();
    await frame.locator(`[data-overview-panel="${id}"]`).waitFor({ state: "visible" });
    assert.equal(await frame.locator(`.ov-tier[href="#${id}"]`).getAttribute("aria-current"), "page");
  }
  for (const id of ["disagreement", "verifier", "divergence"]) {
    await frame.locator("[data-indicator-filter]").selectOption(id);
    assert.equal(await frame.locator("[data-indicator]:visible").count(), 1);
  }
  assert.match(await frame.locator('[data-indicator="divergence"]').innerText(), /Unknown|Unavailable|Not connected/i);
  frame = await open("trust-routing", "?indicator=unknown");
  assert.equal(await frame.locator("[data-indicator-empty]").isVisible(), true);
  await frame.locator("[data-indicator-filter]").selectOption("");
  assert.equal(await frame.locator("[data-indicator]:visible").count(), 3);
  await frame.evaluate(() => { location.hash = "unknown-tier"; });
  await frame.locator("[data-overview-error]").waitFor({ state: "visible" });
  await frame.locator(".oq-skip-link").focus();
  await frame.locator(".oq-skip-link").press("Enter");
  await frame.locator('[data-overview-panel="t2"]').waitFor({ state: "visible" });
  await frame.locator("[data-indicator-filter]").selectOption("verifier");
  await frame.locator('a[href^="audit.html"]:visible').first().click();
  await frame.waitForFunction(() => location.pathname.endsWith("/audit.html"));
  await page.goBack();
  await frame.waitForFunction(() => document.querySelector("[data-indicator-filter]")?.value === "verifier");

  for (const name of pages) {
    frame = await open(name);
    const result = await geometry(frame);
    assert.equal(result.overflow, false, name);
    assert.equal(result.header, "rgba(0, 0, 0, 0)", name);
    assert.equal(result.missingNames, 0, name);
    assert.ok(result.grid.every(display => display === "grid"), name);
  }
});

test("Cost desktop: selection, all source states, exact plot coordinates and bounded return state", { timeout: 90000 }, async t => {
  const { open, page } = await setup(t);
  let frame = await open("cost-governance");
  await frame.locator("#cost-budget").selectOption("secondary");
  assert.equal(await frame.locator("#budget-current").textContent(), "$1,500");
  assert.equal(await frame.locator("#budget-forecast").textContent(), "Unavailable");
  for (const id of ["resource-efficiency", "optimization-cases", "outcomes", "overview"]) {
    await frame.locator(`[data-overview-tab="${id}"]`).click();
    assert.equal(await frame.locator(`[data-overview-panel="${id}"]`).isVisible(), true);
  }
  await frame.locator('[data-overview-tab="resource-efficiency"]').click();
  const points = await frame.locator(".cg-point").evaluateAll(els => els.map(el => [parseFloat(el.style.left), parseFloat(el.style.bottom)]));
  assert.deepEqual(points, [[12, 80], [35, 26.6667]]);
  await frame.locator("#cost-select-example-storage").focus();
  await frame.locator("#cost-select-example-storage").press("Enter");
  assert.equal(await frame.locator("#cost-select-example-storage").evaluate(el => el === document.activeElement), true);
  await frame.locator("#cost-candidate-evidence > summary").click();
  await frame.locator("#cost-search").fill("database");
  assert.match(await frame.locator("#cost-inspector").innerText(), /outside the current filter/);
  assert.equal(await frame.locator("#cost-candidate-evidence").evaluate(el => el.open), true);
  const record = JSON.parse(await frame.locator("#cost-candidate-evidence pre").textContent());
  assert.equal(record.savings, null);
  assert.equal(record.execution_authority, false);
  const expected = await frame.locator("main").evaluate(el => el.fdaiPreviewState.capture());
  await frame.locator("#cost-correlated-audit").focus();
  await frame.locator("#cost-correlated-audit").press("Enter");
  await frame.waitForFunction(() => location.pathname.endsWith("/audit.html"));
  await page.goBack();
  await frame.waitForFunction(value => JSON.stringify(document.querySelector("main")?.fdaiPreviewState?.capture()) === value, JSON.stringify(expected));
  assert.equal(await frame.locator("#cost-candidate-evidence").evaluate(el => el.open), true);
  assert.equal(await frame.locator("#cost-correlated-audit").evaluate(el => el === document.activeElement), true);
  await page.reload();
  await page.waitForFunction(() => document.querySelector("#preview-frame")?.contentDocument?.querySelector("main")?.fdaiPreviewState);
  frame = await (await page.locator("#preview-frame").elementHandle()).contentFrame();
  await frame.waitForFunction(() => document.querySelector("main")?.fdaiPreviewState);
  assert.deepEqual(await frame.locator("main").evaluate(el => el.fdaiPreviewState.capture()), expected);
  assert.equal(await frame.locator("main").evaluate(el => el === document.activeElement), false);
  assert.equal(await frame.locator("main").evaluate((el, state) => el.fdaiPreviewState.restore({ ...state, query: "x".repeat(201) }), expected), false);

  await frame.locator('[data-overview-tab="optimization-cases"]').click();
  await frame.locator("[data-open-cost-candidate]").first().click();
  assert.equal(await frame.locator("#cost-inspector-title").evaluate(el => el === document.activeElement), true);
  await frame.locator(".cg-provenance > summary").click();
  for (const scenario of ["partial", "empty", "unavailable", "denied", "error", "loading", "available"]) {
    await frame.locator("#cost-scenario").selectOption(scenario);
    assert.equal(await frame.locator("#cost-data").isVisible(), ["partial", "available"].includes(scenario));
    if (!["partial", "available"].includes(scenario)) {
      assert.equal(await frame.locator("#cost-reset-preview").isVisible(), true);
      await frame.locator("#cost-reset-preview").click();
      assert.equal(await frame.locator("#cost-scenario").inputValue(), "available");
      assert.equal(await frame.locator('[data-overview-tab][aria-selected="true"]').evaluate(el => el === document.activeElement), true);
    }
  }
});

test("Overview cache identities, rendering budget and long-content fixtures remain bounded", { timeout: 45000 }, async t => {
  const { open, context } = await setup(t);
  const changed = new Map([
    ["overview-quality.css", "overview-quality-v3"], ["overview-workspace.js", "overview-quality-v2"],
    ["settings-workspace-tabs.js", "overview-quality-v2"], ["cost-governance-preview.css", "overview-quality-v2"],
    ["cost-governance-preview.js", "overview-quality-v2"], ["llm-cost-workspace.css", "overview-quality-v2"],
    ["llm-cost-workspace.js", "overview-quality-v3"],
  ]);
  await context.route("**/assets/**", route => {
    const url = new URL(route.request().url());
    const name = url.pathname.split("/").at(-1);
    if (changed.has(name) && url.searchParams.get("v") !== changed.get(name)) {
      return route.fulfill({ contentType: name.endsWith(".css") ? "text/css" : "text/javascript", body: "/* Retained obsolete payload. */" });
    }
    return route.fallback();
  });
  const samples = [];
  for (const name of pages) {
    const started = performance.now();
    const frame = await open(name);
    const elapsed = performance.now() - started;
    assert.ok(elapsed < 2000, `${name}: ${elapsed}ms`);
    assert.equal(await frame.locator("main").evaluate(el => getComputedStyle(el).maxWidth), "1280px");
    if (await frame.locator("[data-overview-tab]").count()) {
      assert.equal(await frame.locator("main").getAttribute("data-settings-tabs-ready"), "true");
    }
    if (name === "llm-cost") assert.ok(await frame.locator("main").evaluate(el => el.fdaiPreviewState));
    if (name === "cost-governance") {
      await frame.locator('[data-overview-tab="resource-efficiency"]').click();
      const update = performance.now();
      await frame.locator("#cost-search").fill("no-matching-candidate");
      assert.match(await frame.locator("#cost-row-count").textContent(), /No candidate matches/);
      assert.ok(performance.now() - update < 1000);
      await frame.locator("#cost-provenance > summary").click();
    }
    await frame.locator(".oq-page-header p, .ov-evidence span").evaluateAll(els => {
      els.forEach(el => { el.textContent = "Long synthetic resource / 긴 예제 리소스 / " + "opaque-example-identifier".repeat(12); });
    });
    assert.equal((await geometry(frame)).overflow, false, name);
    samples.push({ page: name, initialRenderMs: Math.round(elapsed), longContent: "passed", retainedAssets: "passed" });
  }
  const output = join(root, ".fdai/visual-review/overview-suite-runtime");
  await mkdir(output, { recursive: true });
  await writeFile(join(output, "measurements.json"), JSON.stringify({ venue: "local synthetic master iframe", samples }, null, 2) + "\n");
});

test("Vertical disclosures and shared Settings default behavior keep navigation context", { timeout: 45000 }, async t => {
  const { open, page } = await setup(t);
  const frame = await open("verticals");
  for (const summary of await frame.locator("details > summary").all()) {
    await summary.focus();
    await summary.press("Enter");
  }
  assert.equal(await frame.locator("details[open]").count(), 4);
  await frame.locator(".ov-vertical-link").first().click();
  await frame.waitForFunction(() => !location.pathname.endsWith("/verticals.html"));
  await page.goBack();
  await frame.waitForFunction(() => document.querySelectorAll("details[open]").length === 4);
  const settings = await open("settings-runtime");
  const tabs = settings.locator("[data-settings-tab]");
  assert.ok(await tabs.count() > 1);
  await tabs.last().click();
  assert.equal(await tabs.last().getAttribute("aria-selected"), "true");
  await tabs.last().press("Home");
  assert.equal(await tabs.first().getAttribute("aria-selected"), "true");
});

test("Overview responsive: all panels and expanded evidence reflow with accessible controls", { timeout: 120000 }, async t => {
  const { open, page } = await setup(t);
  for (const width of [993, 390, 372]) {
    await page.setViewportSize({ width, height: width === 993 ? 641 : width === 372 ? 824 : 844 });
    for (const name of pages) {
      const frame = await open(name);
      if (width === 993) {
        const navigation = page.getByRole("button", { name: "Toggle design navigation", exact: true });
        if (await navigation.getAttribute("aria-expanded") === "true") await navigation.click();
      }
      for (const tab of await frame.locator("[data-overview-tab]").all()) {
        await tab.click();
        assert.equal((await geometry(frame)).overflow, false, `${name}/${await tab.textContent()}/${width}`);
      }
      for (const summary of await frame.locator("details:visible > summary").all()) await summary.click();
      assert.equal((await geometry(frame)).overflow, false, `${name}/expanded/${width}`);
      if (width <= 390) {
        const short = await frame.locator("main button:visible, main select:visible, main summary:visible").evaluateAll(els => els.flatMap(el => {
          const box = el.getBoundingClientRect();
          return box.width < 44 || box.height < 44 ? [{ text: el.textContent.trim(), width: box.width, height: box.height }] : [];
        }));
        assert.deepEqual(short, [], `${name}/${width}`);
      }
    }
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  for (const name of pages) {
    const frame = await open(name);
    await frame.locator("main, main *").evaluateAll(els => {
      const sizes = els.map(el => parseFloat(getComputedStyle(el).fontSize));
      els.forEach((el, index) => {
        if (el.closest("svg")) return;
        el.style.setProperty("font-size", `${sizes[index] * 2}px`, "important");
        el.style.setProperty("line-height", "1.5", "important");
        el.style.setProperty("letter-spacing", ".12em", "important");
        el.style.setProperty("word-spacing", ".16em", "important");
        if (el.matches("p")) el.style.setProperty("margin-bottom", "2em", "important");
      });

    });
    for (const tab of await frame.locator("[data-overview-tab]").all()) {
      await tab.click();
      const layout = await geometry(frame);
      assert.equal(layout.overflow, false, `${name}/text/${await tab.textContent()}: ${JSON.stringify(layout)}`);
    }
    for (const summary of await frame.locator("details:visible > summary").all()) await summary.click();
    assert.equal((await geometry(frame)).overflow, false, `${name}/text/expanded`);
    if (name === "llm-cost") {
      await frame.locator(".lc-composition").evaluate(el => el.scrollIntoView({ block: "start" }));
      const output = join(root, ".fdai/visual-review/overview-suite-runtime");
      await mkdir(output, { recursive: true });
      await page.screenshot({ path: join(output, "llm-enlarged.png"), animations: "disabled" });
    }
    await page.emulateMedia({ forcedColors: "active", reducedMotion: "reduce" });
    const control = frame.locator("main button:visible, main summary:visible, main a:visible").first();
    await page.keyboard.press("Tab");
    await control.focus();
    assert.ok(await control.evaluate(el => parseFloat(getComputedStyle(el).outlineWidth) >= 2), name);
    await page.emulateMedia({ forcedColors: "none", reducedMotion: "reduce" });
  }
});

test("Overview required control, focus and chart indicators meet non-text contrast", { timeout: 45000 }, async t => {
  const { open, page } = await setup(t);
  const evidence = [];
  for (const name of pages) {
    const frame = await open(name);
    const control = frame.locator("main button:visible, main summary:visible, main a:visible").first();
    await page.keyboard.press("Tab");
    await control.focus();
    const values = await frame.evaluate(() => {
      const rgb = value => value.match(/[\d.]+/g).map(Number);
      const luminance = value => rgb(value).slice(0, 3).map(v => {
        const n = v / 255;
        return n <= .04045 ? n / 12.92 : ((n + .055) / 1.055) ** 2.4;
      }).reduce((sum, value, index) => sum + value * [.2126, .7152, .0722][index], 0);
      const contrast = (foreground, background) => {
        const a = luminance(foreground), b = luminance(background);
        return (Math.max(a, b) + .05) / (Math.min(a, b) + .05);
      };
      const background = element => {
        for (let el = element; el; el = el.parentElement) {
          const color = getComputedStyle(el).backgroundColor;
          if (rgb(color).length === 3 || rgb(color)[3] === 1) return color;
        }
        return "rgb(255, 255, 255)";
      };
      const measures = [];
      for (const el of document.querySelectorAll(".oq-inspect, .cs-control-select, .cs-control-input, .lc-range-option, main .cs-control-button, .oq-tabs [aria-selected=true]")) {
        if (!el.checkVisibility() || el.disabled) continue;
        const style = getComputedStyle(el);
        measures.push({ kind: "control", id: el.id || el.className, ratio: contrast(style.borderTopColor, background(el)) });
      }
      for (const el of document.querySelectorAll(".ov-chart .line, .cg-trend .line, .lc-chart .line")) {
        if (el.checkVisibility()) measures.push({ kind: "chart", id: el.id || el.className.baseVal, ratio: contrast(getComputedStyle(el).stroke, background(el)) });
      }
      const focused = document.activeElement;
      measures.push({ kind: "focus", id: focused.id, ratio: contrast(getComputedStyle(focused).outlineColor, background(focused.parentElement)) });
      return measures;
    });
    assert.ok(values.length > 0);
    assert.deepEqual(values.filter(value => value.ratio < 3), [], name);
    evidence.push({ page: name, values });
  }
  const output = join(root, ".fdai/visual-review/overview-suite-runtime");
  await mkdir(output, { recursive: true });
  await writeFile(join(output, "contrast.json"), JSON.stringify({
    excluded: "Decorative card borders and grid lines; disabled controls; token mix duplicates exact text and is aria-hidden.",
    evidence,
  }, null, 2) + "\n");
});
