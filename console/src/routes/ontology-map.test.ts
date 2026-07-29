import { describe, expect, it, vi } from "vitest";
import {
  loadOntologyMapGraph,
  normalizeOntologyMapRoot,
  ontologyMapRootAction,
  ontologyMapTruncationReasonLabel,
} from "./ontology-map";

describe("ontology resource map", () => {
  it("normalizes a bounded resource root", () => {
    expect(normalizeOntologyMapRoot("  resource-a  ")).toBe("resource-a");
    expect(normalizeOntologyMapRoot("   ")).toBeNull();
    expect(normalizeOntologyMapRoot("x".repeat(513))).toBeNull();
  });

  it("does not request inventory without a root", async () => {
    const panel = vi.fn();

    await expect(loadOntologyMapGraph({ panel }, null)).resolves.toBeNull();
    expect(panel).not.toHaveBeenCalled();
  });

  it("retries the current root without adding duplicate history", () => {
    expect(ontologyMapRootAction("resource-a", "resource-a")).toBe("reload");
    expect(ontologyMapRootAction("resource-a", "resource-b")).toBe("navigate");
    expect(ontologyMapRootAction(null, "resource-a")).toBe("navigate");
  });

  it("loads only the bounded neighborhood around the selected root", async () => {
    const graph = {
      resources: [{ id: "resource-a", type: "test", name: "A", status: "healthy" }],
      links: [],
    };
    const panel = vi.fn().mockResolvedValue(graph);

    await expect(loadOntologyMapGraph({ panel }, "resource-a")).resolves.toBe(graph);
    expect(panel).toHaveBeenCalledWith("/inventory/graph", {
      root: "resource-a",
      depth: "2",
      limit: "200",
      include: "contains,attached_to,depends_on",
    });
  });

  it("rejects a provider response that omits the requested root", async () => {
    const panel = vi.fn().mockResolvedValue({ resources: [], links: [] });

    await expect(loadOntologyMapGraph({ panel }, "resource-a"))
      .rejects.toThrow("requested inventory root is absent");
  });

  it("keeps unknown truncation reasons readable", () => {
    expect(ontologyMapTruncationReasonLabel("resource_limit")).not.toContain("ontology.map");
    expect(ontologyMapTruncationReasonLabel("future_limit")).toContain("future_limit");
  });
});
