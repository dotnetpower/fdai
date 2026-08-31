const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const test = require("node:test");

const html = readFileSync(
  join(__dirname, "..", "conversation-response-patterns.html"),
  "utf8",
);
const css = readFileSync(
  join(__dirname, "..", "assets", "conversation-response-patterns.css"),
  "utf8",
);
const kitIndex = readFileSync(join(__dirname, "..", "index.html"), "utf8");
const masterIndex = readFileSync(join(__dirname, "..", "..", "..", "index.html"), "utf8");

test("response study includes the nine missing operational patterns", () => {
  [
    "investigation",
    "clarification",
    "evidence-posture",
    "proposal",
    "verification",
    "cancellation",
    "memory",
    "structured-brief",
    "markdown-document",
  ].forEach((id) => assert.match(html, new RegExp(`id="${id}"`)));
});

test("routing uses typed state, evidence shape, precedence, and safe fallback", () => {
  assert.match(html, /never browser keyword matching/);
  [
    "clarification",
    "held",
    "action_draft",
    "cancelled",
    "answered",
    "direct_response",
  ].forEach((condition) => assert.match(html, new RegExp(`<code>${condition}</code>`)));
  assert.match(html, /safety state first, then evidence posture, then semantic data shape/);
  assert.match(html, /A preference can choose among valid forms but cannot upgrade missing evidence/);
});

test("evidence posture separates facts, gaps, and prohibited claims", () => {
  assert.match(html, /Verified facts/);
  assert.match(html, /Unavailable evidence/);
  assert.match(html, /Not claimed/);
  assert.match(html, /Missing telemetry is not treated as zero errors/);
  assert.match(html, /Temporal proximity is not treated as causation/);
  assert.match(html, /Partially verified/);
});

test("governed proposal exposes all seven safeguards and cannot execute", () => {
  [
    "Stop condition",
    "Tested rollback",
    "Impact limit",
    "Dry run",
    "Logical-target lock",
    "Stable retry key",
    "Two-phase audit",
  ].forEach((label) => assert.match(html, new RegExp(label)));
  assert.match(html, /Submit for human review/);
  assert.match(html, /Submit for human review<\/button>/);
  assert.match(html, /Approval and execution use distinct principals/);
  assert.doesNotMatch(html, />Execute</);
});

test("clarification uses native controls and records no action", () => {
  assert.equal((html.match(/class="crp-choice"/g) || []).length, 3);
  assert.match(html, /No action taken/);
  assert.match(html, /<textarea[^>]+aria-label=/);
  assert.match(html, /<button class="crp-button" type="button" disabled>Continue/);
});

test("recovery, cancellation, and memory states preserve authority boundaries", () => {
  assert.match(html, /Platform recovered\. User-path recovery remains unverified\./);
  assert.match(html, /No active query was interrupted/);
  assert.match(html, /Cancellation recorded/);
  assert.match(html, /Consent required/);
  assert.match(html, /Raw logs, secrets, temporary state, and unverified claims are excluded/);
  assert.match(html, /The Console does not write durable memory directly/);
});

test("structured brief is outcome first and does not expose internal instructions", () => {
  [
    "Outcome",
    "Scope",
    "Verified evidence",
    "Limits",
    "Next safe step",
  ].forEach((section) => assert.match(html, new RegExp(`>${section}<`)));
  assert.match(html, /without revealing internal instructions or private reasoning/);
  assert.match(html, /No managed-resource change/);
  assert.doesNotMatch(html, /System prompt:/);
});

test("Markdown document is synthetic and exposes a source disclosure", () => {
  assert.match(html, /id="markdown-document"/);
  assert.match(html, /system-prompt-like operational guidance/);
  assert.match(html, /never exposes the runtime system prompt/);
  assert.match(html, /View Markdown source/);
  assert.match(html, /Dynamically assembled Markdown/);
  assert.match(html, /Show assembly inputs/);
  assert.match(css, /\.ex-md-document/);
  assert.match(css, /\.ex-md-assembly/);
  assert.match(css, /\.ex-md-document pre code[\s\S]*background: transparent/);
  assert.match(css, /\.ex-md-source summary:focus-visible/);
});

test("layout has constrained desktop, mobile, focus, and reduced-motion contracts", () => {
  assert.match(css, /@media \(max-width: 980px\)/);
  assert.match(css, /@media \(max-width: 680px\)/);
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(css, /:focus-visible/);
  assert.match(css, /\.crp-table-wrap[\s\S]*overflow-x: auto/);
});

test("specimen remains synthetic and customer-agnostic", () => {
  assert.doesNotMatch(html, /\/subscriptions\//);
  assert.doesNotMatch(html, /resourceGroups\//);
  assert.doesNotMatch(html, /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i);
  assert.match(html, /Values are synthetic/);
});

test("both design indexes expose the response pattern study", () => {
  assert.match(kitIndex, /data-page="conversation-response-patterns\.html"/);
  assert.match(masterIndex, /data-page="mocks\/ui\/conversation-response-patterns\.html"/);
});
