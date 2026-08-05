/**
 * Live cockpit model - state shape, reducer, and pure helpers.
 *
 * SRP: data + state transitions only. No React, no I/O, no DOM. Given
 * an incoming SSE stage event, the reducer folds it into a new
 * {@link LiveState}; that state is what the presentational components in
 * `live.tiles.tsx` render.
 *
 * Extracted from `live.tsx` so the reducer stays testable in isolation
 * and the main component keeps only the SSE wiring / layout.
 */

import type {
  LiveConnectionStatus,
  LiveStageEvent,
  LiveStageName,
  LiveStagePhase,
} from "../hooks/use-live-stream";

// ---------------------------------------------------------------------------
// Constants (shared with the presentational layer)
// ---------------------------------------------------------------------------

export const POOL_SIZE = 12;
export const TICKER_CAP = 8;
export const RATE_WINDOW_MS = 60_000;
export const RATE_BUCKETS = 60; // one bar per second, 60s history
export const AGE_DONE_MS = 3_000;
export const AGE_STALE_MS = 8_000;
export const HIL_RETENTION_MS = 30_000;

export const STAGE_ORDER: readonly LiveStageName[] = [
  "ingest",
  "route",
  "verify",
  "gate",
  "execute",
  "audit",
];

/** Human label per pipeline stage, for the agent-relay tooltip. */
export const STAGE_LABEL: Record<LiveStageName, string> = {
  ingest: "Ingest",
  route: "Route",
  verify: "Verify",
  gate: "Gate",
  execute: "Execute",
  audit: "Audit",
};

/** Pantheon agent -> role, shown in the relay tooltip so an operator can
 * read who owns each step without leaving the tile. */
export const AGENT_ROLE: Record<string, string> = {
  Huginn: "Event Collector",
  Heimdall: "Observer",
  Forseti: "Judge",
  Thor: "Responder",
  Var: "Approver",
  Vidar: "Recovery",
  Saga: "Auditor",
  Odin: "Master Planner",
  Bragi: "Narrator",
};

export const STATUS_LABEL: Record<LiveConnectionStatus, string> = {
  idle: "idle",
  connecting: "connecting",
  open: "live",
  closed: "closed",
  unsupported: "SSE unsupported",
};

export type FilterKind = "all" | "hil" | "deny" | "failed" | "stuck";

// ---------------------------------------------------------------------------
// Rate buckets (per-tier events/sec history)
// ---------------------------------------------------------------------------

/**
 * Per-tier events/sec history: three parallel arrays of {@link RATE_BUCKETS}
 * one-second buckets (oldest first). The trust router routes every event to
 * exactly one tier, so the sparkline plots T0 / T1 / T2 as separate series
 * rather than one opaque total.
 */
export interface RateBuckets {
  readonly t0: readonly number[];
  readonly t1: readonly number[];
  readonly t2: readonly number[];
}

export const RATE_TIER_KEYS = ["t0", "t1", "t2"] as const;
export type RateTierKey = (typeof RATE_TIER_KEYS)[number];

export function emptyRateBuckets(): RateBuckets {
  const zeros = () => new Array(RATE_BUCKETS).fill(0) as readonly number[];
  return { t0: zeros(), t1: zeros(), t2: zeros() };
}

/** Shift a bucket array left by `rolls` seconds, padding zeros on the right. */
export function rollBucketArray(arr: readonly number[], rolls: number): readonly number[] {
  if (rolls <= 0) return arr;
  if (rolls >= arr.length) return new Array(arr.length).fill(0) as readonly number[];
  return [...arr.slice(rolls), ...new Array(rolls).fill(0)] as readonly number[];
}

export function rollRateBuckets(b: RateBuckets, rolls: number): RateBuckets {
  if (rolls <= 0) return b;
  return {
    t0: rollBucketArray(b.t0, rolls),
    t1: rollBucketArray(b.t1, rolls),
    t2: rollBucketArray(b.t2, rolls),
  };
}

export function bumpLastBucket(buckets: readonly number[]): readonly number[] {
  const out = buckets.slice();
  const idx = out.length - 1;
  out[idx] = (out[idx] ?? 0) + 1;
  return out;
}

/** Add `delta` to the last (current-second) bucket - used for latency sums. */
export function bumpLastBucketBy(buckets: readonly number[], delta: number): readonly number[] {
  const out = buckets.slice();
  const idx = out.length - 1;
  out[idx] = (out[idx] ?? 0) + delta;
  return out;
}

/** Total events in the 60s window for one tier (drives the sparkline legend). */
export function sumBuckets(buckets: readonly number[]): number {
  let total = 0;
  for (const v of buckets) total += v;
  return total;
}

// ---------------------------------------------------------------------------
// Tile + reducer state
// ---------------------------------------------------------------------------

export interface TileState {
  readonly event_id: string;
  readonly correlation_id: string;
  readonly vertical: string | undefined;
  readonly tier: string | undefined;
  readonly mode: string | undefined;
  readonly autonomy: string | undefined;
  readonly latency_budget_ms: number | undefined;
  readonly resource_type: string | undefined;
  readonly scope: string | undefined;
  readonly target: string | undefined;
  readonly reason: string | undefined;
  readonly risk: string | undefined;
  readonly impact: string | undefined;
  readonly rule: string | undefined;
  readonly action_type: string | undefined;
  readonly action_types: ReadonlySet<string>;
  readonly gate_decision: string | undefined;
  readonly outcome: string | undefined;
  readonly stages_completed: ReadonlySet<LiveStageName>;
  readonly stage_agents: ReadonlyMap<LiveStageName, string>;
  readonly last_agent: string | undefined;
  readonly last_stage: LiveStageName;
  readonly last_phase: LiveStagePhase;
  readonly first_seen_at: number;
  /** Server timestamp of the first stage frame seen, for latency. */
  readonly first_ts: string | undefined;
  readonly last_seen_at: number;
  readonly completed: boolean;
  readonly failed: boolean;
}

export type LiveSelectionState = "none" | "waiting" | "selected" | "unavailable";

export function liveSelectionState(
  selectedEventId: string | null,
  selectedTile: TileState | null,
  sessionTotal: number,
): LiveSelectionState {
  if (selectedEventId === null) return "none";
  if (selectedTile !== null) return "selected";
  return sessionTotal === 0 ? "waiting" : "unavailable";
}

export interface LiveState {
  /** Fixed-size pool. ``null`` means "empty slot"; populated tiles keep
   *  their index for the whole lifetime of an event so the FE never
   *  reflows. */
  readonly tiles: readonly (TileState | null)[];
  /** Map event_id -> slot index. */
  readonly eventIdToSlot: ReadonlyMap<string, number>;
  readonly ticker: readonly LiveStageEvent[];
  readonly ratePings: readonly number[];
  readonly tierCounts: Readonly<Record<string, number>>;
  readonly gateCounts: Readonly<Record<string, number>>;
  /** 60 one-second buckets per tier, oldest first. */
  readonly rateBuckets: RateBuckets;
  readonly rateBucketAt: number;
  /** Per-second pipeline latency (ms): total and count, for a hover average. */
  readonly latSum: readonly number[];
  readonly latCount: readonly number[];
  readonly selectedEventId: string | null;
  readonly filter: FilterKind;
  readonly now: number;
  /** Wall-clock time the console opened; the header uses it to show
   *  "watching since ..." grounding the operator in time. */
  readonly session_started_at: number;
  /** Total number of terminal (``audit.done``) events observed. */
  readonly session_total: number;
}

export function makeInitialState(): LiveState {
  const now = Date.now();
  return {
    tiles: new Array(POOL_SIZE).fill(null) as readonly (TileState | null)[],
    eventIdToSlot: new Map(),
    ticker: [],
    ratePings: [],
    tierCounts: {},
    gateCounts: {},
    rateBuckets: emptyRateBuckets(),
    rateBucketAt: now,
    latSum: new Array(RATE_BUCKETS).fill(0) as readonly number[],
    latCount: new Array(RATE_BUCKETS).fill(0) as readonly number[],
    selectedEventId: null,
    filter: "all",
    now,
    session_started_at: now,
    session_total: 0,
  };
}

export type Action =
  | { readonly kind: "event"; readonly event: LiveStageEvent }
  | { readonly kind: "batch"; readonly events: readonly LiveStageEvent[] }
  | { readonly kind: "tick"; readonly now: number }
  | { readonly kind: "select"; readonly event_id: string | null }
  | { readonly kind: "filter"; readonly value: FilterKind };

export function reducer(state: LiveState, action: Action): LiveState {
  if (action.kind === "select") {
    return { ...state, selectedEventId: action.event_id };
  }
  if (action.kind === "filter") {
    return { ...state, filter: action.value };
  }
  if (action.kind === "tick") {
    const cutoff = action.now - RATE_WINDOW_MS;
    const pings = state.ratePings.filter((t) => t >= cutoff);
    // Roll the sparkline buckets forward by one per real second passed.
    let bucketAt = state.rateBucketAt;
    let rolls = 0;
    while (action.now - bucketAt >= 1000) {
      rolls += 1;
      bucketAt += 1000;
    }
    const buckets = rolls > 0 ? rollRateBuckets(state.rateBuckets, rolls) : state.rateBuckets;
    const latSum = rolls > 0 ? rollBucketArray(state.latSum, rolls) : state.latSum;
    const latCount = rolls > 0 ? rollBucketArray(state.latCount, rolls) : state.latCount;
    return { ...state, ratePings: pings, rateBuckets: buckets, latSum, latCount, rateBucketAt: bucketAt, now: action.now };
  }

  if (action.kind === "batch") {
    // Fold N events into ONE new state so the SSE stream never
    // triggers N React renders in a row. Bounded upstream by the
    // rAF flusher (see LiveRoute).
    let s = state;
    for (const evt of action.events) s = applyEvent(s, evt);
    return s;
  }

  // action.kind === "event"
  return applyEvent(state, action.event);
}

export function applyEvent(state: LiveState, evt: LiveStageEvent): LiveState {
  const detail = evt.detail ?? {};
  const now = Date.now();

  // Locate the tile's slot: an existing slot for this event_id, or a
  // fresh slot picked by the placement policy below.
  let slotIndex = state.eventIdToSlot.get(evt.event_id) ?? -1;
  const existingSameEvent = slotIndex >= 0 ? state.tiles[slotIndex] : null;
  let displaced: TileState | null = null;

  const tier = pickString(detail, "tier") ?? pickString(detail, "routed_to");
  const rule = pickString(detail, "rule");
  const actionType = pickString(detail, "action_type");
  const scope = pickString(detail, "scope");
  const inferred = inferVertical(
    rule ?? existingSameEvent?.rule,
    actionType ?? existingSameEvent?.action_type,
  );
  const vertical = pickString(detail, "vertical") ?? (inferred === "unknown" ? undefined : inferred);
  const resourceType = pickString(detail, "resource_type");
  const gateDecision =
    pickString(detail, "gate_decision") ??
    (evt.stage === "audit" ? pickString(detail, "decision") : undefined);
  const outcome = pickString(detail, "outcome");
  const mode = pickString(detail, "mode");
  const autonomy = pickString(detail, "autonomy") ?? pickString(detail, "autonomy_class");
  const target = pickString(detail, "target") ?? pickString(detail, "resource_ref");
  const reason = pickString(detail, "reason");
  const risk = pickString(detail, "risk") ?? pickString(detail, "risk_level");
  const impact = pickString(detail, "impact") ?? pickString(detail, "impact_scope");
  const latencyBudgetMs = pickPositiveNumber(detail, "latency_budget_ms");
  const agent = pickString(detail, "producer_principal");

  if (slotIndex < 0) {
    slotIndex = pickSlot(state, now);
    if (slotIndex < 0) {
      // Pool is completely full of sticky (HIL) tiles - drop the event.
      // Extremely rare with POOL_SIZE=96; log and move on. Still record it in
      // the audit stream if it is a terminal audit entry.
      const isAuditEntry =
        evt.stage === "audit" && (evt.phase === "done" || evt.phase === "failed");
      return {
        ...state,
        ticker: isAuditEntry ? [evt, ...state.ticker].slice(0, TICKER_CAP) : state.ticker,
      };
    }
    // Whichever tile currently occupies the picked slot (if any) is
    // about to be overwritten by this new event; its event_id MUST be
    // dropped from the id -> slot map or the map grows unbounded and
    // pins the browser heap.
    displaced = state.tiles[slotIndex] ?? null;
  }
  const previous = existingSameEvent;

  const stages_completed = new Set(previous?.stages_completed ?? []);
  if (evt.phase === "done" || evt.phase === "failed") {
    stages_completed.add(evt.stage);
  }

  const stage_agents = new Map(previous?.stage_agents ?? []);
  if (agent && (evt.phase === "done" || evt.phase === "failed")) {
    stage_agents.set(evt.stage, agent);
  }

  const action_types = new Set(previous?.action_types ?? []);
  if (actionType) action_types.add(actionType);

  const next: TileState = {
    event_id: evt.event_id,
    correlation_id: evt.correlation_id,
    vertical: vertical ?? previous?.vertical,
    tier: tier ?? previous?.tier,
    mode: mode ?? previous?.mode,
    autonomy: autonomy ?? previous?.autonomy,
    latency_budget_ms: latencyBudgetMs ?? previous?.latency_budget_ms,
    resource_type: resourceType ?? previous?.resource_type,
    scope: scope ?? previous?.scope,
    target: target ?? previous?.target,
    reason: reason ?? previous?.reason,
    risk: risk ?? previous?.risk,
    impact: impact ?? previous?.impact,
    rule: rule ?? previous?.rule,
    action_type: actionType ?? previous?.action_type,
    action_types,
    gate_decision: gateDecision ?? previous?.gate_decision,
    outcome: outcome ?? previous?.outcome,
    stages_completed,
    stage_agents,
    last_agent: agent ?? previous?.last_agent,
    last_stage: evt.stage,
    last_phase: evt.phase,
    first_seen_at: previous?.first_seen_at ?? now,
    first_ts: previous?.first_ts ?? evt.ts,
    last_seen_at: now,
    completed: evt.stage === "audit" && evt.phase === "done" ? true : previous?.completed ?? false,
    failed: evt.phase === "failed" || previous?.failed === true,
  };

  const tiles = state.tiles.slice();
  tiles[slotIndex] = next;
  const eventIdToSlot = new Map(state.eventIdToSlot);
  if (!previous) eventIdToSlot.set(evt.event_id, slotIndex);
  // If the previous slot occupant is being displaced (either an
  // in-flight update for the same event_id landing in the same slot -
  // rare - or a brand new event overwriting a stale slot occupant),
  // its event_id is no longer mapped to any slot.
  if (previous && previous.event_id !== evt.event_id) {
    eventIdToSlot.delete(previous.event_id);
  }
  if (displaced && displaced.event_id !== evt.event_id) {
    eventIdToSlot.delete(displaced.event_id);
  }

  // The audit stream is append-only audit entries: show one row per completed
  // event (its terminal audit frame), not every ingest/route/gate/audit stage
  // frame - otherwise ~4 frames x the event rate churn the list unreadably.
  const isAuditEntry = evt.stage === "audit" && (evt.phase === "done" || evt.phase === "failed");
  const isNewTerminal = isAuditEntry && previous?.completed !== true;
  const ticker = isNewTerminal ? [evt, ...state.ticker].slice(0, TICKER_CAP) : state.ticker;

  // KPI accumulators fire only on the terminal audit.done frame so one
  // event contributes exactly once - matching audit-log semantics.
  const shouldCount = evt.stage === "audit" && evt.phase === "done" && previous?.completed !== true;
  const ratePings = shouldCount ? [...state.ratePings, now] : state.ratePings;
  const bumpTier =
    shouldCount && (RATE_TIER_KEYS as readonly string[]).includes(next.tier ?? "")
      ? (next.tier as RateTierKey)
      : null;
  const rateBuckets = bumpTier
    ? { ...state.rateBuckets, [bumpTier]: bumpLastBucket(state.rateBuckets[bumpTier]) }
    : state.rateBuckets;
  // Pipeline latency for the completed event: from when the console first saw
  // it (ingest) to this terminal audit.done frame - the same span the tile age
  // uses. Fold into the current-second bucket so the sparkline hover can show
  // the average ms for that second.
  // Pipeline latency for the completed event. Prefer a backend-reported
  // latency_ms; else the server ts span (first stage frame -> this terminal
  // frame); else the client-observed span. Fold into the current-second
  // bucket so the sparkline hover can show the average ms for that second.
  let latencyMs = 0;
  if (shouldCount) {
    const reported = typeof detail.latency_ms === "number" ? detail.latency_ms : null;
    const firstMs = next.first_ts ? Date.parse(next.first_ts) : NaN;
    const lastMs = Date.parse(evt.ts);
    const tsSpan =
      Number.isFinite(firstMs) && Number.isFinite(lastMs) && lastMs >= firstMs
        ? lastMs - firstMs
        : null;
    latencyMs = reported ?? tsSpan ?? Math.max(0, now - next.first_seen_at);
  }
  const latSum = shouldCount ? bumpLastBucketBy(state.latSum, latencyMs) : state.latSum;
  const latCount = shouldCount ? bumpLastBucket(state.latCount) : state.latCount;
  const tierCounts =
    shouldCount && next.tier
      ? { ...state.tierCounts, [next.tier]: (state.tierCounts[next.tier] ?? 0) + 1 }
      : state.tierCounts;
  const gateCounts =
    shouldCount && next.gate_decision
      ? {
          ...state.gateCounts,
          [next.gate_decision]: (state.gateCounts[next.gate_decision] ?? 0) + 1,
        }
      : state.gateCounts;

  return {
    ...state,
    tiles,
    eventIdToSlot,
    ticker,
    ratePings,
    rateBuckets,
    latSum,
    latCount,
    tierCounts,
    gateCounts,
    session_total: shouldCount ? state.session_total + 1 : state.session_total,
  };
}

// ---------------------------------------------------------------------------
// Field parsing + slot placement
// ---------------------------------------------------------------------------

export function pickString(detail: Record<string, unknown>, key: string): string | undefined {
  const v = detail[key];
  return typeof v === "string" ? v : undefined;
}

export function pickPositiveNumber(
  detail: Record<string, unknown>,
  key: string,
): number | undefined {
  const value = detail[key];
  return typeof value === "number" && Number.isFinite(value) && value > 0
    ? value
    : undefined;
}

export function isTileStuck(tile: TileState, now: number): boolean {
  return (
    tile.latency_budget_ms !== undefined &&
    !tile.completed &&
    !tile.failed &&
    tile.gate_decision !== "hil" &&
    now - tile.first_seen_at > tile.latency_budget_ms
  );
}

/**
 * Infer the vertical from the rule id / action_type when the server
 * did not tag it explicitly. Prefix-based, aligned with the shipped
 * rule catalog's category taxonomy (cost / reliability / security /
 * config_drift), collapsed onto the four verticals the FE colors.
 */
export function inferVertical(rule: string | undefined, actionType: string | undefined): string {
  const src = (rule ?? actionType ?? "").toLowerCase();
  if (!src) return "unknown";
  if (src.startsWith("cost.") || src.includes("right-size") || src.includes("orphan")) return "cost";
  if (
    src.startsWith("reliability.") ||
    src.startsWith("database.") ||
    src.startsWith("disk.snapshot") ||
    src.includes("backup") ||
    src.includes("failover") ||
    src.includes("zone-red")
  ) {
    return "resilience";
  }
  return "change";
}

/**
 * Choose a slot for a new tile.
 *
 * Preference order:
 *   1. First empty slot (during warm-up the swarm fills naturally).
 *   2. Oldest completed non-HIL tile past AGE_STALE_MS (recycle).
 *   3. Any completed non-HIL tile (evict oldest).
 *   4. Oldest completed HIL tile past HIL_RETENTION_MS.
 *   5. -1 (drop the event).
 *
 * HIL tiles are retained longer than ordinary outcomes, but not forever.
 * The Approvals route owns the complete queue; Live must not let old
 * presentation state starve new control-loop observations.
 */
export function pickSlot(state: LiveState, now: number): number {
  const empties: number[] = [];
  for (let i = 0; i < state.tiles.length; i++) {
    if (state.tiles[i] === null) empties.push(i);
  }
  if (empties.length > 0) {
    // Shuffle first-fill so tiles do NOT crawl in from top-left.
    return empties[Math.floor(Math.random() * empties.length)] ?? -1;
  }

  let oldestIdx = -1;
  let oldestTs = Infinity;
  for (let i = 0; i < state.tiles.length; i++) {
    const t = state.tiles[i];
    if (!t) continue;
    if (t.event_id === state.selectedEventId) continue;
    if (t.gate_decision === "hil") continue; // sticky
    const ageThreshold = t.completed ? AGE_DONE_MS : AGE_STALE_MS;
    if (now - t.last_seen_at < ageThreshold) continue;
    if (t.last_seen_at < oldestTs) {
      oldestTs = t.last_seen_at;
      oldestIdx = i;
    }
  }
  if (oldestIdx >= 0) return oldestIdx;

  oldestIdx = -1;
  oldestTs = Infinity;
  for (let i = 0; i < state.tiles.length; i++) {
    const tile = state.tiles[i];
    if (!tile || tile.gate_decision !== "hil" || !tile.completed) continue;
    if (now - tile.last_seen_at < HIL_RETENTION_MS) continue;
    if (tile.last_seen_at < oldestTs) {
      oldestTs = tile.last_seen_at;
      oldestIdx = i;
    }
  }
  if (oldestIdx >= 0) return oldestIdx;

  // No aged-out tile. Evict the oldest completed non-HIL anyway.
  oldestIdx = -1;
  oldestTs = Infinity;
  for (let i = 0; i < state.tiles.length; i++) {
    const t = state.tiles[i];
    if (!t || t.gate_decision === "hil") continue;
    if (t.event_id === state.selectedEventId) continue;
    if (!t.completed) continue;
    if (t.last_seen_at < oldestTs) {
      oldestTs = t.last_seen_at;
      oldestIdx = i;
    }
  }
  return oldestIdx;
}

// ---------------------------------------------------------------------------
// Filter + formatting helpers (shared with the presentational layer)
// ---------------------------------------------------------------------------

export function matchesFilter(tile: TileState, filter: FilterKind, now = Date.now()): boolean {
  if (filter === "all") return true;
  if (filter === "hil") return tile.gate_decision === "hil";
  if (filter === "deny") return tile.gate_decision === "deny";
  if (filter === "failed") return tile.failed;
  if (filter === "stuck") return isTileStuck(tile, now);
  return true;
}

export function shortTime(iso: string): string {
  const match = iso.match(/T(\d\d:\d\d:\d\d\.\d{3})/);
  return match?.[1] ?? iso;
}

export function formatAge(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  const secs = Math.floor(ms / 1000);
  if (secs < 60) return `${secs}s`;
  const mins = Math.floor(secs / 60);
  return `${mins}m`;
}

export function formatDuration(ms: number): string {
  const secs = Math.floor(ms / 1000);
  if (secs < 60) return `${secs}s`;
  const mins = Math.floor(secs / 60);
  const remSecs = secs % 60;
  if (mins < 60) return remSecs > 0 ? `${mins}m ${remSecs}s` : `${mins}m`;
  const hrs = Math.floor(mins / 60);
  const remMins = mins % 60;
  return remMins > 0 ? `${hrs}h ${remMins}m` : `${hrs}h`;
}
