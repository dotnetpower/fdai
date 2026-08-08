import type { ElkExtendedEdge } from "elkjs/lib/elk-api.js";

import type { DiagramLayout, PositionedShape } from "./elk.js";
import type { DiagramSpec } from "../model/types.js";

function straightEdges(
  spec: DiagramSpec,
  nodes: Map<string, PositionedShape>,
): ElkExtendedEdge[] {
  return spec.edges.map((edge) => {
    const source = nodes.get(edge.from.split(":", 1)[0]!);
    const target = nodes.get(edge.to.split(":", 1)[0]!);
    if (!source || !target) return { id: edge.id, sources: [edge.from], targets: [edge.to] };
    return {
      id: edge.id,
      sources: [edge.from],
      targets: [edge.to],
      sections: [{
        id: `${edge.id}-specialized-route`,
        startPoint: { x: source.x + source.width / 2, y: source.y + source.height / 2 },
        endPoint: { x: target.x + target.width / 2, y: target.y + target.height / 2 },
      }],
    };
  });
}

export function layoutCoordinate(spec: DiagramSpec): DiagramLayout {
  const padding = spec.canvas.padding ?? 56;
  const width = Math.max(480, spec.canvas.width - padding * 2);
  const height = Math.max(320, spec.canvas.height - padding * 2);
  const nodes = new Map<string, PositionedShape>();
  spec.nodes.forEach((node, index) => {
    const diameter = spec.kind === "venn"
      ? Math.max(80, (node.size ?? 32) * 4)
      : Math.max(24, node.size ?? 30);
    const centerX = padding + (node.xValue! / 100) * width;
    const centerY = padding + ((100 - node.yValue!) / 100) * height;
    nodes.set(node.id, {
      id: node.id,
      x: centerX - diameter / 2,
      y: centerY - diameter / 2,
      width: diameter,
      height: diameter,
      depth: 0,
      paletteIndex: index,
    });
  });
  return {
    width: Math.max(spec.canvas.width, width + padding * 2),
    height: Math.max(spec.canvas.height, height + padding * 2),
    groups: new Map(),
    nodes,
    edges: straightEdges(spec, nodes),
  };
}

function polarPoint(
  centerX: number,
  centerY: number,
  radius: number,
  angle: number,
): { x: number; y: number } {
  return {
    x: centerX + Math.cos(angle) * radius,
    y: centerY + Math.sin(angle) * radius,
  };
}

function pieLayout(spec: DiagramSpec): DiagramLayout {
  const width = Math.max(640, spec.canvas.width);
  const height = Math.max(480, spec.canvas.height);
  const centerX = width / 2;
  const centerY = height / 2;
  const radius = Math.min(width, height) * 0.32;
  const total = spec.nodes.reduce((sum, node) => sum + node.value!, 0);
  const nodes = new Map<string, PositionedShape>();
  let angle = -Math.PI / 2;
  spec.nodes.forEach((node, index) => {
    const sweep = node.value! / total * Math.PI * 2;
    const nextAngle = angle + sweep;
    const start = polarPoint(centerX, centerY, radius, angle);
    const end = polarPoint(centerX, centerY, radius, nextAngle);
    const largeArc = sweep > Math.PI ? 1 : 0;
    const middle = polarPoint(centerX, centerY, radius * 0.65, angle + sweep / 2);
    nodes.set(node.id, {
      id: node.id,
      x: middle.x - 62,
      y: middle.y - 24,
      width: 124,
      height: 48,
      depth: 0,
      path: `M${centerX} ${centerY} L${start.x} ${start.y} A${radius} ${radius} 0 ${largeArc} 1 ${end.x} ${end.y} Z`,
      paletteIndex: index,
    });
    angle = nextAngle;
  });
  return { width, height, groups: new Map(), nodes, edges: [] };
}

function radarLayout(spec: DiagramSpec): DiagramLayout {
  const width = Math.max(640, spec.canvas.width);
  const height = Math.max(480, spec.canvas.height);
  const centerX = width / 2;
  const centerY = height / 2;
  const radius = Math.min(width, height) * 0.34;
  const nodes = new Map<string, PositionedShape>();
  spec.nodes.forEach((node, index) => {
    const angle = -Math.PI / 2 + index / spec.nodes.length * Math.PI * 2;
    const point = polarPoint(centerX, centerY, radius * node.value! / 100, angle);
    const diameter = Math.max(36, node.size ?? 36);
    nodes.set(node.id, {
      id: node.id,
      x: point.x - diameter / 2,
      y: point.y - diameter / 2,
      width: diameter,
      height: diameter,
      depth: 0,
      paletteIndex: index,
    });
  });
  return {
    width,
    height,
    groups: new Map(),
    nodes,
    edges: straightEdges(spec, nodes),
  };
}

export function layoutRadial(spec: DiagramSpec): DiagramLayout {
  return spec.kind === "pie" ? pieLayout(spec) : radarLayout(spec);
}

export function layoutGrid(spec: DiagramSpec): DiagramLayout {
  const padding = spec.canvas.padding ?? 40;
  const gap = 20;
  const groups = new Map<string, PositionedShape>();
  const nodes = new Map<string, PositionedShape>();
  const rootGroups = spec.groups.filter((group) => !group.parent);
  const columnCount = Math.max(
    1,
    rootGroups.length,
    ...spec.nodes.map((node) => (node.column ?? 0) + 1),
  );
  const columnWidth = (spec.canvas.width - padding * 2 - gap * (columnCount - 1)) / columnCount;
  rootGroups.forEach((group, groupIndex) => {
    const x = padding + groupIndex * (columnWidth + gap);
    const tasks = spec.nodes.filter((node) => node.parent === group.id);
    const height = Math.max(180, 64 + tasks.length * 88);
    groups.set(group.id, { id: group.id, x, y: padding, width: columnWidth, height, depth: 0 });
    tasks.forEach((node, index) => {
      nodes.set(node.id, {
        id: node.id,
        x: x + 18,
        y: padding + 50 + index * 82,
        width: columnWidth - 36,
        height: 64,
        depth: 1,
        paletteIndex: index,
      });
    });
  });
  const rootNodes = spec.nodes.filter((node) => !node.parent);
  if (spec.kind === "packet" && rootNodes.length) {
    const total = rootNodes.reduce((sum, node) => sum + (node.value ?? 1), 0);
    let x = padding;
    rootNodes.forEach((node, index) => {
      const nodeWidth = (spec.canvas.width - padding * 2) * (node.value ?? 1) / total;
      nodes.set(node.id, { id: node.id, x, y: padding, width: nodeWidth, height: 84, depth: 0, paletteIndex: index });
      x += nodeWidth;
    });
  } else {
    rootNodes.forEach((node, index) => {
      const column = node.column ?? index % columnCount;
      const row = node.row ?? Math.floor(index / columnCount);
      nodes.set(node.id, {
        id: node.id,
        x: padding + column * (columnWidth + gap),
        y: padding + row * 92,
        width: columnWidth,
        height: 72,
        depth: 0,
        paletteIndex: index,
      });
    });
  }
  const bottom = Math.max(
    spec.canvas.height,
    ...[...groups.values(), ...nodes.values()].map((shape) => shape.y + shape.height + padding),
  );
  return {
    width: spec.canvas.width,
    height: bottom,
    groups,
    nodes,
    edges: straightEdges(spec, nodes),
  };
}
