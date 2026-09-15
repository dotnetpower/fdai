import type { ProcessJournalResponse, ProcessSummary } from "./processes.model";

const AT = "2026-09-01T09:00:00Z";
const DIGEST = `sha256:${"a".repeat(64)}`;
const RECORDS: readonly ProcessSummary[] = [
  {
    id: "sample-process-1",
    workflow_ref: "incident-review",
    workflow_version: "1",
    status: "waiting",
    current_step: "independent-approval",
    target_resource_id: "sample-resource",
    updated_at: AT,
    has_view: false,
  },
  {
    id: "sample-process-2",
    workflow_ref: "observation-wait",
    workflow_version: "1",
    status: "waiting",
    current_step: "wait-for-evidence",
    target_resource_id: "example-workload-worker",
    updated_at: AT,
    has_view: false,
  },
  {
    id: "sample-process-3",
    workflow_ref: "baseline-review",
    workflow_version: "1",
    status: "failed",
    current_step: "evidence-gate",
    target_resource_id: "example-workload-api",
    updated_at: AT,
    has_view: false,
  },
];

/** GET-only presentation fixtures; every sample control has no permitted transitions. */
export function sampleProcessResponse(path: string): unknown {
  if (path === "/views/process") {
    return {
      source: "synthetic-preview",
      synthetic: true,
      durable: false,
      principal_scoped: true,
      items: RECORDS,
    };
  }
  const record = RECORDS.find((item) => path === `/views/process/${item.id}/events`);
  return record ? journal(record) : undefined;
}

function journal(record: ProcessSummary): ProcessJournalResponse {
  const review = record.id === "sample-process-1";
  const correlation = review ? "sample-correlation-1" : `sample-correlation-${record.id}`;
  const process = {
    ...record,
    started_at: "2026-09-01T08:50:00Z",
    correlation_id: correlation,
    revision: 3,
  };
  const eventSteps: readonly (readonly [string, string])[] = [
    ["process.created", "shadow workflow recorded"],
    ["step.started", record.current_step],
    ["step.completed", "sample evidence collected"],
    [record.status === "failed" ? "step.failed" : "step.waiting",
      record.status === "failed" ? "independent verification missing" : "waiting for independent evidence"],
  ];
  const events = eventSteps.map(([kind, reason], index) => ({
    event_id: `sample-process-event-${record.id}-${index + 1}`,
    kind,
    recorded_at: `2026-09-01T08:${50 + index}:00Z`,
    correlation_id: correlation,
    causation_id: index ? `sample-process-event-${record.id}-${index}` : null,
    step_id: record.current_step,
    attempt: 1,
    payload: { reason, sample: true },
  }));
  return {
    process,
    events,
    count: events.length,
    control: {
      authoritative: true,
      principal_scoped: true,
      available: true,
      process_revision: 3,
      catalog_revision: "sample-catalog-1",
      mode: "shadow",
      reason: null,
      step: {
        id: record.current_step,
        kind: review ? "approval" : record.status === "waiting" ? "wait" : "gate",
        state: record.status,
        attempt: 1,
        reason: record.status === "failed" ? "verification_missing" : "independent_evidence_pending",
        requirements: review
          ? { approval_role: "Approver", quorum: 2, approved_count: 1, no_self_approval: true }
          : { evidence_state: record.status === "failed" ? "missing" : "pending" },
      },
      permitted_transitions: [],
      acceptance_is_success: false,
    },
    investigation: review ? {
      read_only: true,
      mutation_controls: false,
      process_revision: 3,
      process_id: record.id,
      workflow_version: record.workflow_version,
      incident_id: "sample-incident-latency",
      initial_frame_digest: DIGEST,
      initial_active_set_receipt_digest: DIGEST,
      active_strategy_digest: DIGEST,
      challenger_strategy_digest: null,
      budget: {
        max_rounds: 4,
        max_queries: 6,
        max_cost_units: 8,
        deadline_at: "2026-09-01T09:15:00Z",
        policy_digest: DIGEST,
      },
      rounds: [1, 2].map((index) => ({
        round_index: index,
        iteration_digest: `sha256:${String(index).repeat(64)}`,
        frame_digest: DIGEST,
        evidence_cutoff: `2026-09-01T08:5${index}:00Z`,
        graph_revision: "sample-graph-1",
        active_hypothesis_ids: ["example-hypothesis-rollout", "example-hypothesis-restart"],
        active_set_receipt_digest: DIGEST,
        selection_digest: DIGEST,
        selected_candidate_id: index === 1 ? "example-probe-lifecycle" : null,
        separated_pair_count: 0,
        total_pair_count: 1,
        hold_reason: index === 2 ? "Independent observation missing" : null,
        shadow_comparison_digest: null,
        execution: null,
        revision: null,
      })),
      round_count: 2,
      terminal: {
        result_digest: DIGEST,
        disposition: "insufficient_evidence",
        terminal_frame_digest: DIGEST,
        terminal_active_set_receipt_digest: DIGEST,
        used_queries: 2,
        used_cost_units: 2,
      },
      closure: null,
    } : null,
    planning: review ? {
      current_phase: "revision",
      phase_count: 3,
      phases: ["proposal", "critique", "revision"].map((phase, index) => ({
        phase,
        actor_agent: index === 1 ? "Heimdall" : "Huginn",
        recorded_at: `2026-09-01T08:5${index + 4}:00Z`,
        event_id: `sample-planning-${phase}`,
        evidence_refs: ["sample-evidence-1"],
      })),
      plan: {
        plan_id: "sample-plan-review",
        logic_release_digest: DIGEST,
        complete: false,
        reason: "Independent simulation evidence is missing",
        selected_option_id: null,
        requires_human_approval: true,
        margin: null,
        candidates: [{
          candidate_id: "example-candidate-observe",
          action_type: null,
          disposition: "held",
          reasons: ["Independent simulation evidence is missing"],
          proposing_agents: ["Huginn"],
          logic_receipt_refs: ["sample-logic-1"],
          simulation_receipt_refs: [],
          constraint_evaluation_refs: ["sample-constraint-1"],
          expected_effects: [],
        }],
      },
    } : null,
  };
}
