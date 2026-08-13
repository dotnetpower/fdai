import { describe, expect, it, vi } from "vitest";
import { OperatorApiError } from "../api";
import { loadAnalyticsData } from "./analytics-data";

describe("analytics source isolation", () => {
  it("does not request promotion gates for hubs that do not consume them", async () => {
    const client = {
      dashboardMetrics: vi.fn().mockResolvedValue({ events_total: 0 }),
      autonomy: vi.fn().mockResolvedValue({ source: "measurement" }),
      panel: vi.fn().mockRejectedValue(new Error("gates unavailable")),
    };

    const data = await loadAnalyticsData(client as never);

    expect(data.gates).toBeNull();
    expect(client.panel).not.toHaveBeenCalled();
  });

  it("keeps the KPI backbone when optional assurance projections are unavailable", async () => {
    const client = {
      dashboardMetrics: vi.fn().mockResolvedValue({ events_total: 0 }),
      autonomy: vi.fn().mockRejectedValue(new OperatorApiError(503, "projection unavailable")),
      panel: vi.fn().mockRejectedValue(new OperatorApiError(503, "projection unavailable")),
    };

    await expect(loadAnalyticsData(client as never, { includeGates: true })).resolves.toEqual({
      kpi: { events_total: 0 },
      autonomy: null,
      gates: null,
    });
  });
});
