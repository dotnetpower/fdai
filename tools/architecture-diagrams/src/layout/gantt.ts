import type { ElkExtendedEdge } from "elkjs/lib/elk-api.js";

import type { DiagramLayout, PositionedShape } from "./elk.js";
import type { DiagramNode, DiagramSpec } from "../model/types.js";

const DAY_MS = 86_400_000;

interface ScheduledTask {
  start: number;
  end: number;
}

function temporalValue(value: number | string): number {
  if (typeof value === "number") return value;
  const parsed = Date.parse(`${value}T00:00:00Z`);
  if (!Number.isFinite(parsed)) throw new Error(`Invalid Gantt date '${value}'`);
  return parsed / DAY_MS;
}

function resolveSchedule(spec: DiagramSpec): Map<string, ScheduledTask> {
  const nodeById = new Map(spec.nodes.map((node) => [node.id, node]));
  const result = new Map<string, ScheduledTask>();
  const visiting = new Set<string>();
  const resolve = (node: DiagramNode): ScheduledTask => {
    const existing = result.get(node.id);
    if (existing) return existing;
    if (visiting.has(node.id)) {
      throw new Error(`Gantt dependency cycle includes '${node.id}'`);
    }
    visiting.add(node.id);
    const dependency = node.after ? nodeById.get(node.after) : undefined;
    if (node.after && !dependency) {
      throw new Error(`Unknown Gantt dependency '${node.after}'`);
    }
    const start = node.start !== undefined
      ? temporalValue(node.start)
      : resolve(dependency!).end;
    const end = node.end !== undefined
      ? temporalValue(node.end)
      : start + node.duration!;
    if (end <= start) throw new Error(`Gantt task '${node.id}' must end after it starts`);
    const scheduled = { start, end };
    result.set(node.id, scheduled);
    visiting.delete(node.id);
    return scheduled;
  };
  for (const node of spec.nodes) resolve(node);
  return result;
}

function dependencyEdges(
  spec: DiagramSpec,
  nodes: Map<string, PositionedShape>,
): ElkExtendedEdge[] {
  return spec.edges.map((edge) => {
    const source = nodes.get(edge.from.split(":", 1)[0]!);
    const target = nodes.get(edge.to.split(":", 1)[0]!);
    if (!source || !target) return { id: edge.id, sources: [edge.from], targets: [edge.to] };
    const startPoint = { x: source.x + source.width, y: source.y + source.height / 2 };
    const endPoint = { x: target.x, y: target.y + target.height / 2 };
    const laneX = (startPoint.x + endPoint.x) / 2;
    return {
      id: edge.id,
      sources: [edge.from],
      targets: [edge.to],
      sections: [{
        id: `${edge.id}-gantt-route`,
        startPoint,
        bendPoints: [
          { x: laneX, y: startPoint.y },
          { x: laneX, y: endPoint.y },
        ],
        endPoint,
      }],
    };
  });
}

export function layoutGantt(spec: DiagramSpec): DiagramLayout {
  const schedule = resolveSchedule(spec);
  const values = [...schedule.values()];
  const origin = Math.min(...values.map((task) => task.start));
  const finish = Math.max(...values.map((task) => task.end));
  const span = Math.max(1, finish - origin);
  const padding = spec.canvas.padding ?? 40;
  const chartWidth = Math.max(480, spec.canvas.width - padding * 2);
  const rowHeight = 34;
  const rowGap = 12;
  const groupGap = 20;
  const groupHeader = 42;
  const groupPadding = 16;
  const taskWidth = chartWidth - groupPadding * 2;
  const groups = new Map<string, PositionedShape>();
  const nodes = new Map<string, PositionedShape>();
  const sections = [
    ...spec.groups.filter((group) => !group.parent).map((group) => group.id),
    ...(spec.nodes.some((node) => !node.parent) ? ["root"] : []),
  ];
  let y = padding;
  for (const sectionId of sections) {
    const tasks = spec.nodes.filter((node) =>
      sectionId === "root" ? !node.parent : node.parent === sectionId,
    );
    if (!tasks.length) continue;
    const sectionHeight = groupHeader + groupPadding * 2 +
      tasks.length * rowHeight + Math.max(0, tasks.length - 1) * rowGap;
    if (sectionId !== "root") {
      groups.set(sectionId, {
        id: sectionId,
        x: padding,
        y,
        width: chartWidth,
        height: sectionHeight,
        depth: 0,
      });
    }
    const contentY = y + (sectionId === "root" ? 0 : groupHeader) + groupPadding;
    tasks.forEach((node, index) => {
      const task = schedule.get(node.id)!;
      nodes.set(node.id, {
        id: node.id,
        x: padding + groupPadding + ((task.start - origin) / span) * taskWidth,
        y: contentY + index * (rowHeight + rowGap),
        width: Math.max(32, ((task.end - task.start) / span) * taskWidth),
        height: rowHeight,
        depth: sectionId === "root" ? 0 : 1,
      });
    });
    y += sectionHeight + groupGap;
  }
  return {
    width: Math.max(spec.canvas.width, chartWidth + padding * 2),
    height: Math.max(spec.canvas.height, y - groupGap + padding),
    groups,
    nodes,
    edges: dependencyEdges(spec, nodes),
  };
}
