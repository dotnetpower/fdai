import { describe, expect, it, vi } from "vitest";
import { OperatorApiError } from "../api";
import { decodeAutonomyPayload, decodeDashboardKpi } from "../api-insights";
import {
  autonomyStateForRequest,
  loadAnalyticsData,
  loadAutonomyDataForMode,
  sampleAnalyticsData,
} from "./analytics-data";

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
      autonomy: vi.fn().mockRejectedValue(
        new OperatorApiError(503, "projection unavailable", "projection-unavailable"),
      ),
      panel: vi.fn().mockRejectedValue(
        new OperatorApiError(503, "projection unavailable", "projection-unavailable"),
      ),
    };

    await expect(loadAnalyticsData(client as never, { includeGates: true })).resolves.toEqual({
      kpi: { events_total: 0 },
      autonomy: null,
      gates: null,
    });
  });

  it("builds the deterministic Sample projection with optional assurance gates", () => {
    const data = sampleAnalyticsData(true);

    expect(data.autonomy?.source).toMatchObject({
      name: "sample-preview",
      kind: "synthetic",
    });
    expect(data.gates).not.toBeNull();
    expect(decodeAutonomyPayload({
      schema_version: "1.0.0",
      ...data.autonomy,
    })).toEqual(data.autonomy);
    expect(decodeDashboardKpi(data.kpi)).toEqual(data.kpi);
  });

  it("loads vertical outcome measurements without depending on dashboard KPI", async () => {
    const autonomy = sampleAnalyticsData().autonomy!;
    const client = {
      dashboardMetrics: vi.fn().mockRejectedValue(new Error("KPI unavailable")),
      autonomy: vi.fn().mockResolvedValue(autonomy),
    };

    await expect(loadAutonomyDataForMode("live", client as never)).resolves.toBe(autonomy);
    expect(client.dashboardMetrics).not.toHaveBeenCalled();
    expect(client.autonomy).toHaveBeenCalledOnce();
  });

  it("does not call the Operator API for Sample vertical outcomes", async () => {
    const client = {
      autonomy: vi.fn().mockRejectedValue(new Error("must not be called")),
    };

    await expect(loadAutonomyDataForMode("sample", client as never))
      .resolves.toBe(sampleAnalyticsData().autonomy);
    expect(client.autonomy).not.toHaveBeenCalled();
  });

  it("hides a completed result when the active request identity changes", () => {
    const firstClient = {} as never;
    const nextClient = {} as never;
    const data = sampleAnalyticsData().autonomy;
    const request = {
      client: firstClient,
      dataMode: "sample" as const,
      state: { status: "ready" as const, data },
    };

    expect(autonomyStateForRequest(request, firstClient, "sample")).toBe(request.state);
    expect(autonomyStateForRequest(request, nextClient, "sample")).toEqual({
      status: "loading",
    });
    expect(autonomyStateForRequest(request, firstClient, "live")).toEqual({
      status: "loading",
    });
  });
});
