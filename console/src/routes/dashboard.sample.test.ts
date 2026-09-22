import { describe, expect, test, vi } from "vitest";
import { loadDashboardOverviewForMode } from "./dashboard.loading";
import { DASHBOARD_SAMPLE_DATA } from "./dashboard.sample";

describe("Dashboard sample mode", () => {
  test("returns the deterministic fixture without calling a live source", async () => {
    const client = {
      dashboardMetrics: vi.fn(),
      costGovernanceAvailability: vi.fn(),
      costGovernance: vi.fn(),
      panel: vi.fn(),
      autonomy: vi.fn(),
    };
    const publishBackbone = vi.fn();

    const result = await loadDashboardOverviewForMode("sample", client, publishBackbone);

    expect(result).toBe(DASHBOARD_SAMPLE_DATA);
    expect(publishBackbone).toHaveBeenCalledWith(DASHBOARD_SAMPLE_DATA);
    expect(client.dashboardMetrics).not.toHaveBeenCalled();
    expect(client.costGovernanceAvailability).not.toHaveBeenCalled();
    expect(client.costGovernance).not.toHaveBeenCalled();
    expect(client.panel).not.toHaveBeenCalled();
    expect(client.autonomy).not.toHaveBeenCalled();
  });

  test("provides a multi-point trend for every Sample operating outcome", () => {
    const autonomy = DASHBOARD_SAMPLE_DATA.autonomy!;
    const trends = {
      auto_resolution_rate: autonomy.success.auto_resolution_rate.value,
      human_touchpoints: autonomy.success.human_touchpoints_per_100.value,
      mttr: autonomy.success.mttr_seconds.value,
      change_lead_time: autonomy.success.change_lead_time_seconds.value,
      cost_per_resolved_event: autonomy.success.cost_per_resolved_event_usd.value,
    };

    for (const [key, current] of Object.entries(trends)) {
      expect(autonomy.trend[key]).toHaveLength(8);
      expect(autonomy.trend[key]?.at(-1)).toBe(current);
    }
  });
});
