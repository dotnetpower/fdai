import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { architectureResourceFromValue } from "./architecture-map";
import { geometryOf } from "./architecture-map.model";
import {
  architectureCanvasHeight,
  architectureLegendReserveWidth,
  architectureZoomScale,
  architectureWorldSize,
  fitCamera,
  pickResource,
  project,
  type Camera,
} from "./architecture-map.geometry";
import {
  architectureLinkIsDrawable,
  architectureLinkElevation,
  architectureOverlayOrder,
  architectureFloorLegendEntries,
  architectureFloorLegendFontSize,
  architectureLabelFontSize,
  fitArchitectureLabel,
} from "./architecture-map-renderer";
import {
  architectureInteractionOptions,
  architectureLayoutFrame,
} from "./use-architecture-map-controller";

const styles = readFileSync(fileURLToPath(new URL("../styles.css", import.meta.url)), "utf8");
const overviewPanelSource = readFileSync(
  fileURLToPath(new URL("./architecture-overview-panel.tsx", import.meta.url)),
  "utf8",
);

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

  it("paints the selected label after every other node overlay", () => {
    const nodes = [
      { id: "selected", type: "compute.vm" },
      { id: "neighbor", type: "disk" },
      { id: "other", type: "postgresql-server" },
    ] as never;
    expect(architectureOverlayOrder(nodes, "selected").map((node) => node.id))
      .toEqual(["neighbor", "other", "selected"]);
  });
});

describe("architecture resource legend", () => {
  it("keeps the floating panel free of metrics, descriptions, and layer filters", () => {
    expect(overviewPanelSource).not.toMatch(
      /architecture-(?:provenance|summary|layer-bar|filter-summary)/,
    );
    expect(overviewPanelSource).not.toMatch(/entry\.(?:count|types)/);
  });

  it("groups present resources into simple visual tokens", () => {
    const entries = architectureFloorLegendEntries([
      { id: "vm", type: "compute.vm" },
      { id: "db-1", type: "postgresql" },
      { id: "db-2", type: "postgresql-server" },
    ] as never);

    expect(entries).toEqual(["database", "virtual-machine"]);
  });

  it("scales floor legend text with camera zoom inside readable bounds", () => {
    expect(architectureFloorLegendFontSize(18)).toBe(8);
    expect(architectureFloorLegendFontSize(42)).toBeCloseTo(10.4);
    expect(architectureFloorLegendFontSize(132)).toBe(12);
  });
});

describe("architecture map zoom", () => {
  it("round-trips one zoom step without scale drift", () => {
    const initial = 42;
    expect(architectureZoomScale(architectureZoomScale(initial, "in"), "out"))
      .toBeCloseTo(initial, 10);
  });
});

describe("architecture floor legend space", () => {
  it("reserves a bounded right-side floor area at desktop and mobile widths", () => {
    expect(architectureLegendReserveWidth(1200)).toBe(312);
    expect(architectureLegendReserveWidth(700)).toBe(240);
    expect(architectureLegendReserveWidth(390)).toBeCloseTo(132.6);
    expect(architectureLegendReserveWidth(200)).toBe(96);
  });
});

describe("architecture selection camera", () => {
  it("keeps the camera frame when selection reveals resources inside the same regions", () => {
    const region = {
      id: "rg", type: "resource-group", name: "rg", status: "healthy",
      x: 0, y: 0, w: 8, h: 8,
    };
    const overview = {
      resources: [region, { id: "vm", type: "compute.vm", x: 2, y: 2 }],
    } as never;
    const selected = {
      resources: [
        region,
        { id: "vm", type: "compute.vm", x: 2, y: 2 },
        { id: "nic", type: "network.interface", x: 3, y: 2 },
      ],
    } as never;

    expect(architectureLayoutFrame(selected)).toBe(architectureLayoutFrame(overview));
  });

  it("changes the camera frame when the owning region geometry changes", () => {
    const graph = (width: number) => ({
      resources: [{
        id: "rg", type: "resource-group", name: "rg", status: "healthy",
        x: 0, y: 0, w: width, h: 8,
      }],
    }) as never;

    expect(architectureLayoutFrame(graph(12))).not.toBe(architectureLayoutFrame(graph(8)));
  });
});

describe("architecture drag rendering", () => {
  it("keeps blocks and connections while deferring expensive reflections and labels", () => {
    const options = {
      showConnections: true,
      showReflections: true,
      showLabels: true,
      showGrid: true,
    };

    expect(architectureInteractionOptions(options, true)).toEqual({
      showConnections: true,
      showReflections: false,
      showLabels: false,
      showGrid: true,
    });
    expect(architectureInteractionOptions(options, false)).toBe(options);
  });
});

describe("architecture world sizing", () => {
  it("fits a content-sized world and grows the canvas with it", () => {
    const graph = {
      resources: [
        { id: "sub", type: "subscription", x: 0, y: 0, w: 24, h: 30 },
      ],
    } as never;
    const camera: Camera = { yaw: Math.PI / 4, pitch: .58, scale: 42, panX: 0, panY: 0 };

    expect(architectureWorldSize(graph)).toEqual({ width: 24, height: 30 });
    expect(architectureCanvasHeight(graph)).toBe(840);
    fitCamera(camera, 1000, 960, graph);
    expect(camera.worldWidth).toBe(24);
    expect(camera.worldHeight).toBe(30);
    expect(camera.scale).toBeGreaterThanOrEqual(18);
  });
});

describe("architecture connections", () => {
  it("draws containment and node-to-node semantic links", () => {
    const region = { id: "rg", type: "resource-group", w: 4, h: 4 } as never;
    const app = { id: "app", type: "compute.container-app" } as never;
    const database = { id: "db", type: "postgresql-server" } as never;
    expect(architectureLinkIsDrawable(
      region,
      app,
      { source: "rg", target: "app", type: "contains" },
    )).toBe(true);
    expect(architectureLinkIsDrawable(
      app,
      database,
      { source: "app", target: "db", type: "depends_on" },
    )).toBe(true);
    expect(architectureLinkIsDrawable(
      region,
      database,
      { source: "rg", target: "db", type: "depends_on" },
    )).toBe(false);
  });

  it("raises semantic links above the connected block tops", () => {
    const vm = { id: "vm", type: "compute.vm" } as never;
    expect(architectureLinkElevation(vm)).toBeGreaterThan(
      .1 + geometryOf(vm).height,
    );
  });
});

describe("architecture responsive layout", () => {
  it("gives the map the full workspace width before the inspector", () => {
    expect(styles).toMatch(
      /\.architecture-stage\s*\{[^}]*grid-template-columns:\s*minmax\(0, 1fr\)/,
    );
    expect(styles).toMatch(
      /\.architecture-inspector\s*\{[^}]*grid-template-columns:\s*minmax\(0, 1\.4fr\)/,
    );
  });

  it("uses the page scroll instead of fixed workspace or inspector scroll regions", () => {
    expect(styles).not.toMatch(/\.architecture-workspace\s*\{[^}]*100vh/s);
    expect(styles).not.toMatch(/\.architecture-inspector\s*\{[^}]*max-height/s);
    expect(styles).not.toMatch(/\.architecture-inspector\s*\{[^}]*overflow:\s*auto/s);
  });

  it("keeps the resource legend out of the DOM overlay layer", () => {
    expect(styles).toMatch(
      /\.architecture-overview-panel\s*\{[^}]*position:\s*absolute;[^}]*top:\s*12px;[^}]*right:\s*12px;[^}]*width:\s*min\(220px/,
    );
    expect(styles).not.toMatch(
      /\.architecture-(?:resource-legend|legend-panel)\s*\{/,
    );
  });

  it("keeps the compact legend and resource index free of horizontal scrolling", () => {
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
