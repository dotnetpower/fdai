// Synthetic response forms for the Command deck study (deck.html). The engine in deck-sources.js
// replays every form with one turn anatomy: typed intent, read-only preparation, a cited answer,
// structured answer blocks, verification, sources, a run record, and follow-ups.
// Every value is synthetic. Nothing here performs a request, a model call, or a state change.
(function () {
  "use strict";

  window.FdaiDeckForms = function (kit) {
    var intent = kit.intent;
    var check = kit.check;
    var verified = kit.verified;
    var DAY = kit.day;

    function attention(label, detail) {
      return { tone: "attention", mark: "!", label: label, detail: detail };
    }

    // ---------- Answer form: connected resources (shared correlation with Trace and Activity) ----------
    var CONNECTED = {
      sources: {
        graphTarget: { kind: "Inventory", title: "checkout-api", meta: "Resource, container app, generation 2026-09-28T10:40Z", time: "10:40:12", href: "architecture.html" },
        graphLinks: { kind: "Ontology", title: "Direct typed relationships", meta: "6 relationships at depth 1, stored direction preserved", time: "10:40:14", href: "ontology.html" },
        graphAudit: { kind: "Audit", title: "Read correlation sample-query-connected-resources-01", meta: "Target resolved, graph queried, evidence verified", time: "10:40:15", href: "agent-activity.html" },
        revisionHealth: { kind: "Health", title: "checkout-api revision 0042", meta: "Became ready at 02:41 UTC", time: "02:41:07", href: "architecture.html" },
        revisionInventory: { kind: "Inventory", title: "checkout-api", meta: "Running, confirmed at 07:42 UTC", time: "07:42:19", href: "architecture.html" },
        restoreRecord: { kind: "Audit", title: "Restore attempt, example-postgres", meta: "Failed at 02:14 UTC: requested point is outside the retention window", time: "02:14:31", href: "audit.html" },
        retentionHistory: { kind: "Audit", title: "Configuration changes, last 30 days", meta: "No backup_retention_days change recorded", time: "10:41:05", href: "audit.html" }
      },
      tools: {
        graphTarget: { label: "Resolve target", tool: "graph.resolve", input: "query", command: "graph.resolve name=checkout-api kind=Resource", ms: 22,
          output: { resource: "checkout-api", kind: "Resource", generation: DAY + "T10:40:00Z", matches: 1 } },
        graphLinks: { label: "Read graph", tool: "graph.relationships", input: "query", command: "graph.relationships resource=checkout-api depth=1 link_types=contains,depends_on,attached_to", ms: 64,
          output: { resource: "checkout-api", depth: 1, relationships: 6, incoming: 1, outgoing: 5, cutoff: DAY + "T10:40:00Z" } },
        graphAudit: { label: "Verify evidence", tool: "evidence.verify", input: "command", command: "evidence.verify correlation=sample-query-connected-resources-01", ms: 18,
          output: { correlation: "sample-query-connected-resources-01", references: 6, direction_preserved: true, provider_reachability: "not_tested" } },
        revisionHealth: { label: "Read revision health", tool: "health.transitions", input: "query", command: "health.transitions resource=checkout-api window=P1D", ms: 41,
          output: { resource: "checkout-api", revision: "0042", transition: "ready", event_time: DAY + "T02:41:07Z" } },
        revisionInventory: { label: "Read inventory", tool: "inventory.read", input: "query", command: "inventory.read resource=checkout-api fields=state", ms: 37,
          output: { resource: "checkout-api", state: "Running", observed_at: DAY + "T07:42:19Z" } },
        restoreRecord: { label: "Read restore record", tool: "audit.records", input: "query", command: "audit.records kind=restore resource=example-postgres window=P1D", ms: 29,
          output: { resource: "example-postgres", result: "failed", reason: "point_outside_retention", requested_point: DAY + "T02:10:00Z", recorded_at: DAY + "T02:14:31Z" } },
        retentionHistory: { label: "Read change history", tool: "audit.changes", input: "query", command: "audit.changes resource=example-postgres property=backup_retention_days window=P30D", ms: 34,
          output: { resource: "example-postgres", property: "backup_retention_days", changes: 0, window: "P30D" } }
      },
      scenario: {
        label: "Connected resources",
        question: "Show me the resources connected to checkout-api.",
        title: "Resources connected to checkout-api",
        route: "Inventory",
        screen: { route: "inventory", resource: "checkout-api" },
        correlation: "sample-query-connected-resources-01",
        unavailableSources: [],
        stages: [
          intent("List direct relationships", "checkout-api (Resource)", "Direct relationships, depth 1", "Evidence cutoff 10:40 UTC"),
          { label: "Resolve target", detail: "checkout-api, one exact match", phase: "Retrieve", emits: ["graphTarget"] },
          { label: "Read graph", detail: "contains, depends_on, and attached_to at depth 1", phase: "Retrieve", emits: ["graphLinks"] },
          { label: "Verify evidence", detail: "Six references, stored direction preserved", phase: "Ground", emits: ["graphAudit"] },
          check("6 of 6 relationships supported by 3 sources")
        ],
        sources: ["graphTarget", "graphLinks", "graphAudit"],
        answer: [
          { text: "checkout-api{graphTarget} has six direct typed relationships in the selected generation{graphLinks}. One is incoming: runtime-environment contains the service. The other five are outgoing dependencies and attachments{graphAudit}." }
        ],
        blocks: [
          { type: "table", caption: "Direct typed relationships for checkout-api", columns: ["Related resource", "Relationship", "Direction", "Observed"], code: [1],
            rows: [
              ["runtime-environment", "contains", "Incoming", "02:31 UTC"],
              ["event-stream", "depends_on", "Outgoing", "07:11 UTC"],
              ["state-db", "depends_on", "Outgoing", "02:39 UTC"],
              ["secrets", "attached_to", "Outgoing", "07:33 UTC"],
              ["registry", "depends_on", "Outgoing", "07:36 UTC"],
              ["observability", "attached_to", "Outgoing", "07:39 UTC"]
            ] },
          { type: "groups", groups: [
            { tone: "verified", title: "Verified facts", items: ["Six direct links are present.", "Stored direction is preserved."] },
            { tone: "unavailable", title: "Unavailable evidence", items: ["Provider reachability is not tested by this snapshot."] },
            { tone: "unclaimed", title: "Not claimed", items: ["A relationship does not prove causation.", "No change was authorized or executed."] }
          ] }
        ],
        notes: [],
        verification: verified("6 of 6 relationships supported"),
        answerState: null,
        pill: { attention: false, issue: null },
        followups: ["connectedChanged"],
        announce: "Answer ready. Verified: checkout-api has six direct typed relationships."
      },
      followups: {
        connectedChanged: {
          question: "What changed recently for this service?",
          stages: [
            intent("Explain recent verified transitions", "checkout-api (Resource)", "Health and inventory", "Last 24 hours"),
            { label: "Read revision health", detail: "Revision 0042 became ready at 02:41 UTC", phase: "Retrieve", emits: ["revisionHealth"] },
            { label: "Read inventory", detail: "Running, confirmed at 07:42 UTC", phase: "Retrieve", emits: ["revisionInventory"] },
            check("2 of 2 claims supported by 2 sources")
          ],
          sources: ["revisionHealth", "revisionInventory"],
          answer: [{ text: "The latest verified transition is revision 0042 of checkout-api becoming ready at 02:41 UTC{revisionHealth}. Inventory confirmed the current Running state at 07:42 UTC{revisionInventory}." }],
          blocks: [
            { type: "facts", rows: [["Target", "checkout-api"], ["Event time", DAY + ", 02:41 UTC"], ["Known at", DAY + ", 10:41 UTC"], ["Sources", "Resource health, FDAI audit"]] }
          ],
          notes: [{ after: 0, when: "stream", tone: "attention", label: "Not claimed", text: "the sequence establishes timing, not that the revision caused another observed condition." }],
          verification: verified("2 of 2 claims supported"),
          announce: "Answer ready. Verified: 2 of 2 claims supported."
        }
      }
    };

    // ---------- Incident form ----------
    var INCIDENT_SOURCES = {
      incidentRecord: { kind: "Incident", title: "INC-260928-08", meta: "Open, SEV 2 at last record; notification routing", time: "07:17:02", href: "incidents.html",
        facts: [["Recorded state", "Open at last record"], ["Severity", "SEV 2, rationale not recorded"]] },
      auditOpen: { kind: "Audit", title: "audit:68858", meta: "Heimdall recorded Open and SEV 2", time: "07:17:02", href: "audit.html",
        facts: [["Actor", "Heimdall"], ["Mode", "Shadow"], ["Limitation", "The severity rationale is not included."]] },
      auditEscalation: { kind: "Audit", title: "audit:68881", meta: "Approval Sink recorded notification escalation", time: "07:20:46", href: "audit.html",
        facts: [["Actor", "Approval Sink"], ["Mode", "Shadow"], ["Limitation", "No human acknowledgement is included."]] },
      auditRoute: { kind: "Audit", title: "audit:68882", meta: "Notifications Router recorded route_unresolved", time: "07:20:47", href: "audit.html",
        facts: [["Actor", "Notifications Router"], ["Mode", "Shadow"], ["Recorded reason", "route_unresolved, no resolvable channels"],
          ["Limitation", "No current binding readback, delivery receipt, or recovery observation is included."]] },
      routingDown: { kind: "Routing", title: "Route-to-channel bindings", meta: "Not read: no authorized readback in this snapshot", href: "settings-integrations.html", unavailable: true },
      dbPressure: { kind: "Metric", title: "example-db CPU", meta: "Above 90% from 10:05 to 10:35 UTC", time: "10:35:00", href: "dashboard.html" },
      dbChecks: { kind: "Health", title: "example-api connection checks", meta: "2 of 6 timed out at 10:12 and 10:27 UTC", time: "10:27:12", href: "dashboard.html" },
      apiCompute: { kind: "Metric", title: "example-api compute", meta: "CPU 41%, memory 58%, below saturation", time: "10:35:00", href: "dashboard.html" },
      apiRevisions: { kind: "Inventory", title: "example-api revisions", meta: "0043 not ready; last ready 0042 shows the same dependency failure", time: "10:40:30", href: "architecture.html" },
      queryDown: { kind: "Diagnostics", title: "Query-level diagnostics", meta: "Unavailable: not enabled on example-db", href: "settings-diagnostics.html", unavailable: true }
    };

    var INCIDENT_TOOLS = {
      incidentRecord: { label: "Read incident", tool: "incidents.read", input: "query", command: "incidents.read id=INC-260928-08", ms: 26,
        output: { id: "INC-260928-08", state: "open", severity: "SEV2", recorded_at: DAY + "T07:17:02Z", correlation: "corr-notify-08" } },
      auditOpen: { label: "Read audit record", tool: "audit.records", input: "query", command: "audit.records id=68858", ms: 18,
        output: { id: 68858, actor: "heimdall", activity: "incident_open", mode: "shadow", recorded_at: DAY + "T07:17:02Z" } },
      auditEscalation: { label: "Read audit record", tool: "audit.records", input: "query", command: "audit.records id=68881", ms: 17,
        output: { id: 68881, actor: "approval_sink", activity: "notification_escalation", mode: "shadow", acknowledged: null, recorded_at: DAY + "T07:20:46Z" } },
      auditRoute: { label: "Read audit record", tool: "audit.records", input: "query", command: "audit.records id=68882", ms: 19,
        output: { id: 68882, actor: "notifications_router", reason: "route_unresolved", channels: 0, recorded_at: DAY + "T07:20:47Z" } },
      routingDown: { label: "Read route bindings", tool: "routing.bindings", input: "query", command: "routing.bindings incident=INC-260928-08", ms: 12, status: "failed",
        output: { status: "unavailable", reason: "readback_not_authorized" } },
      dbPressure: { label: "Read database CPU", tool: "telemetry.metrics", input: "query", command: "telemetry.metrics resource=example-db metric=cpu_percent window=10:05/10:35", ms: 88,
        output: { resource: "example-db", metric: "cpu_percent", min: 91.2, max: 98.7, window: "10:05/10:35Z" } },
      dbChecks: { label: "Read connection checks", tool: "health.probe_results", input: "query", command: "health.probe_results resource=example-api probe=db-connection window=10:05/10:35", ms: 54,
        output: { resource: "example-api", probe: "db-connection", attempts: 6, timeouts: 2, timeout_ms: 5000 } },
      apiCompute: { label: "Read application compute", tool: "telemetry.metrics", input: "query", command: "telemetry.metrics resource=example-api metric=cpu_percent,memory_percent window=10:05/10:35", ms: 71,
        output: { resource: "example-api", cpu_percent_max: 41, memory_percent_max: 58 } },
      apiRevisions: { label: "Read revisions", tool: "inventory.read", input: "query", command: "inventory.read resource=example-api fields=revisions,readiness", ms: 44,
        output: { resource: "example-api", revisions: [{ id: "0043", ready: false }, { id: "0042", ready: false, last_ready_at: DAY + "T09:58:10Z" }] } },
      queryDown: { label: "Read query diagnostics", tool: "diagnostics.queries", input: "query", command: "diagnostics.queries resource=example-db window=10:05/10:35", ms: 1500, status: "failed",
        output: { status: "unavailable", reason: "diagnostics_not_enabled" } }
    };

    var INCIDENT = {
      label: "Incident",
      route: "Incidents",
      title: "What happened with INC-260928-08?",
      question: "What happened with INC-260928-08, what is affected, and what should I check next?",
      lead: "Bragi summarizes an incident from recorded evidence, keeps unknowns explicit, and proposes only read-only next steps. This preview replays scripted incident briefs.",
      sources: INCIDENT_SOURCES,
      tools: INCIDENT_TOOLS,
      order: ["open", "readiness"],
      scenarios: {
        open: {
          label: "Open incident",
          profile: "operational_brief",
          screen: { route: "incidents", incident: "INC-260928-08" },
          correlation: "corr-notify-08",
          unavailableSources: [],
          stages: [
            intent("Summarize an incident and the next safe check", "INC-260928-08 (Incident)", "Notification routing", "Recorded evidence"),
            { label: "Read incident", detail: "Open, SEV 2 at last record", phase: "Retrieve", emits: ["incidentRecord"] },
            { label: "Read audit records", detail: "3 records, 07:17:02 to 07:20:47 UTC, shadow", phase: "Retrieve", emits: ["auditOpen", "auditEscalation", "auditRoute"] },
            { label: "Read route bindings", detail: "Not authorized: current configuration not read", phase: "Retrieve", emits: ["routingDown"], attention: true },
            check("4 of 4 claims supported; current state unknown", true)
          ],
          sources: ["incidentRecord", "auditOpen", "auditEscalation", "auditRoute", "routingDown"],
          head: { ref: "INC-260928-08 \u00b7 Notification routing", title: "Operational alert route unresolved" },
          answer: [
            { text: "The shadow evaluation found no usable alert channel{auditRoute}. The incident was open at SEV 2 when last recorded{incidentRecord}, and the escalation that followed is not proof that a person received it{auditEscalation}." }
          ],
          blocks: [
            { type: "status", items: [
              { tone: "failure", text: "Open at last record" },
              { tone: "attention", text: "SEV 2", meta: "recorded" },
              { tone: "neutral", text: "Current status unknown" }
            ], note: "Historical evidence \u00b7 " + DAY + ", 07:20:47 UTC \u00b7 Not live" },
            { type: "facts", rows: [
              ["Affected scope", "Notification routing; service and environment unknown"],
              ["Customer impact", "Not established"],
              ["Delivery and recovery", "Not verified"],
              ["Response owner", "Not recorded"]
            ] },
            { type: "note", tone: "attention", label: "Unknown", text: "the current route configuration. No authorized readback is in this snapshot{routingDown}, so no root cause is claimed." },
            { type: "timeline", title: "Recorded timeline", meta: "3 records \u00b7 Shadow",
              note: "Observation window: 3m 45s. This is the span between records, not the incident duration.",
              items: [
                { time: "07:17:02", title: "Incident opened", text: "Heimdall recorded Open and SEV 2. The severity rationale is not included{auditOpen}." },
                { time: "07:20:46", title: "Escalation recorded", text: "Approval Sink recorded notification escalation. No human acknowledgement is included{auditEscalation}." },
                { time: "07:20:47", title: "Route unresolved", text: "Notifications Router recorded `route_unresolved`. No delivery receipt is included{auditRoute}." }
              ],
              after: "No later observation is in this snapshot. Absence of a later record does not prove the incident is still active." },
            { type: "next", text: "Read the current route-to-channel bindings and channel availability. This is a read-only check." }
          ],
          notes: [],
          verification: attention("Current state unknown", "4 of 4 claims supported"),
          answerState: null,
          pill: { attention: true, issue: "1 source not read" },
          followups: ["incidentConfirm", "incidentGaps"],
          announce: "Answer ready. The incident was open at last record; its current state is unknown."
        },
        readiness: {
          label: "Service readiness",
          profile: "operational_brief",
          question: "Why is the example-api revision not becoming ready, and what should we do next?",
          title: "Why is example-api not ready?",
          route: "Dashboard",
          screen: { route: "dashboard", resource: "example-api" },
          unavailableSources: [],
          stages: [
            intent("Explain a readiness failure and the next safe step", "example-api (container app)", "example-api and its declared dependencies", "10:05 to 10:35 UTC"),
            { label: "Read revisions", detail: "0043 not ready; 0042 shows the same dependency failure", phase: "Retrieve", emits: ["apiRevisions"] },
            { label: "Read database CPU", detail: "example-db above 90% for the whole window", phase: "Retrieve", emits: ["dbPressure"] },
            { label: "Read connection checks", detail: "2 of 6 checks timed out", phase: "Retrieve", emits: ["dbChecks"] },
            { label: "Read application compute", detail: "Below saturation", phase: "Retrieve", emits: ["apiCompute"] },
            { label: "Read query diagnostics", detail: "Unavailable: diagnostics not enabled", phase: "Retrieve", emits: ["queryDown"], attention: true },
            check("5 of 5 claims supported; 1 limit preserved", true)
          ],
          sources: ["apiRevisions", "dbPressure", "dbChecks", "apiCompute", "queryDown"],
          head: { ref: "Operational assessment \u00b7 example-api", title: "Database pressure is blocking readiness" },
          answer: [
            { text: "Hold the rollout and recover the shared database before restarting the current revision. example-db stayed above 90% CPU for the whole window{dbPressure}, and 2 of 6 connection checks from example-api timed out{dbChecks}, while the application's own compute stayed below saturation{apiCompute}." },
            { text: "The last ready revision shows the same dependency failure{apiRevisions}, so a rollback alone is not expected to restore service." }
          ],
          blocks: [
            { type: "facts", rows: [["Target", "example-api"], ["Scope", "1 application, 1 shared dependency"], ["Window", "10:05 to 10:35 UTC"], ["Authority", "Read-only assessment"]] },
            { type: "steps", title: "Next safe steps", items: [
              { title: "Freeze rollout", text: "Stop additional rollout activity for example-api." },
              { title: "Prepare a bounded recovery proposal", text: "A typed request with all seven safeguards, not a direct change." },
              { title: "Submit for human review", text: "The server revalidates the request, and a separate executor identity applies any approved change." }
            ] }
          ],
          notes: [{ after: 1, when: "stream", tone: "attention", label: "Limit", text: "query-level diagnostics are unavailable{queryDown}. This answer does not name a slow query or claim that the rollout introduced the database load." }],
          verification: attention("Verified with limits", "5 of 5 claims supported"),
          answerState: null,
          pill: { attention: true, issue: "1 limit" },
          followups: ["readinessProposal", "readinessRollback"],
          announce: "Answer ready. Database pressure is blocking readiness; one limit is preserved."
        }
      },
      followups: {
        incidentConfirm: {
          question: "What would confirm recovery?",
          stages: [
            intent("List the evidence that would confirm recovery", "INC-260928-08 (Incident)", "Notification routing", "After any authorized change"),
            { label: "Read incident", detail: "Open, SEV 2 at last record", phase: "Retrieve", emits: ["incidentRecord"] },
            { label: "Read audit record", detail: "route_unresolved, no delivery receipt", phase: "Retrieve", emits: ["auditRoute"] },
            check("2 of 2 claims supported by 2 sources")
          ],
          sources: ["incidentRecord", "auditRoute"],
          answer: [{ text: "Recovery is confirmed only by fresh, independent evidence for the same target{incidentRecord}. The recorded failure has no delivery receipt{auditRoute}, so each step below is still outstanding." }],
          blocks: [
            { type: "steps", items: [
              { title: "Establish the current scope and owner", text: "Obtain the current incident state and a human acknowledgement through an authorized read." },
              { title: "Inspect the current configuration", text: "Verify the exact route, channel bindings, and channel availability, and compare them with the recorded failure." },
              { title: "Separate change from investigation", text: "Channel configuration and delivery retries are changes, not read-only checks. They need the applicable policy, authorization, approval, and execution safeguards." },
              { title: "Observe the outcome independently", text: "Require a delivery receipt and an authoritative recovery observation for the same target. Dispatch alone is not success." }
            ] }
          ],
          notes: [{ after: 0, when: "stream", tone: "attention", label: "Authority", text: "this checklist grants no approval or execution authority." }],
          verification: verified("2 of 2 claims supported"),
          announce: "Answer ready. Four checks would confirm recovery; all are outstanding."
        },
        incidentGaps: {
          question: "Which evidence is missing?",
          stages: [
            intent("List missing evidence and its consequence", "INC-260928-08 (Incident)", "Notification routing", "Recorded evidence"),
            { label: "Read incident", detail: "Severity rationale not recorded", phase: "Retrieve", emits: ["incidentRecord"] },
            { label: "Read audit record", detail: "Escalation without acknowledgement", phase: "Retrieve", emits: ["auditEscalation"] },
            check("4 of 4 gaps traced to their records")
          ],
          sources: ["incidentRecord", "auditEscalation"],
          answer: [{ text: "Four gaps keep the incident's impact and recovery unknown. None of them can be filled from older records{incidentRecord}." }],
          blocks: [
            { type: "facts", rows: [
              ["Impact scope", "Unknown: service, environment, region, and missed alert count are not recorded"],
              ["Response ownership", "Not recorded: an escalation event alone does not prove someone is responding"],
              ["Delivery and recovery", "Missing: no delivery receipt or independent post-change observation"],
              ["Severity rationale", "Not recorded: SEV 2 is copied from the incident record"]
            ] }
          ],
          notes: [{ after: 0, when: "stream", tone: "attention", label: "Not claimed", text: "customer impact. The escalation record carries no acknowledgement{auditEscalation}." }],
          verification: verified("4 of 4 gaps traced"),
          announce: "Answer ready. Four evidence gaps remain."
        },
        readinessProposal: {
          question: "Draft the recovery proposal",
          stages: [
            intent("Draft a bounded recovery request", "example-api (container app)", "One revision restart after database recovery", "Current"),
            { label: "Read revisions", detail: "0043 is the restart target", phase: "Retrieve", emits: ["apiRevisions"] },
            check("Draft only: nothing is submitted")
          ],
          sources: ["apiRevisions"],
          answer: [{ text: "A recovery proposal is a separate governed request. Open the Change form to review the typed draft, its seven safeguards, and the approval it needs before anything runs{apiRevisions}." }],
          blocks: [
            { type: "next", text: "Review the draft in the Change form. This conversation does not submit or run it.", link: { href: "deck.html?form=change&scenario=proposal", text: "Open the proposal preview" } }
          ],
          notes: [],
          verification: verified("Draft not submitted"),
          announce: "Answer ready. The proposal is a separate request."
        },
        readinessRollback: {
          question: "Why won't a rollback fix it?",
          stages: [
            intent("Explain why rollback is not expected to help", "example-api (container app)", "Revisions 0042 and 0043", "10:05 to 10:35 UTC"),
            { label: "Read revisions", detail: "0042 shows the same dependency failure", phase: "Retrieve", emits: ["apiRevisions"] },
            { label: "Read connection checks", detail: "Timeouts affect both revisions", phase: "Retrieve", emits: ["dbChecks"] },
            check("2 of 2 claims supported by 2 sources")
          ],
          sources: ["apiRevisions", "dbChecks"],
          answer: [{ text: "Revision 0042, the last one that was ready, now fails the same dependency check{apiRevisions}. The connection timeouts come from the shared database, not from code that changed between revisions{dbChecks}." }],
          notes: [],
          verification: verified("2 of 2 claims supported"),
          announce: "Answer ready. Verified: 2 of 2 claims supported."
        }
      }
    };

    // ---------- Change form: governed proposal, effect verification, cancellation ----------
    var CHANGE_SOURCES = {
      actionRestart: { kind: "ActionType", title: "ops.restart-service", meta: "Forward-only restart; resource blast radius; T0 ceiling enforce with approval", catalog: "Catalog 1.0.0", href: "actions.html" },
      restartRegistry: { kind: "Promotion", title: "Promotion registry", meta: "ops.restart-service: enforce with human approval in this example", time: "10:40:02", href: "promotion.html" },
      restartTarget: { kind: "Inventory", title: "example-api revision 0043", meta: "Not ready; single target in example-rg", time: "10:40:30", href: "architecture.html" },
      restartDryRun: { kind: "Receipt", title: "Dry-run receipt", meta: "Succeeded against revision 0043 at 10:40:44 UTC", time: "10:40:44", href: "audit.html" },
      restartAuditPath: { kind: "Audit", title: "Two-phase audit path", meta: "Intent sink configured; completion sink missing", time: "10:40:50", href: "audit.html" },
      effectProvision: { kind: "Observation", title: "Heimdall independent read", meta: "Revision 0043 provisioned and ready at 11:02 UTC", time: "11:02:18", href: "agent-activity.html" },
      effectHealth: { kind: "Health", title: "example-api health endpoint", meta: "200 OK, 5 of 5 probes after 11:02 UTC", time: "11:04:40", href: "dashboard.html" },
      effectTraffic: { kind: "Metric", title: "User request series", meta: "No user traffic entered the window", time: "11:05:00", href: "dashboard.html" },
      executorReceipt: { kind: "Executor", title: "Thor dispatch receipt", meta: "Accepted by the provider API at 11:01:52 UTC", time: "11:01:52", href: "audit.html" },
      resumableWork: { kind: "Work", title: "Resumable conversation work", meta: "1 paused investigation: weekly drift review", time: "10:41:04", href: "scheduler-runs.html" },
      cancelReceipt: { kind: "Audit", title: "Cancellation record", meta: "Weekly drift review cancelled; no live process terminated", time: "10:41:05", href: "audit.html" }
    };

    var CHANGE_TOOLS = {
      actionRestart: { label: "Read ActionType", tool: "action_types.read", input: "query", command: "action_types.read name=ops.restart-service", ms: 14,
        output: { name: "ops.restart-service", rollback_contract: "state_forward_only", blast_radius: "resource", execution_path: "direct_api", ceiling_by_tier: { t0: "enforce_hil" } } },
      restartRegistry: { label: "Read promotion registry", tool: "promotion.registry", input: "query", command: "promotion.registry action_type=ops.restart-service", ms: 19,
        output: { action_type: "ops.restart-service", state: "enforce_hil", since: "2026-09-10" } },
      restartTarget: { label: "Read target", tool: "inventory.read", input: "query", command: "inventory.read resource=example-api revision=0043 fields=readiness,resource_group", ms: 33,
        output: { resource: "example-api", revision: "0043", ready: false, resource_group: "example-rg" } },
      restartDryRun: { label: "Read dry-run receipt", tool: "dry_run.receipts", input: "query", command: "dry_run.receipts action_type=ops.restart-service target=example-api/0043", ms: 27,
        output: { status: "succeeded", target: "example-api/0043", at: DAY + "T10:40:44Z" } },
      restartAuditPath: { label: "Check audit path", tool: "audit.paths", input: "query", command: "audit.paths action_type=ops.restart-service", ms: 16,
        output: { intent_sink: "configured", completion_sink: "missing" } },
      effectProvision: { label: "Read independent observation", tool: "effect.observe", input: "query", command: "effect.observe target=example-api/0043 expect=ready", ms: 62,
        output: { observer: "heimdall", target: "example-api/0043", ready: true, observed_at: DAY + "T11:02:18Z" } },
      effectHealth: { label: "Read health probes", tool: "health.probe_results", input: "query", command: "health.probe_results resource=example-api probe=http window=11:02/11:05", ms: 48,
        output: { probe: "http", attempts: 5, succeeded: 5, status: 200 } },
      effectTraffic: { label: "Read user request series", tool: "telemetry.metrics", input: "query", command: "telemetry.metrics resource=example-api metric=requests,success_rate window=11:02/11:05", ms: 57,
        output: { requests: 0, success_rate: null, reason: "no_user_traffic" } },
      executorReceipt: { label: "Read dispatch receipt", tool: "audit.records", input: "query", command: "audit.records kind=dispatch target=example-api/0043 limit=1", ms: 21,
        output: { executor: "thor", accepted: true, at: DAY + "T11:01:52Z", effect_verified: false } },
      resumableWork: { label: "List resumable work", tool: "work.resumable", input: "query", command: "work.resumable conversation=current", ms: 12,
        output: { items: [{ id: "work-drift-weekly", state: "paused", active_query: false }] } },
      cancelReceipt: { label: "Cancel resumable work", tool: "work.cancel", input: "command", command: "work.cancel id=work-drift-weekly scope=future_resume", ms: 9, authority: "conversation",
        output: { id: "work-drift-weekly", before: "paused", after: "cancelled", live_process_terminated: false } }
    };

    var CHANGE = {
      label: "Change",
      route: "Dashboard",
      title: "Recover example-api",
      question: "Propose the safest recovery for example-api without executing it.",
      lead: "Bragi drafts typed requests, reports verified effects, and records cancellations. The server revalidates every request, and a separate executor identity applies any approved change. This preview replays scripted change conversations.",
      sources: CHANGE_SOURCES,
      tools: CHANGE_TOOLS,
      order: ["proposal", "verification", "cancellation"],
      scenarios: {
        proposal: {
          label: "Governed proposal",
          profile: "governed_proposal",
          screen: { route: "dashboard", resource: "example-api" },
          unavailableSources: [],
          stages: [
            intent("Draft a bounded recovery request", "example-api revision 0043", "One revision restart after database recovery", "Current"),
            { label: "Read ActionType", detail: "ops.restart-service: forward-only, resource blast radius", phase: "Ground", emits: ["actionRestart"] },
            { label: "Read promotion registry", detail: "Enforce with human approval", phase: "Retrieve", emits: ["restartRegistry"] },
            { label: "Read target", detail: "Revision 0043, not ready, example-rg", phase: "Retrieve", emits: ["restartTarget"] },
            { label: "Read dry-run receipt", detail: "Succeeded at 10:40:44 UTC", phase: "Retrieve", emits: ["restartDryRun"] },
            { label: "Check audit path", detail: "Completion sink missing", phase: "Verify", emits: ["restartAuditPath"], attention: true },
            check("Draft complete; 6 of 7 safeguards ready", true)
          ],
          sources: ["actionRestart", "restartRegistry", "restartTarget", "restartDryRun", "restartAuditPath"],
          answer: [
            { text: "I drafted one restart of revision 0043{restartTarget} with `ops.restart-service`{actionRestart}, to run only after example-db recovers. This ActionType runs with human approval{restartRegistry}, and a restart is forward-only: undoing it means starting the service again." },
            { text: "The draft can't be submitted yet. Six safeguards are ready, but the two-phase audit has no completion path{restartAuditPath}." }
          ],
          blocks: [
            { type: "proposal", title: "Restart example-api revision 0043", state: "Not submitted",
              fields: [["ActionType", "ops.restart-service"], ["Target", "example-api / 0043"], ["Blast radius", "1 resource"], ["Approval", "Human approval required"]],
              safeguards: [
                { label: "Stop condition", state: "ready", detail: "3 provider errors or 300 s" },
                { label: "Tested rollback", state: "ready", detail: "Forward-only: restart again" },
                { label: "Blast-radius limit", state: "ready", detail: "One revision" },
                { label: "Successful dry run", state: "ready", detail: "10:40:44 UTC" },
                { label: "Logical-target lock", state: "ready", detail: "example-api/0043" },
                { label: "Stable idempotency key", state: "ready", detail: "restart-0043-0928" },
                { label: "Two-phase audit", state: "missing", detail: "No completion path" }
              ],
              actions: [
                { label: "Submit for human review", action: "submit-proposal", disabled: true, reason: "Blocked until all seven safeguards are ready" },
                { label: "Discard draft", action: "discard-proposal" }
              ] }
          ],
          notes: [],
          verification: attention("Blocked", "6 of 7 safeguards ready"),
          answerState: null,
          pill: { attention: true, issue: "1 safeguard missing" },
          followups: ["changeAuditPath", "changeWhoRuns"],
          announce: "Draft ready but blocked. The two-phase audit safeguard is missing."
        },
        verification: {
          label: "Effect verification",
          profile: "recovery_verification",
          clock: "11:05:30",
          question: "Did the restart actually fix example-api?",
          title: "Did the restart fix example-api?",
          screen: { route: "dashboard", resource: "example-api" },
          unavailableSources: [],
          stages: [
            intent("Verify the effect of an approved change", "example-api revision 0043", "Platform and user path", "11:01 to 11:05 UTC"),
            { label: "Read dispatch receipt", detail: "Accepted by the provider API", phase: "Retrieve", emits: ["executorReceipt"] },
            { label: "Read independent observation", detail: "Revision ready at 11:02 UTC", phase: "Verify", emits: ["effectProvision"] },
            { label: "Read health probes", detail: "5 of 5 succeeded", phase: "Verify", emits: ["effectHealth"] },
            { label: "Read user request series", detail: "No user traffic in the window", phase: "Verify", emits: ["effectTraffic"], attention: true },
            check("Platform effect verified; user path not verified", true)
          ],
          sources: ["effectProvision", "effectHealth", "effectTraffic", "executorReceipt"],
          answer: [
            { text: "The platform recovered: an independent read saw revision 0043 ready at 11:02 UTC{effectProvision}, and 5 of 5 health probes succeeded afterwards{effectHealth}. User-path recovery is not verified yet, because no user traffic entered the window{effectTraffic}." }
          ],
          blocks: [
            { type: "groups", groups: [
              { tone: "verified", title: "Verified", items: ["Revision 0043 is provisioned and ready.", "The health endpoint answers 200 OK."] },
              { tone: "unavailable", title: "Not yet verified", items: ["Success rate and latency under user traffic."] },
              { tone: "unclaimed", title: "Not claimed", items: ["The provider accepting the restart is not proof of recovery."] }
            ] }
          ],
          notes: [{ after: 0, when: "stream", tone: "attention", label: "Not success on its own", text: "the executor's dispatch receipt only shows the provider accepted the request{executorReceipt}." }],
          verification: attention("Partially verified", "Platform verified, user path pending"),
          answerState: "partial",
          pill: { attention: true, issue: "user path pending" },
          followups: ["changeWhenVerified"],
          announce: "Answer ready. The platform effect is verified; user-path recovery is not verified yet."
        },
        cancellation: {
          label: "Cancellation",
          profile: "cancellation_receipt",
          question: "Cancel the investigation and tell me exactly what stopped.",
          title: "Cancel the investigation",
          route: "Scheduler runs",
          screen: { route: "scheduler-runs" },
          authority: "Conversation state only",
          unavailableSources: [],
          stages: [
            intent("Cancel resumable conversation work", "Current conversation", "Resumable work only", "Now"),
            { label: "List resumable work", detail: "1 paused investigation, no active query", phase: "Retrieve", emits: ["resumableWork"] },
            { label: "Cancel resumable work", detail: "Future resume removed; no managed resource touched", phase: "Record", emits: ["cancelReceipt"] },
            check("Cancellation recorded")
          ],
          sources: ["resumableWork", "cancelReceipt"],
          answer: [
            { text: "No active query was interrupted: the only resumable work was a paused investigation{resumableWork}. It is now cancelled, so it can't restart later{cancelReceipt}." }
          ],
          blocks: [
            { type: "table", caption: "Cancellation outcome for resumable work", columns: ["Work item", "Before", "After", "Stopped scope"],
              rows: [["Weekly drift review", "Paused", "Cancelled", "Future resume only. No live process was terminated."]] }
          ],
          notes: [],
          verification: verified("Cancellation recorded"),
          answerState: null,
          pill: { attention: false, issue: null },
          followups: ["changeResume"],
          announce: "Cancellation recorded. No active query was interrupted."
        }
      },
      followups: {
        changeAuditPath: {
          question: "What would unblock the two-phase audit?",
          stages: [
            intent("Explain a missing safeguard", "ops.restart-service (ActionType)", "Two-phase audit", "Current"),
            { label: "Check audit path", detail: "Intent sink configured, completion sink missing", phase: "Verify", emits: ["restartAuditPath"], attention: true },
            check("1 of 1 claims supported", true)
          ],
          sources: ["restartAuditPath"],
          answer: [{ text: "The audit records intent before dispatch, but has nowhere to record completion{restartAuditPath}. A platform owner has to configure the completion sink; the conversation can't change it." }],
          notes: [],
          verification: verified("1 of 1 claims supported"),
          announce: "Answer ready. The completion sink must be configured by a platform owner."
        },
        changeWhoRuns: {
          question: "Who would run the restart?",
          stages: [
            intent("Explain approval and executor separation", "ops.restart-service (ActionType)", "Approval and execution", "Current"),
            { label: "Read promotion registry", detail: "Enforce with human approval", phase: "Retrieve", emits: ["restartRegistry"] },
            check("2 of 2 claims supported")
          ],
          sources: ["restartRegistry"],
          answer: [{ text: "A person approves the request, and a separate executor identity runs it; neither the conversation nor the approver's identity applies the change{restartRegistry}. The server checks the request again before dispatch." }],
          notes: [],
          verification: verified("2 of 2 claims supported"),
          announce: "Answer ready. Approval and execution use separate identities."
        },
        changeWhenVerified: {
          question: "When will the user path be verified?",
          stages: [
            intent("Explain the pending verification", "example-api (container app)", "User path", "Next traffic window"),
            { label: "Read user request series", detail: "No user traffic yet", phase: "Verify", emits: ["effectTraffic"] },
            check("1 of 1 claims supported")
          ],
          sources: ["effectTraffic"],
          answer: [{ text: "Only after real user requests reach revision 0043. The request series is empty so far{effectTraffic}, so FDAI keeps the effect partially verified instead of assuming success." }],
          notes: [],
          verification: verified("1 of 1 claims supported"),
          announce: "Answer ready. Verification waits for user traffic."
        },
        changeResume: {
          question: "Can I resume it later?",
          stages: [
            intent("Explain what a cancellation removes", "Weekly drift review (work item)", "Resumable work", "Now"),
            { label: "Read cancellation record", detail: "Future resume removed", phase: "Retrieve", emits: ["cancelReceipt"] },
            check("1 of 1 claims supported")
          ],
          sources: ["cancelReceipt"],
          answer: [{ text: "No. Cancelling removed the ability to resume this work{cancelReceipt}. Ask the question again to start a new investigation with a fresh plan and fresh reads." }],
          notes: [],
          verification: verified("1 of 1 claims supported"),
          announce: "Answer ready. Cancelled work cannot be resumed."
        }
      }
    };

    // ---------- Memory and documents form ----------
    var MEMORY_SOURCES = {
      lessonIncident: { kind: "Incident", title: "incident:example-017", meta: "Readiness failed while example-db was saturated", time: "08:52:00", href: "incidents.html" },
      lessonEvidence: { kind: "Evidence", title: "evidence:db-218", meta: "Connection timeouts during sustained CPU pressure", time: "08:50:00", href: "audit.html" },
      memoryPolicy: { kind: "Policy", title: "Memory retention policy", meta: "Consent required; raw logs, secrets, and unverified claims excluded", catalog: "Settings", href: "settings-memory.html" },
      docContract: { kind: "Contract", title: "Investigation response contract", meta: "Immutable sections and output fields", catalog: "Catalog 1.0.0", href: "conversation-response-patterns.html" },
      docEvidence: { kind: "Evidence", title: "Verified evidence projection", meta: "3 findings and 2 limits from 10:05 to 10:35 UTC", time: "10:35:00", href: "audit.html" },
      docMemory: { kind: "Memory", title: "Consented memory record", meta: "1 record: readiness and database saturation", time: "09:12:40", href: "settings-memory.html" }
    };

    var MEMORY_TOOLS = {
      lessonIncident: { label: "Read incident", tool: "incidents.read", input: "query", command: "incidents.read id=example-017", ms: 24,
        output: { id: "example-017", summary: "readiness_failed", dependency: "example-db", state: "resolved" } },
      lessonEvidence: { label: "Read evidence", tool: "evidence.read", input: "query", command: "evidence.read id=db-218", ms: 31,
        output: { id: "db-218", signature: "connection_timeout", condition: "cpu_percent > 90" } },
      memoryPolicy: { label: "Read retention policy", tool: "memory.policy", input: "query", command: "memory.policy scope=operator", ms: 11,
        output: { consent_required: true, excluded: ["raw_logs", "secrets", "temporary_state", "unverified_claims"] } },
      docContract: { label: "Read response contract", tool: "contracts.read", input: "query", command: "contracts.read name=investigation-response", ms: 13,
        output: { name: "investigation-response", sections: 5, execution_authority: false } },
      docEvidence: { label: "Read verified evidence", tool: "evidence.projection", input: "query", command: "evidence.projection investigation=example-api-readiness", ms: 35,
        output: { findings: 3, limits: 2, window: "10:05/10:35Z" } },
      docMemory: { label: "Read consented memory", tool: "memory.read", input: "query", command: "memory.read scope=operator consented=true", ms: 15,
        output: { records: 1, topic: "readiness_database_saturation" } }
    };

    var DOCUMENT_SOURCE = [
      "# Application readiness investigation",
      "",
      "> **Status:** Review required  ",
      "> **Authority:** Read-only  ",
      "> **Evidence window:** 10:05-10:35 UTC",
      "",
      "## Objective",
      "Determine why `example-api` is not becoming ready.",
      "",
      "## Verified findings",
      "- Database CPU remained above the operating threshold.",
      "- Two connection checks timed out.",
      "- Application compute remained below saturation.",
      "",
      "## Limits",
      "- Query-level diagnostics were unavailable.",
      "- No individual query or rollout is claimed as the cause.",
      "",
      "## Response procedure",
      "1. Freeze additional rollout activity.",
      "2. Complete all seven safeguards.",
      "3. Submit the typed request for human review."
    ].join("\n");

    var MEMORY = {
      label: "Memory and documents",
      route: "Incidents",
      title: "Retain a lesson",
      question: "What reusable lesson should be retained from this incident?",
      lead: "Bragi proposes memory only with consent and renders verified documents from governed inputs. This preview replays scripted memory and document requests.",
      sources: MEMORY_SOURCES,
      tools: MEMORY_TOOLS,
      order: ["retention", "document"],
      scenarios: {
        retention: {
          label: "Memory retention",
          profile: "memory_retention",
          screen: { route: "incidents", incident: "example-017" },
          unavailableSources: [],
          stages: [
            intent("Propose a reusable lesson", "incident:example-017 (Incident)", "Verified cause and reuse condition", "Incident lifetime"),
            { label: "Read incident", detail: "Readiness failed during database saturation", phase: "Retrieve", emits: ["lessonIncident"] },
            { label: "Read evidence", detail: "Timeouts under sustained CPU pressure", phase: "Retrieve", emits: ["lessonEvidence"] },
            { label: "Read retention policy", detail: "Consent required; exclusions apply", phase: "Ground", emits: ["memoryPolicy"] },
            check("3 of 3 fields supported by 3 sources")
          ],
          sources: ["lessonIncident", "lessonEvidence", "memoryPolicy"],
          answer: [
            { text: "One lesson is reusable: readiness failed because connection checks timed out while the shared database was saturated{lessonIncident}{lessonEvidence}. Nothing is stored until you review and consent{memoryPolicy}." }
          ],
          blocks: [
            { type: "consent", title: "Retention request", state: "Consent required", stateTone: "attention",
              fields: [["Symptom", "Readiness failed while a shared database was saturated."], ["Verified cause", "Connection checks timed out during sustained pressure."],
                ["Reuse condition", "Only with the same dependency edge and timeout signature."], ["Provenance", "incident:example-017 and evidence:db-218"]],
              excluded: "Raw logs, secrets, temporary state, and unverified claims are excluded.",
              actions: [
                { label: "Review retention request", action: "review-memory" },
                { label: "Discard", action: "discard-memory" }
              ] }
          ],
          notes: [],
          verification: verified("3 of 3 fields supported"),
          answerState: null,
          pill: { attention: false, issue: null },
          followups: ["memoryWhere", "memoryExcluded"],
          announce: "Answer ready. One lesson is proposed; consent is required before retention."
        },
        document: {
          label: "Markdown document",
          profile: "markdown_document",
          question: "Show the investigation response contract as a clean Markdown document.",
          title: "Readiness investigation document",
          route: "Dashboard",
          screen: { route: "dashboard", resource: "example-api" },
          unavailableSources: [],
          stages: [
            intent("Render a document from verified inputs", "example-api readiness investigation", "Response contract and verified evidence", "10:05 to 10:35 UTC"),
            { label: "Read response contract", detail: "5 immutable sections", phase: "Ground", emits: ["docContract"] },
            { label: "Read verified evidence", detail: "3 findings and 2 limits", phase: "Retrieve", emits: ["docEvidence"] },
            { label: "Read consented memory", detail: "1 record", phase: "Retrieve", emits: ["docMemory"] },
            check("Document assembled from 3 governed inputs")
          ],
          sources: ["docContract", "docEvidence", "docMemory"],
          answer: [
            { text: "Here is the investigation as a Markdown document. Its sections come from the response contract{docContract}, and every finding and limit comes from the verified evidence{docEvidence}{docMemory}." }
          ],
          blocks: [
            { type: "document", assembly: ["5 sections", "3 governed inputs", "assembly:7d4c2a1f"],
              title: "Application readiness investigation",
              meta: [["Status", "Review required"], ["Authority", "Read-only"], ["Evidence window", "10:05-10:35 UTC"]],
              sections: [
                { heading: "Objective", paragraphs: ["Determine why `example-api` is not becoming ready and identify the next safe step without changing a managed resource."] },
                { heading: "Verified findings", list: ["Database CPU remained above the operating threshold.", "Two connection checks timed out in the same evidence window.", "Application CPU and memory remained below saturation."] },
                { heading: "Limits", list: ["Query-level diagnostics were unavailable.", "No individual query or rollout is claimed as the cause."] },
                { heading: "Response procedure", ordered: ["Freeze additional rollout activity.", "Prepare a recovery proposal with all seven safeguards.", "Submit the typed request for independent human review."] },
                { heading: "Output contract", table: { caption: "Markdown response output contract", columns: ["Field", "Required value"],
                  rows: [["Conclusion", "Evidence-qualified and time-bounded"], ["Missing evidence", "Explicitly preserved"], ["Execution", "Not authorized"]] } },
                { heading: "Machine-readable summary", code: ["disposition: answered", "evidence: complete", "presentation_profile: markdown_document",
                  "assembly_mode: dynamic", "assembly_digest: 7d4c2a1f", "execution_authority: false"].join("\n") }
              ],
              source: DOCUMENT_SOURCE }
          ],
          notes: [],
          verification: verified("3 governed inputs, 0 unsupported claims"),
          answerState: null,
          pill: { attention: false, issue: null },
          followups: ["documentInputs"],
          announce: "Document ready. Assembled from 3 governed inputs."
        }
      },
      followups: {
        memoryWhere: {
          question: "Where would this lesson be used?",
          stages: [
            intent("Explain where a retained lesson applies", "Proposed lesson", "Reuse condition", "After consent"),
            { label: "Read retention policy", detail: "Reuse bound to the declared condition", phase: "Ground", emits: ["memoryPolicy"] },
            check("1 of 1 claims supported")
          ],
          sources: ["memoryPolicy"],
          answer: [{ text: "Only in a later conversation whose evidence shows the same dependency edge and timeout signature{memoryPolicy}. It is shown as context, never as evidence, and you can remove it in Settings." }],
          notes: [],
          verification: verified("1 of 1 claims supported"),
          announce: "Answer ready. The lesson applies only under its reuse condition."
        },
        memoryExcluded: {
          question: "What is left out?",
          stages: [
            intent("Explain retention exclusions", "Proposed lesson", "Retention policy", "Current"),
            { label: "Read retention policy", detail: "4 excluded categories", phase: "Ground", emits: ["memoryPolicy"] },
            check("1 of 1 claims supported")
          ],
          sources: ["memoryPolicy"],
          answer: [{ text: "Raw logs, secrets, temporary state, and any claim that verification did not support{memoryPolicy}. The lesson keeps only the verified cause, its reuse condition, and where it came from." }],
          notes: [],
          verification: verified("1 of 1 claims supported"),
          announce: "Answer ready. Four categories are excluded."
        },
        documentInputs: {
          question: "Which inputs built this document?",
          stages: [
            intent("List the document inputs", "Readiness investigation document", "Assembly inputs", "Current"),
            { label: "Read response contract", detail: "Immutable sections", phase: "Ground", emits: ["docContract"] },
            { label: "Read verified evidence", detail: "Findings and limits", phase: "Retrieve", emits: ["docEvidence"] },
            { label: "Read consented memory", detail: "1 record", phase: "Retrieve", emits: ["docMemory"] },
            check("3 of 3 inputs traced")
          ],
          sources: ["docContract", "docEvidence", "docMemory"],
          answer: [{ text: "Three governed inputs: the immutable response contract{docContract}, the verified evidence projection{docEvidence}, and one consented memory record{docMemory}. No other text entered the document." }],
          notes: [],
          verification: verified("3 of 3 inputs traced"),
          announce: "Answer ready. Three governed inputs built the document."
        }
      }
    };

    // A held answer: verification rejected a causal claim, so only verified facts remain.
    var UNVERIFIED = {
      label: "Unverified",
      profile: "evidence_posture",
      question: "Did the retention change cause last night's restore failure on example-postgres?",
      title: "Did the retention change cause the restore failure?",
      unavailableSources: [],
      stages: [
        intent("Explain the cause of a failure", "example-postgres (postgresql-server)", "Restore attempt and retention history", "Last 30 days"),
        { label: "Read restore record", detail: "Failed at 02:14 UTC: point outside the retention window", phase: "Retrieve", emits: ["restoreRecord"] },
        { label: "Read inventory", detail: "backup_retention_days 3, observed 10:40:52 UTC", phase: "Retrieve", emits: ["inventory"] },
        { label: "Read change history", detail: "No retention change in 30 days", phase: "Retrieve", emits: ["retentionHistory"] },
        check("Causal claim unsupported after one regeneration; answer held", true)
      ],
      sources: ["restoreRecord", "inventory", "retentionHistory"],
      answer: [
        { text: "I can't confirm that a retention change caused it. The restore at 02:14 UTC failed because the requested point was outside the retention window{restoreRecord}, and retention is currently 3 days{inventory}. No retention change is recorded in the last 30 days{retentionHistory}." }
      ],
      notes: [{ after: 0, when: "stream", tone: "conflict", label: "Held", text: "verification rejected the causal claim twice, so this answer shows only verified facts." }],
      verification: { tone: "failure", mark: "!", label: "Not verified", detail: "Causal claim unsupported" },
      answerState: "unverified",
      pill: { attention: true, issue: "unsupported claim" },
      followups: ["unverifiedRestore"],
      announce: "Answer held. The causal claim could not be verified."
    };

    var UNVERIFIED_FOLLOWUPS = {
      unverifiedRestore: {
        question: "Show the restore attempt",
        stages: [
          intent("Show a recorded restore attempt", "example-postgres (postgresql-server)", "Restore records", "Last 24 hours"),
          { label: "Read restore record", detail: "1 failed attempt", phase: "Retrieve", emits: ["restoreRecord"] },
          check("1 of 1 claims supported")
        ],
        sources: ["restoreRecord"],
        answer: [{ text: "One restore was attempted, and it failed because its requested point was older than the retention window allowed{restoreRecord}." }],
        blocks: [
          { type: "facts", rows: [["Requested point", "02:10 UTC"], ["Oldest restorable point", "3 days earlier"], ["Result", "Failed"], ["Recorded", "02:14 UTC"]] }
        ],
        notes: [],
        verification: verified("1 of 1 claims supported"),
        announce: "Answer ready. Verified: 1 of 1 claims supported."
      }
    };

    return {
      answer: { sources: CONNECTED.sources, tools: CONNECTED.tools, scenarios: { unverified: UNVERIFIED, connected: CONNECTED.scenario },
        followups: Object.assign({}, CONNECTED.followups, UNVERIFIED_FOLLOWUPS) },
      incident: INCIDENT,
      change: CHANGE,
      memory: MEMORY
    };
  };
})();
