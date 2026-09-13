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
let navigationSequence = 0;

/** Open the actual root shell and wait for its exact local iframe route. */
async function open(path) {
  navigationSequence += 1;
  await page.goto(`http://127.0.0.1:5373/?interaction=${suite}-${navigationSequence}#mocks/ui/${path}`, {
    waitUntil: "load",
  });
  await page.waitForFunction(expected => {
    const frame = document.querySelector("#preview-frame");
    return frame?.contentDocument?.readyState === "complete" &&
      frame.contentWindow.location.pathname === `/mocks/ui/${expected.split("?")[0]}`;
  }, path, { timeout: 10000 });
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
      assert.match(await page.locator("[data-nav-result]").textContent(), /0 of 102/);
      assert.equal(await page.locator('.nav-group:visible').count(), 0);
      await page.locator("[data-nav-clear]").click();
      assert.equal(await page.locator('.side [aria-current="page"]').isVisible(), true);
      assert.equal(await search.inputValue(), "");
    });
    await check("Menu navigation supports browser Back and Forward", async () => {
      await open("hil.html");
      await page.locator('[data-page="mocks/ui/incidents.html"]:visible').click();
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
      await frame.locator('[data-ontology-tab="instances"]').evaluate(element => element.click());
      await frame.locator(".flow-ontology-embed").waitFor({ state: "visible" });
      const instanceFrame = frame.locator(".flow-ontology-embed");
      assert.equal(await instanceFrame.isVisible(), true);
      const embedded = await (await instanceFrame.elementHandle()).contentFrame();
      assert.match(await embedded.locator("#oi-stage-title").innerText(), /checkout-api/);
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
      const measures = await frame.locator("#previewState, #fleetClear, .fl-summary").evaluateAll(elements => {
        const channels = color => (color.match(/[\d.]+/g) || [0, 0, 0]).slice(0, 3).map(Number);
        const luminance = color => channels(color).map(value => {
          const normalized = value / 255;
          return normalized <= .04045 ? normalized / 12.92 : ((normalized + .055) / 1.055) ** 2.4;
        }).reduce((total, value, index) => total + value * [.2126, .7152, .0722][index], 0);
        const contrast = (first, second) => {
          const a = luminance(first), b = luminance(second);
          return (Math.max(a, b) + .05) / (Math.min(a, b) + .05);
        };
        return elements.filter(element => element.checkVisibility()).map(element => {
          const style = getComputedStyle(element);
          return {
            selector: element.id || element.className,
            ratio: contrast(style.borderTopColor, style.backgroundColor),
            borderWidth: parseFloat(style.borderTopWidth),
          };
        });
      });
      assert.ok(measures.every(item => item.borderWidth >= 1 && item.ratio >= 3), JSON.stringify(measures));
      await frame.locator(".ap-provenance summary").focus();
      await page.keyboard.press("Tab");
      assert.equal(await frame.locator("#previewState").evaluate(element => element === document.activeElement), true);
      await page.waitForTimeout(50);
      const focus = await frame.locator("#previewState").evaluate(element => {
        const style = getComputedStyle(element);
        return { focusVisible: element.matches(":focus-visible"), width: parseFloat(style.outlineWidth), style: style.outlineStyle };
      });
      assert.ok(focus.focusVisible && focus.width >= 2 && focus.style !== "none", JSON.stringify(focus));
      assert.equal(await frame.locator(".fl-card").count(), 15);
      assert.equal(await frame.locator(".fl-card .ap-actions .ap-button").first().innerText(), "Agent focus");
      assert.equal(await frame.locator(".fl-card .ap-state").first().innerText(), "Idle");
      await frame.locator(".fl-details summary").first().click();
      assert.match(await frame.locator(".fl-details").first().innerText(), /Runtime binding/);
      await frame.locator(".ap-provenance summary").click();
      assert.match(await frame.locator(".ap-provenance").innerText(), /No backend, live model, or executor is connected/);
      const ask = frame.getByRole("button", { name: "Ask Odin in preview" });
      await ask.click();
      assert.match(await frame.locator("#agentsPreviewDialog").innerText(), /grants no authority/);
      await frame.locator("#agentsPreviewDialog button").click();
      assert.equal(await ask.evaluate(element => element === document.activeElement), true);
      const filterMs = await frame.locator("#fleetSearch").evaluate(async element => {
        const started = performance.now();
        element.value = "Forseti";
        element.dispatchEvent(new Event("input", { bubbles: true }));
        await new Promise(requestAnimationFrame);
        return performance.now() - started;
      });
      assert.ok(filterMs < 100, `Fleet filter took ${filterMs.toFixed(1)}ms`);
      assert.equal(await frame.locator(".fl-card").count(), 1);
      await frame.locator("#fleetClear").click();
      assert.equal(await frame.locator(".fl-card").count(), 15);
      await frame.locator("#fleetSearch").fill("no-such-agent");
      await frame.locator("[data-clear-fleet]").click();
      assert.equal(await frame.locator("#fleetSearch").evaluate(element => element === document.activeElement), true);
      assert.equal(await frame.locator(".fl-card").count(), 15);
      assert.ok(await frame.locator(".ap-check").evaluate(element => element.getBoundingClientRect().height >= 44));
      await frame.locator('[data-summary-state="engaged"]').click();
      assert.match(await frame.locator('[data-summary-state="engaged"]').evaluate(element => getComputedStyle(element).boxShadow), /inset/);
      await frame.locator('[data-summary-state="engaged"]').click();
      await frame.locator("#previewState").selectOption("disconnected");
      assert.match(await frame.locator("#previewSourceLabel").innerText(), /Disconnected/);
      assert.match(await frame.locator(".fl-card .ap-state").first().innerText(), /^Last:/);
      await frame.locator("#previewState").selectOption("loading");
      assert.equal(await frame.locator(".ap-skeleton").isVisible(), true);
      assert.equal(await frame.locator("#previewSourceState").getAttribute("aria-busy"), "true");
      await frame.locator("#previewState").selectOption("unobserved");
      assert.equal(await frame.locator(".fl-card").count(), 15);
      assert.match(await frame.locator(".fl-card").first().innerText(), /Unavailable without a runtime signal/);
      await frame.locator("#previewState").selectOption("error");
      assert.match(await frame.locator("#previewSourceState").innerText(), /Evidence source unavailable/);
      await frame.locator("[data-restore-preview]").click();
      assert.equal(await frame.locator("#previewState").inputValue(), "snapshot");
      assert.equal(await frame.locator("#previewState").evaluate(element => element === document.activeElement), true);
    });
    await check("Organization selection preserves accountable roles", async () => {
      const frame = await open("agents-constellation.html");
      assert.equal(await frame.locator("#orgTree [data-agent]").count(), 15);
      await frame.locator('#orgTree [data-agent="forseti"]').click();
      assert.match(await frame.locator("#agentFocus").innerText(), /Forseti/);
      assert.match(await frame.locator("#agentFocus").innerText(), /Judge/);
      assert.match(await frame.locator(".ap-incident").first().innerText(), /^Investigating/);
      assert.match(await frame.locator(".ap-incident").first().innerText(), /High severity/);
      await frame.locator("#incidentList .ap-incident").nth(1).click();
      assert.equal(await frame.locator("#incidentList .ap-incident").nth(1).evaluate(element => element === document.activeElement), true);
      assert.match(await frame.locator("#incidentWorkflow").innerText(), /SAMPLE-103/);
      await frame.locator('#orgTree [data-agent="forseti"]').focus();
      await page.keyboard.press("ArrowDown");
      assert.equal(await frame.locator('#orgTree [data-agent="huginn"]').evaluate(element => element === document.activeElement), true);
      await frame.locator('#orgTree [data-agent="forseti"]').click();
      await frame.locator("[data-close-focus]").click();
      assert.equal(await frame.locator('#orgTree [data-agent="forseti"]').evaluate(element => element === document.activeElement), true);
      await frame.locator("#previewState").selectOption("loading");
      assert.equal(await frame.locator("#orgWorkspace").isVisible(), false);
      await frame.locator("#previewState").selectOption("unobserved");
      assert.equal(await frame.locator("#orgTree [data-agent]").count(), 15);
      assert.match(await frame.locator("#incidentWorkflow").innerText(), /No incident evidence is available/);
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
      await page.keyboard.press("Escape");
      assert.equal(await frame.locator("#activityColumns").getAttribute("open"), null);
      assert.equal(await frame.locator("#activityColumns summary").evaluate(element => element === document.activeElement), true);
      await frame.locator("#activityAppend").click();
      assert.equal(await frame.locator("#activityRows tr").count(), count + 1);
      await frame.locator("#activityKeywordFilter").fill("no-such-activity");
      assert.equal(await frame.locator("#activityLogEmpty").isVisible(), true);
      await frame.locator("#activityClear").click();
      assert.equal(await frame.locator("#activityRows tr").count(), count + 1);
      await frame.locator("#activityFullscreen").click();
      await frame.locator("#activityFullscreen[aria-pressed='true']").waitFor();
      await frame.locator("#activityFullscreen").click();
      await frame.locator("#activityFullscreen[aria-pressed='false']").waitFor();
      assert.equal(await frame.locator("#activityFullscreen").evaluate(element => element === document.activeElement), true);
      await page.waitForTimeout(100);
      await frame.getByRole("button", { name: "Waterfall" }).click();
      const firstStep = frame.locator("[data-step]").first();
      await firstStep.click();
      assert.equal(await frame.locator("#activityStep").isVisible(), true);
      assert.equal(await frame.locator("#activityStep h2").evaluate(element => element === document.activeElement), true);
      await frame.locator("[data-close-step]").click();
      assert.equal(await firstStep.evaluate(element => element === document.activeElement), true);
      await frame.locator("#previewState").selectOption("error");
      assert.equal(await frame.locator("#activityWaterfallView").isVisible(), true);
      assert.match(await frame.locator("#activityWaterfallView").innerText(), /No audit records in this selection/);
      await frame.locator("[data-restore-preview]").click();
      assert.equal(await frame.locator("#previewState").inputValue(), "snapshot");
    });
    await check("Agent routes reflow through constrained and mobile containers", async () => {
      for (const viewport of [{ width: 993, height: 641 }, { width: 390, height: 844 }, { width: 320, height: 844 }]) {
        await page.setViewportSize(viewport);
        for (const path of ["agents.html", "agents-constellation.html", "agent-activity.html"]) {
          const frame = await open(path);
          assert.ok(await frame.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth), `${path} at ${viewport.width}px`);
        }
      }
      const frame = await open("agents.html");
      await frame.locator(".fl-card .fl-work strong").first().evaluate(element => {
        element.textContent = "example-agent-observation-correlation-00000000000000000000000000000000-한글-장문-근거";
      });
      const spacingOverride = await frame.addStyleTag({ content: "* { line-height: 1.5 !important; letter-spacing: .12em !important; word-spacing: .16em !important; } p { margin-bottom: 2em !important; }" });
      assert.ok(await frame.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth));
      const touchTargets = await frame.locator("button, select, input:not([type=checkbox]), summary, .ap-button, .cs-subnav a").evaluateAll(elements =>
        elements.filter(element => element.checkVisibility()).map(element => ({
          text: (element.textContent || element.getAttribute("aria-label") || "").trim(),
          height: element.getBoundingClientRect().height,
        })));
      assert.ok(touchTargets.every(target => target.height >= 44), JSON.stringify(touchTargets.filter(target => target.height < 44)));
      await spacingOverride.evaluate(element => element.remove());
      await page.setViewportSize({ width: 1440, height: 900 });
      await page.emulateMedia({ forcedColors: "active", reducedMotion: "reduce" });
      const desktop = await open("agents.html");
      assert.ok(await desktop.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth));
      await desktop.locator('[data-summary-state="engaged"]').click();
      assert.notEqual(await desktop.locator('[data-summary-state="engaged"]').evaluate(element => getComputedStyle(element).outlineStyle), "none");
      await desktop.locator('[data-summary-state="engaged"]').click();
      await page.emulateMedia({ forcedColors: "none", reducedMotion: "reduce" });
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
    const governanceNames = ["architecture", "ontology", "handover", "rules", "workflow-builder", "capabilities", "skills", "blast-radius", "promotion", "context-selection-comparisons", "scope"];
    for (const name of [...governanceNames, "audit", "browser-evidence", "forecast-learning", "conversation-search", "conversation-assurance", "reports", "rule-trace", "rca", "documents"]) {
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
        if (governanceNames.includes(name)) {
          assert.ok(await buttons.evaluateAll(elements => elements.every(element => {
            const panel = document.getElementById(element.getAttribute("aria-controls"));
            return panel?.getAttribute("aria-labelledby") === element.id;
          })));
          if (name === "handover") {
            assert.ok(await frame.locator("[data-oversight-agent]").evaluateAll(elements => elements.every(element => {
              return document.getElementById(element.getAttribute("aria-controls"))?.hasAttribute("aria-live");
            })));
          }
        }
        assert.ok(await frame.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth));
      });
    }
    await check("Architecture exposes one ordered typed path and a real drill-down", async () => {
      const frame = await open("architecture.html");
      assert.equal(await frame.locator(".cp-node:visible").count(), 5);
      assert.equal(await frame.locator(".cp-network-edge:visible").count(), 4);
      assert.deepEqual(await frame.locator(".cp-network-edge:visible > span").allTextContents(), ["routes_to", "traverses", "reaches", "depends_on"]);
      assert.match(await frame.locator("#architecture-runtime-relationship").innerText(), /Front Door[\s\S]*traverses[\s\S]*Private Link/);
      assert.equal(await frame.getByRole("link", { name: "Open Service map" }).getAttribute("href"), "service-map.html");
      await frame.getByRole("tab", { name: "Authority boundary" }).click();
      assert.match(await frame.locator("#architecture-authority-lanes").innerText(), /Read plane[\s\S]*Change plane/);
      await frame.getByRole("tab", { name: "Effect verification" }).click();
      assert.match(await frame.locator("#architecture-effect-path").innerText(), /ExpectedEffect[\s\S]*ObservedOutcome/);
      await page.waitForFunction(() => location.hash.includes("lens=effect"));
    });
    await check("Ontology selection and view changes remain keyboard operable", async () => {
      const frame = await open("ontology.html?view=map");
      const stateLens = frame.getByRole("button", { name: "State" });
      await stateLens.focus();
      await page.keyboard.press("Enter");
      assert.equal(await stateLens.getAttribute("aria-pressed"), "true");
      assert.equal(await frame.locator(".ontology-semantic-state").isVisible(), true);
      const resource = frame.getByRole("button", { name: /Resource 5 relationships/ });
      await resource.focus();
      await page.keyboard.press("Enter");
      assert.equal(await resource.getAttribute("aria-pressed"), "true");
      const actions = frame.getByRole("link", { name: /Actions 42/ });
      await actions.focus();
      assert.equal(await actions.evaluate(element => element === document.activeElement), true);
      await actions.evaluate(element => element.click());
      await page.waitForFunction(() => location.hash.includes("view=actions"));
      await page.reload({ waitUntil: "load" });
      await page.waitForFunction(() => {
        const preview = document.querySelector("#preview-frame");
        return preview?.contentDocument?.readyState === "complete" &&
          preview?.contentWindow.location.search.includes("view=actions");
      }, undefined, { timeout: 10000 });
      const refreshed = await (await page.locator("#preview-frame").elementHandle()).contentFrame();
      assert.equal(await refreshed.locator('[data-ontology-view="actions"]').isVisible(), true);
      assert.match(await refreshed.evaluate(() => location.search), /view=actions/);
    });
    await check("Governance list filters update results, selection, and empty recovery", async () => {
      for (const scenario of [
        ["handover.html", "Bragi", "agents", "Bragi"],
        ["capabilities.html", "database.enable-pitr", "capabilities", "database.enable-pitr"],
        ["skills.html", "kubernetes-debug", "skills", "kubernetes-debug"],
        ["promotion.html", "identity.cert.rotate", "promotion", "identity.cert.rotate"],
      ]) {
        const [path, query, group, selectedText] = scenario;
        const frame = await open(path);
        const search = frame.locator('[data-fg-filter-key="search"]');
        await search.fill(query);
        assert.equal(await frame.locator(`[data-fg-filter-count="${group}"]`).innerText(), path === "handover.html" ? "1 of 15 shown" : path === "promotion.html" ? "1 of 6 shown" : "1 of 5 shown");
        assert.match(await frame.locator(`[data-fg-filter-item="${group}"]:not([hidden])`).innerText(), new RegExp(selectedText));
        await search.fill("no-such-governance-record");
        assert.equal(await frame.locator(`[data-fg-filter-empty="${group}"]`).isVisible(), true);
        await search.fill("");
        assert.equal(await frame.locator(`[data-fg-filter-empty="${group}"]`).isVisible(), false);
        assert.equal(await search.evaluate(element => element === document.activeElement), true);
      }
    });
    await check("Rules filters and view selector expose real states", async () => {
      const frame = await open("rules.html");
      await frame.locator('[data-fg-filter-key="search"]').fill("database.pitr.required");
      assert.equal(await frame.locator('[data-fg-filter-item="rules"]:not([hidden])').count(), 1);
      await frame.locator('[data-fg-filter-key="severity"]').selectOption("critical");
      assert.equal(await frame.locator('[data-fg-filter-empty="rules"]').isVisible(), true);
      await frame.locator('[data-fg-select-input="rules"]').selectOption("candidates");
      assert.equal(await frame.locator('[data-fg-panel="rules"][data-fg-value="candidates"]').isVisible(), true);
      assert.equal(await frame.locator('[data-fg-select="rules"][data-fg-value="candidates"]').getAttribute("aria-pressed"), "true");
    });
    await check("Read-only review context is not presented as a dead form", async () => {
      for (const path of ["workflow-builder.html", "context-selection-comparisons.html", "scope.html"]) {
        const frame = await open(path);
        assert.equal(await frame.locator(".fg-toolbar select, .fg-toolbar input").count(), 0);
        assert.equal(await frame.locator(".fg-static-control").count(), 3);
      }
      const workflow = await open("workflow-builder.html");
      assert.equal(await workflow.locator(".workflow-catalog button").count(), 0);
      const quality = workflow.locator('[data-fg-select="workflow-step"][data-fg-value="quality"]');
      await quality.focus();
      await page.keyboard.press("Enter");
      assert.equal(await quality.getAttribute("aria-pressed"), "true");
      assert.equal(await workflow.locator('[data-fg-panel="workflow-step"][data-fg-value="quality"]').isVisible(), true);
      const scope = await open("scope.html");
      assert.equal(await scope.locator(".scope-axis-path[aria-hidden=true]").count(), 6);
      assert.equal(await scope.locator(".scope-axis-path [style]").count(), 0);
    });
    await check("Governance routes preserve mobile targets, enlargement, and forced-color selection", async () => {
      const names = ["architecture", "ontology", "handover", "rules", "workflow-builder", "capabilities", "skills", "blast-radius", "promotion", "context-selection-comparisons", "scope"];
      await page.setViewportSize({ width: 390, height: 844 });
      for (const name of names) {
        const frame = await open(`${name}.html`);
        assert.ok(await frame.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth), `${name} mobile overflow`);
        const short = await frame.locator("button, input, select, summary").evaluateAll(elements => elements
          .filter(element => element.checkVisibility({ checkVisibilityCSS: true, checkOpacity: true }))
          .filter(element => element.getBoundingClientRect().height < 44)
          .map(element => ({ text: element.textContent.trim() || element.getAttribute("aria-label"), height: element.getBoundingClientRect().height })));
        assert.deepEqual(short, [], `${name} mobile targets: ${JSON.stringify(short)}`);
      }
      await page.setViewportSize({ width: 320, height: 844 });
      const architecture = await open("architecture.html");
      assert.ok(await architecture.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth));
      await page.setViewportSize({ width: 720, height: 700 });
      const scope = await open("scope.html");
      await scope.addStyleTag({ content: "p { line-height: 1.5 !important; margin-bottom: 2em !important; } * { letter-spacing: .12em !important; word-spacing: .16em !important; }" });
      await scope.locator(".fg-header p").evaluate(element => {
        element.textContent += " example-target-00000000000000000000000000000000 한국어 장문 경계 설명";
      });
      assert.ok(await scope.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth));
      await page.emulateMedia({ forcedColors: "active", reducedMotion: "reduce" });
      const promotion = await open("promotion.html");
      assert.notEqual(await promotion.locator(".promotion-row.is-selected").evaluate(element => getComputedStyle(element).outlineStyle), "none");
      await page.emulateMedia({ forcedColors: "none", reducedMotion: "reduce" });
      await page.setViewportSize({ width: 1440, height: 900 });
    });
    await check("Report samples retain exact values and never imply a live render", async () => {
      const frame = await open("reports.html");
      assert.match(await frame.locator(".report-mini-bars").getAttribute("aria-label"), /Monday 48.*Sunday 68/);
      assert.equal(await frame.locator(".report-mini-bar").count(), 7);
      assert.equal(await frame.locator(".chart-source-limit").count(), 0);
      await frame.locator("[data-evidence-report-template]").selectOption("control");
      await frame.locator("form[data-fg-static-form] button[type=submit]").click();
      assert.match(await frame.locator(".fg-form-result").innerText(), /No request was sent/);
      assert.equal(await frame.locator('[data-fg-select="report"][data-fg-value="control"]').getAttribute("aria-pressed"), "true");
      assert.equal(await frame.locator('[data-fg-panel="report"][data-fg-value="control"]').isVisible(), true);
      await frame.locator('[data-fg-select="report"][data-fg-value="cost"]').click();
      assert.equal(await frame.locator("[data-evidence-report-template]").inputValue(), "cost");
      await frame.locator('[data-evidence-report-form] input[required]').fill("INVALID!");
      assert.equal(await frame.locator("[data-evidence-report-form]").evaluate(form => form.checkValidity()), false);
    });
    await check("Forecast charts expose the exact synthetic measurements they encode", async () => {
      const frame = await open("forecast-learning.html");
      const heights = await frame.locator(".forecast-bar i").evaluateAll(elements => elements.map(element => element.getBoundingClientRect().height));
      assert.equal(heights.length, 5);
      assert.ok(heights.every(height => height > 30));
      assert.match(await frame.locator(".forecast-calibration").getAttribute("aria-label"), /v8 64%.*v12 71%/);
      assert.deepEqual(await frame.locator(".calibration-values dd").allTextContents(), ["27% actual", "43% actual", "59% actual", "72% actual"]);
      assert.equal(await frame.locator(".chart-source-limit").count(), 0);
    });
    await check("Assurance Twin review selection updates detail without widening authority", async () => {
      const frame = await open("assurance-twin.html");
      const options = frame.locator("[data-assurance-review]");
      assert.equal(await options.count(), 3);
      await options.nth(1).focus();
      await page.keyboard.press("Enter");
      assert.equal(await options.nth(1).getAttribute("aria-pressed"), "true");
      assert.match(await frame.locator(".cp-workspace-detail").innerText(), /example\/repository#41[\s\S]*No operational effect/);
      assert.equal(await options.nth(1).getAttribute("aria-controls"), "assurance-review-detail");
    });
    await check("Conversation search filters, exposes an empty state, and restores focus", async () => {
      const frame = await open("conversation-search.html");
      assert.equal(await frame.locator(".search-result-list li:not([hidden])").count(), 1);
      const query = frame.locator('[data-evidence-search] input[type="search"]');
      await query.fill("no matching authorized sample");
      await frame.locator("[data-evidence-search] button[type=submit]").click();
      assert.equal(await frame.locator("[data-evidence-search-empty]").isVisible(), true);
      assert.equal(await frame.locator(".search-workbench .fg-detail").isVisible(), false);
      assert.equal(await frame.locator(".search-workbench").getAttribute("class"), "fg-workbench search-workbench is-empty");
      await frame.locator("[data-evidence-clear-search]").click();
      assert.equal(await frame.locator(".search-result-list li:not([hidden])").count(), 3);
      assert.equal(await query.evaluate(element => element === document.activeElement), true);
    });
    await check("Audit cursor preview appends bounded samples and preserves selection", async () => {
      const frame = await open("audit.html");
      assert.equal(await frame.locator("[data-evidence-next-record]:visible").count(), 0);
      await frame.locator("[data-evidence-append]").click();
      assert.equal(await frame.locator("[data-evidence-next-record]:visible").count(), 2);
      assert.equal(await frame.locator("[data-evidence-append]").isDisabled(), true);
      const appended = frame.locator('button[data-fg-value="verification-timeout"]');
      await appended.click();
      assert.equal(await appended.getAttribute("aria-pressed"), "true");
      assert.match(await frame.locator('[data-fg-panel="audit"][data-fg-value="verification-timeout"]').innerText(), /terminal success remains unavailable/);
    });
    await check("RCA correlation and result-state controls preserve honest mock feedback", async () => {
      const frame = await open("rca.html");
      const toggle = frame.locator("[data-rca-query-toggle]");
      await toggle.click();
      assert.equal(await toggle.getAttribute("aria-expanded"), "true");
      await frame.locator("#rca-correlation").fill("inc-example-recovery-42");
      await frame.locator("#rca-lookup button[type=submit]").click();
      assert.equal(await frame.locator("[data-rca-correlation]").innerText(), "inc-01J2-API-LATENCY");
      assert.equal(await frame.locator("#rca-lookup").isVisible(), true);
      assert.match(await frame.locator("[data-rca-query-status]").innerText(), /No local synthetic RCA sample matches/);
      await frame.locator("#rca-correlation").fill("inc-01J2-API-LATENCY");
      await frame.locator("#rca-lookup button[type=submit]").click();
      assert.equal(await frame.locator("#rca-lookup").isVisible(), false);
      assert.match(await frame.locator("[data-rca-query-status]").innerText(), /No request was sent/);
      await frame.locator('[data-rca-view="abstained"]').click();
      assert.equal(await frame.locator('[data-rca-panel="abstained"]').isVisible(), true);
      assert.match(await frame.locator('[data-rca-panel="abstained"]').innerText(), /no root cause presented/i);
    });
    await check("Clipboard denial never displays a success receipt", async () => {
      const frame = await open("rule-trace.html");
      await frame.evaluate(() => Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: () => Promise.reject(new Error("Denied for regression test")) } }));
      await frame.locator("[data-fg-copy]:visible").click();
      assert.match(await frame.locator(".fg-copy-result").innerText(), /Copy unavailable/);
      assert.doesNotMatch(await frame.locator(".fg-copy-result").innerText(), /Copied/);
    });
    await check("Every Evidence selector exposes its matching state", async () => {
      for (const name of ["audit", "browser-evidence", "forecast-learning", "conversation-search", "conversation-assurance", "reports", "rule-trace"]) {
        const frame = await open(`${name}.html`);
        if (name === "audit") await frame.locator("[data-evidence-append]").click();
        if (name === "conversation-search") {
          await frame.locator('[data-evidence-search] input[type="search"]').fill("");
          await frame.locator("[data-evidence-search]").evaluate(form => form.requestSubmit());
        }
        const controls = frame.locator("[data-fg-select]:visible");
        for (let index = 0; index < await controls.count(); index += 1) {
          const control = controls.nth(index);
          const group = await control.getAttribute("data-fg-select");
          const value = await control.getAttribute("data-fg-value");
          await control.click();
          assert.equal(await control.getAttribute("aria-pressed"), "true", `${name}:${group}:${value}`);
          assert.equal(await frame.locator(`[data-fg-select="${group}"][aria-pressed="true"]`).count(), 1, `${name}:${group}`);
          const panel = frame.locator(`[data-fg-panel="${group}"][data-fg-value="${value}"]`);
          if (await panel.count()) assert.equal(await panel.isVisible(), true, `${name}:${group}:${value}`);
        }
      }
    });
    await check("Evidence routes keep semantic text, named controls, and desktop geometry", async () => {
      for (const name of ["audit", "browser-evidence", "forecast-learning", "assurance-twin", "conversation-search", "conversation-assurance", "reports", "rule-trace", "rca"]) {
        const frame = await open(`${name}.html`);
        assert.equal(await frame.locator("main").count(), 1, name);
        assert.equal(await frame.locator("h1").count(), 1, name);
        const findings = await frame.evaluate(() => {
          const visible = element => element.checkVisibility({ checkVisibilityCSS: true, checkOpacity: true }) &&
            !element.closest('[hidden], [aria-hidden="true"], .cs-sr-only');
          const text = [...document.querySelectorAll("p, small, span, dt, dd, th, td, label, strong, a, button, time")]
            .filter(element => visible(element) && element.textContent.trim());
          const controls = [...document.querySelectorAll("button, input, select, textarea, summary")]
            .filter(visible);
          return {
            tiny: text.filter(element => parseFloat(getComputedStyle(element).fontSize) < 12)
              .map(element => ({ text: element.textContent.trim().slice(0, 60), size: getComputedStyle(element).fontSize })),
            unnamed: controls.filter(element => !element.getAttribute("aria-label") &&
              !element.getAttribute("aria-labelledby") && !element.labels?.length &&
              !element.textContent.trim() && !element.getAttribute("title")).length,
            overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
          };
        });
        assert.deepEqual(findings.tiny, [], `${name}: ${JSON.stringify(findings.tiny)}`);
        assert.equal(findings.unnamed, 0, name);
        assert.equal(findings.overflow, 0, name);
      }
    });
    await check("Evidence routes reflow at constrained, mobile, and 200-percent-equivalent widths", async () => {
      const names = ["audit", "browser-evidence", "forecast-learning", "assurance-twin", "conversation-search", "conversation-assurance", "reports", "rule-trace", "rca"];
      for (const viewport of [{ width: 993, height: 641 }, { width: 390, height: 844 }, { width: 320, height: 844 }]) {
        await page.setViewportSize(viewport);
        for (const name of names) {
          const frame = await open(`${name}.html`);
          assert.ok(await frame.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth), `${name} at ${viewport.width}px`);
          if (viewport.width <= 390) {
            const short = await frame.locator("button, input, select, summary").evaluateAll(elements => elements
              .filter(element => element.checkVisibility({ checkVisibilityCSS: true, checkOpacity: true }))
              .filter(element => element.getBoundingClientRect().height < 44)
              .map(element => ({ text: element.textContent.trim() || element.getAttribute("aria-label"), height: element.getBoundingClientRect().height })));
            assert.deepEqual(short, [], `${name} at ${viewport.width}px: ${JSON.stringify(short)}`);
          }
        }
      }
      await page.setViewportSize({ width: 720, height: 450 });
      const frame = await open("rca.html");
      await frame.addStyleTag({ content: "p { line-height: 1.5 !important; margin-bottom: 2em !important; } * { letter-spacing: .12em !important; word-spacing: .16em !important; }" });
      await frame.locator("#rc-hypothesis-title").evaluate(element => {
        element.textContent = "example-correlation-00000000000000000000000000000000 한국어 장문 근거도 페이지 폭을 확장하지 않습니다";
      });
      assert.ok(await frame.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth));
      await page.emulateMedia({ forcedColors: "active" });
      assert.notEqual(await frame.locator('[data-rca-view="grounded"]').evaluate(element => getComputedStyle(element).outlineStyle), "none");
      await page.emulateMedia({ forcedColors: "none" });
      await page.setViewportSize({ width: 1440, height: 900 });
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
