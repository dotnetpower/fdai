import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it } from "vitest";
import { setLocale } from "../i18n";
import {
  architectureMapAriaLabel,
  architectureMapLayerLabel,
  architectureMapSelectLabel,
  architectureMapSelectOptionLabel,
  architectureResourceFromValue,
} from "./architecture-map";
import {
  ARCHITECTURE_RESOURCE_ABBREVIATIONS,
  architectureResourceAbbreviation,
} from "./architecture-resource-abbreviations";
import { geometryOf, RESOURCE_COLOR_TOKENS } from "./architecture-map.model";
import {
  architectureCanvasHeight,
  DEFAULT_ORTHOGRAPHIC_CAMERA,
  architectureLegendReserveWidth,
  architectureZoomScale,
  architectureWorldSize,
  fitCamera,
  pickResource,
  project,
  zoomCameraAtPoint,
  type Camera,
} from "./architecture-map.geometry";
import {
  architectureLinkIsDrawable,
  architectureLinkElevation,
  architectureNodeLabelIsVisible,
  architectureOverlayOrder,
  architectureFloorLegendEntries,
  architectureFloorLegendFontSize,
  architectureGlyphFontSize,
  architectureLegendTextColor,
  architectureLabelFontSize,
  DEFAULT_ARCHITECTURE_MAP_PALETTE,
  fitArchitectureLabel,
} from "./architecture-map-renderer";
import {
  architectureInteractionOptions,
  architectureLayoutFrame,
  architecturePointerButtonsDragMode,
  architecturePointerDragMode,
} from "./use-architecture-map-controller";
import { architectureNetworkPlaneLabelIsVisible } from "./architecture-network-renderer";

const styles = readFileSync(fileURLToPath(new URL("../styles.css", import.meta.url)), "utf8");
const overviewPanelSource = readFileSync(
  fileURLToPath(new URL("./architecture-overview-panel.tsx", import.meta.url)),
  "utf8",
);

function relativeLuminance(hex: string): number {
  const weights = [.2126, .7152, .0722] as const;
  return [1, 3, 5]
    .map((index) => Number.parseInt(hex.slice(index, index + 2), 16) / 255)
    .map((channel) => channel <= .04045
      ? channel / 12.92
      : ((channel + .055) / 1.055) ** 2.4)
    .reduce((total, channel, index) => total + channel * weights[index]!, 0);
}

function contrastRatio(first: string, second: string): number {
  const firstLuminance = relativeLuminance(first);
  const secondLuminance = relativeLuminance(second);
  return (Math.max(firstLuminance, secondLuminance) + .05)
    / (Math.min(firstLuminance, secondLuminance) + .05);
}

afterEach(() => setLocale("en"));

describe("architecture resource navigator", () => {
  it("selects only an exact resource id", () => {
    const resources = [
      { id: "Run_A", name: "Worker", type: "compute.vm" },
    ] as never;
    expect(architectureResourceFromValue(resources, "Run_A")).toMatchObject({ id: "Run_A" });
    expect(architectureResourceFromValue(resources, "run-a")).toBeNull();
  });

  it("provides a minimum pointer target and selects the narrowest boundary", () => {
    const camera: Camera = { ...DEFAULT_ORTHOGRAPHIC_CAMERA, scale: 22 };
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
  it("localizes shared map controls for Korean routes", () => {
    setLocale("ko");

    expect(architectureMapLayerLabel("scope")).toBe("범위 및 경계");
    expect(architectureMapAriaLabel(3)).toBe("리소스 3개의 2D 아키텍처 지도");
    expect(architectureMapSelectLabel()).toBe("아키텍처 리소스 선택");
    expect(architectureMapSelectOptionLabel()).toBe("리소스 선택");
  });

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

  it("labels path workloads by default and expands any selected path resource", () => {
    const vm = { id: "vm", type: "compute.vm", network_plane_id: "subnet" } as never;
    const nic = { id: "nic", type: "network.interface", network_plane_id: "subnet" } as never;
    const unassigned = { id: "db", type: "postgresql-server" } as never;

    expect(architectureNodeLabelIsVisible(vm, false, 42)).toBe(true);
    expect(architectureNodeLabelIsVisible(nic, false, 42)).toBe(false);
    expect(architectureNodeLabelIsVisible(nic, true, 6)).toBe(true);
    expect(architectureNodeLabelIsVisible(unassigned, false, 42)).toBe(true);
  });

  it("uses glyphs instead of unselected node labels at dense overview scale", () => {
    const workload = { id: "vm", type: "compute.vm", network_plane_id: "subnet" } as never;
    const unassigned = { id: "db", type: "postgresql-server" } as never;

    expect(architectureNodeLabelIsVisible(workload, false, 6)).toBe(false);
    expect(architectureNodeLabelIsVisible(unassigned, false, 6)).toBe(false);
    expect(architectureNodeLabelIsVisible(workload, false, 12)).toBe(true);
  });

  it("keeps VNet names but hides unselected subnet names at dense overview scale", () => {
    const vnet = { id: "vnet", type: "network.vnet" } as never;
    const subnet = { id: "subnet", type: "network.subnet" } as never;

    expect(architectureNetworkPlaneLabelIsVisible(vnet, null, 6)).toBe(true);
    expect(architectureNetworkPlaneLabelIsVisible(subnet, null, 6)).toBe(false);
    expect(architectureNetworkPlaneLabelIsVisible(subnet, "subnet", 6)).toBe(true);
    expect(architectureNetworkPlaneLabelIsVisible(subnet, null, 12)).toBe(false);
    expect(architectureNetworkPlaneLabelIsVisible(subnet, null, 18)).toBe(true);
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

  it("fits long CAF abbreviations inside resource glyphs", () => {
    expect(architectureGlyphFontSize(42, "vm")).toBeCloseTo(12.4);
    expect(architectureGlyphFontSize(42, "evhns")).toBeLessThan(10);
    expect(architectureGlyphFontSize(132, "domain")).toBeGreaterThanOrEqual(7);
  });
});

describe("architecture CAF abbreviations", () => {
  it.each([
    ["compute.vm", "vm"],
    ["compute.vm-scale-set", "vmss"],
    ["compute.container-app", "ca"],
    ["compute.container-app-environment", "cae"],
    ["compute.container-app-job", "caj"],
    ["network.vnet", "vnet"],
    ["network.subnet", "snet"],
    ["network.interface", "nic"],
    ["network.private-endpoint", "pep"],
    ["postgresql-server", "pgsql"],
    ["application-insights", "appi"],
    ["event-hub", "evhns"],
  ] as const)("maps %s to %s", (type, expected) => {
    expect(architectureResourceAbbreviation(type)).toBe(expected);
  });

  it("uses an explicit neutral fallback only for unknown resources", () => {
    expect(architectureResourceAbbreviation("future-resource")).toBe("res");
    expect(Object.values(ARCHITECTURE_RESOURCE_ABBREVIATIONS)).not.toContain("res");
    expect(Object.values(ARCHITECTURE_RESOURCE_ABBREVIATIONS).every(
      (abbreviation) => /^[a-z0-9]+$/.test(abbreviation),
    )).toBe(true);
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
    expect(architectureFloorLegendFontSize(18)).toBe(13);
    expect(architectureFloorLegendFontSize(42)).toBeCloseTo(18.28);
    expect(architectureFloorLegendFontSize(132)).toBe(22);
  });

  it("keeps every colored legend label at AA text contrast", () => {
    for (const token of Object.values(RESOURCE_COLOR_TOKENS)) {
      expect(contrastRatio(
        architectureLegendTextColor(token.color),
        DEFAULT_ARCHITECTURE_MAP_PALETTE.background,
      ), token.label).toBeGreaterThanOrEqual(4.5);
    }
  });
});

describe("architecture map zoom", () => {
  it("round-trips one zoom step without scale drift", () => {
    const initial = 42;
    expect(architectureZoomScale(architectureZoomScale(initial, "in"), "out"))
      .toBeCloseTo(initial, 10);
    expect(architectureZoomScale(14, "out")).toBe(14);
  });

  it("supports deep inspection and keeps pointer position anchored", () => {
    expect(architectureZoomScale(500, "in")).toBe(512);
    const camera: Camera = {
      ...DEFAULT_ORTHOGRAPHIC_CAMERA,
      scale: 40,
      panX: -20,
      panY: 12,
    };
    const width = 1000;
    const height = 700;
    const pointer = { x: 720, y: 260 };
    const relativeX = pointer.x - (width / 2 + camera.panX);
    const relativeY = pointer.y - (height / 2 + camera.panY);

    zoomCameraAtPoint(camera, "in", pointer.x, pointer.y, width, height);

    expect(camera.scale).toBe(48);
    expect(width / 2 + camera.panX + relativeX * 1.2).toBeCloseTo(pointer.x);
    expect(height / 2 + camera.panY + relativeY * 1.2).toBeCloseTo(pointer.y);
  });
});

describe("architecture orthographic projection", () => {
  it("keeps world scale uniform and ignores resource height", () => {
    const camera: Camera = {
      ...DEFAULT_ORTHOGRAPHIC_CAMERA,
      scale: 40,
      worldWidth: 18,
      worldHeight: 12,
    };
    const centerX = 500;
    const near = project(camera, 1000, 700, 12, 1, .2);
    const far = project(camera, 1000, 700, 12, 11, .2);
    const elevated = project(camera, 1000, 700, 12, 1, 1.2);
    expect(Math.abs(near.x - centerX)).toBeCloseTo(Math.abs(far.x - centerX));
    expect(elevated).toMatchObject({ x: near.x, y: near.y });
    expect(project(camera, 1000, 700, 13, 1).x - near.x).toBeCloseTo(40);
  });
});

describe("architecture map pan", () => {
  it("maps left and middle drag to the same 2D pan interaction", () => {
    expect(architecturePointerDragMode(0)).toBe("pan");
    expect(architecturePointerDragMode(1)).toBe("pan");
    expect(architecturePointerDragMode(2)).toBeNull();
    expect(architecturePointerButtonsDragMode(1)).toBe("pan");
    expect(architecturePointerButtonsDragMode(4)).toBe("pan");
    expect(architecturePointerButtonsDragMode(0)).toBeNull();
  });
});

describe("architecture floor legend space", () => {
  it("reserves a bounded desktop legend area and gives narrow maps the full canvas", () => {
    expect(architectureLegendReserveWidth(1200)).toBe(288);
    expect(architectureLegendReserveWidth(700)).toBe(220);
    expect(architectureLegendReserveWidth(619)).toBe(0);
    expect(architectureLegendReserveWidth(390)).toBe(0);
  });
});

describe("architecture selection frame", () => {
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
  it("keeps 2D resources and connections while deferring labels", () => {
    const options = {
      showConnections: true,
      showLabels: true,
      showGrid: true,
    };

    expect(architectureInteractionOptions(options, true)).toEqual({
      showConnections: true,
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
    const camera: Camera = { ...DEFAULT_ORTHOGRAPHIC_CAMERA };

    expect(architectureWorldSize(graph)).toEqual({ width: 24, height: 30 });
    expect(architectureCanvasHeight(graph)).toBe(1080);
    expect(architectureCanvasHeight({
      resources: [{ id: "sub", type: "subscription", x: 0, y: 0, w: 24, h: 100 }],
    } as never)).toBe(3600);
    fitCamera(camera, 1000, 960, graph);
    expect(camera.worldWidth).toBe(24);
    expect(camera.worldHeight).toBe(30);
    expect(camera.scale).toBeGreaterThanOrEqual(6);
  });

  it("anchors a tall content-driven world in the first visible frame", () => {
    const graph = {
      resources: [
        { id: "sub", type: "subscription", x: 0, y: 0, w: 24, h: 100 },
      ],
    } as never;
    const camera: Camera = {
      ...DEFAULT_ORTHOGRAPHIC_CAMERA,
    };
    const canvasHeight = architectureCanvasHeight(graph);

    fitCamera(camera, 1000, canvasHeight, graph);
    const corners = [0, 1.2].flatMap((z) => [
      project(camera, 1000, canvasHeight, 0, 0, z),
      project(camera, 1000, canvasHeight, 24, 0, z),
      project(camera, 1000, canvasHeight, 24, 100, z),
      project(camera, 1000, canvasHeight, 0, 100, z),
    ]);

    expect(Math.min(...corners.map((point) => point.y))).toBeCloseTo(60, 5);
  });

  it("centers a narrow 2D world below the mobile map controls", () => {
    const graph = {
      resources: [
        { id: "sub", type: "subscription", x: 0, y: 0, w: 18, h: 12 },
      ],
    } as never;
    const camera: Camera = { ...DEFAULT_ORTHOGRAPHIC_CAMERA };

    fitCamera(camera, 290, 520, graph);

    expect(project(camera, 290, 520, 0, 0).y).toBeGreaterThanOrEqual(112);
    expect(project(camera, 290, 520, 18, 12).y).toBeLessThanOrEqual(440);
  });

  it("fits a focused resource-group view to its compact content world", () => {
    const graph = {
      active_view: "rg",
      views: [{ id: "rg", kind: "resource_group" }],
      resources: [
        { id: "sub", type: "subscription", x: .25, y: .25, w: 11, h: 6.5 },
        { id: "rg", type: "resource-group", x: .7, y: 1.1, w: 10, h: 5.5 },
      ],
    } as never;

    expect(architectureWorldSize(graph)).toEqual({ width: 11.25, height: 6.75 });
    expect(architectureCanvasHeight(graph)).toBe(560);
    const camera: Camera = {
      ...DEFAULT_ORTHOGRAPHIC_CAMERA,
    };
    fitCamera(camera, 1200, 680, graph);
    const world = architectureWorldSize(graph);
    const corners = [
      project(camera, 1200, 680, 0, 0, 0),
      project(camera, 1200, 680, world.width, 0, 0),
      project(camera, 1200, 680, world.width, world.height, 0),
      project(camera, 1200, 680, 0, world.height, 0),
    ];
    expect(Math.min(...corners.map((point) => point.x))).toBeGreaterThanOrEqual(24);
    expect(Math.max(...corners.map((point) => point.y))).toBeLessThanOrEqual(656);
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

  it("uses nested network planes instead of drawing a containment chord", () => {
    const vnet = { id: "vnet", type: "network.vnet", w: 8, h: 6 } as never;
    const subnet = { id: "subnet", type: "network.subnet", w: 4, h: 3 } as never;
    const vm = { id: "vm", type: "compute.vm" } as never;

    expect(architectureLinkIsDrawable(
      vnet,
      subnet,
      { source: "vnet", target: "subnet", type: "contains" },
    )).toBe(false);
    const attachedVm = {
      id: "vm", type: "compute.vm", network_plane_id: "subnet",
    } as never;
    expect(architectureLinkIsDrawable(
      attachedVm,
      subnet,
      { source: "vm", target: "subnet", type: "attached_to" },
    )).toBe(false);
    const nic = { id: "nic", type: "network.interface", network_plane_id: "subnet" } as never;
    expect(architectureLinkIsDrawable(
      attachedVm,
      nic,
      { source: "vm", target: "nic", type: "attached_to" },
    )).toBe(false);
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
      /@media \(max-width: 620px\)[\s\S]*?\.architecture-canvas-shell\s*\{[^}]*min-height:\s*min\(var\(--architecture-canvas-height, 640px\), 520px\)/,
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
