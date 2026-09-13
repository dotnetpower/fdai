import type { RecordedGraph } from "./contract";

export type Position = readonly [number, number, number];

/** Reuse the Console map coordinates; actual instances cluster around their declared ObjectType. */
export function fullMapLayout(graph: RecordedGraph): Map<string, Position> {
  const positions = new Map<string, Position>();
  const catalog = graph.resources.filter((node) => node.catalogPosition);
  const xs = catalog.map((node) => node.catalogPosition![0]);
  const ys = catalog.map((node) => node.catalogPosition![1]);
  const centerX = (Math.min(...xs) + Math.max(...xs)) / 2;
  const centerY = (Math.min(...ys) + Math.max(...ys)) / 2;
  const scale = Math.min(56 / Math.max(1, Math.max(...xs) - Math.min(...xs)), 36 / Math.max(1, Math.max(...ys) - Math.min(...ys)));
  for (const node of catalog) {
    positions.set(node.id, [(node.catalogPosition![0] - centerX) * scale,
      -(node.catalogPosition![1] - centerY) * scale, Math.sin((node.community ?? 0) * 2.399) * 5]);
  }
  const groups = new Map<string, typeof graph.resources[number][]>();
  for (const node of graph.resources) {
    if (node.nodeKind !== "instance") continue;
    if (!groups.has(node.typeNode!)) groups.set(node.typeNode!, []);
    groups.get(node.typeNode!)!.push(node);
  }
  for (const [type, nodes] of groups) {
    const anchor = positions.get(type);
    if (!anchor) throw new Error("Instance type anchor is absent.");
    [...nodes].sort((a, b) => a.id.localeCompare(b.id)).forEach((node, index) => {
      const fraction = (index + 0.5) / nodes.length;
      const angle = index * 2.399963;
      const radius = 1.4 + Math.cbrt(fraction) * 3.6;
      const z = 1 - 2 * fraction;
      const planar = Math.sqrt(1 - z * z);
      positions.set(node.id, [
        anchor[0] + Math.cos(angle) * radius * planar,
        anchor[1] + Math.sin(angle) * radius * planar,
        anchor[2] + z * radius,
      ]);
    });
  }
  return positions;
}

/** Deterministic topology springs. Retained identities keep their positions on state-only refreshes. */
export function layoutRelationships(graph: RecordedGraph, previous: ReadonlyMap<string, Position> = new Map()): Map<string, Position> {
  if (graph.resources.some((node) => node.catalogPosition)) return fullMapLayout(graph);
  const ordered = [...graph.resources].sort((a, b) => a.id.localeCompare(b.id));
  const positions = new Map<string, [number, number, number]>();
  ordered.forEach((resource, index) => {
    const existing = previous.get(resource.id);
    const radius = 10 + Math.sqrt(index + 1) * 2;
    const angle = index * 2.399963;
    positions.set(resource.id, existing ? [...existing] : resource.id === graph.root ? [0, 0, 0]
      : [Math.cos(angle) * radius, Math.sin(angle) * radius * 0.65, Math.sin(index * 1.73) * 8]);
  });
  if (previous.size) return positions;
  for (let iteration = 0; iteration < 70; iteration++) {
    const forces = new Map(ordered.map((resource) => [resource.id, [0, 0, 0]]));
    for (let i = 0; i < ordered.length; i++) {
      const first = ordered[i]!.id;
      const a = positions.get(first)!;
      for (let j = i + 1; j < ordered.length; j++) {
        const second = ordered[j]!.id;
        const b = positions.get(second)!;
        const d = a.map((coordinate, axis) => coordinate - b[axis]!);
        const squared = Math.max(3, d.reduce((sum, value) => sum + value * value, 0));
        const force = Math.min(0.2, 12 / squared);
        for (let axis = 0; axis < 3; axis++) {
          forces.get(first)![axis]! += d[axis]! * force;
          forces.get(second)![axis]! -= d[axis]! * force;
        }
      }
    }
    for (const link of graph.links) {
      const a = positions.get(link.source)!;
      const b = positions.get(link.target)!;
      const difference = b.map((coordinate, axis) => coordinate - a[axis]!);
      const distance = Math.max(1, Math.hypot(...difference));
      const tension = Math.max(-0.05, Math.min(0.05, (distance - 10) * 0.006));
      for (let axis = 0; axis < 3; axis++) {
        forces.get(link.source)![axis]! += difference[axis]! * tension;
        forces.get(link.target)![axis]! -= difference[axis]! * tension;
      }
    }
    for (const resource of ordered) {
      if (resource.id === graph.root) continue;
      const point = positions.get(resource.id)!;
      const force = forces.get(resource.id)!;
      for (let axis = 0; axis < 3; axis++) point[axis] = Math.max(-44, Math.min(44, point[axis]! + Math.max(-1, Math.min(1, force[axis]!)) * 0.45 - point[axis]! * 0.006));
    }
  }
  const extent = [0, 0, 0];
  for (const point of positions.values()) {
    for (let axis = 0; axis < 3; axis++) extent[axis] = Math.max(extent[axis]!, Math.abs(point[axis]!));
  }
  const scale = Math.min(1, 30 / Math.max(1, extent[0]!), 18 / Math.max(1, extent[1]!), 12 / Math.max(1, extent[2]!));
  for (const point of positions.values()) {
    for (let axis = 0; axis < 3; axis++) point[axis] = point[axis]! * scale;
  }
  return positions;
}

export function relationshipSubset(graph: RecordedGraph, type: string, lens: "all" | "catalog" | "instances" = "all", objectType = "all") {
  const resources = graph.resources.filter((node) =>
    (lens === "all" || (lens === "catalog" ? node.nodeKind !== "instance" : node.nodeKind === "instance" || node.nodeKind === "object_type"))
    && (objectType === "all" || node.objectType === objectType));
  const ids = new Set(resources.map((node) => node.id));
  const links = graph.links.filter((link) => ids.has(link.source) && ids.has(link.target) && (type === "all" || link.type === type));
  if (type === "all") return { resources, links };
  const endpoints = new Set([graph.root, ...links.flatMap((link) => [link.source, link.target])]);
  return { resources: resources.filter((resource) => endpoints.has(resource.id)), links };
}
