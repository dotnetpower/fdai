import { afterEach, describe, expect, test } from "vitest";
import { setLocale } from "../i18n";
import type { LiveStageEvent } from "../hooks/use-live-stream";
import {
  observationReasonLabel,
  observationReasonSummary,
  tileEffectLabel,
  tileReasonLabel,
  tileScopeLabel,
} from "./live.absence";
import { applyEvent, makeInitialState, type TileState } from "./live.model";

function stage(
  name: LiveStageEvent["stage"],
  phase: LiveStageEvent["phase"],
  detail: Record<string, unknown> = {},
): LiveStageEvent {
  return {
    event_id: "evt-absence",
    correlation_id: "corr-absence",
    stage: name,
    phase,
    source: "runtime-observed",
    ts: "2026-07-15T00:00:00.000Z",
    detail,
    ...(phase === "failed" ? { error: "execution_failed" } : {}),
  };
}

function tile(...events: LiveStageEvent[]): TileState {
  let state = makeInitialState(2);
  for (const event of events) state = applyEvent(state, event);
  const found = state.tiles.find((item) => item?.event_id === "evt-absence");
  if (!found) throw new Error("tile was not created");
  return found;
}

afterEach(() => setLocale("en"));

describe("cause-specific text for absent Live values", () => {
  test("keeps a reported reason and scope unchanged", () => {
    const reported = tile(stage("gate", "done", { reason: "Policy needs review", scope: "prod" }));
    expect(tileReasonLabel(reported)).toBe("Policy needs review");
    expect(tileScopeLabel(reported)).toBe("prod");
  });

  test("distinguishes an unfinished, a finished and a failed item without a reason", () => {
    const pending = tile(stage("route", "done", { tier: "t0" }));
    const completed = tile(stage("audit", "done", { mode: "shadow" }));
    const failed = tile(stage("execute", "failed"));
    expect(tileReasonLabel(pending)).toBe("Not recorded yet");
    expect(tileReasonLabel(completed)).toBe("No reason was reported with this decision");
    expect(tileReasonLabel(failed)).toBe("Failed - no reason was reported");
    expect(new Set([pending, completed, failed].map(tileReasonLabel)).size).toBe(3);
  });

  test("never presents a missing field as the generic not-observed label", () => {
    const completed = tile(stage("audit", "done", { mode: "shadow" }));
    expect(tileScopeLabel(completed)).toBe("Scope not reported by this event");
    expect(tileEffectLabel(completed, null)).toBe("Not applied - shadow mode records only");
    expect(tileEffectLabel(tile(stage("route", "done")), null)).toBe("Pending");
  });

  test("renders Korean copy for the same causes", () => {
    setLocale("ko");
    const completed = tile(stage("audit", "done", { mode: "shadow" }));
    expect(tileReasonLabel(completed)).toBe("이 결정과 함께 보고된 사유 없음");
    expect(tileScopeLabel(completed)).toBe("이 이벤트가 범위를 보고하지 않음");
  });

  test("labels known source reason codes and keeps an unknown code visible", () => {
    expect(observationReasonLabel("source_timeout")).toBe("Source read timed out");
    expect(observationReasonLabel("source_stale")).toBe("Source data is older than its freshness limit");
    expect(observationReasonLabel("brand_new_code")).toBe("brand_new_code");
    expect(observationReasonSummary([])).toBe("");
    expect(observationReasonSummary(["source_timeout"])).toBe("Source read timed out");
    expect(observationReasonSummary(["source_timeout", "source_stale", "x"])).toBe(
      "Source read timed out (+2 more)",
    );
    setLocale("ko");
    expect(observationReasonSummary(["source_timeout", "source_stale"])).toBe(
      "소스 읽기 시간 초과 외 1건",
    );
  });
});
