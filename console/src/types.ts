/**
 * Payload shapes returned by the read API. Mirrored from
 * `src/fdai/delivery/read_api/read_model.py`. Keep in sync by hand
 * - the surface is intentionally small (three routes).
 */

export interface AuditItem {
  readonly seq: number;
  readonly event_id: string;
  readonly correlation_id: string | null;
  readonly actor: string;
  readonly action_kind: string;
  readonly mode: "shadow" | "enforce";
  readonly entry: Record<string, unknown>;
  readonly entry_hash: string;
  readonly previous_hash: string;
  readonly recorded_at: string;
}

export interface AuditPage {
  readonly items: readonly AuditItem[];
  readonly next_cursor: string | null;
}

export type IncidentStatus = "open" | "in_progress" | "resolved";
export type IncidentStatusFilter = "active" | "resolved" | "all";

export interface IncidentSummary {
  readonly correlation_id: string;
  readonly incident_id: string | null;
  readonly ticket_id: string | null;
  readonly title: string;
  readonly severity: string;
  readonly status: IncidentStatus;
  readonly status_source: "incident_lifecycle" | "audit_projection";
  readonly disposition: string;
  readonly verdict: string;
  readonly vertical: string;
  readonly opened_at: string;
  readonly last_updated_at: string;
  readonly latest_mode: "shadow" | "enforce";
  readonly history_count: number;
  readonly involved_agents: readonly string[];
}

export interface IncidentPage {
  readonly items: readonly IncidentSummary[];
  readonly next_cursor: string | null;
}

export type RcaTier = "t0" | "t1" | "t2" | "unknown";
export type RcaOutcome = "grounded" | "abstained" | "unknown";

export interface RcaCitation {
  readonly kind: string;
  readonly ref: string;
}

export interface RcaCausalHop {
  readonly cause_event_id: string;
  readonly effect_event_id: string;
  readonly cause_resource_ref: string;
  readonly effect_resource_ref: string;
  readonly lead_seconds: number;
  readonly relationship: string;
  readonly confidence: number;
}

export interface RcaCausalChain {
  readonly root_event_id: string;
  readonly failure_event_id: string;
  readonly confidence: number;
  readonly ambiguity: number;
  readonly hops: readonly RcaCausalHop[];
}

export interface RcaHypothesis {
  readonly seq: number;
  readonly tier: RcaTier;
  readonly outcome: RcaOutcome;
  readonly grounded: boolean;
  readonly cause: string | null;
  readonly confidence: number | null;
  readonly reason: string | null;
  readonly citations: readonly RcaCitation[];
  readonly remediation_ref: string | null;
  readonly causal_chain: RcaCausalChain | null;
  readonly mode: "shadow" | "enforce";
  readonly recorded_at: string;
}

export interface RcaResponsePlan {
  readonly verdict: string;
  readonly decision: string | null;
  readonly action_kind: string | null;
  readonly mode: "shadow" | "enforce" | null;
  readonly rollback_reference: string | null;
  readonly recorded_at: string | null;
}

export interface RcaView {
  readonly correlation_id: string;
  readonly incident_id: string | null;
  readonly hypotheses: readonly RcaHypothesis[];
  readonly response: RcaResponsePlan | null;
}

export type ScopeAxisName = "monitoring" | "action";
export type ScopeEntryState = "included" | "excluded";
export type ScopeEntryLevel = "subscription" | "resource_group";

export interface ScopeEntry {
  readonly address: string;
  readonly level: ScopeEntryLevel;
  readonly subscription: string;
  readonly resource_group: string | null;
  readonly state: ScopeEntryState;
}

export interface ScopeAxis {
  readonly axis: ScopeAxisName;
  readonly entries: readonly ScopeEntry[];
}

export interface ExecutorBoundary {
  readonly resource_groups: readonly string[];
  readonly note: string | null;
}

export interface EffectiveScope {
  readonly monitoring: ScopeAxis;
  readonly action: ScopeAxis;
  readonly executor_boundary: ExecutorBoundary;
}

export interface AuditSample {
  readonly from_seq: number | null;
  readonly through_seq: number | null;
  readonly row_count: number;
  readonly limit: number;
}

export interface DashboardKpi {
  readonly event_count: number;
  readonly shadow_share: number;
  readonly enforce_share: number;
  readonly hil_pending: number;
  readonly by_action_kind: Record<string, number>;
  readonly by_outcome: Record<string, number>;
  readonly by_tier: Record<string, number>;
  readonly last_recorded_at: string | null;
  readonly audit_sample: AuditSample | null;
}

/**
 * Cost-vertical summary served by the FinOps read panel
 * (`GET /finops`, `ExampleFinOpsPanel` in `read_api/panels.py`). It is a
 * fork/opt-in panel: production or a fork that has not registered it
 * returns 404, so the Overview treats a missing payload as "cost axis
 * unavailable" rather than an error.
 */
export interface FinOpsPayload {
  readonly vertical: string;
  readonly total_actions: number;
  readonly by_kind: Record<string, number>;
  readonly estimated_monthly_savings: number;
  readonly sampled_events: number;
}

/** One success metric measured against the reference-agent baseline.
 * Null values mean the source has not observed the measurement.
 * `direction` says which way is better, so the console can render the
 * improvement factor correctly (higher-is-better vs lower-is-better). */
export interface MetricVsBaseline {
  readonly value: number | null;
  readonly baseline: number | null;
  readonly direction: "higher" | "lower";
}

/** One guard metric with its veto threshold (goals-and-metrics guards). */
export interface GuardMetric {
  readonly key: string;
  readonly value: number;
  readonly baseline: number;
  readonly threshold: number;
  readonly ok: boolean;
}

/** Per-vertical activity split (Resilience / Change Safety / Cost). */
export interface VerticalSummary {
  readonly key: string;
  readonly events: number;
  readonly auto_resolved: number;
  readonly open_risks: number;
  readonly monthly_savings: number;
}

/**
 * Autonomy measurement summary (`GET /kpi/autonomy`,
 * `AutonomyMeasurementPanel`). The goals-and-metrics surface: success
 * metrics vs baseline, guard metrics, per-vertical split, tier mix vs
 * band, and an auto-resolution trend. `synthetic` is true in the dev
 * harness (no real measurement pipeline); opt-in like finops (404 => the
 * Overview falls back to the audit-only summary).
 */
export interface AutonomyPayload {
  readonly synthetic: boolean;
  readonly window_days: number;
  readonly sample_size: number;
  readonly confidence: number | null;
  readonly source: {
    readonly name: string;
    readonly kind: "audit" | "measurement" | "synthetic";
    readonly as_of: string | null;
  };
  readonly rules: {
    readonly active: number;
    readonly candidates_30d: number;
    readonly promoted_30d: number;
  };
  readonly success: {
    readonly auto_resolution_rate: MetricVsBaseline;
    readonly human_touchpoints_per_100: MetricVsBaseline;
    readonly mttr_seconds: MetricVsBaseline;
    readonly change_lead_time_seconds: MetricVsBaseline;
    readonly cost_per_resolved_event_usd: MetricVsBaseline;
  };
  readonly leading: {
    readonly mixed_model_disagreement_rate: MetricVsBaseline;
    readonly verifier_failure_rate: MetricVsBaseline;
    readonly shadow_divergence_rate: MetricVsBaseline;
  };
  readonly guards: readonly GuardMetric[];
  readonly verticals: readonly VerticalSummary[];
  readonly tier: {
    readonly mix: Record<string, number>;
    readonly bands: Record<string, readonly [number, number]>;
  };
  readonly trend: Record<string, readonly number[]>;
}

export interface HilQueueItem {
  readonly idempotency_key: string;
  readonly event_id: string;
  readonly action_kind: string;
  readonly reason: string;
  readonly requested_at: string;
  readonly correlation_id: string | null;
  readonly approval_id: string;
  readonly action_id: string;
  readonly target_resource_ref: string;
  readonly mode: string;
  readonly stop_condition: string;
  readonly rollback_kind: string;
  readonly rollback_reference: string | null;
  readonly blast_radius_scope: string;
  readonly blast_radius_count: number | null;
  readonly blast_radius_rate_per_minute: number | null;
  readonly blast_radius_summary: string;
  readonly reasons: readonly string[];
  readonly citing_rule_ids: readonly string[];
  readonly ttl_expires_at: string | null;
}

export interface HilQueuePage {
  readonly items: readonly HilQueueItem[];
  readonly total: number;
  readonly detail_level: "full" | "count_only";
}

export interface ApiError {
  readonly error: {
    readonly status: number;
    readonly message: string;
  };
}
