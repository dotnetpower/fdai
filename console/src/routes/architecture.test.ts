import { describe, expect, it, vi } from "vitest";
import { ReadApiError } from "../api";
import {
  architectureResourceExists,
  architectureViewExists,
  formatAge,
  loadArchitectureGraph,
} from "./architecture";

describe("architecture resource selection", () => {
  it("advances snapshot age from an explicit clock", () => {
    const snapshot = "2026-07-17T09:00:00Z";
    expect(formatAge(snapshot, Date.parse("2026-07-17T09:00:05Z"))).toBe("5s ago");
    expect(formatAge(snapshot, Date.parse("2026-07-17T09:02:00Z"))).toBe("2m ago");
  });

  const resources = [{ id: "web-api" }, { id: "event-worker" }];

  it("accepts an empty or present selection", () => {
    expect(architectureResourceExists(resources, null)).toBe(true);
    expect(architectureResourceExists(resources, "web-api")).toBe(true);
  });

  it("rejects an explicit resource outside the current graph", () => {
    expect(architectureResourceExists(resources, "missing-resource")).toBe(false);
  });
});

describe("architecture view selection", () => {
  const graph = {
    active_view: "fdai-control-plane",
    views: [
      { id: "fdai-control-plane", label: "FDAI", kind: "fdai" as const, classification: "ownership_tag" as const, description: "", root_resource_id: "fdai" },
      { id: "commerce-api", label: "Commerce", kind: "service" as const, classification: "service_tag" as const, description: "", root_resource_id: "commerce" },
    ],
  };

  it("accepts the default, active, and registered views", () => {
    expect(architectureViewExists(graph, null)).toBe(true);
    expect(architectureViewExists(graph, "fdai-control-plane")).toBe(true);
    expect(architectureViewExists(graph, "commerce-api")).toBe(true);
  });

  it("rejects a backend fallback for an unknown explicit view", () => {
    expect(architectureViewExists(graph, "production")).toBe(false);
  });

  it("reloads the default graph after a named-view 404", async () => {
    const panel = vi.fn()
      .mockRejectedValueOnce(new ReadApiError(404, "view not found"))
      .mockResolvedValueOnce(graph);

    await expect(loadArchitectureGraph({ panel }, "production")).resolves.toBe(graph);
    expect(panel).toHaveBeenNthCalledWith(1, "/inventory/graph", {
      depth: "4",
      include: "contains,attached_to,depends_on",
      scope: "production",
    });
    expect(panel).toHaveBeenNthCalledWith(2, "/inventory/graph", {
      depth: "4",
      include: "contains,attached_to,depends_on",
    });
  });
});
