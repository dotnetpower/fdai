import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import type { PresentationBlock } from "../backend-types";
import { comparisonTrackStyle, timeSeriesStyle } from "./charts";
import { presentationModuleRegistration } from "./registry";

const kinds: PresentationBlock["kind"][] = [
  "summary",
  "callout",
  "table",
  "threshold_table",
  "list",
  "coverage",
  "bar",
  "time_series",
  "comparison",
  "scatter",
  "heatmap",
  "timeline",
  "evidence",
];

describe("presentation module registry", () => {
  it("registers one responsive and accessible module for every closed block kind", () => {
    for (const kind of kinds) {
      const registered = presentationModuleRegistration(kind);
      expect(registered.component).toBeTypeOf("function");
      expect(["reflow", "scroll", "stack"]).toContain(registered.responsivePolicy);
      expect(["description-list", "exact-table", "ordered-list"])
        .toContain(registered.accessibilityFallback);
    }
  });

  it("keeps the shell kind-neutral and pins chart accessibility CSS", () => {
    const shell = readFileSync(
      fileURLToPath(new URL("../structured-reply.tsx", import.meta.url)),
      "utf8",
    );
    const css = readFileSync(
      fileURLToPath(new URL("../structured-reply.css", import.meta.url)),
      "utf8",
    );
    const chartCss = readFileSync(
      fileURLToPath(new URL("../../components/charts.css", import.meta.url)),
      "utf8",
    );
    const value = readFileSync(
      fileURLToPath(new URL("./value.tsx", import.meta.url)),
      "utf8",
    );

    expect(shell).toContain("PresentationModuleView");
    expect(shell).not.toMatch(/block\.kind\s*===/);
    // Exact values and collapsed blocks open as the conversation layer's quiet disclosure, which
    // keeps a visible focus ring and a 44px touch target on narrow screens.
    const charts = readFileSync(fileURLToPath(new URL("./charts.tsx", import.meta.url)), "utf8");
    const layer = readFileSync(
      fileURLToPath(new URL("../../../../ui/calm-slate-deck-conversation.css", import.meta.url)),
      "utf8",
    );
    expect(charts).toContain('<details class="deck-presentation-exact-values cs-deck-disclosure">');
    expect(shell).toContain('class="deck-presentation-block is-collapsible cs-deck-disclosure"');
    expect(layer).toMatch(/\.cs-deck-disclosure-summary:focus-visible \{[^}]*outline: 2px solid var\(--cs-steel\);/s);
    expect(layer).toMatch(/@media \(max-width: 640px\) \{\s*:is\([^)]*\.cs-deck-disclosure-summary\) \{\s*min-height: 44px;/);
    expect(chartCss).toContain(".fd-chart-point:focus-visible");
    expect(chartCss).toContain(".fd-bar-track:focus-visible");
    expect(css).toContain(".deck-presentation-comparison-track:focus-visible");
    expect(css).toContain("@media (prefers-reduced-motion: reduce)");
    expect(value).toContain("isOpaqueIdentifierField(columnKey, label)");
    expect(value).toContain('class="deck-presentation-identifier"');
    expect(css).toMatch(/\.deck-presentation-identifier \{[^}]*text-overflow: ellipsis;[^}]*white-space: nowrap;/s);
    expect(css).toContain(".deck-presentation-table td > .tooltip-anchor:focus-within");
  });

  it("keeps every ordered time-series point on one explicit grid axis", () => {
    expect(timeSeriesStyle(7)).toEqual({ "--series-count": 7 });
  });

  it("preserves comparison direction around a shared zero baseline", () => {
    expect(comparisonTrackStyle([-20, 40], -20)).toEqual({
      "--comparison-zero": "33.33333333333333%",
      "--comparison-start": "0%",
      "--comparison-width": "33.33333333333333%",
    });
    expect(comparisonTrackStyle([-20, 40], 40)).toEqual({
      "--comparison-zero": "33.33333333333333%",
      "--comparison-start": "33.33333333333333%",
      "--comparison-width": "66.66666666666667%",
    });
  });
});
