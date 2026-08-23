import type { ElkLabel } from "elkjs/lib/elk-api.js";
import type { ElkPoint } from "elkjs/lib/elk-api.js";

import type { DiagramLayout, PositionedShape } from "./elk.js";
import { sampleCubic } from "./curve.js";
import type { DiagramSpec } from "../model/types.js";

interface Box {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
}

interface EdgeSegment {
  edgeId: string;
  source: string;
  target: string;
  start: ElkPoint;
  end: ElkPoint;
}

function intersects(left: Box, right: Box, padding = 0): boolean {
  return (
    left.x < right.x + right.width - padding &&
    left.x + left.width > right.x + padding &&
    left.y < right.y + right.height - padding &&
    left.y + left.height > right.y + padding
  );
}

function contains(parent: Box, child: Box, padding = 0): boolean {
  return (
    child.x >= parent.x + padding &&
    child.y >= parent.y + padding &&
    child.x + child.width <= parent.x + parent.width - padding &&
    child.y + child.height <= parent.y + parent.height - padding
  );
}

function segmentIntersectsBox(
  start: ElkPoint,
  end: ElkPoint,
  box: Box,
  padding = 0,
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

function endpointElementId(endpoint: string): string {
  return endpoint.split(":", 1)[0] ?? endpoint;
}

function segmentsProperlyCross(
  firstStart: ElkPoint,
  firstEnd: ElkPoint,
  secondStart: ElkPoint,
  secondEnd: ElkPoint,
): boolean {
  const firstDelta = {
    x: firstEnd.x - firstStart.x,
    y: firstEnd.y - firstStart.y,
  };
  const secondDelta = {
    x: secondEnd.x - secondStart.x,
    y: secondEnd.y - secondStart.y,
  };
  const determinant = firstDelta.x * secondDelta.y - firstDelta.y * secondDelta.x;
  if (Math.abs(determinant) < 0.0001) return false;
  const offset = {
    x: secondStart.x - firstStart.x,
    y: secondStart.y - firstStart.y,
  };
  const firstRatio = (offset.x * secondDelta.y - offset.y * secondDelta.x) / determinant;
  const secondRatio = (offset.x * firstDelta.y - offset.y * firstDelta.x) / determinant;
  const epsilon = 0.0001;
  return firstRatio > epsilon
    && firstRatio < 1 - epsilon
    && secondRatio > epsilon
    && secondRatio < 1 - epsilon;
}

function labelBox(
  edgeId: string,
  label: ElkLabel,
  container: PositionedShape | undefined,
): Box | undefined {
  if (
    label.x === undefined ||
    label.y === undefined ||
    label.width === undefined ||
    label.height === undefined
  ) {
    return undefined;
  }
  return {
    id: edgeId,
    x: label.x + (container?.x ?? 0),
    y: label.y + (container?.y ?? 0),
    width: label.width,
    height: label.height,
  };
}

export function layoutIntegrityErrors(
  spec: DiagramSpec,
  layout: DiagramLayout,
): string[] {
  const errors: string[] = [];
  const nodes = [...layout.nodes.values()];
  const edgeLabelBoxes: Box[] = [];
  const stepBadgeBoxes: Box[] = [];
  const networkSegments: EdgeSegment[] = [];

  const intentionalNodeOverlap = spec.kind === "pie" || spec.kind === "venn";
  for (
    let leftIndex = 0;
    leftIndex < nodes.length && !intentionalNodeOverlap;
    leftIndex += 1
  ) {
    for (
      let rightIndex = leftIndex + 1;
      rightIndex < nodes.length;
      rightIndex += 1
    ) {
      const left = nodes[leftIndex]!;
      const right = nodes[rightIndex]!;
      if (intersects(left, right, 1)) {
        errors.push(`Nodes '${left.id}' and '${right.id}' overlap`);
      }
    }
  }

  const parentByNode = new Map(spec.nodes.map((node) => [node.id, node.parent]));
  for (const node of nodes) {
    const parentId = parentByNode.get(node.id);
    if (!parentId) continue;
    const parent = layout.groups.get(parentId);
    if (!parent) {
      errors.push(`Node '${node.id}' has no positioned parent '${parentId}'`);
    } else if (!contains(parent, node, 1)) {
      errors.push(`Node '${node.id}' escapes parent '${parentId}'`);
    }
  }

  if (spec.kind === "network") {
    const parentByGroup = new Map(spec.groups.map((group) => [group.id, group.parent]));
    const groups = [...layout.groups.values()];
    for (let leftIndex = 0; leftIndex < groups.length; leftIndex += 1) {
      for (let rightIndex = leftIndex + 1; rightIndex < groups.length; rightIndex += 1) {
        const left = groups[leftIndex]!;
        const right = groups[rightIndex]!;
        if (parentByGroup.get(left.id) !== parentByGroup.get(right.id)) continue;
        if (intersects(left, right, 1)) {
          errors.push(`Peer groups '${left.id}' and '${right.id}' overlap`);
        }
      }
    }
  }

  for (const edge of layout.edges) {
    const container = edge.container
      ? layout.groups.get(edge.container)
      : undefined;
    for (const label of edge.labels ?? []) {
      const box = labelBox(edge.id, label, container);
      if (!box) {
        errors.push(`Edge '${edge.id}' label has no complete layout box`);
        continue;
      }
      edgeLabelBoxes.push(box);
      for (const node of nodes) {
        if (intersects(box, node, 2)) {
          errors.push(`Edge '${edge.id}' label overlaps node '${node.id}'`);
        }
      }
      const specEdge = spec.edges.find((candidate) => candidate.id === edge.id);
      if (specEdge?.step) {
        const badge = {
          id: edge.id,
          x: box.x - 32,
          y: box.y + box.height / 2 - 13,
          width: 26,
          height: 26,
        };
        stepBadgeBoxes.push(badge);
        const endpointIds = new Set([
          endpointElementId(specEdge.from),
          endpointElementId(specEdge.to),
        ]);
        for (const node of nodes) {
          if (endpointIds.has(node.id)) continue;
          if (intersects(badge, node, 1)) {
            errors.push(`Edge '${edge.id}' step badge overlaps node '${node.id}'`);
          }
        }
      }
    }

    const specEdge = spec.edges.find((candidate) => candidate.id === edge.id);
    if (!specEdge) continue;
    const effectiveRoute = specEdge?.route ??
      (spec.canvas.networkPreset ? "orthogonal-shortest" : undefined);
    if (
      effectiveRoute !== "diagonal" &&
      effectiveRoute !== "curve" &&
      effectiveRoute !== "orthogonal" &&
      effectiveRoute !== "orthogonal-shortest" &&
      effectiveRoute !== "orthogonal-horizontal" &&
      effectiveRoute !== "orthogonal-trunk" &&
      effectiveRoute !== "orthogonal-top" &&
      effectiveRoute !== "orthogonal-above" &&
      effectiveRoute !== "orthogonal-gap" &&
      effectiveRoute !== "orthogonal-right" &&
      effectiveRoute !== "orthogonal-approval"
    ) continue;
    const endpointIds = new Set([
      endpointElementId(specEdge.from),
      endpointElementId(specEdge.to),
    ]);
    for (const section of edge.sections ?? []) {
      const routePoints = [
        section.startPoint,
        ...(section.bendPoints ?? []),
        section.endPoint,
      ];
      const sampledPoints =
        effectiveRoute === "curve"
          ? sampleCubic(section.startPoint, section.endPoint)
          : routePoints;
      const points = sampledPoints.map((point) => ({
        x: point.x + (container?.x ?? 0),
        y: point.y + (container?.y ?? 0),
      }));
      if (spec.kind === "network" && effectiveRoute !== "orthogonal-trunk") {
        for (let index = 1; index < points.length; index += 1) {
          networkSegments.push({
            edgeId: edge.id,
            source: endpointElementId(specEdge.from),
            target: endpointElementId(specEdge.to),
            start: points[index - 1]!,
            end: points[index]!,
          });
        }
      }
      for (let index = 1; index < points.length; index += 1) {
        const start = points[index - 1]!;
        const end = points[index]!;
        for (const node of nodes) {
          if (endpointIds.has(node.id)) continue;
          if (segmentIntersectsBox(start, end, node, 3)) {
            errors.push(
              `${effectiveRoute === "curve" ? "Curved" : effectiveRoute === "orthogonal" || effectiveRoute === "orthogonal-shortest" || effectiveRoute === "orthogonal-horizontal" || effectiveRoute === "orthogonal-trunk" || effectiveRoute === "orthogonal-top" || effectiveRoute === "orthogonal-above" || effectiveRoute === "orthogonal-gap" || effectiveRoute === "orthogonal-right" || effectiveRoute === "orthogonal-approval" ? "Orthogonal" : "Diagonal"} edge '${edge.id}' crosses node '${node.id}'`,
            );
          }
        }
      }
    }
  }

  for (let leftIndex = 0; leftIndex < networkSegments.length; leftIndex += 1) {
    for (let rightIndex = leftIndex + 1; rightIndex < networkSegments.length; rightIndex += 1) {
      const left = networkSegments[leftIndex]!;
      const right = networkSegments[rightIndex]!;
      if (left.edgeId === right.edgeId) continue;
      if (
        left.source === right.source
        || left.source === right.target
        || left.target === right.source
        || left.target === right.target
      ) continue;
      if (segmentsProperlyCross(left.start, left.end, right.start, right.end)) {
        const ids = [left.edgeId, right.edgeId].sort();
        const message = `Network edges '${ids[0]}' and '${ids[1]}' cross`;
        if (!errors.includes(message)) errors.push(message);
      }
    }
  }

  for (let leftIndex = 0; leftIndex < edgeLabelBoxes.length; leftIndex += 1) {
    for (
      let rightIndex = leftIndex + 1;
      rightIndex < edgeLabelBoxes.length;
      rightIndex += 1
    ) {
      const left = edgeLabelBoxes[leftIndex]!;
      const right = edgeLabelBoxes[rightIndex]!;
      if (intersects(left, right, 1)) {
        errors.push(`Edge labels '${left.id}' and '${right.id}' overlap`);
      }
    }
  }
  for (const badge of stepBadgeBoxes) {
    for (const label of edgeLabelBoxes) {
      if (badge.id !== label.id && intersects(badge, label, 1)) {
        errors.push(`Edge '${badge.id}' step badge overlaps label '${label.id}'`);
      }
    }
  }

  return errors;
}

export function assertLayoutIntegrity(
  spec: DiagramSpec,
  layout: DiagramLayout,
): void {
  const errors = layoutIntegrityErrors(spec, layout);
  if (errors.length) {
    throw new Error(`Diagram layout integrity failed: ${errors.join("; ")}`);
  }
}
