export type Locale = "en" | "ko";
export type Direction = "RIGHT" | "DOWN";
export type LocalizedText = Record<Locale, string>;

export interface DiagramDocumentText {
  title: string;
  description: string;
  alt: string;
}

export interface DiagramGroup {
  id: string;
  parent?: string;
  kind: "system" | "cloud" | "region" | "network" | "subnet" | "cluster" | "layer";
  label: LocalizedText;
  description?: LocalizedText;
  direction?: Direction;
  layout?: "flow" | "row" | "column" | "free";
  placement?: "below";
}

export interface DiagramPort {
  id: string;
  side: "NORTH" | "EAST" | "SOUTH" | "WEST";
}

export interface DiagramNode {
  id: string;
  parent?: string;
  kind: "azure-service" | "service" | "process" | "store" | "external" | "person" | "agent" | "decision";
  icon?: string;
  label: LocalizedText;
  description?: LocalizedText;
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
  | "write";

export interface DiagramEdge {
  id: string;
  from: string;
  to: string;
  kind: EdgeKind;
  label?: LocalizedText;
  protocol?: string;
  route?: "diagonal" | "curve";
}

export interface DiagramSpec {
  id: string;
  version: number;
  kind: "context" | "container" | "component" | "deployment" | "data-flow" | "network";
  updated?: string;
  locales: Record<Locale, DiagramDocumentText>;
  canvas: {
    width: number;
    height: number;
    direction: Direction;
    padding?: number;
  };
  groups: DiagramGroup[];
  nodes: DiagramNode[];
  edges: DiagramEdge[];
  legend?: Array<{ kind: EdgeKind; label: LocalizedText }>;
  references?: Array<{ label: LocalizedText; url: string }>;
}
