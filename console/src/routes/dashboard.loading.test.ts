import { describe, expect, it, vi } from "vitest";
import { OperatorApiError } from "../api";
import type { DashboardKpi } from "../types";
import { loadDashboardOverview } from "./dashboard.loading";

const KPI: DashboardKpi = {
  event_count: 10,
  shadow_share: 0.95,
  enforce_share: 0.05,
  hil_pending: 0,
  by_action_kind: {},
  by_outcome: {},
  by_tier: {},
  last_recorded_at: null,
  audit_sample: null,
};

describe("loadDashboardOverview", () => {
  it("publishes the KPI backbone before optional projections settle", async () => {
    const pending = new Promise<never>(() => undefined);
    const publishBackbone = vi.fn();
    const panelCall = vi.fn();
    const client = {
      dashboardMetrics: vi.fn(async () => KPI),
      finops: vi.fn(() => pending),
      panel<T>(path: string): Promise<T> {
        panelCall(path);
        return pending;
      },
      autonomy: vi.fn(() => pending),
    };

    void loadDashboardOverview(client, publishBackbone);

    await vi.waitFor(() => {
      expect(publishBackbone).toHaveBeenCalledWith({
        kpi: KPI,
        finops: null,
        gates: null,
        autonomy: null,
      });
    });
    expect(client.finops).toHaveBeenCalledOnce();
    expect(panelCall).toHaveBeenCalledOnce();
    expect(client.autonomy).toHaveBeenCalledOnce();
  });

  it("keeps the KPI backbone when the source registry refuses an unserved route", async () => {
    // The registry reports an unavailable source as 503 before any request is
    // sent, so every optional overview projection must tolerate that status.
    const publishBackbone = vi.fn();
    const client = {
      dashboardMetrics: vi.fn(async () => KPI),
      finops: vi.fn(async () => { throw new OperatorApiError(503, "not served here"); }),
      panel: vi.fn(async () => { throw new OperatorApiError(503, "not served here"); }),
      autonomy: vi.fn(async () => { throw new OperatorApiError(503, "not served here"); }),
    };

    await expect(loadDashboardOverview(client, publishBackbone)).resolves.toEqual({
      kpi: KPI,
      finops: null,
      gates: null,
      autonomy: null,
    });
  });

  it("keeps the KPI backbone when the optional promotion projection is unavailable", async () => {
    const publishBackbone = vi.fn();
    const client = {
      dashboardMetrics: vi.fn(async () => KPI),
      finops: vi.fn(async () => { throw new OperatorApiError(404, "not found"); }),
      panel: vi.fn(async () => { throw new OperatorApiError(503, "unavailable"); }),
      autonomy: vi.fn(async () => { throw new OperatorApiError(404, "not found"); }),
    };

    await expect(loadDashboardOverview(client, publishBackbone)).resolves.toEqual({
      kpi: KPI,
      finops: null,
      gates: null,
      autonomy: null,
    });
  });
});
