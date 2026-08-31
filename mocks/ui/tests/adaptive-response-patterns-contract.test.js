const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const test = require("node:test");

const html = readFileSync(join(__dirname, "..", "deck-sources-v2.html"), "utf8");

test("adaptive conversation embeds all typed response examples", () => {
  [
    "investigation",
    "clarification",
    "evidence",
    "proposal",
    "verification",
    "cancellation",
    "memory",
    "brief",
    "markdown",
  ].forEach((pattern) => {
    assert.match(html, new RegExp(`data-response-pattern="${pattern}"`));
    assert.match(html, new RegExp(`${pattern}: \\{`));
  });
});

test("response example renders inside actual transcript turns", () => {
  assert.match(html, /class="ex-pattern-applied"/);
  assert.match(html, /class="ex-turn is-user cs-deck-turn cs-deck-user-turn"/);
  assert.match(html, /class="ex-turn is-bragi cs-deck-turn cs-deck-agent-turn"/);
  assert.match(html, /id="ex-pattern-body"[^>]*aria-live="polite"/);
});

test("visible decision metadata comes from typed presentation state", () => {
  assert.match(html, /Simulates a server-selected typed presentation profile/);
  assert.match(html, /id="ex-pattern-disposition">disposition: answered/);
  assert.match(html, /id="ex-pattern-evidence">evidence: complete/);
  assert.match(html, /id="ex-pattern-profile">profile: operational_brief/);
  assert.match(html, /Presentation validated against typed state and evidence references/);
});

test("integrated proposal cannot execute managed-resource changes", () => {
  assert.match(html, /The Console does not execute this change/);
  assert.match(html, /Submit for human review<\/button>/);
  assert.doesNotMatch(html, />Execute now</);
});

test("Markdown document exposes rendered structure and synthetic source", () => {
  assert.match(html, /data-response-pattern="markdown"/);
  assert.match(html, /profile: "markdown_document"/);
  assert.match(html, /class="ex-md-document"/);
  assert.match(html, /<h3>Objective<\/h3>/);
  assert.match(html, /<h3>Verified findings<\/h3>/);
  assert.match(html, /<h3>Limits<\/h3>/);
  assert.match(html, /<h3>Response procedure<\/h3>/);
  assert.match(html, /<h3>Output contract<\/h3>/);
  assert.match(html, /View Markdown source/);
  assert.match(html, /execution_authority: false/);
  assert.match(html, /\.ex-md-document pre code \{ padding: 0; background: transparent; color: inherit; font: inherit; \}/);
  assert.match(html, /Dynamically assembled Markdown/);
  assert.match(html, /Show assembly inputs/);
  assert.match(html, /Immutable response contract/);
  assert.match(html, /1 consented user-memory record/);
  assert.match(html, /assembly_mode: dynamic/);
  assert.match(html, /assembly_digest: 7d4c2a1f/);
});

test("selector is accessible and mobile targets remain usable", () => {
  assert.match(html, /role="group" aria-label="Choose an adaptive response example"/);
  assert.match(html, /\.ex-pattern-tabs button:focus-visible/);
  assert.match(html, /\.ex-pattern-tabs button \{ min-height: 44px; \}/);
});
