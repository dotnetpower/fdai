import { describe, expect, test, vi } from "vitest";
import {
  activateTabByKey,
  barWidthPercent,
  MAX_WIDGET_RENDER_DEPTH,
  nextTabIndex,
  numericBarValue,
  SUPPORTED_REPORT_WIDGET_TYPES,
} from "./process-view-renderer";
import {
  BLOCKED_REPORT_WIDGET_TYPES,
  UPSTREAM_REPORT_WIDGET_TYPES,
  missingWidgetTypes,
} from "./process-view-widget-contract";
import {
  boundedRatio,
  normalizedPointPositions,
  percent,
} from "./process-view-widget-utils";
import { flattenFlameFrames } from "./process-view-widgets.flows";
import { formatCurrency } from "./process-view-widgets.summaries";
import { safeRasterImageSrc } from "./process-view-widgets.content";

describe("report widget registry", () => {
  test("covers every widget type used by the shipped reports", () => {
    expect(SUPPORTED_REPORT_WIDGET_TYPES).toEqual(new Set([
      "query_value",
      "bar_chart",
      "timeseries",
      "top_list",
      "table",
      "list_stream",
      "check_status",
      "topology_map",
      "group",
      "tabs",
      "change",
      "distribution",
      "heatmap",
      "pie_chart",
      "scatter_plot",
      "sparkline",
      "gauge",
      "progress_bar",
      "funnel",
      "sankey",
      "treemap",
      "retention",
      "flame_graph",
      "split_graph",
      "alert_status",
      "event_stream",
      "slo_summary",
      "service_summary",
      "cost_summary",
      "budget_summary",
      "free_text",
      "note",
      "image",
      "hostmap",
      "geomap",
      "process_steps",
      "comparison",
    ]));
  });

  test("accounts for every upstream backend widget type", () => {
    expect(UPSTREAM_REPORT_WIDGET_TYPES).toHaveLength(38);
    expect(BLOCKED_REPORT_WIDGET_TYPES).toEqual(new Set(["iframe"]));
    expect(missingWidgetTypes(SUPPORTED_REPORT_WIDGET_TYPES)).toEqual([]);
  });

  test("implements wrapping tab keyboard navigation", () => {
    expect(MAX_WIDGET_RENDER_DEPTH).toBe(8);
    expect(nextTabIndex(0, "ArrowRight", 3)).toBe(1);
    expect(nextTabIndex(2, "ArrowRight", 3)).toBe(0);
    expect(nextTabIndex(0, "ArrowLeft", 3)).toBe(2);
    expect(nextTabIndex(1, "Home", 3)).toBe(0);
    expect(nextTabIndex(1, "End", 3)).toBe(2);
    expect(nextTabIndex(1, "Enter", 3)).toBe(1);
  });

  test("moves DOM focus with roving tab selection", () => {
    const focus = vi.fn();
    expect(activateTabByKey(0, "ArrowRight", 3, focus)).toBe(1);
    expect(focus).toHaveBeenCalledWith(1);
  });

  test("does not fabricate a positive bar for zero or missing values", () => {
    expect(numericBarValue(undefined)).toBeNull();
    expect(barWidthPercent(null, 10)).toBe(0);
    expect(barWidthPercent(0, 10)).toBe(0);
    expect(barWidthPercent(5, 10)).toBe(50);
  });

  test("clamps visual ratios and normalizes scatter coordinates", () => {
    expect(boundedRatio(-1)).toBe(0);
    expect(boundedRatio(1.4)).toBe(1);
    expect(boundedRatio(Number.NaN)).toBeNull();
    expect(percent(0.125)).toBe("12.5%");
    const points = normalizedPointPositions([
      { x: 10, y: 20 },
      { x: 20, y: 40 },
      { x: "invalid", y: 30 },
    ]);
    expect(points).toHaveLength(2);
    expect(points[0]).toMatchObject({ x: 8, y: 88 });
    expect(points[1]).toMatchObject({ x: 312, y: 8 });
  });

  test("bounds flame graph depth and frame count", () => {
    const root = { name: "root", value: 10, children: [] as unknown[] };
    let cursor = root;
    for (let index = 0; index < 20; index += 1) {
      const child = { name: `child-${index}`, value: 9 - index, children: [] as unknown[] };
      cursor.children.push(child);
      cursor = child;
    }
    const frames = flattenFlameFrames([root], 4, 5);
    expect(frames).toHaveLength(5);
    expect(frames.at(-1)?.depth).toBe(4);
  });

  test("formats finite costs and rejects malformed currency codes", () => {
    expect(formatCurrency(undefined, "USD")).toBe("-");
    expect(formatCurrency(12.5, "not-a-code")).toContain("12.50");
    expect(formatCurrency(12.5, "USD")).toContain("12.50");
  });

  test("allows raster images but blocks executable or credentialed sources", () => {
    expect(safeRasterImageSrc("/evidence/chart.webp")).toBe("/evidence/chart.webp");
    expect(safeRasterImageSrc("https://example.com/chart.png")).toBe("https://example.com/chart.png");
    expect(safeRasterImageSrc("https://user:secret@example.com/chart.png")).toBeNull();
    expect(safeRasterImageSrc("javascript:alert(1).png")).toBeNull();
    expect(safeRasterImageSrc("https://example.com/chart.svg")).toBeNull();
  });
});
