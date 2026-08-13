import { describe, expect, it } from "vitest";
import {
  fitOntologyKnowledgeGraph,
  hitTestOntologyNode,
  ontologyWorldToScreen,
} from "./ontology-knowledge-graph.geometry";
import type { OntologyKnowledgeGraph } from "./ontology-knowledge-graph.model";

const graph: OntologyKnowledgeGraph = {
  schemaVersion: "1",
  generatedFrom: "test",
  ontologyReleaseDigest: `sha256:${"0".repeat(64)}`,
  mutationAuthority: false,
  nodes: [
    { id: "left", label: "Left", kind: "rule", group: "Rules", detail: "Left", community: 1, degree: 2, x: 0, y: 0 },
    { id: "right", label: "Right", kind: "action_type", group: "Actions", detail: "Right", community: 1, degree: 2, x: 100, y: 50 },
  ],
  edges: [{ id: "edge", source: "left", target: "right", kind: "rule_dispatch", label: "remediates" }],
};

describe("ontology knowledge graph geometry", () => {
  it("fits every node into a bounded viewport", () => {
    const camera = fitOntologyKnowledgeGraph(graph, 800, 500);
    const points = graph.nodes.map((node) => ontologyWorldToScreen(node, camera));

    expect(points.every((point) => point.x >= 0 && point.x <= 800)).toBe(true);
    expect(points.every((point) => point.y >= 0 && point.y <= 500)).toBe(true);
  });

  it("hit-tests the nearest visible node", () => {
    const camera = fitOntologyKnowledgeGraph(graph, 800, 500);
    const point = ontologyWorldToScreen(graph.nodes[1]!, camera);

    expect(hitTestOntologyNode(graph, camera, point)?.id).toBe("right");
  });
});
