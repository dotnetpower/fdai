import type { AgentOperationalActivityMessage } from "../agent-operational-activity";
import type { LiveStageEvent } from "../hooks/use-live-stream";

export const LIVE_METRIC_WINDOW_MS = 60_000;
export const LIVE_METRIC_CAPACITY = 10_000;
export const LIVE_METRIC_TIERS = ["t0", "t1", "t2"] as const;
export const LIVE_METRIC_GATES = ["auto", "hil", "abstain", "deny"] as const;
type Tier = typeof LIVE_METRIC_TIERS[number];
type Gate = typeof LIVE_METRIC_GATES[number];
type Lane = "control" | "source";
interface TimedValue<T> {
  readonly at: number;
  readonly value: T;
  readonly lastSeenAt?: number;
}

/** Tab-local measurements, independent of the bounded card pool and execution authority. */
export interface LiveMetrics {
  readonly frames: Map<string, TimedValue<Lane>>;
  readonly tiers: Map<string, TimedValue<Tier>>;
  readonly gates: Map<string, TimedValue<Gate>>;
  partialUntil: number;
}

export function createLiveMetrics(): LiveMetrics {
  return { frames: new Map(), tiers: new Map(), gates: new Map(), partialUntil: 0 };
}

function prune<T>(values: Map<string, TimedValue<T>>, now: number): void {
  for (const [key, item] of values) {
    if ((item.lastSeenAt ?? item.at) <= now - LIVE_METRIC_WINDOW_MS) values.delete(key);
  }
}

function retain<T>(
  metrics: LiveMetrics,
  values: Map<string, TimedValue<T>>,
  key: string,
  item: TimedValue<T>,
  now: number,
): void {
  const previous = values.get(key);
  // Identical facts on later stages or reconnects don't restart their measurement window.
  if (previous?.value === item.value) {
    values.set(key, {
      ...previous,
      at: Math.min(previous.at, item.at),
      lastSeenAt: Math.max(previous.lastSeenAt ?? previous.at, item.at),
    });
    return;
  }
  if (previous && (previous.lastSeenAt ?? previous.at) > item.at) return;
  prune(values, now);
  if (!values.has(key) && values.size >= LIVE_METRIC_CAPACITY) {
    metrics.partialUntil = now + LIVE_METRIC_WINDOW_MS;
    return;
  }
  values.set(key, item);
}

function eventTime(metrics: LiveMetrics, timestamp: string, now: number): number | null {
  const at = Date.parse(timestamp);
  if (!Number.isFinite(at) || at > now) {
    metrics.partialUntil = now + LIVE_METRIC_WINDOW_MS;
    return null;
  }
  return at > now - LIVE_METRIC_WINDOW_MS ? at : null;
}

/** Count one decoded business frame, deduplicating replay without counting transport heartbeats. */
export function observeLiveControl(metrics: LiveMetrics, event: LiveStageEvent, now: number): void {
  const at = eventTime(metrics, event.ts, now);
  if (at === null) return;
  const key = JSON.stringify([event.event_id, event.correlation_id, event.stage, event.phase, event.ts]);
  retain(metrics, metrics.frames, `control:${key}`, { at, value: "control" }, now);
  const detail = event.detail ?? {};
  const tier = LIVE_METRIC_TIERS.find(value => value === (detail.tier ?? detail.routed_to));
  if (event.phase === "done" || event.phase === "failed") {
    if (tier) {
      retain(metrics, metrics.tiers, event.event_id, { at, value: tier }, now);
    }
    const gate = LIVE_METRIC_GATES.find(value =>
      value === (detail.gate_decision ?? (event.stage === "audit" ? detail.decision : undefined)),
    );
    if (gate) {
      retain(metrics, metrics.gates, event.event_id, { at, value: gate }, now);
    }
  }
}

/** Source lifecycle frames affect throughput only, never tier, gate, or finding counts. */
export function observeLiveSource(
  metrics: LiveMetrics,
  activity: AgentOperationalActivityMessage,
  now: number,
): void {
  const at = eventTime(metrics, activity.observed_at, now);
  if (at === null) return;
  retain(metrics, metrics.frames, `source:${activity.idempotency_key}`, { at, value: "source" }, now);
}

/** Derive the last 60 event-time seconds; old snapshots don't become a new arrival spike. */
export function summarizeLiveMetrics(metrics: LiveMetrics, now: number) {
  prune(metrics.frames, now);
  prune(metrics.tiers, now);
  prune(metrics.gates, now);
  const controlBuckets = new Array<number>(60).fill(0);
  const sourceBuckets = new Array<number>(60).fill(0);
  const tierCounts = { t0: 0, t1: 0, t2: 0 };
  const gateCounts = { auto: 0, hil: 0, abstain: 0, deny: 0 };
  let control = 0;
  let source = 0;
  for (const item of metrics.frames.values()) {
    if (item.at <= now - LIVE_METRIC_WINDOW_MS) continue;
    const index = 59 - Math.min(59, Math.floor((now - item.at) / 1_000));
    if (item.value === "control") {
      control += 1;
      controlBuckets[index] = (controlBuckets[index] ?? 0) + 1;
    } else {
      source += 1;
      sourceBuckets[index] = (sourceBuckets[index] ?? 0) + 1;
    }
  }
  for (const item of metrics.tiers.values()) {
    if (item.at > now - LIVE_METRIC_WINDOW_MS) tierCounts[item.value] += 1;
  }
  for (const item of metrics.gates.values()) {
    if (item.at > now - LIVE_METRIC_WINDOW_MS) gateCounts[item.value] += 1;
  }
  const gateTotal = Object.values(gateCounts).reduce((sum, value) => sum + value, 0);
  return {
    eps: ((control + source) / 60).toFixed(2),
    control,
    source,
    controlBuckets,
    sourceBuckets,
    tierCounts,
    gateCounts,
    tierTotal: Object.values(tierCounts).reduce((sum, value) => sum + value, 0),
    gateTotal,
    autoShare: gateTotal === 0 ? 0 : Math.round(gateCounts.auto / gateTotal * 100),
    partial: metrics.partialUntil > now,
  };
}

export type LiveMetricSummary = ReturnType<typeof summarizeLiveMetrics>;
