import type {
  ElkEdgeSection,
  ElkExtendedEdge,
  ElkPoint,
} from "elkjs/lib/elk-api.js";

import type { DiagramLayout, PositionedShape } from "./elk.js";
import {
  collinearOverlapLength,
  LANE_OVERLAP_TOLERANCE,
} from "./segments.js";
import type { DiagramSpec } from "../model/types.js";

type Side = "NORTH" | "EAST" | "SOUTH" | "WEST";

interface Anchor {
  point: ElkPoint;
  side: Side;
}

interface Candidate {
  section: ElkEdgeSection;
  cost: number;
}

const ENDPOINT_STUB = 12;

interface UsedSegment {
  edgeId: string;
  sourceId: string;
  targetId: string;
  start: ElkPoint;
  end: ElkPoint;
}

function endpointElementId(endpoint: string): string {
  return endpoint.split(":", 1)[0] ?? endpoint;
}

function endpointShape(
  endpoint: string,
  nodes: DiagramLayout["nodes"],
  groups: DiagramLayout["groups"],
): PositionedShape | undefined {
  const elementId = endpointElementId(endpoint);
  return nodes.get(elementId) ?? groups.get(elementId);
}

function segmentIntersectsBox(
  start: ElkPoint,
  end: ElkPoint,
  box: PositionedShape,
  padding = 3,
): boolean {
  const left = box.x - padding;
  const right = box.x + box.width + padding;
  const top = box.y - padding;
  const bottom = box.y + box.height + padding;
  const deltaX = end.x - start.x;
  const deltaY = end.y - start.y;
  let minimum = 0;
  let maximum = 1;
  for (const [origin, delta, low, high] of [
    [start.x, deltaX, left, right],
    [start.y, deltaY, top, bottom],
  ] as const) {
    if (delta === 0) {
      if (origin < low || origin > high) return false;
      continue;
    }
    const first = (low - origin) / delta;
    const second = (high - origin) / delta;
    minimum = Math.max(minimum, Math.min(first, second));
    maximum = Math.min(maximum, Math.max(first, second));
    if (minimum > maximum) return false;
  }
  return true;
}

function compactPoints(points: ElkPoint[]): ElkPoint[] {
  return points.filter(
    (point, index) =>
      index === 0 ||
      point.x !== points[index - 1]!.x ||
      point.y !== points[index - 1]!.y,
  );
}

function sectionFromPoints(edgeId: string, points: ElkPoint[]): Candidate {
  const compacted = compactPoints(points);
  const segments = compacted.slice(1).map((end, index) => ({
    start: compacted[index]!,
    end,
  }));
  const cost =
    segments.reduce(
      (total, segment) =>
        total +
        Math.abs(segment.end.x - segment.start.x) +
        Math.abs(segment.end.y - segment.start.y),
      0,
    ) +
    Math.max(0, compacted.length - 2) * 24;
  return {
    section: {
      id: `${edgeId}-missing-edge-route`,
      startPoint: compacted[0]!,
      ...(compacted.length > 2
        ? { bendPoints: compacted.slice(1, compacted.length - 1) }
        : {}),
      endPoint: compacted.at(-1)!,
    },
    cost,
  };
}

function sectionPoints(section: ElkEdgeSection): ElkPoint[] {
  return [
    section.startPoint,
    ...(section.bendPoints ?? []),
    section.endPoint,
  ];
}

function sectionSegments(section: ElkEdgeSection): Array<{
  start: ElkPoint;
  end: ElkPoint;
}> {
  const points = sectionPoints(section);
  return points.slice(1).map((end, index) => ({
    start: points[index]!,
    end,
  }));
}

function sectionIsClear(
  section: ElkEdgeSection,
  obstacles: PositionedShape[],
): boolean {
  return sectionSegments(section).every(({ start, end }) => {
    if (start.x !== end.x && start.y !== end.y) return false;
    return obstacles.every(
      (obstacle) => !segmentIntersectsBox(start, end, obstacle, 3),
    );
  });
}

function sharesEndpoint(
  left: { sourceId: string; targetId: string },
  right: { sourceId: string; targetId: string },
): boolean {
  return (
    left.sourceId === right.sourceId ||
    left.sourceId === right.targetId ||
    left.targetId === right.sourceId ||
    left.targetId === right.targetId
  );
}

function maximumUnrelatedOverlap(
  section: ElkEdgeSection,
  sourceId: string,
  targetId: string,
  usedSegments: UsedSegment[],
): number {
  let maximum = 0;
  for (const segment of sectionSegments(section)) {
    for (const used of usedSegments) {
      if (sharesEndpoint({ sourceId, targetId }, used)) continue;
      maximum = Math.max(
        maximum,
        collinearOverlapLength(segment.start, segment.end, used.start, used.end),
      );
    }
  }
  return maximum;
}

function uniqueSorted(values: number[]): number[] {
  return [...new Set(values.map((value) => Math.round(value * 1000) / 1000))]
    .sort((left, right) => left - right);
}

function midpointGaps(
  intervals: Array<{ start: number; end: number }>,
  minimumGap = 24,
): number[] {
  const sorted = intervals
    .map((interval) => ({
      start: Math.min(interval.start, interval.end) - 3,
      end: Math.max(interval.start, interval.end) + 3,
    }))
    .sort((left, right) => left.start - right.start);
  const gaps: number[] = [];
  for (let index = 1; index < sorted.length; index += 1) {
    const left = sorted[index - 1]!;
    const right = sorted[index]!;
    if (right.start - left.end >= minimumGap) {
      gaps.push((left.end + right.start) / 2);
    }
  }
  return gaps;
}

function laneValues(
  start: number,
  end: number,
  intervals: Array<{ start: number; end: number }>,
  offset: number,
): number[] {
  const minimum = Math.min(start, end, ...intervals.map((interval) => interval.start));
  const maximum = Math.max(start, end, ...intervals.map((interval) => interval.end));
  const outsideOffset = Math.abs(offset);
  return uniqueSorted([
    start,
    end,
    (start + end) / 2,
    Math.max(0, minimum - 48 - outsideOffset),
    maximum + 48 + outsideOffset,
    ...midpointGaps(intervals),
  ]);
}

function attachmentSpan(shape: PositionedShape, side: Side): number {
  const dimension = side === "EAST" || side === "WEST"
    ? shape.height
    : shape.width;
  return Math.max(0, dimension - 24);
}

function attachmentOffset(
  edgeId: string,
  endpointId: string,
  side: Side,
  shape: PositionedShape,
  endpointUses: Map<string, string[]>,
): number {
  const uses = endpointUses.get(endpointUseKey(endpointId, side)) ?? [edgeId];
  if (uses.length <= 1) return 0;
  const index = Math.max(0, uses.indexOf(edgeId));
  const span = Math.min(attachmentSpan(shape, side), (uses.length - 1) * 18);
  return -span / 2 + (span * index) / (uses.length - 1);
}

function endpointUseKey(endpointId: string, side: Side): string {
  return `${endpointId}:${side}`;
}

function anchorSides(
  source: PositionedShape,
  target: PositionedShape,
): { sourceSide: Side; targetSide: Side } {
  const sourceCenter = {
    x: source.x + source.width / 2,
    y: source.y + source.height / 2,
  };
  const targetCenter = {
    x: target.x + target.width / 2,
    y: target.y + target.height / 2,
  };
  const horizontal =
    Math.abs(targetCenter.x - sourceCenter.x) >=
    Math.abs(targetCenter.y - sourceCenter.y);
  if (horizontal) {
    const targetIsRight = targetCenter.x >= sourceCenter.x;
    return {
      sourceSide: targetIsRight ? "EAST" : "WEST",
      targetSide: targetIsRight ? "WEST" : "EAST",
    };
  }

  const targetIsBelow = targetCenter.y >= sourceCenter.y;
  return {
    sourceSide: targetIsBelow ? "SOUTH" : "NORTH",
    targetSide: targetIsBelow ? "NORTH" : "SOUTH",
  };
}

function anchors(
  edgeId: string,
  sourceId: string,
  targetId: string,
  source: PositionedShape,
  target: PositionedShape,
  endpointUses: Map<string, string[]>,
): { source: Anchor; target: Anchor; laneOffset: number } {
  const sourceCenter = {
    x: source.x + source.width / 2,
    y: source.y + source.height / 2,
  };
  const targetCenter = {
    x: target.x + target.width / 2,
    y: target.y + target.height / 2,
  };
  const { sourceSide, targetSide } = anchorSides(source, target);
  if (sourceSide === "EAST" || sourceSide === "WEST") {
    const targetIsRight = sourceSide === "EAST";
    const sourceOffset = attachmentOffset(
      edgeId,
      sourceId,
      sourceSide,
      source,
      endpointUses,
    );
    const targetOffset = attachmentOffset(
      edgeId,
      targetId,
      targetSide,
      target,
      endpointUses,
    );
    return {
      source: {
        side: sourceSide,
        point: {
          x: targetIsRight ? source.x + source.width : source.x,
          y: sourceCenter.y + sourceOffset,
        },
      },
      target: {
        side: targetSide,
        point: {
          x: targetIsRight ? target.x : target.x + target.width,
          y: targetCenter.y + targetOffset,
        },
      },
      laneOffset: sourceOffset || targetOffset,
    };
  }

  const targetIsBelow = sourceSide === "SOUTH";
  const sourceOffset = attachmentOffset(
    edgeId,
    sourceId,
    sourceSide,
    source,
    endpointUses,
  );
  const targetOffset = attachmentOffset(
    edgeId,
    targetId,
    targetSide,
    target,
    endpointUses,
  );
  return {
    source: {
      side: sourceSide,
      point: {
        x: sourceCenter.x + sourceOffset,
        y: targetIsBelow ? source.y + source.height : source.y,
      },
    },
    target: {
      side: targetSide,
      point: {
        x: targetCenter.x + targetOffset,
        y: targetIsBelow ? target.y : target.y + target.height,
      },
    },
    laneOffset: sourceOffset || targetOffset,
  };
}

function stubPoint(anchor: Anchor, distance: number): ElkPoint {
  switch (anchor.side) {
    case "EAST":
      return { x: anchor.point.x + distance, y: anchor.point.y };
    case "WEST":
      return { x: anchor.point.x - distance, y: anchor.point.y };
    case "SOUTH":
      return { x: anchor.point.x, y: anchor.point.y + distance };
    case "NORTH":
      return { x: anchor.point.x, y: anchor.point.y - distance };
  }
}

function directRouteAllowed(source: Anchor, target: Anchor): boolean {
  if (
    (source.side === "EAST" || source.side === "WEST") &&
    (target.side === "EAST" || target.side === "WEST")
  ) {
    return source.point.y === target.point.y;
  }
  if (
    (source.side === "NORTH" || source.side === "SOUTH") &&
    (target.side === "NORTH" || target.side === "SOUTH")
  ) {
    return source.point.x === target.point.x;
  }
  return false;
}

function routeCandidates(
  edgeId: string,
  sourceAnchor: Anchor,
  targetAnchor: Anchor,
  laneObstacles: PositionedShape[],
  laneOffset: number,
  sourceId: string,
  targetId: string,
  usedSegments: UsedSegment[],
): Candidate[] {
  const source = stubPoint(sourceAnchor, ENDPOINT_STUB);
  const target = stubPoint(targetAnchor, ENDPOINT_STUB);
  const xIntervals = laneObstacles.map((node) => ({
    start: node.x,
    end: node.x + node.width,
  }));
  const yIntervals = laneObstacles.map((node) => ({
    start: node.y,
    end: node.y + node.height,
  }));
  const xLanes = laneValues(source.x, target.x, xIntervals, laneOffset);
  const yLanes = laneValues(source.y, target.y, yIntervals, laneOffset);
  const unrelatedUsedSegments = usedSegments.filter(
    (segment) => !sharesEndpoint({ sourceId, targetId }, segment),
  );
  const occupiedXLanes = unrelatedUsedSegments
    .filter((segment) => segment.start.x === segment.end.x)
    .flatMap((segment) => [
      segment.start.x - LANE_OVERLAP_TOLERANCE - 8,
      segment.start.x + LANE_OVERLAP_TOLERANCE + 8,
    ]);
  const occupiedYLanes = unrelatedUsedSegments
    .filter((segment) => segment.start.y === segment.end.y)
    .flatMap((segment) => [
      segment.start.y - LANE_OVERLAP_TOLERANCE - 8,
      segment.start.y + LANE_OVERLAP_TOLERANCE + 8,
    ]);
  const shiftedYLanes = uniqueSorted([
    ...yLanes,
    ...occupiedYLanes,
    ...yLanes.map((lane) => Math.max(0, lane + laneOffset)),
  ]);
  const shiftedXLanes = uniqueSorted([
    ...xLanes,
    ...occupiedXLanes,
    ...xLanes.map((lane) => Math.max(0, lane + laneOffset)),
  ]);
  const candidates = [
    ...(directRouteAllowed(sourceAnchor, targetAnchor)
      ? [sectionFromPoints(edgeId, [sourceAnchor.point, targetAnchor.point])]
      : []),
    sectionFromPoints(edgeId, [
      sourceAnchor.point,
      source,
      target,
      targetAnchor.point,
    ]),
    sectionFromPoints(edgeId, [
      sourceAnchor.point,
      source,
      { x: target.x, y: source.y },
      target,
      targetAnchor.point,
    ]),
    sectionFromPoints(edgeId, [
      sourceAnchor.point,
      source,
      { x: source.x, y: target.y },
      target,
      targetAnchor.point,
    ]),
  ];
  for (const laneX of shiftedXLanes) {
    candidates.push(
      sectionFromPoints(edgeId, [
        sourceAnchor.point,
        source,
        { x: laneX, y: source.y },
        { x: laneX, y: target.y },
        target,
        targetAnchor.point,
      ]),
    );
  }
  for (const laneY of shiftedYLanes) {
    candidates.push(
      sectionFromPoints(edgeId, [
        sourceAnchor.point,
        source,
        { x: source.x, y: laneY },
        { x: target.x, y: laneY },
        target,
        targetAnchor.point,
      ]),
    );
  }
  const outerXLanes = [shiftedXLanes[0], shiftedXLanes.at(-1)].filter(
    (lane): lane is number => lane !== undefined,
  );
  const outerYLanes = [shiftedYLanes[0], shiftedYLanes.at(-1)].filter(
    (lane): lane is number => lane !== undefined,
  );
  for (const laneX of outerXLanes) {
    for (const laneY of shiftedYLanes) {
      candidates.push(
        sectionFromPoints(edgeId, [
          sourceAnchor.point,
          source,
          { x: laneX, y: source.y },
          { x: laneX, y: laneY },
          { x: target.x, y: laneY },
          target,
          targetAnchor.point,
        ]),
      );
    }
  }
  for (const laneY of outerYLanes) {
    for (const laneX of shiftedXLanes) {
      candidates.push(
        sectionFromPoints(edgeId, [
          sourceAnchor.point,
          source,
          { x: source.x, y: laneY },
          { x: laneX, y: laneY },
          { x: laneX, y: target.y },
          target,
          targetAnchor.point,
        ]),
      );
    }
  }
  return candidates.sort((left, right) => left.cost - right.cost);
}

function orthogonalFallbackSection(
  edgeId: string,
  sourceId: string,
  targetId: string,
  source: PositionedShape,
  target: PositionedShape,
  nodes: DiagramLayout["nodes"],
  endpointUses: Map<string, string[]>,
  usedSegments: UsedSegment[],
): ElkEdgeSection {
  const anchor = anchors(edgeId, sourceId, targetId, source, target, endpointUses);
  const allNodes = [...nodes.values()];
  const obstacles = allNodes.filter(
    (node) => node.id !== sourceId && node.id !== targetId,
  );
  const candidates = routeCandidates(
    edgeId,
    anchor.source,
    anchor.target,
    allNodes,
    anchor.laneOffset,
    sourceId,
    targetId,
    usedSegments,
  )
    .map((candidate) => ({
      ...candidate,
      cost:
        candidate.cost +
        maximumUnrelatedOverlap(
          candidate.section,
          sourceId,
          targetId,
          usedSegments,
        ) * 1000,
    }))
    .sort((left, right) => left.cost - right.cost);
  return (
    candidates.find((candidate) => sectionIsClear(candidate.section, obstacles))
      ?.section ?? candidates[0]!.section
  );
}

function labelPosition(
  section: ElkEdgeSection,
  width: number,
  height: number,
  source: PositionedShape,
  target: PositionedShape,
  nodes: Iterable<PositionedShape>,
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
  const wideHorizontal = horizontalSegments
    .filter((segment) => segment.length >= width + 24)
    .at(-1);
  const longestHorizontal = horizontalSegments.sort(
    (left, right) => right.length - left.length,
  )[0];
  const segment =
    wideHorizontal ??
    longestHorizontal ??
    segments.sort((left, right) => right.length - left.length)[0];
  const nodeList = [...nodes];
  const midpointX =
    (source.x + source.width / 2 + target.x + target.width / 2) / 2;
  const clear = (candidate: { x: number; y: number }): boolean => {
    for (const node of nodeList) {
      if (
        candidate.x < node.x + node.width - 2 &&
        candidate.x + width > node.x + 2 &&
        candidate.y < node.y + node.height - 2 &&
        candidate.y + height > node.y + 2
      ) {
        return false;
      }
    }
    return true;
  };
  const fallback = !segment
    ? { x: section.startPoint.x, y: section.startPoint.y }
    : segment.start.y === segment.end.y
      ? {
          x: (segment.start.x + segment.end.x) / 2 - width / 2,
          y: segment.start.y - height - 6,
        }
      : {
          x: segment.start.x + 8,
          y: (segment.start.y + segment.end.y) / 2 - height / 2,
        };
  const candidates = [
    fallback,
    {
      x: midpointX - width / 2,
      y: Math.min(source.y, target.y) - height - 10,
    },
    {
      x: midpointX - width / 2,
      y: Math.max(source.y + source.height, target.y + target.height) + 10,
    },
    {
      x: Math.min(source.x, target.x) - width - 10,
      y:
        (source.y + target.y + source.height / 2 + target.height / 2) / 2 -
        height / 2,
    },
    {
      x: Math.max(source.x + source.width, target.x + target.width) + 10,
      y:
        (source.y + target.y + source.height / 2 + target.height / 2) / 2 -
        height / 2,
    },
  ].map((candidate) => ({
    x: Math.max(0, candidate.x),
    y: Math.max(0, candidate.y),
  }));
  return candidates.find(clear) ?? fallback;
}

function endpointUses(
  spec: DiagramSpec,
  edges: ElkExtendedEdge[],
  nodes: DiagramLayout["nodes"],
  groups: DiagramLayout["groups"],
): Map<string, string[]> {
  const specEdgeById = new Map(spec.edges.map((edge) => [edge.id, edge]));
  const uses = new Map<string, string[]>();
  for (const edge of edges) {
    if ((edge.sections?.length ?? 0) > 0) continue;
    const specEdge = specEdgeById.get(edge.id);
    if (!specEdge) continue;
    const source = endpointShape(specEdge.from, nodes, groups);
    const target = endpointShape(specEdge.to, nodes, groups);
    if (!source || !target) continue;
    const { sourceSide, targetSide } = anchorSides(source, target);
    for (const [endpoint, side] of [
      [specEdge.from, sourceSide],
      [specEdge.to, targetSide],
    ] as const) {
      const endpointId = endpointElementId(endpoint);
      const key = endpointUseKey(endpointId, side);
      const endpointEdges = uses.get(key) ?? [];
      endpointEdges.push(edge.id);
      uses.set(key, endpointEdges);
    }
  }
  return uses;
}

function collectUsedSegments(
  spec: DiagramSpec,
  edge: ElkExtendedEdge,
  groups: DiagramLayout["groups"],
): UsedSegment[] {
  const specEdge = spec.edges.find((candidate) => candidate.id === edge.id);
  if (!specEdge) return [];
  const container = edge.container ? groups.get(edge.container) : undefined;
  const offsetX = container?.x ?? 0;
  const offsetY = container?.y ?? 0;
  return (edge.sections ?? []).flatMap((section) => {
    const points = sectionPoints(section).map((point) => ({
      x: point.x + offsetX,
      y: point.y + offsetY,
    }));
    return points.slice(1).map((end, index) => ({
      edgeId: edge.id,
      sourceId: endpointElementId(specEdge.from),
      targetId: endpointElementId(specEdge.to),
      start: points[index]!,
      end,
    }));
  });
}

export function routeMissingEdgeSections(
  spec: DiagramSpec,
  edges: ElkExtendedEdge[],
  nodes: DiagramLayout["nodes"],
  groups: DiagramLayout["groups"],
): ElkExtendedEdge[] {
  const specEdgeById = new Map(spec.edges.map((edge) => [edge.id, edge]));
  const uses = endpointUses(spec, edges, nodes, groups);
  const usedSegments = edges.flatMap((edge) =>
    (edge.sections?.length ?? 0) > 0
      ? collectUsedSegments(spec, edge, groups)
      : [],
  );
  return edges.map((edge) => {
    if ((edge.sections?.length ?? 0) > 0) return edge;
    const specEdge = specEdgeById.get(edge.id);
    if (!specEdge) return edge;
    const sourceId = endpointElementId(specEdge.from);
    const targetId = endpointElementId(specEdge.to);
    const source = endpointShape(specEdge.from, nodes, groups);
    const target = endpointShape(specEdge.to, nodes, groups);
    if (!source || !target) return edge;
    const section = orthogonalFallbackSection(
      edge.id,
      sourceId,
      targetId,
      source,
      target,
      nodes,
      uses,
      usedSegments,
    );
    const labels = edge.labels?.map((label) => ({
      ...label,
      ...labelPosition(
        section,
        label.width ?? 0,
        label.height ?? 0,
        source,
        target,
        nodes.values(),
      ),
    }));
    const next: ElkExtendedEdge = {
      ...edge,
      sections: [section],
      ...(labels ? { labels } : {}),
    };
    delete next.container;
    usedSegments.push(...collectUsedSegments(spec, next, groups));
    return next;
  });
}
