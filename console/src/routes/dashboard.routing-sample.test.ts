import { describe, expect, test } from "vitest";
import { decodeDashboardKpi } from "../api-insights";
import { routingSampleParams } from "./dashboard.model";

const kpi = {
  event_count: 500,
  shadow_share: 1,
  enforce_share: 0,
  hil_pending: 2,
  by_action_kind: { "audit.record": 500 },
  by_tier: { t0: 3 },
  by_outcome: { auto: 1, hil: 2 },
  last_recorded_at: "2026-09-12T00:00:00Z",
  audit_sample: { from_seq: 5001, through_seq: 5500, row_count: 500, limit: 500 },
  routing_sample: {
    from_seq: 1, through_seq: 10, row_count: 3, limit: 500,
    action_kind: "measurement.control_loop.v1", window_days: 30,
  },
};

describe("canonical routing sample", () => {
  test("keeps decision evidence separate from the general audit sample", () => {
    const decoded = decodeDashboardKpi(kpi);
    expect(decoded.event_count).toBe(500);
    expect(decoded.routing_sample?.row_count).toBe(3);
    expect(routingSampleParams(decoded)).toEqual({
      from_seq: 1, through_seq: 10, action: "measurement.control_loop.v1", window: "30d",
    });
  });

  test("keeps legacy producers compatible without inventing another sample", () => {
    const { routing_sample: _routing, ...legacy } = kpi;
    const decoded = decodeDashboardKpi(legacy);
    expect(decoded.routing_sample).toBeUndefined();
    expect(routingSampleParams(decoded)).toEqual({ from_seq: 5001, through_seq: 5500 });
  });

  test("retains the canonical filter when a measured decision sample is empty", () => {
    const decoded = decodeDashboardKpi({
      ...kpi,
      by_tier: {},
      by_outcome: {},
      routing_sample: { ...kpi.routing_sample, from_seq: null, through_seq: null, row_count: 0 },
    });
    expect(routingSampleParams(decoded)).toEqual({
      action: "measurement.control_loop.v1", window: "30d",
    });
  });

  test.each([
    { action_kind: "audit.record" },
    { window_days: 0 },
    { row_count: 501 },
    { from_seq: null },
    { through_seq: 0 },
  ])("rejects inconsistent source metadata: %j", (invalid) => {
    expect(() => decodeDashboardKpi({
      ...kpi, routing_sample: { ...kpi.routing_sample, ...invalid },
    })).toThrow();
  });

  test("rejects distributions that contradict the canonical sample", () => {
    expect(() => decodeDashboardKpi({ ...kpi, by_outcome: { auto: 500 } })).toThrow();
    expect(() => decodeDashboardKpi({ ...kpi, by_tier: { t0: -1 } })).toThrow();
    expect(() => decodeDashboardKpi({ ...kpi, by_tier: { t0: 4 } })).toThrow();
  });
});
