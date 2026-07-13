import { describe, expect, test } from "vitest";
import {
  architectureHref,
  architectureViewFromHash,
  constrainGraph,
  graphSubset,
  layerOf,
  selectedResourceIdFromHash,
  shapeOf,
  type InventoryGraphResponse,
} from "./architecture-map.model";

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
  test("maps resource types to visual layers", () => {
    expect(layerOf(GRAPH.resources[1]!)).toBe("compute");
    expect(layerOf(GRAPH.resources[2]!)).toBe("data");
  });

  test("renders PostgreSQL as a cylinder and other resources as blocks", () => {
    expect(shapeOf(GRAPH.resources[2]!)).toBe("cylinder");
    expect(shapeOf(GRAPH.resources[1]!)).toBe("block");
  });

  test("filters resources and dangling links together", () => {
    const subset = graphSubset(GRAPH, new Set(["scope", "compute"]));
    expect(subset.resources.map((resource) => resource.id)).toEqual(["rg", "app"]);
    expect(subset.links).toEqual([{ source: "rg", target: "app", type: "contains" }]);
  });

  test("round-trips resource deep links", () => {
    expect(architectureHref("web api")).toBe("#/architecture?resource=web+api");
    expect(selectedResourceIdFromHash("#/architecture?resource=web%20api")).toBe("web api");
    expect(architectureHref("web-api", "commerce-api")).toBe("#/architecture?resource=web-api&view=commerce-api");
    expect(architectureViewFromHash("#/architecture?view=commerce-api")).toBe("commerce-api");
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
});