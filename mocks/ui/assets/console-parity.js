(function () {
  "use strict";

  function status(text, tone) {
    return { kind: "status", text: text, tone: tone || "neutral" };
  }

  function code(text, href) {
    return { kind: "code", text: text, href: href };
  }

  function link(text, href) {
    return { kind: "link", text: text, href: href };
  }

  var common = {
    syntheticNote: "Illustrative data. Values show the intended Console structure and make no operational claim.",
    asOf: "2026-08-27T10:15:00Z"
  };

  function knowledgeSourcePage(sourceId, title, identityModel) {
    return {
      renderer: "knowledge",
      variant: "connector",
      sourceId: sourceId,
      group: "Knowledge",
      title: title,
      subtitle: "Read-only source readiness, repository coverage, and bounded synchronization evidence.",
      note: "Source connectivity authorizes observation only. It grants no approval or execution authority.",
      identityModel: identityModel
    };
  }

  var pages = {
    "knowledge": {
      renderer: "knowledge",
      variant: "overview",
      group: "Knowledge",
      title: "Knowledge overview",
      subtitle: "Governed documents and external sources available for evidence-grounded retrieval.",
      note: "Availability, authorization, freshness, and completeness remain independent. Missing source evidence is never inferred."
    },
    "github": knowledgeSourcePage("github", "GitHub", "App installation"),
    "gitlab": knowledgeSourcePage("gitlab", "GitLab", "Project token broker"),
    "azure-devops": knowledgeSourcePage("azure-devops", "Azure DevOps", "Workload identity"),
    "assurance-twin": {
      group: "Evidence",
      title: "Assurance Twin",
      subtitle: "Posture reports, ambient change reviews, and evidence gaps from independent assessment.",
      note: "Twin output is read-only evidence. A blocked or review verdict cannot approve, promote, or execute an action.",
      kpis: [["Posture reports", "6", "current scope"], ["Blocked", "1", "critical finding"], ["Needs review", "2", "evidence gaps"], ["Ambient reviews", "14", "30-day window"]],
      sections: [
        {
          title: "Posture reports",
          description: "Independent assessment keeps verdict, scope, freshness, and action effect explicit.",
          type: "table",
          columns: ["Scope", "Verdict", "Mode", "Findings", "Freshness", "Generated"],
          rows: [
            [code("platform-production"), status("Blocked", "danger"), "Enforce", "3", status("Fresh", "success"), "10:12Z"],
            [code("shared-services"), status("Needs review", "warning"), "Shadow", "2", status("Stale", "warning"), "09:48Z"],
            [code("sandbox"), status("Clear", "success"), "Shadow", "0", status("Fresh", "success"), "09:31Z"]
          ]
        },
        {
          title: "Selected ambient review",
          type: "workspace",
          listTitle: "Recent reviews",
          detailTitle: "owner/repository#42",
          list: [["owner/repository#42", "Blocked - 2 findings"], ["owner/repository#41", "Clear - no findings"], ["owner/repository#39", "Needs review - stale evidence"]],
          detail: "The independent review found a high-severity scope expansion and retained the exact evidence references used for the verdict.",
          facts: [["Mode", "Enforce"], ["Verdict", status("Blocked", "danger")], ["Findings", "2"], ["Evidence freshness", status("Fresh", "success")], ["Action effect", "Change remains blocked"], ["Audit", link("Review evidence", "audit.html?kind=assurance-twin")]]
        }
      ]
    },
    "detection-readiness": {
      group: "Operations",
      title: "Detection coverage",
      subtitle: "Evaluation coverage across supported API, Kubernetes, AI, database, and gateway resources.",
      note: "Coverage is read-only evaluation evidence. A no-finding result is not a health or readiness claim.",
      kpis: [["Candidate resources", "7", "supported inventory"], ["Selected resources", "5", "latest attempt"], ["Evaluated resources", "4", "completed analysis"], ["Findings", "1", "latest attempt"]],
      sections: [
        { title: "Technical provenance", type: "facts", items: [["Source", "Analyzer run receipt"], ["Latest attempt", common.asOf], ["Coverage schema", code("1.1.0")], ["Authority", "None"]] },
        { title: "Coverage by resource type", description: "Each row keeps candidates, evaluations, holds, findings, and errors separate.", type: "table", columns: ["Resource type", "Candidates", "Selected", "Evaluated", "Held", "Findings", "Errors"], rows: [
          ["API gateway", "1", "1", "1", "0", "0", "0"],
          ["Kubernetes cluster", "2", "1", "1", "1", "1", "0"],
          ["LLM endpoint", "1", "1", "1", "0", "0", "0"],
          ["MySQL server", "2", "1", "0", "1", "0", "1"],
          ["Application Gateway", "1", "1", "1", "0", "0", "0"]
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
    "audit": {
      group: "Evidence",
      title: "Audit log",
      subtitle: "Reconstruct decisions, authority, dispatch, verification, rollback, and terminal outcomes from one append-only ledger.",
      note: "Ledger rows are immutable evidence references. Search, filtering, export, and judge-only replay never re-execute an action.",
      kpis: [["Ledger entries", "1,842", "24-hour bounded window"], ["Terminally closed", "99.6%", "effect or no-op recorded"], ["Human review", "16%", "HIL, abstain, or deny"], ["Rollback paths", "7", "all linked and tested"]],
      sections: [
        { id: "audit-query", title: "Query the ledger", description: "Narrow immutable records without changing their order or interpretation.", type: "form", fields: [["Search", "search", "Event, correlation, rule, actor, or idempotency key", 3], ["Decision", "select", ["All decisions", "Auto", "HIL", "Abstain", "Deny", "Rollback"], 2], ["Mode", "select", ["All modes", "Shadow", "Enforce", "HIL"], 2], ["Tier", "select", ["All tiers", "T0", "T1", "T2"], 1], ["Window", "select", ["Last 24 hours", "Last 7 days", "Last 30 days"], 2]], action: "Apply query", inlineAction: true, actionSpan: 2 },
        { title: "Audit ledger", description: "Newest first. Each identity opens the narrowest evidence view for that record.", type: "table", columns: ["Recorded", "Event / rule", "Tier", "Decision", "Mode", "Actor", "Effect verification"], rows: [
          ["10:15:04Z", code("storage.public-blob.deny", "rule-trace.html?correlation=evt-storage-104"), "T0", status("PR opened", "success"), status("Enforce", "info"), "executor / workload identity", link("Observed", "audit.html?record=aud-104")],
          ["10:14:52Z", code("compute.autoscale.floor.min-2", "rule-trace.html?correlation=evt-scale-103"), "T1", status("Learned action reused", "success"), status("Shadow", "neutral"), "shadow judge", link("No effect expected", "audit.html?record=aud-103")],
          ["10:14:31Z", code("network.firewall.orphan-rule", "rca.html?correlation=evt-network-102"), "T2", status("Abstain to HIL", "warning"), status("HIL", "warning"), "quality gate", link("No-op sealed", "audit.html?record=aud-102")],
          ["10:13:58Z", code("cost.rightsize.candidate", "rule-trace.html?correlation=evt-cost-101"), "T0", status("Compliant no-op", "neutral"), status("No action", "neutral"), "trust router", link("No-op sealed", "audit.html?record=aud-101")],
          ["10:13:21Z", code("k8s.rbac.cluster-admin.narrow", "rule-trace.html?correlation=evt-rbac-100"), "T0", status("Denied by policy", "danger"), status("Deny", "danger"), "risk gate", link("No dispatch", "audit.html?record=aud-100")],
          ["10:11:03Z", code("governance.exemption.review", "rules.html#rules-overrides"), "-", status("Override revised", "info"), status("Enforce", "info"), "two human principals", link("Revision observed", "audit.html?record=aud-099")],
          ["09:41:52Z", code("compute.autoscale.raise-floor", "rca.html?correlation=evt-scale-098"), "T2", status("Rollback verified", "warning"), status("Enforce", "info"), "executor / workload identity", link("Recovered", "audit.html?record=aud-098")]
        ] },
        { title: "Selected record", description: "Decision and effect evidence remain distinct through terminal closure.", type: "workspace", listTitle: "Related records", detailTitle: "Audit record aud-104", list: [["aud-104", "Intent and eligibility"], ["aud-105", "Dispatch accepted"], ["aud-106", "Effect independently observed"], ["aud-107", "Terminal closure"]], detail: "A deterministic rule proposed a reversible configuration change. Policy, dry-run, target lock, idempotency, approval, and rollback references were captured before dispatch; independent observation closed the expected effect.", facts: [["Correlation", code("corr-storage-031")], ["Idempotency", code("idem-storage-031")], ["Rollback", code("pr-revert:2148")], ["Expected effect", "Public access disabled"], ["Observation source", "Provider configuration"], ["Terminal state", status("Verified", "success")]] },
        { title: "Ledger guarantees", description: "Evidence semantics that remain true for every filtered or exported view.", type: "facts", items: [["Ordering", "Per-target serialized"], ["Replay", "Judge only; no execution"], ["Retention", "Policy controlled"], ["Sensitive values", "Redacted before persistence"], ["Authority", "Actor and executor remain distinct"], ["Integrity", "Append-only terminal closure"]] }
      ]
    },
    "browser-evidence": {
      group: "Evidence",
      title: "Browser evidence",
      subtitle: "Immutable redacted evidence from allowlisted browser captures.",
      note: "Captured payloads remain outside this metadata-only view. Untrusted content never becomes an instruction.",
      kpis: [["Artifacts", "847", "retained metadata"], ["Expired", "142", "policy applied"], ["Redactions", "2,318", "before retention"], ["Isolation verified", "98%", "measured"]],
      sections: [
        { id: "browser-evidence-query", title: "Review captured evidence", description: "Search metadata without exposing captured payloads.", type: "form", fields: [["Artifact or policy", "search", "Artifact id or redaction policy", 6], ["Custody", "select", ["All states", "Retained", "Expired", "Legal hold"], 3], ["Isolation", "select", ["All results", "Verified", "Unavailable"], 3]], action: "Apply filters" },
        { title: "Evidence custody", type: "table", columns: ["Artifact", "Policy", "Origin", "Captured", "Expires", "Selectors", "Redactions", "Isolation", "Legal hold"], rows: [
          [code("bev-82a1", "audit.html?artifact=bev-82a1"), code("browser-redaction-v4"), "Allowlisted host", "Aug 27 10:04", "Sep 26", "18", "7", status("Verified", "success"), "No"],
          [code("bev-819c"), code("browser-redaction-v4"), "Allowlisted host", "Aug 27 09:48", "Sep 26", "11", "3", status("Verified", "success"), "Yes"],
          [code("bev-80f2"), code("browser-redaction-v3"), "Allowlisted host", "Aug 26 21:17", "Expired", "9", "2", status("Unavailable", "warning"), "No"]
        ] },
        { title: "Selected artifact", type: "workspace", listTitle: "Custody chain", detailTitle: "Artifact bev-82a1", list: [["10:04:11Z", "Capture admitted"], ["10:04:12Z", "Redaction completed"], ["10:04:12Z", "Isolation verified"], ["10:04:13Z", "Metadata sealed"]], detail: "The artifact remains outside this metadata-only surface. Selectors, redaction counts, policy revision, and isolation outcome are retained for reproducible review.", facts: [["Policy", code("browser-redaction-v4")], ["Payload visibility", "Not exposed"], ["Origin", "Allowlisted host"], ["Redactions", "7"], ["Isolation", status("Verified", "success")], ["Audit", link("Open record", "audit.html?artifact=bev-82a1")]] },
        { title: "Boundary", type: "facts", items: [["Captured content", "Not exposed"], ["Prompt-injection findings", "3 metadata records"], ["Source URL", "Redacted"], ["Execution authority", "None"], ["Retention policy", "30 days"], ["Legal holds", "12"]] }
      ]
    },
    "forecast-learning": {
      group: "Evidence",
      title: "Forecast learning",
      subtitle: "Prediction closure, miss origin, publication, and retention evidence.",
      kpis: [["Episodes", "342", "retained"], ["Closed", "298", "87%"], ["Overdue", "6", "needs closure"], ["Complete evidence", "89%", "measured"]],
      sections: [
        { title: "Learning closure", description: "Compare predictions only after the authoritative outcome window closes.", type: "bars", items: [["Correct", 71, "244"], ["Missed signal", 11, "38"], ["Wrong scope", 8, "27"], ["Held for review", 10, "33"]] },
        { title: "Outcome distribution", type: "table", columns: ["Outcome", "Miss origin", "Count", "Share"], rows: [
          ["Correct", "-", "244", "71%"],
          ["Missed signal", "observation", "38", "11%"],
          ["Wrong scope", "context selection", "27", "8%"],
          ["Held for review", "insufficient evidence", "33", "10%"]
        ] },
        { title: "Selected episode", type: "workspace", listTitle: "Recent episodes", detailTitle: "Forecast episode fc-2841", list: [["fc-2841", "Closed - wrong scope"], ["fc-2838", "Closed - correct"], ["fc-2829", "Awaiting outcome"], ["fc-2817", "Held for review"]], detail: "The forecast correctly anticipated resource pressure but selected a broader service boundary than the observed outcome. The miss is attributed to context selection, not model confidence.", facts: [["Prediction window", "24 hours"], ["Closed at", common.asOf], ["Confidence", "0.82"], ["Evidence completeness", "96%"], ["Miss origin", status("Context selection", "warning")], ["Audit", link("Open episode", "audit.html?episode=fc-2841")]] },
        { title: "Publication and retention debt", type: "facts", items: [["Publication pending", "5"], ["Oldest pending", "19 hours"], ["Dead-lettered", "1"], ["Retention overdue", "2"], ["Calibration drift", "1.8 pp"], ["Review cohort", code("forecast-v12")]] }
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
        ] },
        { title: "Selected result context", type: "workspace", listTitle: "Authorized turns", detailTitle: "Promotion blockers", list: [["09:41", "Operator question"], ["09:42", "Assistant evidence summary"], ["09:43", "Operator follow-up"], ["09:44", "Assurance assessment"]], detail: "Only the selected authorized result loads surrounding context. Search snippets do not silently widen purpose, role, or session scope.", facts: [["Session", code("conv-18")], ["Purpose", "Operational review"], ["Loaded turns", "4"], ["Evidence refs", "6"], ["Authorization", status("Current", "success")], ["Audit", link("Search access record", "audit.html?conversation=conv-18")]] },
        { title: "Search boundary", type: "facts", items: [["Authorization filter", "Server owned"], ["Context loading", "Operator selected"], ["Cross-session scope", "Purpose bounded"], ["Unavailable results", "Explained, not inferred"], ["Mutation authority", "None"], ["Retention", "Policy controlled"]] }
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
        ] },
        { title: "Decision calibration", description: "Measured outcomes by assurance class for the retained cohort.", type: "bars", items: [["Correct", 86, "134"], ["Incomplete", 7, "11"], ["Unsupported", 3, "4"], ["Disputed", 4, "7"]] },
        { title: "Assurance boundary", type: "facts", items: [["Cohort", code("assurance-v9")], ["Independent judges", "3"], ["Human disputes", "7 open or retained"], ["Answer mutation", "None"], ["Promotion authority", "None"], ["Ledger", link("Assessment records", "audit.html?kind=conversation-assurance")]] }
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
        ] },
        { title: "Recent renders", description: "Each render remains pinned to its catalog definition and bounded source revisions.", type: "table", columns: ["Report", "Window", "Sources", "State", "Render", "Evidence digest"], rows: [
          ["Weekly operations review", "7 days", "5 / 5", status("Complete", "success"), "684 ms", code("rep-84a1")],
          ["Control assurance", "30 days", "4 / 5", status("Partial", "warning"), "721 ms", code("rep-839f")],
          ["Cost governance", "30 days", "3 / 3", status("Complete", "success"), "592 ms", code("rep-82d0")]
        ] },
        { title: "Report contract", type: "facts", items: [["Definition", code("weekly-operations@7")], ["Variables", "Window + scope"], ["Source revisions", "Pinned"], ["Unavailable handling", "Explicit"], ["Workflow execution", "None"], ["Audit", link("Render evidence", "audit.html?report=weekly-operations")]] }
      ]
    },
    "architecture": {
      group: "Governance",
      title: "Architecture",
      subtitle: "Deployed resources, boundaries, and dependencies.",
      note: "The map renders stored topology only. Layout, icons, and focus controls are presentation, not evidence.",
      kpis: [["Resources", "324", "active generation"], ["Links", "512", "typed"], ["Boundaries", "3", "observed"], ["Unknown paths", "7", "coverage incomplete"]],
      sections: [
        { id: "architecture-runtime-path", title: "Observed network path", description: "Stored direction and typed links are shown explicitly; presentation order does not create additional relationships.", type: "network", items: [["Internet", "External", "routes_to"], ["Front Door", "Edge", "traverses"], ["Private Link", "Boundary", "reaches"], ["Operator API", "Service", "depends_on"], ["PostgreSQL", "Data"]] },
        { id: "architecture-runtime-relationship", title: "Selected relationship", type: "facts", items: [["Source", "Front Door"], ["Link type", "traverses"], ["Target", "Private Link"], ["Evidence", "Current configuration at 2026-08-27T10:15:00Z"]] },
        { id: "architecture-runtime-related", title: "Related view", type: "cards", items: [["Service map", "Interactive topology study", "Open the detailed service map for path tracing and inspector behavior.", "service-map.html"], ["Ontology instances", "Operational 2D view", "Inspect one selected Resource and its typed relationships.", "ontology.html?view=instances"]] },
        { id: "architecture-authority-lanes", title: "Language is not authority", description: "Read questions and managed-resource changes cross different boundaries.", type: "cards", items: [["Read plane", "No mutation authority", "Question -> typed read plan -> bounded query -> evidence-qualified answer.", "rule-trace.html?mode=read"], ["Change plane", "Governed authority", "Proposal -> risk gate -> human approval -> isolated Executor.", "hil.html?status=pending"]] },
        { id: "architecture-authority-identities", title: "Separated identities", type: "facts", items: [["Operator", "Requests and reviews"], ["Core", "Judges; no effect role"], ["Approver", "Grants bounded human authority"], ["Executor", "Attempts one eligible effect"], ["Observer", "Independently verifies the result"]] },
        { id: "architecture-effect-path", title: "Independent effect verification", description: "Dispatch success is not operational success.", type: "network", items: [["ExpectedEffect", "Before attempt", "binds"], ["Isolated Executor", "Effect identity", "attempts"], ["Managed target", "External truth", "observed_by"], ["Heimdall", "Independent observer", "produces"], ["ObservedOutcome", "Matched or unresolved"]] },
        { id: "architecture-effect-states", title: "Terminal evidence states", type: "facts", items: [["Matched", "Expected effect independently observed"], ["Mismatched", "Observed result differs"], ["Timeout", "Fresh observation did not arrive"], ["Unscorable", "Required evidence is incomplete"], ["Audit closure", "Saga records intent, execution, and outcome separately"]] }
      ]
    },
    "capabilities": {
      group: "Governance",
      title: "Capabilities",
      subtitle: "Declared capability contracts, side-effect classes, roles, and default modes.",
      note: "The catalog describes eligibility. It grants no role, approval, or execution authority.",
      kpis: [["Declared", "142", "exact release"], ["Read-only", "89", "side effect class"], ["Observation mode", "23", "no changes applied"], ["Role restricted", "8", "current principal"]],
      sections: [
        { id: "capability-query", title: "Review capability contracts", description: "Filter declarations by operator intent and authority boundary.", type: "form", fields: [["Search", "search", "Capability id or summary", 6], ["Side effect", "select", ["All classes", "Read", "Simulate", "Execute"], 2], ["Mode", "select", ["All modes", "Observation", "Enforcement"], 2], ["Role", "select", ["All roles", "Reader", "Operator", "Executor"], 2]], action: "Apply filters" },
        { title: "Capability declarations", type: "table", columns: ["Capability", "Category", "Summary", "Side effect", "Mode", "Required role"], rows: [
          [code("inventory.read", "ontology.html?view=actions"), "Observation", "Read bounded inventory projection", status("Read", "info"), status("Enforcement", "success"), "Reader"],
          [code("impact.simulate", "blast-radius.html"), "Safety", "Compute stored-direction impact scope", status("Simulate", "info"), status("Enforcement", "success"), "Operator"],
          [code("resource.restart", "promotion.html"), "Execution", "Restart an approved workload", status("Execute", "warning"), status("Observation", "warning"), "Executor"],
          [code("workflow.inspect", "workflow-builder.html"), "Orchestration", "Read process definition and durable state", status("Read", "info"), status("Enforcement", "success"), "Reader"],
          [code("evidence.export", "audit.html"), "Evidence", "Export authorized immutable metadata", status("Read", "info"), status("Enforcement", "success"), "Operator"]
        ] },
        { title: "Selected declaration", type: "workspace", listTitle: "Contract facets", detailTitle: "impact.simulate", list: [["Intent", "Safety analysis"], ["Authority", "No managed-resource effect"], ["Inputs", "Target + bounded depth"], ["Evidence", "Stored directed graph"]], detail: "Computes a bounded what-if reachability projection. Unknown relationship coverage is reported explicitly and never treated as zero impact.", facts: [["Declaration source", "Ontology release"], ["Default mode", status("Enforcement", "success")], ["Required role", "Operator"], ["Mutation authority", "None"], ["Owner", "Risk gate"], ["Audit route", link("Filtered ledger", "audit.html?capability=impact.simulate")]] },
        { title: "Catalog health", type: "facts", items: [["Release", code("capabilities-v18")], ["Schema validation", status("Passed", "success")], ["Missing owners", "0"], ["Missing authority class", "0"], ["Promotion blockers", "3"], ["Last reviewed", common.asOf]] }
      ]
    },
    "skills": {
      group: "Governance",
      title: "Skills",
      subtitle: "Installed runtime skill metadata, dependencies, eligibility, and load diagnostics.",
      note: "Skill eligibility describes runtime composition. Loading a skill does not grant authority.",
      kpis: [["Installed", "23", "current bundle"], ["Enabled", "20", "eligible"], ["Missing tools", "3", "blocked"], ["Diagnostics", "2", "needs review"]],
      sections: [
        { id: "skill-query", title: "Inspect runtime skills", description: "Separate installation, eligibility, and accountable agent assignment.", type: "form", fields: [["Search", "search", "Skill or tool", 6], ["Eligibility", "select", ["All states", "Eligible", "Blocked", "Disabled"], 3], ["Agent", "select", ["All agents", "Huginn", "Bragi", "Muninn", "Njord"], 3]], action: "Apply filters" },
        { title: "Runtime skills", type: "table", columns: ["Skill", "Version", "Status", "Required tools", "Allowed agents", "Eligibility"], rows: [
          [code("azure-inventory"), "2.4.1", status("Enabled", "success"), "az, jq", "Huginn", status("Eligible", "success")],
          [code("cost-analysis"), "1.8.0", status("Enabled", "success"), "python", "Bragi, Muninn", status("Eligible", "success")],
          [code("kubernetes-debug"), "0.9.3", status("Blocked", "warning"), "kubectl", "Huginn", status("Tool missing", "warning")],
          [code("evidence-correlation"), "1.6.2", status("Enabled", "success"), "python", "Heimdall, Forseti", status("Eligible", "success")],
          [code("browser-observation"), "1.3.0", status("Disabled", "neutral"), "browser", "Huginn", status("Operator disabled", "neutral")]
        ] },
        { title: "Selected skill", type: "workspace", listTitle: "Skill contracts", detailTitle: "azure-inventory 2.4.1", list: [["Purpose", "Bounded provider inventory"], ["Tools", "az + jq"], ["Agent", "Huginn"], ["Authority", "Read only"]], detail: "Loads only when the provider toolchain and role-scoped source are available. Tool presence, enabled state, and action authority remain independent.", facts: [["Package source", code("core-skills@18")], ["Allowed agents", "Huginn"], ["Network boundary", "Provider API allowlist"], ["Mutation authority", "None"], ["Last diagnostic", status("Passed", "success")], ["Audit evidence", link("Open ledger", "audit.html?skill=azure-inventory")]] },
        { title: "Bundles and diagnostics", type: "facts", items: [["Core bundle", status("Compatible", "success")], ["Operations bundle", status("Compatible", "success")], ["Optional bundle", status("4 incompatibilities", "warning")], ["Load failures", "2 retained"], ["Unowned skills", "0"], ["Signed manifest", status("Verified", "success")]] }
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
        ] },
        { title: "Selected document", type: "workspace", listTitle: "Processing receipts", detailTitle: "handover-platform.pdf", list: [["Upload", "Authorized and hashed"], ["Malware scan", "Clean"], ["Protection", "Applied"], ["Index", "Ready"]], detail: "The document was admitted for knowledge grounding after explicit consent, malware scanning, protection, and collection authorization. Content is not exposed in this metadata review.", facts: [["Collection", "Operational handovers"], ["Purpose", "Knowledge grounding"], ["Protection", status("Applied", "success")], ["Index state", status("Ready", "success")], ["Digest", code("doc-3f8a")], ["Audit", link("Ingestion receipts", "audit.html?document=doc-3f8a")]] },
        { title: "Ingestion boundary", type: "facts", items: [["Consent", "Explicit"], ["Malware scan", "Required"], ["Failed payloads", "Not retained"], ["Collection ACL", "Server enforced"], ["Execution authority", "None"], ["Retention", "Collection policy"]] }
      ]
    },
    "context-selection-comparisons": {
      group: "Governance",
      title: "Context policy comparisons",
      subtitle: "Baseline and shadow context-selection evidence.",
      note: "Comparisons are read-only evaluations. Candidate policy output cannot change production selection.",
      kpis: [["Comparisons", "47", "current cohort"], ["Successful", "44", "93.6%"], ["Failures", "3", "reason retained"], ["Mutation controls", "0", "read only"]],
      sections: [
        { id: "context-query", title: "Compare policy output", description: "Inspect one baseline and shadow candidate over the same frozen cohort.", type: "form", fields: [["Baseline", "select", ["baseline-v7", "baseline-v6"], 3], ["Candidate", "select", ["candidate-v8", "candidate-v9"], 3], ["Outcome", "select", ["All outcomes", "Successful", "Failed"], 3], ["Search", "search", "Evaluation or omission", 3]], action: "Apply comparison" },
        { title: "Policy evaluations", type: "table", columns: ["Evaluation", "Baseline", "Candidate", "Tokens", "Overlap", "Omissions", "Pinned", "Latency", "Failure"], rows: [
          [code("ctx-41a8"), code("baseline-v7"), code("candidate-v8"), "4,200 / 3,800", "94%", "0", status("Preserved", "success"), "84 ms", "-"],
          [code("ctx-4092"), code("baseline-v7"), code("candidate-v8"), "3,880 / 3,510", "91%", "1", status("Preserved", "success"), "78 ms", "-"],
          [code("ctx-3ff1"), code("baseline-v7"), code("candidate-v8"), "-", "-", "-", status("Missing", "danger"), "91 ms", "source_unavailable"]
        ] },
        { title: "Selected evaluation", type: "workspace", listTitle: "Comparison dimensions", detailTitle: "Evaluation ctx-41a8", list: [["Pinned evidence", "Preserved"], ["Source diversity", "Equivalent"], ["Token budget", "-9.5%"], ["Answer support", "No omissions"]], detail: "The candidate retained every pinned evidence item while reducing duplicate context. It remains shadow output and cannot change production selection until the review cohort closes.", facts: [["Baseline", code("baseline-v7")], ["Candidate", code("candidate-v8")], ["Overlap", "94%"], ["Pinned items", "12 / 12"], ["Decision", status("Candidate better", "success")], ["Audit", link("Evaluation evidence", "audit.html?evaluation=ctx-41a8")]] },
        { title: "Evaluation contract", type: "facts", items: [["Cohort", code("context-policy-v8")], ["Frozen queries", "47"], ["Pinned evidence loss", "0 allowed"], ["Authority", "Shadow only"], ["Failures retained", "3"], ["Review cutoff", common.asOf]] }
      ]
    },
    "scope": {
      group: "Governance",
      title: "Scope",
      subtitle: "Effective monitoring and action scope with IAM boundaries.",
      note: "Monitoring scope never implies action authority. The executor boundary is evaluated independently.",
      kpis: [["Monitoring entries", "24", "effective"], ["Action entries", "18", "more restrictive"], ["Subscriptions", "3", "authorized"], ["Executor boundary", "1", "isolated"]],
      sections: [
        { id: "scope-query", title: "Inspect effective scope", description: "Resolve monitoring and action axes independently for one logical boundary.", type: "form", fields: [["Search", "search", "Logical scope or resource group", 6], ["Axis", "select", ["All axes", "Monitoring", "Action"], 3], ["State", "select", ["All states", "Included", "Excluded"], 3]], action: "Apply filters" },
        { title: "Effective scope", type: "table", columns: ["Subscription", "Axis", "State", "Resource group", "Address"], rows: [
          [code("sub-platform"), "Monitoring", status("Included", "success"), "rg-platform-prod", code("/subscriptions/.../rg-platform-prod")],
          [code("sub-platform"), "Action", status("Included", "warning"), "rg-platform-prod", code("/subscriptions/.../rg-platform-prod")],
          [code("sub-shared"), "Action", status("Excluded", "danger"), "rg-shared-data", code("/subscriptions/.../rg-shared-data")]
        ] },
        { title: "Selected boundary", type: "workspace", listTitle: "Independent axes", detailTitle: "platform-production", list: [["Monitoring", "Included"], ["Action", "Included with ceiling"], ["Approval", "Action dependent"], ["Executor", "Logical target lock"]], detail: "Monitoring inclusion authorizes observation only. Action eligibility is narrower and is re-evaluated with role, risk, approval, target lock, and promotion state for every request.", facts: [["Policy release", code("scope-v12")], ["IAM snapshot", status("Current", "success")], ["Action targets", "18"], ["Wildcard grants", "0"], ["Executor identity", "Isolated"], ["Audit", link("Boundary changes", "audit.html?scope=platform-production")]] },
        { title: "Boundary evidence", type: "facts", items: [["Policy release", code("scope-v12")], ["IAM snapshot", status("Current", "success")], ["Action target locks", "18"], ["Wildcard grants", "0"], ["Unresolved subjects", "0"], ["Last convergence", common.asOf]] }
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
    var rendered;
    if (value && typeof value === "object") {
      if (value.kind === "status") {
        rendered = '<span class="cp-status is-' + escapeHtml(value.tone) + '">' + escapeHtml(value.text) + "</span>";
      }
      if (value.kind === "code") rendered = '<code class="cp-code">' + escapeHtml(value.text) + "</code>";
      if (value.kind === "link") rendered = escapeHtml(value.text);
      if (value.href && rendered) return '<a href="' + escapeHtml(value.href) + '">' + rendered + "</a>";
      if (rendered) return rendered;
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
      var action = item[3] ? '<a class="cp-card-link" href="' + escapeHtml(item[3]) + '">Open ' + escapeHtml(item[0]) + "</a>" : "";
      return '<article class="cp-card' + (index === 0 ? " is-selected" : "") + '"><div class="cp-card-head"><h3>' +
        escapeHtml(item[0]) + '</h3><span class="cp-status is-' + (index === 0 ? "info" : "neutral") + '">' +
        escapeHtml(item[1]) + "</span></div><p>" + escapeHtml(item[2]) + "</p>" + action + "</article>";
    }).join("") + "</div>";
  }

  function renderForm(section) {
    var fields = section.fields.map(function (field, index) {
      var id = "cp-field-" + (section.id ? section.id + "-" : "") + index;
      var span = field[3] || 4;
      var control;
      if (field[1] === "select") {
        control = '<select class="cs-control-select" id="' + id + '"' + (section.disabled ? " disabled" : "") + ">" + field[2].map(function (option) {
          return "<option" + (section.initialValues && section.initialValues[index] === option ? " selected" : "") + ">" + escapeHtml(option) + "</option>";
        }).join("") + "</select>";
      } else if (field[1] === "checkbox") {
        control = '<label class="cp-checkbox"><input id="' + id + '" type="checkbox"' + (section.disabled ? " disabled" : "") + " /> " + escapeHtml(field[2]) + "</label>";
      } else {
        control = '<input class="cs-control-input" id="' + id + '" type="' + escapeHtml(field[1]) + '"' + (section.disabled ? " disabled" : "") +
          (section.initialValues && section.initialValues[index] !== undefined ? ' value="' + escapeHtml(section.initialValues[index]) + '"' : "") +
          (field[2] ? ' placeholder="' + escapeHtml(field[2]) + '"' : "") + " />";
      }
      return '<div class="cp-field" style="--cp-field-span:' + span + '"><label for="' + id + '">' +
        escapeHtml(field[0]) + "</label>" + control + "</div>";
    }).join("");
    return '<form class="cp-form' + (section.inlineAction ? " has-inline-action" : "") + '" data-cp-form><p class="cp-form-note">Synthetic controls mirror the Console form and do not submit data.</p>' +
      fields + '<div class="cp-form-actions"' + (section.actionSpan ? ' style="--cp-action-span:' + section.actionSpan + '"' : "") + '><button class="cs-control-button is-primary" type="submit"' + (section.disabled ? " disabled" : "") + ">" +
      escapeHtml(section.action) + "</button></div></form>";
  }

  function renderWorkspace(section) {
    if (section.records) return window.FDAI_OPERATIONS_RENDERER.workspace(section);
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
    return '<div class="cp-network" role="list" aria-label="Observed directed topology path">' +
      items.map(function (item, index) {
        var relationship = item[2] && index < items.length - 1
          ? '<span class="cp-network-edge" aria-label="' + escapeHtml(item[0] + " " + item[2] + " " + items[index + 1][0]) +
            '"><span>' + escapeHtml(item[2]) + "</span></span>"
          : "";
        return '<span class="cp-node" role="listitem"><span class="cp-node-order">' +
          String(index + 1).padStart(2, "0") + '</span><strong>' + escapeHtml(item[0]) + "</strong><small>" +
          escapeHtml(item[1]) + "</small></span>" + relationship;
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
    if (section.type === "disclosure") {
      return '<section class="cp-section op-technical-disclosure"' +
        (section.id ? ' id="' + escapeHtml(section.id) + '"' : "") +
        '><details><summary>' + escapeHtml(section.title) + "</summary>" +
        (section.description ? "<p>" + escapeHtml(section.description) + "</p>" : "") +
        renderFacts(section.items) + "</details></section>";
    }
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
    if (window.FDAI_OPERATIONS_WORK_PAGES) Object.assign(pages, window.FDAI_OPERATIONS_WORK_PAGES);
    var pageId = document.body.getAttribute("data-console-page");
    var page = pages[pageId];
    if (!page) {
      root.innerHTML = '<div class="cs-empty"><strong>Mock unavailable</strong>No Console parity specification exists for this page.</div>';
      return;
    }
    if (page.renderer === "knowledge") {
      if (!window.FDAI_KNOWLEDGE_RENDERER) {
        root.innerHTML = '<div role="alert"><strong>Knowledge preview unavailable</strong><p>The local Knowledge renderer did not load.</p></div>';
        return;
      }
      window.FDAI_KNOWLEDGE_RENDERER.mount(root, page, pageId, common);
      return;
    }
    document.title = page.title + " - FDAI Console";
    var kpiMarkup = '<section class="cp-kpis" data-kpi-count="' + page.kpis.length + '" aria-label="' + escapeHtml(page.title) + ' summary" style="--cp-kpi-columns:' +
      Math.min(4, page.kpis.length) + '">' + page.kpis.map(function (item) {
        return '<article class="cp-kpi"><span>' + escapeHtml(item[0]) + '</span><strong' + (/^[\d$]/.test(String(item[1])) ? "" : ' class="op-value-label"') + ">" +
          escapeHtml(item[1]) + "</strong><small>" + escapeHtml(item[2]) + "</small></article>";
      }).join("") + "</section>";
    root.innerHTML = '<header class="cp-header"><div class="cp-header-copy"><h1>' +
      escapeHtml(page.title) + "</h1><p>" + escapeHtml(page.subtitle) +
      '</p></div><div class="cp-header-meta"><span>Synthetic specimen</span><strong>' +
      escapeHtml(common.asOf) + "</strong></div></header>" +
      (page.views ? '<details class="cs-readonly-banner op-preview-note"><summary><strong>Synthetic preview.</strong> No live requests or actions.</summary><p>' +
        escapeHtml(page.note || common.syntheticNote) + "</p></details>" :
        '<div class="cs-readonly-banner"><strong>Read-only specimen.</strong>' + escapeHtml(page.note || common.syntheticNote) + "</div>") +
      (page.kpisInFirstView ? "" : kpiMarkup) +
      (page.views
        ? window.FDAI_OPERATIONS_RENDERER.views(
            page,
            page.kpisInFirstView ? kpiMarkup : "",
          )
        : page.sections.map(renderSection).join(""));

    root.querySelectorAll("[data-cp-form]").forEach(function (form) {
      form.addEventListener("submit", function (event) { event.preventDefault(); });
    });
    root.querySelectorAll(".cp-tab").forEach(function (tab) {
      if (tab.hasAttribute("data-op-tab")) return;
      tab.addEventListener("click", function () {
        root.querySelectorAll(".cp-tab").forEach(function (candidate) {
          candidate.setAttribute("aria-selected", String(candidate === tab));
        });
        root.querySelectorAll(".cp-tab-panel").forEach(function (panel) {
          panel.hidden = panel.id !== tab.getAttribute("aria-controls");
        });
      });
    });
    if (document.body.classList.contains("cs-operator-neutral") && window.FDAI_OPERATIONS_RENDERER) {
      window.FDAI_OPERATIONS_RENDERER.bind(root, page, pageId).catch(function (error) {
        console.error("Operations preview could not initialize.", error);
        root.innerHTML = '<div role="alert"><strong>Operations preview unavailable</strong><p>The local fixture or navigation contract could not be loaded.</p></div>';
      });
    }
  }

  window.FDAI_CONSOLE_PARITY_PAGES = pages;
  window.FDAI_CONSOLE_PARITY_UI = { section: renderSection, facts: renderFacts, escape: escapeHtml };
  document.addEventListener("DOMContentLoaded", mount);
})();
