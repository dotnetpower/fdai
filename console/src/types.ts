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
}

export interface ApiError {
  readonly error: {
    readonly status: number;
    readonly message: string;
  };
}
