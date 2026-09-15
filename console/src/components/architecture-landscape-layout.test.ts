import { describe, expect, it } from "vitest";
import {
  ARCHITECTURE_LANDSCAPE_GROUP_LIMIT,
  ARCHITECTURE_SCOPE_DETAIL_LIMIT,
  architectureLandscapeOverviewGraph,
  architectureScopeDetailGraph,
  layoutGeometrylessArchitectureGraph,
} from "./architecture-landscape-layout";
import type { InventoryGraphResponse } from "./architecture-map.model";

const RAW_GRAPH: InventoryGraphResponse = {
  snapshot_at: "2026-09-15T00:00:00Z",
  freshness: "fresh",
  scope: null,
  depth: 4,
  included_link_types: ["contains", "depends_on"],
  truncated: true,
  resources: [
    { id: "subscription", type: "subscription", name: "Example subscription", status: "unknown" },
    { id: "group-a", type: "resource-group", name: "Workload A", status: "unknown", parent_id: "subscription" },
    { id: "group-b", type: "resource-group", name: "Workload B", status: "unknown", parent_id: "subscription" },
    { id: "app", type: "app-service", name: "Application", status: "healthy", parent_id: "group-a" },
    { id: "data", type: "postgresql", name: "Database", status: "healthy", parent_id: "group-b" },
  ],
  links: [
    { source: "subscription", target: "group-a", type: "contains" },
    { source: "subscription", target: "group-b", type: "contains" },
    { source: "app", target: "data", type: "depends_on" },
  ],
};

describe("geometry-less Architecture inventory", () => {
  it("generates finite regions and distinct Resource positions", () => {
    const laidOut = layoutGeometrylessArchitectureGraph(RAW_GRAPH);
    const subscription = laidOut.resources.find((resource) => resource.id === "subscription")!;
    const groups = laidOut.resources.filter((resource) => resource.type === "resource-group");
    const nodes = laidOut.resources.filter((resource) =>
      resource.type !== "subscription" && resource.type !== "resource-group");

    expect(subscription).toMatchObject({ x: 0, y: 0 });
    expect(subscription.w).toBeGreaterThan(0);
    expect(subscription.h).toBeGreaterThan(0);
    expect(groups.every((resource) =>
      Number.isFinite(resource.x)
      && Number.isFinite(resource.y)
      && Number.isFinite(resource.w)
      && Number.isFinite(resource.h))).toBe(true);
    expect(new Set(nodes.map((resource) => `${resource.x}:${resource.y}`)).size)
      .toBe(nodes.length);
  });

  it("bounds the Landscape to the largest returned Resource Group scopes", () => {
    const groups = Array.from({ length: 24 }, (_, index) => ({
      id: `group-${index}`,
      type: "resource-group",
      name: `Group ${index.toString().padStart(2, "0")}`,
      status: "unknown",
      parent_id: "subscription",
    }));
    const resources = groups.flatMap((group, groupIndex) =>
      Array.from({ length: groupIndex + 1 }, (_, resourceIndex) => ({
        id: `${group.id}-resource-${resourceIndex}`,
        type: "app-service",
        name: `Resource ${resourceIndex}`,
        status: "healthy",
        parent_id: group.id,
      })));
    const overview = architectureLandscapeOverviewGraph({
      ...RAW_GRAPH,
      resources: [RAW_GRAPH.resources[0]!, ...groups, ...resources],
      links: [],
    });
    const visibleGroups = overview.resources.filter((resource) =>
      resource.type === "resource-group");

    expect(visibleGroups).toHaveLength(ARCHITECTURE_LANDSCAPE_GROUP_LIMIT);
    expect(visibleGroups[0]?.collapsed_count).toBeGreaterThan(0);
    expect(visibleGroups.some((resource) => resource.id === "group-23")).toBe(true);
    expect(visibleGroups.some((resource) => resource.id === "group-0")).toBe(false);
  });

  it("keeps selected scope context and type diversity inside the detail bound", () => {
    const resources = Array.from({ length: 80 }, (_, index) => ({
      id: `resource-${index}`,
      type: index % 2 === 0 ? "app-service" : "postgresql",
      name: `Resource ${index.toString().padStart(2, "0")}`,
      status: "healthy",
      parent_id: "group-a",
    }));
    const detail = architectureScopeDetailGraph({
      ...RAW_GRAPH,
      resources: [
        RAW_GRAPH.resources[0]!,
        RAW_GRAPH.resources[1]!,
        ...resources,
        { id: "related", type: "event-hub", name: "Related", status: "healthy", parent_id: "group-a" },
      ],
      links: [{ source: "resource-79", target: "related", type: "depends_on" }],
    }, "resource-79");
    const ids = new Set(detail.resources.map((resource) => resource.id));

    expect(ids.has("subscription")).toBe(true);
    expect(ids.has("group-a")).toBe(true);
    expect(ids.has("resource-79")).toBe(true);
    expect(ids.has("related")).toBe(true);
    expect(detail.resources.length).toBeLessThanOrEqual(ARCHITECTURE_SCOPE_DETAIL_LIMIT + 8);
    expect(new Set(detail.resources.map((resource) => resource.type))).toEqual(
      new Set(["subscription", "resource-group", "app-service", "postgresql", "event-hub"]),
    );
  });

  it("counts cross-scope relationships without rewriting their endpoints", () => {
    const overview = architectureLandscapeOverviewGraph(RAW_GRAPH);
    const groupA = overview.resources.find((resource) => resource.id === "group-a")!;
    const groupB = overview.resources.find((resource) => resource.id === "group-b")!;

    expect(groupA.external_link_count).toBe(1);
    expect(groupB.external_link_count).toBe(1);
    expect(overview.links).toEqual([
      { source: "subscription", target: "group-a", type: "contains" },
      { source: "subscription", target: "group-b", type: "contains" },
    ]);
  });
});
