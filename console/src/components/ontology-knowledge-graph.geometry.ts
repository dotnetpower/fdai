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

export interface KnowledgeGraphArrowHead {
  readonly tip: KnowledgeGraphPoint;
  readonly left: KnowledgeGraphPoint;
  readonly right: KnowledgeGraphPoint;
}

export interface KnowledgeGraphSelfLoop {
  readonly start: KnowledgeGraphPoint;
  readonly control: KnowledgeGraphPoint;
  readonly end: KnowledgeGraphPoint;
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

export function ontologySettledScreenPoint(
  point: KnowledgeGraphPoint,
  center: KnowledgeGraphPoint,
  progress: number,
  seed: string,
): KnowledgeGraphPoint {
  if (progress === 1) return point;
  const hash = [...seed].reduce(
    (total, character) => (total * 31 + character.charCodeAt(0)) >>> 0,
    0,
  );
  const angle = hash % 360 * Math.PI / 180;
  const displacement = 1 - progress;
  const radialScale = .82 + .18 * progress;
  const drift = 8 * displacement;
  return {
    x: center.x + (point.x - center.x) * radialScale + Math.cos(angle) * drift,
    y: center.y + (point.y - center.y) * radialScale + Math.sin(angle) * drift,
  };
}

export function ontologyScreenToWorld(
  point: KnowledgeGraphPoint,
  camera: KnowledgeGraphCamera,
): KnowledgeGraphPoint {
  return { x: (point.x - camera.x) / camera.scale, y: (point.y - camera.y) / camera.scale };
}

export function ontologyArrowHead(
  control: KnowledgeGraphPoint,
  target: KnowledgeGraphPoint,
  targetRadius: number,
  size: number,
): KnowledgeGraphArrowHead {
  const deltaX = target.x - control.x;
  const deltaY = target.y - control.y;
  const distance = Math.max(1, Math.hypot(deltaX, deltaY));
  const unitX = deltaX / distance;
  const unitY = deltaY / distance;
  const tip = {
    x: target.x - unitX * targetRadius,
    y: target.y - unitY * targetRadius,
  };
  const base = {
    x: tip.x - unitX * size,
    y: tip.y - unitY * size,
  };
  const wing = size * .62;
  return {
    tip,
    left: { x: base.x + unitY * wing, y: base.y - unitX * wing },
    right: { x: base.x - unitY * wing, y: base.y + unitX * wing },
  };
}

export function ontologySelfLoop(
  center: KnowledgeGraphPoint,
  radius: number,
): KnowledgeGraphSelfLoop {
  const startAngle = -Math.PI / 3;
  const endAngle = Math.PI / 6;
  return {
    start: {
      x: center.x + Math.cos(startAngle) * radius,
      y: center.y + Math.sin(startAngle) * radius,
    },
    control: {
      x: center.x + radius * 3,
      y: center.y - radius * 3,
    },
    end: {
      x: center.x + Math.cos(endAngle) * radius,
      y: center.y + Math.sin(endAngle) * radius,
    },
  };
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
