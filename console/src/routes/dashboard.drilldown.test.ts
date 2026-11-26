import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, test } from "vitest";
import { buildDashboardTelemetry } from "./dashboard";
import { DASHBOARD_SAMPLE_DATA } from "./dashboard.sample";

function source(name: string): string {
  return readFileSync(fileURLToPath(new URL(name, import.meta.url)), "utf8");
}

describe("Dashboard drill-down contract", () => {
  test("links posture, evidence metadata, outcomes, and unavailable states", () => {
    const executive = source("./dashboard.executive.tsx");
    const dashboard = source("./dashboard.tsx");

    expect(executive).toContain('class="overview-status-primary"');
    expect(executive).toContain("<EvidenceLink");
    expect(executive).toContain('class="overview-trend-link"');
    expect(executive).toContain('unavailable ? "is-unavailable" : ""');
    expect(executive).toContain("href={href}");
    expect(dashboard.match(/class="overview-unavailable-link"/g)?.length).toBeGreaterThanOrEqual(2);
    const posture = source("./dashboard.posture.tsx");
    expect(posture).toContain('segments: ["auto-resolution"]');
    expect(posture).toContain('mode: "shadow"');
    expect(posture).toContain('routeHref("promotion-gates")');
    expect(posture).toContain("sample.row_count");
    expect(posture).toContain("value === null");
  });

  test("keeps essential KPI + live timeline primary and detailed evidence behind disclosure", () => {
    const dashboard = source("./dashboard.tsx");
    const kpiIndex = dashboard.indexOf('class="overview-kpi-grid"');
    const timelineIndex = dashboard.indexOf("<LiveScatterTimeline");
    const detailsIndex = dashboard.indexOf('<details class="advanced-details overview-details">');
    expect(kpiIndex).toBeGreaterThan(0);
    expect(timelineIndex).toBeGreaterThan(kpiIndex);
    expect(detailsIndex).toBeGreaterThan(timelineIndex);
    const positions = ["attention", "posture", "routing", "outcomes"]
      .map((id) => dashboard.indexOf(`id="${id}"`));
    expect(positions.every((position) => position > detailsIndex)).toBe(true);
    expect(positions).toEqual([...positions].sort((a, b) => a - b));
    expect(detailsIndex).toBeLessThan(dashboard.indexOf("<ExecutiveStatus"));
    expect(dashboard).not.toContain("overview-section-number");
    expect(source("./dashboard.skeleton.tsx")).toContain('layout="metrics" blocks={4}');
  });

  test("uses the header action as the resource dashboard navigation path", () => {
    const dashboard = source("./dashboard.tsx");

    expect(dashboard).toContain('class="cs-control-button overview-resource-dashboard-link"');
    expect(dashboard).toContain('href={resourceDashboardHref(dataMode)}');
    expect(dashboard).toContain('routeHref("dashboard-v2"');
    expect(dashboard).toContain("<ResourceDashboardIcon />");
  });

  test("links distribution headers, bar segments, legends, and attention cards", () => {
    const distributions = source("./dashboard.distributions.tsx");

    expect(distributions).toContain('<a class="overview-distribution-head"');
    expect(distributions).toContain('class={`overview-distribution-segment tone-${toneFor(row)}`}');
    expect(distributions).toContain("<a key={row.key} href={hrefFor(row)}>");
    expect(distributions).toContain('<a class="overview-attention-card" href={href}>');
  });

  test("links verticals, rule provenance, rule counts, and collapsed audit counts", () => {
    const signals = source("./dashboard.signals.tsx");
    const dashboard = source("./dashboard.tsx");

    expect(signals).toContain('class={`card overview-vertical overview-vertical-${vertical.key} overview-drill-card`}');
    expect(signals).toContain('<a class="overview-rules-provenance"');
    expect(signals.match(/<a class="overview-rules-stat/g)?.length).toBe(3);
    expect(dashboard).toContain("[filterKey]: r.key");
    expect(dashboard.match(/<a href=\{routeHref\("audit"/g)?.length).toBeGreaterThanOrEqual(2);
  });

  test("derives telemetry buckets, domain rows, and prioritized ticker state honestly", () => {
    const sampleTelemetry = buildDashboardTelemetry(
      DASHBOARD_SAMPLE_DATA.kpi,
      DASHBOARD_SAMPLE_DATA.autonomy,
      DASHBOARD_SAMPLE_DATA.gates,
      0,
    );
    expect(sampleTelemetry.buckets.length).toBeGreaterThan(0);
    expect(sampleTelemetry.points.length).toBe(sampleTelemetry.buckets.length);
    expect(sampleTelemetry.domains.map((row) => row.id)).toEqual([
      "resilience",
      "change_safety",
      "cost",
      "unattributed",
    ]);
    expect(sampleTelemetry.tickerCategory).toBe("human");

    const escapedTelemetry = buildDashboardTelemetry(
      DASHBOARD_SAMPLE_DATA.kpi,
      DASHBOARD_SAMPLE_DATA.autonomy,
      DASHBOARD_SAMPLE_DATA.gates,
      2,
    );
    expect(escapedTelemetry.tickerCategory).toBe("sec");
    expect(escapedTelemetry.signals.some((item) => item.id === "sig-escapes")).toBe(true);

    const liveOutcomeTelemetry = buildDashboardTelemetry(
      {
        ...DASHBOARD_SAMPLE_DATA.kpi,
        event_count: 74450,
        hil_pending: 481,
        by_outcome: {
          shadow: 68168,
          started: 2865,
          completed: 1805,
          degraded: 1059,
          retained: 553,
        },
      },
      null,
      null,
      null,
    );
    expect(liveOutcomeTelemetry.totals.auto).toBe(68168 + 2865 + 1805);
    expect(liveOutcomeTelemetry.totals.sre).toBe(1059 + 553);
    expect(liveOutcomeTelemetry.points.some((pt) => pt.category === "sre")).toBe(true);
    expect(liveOutcomeTelemetry.points.some((pt) => pt.category === "auto")).toBe(true);

    const emptyTelemetry = buildDashboardTelemetry(
      {
        ...DASHBOARD_SAMPLE_DATA.kpi,
        event_count: 0,
        hil_pending: 0,
        by_outcome: {},
        by_action_kind: {},
        by_tier: {},
        last_recorded_at: null,
        audit_sample: null,
      },
      null,
      null,
      null,
    );
    expect(emptyTelemetry.buckets).toEqual([]);
    expect(emptyTelemetry.points).toEqual([]);
    expect(emptyTelemetry.domains).toEqual([]);
    expect(emptyTelemetry.signals).toEqual([]);
    expect(emptyTelemetry.tickerTime).toBe("-");
  });
});
