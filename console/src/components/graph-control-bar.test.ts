import { describe, expect, test, vi } from "vitest";
import { GraphControlBar, GraphLegendSwatch } from "./graph-control-bar";

describe("GraphControlBar", () => {
  test("GraphLegendSwatch renders inline SVG markers instead of CSS border lines", () => {
    const arrow = JSON.stringify(GraphLegendSwatch({ kind: "arrow", stroke: "#637c93" }));
    const thick = JSON.stringify(GraphLegendSwatch({ kind: "thick", stroke: "var(--accent)" }));
    const dotted = JSON.stringify(GraphLegendSwatch({ kind: "dotted", stroke: "#4f7a69" }));
    const doubleLine = JSON.stringify(GraphLegendSwatch({ kind: "double", stroke: "#315f82" }));

    expect(arrow).toContain("svg");
    expect(arrow).toContain("path");
    expect(thick).toContain("3.5");
    expect(dotted).toContain("1.8 2.5");
    expect(doubleLine).toContain("y1\":\"4");
    expect(doubleLine).toContain("y1\":\"8");
  });

  test("renders zoom percentage, fit, fullscreen, inspector, and legend items", () => {
    const onZoomIn = vi.fn();
    const onZoomOut = vi.fn();
    const onFit = vi.fn();
    const onToggleFullscreen = vi.fn();
    const onToggleInspector = vi.fn();

    const vnode = GraphControlBar({
      ariaLabel: "Graph controls",
      scale: 0.75,
      minScale: 0.5,
      maxScale: 2,
      onZoomOut,
      onZoomIn,
      onFit,
      fitLabel: "Fit",
      fullscreen: false,
      onToggleFullscreen,
      inspectorOpen: true,
      onToggleInspector,
      legendItems: [
        { id: "traffic", label: "Traffic path", kind: "thick", stroke: "var(--accent)", count: "4/4" },
      ],
    });

    const rendered = JSON.stringify(vnode);
    expect(rendered).toContain("75%");
    expect(rendered).toContain("Fit");
    expect(rendered).toContain("Traffic path");
    expect(rendered).toContain("4/4");
  });
});
