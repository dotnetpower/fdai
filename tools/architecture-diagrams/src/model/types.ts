export type Locale = "en" | "ko";
export type Direction = "RIGHT" | "DOWN";
export type LocalizedText = Record<Locale, string>;
export type DiagramKind =
  | "context"
  | "container"
  | "component"
  | "deployment"
  | "data-flow"
  | "network"
  | "conceptual-flow";

export type DiagramNodeShape =
  | "card"
  | "diamond"
  | "terminator"
  | "database"
  | "document"
  | "circle";

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
  label: LocalizedText;
  description?: LocalizedText;
  content?: LocalizedText[];
  width?: number;
  height?: number;
  ports?: DiagramPort[];
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
  | "feedback";

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
    | "orthogonal-right";
  lane?: number;
  step?: number;
}

export interface DiagramSpec {
  id: string;
  version: number;
  kind: DiagramKind;
  updated?: string;
  formats?: Array<"svg" | "png">;
  locales: Record<Locale, DiagramDocumentText>;
  canvas: {
    width: number;
    height: number;
    direction: Direction;
    rootLayout?: "row" | "column";
    padding?: number;
    profile?: "default" | "azure-reference" | "conceptual";
  };
  groups: DiagramGroup[];
  nodes: DiagramNode[];
  edges: DiagramEdge[];
  legend?: Array<
    | { kind: EdgeKind; tone?: never; label: LocalizedText }
    | { kind?: never; tone: DiagramTone; label: LocalizedText }
  >;
  references?: Array<{ label: LocalizedText; url: string }>;
}
