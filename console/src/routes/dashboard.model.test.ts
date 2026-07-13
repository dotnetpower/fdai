import { describe, expect, test } from "vitest";
import type { DashboardKpi } from "../types";
import { overviewHealth } from "./dashboard.model";

const KPI: DashboardKpi = {
  event_count: 10,
  shadow_share: 0.95,
  enforce_share: 0.05,
  hil_pending: 0,
  by_action_kind: {},
  by_outcome: {},
  by_tier: {},
  last_recorded_at: null,
};

const AUTONOMY = {
  guards: [{ key: "escape", value: 0, baseline: 0, threshold: 0, ok: true }],
};

describe("overview health", () => {
  test("is healthy only when all required guard evidence passes", () => {
    expect(overviewHealth(KPI, 0, AUTONOMY)).toBe("healthy");
  });

  test("reports attention for any known failed guard", () => {
    expect(overviewHealth(KPI, 0, { ...AUTONOMY, guards: [{ ...AUTONOMY.guards[0]!, ok: false }] })).toBe("attention");
    expect(overviewHealth({ ...KPI, hil_pending: 1 }, 0, AUTONOMY)).toBe("attention");
  });

  test("reports unknown when required guard evidence is absent", () => {
    expect(overviewHealth(KPI, null, AUTONOMY)).toBe("unknown");
    expect(overviewHealth(KPI, 0, null)).toBe("unknown");
  });
});