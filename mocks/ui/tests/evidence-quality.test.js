const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const test = require("node:test");

const uiRoot = join(__dirname, "..");
const pages = [
  "audit.html",
  "browser-evidence.html",
  "forecast-learning.html",
  "assurance-twin.html",
  "conversation-search.html",
  "conversation-assurance.html",
  "reports.html",
  "rule-trace.html",
  "rca.html",
];
const qualityStyles = readFileSync(join(uiRoot, "assets", "evidence-quality.css"), "utf8");
const qualityScript = readFileSync(join(uiRoot, "assets", "evidence-quality.js"), "utf8");
const focusedScript = readFileSync(
  join(uiRoot, "assets", "focused-governance-workspaces.js"),
  "utf8",
);

test("all Evidence navigation routes load the focused quality contract", () => {
  const master = readFileSync(join(uiRoot, "..", "..", "index.html"), "utf8");
  pages.forEach((file) => {
    const html = readFileSync(join(uiRoot, file), "utf8");
    assert.match(master, new RegExp(`data-page="mocks/ui/${file}"`), file);
    assert.match(html, /data-evidence-quality/, file);
    assert.match(html, new RegExp(`data-evidence-page="${file.replace(".html", "")}"`), file);
    assert.match(html, /assets\/evidence-quality\.css\?v=3/, file);
    assert.match(html, /assets\/evidence-quality\.js\?v=3/, file);
    assert.match(html, /<main\b/, file);
  });
});

test("Evidence quality styles use semantic type roles and adaptive accessibility modes", () => {
  assert.match(qualityStyles, /var\(--cs-type-label-size\)/);
  assert.match(qualityStyles, /var\(--cs-type-compact-size\)/);
  assert.match(qualityStyles, /@media \(max-width: 620px\)/);
  assert.match(qualityStyles, /\.rc-chain \{\s+grid-template-columns: minmax\(0, 1fr\)/);
  assert.match(qualityStyles, /min-height: 44px/);
  assert.match(qualityStyles, /@media \(forced-colors: active\)/);
  assert.match(qualityStyles, /outline: 2px solid Highlight/);
  assert.doesNotMatch(qualityStyles, /font-size:\s*(?:[0-9]|1[01])px/);
});

test("Evidence interactions keep selection, search, cursor, and mock feedback explicit", () => {
  [
    "function enhanceSelectors()",
    "function bindAssuranceTwin()",
    "function bindConversationSearch()",
    "function bindReportForm()",
    "function bindAuditPagination()",
    "function enhanceRcaStates()",
  ].forEach((contract) => assert.match(qualityScript, new RegExp(contract.replace(/[()]/g, "\\$&"))));
  assert.match(qualityScript, /No request was sent/);
  assert.match(qualityScript, /aria-controls/);
  assert.match(qualityScript, /aria-live/);
  assert.match(focusedScript, /data-fg-static-message/);
  assert.match(focusedScript, /hasAttribute\("data-fg-measured-chart"\)/);
});

test("Evidence charts expose exact synthetic values instead of decorative geometry", () => {
  const forecast = readFileSync(join(uiRoot, "forecast-learning.html"), "utf8");
  const reports = readFileSync(join(uiRoot, "reports.html"), "utf8");
  assert.equal((forecast.match(/data-fg-measured-chart/g) || []).length, 2);
  assert.match(forecast, /v8 64%.*v12 71%/);
  assert.match(forecast, /22% predicted.*72% actual/);
  assert.match(forecast, /298 closed synthetic episodes/);
  assert.equal((reports.match(/class="report-mini-bar"/g) || []).length, 7);
  assert.match(reports, /Monday 48.*Sunday 68/);
  assert.match(reports, /Partial evidence/);
  assert.match(reports, /Sources pinned 5 \/ current 4/);
});

test("Evidence recovery states remain explicit and read-only", () => {
  const audit = readFileSync(join(uiRoot, "audit.html"), "utf8");
  const search = readFileSync(join(uiRoot, "conversation-search.html"), "utf8");
  const rca = readFileSync(join(uiRoot, "rca.html"), "utf8");
  assert.equal((audit.match(/data-evidence-next-record/g) || []).length, 2);
  assert.match(audit, /terminal success remains unavailable/);
  assert.match(search, /data-evidence-search-empty/);
  assert.match(search, /No conversation or source request is sent/);
  assert.match(rca, /data-rca-query-status/);
  assert.match(rca, /No incident or evidence request is sent/);
  assert.match(rca, /Confidence does not grant action authority/);
  [audit, search, rca].forEach((html) => {
    assert.doesNotMatch(html, /<(?:button|a)[^>]*>\s*(?:Approve|Execute|Delete|Remediate)\s*</i);
  });
});

test("RCA and Assurance Twin use the shared neutral Evidence presentation", () => {
  const assuranceTwin = readFileSync(join(uiRoot, "assurance-twin.html"), "utf8");
  const rca = readFileSync(join(uiRoot, "rca.html"), "utf8");

  assert.match(assuranceTwin, /assets\/governance-evidence-workspace\.css\?v=9/);
  assert.match(assuranceTwin, /class="cs-governance-evidence"/);
  assert.match(rca, /class="rc-header-meta"/);
  assert.match(rca, /Evidence mode/);
  assert.doesNotMatch(rca, /conic-gradient/);
  assert.doesNotMatch(rca, /rc-confidence-ring::before/);
  assert.doesNotMatch(rca, /style="color:var\(--cs-sage\)"/);
});
