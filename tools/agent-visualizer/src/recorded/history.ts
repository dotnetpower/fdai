import type { RecordedAxis, RecordedFact, RecordedGraph } from "./contract";

export interface ObservedChange {
  readonly id: string;
  readonly resourceId: string;
  readonly name: string;
  readonly axis: RecordedAxis;
  readonly before: RecordedFact;
  readonly after: RecordedFact;
  readonly generation: string;
  readonly readAt: string;
}

export const AXES: readonly RecordedAxis[] = ["operational", "provisioning", "availability"];

/** Compare actual recorded facts only. Missing/unknown/new incarnation isn't a proven transition. */
export function observedChanges(before: RecordedGraph, after: RecordedGraph, readAt: string): ObservedChange[] {
  if (before.root !== after.root) return [];
  const previous = new Map(before.resources.map((resource) => [resource.id, resource]));
  const changes: ObservedChange[] = [];
  for (const resource of after.resources) {
    const old = previous.get(resource.id);
    if (!old || old.incarnation !== resource.incarnation) continue;
    for (const axis of AXES) {
      const first = old.states?.[axis];
      const last = resource.states?.[axis];
      if (!first || !last || first.value === null || last.value === null || first.value === last.value
        || first.freshness === "unknown" || last.freshness === "unknown"
        || first.conflicts.length || last.conflicts.length
        || !first.observed_at || !last.observed_at || !last.recorded_at
        || !first.source_path || first.source_path !== last.source_path
        || Date.parse(last.observed_at) <= Date.parse(first.observed_at)) continue;
      changes.push({
        id: JSON.stringify([resource.id, resource.incarnation, axis, first.observed_at, last.observed_at, first.value, last.value]),
        resourceId: resource.id, name: resource.name ?? resource.resourceType, axis,
        before: first, after: last, generation: after.generation, readAt,
      });
    }
  }
  return changes;
}

export function mergeChanges(existing: readonly ObservedChange[], incoming: readonly ObservedChange[]) {
  const result = new Map(existing.map((change) => [change.id, change]));
  incoming.forEach((change) => result.set(change.id, change));
  return [...result.values()].slice(-300);
}
