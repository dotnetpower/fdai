import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, test } from "vitest";
import { layoutArchitecturePresentation } from "./architecture-map-layout";
import {
  DEFAULT_ARCHITECTURE_DISPLAY_OPTIONS,
  architecturePresentationGraph,
  architectureHref,
  DEFAULT_ARCHITECTURE_CAMERA_VIEW,
  architectureViewKindLabel,
  architectureViewFromHash,
  constrainGraph,
  expandSimpleResourceGroupPanels,
  geometryOf,
  graphSubset,
  hasExplicitVisualMapping,
  layerOf,
  relatedResourceIds,
  resourceColorTokenOf,
  resourceTypeLabelOf,
  resourceColorOf,
  selectedResourceIdFromHash,
  shapeOf,
  type InventoryGraphResponse,
} from "./architecture-map.model";

describe("architecture display defaults", () => {
  test("shows resource reflections and connections by default", () => {
    expect(DEFAULT_ARCHITECTURE_DISPLAY_OPTIONS.showReflections).toBe(true);
    expect(DEFAULT_ARCHITECTURE_DISPLAY_OPTIONS.showConnections).toBe(true);
  });
});

describe("architecture Azure discovery mappings", () => {
  test.each([
    ["compute.container-app-job", "runtime"],
    ["network.interface", "network"],
    ["network.private-dns-zone", "network"],
    ["container-registry", "data"],
    ["event-hub", "messaging"],
    ["application-insights", "observability"],
  ] as const)("maps %s to the %s layer", (resourceType, layer) => {
    const resource = { id: resourceType, type: resourceType } as never;
    expect(layerOf(resource)).toBe(layer);
    expect(hasExplicitVisualMapping(resourceType)).toBe(true);
  });
});

const GRAPH: InventoryGraphResponse = {
  snapshot_at: "2026-07-13T00:00:00Z",
  freshness: "fresh",
  scope: null,
  depth: 4,
  included_link_types: ["contains", "depends_on"],
  resources: [
    { id: "rg", type: "resource-group", name: "rg", status: "healthy", w: 4, h: 4 },
    { id: "app", type: "app-service", name: "app", status: "healthy", parent_id: "rg" },
    { id: "db", type: "postgresql", name: "db", status: "healthy", parent_id: "rg" },
  ],
  links: [
    { source: "rg", target: "app", type: "contains" },
    { source: "app", target: "db", type: "depends_on" },
  ],
  truncated: false,
};

describe("architecture map model", () => {
  test("uses the isometric camera by default", () => {
    expect(DEFAULT_ARCHITECTURE_CAMERA_VIEW).toBe("iso");
  });

  test("maps resource types to visual layers", () => {
    expect(layerOf(GRAPH.resources[1]!)).toBe("runtime");
    expect(layerOf(GRAPH.resources[2]!)).toBe("data");
    expect(layerOf({ id: "eh", type: "event-hub", name: "eh", status: "healthy" })).toBe("messaging");
  });

  test.each([
    ["front-door", "network"],
    ["application-gateway", "network"],
    ["web-application-firewall", "security"],
    ["compute.container-app", "runtime"],
    ["network.vnet", "network"],
    ["network.nsg", "security"],
    ["object-storage", "data"],
    ["cache", "data"],
    ["managed-identity", "security"],
    ["log-workspace", "observability"],
  ] as const)("maps canonical %s to the %s layer", (type, layer) => {
    expect(layerOf({ id: type, type, name: type, status: "healthy" })).toBe(layer);
  });

  test.each([
    ["compute.vm", "virtual-machine", "#0078D4"],
    ["compute.vm-scale-set", "vm-scale-set", "#1490DF"],
    ["network.private-endpoint", "private-endpoint", "#32BEDD"],
    ["network.public-ip", "public-ip", "#AD52E3"],
    ["diagnostic-settings", "diagnostic-settings", "#155EA1"],
    ["file-share", "file-share", "#773ADC"],
    ["disk", "disk", "#5EA0EF"],
    ["nosql-database", "cosmos-db", "#32BEDD"],
    ["managed-identity", "managed-identity", "#1988D9"],
    ["certificate", "certificate", "#D15900"],
    ["log-workspace", "log-analytics", "#A997E2"],
    ["metrics-workspace", "azure-monitor", "#155EA1"],
  ] as const)("predefines canonical %s as %s", (type, token, color) => {
    const resource = { id: type, type, name: type, status: "healthy" };
    expect(resourceColorTokenOf(resource)).toBe(token);
    expect(resourceColorOf(resource)).toBe(color);
  });

  test.each([
    ["event-hub", "event-hub", "#76BC2D"],
    ["postgresql", "database", "#005BA1"],
    ["storage-account", "storage", "#37C2B1"],
    ["key-vault", "key-vault", "#FF9300"],
    ["firewall", "firewall", "#E62323"],
    ["app-service", "app-service", "#0078D4"],
    ["container-app", "container-app", "#773ADC"],
    ["function-app", "function-app", "#C19C00"],
    ["aks-cluster", "aks", "#5C2D91"],
    ["future-resource", "generic", "#697586"],
  ] as const)("maps %s to the %s Azure-aligned color", (type, token, color) => {
    const resource = { id: type, type, name: type, status: "healthy" };
    expect(resourceColorTokenOf(resource)).toBe(token);
    expect(resourceColorOf(resource)).toBe(color);
  });

  test.each([
    ["postgresql", "cylinder"],
    ["app-service", "block"],
    ["container-app", "block"],
    ["application-gateway", "gateway"],
    ["front-door", "gateway"],
    ["load-balancer", "gateway"],
    ["storage-account", "slab"],
    ["event-hub", "hexagon"],
    ["service-bus", "hexagon"],
    ["key-vault", "compact"],
    ["firewall", "compact"],
    ["network.load-balancer", "gateway"],
    ["nosql-database", "cylinder"],
    ["file-share", "slab"],
    ["disk", "slab"],
    ["network.vnet", "lane"],
    ["network.subnet", "lane"],
  ] as const)("maps %s to the %s shape", (type, expected) => {
    expect(shapeOf({ id: type, type, name: type, status: "healthy" })).toBe(expected);
  });

  test("uses readable proportions for semantic shape variants", () => {
    const resource = (type: string) => ({ id: type, type, name: type, status: "healthy" });
    expect(geometryOf(resource("application-gateway")).width).toBeGreaterThan(
      geometryOf(resource("app-service")).width,
    );
    expect(geometryOf(resource("application-gateway")).height).toBeLessThan(
      geometryOf(resource("app-service")).height,
    );
    expect(geometryOf(resource("storage-account")).height).toBeLessThan(
      geometryOf(resource("postgresql")).height,
    );
    expect(geometryOf(resource("network.vnet")).width).toBeGreaterThan(
      geometryOf(resource("application-gateway")).width,
    );
    expect(geometryOf(resource("network.vnet")).height).toBeLessThan(
      geometryOf(resource("storage-account")).height,
    );
  });

  test.each([
    ["waf", "security"],
    ["l4-load-balancer", "network"],
    ["event-hubs", "messaging"],
    ["message-queue", "messaging"],
    ["kafka", "messaging"],
    ["nsg", "security"],
  ] as const)("maps the %s shape alias to the %s layer", (type, expected) => {
    expect(layerOf({ id: type, type, name: type, status: "healthy" })).toBe(expected);
  });

  test("filters resources and dangling links together", () => {
    const subset = graphSubset(GRAPH, new Set(["scope", "runtime"]));
    expect(subset.resources.map((resource) => resource.id)).toEqual(["rg", "app"]);
    expect(subset.links).toEqual([{ source: "rg", target: "app", type: "contains" }]);
  });

  test("filters data stores independently from messaging resources", () => {
    const graph = {
      ...GRAPH,
      resources: [
        ...GRAPH.resources,
        { id: "events", type: "event-hub", name: "events", status: "healthy" },
      ],
    };
    expect(graphSubset(graph, new Set(["data"])).resources.map((resource) => resource.id)).toEqual(["db"]);
    expect(graphSubset(graph, new Set(["messaging"])).resources.map((resource) => resource.id)).toEqual(["events"]);
  });

  test("identifies the selected resource neighborhood", () => {
    expect(relatedResourceIds(GRAPH, "app")).toEqual(new Set(["app", "rg", "db"]));
    expect(relatedResourceIds(GRAPH, "missing")).toBeUndefined();
  });

  test("collapses auxiliary resources until their owner is selected", () => {
    const graph: InventoryGraphResponse = {
      ...GRAPH,
      resources: [
        { id: "rg", type: "resource-group", name: "rg", status: "healthy", w: 8, h: 8 },
        { id: "vm", type: "compute.vm", name: "vm", status: "healthy", parent_id: "rg" },
        { id: "nic", type: "network.interface", name: "nic", status: "healthy", parent_id: "rg" },
        { id: "disk", type: "disk", name: "disk", status: "healthy", parent_id: "rg" },
        { id: "identity", type: "managed-identity", name: "identity", status: "healthy", parent_id: "rg" },
        { id: "db", type: "postgresql-server", name: "db", status: "healthy", parent_id: "rg" },
      ],
      links: [
        { source: "rg", target: "vm", type: "contains" },
        { source: "rg", target: "nic", type: "contains" },
        { source: "rg", target: "disk", type: "contains" },
        { source: "rg", target: "identity", type: "contains" },
        { source: "rg", target: "db", type: "contains" },
        { source: "vm", target: "nic", type: "attached_to" },
        { source: "vm", target: "disk", type: "attached_to" },
      ],
    };

    const overview = architecturePresentationGraph(graph, null);
    expect(overview.resources.map((resource) => resource.id)).toEqual(["rg", "vm", "db"]);
    expect(overview.resources.find((resource) => resource.id === "vm")?.collapsed_count).toBe(2);
    expect(overview.resources.find((resource) => resource.id === "rg")?.collapsed_count).toBe(1);

    const focused = architecturePresentationGraph(graph, "vm");
    expect(focused.resources.map((resource) => resource.id)).toEqual([
      "rg", "vm", "nic", "disk", "db",
    ]);
    expect(focused.links).toContainEqual({ source: "vm", target: "nic", type: "attached_to" });
    expect(focused.resources.some((resource) => resource.id === "identity")).toBe(false);

    const laidOut = constrainGraph(graph);
    const laidOutOverview = architecturePresentationGraph(laidOut, null);
    const laidOutFocused = architecturePresentationGraph(laidOut, "vm");
    for (const resource of laidOutOverview.resources) {
      const focusedResource = laidOutFocused.resources.find(
        (candidate) => candidate.id === resource.id,
      );
      expect(focusedResource?.x).toBe(resource.x);
      expect(focusedResource?.y).toBe(resource.y);
      expect(focusedResource?.w).toBe(resource.w);
      expect(focusedResource?.h).toBe(resource.h);
    }
  });

  test("uses a plain resource type label instead of requiring acronym decoding", () => {
    expect(resourceTypeLabelOf({ id: "vm", type: "compute.vm" } as never))
      .toBe("Virtual machines");
    expect(resourceTypeLabelOf({ id: "pip", type: "network.public-ip" } as never))
      .toBe("Public IP");
  });

  test("reveals direct auxiliary children when a boundary is selected", () => {
    const graph: InventoryGraphResponse = {
      ...GRAPH,
      resources: [
        { id: "rg", type: "resource-group", name: "rg", status: "healthy", w: 8, h: 8 },
        { id: "identity", type: "managed-identity", name: "identity", status: "healthy", parent_id: "rg" },
      ],
      links: [{ source: "rg", target: "identity", type: "contains" }],
    };

    expect(architecturePresentationGraph(graph, "rg").resources.map((resource) => resource.id))
      .toEqual(["rg", "identity"]);
  });

  test("keeps a compact overview and gives revealed VM auxiliaries distinct slots", () => {
    const graph: InventoryGraphResponse = {
      ...GRAPH,
      resources: [
        { id: "sub", type: "subscription", name: "sub", status: "healthy", x: 0, y: 0, w: 18, h: 12 },
        ...Array.from({ length: 3 }, (_, index) => ({
          id: `rg-${index}`,
          type: "resource-group",
          name: `rg-${index}`,
          status: "healthy",
          parent_id: "sub",
          x: index * 5,
          y: 1,
          w: 4,
          h: 4,
        })),
        { id: "vm", type: "compute.vm", name: "vm", status: "healthy", parent_id: "rg-0" },
        { id: "nic", type: "network.interface", name: "nic", status: "healthy", parent_id: "rg-0" },
        { id: "disk", type: "disk", name: "disk", status: "healthy", parent_id: "rg-0" },
        ...Array.from({ length: 8 }, (_, index) => ({
          id: `identity-${index}`,
          type: "managed-identity",
          name: `identity-${index}`,
          status: "healthy",
          parent_id: "rg-0",
        })),
      ],
      links: [
        { source: "vm", target: "nic", type: "attached_to" },
        { source: "vm", target: "disk", type: "attached_to" },
      ],
    };

    const overview = layoutArchitecturePresentation(graph, null);
    const focused = layoutArchitecturePresentation(graph, "vm");
    const overviewVm = overview.resources.find((resource) => resource.id === "vm")!;
    const focusedVm = focused.resources.find((resource) => resource.id === "vm")!;
    const revealed = focused.resources.filter((resource) => ["nic", "disk"].includes(resource.id));

    expect(overview.resources.some((resource) => resource.id === "nic")).toBe(false);
    expect(focusedVm).toMatchObject({ x: overviewVm.x, y: overviewVm.y });
    expect(new Set(revealed.map((resource) => `${resource.x}:${resource.y}`)).size).toBe(2);
    expect(revealed.every((resource) => resource.x !== overviewVm.x || resource.y !== overviewVm.y))
      .toBe(true);
  });

  test("predefines every canonical resource vocabulary color", () => {
    const vocabularyPath = fileURLToPath(new URL(
      "../../../rule-catalog/vocabulary/resource-types.yaml",
      import.meta.url,
    ));
    const canonicalTypes = [...readFileSync(vocabularyPath, "utf8").matchAll(/^  - id: ([a-z0-9.-]+)$/gm)]
      .map((match) => match[1]!);
    expect(canonicalTypes.length).toBeGreaterThan(0);
    for (const type of canonicalTypes) {
      expect(hasExplicitVisualMapping(type), `${type} needs an explicit layer and color`).toBe(true);
    }
  });

  test("round-trips resource deep links", () => {
    expect(architectureHref("web api")).toBe("/architecture?resource=web+api");
    expect(selectedResourceIdFromHash("#/architecture?resource=web%20api")).toBe("web api");
    expect(architectureHref("web-api", "commerce-api")).toBe("/architecture?resource=web-api&view=commerce-api");
    expect(architectureViewFromHash("#/architecture?view=commerce-api")).toBe("commerce-api");
  });

  test("labels architecture view boundaries explicitly", () => {
    expect(architectureViewKindLabel({
      id: "fdai-control-plane",
      label: "FDAI",
      kind: "fdai",
      classification: "ownership_tag",
      description: "",
      root_resource_id: "fdai",
    })).toBe("FDAI");
    expect(architectureViewKindLabel({
      id: "service:orders",
      label: "Orders",
      kind: "service",
      classification: "service_tag",
      description: "",
      root_resource_id: "rg-orders",
    })).toBe("Service");
    expect(architectureViewKindLabel({
      id: "rg-shared",
      label: "rg-shared",
      kind: "resource_group",
      classification: "resource_group_fallback",
      description: "",
      root_resource_id: "rg-shared",
    })).toBe("Resource group");
  });

  test("clamps regions and nodes inside their parent boundaries", () => {
    const constrained = constrainGraph({
      ...GRAPH,
      resources: [
        { id: "sub", type: "subscription", name: "sub", status: "healthy", x: 0, y: 0, w: 10, h: 8 },
        { id: "rg", type: "resource-group", name: "rg", status: "healthy", parent_id: "sub", x: 8, y: 7, w: 5, h: 5 },
        { id: "app", type: "app-service", name: "app", status: "healthy", parent_id: "rg", x: 20, y: 20 },
      ],
    });
    const region = constrained.resources[1]!;
    const app = constrained.resources[2]!;
    expect((region.x ?? 0) + (region.w ?? 0)).toBeLessThanOrEqual(9.88);
    expect((region.y ?? 0) + (region.h ?? 0)).toBeLessThanOrEqual(7.88);
    expect(app.x).toBeLessThanOrEqual((region.x ?? 0) + (region.w ?? 0) - .58);
    expect(app.y).toBeCloseTo((region.y ?? 0) + (region.h ?? 0) - .44, 8);
  });

  test("scales a wide gateway to fit a narrow parent", () => {
    const constrained = constrainGraph({
      ...GRAPH,
      resources: [
        { id: "rg", type: "resource-group", name: "rg", status: "healthy", x: 0, y: 0, w: 1, h: 1 },
        { id: "gateway", type: "application-gateway", name: "gateway", status: "healthy", parent_id: "rg", x: 1, y: 1 },
      ],
    });
    const gateway = constrained.resources[1]!;
    const geometry = geometryOf(gateway);
    expect((gateway.x ?? 0) - geometry.width / 2).toBeGreaterThanOrEqual(.06);
    expect((gateway.x ?? 0) + geometry.width / 2).toBeLessThanOrEqual(.94);
    expect((gateway.y ?? 0) - geometry.depth / 2).toBeGreaterThanOrEqual(.06);
    expect((gateway.y ?? 0) + geometry.depth / 2).toBeLessThanOrEqual(.94);
  });

  test("sizes simple resource-group panels around EGT-scale resources", () => {
    const groups = Array.from({ length: 6 }, (_, index) => ({
      id: `group-${index}`,
      type: "resource-group",
      name: `group-${index}`,
      status: "healthy",
      parent_id: "subscription",
      x: (index % 3) * 2.2,
      y: Math.floor(index / 3) * 4,
      w: 2,
      h: 3.5,
    }));
    const children = groups.flatMap((group, groupIndex) => Array.from(
      { length: 4 },
      (_, childIndex) => ({
        id: `resource-${groupIndex}-${childIndex}`,
        type: "app-service",
        name: `resource-${groupIndex}-${childIndex}`,
        status: "healthy",
        parent_id: group.id,
      }),
    ));
    const expanded = constrainGraph({
      ...GRAPH,
      resources: [
        { id: "subscription", type: "subscription", name: "subscription", status: "healthy", x: 0, y: 0, w: 17.3, h: 11.3 },
        ...groups,
        ...children,
      ],
    });
    const expandedGroups = expanded.resources.filter((resource) => resource.type === "resource-group");
    const expandedChildren = expanded.resources.filter((resource) => resource.type === "app-service");

    expect(expandedGroups.every((group) => (group.w ?? 0) >= 4.8)).toBe(true);
    expect(expandedChildren.every((resource) => (resource.render_scale ?? 0) >= 1)).toBe(true);
    expect(graphSubset(expanded, new Set(["runtime"])).resources.every(
      (resource) => (resource.render_scale ?? 0) >= 1,
    )).toBe(true);
  });

  test("expands a dense resource group instead of shrinking its nodes", () => {
    const children = Array.from({ length: 80 }, (_, index) => ({
      id: `resource-${index}`,
      type: index === 0 ? "event-grid-topic" : "managed-identity",
      name: `resource-${index}`,
      status: "healthy",
      parent_id: "group-0",
    }));
    const expanded = constrainGraph({
      ...GRAPH,
      resources: [
        { id: "subscription", type: "subscription", name: "subscription", status: "healthy", x: 0, y: 0, w: 17.3, h: 11.3 },
        ...Array.from({ length: 3 }, (_, index) => ({
          id: `group-${index}`,
          type: "resource-group",
          name: `group-${index}`,
          status: "healthy",
          parent_id: "subscription",
          x: index * 5,
          y: 1,
          w: 4,
          h: 8,
        })),
        ...children,
      ],
    });
    const subscription = expanded.resources[0]!;
    const group = expanded.resources.find((resource) => resource.id === "group-0")!;
    const denseChildren = expanded.resources.filter((resource) => resource.parent_id === "group-0");

    expect(subscription.h).toBeGreaterThan(11.3);
    expect(group.h).toBeGreaterThan(16);
    expect(denseChildren.every((resource) => (resource.render_scale ?? 0) >= 1)).toBe(true);
    expect(new Set(denseChildren.map((resource) => `${resource.x}:${resource.y}`)).size)
      .toBe(denseChildren.length);
  });

  test("preserves authored layouts that contain nested regions", () => {
    const graph = {
      ...GRAPH,
      resources: [
        { id: "subscription", type: "subscription", name: "subscription", status: "healthy", x: 0, y: 0, w: 17.3, h: 11.3 },
        ...Array.from({ length: 3 }, (_, index) => ({
          id: `group-${index}`,
          type: "resource-group",
          name: `group-${index}`,
          status: "healthy",
          parent_id: "subscription",
          x: index * 5,
          y: 1,
          w: 4,
          h: 8,
        })),
        { id: "network", type: "virtual-network", name: "network", status: "healthy", parent_id: "group-0", x: 1, y: 2, w: 3, h: 4 },
      ],
    };

    expect(expandSimpleResourceGroupPanels(graph as InventoryGraphResponse).resources)
      .toEqual(graph.resources);
  });
});
