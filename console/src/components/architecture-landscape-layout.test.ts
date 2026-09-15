import { describe, expect, it } from "vitest";
import {
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
});
