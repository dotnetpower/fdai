import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, test } from "vitest";

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
    expect(executive).toContain('<a href={href} class="card overview-metric overview-drill-card">');
    expect(dashboard.match(/class="overview-unavailable-link"/g)?.length).toBeGreaterThanOrEqual(3);
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
});
