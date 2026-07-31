import type {
  OntologyKnowledgeEdge,
  OntologyKnowledgeGraph,
  OntologyKnowledgeNode,
} from "./ontology-knowledge-graph.model";

export interface KnowledgeGraphCamera {
  x: number;
  y: number;
  scale: number;
}

export interface KnowledgeGraphPoint {
  readonly x: number;
  readonly y: number;
}

export interface KnowledgeGraphIndex {
  readonly nodeById: ReadonlyMap<string, OntologyKnowledgeNode>;
  readonly adjacency: ReadonlyMap<string, readonly OntologyKnowledgeEdge[]>;
}

export function cloneOntologyKnowledgeGraph(graph: OntologyKnowledgeGraph): OntologyKnowledgeGraph {
  return { ...graph, nodes: graph.nodes.map((node) => ({ ...node })), edges: [...graph.edges] };
}

export function indexOntologyKnowledgeGraph(graph: OntologyKnowledgeGraph): KnowledgeGraphIndex {
  const nodeById = new Map(graph.nodes.map((node) => [node.id, node]));
  const adjacency = new Map(graph.nodes.map((node) => [node.id, [] as OntologyKnowledgeEdge[]]));
  for (const edge of graph.edges) {
    adjacency.get(edge.source)?.push(edge);
    adjacency.get(edge.target)?.push(edge);
  }
  return { nodeById, adjacency };
}

export function ontologyNodeRadius(node: OntologyKnowledgeNode): number {
  return Math.min(18, 4.5 + Math.sqrt(node.degree) * 1.45);
}

export function ontologyWorldToScreen(
  node: Pick<OntologyKnowledgeNode, "x" | "y">,
  camera: KnowledgeGraphCamera,
): KnowledgeGraphPoint {
  return { x: node.x * camera.scale + camera.x, y: node.y * camera.scale + camera.y };
}

export function ontologyScreenToWorld(
  point: KnowledgeGraphPoint,
  camera: KnowledgeGraphCamera,
): KnowledgeGraphPoint {
  return { x: (point.x - camera.x) / camera.scale, y: (point.y - camera.y) / camera.scale };
}

export function fitOntologyKnowledgeGraph(
  graph: OntologyKnowledgeGraph,
  width: number,
  height: number,
): KnowledgeGraphCamera {
  if (graph.nodes.length === 0) return { x: width / 2, y: height / 2, scale: 1 };
  const xs = graph.nodes.map((node) => node.x);
  const ys = graph.nodes.map((node) => node.y);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const scale = Math.max(.18, Math.min((width - 70) / Math.max(1, maxX - minX), (height - 70) / Math.max(1, maxY - minY)));
  return {
    scale,
    x: (width - (minX + maxX) * scale) / 2,
    y: (height - (minY + maxY) * scale) / 2,
  };
}

export function hitTestOntologyNode(
  graph: OntologyKnowledgeGraph,
  camera: KnowledgeGraphCamera,
  point: KnowledgeGraphPoint,
): OntologyKnowledgeNode | null {
  let best: OntologyKnowledgeNode | null = null;
  let bestDistance = Number.POSITIVE_INFINITY;
  for (const node of graph.nodes) {
    const position = ontologyWorldToScreen(node, camera);
    const distance = Math.hypot(point.x - position.x, point.y - position.y);
    const threshold = Math.max(8, ontologyNodeRadius(node) * Math.max(.7, camera.scale) + 4);
    if (distance <= threshold && distance < bestDistance) {
      best = node;
      bestDistance = distance;
    }
  }
  return best;
}

export function convexHull(points: readonly KnowledgeGraphPoint[]): readonly KnowledgeGraphPoint[] {
  if (points.length < 3) return points;
  const sorted = [...points].sort((left, right) => left.x - right.x || left.y - right.y);
  const cross = (origin: KnowledgeGraphPoint, left: KnowledgeGraphPoint, right: KnowledgeGraphPoint) =>
    (left.x - origin.x) * (right.y - origin.y) - (left.y - origin.y) * (right.x - origin.x);
  const lower: KnowledgeGraphPoint[] = [];
  const upper: KnowledgeGraphPoint[] = [];
  for (const point of sorted) {
    while (lower.length >= 2 && cross(lower[lower.length - 2]!, lower[lower.length - 1]!, point) <= 0) lower.pop();
    lower.push(point);
  }
  for (const point of [...sorted].reverse()) {
    while (upper.length >= 2 && cross(upper[upper.length - 2]!, upper[upper.length - 1]!, point) <= 0) upper.pop();
    upper.push(point);
  }
  lower.pop();
  upper.pop();
  return lower.concat(upper);
}
