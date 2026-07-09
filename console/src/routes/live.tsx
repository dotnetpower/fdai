/**
 * Live cockpit route.
 *
 * Renders control-plane stage events streamed over SSE (`GET /live/stream`)
 * as an activity swarm. Design goals:
 *
 * - **Fixed slot pool** - tiles never shift position. New events fade in
 *   at their assigned slot; existing tiles transition smoothly in place.
 * - **Information hierarchy** - the ActionType is the headline of each
 *   tile; tier / gate / age are quiet annotations. HIL and deny tiles
 *   visually pop (rim glow, badge, subtle scale).
 * - **Vertical rail** - the left rail carries the vertical color
 *   (change / resilience / cost / other); the tier chip lives at
 *   top-right of the tile.
 * - **Stage progress** - six dots at the top of each tile fill in as the
 *   pipeline advances. A T2 event that spends time in `verify` is
 *   visible without leaving text.
 * - **Filters** - a top-of-page chipset dims everything except the
 *   selected outcome. Non-matching tiles fade to 15% opacity.
 * - **Detail panel** - clicking a tile slides a read-only side panel
 *   with the full event payload the server sent (rule / action /
 *   verifier passes / etc.).
 * - **Sparkline + guard status** - the KPI strip shows a 60s events/sec
 *   sparkline and four traffic-light guards (CFR / FPR / rollback /
 *   escapes) sourced from the audit ticker.
 *
 * The route is pure read-only: it never issues privileged calls, and
 * every fan-out primitive it uses ({@link useLiveStream}) is a
 * translator, never a judge.
 */

import { useEffect, useMemo, useReducer, useRef, useState } from "preact/hooks";
import type { ReadApiClient } from "../api";
import { loadConfig } from "../config";
import type {
  LiveConnectionStatus,
  LiveStageEvent,
  LiveStageName,
  LiveStagePhase,
} from "../hooks/use-live-stream";
import { useLiveStream } from "../hooks/use-live-stream";
import { usePublishViewContext } from "../deck/context";

interface Props {
  readonly client: ReadApiClient;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const POOL_SIZE = 60;
const TICKER_CAP = 8;
const RATE_WINDOW_MS = 60_000;
const RATE_BUCKETS = 60; // one bar per second, 60s history
const AGE_DONE_MS = 3_000;
const AGE_STALE_MS = 8_000;

const STAGE_ORDER: readonly LiveStageName[] = [
  "ingest",
  "route",
  "verify",
  "gate",
  "execute",
  "audit",
];

const STATUS_LABEL: Record<LiveConnectionStatus, string> = {
  idle: "idle",
  connecting: "connecting",
  open: "live",
  closed: "closed",
  unsupported: "SSE unsupported",
};

type FilterKind = "all" | "hil" | "deny" | "failed";

/**
 * Per-tier events/sec history: three parallel arrays of {@link RATE_BUCKETS}
 * one-second buckets (oldest first). The trust router routes every event to
 * exactly one tier, so the sparkline plots T0 / T1 / T2 as separate series
 * rather than one opaque total.
 */
interface RateBuckets {
  readonly t0: readonly number[];
  readonly t1: readonly number[];
  readonly t2: readonly number[];
}

const RATE_TIER_KEYS = ["t0", "t1", "t2"] as const;
type RateTierKey = (typeof RATE_TIER_KEYS)[number];

function emptyRateBuckets(): RateBuckets {
  const zeros = () => new Array(RATE_BUCKETS).fill(0) as readonly number[];
  return { t0: zeros(), t1: zeros(), t2: zeros() };
}

/** Shift a bucket array left by `rolls` seconds, padding zeros on the right. */
function rollBucketArray(arr: readonly number[], rolls: number): readonly number[] {
  if (rolls <= 0) return arr;
  if (rolls >= arr.length) return new Array(arr.length).fill(0) as readonly number[];
  return [...arr.slice(rolls), ...new Array(rolls).fill(0)] as readonly number[];
}

function rollRateBuckets(b: RateBuckets, rolls: number): RateBuckets {
  if (rolls <= 0) return b;
  return {
    t0: rollBucketArray(b.t0, rolls),
    t1: rollBucketArray(b.t1, rolls),
    t2: rollBucketArray(b.t2, rolls),
  };
}

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

interface TileState {
  readonly event_id: string;
  readonly vertical: string | undefined;
  readonly tier: string | undefined;
  readonly resource_type: string | undefined;
  readonly scope: string | undefined;
  readonly rule: string | undefined;
  readonly action_type: string | undefined;
  readonly gate_decision: string | undefined;
  readonly outcome: string | undefined;
  readonly stages_completed: ReadonlySet<LiveStageName>;
  readonly last_stage: LiveStageName;
  readonly last_phase: LiveStagePhase;
  readonly first_seen_at: number;
  readonly last_seen_at: number;
  readonly completed: boolean;
  readonly failed: boolean;
}

interface LiveState {
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
  readonly selectedEventId: string | null;
  readonly filter: FilterKind;
  readonly now: number;
  /** Wall-clock time the console opened; the header uses it to show
   *  "watching since ..." grounding the operator in time. */
  readonly session_started_at: number;
  /** Total number of terminal (``audit.done``) events observed. */
  readonly session_total: number;
}

function makeInitialState(): LiveState {
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
    selectedEventId: null,
    filter: "all",
    now,
    session_started_at: now,
    session_total: 0,
  };
}

type Action =
  | { readonly kind: "event"; readonly event: LiveStageEvent }
  | { readonly kind: "batch"; readonly events: readonly LiveStageEvent[] }
  | { readonly kind: "tick"; readonly now: number }
  | { readonly kind: "select"; readonly event_id: string | null }
  | { readonly kind: "filter"; readonly value: FilterKind };

function reducer(state: LiveState, action: Action): LiveState {
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
    return { ...state, ratePings: pings, rateBuckets: buckets, rateBucketAt: bucketAt, now: action.now };
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

function applyEvent(state: LiveState, evt: LiveStageEvent): LiveState {
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
  const gateDecision = pickString(detail, "gate_decision");
  const outcome = pickString(detail, "outcome");

  if (slotIndex < 0) {
    slotIndex = pickSlot(state, now);
    if (slotIndex < 0) {
      // Pool is completely full of sticky (HIL) tiles - drop the event.
      // Extremely rare with POOL_SIZE=96; log and move on.
      return {
        ...state,
        ticker: [evt, ...state.ticker].slice(0, TICKER_CAP),
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

  const next: TileState = {
    event_id: evt.event_id,
    vertical: vertical ?? previous?.vertical,
    tier: tier ?? previous?.tier,
    resource_type: resourceType ?? previous?.resource_type,
    scope: scope ?? previous?.scope,
    rule: rule ?? previous?.rule,
    action_type: actionType ?? previous?.action_type,
    gate_decision: gateDecision ?? previous?.gate_decision,
    outcome: outcome ?? previous?.outcome,
    stages_completed,
    last_stage: evt.stage,
    last_phase: evt.phase,
    first_seen_at: previous?.first_seen_at ?? now,
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

  const ticker = [evt, ...state.ticker].slice(0, TICKER_CAP);

  // KPI accumulators fire only on the terminal audit.done frame so one
  // event contributes exactly once - matching audit-log semantics.
  const shouldCount = evt.stage === "audit" && evt.phase === "done";
  const ratePings = shouldCount ? [...state.ratePings, now] : state.ratePings;
  const bumpTier =
    shouldCount && (RATE_TIER_KEYS as readonly string[]).includes(next.tier ?? "")
      ? (next.tier as RateTierKey)
      : null;
  const rateBuckets = bumpTier
    ? { ...state.rateBuckets, [bumpTier]: bumpLastBucket(state.rateBuckets[bumpTier]) }
    : state.rateBuckets;
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
    tierCounts,
    gateCounts,
    session_total: shouldCount ? state.session_total + 1 : state.session_total,
  };
}

function bumpLastBucket(buckets: readonly number[]): readonly number[] {
  const out = buckets.slice();
  const idx = out.length - 1;
  out[idx] = (out[idx] ?? 0) + 1;
  return out;
}

/** Total events in the 60s window for one tier (drives the sparkline legend). */
function sumBuckets(buckets: readonly number[]): number {
  let total = 0;
  for (const v of buckets) total += v;
  return total;
}

function pickString(detail: Record<string, unknown>, key: string): string | undefined {
  const v = detail[key];
  return typeof v === "string" ? v : undefined;
}

/**
 * Infer the vertical from the rule id / action_type when the server
 * did not tag it explicitly. Prefix-based, aligned with the shipped
 * rule catalog's category taxonomy (cost / reliability / security /
 * config_drift), collapsed onto the four verticals the FE colors.
 */
function inferVertical(rule: string | undefined, actionType: string | undefined): string {
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
 *   4. -1 (drop the event).
 *
 * HIL tiles are sticky - they never get evicted, so a human always
 * has time to review the queue.
 */
function pickSlot(state: LiveState, now: number): number {
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
    if (t.gate_decision === "hil") continue; // sticky
    const ageThreshold = t.completed ? AGE_DONE_MS : AGE_STALE_MS;
    if (now - t.last_seen_at < ageThreshold) continue;
    if (t.last_seen_at < oldestTs) {
      oldestTs = t.last_seen_at;
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
    if (!t.completed) continue;
    if (t.last_seen_at < oldestTs) {
      oldestTs = t.last_seen_at;
      oldestIdx = i;
    }
  }
  return oldestIdx;
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

export function LiveRoute({ client }: Props) {
  const [state, dispatch] = useReducer(reducer, undefined, makeInitialState);
  const [tickerPaused, setTickerPaused] = useState(false);
  const [tickerCollapsed, setTickerCollapsed] = useState(false);
  const pausedSnapshotRef = useRef<readonly LiveStageEvent[]>([]);
  const pausedAtRef = useRef<number>(0);
  const [pausedSince, setPausedSince] = useState<number>(0);

  const url = useMemo(() => {
    const cfg = loadConfig();
    const base = cfg.readApiBaseUrl || (typeof window !== "undefined" ? window.location.origin : "");
    return `${base.replace(/\/$/, "")}/live/stream`;
  }, []);

  const { status, lastError } = useLiveStream({
    url,
    onEvent: (event) => {
      // Buffer events; the setInterval flusher below folds them into
      // ONE reducer dispatch per tick so a high-rate stream never
      // triggers one React render per event (that path OOMs the
      // browser after a few minutes on tabs left open).
      pendingEventsRef.current.push(event);
    },
  });

  // Buffer + interval flusher for the SSE stream. Bounded at
  // FLUSH_CAP so a tab that was in the background does not drain a
  // huge backlog into one dispatch when it becomes visible. Uses
  // setInterval (not requestAnimationFrame) so the flusher does NOT
  // fire at 60 Hz when the buffer is empty - the reducer only runs
  // when there is real work.
  const pendingEventsRef = useRef<LiveStageEvent[]>([]);
  useEffect(() => {
    const FLUSH_CAP = 200;
    const FLUSH_INTERVAL_MS = 250;
    const handle = window.setInterval(() => {
      const buffer = pendingEventsRef.current;
      if (buffer.length === 0) return;
      const drained =
        buffer.length > FLUSH_CAP ? buffer.slice(-FLUSH_CAP) : buffer.slice();
      pendingEventsRef.current = [];
      dispatch({ kind: "batch", events: drained });
    }, FLUSH_INTERVAL_MS);
    return () => {
      window.clearInterval(handle);
      pendingEventsRef.current = [];
    };
  }, []);

  useEffect(() => {
    const handle = window.setInterval(() => {
      dispatch({ kind: "tick", now: Date.now() });
    }, 250);
    return () => window.clearInterval(handle);
  }, []);

  // Client is unused today but part of the panel contract; keep the
  // reference alive to silence unused-var complaints in strict mode.
  void client;

  // Freeze the ticker snapshot at pause time; while paused, the reducer
  // keeps updating state.ticker in the background but the operator sees
  // a stable list plus a "N new" counter so nothing is missed.
  const displayedTicker = tickerPaused ? pausedSnapshotRef.current : state.ticker;
  const newSincePause =
    tickerPaused && pausedSince > 0 ? Math.max(0, state.session_total - pausedSince) : 0;

  const togglePause = () => {
    if (tickerPaused) {
      setTickerPaused(false);
      setPausedSince(0);
      pausedSnapshotRef.current = [];
      pausedAtRef.current = 0;
    } else {
      pausedSnapshotRef.current = state.ticker;
      pausedAtRef.current = Date.now();
      setPausedSince(state.session_total);
      setTickerPaused(true);
    }
  };
  const toggleCollapse = () => setTickerCollapsed((v) => !v);

  const selectedTile = state.selectedEventId
    ? state.tiles.find((t) => t?.event_id === state.selectedEventId) ?? null
    : null;

  const eps = (state.ratePings.length / (RATE_WINDOW_MS / 1000)).toFixed(1);
  const gateTotal = Object.values(state.gateCounts).reduce((a, b) => a + b, 0);
  const tierTotal = Object.values(state.tierCounts).reduce((a, b) => a + b, 0);
  const hilPending = (state.gateCounts.hil ?? 0);

  // Attention triage - count tiles the operator actually needs to look at.
  // A tile is "stuck" if it started > STUCK_MS ago, is not completed, and
  // did not reach `audit`. HIL is sticky by design so it always counts.
  const STUCK_MS = 20_000;
  const attention = state.tiles.reduce(
    (acc, tile) => {
      if (!tile) return acc;
      if (tile.gate_decision === "hil") acc.hil += 1;
      if (tile.gate_decision === "deny") acc.deny += 1;
      if (tile.failed) acc.failed += 1;
      const stuck =
        !tile.completed &&
        !tile.failed &&
        tile.gate_decision !== "hil" &&
        state.now - tile.first_seen_at > STUCK_MS;
      if (stuck) acc.stuck += 1;
      return acc;
    },
    { hil: 0, deny: 0, failed: 0, stuck: 0 },
  );
  const attentionTotal = attention.hil + attention.deny + attention.failed + attention.stuck;

  // Environment / mode indicator. Dev mode is a session flag from config
  // - never fabricate a customer-facing environment value here.
  const isDevMode = useMemo(() => loadConfig().devMode === true, []);

  // Publish a rich view snapshot to the CommandDeck so the operator
  // can ask "what am I looking at?" and get grounded answers.
  const verticalCounts = useMemo(() => {
    const acc: Record<string, number> = { change: 0, resilience: 0, cost: 0, unknown: 0 };
    for (const t of state.tiles) {
      if (!t) continue;
      const v = t.vertical ?? "unknown";
      acc[v] = (acc[v] ?? 0) + 1;
    }
    return acc;
  }, [state.tiles]);
  const shadowCount = useMemo(
    () => state.tiles.filter((t) => t?.stages_completed.has("execute")).length,
    [state.tiles],
  );
  const activeTileCount = useMemo(
    () => state.tiles.filter((t) => t !== null).length,
    [state.tiles],
  );

  usePublishViewContext(
    () => {
      const pct = (v: number, total: number) =>
        total === 0 ? "0%" : `${Math.round((v / total) * 100)}%`;
      const stuckSet = new Set<string>();
      for (const t of state.tiles) {
        if (!t) continue;
        const stuck =
          !t.completed &&
          !t.failed &&
          t.gate_decision !== "hil" &&
          state.now - t.first_seen_at > 20_000;
        if (stuck) stuckSet.add(t.event_id);
      }
      return {
        routeId: "live",
        routeLabel: "Live cockpit",
        headline: `${activeTileCount} tile(s), ${eps} eps, ${attentionTotal} needing attention`,
        capturedAt: new Date().toISOString(),
        facts: [
          { key: "eps", value: eps, group: "throughput" },
          { key: "session.total", value: state.session_total, group: "throughput" },
          {
            key: "session.duration",
            value: formatDuration(state.now - state.session_started_at),
            group: "throughput",
          },
          { key: "tiles.active", value: activeTileCount, group: "tiles" },
          { key: "tiles.empty", value: POOL_SIZE - activeTileCount, group: "tiles" },
          { key: "tiles.shadow", value: shadowCount, group: "tiles" },
          { key: "tier.t0", value: pct(state.tierCounts.t0 ?? 0, tierTotal), group: "tier" },
          { key: "tier.t1", value: pct(state.tierCounts.t1 ?? 0, tierTotal), group: "tier" },
          { key: "tier.t2", value: pct(state.tierCounts.t2 ?? 0, tierTotal), group: "tier" },
          { key: "gate.auto", value: pct(state.gateCounts.auto ?? 0, gateTotal), group: "gate" },
          { key: "gate.hil", value: pct(state.gateCounts.hil ?? 0, gateTotal), group: "gate" },
          { key: "gate.abstain", value: pct(state.gateCounts.abstain ?? 0, gateTotal), group: "gate" },
          { key: "gate.deny", value: pct(state.gateCounts.deny ?? 0, gateTotal), group: "gate" },
          { key: "attention.total", value: attentionTotal, group: "attention" },
          { key: "attention.hil", value: attention.hil, group: "attention" },
          { key: "attention.deny", value: attention.deny, group: "attention" },
          { key: "attention.failed", value: attention.failed, group: "attention" },
          { key: "attention.stuck", value: attention.stuck, group: "attention" },
          { key: "verticals.change", value: verticalCounts.change ?? 0, group: "verticals" },
          { key: "verticals.resilience", value: verticalCounts.resilience ?? 0, group: "verticals" },
          { key: "verticals.cost", value: verticalCounts.cost ?? 0, group: "verticals" },
          { key: "verticals.unknown", value: verticalCounts.unknown ?? 0, group: "verticals" },
        ],
        records: {
          tiles: state.tiles
            .filter((t): t is TileState => t !== null)
            .map((t) => ({
              event_id: t.event_id,
              action_type: t.action_type ?? null,
              rule: t.rule ?? null,
              tier: t.tier ?? null,
              gate_decision: t.gate_decision ?? null,
              vertical: t.vertical ?? "unknown",
              resource_type: t.resource_type ?? null,
              scope: t.scope ?? null,
              stages_completed: [...t.stages_completed],
              completed: t.completed,
              failed: t.failed,
              stuck: stuckSet.has(t.event_id),
              age_ms: state.now - t.first_seen_at,
            })),
        },
      };
    },
    [
      state.tiles,
      // state.now intentionally omitted: the deck snapshot is a
      // low-frequency projection (chat context, not live UI). Including
      // it here rebuilds the ~60-tile snapshot 4x/sec regardless of
      // real event flow, which pins CPU + GC pressure on tabs left
      // open for hours. Every real state change already comes through
      // state.tiles / state.tierCounts / state.gateCounts.
      state.tierCounts,
      state.gateCounts,
      state.session_total,
      state.session_started_at,
      eps,
      gateTotal,
      tierTotal,
      attentionTotal,
      attention.hil,
      attention.deny,
      attention.failed,
      attention.stuck,
      verticalCounts,
      shadowCount,
      activeTileCount,
    ],
  );

  // Keyboard shortcuts: ESC closes the detail panel, `p` toggles pause,
  // `1..4` cycles the filter chips. All shortcuts are inert while the
  // focus is inside an input/textarea so they never steal typing.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      const tag = target?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || target?.isContentEditable) return;
      if (e.key === "Escape" && state.selectedEventId) {
        dispatch({ kind: "select", event_id: null });
        e.preventDefault();
        return;
      }
      if (e.key === "p" || e.key === "P") {
        togglePause();
        e.preventDefault();
        return;
      }
      const idx = ["1", "2", "3", "4"].indexOf(e.key);
      if (idx >= 0) {
        const filters: readonly FilterKind[] = ["all", "hil", "deny", "failed"];
        const value = filters[idx];
        if (value !== undefined) {
          dispatch({ kind: "filter", value });
          e.preventDefault();
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [state.selectedEventId, tickerPaused, state.session_total, state.ticker]);

  return (
    <div class="live" data-filter={state.filter} data-ticker-collapsed={tickerCollapsed ? "1" : "0"}>
      <section class="live-header">
        <div>
          <h2>Live</h2>
          <p class="muted">
            Every tile is one control-plane action flowing through the pipeline. Wire:
            <code>GET /live/stream</code>.
          </p>
        </div>
        <div class="live-header-right">
          {isDevMode ? (
            <span class="live-env-badge live-env-dev" title="dev mode: synthetic events, no real cloud calls">
              dev
            </span>
          ) : null}
          <span class="live-header-session muted">
            watching for <strong>{formatDuration(state.now - state.session_started_at)}</strong>
            {" · "}
            <strong>{state.session_total}</strong> events
          </span>
          <div class={`live-status live-status-${status}`}>
            <span class="live-status-dot" />
            <span>{STATUS_LABEL[status]}</span>
            {lastError ? <span class="muted"> · {lastError}</span> : null}
          </div>
        </div>
      </section>

      <section
        class={`live-attention ${attentionTotal > 0 ? "live-attention-active" : "live-attention-calm"}`}
        aria-label="operator attention triage"
      >
        {attentionTotal === 0 ? (
          <span class="live-attention-calm-text">
            <span class="live-attention-dot" aria-hidden="true" /> no attention needed · autonomy holding
          </span>
        ) : (
          <>
            <span class="live-attention-label">attention</span>
            {attention.hil > 0 ? (
              <button
                type="button"
                class="live-attention-chip live-attention-hil"
                onClick={() => dispatch({ kind: "filter", value: "hil" })}
                title="HIL: high-risk actions awaiting a human approver"
              >
                <strong>{attention.hil}</strong> HIL waiting
              </button>
            ) : null}
            {attention.deny > 0 ? (
              <button
                type="button"
                class="live-attention-chip live-attention-deny"
                onClick={() => dispatch({ kind: "filter", value: "deny" })}
                title="Deny: risk-gate refused; investigate why the policy fired"
              >
                <strong>{attention.deny}</strong> denied
              </button>
            ) : null}
            {attention.failed > 0 ? (
              <button
                type="button"
                class="live-attention-chip live-attention-failed"
                onClick={() => dispatch({ kind: "filter", value: "failed" })}
                title="Failed: action or stage errored; check the audit entry"
              >
                <strong>{attention.failed}</strong> failed
              </button>
            ) : null}
            {attention.stuck > 0 ? (
              <span
                class="live-attention-chip live-attention-stuck"
                title={`Stuck: ${STUCK_MS / 1000}s+ without reaching audit`}
              >
                <strong>{attention.stuck}</strong> stuck
              </span>
            ) : null}
          </>
        )}
      </section>

      <section class="grid live-kpis">
        <div class="card kpi live-kpi-eps">
          <span class="label">Events / sec (60s)</span>
          <span class="value">{eps}</span>
          <Sparkline buckets={state.rateBuckets} />
          <div class="live-spark-legend" aria-hidden="true">
            <span class="live-spark-key t0"><i />T0 <b>{sumBuckets(state.rateBuckets.t0)}</b></span>
            <span class="live-spark-key t1"><i />T1 <b>{sumBuckets(state.rateBuckets.t1)}</b></span>
            <span class="live-spark-key t2"><i />T2 <b>{sumBuckets(state.rateBuckets.t2)}</b></span>
          </div>
        </div>
        <div class="card kpi">
          <span class="label">Tier mix (60s)</span>
          <StackBar
            entries={(["t0", "t1", "t2"] as const).map((k) => ({
              key: k,
              label: k.toUpperCase(),
              value: state.tierCounts[k] ?? 0,
              className: `live-tier live-tier-${k}`,
            }))}
            total={tierTotal}
          />
        </div>
        <div class="card kpi">
          <span class="label">Gate mix (60s)</span>
          <StackBar
            entries={(["auto", "hil", "abstain", "deny"] as const).map((k) => ({
              key: k,
              label: k,
              value: state.gateCounts[k] ?? 0,
              className: `live-gate live-gate-${k}`,
            }))}
            total={gateTotal}
          />
        </div>
        <div class="card kpi live-kpi-guards">
          <span class="label">Guards</span>
          <div class="live-guards">
            <span class="live-guard ok">CFR</span>
            <span class="live-guard ok">FPR</span>
            <span class="live-guard ok">RB</span>
            <span class="live-guard ok">ESC</span>
          </div>
          <span class="live-guards-note muted">
            {hilPending > 0 ? `${hilPending} HIL pending` : "within budget"}
          </span>
        </div>
      </section>

      <section class="live-filterbar" aria-label="tile filters">
        {(["all", "hil", "deny", "failed"] as const).map((f, i) => (
          <button
            key={f}
            type="button"
            class={`live-filter-chip ${state.filter === f ? "active" : ""}`}
            onClick={() => dispatch({ kind: "filter", value: f })}
            title={`filter: ${f} (press ${i + 1})`}
          >
            {f}
            <span class="live-filter-kbd" aria-hidden="true">{i + 1}</span>
          </button>
        ))}
        <span class="muted live-filterbar-hint">
          click a tile for details · <kbd>Esc</kbd> close · <kbd>P</kbd> pause · <kbd>1</kbd>-<kbd>4</kbd> filter
        </span>
      </section>

      <section class="live-swarm" aria-label="live control-plane activity">
        {state.tiles.map((tile, idx) => (
          <LiveTile
            key={idx}
            tile={tile}
            filter={state.filter}
            selected={tile?.event_id === state.selectedEventId}
            now={state.now}
            onClick={
              tile
                ? () =>
                    dispatch({
                      kind: "select",
                      event_id: tile.event_id === state.selectedEventId ? null : tile.event_id,
                    })
                : undefined
            }
          />
        ))}
      </section>

      <aside
        class={`live-ticker card${tickerCollapsed ? " live-ticker-collapsed" : ""}${tickerPaused ? " live-ticker-paused" : ""}`}
        aria-label="audit stream"
      >
        <header class="live-ticker-header">
          <h3>
            Audit stream <span class="muted">· append-only</span>
            {tickerPaused && newSincePause > 0 ? (
              <span class="live-ticker-badge" title="new terminal events observed since pause">
                {newSincePause} new
              </span>
            ) : null}
          </h3>
          <div class="live-ticker-controls" role="toolbar" aria-label="ticker controls">
            <button
              type="button"
              class="live-ticker-btn"
              onClick={togglePause}
              aria-pressed={tickerPaused}
              title={tickerPaused ? "Resume ticker" : "Pause ticker"}
              aria-label={tickerPaused ? "Resume ticker" : "Pause ticker"}
            >
              {tickerPaused ? (
                // play icon
                <svg viewBox="0 0 12 12" width="12" height="12" aria-hidden="true">
                  <path d="M3 2 L10 6 L3 10 Z" fill="currentColor" />
                </svg>
              ) : (
                // pause icon
                <svg viewBox="0 0 12 12" width="12" height="12" aria-hidden="true">
                  <rect x="3" y="2" width="2.5" height="8" fill="currentColor" />
                  <rect x="6.5" y="2" width="2.5" height="8" fill="currentColor" />
                </svg>
              )}
            </button>
            <button
              type="button"
              class="live-ticker-btn"
              onClick={toggleCollapse}
              aria-expanded={!tickerCollapsed}
              title={tickerCollapsed ? "Expand ticker" : "Collapse ticker"}
              aria-label={tickerCollapsed ? "Expand ticker" : "Collapse ticker"}
            >
              {tickerCollapsed ? (
                // chevron up (expand → show content upward)
                <svg viewBox="0 0 12 12" width="12" height="12" aria-hidden="true">
                  <path
                    d="M2 8 L6 4 L10 8"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="1.6"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                  />
                </svg>
              ) : (
                // chevron down (collapse)
                <svg viewBox="0 0 12 12" width="12" height="12" aria-hidden="true">
                  <path
                    d="M2 4 L6 8 L10 4"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="1.6"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                  />
                </svg>
              )}
            </button>
          </div>
        </header>
        {tickerCollapsed ? null : (
          <ol>
            {displayedTicker.map((evt, i) => {
              const tier = (evt.detail?.tier as string | undefined) ?? "abstain";
              const gate = evt.detail?.gate_decision as string | undefined;
              const rule = evt.detail?.rule as string | undefined;
              const action = evt.detail?.action_type as string | undefined;
              const scope = evt.detail?.scope as string | undefined;
              const outcome = evt.detail?.outcome as string | undefined;
              return (
                <li key={`${evt.event_id}-${evt.stage}-${evt.phase}-${evt.ts}-${i}`}>
                  <span class="muted">{shortTime(evt.ts)}</span>
                  <span class={`live-tier live-tier-${tier}`}>
                    {tier === "abstain" ? "N/A" : tier.toUpperCase()}
                  </span>
                  <code>{evt.event_id.slice(0, 8)}</code>
                  <span class="live-ticker-stage">{evt.stage}.{evt.phase}</span>
                  {action ? <strong>{action}</strong> : null}
                  {scope ? <span class="live-ticker-scope">@{scope}</span> : null}
                  {rule && rule !== action ? <span class="muted">({rule})</span> : null}
                  {gate ? <span class={`live-gate live-gate-${gate}`}>{gate}</span> : null}
                  {outcome && outcome !== gate ? (
                    <span class={`live-ticker-tail ${outcome}`}>{outcome}</span>
                  ) : null}
                </li>
              );
            })}
            {displayedTicker.length === 0 ? (
              <li class="muted">Waiting for stage frames…</li>
            ) : null}
          </ol>
        )}
      </aside>

      {selectedTile ? (
        <DetailPanel
          tile={selectedTile}
          now={state.now}
          onClose={() => dispatch({ kind: "select", event_id: null })}
        />
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

interface TileProps {
  readonly tile: TileState | null;
  readonly filter: FilterKind;
  readonly selected: boolean;
  readonly now: number;
  readonly onClick: (() => void) | undefined;
}

function LiveTile({ tile, filter, selected, now, onClick }: TileProps) {
  if (!tile) {
    return <div class="live-tile live-tile-empty" data-empty="1" aria-hidden="true" />;
  }

  const vertical = tile.vertical ?? "unknown";
  const tier = tile.tier ?? "abstain";
  const gate = tile.gate_decision ?? "";
  const dimmed = matchesFilter(tile, filter) ? "" : " dimmed";
  const failed = tile.failed ? "1" : "0";
  const done = tile.completed ? "1" : "0";
  const ageMs = Math.max(0, now - tile.first_seen_at);
  const heading =
    tile.action_type ??
    (tile.completed && !tile.gate_decision ? "no rule matched" : "routing...");
  const tierLabel = tier === "abstain" ? "N/A" : tier.toUpperCase();
  // Abstain-and-done tiles carry zero operational information. Mark
  // them so CSS can quiet them into a background pattern rather than
  // stealing visual weight from remediation tiles.
  const abstain = tile.completed && !tile.gate_decision && !tile.action_type ? "1" : "0";

  return (
    <button
      type="button"
      class={`live-tile live-tile-vertical-${vertical} live-tile-gate-${gate}${dimmed}`}
      data-empty="0"
      data-failed={failed}
      data-done={done}
      data-abstain={abstain}
      data-selected={selected ? "1" : "0"}
      onClick={onClick}
      aria-label={`${tile.action_type ?? "(routing)"} on ${tile.resource_type ?? "unknown"}`}
    >
      <StageDots completed={tile.stages_completed} last_stage={tile.last_stage} />
      <div class="live-tile-top">
        <span class="live-tile-action" title={tile.rule ?? tile.action_type}>
          {heading}
        </span>
        <span class={`live-tier live-tier-${tier}`}>{tierLabel}</span>
      </div>
      <div class="live-tile-target">
        <span>{tile.resource_type ?? "-"}</span>
        <span class="muted">{tile.scope ? ` · ${tile.scope}` : ""}</span>
      </div>
      <div class="live-tile-foot">
        {gate ? (
          <span class={`live-gate live-gate-${gate}`}>{gate}</span>
        ) : (
          <span class="muted">…</span>
        )}
        {tile.stages_completed.has("execute") ? (
          <span class="live-tile-mode" title="Action executed in shadow mode - a remediation PR, not an enforce write">
            shadow
          </span>
        ) : null}
        <span class="muted live-tile-age">{formatAge(ageMs)}</span>
      </div>
      {gate === "hil" ? <span class="live-tile-badge">needs approval</span> : null}
    </button>
  );
}

function StageDots({
  completed,
  last_stage,
}: {
  readonly completed: ReadonlySet<LiveStageName>;
  readonly last_stage: LiveStageName;
}) {
  return (
    <div class="live-tile-progress" aria-hidden="true">
      {STAGE_ORDER.map((stage) => (
        <span
          key={stage}
          class={`live-tile-dot ${completed.has(stage) ? "done" : ""} ${last_stage === stage ? "current" : ""}`}
        />
      ))}
    </div>
  );
}

function matchesFilter(tile: TileState, filter: FilterKind): boolean {
  if (filter === "all") return true;
  if (filter === "hil") return tile.gate_decision === "hil";
  if (filter === "deny") return tile.gate_decision === "deny";
  if (filter === "failed") return tile.failed;
  return true;
}

function Sparkline({ buckets }: { readonly buckets: RateBuckets }) {
  const width = 240;
  const height = 44;
  const pad = 3;
  // Drop the trailing bucket: it is the current, still-accumulating second.
  // Plotting it makes the right edge sawtooth down to zero on every 1s roll
  // (events refill it from 0 each second). Rendering only completed seconds
  // keeps the right edge stable - it is the last fully-elapsed second.
  const t0 = buckets.t0.slice(0, -1);
  const t1 = buckets.t1.slice(0, -1);
  const t2 = buckets.t2.slice(0, -1);
  const series = [t0, t1, t2];
  const n = t0.length;
  // Shared scale so the three tiers stay comparable; a small headroom keeps
  // the dominant T0 line off the top edge for a calmer read.
  const max = Math.max(1, ...t0, ...t1, ...t2) * 1.15;
  const stepX = width / (n - 1 || 1);
  const base = height - pad;
  const span = height - pad * 2;
  const cls = ["live-spark-t0", "live-spark-t1", "live-spark-t2"] as const;
  // Smooth the line (quadratic through bucket midpoints) so a low, noisy
  // per-second rate reads as a calm curve instead of a jagged staircase.
  const linePath = (arr: readonly number[]): string => {
    const pts = arr.map((v, i) => [i * stepX, base - (v / max) * span] as const);
    const first = pts[0];
    if (!first) return "";
    let d = `M${first[0].toFixed(1)},${first[1].toFixed(1)}`;
    for (let j = 0; j < pts.length - 1; j++) {
      const a = pts[j];
      const b = pts[j + 1];
      if (!a || !b) continue;
      const mx = (a[0] + b[0]) / 2;
      const my = (a[1] + b[1]) / 2;
      d += ` Q${a[0].toFixed(1)},${a[1].toFixed(1)} ${mx.toFixed(1)},${my.toFixed(1)}`;
    }
    const last = pts[pts.length - 1];
    if (last) d += ` L${last[0].toFixed(1)},${last[1].toFixed(1)}`;
    return d;
  };
  const lastX = (n - 1) * stepX;
  return (
    <svg
      class="live-spark"
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      aria-hidden="true"
    >
      {series.map((arr, i) => {
        const d = linePath(arr);
        if (!d) return null;
        return (
          <g key={cls[i]}>
            <path d={`${d} L${lastX.toFixed(1)},${height} L0,${height} Z`} class={`live-spark-area ${cls[i]}-area`} />
            <path
              d={d}
              fill="none"
              class={cls[i]}
              stroke-width="1.6"
              stroke-linecap="round"
              stroke-linejoin="round"
            />
          </g>
        );
      })}
    </svg>
  );
}

interface StackEntry {
  readonly key: string;
  readonly label: string;
  readonly value: number;
  readonly className: string;
}

function StackBar({ entries, total }: { readonly entries: readonly StackEntry[]; readonly total: number }) {
  return (
    <div class="live-stackbar">
      <div class="live-stackbar-bar" aria-hidden="true">
        {entries.map((e) => (
          <span
            key={e.key}
            class={`live-stackbar-seg ${e.className}`}
            style={{ width: `${total > 0 ? (e.value / total) * 100 : 0}%` }}
          />
        ))}
      </div>
      <div class="live-stackbar-legend">
        {entries.map((e) => (
          <span key={e.key} class={e.className}>
            {e.label} {total > 0 ? Math.round((e.value / total) * 100) : 0}%
          </span>
        ))}
      </div>
    </div>
  );
}

function DetailPanel({
  tile,
  now,
  onClose,
}: {
  readonly tile: TileState;
  readonly now: number;
  readonly onClose: () => void;
}) {
  return (
    <div class="live-detail-backdrop" onClick={onClose}>
      <aside class="live-detail-panel" onClick={(e) => e.stopPropagation()}>
        <header>
          <h3>{tile.action_type ?? "(pending)"}</h3>
          <button type="button" class="live-detail-close" onClick={onClose} aria-label="Close">
            ×
          </button>
        </header>
        <dl class="live-detail-list">
          <dt>Event id</dt>
          <dd><code>{tile.event_id}</code></dd>
          <dt>Rule</dt>
          <dd>{tile.rule ?? "-"}</dd>
          <dt>ActionType</dt>
          <dd>{tile.action_type ?? "-"}</dd>
          <dt>Vertical</dt>
          <dd>{tile.vertical ?? "-"}</dd>
          <dt>Resource type</dt>
          <dd>{tile.resource_type ?? "-"}</dd>
          <dt>Scope</dt>
          <dd>{tile.scope ?? "-"}</dd>
          <dt>Tier</dt>
          <dd>
            {tile.tier ? (
              <span class={`live-tier live-tier-${tile.tier}`}>{tile.tier.toUpperCase()}</span>
            ) : (
              "-"
            )}
          </dd>
          <dt>Gate decision</dt>
          <dd>
            {tile.gate_decision ? (
              <span class={`live-gate live-gate-${tile.gate_decision}`}>{tile.gate_decision}</span>
            ) : (
              "-"
            )}
          </dd>
          <dt>Stages completed</dt>
          <dd>
            {STAGE_ORDER.filter((s) => tile.stages_completed.has(s)).join(" · ") || "-"}
          </dd>
          <dt>Failed</dt>
          <dd>{tile.failed ? "yes" : "no"}</dd>
          <dt>Age</dt>
          <dd>{formatAge(Math.max(0, now - tile.first_seen_at))}</dd>
          <dt>Outcome</dt>
          <dd>{tile.outcome ?? "-"}</dd>
        </dl>
        <h4 class="live-detail-subhead">Safety invariants (executor guarantees)</h4>
        <ul class="live-detail-safety">
          <li>stop-condition on the ActionType</li>
          <li>tested rollback path</li>
          <li>blast-radius cap enforced</li>
          <li>audit-log entry per terminal outcome</li>
        </ul>
        <p class="muted live-detail-note">
          This panel is read-only. Approvals happen in ChatOps or via a remediation PR.
        </p>
      </aside>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------

function shortTime(iso: string): string {
  const match = iso.match(/T(\d\d:\d\d:\d\d\.\d{3})/);
  return match?.[1] ?? iso;
}

function formatAge(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  const secs = Math.floor(ms / 1000);
  if (secs < 60) return `${secs}s`;
  const mins = Math.floor(secs / 60);
  return `${mins}m`;
}

function formatDuration(ms: number): string {
  const secs = Math.floor(ms / 1000);
  if (secs < 60) return `${secs}s`;
  const mins = Math.floor(secs / 60);
  const remSecs = secs % 60;
  if (mins < 60) return remSecs > 0 ? `${mins}m ${remSecs}s` : `${mins}m`;
  const hrs = Math.floor(mins / 60);
  const remMins = mins % 60;
  return remMins > 0 ? `${hrs}h ${remMins}m` : `${hrs}h`;
}
