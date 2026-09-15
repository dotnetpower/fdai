import { describe, expect, it } from "vitest";
import {
  ARCHITECTURE_TOPOLOGY_MAX_SCALE,
  ARCHITECTURE_TOPOLOGY_MIN_SCALE,
  architectureTopologyActiveIds,
  architectureTopologyBounds,
  architectureTopologyCanvasSize,
  architectureTopologyFitScale,
  architectureTopologyInitialView,
  architectureTopologyLabelLines,
  architectureTopologyLinkRoute,
  architectureTopologyUnplacedIds,
  architectureTopologyZoomScrollTarget,
  clampArchitectureTopologyScale,
} from "./architecture-topology-graph.model";
import {
  layoutArchitectureImpactPresentation,
  layoutArchitecturePresentation,
} from "./architecture-map-layout";
import {
  architectureTopologyNodeDimensions,
} from "./architecture-topology-dimensions";
import {
  architectureNetworkIconForResourceType,
  architectureNetworkIconSourceIsSafe,
} from "./architecture-network-icons";
import { constrainGraph, isRegion } from "./architecture-map.model";

describe("Architecture topology geometry", () => {
  it("contains regions and centered resource cards with stable padding", () => {
    const bounds = architectureTopologyBounds([
      { id: "vnet", type: "network.vnet", name: "Network", status: "healthy", x: 2, y: 3, w: 8, h: 5 },
      { id: "vm", type: "compute.vm", name: "VM", status: "healthy", x: 9.5, y: 7.5 },
    ]);

    expect(bounds.x).toBeLessThanOrEqual(1.5);
    expect(bounds.y).toBeLessThanOrEqual(2.2);
    expect(bounds.x + bounds.width).toBeGreaterThanOrEqual(10.7);
    expect(bounds.y + bounds.height).toBeGreaterThanOrEqual(9);
  });

  it("rejects missing presentation geometry instead of inventing coordinate zero", () => {
    expect(architectureTopologyUnplacedIds([
      { id: "group", type: "resource-group", name: "Group", status: "unknown" },
      { id: "app", type: "app-service", name: "App", status: "healthy", x: 1, y: 2 },
    ])).toEqual(["group"]);
    expect(architectureTopologyUnplacedIds([
      { id: "group", type: "resource-group", name: "Group", status: "unknown", x: 0, y: 0, w: 4, h: 3 },
      { id: "app", type: "app-service", name: "App", status: "healthy", x: 1, y: 2 },
    ])).toEqual([]);
  });

  it("fits the authored canvas without enlarging and clamps explicit zoom", () => {
    const canvas = architectureTopologyCanvasSize({ x: 0, y: 0, width: 18, height: 12 });
    expect(canvas).toEqual({ width: 1152, height: 768 });
    expect(architectureTopologyFitScale(canvas, 1200, 800)).toBe(1);
    expect(architectureTopologyFitScale(canvas, 600, 500)).toBeLessThan(1);
    expect(clampArchitectureTopologyScale(0)).toBe(ARCHITECTURE_TOPOLOGY_MIN_SCALE);
    expect(clampArchitectureTopologyScale(4)).toBe(ARCHITECTURE_TOPOLOGY_MAX_SCALE);
  });

  it("resets a new presentation canvas to its fitted origin", () => {
    expect(architectureTopologyInitialView(
      { width: 1200, height: 800 },
      600,
      500,
    )).toEqual({
      scale: architectureTopologyFitScale({ width: 1200, height: 800 }, 600, 500),
      scroll: { left: 0, top: 0 },
    });
  });

  it("preserves the viewport center while zooming", () => {
    expect(architectureTopologyZoomScrollTarget({
      scrollLeft: 200,
      scrollTop: 100,
      viewportWidth: 800,
      viewportHeight: 600,
      currentScale: 1,
      nextScale: 1.2,
    })).toEqual({ left: 320, top: 180 });
  });

  it("routes relationships to node and region boundaries", () => {
    const source = {
      id: "nic", type: "network.interface", name: "Interface", status: "healthy", x: 2, y: 2,
    };
    const target = {
      id: "subnet", type: "network.subnet", name: "Subnet", status: "healthy",
      x: 0, y: 0, w: 6, h: 6,
    };
    const route = architectureTopologyLinkRoute(source, target, [source, target], "attached_to");

    expect(route.path).not.toContain("M2 2");
    expect(route.path).toMatch(/L0 3$/);
  });

  it("keeps highlighted resources' subnet, VNet, and parent boundaries active", () => {
    const graph = {
      resources: [
        { id: "group", type: "resource-group", name: "Group", status: "healthy" },
        { id: "vnet", type: "network.vnet", name: "VNet", status: "healthy", parent_id: "group" },
        { id: "subnet", type: "network.subnet", name: "Subnet", status: "healthy", parent_id: "group" },
        { id: "vm", type: "compute.vm", name: "VM", status: "healthy", parent_id: "group", network_plane_id: "subnet" },
        { id: "other", type: "compute.vm", name: "Other", status: "healthy", parent_id: "group" },
      ],
      links: [{ source: "vnet", target: "subnet", type: "contains" as const }],
    };

    const active = architectureTopologyActiveIds(graph, new Set(["vm"]));

    expect(active).toEqual(new Set(["vm", "subnet", "group", "vnet"]));
    expect(active?.has("other")).toBe(false);
  });

  it("bounds long visible labels without changing their accessible source", () => {
    expect(architectureTopologyLabelLines("Workload VM")).toEqual(["Workload VM"]);
    expect(architectureTopologyLabelLines("A very long workload service"))
      .toEqual(["A very long", "workload service"]);
    expect(architectureTopologyLabelLines("resource-name-that-is-too-long")[0]).toMatch(/\.\.\.$/);
  });

  it("keeps impacted auxiliary Resources beyond the target's direct neighbors", () => {
    const graph = {
      snapshot_at: "2026-09-14T00:00:00Z",
      freshness: "fresh" as const,
      scope: null,
      depth: 4,
      included_link_types: ["contains", "depends_on", "attached_to"],
      truncated: false,
      resources: [
        { id: "sub", type: "subscription", name: "Subscription", status: "unknown", x: 0, y: 0, w: 20, h: 12 },
        { id: "rg", type: "resource-group", name: "Group", status: "unknown", parent_id: "sub", x: 1, y: 1, w: 18, h: 10 },
        { id: "app", type: "app-service", name: "App", status: "healthy", parent_id: "rg" },
        { id: "vm", type: "compute.vm", name: "VM", status: "healthy", parent_id: "rg" },
        { id: "identity", type: "managed-identity", name: "Identity", status: "healthy", parent_id: "rg" },
      ],
      links: [
        { source: "sub", target: "rg", type: "contains" as const },
        { source: "rg", target: "app", type: "contains" as const },
        { source: "rg", target: "vm", type: "contains" as const },
        { source: "rg", target: "identity", type: "contains" as const },
        { source: "app", target: "vm", type: "depends_on" as const },
        { source: "vm", target: "identity", type: "attached_to" as const },
      ],
    };

    expect(layoutArchitecturePresentation(graph, "app").resources.map((item) => item.id))
      .not.toContain("identity");
    expect(layoutArchitectureImpactPresentation(
      graph,
      new Set(["app", "vm", "identity"]),
    ).resources.map((item) => item.id)).toContain("identity");
  });

  it("packs every revealed auxiliary Resource without card collisions", () => {
    const auxiliaries = Array.from({ length: 12 }, (_, index) => ({
      id: `identity-${index}`,
      type: "managed-identity",
      name: `Identity ${index}`,
      status: "healthy",
      parent_id: "rg",
    }));
    const graph = {
      snapshot_at: "2026-09-14T00:00:00Z",
      freshness: "fresh" as const,
      scope: null,
      depth: 4,
      included_link_types: ["contains", "attached_to"],
      truncated: false,
      resources: [
        { id: "sub", type: "subscription", name: "Subscription", status: "unknown", x: 0, y: 0, w: 8, h: 6 },
        { id: "rg", type: "resource-group", name: "Group", status: "unknown", parent_id: "sub", x: 1, y: 1, w: 5, h: 4 },
        { id: "app", type: "app-service", name: "App", status: "healthy", parent_id: "rg" },
        ...auxiliaries,
      ],
      links: [
        { source: "sub", target: "rg", type: "contains" as const },
        { source: "rg", target: "app", type: "contains" as const },
        ...auxiliaries.flatMap((resource) => [
          { source: "rg", target: resource.id, type: "contains" as const },
          { source: "app", target: resource.id, type: "attached_to" as const },
        ]),
      ],
    };
    const presented = layoutArchitecturePresentation(graph, "rg");
    const nodes = presented.resources.filter((resource) => !isRegion(resource));
    const group = presented.resources.find((resource) => resource.id === "rg")!;

    for (const [index, first] of nodes.entries()) {
      const firstSize = architectureTopologyNodeDimensions(first.render_scale);
      expect(first.x! - firstSize.width / 2).toBeGreaterThanOrEqual(group.x!);
      expect(first.x! + firstSize.width / 2).toBeLessThanOrEqual(group.x! + group.w!);
      expect(first.y! - firstSize.height / 2).toBeGreaterThanOrEqual(group.y!);
      expect(first.y! + firstSize.height / 2).toBeLessThanOrEqual(group.y! + group.h!);
      for (const second of nodes.slice(index + 1)) {
        const secondSize = architectureTopologyNodeDimensions(second.render_scale);
        const overlaps =
          Math.abs(first.x! - second.x!) < (firstSize.width + secondSize.width) / 2
          && Math.abs(first.y! - second.y!) < (firstSize.height + secondSize.height) / 2;
        expect(overlaps, `${first.id} overlaps ${second.id}`).toBe(false);
      }
    }
  });

  it("expands authored containment to the rendered SVG card geometry", () => {
    const graph = {
      snapshot_at: "2026-09-14T00:00:00Z",
      freshness: "fresh" as const,
      scope: null,
      depth: 4,
      included_link_types: ["contains"],
      truncated: false,
      resources: [
        { id: "vnet", type: "network.vnet", name: "Tiny VNet", status: "healthy", x: 1, y: 1, w: 1, h: 1 },
        { id: "app", type: "app-service", name: "App", status: "healthy", network_plane_id: "vnet", x: 1.5, y: 1.5 },
      ],
      links: [{ source: "vnet", target: "app", type: "contains" as const }],
    };
    const constrained = constrainGraph(graph);
    const vnet = constrained.resources.find((resource) => resource.id === "vnet")!;
    const app = constrained.resources.find((resource) => resource.id === "app")!;
    const size = architectureTopologyNodeDimensions(app.render_scale);

    expect(app.x! - size.width / 2).toBeGreaterThanOrEqual(vnet.x!);
    expect(app.x! + size.width / 2).toBeLessThanOrEqual(vnet.x! + vnet.w!);
    expect(app.y! - size.height / 2).toBeGreaterThanOrEqual(vnet.y!);
    expect(app.y! + size.height / 2).toBeLessThanOrEqual(vnet.y! + vnet.h!);
  });
});

describe("Architecture topology icons", () => {
  it("maps reviewed types to official SVGs and leaves unknown types unmapped", () => {
    expect(architectureNetworkIconForResourceType("network.interface")).toMatch(
      /^(?:data:image\/svg\+xml|.*\.svg$)/,
    );
    expect(architectureNetworkIconForResourceType("compute.vm")).toMatch(
      /^(?:data:image\/svg\+xml|.*\.svg$)/,
    );
    expect(architectureNetworkIconForResourceType("future.network/type")).toBeUndefined();
  });

  it("accepts only inert internal SVG references", () => {
    expect(architectureNetworkIconSourceIsSafe('<svg xmlns="http://www.w3.org/2000/svg"><linearGradient id="a"/><path href="#a"/></svg>')).toBe(true);
    expect(architectureNetworkIconSourceIsSafe('<svg xmlns="http://www.w3.org/2000/svg"><image href="https://example.com/icon.svg"/></svg>')).toBe(false);
    expect(architectureNetworkIconSourceIsSafe('<svg xmlns="http://www.w3.org/2000/svg"><script/></svg>')).toBe(false);
  });
});
