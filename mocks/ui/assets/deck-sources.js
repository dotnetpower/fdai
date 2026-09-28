// Command deck conversation studies: the one-shot source-streaming study (deck-sources.html) and
// the adaptive investigation study (deck-adaptive.html), which replays fixtures/adaptive/*.json.
// Synthetic data only. The replay performs no model call, provider read, or state change; the
// adaptive study only fetches its local fixture files.
(function () {
  "use strict";

  var DAY = "2026-09-28";
  var STUDY = document.body.getAttribute("data-study") === "adaptive" ? "adaptive" : "sources";
  var ADAPTIVE = STUDY === "adaptive";
  var ROUTE = ADAPTIVE ? "Inventory" : "Live cockpit";
  var QUESTION = ADAPTIVE
    ? "Compare the configuration in example-inventory.md with the live example-rg-app resource group."
    : "example-postgres keeps getting flagged. Why, and can you fix it automatically?";
  var CONVERSATION_TITLE = ADAPTIVE ? "Configuration comparison" : "Why is example-postgres flagged?";
  var INTRO_LEAD = ADAPTIVE
    ? "Bragi plans typed reads, runs them in waves, and answers from what it observed. This preview replays one scripted investigation."
    : "Bragi answers from read-only sources and cites each claim. This preview replays one scripted question.";
  var INVESTIGATIONS = ["no-drift", "drift", "partial", "conflict", "denied", "clarify", "stale", "budget"];
  var CHECK = "\u2713";
  var CANCELLED = { cancelled: true };
  var TIMING = { readiness: 320, stage: 300, source: 110, paragraph: 70, verify: 320, step: 200, collapse: 240 };
  // Answer text reveals whole words at this many characters per second at 1x speed, and holds
  // briefly after each sentence so the reply reads with a natural cadence.
  var STREAM_CPS = 1000;
  var SENTENCE_PAUSE = 60;
  var SENTENCE_END = /[.!?;]["')\]]*\s*$/;

  // Each source is data FDAI already holds. Catalog entries carry a version; runtime evidence
  // carries its observation time. Rule, policy, and ActionType identifiers match rule-catalog/.
  var SOURCES = {
    screen: { kind: "Screen", title: "Live cockpit, tile #12", meta: "example-postgres shown as flagged", time: "10:41:05", href: "live.html" },
    inventory: { kind: "Inventory", title: "example-postgres", meta: "postgresql-server, backup_retention_days: 3", time: "10:40:52", href: "architecture.html" },
    inventoryNew: { kind: "Inventory", title: "example-postgres", meta: "postgresql-server, backup_retention_days: 7", time: "10:44:12", href: "architecture.html" },
    inventoryDown: { kind: "Inventory", title: "Inventory source", meta: "Unavailable: no response, current configuration not read", href: "architecture.html", unavailable: true },
    rule: { kind: "Rule", title: "postgresql-server.point-in-time-restore", meta: "WAF reliability, high severity, requires at least 7 days of backup retention", catalog: "Catalog 1.0.0", href: "rules.html" },
    policy: { kind: "Policy", title: "point_in_time_restore.rego", meta: "Evaluated to deny: backup_retention_below_min", time: "10:38:40", href: "rule-trace.html" },
    policySource: { kind: "Policy", title: "policies/postgresql/point_in_time_restore.rego", meta: "Denies backup_retention_days below min_retention_days, default 7", catalog: "Catalog 1.0.0", href: "rule-trace.html" },
    verdict: { kind: "Agent", title: "Forseti verdict", meta: "Shadow: judged and logged, not executed", time: "10:38:41", href: "agent-activity.html" },
    action: { kind: "ActionType", title: "remediate.enable-backup-protection", meta: "Default shadow; gate 21 days, 50 samples, 98% accuracy, 0 escapes; T0 ceiling enforce with approval", catalog: "Catalog 1.0.0", href: "actions.html" },
    promotion: { kind: "Promotion", title: "Shadow evidence", meta: "14 days, 31 samples, 100% accuracy, 0 policy escapes", time: "10:41:06", href: "promotion.html" },
    promotionDown: { kind: "Promotion", title: "Shadow evidence", meta: "Unavailable: the Audit source did not respond", href: "promotion.html", unavailable: true },
    registry: { kind: "Promotion", title: "Promotion registry", meta: "remediate.enable-backup-protection: shadow since 2026-09-14, no promotion request", time: "10:41:06", href: "promotion.html" },
    template: { kind: "Template", title: "raise_backup_retention.tftpl", meta: "remediation/postgresql, raises retention to the rule minimum", catalog: "Catalog 1.0.0", href: "rules.html" },
    auditRecord: { kind: "Audit", title: "Shadow judgment record", meta: "Logged, not dispatched; no pull request opened", time: "10:38:41", href: "audit.html" },
    auditNone: { kind: "Audit", title: "Remediation records, last 30 days", meta: "No remediate.enable-backup-protection executions", time: "10:41:06", href: "audit.html" },
    readinessAudit: { kind: "Readiness", title: "Evidence-source readiness", meta: "Audit unavailable; 4 of 5 sources available", time: "10:41:04", href: "settings-diagnostics.html" },
    readinessInventory: { kind: "Readiness", title: "Evidence-source readiness", meta: "Inventory unavailable; 4 of 5 sources available", time: "10:41:04", href: "settings-diagnostics.html" }
  };

  // Screens a source or deck link can open. Leaving the conversation always asks first.
  var PAGE_LABEL = {
    "live.html": "Live cockpit", "architecture.html": "Inventory", "rules.html": "Rule catalog",
    "rule-trace.html": "Rule trace", "agent-activity.html": "Agent activity", "actions.html": "Actions",
    "promotion.html": "Promotion", "audit.html": "Audit", "settings-diagnostics.html": "Diagnostics",
    "incidents.html": "Incidents", "scheduler-runs.html": "Scheduler runs",
    "conversation-assurance.html": "Conversation assurance"
  };

  function pageLabel(href) {
    return PAGE_LABEL[String(href).split(/[?#]/)[0]] || "this screen";
  }

  var READINESS = [
    { key: "inventory", label: "Inventory", href: "architecture.html" },
    { key: "incidents", label: "Incidents", href: "incidents.html" },
    { key: "audit", label: "Audit", href: "audit.html" },
    { key: "knowledge", label: "Knowledge", href: "rules.html" },
    { key: "automation", label: "Automation", href: "scheduler-runs.html" }
  ];

  // Read-only console-tool calls behind each source. Every call has side_effect_class "read".
  var TOOLS = {
    screen: { label: "Read screen snapshot", tool: "screen.snapshot", input: "query", command: "screen.snapshot route=live tile=12", ms: 34,
      output: { route: "live", tile: 12, resource: "example-postgres", status: "flagged", observed_at: DAY + "T10:41:05Z" } },
    inventory: { label: "Read inventory", tool: "inventory.read", input: "query", command: "inventory.read resource=example-postgres fields=backup_retention_days", ms: 61,
      output: { resource: "example-postgres", type: "postgresql-server", backup_retention_days: 3, observed_at: DAY + "T10:40:52Z" } },
    inventoryNew: { label: "Read inventory", tool: "inventory.read", input: "query", command: "inventory.read resource=example-postgres fields=backup_retention_days", ms: 58,
      output: { resource: "example-postgres", type: "postgresql-server", backup_retention_days: 7, observed_at: DAY + "T10:44:12Z" } },
    inventoryDown: { label: "Read inventory", tool: "inventory.read", input: "query", command: "inventory.read resource=example-postgres fields=backup_retention_days", ms: 1500, status: "failed",
      output: { status: "unavailable", reason: "source_timeout", timeout_ms: 1500 } },
    rule: { label: "Match rule catalog", tool: "rule_catalog.match", input: "query", command: "rule_catalog.match resource_type=postgresql-server property=backup_retention_days", ms: 19,
      output: { rule_id: "postgresql-server.point-in-time-restore", version: "1.0.0", source: "waf", severity: "high", parameters: { min_retention_days: 7 } } },
    policy: { label: "Evaluate policy", tool: "policy.evaluate", input: "command", command: "policy.evaluate package=fdai.postgresql.point_in_time_restore resource=example-postgres", ms: 16,
      output: { deny: true, deny_reason: "backup_retention_below_min", evaluated_at: DAY + "T10:38:40Z" } },
    policySkipped: { label: "Evaluate policy", tool: "policy.evaluate", input: "command", command: "policy.evaluate package=fdai.postgresql.point_in_time_restore resource=example-postgres", ms: 2, status: "degraded",
      output: { status: "not_evaluated", reason: "input_unavailable", missing: ["backup_retention_days"] } },
    policySource: { label: "Read policy source", tool: "policy.source", input: "query", command: "policy.source package=fdai.postgresql.point_in_time_restore", ms: 11,
      output: { path: "policies/postgresql/point_in_time_restore.rego", default_min_retention_days: 7, deny_reason: "backup_retention_below_min" } },
    compareTimes: { label: "Compare evidence times", tool: "evidence.compare_times", input: "command", command: "evidence.compare_times left=policy.evaluated_at right=inventory.observed_at", ms: 3, status: "degraded",
      output: { policy_evaluated_at: DAY + "T10:38:40Z", inventory_observed_at: DAY + "T10:44:12Z", newer: "inventory", flag_current: false } },
    verdict: { label: "Read Forseti verdict", tool: "audit.verdicts", input: "query", command: "audit.verdicts agent=forseti resource=example-postgres limit=1", ms: 27,
      output: { agent: "forseti", mode: "shadow", decision: "remediate", executed: false, recorded_at: DAY + "T10:38:41Z" } },
    action: { label: "Read ActionType", tool: "action_types.read", input: "query", command: "action_types.read name=remediate.enable-backup-protection", ms: 14,
      output: { default_mode: "shadow", promotion_gate: { min_shadow_days: 21, min_samples: 50, min_accuracy: 0.98, max_policy_escapes: 0 }, ceiling_by_tier: { t0: "enforce_hil" }, execution_path: "pr_native" } },
    promotion: { label: "Read promotion evidence", tool: "promotion.evidence", input: "query", command: "promotion.evidence action_type=remediate.enable-backup-protection", ms: 38,
      output: { shadow_days: 14, samples: 31, accuracy: 1, policy_escapes: 0, as_of: DAY + "T10:41:06Z" } },
    promotionDown: { label: "Read promotion evidence", tool: "promotion.evidence", input: "query", command: "promotion.evidence action_type=remediate.enable-backup-protection", ms: 1500, status: "failed",
      output: { status: "unavailable", source: "audit", reason: "source_timeout", timeout_ms: 1500 } },
    registry: { label: "Read promotion registry", tool: "promotion.registry", input: "query", command: "promotion.registry action_type=remediate.enable-backup-protection", ms: 21,
      output: { action_type: "remediate.enable-backup-protection", state: "shadow", since: "2026-09-14", promotion_request: null } },
    template: { label: "Read remediation template", tool: "rule_catalog.remediation", input: "query", command: "rule_catalog.remediation rule=postgresql-server.point-in-time-restore", ms: 12,
      output: { template: "remediation/postgresql/raise_backup_retention.tftpl", sets: { backup_retention_days: "min_retention_days" } } },
    auditRecord: { label: "Read audit record", tool: "audit.records", input: "query", command: "audit.records kind=shadow_judgment resource=example-postgres limit=1", ms: 24,
      output: { kind: "shadow_judgment", dispatched: false, pull_request: null, recorded_at: DAY + "T10:38:41Z" } },
    auditNone: { label: "Read audit records", tool: "audit.records", input: "query", command: "audit.records action_type=remediate.enable-backup-protection window=P30D", ms: 33,
      output: { action_type: "remediate.enable-backup-protection", executions: 0, window: "P30D" } },
    readinessAudit: { label: "Read source readiness", tool: "sources.readiness", input: "query", command: "sources.readiness", ms: 9,
      output: { inventory: "available", incidents: "available", audit: "unavailable", knowledge: "available", automation: "available", observed_at: DAY + "T10:41:04Z" } },
    readinessInventory: { label: "Read source readiness", tool: "sources.readiness", input: "query", command: "sources.readiness", ms: 9,
      output: { inventory: "unavailable", incidents: "available", audit: "available", knowledge: "available", automation: "available", observed_at: DAY + "T10:41:04Z" } }
  };

  // Narrator model calls. Bragi only translates: planning maps language to a typed intent and
  // generation phrases verified facts. Decisions come from the deterministic sources above.
  var MODEL = { name: "gpt-4.1-mini", planMs: 412, generationMs: 736, profile: "bragi.narrator", profileVersion: "3.2.0" };

  function intent(goal, target, scope, windowText) {
    return { label: "Resolve intent", phase: "Intent", intent: [["Goal", goal], ["Target", target], ["Scope", scope], ["Window", windowText]] };
  }

  var MAIN_INTENT = intent("Explain a finding and whether it can be fixed", "example-postgres (postgresql-server)", "Live cockpit, tile #12", "Last 30 days");
  var SCREEN_STAGE = { label: "Read this screen", detail: "Live cockpit, tile #12, observed 10:41:05 UTC", phase: "Retrieve", emits: ["screen"] };
  var RULE_STAGE = { label: "Match rule catalog", detail: "postgresql-server.point-in-time-restore, WAF reliability, high", phase: "Ground", emits: ["rule"] };
  var VERDICT_STAGE = { label: "Read Forseti verdict", detail: "Shadow: judged and logged, not executed", phase: "Retrieve", emits: ["verdict"] };

  var GROUNDED_P1 = "example-postgres{screen} is flagged because its backup retention is 3 days{inventory}, below the 7-day minimum that the point-in-time restore rule requires{rule}. The policy check denies this configuration{policy}.";
  var P2_SHADOW = "It can't be fixed automatically. `remediate.enable-backup-protection` resolved to shadow mode in this run, so Forseti judged the finding and logged a proposed fix without executing it{verdict}.";
  var P2_GATE = " Promotion needs at least 21 shadow days, 50 samples, 98% accuracy, and zero policy escapes{action}.";
  var P3_DELIVERY = "Even after promotion, a deterministic (T0) decision for this ActionType stops at enforce with human approval, so the fix would be a remediation pull request that a person reviews{action}. The catalog declares stop conditions, a single-resource blast radius, an idempotency key, and forward-only recovery{action}; a dry-run receipt, a target lock, and a two-phase audit are checked before dispatch. Success is reported only after an independent read confirms the new retention.";

  function check(detail, attention) {
    return { label: "Check answer", detail: detail, phase: "Verify", verify: true, attention: !!attention };
  }

  function verified(detail) {
    return { tone: "verified", mark: CHECK, label: "Verified", detail: detail };
  }

  var GROUNDED_STAGES = [
    MAIN_INTENT,
    SCREEN_STAGE,
    { label: "Read inventory", detail: "example-postgres, backup_retention_days 3, observed 10:40:52 UTC", phase: "Retrieve", emits: ["inventory"] },
    RULE_STAGE,
    { label: "Evaluate policy", detail: "point_in_time_restore.rego: deny, backup_retention_below_min", phase: "Ground", emits: ["policy"] },
    VERDICT_STAGE,
    { label: "Read promotion evidence", detail: "remediate.enable-backup-protection: 14 of 21 days, 31 of 50 samples", phase: "Retrieve", emits: ["action", "promotion"] }
  ];
  var GROUNDED_SOURCES = ["screen", "inventory", "rule", "policy", "verdict", "action", "promotion"];
  var GROUNDED_P2 = P2_SHADOW + P2_GATE + " The latest shadow evidence shows 14 days, 31 samples, 100% accuracy, and no escapes{promotion}.";

  var SCENARIOS = {
    grounded: {
      label: "Grounded",
      unavailableSources: [],
      stages: GROUNDED_STAGES.concat([check("9 of 9 claims supported by 7 sources")]),
      sources: GROUNDED_SOURCES,
      answer: [{ text: GROUNDED_P1 }, { text: GROUNDED_P2 }, { text: P3_DELIVERY }],
      notes: [],
      verification: verified("9 of 9 claims supported"),
      answerState: null,
      pill: { attention: false, issue: null },
      followups: ["shadow", "promote", "proposed"],
      announce: "Answer ready. Verified: 9 of 9 claims are supported by 7 sources."
    },
    partial: {
      label: "Partial evidence",
      unavailableSources: ["audit"],
      stages: GROUNDED_STAGES.slice(0, 6).concat([
        { label: "Read promotion evidence", detail: "Audit source unavailable: shadow history not read", phase: "Retrieve", emits: ["action", "promotionDown"], attention: true },
        check("8 of 8 claims supported; shadow history withheld", true)
      ]),
      sources: ["screen", "inventory", "rule", "policy", "verdict", "action", "promotionDown"],
      answer: [{ text: GROUNDED_P1 }, { text: P2_SHADOW + P2_GATE }, { text: P3_DELIVERY }],
      notes: [{ after: 1, when: "stream", tone: "attention", label: "Evidence limit", text: "shadow history is unavailable because the Audit source did not respond{promotionDown}. Progress toward the promotion gate is unknown." }],
      verification: { tone: "attention", mark: "!", label: "Partial evidence", detail: "8 of 8 claims supported" },
      answerState: "partial",
      pill: { attention: true, issue: "partial evidence" },
      followups: ["sourcesAudit", "promote"],
      announce: "Answer ready with partial evidence. The Audit source was unavailable, so shadow history was not used."
    },
    unavailable: {
      label: "Source unavailable",
      unavailableSources: ["inventory"],
      stages: [
        MAIN_INTENT,
        SCREEN_STAGE,
        { label: "Read inventory", detail: "Inventory source unavailable: current configuration not read", phase: "Retrieve", emits: ["inventoryDown"], attention: true },
        RULE_STAGE,
        { label: "Evaluate policy", detail: "Not evaluated: no current configuration to check", phase: "Ground", attention: true, tool: "policySkipped" },
        check("3 of 3 claims supported; current state unknown", true)
      ],
      sources: ["inventoryDown", "screen", "rule"],
      answer: [
        { text: "I can't confirm why example-postgres is flagged right now. The inventory source is unavailable{inventoryDown}, so its current backup retention is unknown." },
        { text: "The flag on this screen{screen} comes from the point-in-time restore rule, which requires at least 7 days of backup retention{rule}. Ask again after the inventory source recovers." }
      ],
      notes: [{ after: 0, when: "stream", tone: "attention", label: "Unknown", text: "the current `backup_retention_days` of example-postgres. FDAI does not infer it from older records.", link: { href: "settings-diagnostics.html", text: "Open diagnostics" } }],
      verification: { tone: "attention", mark: "!", label: "Source unavailable", detail: "Current state unknown" },
      answerState: null,
      pill: { attention: true, issue: "source unavailable" },
      followups: ["sourcesInventory", "rule"],
      announce: "Answer ready. The inventory source is unavailable, so the current state of example-postgres is unknown."
    },
    conflict: {
      label: "Conflicting evidence",
      unavailableSources: [],
      stages: [
        MAIN_INTENT,
        SCREEN_STAGE,
        { label: "Read inventory", detail: "example-postgres, backup_retention_days 7, observed 10:44:12 UTC", phase: "Retrieve", emits: ["inventoryNew"] },
        RULE_STAGE,
        { label: "Read policy evaluation", detail: "Evaluated 10:38:40 UTC against the earlier value: deny", phase: "Ground", emits: ["policy"] },
        { label: "Compare evidence times", detail: "The flag predates the newer inventory read", phase: "Verify", attention: true, tool: "compareTimes" },
        { label: "Read ActionType", detail: "remediate.enable-backup-protection: default shadow", phase: "Retrieve", emits: ["action"] },
        check("5 of 5 claims supported; state unresolved", true)
      ],
      sources: ["screen", "policy", "inventoryNew", "rule", "action"],
      answer: [
        { text: "The evidence conflicts. This screen{screen} shows example-postgres as flagged by a policy evaluation at 10:38:40 UTC{policy}, but a newer inventory read at 10:44:12 UTC reports 7 days of backup retention{inventoryNew}, which meets the rule's minimum{rule}." },
        { text: "No fix is proposed while the state is unresolved. `remediate.enable-backup-protection` also remains in shadow mode{action}." }
      ],
      notes: [{ after: 0, when: "stream", tone: "conflict", label: "Conflicting evidence", text: "FDAI treats neither reading as the current state until the policy is evaluated again against the newer inventory read." }],
      verification: { tone: "failure", mark: "!", label: "Conflicting evidence", detail: "State unresolved" },
      answerState: null,
      pill: { attention: true, issue: "conflicting evidence" },
      followups: ["newer", "promote"],
      announce: "Answer ready with conflicting evidence. The flag predates a newer inventory read."
    },
    corrected: {
      label: "Corrected",
      unavailableSources: [],
      stages: GROUNDED_STAGES.concat([check("9 of 10 claims supported; 1 unsupported sentence removed", true)]),
      sources: GROUNDED_SOURCES,
      answer: [
        { text: GROUNDED_P1 },
        { text: GROUNDED_P2, unsupported: "Two peer databases had the same finding fixed automatically last month after promotion." },
        { text: P3_DELIVERY }
      ],
      notes: [{ after: 1, when: "verify", tone: "attention", label: "Corrected", text: "verification removed 1 sentence that no source supports, a claim that peer databases were fixed after promotion." }],
      verification: { tone: "attention", mark: "\u21bb", label: "Corrected", detail: "1 sentence removed" },
      answerState: "corrected",
      pill: { attention: false, issue: null },
      followups: ["removed", "shadow"],
      announce: "Answer ready. Verification removed 1 unsupported sentence; the remaining 9 claims are supported."
    }
  };

  var FOLLOWUPS = {
    shadow: {
      question: "Why is it still in shadow mode?",
      stages: [
        intent("Explain why the ActionType is in shadow mode", "remediate.enable-backup-protection (ActionType)", "Promotion evidence", "Since shadow start"),
        { label: "Read ActionType", detail: "Default mode shadow and promotion gate thresholds", phase: "Retrieve", emits: ["action"] },
        { label: "Read promotion evidence", detail: "14 of 21 days, 31 of 50 samples", phase: "Retrieve", emits: ["promotion"] },
        check("2 of 2 claims supported by 2 sources")
      ],
      sources: ["action", "promotion"],
      answer: [{ text: "Every new ActionType starts in shadow mode and stays there until its promotion gate passes{action}. This one has 14 of the required 21 shadow days and 31 of the required 50 samples, with 100% accuracy and no policy escapes so far{promotion}." }],
      verification: verified("2 of 2 claims supported"),
      announce: "Answer ready. Verified: 2 of 2 claims supported."
    },
    promote: {
      question: "What would promote it to enforce?",
      stages: [
        intent("Explain promotion requirements", "remediate.enable-backup-protection (ActionType)", "Promotion registry", "Current"),
        { label: "Read ActionType", detail: "Promotion gate and T0 ceiling", phase: "Retrieve", emits: ["action"] },
        { label: "Read promotion registry", detail: "Shadow since 2026-09-14, no promotion request", phase: "Retrieve", emits: ["registry"] },
        check("3 of 3 claims supported by 2 sources")
      ],
      sources: ["action", "registry"],
      answer: [{ text: "Promotion requires at least 21 shadow days, 50 samples, 98% accuracy, and zero policy escapes{action}. Passing the gate doesn't promote the ActionType by itself: promotion is a separate reviewed change recorded in the promotion registry, and none has been requested{registry}. Even then, a T0 decision stays at enforce with human approval{action}." }],
      verification: verified("3 of 3 claims supported"),
      announce: "Answer ready. Verified: 3 of 3 claims supported."
    },
    proposed: {
      question: "Show the proposed change",
      stages: [
        intent("Show the logged remediation proposal", "example-postgres (postgresql-server)", "Forseti shadow judgment", "Last 30 days"),
        { label: "Read Forseti verdict", detail: "Proposal logged in shadow mode", phase: "Retrieve", emits: ["verdict"] },
        { label: "Read remediation template", detail: "raise_backup_retention.tftpl", phase: "Ground", emits: ["template"] },
        { label: "Read audit record", detail: "Logged, not dispatched", phase: "Retrieve", emits: ["auditRecord"] },
        check("2 of 2 claims supported by 3 sources")
      ],
      sources: ["verdict", "template", "auditRecord"],
      answer: [{ text: "Forseti's shadow judgment proposes raising `backup_retention_days` from 3 to 7 with the `raise_backup_retention` remediation template{verdict}{template}. The proposal was logged, not dispatched, so no pull request exists{auditRecord}." }],
      verification: verified("2 of 2 claims supported"),
      announce: "Answer ready. Verified: 2 of 2 claims supported."
    },
    sourcesAudit: {
      question: "Which sources were unavailable?",
      stages: [
        intent("List unavailable evidence sources", "The previous answer", "Evidence-source readiness", "Observed 10:41:04 UTC"),
        { label: "Read source readiness", detail: "Audit unavailable; 4 of 5 sources available", phase: "Retrieve", emits: ["readinessAudit"] },
        check("2 of 2 claims supported by 1 source")
      ],
      sources: ["readinessAudit"],
      answer: [{ text: "The Audit source did not respond during this answer, so shadow history was not read{readinessAudit}. Inventory, Incidents, Knowledge, and Automation were available{readinessAudit}." }],
      verification: verified("2 of 2 claims supported"),
      announce: "Answer ready. Verified: 2 of 2 claims supported."
    },
    sourcesInventory: {
      question: "Which sources were unavailable?",
      stages: [
        intent("List unavailable evidence sources", "The previous answer", "Evidence-source readiness", "Observed 10:41:04 UTC"),
        { label: "Read source readiness", detail: "Inventory unavailable; 4 of 5 sources available", phase: "Retrieve", emits: ["readinessInventory"] },
        check("2 of 2 claims supported by 1 source")
      ],
      sources: ["readinessInventory"],
      answer: [{ text: "The Inventory source did not respond, so the current configuration of example-postgres was not read{readinessInventory}. Incidents, Audit, Knowledge, and Automation were available{readinessInventory}." }],
      verification: verified("2 of 2 claims supported"),
      announce: "Answer ready. Verified: 2 of 2 claims supported."
    },
    rule: {
      question: "What does the rule check?",
      stages: [
        intent("Explain the rule logic", "postgresql-server.point-in-time-restore (Rule)", "Rule catalog", "Current catalog"),
        RULE_STAGE,
        { label: "Read policy source", detail: "policies/postgresql/point_in_time_restore.rego", phase: "Ground", emits: ["policySource"] },
        check("2 of 2 claims supported by 2 sources")
      ],
      sources: ["rule", "policySource"],
      answer: [{ text: "`postgresql-server.point-in-time-restore` requires at least 7 days of backup retention{rule}. Its policy denies a lower `backup_retention_days` value with the reason `backup_retention_below_min`{policySource}." }],
      verification: verified("2 of 2 claims supported"),
      announce: "Answer ready. Verified: 2 of 2 claims supported."
    },
    newer: {
      question: "Which reading is newer?",
      stages: [
        intent("Compare evidence times", "example-postgres (postgresql-server)", "Inventory and policy evaluation", "10:38 to 10:45 UTC"),
        { label: "Read inventory", detail: "Observed 10:44:12 UTC", phase: "Retrieve", emits: ["inventoryNew"] },
        { label: "Read policy evaluation", detail: "Evaluated 10:38:40 UTC", phase: "Retrieve", emits: ["policy"] },
        check("2 of 2 claims supported by 2 sources")
      ],
      sources: ["inventoryNew", "policy"],
      answer: [{ text: "The inventory read at 10:44:12 UTC{inventoryNew} is newer than the policy evaluation at 10:38:40 UTC that raised the flag{policy}. The flag remains until the policy is evaluated again against the newer read." }],
      verification: verified("2 of 2 claims supported"),
      announce: "Answer ready. Verified: 2 of 2 claims supported."
    },
    removed: {
      question: "What was removed?",
      stages: [
        intent("Explain a verification correction", "The previous answer", "Audit and promotion records", "Last 30 days"),
        { label: "Read audit records", detail: "No matching executions", phase: "Retrieve", emits: ["auditNone"] },
        { label: "Read promotion registry", detail: "Never promoted", phase: "Retrieve", emits: ["registry"] },
        check("2 of 2 claims supported by 2 sources")
      ],
      sources: ["auditNone", "registry"],
      answer: [{ text: "Verification removed one sentence claiming that two peer databases had the same finding fixed after promotion. No audit record supports it{auditNone}, and the ActionType has never been promoted{registry}." }],
      verification: verified("2 of 2 claims supported"),
      announce: "Answer ready. Verified: 2 of 2 claims supported."
    }
  };

  // ---------- DOM helpers ----------
  var SVG_NS = "http://www.w3.org/2000/svg";
  var ICON_PATHS = {
    copy: ["M5.5 5.5h8v8h-8z", "M10.5 5.5V4A1.5 1.5 0 0 0 9 2.5H4A1.5 1.5 0 0 0 2.5 4v5A1.5 1.5 0 0 0 4 10.5h1.5"],
    regenerate: ["M13 8a5 5 0 1 1-1.46-3.54", "M13 2.5V5h-2.5"],
    review: ["M8 2.2l4.8 1.8v3.6c0 3-2 5.2-4.8 6.2-2.8-1-4.8-3.2-4.8-6.2V4z", "M5.8 8.1l1.6 1.6 2.9-3"],
    chevron: ["M5 6.5l3 3 3-3"],
    check: ["M3.5 8.4l2.9 2.9 6.1-6.6"],
    file: ["M4 2.5h5l3 3v8H4z", "M9 2.5v3h3"]
  };

  function h(tag, props, children) {
    var node = document.createElement(tag);
    Object.keys(props || {}).forEach(function (key) {
      var value = props[key];
      if (value === null || value === undefined || value === false) return;
      if (key === "class") node.className = value;
      else if (key === "text") node.textContent = value;
      else node.setAttribute(key, value === true ? "" : String(value));
    });
    (children || []).forEach(function (child) {
      if (child === null || child === undefined || child === false) return;
      node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
    });
    return node;
  }

  // Whitespace between flex items keeps accessible names readable without changing layout.
  function spaced(children) {
    var result = [];
    children.forEach(function (child) {
      if (!child) return;
      if (result.length) result.push(" ");
      result.push(child);
    });
    return result;
  }

  function separator() {
    return h("span", { "aria-hidden": "true", text: "\u00b7" });
  }

  function icon(name) {
    var svg = document.createElementNS(SVG_NS, "svg");
    [["viewBox", "0 0 16 16"], ["width", "16"], ["height", "16"], ["aria-hidden", "true"], ["focusable", "false"],
      ["fill", "none"], ["stroke", "currentColor"], ["stroke-width", "1.4"], ["stroke-linecap", "round"],
      ["stroke-linejoin", "round"]].forEach(function (pair) { svg.setAttribute(pair[0], pair[1]); });
    ICON_PATHS[name].forEach(function (d) {
      var path = document.createElementNS(SVG_NS, "path");
      path.setAttribute("d", d);
      svg.appendChild(path);
    });
    return svg;
  }

  // Synthetic clock: offsets in seconds from the first question at 10:41:03 UTC.
  function stamp(offsetSeconds) {
    var total = 38463 + offsetSeconds;
    var pad = function (value) { return String(value).padStart(2, "0"); };
    var hh = pad(Math.floor(total / 3600));
    var mm = pad(Math.floor((total % 3600) / 60));
    var ss = pad(total % 60);
    return { iso: DAY + "T" + hh + ":" + mm + ":" + ss + "Z", short: hh + ":" + mm };
  }

  function skeleton() {
    return h("span", { class: "cs-deck-skeleton", "aria-hidden": "true" });
  }

  function availableCount(spec) {
    return spec.sources.filter(function (key) { return !SOURCES[key].unavailable; }).length;
  }

  // ---------- Inline answer text: {sourceKey} markers become citations; `code` stays literal. ----------
  var MARKER = /(\S*?)((?:\{[a-zA-Z]+\})+)([.,;:!?)]*)/g;

  function appendText(host, text) {
    text.split(/(`[^`\s]+`)/).forEach(function (part) {
      if (!part) return;
      if (part.length > 2 && part.charAt(0) === "`" && part.charAt(part.length - 1) === "`") {
        host.appendChild(h("code", { text: part.slice(1, -1) }));
      } else {
        host.appendChild(document.createTextNode(part));
      }
    });
  }

  function citation(key, spec, turnId, interactive) {
    var index = spec.sources.indexOf(key);
    if (index < 0) throw new Error("Citation " + key + " is not declared by this answer.");
    var source = SOURCES[key];
    var number = String(index + 1);
    var className = "cs-deck-cite" + (source.unavailable ? " is-unavailable" : "");
    if (!interactive) return h("span", { class: className, "aria-hidden": "true", text: number });
    return h("a", {
      class: className,
      href: "#" + turnId + "-source-" + number,
      "aria-label": "Source " + number + ": " + source.title + (source.unavailable ? ", unavailable" : ""),
      "data-tip": source.title + " - " + source.meta,
      text: number
    });
  }

  // The preceding word, citations, and trailing punctuation never wrap apart.
  function renderInline(host, text, spec, turnId, interactive) {
    var last = 0;
    var match;
    MARKER.lastIndex = 0;
    while ((match = MARKER.exec(text)) !== null) {
      appendText(host, text.slice(last, match.index));
      var run = h("span", { class: "cs-deck-cite-run" });
      appendText(run, match[1]);
      match[2].match(/\{[a-zA-Z]+\}/g).forEach(function (marker) {
        run.appendChild(citation(marker.slice(1, -1), spec, turnId, interactive));
      });
      if (match[3]) run.appendChild(document.createTextNode(match[3]));
      host.appendChild(run);
      last = MARKER.lastIndex;
    }
    appendText(host, text.slice(last));
  }

  function noteElement(note, spec, turnId, interactive) {
    var copy = h("p", null, [h("strong", { text: note.label + ": " })]);
    renderInline(copy, note.text, spec, turnId, interactive);
    if (note.link) {
      copy.appendChild(document.createTextNode(" "));
      copy.appendChild(h("a", { href: note.link.href, text: note.link.text }));
    }
    return h("div", { class: "cs-deck-evidence-note" + (note.tone === "conflict" ? " is-conflict" : ""), role: "note" }, [
      h("span", { class: "cs-deck-evidence-note-mark", "aria-hidden": "true", text: "!" }),
      copy
    ]);
  }

  // ---------- Turn parts ----------
  function stageRow(stage, number, status) {
    var copy = h("span", { class: "cs-grounding-stage-copy" }, [h("span", { class: "cs-grounding-stage-label", text: stage.label })]);
    if (stage.intent) {
      copy.appendChild(h("dl", { class: "cs-grounding-intent" }, stage.intent.map(function (pair) {
        return h("div", null, [h("dt", { text: pair[0] }), h("dd", { text: pair[1] })]);
      })));
    } else {
      copy.appendChild(h("span", { class: "cs-grounding-stage-detail", text: stage.detail }));
    }
    var row = h("li", { class: "cs-grounding-stage", "data-step": String(number) }, [
      h("span", { class: "cs-grounding-mark", "aria-hidden": "true" }),
      copy,
      h("span", { class: "cs-grounding-phase", text: stage.phase }),
      h("span", { class: "cs-sr-only" })
    ]);
    setStageStatus(row, status);
    return row;
  }

  var STAGE_STATUS_TEXT = { pending: "Not started", active: "In progress", attention: "Needs attention", done: "Done" };

  // The mark is the single status cue: the step number, then a spinner, then the outcome.
  function setStageStatus(row, status) {
    ["pending", "active", "done", "attention"].forEach(function (name) { row.classList.toggle("is-" + name, status === name); });
    var mark = row.querySelector(".cs-grounding-mark");
    mark.textContent = "";
    if (status === "pending") mark.textContent = row.getAttribute("data-step");
    else if (status === "active") mark.appendChild(h("span", { class: "cs-grounding-spinner" }));
    else mark.appendChild(h("span", { class: "cs-deck-pop", text: status === "attention" ? "!" : CHECK }));
    row.querySelector(":scope > .cs-sr-only").textContent = STAGE_STATUS_TEXT[status];
  }

  function previewSource(key) {
    var source = SOURCES[key];
    return h("li", { class: "cs-grounding-source" + (source.unavailable ? " is-unavailable" : "") }, [
      h("span", { class: "cs-deck-kind", text: source.kind }),
      h("span", { class: "cs-grounding-source-copy" }, spaced([
        h("span", { class: "cs-grounding-source-title", text: source.title }),
        h("span", { class: "cs-grounding-source-meta", text: source.meta })
      ]))
    ]);
  }

  // ---------- Run record: observed process, execution timeline, and model trace ----------
  var PHASES = [["input", "Input"], ["plan", "Plan"], ["collaboration", "Collaboration"],
    ["evidence", "Evidence and tools"], ["verification", "Verification"], ["answer", "Answer"]];
  var STATE_LABEL = { completed: "Completed", corrected: "Corrected", degraded: "Degraded", failed: "Failed",
    unverified: "Not verified", not_observed: "Not observed" };
  var STATE_MARK = { completed: CHECK, corrected: "\u21bb", degraded: "!", failed: "!", unverified: "!", not_observed: "-" };
  var PROMPT_LAYERS = [["base", "fdai.narrator-base", "2.0.0", 212], ["role", MODEL.profile, MODEL.profileVersion, 164],
    ["locale", "locale.en", "1.0.0", 18], ["response", "grounded-answer", "2.1.0", 236]];

  function clockAt(ms) {
    return new Date(Date.UTC(2026, 8, 28) + ms).toISOString();
  }

  function clockLabel(iso, withMilliseconds) {
    return iso.slice(11, withMilliseconds ? 23 : 19);
  }

  function formatMs(ms) {
    if (ms === 0) return "0 ms";
    return ms < 1000 ? ms + " ms" : (ms / 1000).toFixed(2) + " s";
  }

  function pretty(value) {
    return JSON.stringify(value, null, 2);
  }

  function sha256(text) {
    if (!window.crypto || !window.crypto.subtle || typeof TextEncoder === "undefined") {
      return Promise.resolve("unavailable in this browser context");
    }
    return window.crypto.subtle.digest("SHA-256", new TextEncoder().encode(text)).then(function (buffer) {
      return Array.prototype.map.call(new Uint8Array(buffer), function (byte) {
        return byte.toString(16).padStart(2, "0");
      }).join("");
    });
  }

  function toolKeys(spec) {
    var keys = [];
    spec.stages.forEach(function (stage) {
      (stage.emits || []).forEach(function (key) { keys.push(key); });
      if (stage.tool) keys.push(stage.tool);
    });
    return keys;
  }

  function typedIntent(spec) {
    var fields = {};
    (spec.stages[0].intent || []).forEach(function (pair) { fields[pair[0].toLowerCase()] = pair[1]; });
    var capabilities = [];
    toolKeys(spec).forEach(function (key) {
      if (capabilities.indexOf(TOOLS[key].tool) < 0) capabilities.push(TOOLS[key].tool);
    });
    return { goal: fields.goal, target: fields.target, scope: fields.scope, window: fields.window,
      capabilities: capabilities, side_effect_class: "read" };
  }

  // The narrator model's raw draft, before verification removes unsupported sentences.
  function modelDraft(spec) {
    return spec.answer.map(function (paragraph) {
      var text = paragraph.unsupported ? paragraph.text + " " + paragraph.unsupported : paragraph.text;
      return text.replace(/\{([a-zA-Z]+)\}/g, function (marker, key) {
        return " [" + (spec.sources.indexOf(key) + 1) + "]";
      }).replace(/`/g, "");
    }).join("\n\n");
  }

  function verificationState(spec) {
    if (spec.answerState === "corrected") return "corrected";
    if (spec.verification.tone === "verified") return "completed";
    if (spec.verification.label === "Source unavailable") return "unverified";
    return "degraded";
  }

  function modelCall(kind, start, ms, messages, response, usage, redactions) {
    return { kind: kind, model: MODEL.name, start: start, ms: ms, status: "completed", messages: messages,
      response: response, usage: usage, redactions: redactions };
  }

  // Deterministic synthetic schedule; a replayed turn maps it onto the phase times it observed.
  function buildTrajectory(record) {
    if (record.fixture) return fixtureTrajectory(record);
    var spec = record.spec;
    var question = spec.question || QUESTION;
    var start = (38463 + record.offset) * 1000 + 160;
    var cursor = start;
    var items = [];
    var calls = [];
    var plan = typedIntent(spec);
    items.push({ kind: "turn", kindLabel: "Turn", label: "Input", state: "completed", start: cursor, ms: 0, summary: question,
      facts: [["Source", "operator"]], records: [["Operator input", question]] });
    cursor += 6;
    var planCall = modelCall("semantic_plan", cursor + 8, MODEL.planMs, [
      { role: "system", content: "You are Bragi, the FDAI narrator. Translate the operator question into one typed intent that uses only registered read-only capabilities. Do not decide, approve, or execute anything." },
      { role: "system", content: pretty({ locale: "en", route: "live", screen: { tile: 12, resource: "example-postgres" }, capabilities: plan.capabilities }) },
      { role: "user", content: question }
    ], { content: pretty(plan) }, { prompt_tokens: 1184, completion_tokens: 142, total_tokens: 1326 }, []);
    calls.push(planCall);
    items.push({ kind: "phase", kindLabel: "Phase", label: "Semantic planning", state: "completed", start: cursor, ms: MODEL.planMs + 18,
      summary: "Typed intent: " + plan.goal,
      facts: [["Intent", plan.goal], ["Model", MODEL.name], ["Evidence requirement", "grounded"]], records: [["Answer plan", pretty(plan)]] });
    cursor += MODEL.planMs + 22;
    var attempted = 0;
    var completed = 0;
    toolKeys(spec).forEach(function (key) {
      var tool = TOOLS[key];
      var stateName = tool.status || "completed";
      attempted += 1;
      if (stateName === "completed") completed += 1;
      items.push({ kind: "evidence", kindLabel: "Evidence", label: tool.label, state: stateName, start: cursor, ms: tool.ms,
        summary: SOURCES[key] ? SOURCES[key].title + ": " + SOURCES[key].meta : null,
        facts: [["Tool", tool.tool], ["Authority", "read"]],
        records: [[tool.input === "query" ? "IQL or typed query" : "Executed command", tool.command], ["Observed output", pretty(tool.output)]] });
      cursor += tool.ms + 3;
    });
    var facts = spec.sources.map(function (key, index) {
      var source = SOURCES[key];
      return { n: index + 1, kind: source.kind, title: source.title, fact: source.meta, available: !source.unavailable };
    });
    var draft = modelDraft(spec);
    var generationCall = modelCall("answer_generation", cursor + 6, MODEL.generationMs, [
      { role: "system", content: "Compose the answer only from the verified facts. Cite every claim with its source number, state missing evidence explicitly, and never offer to execute or approve an action." },
      { role: "user", content: pretty({ question: question, facts: facts, claims_must_cite: true }) }
    ], { content: draft }, { prompt_tokens: 1360 + facts.length * 46, completion_tokens: Math.round(draft.length / 4.2),
      total_tokens: 1360 + facts.length * 46 + Math.round(draft.length / 4.2) }, [{ rule: "azure_resource_id", replacements: 1 }]);
    calls.push(generationCall);
    items.push({ kind: "phase", kindLabel: "Phase", label: "Answer generation", state: "completed", start: cursor, ms: MODEL.generationMs + 14,
      summary: spec.answer.length + " paragraphs from " + facts.length + " cited facts",
      facts: [["Model", MODEL.name], ["Format", "markdown"], ["Source", "semantic-direct-response"]], records: [] });
    cursor += MODEL.generationMs + 20;
    var check = spec.stages[spec.stages.length - 1];
    var verification = verificationState(spec);
    var verificationStart = cursor;
    items.push({ kind: "phase", kindLabel: "Phase", label: "Verification", state: verification, start: cursor, ms: 54,
      summary: check.detail, facts: [["Checks", check.detail], ["Authority", "read"]],
      records: [["Verification receipt", pretty({ status: spec.verification.label, detail: check.detail,
        evidence_refs: spec.sources.map(function (key, index) { return "source:" + (index + 1) + ":" + TOOLS[key].tool; }) })]] });
    cursor += 58;
    items.push({ kind: "turn", kindLabel: "Turn", label: "Answer", state: "completed", start: cursor, ms: 0,
      summary: "verification: " + spec.verification.label, facts: [["Source", "semantic-direct-response"], ["Agent", "Bragi"]],
      records: [["Delivery receipt", pretty({ source: "semantic-direct-response", agent: "bragi",
        verification_status: spec.verification.label, citation_count: spec.sources.length, follow_ups: (spec.followups || []).length })]] });
    var trajectory = {
      start: start, end: cursor, items: items, calls: calls, attempted: attempted, completed: completed,
      modelMs: planCall.ms + generationCall.ms, tokens: planCall.usage.total_tokens + generationCall.usage.total_tokens,
      verification: verification
    };
    return record.observed ? observedTrajectory(trajectory, record.observed, [start, generationCall.start - 6, verificationStart])
      : trajectory;
  }

  // A replayed turn records when preparation, streaming, and verification ended. Mapping the
  // synthetic schedule onto those marks keeps the run record's durations equal to what was shown.
  function observedTrajectory(trajectory, observed, marks) {
    var from = marks.concat([trajectory.end]);
    var to = [0, observed.prepared, observed.streamed, observed.total].map(function (ms) { return trajectory.start + ms; });
    function map(time) {
      for (var index = 1; index < from.length; index += 1) {
        if (time <= from[index] || index === from.length - 1) {
          var span = from[index] - from[index - 1];
          var ratio = span > 0 ? Math.min(1, Math.max(0, (time - from[index - 1]) / span)) : 1;
          return to[index - 1] + ratio * (to[index] - to[index - 1]);
        }
      }
      return time;
    }
    trajectory.items.concat(trajectory.calls).forEach(function (entry) {
      var begin = map(entry.start);
      var finish = map(entry.start + entry.ms);
      entry.start = Math.round(begin);
      entry.ms = Math.max(0, Math.round(finish - begin));
    });
    trajectory.end = Math.round(to[3]);
    trajectory.modelMs = trajectory.calls.reduce(function (total, call) { return total + call.ms; }, 0);
    return trajectory;
  }

  function barFor(start, ms, spanStart, span) {
    var left = Math.min(98.5, ((start - spanStart) / span) * 100);
    var width = Math.min(100 - left, Math.max(1.5, (ms / span) * 100));
    var bar = h("span", { class: "cs-run-bar" });
    bar.style.setProperty("--cs-run-start", left.toFixed(2));
    bar.style.setProperty("--cs-run-width", width.toFixed(2));
    return h("span", { class: "cs-run-track", "aria-hidden": "true" }, [bar]);
  }

  function factList(pairs) {
    return h("dl", { class: "cs-run-facts" }, pairs.map(function (pair) {
      return h("div", null, [h("dt", { text: pair[0] }), h("dd", null, [pair[1]])]);
    }));
  }

  var PAYLOAD_LANGUAGE = { "IQL or typed query": "query", "Executed command": "shell", "Typed call": "query",
    "Provider equivalent": "shell" };

  function payload(label, value) {
    return h("section", { class: "cs-run-payload" }, [
      h("strong", { text: label }),
      codeBlock(value, PAYLOAD_LANGUAGE[label])
    ]);
  }

  // ---------- Code: the component gallery's compact code pattern ----------
  var codeSource = new WeakMap();
  var JSON_TOKEN = /("(?:[^"\\]|\\.)*")(\s*:)?|(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)|\b(true|false|null)\b|([{}\[\],])/g;

  function codeToken(text, kind) {
    return h("span", { class: "cs-deck-code-token is-" + kind, text: text });
  }

  function jsonTokens(line) {
    var parts = [];
    var last = 0;
    var match;
    JSON_TOKEN.lastIndex = 0;
    while ((match = JSON_TOKEN.exec(line)) !== null) {
      if (match.index > last) parts.push(line.slice(last, match.index));
      if (match[1]) {
        parts.push(codeToken(match[1], match[2] ? "key" : "string"));
        if (match[2]) parts.push(codeToken(match[2], "punctuation"));
      } else if (match[3]) {
        parts.push(codeToken(match[3], "number"));
      } else if (match[4]) {
        parts.push(codeToken(match[4], "boolean"));
      } else {
        parts.push(codeToken(match[5], "punctuation"));
      }
      last = JSON_TOKEN.lastIndex;
    }
    if (last < line.length) parts.push(line.slice(last));
    return parts;
  }

  // A typed query or command reads as its verb, then key=value arguments.
  function commandTokens(line) {
    var parts = [];
    line.split(/(\s+)/).forEach(function (part, index) {
      var equals = part.indexOf("=");
      if (index === 0 && part) parts.push(codeToken(part, "command"));
      else if (equals > 0) parts.push(codeToken(part.slice(0, equals + 1), "flag"), part.slice(equals + 1));
      else if (/^--?[a-z]/i.test(part)) parts.push(codeToken(part, "flag"));
      else if (part) parts.push(part);
    });
    return parts;
  }

  // Colors never replace the text: copy returns the exact source, and every token stays readable.
  function codeBlock(text, language) {
    var kind = language || (/^\s*[\[{]/.test(text) ? "json" : "text");
    var code = h("code");
    text.split("\n").forEach(function (line) {
      var parts = kind === "json" ? jsonTokens(line) : kind === "text" ? [line] : commandTokens(line);
      code.appendChild(h("span", { class: "cs-deck-code-line" }, parts.length && line ? parts : [" "]));
    });
    var label = kind === "json" ? "JSON" : kind;
    var figure = h("figure", { class: "cs-deck-code" }, [
      h("figcaption", { class: "cs-deck-code-head" }, [
        h("span", { class: "cs-deck-code-lang", text: kind }),
        h("button", { type: "button", class: "cs-deck-code-copy", "data-action": "copy-code", "aria-label": "Copy " + label, text: "Copy" })
      ]),
      h("div", { class: "cs-deck-code-scroll" }, [h("pre", { class: "cs-deck-code-block" }, [code])])
    ]);
    codeSource.set(figure, text);
    return figure;
  }

  function copyCode(button) {
    var figure = button.closest(".cs-deck-code");
    var text = figure && codeSource.get(figure);
    if (text === undefined) return;
    var finish = function (copied) {
      button.textContent = copied ? "Copied" : "Unavailable";
      button.classList.toggle("is-copied", copied);
      announce(copied ? "Copied." : "Copy is unavailable in this preview.");
      window.setTimeout(function () {
        button.textContent = "Copy";
        button.classList.remove("is-copied");
      }, 1200);
    };
    if (!navigator.clipboard || !window.isSecureContext) {
      finish(false);
      return;
    }
    navigator.clipboard.writeText(text).then(function () { finish(true); }, function () { finish(false); });
  }

  function timeValue(iso) {
    return h("time", { datetime: iso, text: clockLabel(iso, true) });
  }

  function timelineEvent(item, trajectory) {
    var span = Math.max(1, trajectory.end - trajectory.start);
    var startIso = clockAt(item.start);
    var detail = h("div", { class: "cs-run-event-detail" });
    if (item.summary) detail.appendChild(h("p", { class: "cs-run-observed" }, [h("span", { text: "Observed detail" }), item.summary]));
    detail.appendChild(factList([["Status", STATE_LABEL[item.state]], ["Started", timeValue(startIso)],
      ["Completed", timeValue(clockAt(item.start + item.ms))]].concat(item.facts)));
    item.records.forEach(function (entry) { detail.appendChild(payload(entry[0], entry[1])); });
    return h("li", { class: "cs-run-event", "data-kind": item.kind, "data-state": item.state }, [h("details", null, [
      h("summary", { class: "cs-run-event-summary" }, spaced([
        h("span", { class: "cs-run-event-kind", text: item.kindLabel }),
        h("strong", { class: "cs-run-event-label", text: item.label }),
        barFor(item.start, item.ms, trajectory.start, span),
        h("span", { class: "cs-run-event-duration", text: formatMs(item.ms) }),
        h("span", { class: "cs-run-event-outcome", text: STATE_LABEL[item.state] }),
        h("span", { class: "cs-run-chevron", "aria-hidden": "true" })
      ])),
      detail
    ])]);
  }

  function modelCallItem(call) {
    return { kind: "model", kindLabel: "Model", label: "Model provider call", state: "completed", start: call.start, ms: call.ms,
      summary: call.kind + " / " + call.model,
      facts: [["Model", call.model], ["Request messages", String(call.messages.length)], ["Response", "Recorded"],
        ["Usage", "prompt " + call.usage.prompt_tokens + " / completion " + call.usage.completion_tokens + " / total " + call.usage.total_tokens],
        ["Redactions", String(call.redactions.reduce(function (total, item) { return total + item.replacements; }, 0))]],
      records: [["Model request", pretty(call.messages)], ["Model response", pretty(call.response)]] };
  }

  function timelineSection(trajectory, includeModelCalls) {
    var items = trajectory.items.concat(includeModelCalls ? trajectory.calls.map(modelCallItem) : [])
      .map(function (item, order) { return { item: item, order: order }; })
      .sort(function (left, right) { return left.item.start - right.item.start || left.order - right.order; })
      .map(function (entry) { return entry.item; });
    return h("section", { class: "cs-run-timeline", "aria-label": "Observed execution timeline" }, [
      h("header", { class: "cs-run-timeline-head" }, [
        h("h3", { class: "cs-run-timeline-title", text: "Observed execution timeline" }),
        h("span", { class: "cs-run-timeline-count", text: items.length + " observed events" })
      ]),
      h("div", { class: "cs-run-axis", "aria-hidden": "true" }, [h("span", { class: "cs-run-axis-range" }, [
        h("span", { text: clockLabel(clockAt(trajectory.start)) }),
        h("span", { text: formatMs(trajectory.end - trajectory.start) }),
        h("span", { text: clockLabel(clockAt(trajectory.end)) })
      ])]),
      h("ol", { class: "cs-run-events" }, items.map(function (item) { return timelineEvent(item, trajectory); }))
    ]);
  }

  function hashLine(label, text) {
    var code = h("code", { text: "computing" });
    sha256(text).then(function (value) { code.textContent = value; });
    return h("p", { class: "cs-model-trace-hash" }, [h("span", { text: label }), code]);
  }

  function modelTraceLane(call, index, spanStart, span) {
    var startIso = clockAt(call.start);
    var systemText = call.messages.filter(function (message) { return message.role === "system"; })
      .map(function (message) { return message.content; }).join("\n\n");
    var groups = [];
    call.messages.forEach(function (message) {
      var previous = groups[groups.length - 1];
      if (message.role === "system" && previous && previous.role === "system") previous.contents.push(message.content);
      else groups.push({ role: message.role, contents: [message.content] });
    });
    var detail = h("div", { class: "cs-model-trace-detail" }, [
      hashLine("Request SHA-256", JSON.stringify(call.messages)),
      h("section", { class: "cs-run-payload", "aria-label": "Dynamic system prompt" }, [
        h("strong", { text: "Dynamic system prompt" }),
        hashLine("SYSTEM SHA-256", systemText),
        factList([["Prompt profile", MODEL.profile + " v" + MODEL.profileVersion],
          ["SYSTEM tokens / budget", "630 / 1200"]]),
        h("ol", { class: "cs-model-trace-layers", "aria-label": "Ordered prompt layers" }, PROMPT_LAYERS.map(function (layer) {
          return h("li", null, [h("code", { text: layer[0] }), h("span", { text: layer[1] + " v" + layer[2] }),
            h("span", { text: layer[3] + " tokens" })]);
        }))
      ]),
      h("ol", { class: "cs-model-trace-messages", "aria-label": "Request messages" }, groups.map(function (group) {
        // Each message keeps its own block, so a JSON context message is highlighted as JSON.
        return h("li", null, [h("strong", { class: "cs-model-trace-role", text: group.role })]
          .concat(group.contents.map(function (content) { return codeBlock(content); })));
      })),
      h("section", { class: "cs-run-payload", "aria-label": "Assistant response" }, [
        h("strong", { text: "Assistant response" }),
        hashLine("Response SHA-256", call.response.content),
        codeBlock(call.response.content)
      ]),
      factList([["prompt_tokens", String(call.usage.prompt_tokens)], ["completion_tokens", String(call.usage.completion_tokens)],
        ["total_tokens", String(call.usage.total_tokens)],
        ["Applied redactions", call.redactions.length ? call.redactions.map(function (item) { return item.rule + " x" + item.replacements; }).join(", ") : "None"]])
    ]);
    return h("li", { class: "cs-model-trace-lane", "data-status": call.status }, [h("details", null, [
      h("summary", { class: "cs-model-trace-lane-summary" }, spaced([
        h("span", { class: "cs-model-trace-index", text: String(index + 1).padStart(2, "0") }),
        h("span", { class: "cs-model-trace-model", text: call.model }),
        h("span", { class: "cs-model-trace-kind", text: call.kind }),
        barFor(call.start, call.ms, spanStart, span),
        h("time", { class: "cs-model-trace-clock", datetime: startIso, text: clockLabel(startIso, true) }),
        h("span", { class: "cs-model-trace-duration", text: formatMs(call.ms) }),
        h("span", { class: "cs-run-chevron", "aria-hidden": "true" })
      ])),
      detail
    ])]);
  }

  function modelTraceSection(trajectory, captureOn, captured) {
    var showCalls = captureOn && captured;
    var section = h("section", { class: "cs-model-trace", "aria-label": "Model provider waterfall" }, [
      h("header", { class: "cs-model-trace-head" }, [
        h("div", null, [
          h("h3", { class: "cs-model-trace-title", text: "Model provider waterfall" }),
          showCalls ? h("p", { class: "cs-model-trace-notice", text: "Actual provider messages and assistant content after deterministic redaction. Hidden reasoning and provider internals are not captured." }) : null
        ]),
        showCalls ? h("span", { class: "cs-model-trace-count", text: trajectory.calls.length + " model calls" }) : null
      ])
    ]);
    if (!showCalls) {
      section.appendChild(h("div", { class: "cs-model-trace-note", role: "note" }, captureOn ? [
        h("strong", { text: "Model trace not captured" }),
        h("p", { text: "No model trace was captured for this turn. Enable capture in Settings before asking a new question." })
      ] : [
        h("strong", { text: "Provider trace capture is off" }),
        h("p", { text: "Enable model request and response trace in Settings. The change applies to new turns and doesn't reveal previously hidden provider data." })
      ]));
      return section;
    }
    var first = trajectory.calls[0].start;
    var last = Math.max.apply(null, trajectory.calls.map(function (call) { return call.start + call.ms; }));
    var span = Math.max(1, (last - first) * 1.1);
    section.appendChild(h("ol", { class: "cs-model-trace-lanes" }, trajectory.calls.map(function (call, index) {
      return modelTraceLane(call, index, first, span);
    })));
    return section;
  }

  function phaseStrip(trajectory, spec) {
    var evidence = trajectory.evidenceState ||
      (toolKeys(spec).some(function (key) { return TOOLS[key].status; }) ? "degraded" : "completed");
    var states = { input: "completed", plan: "completed", collaboration: "not_observed", evidence: evidence,
      verification: trajectory.verification, answer: "completed" };
    return h("ol", { class: "cs-run-phase-strip", "aria-label": "Question-to-answer trajectory phases" }, PHASES.map(function (phase) {
      var value = states[phase[0]];
      return h("li", { class: "cs-run-phase", "data-state": value }, [
        h("span", { class: "cs-run-phase-mark", "aria-hidden": "true", text: STATE_MARK[value] }),
        h("strong", { text: phase[1] }),
        // The check mark already says completed; other states keep their visible label.
        h("small", { class: value === "completed" ? "cs-sr-only" : null, text: STATE_LABEL[value] })
      ]);
    }));
  }

  // The body renders on first open, so settled turns stay light until someone inspects them.
  function runRecord(record, open) {
    var trajectory = buildTrajectory(record);
    var captureOn = state.captureTrace;
    var traceLabel = !captureOn ? "Model trace off" : record.captured ? trajectory.calls.length + " model calls" : "Model trace not captured";
    var stats = [traceLabel, "model " + formatMs(trajectory.modelMs), trajectory.tokens.toLocaleString("en-US") + " tokens",
      "evidence " + trajectory.completed + " of " + trajectory.attempted,
      "verification " + STATE_LABEL[trajectory.verification].toLowerCase()].join(" \u00b7 ");
    var body = h("div", { class: "cs-run-record-body" });
    var details = h("details", { class: "cs-run-record", "data-run-record": record.turnId }, [
      h("summary", { class: "cs-run-record-summary" }, spaced([
        h("span", { class: "cs-run-record-title" }, [
          h("span", { class: "cs-run-record-glyph", "aria-hidden": "true" }, [h("i"), h("i"), h("i")]),
          h("strong", { class: "cs-run-record-heading", text: "Run record" })
        ]),
        h("span", { class: "cs-run-record-stats", text: stats }),
        h("span", { class: "cs-run-record-duration" }, [
          h("span", { class: "cs-run-record-duration-label", text: "Server processing " }),
          formatMs(trajectory.end - trajectory.start)
        ]),
        h("span", { class: "cs-run-record-chevron", "aria-hidden": "true" })
      ])),
      body
    ]);
    function fill() {
      if (body.childElementCount) return;
      body.appendChild(phaseStrip(trajectory, record.spec));
      body.appendChild(timelineSection(trajectory, captureOn && record.captured));
      body.appendChild(modelTraceSection(trajectory, captureOn, record.captured));
    }
    // Filling on the summary click, before the details element opens, avoids painting an empty body.
    details.firstElementChild.addEventListener("click", fill);
    details.addEventListener("toggle", function () { if (details.open) fill(); });
    if (open) {
      fill();
      details.open = true;
    }
    return details;
  }

  // Rebuild in place with the body already filled, so an open record never flashes empty.
  function refreshRunRecords() {
    turns.querySelectorAll("details.cs-run-record").forEach(function (current) {
      var record = records[current.getAttribute("data-run-record")];
      if (record) current.replaceWith(runRecord(record, current.open));
    });
  }

  function actionRow(spec, turnId) {
    var verification = spec.verification;
    var pill = spec.pill || { attention: false, issue: null };
    var available = availableCount(spec);
    // The verdict and its sources lead; the reply tools stay together at the row end.
    var pillChildren = [];
    if (pill.attention) pillChildren.push(h("span", { class: "cs-deck-pill-mark", "aria-hidden": "true", text: "!" }));
    pillChildren.push(h("span", { class: "cs-deck-pill-stat" }, [h("strong", { text: String(available) }), available === 1 ? " source" : " sources"]));
    if (pill.issue) pillChildren.push(separator(), h("span", { class: "cs-deck-pill-issue", text: pill.issue }));
    pillChildren.push(h("span", { class: "cs-deck-pill-more" }, [icon("chevron")]));
    return h("div", { class: "cs-deck-action-row" }, [
      h("span", { class: "cs-deck-verification is-" + verification.tone }, spaced([
        h("span", { class: "cs-deck-verification-mark", "aria-hidden": "true", text: verification.mark }),
        h("span", { text: verification.label }),
        h("span", { class: "cs-deck-verification-detail", text: verification.detail })
      ])),
      h("button", {
        type: "button",
        class: "cs-deck-pill" + (pill.attention ? " is-attention" : ""),
        "aria-expanded": "false",
        "aria-controls": turnId + "-sources",
        "data-action": "sources"
      }, spaced(pillChildren)),
      h("span", { class: "cs-deck-tools" }, [
        h("button", { type: "button", class: "cs-deck-tool cs-deck-tool-icon", "aria-label": "Copy reply", "data-tip": "Copy reply", "data-action": "copy" }, [icon("copy")]),
        h("button", { type: "button", class: "cs-deck-tool cs-deck-tool-icon", "aria-label": "Regenerate", "data-tip": "Ask this question again", "data-action": "regenerate" }, [icon("regenerate")]),
        h("a", { class: "cs-deck-tool cs-deck-tool-icon", href: "conversation-assurance.html", "aria-label": "Review answer quality", "data-tip": "Review answer quality" }, [icon("review")])
      ])
    ]);
  }

  function sourcesPanel(spec, turnId) {
    return h("div", { class: "cs-deck-sources", id: turnId + "-sources", hidden: true }, [
      h("ol", { class: "cs-deck-source-list", "aria-label": "Sources for this answer" }, spec.sources.map(function (key, index) {
        var source = SOURCES[key];
        var number = String(index + 1);
        var when = source.time
          ? h("time", { class: "cs-deck-source-time", datetime: DAY + "T" + source.time + "Z", text: source.time + " UTC" })
          : h("span", { class: "cs-deck-source-time", text: source.unavailable ? "Not read" : source.catalog });
        // A source opens its provenance in place; only its explicit Open action leaves, after asking.
        var detailId = turnId + "-source-" + number + "-detail";
        var tool = TOOLS[key];
        var facts = [["Access", "Read-only"], ["Opens", pageLabel(source.href)]];
        if (tool) facts.unshift(["Read with", tool.tool]);
        return h("li", null, [
          h("button", {
            type: "button",
            class: "cs-deck-source" + (source.unavailable ? " is-unavailable" : ""),
            id: turnId + "-source-" + number,
            "aria-expanded": "false",
            "aria-controls": detailId,
            "data-action": "source-detail"
          }, spaced([
            h("span", { class: "cs-deck-source-num", "aria-hidden": "true", text: number }),
            h("span", { class: "cs-deck-kind", text: source.kind }),
            h("span", { class: "cs-deck-source-copy" }, spaced([
              h("span", { class: "cs-deck-source-title", text: source.title }),
              h("span", { class: "cs-deck-source-meta", text: source.meta })
            ])),
            when
          ])),
          h("div", { class: "cs-deck-source-detail", id: detailId, hidden: true }, [
            h("dl", { class: "cs-deck-source-facts" }, facts.map(function (pair) {
              return h("div", null, [h("dt", { text: pair[0] }), h("dd", { text: pair[1] })]);
            })),
            h("button", { type: "button", class: "cs-deck-source-open", "data-action": "open-page", "data-href": source.href,
              text: "Open " + pageLabel(source.href) })
          ])
        ]);
      }))
    ]);
  }

  function followupList(keys) {
    return h("ul", { class: "cs-deck-followups", "aria-label": "Suggested follow-ups" }, keys.map(function (key) {
      return h("li", null, [h("button", {
        type: "button",
        class: "cs-deck-followup",
        "data-followup": key,
        "aria-disabled": "false",
        text: FOLLOWUPS[key].question
      })]);
    }));
  }

  // The reply time sits beside the agent name, like the time inside the question bubble.
  function setTurnTime(article, offsetSeconds, animate) {
    var head = article.querySelector(".cs-deck-turn-head");
    if (head.querySelector(".cs-deck-head-time")) return;
    var time = stamp(offsetSeconds);
    var name = head.querySelector(".cs-deck-agent-name");
    head.insertBefore(h("time", {
      class: "cs-deck-turn-time cs-deck-head-time" + (animate ? " cs-deck-fade-in" : ""),
      datetime: time.iso,
      text: time.short
    }), name.nextSibling);
  }

  // An attached document shows as a chip inside the question it came with.
  function userTurn(text, offsetSeconds, attachment) {
    var time = stamp(offsetSeconds);
    return h("article", { class: "cs-deck-turn cs-deck-user-turn", "data-turn": "user" }, [
      h("div", { class: "cs-deck-user-bubble" }, [
        attachment ? h("p", { class: "cs-deck-user-attachment" }, spaced([
          icon("file"),
          h("span", { class: "cs-deck-user-attachment-name", text: attachment.name }),
          h("span", { class: "cs-deck-user-attachment-meta", text: attachment.lines + " lines" })
        ])) : null,
        h("p", { class: "cs-deck-user-line", text: text }),
        h("div", { class: "cs-deck-user-time" }, [
          h("time", { class: "cs-deck-turn-time", datetime: time.iso, text: time.short })
        ])
      ])
    ]);
  }

  // Semantic answers carry no reply-source chip, matching the Console turn head.
  function agentArticle(turnId) {
    return h("article", { class: "cs-deck-turn cs-deck-agent-turn", id: turnId, "data-turn": "agent" }, [
      h("header", { class: "cs-deck-turn-head" }, [
        h("span", { class: "cs-deck-agent-name" }, [h("span", { class: "cs-deck-agent-icon ds-agent-icon", "aria-hidden": "true" }), "Bragi"])
      ])
    ]);
  }

  function readinessStrip(mode, animate) {
    if (mode === "loading") {
      return h("div", { class: "cs-deck-readiness is-loading", role: "status", "aria-busy": "true" }, [
        h("span", { class: "cs-sr-only", text: "Loading evidence-source readiness" }),
        skeleton(), skeleton(), skeleton()
      ]);
    }
    var unavailable = (SCENARIOS[mode] || SCENARIOS.grounded).unavailableSources;
    var items = READINESS.map(function (source) {
      var down = unavailable.indexOf(source.key) >= 0;
      return h("li", null, [h("a", {
        class: "cs-deck-readiness-item " + (down ? "is-unavailable" : "is-available"),
        href: source.href,
        "aria-label": source.label + ": " + (down ? "Unavailable" : "Available")
      }, spaced([
        h("span", { class: "cs-deck-readiness-mark", "aria-hidden": "true", text: down ? "!" : CHECK }),
        source.label,
        down ? h("span", { class: "cs-deck-readiness-state", text: "Unavailable" }) : null
      ]))]);
    });
    return h("nav", { class: "cs-deck-readiness" + (animate ? " cs-deck-fade-in" : ""), "aria-label": "Evidence sources" }, [
      h("span", { class: "cs-deck-readiness-label", text: "Evidence sources" }),
      h("ul", { class: "cs-deck-readiness-items" }, items),
      h("span", {
        class: "cs-deck-readiness-summary" + (unavailable.length ? " is-attention" : ""),
        text: unavailable.length ? unavailable.length + " unavailable" : "All available"
      }),
      h("span", { class: "cs-deck-readiness-time" }, [h("time", { datetime: DAY + "T10:41:04Z" }, [
        h("span", { class: "cs-deck-readiness-time-label", text: "Observed " }),
        "10:41:04 UTC"
      ])])
    ]);
  }

  // ---------- State ----------
  var ANSWER_STATE = { partial: "Partial", corrected: "Corrected", stopped: "Stopped", unverified: "Unverified" };
  var params = new URLSearchParams(window.location.search);

  function initialScenario() {
    var requested = params.get("scenario");
    if (ADAPTIVE) return INVESTIGATIONS.indexOf(requested) >= 0 ? requested : "no-drift";
    return SCENARIOS[requested] ? requested : "grounded";
  }

  var reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  var state = {
    scenario: initialScenario(),
    speed: 1,
    width: params.get("width") === "dock" ? "dock" : "full",
    token: 0,
    busy: false,
    active: null,
    stuck: true,
    clock: 0,
    turnSeq: 0,
    asked: {},
    screenAttached: true,
    reduced: reducedMotion.matches,
    captureTrace: params.get("trace") === "on",
    deckState: "loading"
  };
  var pending = new Map();
  var records = {};
  var elapsedTimer = null;

  function byId(id) { return document.getElementById(id); }
  var workspace = byId("ds-workspace");
  var header = byId("ds-header");
  var readiness = byId("ds-readiness");
  var bodyGrid = byId("ds-body");
  var transcript = byId("ds-transcript");
  var turns = byId("ds-turns");
  var jump = byId("ds-jump");
  var composer = byId("ds-composer");
  var input = byId("ds-input");
  var send = byId("ds-send");
  var note = byId("ds-composer-note");
  var contextChip = byId("ds-context");
  var closedPanel = byId("ds-closed");
  var reopen = byId("ds-reopen");
  var titleNode = byId("ds-conversation-title");
  var announcer = byId("ds-announcer");
  var searchInput = byId("ds-search");
  var searchCount = byId("ds-search-count");
  var searchPrev = byId("ds-search-prev");
  var searchNext = byId("ds-search-next");
  var traceSwitch = byId("ds-trace");

  // ---------- Replay control ----------
  function cancelRun() {
    state.token += 1;
    pending.forEach(function (entry) {
      entry.cancel();
      entry.reject(CANCELLED);
    });
    pending.clear();
    stopElapsed();
  }

  function pause(ms, ctx) {
    if (ctx.instant) return Promise.resolve();
    if (ctx.token !== state.token) return Promise.reject(CANCELLED);
    return new Promise(function (resolve, reject) {
      var key = {};
      var id = window.setTimeout(function () {
        pending.delete(key);
        if (ctx.token === state.token) resolve();
        else reject(CANCELLED);
      }, Math.max(0, ms / state.speed));
      pending.set(key, { cancel: function () { window.clearTimeout(id); }, reject: reject });
    });
  }

  function newContext(instant) {
    return { token: state.token, instant: !!instant, reduced: state.reduced };
  }

  function ignoreCancel(error) {
    if (error !== CANCELLED) throw error;
  }

  function setDeckState(value) {
    // While the deck is closed, remember the latest state for reopening instead of exposing it.
    if (value !== "closed" && workspace.getAttribute("data-open") === "false") {
      stateBeforeClose = value;
      return;
    }
    state.deckState = value;
    document.body.setAttribute("data-deck-state", value);
  }

  function updateSend() {
    send.disabled = !state.busy && input.value.trim().length === 0;
  }

  function setBusy(busy) {
    state.busy = busy;
    transcript.setAttribute("aria-busy", busy ? "true" : "false");
    send.classList.toggle("is-stop", busy);
    send.type = busy ? "button" : "submit";
    send.textContent = busy ? "Stop" : "Send";
    // A disabled button drops focus to the document, so keep keyboard users in the composer.
    if (!busy && document.activeElement === send && input.value.trim().length === 0) {
      input.focus({ preventScroll: true });
    }
    updateSend();
    turns.querySelectorAll(".cs-deck-followup").forEach(function (button) {
      button.setAttribute("aria-disabled", busy ? "true" : "false");
    });
  }

  function announce(text) {
    announcer.textContent = "";
    window.setTimeout(function () { announcer.textContent = text; }, 60);
  }

  function startElapsed(node) {
    stopElapsed();
    var started = performance.now();
    elapsedTimer = window.setInterval(function () {
      node.textContent = ((performance.now() - started) / 1000).toFixed(1) + " s";
    }, 100);
  }

  function stopElapsed() {
    if (elapsedTimer) window.clearInterval(elapsedTimer);
    elapsedTimer = null;
  }

  function atBottom() {
    return transcript.scrollHeight - transcript.scrollTop - transcript.clientHeight < 32;
  }

  // Reserved room below the newest turn is blank, so only real content counts as newer below.
  function updateJump() {
    var last = turns.lastElementChild;
    var content = last && last.lastElementChild;
    var bottom = content ? content.getBoundingClientRect().bottom : 0;
    jump.hidden = atBottom() || bottom <= transcript.getBoundingClientRect().bottom + 8;
  }

  // ---------- Scroll follow ----------
  // A live turn eases the view toward new content but never lifts the question being answered above
  // the top edge, so the text someone is reading holds still. When the turn settles, the view eases
  // just far enough to show the verification row. Any scroll the follower did not make itself, such
  // as a wheel, a key, focus moving into view, or find in page, stops the follow unless it lands on
  // the bottom, which follows the newest content instead.
  var follow = { frame: 0, mode: "pin", pin: null, reveal: null, expected: 0 };

  function contentTop(node) {
    return node.getBoundingClientRect().top - transcript.getBoundingClientRect().top + transcript.scrollTop;
  }

  function followTarget() {
    var max = transcript.scrollHeight - transcript.clientHeight;
    if (follow.mode === "bottom" || !follow.pin || !follow.pin.isConnected) return Math.max(0, max);
    var target = Math.min(max, contentTop(follow.pin) - 12);
    if (follow.reveal && follow.reveal.isConnected) {
      var need = contentTop(follow.reveal) + follow.reveal.offsetHeight + 16 - transcript.clientHeight;
      target = Math.max(target, Math.min(max, need));
    }
    return Math.max(0, target);
  }

  function followScroll() {
    if (!state.stuck) {
      updateJump();
      return;
    }
    if (state.reduced) {
      var target = followTarget();
      if (target > transcript.scrollTop) moveScroll(target);
      updateJump();
      return;
    }
    if (!follow.frame) follow.frame = window.requestAnimationFrame(followStep);
  }

  function moveScroll(value) {
    transcript.scrollTop = value;
    follow.expected = transcript.scrollTop;
  }

  function followStep() {
    follow.frame = 0;
    if (!state.stuck) return;
    var distance = followTarget() - transcript.scrollTop;
    if (distance > 0.5) {
      // Ease out with a speed cap, so a long reveal glides instead of leaping.
      moveScroll(transcript.scrollTop + Math.min(28, Math.max(1, distance * 0.16)));
      follow.frame = window.requestAnimationFrame(followStep);
    }
    updateJump();
  }

  // A scroll between the follower's last position and its target, such as a clamp after content
  // shrinks, keeps the follow; anything else is the reader moving the view.
  function noteScroll() {
    var top = transcript.scrollTop;
    if (Math.abs(top - follow.expected) <= 1) return;
    var target = followTarget();
    var onCourse = state.stuck && top >= Math.min(follow.expected, target) - 2 && top <= target + 2;
    if (!onCourse) {
      state.stuck = atBottom();
      if (state.stuck) follow.mode = "bottom";
    }
    follow.expected = top;
  }

  function followTurn(pin) {
    follow.mode = "pin";
    follow.pin = pin;
    follow.reveal = null;
  }

  // Reserve room below a new question so it can rise to the top edge. The reserve keeps the view
  // from snapping when the preparation panel folds and moves to the newest turn when another starts.
  function reserveTurn(article) {
    turns.querySelectorAll(".cs-deck-agent-turn[data-reserved]").forEach(function (node) {
      node.style.minHeight = "";
      node.removeAttribute("data-reserved");
    });
    var question = article.previousElementSibling;
    if (!question) return;
    var need = contentTop(question) - 12 - (transcript.scrollHeight - transcript.clientHeight);
    if (need <= 0) return;
    article.style.minHeight = Math.ceil(article.offsetHeight + need) + "px";
    article.setAttribute("data-reserved", "");
  }

  // ---------- Turn lifecycle ----------
  async function playPreparation(spec, ctx, article) {
    var steps = spec.stages.filter(function (stage) { return !stage.verify; });
    var status = h("span", { class: "cs-grounding-status", text: "Step 1 of " + steps.length });
    var elapsed = h("span", { class: "cs-grounding-elapsed", "aria-hidden": "true", text: "0.0 s" });
    var stages = h("ol", { class: "cs-grounding-stages", "aria-label": "Preparation steps" });
    // The active step's own spinner is the only busy cue, so the header carries no second one.
    var panel = h("section", { class: "cs-grounding-panel", "aria-label": "Preparing answer" }, [
      h("header", { class: "cs-grounding-head" }, spaced([
        h("span", { class: "cs-grounding-title", text: "Preparing answer" }),
        status,
        elapsed,
        h("span", { class: "cs-grounding-authority", text: "Read-only" })
      ])),
      stages
    ]);
    var placeholder = h("div", { class: "cs-deck-answer-skeleton", "aria-hidden": "true" }, [skeleton(), skeleton(), skeleton()]);
    // The window holds as many rows as this turn will read, up to three, so no slot waits in vain.
    var emitted = steps.reduce(function (total, stage) { return total + (stage.emits || []).length; }, 0);
    var slots = Math.max(1, Math.min(3, emitted));
    var sourceList = h("ul", { class: "cs-grounding-source-list" }, Array.from({ length: slots }, function () {
      return h("li", { class: "cs-grounding-source is-placeholder", "aria-hidden": "true" }, [skeleton()]);
    }));
    sourceList.style.setProperty("--cs-grounding-source-rows", String(slots));
    var sourceCount = h("span", { text: "0 read" });
    panel.appendChild(h("div", { class: "cs-grounding-sources" }, [
      h("div", { class: "cs-grounding-sources-head" }, [h("span", { text: "Reading sources" }), sourceCount]),
      sourceList
    ]));
    var fold = h("div", { class: "cs-deck-collapse" + (ctx.reduced ? "" : " cs-deck-enter") }, [h("div", null, [panel])]);
    article.appendChild(fold);
    article.appendChild(placeholder);
    startElapsed(elapsed);
    followScroll();
    var read = 0;
    var missing = 0;
    // The whole plan renders up front as pending rows, so the panel keeps one height while the
    // steps run and nothing below it moves.
    var rows = steps.map(function (stage, index) { return stageRow(stage, index + 1, "pending"); });
    rows.forEach(function (row) { stages.appendChild(row); });
    for (var index = 0; index < steps.length; index += 1) {
      var stage = steps[index];
      var row = rows[index];
      setStageStatus(row, "active");
      status.textContent = "Step " + (index + 1) + " of " + steps.length;
      followScroll();
      await pause(ctx.reduced ? TIMING.step : TIMING.stage, ctx);
      setStageStatus(row, stage.attention ? "attention" : "done");
      var emits = stage.emits || [];
      for (var item = 0; item < emits.length; item += 1) {
        var slot = sourceList.querySelector(":scope > .is-placeholder");
        if (slot) {
          slot.replaceWith(previewSource(emits[item]));
        } else {
          sourceList.appendChild(previewSource(emits[item]));
          rollSourceWindow(sourceList, ctx);
        }
        if (SOURCES[emits[item]].unavailable) missing += 1;
        else read += 1;
        sourceCount.textContent = read + " read" + (missing ? " \u00b7 " + missing + " unavailable" : "");
        followScroll();
        await pause(TIMING.source, ctx);
      }
    }
    status.textContent = "Composing answer";
    await pause(TIMING.stage / 2, ctx);
    stopElapsed();
    return fold;
  }

  // Keep the newest three sources and slide the window instead of jumping when one leaves.
  function rollSourceWindow(list, ctx) {
    if (list.children.length <= 3) return;
    var first = list.firstElementChild;
    var pitch = first.getBoundingClientRect().height + 4;
    first.remove();
    if (ctx.reduced || typeof list.animate !== "function") return;
    list.animate([{ transform: "translateY(" + pitch + "px)" }, { transform: "translateY(0)" }],
      { duration: 220, easing: "cubic-bezier(.2, .7, .2, 1)" });
  }

  // Fold the preparation panel away before the answer starts. Nothing follows the panel while it
  // folds, so no rendered content shifts; the fold time does not scale with replay speed.
  async function foldAway(fold, ctx) {
    if (!fold) return;
    if (!ctx.reduced) {
      fold.classList.add("is-collapsed");
      await pause(TIMING.collapse * state.speed, ctx);
    }
    fold.remove();
  }

  // Build the final inline DOM once, then split its text into words the stream reveals whole, so a
  // half-typed word never appears at a line end and jumps to the next line.
  function revealUnits(root) {
    var units = [];
    (function walk(node) {
      Array.prototype.forEach.call(node.childNodes, function (child) {
        if (child.nodeType === Node.TEXT_NODE) {
          if (!child.nodeValue) return;
          (child.nodeValue.match(/\s*\S+\s*|\s+/g) || []).forEach(function (word) {
            units.push({ node: child, text: word });
          });
          child.nodeValue = "";
        } else if (child.nodeType === Node.ELEMENT_NODE) {
          // A citation run keeps its word, markers, and punctuation together, so it arrives whole
          // rather than growing past the line end and wrapping as a block.
          if (child.classList.contains("cs-deck-cite-run") || child.classList.contains("cs-deck-cite") ||
              child.tagName === "CODE") {
            child.hidden = true;
            units.push({ atom: child, cost: Math.max(2, child.textContent.length) });
          } else {
            walk(child);
          }
        }
      });
    })(root);
    return units;
  }

  function streamParagraph(node, text, spec, ctx, turnId, onReveal) {
    renderInline(node, text, spec, turnId, false);
    followScroll();
    if (ctx.instant || ctx.reduced) {
      if (onReveal) onReveal();
      return ctx.instant ? Promise.resolve() : pause(TIMING.step, ctx);
    }
    if (ctx.token !== state.token) return Promise.reject(CANCELLED);
    var units = revealUnits(node);
    // The caret joins with the first words, so an empty paragraph takes no height beforehand.
    var caret = h("span", { class: "cs-deck-caret", "aria-hidden": "true" });
    return new Promise(function (resolve, reject) {
      var key = {};
      var frameId = 0;
      var index = 0;
      var budget = 0;
      var last = 0;
      var holdUntil = 0;
      function frame(now) {
        if (ctx.token !== state.token) return;
        if (now >= holdUntil) {
          budget += last ? (now - last) * STREAM_CPS * state.speed / 1000 : 0;
          // One fading chunk per text node and frame keeps the DOM small while words arrive softly.
          var chunk = null;
          var chunkNode = null;
          while (index < units.length) {
            var unit = units[index];
            var cost = unit.atom ? unit.cost : unit.text.length;
            if (cost > budget) break;
            budget -= cost;
            index += 1;
            if (unit.atom) {
              unit.atom.hidden = false;
              unit.atom.classList.add("cs-deck-stream-in");
              chunk = null;
              if (index < units.length && SENTENCE_END.test(unit.atom.textContent)) {
                holdUntil = now + SENTENCE_PAUSE / state.speed;
                budget = 0;
                break;
              }
              continue;
            }
            if (!chunk || chunkNode !== unit.node) {
              chunk = h("span", { class: "cs-deck-stream-in" });
              unit.node.parentNode.insertBefore(chunk, unit.node);
              chunkNode = unit.node;
            }
            chunk.textContent += unit.text;
            if (index < units.length && SENTENCE_END.test(unit.text)) {
              holdUntil = now + SENTENCE_PAUSE / state.speed;
              budget = 0;
              break;
            }
          }
        }
        last = now;
        if (index > 0 && !caret.isConnected) node.appendChild(caret);
        if (onReveal && index > 0) {
          onReveal();
          onReveal = null;
        }
        followScroll();
        if (index < units.length) {
          frameId = window.requestAnimationFrame(frame);
          return;
        }
        pending.delete(key);
        caret.remove();
        resolve();
      }
      pending.set(key, { cancel: function () { window.cancelAnimationFrame(frameId); }, reject: reject });
      frameId = window.requestAnimationFrame(frame);
    });
  }

  function setAnswerState(article, value, animate) {
    var head = article.querySelector(".cs-deck-turn-head");
    var badge = head.querySelector(".cs-deck-answer-state");
    if (!value) {
      if (!badge) return;
      if (badge.previousSibling && badge.previousSibling.nodeType === Node.TEXT_NODE) badge.previousSibling.remove();
      badge.remove();
      return;
    }
    if (!badge) {
      badge = h("span");
      head.appendChild(document.createTextNode(" "));
      head.appendChild(badge);
    }
    badge.className = "cs-deck-answer-state is-" + value + (animate ? " cs-deck-fade-in" : "");
    badge.textContent = value === "draft" ? "Draft" : ANSWER_STATE[value];
  }

  // The answer takes the skeleton's place, so the first words appear where the placeholder was.
  function createAnswer(ctx, article) {
    var answer = h("div", { class: "cs-deck-answer" }, [h("div", { class: "cs-deck-prose" })]);
    if (!ctx.instant) setAnswerState(article, "draft", !ctx.reduced);
    article.insertBefore(answer, article.querySelector(":scope > .cs-deck-answer-skeleton"));
    return answer;
  }

  async function streamAnswer(spec, ctx, answer, turnId) {
    if (ctx.instant) return;
    setDeckState("answering");
    var prose = answer.querySelector(".cs-deck-prose");
    var placeholder = answer.parentNode.querySelector(":scope > .cs-deck-answer-skeleton");
    // The skeleton stays until the first words are drawn, so the answer slot is never empty.
    function dropPlaceholder() {
      if (placeholder) placeholder.remove();
      placeholder = null;
    }
    for (var index = 0; index < spec.answer.length; index += 1) {
      var paragraph = spec.answer[index];
      var node = h("p");
      prose.appendChild(node);
      await streamParagraph(node, paragraph.unsupported ? paragraph.text + " " + paragraph.unsupported : paragraph.text, spec, ctx, turnId,
        index === 0 ? dropPlaceholder : null);
      (spec.notes || []).forEach(function (item) {
        if (item.after === index && item.when !== "verify") prose.appendChild(noteElement(item, spec, turnId, false));
      });
      followScroll();
      await pause(TIMING.paragraph, ctx);
    }
  }

  // The pending row is replaced in place by the final action row, so nothing below it jumps.
  async function verifyAnswer(ctx, article) {
    if (ctx.instant) return null;
    var row = h("div", { class: "cs-deck-action-row ds-pending-row" + (ctx.reduced ? "" : " cs-deck-enter") }, [
      h("span", { class: "cs-deck-verification is-pending" }, spaced([
        h("span", { class: "cs-grounding-spinner", "aria-hidden": "true" }),
        h("span", { text: "Checking answer" })
      ]))
    ]);
    article.appendChild(row);
    followScroll();
    await pause(TIMING.verify, ctx);
    return row;
  }

  function finalizeTurn(spec, article, answer, turnId, offset, pendingRow, animate) {
    var prose = answer.querySelector(".cs-deck-prose");
    prose.textContent = "";
    spec.answer.forEach(function (paragraph, index) {
      var node = h("p");
      renderInline(node, paragraph.text, spec, turnId, true);
      prose.appendChild(node);
      (spec.notes || []).forEach(function (item) {
        if (item.after === index) prose.appendChild(noteElement(item, spec, turnId, true));
      });
    });
    setAnswerState(article, spec.answerState, animate);
    var row = actionRow(spec, turnId);
    if (pendingRow && pendingRow.parentNode === article) pendingRow.replaceWith(row);
    else article.appendChild(row);
    article.appendChild(sourcesPanel(spec, turnId));
    // How the answer was produced stays with the answer; follow-ups lead on to the composer.
    var remaining = (spec.followups || []).filter(function (key) { return !state.asked[key]; });
    var arriving = [row, article.appendChild(runRecord(records[turnId]))];
    if (remaining.length) arriving.push(article.appendChild(followupList(remaining)));
    setTurnTime(article, offset + 6, animate);
    if (!animate) return;
    arriving.forEach(function (node, order) {
      node.classList.add("cs-deck-enter");
      if (order) node.setAttribute("data-enter", String(Math.min(order, 3)));
    });
  }

  async function runAgentTurn(spec, ctx, article, turnId, offset) {
    var record = records[turnId];
    var started = performance.now();
    var fold = ctx.instant ? null : await playPreparation(spec, ctx, article);
    await foldAway(fold, ctx);
    var prepared = performance.now() - started;
    var answer = createAnswer(ctx, article);
    await streamAnswer(spec, ctx, answer, turnId);
    var streamed = performance.now() - started;
    var pendingRow = await verifyAnswer(ctx, article);
    if (!ctx.instant) {
      record.observed = { prepared: prepared, streamed: streamed, total: performance.now() - started };
    }
    finalizeTurn(spec, article, answer, turnId, offset, pendingRow, !ctx.instant && !ctx.reduced);
  }

  function beginTurn(spec, article, turnId, offset, ctx, announceProgress) {
    records[turnId] = { spec: spec, offset: offset, turnId: turnId, captured: state.captureTrace };
    state.active = { article: article, spec: spec, turnId: turnId, offset: offset };
    followTurn(article.previousElementSibling);
    if (ctx.instant) return;
    reserveTurn(article);
    setBusy(true);
    setDeckState("preparing");
    if (announceProgress) announce("Bragi is preparing an answer.");
  }

  function settleTurn(spec, ctx, announceResult) {
    if (ctx.token !== state.token) return;
    if (state.active) follow.reveal = state.active.article.querySelector(":scope > .cs-deck-action-row");
    state.active = null;
    setBusy(false);
    setDeckState("settled");
    if (announceResult) announce(spec.announce);
    followScroll();
    if (searchInput.value.trim()) runSearch(false);
  }

  function nextTurnId() {
    state.turnSeq += 1;
    return "ds-turn-" + state.turnSeq;
  }

  function resetConversation() {
    cancelRun();
    if (follow.frame) window.cancelAnimationFrame(follow.frame);
    follow.frame = 0;
    follow.expected = 0;
    followTurn(null);
    hideTip();
    clearSearch();
    state.active = null;
    state.clock = 0;
    state.turnSeq = 0;
    state.asked = {};
    records = {};
    turns.textContent = "";
    note.textContent = "";
    setBusy(false);
  }

  async function playConversation(options) {
    if (ADAPTIVE) return playInvestigationConversation(options);
    resetConversation();
    var spec = SCENARIOS[state.scenario];
    var ctx = newContext(options.instant);
    titleNode.textContent = CONVERSATION_TITLE;
    readiness.textContent = "";
    readiness.appendChild(readinessStrip(ctx.instant ? state.scenario : "loading"));
    turns.appendChild(userTurn(QUESTION, 0));
    var turnId = nextTurnId();
    var article = agentArticle(turnId);
    turns.appendChild(article);
    state.stuck = !options.scrollTop;
    beginTurn(spec, article, turnId, 0, ctx, options.announce);
    try {
      if (!ctx.instant) {
        pause(TIMING.readiness, ctx).then(function () {
          readiness.textContent = "";
          readiness.appendChild(readinessStrip(state.scenario, !ctx.reduced));
        }, ignoreCancel);
      }
      await runAgentTurn(spec, ctx, article, turnId, 0);
      settleTurn(spec, ctx, options.announce);
      if (options.scrollTop) {
        moveScroll(0);
        updateJump();
      }
    } catch (error) {
      ignoreCancel(error);
    }
  }

  // A chosen follow-up folds away instead of vanishing, so the rows below it glide up.
  function retire(node) {
    if (state.reduced || typeof node.animate !== "function") {
      node.remove();
      return;
    }
    node.inert = true;
    node.style.overflow = "hidden";
    var height = node.getBoundingClientRect().height;
    node.animate([{ height: height + "px", opacity: 1 }, { height: "0px", opacity: 0, marginTop: "0px" }],
      { duration: 200, easing: "cubic-bezier(.2, .7, .2, 1)" }).finished.then(function () { node.remove(); }, function () { node.remove(); });
  }

  async function askFollowUp(button) {
    if (state.busy || button.getAttribute("aria-disabled") === "true") return;
    var key = button.getAttribute("data-followup");
    var spec = FOLLOWUPS[key];
    if (!spec) return;
    state.asked[key] = true;
    var item = button.closest("li");
    var list = item.parentElement;
    var neighbor = item.nextElementSibling || item.previousElementSibling;
    retire(list.children.length === 1 ? list : item);
    cancelRun();
    hideTip();
    clearSearch();
    state.clock += 40;
    var offset = state.clock;
    turns.appendChild(userTurn(spec.question, offset));
    var turnId = nextTurnId();
    var article = agentArticle(turnId);
    turns.appendChild(article);
    state.stuck = true;
    var ctx = newContext(false);
    beginTurn(spec, article, turnId, offset, ctx, true);
    (neighbor ? neighbor.querySelector("button") : input).focus({ preventScroll: true });
    followScroll();
    try {
      await runAgentTurn(spec, ctx, article, turnId, offset);
      settleTurn(spec, ctx, true);
    } catch (error) {
      ignoreCancel(error);
    }
  }

  async function regenerate(article) {
    var record = article && records[article.id];
    if (state.busy || !record) return;
    cancelRun();
    hideTip();
    clearSearch();
    Array.prototype.slice.call(article.children).forEach(function (child) {
      if (!child.classList.contains("cs-deck-turn-head")) child.remove();
    });
    setAnswerState(article, null);
    article.querySelectorAll(".cs-deck-head-time").forEach(function (node) { node.remove(); });
    var ctx = newContext(false);
    var fixture = record.fixture;
    state.stuck = false;
    beginTurn(record.spec, article, article.id, record.offset, ctx, true);
    if (fixture) records[article.id].fixture = fixture;
    input.focus({ preventScroll: true });
    article.scrollIntoView({ block: "nearest", behavior: state.reduced ? "auto" : "smooth" });
    try {
      if (fixture) await runInvestigationTurn(fixture, ctx, article, article.id, record.offset);
      else await runAgentTurn(record.spec, ctx, article, article.id, record.offset);
      settleTurn(record.spec, ctx, true);
    } catch (error) {
      ignoreCancel(error);
    }
  }

  // A stop can land mid-paragraph: drop citations and code the stream never revealed, then any
  // paragraph left without visible text, so search and the stopped note see only shown words.
  function pruneUnrevealed(prose) {
    prose.querySelectorAll("[hidden]").forEach(function (node) { node.remove(); });
    prose.querySelectorAll("p").forEach(function (node) {
      if (!node.textContent.trim()) node.remove();
    });
  }

  function stopTurn() {
    var active = state.active;
    if (!state.busy || !active) return;
    cancelRun();
    var article = active.article;
    article.querySelectorAll(".cs-deck-collapse, .cs-grounding-panel, .cs-deck-answer-skeleton, .ds-pending-row, .cs-deck-caret").forEach(function (node) {
      node.remove();
    });
    stopInvestigation(article);
    var answer = article.querySelector(".cs-deck-answer");
    if (!answer) {
      answer = h("div", { class: "cs-deck-answer" }, [h("div", { class: "cs-deck-prose" })]);
      article.appendChild(answer);
    }
    var prose = answer.querySelector(".cs-deck-prose");
    pruneUnrevealed(prose);
    var hadText = prose.textContent.trim().length > 0;
    setAnswerState(article, "stopped");
    prose.appendChild(noteElement({
      tone: "attention",
      label: "Stopped",
      text: hadText ? "this partial answer was not verified. Nothing was changed." : "no answer was composed. Nothing was changed."
    }, active.spec, active.turnId, false));
    article.appendChild(h("div", { class: "cs-deck-action-row" + (state.reduced ? "" : " cs-deck-enter") }, [
      h("button", { type: "button", class: "cs-deck-tool", "data-action": "regenerate", text: "Regenerate" })
    ]));
    setTurnTime(article, active.offset + 6, !state.reduced);
    if (readiness.querySelector(".is-loading")) {
      readiness.textContent = "";
      readiness.appendChild(readinessStrip(state.scenario));
    }
    state.active = null;
    setBusy(false);
    setDeckState("stopped");
    announce("Stopped. Nothing was changed.");
    input.focus({ preventScroll: true });
    if (searchInput.value.trim()) runSearch(false);
  }

  function newConversation() {
    resetConversation();
    if (readiness.querySelector(".is-loading")) {
      readiness.textContent = "";
      readiness.appendChild(readinessStrip(state.scenario));
    }
    titleNode.textContent = "New conversation";
    turns.appendChild(h("section", { class: "ds-intro" + (state.reduced ? "" : " cs-deck-enter"), "aria-labelledby": "ds-intro-title" }, [
      h("h3", { class: "ds-intro-title", id: "ds-intro-title", text: "Ask about " + ROUTE }),
      h("p", { class: "ds-intro-lead", text: INTRO_LEAD }),
      h("button", { type: "button", class: "ds-intro-card", "data-action": "suggest" }, spaced([
        h("span", { class: "ds-intro-card-label", text: "Suggested for this screen" }),
        h("span", { class: "ds-intro-card-text", text: QUESTION })
      ]))
    ]));
    setDeckState("empty");
    updateJump();
    announce("New conversation.");
    turns.querySelector(".ds-intro-card").focus();
  }

  var stateBeforeClose = "settled";

  function setOpen(open) {
    if (!open) {
      if (state.busy) stopTurn();
      hideTip();
      stateBeforeClose = state.deckState;
    }
    [header, readiness, bodyGrid, composer].forEach(function (node) { node.hidden = !open; });
    closedPanel.hidden = open;
    workspace.setAttribute("data-open", open ? "true" : "false");
    setDeckState(open ? stateBeforeClose : "closed");
    (open ? input : reopen).focus();
  }

  // ---------- Search ----------
  var search = { hits: [], active: -1, timer: 0 };

  function clearHighlights() {
    turns.querySelectorAll("mark.cs-deck-search-hit").forEach(function (mark) {
      var parent = mark.parentNode;
      parent.replaceChild(document.createTextNode(mark.textContent), mark);
      parent.normalize();
    });
  }

  function highlight(root, query) {
    var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode: function (node) {
        return node.parentElement && node.parentElement.closest(".cs-deck-cite, .cs-deck-evidence-note-mark, mark, [hidden]")
          ? NodeFilter.FILTER_REJECT
          : NodeFilter.FILTER_ACCEPT;
      }
    });
    var nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    nodes.forEach(function (node) {
      var text = node.nodeValue;
      var lower = text.toLowerCase();
      var index = lower.indexOf(query);
      if (index < 0) return;
      var fragment = document.createDocumentFragment();
      var last = 0;
      while (index >= 0) {
        fragment.appendChild(document.createTextNode(text.slice(last, index)));
        fragment.appendChild(h("mark", { class: "cs-deck-search-hit", text: text.slice(index, index + query.length) }));
        last = index + query.length;
        index = lower.indexOf(query, last);
      }
      fragment.appendChild(document.createTextNode(text.slice(last)));
      node.parentNode.replaceChild(fragment, node);
    });
  }

  function updateSearchUi(scroll) {
    search.hits.forEach(function (mark, index) { mark.classList.toggle("is-active", index === search.active); });
    var query = searchInput.value.trim();
    searchCount.textContent = query.length >= 2 && !state.busy
      ? (search.hits.length ? (search.active + 1) + "/" + search.hits.length : "0/0")
      : "";
    searchPrev.disabled = search.hits.length === 0;
    searchNext.disabled = search.hits.length === 0;
    var active = search.hits[search.active];
    if (scroll && active) {
      active.scrollIntoView({ block: "nearest", behavior: state.reduced ? "auto" : "smooth" });
      updateJump();
    }
  }

  function runSearch(scroll) {
    clearHighlights();
    var query = searchInput.value.trim().toLowerCase();
    search.hits = [];
    search.active = -1;
    if (query.length >= 2 && !state.busy) {
      turns.querySelectorAll(".cs-deck-user-line, .cs-deck-prose").forEach(function (root) { highlight(root, query); });
      search.hits = Array.prototype.slice.call(turns.querySelectorAll("mark.cs-deck-search-hit"));
      search.active = search.hits.length ? 0 : -1;
    }
    updateSearchUi(scroll);
  }

  function clearSearch() {
    clearHighlights();
    search.hits = [];
    search.active = -1;
    updateSearchUi(false);
  }

  function moveSearch(step) {
    if (!search.hits.length) return;
    search.active = (search.active + step + search.hits.length) % search.hits.length;
    updateSearchUi(true);
  }

  // ---------- Tooltip: one fixed node in body so containers never clip or offset it. ----------
  var tip = h("div", { class: "ds-tooltip", id: "ds-tooltip", role: "tooltip", hidden: true });
  document.body.appendChild(tip);
  var tipOwner = null;
  var tipTimer = 0;

  function showTip(target) {
    var text = target.getAttribute("data-tip");
    if (!text) return;
    if (tipOwner && tipOwner !== target) tipOwner.removeAttribute("aria-describedby");
    tipOwner = target;
    tip.textContent = text;
    tip.hidden = false;
    var rect = target.getBoundingClientRect();
    var width = tip.offsetWidth;
    var height = tip.offsetHeight;
    var left = Math.min(Math.max(8, rect.left + rect.width / 2 - width / 2), window.innerWidth - width - 8);
    var top = rect.top - height - 8;
    if (top < 8) top = rect.bottom + 8;
    tip.style.left = Math.round(left) + "px";
    tip.style.top = Math.round(top) + "px";
    var name = target.getAttribute("aria-label") || target.textContent || "";
    if (name.indexOf(text) < 0) target.setAttribute("aria-describedby", "ds-tooltip");
  }

  function hideTip() {
    window.clearTimeout(tipTimer);
    if (tipOwner) tipOwner.removeAttribute("aria-describedby");
    tipOwner = null;
    tip.hidden = true;
  }

  // ---------- Reply actions ----------
  function setSources(article, open) {
    var button = article.querySelector("[data-action='sources']");
    var panel = article.querySelector(".cs-deck-sources");
    if (!button || !panel) return;
    button.setAttribute("aria-expanded", open ? "true" : "false");
    panel.hidden = !open;
    if (!open) panel.querySelectorAll(".is-target").forEach(function (node) { node.classList.remove("is-target"); });
  }

  function revealSource(cite) {
    var article = cite.closest(".cs-deck-agent-turn");
    var target = document.getElementById(cite.getAttribute("href").slice(1));
    if (!article || !target) return;
    setSources(article, true);
    article.querySelectorAll(".cs-deck-source.is-target").forEach(function (node) { node.classList.remove("is-target"); });
    target.classList.add("is-target");
    hideTip();
    target.focus({ preventScroll: true });
    target.scrollIntoView({ block: "nearest", behavior: state.reduced ? "auto" : "smooth" });
    updateJump();
  }

  function plainAnswer(spec) {
    return spec.answer.map(function (paragraph) {
      return paragraph.text.replace(/\{([a-zA-Z]+)\}/g, function (marker, key) {
        return " [" + (spec.sources.indexOf(key) + 1) + "]";
      }).replace(/`/g, "");
    }).join("\n\n");
  }

  function copyReply(button) {
    var article = button.closest(".cs-deck-agent-turn");
    var record = article && records[article.id];
    if (!record) return;
    var finish = function (label) {
      var copied = label === "Copied";
      button.setAttribute("data-tip", label);
      if (copied) button.replaceChildren(icon("check"));
      button.classList.toggle("is-done", copied);
      showTip(button);
      announce(label + ".");
      window.setTimeout(function () {
        button.setAttribute("data-tip", "Copy reply");
        button.classList.remove("is-done");
        if (copied) button.replaceChildren(icon("copy"));
        if (tipOwner === button) hideTip();
      }, 1500);
    };
    if (!navigator.clipboard || !window.isSecureContext) {
      finish("Copy is unavailable in this preview");
      return;
    }
    navigator.clipboard.writeText(record.fixture ? plainInvestigation(record.fixture) : plainAnswer(record.spec)).then(function () {
      finish("Copied");
    }, function () {
      finish("Copy is unavailable in this preview");
    });
  }

  function setPressed(attribute, value) {
    document.querySelectorAll("button[" + attribute + "]").forEach(function (button) {
      button.setAttribute("aria-pressed", button.getAttribute(attribute) === value ? "true" : "false");
    });
  }

  function setScreenAttached(attached) {
    state.screenAttached = attached;
    contextChip.classList.toggle("is-empty", !attached);
    contextChip.setAttribute("aria-label", attached ? "Remove reference screen: " + ROUTE : "Add current screen");
    contextChip.setAttribute("data-tip", attached
      ? "Exclude this screen from future questions. Messages already sent stay in the conversation."
      : "Include the current screen in this conversation. You can remove it before sending.");
    contextChip.textContent = "";
    contextChip.appendChild(h("span", null, attached
      ? [h("span", { class: "cs-deck-context-prefix", text: "Reference screen: " }), ROUTE]
      : ["Add current screen"]));
    contextChip.appendChild(h("span", { "aria-hidden": "true", text: attached ? "\u00d7" : "+" }));
    input.setAttribute("aria-label", attached ? "Ask anything about " + ROUTE + ", or type / for commands" : "Ask anything...");
    if (tipOwner === contextChip) showTip(contextChip);
  }

  function resizeInput() {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight + 2, 120) + "px";
  }

  // ---------- Adaptive investigation: a procedural answer built from typed read waves ----------
  // The study reads the synthetic trajectories in fixtures/adaptive/, the same files the Console's
  // contract tests parse. Density comes from the typed trajectory, never from answer prose.
  var fixtureCache = {};
  var PLAIN_SPEC = { sources: [] };
  var FRESHNESS_TEXT = { fresh: "Current", stale: "Stale", superseded: "Superseded" };
  var AUTHORIZATION_TEXT = { allowed: "Allowed", denied: "Denied", unavailable: "Unavailable" };
  var TONE_STATE = { verified: "completed", attention: "degraded", failure: "unverified", pending: "not_observed" };
  var INVESTIGATION_ANSWER_STATE = { partial: "partial", unverified: "unverified" };
  var REPLAY_MS = { minimum: 320, maximum: 1300, scale: 1.6, deadline: 1200 };

  function loadFixture(name) {
    if (!fixtureCache[name]) {
      fixtureCache[name] = fetch("fixtures/adaptive/" + name + ".json", { cache: "no-cache" }).then(function (response) {
        if (!response.ok) throw new Error("Fixture " + name + " returned " + response.status);
        return response.json();
      });
      fixtureCache[name].catch(function () { delete fixtureCache[name]; });
    }
    return fixtureCache[name];
  }

  function investigationSpec(fixture) {
    var verification = fixture.answer.verification;
    return {
      question: fixture.question,
      sources: [],
      stages: [],
      answer: [],
      followups: [],
      verification: verification,
      announce: "Investigation answered. " + verification.label + ": " + verification.detail + "."
    };
  }

  function activityPresentation(fixture, activity) {
    return fixture.presentation[activity.activity_id] || { operation: activity.authority || "read", authorization: "allowed" };
  }

  function activityKind(activity) {
    if (!activity.execution) return "Comparison";
    var prefix = activity.execution.tool.split(".")[0];
    return prefix.charAt(0).toUpperCase() + prefix.slice(1);
  }

  function activityOutcome(activity, presentation) {
    if (presentation.authorization === "denied") return { status: "denied", text: "Denied" };
    if (activity.status === "completed") return { status: "completed", text: formatMs(activity.execution ? activity.execution.duration_ms : 40) };
    if (activity.status === "failed") return { status: "failed", text: activity.execution && activity.execution.duration_ms >= 5000 ? "Timed out" : "Failed" };
    return { status: "unavailable", text: "Not read" };
  }

  // Reads replay a little slower than they ran so parallel lanes stay legible.
  function replayMs(activity) {
    if (activity.status === "unavailable" && (!activity.execution || activity.execution.duration_ms === 0)) return REPLAY_MS.deadline;
    var ms = activity.execution ? activity.execution.duration_ms : 200;
    return Math.max(REPLAY_MS.minimum, Math.min(REPLAY_MS.maximum, ms * REPLAY_MS.scale));
  }

  function planLead(fixture) {
    return h("p", { class: "cs-deck-plan-lead" }, spaced([
      h("span", { class: "cs-deck-plan-label", text: "Plan" }),
      h("span", { text: fixture.plan.summary })
    ]));
  }

  // An applied preference is a receipt: context for presentation, never evidence or instructions.
  function contextReceipt(receipts) {
    if (!receipts || !receipts.length) return null;
    var current = receipts.filter(function (receipt) { return receipt.freshness === "fresh"; });
    return h("details", { class: "cs-deck-context-receipt" }, [
      h("summary", { class: "cs-deck-context-receipt-summary" }, spaced([
        h("span", { class: "cs-deck-context-receipt-label", text: "Context applied" }),
        h("span", { class: "cs-deck-context-receipt-value", text: current.length
          ? current.map(function (receipt) { return receipt.label; }).join(", ")
          : "No current preference" }),
        h("span", { class: "cs-run-chevron", "aria-hidden": "true" })
      ])),
      h("div", { class: "cs-deck-context-receipt-body" }, [
        h("p", { class: "cs-deck-context-receipt-note", text: "Context only: it shapes the presentation and is not evidence or instructions." }),
        h("ul", { class: "cs-deck-context-receipt-list" }, receipts.map(function (receipt) {
          return h("li", { "data-freshness": receipt.freshness }, spaced([
            h("strong", { text: receipt.label }),
            h("span", { class: "cs-deck-context-receipt-freshness", text: FRESHNESS_TEXT[receipt.freshness] }),
            h("span", { text: "Observed " + clockLabel(receipt.observed_at) }),
            h("code", { text: receipt.digest.slice(0, 12) })
          ]));
        }))
      ])
    ]);
  }

  function seconds(ms) {
    return (ms / 1000).toFixed(1).replace(/\.0$/, "") + " s";
  }

  function thousands(count) {
    return (count / 1000).toFixed(1).replace(/\.0$/, "") + "k";
  }

  // Policy limits show while the turn runs; the server's used-of-maximum telemetry replaces them
  // once the turn ends, so the header never implies a live meter the contract does not stream.
  function limitsText(budget, settled) {
    var limits = budget || { model_calls: { maximum: 5 }, tokens: { maximum: 48000 }, elapsed_ms: { maximum: 60000 } };
    if (!settled || !budget) {
      return "Limits: " + limits.model_calls.maximum + " model calls, " + thousands(limits.tokens.maximum) + " tokens, " +
        seconds(limits.elapsed_ms.maximum);
    }
    var used = budget.model_calls.used + " of " + budget.model_calls.maximum + " model calls, " +
      thousands(budget.tokens.used) + " of " + thousands(budget.tokens.maximum) + " tokens, " +
      seconds(budget.elapsed_ms.used) + " of " + seconds(budget.elapsed_ms.maximum);
    return budget.exhaustion_reason === "deadline" ? "Turn deadline reached: " + used : "Used: " + used;
  }

  function waveItem(title, label, turnId, index) {
    var bodyId = turnId + "-wave-" + index;
    var mark = h("span", { class: "cs-deck-wave-mark", "aria-hidden": "true", text: title === "Compare" ? "=" : String(index) });
    var meta = h("span", { class: "cs-deck-wave-meta", text: "Queued" });
    var head = h("button", {
      type: "button",
      class: "cs-deck-wave-head",
      "aria-expanded": "false",
      "aria-controls": bodyId,
      "data-action": "wave-toggle"
    }, spaced([
      mark,
      h("span", { class: "cs-deck-wave-title", text: title }),
      h("span", { class: "cs-deck-wave-label", text: label }),
      meta,
      h("span", { class: "cs-run-chevron", "aria-hidden": "true" })
    ]));
    var activities = h("ol", { class: "cs-deck-activities" });
    var body = h("div", { class: "cs-deck-wave-body", id: bodyId, hidden: true }, [activities]);
    var node = h("li", { class: "cs-deck-wave", "data-state": "pending" }, [head, body]);
    return { node: node, head: head, mark: mark, meta: meta, activities: activities, body: body, items: [] };
  }

  function setWaveState(wave, value, text) {
    wave.node.setAttribute("data-state", value);
    wave.meta.textContent = text;
    if (value === "running") {
      wave.mark.textContent = "";
      wave.mark.appendChild(h("span", { class: "cs-grounding-spinner" }));
    } else if (value !== "pending") {
      wave.mark.textContent = value === "done" ? CHECK : "!";
    }
  }

  // A new fold or unfold cancels the one in flight and starts from the current height, so a quick
  // second click never leaves the body hidden under an expanded header.
  var waveMotion = new WeakMap();

  function showWave(wave, expanded, animate) {
    var body = wave.body;
    var from = body.hidden ? 0 : body.getBoundingClientRect().height;
    var running = waveMotion.get(body);
    if (running) running.cancel();
    wave.head.setAttribute("aria-expanded", expanded ? "true" : "false");
    body.style.overflow = "";
    if (!animate || state.reduced || typeof body.animate !== "function" || (!expanded && body.hidden)) {
      body.hidden = !expanded;
      return;
    }
    body.hidden = false;
    var to = expanded ? body.getBoundingClientRect().height : 0;
    body.style.overflow = "hidden";
    var motion = body.animate([{ height: from + "px", opacity: expanded ? 0.4 : 1 }, { height: to + "px", opacity: expanded ? 1 : 0.4 }],
      { duration: 220, easing: "cubic-bezier(.2, .7, .2, 1)" });
    waveMotion.set(body, motion);
    motion.finished.then(function () {
      waveMotion.delete(body);
      body.style.overflow = "";
      if (!expanded) body.hidden = true;
    }, function () {});
  }

  function activityItem(fixture, activity) {
    var presentation = activityPresentation(fixture, activity);
    var mark = h("span", { class: "cs-deck-activity-mark", "aria-hidden": "true" });
    var status = h("span", { class: "cs-deck-activity-status" });
    var body = h("div", { class: "cs-deck-activity-detail" }, [
      h("p", { class: "cs-deck-activity-note", text: "Details appear when this read ends." })
    ]);
    var node = h("li", { class: "cs-deck-activity", "data-status": "pending" }, [h("details", null, [
      h("summary", { class: "cs-deck-activity-summary" }, spaced([
        mark,
        h("span", { class: "cs-deck-activity-label", text: activity.label }),
        h("span", { class: "cs-deck-activity-kind", text: activityKind(activity) }),
        status,
        h("span", { class: "cs-run-chevron", "aria-hidden": "true" })
      ])),
      body
    ])]);
    return { node: node, mark: mark, status: status, body: body, activity: activity, presentation: presentation };
  }

  function setActivityRunning(item) {
    item.node.setAttribute("data-status", "running");
    item.mark.textContent = "";
    item.mark.appendChild(h("span", { class: "cs-grounding-spinner" }));
    item.status.textContent = "Running";
  }

  // Details render once the read ends, so a running card never shows an output early.
  function finishActivity(item, animate) {
    var outcome = activityOutcome(item.activity, item.presentation);
    item.node.setAttribute("data-status", outcome.status);
    item.mark.textContent = outcome.status === "completed" ? CHECK : "!";
    if (animate) item.mark.classList.add("cs-deck-pop");
    item.status.textContent = outcome.text;
    fillActivityDetail(item);
    return outcome;
  }

  function fillActivityDetail(item) {
    var activity = item.activity;
    var presentation = item.presentation;
    var execution = activity.execution;
    var target = execution && execution.target;
    item.body.textContent = "";
    if (activity.detail) item.body.appendChild(h("p", { class: "cs-deck-activity-note", text: activity.detail }));
    var facts = [["Operation", presentation.operation || activity.authority || "read"],
      ["Authorization", AUTHORIZATION_TEXT[presentation.authorization] || "Allowed"],
      ["Evidence authority", presentation.evidence_authority || "none"],
      ["Execution authority", "None"]];
    if (target) facts.push(["Target", [target.service, target.component, target.operation].join(" / ")]);
    if (execution) facts.push(["Tool", execution.tool]);
    item.body.appendChild(factList(facts));
    if (!execution) return;
    item.body.appendChild(payload("Typed call", execution.command));
    if (presentation.provider) item.body.appendChild(payload("Provider equivalent", presentation.provider));
    if (execution.output) item.body.appendChild(payload("Observed output", execution.output));
  }

  function milestoneItem(milestone, animate) {
    return h("li", { class: "cs-deck-milestone" + (animate ? " cs-deck-enter" : "") }, spaced([
      h("span", { class: "cs-deck-milestone-label", text: "Progress" }),
      h("span", { class: "cs-deck-milestone-text", text: milestone.text }),
      h("time", { class: "cs-deck-milestone-time", datetime: milestone.recorded_at, text: clockLabel(milestone.recorded_at) })
    ]));
  }

  function investigationFrame(fixture, turnId) {
    var detail = fixture.trajectory_detail;
    var waves = fixture.plan.waves.map(function (wave, index) {
      var entry = waveItem("Wave " + (index + 1), wave.label, turnId, index + 1);
      entry.activityData = detail.activities.filter(function (activity) {
        return activity.branch_id && wave.branch_ids.indexOf(activity.branch_id) >= 0;
      });
      return entry;
    });
    var reductions = detail.activities.filter(function (activity) { return !activity.branch_id; });
    if (reductions.length) {
      var subject = reductions[0].label.replace(/^Compare\s+/i, "");
      var compare = waveItem("Compare", subject.charAt(0).toUpperCase() + subject.slice(1), turnId, waves.length + 1);
      compare.activityData = reductions;
      compare.compare = true;
      waves.push(compare);
    }
    var status = h("span", { class: "cs-deck-investigation-status", text: "Planned: " + fixture.plan.waves.length + " waves" });
    var limits = h("span", { class: "cs-deck-investigation-limits", text: limitsText(detail.turn_budget, false) });
    var list = h("ol", { class: "cs-deck-waves" }, waves.map(function (wave) { return wave.node; }));
    var block = h("section", { class: "cs-deck-investigation", "aria-label": "Investigation" }, [
      h("header", { class: "cs-deck-investigation-head" }, spaced([
        h("span", { class: "cs-deck-investigation-title", text: "Investigation" }),
        status,
        limits
      ])),
      list
    ]);
    return { block: block, status: status, limits: limits, list: list, waves: waves };
  }

  function waveSummary(wave, outcomes) {
    var done = outcomes.filter(function (outcome) { return outcome.status === "completed"; }).length;
    var total = outcomes.length;
    if (wave.compare) return done === total ? "Completed" : "Not completed";
    if (done === total) return total + (total === 1 ? " read completed" : " reads completed");
    return done + " of " + total + " completed";
  }

  async function playWaves(parts, fixture, ctx) {
    var milestones = fixture.trajectory_detail.milestones.slice();
    var planned = fixture.plan.waves.length;
    for (var index = 0; index < parts.waves.length; index += 1) {
      var wave = parts.waves[index];
      parts.status.textContent = wave.compare ? "Comparing results" : "Wave " + (index + 1) + " of " + planned;
      wave.items = wave.activityData.map(function (activity) { return activityItem(fixture, activity); });
      wave.items.forEach(function (item) {
        wave.activities.appendChild(item.node);
        setActivityRunning(item);
      });
      setWaveState(wave, "running", wave.items.length > 1 ? wave.items.length + " reads in parallel" : "Running");
      showWave(wave, true, true);
      followScroll();
      var outcomes = await Promise.all(wave.items.map(function (item) {
        return pause(replayMs(item.activity), ctx).then(function () {
          var outcome = finishActivity(item, !ctx.reduced);
          followScroll();
          return outcome;
        });
      }));
      var trouble = outcomes.some(function (outcome) { return outcome.status !== "completed"; });
      setWaveState(wave, trouble ? "attention" : "done", waveSummary(wave, outcomes));
      await pause(180, ctx);
      showWave(wave, false, true);
      var milestone = wave.compare ? null : milestones.shift();
      if (milestone) {
        parts.list.insertBefore(milestoneItem(milestone, !ctx.reduced), wave.node.nextSibling);
        followScroll();
        await pause(260, ctx);
      }
    }
    milestones.forEach(function (milestone) { parts.list.appendChild(milestoneItem(milestone, !ctx.reduced)); });
    settleInvestigationHead(parts, fixture);
  }

  function settleWaves(parts, fixture) {
    var milestones = fixture.trajectory_detail.milestones.slice();
    parts.waves.forEach(function (wave) {
      wave.items = wave.activityData.map(function (activity) { return activityItem(fixture, activity); });
      var outcomes = wave.items.map(function (item) {
        wave.activities.appendChild(item.node);
        return finishActivity(item, false);
      });
      var trouble = outcomes.some(function (outcome) { return outcome.status !== "completed"; });
      setWaveState(wave, trouble ? "attention" : "done", waveSummary(wave, outcomes));
      var milestone = wave.compare ? null : milestones.shift();
      if (milestone) parts.list.insertBefore(milestoneItem(milestone, false), wave.node.nextSibling);
    });
    milestones.forEach(function (milestone) { parts.list.appendChild(milestoneItem(milestone, false)); });
    settleInvestigationHead(parts, fixture);
  }

  function settleInvestigationHead(parts, fixture) {
    var detail = fixture.trajectory_detail;
    var reads = detail.activities.filter(function (activity) { return activity.execution; });
    var completed = reads.filter(function (activity) { return activity.status === "completed"; }).length;
    parts.status.textContent = fixture.plan.waves.length + (fixture.plan.waves.length === 1 ? " wave, " : " waves, ") +
      completed + " of " + reads.length + " reads completed";
    parts.block.setAttribute("data-settled", "");
  }

  function answerBlocks(fixture, turnId, animate) {
    var answer = fixture.answer;
    var blocks = [];
    if (answer.facts.length) {
      blocks.push(h("dl", { class: "cs-deck-answer-facts" }, answer.facts.map(function (pair) {
        return h("div", null, [h("dt", { text: pair[0] }), h("dd", { text: pair[1] })]);
      })));
    }
    if (answer.checks.length) {
      blocks.push(h("ul", { class: "cs-deck-answer-checks" }, answer.checks.map(function (text) { return h("li", { text: text }); })));
    }
    answer.limitations.forEach(function (text) {
      blocks.push(noteElement({ tone: answer.state === "unverified" ? "conflict" : "attention", label: "Limit", text: text },
        PLAIN_SPEC, turnId, false));
    });
    if (answer.note) blocks.push(h("p", { class: "cs-deck-answer-note", text: answer.note }));
    if (answer.next_step) {
      blocks.push(h("p", { class: "cs-deck-answer-next" }, [h("strong", { text: "Next safe step: " }), answer.next_step]));
    }
    if (animate) blocks.forEach(function (block, order) {
      block.classList.add("cs-deck-enter");
      if (order) block.setAttribute("data-enter", String(Math.min(order, 3)));
    });
    return blocks;
  }

  async function streamInvestigationAnswer(fixture, ctx, answer, turnId) {
    if (ctx.instant) return;
    setDeckState("answering");
    var prose = answer.querySelector(".cs-deck-prose");
    var lead = h("p");
    prose.appendChild(lead);
    await streamParagraph(lead, fixture.answer.lead, PLAIN_SPEC, ctx, turnId, null);
    var blocks = answerBlocks(fixture, turnId, !ctx.reduced);
    for (var index = 0; index < blocks.length; index += 1) {
      prose.appendChild(blocks[index]);
      followScroll();
      await pause(TIMING.paragraph * 2, ctx);
    }
  }

  function investigationActionRow(fixture) {
    var verification = fixture.answer.verification;
    var children = [
      h("span", { class: "cs-deck-verification is-" + verification.tone }, spaced([
        h("span", { class: "cs-deck-verification-mark", "aria-hidden": "true", text: verification.mark }),
        h("span", { text: verification.label }),
        h("span", { class: "cs-deck-verification-detail", text: verification.detail })
      ]))
    ];
    fixture.affordances.forEach(function (affordance) {
      if (affordance.kind !== "draft_remediation") return;
      children.push(h("button", { type: "button", class: "cs-deck-affordance", "data-action": "draft-remediation",
        "data-tip": "Starts a separate request that rechecks scope and policy", text: affordance.label }));
    });
    children.push(h("span", { class: "cs-deck-tools" }, [
      h("button", { type: "button", class: "cs-deck-tool cs-deck-tool-icon", "aria-label": "Copy reply", "data-tip": "Copy reply", "data-action": "copy" }, [icon("copy")]),
      h("button", { type: "button", class: "cs-deck-tool cs-deck-tool-icon", "aria-label": "Regenerate", "data-tip": "Ask this question again", "data-action": "regenerate" }, [icon("regenerate")]),
      h("a", { class: "cs-deck-tool cs-deck-tool-icon", href: "conversation-assurance.html", "aria-label": "Review answer quality", "data-tip": "Review answer quality" }, [icon("review")])
    ]));
    return h("div", { class: "cs-deck-action-row" }, children);
  }

  function previewFollowups(texts) {
    return h("ul", { class: "cs-deck-followups", "aria-label": "Suggested follow-ups" }, texts.map(function (text) {
      return h("li", null, [h("button", { type: "button", class: "cs-deck-followup", "data-followup-text": text, "aria-disabled": "false", text: text })]);
    }));
  }

  function finalizeInvestigation(fixture, article, answer, turnId, offset, pendingRow, animate) {
    // The budget is end-of-turn telemetry, so it replaces the policy limits only once the answer settles.
    var limits = article.querySelector(".cs-deck-investigation-limits");
    if (limits) limits.textContent = limitsText(fixture.trajectory_detail.turn_budget, true);
    var prose = answer.querySelector(".cs-deck-prose");
    prose.textContent = "";
    prose.appendChild(h("p", { text: fixture.answer.lead }));
    answerBlocks(fixture, turnId, false).forEach(function (block) { prose.appendChild(block); });
    setAnswerState(article, INVESTIGATION_ANSWER_STATE[fixture.answer.state] || null, animate);
    var row = investigationActionRow(fixture);
    if (pendingRow && pendingRow.parentNode === article) pendingRow.replaceWith(row);
    else article.appendChild(row);
    var arriving = [row, article.appendChild(runRecord(records[turnId]))];
    if (fixture.followups.length) arriving.push(article.appendChild(previewFollowups(fixture.followups)));
    setTurnTime(article, offset + 6, animate);
    if (!animate) return;
    arriving.forEach(function (node, order) {
      node.classList.add("cs-deck-enter");
      if (order) node.setAttribute("data-enter", String(Math.min(order, 3)));
    });
  }

  async function runInvestigationTurn(fixture, ctx, article, turnId, offset) {
    var record = records[turnId];
    var started = performance.now();
    var parts = investigationFrame(fixture, turnId);
    article.appendChild(planLead(fixture));
    var receipt = contextReceipt(fixture.trajectory_detail.context_receipts);
    if (receipt) article.appendChild(receipt);
    if (!ctx.instant && !ctx.reduced) parts.block.classList.add("cs-deck-enter");
    article.appendChild(parts.block);
    followScroll();
    if (ctx.instant) settleWaves(parts, fixture);
    else await playWaves(parts, fixture, ctx);
    var prepared = performance.now() - started;
    var answer = createAnswer(ctx, article);
    await streamInvestigationAnswer(fixture, ctx, answer, turnId);
    var streamed = performance.now() - started;
    var pendingRow = await verifyAnswer(ctx, article);
    if (!ctx.instant) record.observed = { prepared: prepared, streamed: streamed, total: performance.now() - started };
    finalizeInvestigation(fixture, article, answer, turnId, offset, pendingRow, !ctx.instant && !ctx.reduced);
  }

  async function playInvestigationConversation(options) {
    resetConversation();
    var ctx = newContext(options.instant);
    var name = state.scenario;
    titleNode.textContent = CONVERSATION_TITLE;
    readiness.textContent = "";
    readiness.appendChild(readinessStrip(ctx.instant ? "grounded" : "loading"));
    var fixture;
    try {
      fixture = await loadFixture(name);
    } catch (error) {
      if (ctx.token !== state.token) return;
      turns.appendChild(h("p", { class: "ds-composer-note", role: "status", text: "The " + name + " fixture could not be loaded." }));
      readiness.textContent = "";
      readiness.appendChild(readinessStrip("grounded"));
      setDeckState("settled");
      return;
    }
    if (ctx.token !== state.token) return;
    if (workspace.getAttribute("data-open") === "false") {
      ctx = newContext(true);
      options = { instant: true, announce: false, scrollTop: options.scrollTop };
      readiness.textContent = "";
      readiness.appendChild(readinessStrip("grounded"));
    }
    turns.appendChild(userTurn(fixture.question, 0, fixture.attachment));
    var turnId = nextTurnId();
    var article = agentArticle(turnId);
    turns.appendChild(article);
    state.stuck = !options.scrollTop;
    var spec = investigationSpec(fixture);
    beginTurn(spec, article, turnId, 0, ctx, options.announce);
    records[turnId].fixture = fixture;
    try {
      if (!ctx.instant) {
        pause(TIMING.readiness, ctx).then(function () {
          readiness.textContent = "";
          readiness.appendChild(readinessStrip("grounded", !ctx.reduced));
        }, ignoreCancel);
      }
      await runInvestigationTurn(fixture, ctx, article, turnId, 0);
      settleTurn(spec, ctx, options.announce);
      if (options.scrollTop) {
        moveScroll(0);
        updateJump();
      }
    } catch (error) {
      ignoreCancel(error);
    }
  }

  // Suggested questions and Draft remediation start a separate request; this preview only records it.
  function previewRequest(button, question, reply) {
    if (state.busy) return;
    var item = button.closest(".cs-deck-followups > li");
    if (item) retire(item.parentElement.children.length === 1 ? item.parentElement : item);
    if (button.classList.contains("cs-deck-affordance")) {
      button.disabled = true;
      button.textContent = "Draft requested";
    }
    hideTip();
    state.clock += 40;
    var offset = state.clock;
    turns.appendChild(userTurn(question, offset));
    var turnId = nextTurnId();
    var article = agentArticle(turnId);
    turns.appendChild(article);
    state.stuck = true;
    followTurn(article.previousElementSibling);
    reserveTurn(article);
    article.appendChild(h("div", { class: "cs-deck-answer" + (state.reduced ? "" : " cs-deck-enter") }, [
      h("div", { class: "cs-deck-prose" }, [h("p", { text: reply })])
    ]));
    setTurnTime(article, offset + 1, !state.reduced);
    followScroll();
    announce(reply);
  }

  function plainInvestigation(fixture) {
    var answer = fixture.answer;
    return [answer.lead]
      .concat(answer.facts.map(function (pair) { return pair[0] + ": " + pair[1]; }))
      .concat(answer.checks.map(function (text) { return "- " + text; }))
      .concat(answer.limitations.map(function (text) { return "Limit: " + text; }))
      .concat(answer.note ? [answer.note] : [])
      .concat(answer.next_step ? ["Next safe step: " + answer.next_step] : [])
      .join("\n");
  }

  // The run record maps the investigation onto the same phase, evidence, and model rows as the
  // one-shot study, so both forms share one timeline and one provider waterfall.
  function fixtureTrajectory(record) {
    var fixture = record.fixture;
    var detail = fixture.trajectory_detail;
    var start = (38463 + record.offset) * 1000 + 160;
    var cursor = start;
    var items = [];
    var calls = [];
    var budgetCalls = detail.turn_budget ? detail.turn_budget.model_calls.used : 3;
    items.push({ kind: "turn", kindLabel: "Turn", label: "Input", state: "completed", start: cursor, ms: 0, summary: fixture.question,
      facts: [["Source", "operator"]], records: [["Operator input", fixture.question]] });
    cursor += 6;
    var planOutput = { summary: fixture.plan.summary, waves: fixture.plan.waves.map(function (wave) {
      return { wave: wave.id, label: wave.label, branches: wave.branch_ids };
    }) };
    var planCall = modelCall("semantic_plan", cursor + 8, MODEL.planMs, [
      { role: "system", content: "You are Bragi, the FDAI narrator. Plan once: compile the question into typed read waves that use only registered read-only capabilities. Do not decide, approve, or execute anything." },
      { role: "user", content: fixture.question }
    ], { content: pretty(planOutput) }, { prompt_tokens: 1320, completion_tokens: 188, total_tokens: 1508 }, []);
    calls.push(planCall);
    items.push({ kind: "phase", kindLabel: "Phase", label: "Semantic planning", state: "completed", start: cursor, ms: MODEL.planMs + 18,
      summary: fixture.plan.waves.length + " waves planned", facts: [["Model", MODEL.name], ["Waves", String(fixture.plan.waves.length)]],
      records: [["Answer plan", pretty(planOutput)]] });
    cursor += MODEL.planMs + 22;
    var executions = detail.activities.filter(function (activity) { return activity.execution; });
    var first = executions.length
      ? Math.min.apply(null, executions.map(function (activity) { return Date.parse(activity.execution.started_at); }))
      : 0;
    var evidenceEnd = cursor;
    var attempted = 0;
    var completed = 0;
    detail.activities.forEach(function (activity) {
      var presentation = activityPresentation(fixture, activity);
      var execution = activity.execution;
      var begin = execution ? cursor + (Date.parse(execution.started_at) - first) : evidenceEnd;
      var ms = execution ? execution.duration_ms : 40;
      if (execution) {
        attempted += 1;
        if (activity.status === "completed") completed += 1;
      }
      var records = execution ? [["IQL or typed query", execution.command]] : [];
      if (execution && execution.output) records.push(["Observed output", execution.output]);
      // A denied or cancelled read observed nothing; only a read that ran and broke is a failure.
      var outcome = activity.status === "completed" ? "completed" : activity.status === "failed" ? "failed" : "not_observed";
      items.push({ kind: execution ? "evidence" : "phase", kindLabel: execution ? "Evidence" : "Phase", label: activity.label,
        state: outcome, start: begin, ms: ms, summary: activity.detail || null,
        facts: [["Tool", execution ? execution.tool : "deterministic comparison"], ["Authority", activity.authority],
          ["Authorization", AUTHORIZATION_TEXT[presentation.authorization] || "Allowed"]], records: records });
      evidenceEnd = Math.max(evidenceEnd, begin + ms);
    });
    cursor = evidenceEnd + 6;
    var generationStart = cursor;
    var generationCall = modelCall("answer_generation", cursor + 6, MODEL.generationMs, [
      { role: "system", content: "Compose the answer only from the verified reads. Lead with the finding, keep limits explicit, and never offer to execute or approve an action." },
      { role: "user", content: pretty({ question: fixture.question, facts: fixture.answer.facts, checks: fixture.answer.checks }) }
    ], { content: fixture.answer.lead }, { prompt_tokens: 1640, completion_tokens: 212, total_tokens: 1852 }, []);
    calls.push(generationCall);
    items.push({ kind: "phase", kindLabel: "Phase", label: "Answer generation", state: "completed", start: cursor, ms: MODEL.generationMs + 14,
      summary: "Answer from " + completed + " completed reads", facts: [["Model", MODEL.name]], records: [] });
    cursor += MODEL.generationMs + 20;
    if (budgetCalls >= 3) {
      var reviewCall = modelCall("quality_review", cursor + 4, 280, [
        { role: "system", content: "Review goal coverage, contradictions, and unsupported operational claims. Report issues only." },
        { role: "user", content: fixture.answer.lead }
      ], { content: pretty({ coverage: "complete", issues: [] }) }, { prompt_tokens: 980, completion_tokens: 42, total_tokens: 1022 }, []);
      calls.push(reviewCall);
      items.push({ kind: "phase", kindLabel: "Phase", label: "Quality review", state: "completed", start: cursor, ms: 290,
        summary: "Independent review", facts: [["Model", MODEL.name]], records: [] });
      cursor += 296;
    }
    var verificationStart = cursor;
    var verification = TONE_STATE[fixture.answer.verification.tone] || "not_observed";
    items.push({ kind: "phase", kindLabel: "Phase", label: "Verification", state: verification === "not_observed" ? "completed" : verification,
      start: cursor, ms: 54, summary: fixture.answer.verification.detail, facts: [["Checks", fixture.answer.verification.detail], ["Authority", "read"]],
      records: [] });
    cursor += 58;
    items.push({ kind: "turn", kindLabel: "Turn", label: "Answer", state: "completed", start: cursor, ms: 0,
      summary: "verification: " + fixture.answer.verification.label, facts: [["Agent", "Bragi"]], records: [] });
    var trajectory = {
      start: start, end: cursor, items: items, calls: calls, attempted: attempted, completed: completed,
      modelMs: calls.reduce(function (total, call) { return total + call.ms; }, 0),
      tokens: detail.turn_budget ? detail.turn_budget.tokens.used : calls.reduce(function (total, call) { return total + call.usage.total_tokens; }, 0),
      verification: verification,
      evidenceState: completed < attempted ? "degraded" : "completed"
    };
    return record.observed ? observedTrajectory(trajectory, record.observed, [start, generationStart, verificationStart]) : trajectory;
  }

  // A wave that never started has no reads to show, so its header does not open an empty body.
  function toggleWave(button) {
    var body = document.getElementById(button.getAttribute("aria-controls"));
    var wave = button.closest(".cs-deck-wave");
    if (!body || !wave || /^(pending|skipped)$/.test(wave.getAttribute("data-state"))) return;
    showWave({ head: button, body: body }, button.getAttribute("aria-expanded") !== "true", true);
  }

  // A stop leaves every read that finished, and marks the reads still running as stopped.
  function stopInvestigation(article) {
    var block = article.querySelector(":scope > .cs-deck-investigation");
    if (!block) return;
    // The header counts reads only after the last wave settles; a stop before that says so.
    var unfinished = !block.hasAttribute("data-settled");
    block.querySelectorAll(".cs-deck-activity[data-status='running']").forEach(function (node) {
      node.setAttribute("data-status", "stopped");
      var mark = node.querySelector(".cs-deck-activity-mark");
      mark.textContent = "-";
      node.querySelector(".cs-deck-activity-status").textContent = "Stopped";
      node.querySelector(".cs-deck-activity-detail").replaceChildren(
        h("p", { class: "cs-deck-activity-note", text: "Stopped before this read returned. Nothing was changed." }));
    });
    block.querySelectorAll(".cs-deck-wave[data-state='running']").forEach(function (node) {
      node.setAttribute("data-state", "stopped");
      node.querySelector(".cs-deck-wave-mark").textContent = "-";
      node.querySelector(".cs-deck-wave-meta").textContent = "Stopped";
    });
    block.querySelectorAll(".cs-deck-wave[data-state='pending']").forEach(function (node) {
      node.setAttribute("data-state", "skipped");
      node.querySelector(".cs-deck-wave-meta").textContent = "Not started";
    });
    var status = block.querySelector(".cs-deck-investigation-status");
    if (status && unfinished) status.textContent = "Stopped before the answer";
  }

  // ---------- Leaving the conversation asks first ----------
  var leaveHref = null;
  var leaveTitle = h("h2", { class: "cs-deck-leave-title", id: "ds-leave-title" });
  var leaveBody = h("p", { class: "cs-deck-leave-body", id: "ds-leave-body" });
  var leaveOpen = h("button", { type: "submit", class: "cs-deck-leave-open", value: "open" });
  var leave = h("dialog", { class: "cs-deck-leave", id: "ds-leave", "aria-labelledby": "ds-leave-title", "aria-describedby": "ds-leave-body" }, [
    h("form", { class: "cs-deck-leave-form", method: "dialog" }, [
      leaveTitle,
      leaveBody,
      h("div", { class: "cs-deck-leave-actions" }, [
        h("button", { type: "submit", class: "cs-deck-leave-stay", value: "stay", autofocus: true, text: "Stay here" }),
        leaveOpen
      ])
    ])
  ]);
  workspace.appendChild(leave);

  function confirmLeave(href) {
    if (!href) return;
    var label = pageLabel(href);
    leaveHref = href;
    leaveTitle.textContent = "Open " + label + "?";
    leaveBody.textContent = "This leaves the conversation and shows " + label + " in its place. Stay here to keep reading.";
    leaveOpen.textContent = "Open " + label;
    leave.returnValue = "";
    hideTip();
    leave.showModal();
  }

  leave.addEventListener("close", function () {
    var href = leaveHref;
    leaveHref = null;
    if (leave.returnValue === "open" && href) window.location.assign(href);
  });

  // Any deck link to another screen waits for consent; in-page anchors and new-tab clicks pass.
  // The guard listens on the window in the capture phase, so it runs before any document-level
  // router, including the mock index's preview history, and its preventDefault stops them all.
  window.addEventListener("click", function (event) {
    var link = event.target.closest ? event.target.closest("a[href]") : null;
    if (!link || !workspace.contains(link)) return;
    var href = link.getAttribute("href");
    if (!href || href.charAt(0) === "#") return;
    if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    confirmLeave(href);
  }, true);

  // ---------- Events ----------
  transcript.addEventListener("click", function (event) {
    var target = event.target.closest("a, button");
    if (!target || !transcript.contains(target)) return;
    if (target.classList.contains("cs-deck-cite")) {
      event.preventDefault();
      revealSource(target);
      return;
    }
    if (target.classList.contains("cs-deck-followup")) {
      if (target.hasAttribute("data-followup-text")) {
        previewRequest(target, target.getAttribute("data-followup-text"),
          "This preview replays scripted investigations only. In the Console, this question starts a new request with its own plan, reads, and limits.");
      } else {
        askFollowUp(target);
      }
      return;
    }
    var action = target.getAttribute("data-action");
    if (action === "wave-toggle") {
      toggleWave(target);
    } else if (action === "draft-remediation") {
      previewRequest(target, "Draft a remediation for these differences.",
        "Draft remediation is a separate request. FDAI rechecks the scope, the policy, and whether a typed draft is available before it prepares one, and nothing runs without approval. This preview stops here.");
    } else if (action === "sources") {
      setSources(target.closest(".cs-deck-agent-turn"), target.getAttribute("aria-expanded") !== "true");
    } else if (action === "copy") {
      copyReply(target);
    } else if (action === "copy-code") {
      copyCode(target);
    } else if (action === "source-detail") {
      var detail = document.getElementById(target.getAttribute("aria-controls"));
      var expanded = target.getAttribute("aria-expanded") !== "true";
      target.setAttribute("aria-expanded", expanded ? "true" : "false");
      if (detail) detail.hidden = !expanded;
    } else if (action === "open-page") {
      confirmLeave(target.getAttribute("data-href"));
    } else if (action === "regenerate") {
      regenerate(target.closest(".cs-deck-agent-turn"));
    } else if (action === "suggest") {
      playConversation({ instant: false, announce: true });
      input.focus({ preventScroll: true });
    }
  });

  transcript.addEventListener("scroll", function () {
    hideTip();
    noteScroll();
    updateJump();
  }, { passive: true });

  jump.addEventListener("click", function () {
    state.stuck = true;
    follow.mode = "bottom";
    transcript.scrollTo({ top: transcript.scrollHeight, behavior: state.reduced ? "auto" : "smooth" });
    input.focus({ preventScroll: true });
  });

  // Pointer tooltips wait for a short hover so sweeping across citations does not flash them.
  document.addEventListener("pointerover", function (event) {
    var target = event.target.closest ? event.target.closest("[data-tip]") : null;
    window.clearTimeout(tipTimer);
    if (target) {
      if (target === tipOwner) return;
      tipTimer = window.setTimeout(function () { showTip(target); }, tipOwner ? 60 : 320);
    } else if (tipOwner && document.activeElement !== tipOwner) {
      hideTip();
    }
  });

  document.addEventListener("focusin", function (event) {
    var target = event.target.closest ? event.target.closest("[data-tip]") : null;
    if (target) showTip(target);
    else hideTip();
  });

  document.addEventListener("focusout", function (event) {
    if (event.target === tipOwner) hideTip();
  });

  document.addEventListener("keydown", function (event) {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      searchInput.focus();
      searchInput.select();
    } else if (event.key === "Escape" && !tip.hidden) {
      hideTip();
    }
  });

  window.addEventListener("resize", hideTip);

  searchInput.addEventListener("input", function () {
    window.clearTimeout(search.timer);
    search.timer = window.setTimeout(function () { runSearch(true); }, 120);
  });

  searchInput.addEventListener("search", function () { runSearch(false); });

  searchInput.addEventListener("keydown", function (event) {
    if (event.key !== "Enter") return;
    event.preventDefault();
    moveSearch(event.shiftKey ? -1 : 1);
  });

  searchPrev.addEventListener("click", function () { moveSearch(-1); });
  searchNext.addEventListener("click", function () { moveSearch(1); });
  byId("ds-new").addEventListener("click", newConversation);
  byId("ds-close").addEventListener("click", function () { setOpen(false); });
  reopen.addEventListener("click", function () { setOpen(true); });
  contextChip.addEventListener("click", function () { setScreenAttached(!state.screenAttached); });

  byId("ds-attach").addEventListener("click", function () {
    note.textContent = "Preview only: attachments are not uploaded in this replay.";
  });

  input.addEventListener("input", function () {
    updateSend();
    note.textContent = "";
    resizeInput();
  });

  input.addEventListener("keydown", function (event) {
    if (event.key !== "Enter" || event.shiftKey || event.isComposing) return;
    event.preventDefault();
    if (!state.busy && input.value.trim()) composer.requestSubmit();
  });

  composer.addEventListener("submit", function (event) {
    event.preventDefault();
    if (state.busy || !input.value.trim()) return;
    note.textContent = "Preview only: this replay answers the scripted question and its suggested follow-ups. Your draft is kept.";
  });

  send.addEventListener("click", function (event) {
    if (!state.busy) return;
    event.preventDefault();
    stopTurn();
  });

  document.querySelectorAll("button[data-scenario]").forEach(function (button) {
    button.addEventListener("click", function () {
      state.scenario = button.getAttribute("data-scenario");
      setPressed("data-scenario", state.scenario);
      playConversation({ instant: state.reduced, announce: true });
    });
  });

  document.querySelectorAll("button[data-speed]").forEach(function (button) {
    button.addEventListener("click", function () {
      state.speed = Number(button.getAttribute("data-speed"));
      setPressed("data-speed", button.getAttribute("data-speed"));
    });
  });

  document.querySelectorAll("button[data-width]").forEach(function (button) {
    button.addEventListener("click", function () {
      state.width = button.getAttribute("data-width");
      workspace.setAttribute("data-width", state.width);
      setPressed("data-width", state.width);
      hideTip();
    });
  });

  byId("ds-replay").addEventListener("click", function () { playConversation({ instant: false, announce: true }); });
  byId("ds-finish").addEventListener("click", function () { playConversation({ instant: true, announce: true }); });

  traceSwitch.addEventListener("change", function () {
    state.captureTrace = traceSwitch.checked;
    refreshRunRecords();
    announce(state.captureTrace ? "Model trace capture is on for new turns." : "Model trace capture is off.");
  });

  reducedMotion.addEventListener("change", function (event) { state.reduced = event.matches; });

  // ---------- Start ----------
  setPressed("data-scenario", state.scenario);
  setPressed("data-width", state.width);
  traceSwitch.checked = state.captureTrace;
  workspace.setAttribute("data-width", state.width);
  var settledStart = state.reduced || params.get("state") === "settled";
  playConversation({ instant: settledStart, announce: false, scrollTop: settledStart });
})();
