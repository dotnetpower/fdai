import { describe, expect, test } from "vitest";
import { consumeLiveSse, type LiveStageEvent } from "../hooks/use-live-stream";
import { sampleLiveObservations } from "./operations.sample-events";
import {
  createLiveMetrics,
  LIVE_METRIC_CAPACITY,
  observeLiveControl,
  observeLiveSource,
  summarizeLiveMetrics,
} from "./live.metrics";

const now = Date.parse("2026-09-15T05:00:00Z");
function stage(stage: LiveStageEvent["stage"], offset = 0): LiveStageEvent {
  return {
    event_id: "example-event",
    correlation_id: "example-correlation",
    stage,
    phase: "done",
    source: "runtime-observed",
    ts: new Date(now + offset).toISOString(),
  };
}

describe("Live SSE measurements", () => {
  test("counts source lifecycle and every control stage without waiting for audit", () => {
    const metrics = createLiveMetrics();
    observeLiveSource(metrics, sampleLiveObservations(now)[0]!, now);
    observeLiveControl(metrics, stage("ingest"), now);
    observeLiveControl(metrics, { ...stage("route"), detail: { tier: "t1" } }, now);
    observeLiveControl(metrics, { ...stage("gate"), detail: { gate_decision: "hil" } }, now);
    expect(summarizeLiveMetrics(metrics, now)).toMatchObject({
      control: 3, source: 1, eps: "0.07",
      tierCounts: { t0: 0, t1: 1, t2: 0 },
      gateCounts: { auto: 0, hil: 1, abstain: 0, deny: 0 },
      tierTotal: 1, gateTotal: 1,
    });
  });

  test("does not invent gate or tier facts for source-only work", () => {
    const metrics = createLiveMetrics();
    observeLiveSource(metrics, sampleLiveObservations(now)[2]!, now);
    expect(summarizeLiveMetrics(metrics, now)).toMatchObject({
      source: 1, control: 0, eps: "0.02", gateTotal: 0, tierTotal: 0,
    });
  });

  test("counts distinct lifecycle updates but not repeated delivery of the same update", () => {
    const metrics = createLiveMetrics();
    const completed = sampleLiveObservations(now)[0]!;
    const started = {
      ...completed,
      status: "started" as const,
      activity_id: `${completed.activity_instance_id}:started`,
      idempotency_key: `${completed.activity_instance_id}:started`,
    };
    observeLiveSource(metrics, started, now);
    observeLiveSource(metrics, completed, now);
    observeLiveSource(metrics, completed, now);
    expect(summarizeLiveMetrics(metrics, now)).toMatchObject({
      source: 2, control: 0, gateTotal: 0, tierTotal: 0,
    });
  });

  test("deduplicates snapshot replay and repeated facts without extending their window", () => {
    const metrics = createLiveMetrics();
    const source = sampleLiveObservations(now)[0]!;
    const route = { ...stage("route"), detail: { tier: "t0", gate_decision: "auto" } };
    observeLiveSource(metrics, source, now);
    observeLiveSource(metrics, source, now + 1_000);
    observeLiveControl(metrics, route, now);
    observeLiveControl(metrics, { ...route, source: "replay" }, now + 1_000);
    observeLiveControl(metrics, { ...stage("audit", 20_000), detail: route.detail }, now + 20_000);
    expect(summarizeLiveMetrics(metrics, now + 20_000)).toMatchObject({
      source: 1, control: 2, tierTotal: 1, gateTotal: 1,
    });
    expect(summarizeLiveMetrics(metrics, now + 60_000)).toMatchObject({
      source: 0, control: 1, tierTotal: 0, gateTotal: 0,
    });
    observeLiveControl(metrics, { ...stage("audit", 61_000), detail: route.detail }, now + 61_000);
    expect(summarizeLiveMetrics(metrics, now + 61_000)).toMatchObject({
      tierTotal: 0, gateTotal: 0,
    });
    expect(summarizeLiveMetrics(metrics, now + 121_000).eps).toBe("0.00");
  });

  test("places recent replay in its original second and excludes old snapshots", () => {
    const metrics = createLiveMetrics();
    observeLiveControl(metrics, stage("ingest", -12_000), now);
    observeLiveControl(metrics, stage("audit", -60_000), now);
    observeLiveSource(metrics, sampleLiveObservations(now - 60_000)[0]!, now);
    const summary = summarizeLiveMetrics(metrics, now);
    expect(summary.control).toBe(1);
    expect(summary.source).toBe(0);
    expect(summary.controlBuckets[47]).toBe(1);
    expect(summary.controlBuckets[59]).toBe(0);
  });

  test("revises a real decision but rejects stale and unknown classifications", () => {
    const metrics = createLiveMetrics();
    observeLiveControl(metrics, { ...stage("gate"), detail: { gate_decision: "hil", tier: "t2" } }, now);
    observeLiveControl(metrics, { ...stage("gate", 1_000), detail: { gate_decision: "deny" } }, now + 1_000);
    observeLiveControl(metrics, { ...stage("gate", -1_000), detail: { gate_decision: "auto" } }, now + 1_000);
    observeLiveControl(metrics, { ...stage("route"), detail: { tier: "t9" } }, now + 1_000);
    expect(summarizeLiveMetrics(metrics, now + 1_000)).toMatchObject({
      gateCounts: { auto: 0, hil: 0, deny: 1, abstain: 0 },
      tierCounts: { t0: 0, t1: 0, t2: 1 },
    });
  });

  test("exposes bounded-capacity and invalid-clock gaps instead of a complete-looking result", () => {
    const metrics = createLiveMetrics();
    observeLiveControl(metrics, { ...stage("ingest"), ts: "invalid" }, now);
    expect(summarizeLiveMetrics(metrics, now)).toMatchObject({ partial: true, control: 0 });
    for (let index = 0; index <= LIVE_METRIC_CAPACITY; index += 1) {
      observeLiveControl(metrics, { ...stage("ingest"), event_id: `event-${index}` }, now);
    }
    expect(metrics.frames.size).toBe(LIVE_METRIC_CAPACITY);
    expect(summarizeLiveMetrics(metrics, now).partial).toBe(true);
    expect(summarizeLiveMetrics(metrics, now + 60_000)).toMatchObject({ partial: false, control: 0 });
  });

  test("SSE transport admits business messages only, not keepalives and status snapshots", async () => {
    const metrics = createLiveMetrics();
    const source = sampleLiveObservations(now)[0]!;
    const frame = (event: string, data: unknown) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
    await consumeLiveSse(new Response(
      ": keepalive\n\n" +
      frame("hello", { status: "ok" }) +
      frame("source", { status: "ready", source: "runtime-observed", ts: stage("ingest").ts }) +
      frame("activity-status-snapshot", {
        type: "live.activity-status", status: "ready", reason: null, ts: stage("ingest").ts,
      }) +
      frame("activity-snapshot", source) +
      frame("activity", source) +
      frame("stage", stage("ingest")),
      { headers: { "content-type": "text/event-stream" } },
    ), event => observeLiveControl(metrics, event, now), undefined,
    activity => observeLiveSource(metrics, activity, now));
    expect(summarizeLiveMetrics(metrics, now)).toMatchObject({
      control: 1, source: 1, tierTotal: 0, gateTotal: 0,
    });
  });
});
