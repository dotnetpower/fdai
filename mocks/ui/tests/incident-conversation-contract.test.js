const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const test = require("node:test");

const html = readFileSync(join(__dirname, "..", "incident-conversation.html"), "utf8");

function presentationBlocks() {
  const start = html.indexOf('<div class="deck-presentation"');
  const end = html.indexOf('<details class="deck-trajectory cs-run-record">', start);
  assert.ok(start >= 0 && end > start, "expected one bounded production presentation");
  return html.slice(start, end);
}

test("incident specimen consumes production shell and presentation roles", () => {
  assert.match(html, /href="\.\.\/\.\.\/console\/src\/styles\.css/);
  assert.match(html, /href="\.\.\/\.\.\/console\/src\/deck\/structured-reply\.css/);
  [
    "deck-header",
    "deck-search",
    "deck-layout-controls",
    "deck-transcript-column",
    "cs-deck-workspace-toolbar",
    "cs-deck-composer-shell",
    "cs-deck-composer-grid",
    "cs-deck-composer-input",
    "cs-deck-composer-send",
  ].forEach((role) => assert.match(html, new RegExp(`class="[^"]*${role}`)));
});

test("terminal incident artifact matches the production seven-block contract", () => {
  const presentation = presentationBlocks();
  const kinds = Array.from(
    presentation.matchAll(/class="deck-presentation-block" data-kind="([^"]+)"/g),
    (match) => match[1],
  );
  const headings = Array.from(
    presentation.matchAll(/<h4 id="[^"]+">([^<]+)<\/h4>/g),
    (match) => match[1],
  );

  assert.deepEqual(kinds, ["summary", "table", "summary", "table", "table", "callout", "list"]);
  assert.deepEqual(headings, [
    "Verified incident evidence",
    "Recorded activity",
    "Root cause",
    "Impact evidence",
    "Grounded citations",
    "Limitations",
    "Next safe step",
  ]);
  assert.match(html, /class="deck-presentation" data-layout="operational_brief" data-schema="3"/);
  assert.match(html, /Dynamically assembled operational brief/);
  assert.match(html, /verified_semantic_result/);
  assert.match(html, /incident_projection/);
  assert.doesNotMatch(presentation, /ic-answer-section|ic-chart|Routing evidence/);
  assert.doesNotMatch(html, /aria-label="Preparing answer"/);
});

test("incident tables and terminal values stay aligned with verified production evidence", () => {
  const tables = Array.from(presentationBlocks().matchAll(/<table\b[\s\S]*?<\/table>/g), (match) => match[0]);
  assert.deepEqual(
    tables.map((table) => (table.match(/<th\b/g) || []).length),
    [5, 6, 5],
  );
  assert.match(html, /Operational notification delivery did not complete and was escalated for human attention\./);
  assert.match(html, /No recorded evidence gaps\./);
  assert.match(html, /Configure at least one operational-alert channel in the notification registry, then retry delivery\./);
  assert.match(html, /<dt>Authority<\/dt><dd>Read-only<\/dd>/);
});

test("Run record stays collapsed and uses shared summary roles", () => {
  assert.match(html, /<details class="deck-trajectory cs-run-record">/);
  assert.doesNotMatch(html, /<details class="deck-trajectory cs-run-record" open/);
  [
    "cs-run-record-summary",
    "cs-run-record-title",
    "cs-run-record-glyph",
    "cs-run-record-title-copy",
    "cs-run-record-kicker",
    "cs-run-record-heading",
    "cs-run-record-stats",
    "cs-run-record-duration",
    "cs-run-record-chevron",
  ].forEach((role) => assert.match(html, new RegExp(role)));
  assert.match(html, /End-to-end 10\.8 s/);
  assert.match(html, /class="deck-trajectory-phase-strip cs-run-phase-strip"/);
  assert.match(html, /data-state="not_observed"[^>]*><span class="cs-run-phase-mark">03<\/span><strong>Collaboration<\/strong>/);
  assert.match(html, /class="deck-execution-timeline"/);
  assert.equal((html.match(/class="deck-execution-kind"/g) || []).length, 3);
  assert.match(html, /class="deck-model-trace is-empty"/);
  assert.match(html, /class="deck-trajectory-signals"/);
  assert.match(html, /class="deck-trajectory-question"/);
  assert.match(html, /class="deck-trajectory-body cs-run-record-body"/);
  assert.match(html, /class="deck-trajectory-records"/);
  assert.match(html, /\.deck-trajectory:not\(\[open\]\) \.deck-trajectory-question \{ display: none; \}/);
  assert.match(html, /<section class="deck-model-trace is-empty"[^>]*><header><h4>Model provider waterfall<\/h4><\/header><div class="deck-model-trace-empty-state" role="note">/);
  assert.match(html, /<summary><strong>Execution details<\/strong><span>5<\/span><\/summary>/);
  assert.equal((html.match(/class="deck-trajectory-event"/g) || []).length, 5);
  assert.doesNotMatch(html, /ic-run-timeline|10 observed events/);
});

test("responsive shell owns container queries and bounded auxiliary panels", () => {
  assert.match(html, /class="ic-conversation deck-transcript-column cs-deck-transcript-column"/);
  assert.match(html, /\.ic-workspace\.is-context-open \{ grid-template-columns: minmax\(0, 1fr\) 280px; \}/);
  assert.match(html, /\.ic-workspace\.is-sessions-open\.is-context-open \{ grid-template-columns: 240px minmax\(0, 1fr\) 280px; \}/);
  assert.match(html, /\.ic-workspace\.deck-overlay-mode-workspace \{ inset: auto; \}/);
});

test("incident specimen keeps unique element ids", () => {
  const ids = Array.from(html.matchAll(/\sid="([^"]+)"/g), (match) => match[1]);
  const duplicates = ids.filter((id, index) => ids.indexOf(id) !== index);
  assert.deepEqual(Array.from(new Set(duplicates)), []);
});
