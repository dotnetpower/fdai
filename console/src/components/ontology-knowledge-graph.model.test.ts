import { describe, expect, it } from "vitest";
import rawGraph from "../generated/ontology-knowledge-graph.json";
import {
  ONTOLOGY_EDGE_KINDS,
  ONTOLOGY_NODE_KINDS,
  decodeOntologyKnowledgeGraph,
  ontologyKnowledgeGraphSummary,
} from "./ontology-knowledge-graph.model";

describe("ontology knowledge graph model", () => {
  it("decodes the complete generated catalog topology", () => {
    const graph = decodeOntologyKnowledgeGraph(rawGraph);
    const summary = ontologyKnowledgeGraphSummary(graph);

    expect(summary.nodes).toBeGreaterThan(200);
    expect(summary.edges).toBeGreaterThan(500);
    expect(summary.communities).toBe(12);
    expect(summary.actions).toBeGreaterThan(40);
    expect(summary.agents).toBe(15);
    expect(summary.topHub?.degree).toBeGreaterThan(60);
    expect(new Set(graph.nodes.map((node) => node.kind))).toEqual(new Set(ONTOLOGY_NODE_KINDS));
    expect(new Set(graph.edges.map((edge) => edge.kind))).toEqual(new Set(ONTOLOGY_EDGE_KINDS));
  });

  it("rejects edges whose endpoint is absent", () => {
    expect(() => decodeOntologyKnowledgeGraph({
      schemaVersion: "1",
      generatedFrom: "test",
      nodes: [],
      edges: [{ id: "edge", source: "missing", target: "missing", kind: "agent", label: "owns" }],
    })).toThrow("missing endpoint");
  });
});
