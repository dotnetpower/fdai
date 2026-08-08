import type {
  DiagramGroup,
  DiagramKind,
  Direction,
  EdgeKind,
} from "./types.js";

export type DiagramLayoutStrategy =
  | "layered"
  | "sequence"
  | "swimlane"
  | "state"
  | "tree"
  | "domain"
  | "timeline"
  | "gantt"
  | "coordinate"
  | "radial"
  | "grid";

export interface DiagramDefinition {
  kind: DiagramKind;
  layoutStrategy: DiagramLayoutStrategy;
  hierarchyHandling: "INCLUDE_CHILDREN" | "SEPARATE_CHILDREN";
  direction?: Direction;
  groupDirection?: Direction;
  edgeRouting?: "ORTHOGONAL" | "POLYLINE";
  nodeSpacing?: number;
  layerSpacing?: number;
  rootLayout?: "row" | "column";
  requiredEdgeKind?: EdgeKind;
  requiredGroupPresentation?: DiagramGroup["presentation"];
}

const diagramDefinitions: Record<DiagramKind, DiagramDefinition> = {
  context: {
    kind: "context",
    layoutStrategy: "layered",
    hierarchyHandling: "SEPARATE_CHILDREN",
  },
  container: {
    kind: "container",
    layoutStrategy: "layered",
    hierarchyHandling: "SEPARATE_CHILDREN",
  },
  component: {
    kind: "component",
    layoutStrategy: "layered",
    hierarchyHandling: "SEPARATE_CHILDREN",
  },
  deployment: {
    kind: "deployment",
    layoutStrategy: "layered",
    hierarchyHandling: "INCLUDE_CHILDREN",
  },
  "data-flow": {
    kind: "data-flow",
    layoutStrategy: "layered",
    hierarchyHandling: "SEPARATE_CHILDREN",
  },
  flowchart: {
    kind: "flowchart",
    layoutStrategy: "layered",
    hierarchyHandling: "SEPARATE_CHILDREN",
  },
  graph: {
    kind: "graph",
    layoutStrategy: "layered",
    hierarchyHandling: "SEPARATE_CHILDREN",
  },
  network: {
    kind: "network",
    layoutStrategy: "layered",
    hierarchyHandling: "SEPARATE_CHILDREN",
  },
  "conceptual-flow": {
    kind: "conceptual-flow",
    layoutStrategy: "layered",
    hierarchyHandling: "SEPARATE_CHILDREN",
  },
  sequence: {
    kind: "sequence",
    layoutStrategy: "sequence",
    hierarchyHandling: "SEPARATE_CHILDREN",
    direction: "DOWN",
    edgeRouting: "ORTHOGONAL",
    nodeSpacing: 42,
    layerSpacing: 64,
    requiredEdgeKind: "sequence",
  },
  swimlane: {
    kind: "swimlane",
    layoutStrategy: "swimlane",
    hierarchyHandling: "SEPARATE_CHILDREN",
    direction: "RIGHT",
    groupDirection: "DOWN",
    edgeRouting: "ORTHOGONAL",
    nodeSpacing: 34,
    layerSpacing: 54,
    rootLayout: "row",
    requiredGroupPresentation: "lane",
  },
  state: {
    kind: "state",
    layoutStrategy: "state",
    hierarchyHandling: "SEPARATE_CHILDREN",
    direction: "RIGHT",
    edgeRouting: "POLYLINE",
    nodeSpacing: 44,
    layerSpacing: 58,
    requiredEdgeKind: "transition",
  },
  "decision-tree": {
    kind: "decision-tree",
    layoutStrategy: "tree",
    hierarchyHandling: "SEPARATE_CHILDREN",
    direction: "DOWN",
    edgeRouting: "ORTHOGONAL",
    nodeSpacing: 48,
    layerSpacing: 70,
  },
  domain: {
    kind: "domain",
    layoutStrategy: "domain",
    hierarchyHandling: "SEPARATE_CHILDREN",
    direction: "RIGHT",
    edgeRouting: "POLYLINE",
    nodeSpacing: 52,
    layerSpacing: 64,
    requiredEdgeKind: "association",
  },
  "entity-relationship": {
    kind: "entity-relationship",
    layoutStrategy: "domain",
    hierarchyHandling: "SEPARATE_CHILDREN",
    direction: "RIGHT",
    edgeRouting: "POLYLINE",
    nodeSpacing: 52,
    layerSpacing: 64,
    requiredEdgeKind: "association",
  },
  timeline: {
    kind: "timeline",
    layoutStrategy: "timeline",
    hierarchyHandling: "SEPARATE_CHILDREN",
    direction: "RIGHT",
    edgeRouting: "ORTHOGONAL",
    nodeSpacing: 38,
    layerSpacing: 72,
    requiredEdgeKind: "timeline",
  },
  gantt: {
    kind: "gantt",
    layoutStrategy: "gantt",
    hierarchyHandling: "SEPARATE_CHILDREN",
    direction: "RIGHT",
  },
  "class-diagram": {
    kind: "class-diagram", layoutStrategy: "domain", hierarchyHandling: "SEPARATE_CHILDREN", direction: "RIGHT", edgeRouting: "POLYLINE",
  },
  "user-journey": {
    kind: "user-journey", layoutStrategy: "swimlane", hierarchyHandling: "SEPARATE_CHILDREN", direction: "RIGHT", groupDirection: "DOWN", rootLayout: "row",
  },
  pie: {
    kind: "pie", layoutStrategy: "radial", hierarchyHandling: "SEPARATE_CHILDREN",
  },
  quadrant: {
    kind: "quadrant", layoutStrategy: "coordinate", hierarchyHandling: "SEPARATE_CHILDREN",
  },
  requirement: {
    kind: "requirement", layoutStrategy: "domain", hierarchyHandling: "SEPARATE_CHILDREN", direction: "RIGHT", edgeRouting: "POLYLINE",
  },
  "git-graph": {
    kind: "git-graph", layoutStrategy: "timeline", hierarchyHandling: "SEPARATE_CHILDREN", direction: "RIGHT", edgeRouting: "ORTHOGONAL",
  },
  "c4-context": {
    kind: "c4-context", layoutStrategy: "layered", hierarchyHandling: "SEPARATE_CHILDREN",
  },
  "c4-container": {
    kind: "c4-container", layoutStrategy: "layered", hierarchyHandling: "SEPARATE_CHILDREN",
  },
  "c4-component": {
    kind: "c4-component", layoutStrategy: "layered", hierarchyHandling: "SEPARATE_CHILDREN",
  },
  "c4-deployment": {
    kind: "c4-deployment", layoutStrategy: "layered", hierarchyHandling: "INCLUDE_CHILDREN",
  },
  mindmap: {
    kind: "mindmap", layoutStrategy: "tree", hierarchyHandling: "SEPARATE_CHILDREN", direction: "RIGHT", edgeRouting: "POLYLINE",
  },
  sankey: {
    kind: "sankey", layoutStrategy: "layered", hierarchyHandling: "SEPARATE_CHILDREN", direction: "RIGHT", edgeRouting: "POLYLINE",
  },
  "xy-chart": {
    kind: "xy-chart", layoutStrategy: "coordinate", hierarchyHandling: "SEPARATE_CHILDREN",
  },
  block: {
    kind: "block", layoutStrategy: "grid", hierarchyHandling: "SEPARATE_CHILDREN",
  },
  packet: {
    kind: "packet", layoutStrategy: "grid", hierarchyHandling: "SEPARATE_CHILDREN",
  },
  kanban: {
    kind: "kanban", layoutStrategy: "grid", hierarchyHandling: "SEPARATE_CHILDREN",
  },
  architecture: {
    kind: "architecture", layoutStrategy: "layered", hierarchyHandling: "INCLUDE_CHILDREN",
  },
  radar: {
    kind: "radar", layoutStrategy: "radial", hierarchyHandling: "SEPARATE_CHILDREN",
  },
  venn: {
    kind: "venn", layoutStrategy: "coordinate", hierarchyHandling: "SEPARATE_CHILDREN",
  },
  wardley: {
    kind: "wardley", layoutStrategy: "coordinate", hierarchyHandling: "SEPARATE_CHILDREN",
  },
  cynefin: {
    kind: "cynefin", layoutStrategy: "grid", hierarchyHandling: "SEPARATE_CHILDREN",
  },
  railroad: {
    kind: "railroad", layoutStrategy: "sequence", hierarchyHandling: "SEPARATE_CHILDREN", direction: "RIGHT", edgeRouting: "ORTHOGONAL",
  },
  ishikawa: {
    kind: "ishikawa", layoutStrategy: "tree", hierarchyHandling: "SEPARATE_CHILDREN", direction: "RIGHT", edgeRouting: "POLYLINE",
  },
  "event-modeling": {
    kind: "event-modeling", layoutStrategy: "timeline", hierarchyHandling: "SEPARATE_CHILDREN", direction: "RIGHT", edgeRouting: "ORTHOGONAL",
  },
  "tree-view": {
    kind: "tree-view", layoutStrategy: "tree", hierarchyHandling: "SEPARATE_CHILDREN", direction: "DOWN", edgeRouting: "ORTHOGONAL",
  },
};

export function diagramDefinition(kind: DiagramKind): DiagramDefinition {
  return diagramDefinitions[kind];
}

export function supportedDiagramKinds(): DiagramKind[] {
  return Object.keys(diagramDefinitions) as DiagramKind[];
}
