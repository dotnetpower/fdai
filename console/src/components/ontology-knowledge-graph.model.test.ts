import { describe, expect, it } from "vitest";
import {
  ONTOLOGY_EDGE_KINDS,
  ONTOLOGY_NODE_KINDS,
  decodeOntologyKnowledgeGraph,
  ontologyKnowledgeGraphSummary,
} from "./ontology-knowledge-graph.model";

const nodes = ONTOLOGY_NODE_KINDS.map((kind, index) => ({
  id: `node-${index}`,
  label: kind,
  kind,
  group: "test",
  detail: `${kind} detail`,
  community: 1,
  degree: index + 1,
  x: index * 20,
  y: index * 10,
}));
const rawGraph = {
  schemaVersion: "2.0.0",
  generatedFrom: "test projection",
  ontologyReleaseDigest: `sha256:${"1".repeat(64)}`,
  mutationAuthority: false,
  nodes,
  edges: ONTOLOGY_EDGE_KINDS.map((kind, index) => ({
    id: `edge-${kind}`,
    source: nodes[0]!.id,
    target: nodes[index + 1]!.id,
    kind,
    label: kind,
  })),
};

describe("ontology knowledge graph model", () => {
  it("decodes the complete generated catalog topology", () => {
    const graph = decodeOntologyKnowledgeGraph(rawGraph);
    const summary = ontologyKnowledgeGraphSummary(graph);

    expect(summary.nodes).toBe(ONTOLOGY_NODE_KINDS.length);
    expect(summary.edges).toBe(ONTOLOGY_EDGE_KINDS.length);
    expect(summary.communities).toBe(1);
    expect(summary.actions).toBe(1);
    expect(summary.agents).toBe(1);
    expect(summary.topHub?.degree).toBe(ONTOLOGY_NODE_KINDS.length);
    expect(graph.ontologyReleaseDigest).toMatch(/^sha256:[a-f0-9]{64}$/);
    expect(graph.mutationAuthority).toBe(false);
    expect(graph.nodes.some((node) => node.kind === "interface_type")).toBe(true);
    expect(graph.nodes.some((node) => node.kind === "function_type")).toBe(true);
    expect(new Set(graph.nodes.map((node) => node.kind))).toEqual(new Set(ONTOLOGY_NODE_KINDS));
    expect(new Set(graph.edges.map((edge) => edge.kind))).toEqual(new Set(ONTOLOGY_EDGE_KINDS));
  });

  it("rejects edges whose endpoint is absent", () => {
    expect(() => decodeOntologyKnowledgeGraph({
      schemaVersion: "1",
      generatedFrom: "test",
      ontologyReleaseDigest: `sha256:${"0".repeat(64)}`,
      mutationAuthority: false,
      nodes: [],
      edges: [{ id: "edge", source: "missing", target: "missing", kind: "agent", label: "owns" }],
    })).toThrow("missing endpoint");
  });
});
