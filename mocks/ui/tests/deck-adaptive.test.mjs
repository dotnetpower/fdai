import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const uiRoot = join(root, "mocks/ui");
const fixtureRoot = join(uiRoot, "fixtures/adaptive");
const require = createRequire(join(root, "console/package.json"));
const { chromium } = require("playwright");
const origin = "http://127.0.0.1:5373";

async function fixtures() {
  const index = JSON.parse(await readFile(join(fixtureRoot, "index.json"), "utf8"));
  const entries = await Promise.all(index.scenarios.map(async (entry) => {
    const text = await readFile(join(fixtureRoot, entry.file), "utf8");
    return [entry.scenario, { text, doc: JSON.parse(text) }];
  }));
  return { index, byName: Object.fromEntries(entries) };
}

async function openStudy(browser, query = {}, options = {}) {
  const context = await browser.newContext({
    viewport: options.viewport || { width: 1440, height: 900 },
    reducedMotion: options.reducedMotion || "no-preference",
    forcedColors: options.forcedColors || "none",
  });
  await context.route("**/*", (route) => new URL(route.request().url()).origin === origin
    ? route.continue() : route.abort("blockedbyclient"));
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(String(error)));
  page.on("response", (response) => { if (response.status() >= 400) errors.push(`${response.status()} ${response.url()}`); });
  // The investigation form of the one Command deck page replays the adaptive fixtures.
  const search = new URLSearchParams({ form: "investigation", ...query }).toString();
  await page.goto(`${origin}/?deck-adaptive=${Date.now()}#mocks/ui/deck.html?${search}`,
    { waitUntil: "load" });
  await page.waitForFunction(() => {
    const frame = document.querySelector("#preview-frame");
    return frame?.contentDocument?.readyState === "complete"
      && frame.contentWindow.location.pathname === "/mocks/ui/deck.html";
  });
  const frame = await (await page.locator("#preview-frame").elementHandle()).contentFrame();
  return { context, page, frame, errors };
}

function deckState(frame, value, timeout = 30000) {
  return frame.locator(`body[data-deck-state="${value}"]`).waitFor({ state: "attached", timeout });
}

// Buttons inside the collapsed preview panel are exercised through their click handlers.
function pressPreview(frame, selector) {
  return frame.locator(selector).evaluate((button) => button.click());
}

function squash(text) {
  return text.replace(/\s+/g, " ").trim();
}

function expectedActivityStatuses(doc) {
  const counts = {};
  for (const activity of doc.trajectory_detail.activities) {
    const presentation = doc.presentation[activity.activity_id] || {};
    const status = presentation.authorization === "denied" ? "denied" : activity.status;
    counts[status] = (counts[status] || 0) + 1;
  }
  return counts;
}

test("study page replays every shared synthetic fixture", async () => {
  const [{ index, byName }, html, engine, retired] = await Promise.all([fixtures(),
    readFile(join(uiRoot, "deck.html"), "utf8"), readFile(join(uiRoot, "assets/deck-sources.js"), "utf8"),
    readFile(join(uiRoot, "deck-adaptive.html"), "utf8")]);
  assert.match(html, /<button type="button" data-form="investigation"/);
  assert.match(html, /assets\/deck-sources\.js\?v=/);
  assert.match(html, /calm-slate-deck-conversation\.css\?v=/);
  assert.doesNotMatch(html, /\sstyle="/);
  // The retired study URL keeps working: it opens the investigation form with its parameters.
  assert.match(retired, /query\.set\("form", "investigation"\)/);
  const order = JSON.parse(engine.match(/var INVESTIGATIONS = (\[[^\]]+\]);/)[1]);
  assert.deepEqual(order, index.scenarios.map((entry) => entry.scenario));
  for (const [name, { text, doc }] of Object.entries(byName)) {
    assert.equal(doc.schema, "fdai.mock.adaptive-investigation/1", name);
    assert.equal(doc.scenario, name);
    assert.equal(/^[\x09\x0a\x0d\x20-\x7e]*$/.test(text), true, `${name}: ASCII`);
    assert.doesNotMatch(text, /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i, `${name}: identifiers`);
    assert.doesNotMatch(text, /@[a-z0-9-]+\.[a-z]{2,}/i, `${name}: addresses`);
    for (const address of text.match(/\b\d{1,3}(?:\.\d{1,3}){3}\b/g) || []) {
      assert.match(address, /^(?:192\.0\.2|198\.51\.100|203\.0\.113)\./, `${name}: ${address} is documentation space`);
    }
    for (const resource of text.match(/\b[a-z]+-(?:rg|vm)-[a-z0-9-]+/g) || []) {
      assert.match(resource, /^example-/, `${name}: ${resource}`);
    }
    const detail = doc.trajectory_detail;
    const executions = detail.activities.filter((activity) => activity.execution);
    assert.equal(detail.work_progress_shape.planned_reads, executions.length, `${name}: planned reads`);
    assert.equal(detail.turn_budget.model_calls.reserved, 0, `${name}: settled reservation`);
    // Every activity starts after the question and inside the reported elapsed time.
    const start = Date.parse("2026-09-28T10:41:03.160Z");
    const end = start + detail.turn_budget.elapsed_ms.used;
    for (const activity of executions) {
      const begin = Date.parse(activity.execution.started_at);
      assert.ok(begin >= start && begin + activity.execution.duration_ms <= end, `${name}: ${activity.activity_id} timing`);
    }
    assert.equal(Date.parse(detail.turn_budget.as_of), end, `${name}: as_of`);
  }
});

test("a settled investigation reads plan, work, then answer", { timeout: 60000 }, async () => {
  const { byName } = await fixtures();
  const drift = byName.drift.doc;
  const browser = await chromium.launch({ headless: true });
  try {
    const { context, frame, errors } = await openStudy(browser, { scenario: "drift", state: "settled" });
    await deckState(frame, "settled");
    const layout = await frame.evaluate(() => {
      const article = document.querySelector(".cs-deck-agent-turn");
      return {
        order: [...article.children].map((node) => node.classList[0]),
        attachment: document.querySelector(".cs-deck-user-attachment")?.textContent.replace(/\s+/g, " ").trim(),
        waves: [...document.querySelectorAll(".cs-deck-waves > li")].map((node) => node.classList[0] === "cs-deck-wave"
          ? `wave:${node.querySelector(".cs-deck-wave-title").textContent}:${node.dataset.state}`
          : `milestone:${node.querySelector(".cs-deck-milestone-text").textContent}`),
        expanded: [...document.querySelectorAll(".cs-deck-wave-head")].map((node) => node.getAttribute("aria-expanded")),
        status: document.querySelector(".cs-deck-investigation-status").textContent,
        limits: document.querySelector(".cs-deck-investigation-limits").textContent,
        lead: document.querySelector(".cs-deck-prose > p").textContent,
        facts: [...document.querySelectorAll(".cs-deck-answer-facts > div")].map((node) =>
          [node.querySelector("dt").textContent, node.querySelector("dd").textContent]),
        checks: [...document.querySelectorAll(".cs-deck-answer-checks > li")].map((node) => node.textContent),
        next: document.querySelector(".cs-deck-answer-next")?.textContent,
        verification: document.querySelector(".cs-deck-agent-turn .cs-deck-verification").textContent.replace(/\s+/g, " ").trim(),
        affordances: [...document.querySelectorAll(".cs-deck-affordance")].map((node) => node.textContent),
        stats: document.querySelector(".cs-run-record-stats").textContent,
        duration: document.querySelector(".cs-run-record-duration").textContent,
        followups: [...document.querySelectorAll(".cs-deck-followup")].map((node) => node.textContent),
      };
    });
    assert.deepEqual(layout.order, ["cs-deck-turn-head", "cs-deck-plan-lead", "cs-deck-context-receipt",
      "cs-deck-investigation", "cs-deck-answer", "cs-deck-action-row", "cs-run-record", "cs-deck-followups"]);
    assert.equal(layout.attachment, "example-inventory.md 184 lines");
    const milestones = drift.trajectory_detail.milestones.map((milestone) => `milestone:${milestone.text}`);
    assert.deepEqual(layout.waves, ["wave:Wave 1:done", milestones[0], "wave:Wave 2:done", milestones[1],
      "wave:Compare:done", milestones[2]]);
    assert.deepEqual(layout.expanded, ["false", "false", "false"]);
    assert.equal(layout.status, "2 waves, 7 of 7 reads completed");
    assert.equal(layout.limits, "Used: 3 of 5 model calls, 4.4k of 48k tokens, 3.1 s of 60 s");
    assert.equal(layout.lead, drift.answer.lead);
    assert.deepEqual(layout.facts, drift.answer.facts);
    assert.deepEqual(layout.checks, drift.answer.checks);
    assert.equal(layout.next, `Next safe step: ${drift.answer.next_step}`);
    assert.equal(layout.verification, "\u2713 Verified 12 of 12 checks consistent");
    assert.deepEqual(layout.affordances, ["Draft remediation"]);
    // The run record and the budget telemetry describe the same run.
    assert.match(layout.stats, /\u00b7 4,382 tokens \u00b7 evidence 7 of 7 \u00b7 verification completed$/);
    assert.equal(layout.duration, `Server processing ${(drift.trajectory_detail.turn_budget.elapsed_ms.used / 1000).toFixed(2)} s`);
    assert.deepEqual(layout.followups, drift.followups);
    assert.equal(await frame.getByRole("button", { name: /execute|approve|apply|run now/i }).count(), 0);
    assert.doesNotMatch(await frame.locator(".cs-deck-investigation").innerText(), /draft|permission|risk|\bsafe\b/i);
    assert.deepEqual(errors, []);
    await context.close();
  } finally {
    await browser.close();
  }
});

test("activity cards keep operation, authorization, and authorities separate", { timeout: 60000 }, async () => {
  const { byName } = await fixtures();
  const browser = await chromium.launch({ headless: true });
  try {
    const { context, frame, errors } = await openStudy(browser, { scenario: "drift", state: "settled" });
    await deckState(frame, "settled");
    // Rapid toggles cancel the fold in flight, so the body always matches its header.
    const lastWave = frame.locator(".cs-deck-wave-head").last();
    await lastWave.evaluate((button) => { button.click(); button.click(); button.click(); });
    await frame.waitForTimeout(400);
    assert.equal(await lastWave.getAttribute("aria-expanded"), "true");
    assert.equal(await frame.locator(".cs-deck-wave").last().locator(".cs-deck-wave-body").isVisible(), true);
    // A fold interrupted by a quick reopen must not hide the reopened body when it would have ended.
    await lastWave.evaluate((button) => { button.click(); button.click(); });
    await frame.waitForTimeout(400);
    assert.equal(await lastWave.getAttribute("aria-expanded"), "true");
    assert.equal(await frame.locator(".cs-deck-wave").last().locator(".cs-deck-wave-body").isVisible(), true);
    await lastWave.click();
    await frame.waitForTimeout(400);
    assert.equal(await lastWave.getAttribute("aria-expanded"), "false");
    assert.equal(await frame.locator(".cs-deck-wave").last().locator(".cs-deck-wave-body").isVisible(), false);
    const firstWave = frame.locator(".cs-deck-wave-head").first();
    await firstWave.focus();
    await frame.page().keyboard.press("Enter");
    assert.equal(await firstWave.getAttribute("aria-expanded"), "true");
    await frame.locator(".cs-deck-wave").first().locator(".cs-deck-wave-body").waitFor({ state: "visible" });
    assert.equal(await frame.locator(".cs-deck-wave").first().locator(".cs-deck-activity").count(), 4);
    const card = frame.locator(".cs-deck-activity").filter({ hasText: "Read the resource group" });
    await card.locator("summary").click();
    const opened = await card.evaluate((node) => ({
      facts: Object.fromEntries([...node.querySelectorAll(".cs-run-facts > div")].map((pair) =>
        [pair.querySelector("dt").textContent, pair.querySelector("dd").textContent])),
      payloads: [...node.querySelectorAll(".cs-run-payload")].map((payload) => ({
        label: payload.querySelector("strong").textContent,
        language: payload.querySelector(".cs-deck-code-lang").textContent,
        code: [...payload.querySelectorAll(".cs-deck-code-line")].map((line) => line.textContent).join("\n"),
      })),
      status: node.querySelector(".cs-deck-activity-status").textContent,
    }));
    const drift = byName.drift.doc;
    const activity = drift.trajectory_detail.activities.find((item) => item.activity_id === "a-rg");
    assert.deepEqual(opened.facts, {
      Operation: "read",
      Authorization: "Allowed",
      "Evidence authority": "server_inventory_graph",
      "Execution authority": "None",
      Target: "core-control-plane / inventory / read",
      Tool: "inventory.read",
    });
    assert.deepEqual(opened.payloads.map((payload) => [payload.label, payload.language]),
      [["Typed call", "query"], ["Provider equivalent", "shell"], ["Observed output", "json"]]);
    assert.equal(opened.payloads[0].code, activity.execution.command);
    assert.equal(opened.payloads[1].code, drift.presentation["a-rg"].provider);
    assert.equal(opened.payloads[2].code, activity.execution.output);
    assert.equal(opened.status, "290 ms");

    await pressPreview(frame, 'button[data-scenario="denied"]');
    await pressPreview(frame, "#ds-finish");
    await deckState(frame, "settled");
    await frame.locator(".cs-deck-wave-head").nth(1).click();
    const denied = frame.locator(".cs-deck-activity[data-status='denied']");
    assert.equal(await denied.count(), 1);
    await denied.locator("summary").click();
    const deniedCard = await denied.evaluate((node) => ({
      status: node.querySelector(".cs-deck-activity-status").textContent,
      authorization: [...node.querySelectorAll(".cs-run-facts > div")]
        .find((pair) => pair.querySelector("dt").textContent === "Authorization").querySelector("dd").textContent,
      labels: [...node.querySelectorAll(".cs-run-payload > strong")].map((label) => label.textContent),
      note: node.querySelector(".cs-deck-activity-note").textContent,
    }));
    assert.equal(deniedCard.status, "Denied");
    assert.equal(deniedCard.authorization, "Denied");
    assert.deepEqual(deniedCard.labels, ["Typed call", "Provider equivalent"]);
    assert.equal(deniedCard.note, byName.denied.doc.trajectory_detail.activities
      .find((item) => item.activity_id === "a-network").detail);
    assert.deepEqual(errors, []);
    await context.close();
  } finally {
    await browser.close();
  }
});

test("live replay runs each wave in parallel and gates the next wave", { timeout: 90000 }, async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const { context, frame, errors } = await openStudy(browser, { scenario: "drift" });
    await deckState(frame, "settled");
    await pressPreview(frame, 'button[data-speed="2"]');
    await frame.evaluate(() => {
      window.adaptiveLog = [];
      const snapshot = () => window.adaptiveLog.push({
        deck: document.body.dataset.deckState,
        waves: [...document.querySelectorAll(".cs-deck-wave")].map((wave) => ({
          state: wave.dataset.state,
          items: wave.querySelectorAll(".cs-deck-activity").length,
          running: wave.querySelectorAll(".cs-deck-activity[data-status='running']").length,
          expanded: wave.querySelector(".cs-deck-wave-head").getAttribute("aria-expanded"),
        })),
        milestones: document.querySelectorAll(".cs-deck-milestone").length,
        answer: !!document.querySelector(".cs-deck-answer"),
        limits: document.querySelector(".cs-deck-investigation-limits")?.textContent || "",
      });
      new MutationObserver(snapshot).observe(document.body, {
        subtree: true, childList: true, attributes: true,
        attributeFilter: ["data-state", "data-status", "data-deck-state", "aria-expanded"],
      });
    });
    await pressPreview(frame, "#ds-replay");
    await deckState(frame, "preparing", 5000);
    await deckState(frame, "settled");
    const log = (await frame.evaluate(() => window.adaptiveLog)).filter((entry) => entry.waves.length === 3);
    assert.ok(log.length > 10, `${log.length} snapshots`);
    assert.equal(Math.max(...log.map((entry) => entry.waves[0].running)), 4, "wave 1 reads run together");
    assert.equal(Math.max(...log.map((entry) => entry.waves[1].running)), 3, "wave 2 reads run together");
    for (const entry of log) {
      if (entry.waves[0].state !== "done") assert.equal(entry.waves[1].items, 0, "wave 2 waits for wave 1");
      if (entry.waves[1].state !== "done") assert.equal(entry.waves[2].items, 0, "comparison waits for wave 2");
      const done = entry.waves.filter((wave) => wave.state === "done").length;
      assert.ok(entry.milestones <= done, "a progress line never precedes its wave");
      if (entry.answer) {
        assert.equal(entry.waves.every((wave) => wave.state === "done" && wave.running === 0), true, "answer after the work");
      }
      if (entry.deck === "preparing") assert.match(entry.limits, /^Limits: 5 model calls, 48k tokens, 60 s$/);
    }
    assert.ok(log.some((entry) => entry.waves[0].state === "running" && entry.waves[0].expanded === "true"),
      "the running wave opens");
    const last = log.at(-1);
    assert.deepEqual(last.waves.map((wave) => [wave.state, wave.expanded]), [["done", "false"], ["done", "false"], ["done", "false"]]);
    assert.equal(last.milestones, 3);
    assert.match(last.limits, /^Used: /);
    assert.deepEqual(errors, []);
    await context.close();
  } finally {
    await browser.close();
  }
});

test("each scenario settles with its fixture verdict, limits, and outcomes", { timeout: 120000 }, async () => {
  const { index, byName } = await fixtures();
  const browser = await chromium.launch({ headless: true });
  try {
    const { context, frame, errors } = await openStudy(browser, { state: "settled" });
    await deckState(frame, "settled");
    for (const { scenario } of index.scenarios) {
      const doc = byName[scenario].doc;
      await pressPreview(frame, `button[data-scenario="${scenario}"]`);
      await pressPreview(frame, "#ds-finish");
      await deckState(frame, "settled");
      assert.equal(await frame.locator(`button[data-scenario="${scenario}"]`).getAttribute("aria-pressed"), "true");
      const settled = await frame.evaluate(() => ({
        question: document.querySelector(".cs-deck-user-line").textContent,
        lead: document.querySelector(".cs-deck-prose > p").textContent,
        verification: document.querySelector(".cs-deck-agent-turn .cs-deck-verification").textContent.replace(/\s+/g, " ").trim(),
        badge: document.querySelector(".cs-deck-turn-head .cs-deck-answer-state")?.textContent || null,
        limits: document.querySelector(".cs-deck-investigation-limits").textContent,
        waves: document.querySelectorAll(".cs-deck-wave").length,
        statuses: [...document.querySelectorAll(".cs-deck-activity")].reduce((counts, node) => {
          counts[node.dataset.status] = (counts[node.dataset.status] || 0) + 1;
          return counts;
        }, {}),
        limitations: document.querySelectorAll(".cs-deck-prose .cs-deck-evidence-note").length,
        receipts: [...document.querySelectorAll(".cs-deck-context-receipt-list > li")].map((node) => node.dataset.freshness),
        affordances: document.querySelectorAll(".cs-deck-affordance").length,
        followups: [...document.querySelectorAll(".cs-deck-followup")].map((node) => node.textContent),
        agentTurns: document.querySelectorAll(".cs-deck-agent-turn").length,
      }));
      const verification = doc.answer.verification;
      assert.equal(settled.question, doc.question, scenario);
      assert.equal(settled.lead, doc.answer.lead, scenario);
      assert.equal(settled.verification, `${verification.mark} ${verification.label} ${verification.detail}`, scenario);
      assert.equal(settled.badge, { partial: "Partial", unverified: "Unverified" }[doc.answer.state] || null, scenario);
      assert.match(settled.limits, doc.trajectory_detail.turn_budget.exhaustion_reason === "deadline"
        ? /^Turn deadline reached: / : /^Used: /, scenario);
      const hasCompare = doc.trajectory_detail.activities.some((activity) => !activity.branch_id);
      assert.equal(settled.waves, doc.plan.waves.length + (hasCompare ? 1 : 0), scenario);
      assert.deepEqual(settled.statuses, expectedActivityStatuses(doc), scenario);
      assert.equal(settled.limitations, doc.answer.limitations.length, scenario);
      assert.deepEqual(settled.receipts, doc.trajectory_detail.context_receipts.map((receipt) => receipt.freshness), scenario);
      assert.equal(settled.affordances, doc.affordances.filter((item) => item.kind === "draft_remediation").length, scenario);
      assert.deepEqual(settled.followups, doc.followups, scenario);
      assert.equal(settled.agentTurns, 1, scenario);
    }
    assert.deepEqual(errors, []);
    await context.close();
  } finally {
    await browser.close();
  }
});

test("stop keeps finished reads and marks unfinished work", { timeout: 60000 }, async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const { context, frame, errors } = await openStudy(browser, { scenario: "drift" });
    await frame.locator(".cs-deck-activity[data-status='completed']").first().waitFor({ state: "attached", timeout: 10000 });
    const before = await frame.locator(".cs-deck-activity[data-status='completed']").count();
    assert.equal(await frame.locator("#ds-send").textContent(), "Stop");
    await frame.locator("#ds-send").click();
    await deckState(frame, "stopped", 3000);
    const stopped = await frame.evaluate(() => ({
      completed: document.querySelectorAll(".cs-deck-activity[data-status='completed']").length,
      running: document.querySelectorAll(".cs-deck-activity[data-status='running'], .cs-deck-wave[data-state='running']").length,
      stopped: document.querySelectorAll(".cs-deck-activity[data-status='stopped']").length,
      skipped: [...document.querySelectorAll(".cs-deck-wave[data-state='skipped'] .cs-deck-wave-meta")].map((node) => node.textContent),
      status: document.querySelector(".cs-deck-investigation-status").textContent,
      badge: document.querySelector(".cs-deck-turn-head .cs-deck-answer-state").textContent,
      note: document.querySelector(".cs-deck-evidence-note").textContent,
      spinners: document.querySelectorAll(".cs-deck-investigation .cs-grounding-spinner").length,
    }));
    assert.ok(stopped.completed >= before, `${before} -> ${stopped.completed}`);
    assert.equal(stopped.running, 0);
    assert.ok(stopped.stopped >= 1);
    assert.deepEqual(stopped.skipped, ["Not started", "Not started"]);
    assert.equal(stopped.status, "Stopped before the answer");
    assert.equal(stopped.badge, "Stopped");
    assert.match(stopped.note, /no answer was composed\. Nothing was changed\./);
    assert.equal(stopped.spinners, 0);
    const stoppedCard = frame.locator(".cs-deck-activity[data-status='stopped']").first();
    await stoppedCard.locator("summary").click();
    assert.equal(await stoppedCard.locator(".cs-deck-activity-detail").textContent(),
      "Stopped before this read returned. Nothing was changed.");
    // A wave that never started has nothing to open.
    const skippedHead = frame.locator(".cs-deck-wave[data-state='skipped'] .cs-deck-wave-head").first();
    await skippedHead.click();
    assert.equal(await skippedHead.getAttribute("aria-expanded"), "false");
    assert.equal(await frame.locator(".cs-deck-wave[data-state='skipped'] .cs-deck-wave-body:not([hidden])").count(), 0);
    await frame.locator('.cs-deck-action-row [data-action="regenerate"]').click();
    await deckState(frame, "preparing", 3000);
    assert.equal(await frame.locator(".cs-deck-agent-turn").count(), 1);
    await pressPreview(frame, "#ds-finish");
    await deckState(frame, "settled");
    assert.equal(await frame.locator(".cs-deck-activity[data-status='completed']").count(), 8);
    assert.deepEqual(errors, []);
    await context.close();
  } finally {
    await browser.close();
  }
});

test("a stop after the last wave and a deck closed while loading stay truthful", { timeout: 60000 }, async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const { context, page, frame, errors } = await openStudy(browser, { scenario: "drift" });
    await deckState(frame, "preparing", 5000);
    // Stop in the short window after the last wave ends and before the header settles.
    await frame.evaluate(() => new Promise((resolve) => {
      const observer = new MutationObserver(() => {
        const waves = [...document.querySelectorAll(".cs-deck-wave")];
        const block = document.querySelector(".cs-deck-investigation");
        if (waves.length && waves.every((wave) => wave.dataset.state === "done") && !block.hasAttribute("data-settled")) {
          observer.disconnect();
          document.getElementById("ds-send").click();
          resolve();
        }
      });
      observer.observe(document.body, { subtree: true, attributes: true, attributeFilter: ["data-state"] });
    }));
    await deckState(frame, "stopped", 3000);
    assert.equal(await frame.locator(".cs-deck-investigation-status").textContent(), "Stopped before the answer");
    assert.match(await frame.locator(".cs-deck-evidence-note").textContent(), /no answer was composed/);

    // Closing the deck while a scenario's fixture loads settles that turn instead of replaying it unseen.
    await page.route("**/fixtures/adaptive/partial.json", async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 800));
      await route.continue();
    });
    await pressPreview(frame, 'button[data-scenario="partial"]');
    await frame.locator("#ds-close").click();
    await frame.waitForTimeout(1400);
    assert.equal(await frame.locator("#ds-workspace").getAttribute("data-open"), "false");
    assert.equal(await frame.locator("#ds-transcript").getAttribute("aria-busy"), "false");
    await frame.locator("#ds-reopen").click();
    await deckState(frame, "settled", 3000);
    assert.equal(await frame.locator("#ds-send").textContent(), "Send");
    assert.equal(await frame.locator(".cs-deck-investigation[data-settled]").count(), 1);
    assert.equal(await frame.locator(".cs-deck-activity[data-status='running']").count(), 0);
    assert.equal(await frame.locator(".cs-deck-readiness.is-loading").count(), 0);
    assert.equal(await frame.locator(".cs-deck-turn-head .cs-deck-answer-state").textContent(), "Partial");
    assert.deepEqual(errors, []);
    await context.close();
  } finally {
    await browser.close();
  }
});

test("copy returns every shown answer block, including the qualifying note", { timeout: 60000 }, async () => {
  const { byName } = await fixtures();
  const browser = await chromium.launch({ headless: true });
  try {
    const { context, frame, errors } = await openStudy(browser, { scenario: "no-drift", state: "settled" });
    await context.grantPermissions(["clipboard-read", "clipboard-write"], { origin });
    await deckState(frame, "settled");
    await frame.locator(".cs-deck-agent-turn [data-action='copy']").click();
    await frame.locator(".cs-deck-agent-turn [data-action='copy'].is-done").waitFor({ state: "attached", timeout: 3000 });
    const copied = await frame.evaluate(() => navigator.clipboard.readText());
    const answer = byName["no-drift"].doc.answer;
    assert.equal(copied.split("\n")[0], answer.lead);
    for (const [key, value] of answer.facts) assert.ok(copied.includes(`${key}: ${value}`), key);
    for (const check of answer.checks) assert.ok(copied.includes(`- ${check}`), check);
    assert.ok(copied.includes(answer.note), "note");
    assert.deepEqual(errors, []);
    await context.close();
  } finally {
    await browser.close();
  }
});

test("draft remediation and follow-ups start separate requests that run nothing", { timeout: 60000 }, async () => {
  const { byName } = await fixtures();
  const browser = await chromium.launch({ headless: true });
  try {
    const { context, frame, errors } = await openStudy(browser, { scenario: "drift", state: "settled" });
    await deckState(frame, "settled");
    const draft = frame.locator(".cs-deck-affordance");
    await draft.click();
    assert.equal(await draft.isDisabled(), true);
    assert.equal(await draft.textContent(), "Draft requested");
    const turns = await frame.evaluate(() => [...document.querySelectorAll(".cs-deck-turn")].map((node) =>
      node.querySelector(".cs-deck-user-line, .cs-deck-prose")?.textContent || ""));
    assert.equal(turns.length, 4);
    assert.equal(turns[2], "Draft a remediation for these differences.");
    assert.match(turns[3], /separate request/);
    assert.match(turns[3], /nothing runs without approval/);
    assert.equal(await frame.locator(".cs-deck-agent-turn").last().locator(".cs-run-record, .cs-deck-action-row").count(), 0);
    const followup = frame.locator(".cs-deck-followup").first();
    await followup.click();
    await frame.waitForFunction(() => document.querySelectorAll(".cs-deck-turn").length === 6);
    assert.equal(squash(await frame.locator(".cs-deck-user-turn").last().locator(".cs-deck-user-line").textContent()),
      byName.drift.doc.followups[0]);
    assert.match(await frame.locator(".cs-deck-agent-turn").last().textContent(), /starts a new request with its own plan, reads, and limits/);
    assert.equal(await frame.getByRole("button", { name: /execute|approve|apply|run now/i }).count(), 0);
    assert.deepEqual(errors, []);
    await context.close();
  } finally {
    await browser.close();
  }
});

test("dock, mobile, reduced-motion, and forced-colors states stay readable", { timeout: 90000 }, async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    let study = await openStudy(browser, { scenario: "partial", width: "dock" }, {
      viewport: { width: 390, height: 844 }, reducedMotion: "reduce",
    });
    await deckState(study.frame, "settled");
    await study.frame.locator(".cs-deck-wave-head").nth(1).click();
    const narrow = await study.frame.evaluate(() => ({
      fits: document.querySelector("#ds-transcript").scrollWidth <= document.querySelector("#ds-transcript").clientWidth,
      heads: [...document.querySelectorAll(".cs-deck-wave-head")].map((node) => Math.round(node.getBoundingClientRect().height)),
      summaries: [...document.querySelectorAll(".cs-deck-wave:nth-child(3) .cs-deck-activity-summary")]
        .map((node) => Math.round(node.getBoundingClientRect().height)),
      kindHidden: [...document.querySelectorAll(".cs-deck-activity-kind")].every((node) => getComputedStyle(node).display === "none"),
      animations: [...document.querySelectorAll(".cs-deck-milestone, .cs-deck-investigation, .cs-deck-activity-mark")]
        .every((node) => getComputedStyle(node).animationName === "none"),
      timedOut: document.querySelector(".cs-deck-activity[data-status='failed'] .cs-deck-activity-status").textContent,
    }));
    assert.equal(narrow.fits, true);
    assert.equal(narrow.heads.every((height) => height >= 44), true, narrow.heads.join(","));
    assert.equal(narrow.summaries.length, 3);
    assert.equal(narrow.summaries.every((height) => height >= 44), true, narrow.summaries.join(","));
    assert.equal(narrow.kindHidden, true);
    assert.equal(narrow.animations, true);
    assert.equal(narrow.timedOut, "Timed out");
    assert.deepEqual(study.errors, []);
    await study.context.close();

    study = await openStudy(browser, { scenario: "budget", state: "settled" }, { forcedColors: "active" });
    await deckState(study.frame, "settled");
    const forced = await study.frame.evaluate(() => [...document.querySelectorAll(".cs-deck-wave-mark, .cs-deck-plan-label")]
      .every((node) => getComputedStyle(node).borderTopStyle === "solid" && getComputedStyle(node).borderTopWidth === "1px"));
    assert.equal(forced, true);
    assert.deepEqual(study.errors, []);
    await study.context.close();
  } finally {
    await browser.close();
  }
});
