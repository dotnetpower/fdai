import type {
  ElkEdgeSection,
  ElkExtendedEdge,
  ElkNode,
  ElkPort,
} from "elkjs/lib/elk-api.js";
import { createRequire } from "node:module";

import type {
  DiagramGroup,
  DiagramNode,
  DiagramPort,
  DiagramSpec,
} from "../model/types.js";
import { edgeLabelGeometry, nodeGeometry } from "../model/text.js";

export interface PositionedShape {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
  depth: number;
}

export interface DiagramLayout {
  width: number;
  height: number;
  groups: Map<string, PositionedShape>;
  nodes: Map<string, PositionedShape>;
  edges: ElkExtendedEdge[];
}

const require = createRequire(import.meta.url);
const ElkConstructor = require("elkjs/lib/elk.bundled.js") as typeof import("elkjs/lib/elk-api.js").default;
const elk = new ElkConstructor();

function endpointNodeId(endpoint: string): string {
  return endpoint.split(":", 1)[0] ?? endpoint;
}

function endpointPortSide(
  spec: DiagramSpec,
  endpoint: string,
): DiagramPort["side"] | undefined {
  const [nodeId, portId] = endpoint.split(":", 2);
  if (!nodeId || !portId) return undefined;
  return spec.nodes
    .find((node) => node.id === nodeId)
    ?.ports?.find((port) => port.id === portId)?.side;
}

function bottomRouteSection(
  edgeId: string,
  source: PositionedShape,
  target: PositionedShape,
  laneY: number,
): ElkEdgeSection {
  const startPoint = {
    x: source.x + source.width / 2,
    y: source.y + source.height,
  };
  const endPoint = {
    x: target.x + target.width / 2,
    y: target.y + target.height,
  };
  return {
    id: `${edgeId}-bottom-route`,
    startPoint,
    bendPoints: [
      { x: startPoint.x, y: laneY },
      { x: endPoint.x, y: laneY },
    ],
    endPoint,
  };
}

function applyFixedSideRoutes(
  spec: DiagramSpec,
  edges: ElkExtendedEdge[],
  nodes: Map<string, PositionedShape>,
): { edges: ElkExtendedEdge[]; bottom: number } {
  let bottom = 0;
  const safeLaneY =
    Math.max(...[...nodes.values()].map((node) => node.y + node.height)) + 48;
  const routed = edges.map((edge) => {
    const specEdge = spec.edges.find((candidate) => candidate.id === edge.id);
    if (
      !specEdge ||
      endpointPortSide(spec, specEdge.from) !== "SOUTH" ||
      endpointPortSide(spec, specEdge.to) !== "SOUTH"
    ) {
      return edge;
    }
    const source = nodes.get(endpointNodeId(specEdge.from));
    const target = nodes.get(endpointNodeId(specEdge.to));
    if (!source || !target) return edge;
    const section = bottomRouteSection(edge.id, source, target, safeLaneY);
    const laneY = section.bendPoints?.[0]?.y ?? 0;
    bottom = Math.max(bottom, laneY);
    const routedLabels = edge.labels?.map((label) => ({
      ...label,
      x:
        ((section.bendPoints?.[0]?.x ?? section.startPoint.x) +
          (section.bendPoints?.[1]?.x ?? section.endPoint.x)) /
          2 -
        (label.width ?? 0) / 2,
      y: laneY - (label.height ?? 0) / 2,
    }));
    const next: ElkExtendedEdge = {
      ...edge,
      sections: [section],
      ...(routedLabels ? { labels: routedLabels } : {}),
    };
    delete next.container;
    return next;
  });
  return { edges: routed, bottom };
}

function nodePorts(node: DiagramNode): ElkPort[] | undefined {
  if (!node.ports?.length) return undefined;
  return node.ports.map((port) => ({
    id: `${node.id}:${port.id}`,
    width: 1,
    height: 1,
    layoutOptions: {
      "elk.port.side": port.side,
    },
  }));
}

function elementParent(spec: DiagramSpec, elementId: string): string {
  const node = spec.nodes.find((candidate) => candidate.id === elementId);
  if (node) return node.parent ?? "root";
  const group = spec.groups.find((candidate) => candidate.id === elementId);
  return group?.parent ?? "root";
}

function containerChain(spec: DiagramSpec, endpoint: string): string[] {
  const chain: string[] = [];
  let current = elementParent(spec, endpointNodeId(endpoint));
  while (true) {
    chain.push(current);
    if (current === "root") return chain;
    current = elementParent(spec, current);
  }
}

function edgeContainer(spec: DiagramSpec, edge: DiagramSpec["edges"][number]): string {
  const targetContainers = new Set(containerChain(spec, edge.to));
  return (
    containerChain(spec, edge.from).find((container) =>
      targetContainers.has(container),
    ) ?? "root"
  );
}

function elkEdge(edge: DiagramSpec["edges"][number]): ElkExtendedEdge {
  const label = edgeLabelGeometry(edge);
  return {
    id: edge.id,
    sources: [edge.from],
    targets: [edge.to],
    ...(label
      ? {
          labels: [
            {
              id: `${edge.id}-label`,
              text: edge.label!.en,
              width: label.width,
              height: label.height,
            },
          ],
        }
      : {}),
  };
}

function edgesByContainer(spec: DiagramSpec): Map<string, ElkExtendedEdge[]> {
  const result = new Map<string, ElkExtendedEdge[]>();
  for (const edge of spec.edges) {
    const container = edgeContainer(spec, edge);
    const edges = result.get(container) ?? [];
    edges.push(elkEdge(edge));
    result.set(container, edges);
  }
  return result;
}

function diagramNodeToElk(node: DiagramNode): ElkNode {
  const ports = nodePorts(node);
  const geometry = nodeGeometry(node);
  return {
    id: node.id,
    width: geometry.width,
    height: geometry.height,
    ...(ports ? { ports } : {}),
    ...(ports
      ? { layoutOptions: { "elk.portConstraints": "FIXED_SIDE" } }
      : {}),
  };
}

function childrenForGroup(
  spec: DiagramSpec,
  group: DiagramGroup,
  containedEdges: Map<string, ElkExtendedEdge[]>,
): ElkNode[] {
  const childGroups = spec.groups
    .filter((candidate) => candidate.parent === group.id)
    .map((candidate) => groupToElk(spec, candidate, containedEdges));
  const childNodes = spec.nodes
    .filter((node) => node.parent === group.id)
    .map(diagramNodeToElk);
  return [...childGroups, ...childNodes];
}

function groupToElk(
  spec: DiagramSpec,
  group: DiagramGroup,
  containedEdges: Map<string, ElkExtendedEdge[]>,
): ElkNode {
  const edges = containedEdges.get(group.id);
  return {
    id: group.id,
    children: childrenForGroup(spec, group, containedEdges),
    ...(edges?.length ? { edges } : {}),
    layoutOptions: {
      "elk.algorithm": "layered",
      "elk.direction": group.direction ?? spec.canvas.direction,
      "elk.edgeRouting": "ORTHOGONAL",
      "elk.padding": "[top=52,left=28,bottom=28,right=28]",
      "elk.spacing.nodeNode": "22",
      "elk.layered.spacing.nodeNodeBetweenLayers": "36",
    },
  };
}

function collectShapes(
  node: ElkNode,
  groupIds: Set<string>,
  parentX: number,
  parentY: number,
  depth: number,
  groups: Map<string, PositionedShape>,
  nodes: Map<string, PositionedShape>,
  edges: ElkExtendedEdge[],
): void {
  const x = parentX + (node.x ?? 0);
  const y = parentY + (node.y ?? 0);
  if (node.id !== "root") {
    const shape = {
      id: node.id,
      x,
      y,
      width: node.width ?? 0,
      height: node.height ?? 0,
      depth,
    };
    if (groupIds.has(node.id)) groups.set(node.id, shape);
    else nodes.set(node.id, shape);
  }
  for (const edge of node.edges ?? []) {
    if (node.id === "root") {
      edges.push(edge);
    } else {
      edges.push({ ...edge, container: node.id });
    }
  }
  for (const child of node.children ?? []) {
    collectShapes(child, groupIds, x, y, depth + 1, groups, nodes, edges);
  }
}

function isDescendantGroup(
  spec: DiagramSpec,
  candidateId: string,
  ancestorId: string,
): boolean {
  let current = spec.groups.find((group) => group.id === candidateId)?.parent;
  while (current) {
    if (current === ancestorId) return true;
    current = spec.groups.find((group) => group.id === current)?.parent;
  }
  return false;
}

function nodeBelongsToGroup(
  spec: DiagramSpec,
  nodeId: string,
  groupId: string,
): boolean {
  let current = spec.nodes.find((node) => node.id === nodeId)?.parent;
  while (current) {
    if (current === groupId) return true;
    current = spec.groups.find((group) => group.id === current)?.parent;
  }
  return false;
}

function moveGroupTree(
  spec: DiagramSpec,
  groupId: string,
  deltaX: number,
  deltaY: number,
  groups: Map<string, PositionedShape>,
  nodes: Map<string, PositionedShape>,
): void {
  for (const candidate of groups.values()) {
    if (
      candidate.id === groupId ||
      isDescendantGroup(spec, candidate.id, groupId)
    ) {
      candidate.x += deltaX;
      candidate.y += deltaY;
    }
  }
  for (const node of nodes.values()) {
    if (nodeBelongsToGroup(spec, node.id, groupId)) {
      node.x += deltaX;
      node.y += deltaY;
    }
  }
}

function applyGroupPlacements(
  spec: DiagramSpec,
  groups: Map<string, PositionedShape>,
  nodes: Map<string, PositionedShape>,
): number {
  let bottom = 0;
  for (const groupSpec of spec.groups.filter(
    (group) => group.placement === "below" && group.parent,
  )) {
    const group = groups.get(groupSpec.id);
    const parent = groups.get(groupSpec.parent!);
    if (!group || !parent) continue;
    const siblingGroups = spec.groups.filter(
      (candidate) =>
        candidate.parent === groupSpec.parent && candidate.id !== groupSpec.id,
    );
    const directNodes = spec.nodes.filter(
      (candidate) => candidate.parent === groupSpec.parent,
    );
    const siblingTops = [
      ...siblingGroups
        .map((candidate) => groups.get(candidate.id)?.y)
        .filter((value): value is number => value !== undefined),
      ...directNodes
        .map((candidate) => nodes.get(candidate.id)?.y)
        .filter((value): value is number => value !== undefined),
    ];
    const compactDeltaY = siblingTops.length
      ? Math.min(0, parent.y + 52 - Math.min(...siblingTops))
      : 0;
    if (compactDeltaY) {
      for (const sibling of siblingGroups) {
        moveGroupTree(spec, sibling.id, 0, compactDeltaY, groups, nodes);
      }
      for (const nodeSpec of directNodes) {
        const node = nodes.get(nodeSpec.id);
        if (node) node.y += compactDeltaY;
      }
    }
    const siblingBottoms = [
      ...siblingGroups
        .map((candidate) => groups.get(candidate.id))
        .filter((shape): shape is PositionedShape => Boolean(shape))
        .map((shape) => shape.y + shape.height),
      ...directNodes
        .map((candidate) => nodes.get(candidate.id))
        .filter((shape): shape is PositionedShape => Boolean(shape))
        .map((shape) => shape.y + shape.height),
    ];
    const nextY = Math.max(parent.y + 52, ...siblingBottoms) + 24;
    const nextX = parent.x + (parent.width - group.width) / 2;
    const deltaX = nextX - group.x;
    const deltaY = nextY - group.y;

    moveGroupTree(spec, group.id, deltaX, deltaY, groups, nodes);

    const groupBottom = group.y + group.height;
    const childBottoms = [
      groupBottom,
      ...siblingGroups
        .map((candidate) => groups.get(candidate.id))
        .filter((shape): shape is PositionedShape => Boolean(shape))
        .map((shape) => shape.y + shape.height),
      ...directNodes
        .map((candidate) => nodes.get(candidate.id))
        .filter((shape): shape is PositionedShape => Boolean(shape))
        .map((shape) => shape.y + shape.height),
    ];
    parent.height = Math.max(...childBottoms) - parent.y + 28;
    bottom = Math.max(bottom, parent.y + parent.height);
  }
  return bottom;
}

function boundaryPoint(
  source: PositionedShape,
  target: PositionedShape,
): { x: number; y: number } {
  const sourceX = source.x + source.width / 2;
  const sourceY = source.y + source.height / 2;
  const targetX = target.x + target.width / 2;
  const targetY = target.y + target.height / 2;
  const deltaX = targetX - sourceX;
  const deltaY = targetY - sourceY;
  const scale = Math.min(
    deltaX ? source.width / 2 / Math.abs(deltaX) : Number.POSITIVE_INFINITY,
    deltaY ? source.height / 2 / Math.abs(deltaY) : Number.POSITIVE_INFINITY,
  );
  return {
    x: sourceX + deltaX * scale,
    y: sourceY + deltaY * scale,
  };
}

function applyExplicitRoutes(
  spec: DiagramSpec,
  edges: ElkExtendedEdge[],
  nodes: Map<string, PositionedShape>,
): ElkExtendedEdge[] {
  return edges.map((edge) => {
    const specEdge = spec.edges.find((candidate) => candidate.id === edge.id);
    if (
      !specEdge ||
      (specEdge.route !== "diagonal" && specEdge.route !== "curve")
    ) {
      return edge;
    }
    const source = nodes.get(endpointNodeId(specEdge.from));
    const target = nodes.get(endpointNodeId(specEdge.to));
    if (!source || !target) return edge;
    const startPoint = boundaryPoint(source, target);
    const endPoint = boundaryPoint(target, source);
    const labels = edge.labels?.map((label) => ({
      ...label,
      x: (startPoint.x + endPoint.x) / 2 - (label.width ?? 0) / 2,
      y: (startPoint.y + endPoint.y) / 2 - (label.height ?? 0) / 2,
    }));
    const next: ElkExtendedEdge = {
      ...edge,
      sections: [
        {
          id: `${edge.id}-diagonal-route`,
          startPoint,
          endPoint,
        },
      ],
      ...(labels ? { labels } : {}),
    };
    delete next.container;
    return next;
  });
}

export async function layoutDiagram(spec: DiagramSpec): Promise<DiagramLayout> {
  const containedEdges = edgesByContainer(spec);
  const rootGroups = spec.groups
    .filter((group) => !group.parent)
    .map((group) => groupToElk(spec, group, containedEdges));
  const rootNodes = spec.nodes
    .filter((node) => !node.parent)
    .map(diagramNodeToElk);
  const graph: ElkNode = {
    id: "root",
    children: [...rootGroups, ...rootNodes],
    edges: containedEdges.get("root") ?? [],
    layoutOptions: {
      "elk.algorithm": "layered",
      "elk.direction": spec.canvas.direction,
      "elk.edgeRouting": "ORTHOGONAL",
      "elk.hierarchyHandling": "SEPARATE_CHILDREN",
      "elk.padding": `[top=${spec.canvas.padding ?? 40},left=${spec.canvas.padding ?? 40},bottom=${spec.canvas.padding ?? 40},right=${spec.canvas.padding ?? 40}]`,
      "elk.spacing.nodeNode": "28",
      "elk.layered.spacing.nodeNodeBetweenLayers": "52",
      "elk.layered.considerModelOrder.strategy": "NODES_AND_EDGES",
    },
  };

  const result = await elk.layout(graph);
  const groups = new Map<string, PositionedShape>();
  const nodes = new Map<string, PositionedShape>();
  const edges: ElkExtendedEdge[] = [];
  collectShapes(
    result,
    new Set(spec.groups.map((group) => group.id)),
    0,
    0,
    0,
    groups,
    nodes,
    edges,
  );
  const placementBottom = applyGroupPlacements(spec, groups, nodes);
  const explicitRoutes = applyExplicitRoutes(spec, edges, nodes);
  const routed = applyFixedSideRoutes(spec, explicitRoutes, nodes);

  return {
    width: result.width ?? spec.canvas.width,
    height: Math.max(
      result.height ?? spec.canvas.height,
      placementBottom + 36,
      routed.bottom + 24,
    ),
    groups,
    nodes,
    edges: routed.edges,
  };
}
