import {
  sampleConfigurationBaselines,
  sampleDetectionReadiness,
  sampleOnboarding,
} from "./operations.sample-readiness";
import { sampleProcessResponse } from "./operations.sample-processes";

const SAMPLE_AT = "2026-09-01T09:00:00Z";

export {
  OPERATIONS_SAMPLE_CONTINUATIONS,
  OPERATIONS_SAMPLE_LIVE_EVENTS,
  OPERATIONS_SAMPLE_LIVE_HISTORY_COUNT,
  OPERATIONS_SAMPLE_LIVE_LOOP_INTERVAL_MS,
  OPERATIONS_SAMPLE_LIVE_EVENTS_PER_LOOP,
  sampleLiveStageDelay,
  sampleLivePreviewEvents,
  OPERATIONS_SAMPLE_PROVISION_EVENTS,
  OPERATIONS_SAMPLE_LIVE_VISIBLE_COUNT,
  sampleLiveObservations,
  sampleLiveEvents,
} from "./operations.sample-events";

const BACKGROUND_TASK = {
  task_id: "sample-task-1",
  attempt_id: "sample-task-1:1",
  request_summary: "Investigate a sample latency regression after a rollout.",
  request_truncated: false,
  accountable_agent: "Heimdall",
  execution_worker: "background-task-coordinator",
  kind: "read_only_investigation",
  status: "running",
  revision: 2,
  created_at: "2026-09-01T08:55:00Z",
  updated_at: SAMPLE_AT,
  retention_until: "2026-10-01T09:00:00Z",
  lease_expires_at: "2026-09-01T09:05:00Z",
  budget: { max_wall_seconds: 300 },
  usage: { tokens: 1840, cost_microusd: 240, tool_calls: 2 },
  result_summary: null,
  result_truncated: false,
  evidence_refs: ["sample-evidence-1"],
  evidence_truncated: false,
  terminal_reason: null,
  started_at: "2026-09-01T08:55:05Z",
  finished_at: null,
  duration_seconds: null,
  completion_state: null,
};

export function operationsSampleResponse(
  path: string,
  params: URLSearchParams,
): unknown | undefined {
  if (path === "/system/data-sources") {
    return { surface: "read-data-sources", sources: [] };
  }
  if (path === "/incidents") return sampleIncidents();
  if (path === "/audit") return { items: [], next_cursor: null };
  if (path === "/hil-queue") return sampleApprovals();
  if (path === "/onboarding") return sampleOnboarding();
  if (path === "/detection-coverage" || path === "/detection-readiness") {
    return sampleDetectionReadiness();
  }
  if (path === "/configuration-baselines") return sampleConfigurationBaselines();
  if (path === "/views/process" || path.startsWith("/views/process/")) return sampleProcessResponse(path);
  if (path === "/views/workflow-apps") return sampleWorkflowApps();
  if (path === "/scheduler-runs") {
    return sampleSchedulerRuns(params.get("task_id") ?? "inventory-reconciliation");
  }
  if (path === "/background-tasks") {
    return { tasks: [BACKGROUND_TASK], has_more: false, next_cursor: null };
  }
  if (path === "/background-tasks/sample-task-1") return { task: BACKGROUND_TASK };
  if (path === "/background-tasks/sample-task-1/progress") {
    return {
      task_id: "sample-task-1",
      status: "running",
      next_sequence: 2,
      has_more: false,
      events: [
        {
          sequence: 0,
          kind: "task.started",
          message: "Sample investigation started",
          at: "2026-09-01T08:55:05Z",
          usage: {},
        },
        {
          sequence: 1,
          kind: "evidence.collected",
          message: "Two sample evidence references collected",
          at: SAMPLE_AT,
          usage: { tool_calls: 2 },
        },
      ],
    };
  }
  if (path === "/automation-blueprints") return sampleAutomationBlueprints();
  if (path === "/conversation-delivery") return sampleConversationDelivery();
  return undefined;
}

function sampleIncidents() {
  const item = {
    correlation_id: "sample-correlation-001",
    incident_id: "sample-incident-1",
    lifecycle_state: "resolved",
    target_ref: "sample-checkout-vm-01",
    incident_number: "INC-SAMPLE-0001",
    ticket_id: "sample-ticket-1",
    title: "Checkout capacity is below its objective",
    title_source: "recorded_summary",
    source: {
      platform: "Sample Monitor",
      incident_id: "sample-alert-1",
      status: "triggered",
      fired_at: "2026-09-01T08:45:00Z",
      description: "A recorded maintenance change left the checkout VM deallocated.",
      url: null,
    },
    response_plan: {
      id: "sample-checkout-capacity-response",
      revision: "sample-vm-start-rev-1",
      enabled: true,
      historical_match_count: 3,
      reinvestigation_cooldown_seconds: 10800,
      deduplication_key: "sample-checkout-capacity",
    },
    severity: "high",
    status: "resolved",
    status_source: "incident_lifecycle",
    disposition: "resolved",
    verdict: "hil",
    vertical: "resilience",
    opened_at: "2026-09-01T08:45:00Z",
    last_updated_at: SAMPLE_AT,
    latest_mode: "enforce",
    history_count: 2,
    involved_agents: ["Huginn", "Heimdall", "Forseti", "Var", "Thor", "Saga"],
  };
  return {
    items: [item],
    next_cursor: null,
    metrics: {
      source: "synthetic-preview",
      snapshot_seq: 1,
      denominator: 1,
      matched_total: 1,
      truncated: false,
      window_from: "2026-09-01T08:45:00Z",
      window_to: SAMPLE_AT,
      cohorts: {
        agent_mitigated: 0,
        agent_assisted: 1,
        human_mitigated: 0,
        pending: 0,
        integrity_excluded: 0,
      },
      drilldown: {
        agent_mitigated: [],
        agent_assisted: ["sample-correlation-001"],
        human_mitigated: [],
        pending: [],
        integrity_excluded: [],
      },
      drilldown_truncated: {
        agent_mitigated: false,
        agent_assisted: false,
        human_mitigated: false,
        pending: false,
        integrity_excluded: false,
      },
      median_time_to_mitigate_seconds: null,
      time_to_mitigate_sample_size: 0,
      terminal_rule: "resolved_and_independently_verified",
    },
  };
}

function sampleApprovals() {
  return {
    items: [
      {
        idempotency_key: "sample-idempotency-1",
        event_id: "sample-event-1",
        action_kind: "ops.start-vm",
        reason: "Restoring checkout capacity requires per-execution human approval.",
        requested_at: SAMPLE_AT,
        correlation_id: "sample-correlation-002",
        approval_id: "sample-approval-1",
        action_id: "sample-action-1",
        target_resource_ref: "sample-checkout-standby-vm-01",
        mode: "enforce",
        stop_condition: "checkout health remains below the objective after startup",
        rollback_kind: "ops.deallocate-vm",
        rollback_reference: "sample-checkout-standby-vm-rollback",
        blast_radius_scope: "single_resource",
        blast_radius_count: 1,
        blast_radius_rate_per_minute: null,
        blast_radius_summary: "1 synthetic checkout VM",
        reasons: ["The verifier requires a distinct operator to approve this VM start."],
        citing_rule_ids: ["sample.compute.checkout-capacity.conflicting-evidence"],
        ttl_expires_at: "2026-10-01T09:00:00Z",
        decision_requestable: false,
        decision_unavailable_reason: "sample_mode",
      },
    ],
    total: 1,
    detail_level: "full",
  };
}

function sampleWorkflowApps() {
  return {
    items: [
      {
        id: "sample-incident-review",
        workflow_ref: "incident-review",
        view_ref: "incident-review",
        lifecycle: "published",
        audience: "reader",
        label: { en: "Sample incident review", ko: "예시 인시던트 검토" },
        description: {
          en: "Review a sample incident without execution authority.",
          ko: "실행 권한 없이 예시 인시던트를 검토합니다.",
        },
        route: "/workflow-apps/sample-incident-review",
        group: "operations",
        order: 100,
      },
    ],
    count: 1,
  };
}

function sampleSchedulerRuns(taskId: string) {
  return {
    task_id: taskId,
    source: "synthetic-preview",
    durable: false,
    items: [
      {
        run_id: `sample:${taskId}:1`,
        task_id: taskId,
        scheduled_for: "2026-09-01T08:00:00Z",
        claimed_at: "2026-09-01T08:00:01Z",
        status: "published",
        attempt: 1,
        completed_at: "2026-09-01T08:00:03Z",
        error_kind: null,
      },
      {
        run_id: `sample:${taskId}:2`,
        task_id: taskId,
        scheduled_for: "2026-09-01T09:00:00Z",
        claimed_at: SAMPLE_AT,
        status: "claimed",
        attempt: 1,
        completed_at: null,
        error_kind: null,
      },
    ],
    next_cursor: null,
  };
}

function sampleAutomationBlueprints() {
  return {
    source: "synthetic-preview",
    mutation_controls: false,
    count: 1,
    candidates: [
      {
        candidate_id: "sample-blueprint-1",
        state: "draft",
        normalized_task_intent: "review sample inventory drift",
        schedule_expression: "0 3 * * *",
        resource_scope: "sample-scope",
        delivery_intent: "audit-only",
        required_tools: ["query_inventory"],
        isolation_profile: {
          profile_id: "scheduled.default-deny",
          max_session_seconds: 300,
          max_context_chars: 16000,
          max_tool_calls: 0,
          allowed_tool_ids: [],
        },
        estimated_cost_microusd: 100,
        evidence_fingerprints: ["a".repeat(64), "b".repeat(64)],
        confidence: 0.82,
        expires_at: "2026-10-01T09:00:00Z",
        enabled: false,
        shadow_only: true,
        mutation_tool_ids: [],
      },
    ],
    metrics: {
      proposed: 4,
      accepted: 1,
      rejected: 1,
      expired: 1,
      materialized: 1,
      realized_usage: 0,
      candidate_precision: 0.75,
      acceptance_rate: 0.25,
    },
  };
}

function sampleConversationDelivery() {
  return {
    source: "synthetic-preview",
    read_only: true,
    mutations_available: false,
    delivery_count: 48,
    states: { delivered: 43, ambiguous: 3, abandoned: 2 },
    delivery_latency_ms: { count: 43, average: 420, p95: 980 },
    duplicate_risk_count: 3,
    retry_count: 7,
    abandonment_count: 2,
    breaker_states: { closed: 3, paused: 1 },
    attempt_count: 55,
    acknowledgement_count: 41,
  };
}
