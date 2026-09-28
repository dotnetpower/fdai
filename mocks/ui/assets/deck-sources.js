// Command deck sources - scripted source-streaming study for mocks/ui/deck-sources.html.
// Synthetic data only. The replay performs no network request, model call, or state change.
(function () {
  "use strict";

  var DAY = "2026-09-28";
  var ROUTE = "Live cockpit";
  var QUESTION = "example-postgres keeps getting flagged. Why, and can you fix it automatically?";
  var CONVERSATION_TITLE = "Why is example-postgres flagged?";
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
    chevron: ["M5 6.5l3 3 3-3"]
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

  function payload(label, value) {
    return h("section", { class: "cs-run-payload" }, [
      h("strong", { text: label }),
      h("pre", { class: "cs-run-code" }, [h("code", { text: value })])
    ]);
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
        return h("li", null, [h("strong", { class: "cs-model-trace-role", text: group.role }),
          h("pre", { class: "cs-run-code" }, [h("code", { text: group.contents.join("\n\n") })])]);
      })),
      h("section", { class: "cs-run-payload", "aria-label": "Assistant response" }, [
        h("strong", { text: "Assistant response" }),
        hashLine("Response SHA-256", call.response.content),
        h("pre", { class: "cs-run-code" }, [h("code", { text: call.response.content })])
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
    var evidence = toolKeys(spec).some(function (key) { return TOOLS[key].status; }) ? "degraded" : "completed";
    var states = { input: "completed", plan: "completed", collaboration: "not_observed", evidence: evidence,
      verification: trajectory.verification, answer: "completed" };
    return h("ol", { class: "cs-run-phase-strip", "aria-label": "Question-to-answer trajectory phases" }, PHASES.map(function (phase) {
      var value = states[phase[0]];
      return h("li", { class: "cs-run-phase", "data-state": value }, [
        h("span", { class: "cs-run-phase-mark", "aria-hidden": "true", text: STATE_MARK[value] }),
        h("strong", { text: phase[1] }),
        h("small", { text: STATE_LABEL[value] })
      ]);
    }));
  }

  // The body renders on first open, so settled turns stay light until someone inspects them.
  function runRecord(record, open) {
    var trajectory = buildTrajectory(record);
    var captureOn = state.captureTrace;
    var traceLabel = !captureOn ? "Model trace off" : record.captured ? trajectory.calls.length + " model calls" : "Model trace not captured";
    var stats = traceLabel + " / model " + formatMs(trajectory.modelMs) + " / " + trajectory.tokens.toLocaleString("en-US") +
      " tokens / evidence " + trajectory.completed + "/" + trajectory.attempted + " / verification " + STATE_LABEL[trajectory.verification];
    var body = h("div", { class: "cs-run-record-body" });
    var details = h("details", { class: "cs-run-record", "data-run-record": record.turnId }, [
      h("summary", { class: "cs-run-record-summary" }, spaced([
        h("span", { class: "cs-run-record-title" }, [
          h("span", { class: "cs-run-record-glyph", "aria-hidden": "true" }, [h("i"), h("i"), h("i")]),
          h("span", { class: "cs-run-record-title-copy" }, spaced([
            h("small", { class: "cs-run-record-kicker", text: "Run record" }),
            h("strong", { class: "cs-run-record-heading", text: "Observed process" })
          ]))
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
        return h("li", null, [h("a", {
          class: "cs-deck-source" + (source.unavailable ? " is-unavailable" : ""),
          id: turnId + "-source-" + number,
          href: source.href
        }, spaced([
          h("span", { class: "cs-deck-source-num", "aria-hidden": "true", text: number }),
          h("span", { class: "cs-deck-kind", text: source.kind }),
          h("span", { class: "cs-deck-source-copy" }, spaced([
            h("span", { class: "cs-deck-source-title", text: source.title }),
            h("span", { class: "cs-deck-source-meta", text: source.meta })
          ])),
          when
        ]))]);
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

  function userTurn(text, offsetSeconds) {
    var time = stamp(offsetSeconds);
    return h("article", { class: "cs-deck-turn cs-deck-user-turn", "data-turn": "user" }, [
      h("div", { class: "cs-deck-user-bubble" }, [
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
    var unavailable = SCENARIOS[mode].unavailableSources;
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
  var ANSWER_STATE = { partial: "Partial", corrected: "Corrected", stopped: "Stopped" };
  var params = new URLSearchParams(window.location.search);
  var reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  var state = {
    scenario: SCENARIOS[params.get("scenario")] ? params.get("scenario") : "grounded",
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
  // just far enough to show the verification row. Scrolling by hand stops the follow; returning to
  // the bottom or choosing Jump to latest follows the newest content instead.
  var follow = { frame: 0, mode: "pin", pin: null, reveal: null, userUntil: 0 };

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
      if (target > transcript.scrollTop) transcript.scrollTop = target;
      updateJump();
      return;
    }
    if (!follow.frame) follow.frame = window.requestAnimationFrame(followStep);
  }

  function followStep() {
    follow.frame = 0;
    if (!state.stuck) return;
    var distance = followTarget() - transcript.scrollTop;
    if (distance > 0.5) {
      // Ease out with a speed cap, so a long reveal glides instead of leaping.
      transcript.scrollTop += Math.min(28, Math.max(1, distance * 0.16));
      follow.frame = window.requestAnimationFrame(followStep);
    }
    updateJump();
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
    var sourceList = h("ul", { class: "cs-grounding-source-list" }, [0, 1, 2].map(function () {
      return h("li", { class: "cs-grounding-source is-placeholder", "aria-hidden": "true" }, [skeleton()]);
    }));
    var sourceCount = h("span", { text: "0 read" });
    panel.appendChild(h("div", { class: "cs-grounding-sources" }, [
      h("div", { class: "cs-grounding-sources-head" }, [h("span", { text: "Reading sources" }), sourceCount]),
      sourceList
    ]));
    var fold = h("div", { class: "cs-deck-collapse" }, [h("div", null, [panel])]);
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
        transcript.scrollTop = 0;
        updateJump();
      }
    } catch (error) {
      ignoreCancel(error);
    }
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
    item.remove();
    if (!list.children.length) list.remove();
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
    state.stuck = false;
    beginTurn(record.spec, article, article.id, record.offset, ctx, true);
    input.focus({ preventScroll: true });
    article.scrollIntoView({ block: "nearest" });
    try {
      await runAgentTurn(record.spec, ctx, article, article.id, record.offset);
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
    article.appendChild(h("div", { class: "cs-deck-action-row" }, [
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
    turns.appendChild(h("section", { class: "ds-intro", "aria-labelledby": "ds-intro-title" }, [
      h("h3", { class: "ds-intro-title", id: "ds-intro-title", text: "Ask about " + ROUTE }),
      h("p", { class: "ds-intro-lead", text: "Bragi answers from read-only sources and cites each claim. This preview replays one scripted question." }),
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
      active.scrollIntoView({ block: "nearest" });
      state.stuck = atBottom();
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
    target.scrollIntoView({ block: "nearest" });
    state.stuck = atBottom();
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
      button.setAttribute("data-tip", label);
      showTip(button);
      announce(label + ".");
      window.setTimeout(function () {
        button.setAttribute("data-tip", "Copy reply");
        if (tipOwner === button) hideTip();
      }, 1500);
    };
    if (!navigator.clipboard || !window.isSecureContext) {
      finish("Copy is unavailable in this preview");
      return;
    }
    navigator.clipboard.writeText(plainAnswer(record.spec)).then(function () {
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
      askFollowUp(target);
      return;
    }
    var action = target.getAttribute("data-action");
    if (action === "sources") {
      setSources(target.closest(".cs-deck-agent-turn"), target.getAttribute("aria-expanded") !== "true");
    } else if (action === "copy") {
      copyReply(target);
    } else if (action === "regenerate") {
      regenerate(target.closest(".cs-deck-agent-turn"));
    } else if (action === "suggest") {
      playConversation({ instant: false, announce: true });
      input.focus({ preventScroll: true });
    }
  });

  var SCROLL_KEYS = { ArrowUp: 1, ArrowDown: 1, PageUp: 1, PageDown: 1, Home: 1, End: 1, " ": 1 };
  ["wheel", "touchmove", "keydown", "pointerdown"].forEach(function (type) {
    transcript.addEventListener(type, function (event) {
      if (type === "keydown" && !SCROLL_KEYS[event.key]) return;
      // A pointer press on the scroller itself, not its content, is a scrollbar drag.
      if (type === "pointerdown" && event.target !== transcript) return;
      follow.userUntil = performance.now() + 600;
    }, { passive: true });
  });

  transcript.addEventListener("scroll", function () {
    hideTip();
    if (performance.now() < follow.userUntil) {
      state.stuck = atBottom();
      if (state.stuck) follow.mode = "bottom";
    }
    updateJump();
  }, { passive: true });

  jump.addEventListener("click", function () {
    state.stuck = true;
    follow.mode = "bottom";
    transcript.scrollTo({ top: transcript.scrollHeight, behavior: state.reduced ? "auto" : "smooth" });
    input.focus({ preventScroll: true });
  });

  document.addEventListener("pointerover", function (event) {
    var target = event.target.closest ? event.target.closest("[data-tip]") : null;
    if (target) {
      if (target !== tipOwner) showTip(target);
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
