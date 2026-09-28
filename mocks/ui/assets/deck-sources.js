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
  var TIMING = { readiness: 420, stage: 420, source: 140, word: 28, paragraph: 140, verify: 480, step: 260 };

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
        { label: "Evaluate policy", detail: "Not evaluated: no current configuration to check", phase: "Ground", attention: true },
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
        { label: "Compare evidence times", detail: "The flag predates the newer inventory read", phase: "Verify", attention: true },
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
    regenerate: ["M13 8a5 5 0 1 1-1.46-3.54", "M13 2.5V5h-2.5"]
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
  function stageRow(stage, number, status, entering) {
    var copy = h("span", { class: "cs-grounding-stage-copy" }, [h("span", { class: "cs-grounding-stage-label", text: stage.label })]);
    if (stage.intent) {
      copy.appendChild(h("dl", { class: "cs-grounding-intent" }, stage.intent.map(function (pair) {
        return h("div", null, [h("dt", { text: pair[0] }), h("dd", { text: pair[1] })]);
      })));
    } else {
      copy.appendChild(h("span", { class: "cs-grounding-stage-detail", text: stage.detail }));
    }
    var row = h("li", { class: "cs-grounding-stage" + (entering ? " is-entering" : "") }, [
      h("span", { class: "cs-grounding-mark", "aria-hidden": "true", text: String(number) }),
      copy,
      h("span", { class: "cs-grounding-phase", text: stage.phase }),
      h("span", { class: "cs-grounding-state" })
    ]);
    setStageStatus(row, status);
    return row;
  }

  function setStageStatus(row, status) {
    ["active", "done", "attention"].forEach(function (name) { row.classList.toggle("is-" + name, status === name); });
    var cell = row.querySelector(".cs-grounding-state");
    cell.textContent = "";
    cell.appendChild(status === "active"
      ? h("span", { class: "cs-grounding-spinner", "aria-hidden": "true" })
      : h("span", { "aria-hidden": "true", text: status === "attention" ? "!" : CHECK }));
    cell.appendChild(h("span", {
      class: "cs-sr-only",
      text: status === "active" ? "In progress" : status === "attention" ? "Needs attention" : "Done"
    }));
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

  function processingDisclosure(spec) {
    var available = availableCount(spec);
    return h("details", { class: "cs-deck-processing" }, [
      h("summary", { class: "cs-deck-processing-summary" }, spaced([
        h("span", { class: "cs-deck-processing-label", text: "Deterministic processing" }),
        h("span", { class: "cs-deck-processing-answerer", text: "Deterministic answerer" }),
        h("span", { class: "cs-deck-processing-meta", text: spec.stages.length + " steps \u00b7 Read-only" }),
        h("span", { class: "cs-deck-processing-chevron", "aria-hidden": "true" })
      ])),
      h("div", { class: "cs-deck-processing-body" }, [
        h("p", {
          class: "cs-deck-processing-note",
          text: "No LLM was used. The deterministic answerer composed this answer from " + available +
            (available === 1 ? " source" : " sources") +
            ". Every step used a read-only console-tool (side_effect_class: read), so nothing was executed."
        }),
        h("ol", { class: "cs-grounding-stages", "aria-label": "Retrieval trace" }, spec.stages.map(function (stage, index) {
          return stageRow(stage, index + 1, stage.attention ? "attention" : "done", false);
        }))
      ])
    ]);
  }

  function actionRow(spec, turnId) {
    var verification = spec.verification;
    var pill = spec.pill || { attention: false, issue: null };
    var available = availableCount(spec);
    var pillChildren = [
      h("span", { class: "cs-deck-pill-mark", "aria-hidden": "true", text: pill.attention ? "!" : CHECK }),
      h("span", { class: "cs-deck-pill-stat" }, [h("strong", { text: String(available) }), available === 1 ? " source" : " sources"])
    ];
    if (pill.issue) pillChildren.push(separator(), h("span", { class: "cs-deck-pill-issue", text: pill.issue }));
    pillChildren.push(separator(), h("span", { class: "cs-deck-pill-more", text: "show sources" }));
    return h("div", { class: "cs-deck-action-row" }, [
      h("span", { class: "cs-deck-verification is-" + verification.tone }, spaced([
        h("span", { class: "cs-deck-verification-mark", "aria-hidden": "true", text: verification.mark }),
        h("span", { text: verification.label }),
        h("span", { class: "cs-deck-verification-detail", text: verification.detail })
      ])),
      h("button", { type: "button", class: "cs-deck-tool cs-deck-tool-icon", "aria-label": "Copy reply", "data-tip": "Copy reply", "data-action": "copy" }, [icon("copy")]),
      h("button", { type: "button", class: "cs-deck-tool cs-deck-tool-icon", "aria-label": "Regenerate", "data-tip": "Ask this question again", "data-action": "regenerate" }, [icon("regenerate")]),
      h("a", { class: "cs-deck-tool cs-deck-tool-link", href: "conversation-assurance.html", text: "Review answer quality" }),
      h("button", {
        type: "button",
        class: "cs-deck-pill" + (pill.attention ? " is-attention" : ""),
        "aria-expanded": "false",
        "aria-controls": turnId + "-sources",
        "data-action": "sources"
      }, spaced(pillChildren))
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

  function turnFoot(offsetSeconds) {
    var time = stamp(offsetSeconds);
    return h("div", { class: "cs-deck-turn-foot" }, [
      h("time", { class: "cs-deck-turn-time", datetime: time.iso, text: time.short })
    ]);
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

  function agentArticle(turnId) {
    return h("article", { class: "cs-deck-turn cs-deck-agent-turn", id: turnId, "data-turn": "agent" }, [
      h("header", { class: "cs-deck-turn-head" }, spaced([
        h("span", { class: "cs-deck-agent-name" }, [h("span", { class: "cs-deck-agent-icon ds-agent-icon", "aria-hidden": "true" }), "Bragi"]),
        h("span", { class: "cs-deck-agent-source", text: "Deterministic" })
      ]))
    ]);
  }

  function readinessStrip(mode) {
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
    return h("nav", { class: "cs-deck-readiness", "aria-label": "Evidence sources" }, [
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

  // ---------- Replay control ----------
  function cancelRun() {
    state.token += 1;
    pending.forEach(function (reject, id) {
      window.clearTimeout(id);
      reject(CANCELLED);
    });
    pending.clear();
    stopElapsed();
  }

  function pause(ms, ctx) {
    if (ctx.instant) return Promise.resolve();
    if (ctx.token !== state.token) return Promise.reject(CANCELLED);
    return new Promise(function (resolve, reject) {
      var id = window.setTimeout(function () {
        pending.delete(id);
        if (ctx.token === state.token) resolve();
        else reject(CANCELLED);
      }, Math.max(0, ms / state.speed));
      pending.set(id, reject);
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

  function updateJump() {
    jump.hidden = atBottom();
  }

  function followScroll() {
    if (state.stuck) transcript.scrollTop = transcript.scrollHeight;
    updateJump();
  }

  // ---------- Turn lifecycle ----------
  async function playPreparation(spec, ctx, article) {
    var status = h("span", { class: "cs-grounding-status", text: "Resolving intent and evidence needs" });
    var elapsed = h("span", { class: "cs-grounding-elapsed", "aria-hidden": "true", text: "0.0 s" });
    var stages = h("ol", { class: "cs-grounding-stages", "aria-label": "Preparation steps" });
    var panel = h("section", { class: "cs-grounding-panel", "aria-label": "Preparing answer" }, [
      h("header", { class: "cs-grounding-head" }, spaced([
        h("span", { class: "cs-grounding-spinner", "aria-hidden": "true" }),
        h("span", { class: "cs-grounding-title", text: "Preparing answer" }),
        status,
        elapsed,
        h("span", { class: "cs-grounding-authority", text: "Read-only" })
      ])),
      stages
    ]);
    var placeholder = h("div", { class: "cs-deck-answer-skeleton", "aria-hidden": "true" }, [skeleton(), skeleton(), skeleton()]);
    article.appendChild(panel);
    article.appendChild(placeholder);
    startElapsed(elapsed);
    followScroll();
    var sourceList = null;
    var sourceCount = null;
    var read = 0;
    var missing = 0;
    var steps = spec.stages.filter(function (stage) { return !stage.verify; });
    for (var index = 0; index < steps.length; index += 1) {
      var stage = steps[index];
      var row = stageRow(stage, index + 1, "active", !ctx.reduced);
      stages.appendChild(row);
      status.textContent = stage.label;
      followScroll();
      await pause(ctx.reduced ? TIMING.step : TIMING.stage, ctx);
      setStageStatus(row, stage.attention ? "attention" : "done");
      var emits = stage.emits || [];
      for (var item = 0; item < emits.length; item += 1) {
        if (!sourceList) {
          sourceList = h("ul", { class: "cs-grounding-source-list" });
          sourceCount = h("span");
          panel.appendChild(h("div", { class: "cs-grounding-sources" }, [
            h("div", { class: "cs-grounding-sources-head" }, [h("span", { text: "Reading sources" }), sourceCount]),
            sourceList
          ]));
        }
        sourceList.appendChild(previewSource(emits[item]));
        while (sourceList.children.length > 3) sourceList.firstElementChild.remove();
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
    panel.remove();
    placeholder.remove();
  }

  async function streamParagraph(node, text, spec, ctx, turnId) {
    if (ctx.reduced) {
      renderInline(node, text, spec, turnId, false);
      followScroll();
      await pause(TIMING.step, ctx);
      return;
    }
    var tokens = text.split(/(\s+)/);
    var built = "";
    var caret = h("span", { class: "cs-deck-caret", "aria-hidden": "true" });
    for (var index = 0; index < tokens.length; index += 1) {
      built += tokens[index];
      if (!tokens[index].trim()) continue;
      node.textContent = "";
      renderInline(node, built, spec, turnId, false);
      node.appendChild(caret);
      followScroll();
      await pause(TIMING.word, ctx);
    }
    caret.remove();
  }

  async function streamAnswer(spec, ctx, article, turnId) {
    var answer = h("div", { class: "cs-deck-answer" });
    var prose = h("div", { class: "cs-deck-prose" });
    if (!ctx.instant) answer.appendChild(h("span", { class: "cs-deck-answer-state is-draft", text: "Draft" }));
    answer.appendChild(prose);
    article.appendChild(answer);
    if (ctx.instant) return answer;
    setDeckState("answering");
    for (var index = 0; index < spec.answer.length; index += 1) {
      var paragraph = spec.answer[index];
      var node = h("p");
      prose.appendChild(node);
      await streamParagraph(node, paragraph.unsupported ? paragraph.text + " " + paragraph.unsupported : paragraph.text, spec, ctx, turnId);
      (spec.notes || []).forEach(function (item) {
        if (item.after === index && item.when !== "verify") prose.appendChild(noteElement(item, spec, turnId, false));
      });
      followScroll();
      await pause(TIMING.paragraph, ctx);
    }
    return answer;
  }

  async function verifyAnswer(ctx, article) {
    if (ctx.instant) return;
    var row = h("div", { class: "cs-deck-action-row ds-pending-row" }, [
      h("span", { class: "cs-deck-verification is-pending" }, spaced([
        h("span", { class: "cs-grounding-spinner", "aria-hidden": "true" }),
        h("span", { text: "Checking answer" })
      ]))
    ]);
    article.appendChild(row);
    followScroll();
    await pause(TIMING.verify, ctx);
    row.remove();
  }

  function finalizeTurn(spec, article, answer, turnId, offset) {
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
    var badge = answer.querySelector(".cs-deck-answer-state");
    if (spec.answerState) {
      if (!badge) {
        badge = h("span");
        answer.insertBefore(badge, prose);
      }
      badge.className = "cs-deck-answer-state is-" + spec.answerState;
      badge.textContent = ANSWER_STATE[spec.answerState];
    } else if (badge) {
      badge.remove();
    }
    article.appendChild(processingDisclosure(spec));
    article.appendChild(actionRow(spec, turnId));
    article.appendChild(sourcesPanel(spec, turnId));
    var remaining = (spec.followups || []).filter(function (key) { return !state.asked[key]; });
    if (remaining.length) article.appendChild(followupList(remaining));
    article.appendChild(turnFoot(offset + 6));
  }

  async function runAgentTurn(spec, ctx, article, turnId, offset) {
    if (!ctx.instant) await playPreparation(spec, ctx, article);
    var answer = await streamAnswer(spec, ctx, article, turnId);
    await verifyAnswer(ctx, article);
    finalizeTurn(spec, article, answer, turnId, offset);
  }

  function beginTurn(spec, article, turnId, offset, ctx, announceProgress) {
    records[turnId] = { spec: spec, offset: offset };
    state.active = { article: article, spec: spec, turnId: turnId, offset: offset };
    if (ctx.instant) return;
    setBusy(true);
    setDeckState("preparing");
    if (announceProgress) announce("Bragi is preparing an answer.");
  }

  function settleTurn(spec, ctx, announceResult) {
    if (ctx.token !== state.token) return;
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
        await pause(TIMING.readiness, ctx);
        readiness.textContent = "";
        readiness.appendChild(readinessStrip(state.scenario));
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

  function stopTurn() {
    var active = state.active;
    if (!state.busy || !active) return;
    cancelRun();
    var article = active.article;
    article.querySelectorAll(".cs-grounding-panel, .cs-deck-answer-skeleton, .ds-pending-row, .cs-deck-caret").forEach(function (node) {
      node.remove();
    });
    var answer = article.querySelector(".cs-deck-answer");
    if (!answer) {
      answer = h("div", { class: "cs-deck-answer" }, [h("div", { class: "cs-deck-prose" })]);
      article.appendChild(answer);
    }
    var prose = answer.querySelector(".cs-deck-prose");
    var hadText = prose.textContent.trim().length > 0;
    var badge = answer.querySelector(".cs-deck-answer-state");
    if (!badge) {
      badge = h("span");
      answer.insertBefore(badge, prose);
    }
    badge.className = "cs-deck-answer-state is-stopped";
    badge.textContent = ANSWER_STATE.stopped;
    prose.appendChild(noteElement({
      tone: "attention",
      label: "Stopped",
      text: hadText ? "this partial answer was not verified. Nothing was changed." : "no answer was composed. Nothing was changed."
    }, active.spec, active.turnId, false));
    article.appendChild(h("div", { class: "cs-deck-action-row" }, [
      h("button", { type: "button", class: "cs-deck-tool", "data-action": "regenerate", text: "Regenerate" })
    ]));
    article.appendChild(turnFoot(active.offset + 6));
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
        return node.parentElement && node.parentElement.closest(".cs-deck-cite, .cs-deck-evidence-note-mark, mark")
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
    button.querySelector(".cs-deck-pill-more").textContent = open ? "hide sources" : "show sources";
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

  transcript.addEventListener("scroll", function () {
    hideTip();
    state.stuck = atBottom();
    updateJump();
  }, { passive: true });

  jump.addEventListener("click", function () {
    transcript.scrollTo({ top: transcript.scrollHeight, behavior: state.reduced ? "auto" : "smooth" });
    state.stuck = true;
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

  reducedMotion.addEventListener("change", function (event) { state.reduced = event.matches; });

  // ---------- Start ----------
  setPressed("data-scenario", state.scenario);
  setPressed("data-width", state.width);
  workspace.setAttribute("data-width", state.width);
  var settledStart = state.reduced || params.get("state") === "settled";
  playConversation({ instant: settledStart, announce: false, scrollTop: settledStart });
})();
