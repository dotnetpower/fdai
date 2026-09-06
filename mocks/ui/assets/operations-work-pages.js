/* Synthetic Operations specimens shaped by the corresponding console/src/routes views.
 * No API calls or command authority. The shared renderer owns local selection and navigation.
 */
(function () {
  "use strict";

  var asOf = "2026-09-06T09:15:00Z";
  var synthetic = "Synthetic example snapshot, not live operational evidence. ";
  function status(text, tone, href) {
    return { kind: "status", text: text, tone: tone || "neutral", href: href };
  }
  function code(text, href) { return { kind: "code", text: text, href: href }; }
  function link(text, href) { return { kind: "link", text: text, href: href }; }
  function facts(id, title, items, description) {
    return { id: id, title: title, type: "facts", items: items, description: description };
  }
  function table(id, title, columns, rows, description) {
    return { id: id, title: title, type: "table", columns: columns, rows: rows, description: description };
  }
  function timeline(id, title, items, description) {
    return { id: id, title: title, type: "timeline", items: items, description: description };
  }
  function workspace(id, title, listTitle, records, description) {
    return {
      id: id, title: title, type: "workspace", listTitle: listTitle, records: records,
      list: records.map(function (record) { return [record.label, record.summary]; }),
      detailTitle: records[0].label, detail: records[0].summary, facts: records[0].facts,
      description: description
    };
  }
  function preview(id, title, action, description) {
    return { id: id, title: title, type: "form", fields: [], action: action + " - unavailable in preview", disabled: true, description: description };
  }

  var requestBoundary = "Unavailable in this static preview: no authenticated principal, durable Process, pinned catalog, or current server-owned transition projection. Production checks requester ownership; shadow requests require Contributor, Approver, or Owner, while enforce requests require Owner. These role checks alone never grant a transition. The exact permitted operation is revision-bound, audited, idempotent, and rechecked by the runtime. HTTP 202 accepts a proposal; it is not a completed transition or an operational success.";
  var requestHeaders = [
    ["Request method", code("POST")], ["Revision precondition", code("If-Match: 12")],
    ["Idempotency", code("process:example-process-review:cancel:revision:12")],
    ["Confirmation", "Required for cancel and retry; not an approval of managed-resource execution"],
    ["Acceptance", "Proposal receipt only; independent runtime state remains authoritative"]
  ];

  var processRecords = [
    {
      id: "example-process-review", label: "Readiness review",
      summary: "Waiting for independent approval; investigation and planning evidence remain inspectable.",
      facts: [
        ["Process", code("example-process-review")], ["Workflow", code("example-readiness-review@1")],
        ["Target", code("example-workload-api")], ["State", status("Waiting", "warning")],
        ["Current step", code("example-approval-step")], ["Revision", "12"],
        ["Started", "2026-09-06T09:10:00Z"], ["Updated", asOf], ["Journal events", "4 retained in this sample"]
      ],
      sections: [
        facts("process-control", "Process control", [
          ["Availability", status("Unavailable in preview")], ["Step kind", "Approval"],
          ["Step state", "Waiting"], ["Attempt", "1"], ["Mode", code("shadow")],
          ["Catalog revision", code("example-catalog-revision-7")], ["Reason", code("approval_pending")],
          ["Approval role", "Approver"], ["Quorum", "2 independent approvals required; 1 recorded"],
          ["No self-approval", "Required; requester cannot approve their own request"],
          ["Deadline", "2026-09-06T09:29:00Z"], ["Timeout", "900 seconds"],
          ["Resume", "Not permitted for an approval step; use the existing approval lifecycle"]
        ], requestBoundary),
        preview("process-cancel-preview", "Cancel request preview", "Request cancel", "Only pending or waiting Processes may expose cancel. Confirmation is required. Cancelling is a runtime request, not a cloud-resource action. " + requestBoundary),
        facts("process-request-contract", "Revision and acceptance boundary", requestHeaders),
        facts("process-investigation", "Investigation room", [
          ["Incident", code("example-incident-readiness")], ["Disposition", status("Insufficient evidence", "warning")],
          ["Rounds", "2 / 4"], ["Queries", "2 / 6"], ["Cost units", "2 / 8"],
          ["Closure reason", "Restart evidence does not distinguish the remaining hypotheses."]
        ], "Retained probe choices, evidence cutoffs, budget consumption, and hypothesis separation do not establish causation."),
        table("process-investigation-rounds", "Investigation rounds",
          ["Round", "Evidence cutoff", "Active hypotheses", "Selected probe or hold", "Separation", "Revision / shadow comparison"], [
            ["1", "2026-09-06T09:10:30Z", "example-hypothesis-rollout; example-hypothesis-restart", "example-probe-lifecycle", "0 / 1 pairs", "Continue; example-shadow-comparison-1"],
            ["2", "2026-09-06T09:11:30Z", "example-hypothesis-rollout; example-hypothesis-restart", "Hold: independent observation missing", "0 / 1 pairs", "Insufficient evidence; no later comparison"]
          ]),
        timeline("process-planning-phases", "Planning phases", [
          ["2026-09-06T09:12:00Z", "Proposal", "Huginn - example-planning-event-1"],
          ["2026-09-06T09:12:15Z", "Critique", "Heimdall - example-planning-event-2"],
          ["2026-09-06T09:12:30Z", "Revision", "Huginn - example-planning-event-3"]
        ], "Agent attribution comes from retained phase events, not inferred authority."),
        facts("process-planning", "Planning room", [
          ["Plan", code("example-plan-readiness")], ["Current phase", "Revision"],
          ["Selection", "Held; no selected option"], ["Human review", "Required"],
          ["Margin", "Not reported"], ["Complete", "No; simulation evidence missing"]
        ]),
        table("process-planning-candidates", "Plan candidates",
          ["Candidate", "Proposing agents", "Action", "Disposition", "Expected effects", "Evidence receipts"], [
            [code("example-candidate-observe"), "Huginn", code("hold"), status("Held", "warning"), "No managed-resource effect", "1 logic; 0 simulation; 1 constraint"],
            [code("example-candidate-restart"), "Huginn", code("example-restart-action"), status("Ineligible", "danger"), "readiness: unknown..unknown", "0 logic; 0 simulation; 0 constraint"]
          ], "The restart candidate is ineligible: rollback and simulation receipts are missing. Expected effects are not measured outcomes."),
        timeline("process-journal", "Execution journal", [
          ["2026-09-06T09:10:00Z", "Process created", "example-process-event-1 - example-readiness-review@1; shadow; requester example-principal"],
          ["2026-09-06T09:14:00Z", "Step started", "example-process-event-2 - example-approval-step; attempt 1"],
          ["2026-09-06T09:14:01Z", "Approval requested", "example-process-event-3 - example-approval-request; quorum 2"],
          [asOf, "Process waiting", "example-process-event-4 - approval_pending; no execution dispatched"]
        ], "Oldest to newest. Events are retained records, not a progress animation."),
        facts("process-event-detail", "Recorded event", [
          ["Event", code("example-process-event-4", "processes.html?record=example-process-review&event=example-process-event-4#process-event-detail")],
          ["Correlation", code("example-process-correlation")], ["Causation", code("example-process-event-3")],
          ["Attempt", "1"], ["Payload", code('{"reason":"approval_pending","step_kind":"approval"}')]
        ]),
        facts("process-domain-view", "Readiness evidence view", [
          ["View specification", code("example-readiness-view@1")],
          ["Region", "Retained decision evidence"], ["Evidence cutoff", "2026-09-06T09:12:03Z"],
          ["Readiness at cutoff", status("Partial", "warning", "detection-readiness.html#detection-assessment-history")],
          ["Independent recovery", "Not verified"],
          ["Evidence", code("example-evidence-lifecycle-0", "detection-readiness.html#detection-assessment-history")]
        ], "A synthetic server-rendered ViewSpec region. This earlier decision snapshot is not silently overwritten by the later recovery receipt.")
      ]
    },
    {
      id: "example-process-wait", label: "Wait for the next observation",
      summary: "Waiting on an evidence event; a non-approval wait has guarded resume and cancel requests.",
      facts: [
        ["Process", code("example-process-wait")], ["Workflow", code("example-observation-wait@1")],
        ["Target", code("example-workload-worker")], ["State", status("Waiting", "warning")],
        ["Step", code("example-evidence-wait")], ["Revision", "5"],
        ["Started", "2026-09-06T09:12:00Z"], ["Updated", "2026-09-06T09:12:01Z"], ["Journal events", "2"]
      ],
      sections: [
        facts("process-wait-control", "Wait requirements", [
          ["Availability", status("Unavailable in preview")], ["Step kind", "Wait"], ["Attempt", "1"],
          ["Wait for", code("example-observation-recorded")], ["Timeout", "600 seconds"],
          ["Deadline", "2026-09-06T09:22:00Z"], ["Mode", code("shadow")],
          ["Revision", code("If-Match: 5")], ["Runtime recheck", "Required even after request acceptance"]
        ], requestBoundary),
        preview("process-resume-preview", "Resume request preview", "Request resume", "Only a waiting, non-approval step may expose resume. Runtime must recheck the wait condition and current revision. " + requestBoundary),
        preview("process-wait-cancel-preview", "Cancel request preview", "Request cancel", "Only pending or waiting Processes may expose cancel; confirmation required. " + requestBoundary),
        timeline("process-wait-journal", "Execution journal", [
          ["2026-09-06T09:12:00Z", "Process created", "example-wait-event-1; example-observation-wait@1"],
          ["2026-09-06T09:12:01Z", "Process waiting", "example-wait-event-2; example-evidence-wait; observation pending"]
        ]),
        facts("process-wait-view", "Domain view", [["View specification", "Unavailable; this Process has a runtime journal only"]])
      ]
    },
    {
      id: "example-process-blocked", label: "Blocked evidence gate",
      summary: "Failed before dispatch; a retry preview illustrates bounded, effect-free failure admission.",
      facts: [
        ["Process", code("example-process-blocked")], ["Workflow", code("example-evidence-gate@1")],
        ["Target", code("example-workload-api")], ["State", status("Failed", "danger")],
        ["Step", code("example-readiness-gate")], ["Revision", "8"],
        ["Started", "2026-09-06T09:05:00Z"], ["Updated", "2026-09-06T09:05:02Z"], ["Journal events", "2"]
      ],
      sections: [
        facts("process-retry-control", "Retry admission", [
          ["Availability", status("Unavailable in preview")], ["Step kind", "Gate"], ["Attempt", "1 / 3 maximum"],
          ["Mode", code("enforce")], ["Revision", code("If-Match: 8")],
          ["Gate reference", code("example-readiness-gate")], ["Reason", code("gate_blocked")],
          ["Prior dispatch / compensation / cancellation request", "None in the retained attempt"],
          ["Role ceiling", "Enforce requests require Owner; ownership, evidence, and runtime checks still apply"]
        ], "A failed or timed-out Process is not automatically retryable. The current attempt must contain an allowlisted effect-free failure, remain below three attempts, and contain no blocking event."),
        preview("process-retry-preview", "Retry request preview", "Request retry", "Confirmation required. Prior action dispatch, compensation start/dispatch, or cancellation request blocks retry. Approval attempts require rejection or timeout evidence. " + requestBoundary),
        timeline("process-blocked-journal", "Execution journal", [
          ["2026-09-06T09:05:00Z", "Process created", "example-blocked-event-1; example-evidence-gate@1"],
          ["2026-09-06T09:05:02Z", "Step failed", "example-blocked-event-2; gate_blocked; attempt 1; no action dispatched"]
        ]),
        facts("process-blocked-view", "Domain view", [["View specification", "Unavailable; journal evidence remains visible"]])
      ]
    }
  ];

  var backgroundRecords = [
    {
      id: "example-background-running", label: "Investigate current readiness",
      summary: "Running - result pending; a partial request summary and bounded evidence list are retained.",
      facts: [["Task", code("example-background-running")], ["Status", status("Running", "info")], ["Accountable agent", "Huginn"]],
      sections: [
        facts("background-request", "Requested work", [
          ["Request", "Compare current readiness observations for example-workload-worker with retained Pod lifecycle evidence."],
          ["Request completeness", status("Truncated", "warning")], ["Omitted content", "The stored request summary is bounded; omitted content is not reconstructed."]
        ]),
        facts("background-outcome", "Outcome and evidence", [
          ["Outcome", status("Pending")], ["Explanation", "This investigation is still running; no terminal result has been recorded."],
          ["Result truncated", "No result recorded"],
          ["Evidence", code("example-evidence-worker-a", "detection-readiness.html?record=example-lifecycle-worker#detection-lifecycle-records")],
          ["Evidence completeness", status("Truncated list", "warning")]
        ]),
        facts("background-attribution", "Execution attribution", [
          ["Accountable agent", "Huginn"], ["Execution worker", code("background-task-coordinator")],
          ["Kind", code("read_only_investigation")], ["Updated", asOf]
        ], "The execution worker is infrastructure, not a substituted accountable agent."),
        timeline("background-progress", "Activity timeline", [
          ["2026-09-06T09:13:00Z", "Investigation planned", "Sequence 1: inspect two retained readiness sources."],
          ["2026-09-06T09:13:02Z", "Investigation started", "Sequence 2: owner-scoped task claimed."],
          [asOf, "Investigation progress", "Sequence 3: current receipt found; independent recovery remains unknown."]
        ], "Stored progress events only; the API read is bounded to 256 events."),
        facts("background-technical", "Technical details", [
          ["Created", "2026-09-06T09:13:00Z"], ["Lease expires", "2026-09-06T09:17:00Z"],
          ["Retention until", "2026-09-13T09:13:00Z"], ["Terminal reason", "Not reported"],
          ["Completion state", "Not reported"], ["Duration", "Not reported"],
          ["Tokens", "Not reported"], ["Tool calls", "2"], ["Cost (micro-USD)", "Not reported"]
        ])
      ]
    },
    {
      id: "example-background-complete", label: "Summarize the baseline comparison",
      summary: "Succeeded - bounded summary retained; success describes the read-only task, not cloud remediation.",
      facts: [["Task", code("example-background-complete")], ["Status", status("Succeeded", "success")], ["Accountable agent", "Muninn"]],
      sections: [
        facts("background-complete-request", "Requested work", [["Request", "Summarize example-baseline-v3 drift and unknown resource state."], ["Request truncated", "No"]]),
        facts("background-complete-outcome", "Outcome and evidence", [
          ["Outcome", "One configuration difference and two unknown resource states were reported. No mutation was requested."],
          ["Result completeness", status("Truncated summary", "warning")],
          ["Evidence", code("example-baseline-comparison-3", "configuration-baselines.html#baseline-drift")],
          ["Evidence truncated", "No"]
        ]),
        facts("background-complete-attribution", "Execution attribution", [
          ["Accountable agent", "Muninn"], ["Execution worker", code("background-task-coordinator")],
          ["Kind", code("read_only_investigation")], ["Updated", "2026-09-06T09:10:20Z"]
        ]),
        timeline("background-complete-progress", "Activity timeline", [
          ["2026-09-06T09:10:00Z", "Investigation started", "Sequence 1: read retained baseline comparison."],
          ["2026-09-06T09:10:20Z", "Investigation completed", "Sequence 2: bounded summary stored; no managed-resource effect."]
        ]),
        facts("background-complete-technical", "Technical details", [
          ["Created", "2026-09-06T09:10:00Z"], ["Lease expires", "Not reported"],
          ["Retention until", "2026-09-13T09:10:00Z"], ["Terminal reason", "Investigation completed"],
          ["Completion state", "Result recorded"], ["Duration", "20.0 seconds"],
          ["Tokens", "Not reported"], ["Tool calls", "2"], ["Cost (micro-USD)", "Not reported"]
        ])
      ]
    },
    {
      id: "example-background-unattributed", label: "Request summary unavailable",
      summary: "Unknown - request, result, and accountable-agent attribution are absent from the stored record.",
      facts: [["Task", code("example-background-unattributed")], ["Status", status("Unknown")], ["Accountable agent", "Unattributed"]],
      sections: [
        facts("background-unknown-request", "Requested work", [["Request", "Unavailable in this retained record"], ["Truncation", "No truncation reported; absence is not an empty request"]]),
        facts("background-unknown-outcome", "Outcome and evidence", [["Outcome", "Unavailable; no retained result"], ["Result truncated", "No"], ["Evidence", "No evidence references retained"], ["Evidence truncated", "No"]]),
        facts("background-unknown-attribution", "Execution attribution", [["Accountable agent", "Unattributed; do not infer from the worker"], ["Execution worker", code("background-task-coordinator")], ["Kind", code("read_only_investigation")], ["Updated", "2026-09-06T08:45:00Z"]]),
        facts("background-unknown-progress", "Activity timeline", [["Progress", "No progress events retained"]]),
        facts("background-unknown-technical", "Technical details", [
          ["Created", "2026-09-06T08:45:00Z"], ["Lease expires", "Not reported"], ["Retention until", "2026-09-13T08:45:00Z"],
          ["Terminal reason", "Not reported"], ["Completion state", "Not reported"], ["Duration", "Not reported"],
          ["Tokens", "Not reported"], ["Tool calls", "Not reported"], ["Cost (micro-USD)", "Not reported"]
        ])
      ]
    }
  ];

  window.FDAI_OPERATIONS_WORK_PAGES = {
    "detection-readiness": {
      group: "Operations", title: "Detection readiness",
      subtitle: "Agent-owned evidence that monitored Kubernetes targets can produce governed failure signals.",
      note: synthetic + "Huginn ingests facts, Heimdall reduces readiness, Muninn stores snapshots, and Saga audits transitions. Detection establishes neither cause nor execution authority.",
      kpis: [["Monitored targets", "4", "stored sample"], ["Ready", "1", "six evidence axes"], ["Needs attention", "3", "partial, stale, or unknown"], ["Shadow-limited", "3", "disabled, fallback, or shadow"]],
      views: [
        { id: "targets", label: "Targets", sections: ["detection-provenance", "detection-targets"] },
        { id: "lifecycle", label: "Lifecycle", sections: ["detection-lifecycle-summary", "detection-lifecycle-records"] },
        { id: "failures", label: "Failures", sections: ["pod-lifecycle-summary", "pod-detection-lifecycle"] }
      ],
      sections: [
        facts("detection-provenance", "Evidence provenance", [["Source", code("example-muninn-readiness-projection")], ["Last agent snapshot", asOf], ["Evidence profile", "Synthetic"]]),
        facts("detection-lifecycle-summary", "Pod lifecycle evidence", [
          ["Source", code("example-analyzer-receipts")], ["Last receipt", asOf],
          ["Assessments", "3"], ["Incomplete or missed", "1"], ["Conflicting", "1"]
        ], "Current state stays separate from earlier restart, replacement, publication, and recovery history."),
        workspace("detection-lifecycle-records", "Current state and retained assessments", "Targets", [
          {
            id: "example-lifecycle-api", label: "example-workload-api", summary: "Running now; earlier restart retained; recovery independently verified.",
            facts: [["Current observed state", status("Running", "success")], ["Evidence", status("Complete", "success")], ["Recovery", status("Verified", "success")], ["Publication", status("Duplicate suppressed")]],
            sections: [
              facts("detection-current-assessment", "Current state and latest assessment", [
                ["Lifecycle event", code("container_restart")], ["Observed event time", "2026-09-06T09:14:30Z"],
                ["Recorded time", "2026-09-06T09:14:32Z"], ["Detection latency", "2 seconds"],
                ["Evidence reference", code("example-evidence-lifecycle-1")], ["Duplicate delivery", "Observed and suppressed without republishing"],
                ["Cause claim supported", "No"], ["Execution authority", "None"]
              ]),
              table("detection-assessment-history", "Earlier failure and recovery history",
                ["Observed event", "Current state then", "Signal", "Evidence", "Recovery", "Publication", "Evidence reference"], [
                  ["2026-09-06T09:12:00Z", "Failed", code("container_restart"), status("Incomplete", "warning"), "Open", "Awaiting reconciliation", code("example-evidence-lifecycle-0")]
                ], "The earlier failure remains visible even though the latest observation is Running. Earlier detection latency: 3 seconds; recorded at 2026-09-06T09:12:03Z.")
            ]
          },
          {
            id: "example-lifecycle-worker", label: "example-workload-worker", summary: "Current state unknown because the retained observations conflict.",
            facts: [["Current observed state", status("Unknown")], ["Evidence", status("Conflicting", "danger")], ["Recovery", status("Unknown")], ["Publication", status("Publication uncertain", "warning")]],
            sections: [
              facts("detection-conflicting-assessment", "Current state and latest assessment", [
                ["Lifecycle event", code("conflicting_evidence")], ["Observed event time", "2026-09-06T09:14:00Z"],
                ["Recorded time", "2026-09-06T09:14:04Z"], ["Detection latency", "4 seconds"],
                ["Evidence references", "example-evidence-worker-a; example-evidence-worker-b"],
                ["Cause claim supported", "No"], ["Execution authority", "None"]
              ]),
              facts("detection-conflicting-history", "Earlier failure and recovery history", [["Earlier assessments", "No earlier assessment retained; this is not proof of no prior failure"]])
            ]
          }
        ], "Read-only bounded receipts. Selecting a target changes only this local example."),
        table("detection-targets", "Target readiness", ["Target", "Decision", "Evidence axes", "Coverage gaps", "Authority ceiling"], [
          [code("example-workload-api", "architecture.html?resource=example-workload-api"), status("Ready", "success"), "6 / 6", "Missing 0, stale 0", code("shadow")],
          [code("example-workload-worker", "architecture.html?resource=example-workload-worker"), status("Partial", "warning"), "4 / 6", "Missing 2: detector_bound, pipeline_observed; stale 0", code("deterministic_fallback")],
          [code("example-workload-ingress", "architecture.html?resource=example-workload-ingress"), status("Stale", "warning"), "6 / 6", "Missing 0; stale 1: telemetry_observed", code("human_approval")],
          [code("example-workload-batch", "architecture.html?resource=example-workload-batch"), status("Unknown"), "0 / 6", "Missing 6, stale 0", code("disabled")]
        ], "The six axes are discovered, collector_configured, telemetry_observed, detector_bound, pipeline_observed, and action_governed. Coverage is not a new authorization."),
        facts("pod-lifecycle-summary", "Pod failure and recovery", [["Failing now", "0"], ["Recovery verified", "1"], ["Retained failures", "1"], ["Targets with evidence gaps", "1"]]),
        workspace("pod-detection-lifecycle", "Current state, failure history, and evidence gaps", "Pod projections", [
          {
            id: "example-pod-api", label: "example-workload-api", summary: "Recovered; verified recovery; one failure among two retained records.",
            facts: [["Current state", status("Recovered", "success")], ["Recovery", status("Verified", "success")], ["Current signal", code("container_restart")], ["Current state observed", "2026-09-06T09:14:30Z"], ["Recovery verified at", "2026-09-06T09:14:32Z"], ["Retention", "1 of 2 retained records are failures"]],
            sections: [
              table("pod-failure-history", "Failure history", ["Occurred", "Signal", "Recovery", "Delivery", "Evidence"], [
                ["2026-09-06T09:12:00Z", code("container_restart"), code("restart_observed_recovered"), code("published"), status("Complete", "success")]
              ]),
              facts("pod-evidence-gaps", "Evidence gaps", [["Gaps", "No evidence gap recorded for this target"]])
            ]
          },
          {
            id: "example-pod-worker", label: "example-workload-worker", summary: "Unknown current state; recovery not independently verified; conflicting observations.",
            facts: [["Current state", status("Unknown")], ["Recovery", status("Unknown")], ["Current signal", code("conflicting_evidence")], ["Current state observed", "Not observed"], ["Recovery verified at", "Not independently verified"], ["Retention", "0 of 1 retained records are failures"]],
            sections: [
              facts("pod-worker-history", "Failure history", [["History", "No failure retained; absence does not establish health"]]),
              facts("pod-worker-gaps", "Evidence gaps", [["Gap", status("Conflicting evidence", "warning")], ["Delivery", status("Delivery uncertain", "warning")], ["Details", "example-evidence-worker-a and example-evidence-worker-b disagree on the current Pod identity."]])
            ]
          }
        ], "Failure count, retention, recovery, and unknown evidence remain distinct. No repair controls.")
      ]
    },
    "configuration-baselines": {
      group: "Operations", title: "Configuration baselines",
      subtitle: "Read-only baseline integrity, current drift, Knowledge evidence, and measured latency.",
      note: synthetic + "Inspect only. This surface cannot activate a baseline, mutate configuration, request approval, or execute mitigation.",
      kpis: [["Active version", "example-baseline-v3", "server-owned lifecycle"], ["Drift decision", "Failed", "one finding; two unknowns retained"], ["Citations", "2", "Knowledge evidence"], ["Total latency", "684.0 ms", "synthetic measurement"]],
      views: [
        { id: "baseline", label: "Baseline", sections: ["baseline", "baseline-history"] },
        { id: "drift", label: "Drift", sections: ["baseline-drift", "baseline-knowledge", "baseline-performance"] },
        { id: "review", label: "Review", sections: ["baseline-review", "baseline-safety"] }
      ],
      sections: [
        facts("baseline", "Baseline", [["Scope", code("example-scope")], ["Created", "2026-09-04T08:00:00Z"], ["Document", "example-configuration-baseline"], ["Lifecycle", status("Active", "success")], ["Resources", "12"], ["Topology links", "18"], ["Unknown items", "2"]]),
        table("baseline-history", "Baseline history", ["Version", "Lifecycle", "Created", "Resources", "Comparison", "Findings"], [
          [code("example-baseline-v3"), status("Active", "success"), "2026-09-04T08:00:00Z", "12", status("Passed", "success"), "0"],
          [code("example-baseline-v4"), status("Candidate"), "2026-09-06T08:00:00Z", "12", status("Failed", "danger"), "1"],
          [code("example-baseline-v2"), status("Superseded"), "2026-08-28T08:00:00Z", "11", status("Passed", "success"), "0"]
        ], "Historical comparisons are retained independently of the latest drift decision. Candidate does not mean active."),
        facts("baseline-drift", "Drift", [["Decision", status("Failed", "danger")], ["Findings", "1"], ["Observed", asOf]], "A configuration difference was recorded against example-baseline-v3. Unknown states are not counted as passing evidence."),
        facts("baseline-knowledge", "Knowledge", [["Decision", status("Cited", "success")], ["Citations", "2"]]),
        facts("baseline-performance", "Performance", [["Total latency", "684.0 ms"], ["Observation latency", "420.0 ms"], ["Knowledge latency", "264.0 ms"]]),
        facts("baseline-review", "Weekly review", [["State", status("Paused after failed attempt", "warning")], ["Completed / required runs", "2 / 3"], ["Preserved failed attempts", "1"]]),
        facts("baseline-safety", "Safety evidence", [["Mutations", "0"], ["Approval requests", "0"], ["Mitigation executions", "0"], ["Unsupported claims", "0"]])
      ]
    },
    "processes": {
      group: "Operations", title: "Processes", subtitle: "Runtime journals, investigation and planning evidence, and server-projected transition requests.",
      note: synthetic + "Production Processes are not universally read-only. Guarded request previews below remain unavailable; acceptance never means execution success.",
      kpis: [["Loaded runs", "3", "bounded sample"], ["Active", "2", "waiting"], ["Completed", "0", "not inferred"], ["Failed", "1", "gate-blocked attempt"]],
      views: [
        { id: "workspace", label: "Workspace", sections: ["process-workspace"] },
        { id: "provenance", label: "Provenance", sections: ["process-provenance"] }
      ],
      sections: [
        facts("process-provenance", "Process provenance", [["Source", code("example-process-projection")], ["Evidence", "Synthetic"], ["Storage", "Unknown; durability not reported"], ["Principal scoped", "Required by the production source"], ["Dispatch history", link("Inspect scheduler runs", "scheduler-runs.html?task_id=example-scheduled-readiness#scheduler-dispatch-history")]]),
        workspace("process-workspace", "Process workspace", "Process instances", processRecords, "Select a retained Process. Refresh and selection are read operations; only server-projected transitions can become governed requests.")
      ]
    },
    "workflow-apps": {
      group: "Operations", title: "Workflow apps", subtitle: "Published workflow-specific read surfaces and run history.",
      note: synthetic + "Published describes a catalog lifecycle, not runtime health. Selecting an app loads only its workflow's runs; this route has no launch control.",
      kpis: [["Published apps", "3", "catalog sample"], ["Run examples", "2", "across the represented apps"]],
      views: [
        { id: "catalog", label: "Catalog", sections: ["workflow-app-catalog"] },
        { id: "runs", label: "Runs", sections: ["workflow-app-workspace"] }
      ],
      sections: [
        table("workflow-app-catalog", "Published applications", ["Application", "Workflow", "Lifecycle"], [
          [link("Readiness review", "workflow-apps.html?record=example-app-readiness#workflow-app-workspace"), code("example-readiness-review"), status("Published", "success")],
          [link("Observation wait", "workflow-apps.html?record=example-app-observation#workflow-app-workspace"), code("example-observation-wait"), status("Published", "success")],
          [link("Baseline review", "workflow-apps.html?record=example-app-baseline#workflow-app-workspace"), code("example-baseline-review"), status("Published", "success")]
        ], "Each application binds one published workflow and read-only ViewSpec."),
        workspace("workflow-app-workspace", "Application run history", "Published applications", [
          {
            id: "example-app-readiness", label: "Readiness review", summary: "Evidence, planning, and approval state for example-readiness-review runs.",
            facts: [["Workflow", code("example-readiness-review")], ["View", code("example-readiness-view")], ["Audience", "Reader"], ["Lifecycle", "Published"]],
            sections: [table("workflow-app-runs", "Recent runs", ["Target / Process", "Current step", "Status"], [
              [link("example-workload-api / example-process-review", "processes.html?record=example-process-review#process-workspace"), code("example-approval-step"), status("Waiting", "warning")]
            ], "Source query: workflow_ref=example-readiness-review. No unrelated runs are mixed into this history.")]
          },
          {
            id: "example-app-observation", label: "Observation wait", summary: "Read-only observation wait state for example-observation-wait runs.",
            facts: [["Workflow", code("example-observation-wait")], ["View", code("example-observation-view")], ["Audience", "Reader"], ["Lifecycle", "Published"]],
            sections: [table("workflow-observation-runs", "Recent runs", ["Target / Process", "Current step", "Status"], [
              [link("example-workload-worker / example-process-wait", "processes.html?record=example-process-wait#process-workspace"), code("example-evidence-wait"), status("Waiting", "warning")]
            ])]
          },
          {
            id: "example-app-baseline", label: "Baseline review", summary: "Published catalog entry with no retained Process runs in this bounded example.",
            facts: [["Workflow", code("example-baseline-review")], ["View", code("example-baseline-view")], ["Audience", "Reader"], ["Lifecycle", "Published"]],
            sections: [facts("workflow-baseline-runs", "Recent runs", [["Runs", "No Process runs returned for example-baseline-review"]], "A sourced empty result is distinct from an unavailable process projection.")]
          }
        ], "App not found, unavailable source, and a valid app with no runs are separate production states.")
      ]
    },
    "scheduler-runs": {
      group: "Operations", title: "Scheduler runs", subtitle: "Read-only dispatch evidence from the configured scheduler ledger.",
      note: synthetic + "Published means broker dispatch was recorded, not task execution or outcome success. No retry, cancel, or execute controls.",
      kpis: [["Loaded attempts", "4", "one task, bounded page"], ["Publish rate", "25.0%", "1 / 4 loaded attempts"], ["Failed or lost", "2", "retained failures"], ["Median close", "3.0 s", "3 closed attempts"], ["P95 close", "5.0 s", "loaded sample only"]],
      views: [
        { id: "history", label: "History", sections: ["scheduler-query", "scheduler-dispatch-history", "scheduler-pagination"] },
        { id: "evidence", label: "Evidence", sections: ["scheduler-provenance"] }
      ],
      sections: [
        { id: "scheduler-query", title: "Load dispatch history", type: "form", fields: [["Task ID", "text", "example-scheduled-readiness", 8], ["Status", "select", ["All statuses", "Claimed", "Published", "Failed", "Lost"], 4]], initialValues: ["example-scheduled-readiness", "All statuses"], action: "Load history", description: "Production requires an exact task_id before lookup and requests at most 50 rows. Preview lookup never calls the ledger." },
        facts("scheduler-provenance", "Dispatch provenance", [["Task ID", code("example-scheduled-readiness")], ["Source", code("example-scheduler-ledger")], ["Storage", "Volatile synthetic sample"], ["Measurement boundary", "Claim-to-close latency includes failed and lost attempts; still-claimed rows have no close latency"]]),
        table("scheduler-dispatch-history", "Dispatch history", ["Run ID", "Scheduled for", "Claimed at", "Status", "Attempt", "Completed at", "Error kind"], [
          [code("example-scheduler-run-4"), "2026-09-06T09:15:00Z", "2026-09-06T09:15:00Z", status("Claimed", "warning"), "1", "Not reported", "Not reported"],
          [code("example-scheduler-run-3"), "2026-09-06T09:00:00Z", "2026-09-06T09:00:00Z", status("Published", "success"), "1", "2026-09-06T09:00:02Z", "None recorded"],
          [code("example-scheduler-run-2"), "2026-09-06T08:45:00Z", "2026-09-06T08:45:00Z", status("Failed", "danger"), "1", "2026-09-06T08:45:05Z", code("example-broker-timeout")],
          [code("example-scheduler-run-1"), "2026-09-06T08:30:00Z", "2026-09-06T08:30:00Z", status("Lost", "danger"), "1", "2026-09-06T08:30:03Z", code("example-lease-lost")]
        ], "All four rows belong to example-scheduled-readiness. Publication success is not execution success."),
        facts("scheduler-pagination", "Page boundary", [["Loaded", "4 attempts"], ["Next cursor", code("example-scheduler-cursor-next")], ["More history", "Available in the illustrated ledger; not loaded in this static sample"], ["Append failure behavior", "Retain loaded rows and show a load-more error; never replace missing history with success"]])
      ]
    },
    "background-tasks": {
      group: "Operations", title: "Background tasks", subtitle: "Owner-scoped progress and results for detached read-only investigations.",
      note: synthetic + "Inspect requests, outcomes, agent attribution, and retained progress. Refresh or close details does not cancel a task; no task mutation controls are available.",
      kpis: [["Loaded tasks", "3", "owner-scoped sample"], ["Running", "1", "result pending"], ["Succeeded", "1", "read-only task completed"], ["Unknown", "1", "retained evidence absent"]],
      views: [
        { id: "tasks", label: "Tasks", sections: ["background-task-history", "background-task-detail"] },
        { id: "provenance", label: "Provenance", sections: ["background-pagination"] }
      ],
      sections: [
        table("background-task-history", "Task history", ["Requested work", "Accountable agent", "Status", "Outcome", "Updated"], [
          [link("Investigate current readiness", "background-tasks.html?record=example-background-running#background-task-detail"), "Huginn", status("Running", "info"), "Pending", asOf],
          [link("Summarize the baseline comparison", "background-tasks.html?record=example-background-complete#background-task-detail"), "Muninn", status("Succeeded", "success"), "One difference; two unknown states", "2026-09-06T09:10:20Z"],
          [link("Request summary unavailable", "background-tasks.html?record=example-background-unattributed#background-task-detail"), "Unattributed", status("Unknown"), "Result unavailable", "2026-09-06T08:45:00Z"]
        ], "Selection preserves the task identity across detail and progress snapshots."),
        workspace("background-task-detail", "Investigation details", "Retained tasks", backgroundRecords, "Read-only details support refresh and close. Missing request, result, agent attribution, and truncated fields stay explicit."),
        facts("background-pagination", "Page boundary", [["Page size", "50 maximum"], ["Loaded", "3"], ["Has more", "No; next cursor absent"], ["Progress bound", "256 retained events per detail read"]])
      ]
    },
    "automation-blueprints": {
      group: "Operations", title: "Automation blueprints", subtitle: "Evidence-backed recurring-work suggestions and their bounded isolation requirements.",
      note: synthetic + "Read-only suggestions. This route cannot accept, reject, enable, materialize, schedule, or execute automation. A recorded materialized state grants no new authority.",
      kpis: [["Candidates", "3", "bounded response"], ["Accepted", "1", "retained metric"], ["Rejected", "1", "retained metric"], ["Realized usage", "2", "not inferred from acceptance"]],
      views: [
        { id: "candidates", label: "Candidates", sections: ["automation-blueprint-candidates"] },
        { id: "evidence", label: "Evidence", sections: ["blueprint-provenance"] }
      ],
      sections: [
        table("automation-blueprint-candidates", "Blueprint candidates", ["Automation / schedule", "State", "Scope", "Evidence", "Required tools", "Isolation", "Estimated cost", "Confidence"], [
          ["Review detector evidence / 0 8 * * 1", status("Draft"), code("example-scope"), "3 fingerprints", "example-read-readiness", "example-readonly-profile; 4 tool calls", "180000 micro-USD", "92.0%"],
          ["Summarize baseline drift / 0 9 * * 5", status("Materialized", "success"), code("example-scope"), "2 fingerprints", "example-read-baseline", "example-readonly-profile; 2 tool calls", "90000 micro-USD", "89.0%"],
          ["Compare stale observations / 0 7 * * *", status("Rejected", "warning"), code("example-scope"), "1 fingerprint", "example-read-observations", "example-readonly-profile; 3 tool calls", "120000 micro-USD", "61.0%"]
        ], "Counts are evidence fingerprints, not evidence quality. Confidence is a retained candidate score, not permission."),
        facts("blueprint-provenance", "Source and safety boundary", [["Source", code("example-automation-blueprint-projection")], ["Mutation controls", "Unavailable"], ["Candidate IDs", "example-blueprint-readiness; example-blueprint-baseline; example-blueprint-observations"]])
      ]
    },
    "scheduled-continuations": {
      group: "Operations", title: "Scheduled continuations", subtitle: "Scoped conversation anchors for exact scheduled results and evidence.",
      note: synthetic + "Read-only anchors from user context. Scope, observation window, origin, result identity, and expiry are retained; an anchor never creates execution authority.",
      kpis: [["Anchors", "2", "bounded user context"], ["Active", "1", "retained state"], ["Archived", "1", "retained state"], ["Evidence references", "3", "not an evidence-quality score"]],
      views: [
        { id: "anchors", label: "Anchors", sections: ["continuation-anchors"] },
        { id: "provenance", label: "Provenance", sections: ["continuation-provenance"] }
      ],
      sections: [
        table("continuation-anchors", "Continuation anchors", ["Result / run", "State", "Scope", "Observation window", "Origin", "Evidence", "Digest prefix", "Expires"], [
          [link("Readiness review / example-scheduler-run-3", "scheduler-runs.html?task_id=example-scheduled-readiness#scheduler-dispatch-history"), status("Active", "success"), code("example-scope"), "2026-09-05T09:00:00Z - 2026-09-06T09:00:00Z", "teams:example-conversation-1:example-thread-1", "2", code("example-dige"), "2026-09-13T09:00:00Z"],
          ["Baseline comparison / example-baseline-run-1", status("Archived"), code("example-scope"), "2026-08-29T08:00:00Z - 2026-08-30T08:00:00Z", "web:example-conversation-2", "1", code("example-arch"), "2026-09-06T08:00:00Z"]
        ], "Result summaries show their first line and exact run ID. Digest display is a 12-character prefix, not the full digest."),
        facts("continuation-provenance", "Anchor provenance", [["Source", "User context scheduled_continuations"], ["Anchors", "example-anchor-readiness; example-anchor-baseline"], ["Mutation controls", "None"], ["Unavailable boundary", "A missing user-context source is unavailable, not a fabricated empty anchor list"]])
      ]
    },
    "conversation-delivery": {
      group: "Operations", title: "Conversation delivery", subtitle: "Retained outbound delivery reliability and circuit-breaker evidence.",
      note: synthetic + "Read-only delivery metrics. Ambiguous delivery is duplicate risk, not proof of failure. Retry counts are historical evidence; there is no message retry or breaker-reset control.",
      kpis: [["Deliveries", "12", "retained sample"], ["P95 latency", "Not measured", "no retained latency samples"], ["Duplicate risk", "2", "ambiguous outcomes"], ["Retries", "3", "recorded attempts only"], ["Abandoned", "1", "retained terminal state"], ["Acknowledged", "8", "not human approval"]],
      views: [
        { id: "delivery", label: "Delivery", sections: ["conversation-delivery-evidence"] },
        { id: "breakers", label: "Breakers", sections: ["conversation-delivery-breakers"] },
        { id: "provenance", label: "Provenance", sections: ["conversation-delivery-provenance"] }
      ],
      sections: [
        table("conversation-delivery-evidence", "Delivery states", ["State", "Count", "Interpretation"], [
          [status("Delivered", "success"), "8", "Delivery recorded; no managed-resource effect is established."],
          [status("Ambiguous", "warning"), "2", "Remote effect may have happened; blind retry risks duplication."],
          [status("Abandoned", "warning"), "1", "Retained abandonment; no automatic recovery claim."],
          [status("Pending"), "1", "No terminal delivery result recorded."]
        ]),
        table("conversation-delivery-breakers", "Circuit breakers", ["State", "Count", "Boundary"], [
          [status("Closed", "success"), "2", "Stored breaker state, not current channel health."],
          [status("Open", "warning"), "1", "Dispatch suppression is owned by the delivery runtime."],
          [status("Half open", "warning"), "1", "Probe state is retained; no reset control."]
        ], "No recorded breaker entries would be shown as an explicit empty state, not inferred Closed."),
        facts("conversation-delivery-provenance", "Delivery provenance and latency", [
          ["Source", code("example-conversation-delivery-projection")], ["Read only", "true"], ["Mutations available", "false"],
          ["Attempts", "15"], ["Latency samples", "0"], ["Average latency", "Not measured"],
          ["P95 latency", "Not measured"], ["Observation window", "Not provided by this projection"]
        ], "Missing latency remains unknown, never zero. Counts describe this synthetic projection and are not a fleet-wide success rate.")
      ]
    }
  };
}());
