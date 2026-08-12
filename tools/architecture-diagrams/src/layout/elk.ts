import type {
  ElkEdgeSection,
  ElkExtendedEdge,
  ElkNode,
  ElkPoint,
  ElkPort,
} from "elkjs/lib/elk-api.js";
import { createRequire } from "node:module";

import { layoutGantt } from "./gantt.js";
import {
  layoutCoordinate,
  layoutGrid,
  layoutRadial,
} from "./specialized.js";
import type {
  DiagramGroup,
  DiagramNode,
  DiagramPort,
  DiagramSpec,
} from "../model/types.js";
import { diagramDefinition } from "../model/definitions.js";
import { edgeLabelGeometry, nodeGeometry } from "../model/text.js";

export interface PositionedShape {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
  depth: number;
  path?: string;
  paletteIndex?: number;
  labelX?: number;
  labelY?: number;
  labelWidth?: number;
  leader?: string;
}

export interface DiagramLayout {
  width: number;
  height: number;
  groups: Map<string, PositionedShape>;
  nodes: Map<string, PositionedShape>;
  edges: ElkExtendedEdge[];
  axis?: {
    minimum: number;
    maximum: number;
    x: number;
    width: number;
    kind: "number" | "date";
  };
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

function elkEdge(
  edge: DiagramSpec["edges"][number],
  compact: boolean,
): ElkExtendedEdge {
  const label = edgeLabelGeometry(edge, compact);
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
  const compact = spec.canvas.profile === "azure-reference";
  for (const edge of spec.edges) {
    const container = edgeContainer(spec, edge);
    const edges = result.get(container) ?? [];
    edges.push(elkEdge(edge, compact));
    result.set(container, edges);
  }
  return result;
}

function diagramNodeToElk(
  node: DiagramNode,
  compact: boolean,
  equalizedHeight?: number,
): ElkNode {
  const ports = nodePorts(node);
  const geometry = nodeGeometry(node, compact);
  return {
    id: node.id,
    width: geometry.width,
    height: equalizedHeight ?? geometry.height,
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
  directNodeHeight?: number,
): ElkNode[] {
  const compact = spec.canvas.profile === "azure-reference";
  const childGroupSpecs = spec.groups.filter((candidate) => candidate.parent === group.id);
  const peerNodeSpecs = childGroupSpecs.flatMap((candidate) => {
    const directNodes = spec.nodes.filter((node) => node.parent === candidate.id);
    return directNodes.length === 1 ? directNodes : [];
  });
  const peerNodeHeight = !compact &&
    group.layout === "row" &&
    childGroupSpecs.length > 1 &&
    peerNodeSpecs.length === childGroupSpecs.length
    ? Math.max(...peerNodeSpecs.map((node) => nodeGeometry(node, compact).height))
    : undefined;
  const childGroups = childGroupSpecs.map((candidate) =>
    groupToElk(spec, candidate, containedEdges, peerNodeHeight),
  );
  const childNodeSpecs = spec.nodes.filter((node) => node.parent === group.id);
  const equalizedHeight = directNodeHeight ?? (
    !compact && group.layout === "row" && childNodeSpecs.length > 1
    ? Math.max(...childNodeSpecs.map((node) => nodeGeometry(node, compact).height))
    : undefined
  );
  const childNodes = childNodeSpecs.map((node) =>
    diagramNodeToElk(node, compact, equalizedHeight),
  );
  return [...childGroups, ...childNodes];
}

function groupToElk(
  spec: DiagramSpec,
  group: DiagramGroup,
  containedEdges: Map<string, ElkExtendedEdge[]>,
  directNodeHeight?: number,
): ElkNode {
  const edges = containedEdges.get(group.id);
  const compact = spec.canvas.profile === "azure-reference";
  const definition = diagramDefinition(spec.kind);
  return {
    id: group.id,
    children: childrenForGroup(spec, group, containedEdges, directNodeHeight),
    ...(edges?.length ? { edges } : {}),
    layoutOptions: {
      "elk.algorithm": "layered",
      "elk.direction":
        group.direction ?? definition.groupDirection ?? definition.direction ?? spec.canvas.direction,
      "elk.edgeRouting": definition.edgeRouting ?? "ORTHOGONAL",
      "elk.padding": compact
        ? "[top=44,left=18,bottom=18,right=18]"
        : "[top=52,left=28,bottom=28,right=28]",
      "elk.spacing.nodeNode": String(
        definition.nodeSpacing ?? (compact ? 16 : 22),
      ),
      "elk.layered.spacing.nodeNodeBetweenLayers": String(
        group.layout === "flow" && group.gap !== undefined
          ? group.gap
          : definition.layerSpacing ?? (compact ? 28 : 36),
      ),
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

function groupDepth(spec: DiagramSpec, groupId: string): number {
  let depth = 0;
  let current = spec.groups.find((group) => group.id === groupId)?.parent;
  while (current) {
    depth += 1;
    current = spec.groups.find((group) => group.id === current)?.parent;
  }
  return depth;
}

function applyDirectLayouts(
  spec: DiagramSpec,
  groups: Map<string, PositionedShape>,
  nodes: Map<string, PositionedShape>,
): void {
  const compact = spec.canvas.profile === "azure-reference";
  const left = compact ? 18 : 28;
  const top = compact ? 44 : 52;
  const bottom = compact ? 18 : 28;
  const gap = compact ? 16 : 22;
  const explicitGroups = spec.groups
    .filter((group) => group.layout === "row" || group.layout === "column")
    .sort(
      (leftGroup, rightGroup) =>
        groupDepth(spec, rightGroup.id) - groupDepth(spec, leftGroup.id),
    );
  for (const groupSpec of explicitGroups) {
    const group = groups.get(groupSpec.id);
    const childGap = groupSpec.gap ?? gap;
    const children = [
      ...spec.groups
        .filter((child) => child.parent === groupSpec.id)
        .map((child) => groups.get(child.id)),
      ...spec.nodes
        .filter((node) => node.parent === groupSpec.id)
        .map((node) => nodes.get(node.id)),
    ].filter((child): child is PositionedShape => Boolean(child));
    if (!group || !children.length) continue;
    const moveChild = (child: PositionedShape, x: number, y: number): void => {
      if (groups.has(child.id)) {
        moveGroupTree(spec, child.id, x - child.x, y - child.y, groups, nodes);
      } else {
        child.x = x;
        child.y = y;
      }
    };
    if (groupSpec.layout === "row") {
      const contentHeight = Math.max(...children.map((node) => node.height));
      const contentWidth =
        children.reduce((total, node) => total + node.width, 0) +
        childGap * (children.length - 1);
      const naturalWidth =
        left * 2 + contentWidth;
      const targetWidth = Math.max(naturalWidth, groupSpec.width ?? 0);
      const justify = groupSpec.justify ?? "space-between";
      const rowGap = justify === "space-between" && children.length > 1
        ? childGap + (targetWidth - naturalWidth) / (children.length - 1)
        : childGap;
      let x = group.x + left;
      if (justify === "center") {
        x = group.x + (targetWidth - contentWidth) / 2;
      } else if (justify === "start") {
        x = group.x + left;
      }
      for (const child of children) {
        moveChild(
          child,
          x,
          group.y + top + (contentHeight - child.height) / 2,
        );
        x += child.width + rowGap;
      }
      group.width = targetWidth;
      group.height = top + contentHeight + bottom;
      continue;
    }
    const contentWidth = Math.max(...children.map((node) => node.width));
    const targetWidth = Math.max(left + contentWidth + left, groupSpec.width ?? 0);
    const innerWidth = targetWidth - left * 2;
    let y = group.y + top;
    for (const child of children) {
      moveChild(
        child,
        group.x + left + (innerWidth - child.width) / 2,
        y,
      );
      y += child.height + childGap;
    }
    group.width = targetWidth;
    group.height = y - childGap - group.y + bottom;
  }
}

function applyHorizontalAlignments(
  spec: DiagramSpec,
  groups: Map<string, PositionedShape>,
  nodes: Map<string, PositionedShape>,
): void {
  for (const groupSpec of spec.groups.filter(
    (group) => group.alignWith && !group.placement,
  )) {
    const group = groups.get(groupSpec.id);
    const alignment = groups.get(groupSpec.alignWith!);
    if (!group || !alignment) continue;
    const nextX = alignment.x + (alignment.width - group.width) / 2;
    moveGroupTree(spec, group.id, nextX - group.x, 0, groups, nodes);
  }
}

function applyGroupPlacements(
  spec: DiagramSpec,
  groups: Map<string, PositionedShape>,
  nodes: Map<string, PositionedShape>,
): number {
  let bottom = 0;
  const touchedParents = new Set<string>();
  for (const groupSpec of spec.groups.filter(
    (group) => group.placement === "top" && group.parent,
  )) {
    const group = groups.get(groupSpec.id);
    const parent = groups.get(groupSpec.parent!);
    if (!group || !parent) continue;
    const nextX = parent.x + 28;
    const nextY = parent.y + 49;
    moveGroupTree(
      spec,
      group.id,
      nextX - group.x,
      nextY - group.y,
      groups,
      nodes,
    );
    touchedParents.add(parent.id);
  }
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
    if (compactDeltaY && !groupSpec.alignWith) {
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
    const alignment = groupSpec.alignWith
      ? groups.get(groupSpec.alignWith)
      : parent;
    let containingAlignment = alignment;
    if (groupSpec.alignWith) {
      let currentId = groupSpec.alignWith;
      while (currentId) {
        const current = spec.groups.find(
          (candidate) => candidate.id === currentId,
        );
        if (!current?.parent || current.parent === parent.id) {
          containingAlignment = groups.get(currentId) ?? alignment;
          break;
        }
        currentId = current.parent;
      }
    }
    const nextY = groupSpec.alignWith && alignment
      ? Math.max(
          alignment.y + alignment.height,
          (containingAlignment?.y ?? alignment.y) +
            (containingAlignment?.height ?? alignment.height),
        ) + (groupSpec.placementGap ?? 24)
      : Math.max(parent.y + 52, ...siblingBottoms) +
        (groupSpec.placementGap ?? 24);
    const nextX = alignment
      ? alignment.x + (alignment.width - group.width) / 2
      : parent.x + (parent.width - group.width) / 2;
    const deltaX = nextX - group.x;
    const deltaY = nextY - group.y;

    moveGroupTree(spec, group.id, deltaX, deltaY, groups, nodes);
    touchedParents.add(parent.id);

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
  for (const groupSpec of spec.groups.filter(
    (group) => group.placement === "right" && group.parent,
  )) {
    const group = groups.get(groupSpec.id);
    const parent = groups.get(groupSpec.parent!);
    const alignment = groupSpec.alignWith
      ? groups.get(groupSpec.alignWith)
      : undefined;
    if (!group || !parent || !alignment) continue;
    const nextX = alignment.x + alignment.width + 24;
    const nextY = alignment.y;
    moveGroupTree(
      spec,
      group.id,
      nextX - group.x,
      nextY - group.y,
      groups,
      nodes,
    );
    touchedParents.add(parent.id);
    const childShapes = [
      ...spec.groups
        .filter((candidate) => candidate.parent === parent.id)
        .map((candidate) => groups.get(candidate.id))
        .filter((shape): shape is PositionedShape => Boolean(shape)),
      ...spec.nodes
        .filter((candidate) => candidate.parent === parent.id)
        .map((candidate) => nodes.get(candidate.id))
        .filter((shape): shape is PositionedShape => Boolean(shape)),
    ];
    parent.width = Math.max(
      parent.width,
      ...childShapes.map((shape) => shape.x + shape.width - parent.x + 28),
    );
    parent.height = Math.max(
      parent.height,
      ...childShapes.map((shape) => shape.y + shape.height - parent.y + 28),
    );
    bottom = Math.max(bottom, parent.y + parent.height);
  }
  for (const parentId of touchedParents) {
    const parent = groups.get(parentId);
    if (!parent) continue;
    const childShapes = [
      ...spec.groups
        .filter((candidate) => candidate.parent === parentId)
        .map((candidate) => groups.get(candidate.id))
        .filter((shape): shape is PositionedShape => Boolean(shape)),
      ...spec.nodes
        .filter((candidate) => candidate.parent === parentId)
        .map((candidate) => nodes.get(candidate.id))
        .filter((shape): shape is PositionedShape => Boolean(shape)),
    ];
    parent.width = Math.max(
      56,
      ...childShapes.map((shape) => shape.x + shape.width - parent.x + 28),
    );
    parent.height = Math.max(
      80,
      ...childShapes.map((shape) => shape.y + shape.height - parent.y + 28),
    );
    bottom = Math.max(bottom, parent.y + parent.height);
  }
  return bottom;
}

function applyRootGroupFlow(
  spec: DiagramSpec,
  groups: Map<string, PositionedShape>,
  nodes: Map<string, PositionedShape>,
): { width: number; bottom: number } | undefined {
  const definition = diagramDefinition(spec.kind);
  const configuredRootLayout = spec.canvas.rootLayout ?? definition.rootLayout;
  const implicitCompactColumn =
    spec.canvas.profile === "azure-reference" && spec.canvas.direction === "DOWN";
  if (!configuredRootLayout && !implicitCompactColumn) return undefined;
  const rootGroups = spec.groups
    .filter((group) => !group.parent)
    .map((group) => groups.get(group.id))
    .filter((group): group is PositionedShape => Boolean(group));
  if (!rootGroups.length) return undefined;
  const padding = spec.canvas.padding ?? 24;
  const gap = 38;
  const rootLayout = configuredRootLayout ??
    (spec.canvas.direction === "DOWN" ? "column" : "row");
  if (rootLayout === "row") {
    const contentHeight = Math.max(...rootGroups.map((group) => group.height));
    let x = padding;
    for (const group of rootGroups) {
      moveGroupTree(
        spec,
        group.id,
        x - group.x,
        padding - group.y,
        groups,
        nodes,
      );
      x += group.width + gap;
    }
    return {
      width: x - gap + padding,
      bottom: contentHeight + padding * 2,
    };
  }
  const contentWidth = Math.max(...rootGroups.map((group) => group.width));
  let y = padding;
  for (const group of rootGroups) {
    const x = padding + (contentWidth - group.width) / 2;
    moveGroupTree(spec, group.id, x - group.x, y - group.y, groups, nodes);
    y += group.height + gap;
  }
  return {
    width: contentWidth + padding * 2,
    bottom: y - gap + padding,
  };
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

function orthogonalRouteSection(
  edgeId: string,
  source: PositionedShape,
  target: PositionedShape,
  forceHorizontal = false,
): ElkEdgeSection {
  const sourceCenter = {
    x: source.x + source.width / 2,
    y: source.y + source.height / 2,
  };
  const targetCenter = {
    x: target.x + target.width / 2,
    y: target.y + target.height / 2,
  };
  const horizontal = forceHorizontal ||
    Math.abs(targetCenter.x - sourceCenter.x) >=
    Math.abs(targetCenter.y - sourceCenter.y);
  if (horizontal) {
    const targetIsRight = targetCenter.x >= sourceCenter.x;
    const startPoint = {
      x: targetIsRight ? source.x + source.width : source.x,
      y: sourceCenter.y,
    };
    const endPoint = {
      x: targetIsRight ? target.x : target.x + target.width,
      y: targetCenter.y,
    };
    if (startPoint.y === endPoint.y) {
      return { id: `${edgeId}-orthogonal-route`, startPoint, endPoint };
    }
    const laneX = (startPoint.x + endPoint.x) / 2;
    return {
      id: `${edgeId}-orthogonal-route`,
      startPoint,
      bendPoints: [
        { x: laneX, y: startPoint.y },
        { x: laneX, y: endPoint.y },
      ],
      endPoint,
    };
  }

  const targetIsBelow = targetCenter.y >= sourceCenter.y;
  const startPoint = {
    x: sourceCenter.x,
    y: targetIsBelow ? source.y + source.height : source.y,
  };
  const endPoint = {
    x: targetCenter.x,
    y: targetIsBelow ? target.y : target.y + target.height,
  };
  if (startPoint.x === endPoint.x) {
    return { id: `${edgeId}-orthogonal-route`, startPoint, endPoint };
  }
  const laneY = (startPoint.y + endPoint.y) / 2;
  return {
    id: `${edgeId}-orthogonal-route`,
    startPoint,
    bendPoints: [
      { x: startPoint.x, y: laneY },
      { x: endPoint.x, y: laneY },
    ],
    endPoint,
  };
}

function segmentCrossesNode(
  start: ElkPoint,
  end: ElkPoint,
  node: PositionedShape,
): boolean {
  const padding = 3;
  if (start.x === end.x) {
    return (
      start.x > node.x - padding &&
      start.x < node.x + node.width + padding &&
      Math.max(Math.min(start.y, end.y), node.y - padding) <
        Math.min(Math.max(start.y, end.y), node.y + node.height + padding)
    );
  }
  if (start.y === end.y) {
    return (
      start.y > node.y - padding &&
      start.y < node.y + node.height + padding &&
      Math.max(Math.min(start.x, end.x), node.x - padding) <
        Math.min(Math.max(start.x, end.x), node.x + node.width + padding)
    );
  }
  return true;
}

function orthogonalShortestRouteSection(
  edgeId: string,
  source: PositionedShape,
  target: PositionedShape,
  nodes: Map<string, PositionedShape>,
): ElkEdgeSection {
  const sourceCenter = {
    x: source.x + source.width / 2,
    y: source.y + source.height / 2,
  };
  const targetCenter = {
    x: target.x + target.width / 2,
    y: target.y + target.height / 2,
  };
  const targetIsRight = targetCenter.x >= sourceCenter.x;
  const targetIsBelow = targetCenter.y >= sourceCenter.y;
  const candidates: ElkEdgeSection[] = [
    {
      id: `${edgeId}-orthogonal-shortest-horizontal-first`,
      startPoint: {
        x: targetIsRight ? source.x + source.width : source.x,
        y: sourceCenter.y,
      },
      bendPoints: [{
        x: targetCenter.x,
        y: sourceCenter.y,
      }],
      endPoint: {
        x: targetCenter.x,
        y: targetIsBelow ? target.y : target.y + target.height,
      },
    },
    {
      id: `${edgeId}-orthogonal-shortest-vertical-sides`,
      startPoint: {
        x: sourceCenter.x,
        y: targetIsBelow ? source.y + source.height : source.y,
      },
      bendPoints: [
        {
          x: sourceCenter.x,
          y: (source.y + source.height + target.y) / 2,
        },
        {
          x: targetCenter.x,
          y: (source.y + source.height + target.y) / 2,
        },
      ],
      endPoint: {
        x: targetCenter.x,
        y: targetIsBelow ? target.y : target.y + target.height,
      },
    },
    {
      id: `${edgeId}-orthogonal-shortest-vertical-first`,
      startPoint: {
        x: sourceCenter.x,
        y: targetIsBelow ? source.y + source.height : source.y,
      },
      bendPoints: [{
        x: sourceCenter.x,
        y: targetCenter.y,
      }],
      endPoint: {
        x: targetIsRight ? target.x : target.x + target.width,
        y: targetCenter.y,
      },
    },
  ];
  const obstacles = [...nodes.values()].filter(
    (node) => node.id !== source.id && node.id !== target.id,
  );
  const clear = candidates.find((candidate) => {
    const points = [
      candidate.startPoint,
      ...(candidate.bendPoints ?? []),
      candidate.endPoint,
    ];
    return points.slice(1).every((end, index) =>
      obstacles.every(
        (node) => !segmentCrossesNode(points[index]!, end, node),
      ),
    );
  });
  return clear ?? orthogonalRouteSection(edgeId, source, target);
}

function orthogonalHorizontalRouteSection(
  edgeId: string,
  source: PositionedShape,
  target: PositionedShape,
  nodes: Map<string, PositionedShape>,
  laneIndex: number,
): ElkEdgeSection {
  const targetIsRight = target.x >= source.x;
  const startPoint = {
    x: targetIsRight ? source.x + source.width : source.x,
    y: source.y + source.height / 2,
  };
  const endPoint = {
    x: targetIsRight ? target.x : target.x + target.width,
    y: target.y + target.height / 2,
  };
  const candidates = [...nodes.values()].filter(
    (node) =>
      node.id !== source.id &&
      node.id !== target.id &&
      (targetIsRight
        ? node.x >= startPoint.x && node.x < endPoint.x
        : node.x + node.width <= startPoint.x && node.x > endPoint.x),
  );
  const nearestObstacle = targetIsRight
    ? Math.min(endPoint.x, ...candidates.map((node) => node.x))
    : Math.max(endPoint.x, ...candidates.map((node) => node.x + node.width));
  const laneX = (startPoint.x + nearestObstacle) / 2 +
    laneIndex * (targetIsRight ? 24 : -24);
  return {
    id: `${edgeId}-orthogonal-horizontal-route`,
    startPoint,
    bendPoints: [
      { x: laneX, y: startPoint.y },
      { x: laneX, y: endPoint.y },
    ],
    endPoint,
  };
}

function orthogonalTrunkRouteSection(
  edgeId: string,
  source: PositionedShape,
  target: PositionedShape,
  lane = 0,
  sourceOffset = 0,
  targetOffset = 0,
): ElkEdgeSection {
  const targetIsBelow = target.y >= source.y;
  const startPoint = {
    x: source.x + source.width / 2 + sourceOffset,
    y: targetIsBelow ? source.y + source.height : source.y,
  };
  const endPoint = {
    x: target.x + target.width / 2 + targetOffset,
    y: targetIsBelow ? target.y : target.y + target.height,
  };
  const direction = targetIsBelow ? 1 : -1;
  const trunkY = (startPoint.y + endPoint.y) / 2 + lane * 12 * direction;
  return {
    id: `${edgeId}-orthogonal-trunk-route`,
    startPoint,
    bendPoints: [
      { x: startPoint.x, y: trunkY },
      { x: endPoint.x, y: trunkY },
    ],
    endPoint,
  };
}

function trunkAnchorOffsets(
  spec: DiagramSpec,
  nodes: Map<string, PositionedShape>,
): Map<string, { source: number; target: number }> {
  const offsets = new Map<string, { source: number; target: number }>();
  const connections = new Map<
    string,
    Array<{ edgeId: string; endpoint: "source" | "target"; otherX: number }>
  >();
  for (const edge of spec.edges.filter(
    (candidate) => candidate.route === "orthogonal-trunk",
  )) {
    const sourceId = endpointNodeId(edge.from);
    const targetId = endpointNodeId(edge.to);
    const source = nodes.get(sourceId);
    const target = nodes.get(targetId);
    if (!source || !target) continue;
    const targetIsBelow = target.y >= source.y;
    for (const connection of [
      {
        key: `${sourceId}:${targetIsBelow ? "bottom" : "top"}`,
        endpoint: "source" as const,
        otherX: target.x + target.width / 2,
      },
      {
        key: `${targetId}:${targetIsBelow ? "top" : "bottom"}`,
        endpoint: "target" as const,
        otherX: source.x + source.width / 2,
      },
    ]) {
      const entries = connections.get(connection.key) ?? [];
      entries.push({ edgeId: edge.id, ...connection });
      connections.set(connection.key, entries);
    }
  }
  for (const [key, entries] of connections) {
    if (entries.length < 2) continue;
    const node = nodes.get(key.split(":", 1)[0]!);
    if (!node) continue;
    entries.sort((left, right) => left.otherX - right.otherX);
    const span = Math.min(node.width - 24, (entries.length - 1) * 14);
    entries.forEach((entry, index) => {
      const offset = -span / 2 + (span * index) / (entries.length - 1);
      const edgeOffsets = offsets.get(entry.edgeId) ?? { source: 0, target: 0 };
      edgeOffsets[entry.endpoint] = offset;
      offsets.set(entry.edgeId, edgeOffsets);
    });
  }
  return offsets;
}

function orthogonalTopRouteSection(
  edgeId: string,
  source: PositionedShape,
  target: PositionedShape,
  laneIndex: number,
): ElkEdgeSection {
  const laneY = -8 - laneIndex * 28;
  const startPoint = {
    x: source.x + source.width / 2,
    y: source.y,
  };
  const endPoint = {
    x: target.x + target.width / 2,
    y: target.y,
  };
  return {
    id: `${edgeId}-orthogonal-top-route`,
    startPoint,
    bendPoints: [
      { x: startPoint.x, y: laneY },
      { x: endPoint.x, y: laneY },
    ],
    endPoint,
  };
}

function orthogonalAboveRouteSection(
  edgeId: string,
  source: PositionedShape,
  target: PositionedShape,
  spec: DiagramSpec,
  nodes: Map<string, PositionedShape>,
  laneIndex: number,
): ElkEdgeSection {
  const sourceCenterY = source.y + source.height / 2;
  const targetCenterY = target.y + target.height / 2;
  const targetCenterX = target.x + target.width / 2;
  const sourceX = target.x >= source.x ? source.x + source.width : source.x;
  const sourceCorridorX = target.x >= source.x ? sourceX + 24 : sourceX - 24;
  const targetX = target.x >= source.x ? target.x : target.x + target.width;
  const corridorX = target.x >= source.x ? targetX - 16 : targetX + 16;
  const minimumX = Math.min(sourceCorridorX, corridorX);
  const maximumX = Math.max(sourceCorridorX, corridorX);
  const obstacleTop = Math.min(
    source.y,
    target.y,
    ...[...nodes.values()]
      .filter(
        (node) =>
          node.id !== source.id &&
          node.id !== target.id &&
          node.x < maximumX &&
          node.x + node.width > minimumX,
      )
      .map((node) => node.y),
  );
  const laneY = obstacleTop - 36 - laneIndex * 28;
  const verticalApproachBlocked = [...nodes.values()].some(
    (node) =>
      node.id !== source.id &&
      node.id !== target.id &&
      node.x < targetCenterX &&
      node.x + node.width > targetCenterX &&
      node.y < target.y &&
      node.y + node.height > laneY,
  );
  if (!verticalApproachBlocked) {
    return {
      id: `${edgeId}-orthogonal-above-route`,
      startPoint: { x: sourceX, y: sourceCenterY },
      bendPoints: [
        { x: sourceCorridorX, y: sourceCenterY },
        { x: sourceCorridorX, y: laneY },
        { x: targetCenterX, y: laneY },
      ],
      endPoint: { x: targetCenterX, y: target.y },
    };
  }
  const targetParent = spec.groups.find(
    (group) => group.id === elementParent(spec, target.id),
  );
  if (targetParent?.layout === "row") {
    const clearanceX = target.x >= source.x
      ? target.x - 8
      : target.x + target.width + 8;
    const approachY = target.y - 16;
    return {
      id: `${edgeId}-orthogonal-above-route`,
      startPoint: { x: sourceX, y: sourceCenterY },
      bendPoints: [
        { x: sourceCorridorX, y: sourceCenterY },
        { x: sourceCorridorX, y: laneY },
        { x: clearanceX, y: laneY },
        { x: clearanceX, y: approachY },
        { x: targetCenterX, y: approachY },
      ],
      endPoint: { x: targetCenterX, y: target.y },
    };
  }
  return {
    id: `${edgeId}-orthogonal-above-route`,
    startPoint: { x: sourceX, y: sourceCenterY },
    bendPoints: [
      { x: sourceCorridorX, y: sourceCenterY },
      { x: sourceCorridorX, y: laneY },
      { x: corridorX, y: laneY },
      { x: corridorX, y: targetCenterY },
    ],
    endPoint: { x: targetX, y: targetCenterY },
  };
}

function orthogonalRightRouteSection(
  edgeId: string,
  source: PositionedShape,
  target: PositionedShape,
  nodes: Map<string, PositionedShape>,
  laneIndex: number,
): ElkEdgeSection {
  const sourceCenterY = source.y + source.height / 2;
  const targetIsBelow = target.y >= source.y;
  const targetEntry = {
    x: target.x + target.width / 2,
    y: targetIsBelow ? target.y : target.y + target.height,
  };
  const approachY = targetEntry.y + (targetIsBelow ? -24 : 24);
  const minimumY = Math.min(sourceCenterY, approachY);
  const maximumY = Math.max(sourceCenterY, approachY);
  const obstacleRight = Math.max(
    source.x + source.width,
    target.x + target.width,
    ...[...nodes.values()]
      .filter(
        (node) =>
          node.id !== source.id &&
          node.id !== target.id &&
          node.y < maximumY &&
          node.y + node.height > minimumY,
      )
      .map((node) => node.x + node.width),
  );
  const corridorX = obstacleRight + 36 + laneIndex * 96;
  return {
    id: `${edgeId}-orthogonal-right-route`,
    startPoint: {
      x: source.x + source.width,
      y: sourceCenterY,
    },
    bendPoints: [
      { x: corridorX, y: sourceCenterY },
      { x: corridorX, y: approachY },
      { x: targetEntry.x, y: approachY },
    ],
    endPoint: targetEntry,
  };
}

function orthogonalOuterRouteSection(
  edgeId: string,
  source: PositionedShape,
  target: PositionedShape,
  nodes: Map<string, PositionedShape>,
  laneIndex: number,
): ElkEdgeSection {
  const targetIsBelow = target.y >= source.y;
  const sourceExit = {
    x: source.x + source.width / 2,
    y: targetIsBelow ? source.y + source.height : source.y,
  };
  const sourceApproachY = sourceExit.y + (targetIsBelow ? 24 : -24);
  const targetEntry = {
    x: target.x + target.width / 2,
    y: targetIsBelow ? target.y : target.y + target.height,
  };
  const approachY = targetEntry.y + (targetIsBelow ? -24 : 24);
  const minimumY = Math.min(sourceApproachY, approachY);
  const maximumY = Math.max(sourceApproachY, approachY);
  const obstacleRight = Math.max(
    source.x + source.width,
    target.x + target.width,
    ...[...nodes.values()]
      .filter(
        (node) =>
          node.id !== source.id &&
          node.id !== target.id &&
          node.y < maximumY &&
          node.y + node.height > minimumY,
      )
      .map((node) => node.x + node.width),
  );
  const corridorX = obstacleRight + 36 + laneIndex * 96;
  return {
    id: `${edgeId}-orthogonal-outer-route`,
    startPoint: sourceExit,
    bendPoints: [
      { x: sourceExit.x, y: sourceApproachY },
      { x: corridorX, y: sourceApproachY },
      { x: corridorX, y: approachY },
      { x: targetEntry.x, y: approachY },
    ],
    endPoint: targetEntry,
  };
}

function routeLabelPosition(
  section: ElkEdgeSection,
  width: number,
  height: number,
): { x: number; y: number } {
  const points = [
    section.startPoint,
    ...(section.bendPoints ?? []),
    section.endPoint,
  ];
  const segments = points.slice(1).map((end, index) => ({
    start: points[index]!,
    end,
    length: Math.hypot(end.x - points[index]!.x, end.y - points[index]!.y),
  }));
  const horizontalSegments = segments.filter(
    (segment) => segment.start.y === segment.end.y,
  );
  const targetSide = horizontalSegments
    .filter((segment) => segment.length >= width + 24)
    .at(-1);
  const horizontal = horizontalSegments.sort(
    (left, right) => right.length - left.length,
  )[0];
  const segment =
    targetSide ??
    horizontal ??
    segments.sort((left, right) => right.length - left.length)[0];
  if (!segment) return { x: section.startPoint.x, y: section.startPoint.y };
  if (segment.start.y === segment.end.y) {
    return {
      x: (segment.start.x + segment.end.x) / 2 - width / 2,
      y: segment.start.y - height - 6,
    };
  }
  return {
    x: segment.start.x + 8,
    y: (segment.start.y + segment.end.y) / 2 - height / 2,
  };
}

function rightRouteLabelPosition(
  section: ElkEdgeSection,
  width: number,
  height: number,
): { x: number; y: number } {
  const vertical = section.bendPoints?.slice(0, 2);
  if (!vertical || vertical.length < 2) {
    return routeLabelPosition(section, width, height);
  }
  return {
    x: vertical[0]!.x + 8,
    y: (vertical[0]!.y + vertical[1]!.y) / 2 - height / 2,
  };
}

function routeLaneGroup(spec: DiagramSpec, endpoint: string): string {
  const immediateParent = elementParent(spec, endpointNodeId(endpoint));
  let topGroup = immediateParent;
  while (elementParent(spec, topGroup) !== "root") {
    topGroup = elementParent(spec, topGroup);
  }
  const topKind = spec.groups.find((group) => group.id === topGroup)?.kind;
  return topKind === "cloud" || topKind === "region"
    ? immediateParent
    : topGroup;
}

function applyExplicitRoutes(
  spec: DiagramSpec,
  edges: ElkExtendedEdge[],
  nodes: Map<string, PositionedShape>,
  groups: Map<string, PositionedShape>,
): ElkExtendedEdge[] {
  const trunkOffsets = trunkAnchorOffsets(spec, nodes);
  const aboveLaneByEdge = new Map<string, number>();
  const aboveLaneCountByTargetGroup = new Map<string, number>();
  for (const edge of spec.edges.filter(
    (candidate) => candidate.route === "orthogonal-above",
  )) {
    const targetGroup = routeLaneGroup(spec, edge.to);
    const lane = aboveLaneCountByTargetGroup.get(targetGroup) ?? 0;
    aboveLaneByEdge.set(edge.id, lane + (edge.lane ?? 0));
    aboveLaneCountByTargetGroup.set(targetGroup, lane + 1);
  }
  const rightLaneByEdge = new Map<string, number>();
  const rightLaneCountByTargetGroup = new Map<string, number>();
  for (const edge of spec.edges.filter(
    (candidate) =>
      candidate.route === "orthogonal-right" ||
      candidate.route === "orthogonal-outer",
  )) {
    const targetGroup = elementParent(spec, endpointNodeId(edge.to));
    const lane = rightLaneCountByTargetGroup.get(targetGroup) ?? 0;
    rightLaneByEdge.set(edge.id, lane + (edge.lane ?? 0));
    rightLaneCountByTargetGroup.set(targetGroup, lane + 1);
  }
  const horizontalLaneByEdge = new Map<string, number>();
  const horizontalLaneCountByTargetGroup = new Map<string, number>();
  for (const edge of spec.edges.filter(
    (candidate) => candidate.route === "orthogonal-horizontal",
  )) {
    const targetGroup = elementParent(spec, endpointNodeId(edge.to));
    const lane = horizontalLaneCountByTargetGroup.get(targetGroup) ?? 0;
    horizontalLaneByEdge.set(edge.id, lane);
    horizontalLaneCountByTargetGroup.set(targetGroup, lane + 1);
  }
  const topLaneByEdge = new Map(
    spec.edges
      .filter((edge) => edge.route === "orthogonal-top")
      .map((edge, index) => [edge.id, index]),
  );
  return edges.map((edge) => {
    const specEdge = spec.edges.find((candidate) => candidate.id === edge.id);
    if (
      !specEdge ||
      (specEdge.route !== "diagonal" &&
        specEdge.route !== "curve" &&
      specEdge.route !== "orthogonal" &&
      specEdge.route !== "orthogonal-shortest" &&
        specEdge.route !== "orthogonal-horizontal" &&
      specEdge.route !== "orthogonal-trunk" &&
      specEdge.route !== "orthogonal-top" &&
        specEdge.route !== "orthogonal-above" &&
          specEdge.route !== "orthogonal-right" &&
          specEdge.route !== "orthogonal-outer")
    ) {
      return edge;
    }
    const sourceId = endpointNodeId(specEdge.from);
    const targetId = endpointNodeId(specEdge.to);
    const source = nodes.get(sourceId) ?? groups.get(sourceId);
    const target = nodes.get(targetId) ?? groups.get(targetId);
    if (!source || !target) return edge;
    const section = specEdge.route === "orthogonal-trunk"
      ? orthogonalTrunkRouteSection(
          edge.id,
          source,
          target,
          specEdge.lane ?? 0,
          trunkOffsets.get(edge.id)?.source ?? 0,
          trunkOffsets.get(edge.id)?.target ?? 0,
        )
      : specEdge.route === "orthogonal-top"
        ? orthogonalTopRouteSection(
            edge.id,
            source,
            target,
            topLaneByEdge.get(edge.id) ?? 0,
          )
      : specEdge.route === "orthogonal-horizontal"
      ? orthogonalHorizontalRouteSection(
          edge.id,
          source,
          target,
          nodes,
          horizontalLaneByEdge.get(edge.id) ?? 0,
        )
      : specEdge.route === "orthogonal"
      ? orthogonalRouteSection(
          edge.id,
          source,
          target,
        )
      : specEdge.route === "orthogonal-shortest"
        ? orthogonalShortestRouteSection(
            edge.id,
            source,
            target,
            nodes,
          )
      : specEdge.route === "orthogonal-above"
        ? orthogonalAboveRouteSection(
            edge.id,
            source,
            target,
          spec,
            nodes,
            aboveLaneByEdge.get(edge.id) ?? 0,
          )
        : specEdge.route === "orthogonal-right"
          ? orthogonalRightRouteSection(
              edge.id,
              source,
              target,
              nodes,
              rightLaneByEdge.get(edge.id) ?? 0,
            )
        : specEdge.route === "orthogonal-outer"
          ? orthogonalOuterRouteSection(
              edge.id,
              source,
              target,
              nodes,
              rightLaneByEdge.get(edge.id) ?? 0,
            )
        : {
            id: `${edge.id}-diagonal-route`,
            startPoint: boundaryPoint(source, target),
            endPoint: boundaryPoint(target, source),
          };
    const labels = edge.labels?.map((label) => ({
      ...label,
      ...(specEdge.route === "orthogonal-right" ||
      specEdge.route === "orthogonal-outer" ||
      specEdge.route === "orthogonal-horizontal"
        ? rightRouteLabelPosition(section, label.width ?? 0, label.height ?? 0)
        : specEdge.route === "orthogonal" ||
      specEdge.route === "orthogonal-shortest" ||
      specEdge.route === "orthogonal-trunk" ||
      specEdge.route === "orthogonal-top" ||
      specEdge.route === "orthogonal-above"
        ? routeLabelPosition(section, label.width ?? 0, label.height ?? 0)
        : {
            x:
              (section.startPoint.x + section.endPoint.x) / 2 -
              (label.width ?? 0) / 2,
            y:
              (section.startPoint.y + section.endPoint.y) / 2 -
              (label.height ?? 0) / 2,
          }),
    }));
    const next: ElkExtendedEdge = {
      ...edge,
      sections: [section],
      ...(labels ? { labels } : {}),
    };
    delete next.container;
    return next;
  });
}

export async function layoutDiagram(spec: DiagramSpec): Promise<DiagramLayout> {
  const compact = spec.canvas.profile === "azure-reference";
  const definition = diagramDefinition(spec.kind);
  if (definition.layoutStrategy === "gantt") return layoutGantt(spec);
  if (definition.layoutStrategy === "coordinate") return layoutCoordinate(spec);
  if (definition.layoutStrategy === "radial") return layoutRadial(spec);
  if (definition.layoutStrategy === "grid") return layoutGrid(spec);
  const containedEdges = edgesByContainer(spec);
  const rootGroups = spec.groups
    .filter((group) => !group.parent)
    .map((group) => groupToElk(spec, group, containedEdges));
  const rootNodes = spec.nodes
    .filter((node) => !node.parent)
    .map((node) => diagramNodeToElk(node, compact));
  const graph: ElkNode = {
    id: "root",
    children: [...rootGroups, ...rootNodes],
    edges: containedEdges.get("root") ?? [],
    layoutOptions: {
      "elk.algorithm": "layered",
      "elk.direction": definition.direction ?? spec.canvas.direction,
      "elk.edgeRouting": definition.edgeRouting ?? "ORTHOGONAL",
      "elk.hierarchyHandling": definition.hierarchyHandling,
      "elk.padding": `[top=${spec.canvas.padding ?? (compact ? 24 : 40)},left=${spec.canvas.padding ?? (compact ? 24 : 40)},bottom=${spec.canvas.padding ?? (compact ? 24 : 40)},right=${spec.canvas.padding ?? (compact ? 24 : 40)}]`,
      "elk.spacing.nodeNode": String(
        definition.nodeSpacing ?? (compact ? 18 : 28),
      ),
      "elk.layered.spacing.nodeNodeBetweenLayers": String(
        definition.layerSpacing ?? (compact ? 38 : 52),
      ),
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
  applyDirectLayouts(spec, groups, nodes);
  applyHorizontalAlignments(spec, groups, nodes);
  const placementBottom = applyGroupPlacements(spec, groups, nodes);
  const rootFlow = applyRootGroupFlow(spec, groups, nodes);
  const explicitRoutes = applyExplicitRoutes(spec, edges, nodes, groups);
  const routed = applyFixedSideRoutes(spec, explicitRoutes, nodes);

  let routeRight = 0;
  let routeBottom = 0;
  for (const edge of routed.edges) {
    const container = edge.container ? groups.get(edge.container) : undefined;
    const offsetX = container?.x ?? 0;
    const offsetY = container?.y ?? 0;
    for (const section of edge.sections ?? []) {
      for (const point of [
        section.startPoint,
        ...(section.bendPoints ?? []),
        section.endPoint,
      ]) {
        routeRight = Math.max(routeRight, point.x + offsetX);
        routeBottom = Math.max(routeBottom, point.y + offsetY);
      }
    }
  }

  const width = rootFlow
    ? Math.max(spec.canvas.width, rootFlow.width, routeRight + 24)
    : Math.max(result.width ?? spec.canvas.width, routeRight + 24);
  const height = rootFlow
    ? Math.max(
        spec.canvas.height,
        rootFlow.bottom,
        routed.bottom + 24,
        routeBottom + 24,
      )
    : Math.max(
        result.height ?? spec.canvas.height,
        placementBottom + 36,
        routed.bottom + 24,
        routeBottom + 24,
      );
  return {
    width,
    height,
    groups,
    nodes,
    edges: routed.edges,
  };
}
