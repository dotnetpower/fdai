/* Audit and operational fixtures remain distinct; no synthetic runtime readiness is inferred. */
(function () {
  "use strict";
  const audit = [
    { seq: 101, time: "2026-09-06T08:12:44Z", agent: "Njord", verb: "abstain", action: "cost.advisory.recorded", correlation: "sample-budget", summary: "Advisory cost review completed for example-resource; no change requested.", outcome: "advisory", tier: "T0", duration: 36 },
    { seq: 102, time: "2026-09-06T08:12:46Z", agent: "Saga", verb: "audit", action: "audit.recorded", correlation: "sample-budget", summary: "Synthetic advisory outcome recorded; no operational effect claimed.", outcome: "recorded", tier: "T0", duration: 4 },
    { seq: 103, time: "2026-09-06T09:29:54Z", agent: "Huginn", verb: "audit", action: "event.normalized", correlation: "sample-observation", summary: "Delayed synthetic ingress normalized with its original event time.", outcome: "recorded", tier: "T0", duration: 12 },
    { seq: 104, time: "2026-09-06T09:29:56Z", agent: "Heimdall", verb: "audit", action: "observation.reviewed", correlation: "sample-observation", summary: "Freshness review completed independently from resource-health assessment.", outcome: "recorded", tier: "T0", duration: 44 },
    { seq: 105, time: "2026-09-06T09:30:00Z", agent: "Saga", verb: "audit", action: "incident.resolution.recorded", correlation: "sample-observation", summary: "Synthetic incident resolution recorded from supplied review evidence.", outcome: "recorded", tier: "T0", duration: 5 },
    { seq: 106, time: "2026-09-06T09:33:07Z", agent: "Vidar", verb: "rollback", action: "rollback.probe", correlation: "sample-recovery", summary: "Shadow rollback probe retained. No rollback was executed against a resource.", outcome: "shadow", tier: "T0", duration: 1250, reason: "The probe does not establish tested rollback readiness for production." },
    { seq: 107, time: "2026-09-06T09:41:22Z", agent: "Forseti", verb: "abstain", action: "verdict.abstain", correlation: "sample-change", summary: "Missing freshness evidence prevents a grounded action decision.", outcome: "abstain", tier: "T1", duration: 64, reason: "Insufficient current evidence; human review required." },
    { seq: 108, time: "2026-09-06T09:44:58Z", agent: "Forseti", verb: "reject", action: "verdict.hil", correlation: "sample-change", summary: "Automatic dispatch denied; human approval remains required.", outcome: "hil", tier: "T1", duration: 112,
      conversation: [["Forseti", "Var", "Current human approval is required. Do not dispatch from this advisory verdict."]] },
    { seq: 109, time: "2026-09-06T09:45:03Z", agent: "Var", verb: "audit", action: "approval.pending", correlation: "sample-change", summary: "Human approval request recorded as pending; silence grants no authority.", outcome: "pending", tier: "T1", duration: 8,
      conversation: [["Var", "Forseti", "Approval is pending. The human and executor identities remain distinct."]] },
    { seq: 110, time: "2026-09-06T09:47:16Z", agent: "Saga", verb: "audit", action: "audit.recorded", correlation: "sample-change", summary: "Pending-approval outcome recorded. Dispatch and effect verification have not occurred.", outcome: "recorded", tier: "T1", duration: 4 },
    { seq: 91, time: "2026-09-05T09:10:00Z", agent: "Var", verb: "approve", action: "approval.recorded", correlation: "sample-prior", summary: "Prior synthetic human approval recorded with an independent executor identity.", outcome: "approved", tier: "T0", duration: 8 },
    { seq: 92, time: "2026-09-05T09:10:02Z", agent: "Thor", verb: "execute", action: "action.dispatch.shadow", correlation: "sample-prior", summary: "Shadow dispatch accepted in a fixture; no managed resource changed.", outcome: "shadow", tier: "T0", duration: 21, reason: "Broker acceptance is not an operational success." }
  ].map((item) => ({
    ...item, id: "sample-audit-" + item.seq, route: [item.agent], kind: item.verb, source: "Synthetic audit",
    lane: null, mode: "shadow", queue: 2, inputs: { evidence: "synthetic fixture", target: "example-resource" },
    outputs: { outcome: item.outcome, managed_resource_effect: "none" }
  }));
  const operational = [
    { id: "sample-op-1", time: "2026-09-06T09:40:00Z", route: ["Huginn"], lane: "inventory.scan", kind: "inventory.scan", correlation: "sample-inventory", summary: "Inventory scan returned 12 synthetic resource records.", context: "Completed observation, not a readiness assessment", domain: null },
    { id: "sample-op-2", time: "2026-09-06T09:40:02Z", route: ["Huginn"], lane: "current-state.read", kind: "current-state.read", correlation: "sample-inventory", summary: "Current-state read retained event time and recorded time.", context: "Synthetic read-only projection", domain: null },
    { id: "sample-op-3", time: "2026-09-06T09:40:04Z", route: ["Huginn"], lane: "inventory.ontology-projection", kind: "inventory.ontology-projection", correlation: "sample-inventory", summary: "Ontology projection recorded the synthetic inventory relationships.", context: "Catalog semantics are not runtime health evidence", domain: null },
    { id: "sample-op-4", time: "2026-09-06T09:42:00Z", route: ["Heimdall"], lane: "observation", kind: "observation", correlation: "sample-observe", summary: "Freshness observation is incomplete: one synthetic source is unobserved.", context: "Outcome: incomplete - no healthy state inferred", domain: "availability" },
    { id: "sample-op-5", time: "2026-09-06T09:43:00Z", route: ["Thor"], lane: null, kind: "state", correlation: null, summary: "Synthetic runtime frame reports idle; no active incident is linked.", context: "Observed waiting state, not an executor-readiness check", domain: null },
    { id: "sample-op-6", time: "2026-09-06T09:46:00Z", route: ["Heimdall", "Forseti"], lane: null, kind: "handoff", correlation: "sample-change", summary: "Freshness evidence is incomplete; refrain from an unsupported resource-health conclusion.", context: "Synthetic event-bus handoff; no direct call", domain: null }
  ].map((item) => ({ ...item, source: "Synthetic operational activity" }));
  window.AgentActivityPreviewData = { audit, operational };
}());
