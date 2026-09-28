import assert from "node:assert/strict";
import { existsSync } from "node:fs";
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

async function sources() {
  const [html, script, layer, rule, action, policy] = await Promise.all([
    readFile(join(uiRoot, "deck-sources.html"), "utf8"),
    readFile(join(uiRoot, "assets/deck-sources.js"), "utf8"),
    readFile(join(root, "ui/calm-slate-deck-conversation.css"), "utf8"),
    readFile(join(root, "rule-catalog/catalog/postgresql-server.point-in-time-restore.yaml"), "utf8"),
    readFile(join(root, "rule-catalog/action-types/remediate.enable-backup-protection.yaml"), "utf8"),
    readFile(join(root, "policies/postgresql/point_in_time_restore.rego"), "utf8"),
  ]);
  return { html, script, layer, rule, action, policy };
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
  const search = new URLSearchParams(query).toString();
  await page.goto(`${origin}/?deck-sources=${Date.now()}#mocks/ui/deck-sources.html${search ? `?${search}` : ""}`,
    { waitUntil: "load" });
  await page.waitForFunction(() => {
    const frame = document.querySelector("#preview-frame");
    return frame?.contentDocument?.readyState === "complete"
      && frame.contentWindow.location.pathname === "/mocks/ui/deck-sources.html";
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

test("study copy stays grounded in the shipped rule catalog", async () => {
  const { html, script, rule, action, policy } = await sources();
  assert.match(rule, /^id: postgresql-server\.point-in-time-restore$/m);
  assert.match(rule, /^severity: high$/m);
  assert.match(rule, /^\s+min_retention_days: 7$/m);
  assert.match(rule, /reference: policies\/postgresql\/point_in_time_restore\.rego/);
  assert.match(policy, /deny_reason := "backup_retention_below_min"/);
  assert.match(action, /^default_mode: shadow$/m);
  assert.match(action, /^\s+min_shadow_days: 21$/m);
  assert.match(action, /^\s+min_samples: 50$/m);
  assert.match(action, /^\s+min_accuracy: 0\.98$/m);
  assert.match(action, /^\s+max_policy_escapes: 0$/m);
  assert.match(action, /t0:\n\s+max_autonomy: enforce_hil/);
  assert.match(action, /^execution_path: pr_native$/m);
  assert.match(action, /^rollback_contract: state_forward_only$/m);

  assert.match(script, /7-day minimum that the point-in-time restore rule requires/);
  assert.match(script, /21 shadow days, 50 samples, 98% accuracy, and zero policy escapes/);
  assert.match(script, /stops at enforce with human approval/);
  for (const safeguard of [
    "stop conditions",
    "single-resource blast radius",
    "idempotency key",
    "forward-only recovery",
    "dry-run receipt",
    "target lock",
    "two-phase audit",
    "independent read confirms",
  ]) {
    assert.ok(script.includes(safeguard), safeguard);
  }
  // Every tool the run record lists is a read; the replay never records a write authority.
  assert.match(script, /\["Authority", "read"\]/);
  assert.doesNotMatch(script, /\["Authority", "(?!read")/);
  for (const stale of [/four safety invariants/, /never a deck button/, /gpt-4o-mini/, /side_effect_class of/,
    /Two peer databases had the identical/, /\bgs-[a-z]/]) {
    assert.doesNotMatch(`${html}\n${script}`, stale);
  }
});

test("study links only to existing mock destinations", async () => {
  const { html, script } = await sources();
  const targets = new Set([
    ...[...html.matchAll(/href="([a-z0-9-]+\.html)"/g)].map((match) => match[1]),
    ...[...script.matchAll(/href: "([a-z0-9-]+\.html)"/g)].map((match) => match[1]),
    ...[...script.matchAll(/href: "([a-z0-9-]+\.html)", text:/g)].map((match) => match[1]),
  ]);
  assert.ok(targets.size >= 10);
  for (const target of targets) assert.ok(existsSync(join(uiRoot, target)), target);
});

test("study markup keeps presentation in shared roles", async () => {
  const { html, script, layer } = await sources();
  const primitives = await readFile(join(root, "ui/calm-slate-primitives.css"), "utf8");
  const roles = new Set([
    ...[...html.matchAll(/class="([^"]+)"/g)].flatMap((match) => match[1].split(/\s+/)),
    ...[...script.matchAll(/class: "([^"]+)"/g)].flatMap((match) => match[1].split(/\s+/)),
    ...[...script.matchAll(/className = "([^"]+)"/g)].flatMap((match) => match[1].split(/\s+/)),
  ].filter((name) => /^cs-(?:deck|grounding|run|model)-/.test(name)));
  assert.ok(roles.size >= 100, `${roles.size} roles`);
  for (const role of roles) {
    assert.ok(layer.includes(`.${role}`) || primitives.includes(`.${role}`), `${role} has no shared style`);
  }
  assert.doesNotMatch(html, /\sstyle="/);
  const declarations = layer.replace(/\/\*[\s\S]*?\*\//g, "");
  assert.doesNotMatch(declarations, /!important/);
  assert.doesNotMatch(declarations, /#[0-9a-f]{3,8}\b/i);
  assert.match(layer, /container-name: deck-transcript;/);
});

test("replay streams preparation, answer, and verification before settling", { timeout: 90000 }, async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const { context, frame, errors } = await openStudy(browser);
    await deckState(frame, "preparing", 5000);
    assert.equal(await frame.locator(".cs-deck-readiness.is-loading[aria-busy='true']").count(), 1);
    assert.equal(await frame.locator("#ds-transcript").getAttribute("aria-busy"), "true");
    assert.equal(await frame.locator("#ds-send").textContent(), "Stop");
    assert.equal(await frame.locator("#ds-send").isDisabled(), false);
    await pressPreview(frame, 'button[data-speed="2"]');
    await frame.locator(".cs-grounding-stage.is-active").first().waitFor({ state: "attached", timeout: 5000 });
    assert.equal(await frame.locator(".cs-deck-answer-skeleton").count(), 1);
    // The whole plan renders up front, so the panel keeps one height while steps run.
    const planned = await frame.locator(".cs-grounding-stage").count();
    assert.ok(planned >= 6, `${planned} planned steps`);
    assert.ok(await frame.locator(".cs-grounding-stage.is-pending").count() >= 1);
    const panelHeight = await frame.locator(".cs-grounding-panel").evaluate((node) => node.getBoundingClientRect().height);
    await frame.waitForFunction(() => {
      const count = document.querySelector(".cs-grounding-sources-head > span:last-child");
      return count && Number.parseInt(count.textContent, 10) >= 4;
    }, null, { timeout: 15000 });
    assert.equal(await frame.locator(".cs-grounding-source-list > li").count(), 3);
    assert.equal(await frame.locator(".cs-grounding-stage").count(), planned);
    const laterHeight = await frame.locator(".cs-grounding-panel").evaluate((node) => node.getBoundingClientRect().height);
    assert.ok(Math.abs(laterHeight - panelHeight) < 0.5, `${panelHeight} -> ${laterHeight}`);
    await deckState(frame, "answering");
    assert.equal(await frame.locator(".cs-deck-turn-head .cs-deck-answer-state.is-draft").textContent(), "Draft");
    assert.equal(await frame.locator(".cs-grounding-panel, .cs-deck-collapse").count(), 0);
    assert.equal(await frame.locator(".cs-deck-agent-source").count(), 0);
    await deckState(frame, "settled");
    assert.equal(await frame.locator("#ds-transcript").getAttribute("aria-busy"), "false");
    assert.equal(await frame.locator("#ds-send").textContent(), "Send");
    assert.equal(await frame.locator(".cs-deck-caret, .cs-deck-answer-state").count(), 0);
    assert.match(await frame.locator(".cs-deck-verification").textContent(), /Verified\s+9 of 9 claims supported/);
    assert.equal(await frame.locator(".cs-deck-followup").count(), 3);
    assert.equal(await frame.locator(".cs-run-record").evaluate((node) => node.open), false);
    assert.match(await frame.locator(".cs-run-record-stats").textContent(), /^Model trace off \u00b7 model /);
    // The automatic first replay stays silent, so no stale progress message remains.
    assert.equal(await frame.locator("#ds-announcer").textContent(), "");
    await pressPreview(frame, "#ds-finish");
    await frame.locator("#ds-announcer")
      .filter({ hasText: /^Answer ready\. Verified: 9 of 9 claims are supported by 7 sources\.$/ })
      .waitFor({ state: "attached", timeout: 3000 });
    assert.deepEqual(errors, []);
    await context.close();
  } finally {
    await browser.close();
  }
});

test("preparation shows each result only after its step and the record matches the replay", { timeout: 90000 }, async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const { context, frame, errors } = await openStudy(browser, { trace: "on" });
    await frame.locator(".cs-grounding-stage.is-active").first().waitFor({ state: "attached", timeout: 5000 });
    const early = await frame.evaluate(() => ({
      placeholders: document.querySelectorAll(".cs-grounding-source.is-placeholder").length,
      headSpinners: document.querySelectorAll(".cs-grounding-head .cs-grounding-spinner").length,
      status: document.querySelector(".cs-grounding-status").textContent,
      pendingHidden: [...document.querySelectorAll(".cs-grounding-stage.is-pending .cs-grounding-stage-detail")]
        .every((node) => getComputedStyle(node).visibility === "hidden"),
      activeMark: !!document.querySelector(".cs-grounding-stage.is-active .cs-grounding-mark .cs-grounding-spinner"),
    }));
    assert.equal(early.placeholders, 3);
    assert.equal(early.headSpinners, 0);
    assert.match(early.status, /^Step 1 of 7$/);
    assert.equal(early.pendingHidden, true);
    assert.equal(early.activeMark, true);
    await frame.waitForFunction(() => document.querySelector(".cs-grounding-status")?.textContent === "Composing answer",
      null, { timeout: 15000 });
    const prepared = await frame.evaluate(() => ({
      elapsed: Number.parseFloat(document.querySelector(".cs-grounding-elapsed").textContent),
      doneShown: [...document.querySelectorAll(".cs-grounding-stage.is-done .cs-grounding-stage-detail")]
        .every((node) => getComputedStyle(node).visibility === "visible"),
      placeholders: document.querySelectorAll(".cs-grounding-source.is-placeholder").length,
    }));
    assert.equal(prepared.doneShown, true);
    assert.equal(prepared.placeholders, 0);
    await deckState(frame, "settled");
    const recorded = Number.parseFloat((await frame.locator(".cs-run-record-duration").textContent()).replace(/^\D+/, ""));
    assert.ok(recorded >= prepared.elapsed, `${recorded} s recorded for ${prepared.elapsed} s of preparation`);
    assert.match(await frame.locator(".cs-run-record-stats").textContent(), /^2 model calls \u00b7 /);
    assert.deepEqual(errors, []);
    await context.close();
  } finally {
    await browser.close();
  }
});

test("stop and scenario changes cancel the running replay", { timeout: 90000 }, async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const { context, frame, errors } = await openStudy(browser);
    await pressPreview(frame, 'button[data-speed="2"]');
    await deckState(frame, "answering");
    await frame.locator("#ds-search").fill("postgres");
    await frame.locator("#ds-send").click();
    await deckState(frame, "stopped", 3000);
    assert.equal(await frame.locator(".cs-deck-turn-head .cs-deck-answer-state.is-stopped").textContent(), "Stopped");
    assert.match(await frame.locator(".cs-deck-evidence-note").last().textContent(), /not verified\. Nothing was changed\./);
    assert.equal(await frame.locator("#ds-send").isDisabled(), true);
    assert.equal(await frame.evaluate(() => document.activeElement?.id), "ds-input");
    assert.match(await frame.locator("#ds-search-count").textContent(), /^1\/\d+$/);
    assert.equal(await frame.locator("#ds-search-next").isDisabled(), false);

    // Regenerating clears the stale stopped state before the new attempt prepares.
    await frame.locator('.cs-deck-action-row [data-action="regenerate"]').click();
    await deckState(frame, "preparing", 3000);
    assert.equal(await frame.locator(".cs-deck-turn-head .cs-deck-answer-state").count(), 0);
    assert.equal(await frame.locator(".cs-deck-turn-head").evaluate((node) => node.childNodes.length), 1);
    assert.equal(await frame.locator(".cs-deck-agent-turn").count(), 1);

    await pressPreview(frame, "#ds-replay");
    await deckState(frame, "preparing", 3000);
    await pressPreview(frame, 'button[data-scenario="conflict"]');
    assert.equal(await frame.locator('button[data-scenario="conflict"]').getAttribute("aria-pressed"), "true");
    await deckState(frame, "settled");
    assert.equal(await frame.locator(".cs-deck-agent-turn").count(), 1);
    assert.match(await frame.locator(".cs-deck-verification").textContent(), /Conflicting evidence/);
    assert.deepEqual(errors, []);
    await context.close();
  } finally {
    await browser.close();
  }
});

test("each scenario settles with explicit evidence posture and ordered citations", { timeout: 90000 }, async () => {
  const expectations = {
    grounded: { verification: /Verified/, summary: "All available", note: null, state: null, issue: null },
    partial: { verification: /Partial evidence/, summary: "1 unavailable", note: /Evidence limit: shadow history is unavailable/, state: "Partial", issue: "partial evidence" },
    unavailable: { verification: /Source unavailable/, summary: "1 unavailable", note: /Unknown: the current backup_retention_days/, state: null, issue: "source unavailable" },
    conflict: { verification: /Conflicting evidence/, summary: "All available", note: /Conflicting evidence: FDAI treats neither reading/, state: null, issue: "conflicting evidence" },
    corrected: { verification: /Corrected/, summary: "All available", note: /Corrected: verification removed 1 sentence/, state: "Corrected", issue: null },
  };
  const browser = await chromium.launch({ headless: true });
  try {
    for (const [scenario, expected] of Object.entries(expectations)) {
      const { context, frame, errors } = await openStudy(browser, { scenario, state: "settled" });
      await deckState(frame, "settled", 5000);
      assert.match(await frame.locator(".cs-deck-verification").textContent(), expected.verification, scenario);
      assert.equal(await frame.locator(".cs-deck-readiness-summary").textContent(), expected.summary, scenario);
      if (expected.note) assert.match(await frame.locator(".cs-deck-evidence-note").textContent(), expected.note, scenario);
      else assert.equal(await frame.locator(".cs-deck-evidence-note").count(), 0, scenario);
      if (expected.state) {
        assert.equal(await frame.locator(".cs-deck-turn-head .cs-deck-answer-state").textContent(), expected.state, scenario);
      }
      else assert.equal(await frame.locator(".cs-deck-answer-state").count(), 0, scenario);
      if (expected.issue) assert.equal(await frame.locator(".cs-deck-pill-issue").textContent(), expected.issue, scenario);
      else assert.equal(await frame.locator(".cs-deck-pill-issue").count(), 0, scenario);
      const citations = await frame.evaluate(() => {
        const article = document.querySelector(".cs-deck-agent-turn");
        const cites = [...article.querySelectorAll("a.cs-deck-cite")];
        const firstSeen = [];
        for (const cite of cites) if (!firstSeen.includes(cite.textContent)) firstSeen.push(cite.textContent);
        return {
          firstSeen: firstSeen.map(Number),
          rows: article.querySelectorAll(".cs-deck-source").length,
          missing: cites.filter((cite) => !document.getElementById(cite.getAttribute("href").slice(1))).length,
        };
      });
      assert.equal(citations.missing, 0, scenario);
      assert.deepEqual(citations.firstSeen, citations.firstSeen.slice().sort((a, b) => a - b), scenario);
      assert.equal(citations.firstSeen.length, citations.rows, scenario);
      assert.deepEqual(errors, [], scenario);
      await context.close();
    }
  } finally {
    await browser.close();
  }
});

test("citations, sources, follow-ups, and search work from the keyboard", { timeout: 90000 }, async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const { context, page, frame, errors } = await openStudy(browser, { state: "settled" });
    await deckState(frame, "settled", 5000);
    const cite = frame.locator("a.cs-deck-cite").nth(2);
    await cite.focus();
    const tooltip = frame.locator("#ds-tooltip");
    assert.equal(await tooltip.isVisible(), true);
    assert.equal(await tooltip.getAttribute("role"), "tooltip");
    assert.match(await tooltip.textContent(), /postgresql-server\.point-in-time-restore/);
    assert.equal(await cite.getAttribute("aria-describedby"), "ds-tooltip");
    await page.keyboard.press("Escape");
    assert.equal(await tooltip.isVisible(), false);
    await page.keyboard.press("Enter");
    assert.equal(await frame.locator("[data-action='sources']").getAttribute("aria-expanded"), "true");
    assert.equal(await frame.evaluate(() => document.activeElement?.id), "ds-turn-1-source-3");
    assert.equal(await frame.locator("#ds-turn-1-source-3").evaluate((node) => node.classList.contains("is-target")), true);

    await frame.locator(".cs-deck-followup").first().click();
    await deckState(frame, "preparing", 3000);
    assert.equal(await frame.locator(".cs-deck-followup").first().getAttribute("aria-disabled"), "true");
    await deckState(frame, "settled");
    assert.equal(await frame.locator(".cs-deck-agent-turn").count(), 2);
    assert.equal(await frame.locator(".cs-deck-followup").count(), 2);
    assert.match(await frame.locator(".cs-deck-user-line").last().textContent(), /Why is it still in shadow mode\?/);

    await frame.locator("#ds-search").fill("shadow");
    await frame.locator("#ds-search-count").filter({ hasText: /^1\/\d+$/ }).waitFor({ timeout: 3000 });
    assert.ok(await frame.locator("mark.cs-deck-search-hit").count() >= 3);
    await frame.locator("#ds-search").press("Enter");
    assert.match(await frame.locator("#ds-search-count").textContent(), /^2\/\d+$/);
    assert.deepEqual(errors, []);
    await context.close();
  } finally {
    await browser.close();
  }
});

test("keyboard focus and closed-deck state survive turn completion", { timeout: 90000 }, async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const { context, frame, errors } = await openStudy(browser);
    await pressPreview(frame, 'button[data-speed="2"]');
    await deckState(frame, "preparing", 5000);
    await frame.locator("#ds-send").focus();
    await deckState(frame, "settled");
    assert.equal(await frame.evaluate(() => document.activeElement?.id), "ds-input");

    await pressPreview(frame, "#ds-replay");
    await deckState(frame, "preparing", 3000);
    await frame.locator("#ds-close").click();
    await deckState(frame, "closed", 3000);
    await pressPreview(frame, "#ds-finish");
    assert.equal(await frame.evaluate(() => document.body.dataset.deckState), "closed");
    await frame.locator("#ds-reopen").click();
    await deckState(frame, "settled", 3000);
    assert.equal(await frame.locator(".cs-deck-answer-state.is-stopped").count(), 0);
    assert.match(await frame.locator(".cs-deck-verification").textContent(), /Verified/);
    assert.deepEqual(errors, []);
    await context.close();
  } finally {
    await browser.close();
  }
});

test("run record shows the observed process and captures model traces per turn", { timeout: 90000 }, async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const { context, frame, errors } = await openStudy(browser, { state: "settled" });
    await deckState(frame, "settled", 5000);
    const first = frame.locator(".cs-run-record").first();
    assert.equal(await frame.locator(".cs-run-record").count(), 1);
    assert.equal(await first.locator(".cs-run-record-body").evaluate((node) => node.childElementCount), 0);
    assert.match(await first.locator(".cs-run-record-stats").textContent(),
      /^Model trace off \u00b7 model 1\.15 s \u00b7 3,256 tokens \u00b7 evidence 7 of 7 \u00b7 verification completed$/);
    assert.match(await first.locator(".cs-run-record-duration").textContent(), /^Server processing \d+\.\d+ s$/);
    await first.locator(":scope > summary").click();
    assert.equal(await first.locator(".cs-run-phase").count(), 6);
    assert.equal(await first.locator(".cs-run-event").count(), 12);
    assert.equal(await first.locator('.cs-run-event[data-kind="model"]').count(), 0);
    assert.match(await first.locator(".cs-model-trace-note").textContent(), /^Provider trace capture is off/);

    // A deterministic read keeps its typed query and observed output in the event detail.
    const read = first.locator('.cs-run-event[data-kind="evidence"]').first();
    await read.locator("summary").click();
    assert.match(await read.locator(".cs-run-event-detail").textContent(), /screen\.snapshot route=live tile=12/);

    // Turning capture on never reveals a turn that was answered without it.
    await frame.locator("#ds-trace").evaluate((input) => input.click());
    assert.match(await first.locator(".cs-run-record-stats").textContent(), /^Model trace not captured \u00b7 /);
    // An open record is rebuilt with its body already filled.
    assert.equal(await first.evaluate((node) => node.open), true);
    assert.match(await first.locator(".cs-model-trace-note").textContent(), /^Model trace not captured/);
    assert.equal(await first.locator('.cs-run-event[data-kind="model"]').count(), 0);

    await pressPreview(frame, 'button[data-speed="2"]');
    await frame.locator(".cs-deck-followup").first().click();
    await deckState(frame, "preparing", 3000);
    await deckState(frame, "settled");
    const second = frame.locator(".cs-run-record").nth(1);
    assert.match(await second.locator(".cs-run-record-stats").textContent(), /^2 model calls \u00b7 /);
    await second.locator(":scope > summary").click();
    assert.equal(await second.locator('.cs-run-event[data-kind="model"]').count(), 2);
    assert.equal(await second.locator(".cs-model-trace-lane").count(), 2);
    assert.equal(await second.locator(".cs-model-trace-count").textContent(), "2 model calls");
    const lane = second.locator(".cs-model-trace-lane").first();
    await lane.locator("summary").click();
    await frame.waitForFunction(() => [...document.querySelectorAll(".cs-model-trace-lane details[open] .cs-model-trace-hash code")]
      .every((code) => /^[0-9a-f]{64}$/.test(code.textContent)), null, { timeout: 3000 });
    assert.equal(await lane.locator(".cs-model-trace-hash").count(), 3);
    assert.equal(await lane.locator(".cs-model-trace-layers > li").count(), 4);
    assert.ok(await lane.locator(".cs-model-trace-messages > li").count() >= 2);
    assert.match(await lane.textContent(), /Assistant response/);

    // The display setting hides captured provider data again without discarding the record.
    await frame.locator("#ds-trace").evaluate((input) => input.click());
    assert.match(await second.locator(".cs-run-record-stats").textContent(), /^Model trace off \u00b7 /);
    assert.equal(await frame.locator(".cs-model-trace-lane").count(), 0);
    assert.deepEqual(errors, []);
    await context.close();
  } finally {
    await browser.close();
  }
});

test("run record reads as one quiet line and colors only trouble", { timeout: 60000 }, async () => {
  const { layer } = await sources();
  assert.match(layer, /::details-content \{\n  block-size: 0;/);
  const browser = await chromium.launch({ headless: true });
  try {
    const { context, frame, errors } = await openStudy(browser, { state: "settled", scenario: "partial", trace: "on" });
    await deckState(frame, "settled", 5000);
    await frame.locator(".cs-run-record > summary").click();
    const record = await frame.evaluate(() => {
      const summary = document.querySelector(".cs-run-record-summary");
      const color = (node) => getComputedStyle(node).color;
      const completed = document.querySelector('.cs-run-event[data-state="completed"] .cs-run-event-outcome');
      const failed = document.querySelector('.cs-run-event[data-state="failed"] .cs-run-event-outcome');
      const kind = document.querySelector(".cs-run-event-kind");
      return {
        heading: summary.querySelector(".cs-run-record-heading").textContent,
        kicker: summary.querySelectorAll(".cs-run-record-kicker").length,
        oneLine: summary.getBoundingClientRect().height <= 48,
        statsFit: summary.querySelector(".cs-run-record-stats").scrollWidth <= summary.querySelector(".cs-run-record-stats").clientWidth,
        completedNeutral: color(completed) === color(kind),
        failedColored: color(failed) !== color(kind),
        kindBorder: getComputedStyle(kind).borderTopStyle,
        completedPhaseLabels: [...document.querySelectorAll('.cs-run-phase[data-state="completed"] small')]
          .every((node) => node.classList.contains("cs-sr-only")),
        degradedPhaseLabel: document.querySelector('.cs-run-phase[data-state="degraded"] small').classList.contains("cs-sr-only"),
      };
    });
    assert.equal(record.heading, "Run record");
    assert.equal(record.kicker, 0);
    assert.equal(record.oneLine, true);
    assert.equal(record.statsFit, true);
    assert.equal(record.completedNeutral, true);
    assert.equal(record.failedColored, true);
    assert.equal(record.kindBorder, "none");
    assert.equal(record.completedPhaseLabels, true);
    assert.equal(record.degradedPhaseLabel, false);
    assert.deepEqual(errors, []);
    await context.close();
  } finally {
    await browser.close();
  }
});

test("run record payloads use the component gallery's compact code pattern", { timeout: 60000 }, async () => {
  const [tokens, gallery] = await Promise.all([
    readFile(join(root, "ui/calm-slate-tokens.css"), "utf8"),
    readFile(join(uiRoot, "assets/calm-slate.css"), "utf8"),
  ]);
  assert.match(tokens, /--cs-code-bg: #222a31;/);
  assert.match(gallery, /\.cs-code-compact \{[^}]*background: var\(--cs-code-bg\)/);
  assert.match(gallery, /\.cs-code-token\.is-key \{ color: var\(--cs-code-key\); \}/);
  const browser = await chromium.launch({ headless: true });
  try {
    const { context, frame, errors } = await openStudy(browser, { state: "settled", trace: "on" });
    await context.grantPermissions(["clipboard-read", "clipboard-write"], { origin });
    await deckState(frame, "settled", 5000);
    await frame.locator(".cs-run-record > summary").click();
    const event = frame.locator('.cs-run-event[data-kind="evidence"]').first();
    await event.locator("summary").click();
    const blocks = await event.evaluate((node) => [...node.querySelectorAll(".cs-deck-code")].map((block) => ({
      lang: block.querySelector(".cs-deck-code-lang").textContent,
      copy: block.querySelector(".cs-deck-code-copy").getAttribute("aria-label"),
      background: getComputedStyle(block).backgroundColor,
      tokens: [...new Set([...block.querySelectorAll(".cs-deck-code-token")].map((token) => token.className.split(" ")[1]))].sort(),
    })));
    assert.deepEqual(blocks.map((block) => block.lang), ["query", "json"]);
    assert.deepEqual(blocks.map((block) => block.copy), ["Copy query", "Copy JSON"]);
    assert.ok(blocks.every((block) => block.background === "rgb(34, 42, 49)"), blocks.map((block) => block.background).join(","));
    assert.deepEqual(blocks[0].tokens, ["is-command", "is-flag"]);
    assert.deepEqual(blocks[1].tokens, ["is-key", "is-number", "is-punctuation", "is-string"]);
    assert.equal(await frame.locator(".cs-run-code").count(), 0);

    // Copy returns the exact source, then the button settles back to its idle label.
    const copy = event.locator(".cs-deck-code-copy").nth(1);
    await copy.click();
    await frame.locator(".cs-deck-code-copy.is-copied").waitFor({ state: "attached", timeout: 2000 });
    assert.equal(await copy.textContent(), "Copied");
    const copied = await frame.evaluate(() => navigator.clipboard.readText());
    assert.equal(JSON.parse(copied).resource, "example-postgres");
    assert.match(copied, /\n  "route": "live",\n/);
    await frame.locator(".cs-deck-code-copy.is-copied").waitFor({ state: "detached", timeout: 3000 });
    assert.equal(await copy.textContent(), "Copy");
    assert.deepEqual(errors, []);
    await context.close();
  } finally {
    await browser.close();
  }
});

test("trace capture can start on from the URL", { timeout: 60000 }, async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const { context, frame, errors } = await openStudy(browser, { state: "settled", scenario: "partial", trace: "on" });
    await deckState(frame, "settled", 5000);
    assert.equal(await frame.locator("#ds-trace").isChecked(), true);
    assert.match(await frame.locator(".cs-run-record-stats").textContent(), /^2 model calls \u00b7 .*evidence 6 of 7 \u00b7 verification degraded$/);
    await frame.locator(".cs-run-record > summary").click();
    assert.equal(await frame.locator('.cs-run-event[data-state="failed"]').count(), 1);
    assert.equal(await frame.locator('.cs-run-phase[data-state="degraded"]').count(), 2);
    assert.deepEqual(errors, []);
    await context.close();
  } finally {
    await browser.close();
  }
});

test("streaming reveals whole words in place and follow-ups rise to the top without jumps", { timeout: 90000 }, async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const { context, frame, errors } = await openStudy(browser, {}, { viewport: { width: 993, height: 641 } });
    // Sample every frame: streamed words must end at a word boundary and never move once shown.
    await frame.evaluate(() => {
      const report = window.__streamCheck = { frames: 0, partial: 0, moved: 0, maxScrollStep: 0, questionAbove: 0 };
      const seen = new WeakMap();
      const transcript = document.getElementById("ds-transcript");
      let lastScroll = transcript.scrollTop;
      const tick = () => {
        const caret = document.querySelector(".cs-deck-caret");
        const paragraph = caret && caret.closest("p");
        if (paragraph) {
          report.frames += 1;
          const chunks = paragraph.querySelectorAll(".cs-deck-stream-in");
          const lastChunk = chunks[chunks.length - 1];
          if (lastChunk && !lastChunk.matches(".cs-deck-cite-run, .cs-deck-cite, code") && !/[\s.,;:!?)]$/.test(lastChunk.textContent)) {
            report.partial += 1;
          }
          const base = paragraph.getBoundingClientRect();
          chunks.forEach((chunk) => {
            const rect = chunk.getClientRects()[0];
            if (!rect) return;
            const spot = [rect.left - base.left, rect.top - base.top];
            const before = seen.get(chunk);
            if (before && (Math.abs(spot[0] - before[0]) > 1 || Math.abs(spot[1] - before[1]) > 1)) report.moved += 1;
            seen.set(chunk, spot);
          });
        }
        report.maxScrollStep = Math.max(report.maxScrollStep, Math.abs(transcript.scrollTop - lastScroll));
        lastScroll = transcript.scrollTop;
        const questions = transcript.querySelectorAll(".cs-deck-user-turn");
        const question = questions[questions.length - 1];
        if (document.body.dataset.deckState !== "settled" && question &&
            question.getBoundingClientRect().top < transcript.getBoundingClientRect().top - 1) report.questionAbove += 1;
        requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    });
    await deckState(frame, "settled");
    // Scroll the way a reader would before choosing a follow-up, then measure only the app's motion.
    await frame.evaluate(() => {
      const transcript = document.getElementById("ds-transcript");
      transcript.scrollTop = transcript.scrollHeight;
      window.__streamCheck.maxScrollStep = 0;
    });
    await frame.waitForTimeout(100);
    await frame.evaluate(() => { window.__streamCheck.maxScrollStep = 0; });
    await frame.locator(".cs-deck-followup").first().evaluate((button) => button.click());
    await deckState(frame, "preparing", 3000);
    await deckState(frame, "settled");
    await frame.waitForTimeout(600);
    const report = await frame.evaluate(() => {
      const transcript = document.getElementById("ds-transcript").getBoundingClientRect();
      const row = document.querySelectorAll(".cs-deck-agent-turn")[1].querySelector(":scope > .cs-deck-action-row");
      const box = row.getBoundingClientRect();
      return { ...window.__streamCheck, verdictVisible: box.top >= transcript.top && box.bottom <= transcript.bottom };
    });
    assert.ok(report.frames > 20, `${report.frames} streaming frames`);
    assert.equal(report.partial, 0);
    assert.equal(report.moved, 0);
    assert.equal(report.questionAbove, 0);
    assert.ok(report.maxScrollStep <= 30, `${report.maxScrollStep}px scroll step`);
    // While the turn is live the question holds at the top; on settle the view eases to the verdict.
    assert.equal(report.verdictVisible, true);
    // Settled parts arrive with a short stagger instead of appearing at once.
    const second = frame.locator(".cs-deck-agent-turn").nth(1);
    assert.equal(await second.locator(":scope > .cs-deck-action-row.cs-deck-enter").count(), 1);
    assert.equal(await second.locator(':scope > .cs-run-record.cs-deck-enter[data-enter]').count(), 1);
    assert.deepEqual(errors, []);
    await context.close();
  } finally {
    await browser.close();
  }
});

test("settled answers keep the verdict, sources, tools, and record together", { timeout: 60000 }, async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    let { context, frame, errors } = await openStudy(browser, { state: "settled" });
    await deckState(frame, "settled", 5000);
    const layout = await frame.evaluate(() => {
      const article = document.querySelector(".cs-deck-agent-turn");
      const head = article.querySelector(".cs-deck-turn-head");
      const tools = [...article.querySelectorAll(".cs-deck-tools .cs-deck-tool")];
      return {
        order: [...article.children].map((node) => node.className.split(" ")[0]),
        time: head.querySelector(".cs-deck-agent-name + .cs-deck-head-time")?.textContent,
        tools: tools.map((node) => node.getAttribute("aria-label")),
        quiet: tools.every((node) => getComputedStyle(node).borderTopColor === "rgba(0, 0, 0, 0)"),
        pillMarks: article.querySelectorAll(".cs-deck-pill .cs-deck-pill-mark").length,
      };
    });
    assert.deepEqual(layout.order, ["cs-deck-turn-head", "cs-deck-answer", "cs-deck-action-row", "cs-deck-sources",
      "cs-run-record", "cs-deck-followups"]);
    assert.equal(layout.time, "10:41");
    assert.deepEqual(layout.tools, ["Copy reply", "Regenerate", "Review answer quality"]);
    assert.equal(layout.quiet, true);
    assert.equal(layout.pillMarks, 0);
    await frame.locator("[data-action='sources']").click();
    const opened = await frame.evaluate(() => ({
      rotated: getComputedStyle(document.querySelector(".cs-deck-pill-more > svg")).transform !== "none",
      rowBorders: [...document.querySelectorAll(".cs-deck-source")].every((node) => getComputedStyle(node).borderTopStyle === "none"),
      listBorder: getComputedStyle(document.querySelector(".cs-deck-source-list")).borderTopStyle,
    }));
    assert.equal(opened.rotated, true);
    assert.equal(opened.rowBorders, true);
    assert.equal(opened.listBorder, "solid");
    assert.deepEqual(errors, []);
    await context.close();

    ({ context, frame, errors } = await openStudy(browser, { state: "settled", scenario: "partial" }));
    await deckState(frame, "settled", 5000);
    const edges = await frame.evaluate(() => {
      const prose = document.querySelector(".cs-deck-prose").getBoundingClientRect();
      const note = document.querySelector(".cs-deck-evidence-note").getBoundingClientRect();
      return { prose: Math.round(prose.right), note: Math.round(note.right) };
    });
    assert.equal(edges.note, edges.prose);
    assert.equal(await frame.locator(".cs-deck-pill .cs-deck-pill-mark").textContent(), "!");
    assert.deepEqual(errors, []);
    await context.close();
  } finally {
    await browser.close();
  }
});

test("tooltips wait for hover intent and chosen follow-ups fold away", { timeout: 90000 }, async () => {
  const { layer } = await sources();
  assert.match(layer, /@starting-style \{\n  \.cs-deck-jump/);
  const browser = await chromium.launch({ headless: true });
  try {
    const { context, frame, errors } = await openStudy(browser, { state: "settled" });
    await deckState(frame, "settled", 5000);
    const cite = frame.locator("a.cs-deck-cite").first();
    await cite.hover();
    assert.equal(await frame.locator("#ds-tooltip").isVisible(), false);
    await frame.locator("#ds-tooltip").waitFor({ state: "visible", timeout: 2000 });
    await frame.locator(".cs-deck-prose > p").first().hover({ position: { x: 4, y: 4 } });
    assert.equal(await frame.locator("#ds-tooltip").isVisible(), false);

    const count = await frame.locator(".cs-deck-followup").count();
    await frame.locator(".cs-deck-followup").first().evaluate((button) => button.click());
    const retiring = frame.locator(".cs-deck-followups > li").first();
    assert.equal(await retiring.evaluate((node) => node.inert), true);
    await frame.waitForFunction((before) => document.querySelectorAll(".cs-deck-agent-turn")[0]
      .querySelectorAll(".cs-deck-followup").length === before - 1, count, { timeout: 2000 });
    assert.deepEqual(errors, []);
    await context.close();
  } finally {
    await browser.close();
  }
});

test("the follower yields to focus moves and keeps a keyboard-started turn pinned", { timeout: 90000 }, async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const { context, page, frame, errors } = await openStudy(browser, {}, { viewport: { width: 993, height: 641 } });
    await pressPreview(frame, 'button[data-speed="2"]');
    await deckState(frame, "settled");
    const inView = () => frame.evaluate(() => {
      const box = document.activeElement.getBoundingClientRect();
      const view = document.getElementById("ds-transcript").getBoundingClientRect();
      return box.top >= view.top - 1 && box.bottom <= view.bottom + 1;
    });
    const questionOffset = () => frame.evaluate(() => {
      const questions = document.querySelectorAll(".cs-deck-user-turn");
      return questions[questions.length - 1].getBoundingClientRect().top - document.getElementById("ds-transcript").getBoundingClientRect().top;
    });

    // Space activates the follow-up; the new question still rises to the top edge.
    await frame.locator(".cs-deck-followup").first().focus();
    await page.keyboard.press(" ");
    await deckState(frame, "preparing", 3000);
    await frame.waitForTimeout(1200);
    const offset = await questionOffset();
    assert.ok(offset >= -1 && offset <= 40, `${Math.round(offset)}px question offset`);

    // Tab brings the next follow-up into view; the follower must not pull it away again.
    await page.keyboard.press("Tab");
    await frame.waitForTimeout(900);
    assert.equal(await frame.evaluate(() => document.activeElement.classList.contains("cs-deck-followup")), true);
    assert.equal(await inView(), true);
    assert.deepEqual(errors, []);
    await context.close();
  } finally {
    await browser.close();
  }
});

test("short turns size the source window and the preparation panel fades out", { timeout: 90000 }, async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const { context, frame, errors } = await openStudy(browser, { state: "settled" });
    await deckState(frame, "settled", 5000);
    await frame.locator(".cs-deck-followup").first().evaluate((button) => button.click());
    await frame.waitForFunction(() => document.querySelector(".cs-grounding-status")?.textContent === "Composing answer",
      null, { timeout: 15000 });
    const window = await frame.evaluate(() => {
      const list = document.querySelector(".cs-grounding-source-list");
      return {
        rows: list.style.getPropertyValue("--cs-grounding-source-rows"),
        items: list.children.length,
        placeholders: list.querySelectorAll(".is-placeholder").length,
        height: Math.round(list.getBoundingClientRect().height),
      };
    });
    assert.deepEqual(window, { rows: "2", items: 2, placeholders: 0, height: 64 });
    // Sample the fold every frame: it must pass through partial opacity instead of vanishing.
    const fades = await frame.evaluate(() => new Promise((resolve) => {
      const seen = [];
      const tick = () => {
        const fold = document.querySelector(".cs-deck-collapse.is-collapsed");
        if (fold) seen.push(Number(getComputedStyle(fold).opacity));
        if (seen.length >= 10 || (!fold && seen.length)) resolve(seen);
        else requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    }));
    assert.ok(fades.some((value) => value > 0.05 && value < 0.95), fades.join(","));
    assert.deepEqual(errors, []);
    await context.close();
  } finally {
    await browser.close();
  }
});

test("stopping mid-paragraph keeps only the revealed words", { timeout: 60000 }, async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const { context, frame, errors } = await openStudy(browser);
    await pressPreview(frame, 'button[data-speed="0.5"]');
    await deckState(frame, "answering");
    // Check and stop in one frame, so the stop lands while citations are still unrevealed.
    await frame.waitForFunction(() => {
      const prose = document.querySelector(".cs-deck-agent-turn .cs-deck-prose");
      if (!prose || !prose.textContent.trim() || !prose.querySelector("[hidden]")) return false;
      document.getElementById("ds-send").click();
      return true;
    }, null, { timeout: 10000, polling: "raf" });
    await deckState(frame, "stopped", 3000);
    assert.equal(await frame.locator(".cs-deck-prose [hidden]").count(), 0);
    assert.equal(await frame.locator(".cs-deck-prose p").evaluateAll((nodes) =>
      nodes.every((node) => node.textContent.trim().length > 0)), true);
    assert.match(await frame.locator(".cs-deck-evidence-note").last().textContent(), /this partial answer was not verified/);
    assert.deepEqual(errors, []);
    await context.close();
  } finally {
    await browser.close();
  }
});

test("run record keeps wide timeline content inside the record above the compact breakpoint", { timeout: 60000 }, async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const { context, frame, errors } = await openStudy(browser, { state: "settled", trace: "on" },
      { viewport: { width: 975, height: 800 }, reducedMotion: "reduce" });
    await deckState(frame, "settled", 5000);
    await frame.locator(".cs-run-record > summary").click();
    await frame.evaluate(() => document.querySelectorAll(".cs-run-record details").forEach((node) => { node.open = true; }));
    const layout = await frame.evaluate(() => {
      const record = document.querySelector(".cs-run-record");
      const edge = record.getBoundingClientRect().right + 0.5;
      const body = record.querySelector(".cs-run-record-body");
      return {
        column: document.querySelector(".cs-deck-transcript").clientWidth,
        lanes: record.querySelectorAll(".cs-model-trace-lane details[open]").length,
        clipped: [...record.querySelectorAll("*")].filter((node) => {
          const box = node.getBoundingClientRect();
          return box.width > 0 && box.right > edge;
        }).length,
        bodyFits: body.scrollWidth <= body.clientWidth,
        kindShown: getComputedStyle(record.querySelector(".cs-run-event-kind")).display !== "none",
      };
    });
    assert.ok(layout.column > 620 && layout.column < 660, `${layout.column}px column`);
    assert.equal(layout.kindShown, true);
    assert.equal(layout.lanes, 2);
    assert.equal(layout.clipped, 0);
    assert.equal(layout.bodyFits, true);
    assert.deepEqual(errors, []);
    await context.close();
  } finally {
    await browser.close();
  }
});

test("dock width uses container layout without horizontal overflow", { timeout: 60000 }, async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const { context, frame, errors } = await openStudy(browser, { state: "settled", width: "dock" });
    await deckState(frame, "settled", 5000);
    await frame.locator(".cs-run-record > summary").click();
    await frame.locator("[data-action='sources']").click();
    assert.equal(await frame.locator(".cs-deck-sources").isVisible(), true);
    const layout = await frame.evaluate(() => {
      const workspace = document.getElementById("ds-workspace").getBoundingClientRect();
      const event = document.querySelector(".cs-run-event-summary");
      const phases = document.querySelector(".cs-run-phase-strip");
      const source = document.querySelector(".cs-deck-source");
      const label = document.querySelector(".cs-deck-readiness-label");
      const overflow = ["#ds-workspace", "#ds-transcript", "#ds-composer", ".cs-deck-sources", ".cs-run-record"].map((selector) => {
        const node = document.querySelector(selector);
        return node.scrollWidth <= node.clientWidth;
      });
      return {
        width: Math.round(workspace.width),
        columns: getComputedStyle(event).gridTemplateColumns.split(" ").length,
        phaseColumns: getComputedStyle(phases).gridTemplateColumns.split(" ").length,
        kindShown: getComputedStyle(event.querySelector(".cs-run-event-kind")).display !== "none",
        sourceColumns: getComputedStyle(source).gridTemplateColumns.split(" ").length,
        labelClip: getComputedStyle(label).clipPath,
        overflow,
        documentFits: document.documentElement.scrollWidth <= document.documentElement.clientWidth,
      };
    });
    assert.ok(layout.width <= 440, `${layout.width}`);
    assert.equal(layout.columns, 4);
    assert.equal(layout.phaseColumns, 3);
    assert.equal(layout.kindShown, false);
    assert.equal(layout.sourceColumns, 2);
    assert.equal(layout.labelClip, "inset(50%)");
    assert.deepEqual(layout.overflow, [true, true, true, true, true]);
    assert.equal(layout.documentFits, true);
    assert.deepEqual(errors, []);
    await context.close();
  } finally {
    await browser.close();
  }
});

test("empty, closed, reduced-motion, and forced-colors states stay operable", { timeout: 90000 }, async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    let { context, frame, errors } = await openStudy(browser, {}, { reducedMotion: "reduce" });
    await deckState(frame, "settled", 5000);
    assert.equal(await frame.locator(".cs-grounding-panel").count(), 0);
    await frame.locator("#ds-new").click();
    await deckState(frame, "empty", 3000);
    assert.equal(await frame.locator("#ds-conversation-title").textContent(), "New conversation");
    assert.equal(await frame.evaluate(() => document.activeElement?.classList.contains("ds-intro-card")), true);
    await frame.locator(".ds-intro-card").press("Enter");
    await deckState(frame, "preparing", 3000);
    assert.equal(await frame.evaluate(() => document.activeElement?.id), "ds-input");
    await deckState(frame, "settled");
    assert.equal(await frame.locator(".cs-deck-caret").count(), 0);
    await frame.locator("#ds-close").click();
    await deckState(frame, "closed", 3000);
    assert.equal(await frame.locator("#ds-closed").isVisible(), true);
    await frame.locator("#ds-reopen").click();
    assert.equal(await frame.evaluate(() => document.activeElement?.id), "ds-input");
    await frame.locator("#ds-input").fill("Is anything else flagged?");
    await frame.locator("#ds-input").press("Enter");
    assert.match(await frame.locator("#ds-composer-note").textContent(), /Preview only/);
    assert.equal(await frame.locator("#ds-input").inputValue(), "Is anything else flagged?");
    assert.deepEqual(errors, []);
    await context.close();

    ({ context, frame, errors } = await openStudy(browser, { state: "settled" }, { forcedColors: "active" }));
    await deckState(frame, "settled", 5000);
    const borders = await frame.evaluate(() => [".cs-deck-cite", ".cs-deck-readiness-item", ".cs-grounding-phase"]
      .map((selector) => document.querySelector(selector))
      .filter(Boolean)
      .map((node) => getComputedStyle(node).borderTopStyle));
    assert.ok(borders.length >= 2);
    assert.ok(borders.every((style) => style !== "none"), borders.join(","));
    assert.deepEqual(errors, []);
    await context.close();
  } finally {
    await browser.close();
  }
});
