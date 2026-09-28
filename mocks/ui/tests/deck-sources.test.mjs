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
  assert.match(script, /side_effect_class: read/);
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
  ].filter((name) => /^cs-(?:deck|grounding)-/.test(name)));
  assert.ok(roles.size >= 60, `${roles.size} roles`);
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
    await frame.waitForFunction(() => {
      const count = document.querySelector(".cs-grounding-sources-head > span:last-child");
      return count && Number.parseInt(count.textContent, 10) >= 4;
    }, null, { timeout: 15000 });
    assert.equal(await frame.locator(".cs-grounding-source-list > li").count(), 3);
    await deckState(frame, "answering");
    assert.equal(await frame.locator(".cs-deck-answer-state.is-draft").textContent(), "Draft");
    assert.equal(await frame.locator(".cs-grounding-panel").count(), 0);
    await deckState(frame, "settled");
    assert.equal(await frame.locator("#ds-transcript").getAttribute("aria-busy"), "false");
    assert.equal(await frame.locator("#ds-send").textContent(), "Send");
    assert.equal(await frame.locator(".cs-deck-caret, .cs-deck-answer-state").count(), 0);
    assert.match(await frame.locator(".cs-deck-verification").textContent(), /Verified\s+9 of 9 claims supported/);
    assert.equal(await frame.locator(".cs-deck-followup").count(), 3);
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

test("stop and scenario changes cancel the running replay", { timeout: 90000 }, async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const { context, frame, errors } = await openStudy(browser);
    await pressPreview(frame, 'button[data-speed="2"]');
    await deckState(frame, "answering");
    await frame.locator("#ds-search").fill("postgres");
    await frame.locator("#ds-send").click();
    await deckState(frame, "stopped", 3000);
    assert.equal(await frame.locator(".cs-deck-answer-state.is-stopped").textContent(), "Stopped");
    assert.match(await frame.locator(".cs-deck-evidence-note").last().textContent(), /not verified\. Nothing was changed\./);
    assert.equal(await frame.locator("#ds-send").isDisabled(), true);
    assert.equal(await frame.evaluate(() => document.activeElement?.id), "ds-input");
    assert.match(await frame.locator("#ds-search-count").textContent(), /^1\/\d+$/);
    assert.equal(await frame.locator("#ds-search-next").isDisabled(), false);

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
      if (expected.state) assert.equal(await frame.locator(".cs-deck-answer-state").textContent(), expected.state, scenario);
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

test("dock width uses container layout without horizontal overflow", { timeout: 60000 }, async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const { context, frame, errors } = await openStudy(browser, { state: "settled", width: "dock" });
    await deckState(frame, "settled", 5000);
    await frame.locator(".cs-deck-processing > summary").click();
    await frame.locator("[data-action='sources']").click();
    assert.equal(await frame.locator(".cs-deck-sources").isVisible(), true);
    const layout = await frame.evaluate(() => {
      const workspace = document.getElementById("ds-workspace").getBoundingClientRect();
      const stage = document.querySelector(".cs-deck-processing .cs-grounding-stage");
      const source = document.querySelector(".cs-deck-source");
      const label = document.querySelector(".cs-deck-readiness-label");
      const overflow = ["#ds-workspace", "#ds-transcript", "#ds-composer", ".cs-deck-sources"].map((selector) => {
        const node = document.querySelector(selector);
        return node.scrollWidth <= node.clientWidth;
      });
      return {
        width: Math.round(workspace.width),
        columns: getComputedStyle(stage).gridTemplateColumns.split(" ").length,
        sourceColumns: getComputedStyle(source).gridTemplateColumns.split(" ").length,
        labelClip: getComputedStyle(label).clipPath,
        overflow,
        documentFits: document.documentElement.scrollWidth <= document.documentElement.clientWidth,
      };
    });
    assert.ok(layout.width <= 440, `${layout.width}`);
    assert.equal(layout.columns, 3);
    assert.equal(layout.sourceColumns, 2);
    assert.equal(layout.labelClip, "inset(50%)");
    assert.deepEqual(layout.overflow, [true, true, true, true]);
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
