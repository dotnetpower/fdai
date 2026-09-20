const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const test = require("node:test");

const uiRoot = join(__dirname, "..");
const read = (path) => readFileSync(join(uiRoot, path), "utf8");
const correlation = "sample-query-connected-resources-01";

test("Command Deck exposes one bounded Resource context and honest evidence posture", () => {
  const deck = read("deck.html");
  assert.match(deck, /Selected Resource<\/span><strong>checkout-api/);
  assert.match(deck, new RegExp(correlation));
  assert.match(deck, /total response 7\.8 s/);
  assert.match(deck, /Verified facts/);
  assert.match(deck, /Unavailable evidence/);
  assert.match(deck, /Not claimed/);
  assert.match(deck, /runtime-environment<\/td><td><code>contains/);
  assert.match(deck, /six direct typed relationships/i);
  assert.match(deck, /What changed recently for this service/);
  assert.match(deck, /Event time[\s\S]*Known at[\s\S]*Sources/);
  assert.doesNotMatch(
    deck.match(/<section class="flow-featured-query"[\s\S]*?<\/section>/)?.[0] || "",
    /<button[^>]*>\s*(Approve|Execute|Apply)/i,
  );
});

test("Ontology Instances embeds the actual 2D mock behind the existing tab", () => {
  const ontology = read("ontology.html");
  const instances = read("ontology-instances-2d.html");
  assert.match(ontology, /ontology-instances-2d\.html\?embedded=1&amp;instance=checkout-api/);
  assert.doesNotMatch(ontology, /No runtime claim in this specimen/);
  assert.match(instances, /id:"checkout-api"/);
  assert.match(instances, /body\.classList\.add\("is-embedded"\)/);
  assert.match(instances, /Direct incoming and outgoing relationships/);
  assert.match(instances, /Missing provider evidence remains unavailable/);
});

test("Trace separates read investigation from decision and action reconstruction", () => {
  const trace = read("rule-trace.html");
  assert.match(trace, /data-trace-mode="read"/);
  assert.match(trace, /data-trace-mode="decision"/);
  assert.match(trace, /aria-controls="trace-surface-read"/);
  assert.match(trace, /role="tabpanel" aria-labelledby="trace-tab-read"/);
  assert.match(trace, /Target resolved/);
  assert.match(trace, /LinkTypes checked/);
  assert.match(trace, /Graph queried/);
  assert.match(trace, /Six direct relationships returned/);
  assert.match(trace, /Incoming contains<\/span><strong>runtime-environment/);
  assert.match(trace, /No change was authorized|no mutation capability/i);
  assert.match(trace, /T1 matched a reviewed outcome/);
  assert.match(trace, /assets\/trace-preview\.js/);
});

test("Agent Activity retains machine actions while presenting readable read stages", () => {
  const data = read("assets/agent-activity-preview-data.js");
  const waterfall = read("assets/agent-activity-preview-waterfall.js");
  assert.equal((data.match(new RegExp(correlation, "g")) || []).length, 4);
  for (const action of [
    "read.target-resolved",
    "read.graph-queried",
    "read.evidence-verified",
    "read.answer-recorded",
  ]) {
    assert.match(data, new RegExp(action.replace(".", "\\.")));
    assert.match(waterfall, new RegExp(action.replace(".", "\\.")));
  }
  assert.match(waterfall, /Handoff bar width is not work duration/);
});

test("Agents previews preserve the canonical event-bus ownership contract", () => {
  const source = read("assets/agents-preview-data.js");
  const actual = Object.fromEntries(
    Array.from(
      source.matchAll(/\{ name: "([A-Za-z]+)"[^\n]*? owns: "([^"]+)"/g),
      (match) => [match[1], match[2]],
    ),
  );
  assert.deepEqual(actual, {
    Odin: "ArbitrationDecision",
    Heimdall: "Anomaly, Drift, Forecast, ForecastOutcome, RetrievalValidation, EvidenceConflict, RecoveryEffectObservation",
    Huginn: "Event, Change",
    Forseti: "Verdict, SecurityEvent, ArbitrationRequest, ProspectiveLineage",
    Var: "Approval",
    Thor: "ActionRun",
    Vidar: "Rollback",
    Saga: "AuditEntry, Issue",
    Bragi: "Conversation, Turn, UserPreference, HandoffEscalation, PostTurnReview",
    Njord: "CostAnomaly",
    Freyr: "CapacityForecast, CapacityGraduationRecommendation",
    Loki: "ChaosExperiment, ResilienceScore",
    Mimir: "Rule, Policy, RuleGenerationBuildRequest, RuleGenerationBuildResult",
    Norns: "RuleCandidate, Pattern",
    Muninn: "StateSnapshot, ContextIndex",
  });
});

test("Approval, Audit, Architecture, and Dashboard preserve lifecycle boundaries", () => {
  const approvals = read("hil.html");
  const approvalScript = read("assets/approvals-preview.js");
  const audit = read("audit.html");
  const architecture = read("assets/console-parity.js");
  const architecturePage = read("architecture.html");
  const dashboard = read("dashboard.html");

  assert.match(approvals, /mode=decision&amp;correlation=example-correlation-1/);
  assert.match(approvalScript, /Proposal authority and effect lifecycle/);
  assert.match(approvalScript, /\["Execution", "Not started"/);
  assert.match(audit, /Execution receipt<\/span><strong>Recorded/);
  assert.match(audit, /Effect observation<\/span><strong>Independently verified/);
  for (const id of [
    "architecture-runtime-path",
    "architecture-authority-lanes",
    "architecture-effect-path",
  ]) assert.match(architecture, new RegExp(id));
  assert.match(architecturePage, /assets\/architecture-lenses\.js/);
  assert.match(read("assets/architecture-lenses.js"), /role", "tabpanel"/);
  assert.match(read("assets/architecture-lenses.js"), /aria-controls/);
  assert.match(dashboard, new RegExp(correlation));
  assert.match(dashboard, /audit\.html\?correlation=corr-storage-031/);
});
