/** Focused browser evidence for the five synthetic Knowledge workspaces. */
import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const require = createRequire(join(root, "console/package.json"));
const { chromium } = require("playwright");
const origin = "http://127.0.0.1:5373";
const routes = ["knowledge", "documents", "github", "gitlab", "azure-devops"];
const output = join(root, ".fdai/visual-review/knowledge-rubric");
const results = [];
const renderBudgetMs = 1500;
const interactionBudgetMs = 250;

await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  viewport: { width: 1440, height: 900 },
  reducedMotion: "reduce",
});
await context.route("**/*", (route) => {
  const url = new URL(route.request().url());
  return url.origin === origin || ["data:", "blob:"].includes(url.protocol)
    ? route.continue()
    : route.abort("blockedbyclient");
});
const page = await context.newPage();
page.setDefaultTimeout(6000);

async function open(route) {
  await page.goto(`${origin}/#mocks/ui/${route}.html`, { waitUntil: "load" });
  await page.waitForFunction((expected) => {
    const preview = document.querySelector("#preview-frame");
    return preview?.contentDocument?.readyState === "complete" &&
      preview.contentWindow.location.pathname === `/mocks/ui/${expected}.html`;
  }, route);
  const frame = await (await page.locator("#preview-frame").elementHandle()).contentFrame();
  await frame.locator("main h1").waitFor();
  return frame;
}

async function measure(frame) {
  return frame.evaluate(() => {
    const visible = (element) => {
      const style = getComputedStyle(element);
      const box = element.getBoundingClientRect();
      return box.width > 0 && box.height > 0 && style.display !== "none" &&
        style.visibility !== "hidden" && style.opacity !== "0" &&
        !element.closest('[hidden], [aria-hidden="true"], .kw-skip');
    };
    const text = [...document.querySelectorAll("body *")].filter((element) =>
      visible(element) &&
      !element.matches("script, style, svg, svg *, option") &&
      [...element.childNodes].some((node) => node.nodeType === Node.TEXT_NODE && node.textContent.trim()),
    );
    const unnamed = [...document.querySelectorAll("a, button, input, select, summary")]
      .filter(visible)
      .filter((element) => !element.getAttribute("aria-label") &&
        !element.getAttribute("aria-labelledby") &&
        !element.labels?.length &&
        !element.textContent.trim());
    return {
      documentWidth: document.documentElement.clientWidth,
      documentScrollWidth: document.documentElement.scrollWidth,
      mainWidth: document.querySelector("main").clientWidth,
      mainScrollWidth: document.querySelector("main").scrollWidth,
      headings: [...document.querySelectorAll("h1, h2, h3")].filter(visible)
        .map((heading) => ({ level: Number(heading.tagName.slice(1)), text: heading.textContent.trim() })),
      smallText: text.filter((element) => parseFloat(getComputedStyle(element).fontSize) < 12)
        .map((element) => element.textContent.trim().slice(0, 80)),
      unnamed: unnamed.length,
    };
  });
}

async function check(name, run) {
  try {
    const evidence = await run();
    results.push({ name, disposition: "passed", evidence });
    console.log(`PASS ${name}`);
  } catch (error) {
    results.push({ name, disposition: "failed", reason: error.message });
    console.error(`FAIL ${name}: ${error.message}`);
    process.exitCode = 1;
  }
}

try {
  await check("Desktop defaults identify every Knowledge route without overflow", async () => {
    const evidence = [];
    for (const route of routes) {
      const errors = [];
      const onPageError = (error) => errors.push(error.message);
      page.on("pageerror", onPageError);
      const frame = await open(route);
      const metrics = await measure(frame);
      assert.equal(errors.length, 0, `${route}: ${errors.join("; ")}`);
      assert.equal(metrics.documentScrollWidth, metrics.documentWidth, `${route}: document overflow`);
      assert.equal(metrics.mainScrollWidth, metrics.mainWidth, `${route}: main overflow`);
      assert.equal(metrics.smallText.length, 0, `${route}: ${metrics.smallText.join(" | ")}`);
      assert.equal(metrics.unnamed, 0, `${route}: unnamed controls`);
      assert.equal(await frame.locator("h1").count(), 1, `${route}: h1 count`);
      assert.equal(await frame.locator('.kw-source-nav [aria-current="page"]').count(), 1, `${route}: current source`);
      metrics.headings.slice(1).forEach((heading, index) => {
        assert.ok(heading.level <= metrics.headings[index].level + 1, `${route}: heading order`);
      });
      const current = frame.locator('.kw-source-nav [aria-current="page"]');
      await current.focus();
      assert.notEqual(await current.evaluate((element) => getComputedStyle(element).outlineStyle), "none");
      await page.screenshot({ path: join(output, `desktop-${route}.png`), fullPage: true });
      evidence.push({ route, metrics });
      page.off("pageerror", onPageError);
    }
    return evidence;
  });

  await check("Overview links reach the exact source route", async () => {
    const frame = await open("knowledge");
    assert.equal(await frame.locator(".kw-source-row").count(), 4);
    await frame.getByRole("link", { name: /GitHub Repository connector/ }).click();
    await page.waitForFunction(() => location.hash.startsWith("#mocks/ui/github.html"));
    const destination = await (await page.locator("#preview-frame").elementHandle()).contentFrame();
    await destination.locator("h1").waitFor();
    assert.match(await destination.locator("h1").innerText(), /GitHub/);
    return { destination: page.url() };
  });

  await check("Connector specimens expose honest state, filtering, selection, and recovery", async () => {
    for (const route of ["github", "gitlab", "azure-devops"]) {
      const frame = await open(route);
      const picker = frame.locator("[data-kw-connector-state]");
      assert.match(await frame.locator("[data-kw-state-region]").innerText(), /not configured/);
      assert.equal(await frame.locator("[data-kw-repository]").count(), 0);
      await picker.selectOption("checking");
      assert.equal(await frame.locator("[data-kw-state-region]").getAttribute("aria-busy"), "true");
      assert.match(await frame.locator("[data-kw-state-region]").innerText(), /Existing evidence remains unchanged/);
      await picker.selectOption("connected");
      assert.equal(await frame.locator("[data-kw-repository]").count(), 3);
      const connectedMetrics = await measure(frame);
      assert.equal(connectedMetrics.documentScrollWidth, connectedMetrics.documentWidth, `${route}: connected overflow`);
      assert.equal(connectedMetrics.smallText.length, 0, `${route}: connected small text`);
      await picker.selectOption("error");
      assert.match(await frame.locator("[data-kw-state-region]").innerText(), /not substituted/);
    }

    const frame = await open("github");
    const picker = frame.locator("[data-kw-connector-state]");
    await picker.selectOption("connected");
    assert.match(await frame.locator(".kw-connected-note").innerText(), /No live provider request was made/);
    const repositories = frame.locator("[data-kw-repository]");
    assert.equal(await repositories.count(), 3);
    await repositories.nth(1).click();
    assert.equal(await repositories.nth(1).getAttribute("aria-pressed"), "true");
    assert.match(await frame.locator("[data-kw-repository-detail]").innerText(), /services\/catalog/);
    await page.screenshot({ path: join(output, "desktop-github-connected.png"), fullPage: true });
    await frame.locator("[data-kw-repository-search]").fill("no matching repository");
    assert.equal(await frame.locator("[data-kw-repository-empty]").isVisible(), true);
    assert.equal(await frame.locator("[data-kw-repository-detail]").isVisible(), false);
    await frame.locator("[data-kw-repository-search]").fill("");
    assert.equal(await frame.locator("[data-kw-repository-detail]").isVisible(), true);

    await picker.selectOption("error");
    const retry = frame.locator("[data-kw-retry]");
    await retry.focus();
    await page.keyboard.press("Enter");
    const region = frame.locator("[data-kw-state-region]");
    assert.equal(await region.evaluate((element) => element === document.activeElement), true);
    await frame.waitForFunction(() =>
      document.querySelector("[data-kw-connector-state]").value === "setup",
    );
    assert.match(await region.innerText(), /not configured/);

    const disclosure = frame.locator(".kw-disclosure");
    await disclosure.locator("summary").focus();
    await page.keyboard.press("Enter");
    assert.equal(await disclosure.getAttribute("open"), "");
    return { connectorRoutes: 3, connectedRecords: 3, recovery: "setup" };
  });

  await check("Documents validates consent without sending data and preserves receipt states", async () => {
    const frame = await open("documents");
    const submit = frame.locator("[data-kw-document-submit]");
    assert.equal(await submit.isDisabled(), true);
    await frame.locator("#document-file").setInputFiles({
      name: "authorized-runbook.pdf",
      mimeType: "application/pdf",
      buffer: Buffer.from("%PDF-1.4 synthetic"),
    });
    assert.equal(await submit.isDisabled(), true);
    await frame.locator("#document-consent").check();
    assert.equal(await submit.isEnabled(), true);
    await submit.click();
    const result = frame.locator("#document-upload-result");
    assert.match(await result.innerText(), /No upload or retention request was sent/);
    assert.equal(await result.evaluate((element) => element === document.activeElement), true);

    const receipt = frame.locator('[data-fg-select="document"]').nth(2);
    await receipt.click();
    assert.equal(await receipt.getAttribute("aria-pressed"), "true");
    assert.equal(await frame.locator("#document-failed-panel").isVisible(), true);
    assert.match(await frame.locator("#document-failed-panel").innerText(), /Content was not retained/);

    const picker = frame.locator("[data-kw-library-state]");
    for (const state of ["loading", "empty", "unavailable"]) {
      await picker.selectOption(state);
      assert.equal(await frame.locator(`[data-kw-library-panel="${state}"]`).isVisible(), true);
      const stateMetrics = await measure(frame);
      assert.equal(stateMetrics.documentScrollWidth, stateMetrics.documentWidth, `documents: ${state} overflow`);
    }
    await frame.locator("[data-kw-library-retry]").click();
    await frame.waitForFunction(() =>
      document.querySelector("[data-kw-library-state]").value === "records",
    );
    assert.equal(await frame.locator('[data-kw-library-panel="records"]').isVisible(), true);
    return { formResult: await result.innerText(), receiptState: "rejected", recovery: "records" };
  });

  await check("Constrained desktop reflows all Knowledge routes", async () => {
    await page.setViewportSize({ width: 993, height: 641 });
    const evidence = [];
    for (const route of routes) {
      const frame = await open(route);
      const metrics = await measure(frame);
      assert.equal(metrics.documentScrollWidth, metrics.documentWidth, `${route}: document overflow`);
      assert.equal(metrics.mainScrollWidth, metrics.mainWidth, `${route}: main overflow`);
      evidence.push({ route, width: metrics.documentWidth });
    }
    return evidence;
  });

  await check("Mobile routes reflow, retain touch targets, and tolerate text spacing", async () => {
    await page.setViewportSize({ width: 390, height: 844 });
    const evidence = [];
    for (const route of routes) {
      const frame = await open(route);
      if (["github", "gitlab", "azure-devops"].includes(route)) {
        await frame.locator("[data-kw-connector-state]").selectOption("connected");
      }
      await frame.addStyleTag({
        content: "p { line-height: 1.5 !important; margin-bottom: 2em !important; letter-spacing: .12em !important; word-spacing: .16em !important; }",
      });
      const metrics = await measure(frame);
      assert.equal(metrics.documentScrollWidth, metrics.documentWidth, `${route}: document overflow`);
      assert.equal(metrics.mainScrollWidth, metrics.mainWidth, `${route}: main overflow`);
      const undersized = await frame.locator("a, button, input, select, summary").evaluateAll((elements) =>
        elements.filter((element) => {
          if (!element.checkVisibility({ checkVisibilityCSS: true, checkOpacity: true })) return false;
          const box = element.getBoundingClientRect();
          if (element.matches('input[type="checkbox"]')) {
            const label = element.closest("label")?.getBoundingClientRect();
            return !label || label.width < 44 || label.height < 44;
          }
          if (element.matches('input[type="file"]')) {
            const label = element.closest("label")?.getBoundingClientRect();
            return !label || label.width < 44 || label.height < 44;
          }
          return box.width < 44 || box.height < 44;
        }).map((element) => element.outerHTML.slice(0, 120)),
      );
      assert.deepEqual(undersized, [], `${route}: undersized targets`);
      evidence.push({ route, width: metrics.documentWidth, targets: "44px minimum" });
    }
    return evidence;
  });

  await check("A 200-percent-equivalent viewport preserves reflow and long content", async () => {
    await page.setViewportSize({ width: 720, height: 900 });
    const evidence = [];
    for (const route of routes) {
      const frame = await open(route);
      const heading = frame.locator("h1 span").last();
      await heading.evaluate((element) => {
        element.textContent += " - 장기 운영 지식 검토 / source-0123456789abcdef0123456789abcdef";
      });
      const metrics = await measure(frame);
      assert.equal(metrics.documentScrollWidth, metrics.documentWidth, `${route}: enlarged equivalent overflow`);
      assert.equal(metrics.mainScrollWidth, metrics.mainWidth, `${route}: enlarged equivalent main overflow`);
      evidence.push({ route, width: metrics.documentWidth });
    }
    return evidence;
  });

  await check("Local rendering and state feedback stay within the declared budget", async () => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const renderStarted = performance.now();
    const frame = await open("github");
    const renderMs = performance.now() - renderStarted;
    const interactionStarted = performance.now();
    await frame.locator("[data-kw-connector-state]").selectOption("connected");
    await frame.locator("[data-kw-repository]").first().waitFor();
    const interactionMs = performance.now() - interactionStarted;
    assert.ok(renderMs <= renderBudgetMs, `render ${renderMs.toFixed(1)}ms exceeds ${renderBudgetMs}ms`);
    assert.ok(interactionMs <= interactionBudgetMs, `interaction ${interactionMs.toFixed(1)}ms exceeds ${interactionBudgetMs}ms`);
    return {
      renderMs: Number(renderMs.toFixed(1)),
      renderBudgetMs,
      interactionMs: Number(interactionMs.toFixed(1)),
      interactionBudgetMs,
    };
  });

  await check("Forced colors preserve current and selected states", async () => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.emulateMedia({ forcedColors: "active", reducedMotion: "reduce" });
    const frame = await open("github");
    const current = frame.locator('.kw-source-nav [aria-current="page"]');
    assert.notEqual((await current.evaluate((element) => getComputedStyle(element).borderColor)), "rgba(0, 0, 0, 0)");
    await frame.locator("[data-kw-connector-state]").selectOption("connected");
    const selected = frame.locator('[data-kw-repository][aria-pressed="true"]');
    assert.notEqual((await selected.evaluate((element) => getComputedStyle(element).outlineStyle)), "none");
    return { forcedColors: "active", reducedMotion: "reduce" };
  });
} finally {
  await writeFile(join(output, "browser-results.json"), `${JSON.stringify(results, null, 2)}\n`);
  await browser.close();
}
