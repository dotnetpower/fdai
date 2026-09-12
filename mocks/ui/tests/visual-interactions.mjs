/** Focused browser regressions for synthetic mock presentation; no live services or actions. */
import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const require = createRequire(join(root, "console/package.json"));
const { chromium } = require("playwright");
const suite = process.argv[2] || "shell";
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, reducedMotion: "reduce" });
await context.route("**/*", route => new URL(route.request().url()).origin === "http://127.0.0.1:5373"
  ? route.continue() : route.abort("blockedbyclient"));
const page = await context.newPage();
page.setDefaultTimeout(5000);
const results = [];
const output = join(root, ".fdai/visual-review", `interactions-${suite}`);
await mkdir(output, { recursive: true });

/** Open the actual root shell and wait for its exact local iframe route. */
async function open(path) {
  await page.goto(`http://127.0.0.1:5373/#mocks/ui/${path}`, { waitUntil: "load" });
  await page.waitForFunction(expected => {
    const frame = document.querySelector("#preview-frame");
    return frame?.contentDocument?.readyState === "complete" &&
      frame.contentWindow.location.pathname === `/mocks/ui/${expected.split("?")[0]}`;
  }, path);
  return (await page.locator("#preview-frame").elementHandle()).contentFrame();
}

async function check(name, run) {
  try {
    await run();
    results.push({ name, disposition: "passed" });
    console.log(`PASS ${name}`);
  } catch (error) {
    results.push({ name, disposition: "failed", reason: error.message });
    console.error(`FAIL ${name}: ${error.message}`);
    process.exitCode = 1;
  }
}

try {
  if (suite === "shell") {
    await check("Shell preserves the preview boundary and title", async () => {
      await open("hil.html");
      assert.match(await page.locator("[data-preview-boundary]").innerText(), /Synthetic preview/);
      assert.match(await page.locator("#preview-frame").getAttribute("title"), /Approvals/);
      assert.equal(await page.locator("#now-path").isVisible(), false);
      assert.equal(await page.locator('.side [aria-current="page"]').count(), 1);
    });
    await check("Search has a visible empty state and restores a filtered route", async () => {
      await open("hil.html?status=pending");
      const search = page.locator("[data-nav-search]");
      await search.fill("no-such-design-preview");
      assert.equal(await page.locator("[data-nav-empty]").isVisible(), true);
      assert.match(await page.locator("[data-nav-result]").textContent(), /0 of 91/);
      assert.equal(await page.locator('.nav-group:visible').count(), 0);
      await page.locator("[data-nav-clear]").click();
      assert.equal(await page.locator('.side [aria-current="page"]').isVisible(), true);
      assert.equal(await search.inputValue(), "");
    });
    await check("Menu navigation supports browser Back and Forward", async () => {
      await open("hil.html");
      await page.locator('[data-page="mocks/ui/incidents.html"]').click();
      await page.waitForFunction(() => location.hash.startsWith("#mocks/ui/incidents.html"));
      await page.goBack();
      await page.waitForFunction(() => location.hash === "#mocks/ui/hil.html");
      assert.equal(await page.locator('.side [aria-current="page"]').getAttribute("data-page"), "mocks/ui/hil.html");
      await page.goForward();
      await page.waitForFunction(() => location.hash.startsWith("#mocks/ui/incidents.html"));
    });
    await check("Unknown and malformed preview routes fail to a local dashboard", async () => {
      for (const hash of ["javascript:alert(1)", "%broken-encoding"]) {
        await page.goto(`http://127.0.0.1:5373/#${hash}`, { waitUntil: "load" });
        await page.waitForFunction(() => location.hash === "#mocks/ui/dashboard.html");
        await page.waitForFunction(() => document.querySelector("#preview-frame").contentWindow.location.pathname === "/mocks/ui/dashboard.html");
        assert.match(await page.locator("#preview-frame").getAttribute("title"), /Dashboard/);
      }
    });
  } else if (suite === "approvals") {
    await check("Approval totals and fixed-time boundary agree with records", async () => {
      const frame = await open("hil.html");
      assert.equal(await frame.locator('[data-approval-total="pending"]').textContent(), "2");
      assert.equal(await frame.locator('[data-approval-total="expired"]').textContent(), "1");
      assert.equal(await frame.locator('[data-approval-state="pending"]').count(), 2);
      assert.equal(await frame.locator('.approval-cutoff time').getAttribute("datetime"), "2026-09-06T04:00:00Z");
      assert.equal(await frame.locator('.approval-meta time:visible').count(), 3);
      assert.equal(await frame.getByRole("button", { name: /^(approve|reject|execute)$/i }).count(), 0);
    });
    await check("Status and query filters compose, recover, and survive reload", async () => {
      let frame = await open("hil.html");
      await frame.locator("[data-approval-status]").selectOption("pending");
      assert.equal(await frame.locator('[data-approval]:not([hidden])').count(), 2);
      await frame.locator("[data-approval-search]").fill("database");
      assert.equal(await frame.locator('[data-approval]:not([hidden])').count(), 1);
      await page.waitForFunction(() => location.hash.includes("q=database") && location.hash.includes("status=pending"));
      await page.reload({ waitUntil: "load" });
      frame = await (await page.locator("#preview-frame").elementHandle()).contentFrame();
      await frame.waitForLoadState("load");
      assert.equal(await frame.locator("[data-approval-search]").inputValue(), "database");
      assert.equal(await frame.locator('[data-approval]:not([hidden])').count(), 1);
      await frame.locator("[data-approval-search]").fill("없는 제안 / no matching record");
      assert.equal(await frame.locator("[data-approval-empty]").isVisible(), true);
      assert.equal(await frame.locator("[data-approval-count]").innerText(), "0 of 3 shown");
      await frame.locator("[data-clear-approvals]").click();
      assert.equal(await frame.locator('[data-approval]:not([hidden])').count(), 3);
      assert.equal(await frame.locator("[data-approval-search]").evaluate(element => element === document.activeElement), true);
    });
    await check("Keyboard disclosure exposes missing safeguards without granting authority", async () => {
      const frame = await open("hil.html");
      const disclosure = frame.locator("[data-approval] details").first();
      await frame.locator("[data-approval] summary").first().focus();
      await page.keyboard.press("Enter");
      assert.equal(await disclosure.getAttribute("open"), "");
      const text = await disclosure.innerText();
      for (const name of ["Rollback", "Stop condition", "Blast radius", "Dry-run receipt", "Logical-target lock", "Stable idempotency key", "Two-phase audit", "Required quorum", "Independent effect observation"]) assert.ok(text.includes(name), name);
      assert.match(text, /self-approval is never allowed/);
      assert.match(text, /cannot authorize a change/);
      assert.ok(await frame.locator("[data-approval] summary").first().evaluate(element => getComputedStyle(element).outlineStyle !== "none"));
    });
  } else if (suite === "overview") {
    await check("Outcome comparison has two primary and five balanced supporting metrics", async () => {
      const frame = await open("operating-outcomes.html");
      const boxes = await frame.locator("#auto-resolution .cs-metric-link").evaluateAll(elements => elements.map(element => {
        const box = element.getBoundingClientRect(); return { y: box.y, width: box.width };
      }));
      assert.equal(boxes.length, 7);
      assert.equal(boxes[0].y, boxes[1].y);
      assert.equal(new Set(boxes.slice(2).map(box => box.y)).size, 1);
      assert.ok(boxes[0].width > boxes[2].width);
      await frame.locator('[data-overview-tab="cost-per-resolved-event"]').click();
      assert.equal(await frame.locator('[data-overview-panel="cost-per-resolved-event"]').isVisible(), true);
      assert.match(await frame.locator('[data-overview-panel="cost-per-resolved-event"]').innerText(), /unavailable|not connected/i);
    });
    for (const [path, selector] of [
      ["control-assurance.html", ".ov-guard-name small, .oq-guard-values"],
      ["trust-routing.html", ".ov-route-step"],
      ["verticals.html", ".ov-vertical-purpose, .ov-status"],
      ["llm-cost.html", ".lc-timezone, .lc-range-option"],
      ["provision.html", ".pv-label, .pv-status"],
      ["onboarding.html", ".ob-count"],
    ]) await check(`${path} uses readable operational annotations`, async () => {
      const frame = await open(path);
      const sizes = await frame.locator(selector).evaluateAll(elements => elements.map(element => parseFloat(getComputedStyle(element).fontSize)));
      assert.ok(sizes.length > 0);
      assert.ok(sizes.every(size => size >= 13), JSON.stringify(sizes));
    });
    await check("Incident action text contrasts with its dark surface", async () => {
      const frame = await open("incidents.html");
      const style = await frame.locator(".in-intervene-button").first().evaluate(element => ({ color: getComputedStyle(element).color, background: getComputedStyle(element).backgroundColor }));
      assert.equal(style.color, "rgb(255, 255, 255)");
      assert.equal(style.background, "rgb(64, 64, 64)");
    });
  } else if (suite === "graphs") {
    await check("Semantic model keeps exact types and independent reference views", async () => {
      const frame = await open("ontology.html");
      const count = await frame.locator("[data-ontology-node]").count();
      assert.ok(count >= 20);
      await frame.locator('[data-ontology-node="ArchitectureConstraint"]').click();
      assert.match(await frame.locator("[data-ontology-inspector]").innerText(), /ArchitectureConstraint/);
      const code = frame.locator('[data-ontology-node="ArchitectureConstraint"] code');
      const box = await code.evaluate(element => ({ font: parseFloat(getComputedStyle(element).fontSize), width: element.clientWidth, scroll: element.scrollWidth, height: element.getBoundingClientRect().height }));
      assert.ok(box.font >= 13 && box.scroll <= box.width + 1 && box.height <= 40);
      await frame.locator('[data-ontology-lens="state"]').click();
      assert.equal(await frame.locator("[data-ontology-node]").count(), count);
      await frame.locator('[data-ontology-tab="instances"]').click();
      assert.match(await frame.locator('[data-ontology-view="instances"]').innerText(), /No runtime claim/);
    });
    await check("Instance graph preserves source identity and readable inspector facts", async () => {
      const frame = await open("ontology-instances-2d.html");
      await frame.locator("#oi-search").fill("state-db");
      assert.equal(await frame.locator("#oi-directory button").count(), 1);
      await frame.locator("#oi-directory button").click();
      assert.match(await frame.locator(".oi-inspector").innerText(), /state-db/);
      assert.ok(await frame.locator(".oi-facts dt").first().evaluate(element => parseFloat(getComputedStyle(element).fontSize) >= 13));
      assert.ok(await frame.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth));
    });
  } else if (suite === "agents") {
    await check("Fleet keeps all fixed agents and distinguishes evidence states", async () => {
      const frame = await open("agents.html");
      assert.equal(await frame.locator(".fl-card").count(), 15);
      await frame.locator("#fleetSearch").fill("Forseti");
      assert.equal(await frame.locator(".fl-card").count(), 1);
      await frame.locator("#fleetClear").click();
      assert.equal(await frame.locator(".fl-card").count(), 15);
      assert.ok(await frame.locator(".ap-check").evaluate(element => element.getBoundingClientRect().height >= 44));
      await frame.locator("#previewState").selectOption("loading");
      assert.equal(await frame.locator(".ap-skeleton").isVisible(), true);
      assert.equal(await frame.locator("#previewSourceState").getAttribute("aria-busy"), "true");
      await frame.locator("#previewState").selectOption("unobserved");
      assert.equal(await frame.locator(".fl-card").count(), 15);
      assert.match(await frame.locator(".fl-card").first().innerText(), /Unavailable without a runtime signal/);
    });
    await check("Organization selection preserves accountable roles", async () => {
      const frame = await open("agents-constellation.html");
      assert.equal(await frame.locator("#orgTree [data-agent]").count(), 15);
      await frame.locator('#orgTree [data-agent="forseti"]').click();
      assert.match(await frame.locator("#agentFocus").innerText(), /Forseti/);
      assert.match(await frame.locator("#agentFocus").innerText(), /Judge/);
    });
    await check("Activity columns have full label targets and preserve the journal", async () => {
      const frame = await open("agent-activity.html");
      const count = await frame.locator("#activityRows tr").count();
      assert.ok(count > 0);
      await frame.locator("#activityColumns summary").click();
      assert.ok(await frame.locator(".ap-column-menu label").evaluateAll(elements => elements.every(element => element.getBoundingClientRect().height >= 44)));
      await frame.locator('.ap-column-menu input[value="type"]').check();
      assert.equal(await frame.locator('#activityTable th[data-column="type"]').isVisible(), true);
      assert.equal(await frame.locator("#activityRows tr").count(), count);
    });
  } else if (suite === "operations") {
    await check("Dense scheduler records keep labels and truthful filtered results", async () => {
      const frame = await open("scheduler-runs.html");
      await frame.locator('[data-operator-ready="true"]').waitFor();
      const rows = frame.locator("#scheduler-dispatch-history tbody tr");
      assert.equal(await rows.count(), 4);
      assert.equal(await rows.first().evaluate(element => getComputedStyle(element).display), "grid");
      assert.ok(await rows.first().locator("td").evaluateAll(elements => elements.every(element => element.dataset.label && element.getBoundingClientRect().width > 200)));
      await frame.locator("#scheduler-query input").fill("unknown-task");
      await frame.locator("#scheduler-query button[type=submit]").click();
      assert.equal(await frame.locator("#scheduler-dispatch-history tbody tr:not([hidden])").count(), 0);
      assert.match(await frame.locator("[data-op-query-result]").innerText(), /No ledger request was made/);
      assert.equal(await frame.locator(".cp-kpis").isVisible(), false);
    });
    await check("Process workspace preserves selection and explicit loading/error/empty states", async () => {
      const frame = await open("processes.html");
      await frame.locator('[data-operator-ready="true"]').waitFor();
      const records = frame.locator("[data-op-record]");
      await records.nth(1).click();
      assert.equal(await records.nth(1).getAttribute("aria-pressed"), "true");
      const preview = frame.locator(".op-preview-state select");
      await preview.selectOption("loading");
      assert.equal(await frame.locator(".op-state .cs-state-loading-lines").isVisible(), true);
      for (const [mode, pattern] of [["unavailable", /Missing evidence is not zero/], ["error", /No successful result/], ["empty", /not proof of absence/]]) {
        await preview.selectOption(mode);
        assert.match(await frame.locator(".op-state").innerText(), pattern);
        assert.equal(await frame.locator("[data-op-content]").isVisible(), false);
      }
      await preview.selectOption("sample-data");
      assert.equal(await frame.locator("[data-op-content]").isVisible(), true);
    });
  } else if (suite === "governance") {
    for (const name of ["handover", "rules", "workflow-builder", "capabilities", "skills", "blast-radius", "promotion", "context-selection-comparisons", "scope", "audit", "browser-evidence", "forecast-learning", "conversation-search", "conversation-assurance", "reports", "rule-trace", "rca", "documents"]) {
      await check(`${name} keeps readable facts and selectable evidence`, async () => {
        const frame = await open(`${name}.html`);
        const metrics = await frame.locator(".fg-metric strong").evaluateAll(elements => elements.map(element => ({ height: element.getBoundingClientRect().height, line: parseFloat(getComputedStyle(element).lineHeight), width: element.clientWidth, scroll: element.scrollWidth })));
        assert.ok(metrics.every(metric => metric.height <= metric.line * 2 + 1 && metric.scroll <= metric.width + 1), JSON.stringify(metrics));
        const buttons = frame.locator("[data-fg-select]");
        if (await buttons.count() > 1) {
          const second = buttons.nth(1);
          const group = await second.getAttribute("data-fg-select");
          await second.click();
          assert.equal(await second.getAttribute("aria-pressed"), "true");
          assert.equal(await frame.locator(`[data-fg-select="${group}"][aria-pressed="true"]`).count(), 1);
        }
        assert.ok(await frame.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth));
      });
    }
    await check("Static report form reports no request instead of a false render receipt", async () => {
      const frame = await open("reports.html");
      await frame.locator("form[data-fg-static-form] button[type=submit]").click();
      assert.match(await frame.locator(".fg-form-result").innerText(), /No request was sent/);
      assert.match(await frame.locator(".report-mini-bars").getAttribute("aria-label"), /recorded measurements are unavailable/);
    });
    await check("Forecast bars have real geometry and an explicit measurement limitation", async () => {
      const frame = await open("forecast-learning.html");
      const heights = await frame.locator(".forecast-bar i").evaluateAll(elements => elements.map(element => element.getBoundingClientRect().height));
      assert.equal(heights.length, 5);
      assert.ok(heights.every(height => height > 30));
      assert.match(await frame.locator(".chart-source-limit").innerText(), /Source values and units were not recorded/);
    });
    await check("Clipboard denial never displays a success receipt", async () => {
      const frame = await open("rule-trace.html");
      await frame.evaluate(() => Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: () => Promise.reject(new Error("Denied for regression test")) } }));
      await frame.locator("[data-fg-copy]").click();
      assert.match(await frame.locator(".fg-copy-result").innerText(), /Copy unavailable/);
      assert.doesNotMatch(await frame.locator(".fg-copy-result").innerText(), /Copied/);
    });
  } else if (suite === "remaining") {
    for (const name of ["settings", "settings-models", "settings-runtime", "settings-memory", "settings-iam", "settings-integrations", "settings-diagnostics"]) {
      await check(`${name} aligns to the shared workspace and changes views`, async () => {
        const frame = await open(`${name}.html`);
        assert.ok(await frame.locator("h1").evaluate(element => Math.abs(element.getBoundingClientRect().x - 24) <= 1));
        const tabs = frame.locator('[role="tab"]');
        if (await tabs.count() > 1) {
          await tabs.nth(1).click();
          assert.equal(await tabs.nth(1).getAttribute("aria-selected"), "true");
          const panel = await tabs.nth(1).getAttribute("aria-controls");
          if (panel) assert.equal(await frame.locator(`#${panel}`).isVisible(), true);
        }
      });
    }
    await check("Integration guide loads all local images without accepting a secret", async () => {
      const frame = await open("settings-integrations.html");
      await frame.locator('[data-integration-tab="teams-workflows"]').click();
      await frame.locator('[data-teams-workflow-ready="true"]').waitFor();
      await frame.locator(".tw-guide summary").click();
      const images = frame.locator(".tw-guide img");
      assert.ok(await images.count() >= 8);
      for (const image of await images.all()) {
        await image.scrollIntoViewIfNeeded();
        await image.evaluate(element => element.decode());
        assert.ok(await image.evaluate(element => element.naturalWidth > 0));
      }
      assert.equal(await frame.locator("#tw-webhook-url").isDisabled(), true);
    });
    await check("Nested kit rail collapses without losing its preview", async () => {
      const frame = await open("index.html");
      assert.equal(await frame.locator(".side").isVisible(), false);
      await frame.locator(".kit-toggle").click();
      assert.equal(await frame.locator(".side").isVisible(), true);
      await frame.locator(".kit-toggle").click();
      assert.equal(await frame.locator(".preview iframe").isVisible(), true);
    });
    for (const path of ["ui-webgl/index.html", "ui-webgl/dashboard.html", "ui-cells/index.html"]) await check(`${path} explains blocked graphics dependencies`, async () => {
      await page.goto(`http://127.0.0.1:5373/#mocks/${path}`, { waitUntil: "load" });
      const frame = await (await page.locator("#preview-frame").elementHandle()).contentFrame();
      await frame.locator("[data-experiment-fallback]").waitFor({ timeout: 8000 });
      assert.match(await frame.locator("[data-experiment-fallback]").innerText(), /not an operational surface/);
      assert.equal(await frame.locator("#loading").isVisible(), false);
      assert.match(await frame.locator("[data-experiment-fallback] a").getAttribute("href"), /ontology-instances-2d/);
    });
  } else if (suite === "responsive") {
    await check("Mobile navigation opens, closes with Escape, and returns keyboard focus", async () => {
      await page.setViewportSize({ width: 390, height: 844 });
      await open("hil.html");
      const toggle = page.locator("[data-nav-toggle]");
      assert.equal(await page.locator("#master-nav").isVisible(), false);
      await toggle.click();
      assert.equal(await toggle.getAttribute("aria-expanded"), "true");
      await page.keyboard.press("Escape");
      assert.equal(await page.locator("#master-nav").isVisible(), false);
      assert.equal(await toggle.evaluate(element => element === document.activeElement), true);
      await toggle.click();
      await page.locator('[data-page="mocks/ui/incidents.html"]').click();
      assert.equal(await page.locator("#master-nav").isVisible(), false);
    });
    await check("Mobile approval facts fit long bilingual content and keep touch targets", async () => {
      const frame = await open("hil.html");
      await frame.locator("[data-approval] summary").first().click();
      await frame.locator("[data-approval] .cp-facts dd").first().evaluate(element => { element.textContent = "example-approval-for-a-long-resource-identifier-2026-09-07-한글-근거-확인"; });
      assert.ok(await frame.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth));
      const summary = await frame.locator("[data-approval] summary").first().boundingBox();
      assert.ok(summary.height >= 44);
      const totals = await frame.locator(".approval-summary dd").evaluateAll(elements => elements.map(element => element.getBoundingClientRect().y));
      assert.ok(Math.max(...totals) - Math.min(...totals) <= 1);
    });
    await check("Mobile activity column popup remains entirely inside the viewport", async () => {
      const frame = await open("agent-activity.html");
      await frame.locator("#activityColumns summary").click();
      const box = await frame.locator(".ap-column-menu").evaluate(element => ({ left: element.getBoundingClientRect().left, right: element.getBoundingClientRect().right, width: innerWidth }));
      assert.ok(box.left >= 0 && box.right <= box.width, JSON.stringify(box));
      await frame.locator('.ap-column-menu input[value="type"]').check();
      assert.equal(await frame.locator('#activityTable th[data-column="type"]').isVisible(), true);
    });
    await check("Desktop comparison remains accepted after responsive edits", async () => {
      await page.setViewportSize({ width: 1440, height: 900 });
      const frame = await open("hil.html");
      assert.ok(await frame.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth));
      const third = await frame.locator("[data-approval] h2").nth(2).boundingBox();
      assert.ok(third.y < 900);
      const summary = await frame.locator("[data-approval] summary").first().evaluate(element => ({ animation: getComputedStyle(element).animationName, font: parseFloat(getComputedStyle(element).fontSize) }));
      assert.equal(summary.animation, "none");
      assert.ok(summary.font >= 13);
    });
  } else if (suite === "incident") {
    await check("Incident citations reveal exact nested evidence and preserve uncertainty", async () => {
      const frame = await open("incident-conversation.html");
      await frame.locator('a[href="#routing-evidence"]').click();
      assert.equal(await frame.locator("#incident-evidence").getAttribute("open"), "");
      await frame.locator('#routing-evidence a[href="#audit-68882"]').click();
      assert.equal(await frame.locator("#audit-68882").getAttribute("open"), "");
      assert.match(await frame.locator("#audit-68882").innerText(), /No current binding readback/);
      assert.match(await frame.locator(".ic-state-line").innerText(), /Current status unknown/);
    });
    await check("Incident preview renders typed text literally and never invents an answer", async () => {
      const frame = await open("incident-conversation.html");
      await frame.locator("#incident-question").fill('<img src=x onerror=alert(1)> 근거를 확인해 주세요');
      await frame.locator("#incident-question-form button").click();
      assert.equal(await frame.locator(".ic-preview-question img").count(), 0);
      assert.match(await frame.locator(".ic-preview-question").innerText(), /<img src=x/);
      assert.match(await frame.locator("#preview-status").innerText(), /No request was sent/);
      assert.equal(await frame.locator(".ic-answer").count(), 1);
    });
  } else {
    throw new Error(`Unknown visual interaction suite: ${suite}`);
  }
  await page.screenshot({ path: join(output, "final.png"), animations: "disabled" });
} finally {
  await writeFile(join(output, "results.json"), JSON.stringify({ suite, scope: "synthetic-local-mocks", results }, null, 2) + "\n");
  await browser.close();
}
