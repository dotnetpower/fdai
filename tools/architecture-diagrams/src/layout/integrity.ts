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

  for (let leftIndex = 0; leftIndex < nodes.length; leftIndex += 1) {
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
      for (const node of nodes) {
        if (intersects(box, node, 2)) {
          errors.push(`Edge '${edge.id}' label overlaps node '${node.id}'`);
        }
      }
    }

    const specEdge = spec.edges.find((candidate) => candidate.id === edge.id);
    if (specEdge?.route !== "diagonal" && specEdge?.route !== "curve") continue;
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
        specEdge.route === "curve"
          ? sampleCubic(section.startPoint, section.endPoint)
          : routePoints;
      const points = sampledPoints.map((point) => ({
        x: point.x + (container?.x ?? 0),
        y: point.y + (container?.y ?? 0),
      }));
      for (let index = 1; index < points.length; index += 1) {
        const start = points[index - 1]!;
        const end = points[index]!;
        for (const node of nodes) {
          if (endpointIds.has(node.id)) continue;
          if (segmentIntersectsBox(start, end, node, 3)) {
            errors.push(
              `${specEdge.route === "curve" ? "Curved" : "Diagonal"} edge '${edge.id}' crosses node '${node.id}'`,
            );
          }
        }
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
