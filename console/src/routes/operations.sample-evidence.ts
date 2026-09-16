import type {
  AuditItem,
  IncidentOutcomeCohort,
  IncidentSummary,
  RcaView,
} from "../types";
import { getLocale } from "../i18n";

const SAMPLE_AT = "2026-09-01T09:00:00Z";
const COMPLETED_CORRELATION = "sample-correlation-001";
const PENDING_CORRELATION = "sample-correlation-002";
const sampleText = (english: string, korean: string): string =>
  getLocale() === "ko" ? korean : english;

const SAMPLE_INCIDENTS = [
  {
    correlation_id: COMPLETED_CORRELATION,
    incident_id: "sample-incident-1",
    lifecycle_state: "resolved",
    target_ref: "sample-checkout-vm-01",
    incident_number: "INC-SAMPLE-0001",
    ticket_id: "sample-ticket-1",
    title: sampleText(
      "Checkout capacity is below its objective",
      "결제 처리 서버 용량이 목표보다 낮음",
    ),
    title_source: "recorded_summary",
    source: {
      platform: "Sample Monitor",
      incident_id: "sample-alert-1",
      status: "resolved",
      fired_at: "2026-09-01T08:45:00Z",
      description: sampleText(
        "A recorded maintenance change left the checkout VM deallocated.",
        "기록된 유지보수 후 결제 처리 VM이 할당 해제 상태로 남았습니다.",
      ),
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
    history_count: 6,
    involved_agents: ["Huginn", "Heimdall", "Forseti", "Var", "Thor", "Saga"],
  },
  {
    correlation_id: PENDING_CORRELATION,
    incident_id: "sample-incident-2",
    lifecycle_state: "triaging",
    target_ref: "sample-checkout-standby-vm-01",
    incident_number: "INC-SAMPLE-0002",
    ticket_id: "sample-ticket-2",
    title: sampleText(
      "Checkout capacity recovery is waiting for approval",
      "결제 처리 용량 복구가 사람 승인을 기다리는 중",
    ),
    title_source: "recorded_summary",
    source: {
      platform: "Sample Monitor",
      incident_id: "sample-alert-2",
      status: "triggered",
      fired_at: "2026-09-01T08:45:00Z",
      description: sampleText(
        "One of three checkout VMs remained deallocated after maintenance.",
        "결제 처리 VM 3대 중 1대가 유지보수 후 할당 해제 상태로 남았습니다.",
      ),
      url: null,
    },
    response_plan: {
      id: "sample-checkout-capacity-approval",
      revision: "sample-vm-start-rev-2",
      enabled: true,
      historical_match_count: 3,
      reinvestigation_cooldown_seconds: 10800,
      deduplication_key: "sample-checkout-capacity-approval",
    },
    severity: "high",
    status: "open",
    status_source: "incident_lifecycle",
    disposition: "awaiting_hil",
    verdict: "hil",
    vertical: "resilience",
    opened_at: "2026-09-01T08:45:00Z",
    last_updated_at: "2026-09-01T08:48:00Z",
    latest_mode: "enforce",
    history_count: 3,
    involved_agents: ["Huginn", "Forseti", "Var"],
  },
] satisfies readonly IncidentSummary[];

interface SampleAuditRecord {
  readonly seq: number;
  readonly correlationId: string;
  readonly eventId: string;
  readonly actor: string;
  readonly actionKind: string;
  readonly stage: string;
  readonly decision: string | null;
  readonly reason: string;
  readonly actionId: string | null;
  readonly attempt: number | null;
  readonly executionPath: string | null;
  readonly outcome: string;
  readonly targetResourceRef: string;
  readonly recordedAt: string;
}

function sampleAuditItem(record: SampleAuditRecord): AuditItem {
  return {
    seq: record.seq,
    event_id: record.eventId,
    correlation_id: record.correlationId,
    actor: record.actor,
    action_kind: record.actionKind,
    mode: "enforce",
    entry: {
      stage: record.stage,
      decision: record.decision,
      reason: record.reason,
      action_id: record.actionId,
      attempt: record.attempt,
      execution_path: record.executionPath,
      outcome: record.outcome,
      target_resource_ref: record.targetResourceRef,
      tier: "t0",
      vertical: "resilience",
    },
    entry_hash: `sample-entry-hash-${record.seq}`,
    previous_hash: `sample-entry-hash-${record.seq - 1}`,
    recorded_at: record.recordedAt,
  };
}

const SAMPLE_AUDIT_ITEMS = [
  sampleAuditItem({
    seq: 2003,
    correlationId: PENDING_CORRELATION,
    eventId: "sample-approval-event-1",
    actor: "Var",
    actionKind: "hil.pending",
    stage: "approval",
    decision: "hil",
    reason: sampleText(
      "A distinct human decision is required before the VM start can be dispatched.",
      "VM 시작을 전달하기 전에 별도 사람의 결정이 필요합니다.",
    ),
    actionId: "sample-action-1",
    attempt: 1,
    executionPath: "human_approval",
    outcome: "awaiting_hil",
    targetResourceRef: "sample-checkout-standby-vm-01",
    recordedAt: "2026-09-01T08:48:00Z",
  }),
  sampleAuditItem({
    seq: 2002,
    correlationId: PENDING_CORRELATION,
    eventId: "sample-approval-event-1",
    actor: "Forseti",
    actionKind: "risk_gate.evaluate",
    stage: "gate",
    decision: "hil",
    reason: sampleText(
      "Starting the checkout VM requires independent human approval.",
      "결제 처리 VM을 시작하려면 독립적인 사람 승인이 필요합니다.",
    ),
    actionId: "sample-action-1",
    attempt: 1,
    executionPath: "human_approval",
    outcome: "approval_required",
    targetResourceRef: "sample-checkout-standby-vm-01",
    recordedAt: "2026-09-01T08:47:00Z",
  }),
  sampleAuditItem({
    seq: 2001,
    correlationId: PENDING_CORRELATION,
    eventId: "sample-approval-event-1",
    actor: "Huginn",
    actionKind: "incident.open",
    stage: "ingest",
    decision: null,
    reason: sampleText(
      "One of three checkout VMs remained deallocated after maintenance.",
      "결제 처리 VM 3대 중 1대가 유지보수 후 할당 해제 상태로 남았습니다.",
    ),
    actionId: null,
    attempt: null,
    executionPath: null,
    outcome: "incident_opened",
    targetResourceRef: "sample-checkout-standby-vm-01",
    recordedAt: "2026-09-01T08:45:00Z",
  }),
  sampleAuditItem({
    seq: 1006,
    correlationId: COMPLETED_CORRELATION,
    eventId: "sample-event-001",
    actor: "Saga",
    actionKind: "incident.resolved",
    stage: "audit",
    decision: null,
    reason: sampleText(
      "The independently observed VM state satisfied the recovery objective.",
      "독립적으로 관찰한 VM 상태가 복구 목표를 충족했습니다.",
    ),
    actionId: "sample-completed-action-1",
    attempt: 1,
    executionPath: "provider_api",
    outcome: "effect_verified",
    targetResourceRef: "sample-checkout-vm-01",
    recordedAt: "2026-09-01T08:51:00Z",
  }),
  sampleAuditItem({
    seq: 1005,
    correlationId: COMPLETED_CORRELATION,
    eventId: "sample-event-001",
    actor: "Heimdall",
    actionKind: "effect_observation.verified",
    stage: "verify",
    decision: null,
    reason: sampleText(
      "An independent observation confirmed that the VM is running.",
      "독립 관찰에서 VM이 실행 중임을 확인했습니다.",
    ),
    actionId: "sample-completed-action-1",
    attempt: 1,
    executionPath: "provider_api",
    outcome: "effect_verified",
    targetResourceRef: "sample-checkout-vm-01",
    recordedAt: "2026-09-01T08:50:00Z",
  }),
  sampleAuditItem({
    seq: 1004,
    correlationId: COMPLETED_CORRELATION,
    eventId: "sample-event-001",
    actor: "Thor",
    actionKind: "action.dispatch",
    stage: "execute",
    decision: null,
    reason: sampleText(
      "The provider accepted the approved VM start request.",
      "공급자가 승인된 VM 시작 요청을 접수했습니다.",
    ),
    actionId: "sample-completed-action-1",
    attempt: 1,
    executionPath: "provider_api",
    outcome: "accepted",
    targetResourceRef: "sample-checkout-vm-01",
    recordedAt: "2026-09-01T08:49:00Z",
  }),
  sampleAuditItem({
    seq: 1003,
    correlationId: COMPLETED_CORRELATION,
    eventId: "sample-event-001",
    actor: "Var",
    actionKind: "hil.approved",
    stage: "approval",
    decision: "approved",
    reason: sampleText(
      "A distinct human approved the exact VM start action.",
      "별도 사람이 정확한 VM 시작 작업을 승인했습니다.",
    ),
    actionId: "sample-completed-action-1",
    attempt: 1,
    executionPath: "human_approval",
    outcome: "approved",
    targetResourceRef: "sample-checkout-vm-01",
    recordedAt: "2026-09-01T08:48:00Z",
  }),
  sampleAuditItem({
    seq: 1002,
    correlationId: COMPLETED_CORRELATION,
    eventId: "sample-event-001",
    actor: "Forseti",
    actionKind: "risk_gate.evaluate",
    stage: "gate",
    decision: "hil",
    reason: sampleText(
      "Starting the checkout VM requires independent human approval.",
      "결제 처리 VM을 시작하려면 독립적인 사람 승인이 필요합니다.",
    ),
    actionId: "sample-completed-action-1",
    attempt: 1,
    executionPath: "human_approval",
    outcome: "approval_required",
    targetResourceRef: "sample-checkout-vm-01",
    recordedAt: "2026-09-01T08:47:00Z",
  }),
  sampleAuditItem({
    seq: 1001,
    correlationId: COMPLETED_CORRELATION,
    eventId: "sample-event-001",
    actor: "Huginn",
    actionKind: "incident.open",
    stage: "ingest",
    decision: null,
    reason: sampleText(
      "Checkout capacity fell below the required three running VMs.",
      "실행 중인 결제 처리 VM이 필요한 3대보다 적어졌습니다.",
    ),
    actionId: null,
    attempt: null,
    executionPath: null,
    outcome: "incident_opened",
    targetResourceRef: "sample-checkout-vm-01",
    recordedAt: "2026-09-01T08:45:00Z",
  }),
] as const;

export function sampleEvidenceResponse(
  path: string,
  params: URLSearchParams,
): unknown | undefined {
  if (path === "/incidents") return sampleIncidentPage(params);
  if (path === "/audit") return sampleAuditPage(params);
  if (path.startsWith("/audit/") && path.endsWith("/trace")) {
    return sampleTrace(path.slice("/audit/".length, -"/trace".length));
  }
  if (path === "/rca") return sampleRca(params.get("correlation") ?? "");
  return undefined;
}

function sampleIncidentPage(params: URLSearchParams) {
  const status = params.get("status");
  const correlation = params.get("correlation_id");
  const query = params.get("q")?.trim().toLowerCase() ?? "";
  const vertical = params.get("vertical");
  const severity = params.get("severity");
  const matching = SAMPLE_INCIDENTS.filter((item) => (
    (status === null
      || status === "all"
      || (status === "active" && item.status !== "resolved")
      || (status === "resolved" && item.status === "resolved"))
    && (correlation === null || item.correlation_id === correlation)
    && (vertical === null || item.vertical === vertical)
    && (severity === null || item.severity === severity)
    && (
      query === ""
      || [
        item.title,
        item.correlation_id,
        item.incident_number,
        item.target_ref,
      ].some((value) => value?.toLowerCase().includes(query))
    )
  ));
  const items = matching.slice(0, sampleLimit(params.get("limit"), matching.length));
  return {
    items,
    next_cursor: null,
    metrics: sampleIncidentMetrics(matching),
  };
}

function sampleIncidentMetrics(items: readonly IncidentSummary[]) {
  const cohorts: Record<IncidentOutcomeCohort, number> = {
    agent_mitigated: 0,
    agent_assisted: 0,
    human_mitigated: 0,
    pending: 0,
    integrity_excluded: 0,
  };
  const drilldown: Record<IncidentOutcomeCohort, string[]> = {
    agent_mitigated: [],
    agent_assisted: [],
    human_mitigated: [],
    pending: [],
    integrity_excluded: [],
  };
  for (const item of items) {
    const cohort: IncidentOutcomeCohort = item.status === "resolved"
      ? "agent_assisted"
      : "pending";
    cohorts[cohort] += 1;
    drilldown[cohort].push(item.correlation_id);
  }
  const resolvedCount = cohorts.agent_assisted;
  const times = items.flatMap((item) => [item.opened_at, item.last_updated_at]).sort();
  return {
    source: "synthetic-preview",
    snapshot_seq: 2,
    denominator: items.length,
    matched_total: items.length,
    truncated: false,
    window_from: times[0] ?? null,
    window_to: times.at(-1) ?? null,
    cohorts,
    drilldown,
    drilldown_truncated: {
      agent_mitigated: false,
      agent_assisted: false,
      human_mitigated: false,
      pending: false,
      integrity_excluded: false,
    },
    median_time_to_mitigate_seconds: resolvedCount > 0 ? 360 : null,
    time_to_mitigate_sample_size: resolvedCount,
    terminal_rule: "resolved_and_independently_verified",
  };
}

function sampleAuditPage(params: URLSearchParams) {
  const correlation = params.get("correlation_id");
  const mode = params.get("mode");
  const action = params.get("action");
  const outcome = params.get("outcome");
  const tier = params.get("tier");
  const vertical = params.get("vertical");
  const fromSeq = sampleSequence(params.get("from_seq"));
  const throughSeq = sampleSequence(params.get("through_seq"));
  const matching = SAMPLE_AUDIT_ITEMS.filter((item) => (
    (correlation === null || item.correlation_id === correlation)
    && (mode === null || item.mode === mode)
    && (action === null || item.action_kind === action)
    && (outcome === null || item.entry["outcome"] === outcome)
    && (tier === null || item.entry["tier"] === tier)
    && (vertical === null || item.entry["vertical"] === vertical)
    && (fromSeq === null || item.seq >= fromSeq)
    && (throughSeq === null || item.seq <= throughSeq)
  ));
  return {
    items: matching.slice(0, sampleLimit(params.get("limit"), matching.length)),
    next_cursor: null,
  };
}

function sampleTrace(encodedCorrelation: string): unknown | undefined {
  let correlation: string;
  try {
    correlation = decodeURIComponent(encodedCorrelation);
  } catch {
    return undefined;
  }
  const incident = SAMPLE_INCIDENTS.find((item) => item.correlation_id === correlation);
  const records = SAMPLE_AUDIT_ITEMS
    .filter((item) => item.correlation_id === correlation)
    .slice()
    .reverse();
  if (incident === undefined || records.length === 0) return undefined;
  const steps = records.map((item) => ({
    seq: item.seq,
    event_id: item.event_id,
    source_correlation_id: null,
    recorded_at: item.recorded_at,
    actor: item.actor,
    stage: nullableText(item.entry, "stage"),
    decision: nullableText(item.entry, "decision"),
    reason: nullableText(item.entry, "reason"),
    action_kind: item.action_kind,
    mode: item.mode,
    action_id: nullableText(item.entry, "action_id"),
    attempt: nullablePositiveInteger(item.entry, "attempt"),
    execution_path: nullableText(item.entry, "execution_path"),
    outcome: nullableText(item.entry, "outcome"),
    entry_hash: item.entry_hash,
    previous_hash: item.previous_hash,
  }));
  const latest = steps.at(-1)!;
  const actionAttempts = new Set(
    steps.flatMap((step) =>
      step.action_id === null ? [] : [`${step.action_id}:${step.attempt ?? "unknown"}`]
    ),
  );
  return {
    correlation_id: correlation,
    step_count: steps.length,
    steps,
    terminal_stage: latest.stage,
    trace_kind: "decision",
    source_authority: "operator-audit-log",
    complete: true,
    first_recorded_at: steps[0]!.recorded_at,
    last_recorded_at: latest.recorded_at,
    latest_sequence: latest.seq,
    latest_activity_stage: latest.stage,
    latest_action_kind: latest.action_kind,
    latest_actor: latest.actor,
    latest_decision: latestRecordedDecision(steps),
    latest_outcome: latest.outcome,
    latest_mode: latest.mode,
    target_resource_ref: incident.target_ref,
    target_count: incident.target_ref === null ? 0 : 1,
    action_attempt_count: actionAttempts.size,
    effect_observation_count: steps.filter((step) =>
      step.action_kind.startsWith("effect_observation.")
    ).length,
    incident_evidence_recorded: true,
    rca_evidence_recorded: false,
  };
}

function sampleRca(correlation: string): RcaView | undefined {
  const incident = SAMPLE_INCIDENTS.find((item) => item.correlation_id === correlation);
  if (incident === undefined) return undefined;
  return {
    correlation_id: correlation,
    incident_id: incident.incident_id,
    hypotheses: [],
    response: null,
  };
}

function sampleLimit(value: string | null, fallback: number): number {
  if (value === null || !/^[1-9][0-9]*$/.test(value)) return fallback;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) ? parsed : fallback;
}

function sampleSequence(value: string | null): number | null {
  if (value === null || !/^[1-9][0-9]*$/.test(value)) return null;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) ? parsed : null;
}

function nullableText(value: Record<string, unknown>, key: string): string | null {
  return typeof value[key] === "string" && value[key].length > 0
    ? value[key]
    : null;
}

function nullablePositiveInteger(
  value: Record<string, unknown>,
  key: string,
): number | null {
  const candidate = value[key];
  return typeof candidate === "number"
    && Number.isSafeInteger(candidate)
    && candidate > 0
    ? candidate
    : null;
}

function latestRecordedDecision(
  steps: readonly { readonly decision: string | null }[],
): string | null {
  for (let index = steps.length - 1; index >= 0; index -= 1) {
    const decision = steps[index]?.decision;
    if (decision !== null && decision !== undefined) return decision;
  }
  return null;
}
