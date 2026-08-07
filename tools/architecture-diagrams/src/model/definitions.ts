import type { DiagramKind } from "./types.js";

export type DiagramLayoutStrategy = "layered";

export interface DiagramDefinition {
  kind: DiagramKind;
  layoutStrategy: DiagramLayoutStrategy;
  hierarchyHandling: "INCLUDE_CHILDREN" | "SEPARATE_CHILDREN";
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
  network: {
    kind: "network",
    layoutStrategy: "layered",
    hierarchyHandling: "SEPARATE_CHILDREN",
  },
};

export function diagramDefinition(kind: DiagramKind): DiagramDefinition {
  return diagramDefinitions[kind];
}

export function supportedDiagramKinds(): DiagramKind[] {
  return Object.keys(diagramDefinitions) as DiagramKind[];
}
