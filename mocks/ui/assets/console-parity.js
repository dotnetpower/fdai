(function () {
  "use strict";

  function status(text, tone) {
    return { kind: "status", text: text, tone: tone || "neutral" };
  }

  function code(text) {
    return { kind: "code", text: text };
  }

  var common = {
    syntheticNote: "Illustrative data. Values show the intended Console structure and make no operational claim.",
    asOf: "2026-08-27T10:15:00Z"
  };

  var pages = {
    "detection-readiness": {
      group: "Operations",
      title: "Detection readiness",
      subtitle: "Agent-owned evidence that monitored Kubernetes targets can produce governed failure signals.",
      note: "Agent-owned state, not a browser health check. Readiness is reduced from stored observations.",
      kpis: [["Monitored targets", "15", "active generation"], ["Ready", "12", "current evidence"], ["Needs attention", "3", "missing or stale"], ["Observation mode", "2", "no changes applied"]],
      sections: [
        { title: "Evidence provenance", type: "facts", items: [["Source", "Muninn readiness projection"], ["Last agent snapshot", common.asOf], ["Generation", "gen-20260827-1015"], ["Coverage", "15 of 15 targets"]] },
        { title: "Target readiness", description: "Each row keeps decision, evidence gaps, and authority ceiling separate.", type: "table", columns: ["Target", "Decision", "Evidence", "Coverage gaps", "Authority ceiling"], rows: [
          [code("aks-platform-prod"), status("Ready", "success"), "4 / 4 axes", "None", "Deterministic fallback"],
          [code("payments-api"), status("Partial", "warning"), "3 / 4 axes", "Probe result stale", "Observation mode"],
          [code("ingress-public"), status("Blocked", "danger"), "2 / 4 axes", "Detector unavailable", "Human approval"],
          [code("inventory-worker"), status("Ready", "success"), "4 / 4 axes", "None", "Deployment"]
        ] }
      ]
    },
    "configuration-baselines": {
      group: "Operations",
      title: "Configuration baselines",
      subtitle: "Read-only baseline integrity, current drift, Knowledge evidence, and measured latency.",
      note: "This view cannot activate a baseline, approve, mitigate, or mutate cloud resources.",
      kpis: [["Active version", "v2.3.1", "reviewed baseline"], ["Drift decision", "No findings", "847 resources"], ["Citations", "142", "Knowledge evidence"], ["Total latency", "684 ms", "measured"]],
      sections: [
        { title: "Baseline", type: "facts", items: [["Scope", "platform-production"], ["Created", "2026-08-25T04:00:00Z"], ["Topology links", "1,942"], ["Unknown items", "7"]] },
        { title: "Baseline history", description: "Server-owned versions compared with the active baseline.", type: "table", columns: ["Version", "Lifecycle", "Created", "Resources", "Comparison", "Findings"], rows: [
          ["v2.3.1", status("Active", "success"), "Aug 25", "847", "Current", "0"],
          ["v2.3.0", status("Superseded"), "Aug 18", "839", "8 resources changed", "3"],
          ["v2.2.4", status("Archived"), "Aug 11", "831", "16 resources changed", "8"]
        ] },
        { title: "Review and safety", type: "facts", items: [["Weekly review", "Ready"], ["Preserved failed attempts", "1"], ["Mutation controls", "0"], ["Unsupported claims", "0"]] }
      ]
    },
    "processes": {
      group: "Operations",
      title: "Processes",
      subtitle: "Workflow runtime state and dynamic ontology-backed views.",
      kpis: [["Loaded processes", "8", "bounded page"], ["Running", "2", "current"], ["Waiting", "3", "external condition"], ["Completed", "3", "terminal"]],
      sections: [
        { title: "Find a process", type: "form", fields: [["Search", "text", "incident, workflow, or process id", 6], ["Status", "select", ["All statuses", "Running", "Waiting", "Completed"], 3], ["Owner", "select", ["All agents", "Huginn", "Heimdall", "Saga"], 3]], action: "Apply filters" },
        { title: "Process workspace", type: "workspace", listTitle: "Process instances", detailTitle: "Incident evidence review", list: [["proc-8f2a", "Running - Heimdall"], ["proc-771c", "Waiting - human approval"], ["proc-5d90", "Completed - Saga audited"]], detail: "The selected process is collecting current detector and topology evidence before the next governed decision.", facts: [["Current step", "verify_evidence"], ["Definition", "incident-review@4"], ["Revision", "12"], ["Target", "payments-api"]] }
      ]
    },
    "workflow-apps": {
      group: "Operations",
      title: "Workflow apps",
      subtitle: "Published workflow-specific read surfaces and run history.",
      kpis: [["Published apps", "8", "current catalog"], ["Healthy", "7", "source available"], ["Unavailable", "1", "projection missing"], ["Recent runs", "26", "24 hours"]],
      sections: [
        { title: "Published applications", type: "workspace", listTitle: "Workflow apps", detailTitle: "Change review", list: [["change-review", "workflow/change-safety"], ["incident-review", "workflow/resilience"], ["cost-review", "workflow/cost-governance"]], detail: "A bounded read surface for immutable workflow definition, current process state, and recovery history.", facts: [["Workflow", "change-safety@7"], ["View", "process/change-review"], ["Latest run", "Completed"], ["Compensation", "Not required"]] },
        { title: "Recent runs", type: "table", columns: ["Process", "App", "State", "Current step", "Updated"], rows: [
          [code("proc-61b8"), "Change review", status("Completed", "success"), "audit", "2 min ago"],
          [code("proc-72c1"), "Incident review", status("Running", "info"), "collect evidence", "18 sec ago"],
          [code("proc-81d0"), "Cost review", status("Waiting", "warning"), "review", "11 min ago"]
        ] }
      ]
    },
    "scheduler-runs": {
      group: "Operations",
      title: "Scheduler runs",
      subtitle: "Read-only dispatch evidence from the configured scheduler ledger.",
      note: "Published means broker dispatch was recorded. It does not prove task execution or outcome success.",
      kpis: [["Loaded attempts", "12", "current page"], ["Publish rate", "83%", "10 of 12"], ["Failed or lost", "2", "needs review"], ["Median close", "1.8 s", "claim to close"]],
      sections: [
        { title: "Load dispatch history", type: "form", fields: [["Task ID", "text", "task-20260827-0042", 8], ["Status", "select", ["All statuses", "Claimed", "Published", "Failed", "Lost"], 4]], action: "Load history" },
        { title: "Dispatch history", type: "table", columns: ["Run ID", "Task ID", "Status", "Scheduled", "Attempt", "Completed", "Error kind"], rows: [
          [code("run-04c2"), code("task-0042"), status("Published", "success"), "10:03:00Z", "1", "10:03:02Z", "-"],
          [code("run-04b9"), code("task-0041"), status("Failed", "danger"), "09:58:00Z", "2", "09:58:05Z", "broker_timeout"],
          [code("run-04a8"), code("task-0040"), status("Claimed", "info"), "09:54:00Z", "1", "-", "-"]
        ] }
      ]
    },
    "background-tasks": {
      group: "Operations",
      title: "Background tasks",
      subtitle: "Owner-scoped progress and results for detached read-only investigations.",
      note: "Inspect requests, outcomes, agent attribution, and progress. Task changes remain unavailable here.",
      kpis: [["Loaded tasks", "7", "owner scoped"], ["Running", "2", "within budget"], ["Succeeded", "4", "retained result"], ["Failed", "1", "terminal reason"]],
      sections: [
        { title: "Task history", type: "workspace", listTitle: "Background tasks", detailTitle: "Kubernetes readiness investigation", list: [["task-7a31", "Running - Huginn"], ["task-79f2", "Succeeded - Muninn"], ["task-774c", "Failed - Heimdall"]], detail: "Collect current stored evidence for the selected target and report only what the evidence establishes.", facts: [["Task ID", "task-7a31"], ["Accountable agent", "Huginn"], ["Execution worker", "background-task-coordinator"], ["Budget", "90 s / 8 tool calls"]] },
        { title: "Activity timeline", type: "timeline", items: [["10:12:01Z", "Investigation planned", "4 evidence reads allowed"], ["10:12:03Z", "Investigation started", "Inventory snapshot loaded"], ["10:12:08Z", "Progress", "Detector receipt verified"], ["10:12:14Z", "Progress", "Topology evidence pending"]] }
      ]
    },
    "automation-blueprints": {
      group: "Operations",
      title: "Automation blueprints",
      subtitle: "Evidence-backed recurring-work suggestions awaiting operator review.",
      note: "Suggestions are read-only. Accepting or materializing automation remains a governed workflow.",
      kpis: [["Proposed", "4", "awaiting review"], ["Accepted", "4", "reviewed"], ["Rejected", "3", "reason retained"], ["Candidate precision", "87%", "measured cohort"]],
      sections: [
        { title: "Blueprint candidates", type: "table", columns: ["Candidate", "State", "Task intent", "Schedule", "Scope", "Cost", "Confidence", "Expires"], rows: [
          [code("bp-2841"), status("Proposed", "info"), "Review stale detector evidence", "0 8 * * 1", "aks-platform", "$0.18", "92%", "Sep 10"],
          [code("bp-2817"), status("Accepted", "success"), "Summarize promotion blockers", "0 9 * * 5", "governance", "$0.09", "89%", "-"],
          [code("bp-2792"), status("Rejected", "danger"), "Retry failed deployment", "event", "production", "$0.31", "64%", "-"]
        ] },
        { title: "Isolation profile", type: "facts", items: [["Execution authority", "None"], ["Network", "Read-only allowlist"], ["Secrets", "Unavailable"], ["Materialization", "Governance PR"]] }
      ]
    },
    "scheduled-continuations": {
      group: "Operations",
      title: "Scheduled continuations",
      subtitle: "Scoped conversation anchors for exact scheduled results and evidence.",
      note: "A continuation preserves scope and evidence identity. It cannot create execution authority.",
      kpis: [["Anchors", "5", "bounded result"], ["Active", "3", "not expired"], ["Archived", "2", "retained"], ["Evidence refs", "18", "exact receipts"]],
      sections: [
        { title: "Continuation anchors", type: "table", columns: ["Result", "State", "Scope", "Window", "Origin", "Evidence", "Digest", "Expires"], rows: [
          ["Weekly detector review", status("Active", "success"), "aks-platform", "7 days", "Teams / thread-42", "6", code("b41c8e90"), "Sep 03"],
          ["Cost anomaly follow-up", status("Active", "success"), "cost-governance", "24 hours", "Web / conv-18", "4", code("82d1f7aa"), "Aug 29"],
          ["Promotion summary", status("Archived"), "governance", "30 days", "Slack / thread-9", "8", code("1ee09d6c"), "Aug 25"]
        ] }
      ]
    },
    "conversation-delivery": {
      group: "Operations",
      title: "Conversation delivery",
      subtitle: "Reply latency, retries, duplicate risk, abandonment, and adapter health.",
      note: "Delivery state is transport evidence. It does not validate the operational content of a reply.",
      kpis: [["Deliveries", "1,247", "30 days"], ["P95 latency", "340 ms", "acknowledged"], ["Duplicate risk", "12", "deduplicated"], ["Abandoned", "4", "terminal"]],
      sections: [
        { title: "Delivery states", type: "bars", items: [["Delivered", 92, "1,147"], ["Ambiguous", 5, "63"], ["Abandoned", 2, "24"], ["Failed", 1, "13"]] },
        { title: "Adapter circuit breakers", type: "table", columns: ["Adapter", "State", "Retries", "Last success", "Oldest pending"], rows: [
          ["Web", status("Closed", "success"), "3", "12 sec ago", "-"],
          ["Teams", status("Half-open", "warning"), "18", "4 min ago", "2 min"],
          ["Slack", status("Closed", "success"), "7", "31 sec ago", "-"]
        ] }
      ]
    },
    "browser-evidence": {
      group: "Evidence",
      title: "Browser evidence",
      subtitle: "Immutable redacted evidence from allowlisted browser captures.",
      note: "Captured payloads remain outside this metadata-only view. Untrusted content never becomes an instruction.",
      kpis: [["Artifacts", "847", "retained metadata"], ["Expired", "142", "policy applied"], ["Redactions", "2,318", "before retention"], ["Isolation verified", "98%", "measured"]],
      sections: [
        { title: "Evidence custody", type: "table", columns: ["Artifact", "Policy", "Origin", "Captured", "Expires", "Selectors", "Redactions", "Isolation", "Legal hold"], rows: [
          [code("bev-82a1"), code("browser-redaction-v4"), "Allowlisted host", "Aug 27 10:04", "Sep 26", "18", "7", status("Verified", "success"), "No"],
          [code("bev-819c"), code("browser-redaction-v4"), "Allowlisted host", "Aug 27 09:48", "Sep 26", "11", "3", status("Verified", "success"), "Yes"],
          [code("bev-80f2"), code("browser-redaction-v3"), "Allowlisted host", "Aug 26 21:17", "Expired", "9", "2", status("Unavailable", "warning"), "No"]
        ] },
        { title: "Boundary", type: "facts", items: [["Captured content", "Not exposed"], ["Prompt-injection findings", "3 metadata records"], ["Source URL", "Redacted"], ["Execution authority", "None"]] }
      ]
    },
    "forecast-learning": {
      group: "Evidence",
      title: "Forecast learning",
      subtitle: "Prediction closure, miss origin, publication, and retention evidence.",
      kpis: [["Episodes", "342", "retained"], ["Closed", "298", "87%"], ["Overdue", "6", "needs closure"], ["Complete evidence", "89%", "measured"]],
      sections: [
        { title: "Outcome distribution", type: "table", columns: ["Outcome", "Miss origin", "Count", "Share"], rows: [
          ["Correct", "-", "244", "71%"],
          ["Missed signal", "observation", "38", "11%"],
          ["Wrong scope", "context selection", "27", "8%"],
          ["Held for review", "insufficient evidence", "33", "10%"]
        ] },
        { title: "Publication and retention debt", type: "facts", items: [["Publication pending", "5"], ["Oldest pending", "19 hours"], ["Dead-lettered", "1"], ["Retention overdue", "2"]] }
      ]
    },
    "conversation-search": {
      group: "Evidence",
      title: "Conversation search",
      subtitle: "Find authorized turns across prior sessions.",
      note: "Search results are authorization filtered. Context loads only for the selected result.",
      kpis: [["Results", "23", "bounded page"], ["Sessions", "9", "authorized"], ["Context loaded", "3", "operator selected"], ["Unavailable", "1", "source gap"]],
      sections: [
        { title: "Search conversations", type: "form", fields: [["Query", "search", "promotion blocker evidence", 7], ["Role", "select", ["All roles", "Operator", "Assistant"], 2], ["Mode", "select", ["Full text", "Semantic", "Hybrid"], 3]], action: "Search" },
        { title: "Results", type: "cards", items: [
          ["Promotion blockers for database failover", "Assistant - Aug 27, 09:42", "The evidence shows two blocked safeguards and one unavailable rollback receipt."],
          ["Why is detector readiness partial?", "Operator - Aug 26, 18:04", "The target is missing a current probe receipt. No absence claim was made."],
          ["Cost anomaly evidence", "Assistant - Aug 25, 14:21", "Attribution is incomplete for two shared services."]
        ] }
      ]
    },
    "conversation-assurance": {
      group: "Evidence",
      title: "Conversation assurance",
      subtitle: "Evidence-based answer review, model agreement, cost, and disputes.",
      kpis: [["Assessments", "156", "30 days"], ["Passed", "134", "85.9%"], ["Failed", "15", "reviewed"], ["Disputed", "7", "operator raised"]],
      sections: [
        { title: "Assessment queue", type: "workspace", listTitle: "Reviewed turns", detailTitle: "Assessment turn-8a31", list: [["turn-8a31", "Incomplete - disputed"], ["turn-89f2", "Correct - agreed"], ["turn-87c4", "Hallucination - failed"]], detail: "The answer cited the correct incident but omitted the stale evidence limitation from the primary response.", facts: [["Decision", "Incomplete"], ["Model agreement", "67%"], ["Cost", "$0.012"], ["Dispute", "Open"]] },
        { title: "Recent decisions", type: "table", columns: ["Turn", "Decision", "Agreement", "Cost", "Dispute"], rows: [
          [code("turn-8a31"), status("Incomplete", "warning"), "67%", "$0.012", "Open"],
          [code("turn-89f2"), status("Correct", "success"), "100%", "$0.009", "No"],
          [code("turn-87c4"), status("Unsupported claim", "danger"), "33%", "$0.015", "Resolved"]
        ] }
      ]
    },
    "reports": {
      group: "Evidence",
      title: "Reports",
      subtitle: "Declarative live boards rendered from the report catalog.",
      note: "Rendered views read exact report definitions and bounded variables. They do not execute workflow steps.",
      kpis: [["Templates", "5", "current catalog"], ["Widgets", "18", "allowlisted"], ["Sources ready", "4 / 5", "one unavailable"], ["Last render", "684 ms", "measured"]],
      sections: [
        { title: "Render a report", type: "form", fields: [["Report", "select", ["Weekly operations review", "Control assurance", "Cost governance"], 4], ["Window", "select", ["Last 7 days", "Last 30 days"], 4], ["Scope", "text", "platform-production", 4]], action: "Render report" },
        { title: "Weekly operations review", type: "cards", items: [
          ["Operating posture", "Measured", "73% auto-resolution with 8 pending approvals."],
          ["Control assurance", "Attention", "One guard remains below its evidence threshold."],
          ["Evidence freshness", "Current", "Four sources current; one source unavailable."]
        ] }
      ]
    },
    "architecture": {
      group: "Governance",
      title: "Architecture",
      subtitle: "Deployed resources, boundaries, and dependencies.",
      note: "The map renders stored topology only. Layout, icons, and focus controls are presentation, not evidence.",
      kpis: [["Resources", "324", "active generation"], ["Links", "512", "typed"], ["Boundaries", "3", "observed"], ["Unknown paths", "7", "coverage incomplete"]],
      sections: [
        { title: "Observed network path", description: "Focus, camera, and export controls do not change the underlying topology.", type: "network", items: [["Internet", "External"], ["Front Door", "Edge"], ["Private Link", "Boundary"], ["Operator API", "Service"], ["PostgreSQL", "Data"]] },
        { title: "Selected relationship", type: "facts", items: [["Source", "Front Door"], ["Link type", "routes_to"], ["Target", "Operator API"], ["Evidence", "Current configuration"]] },
        { title: "Related view", type: "cards", items: [["Service map", "Interactive topology study", "Open the detailed 2.5D service map for path tracing and inspector behavior."]] }
      ]
    },
    "capabilities": {
      group: "Governance",
      title: "Capabilities",
      subtitle: "Declared capability contracts, side-effect classes, roles, and default modes.",
      note: "The catalog describes eligibility. It grants no role, approval, or execution authority.",
      kpis: [["Declared", "142", "exact release"], ["Read-only", "89", "side effect class"], ["Observation mode", "23", "no changes applied"], ["Role restricted", "8", "current principal"]],
      sections: [
        { title: "Capability declarations", type: "table", columns: ["Capability", "Category", "Summary", "Side effect", "Mode", "Required role"], rows: [
          [code("inventory.read"), "Observation", "Read bounded inventory projection", status("Read", "info"), status("Enforcement", "success"), "Reader"],
          [code("impact.simulate"), "Safety", "Compute stored-direction impact scope", status("Simulate", "info"), status("Enforcement", "success"), "Operator"],
          [code("resource.restart"), "Execution", "Restart an approved workload", status("Execute", "warning"), status("Observation", "warning"), "Executor"]
        ] }
      ]
    },
    "skills": {
      group: "Governance",
      title: "Skills",
      subtitle: "Installed runtime skill metadata, dependencies, eligibility, and load diagnostics.",
      note: "Skill eligibility describes runtime composition. Loading a skill does not grant authority.",
      kpis: [["Installed", "23", "current bundle"], ["Enabled", "20", "eligible"], ["Missing tools", "3", "blocked"], ["Diagnostics", "2", "needs review"]],
      sections: [
        { title: "Runtime skills", type: "table", columns: ["Skill", "Version", "Status", "Required tools", "Allowed agents", "Eligibility"], rows: [
          [code("azure-inventory"), "2.4.1", status("Enabled", "success"), "az, jq", "Huginn", "Eligible"],
          [code("cost-analysis"), "1.8.0", status("Enabled", "success"), "python", "Bragi, Muninn", "Eligible"],
          [code("kubernetes-debug"), "0.9.3", status("Blocked", "warning"), "kubectl", "Huginn", "Tool missing"]
        ] },
        { title: "Bundles and diagnostics", type: "facts", items: [["Core bundle", "Compatible"], ["Operations bundle", "Compatible"], ["Optional bundle", "4 incompatibilities"], ["Load failures", "2 retained"]] }
      ]
    },
    "documents": {
      group: "Evidence",
      title: "Documents",
      subtitle: "Upload, scan, protect, and index governed documents.",
      note: "This specimen demonstrates the bounded ingestion form. It does not upload or retain a file.",
      kpis: [["Collections", "4", "authorized"], ["Processing", "1", "scan complete"], ["Ready", "2", "indexed"], ["Failed", "1", "reason visible"]],
      sections: [
        { title: "Prepare ingestion", type: "form", fields: [["Collection", "select", ["Operational handovers", "Runbooks", "Architecture reviews"], 4], ["Purpose", "select", ["Knowledge grounding", "Ownership handover"], 4], ["Storage mode", "select", ["Protected", "Temporary"], 4], ["File", "file", "", 8], ["Consent", "checkbox", "I confirm this document is authorized for ingestion.", 4]], action: "Start governed upload" },
        { title: "Recent ingestion", type: "table", columns: ["Document", "Collection", "State", "Scan", "Protection", "Updated"], rows: [
          ["handover-platform.pdf", "Operational handovers", status("Ready", "success"), "Clean", "Protected", "2 min ago"],
          ["network-review.docx", "Architecture reviews", status("Processing", "info"), "Clean", "Pending index", "18 sec ago"],
          ["legacy-runbook.pdf", "Runbooks", status("Failed", "danger"), "Rejected", "Not stored", "14 min ago"]
        ] }
      ]
    },
    "context-selection-comparisons": {
      group: "Governance",
      title: "Context policy comparisons",
      subtitle: "Baseline and shadow context-selection evidence.",
      note: "Comparisons are read-only evaluations. Candidate policy output cannot change production selection.",
      kpis: [["Comparisons", "47", "current cohort"], ["Successful", "44", "93.6%"], ["Failures", "3", "reason retained"], ["Mutation controls", "0", "read only"]],
      sections: [
        { title: "Policy evaluations", type: "table", columns: ["Evaluation", "Baseline", "Candidate", "Tokens", "Overlap", "Omissions", "Pinned", "Latency", "Failure"], rows: [
          [code("ctx-41a8"), code("baseline-v7"), code("candidate-v8"), "4,200 / 3,800", "94%", "0", status("Preserved", "success"), "84 ms", "-"],
          [code("ctx-4092"), code("baseline-v7"), code("candidate-v8"), "3,880 / 3,510", "91%", "1", status("Preserved", "success"), "78 ms", "-"],
          [code("ctx-3ff1"), code("baseline-v7"), code("candidate-v8"), "-", "-", "-", status("Missing", "danger"), "91 ms", "source_unavailable"]
        ] }
      ]
    },
    "scope": {
      group: "Governance",
      title: "Scope",
      subtitle: "Effective monitoring and action scope with IAM boundaries.",
      note: "Monitoring scope never implies action authority. The executor boundary is evaluated independently.",
      kpis: [["Monitoring entries", "24", "effective"], ["Action entries", "18", "more restrictive"], ["Subscriptions", "3", "authorized"], ["Executor boundary", "1", "isolated"]],
      sections: [
        { title: "Effective scope", type: "table", columns: ["Subscription", "Axis", "State", "Resource group", "Address"], rows: [
          [code("sub-platform"), "Monitoring", status("Included", "success"), "rg-platform-prod", code("/subscriptions/.../rg-platform-prod")],
          [code("sub-platform"), "Action", status("Included", "warning"), "rg-platform-prod", code("/subscriptions/.../rg-platform-prod")],
          [code("sub-shared"), "Action", status("Excluded", "danger"), "rg-shared-data", code("/subscriptions/.../rg-shared-data")]
        ] },
        { title: "Boundary evidence", type: "facts", items: [["Policy release", "scope-v12"], ["IAM snapshot", "current"], ["Action target locks", "18"], ["Wildcard grants", "0"]] }
      ]
    },
    "labs": {
      group: "Labs",
      title: "Labs",
      subtitle: "Development-only UI experiments.",
      note: "Labs are static design references. They are not production features or operational evidence.",
      kpis: [["Experiments", "11", "static"], ["Interactive", "7", "local only"], ["Production authority", "0", "none"], ["Shared tokens", "100%", "Calm Slate"]],
      sections: [
        { title: "Design studies", type: "cards", items: [
          ["Component gallery", "23 sections", "Shared controls, feedback states, charts, tables, and responsive references."],
          ["Command Deck studies", "Conversation", "Transcript, evidence, source, and decision presentation experiments."],
          ["Navigation study", "Shell", "Compact hierarchy, active-state, and constrained-viewport exploration."]
        ] }
      ]
    },
    "settings-runtime": {
      group: "Settings",
      title: "Runtime policies",
      subtitle: "Audited runtime behavior, budgets, freshness, retention, and logging.",
      note: "Overrides are revisioned settings. This static specimen does not save or change runtime behavior.",
      kpis: [["Settings", "6", "allowlisted"], ["Overrides", "2", "current principal"], ["Restart required", "1", "pending"], ["Unavailable", "1", "source gap"]],
      sections: [
        { id: "runtime-policy-settings", title: "Runtime policy settings", type: "table", columns: ["Setting", "Environment value", "Override", "Status", "Effect"], rows: [
          ["Evidence freshness", "15 min", "10 min", status("Overridden", "info"), "Next request"],
          ["Investigation budget", "90 s", "-", status("Inherited", "success"), "Current"],
          ["Audit retention", "365 days", "730 days", status("Restart required", "warning"), "After restart"],
          ["Verbose provider logs", "Off", "-", status("Unavailable", "neutral"), "No change"]
        ] },
        { id: "runtime-override-editor", title: "Edit an allowlisted override", type: "form", fields: [["Setting", "select", ["Evidence freshness", "Investigation budget", "Audit retention"], 5], ["Override value", "text", "10 min", 4], ["Revision", "text", "12", 3]], action: "Save revisioned override" }
      ]
    }
  };

  function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, function (character) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[character];
    });
  }

  function renderCell(value) {
    if (value && typeof value === "object") {
      if (value.kind === "status") {
        return '<span class="cp-status is-' + escapeHtml(value.tone) + '">' + escapeHtml(value.text) + "</span>";
      }
      if (value.kind === "code") return '<code class="cp-code">' + escapeHtml(value.text) + "</code>";
    }
    return escapeHtml(value);
  }

  function renderTable(section) {
    var headings = section.columns.map(function (column) {
      return '<th scope="col">' + escapeHtml(column) + "</th>";
    }).join("");
    var rows = section.rows.map(function (row) {
      return "<tr>" + row.map(function (cell, index) {
        return '<td data-label="' + escapeHtml(section.columns[index]) + '">' + renderCell(cell) + "</td>";
      }).join("") + "</tr>";
    }).join("");
    return '<div class="cp-table-wrap"><table class="cp-table"><caption>' +
      escapeHtml(section.description || section.title) + "</caption><thead><tr>" + headings +
      "</tr></thead><tbody>" + rows + "</tbody></table></div>";
  }

  function renderFacts(items) {
    return '<dl class="cp-facts">' + items.map(function (item) {
      return "<div><dt>" + escapeHtml(item[0]) + "</dt><dd>" + renderCell(item[1]) + "</dd></div>";
    }).join("") + "</dl>";
  }

  function renderCards(items) {
    return '<div class="cp-card-grid">' + items.map(function (item, index) {
      return '<article class="cp-card' + (index === 0 ? " is-selected" : "") + '"><div class="cp-card-head"><h3>' +
        escapeHtml(item[0]) + '</h3><span class="cp-status is-' + (index === 0 ? "info" : "neutral") + '">' +
        escapeHtml(item[1]) + "</span></div><p>" + escapeHtml(item[2]) + "</p></article>";
    }).join("") + "</div>";
  }

  function renderForm(section) {
    var fields = section.fields.map(function (field, index) {
      var id = "cp-field-" + index;
      var span = field[3] || 4;
      var control;
      if (field[1] === "select") {
        control = '<select class="cs-control-select" id="' + id + '">' + field[2].map(function (option) {
          return "<option>" + escapeHtml(option) + "</option>";
        }).join("") + "</select>";
      } else if (field[1] === "checkbox") {
        control = '<label class="cp-checkbox"><input id="' + id + '" type="checkbox" /> ' + escapeHtml(field[2]) + "</label>";
      } else {
        control = '<input class="cs-control-input" id="' + id + '" type="' + escapeHtml(field[1]) + '"' +
          (field[2] ? ' placeholder="' + escapeHtml(field[2]) + '"' : "") + " />";
      }
      return '<div class="cp-field" style="--cp-field-span:' + span + '"><label for="' + id + '">' +
        escapeHtml(field[0]) + "</label>" + control + "</div>";
    }).join("");
    return '<form class="cp-form" data-cp-form><p class="cp-form-note">Synthetic controls mirror the Console form and do not submit data.</p>' +
      fields + '<div class="cp-form-actions"><button class="cs-control-button is-primary" type="submit">' +
      escapeHtml(section.action) + "</button></div></form>";
  }

  function renderWorkspace(section) {
    return '<div class="cp-workspace"><aside class="cp-workspace-list"><h3>' +
      escapeHtml(section.listTitle) + "</h3><ul>" + section.list.map(function (item, index) {
        return '<li class="' + (index === 0 ? "is-selected" : "") + '"><strong>' + escapeHtml(item[0]) +
          "</strong><small>" + escapeHtml(item[1]) + "</small></li>";
      }).join("") + '</ul></aside><article class="cp-workspace-detail"><h3>' + escapeHtml(section.detailTitle) +
      '</h3><div class="cp-workspace-body"><p>' + escapeHtml(section.detail) + "</p>" +
      renderFacts(section.facts) + "</div></article></div>";
  }

  function renderTimeline(items) {
    return '<ol class="cp-timeline">' + items.map(function (item) {
      return "<li><time>" + escapeHtml(item[0]) + "</time><div><strong>" + escapeHtml(item[1]) +
        "</strong><small>" + escapeHtml(item[2]) + "</small></div></li>";
    }).join("") + "</ol>";
  }

  function renderBars(items) {
    return '<div class="cp-bars">' + items.map(function (item) {
      return '<div class="cp-bar-row"><span>' + escapeHtml(item[0]) + '</span><div class="cp-bar-track"><span style="--cp-value:' +
        Number(item[1]) + '%"></span></div><strong>' + escapeHtml(item[2]) + "</strong></div>";
    }).join("") + "</div>";
  }

  function renderNetwork(items) {
    return '<div class="cp-network" role="img" aria-label="Illustrative stored topology path">' +
      items.map(function (item) {
        return '<span class="cp-node"><strong>' + escapeHtml(item[0]) + "</strong><small>" +
          escapeHtml(item[1]) + "</small></span>";
      }).join("") + "</div>";
  }

  function renderTabs(section) {
    var tabs = section.tabs.map(function (tab, index) {
      return '<button class="cp-tab" id="cp-tab-' + index + '" type="button" role="tab" aria-controls="cp-panel-' +
        index + '" aria-selected="' + (index === 0 ? "true" : "false") + '">' + escapeHtml(tab.label) + "</button>";
    }).join("");
    var panels = section.tabs.map(function (tab, index) {
      return '<div class="cp-tab-panel" id="cp-panel-' + index + '" role="tabpanel" aria-labelledby="cp-tab-' +
        index + '"' + (index === 0 ? "" : " hidden") + ">" + renderTable(tab) + "</div>";
    }).join("");
    return '<div class="cp-tabs" role="tablist" aria-label="' + escapeHtml(section.title) + '">' + tabs + "</div>" + panels;
  }

  function renderSection(section) {
    var body = "";
    if (section.type === "table") body = renderTable(section);
    if (section.type === "facts") body = renderFacts(section.items);
    if (section.type === "cards") body = renderCards(section.items);
    if (section.type === "form") body = renderForm(section);
    if (section.type === "workspace") body = renderWorkspace(section);
    if (section.type === "timeline") body = renderTimeline(section.items);
    if (section.type === "bars") body = renderBars(section.items);
    if (section.type === "network") body = renderNetwork(section.items);
    if (section.type === "tabs") body = renderTabs(section);
    return '<section class="cp-section"' + (section.id ? ' id="' + escapeHtml(section.id) + '"' : "") + '><header class="cp-section-head"><div><h2>' +
      escapeHtml(section.title) + "</h2>" + (section.description ? "<p>" + escapeHtml(section.description) + "</p>" : "") +
      "</div>" + (section.count ? '<span class="cp-section-count">' + escapeHtml(section.count) + "</span>" : "") +
      "</header>" + body + "</section>";
  }

  function mount() {
    var root = document.querySelector("[data-console-parity-page]");
    if (!root) return;
    var pageId = document.body.getAttribute("data-console-page");
    var page = pages[pageId];
    if (!page) {
      root.innerHTML = '<div class="cs-empty"><strong>Mock unavailable</strong>No Console parity specification exists for this page.</div>';
      return;
    }
    document.title = page.title + " - FDAI Console";
    root.innerHTML = '<header class="cp-header"><div class="cp-header-copy"><h1>' +
      escapeHtml(page.title) + "</h1><p>" + escapeHtml(page.subtitle) +
      '</p></div><div class="cp-header-meta"><span>Synthetic specimen</span><strong>' +
      escapeHtml(common.asOf) + "</strong></div></header>" +
      '<div class="cs-readonly-banner"><strong>Read-only specimen.</strong>' +
      escapeHtml(page.note || common.syntheticNote) + "</div>" +
      '<section class="cp-kpis" aria-label="' + escapeHtml(page.title) + ' summary" style="--cp-kpi-columns:' +
      Math.min(4, page.kpis.length) + '">' + page.kpis.map(function (item) {
        return '<article class="cp-kpi"><span>' + escapeHtml(item[0]) + "</span><strong>" +
          escapeHtml(item[1]) + "</strong><small>" + escapeHtml(item[2]) + "</small></article>";
      }).join("") + "</section>" + page.sections.map(renderSection).join("");

    root.querySelectorAll("[data-cp-form]").forEach(function (form) {
      form.addEventListener("submit", function (event) { event.preventDefault(); });
    });
    root.querySelectorAll(".cp-tab").forEach(function (tab) {
      tab.addEventListener("click", function () {
        root.querySelectorAll(".cp-tab").forEach(function (candidate) {
          candidate.setAttribute("aria-selected", String(candidate === tab));
        });
        root.querySelectorAll(".cp-tab-panel").forEach(function (panel) {
          panel.hidden = panel.id !== tab.getAttribute("aria-controls");
        });
      });
    });
  }

  window.FDAI_CONSOLE_PARITY_PAGES = pages;
  document.addEventListener("DOMContentLoaded", mount);
})();
