import type {
  NetworkBoundaryRole,
  NetworkConnectionKind,
  NetworkDirection,
  NetworkEvidencePosture,
  NetworkLayoutPreset,
  NetworkPolicy,
  NetworkTrafficClass,
} from "@fdai/network-topology-contracts";

export type Locale = "en" | "ko";
export type Direction = "RIGHT" | "DOWN";
export type LocalizedText = Record<Locale, string>;
export type DiagramKind =
  | "context"
  | "container"
  | "component"
  | "deployment"
  | "data-flow"
  | "flowchart"
  | "graph"
  | "network"
  | "conceptual-flow"
  | "sequence"
  | "swimlane"
  | "state"
  | "decision-tree"
  | "domain"
  | "entity-relationship"
  | "timeline"
  | "gantt"
  | "class-diagram"
  | "user-journey"
  | "pie"
  | "quadrant"
  | "requirement"
  | "git-graph"
  | "c4-context"
  | "c4-container"
  | "c4-component"
  | "c4-deployment"
  | "mindmap"
  | "sankey"
  | "xy-chart"
  | "block"
  | "packet"
  | "kanban"
  | "architecture"
  | "radar"
  | "venn"
  | "wardley"
  | "cynefin"
  | "railroad"
  | "ishikawa"
  | "event-modeling"
  | "tree-view";

export type DiagramNodeShape =
  | "card"
  | "diamond"
  | "terminator"
  | "database"
  | "document"
  | "circle"
  | "bar"
  | "pie-slice";

export type DiagramNodeStatus =
  | "planned"
  | "active"
  | "done"
  | "critical"
  | "milestone";

export type DiagramTone =
  | "input"
  | "interpretation"
  | "model"
  | "policy"
  | "decision"
  | "execution"
  | "feedback"
  | "store"
  | "neutral";

export interface DiagramDocumentText {
  title: string;
  description: string;
  alt: string;
}

export interface DiagramGroup {
  id: string;
  parent?: string;
  kind: "system" | "cloud" | "region" | "network" | "subnet" | "cluster" | "layer";
  presentation?: "boundary" | "band" | "panel" | "lane" | "sidebar" | "feedback" | "datastore";
  label: LocalizedText;
  description?: LocalizedText;
  direction?: Direction;
  layout?: "flow" | "row" | "column" | "free";
  gap?: number;
  justify?: "start" | "center" | "space-between";
  placement?: "top" | "below" | "right";
  placementGap?: number;
  alignWith?: string;
  width?: number;
  networkRole?: NetworkBoundaryRole;
  addressPrefixes?: string[];
  region?: string;
  availabilityZones?: string[];
}

export interface DiagramPort {
  id: string;
  side: "NORTH" | "EAST" | "SOUTH" | "WEST";
}

export interface DiagramNode {
  id: string;
  parent?: string;
  kind: "azure-service" | "service" | "process" | "store" | "external" | "person" | "agent" | "decision";
  presentation?: "card" | "icon";
  shape?: DiagramNodeShape;
  tone?: DiagramTone;
  badge?: number;
  icon?: string;
  resourceType?: string;
  label: LocalizedText;
  description?: LocalizedText;
  content?: LocalizedText[];
  start?: number | string;
  end?: number | string;
  duration?: number;
  after?: string;
  status?: DiagramNodeStatus;
  progress?: number;
  value?: number;
  xValue?: number;
  yValue?: number;
  size?: number;
  row?: number;
  column?: number;
  width?: number;
  height?: number;
  ports?: DiagramPort[];
  networkRole?: NetworkBoundaryRole;
  addresses?: string[];
  listener?: string;
  sku?: string;
  securityFacts?: LocalizedText[];
}

export type EdgeKind =
  | "request"
  | "event"
  | "approval"
  | "mutation"
  | "audit"
  | "rollback"
  | "read"
  | "write"
  | "feedback"
  | "sequence"
  | "transition"
  | "association"
  | "dependency"
  | "timeline";

export interface DiagramEdge {
  id: string;
  from: string;
  to: string;
  kind: EdgeKind;
  label?: LocalizedText;
  protocol?: string;
  route?:
    | "diagonal"
    | "curve"
    | "orthogonal"
    | "orthogonal-shortest"
    | "orthogonal-horizontal"
    | "orthogonal-trunk"
    | "orthogonal-top"
    | "orthogonal-above"
    | "orthogonal-gap"
    | "orthogonal-right"
    | "orthogonal-outer"
    | "orthogonal-approval";
  lane?: number;
  step?: number;
  weight?: number;
  connectionKind?: NetworkConnectionKind;
  direction?: NetworkDirection;
  trafficClass?: NetworkTrafficClass;
  policy?: NetworkPolicy;
  port?: string;
  nextHop?: string;
  sourceEvidence?: Extract<NetworkEvidencePosture, "expected">;
}

export interface DiagramAnnotation {
  id: string;
  title: LocalizedText;
  body: LocalizedText[];
  tone: "information" | "policy";
  placement: "top-left" | "top-right" | "bottom-left" | "bottom-right";
  anchor?: string;
}

export interface DiagramSpec {
  id: string;
  version: number;
  kind: DiagramKind;
  posture?: "expected";
  updated?: string;
  formats?: Array<"svg" | "png">;
  locales: Record<Locale, DiagramDocumentText>;
  canvas: {
    width: number;
    height: number;
    direction: Direction;
    rootLayout?: "row" | "column";
    xAxis?: LocalizedText;
    yAxis?: LocalizedText;
    padding?: number;
    profile?: "default" | "azure-reference" | "network-azure-reference" | "conceptual";
    networkPreset?: NetworkLayoutPreset;
  };
  groups: DiagramGroup[];
  nodes: DiagramNode[];
  edges: DiagramEdge[];
  annotations?: DiagramAnnotation[];
  legend?: Array<
    | { kind: EdgeKind; tone?: never; label: LocalizedText }
    | { kind?: never; tone: DiagramTone; label: LocalizedText }
  >;
  references?: Array<{ label: LocalizedText; url: string }>;
}

/** Returns whether a profile uses compact Azure reference geometry. */
export function isReferenceDiagramProfile(
  profile: DiagramSpec["canvas"]["profile"],
): boolean {
  return profile === "azure-reference" || profile === "network-azure-reference";
}
