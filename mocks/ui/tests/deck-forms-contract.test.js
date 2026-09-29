const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const test = require("node:test");

// Contracts for the Command deck response forms that deck-forms.js supplies: the incident brief,
// governed change, memory and documents, and the answer form's connected-resources and held
// scenarios. The engine renders them with the same turn anatomy as every other form.
const uiRoot = join(__dirname, "..");
const repoRoot = join(uiRoot, "..", "..");
const read = (path) => readFileSync(join(uiRoot, path), "utf8");
const deck = read("deck.html");
const engine = read("assets/deck-sources.js");
const formsSource = read("assets/deck-forms.js");

function loadForms() {
  const sandbox = {};
  new Function("window", formsSource)(sandbox);
  const intent = (goal, target, scope, windowText) => ({ label: "Resolve intent", phase: "Intent",
    intent: [["Goal", goal], ["Target", target], ["Scope", scope], ["Window", windowText]] });
  const check = (detail, attention) => ({ label: "Check answer", detail, phase: "Verify", verify: true, attention: !!attention });
  const verified = (detail) => ({ tone: "verified", mark: "\u2713", label: "Verified", detail });
  return sandbox.FdaiDeckForms({ day: "2026-09-28", intent, check, verified });
}

const forms = loadForms();
const text = (value) => JSON.stringify(value);

test("one Command deck page carries every response form", () => {
  const buttons = [...deck.matchAll(/data-form="([a-z]+)"/g)].map((match) => match[1]);
  assert.deepEqual(buttons, ["answer", "investigation", "incident", "change", "memory"]);
  assert.match(engine, /var FORM_ORDER = \["answer", "investigation", "incident", "change", "memory"\];/);
  assert.match(deck, /assets\/deck-forms\.js\?v=[^"]+" defer><\/script>\s*<script src="assets\/deck-sources\.js/);
  assert.deepEqual(Object.keys(forms).sort(), ["answer", "change", "incident", "memory"]);
  for (const name of ["incident", "change", "memory"]) {
    const form = forms[name];
    assert.deepEqual(Object.keys(form.scenarios), form.order, name);
    for (const key of ["label", "route", "title", "question", "lead"]) assert.ok(form[key], `${name}.${key}`);
  }
});

test("every citation, source, and read resolves inside its own form", () => {
  const engineSources = [...engine.matchAll(/^ {4}([a-zA-Z]+): \{ kind: "/gm)].map((match) => match[1]);
  for (const [name, form] of Object.entries(forms)) {
    const specs = [...Object.values(form.scenarios), ...Object.values(form.followups || {})];
    for (const spec of specs) {
      const label = `${name}: ${spec.label || spec.question}`;
      const known = (key) => key in form.sources || engineSources.includes(key);
      for (const key of spec.sources) assert.ok(known(key), `${label}: source ${key}`);
      for (const marker of text([spec.answer, spec.notes, spec.blocks]).matchAll(/\{([a-zA-Z]+)\}/g)) {
        assert.ok(spec.sources.includes(marker[1]), `${label}: citation ${marker[1]}`);
      }
      for (const stage of spec.stages) {
        for (const key of stage.emits || []) {
          assert.ok(spec.sources.includes(key), `${label}: emitted ${key}`);
          assert.ok(key in form.tools || engine.includes(`    ${key}: { label: "`), `${label}: read ${key}`);
        }
      }
      assert.equal(spec.stages.at(-1).verify, true, `${label}: verification step`);
      for (const key of spec.followups || []) assert.ok(key in form.followups || engine.includes(`    ${key}: {`), `${label}: follow-up ${key}`);
    }
    for (const tool of Object.values(form.tools)) {
      assert.ok(!tool.authority || tool.authority === "conversation", `${name}: ${tool.tool} authority`);
    }
  }
});

test("response examples keep their typed presentation profiles", () => {
  const profiles = new Set([...formsSource.matchAll(/profile: "([a-z_]+)"/g), ...engine.matchAll(/profile: "([a-z_]+)"/g)]
    .map((match) => match[1]));
  for (const profile of ["evidence_posture", "governed_proposal", "recovery_verification", "cancellation_receipt",
    "memory_retention", "operational_brief", "markdown_document"]) {
    assert.ok(profiles.has(profile), profile);
  }
  assert.match(engine, /"Presentation profile", fixture\.scenario === "clarify" \? "target_selection" : "investigation"/);
  assert.match(engine, /if \(spec\.profile\) delivery\.presentation_profile = spec\.profile;/);
});

test("incident brief leads with historical facts and explicit uncertainty", () => {
  const brief = text(forms.incident.scenarios.open);
  for (const label of ["Open at last record", "Current status unknown", "Historical evidence", "Not live",
    "Customer impact", "Not established", "Delivery and recovery", "Not verified", "Response owner", "Not recorded"]) {
    assert.ok(brief.includes(label), label);
  }
  assert.match(brief, /The shadow evaluation found no usable alert channel/);
  assert.match(brief, /no root cause is claimed/);
  assert.match(brief, /Observation window: 3m 45s/);
  assert.match(brief, /span between records, not the incident duration/);
  assert.match(brief, /Absence of a later record does not prove the incident is still active/);
  assert.deepEqual(forms.incident.scenarios.open.sources.filter((key) => key.startsWith("audit")), ["auditOpen", "auditEscalation", "auditRoute"]);
  const records = ["68858", "68881", "68882"].map((id) => forms.incident.sources[
    Object.keys(forms.incident.sources).find((key) => forms.incident.sources[key].title === `audit:${id}`)]);
  assert.ok(records.every(Boolean));
  assert.match(text(records), /No human acknowledgement is included/);
  assert.match(text(records), /No current binding readback, delivery receipt, or recovery observation is included/);
  assert.equal(forms.incident.sources.routingDown.unavailable, true);
  assert.match(forms.incident.scenarios.open.blocks.find((block) => block.type === "next").text, /read-only check/);
  const confirm = text(forms.incident.followups.incidentConfirm);
  assert.match(confirm, /Channel configuration and delivery retries are changes, not read-only checks/);
  assert.match(confirm, /Dispatch alone is not success/);
  assert.match(confirm, /this checklist grants no approval or execution authority/);
});

test("governed change drafts only, names seven safeguards, and verifies effects independently", () => {
  const action = readFileSync(join(repoRoot, "rule-catalog/action-types/ops.restart-service.yaml"), "utf8");
  assert.match(action, /^rollback_contract: state_forward_only$/m);
  assert.match(action, /t0:\n\s+max_autonomy: enforce_hil/);
  assert.match(action, /static_bucket: resource$/m);
  const proposal = forms.change.scenarios.proposal.blocks.find((block) => block.type === "proposal");
  assert.deepEqual(proposal.safeguards.map((item) => item.label), ["Stop condition", "Tested rollback", "Blast-radius limit",
    "Successful dry run", "Logical-target lock", "Stable idempotency key", "Two-phase audit"]);
  assert.equal(proposal.safeguards.filter((item) => item.state === "missing").length, 1);
  const submit = proposal.actions.find((item) => item.action === "submit-proposal");
  assert.equal(submit.disabled, true);
  assert.match(submit.reason, /all seven safeguards/);
  assert.doesNotMatch(formsSource, /label: "(?:Execute|Run now|Apply|Approve)\b/);
  assert.match(forms.change.lead, /a separate executor identity applies any approved change/);
  const effect = text(forms.change.scenarios.verification);
  assert.match(effect, /The provider accepting the restart is not proof of recovery/);
  assert.equal(forms.change.scenarios.verification.answerState, "partial");
  assert.match(text(forms.change.scenarios.cancellation), /No live process was terminated/);
  assert.equal(forms.change.tools.cancelReceipt.authority, "conversation");
});

test("memory needs consent and documents keep their structure and authority", () => {
  const consent = forms.memory.scenarios.retention.blocks.find((block) => block.type === "consent");
  assert.equal(consent.state, "Consent required");
  assert.match(consent.excluded, /Raw logs, secrets, temporary state, and unverified claims are excluded/);
  assert.match(text(forms.memory.scenarios.retention.answer), /Nothing is stored until you review and consent/);
  const document = forms.memory.scenarios.document.blocks.find((block) => block.type === "document");
  assert.deepEqual(document.sections.map((section) => section.heading), ["Objective", "Verified findings", "Limits",
    "Response procedure", "Output contract", "Machine-readable summary"]);
  assert.match(document.sections.at(-1).code, /execution_authority: false/);
  assert.match(document.sections.at(-1).code, /assembly_mode: dynamic/);
  assert.match(document.source, /^# Application readiness investigation/);
  assert.match(engine, /disclosure\("View Markdown source"/);
});

test("forms stay synthetic, local, and free of markup injection", () => {
  for (const source of [formsSource, engine]) {
    assert.doesNotMatch(source, /XMLHttpRequest|WebSocket|EventSource|innerHTML\s*=|insertAdjacentHTML/);
  }
  assert.doesNotMatch(formsSource, /fetch\s*\(/);
  assert.deepEqual([...engine.matchAll(/fetch\(([^,]+),/g)].map((match) => match[1]).sort(),
    ["\"fixtures/adaptive/\" + name + \".json\"", "PROMPT_FILE"]);
  assert.match(engine, /var PROMPT_FILE = "assets\/prompts\/system-prompt\.example\.md";/);
  assert.equal(/^[\x09\x0a\x0d\x20-\x7e]*$/.test(formsSource.replace(/\\u[0-9a-f]{4}/gi, "")), true, "ASCII source");
  for (const resource of formsSource.match(/\b[a-z]+-(?:rg|vm|db|api)\b/g) || []) {
    assert.match(resource, /^(?:example|checkout|state)-/, resource);
  }
});
