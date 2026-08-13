import {
  convexHull,
  ontologyNodeRadius,
  ontologyWorldToScreen,
  type KnowledgeGraphCamera,
  type KnowledgeGraphIndex,
  type KnowledgeGraphPoint,
} from "./ontology-knowledge-graph.geometry";
import type {
  OntologyKnowledgeEdge,
  OntologyKnowledgeEdgeKind,
  OntologyKnowledgeGraph,
  OntologyKnowledgeNode,
  OntologyKnowledgeNodeKind,
} from "./ontology-knowledge-graph.model";

export const ONTOLOGY_NODE_STYLES: Readonly<Record<OntologyKnowledgeNodeKind, { readonly label: string; readonly fill: string }>> = {
  object_type: { label: "ObjectType", fill: "#44688e" },
  interface_type: { label: "InterfaceType", fill: "#57758f" },
  function_type: { label: "FunctionType", fill: "#9b7048" },
  resource_type: { label: "ResourceType", fill: "#4f847e" },
  rule: { label: "Rule", fill: "#7b6c9c" },
  action_type: { label: "ActionType", fill: "#bc7449" },
  workflow: { label: "Workflow", fill: "#a58a4a" },
  agent: { label: "Agent", fill: "#5e8259" },
  signal_type: { label: "SignalType", fill: "#a65d67" },
  property: { label: "Property", fill: "#6e747b" },
};

const EDGE_COLORS: Readonly<Record<OntologyKnowledgeEdgeKind, string>> = {
  link_type: "#4f847e",
  interface: "#57758f",
  instance_of: "#a5a8ab",
  rule_dispatch: "#6f88a5",
  workflow: "#7b6c9c",
  agent: "#bc7449",
};

export interface OntologyKnowledgeGraphPalette {
  readonly background: string;
  readonly grid: string;
  readonly foreground: string;
  readonly muted: string;
  readonly labelBackground: string;
  readonly nodeStroke: string;
  readonly selected: string;
  readonly hovered: string;
  readonly hull: string;
  readonly hullStroke: string;
  readonly selectedHull: string;
}

export interface OntologyKnowledgeGraphRenderState {
  readonly graph: OntologyKnowledgeGraph;
  readonly index: KnowledgeGraphIndex;
  readonly camera: KnowledgeGraphCamera;
  readonly selectedId: string | null;
  readonly hoveredId: string | null;
  readonly enabledEdges: ReadonlySet<OntologyKnowledgeEdgeKind>;
  readonly palette: OntologyKnowledgeGraphPalette;
}

type VisualState = "selected" | "hovered" | "related" | "normal" | "muted";

function nodeState(node: OntologyKnowledgeNode, state: OntologyKnowledgeGraphRenderState): VisualState {
  if (node.id === state.selectedId) return "selected";
  if (node.id === state.hoveredId) return "hovered";
  if (state.selectedId === null) return "normal";
  return state.index.adjacency.get(state.selectedId)?.some(
    (edge) => edge.source === node.id || edge.target === node.id,
  ) ? "related" : "muted";
}

function edgeState(edge: OntologyKnowledgeEdge, selectedId: string | null): "related" | "normal" | "muted" {
  if (selectedId === null) return "normal";
  return edge.source === selectedId || edge.target === selectedId ? "related" : "muted";
}

function drawGrid(context: CanvasRenderingContext2D, width: number, height: number, state: OntologyKnowledgeGraphRenderState): void {
  const spacing = Math.max(22, 70 * state.camera.scale);
  const offsetX = ((state.camera.x % spacing) + spacing) % spacing;
  const offsetY = ((state.camera.y % spacing) + spacing) % spacing;
  context.beginPath();
  for (let x = offsetX; x < width; x += spacing) { context.moveTo(x, 0); context.lineTo(x, height); }
  for (let y = offsetY; y < height; y += spacing) { context.moveTo(0, y); context.lineTo(width, y); }
  context.strokeStyle = state.palette.grid;
  context.lineWidth = 1;
  context.stroke();
}

function drawCommunities(context: CanvasRenderingContext2D, state: OntologyKnowledgeGraphRenderState): void {
  const groups = new Map<number, KnowledgeGraphPoint[]>();
  for (const node of state.graph.nodes) {
    const points = groups.get(node.community) ?? [];
    points.push(ontologyWorldToScreen(node, state.camera));
    groups.set(node.community, points);
  }
  const selectedCommunity = state.selectedId === null
    ? null
    : state.index.nodeById.get(state.selectedId)?.community ?? null;
  for (const [community, points] of groups) {
    const baseHull = convexHull(points);
    if (baseHull.length === 0) continue;
    const total = baseHull.reduce((sum, point) => ({ x: sum.x + point.x, y: sum.y + point.y }), { x: 0, y: 0 });
    const center = { x: total.x / baseHull.length, y: total.y / baseHull.length };
    const hull = baseHull.map((point) => {
      const deltaX = point.x - center.x;
      const deltaY = point.y - center.y;
      const distance = Math.max(1, Math.hypot(deltaX, deltaY));
      return { x: point.x + deltaX / distance * 22, y: point.y + deltaY / distance * 22 };
    });
    context.beginPath();
    hull.forEach((point, index) => index === 0 ? context.moveTo(point.x, point.y) : context.lineTo(point.x, point.y));
    context.closePath();
    context.fillStyle = community === selectedCommunity ? state.palette.selectedHull : state.palette.hull;
    context.fill();
    context.setLineDash([5, 6]);
    context.strokeStyle = community === selectedCommunity ? state.palette.selected : state.palette.hullStroke;
    context.lineWidth = community === selectedCommunity ? 1.5 : 1;
    context.stroke();
    context.setLineDash([]);
    if (state.camera.scale > .3) {
      const top = hull.reduce((best, point) => point.y < best.y ? point : best);
      context.font = "700 9px 'Segoe UI', sans-serif";
      context.textAlign = "left";
      context.textBaseline = "bottom";
      context.fillStyle = state.palette.muted;
      context.fillText(`C${community} / ${points.length}`, top.x, top.y - 3);
    }
  }
}

function drawEdge(context: CanvasRenderingContext2D, edge: OntologyKnowledgeEdge, state: OntologyKnowledgeGraphRenderState): void {
  if (!state.enabledEdges.has(edge.kind)) return;
  const sourceNode = state.index.nodeById.get(edge.source);
  const targetNode = state.index.nodeById.get(edge.target);
  if (!sourceNode || !targetNode) return;
  const source = ontologyWorldToScreen(sourceNode, state.camera);
  const target = ontologyWorldToScreen(targetNode, state.camera);
  const visualState = edgeState(edge, state.selectedId);
  const deltaX = target.x - source.x;
  const deltaY = target.y - source.y;
  const distance = Math.max(1, Math.hypot(deltaX, deltaY));
  const direction = [...edge.id].reduce((total, character) => total + character.charCodeAt(0), 0) % 2 ? 1 : -1;
  const bend = Math.min(24, distance * .08) * direction;
  const controlX = (source.x + target.x) / 2 - deltaY / distance * bend;
  const controlY = (source.y + target.y) / 2 + deltaX / distance * bend;
  context.beginPath();
  context.moveTo(source.x, source.y);
  context.quadraticCurveTo(controlX, controlY, target.x, target.y);
  context.strokeStyle = EDGE_COLORS[edge.kind];
  context.globalAlpha = visualState === "related" ? .82 : visualState === "muted" ? .018 : .10;
  context.lineWidth = visualState === "related" ? 2 : 1;
  context.stroke();
  if (visualState === "related" && state.camera.scale > .5) {
    const middleX = .25 * source.x + .5 * controlX + .25 * target.x;
    const middleY = .25 * source.y + .5 * controlY + .25 * target.y;
    context.globalAlpha = 1;
    context.font = "10px 'Cascadia Code', Consolas, monospace";
    context.textAlign = "center";
    context.textBaseline = "bottom";
    const labelWidth = context.measureText(edge.label).width + 8;
    context.fillStyle = state.palette.labelBackground;
    context.fillRect(middleX - labelWidth / 2, middleY - 13, labelWidth, 14);
    context.fillStyle = state.palette.muted;
    context.fillText(edge.label, middleX, middleY - 2);
  }
}

function drawNode(context: CanvasRenderingContext2D, node: OntologyKnowledgeNode, state: OntologyKnowledgeGraphRenderState): void {
  const position = ontologyWorldToScreen(node, state.camera);
  const visualState = nodeState(node, state);
  const radius = Math.max(3.2, ontologyNodeRadius(node) * Math.min(1.15, Math.max(.65, state.camera.scale)));
  context.globalAlpha = visualState === "muted" ? .11 : 1;
  if (visualState === "selected" || visualState === "hovered") {
    context.beginPath();
    context.arc(position.x, position.y, radius + 3, 0, Math.PI * 2);
    context.strokeStyle = visualState === "selected" ? state.palette.selected : state.palette.hovered;
    context.lineWidth = 2;
    context.stroke();
  }
  context.beginPath();
  context.arc(position.x, position.y, radius, 0, Math.PI * 2);
  context.fillStyle = ONTOLOGY_NODE_STYLES[node.kind].fill;
  context.fill();
  context.strokeStyle = state.palette.nodeStroke;
  context.lineWidth = 1.5;
  context.stroke();
}

interface LabelBox { readonly left: number; readonly right: number; readonly top: number; readonly bottom: number }

function drawNodeLabel(context: CanvasRenderingContext2D, node: OntologyKnowledgeNode, boxes: LabelBox[], state: OntologyKnowledgeGraphRenderState): void {
  const position = ontologyWorldToScreen(node, state.camera);
  const visualState = nodeState(node, state);
  if (!(visualState === "selected" || visualState === "hovered" || visualState === "related" || node.degree >= 8 || state.camera.scale > 1.05)) return;
  const radius = Math.max(3.2, ontologyNodeRadius(node) * Math.min(1.15, Math.max(.65, state.camera.scale)));
  context.globalAlpha = visualState === "muted" ? .18 : 1;
  context.font = `${visualState === "selected" ? "700" : "600"} 11px 'Segoe UI', sans-serif`;
  context.textAlign = "center";
  context.textBaseline = "top";
  const label = node.label.length > 28 ? `${node.label.slice(0, 26)}..` : node.label;
  const width = context.measureText(label).width + 8;
  const box = { left: position.x - width / 2, right: position.x + width / 2, top: position.y + radius + 3, bottom: position.y + radius + 18 };
  const overlaps = boxes.some((other) => box.left < other.right + 3 && box.right > other.left - 3 && box.top < other.bottom + 2 && box.bottom > other.top - 2);
  if (overlaps && visualState !== "selected" && visualState !== "hovered") return;
  boxes.push(box);
  context.fillStyle = state.palette.labelBackground;
  context.fillRect(box.left, box.top, width, 15);
  context.fillStyle = state.palette.foreground;
  context.fillText(label, position.x, box.top + 2);
}

export function renderOntologyKnowledgeGraph(
  context: CanvasRenderingContext2D,
  width: number,
  height: number,
  state: OntologyKnowledgeGraphRenderState,
): void {
  context.clearRect(0, 0, width, height);
  context.fillStyle = state.palette.background;
  context.fillRect(0, 0, width, height);
  drawGrid(context, width, height, state);
  const ordered = [...state.graph.nodes].sort((left, right) => left.degree - right.degree);
  const priority: Readonly<Record<VisualState, number>> = { selected: 4, hovered: 3, related: 2, normal: 1, muted: 0 };
  const labels = [...ordered].reverse().sort((left, right) => priority[nodeState(right, state)] - priority[nodeState(left, state)] || right.degree - left.degree);
  drawCommunities(context, state);
  state.graph.edges.forEach((edge) => drawEdge(context, edge, state));
  ordered.forEach((node) => drawNode(context, node, state));
  const labelBoxes: LabelBox[] = [];
  labels.forEach((node) => drawNodeLabel(context, node, labelBoxes, state));
  context.globalAlpha = 1;
}
