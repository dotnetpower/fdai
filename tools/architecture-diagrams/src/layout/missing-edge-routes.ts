import type {
  ElkEdgeSection,
  ElkExtendedEdge,
} from "elkjs/lib/elk-api.js";

import type { DiagramLayout, PositionedShape } from "./elk.js";
import type { DiagramSpec } from "../model/types.js";

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

function orthogonalFallbackSection(
  edgeId: string,
  source: PositionedShape,
  target: PositionedShape,
): ElkEdgeSection {
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
    const startPoint = {
      x: targetIsRight ? source.x + source.width : source.x,
      y: sourceCenter.y,
    };
    const endPoint = {
      x: targetIsRight ? target.x : target.x + target.width,
      y: targetCenter.y,
    };
    if (startPoint.y === endPoint.y) {
      return { id: `${edgeId}-missing-edge-route`, startPoint, endPoint };
    }
    const laneX = (startPoint.x + endPoint.x) / 2;
    return {
      id: `${edgeId}-missing-edge-route`,
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
    return { id: `${edgeId}-missing-edge-route`, startPoint, endPoint };
  }
  const laneY = (startPoint.y + endPoint.y) / 2;
  return {
    id: `${edgeId}-missing-edge-route`,
    startPoint,
    bendPoints: [
      { x: startPoint.x, y: laneY },
      { x: endPoint.x, y: laneY },
    ],
    endPoint,
  };
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

export function routeMissingEdgeSections(
  spec: DiagramSpec,
  edges: ElkExtendedEdge[],
  nodes: DiagramLayout["nodes"],
  groups: DiagramLayout["groups"],
): ElkExtendedEdge[] {
  const specEdgeById = new Map(spec.edges.map((edge) => [edge.id, edge]));
  return edges.map((edge) => {
    if ((edge.sections?.length ?? 0) > 0) return edge;
    const specEdge = specEdgeById.get(edge.id);
    if (!specEdge) return edge;
    const source = endpointShape(specEdge.from, nodes, groups);
    const target = endpointShape(specEdge.to, nodes, groups);
    if (!source || !target) return edge;
    const section = orthogonalFallbackSection(edge.id, source, target);
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
    return next;
  });
}
