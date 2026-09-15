import { describe, expect, test } from "vitest";

import { decodeAgentOperationalActivity } from "../agent-operational-activity";
import type { LiveStageEvent } from "../hooks/use-live-stream";
import {
  composeLiveActivityItems,
  liveActivityCounts,
  visibleLiveActivityItems,
} from "./live.activity";
import { applyEvent, makeInitialState } from "./live.model";

function controlEvent(
  gateDecision: "auto" | "hil" = "auto",
): LiveStageEvent {
  return {
    event_id: "event-1",
    correlation_id: "correlation-1",
    stage: "gate",
    phase: "done",
    source: "runtime-observed",
    ts: "2026-09-15T00:00:00Z",
    detail: {
      gate_decision: gateDecision,
      tier: "t0",
    },
  };
}

function sourceActivity() {
  const activity = decodeAgentOperationalActivity({
    type: "agent.operational-activity",
    schema_version: "1.3.0",
    activity_id: "observation:resource-health:campaign-1:completed",
    activity_instance_id: "observation:resource-health:campaign-1",
    idempotency_key: "observation:resource-health:campaign-1:completed",
    kind: "observation",
    status: "completed",
    owner_agent: "Heimdall",
    producer: "observation-campaign-job",
    observation_domain: "resource-health",
    observed_at: "2026-09-15T00:00:02Z",
    source: "resource-health",
    freshness: "fresh",
    evidence_count: 4,
    duration_ms: 2_000,
    correlation_id: "campaign-1",
    reason_codes: [],
    summary_key: "source_observation",
    scope_class: "source-domain",
    target_count: null,
    result_state: "measured",
    result_count: 4,
    result_unit: "records",
    source_cutoff: "2026-09-15T00:00:02Z",
    started_at: "2026-09-15T00:00:00Z",
    completed_at: "2026-09-15T00:00:02Z",
    execution_authority: false,
  });
  if (activity === null) throw new Error("fixture MUST satisfy activity schema");
  return activity;
}

describe("Live unified activity", () => {
  test("orders activity by first observation without moving lifecycle updates", () => {
    const state = applyEvent(
      {
        ...makeInitialState(),
        now: Date.parse("2026-09-15T00:00:01Z"),
      },
      controlEvent(),
    );
    const current = state.tiles.find((item) => item !== null);
    if (current === undefined) throw new Error("control tile MUST exist");
    const tile = {
      ...current,
      first_ts: "2026-09-15T00:00:01Z",
      first_seen_at: Date.parse("2026-09-15T00:00:01Z"),
      last_seen_at: Date.parse("2026-09-15T00:00:01Z"),
    };

    expect(
      composeLiveActivityItems(
        [tile],
        [sourceActivity()],
        "all",
        Date.parse("2026-09-15T00:00:03Z"),
      ).map((item) => item.kind),
    ).toEqual(["control", "source"]);
  });

  test("keeps source and control filters semantically distinct", () => {
    const state = applyEvent(
      {
        ...makeInitialState(),
        now: Date.parse("2026-09-15T00:00:01Z"),
      },
      controlEvent("hil"),
    );
    const tile = state.tiles.find((item) => item !== null);
    if (tile === undefined) throw new Error("control tile MUST exist");
    const observation = sourceActivity();
    const now = Date.parse("2026-09-15T00:00:03Z");

    expect(composeLiveActivityItems([tile], [observation], "source", now))
      .toHaveLength(1);
    expect(composeLiveActivityItems([tile], [observation], "source", now)[0]?.kind)
      .toBe("source");
    expect(composeLiveActivityItems([tile], [observation], "control", now)[0]?.kind)
      .toBe("control");
    expect(composeLiveActivityItems([tile], [observation], "hil", now)[0]?.kind)
      .toBe("control");
    expect(liveActivityCounts([tile], [observation], now)).toMatchObject({
      all: 2,
      control: 1,
      source: 1,
      hil: 1,
    });
  });

  test("uses event time when replay arrives together and preserves order after updates", () => {
    const initial = controlEvent();
    let state = applyEvent(makeInitialState(), {
      ...initial,
      event_id: "older",
      ts: "2026-09-14T23:59:59Z",
    });
    state = applyEvent(state, {
      ...initial,
      event_id: "newer",
      ts: "2026-09-15T00:00:01Z",
    });
    const items = () => composeLiveActivityItems(
      state.tiles.filter((tile) => tile !== null),
      [sourceActivity()],
      "all",
      Date.parse("2026-09-15T00:00:30Z"),
    ).map((item) => item.key);
    const before = items();
    expect(before).toEqual([
      "control:newer",
      `source:${sourceActivity().activity_instance_id}`,
      "control:older",
    ]);
    state = applyEvent(state, {
      ...initial,
      event_id: "older",
      stage: "audit",
      ts: "2026-09-15T00:00:20Z",
    });
    expect(items()).toEqual(before);

    state = applyEvent(state, {
      ...initial,
      event_id: "newest",
      ts: "2026-09-15T00:00:25Z",
    });
    expect(items()).toEqual(["control:newest", ...before]);
  });

  test("limits cards while retaining an explicitly selected item", () => {
    const items = Array.from({ length: 20 }, (_, index) => ({
      kind: "control" as const,
      key: `control:${index}`,
      observedAt: 20 - index,
      tile: {} as never,
    }));

    expect(visibleLiveActivityItems(items, null)).toHaveLength(15);
    expect(visibleLiveActivityItems(items, "control:19")).toHaveLength(15);
    expect(visibleLiveActivityItems(items, "control:19").at(-1)?.key)
      .toBe("control:19");
  });
});
