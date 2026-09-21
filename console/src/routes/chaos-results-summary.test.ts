import { describe, expect, test, vi } from "vitest";

import type { RenderedReportView } from "./reporting.model";
import {
  decodeChaosResultSummary,
  loadChaosResultSummary,
} from "./chaos-results-summary";

function report(): RenderedReportView {
  const rows = [
    { outcome: "validated", detected: true, reverted: true },
    { outcome: "not_detected", detected: false, reverted: false },
  ];
  return {
    id: "chaos-enforce-results",
    version: "1.0.0",
    name: "Chaos Enforce Results",
    description: "Measured outcomes",
    generated_at: "2026-09-21T12:30:00+00:00",
    time_range: {},
    variables: { window_days: "30" },
    tags: ["measured"],
    provenance: {
      availability: "available",
      synthetic: false,
      sources: [{
        datasource: "chaos_results",
        source: "operator_chaos_report_signal",
        availability: "available",
        synthetic: false,
        as_of: "2026-09-21T12:12:11+00:00",
      }],
    },
    widgets: [
      valueWidget("experiments", 2),
      valueWidget("validated", 1),
      valueWidget("detection-gaps", 1),
      valueWidget("rollback-failures", 0),
      {
        id: "experiment-results",
        type: "table",
        title: "Results",
        data: { rows, total_rows: rows.length },
        options: {},
      },
    ],
  };
}

function valueWidget(id: string, value: number) {
  return {
    id,
    type: "query_value",
    title: id,
    data: { value, unit: "runs" },
    options: {},
  };
}

describe("chaos result summary", () => {
  test("decodes reconciled measured report evidence", () => {
    expect(decodeChaosResultSummary(report())).toEqual({
      experiments: 2,
      validated: 1,
      detectionGaps: 1,
      rollbackFailures: 0,
      detected: 1,
      reverted: 1,
      source: "operator_chaos_report_signal",
      asOf: "2026-09-21T12:12:11+00:00",
    });
  });

  test("rejects synthetic or unreconciled report evidence", () => {
    expect(() => decodeChaosResultSummary({
      ...report(),
      provenance: { ...report().provenance, synthetic: true },
    })).toThrow(/provenance/);

    const source = report();
    const malformed = {
      ...source,
      widgets: source.widgets.map((widget, index) => index === 0
        ? { ...widget, data: { ...widget.data, value: 3 } }
        : widget),
    };
    expect(() => decodeChaosResultSummary(malformed)).toThrow(/totals do not reconcile/);
  });

  test("loads the bounded 30 day report through the reporting client", async () => {
    const renderReport = vi.fn().mockResolvedValue(report());

    await expect(loadChaosResultSummary({ renderReport })).resolves.toEqual({
      status: "ready",
      data: expect.objectContaining({ experiments: 2, detectionGaps: 1 }),
    });
    expect(renderReport).toHaveBeenCalledWith(
      "chaos-enforce-results",
      { window_days: "30" },
    );
  });

  test("keeps unexpected report failures distinct from unavailable evidence", async () => {
    const renderReport = vi.fn().mockRejectedValue(new Error("report transport failed"));

    await expect(loadChaosResultSummary({ renderReport })).resolves.toEqual({
      status: "error",
      message: "report transport failed",
    });
  });
});
