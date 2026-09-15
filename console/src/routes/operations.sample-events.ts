import type { AgentOperationalActivityV13Message } from "../agent-operational-activity";
import type { LiveStageEvent } from "../hooks/use-live-stream";
import type { ProvisionEvent } from "../hooks/use-provision-stream";
import type { ScheduledContinuationPayload } from "../user-context-client";

const SAMPLE_AT = "2026-09-01T09:00:00Z";

export const OPERATIONS_SAMPLE_LIVE_VISIBLE_COUNT = 12;
export const OPERATIONS_SAMPLE_LIVE_HISTORY_COUNT = 180;
export const OPERATIONS_SAMPLE_LIVE_LOOP_INTERVAL_MS = 1_000;
export const OPERATIONS_SAMPLE_LIVE_STAGE_INTERVAL_MS = 800;
export const OPERATIONS_SAMPLE_LIVE_EVENTS_PER_LOOP = 3;

export function sampleLiveObservations(
  now = Date.now(),
): readonly AgentOperationalActivityV13Message[] {
  const sourceRead = (
    domain: "metrics" | "activity-log" | null,
    owner: "Heimdall" | "Huginn",
    offsetMs: number,
    durationMs: number,
    resultCount: number,
  ): AgentOperationalActivityV13Message => {
    const observedAt = new Date(now - offsetMs).toISOString();
    const startedAt = new Date(now - offsetMs - durationMs).toISOString();
    const activityInstanceId = domain === null
      ? "inventory.scan:sample-campaign"
      : `observation:${domain}:sample-campaign`;
    const status = domain === null ? "degraded" : "completed";
    return {
      type: "agent.operational-activity",
      schema_version: "1.3.0",
      activity_id: `${activityInstanceId}:${status}`,
      activity_instance_id: activityInstanceId,
      idempotency_key: `${activityInstanceId}:${status}`,
      kind: domain === null ? "inventory.scan" : "observation",
      status,
      owner_agent: owner,
      producer: domain === null ? "inventory-sync-job" : "observation-campaign-job",
      observation_domain: domain,
      observed_at: observedAt,
      source: `sample-${domain ?? "inventory"}`,
      freshness: domain === null ? "stale" : "fresh",
      evidence_count: resultCount,
      duration_ms: durationMs,
      correlation_id: `sample-campaign-${domain ?? "inventory"}`,
      reason_codes: domain === null ? ["source_stale"] : [],
      summary_key: domain === null ? "inventory_collection" : "source_observation",
      scope_class: domain === null ? "configured-estate" : "source-domain",
      target_count: null,
      result_state: "measured",
      result_count: resultCount,
      result_unit: domain === null ? "evidence-items" : "records",
      source_cutoff: observedAt,
      started_at: startedAt,
      completed_at: observedAt,
      execution_authority: false,
    };
  };
  return [
    sourceRead("metrics", "Heimdall", 1_000, 1_400, 0),
    sourceRead("activity-log", "Huginn", 2_000, 6_700, 9),
    sourceRead(null, "Huginn", 3_000, 26, 3_205),
  ];
}

const SAMPLE_WORKLOADS = [
  {
    resourceType: "compute.container-app",
    actionType: "ops.restart",
    target: "sample-container-app",
    scope: "sample-service-ring",
    vertical: "resilience",
    rule: "sample.resilience.restart-threshold",
    impact: "single sample revision",
  },
  {
    resourceType: "compute.virtual-machine",
    actionType: "ops.scale-out",
    target: "sample-vm-scale-set",
    scope: "sample-compute-pool",
    vertical: "cost",
    rule: "sample.cost.capacity-envelope",
    impact: "two sample instances",
  },
  {
    resourceType: "compute.aks",
    actionType: "ops.reconfigure",
    target: "sample-aks-cluster",
    scope: "sample-workload-zone",
    vertical: "change",
    rule: "sample.change.rollout-guard",
    impact: "one sample namespace",
  },
  {
    resourceType: "data.postgresql",
    actionType: "ops.investigate",
    target: "sample-postgresql",
    scope: "sample-data-plane",
    vertical: "resilience",
    rule: "sample.resilience.replica-lag",
    impact: "one sample replica",
  },
  {
    resourceType: "data.storage-account",
    actionType: "ops.rotate",
    target: "sample-storage-account",
    scope: "sample-storage-scope",
    vertical: "change",
    rule: "sample.change.rotation-window",
    impact: "single sample binding",
  },
  {
    resourceType: "network.application-gateway",
    actionType: "ops.reconfigure",
    target: "sample-application-gateway",
    scope: "sample-edge-zone",
    vertical: "resilience",
    rule: "sample.resilience.backend-health",
    impact: "one sample backend pool",
  },
  {
    resourceType: "network.load-balancer",
    actionType: "ops.investigate",
    target: "sample-load-balancer",
    scope: "sample-network-zone",
    vertical: "resilience",
    rule: "sample.resilience.probe-drift",
    impact: "one sample frontend",
  },
  {
    resourceType: "observability.log-analytics",
    actionType: "ops.reconfigure",
    target: "sample-log-workspace",
    scope: "sample-observability-plane",
    vertical: "cost",
    rule: "sample.cost.retention-envelope",
    impact: "one sample table",
  },
  {
    resourceType: "ai.model-deployment",
    actionType: "ops.scale-out",
    target: "sample-model-deployment",
    scope: "sample-ai-capacity",
    vertical: "cost",
    rule: "sample.cost.model-capacity",
    impact: "one sample deployment",
  },
  {
    resourceType: "integration.event-hub",
    actionType: "ops.investigate",
    target: "sample-event-stream",
    scope: "sample-integration-plane",
    vertical: "resilience",
    rule: "sample.resilience.consumer-lag",
    impact: "one sample consumer group",
  },
] as const;
const TIERS = ["t0", "t1", "t2"] as const;
const NON_HIL_DECISIONS = ["auto", "deny", "abstain"] as const;

function sampleDecision(index: number): "auto" | "deny" | "abstain" | "hil" {
  if (index < OPERATIONS_SAMPLE_LIVE_HISTORY_COUNT && index % 60 === 0) return "hil";
  if (index >= OPERATIONS_SAMPLE_LIVE_HISTORY_COUNT && index % 24 === 0) return "hil";
  return NON_HIL_DECISIONS[(index + Math.floor(index / 3)) % NON_HIL_DECISIONS.length]!;
}

function sampleDecisionContext(decision: "auto" | "deny" | "abstain" | "hil") {
  if (decision === "auto") {
    return {
      autonomy: "A1",
      risk: "low",
      reason: "Deterministic sample evidence is inside the bounded policy envelope.",
    };
  }
  if (decision === "hil") {
    return {
      autonomy: "A3-H",
      risk: "high",
      reason: "High-risk sample work requires independent human approval.",
    };
  }
  if (decision === "deny") {
    return {
      autonomy: "A4",
      risk: "critical",
      reason: "The sample blast-radius estimate exceeds the policy limit.",
    };
  }
  return {
    autonomy: "A0",
    risk: "medium",
    reason: "Required sample telemetry is incomplete, so the control loop abstains.",
  };
}

export function sampleLiveEvents(
  start: number,
  count: number,
): readonly LiveStageEvent[] {
  const base = Date.parse("2026-09-01T08:30:00Z");
  return Array.from({ length: count }, (_, offset) => {
    const index = start + offset;
    const sequence = String(index + 1).padStart(3, "0");
    const eventId = `sample-event-${sequence}`;
    const correlationId = `sample-correlation-${sequence}`;
    const workload = SAMPLE_WORKLOADS[index % SAMPLE_WORKLOADS.length]!;
    const tier = TIERS[index % TIERS.length]!;
    const decision = sampleDecision(index);
    const decisionContext = sampleDecisionContext(decision);
    const executionFailed = decision === "auto" && Math.floor(index / 3) % 15 === 5;
    const timestamp = (offset: number) =>
      new Date(base + index * 30_000 + offset * 1_000).toISOString();
    const shared = {
      mode: "shadow",
      autonomy: decisionContext.autonomy,
      resource_type: workload.resourceType,
      action_type: workload.actionType,
      target: `${workload.target}-${String((index % 6) + 1).padStart(2, "0")}`,
      scope: workload.scope,
      vertical: workload.vertical,
      rule: workload.rule,
      reason: decisionContext.reason,
      risk: decisionContext.risk,
      impact: workload.impact,
      latency_budget_ms: 8_000 + (index % 4) * 2_000,
    };
    const frames: LiveStageEvent[] = [
      {
        event_id: eventId,
        correlation_id: correlationId,
        stage: "ingest",
        phase: "done",
        source: "synthetic-dev",
        ts: timestamp(0),
        detail: {
          ...shared,
          event_type: "sample.resource.changed",
          producer_principal: "Huginn",
        },
      },
      {
        event_id: eventId,
        correlation_id: correlationId,
        stage: "route",
        phase: "done",
        source: "synthetic-dev",
        ts: timestamp(1),
        detail: {
          ...shared,
          routed_to: tier,
          producer_principal: "Odin",
        },
      },
      {
        event_id: eventId,
        correlation_id: correlationId,
        stage: "verify",
        phase: "done",
        source: "synthetic-dev",
        ts: timestamp(2),
        detail: {
          ...shared,
          tier,
          producer_principal: "Heimdall",
        },
      },
      {
        event_id: eventId,
        correlation_id: correlationId,
        stage: "gate",
        phase: "done",
        source: "synthetic-dev",
        ts: timestamp(3),
        detail: {
          ...shared,
          tier,
          gate_decision: decision,
          producer_principal: decision === "hil" ? "Var" : "Forseti",
        },
      },
    ];
    if (decision === "auto") {
      frames.push({
        event_id: eventId,
        correlation_id: correlationId,
        stage: "execute",
        phase: executionFailed ? "failed" : "done",
        source: "synthetic-dev",
        ts: timestamp(4),
        detail: {
          ...shared,
          tier,
          gate_decision: decision,
          producer_principal: "Thor",
        },
      });
    }
    frames.push({
      event_id: eventId,
      correlation_id: correlationId,
      stage: "audit",
      phase: executionFailed ? "failed" : "done",
      source: "synthetic-dev",
      ts: timestamp(decision === "auto" ? 5 : 4),
      detail: {
        ...shared,
        tier,
        decision,
        outcome: executionFailed
          ? "simulation_failed"
          : decision === "auto"
            ? "resolved"
            : `${decision}_recorded`,
        producer_principal: "Saga",
      },
    });
    return frames;
  }).flat();
}

export const OPERATIONS_SAMPLE_LIVE_EVENTS = sampleLiveEvents(
  0,
  OPERATIONS_SAMPLE_LIVE_HISTORY_COUNT,
);

export const OPERATIONS_SAMPLE_PROVISION_EVENTS: readonly ProvisionEvent[] = [
  {
    type: "provision.snapshot",
    phase: "snapshot",
    run_id: "sample-provision-run",
    sequence: 12,
    attempt: 1,
    state: "applying",
    current_stage: "initial-inventory",
    stages_completed: 4,
    stages_total: 6,
    last_progress_at: SAMPLE_AT,
    ready: false,
    readiness: {
      database: true,
      semantic: true,
      models: true,
      runtime: true,
      inventory: false,
      system: false,
    },
    stages: [
      { id: "database", status: "completed" },
      { id: "semantic-defaults", status: "completed" },
      { id: "model-deployments", status: "completed" },
      { id: "console", status: "completed" },
      { id: "initial-inventory", status: "active" },
      { id: "system-readiness", status: "pending" },
    ],
  },
];

export const OPERATIONS_SAMPLE_CONTINUATIONS: readonly ScheduledContinuationPayload[] = [
  {
    anchor_id: "sample-anchor-1",
    task_id: "sample-task-1",
    run_id: "sample-run-1",
    owner_principal_id: "sample-principal",
    scope_ref: "sample-scope",
    mode: "origin_thread",
    origin: {
      channel_kind: "console",
      channel_ref: "sample-channel",
      conversation_ref: "sample-conversation",
      thread_ref: null,
      audience: "direct",
    },
    result_digest: `sha256:${"a".repeat(64)}`,
    result_summary: "Sample capacity review completed with no execution authority.",
    evidence_refs: ["sample-evidence-1", "sample-evidence-2"],
    observation_started_at: "2026-09-01T08:30:00Z",
    observation_ended_at: SAMPLE_AT,
    created_at: SAMPLE_AT,
    expires_at: "2026-10-01T09:00:00Z",
    state: "active",
  },
];
