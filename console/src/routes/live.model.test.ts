import { describe, expect, test } from "vitest";
import type { LiveStageEvent } from "../hooks/use-live-stream";
import {
  liveSelectionState,
  applyEvent,
  HIL_RETENTION_MS,
  isTileStuck,
  makeInitialState,
  matchesFilter,
  pickSlot,
} from "./live.model";
import { appendLiveBacklog, drainLiveBacklog, liveTraceHref } from "./live";
import {
  authorityModeHelp,
  authorityModeLabel,
  compareLiveTiles,
  liveControlState,
} from "./live.tiles";

describe("live event selection", () => {
  test("links a recent outcome to correlation-scoped Trace evidence", () => {
    expect(liveTraceHref("corr-1")).toBe("/trace?correlation=corr-1");
  });

  test("distinguishes waiting, selected, and unavailable deep links", () => {
    expect(liveSelectionState(null, null, 0)).toBe("none");
    expect(liveSelectionState("event-1", null, 0)).toBe("waiting");
    expect(liveSelectionState("event-1", {} as never, 0)).toBe("selected");
    expect(liveSelectionState("event-1", null, 1)).toBe("unavailable");
  });
});

describe("live frame backlog", () => {
  test("preserves arrival order across bounded drains", () => {
    const events = [
      { ...stageEvent("ingest", {}), event_id: "one" },
      { ...stageEvent("route", {}), event_id: "two" },
      { ...stageEvent("audit", {}), event_id: "three" },
    ];
    const first = drainLiveBacklog(events, 2);
    expect(first.drained.map((event) => event.event_id)).toEqual(["one", "two"]);
    expect(first.remaining.map((event) => event.event_id)).toEqual(["three"]);
  });

  test("retains newest frames and reports bounded overflow", () => {
    const one = { ...stageEvent("ingest", {}), event_id: "one" };
    const two = { ...stageEvent("route", {}), event_id: "two" };
    const three = { ...stageEvent("audit", {}), event_id: "three" };
    const result = appendLiveBacklog([one, two], three, 2);
    expect(result.backlog.map((event) => event.event_id)).toEqual(["two", "three"]);
    expect(result.dropped).toBe(1);
  });
});

function stageEvent(
  stage: LiveStageEvent["stage"],
  detail: Record<string, unknown>,
): LiveStageEvent {
  return {
    event_id: "evt-live-1",
    correlation_id: "corr-live-1",
    stage,
    phase: "done",
    source: "runtime-observed",
    ts: "2026-07-15T00:00:00.000Z",
    detail,
  };
}

describe("Live cockpit model", () => {
  test("retains correlation and execution mode across stage frames", () => {
    let state = makeInitialState();
    state = applyEvent(state, stageEvent("route", { tier: "t0" }));
    state = applyEvent(state, stageEvent("execute", { mode: "enforce" }));
    state = applyEvent(state, stageEvent("audit", { outcome: "executed" }));

    const tile = state.tiles.find((candidate) => candidate?.event_id === "evt-live-1");
    expect(tile?.correlation_id).toBe("corr-live-1");
    expect(tile?.mode).toBe("enforce");
    expect(tile?.completed).toBe(true);
  });

  test("preserves authoritative work context without inferring missing fields", () => {
    let state = makeInitialState();
    state = applyEvent(
      state,
      stageEvent("gate", {
        tier: "t2",
        mode: "shadow",
        autonomy: "A0",
        resource_type: "compute.vm",
        scope: "example-scope",
        target: "example-target",
        reason: "Policy evidence requires review",
        risk: "medium",
        impact: "one resource",
      }),
    );

    const tile = state.tiles.find((candidate) => candidate?.event_id === "evt-live-1");
    expect(tile).toMatchObject({
      autonomy: "A0",
      target: "example-target",
      reason: "Policy evidence requires review",
      risk: "medium",
      impact: "one resource",
    });
  });

  test("explains explicit authority without inventing a missing autonomy class", () => {
    let state = makeInitialState();
    state = applyEvent(
      state,
      stageEvent("gate", {
        autonomy: "A3-H",
        mode: "gated",
        gate_decision: "hil",
      }),
    );
    const explicit = state.tiles.find((candidate) => candidate?.event_id === "evt-live-1");
    expect(explicit && authorityModeLabel(explicit)).toBe("A3-H · GATED");
    expect(explicit && authorityModeHelp(explicit)).toContain("human approval");
    expect(explicit && liveControlState(explicit)).toMatchObject({
      policy: "Approval",
      authority: "A3-H",
      execution: "Not dispatched",
    });

    state = makeInitialState();
    state = applyEvent(state, stageEvent("route", { tier: "t0" }));
    const missing = state.tiles.find((candidate) => candidate?.event_id === "evt-live-1");
    expect(missing && authorityModeLabel(missing)).toBe("Pending");
    expect(missing && authorityModeHelp(missing)).toContain("has not published an exact autonomy class");
  });

  test("uses the terminal event decision and counts a replay only once", () => {
    let state = makeInitialState();
    state = applyEvent(
      state,
      stageEvent("gate", {
        action_type: "remediate.first",
        gate_decision: "auto",
      }),
    );
    state = applyEvent(
      state,
      stageEvent("gate", {
        action_type: "remediate.second",
        gate_decision: "deny",
      }),
    );
    const terminal = stageEvent("audit", {
      outcome: "denied",
      decision: "deny",
      mode: "shadow",
    });
    state = applyEvent(state, terminal);
    state = applyEvent(state, terminal);

    const tile = state.tiles.find((candidate) => candidate?.event_id === "evt-live-1");
    expect(tile?.gate_decision).toBe("deny");
    expect(tile?.action_types).toEqual(
      new Set(["remediate.first", "remediate.second"]),
    );
    expect(state.session_total).toBe(1);
    expect(state.gateCounts.deny).toBe(1);
  });

  test("marks only budgeted in-flight work as stuck", () => {
    let state = makeInitialState();
    state = applyEvent(
      state,
      stageEvent("route", { tier: "t2", latency_budget_ms: 5000 }),
    );
    const tile = state.tiles.find((candidate) => candidate?.event_id === "evt-live-1");
    expect(tile).not.toBeNull();
    expect(tile && isTileStuck(tile, tile.first_seen_at + 5001)).toBe(true);
    expect(tile && matchesFilter(tile, "stuck", tile.first_seen_at + 5001)).toBe(true);
  });

  test("does not guess stuck state without an authoritative budget", () => {
    let state = makeInitialState();
    state = applyEvent(state, stageEvent("route", { tier: "t2" }));
    const tile = state.tiles.find((candidate) => candidate?.event_id === "evt-live-1");
    expect(tile).not.toBeNull();
    expect(tile && isTileStuck(tile, tile.first_seen_at + 60_000)).toBe(false);
  });

  test("orders work by attention priority and then newest observation", () => {
    let state = makeInitialState();
    state = applyEvent(state, stageEvent("route", { tier: "t0" }));
    const base = state.tiles.find((candidate) => candidate?.event_id === "evt-live-1");
    expect(base).not.toBeNull();
    if (!base) return;

    const activeOlder = { ...base, event_id: "active-older", last_seen_at: 100 };
    const activeNewer = { ...base, event_id: "active-newer", last_seen_at: 200 };
    const failedOldest = { ...base, event_id: "failed", failed: true, last_seen_at: 50 };

    expect(
      [activeOlder, failedOldest, activeNewer]
        .sort((left, right) => compareLiveTiles(left, right, base.first_seen_at))
        .map((tile) => tile.event_id),
    ).toEqual(["failed", "active-newer", "active-older"]);
  });

  test("recycles completed approvals after the bounded Live retention window", () => {
    let state = makeInitialState();
    for (let index = 0; index < state.tiles.length; index += 1) {
      const event: LiveStageEvent = {
        ...stageEvent("audit", { gate_decision: "hil" }),
        event_id: `evt-hil-${index}`,
        correlation_id: `corr-hil-${index}`,
      };
      state = applyEvent(state, event);
    }

    const oldest = state.tiles.filter((tile) => tile !== null)
      .reduce((minimum, tile) => Math.min(minimum, tile.last_seen_at), Number.POSITIVE_INFINITY);
    expect(pickSlot(state, oldest + HIL_RETENTION_MS + 1)).toBeGreaterThanOrEqual(0);
  });

  test("does not recycle the tile selected for detail inspection", () => {
    let state = makeInitialState();
    for (let index = 0; index < state.tiles.length; index += 1) {
      state = applyEvent(state, {
        ...stageEvent("audit", { decision: "auto", outcome: "executed" }),
        event_id: `evt-complete-${index}`,
        correlation_id: `corr-complete-${index}`,
      });
    }
    const selected = state.tiles.find((tile) => tile !== null);
    expect(selected).not.toBeNull();
    state = { ...state, selectedEventId: selected?.event_id ?? null };

    expect(pickSlot(state, Date.now() + HIL_RETENTION_MS)).not.toBe(
      state.eventIdToSlot.get(selected?.event_id ?? ""),
    );
  });
});
