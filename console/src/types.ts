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

export interface DashboardKpi {
  readonly event_count: number;
  readonly shadow_share: number;
  readonly enforce_share: number;
  readonly hil_pending: number;
  readonly by_action_kind: Record<string, number>;
  readonly by_outcome: Record<string, number>;
  readonly by_tier: Record<string, number>;
  readonly last_recorded_at: string | null;
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
 * `direction` says which way is better, so the console can render the
 * improvement factor correctly (higher-is-better vs lower-is-better). */
export interface MetricVsBaseline {
  readonly value: number;
  readonly baseline: number;
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
}

export interface HilQueuePage {
  readonly items: readonly HilQueueItem[];
  readonly total: number;
}

export interface ApiError {
  readonly error: {
    readonly status: number;
    readonly message: string;
  };
}
