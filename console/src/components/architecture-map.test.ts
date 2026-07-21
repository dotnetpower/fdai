import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { architectureResourceFromValue } from "./architecture-map";
import {
  architectureZoomScale,
  pickResource,
  project,
  type Camera,
} from "./architecture-map.geometry";
import {
  architectureLabelFontSize,
  fitArchitectureLabel,
} from "./architecture-map-renderer";

const styles = readFileSync(fileURLToPath(new URL("../styles.css", import.meta.url)), "utf8");

describe("architecture resource navigator", () => {
  it("selects only an exact resource id", () => {
    const resources = [
      { id: "Run_A", name: "Worker", type: "compute.vm" },
    ] as never;
    expect(architectureResourceFromValue(resources, "Run_A")).toMatchObject({ id: "Run_A" });
    expect(architectureResourceFromValue(resources, "run-a")).toBeNull();
  });

  it("provides a minimum pointer target and selects the narrowest boundary", () => {
    const camera: Camera = { yaw: 0, pitch: 1.5, scale: 22, panX: 0, panY: 0 };
    const node = { id: "app", name: "App", type: "app-service", status: "healthy", x: 4, y: 4 };
    const outer = { id: "sub", name: "Sub", type: "subscription", status: "healthy", x: 0, y: 0, w: 10, h: 10 };
    const inner = { id: "rg", name: "RG", type: "resource-group", status: "healthy", x: 2, y: 2, w: 4, h: 4 };
    const nodePoint = project(camera, 400, 300, 4, 4, .27);
    expect(pickResource({ resources: [outer, inner, node], links: [] } as never, camera, 400, 300, nodePoint.x + 20, nodePoint.y)).toMatchObject({ id: "app" });
    const boundaryPoint = project(camera, 400, 300, 3, 3, .01);
    expect(pickResource({ resources: [outer, inner], links: [] } as never, camera, 400, 300, boundaryPoint.x, boundaryPoint.y)).toMatchObject({ id: "rg" });
  });
});

describe("architecture map labels", () => {
  it("grows labels with zoom while preserving readable bounds", () => {
    expect(architectureLabelFontSize(22)).toBe(13);
    expect(architectureLabelFontSize(23)).toBeGreaterThan(13);
    expect(architectureLabelFontSize(42)).toBeCloseTo(15.8);
    expect(architectureLabelFontSize(84)).toBe(20);
    expect(architectureLabelFontSize(132)).toBe(20);
  });

  it("keeps the selected label larger", () => {
    expect(architectureLabelFontSize(42, true)).toBeCloseTo(18.2);
    expect(architectureLabelFontSize(84, true)).toBe(22);
  });

  it("fits long labels within the available canvas width", () => {
    const measure = (value: string) => value.length * 8;
    const fitted = fitArchitectureLabel("resource-name-that-does-not-fit", 112, measure);
    expect(fitted).toMatch(/\.\.\.$/);
    expect(measure(fitted)).toBeLessThanOrEqual(112);
    expect(fitArchitectureLabel("short-name", 112, measure)).toBe("short-name");
  });
});

describe("architecture map zoom", () => {
  it("round-trips one zoom step without scale drift", () => {
    const initial = 42;
    expect(architectureZoomScale(architectureZoomScale(initial, "in"), "out"))
      .toBeCloseTo(initial, 10);
  });
});

describe("architecture responsive layout", () => {
  it("uses the page scroll instead of fixed workspace or inspector scroll regions", () => {
    expect(styles).not.toMatch(/\.architecture-workspace\s*\{[^}]*100vh/s);
    expect(styles).not.toMatch(/\.architecture-inspector\s*\{[^}]*max-height/s);
    expect(styles).not.toMatch(/\.architecture-inspector\s*\{[^}]*overflow:\s*auto/s);
  });

  it("keeps the mobile summary compact", () => {
    expect(styles).toMatch(
      /@media \(max-width: 620px\)[\s\S]*?\.architecture-summary\s*\{[^}]*repeat\(2, minmax\(0, 1fr\)\)/,
    );
  });

  it("keeps mobile filters and the resource index free of horizontal scrolling", () => {
    expect(styles).toMatch(
      /@media \(max-width: 620px\)[\s\S]*?\.architecture-layer-bar\s*\{[^}]*display:\s*grid;[^}]*repeat\(3, minmax\(0, 1fr\)\)/,
    );
    expect(styles).toMatch(
      /@media \(max-width: 620px\)[\s\S]*?\.architecture-index-table-wrap\s*\{[^}]*overflow-x:\s*visible/,
    );
    expect(styles).toMatch(
      /@media \(max-width: 620px\)[\s\S]*?\.architecture-index-grid table\s*\{[^}]*table-layout:\s*fixed/,
    );
  });

  it("uses theme-aware 44px zoom controls", () => {
    expect(styles).toMatch(/\.architecture-zoom-controls button\s*\{[^}]*min-height:\s*44px/);
    expect(styles).toMatch(
      /\.architecture-zoom-controls button,[\s\S]*?width:\s*44px;[\s\S]*?background:\s*color-mix\([^;]*var\(--bg-elevated\)/,
    );
  });
});
