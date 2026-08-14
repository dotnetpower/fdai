import { describe, expect, it } from "vitest";
import {
  fitOntologyKnowledgeGraph,
  hitTestOntologyNode,
  ontologyArrowHead,
  ontologySelfLoop,
  ontologySettledScreenPoint,
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

  it("places an arrowhead before the target node boundary", () => {
    const arrow = ontologyArrowHead(
      { x: 50, y: 0 },
      { x: 100, y: 0 },
      12,
      6,
    );

    expect(arrow.tip).toEqual({ x: 88, y: 0 });
    expect(arrow.left.x).toBeLessThan(arrow.tip.x);
    expect(arrow.right.x).toBeLessThan(arrow.tip.x);
    expect(arrow.left.y).toBeLessThan(0);
    expect(arrow.right.y).toBeGreaterThan(0);
  });

  it("creates a visible self-loop outside the node boundary", () => {
    const loop = ontologySelfLoop({ x: 100, y: 100 }, 14);

    expect(loop.start).not.toEqual(loop.end);
    expect(loop.control.x).toBeGreaterThan(114);
    expect(loop.control.y).toBeLessThan(86);
    expect(Math.hypot(loop.start.x - 100, loop.start.y - 100)).toBeGreaterThanOrEqual(14);
    expect(Math.hypot(loop.end.x - 100, loop.end.y - 100)).toBeGreaterThanOrEqual(14);
  });

  it("settles deterministically onto the exact layout point", () => {
    const point = { x: 180, y: 120 };
    const center = { x: 100, y: 100 };
    const initial = ontologySettledScreenPoint(point, center, 0, "node-a");

    expect(initial).toEqual(ontologySettledScreenPoint(point, center, 0, "node-a"));
    expect(Math.hypot(initial.x - center.x, initial.y - center.y)).toBeLessThan(
      Math.hypot(point.x - center.x, point.y - center.y),
    );
    expect(ontologySettledScreenPoint(point, center, 1, "node-a")).toEqual(point);
  });
});
