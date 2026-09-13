import type { RecordedGraph, RecordedLink, RecordedResource } from "./contract";

export interface SnapshotEvent {
  readonly id: string;
  readonly resourceId: string;
  readonly at: string;
  readonly recordedAt: string;
  readonly state: string | null;
  readonly before: string | null;
  readonly stateType: string;
  readonly lane: string;
  readonly authority: string;
  readonly synthetic: boolean;
  readonly conflicts: number;
  readonly completeness: number;
}
export interface OntologySnapshot {
  readonly version: 2;
  readonly source: {
    readonly kind: "local-postgresql";
    readonly capturedAt: string;
    readonly readOnly: true;
    readonly privacy: string;
    readonly catalogDigest: string;
    readonly catalogComplete: boolean;
  };
  readonly counts: {
    readonly objectTypes: number;
    readonly catalogNodes: number;
    readonly catalogLinks: number;
    readonly instances: number;
    readonly storedLinks: number;
    readonly resolvedStoredLinks: number;
    readonly unresolvedStoredLinks: number;
    readonly history: number;
    readonly historyForCurrentInstances: number;
    readonly byType: Readonly<Record<string, number>>;
  };
  readonly startAt: string;
  readonly endAt: string;
  readonly graph: RecordedGraph;
  readonly events: readonly SnapshotEvent[];
}

function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Invalid full ontology object.");
  return value as Record<string, unknown>;
}
function text(value: unknown, max = 4096) {
  if (typeof value !== "string" || !value.trim() || value.length > max) throw new Error("Invalid full ontology text.");
  return value;
}
function integer(value: unknown) {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0) throw new Error("Invalid full ontology count.");
  return value;
}
function timestamp(value: unknown) {
  const raw = text(value, 64);
  if (!/^\d{4}-\d{2}-\d{2}T.*(?:Z|[+-]\d{2}:\d{2})$/.test(raw) || !Number.isFinite(Date.parse(raw))) throw new Error("Invalid full ontology time.");
  return raw;
}
const nullableText = (value: unknown) => value === null ? null : text(value);
const nullableTime = (value: unknown) => value === null ? null : timestamp(value);
function boolean(value: unknown) { if (typeof value !== "boolean") throw new Error("Invalid full ontology flag."); return value; }
function array(value: unknown, max: number): unknown[] {
  if (!Array.isArray(value) || value.length > max) throw new Error("Full ontology export exceeds its explicit bound.");
  return value;
}
function coordinate(value: unknown) {
  if (typeof value !== "number" || !Number.isFinite(value) || Math.abs(value) > 1_000_000) throw new Error("Invalid catalog coordinate.");
  return value;
}

/** Validate exact full-map accounting. Never replace absent DB data with an illustrative specimen. */
export function decodeOntologySnapshot(input: unknown): OntologySnapshot {
  const raw = object(input);
  const source = object(raw.source);
  if (raw.version !== 2 || source.kind !== "local-postgresql" || source.readOnly !== true
    || source.isolation !== "repeatable-read" || source.databaseReadComplete !== true) throw new Error("A complete read-only local DB export is required.");
  const capturedAt = timestamp(source.capturedAt);
  const counts = object(raw.counts);
  const byType = Object.fromEntries(Object.entries(object(counts.byType)).map(([name, count]) => [name, integer(count)]));
  const resources = array(raw.nodes, 30000).map((value): RecordedResource => {
    const node = object(value);
    const kind = text(node.kind, 64);
    const common = {
      id: text(node.id), name: text(node.label, 512), nodeKind: kind,
      objectType: nullableText(node.objectType),
      resourceType: kind === "instance" ? (node.resourceType === null ? text(node.objectType) : text(node.resourceType)) : text(node.group),
      incarnation: null, states: null,
    };
    if (kind === "instance") {
      const state = object(node.state);
      return { ...common, typeNode: text(node.typeNode), revision: integer(node.revision),
        storedState: { value: nullableText(state.value), lane: text(state.lane),
          effectiveAt: nullableTime(state.effectiveAt), recordedAt: nullableTime(state.recordedAt),
          synthetic: state.synthetic === null ? null : boolean(state.synthetic) } };
    }
    return { ...common, detail: text(node.detail), community: integer(node.community),
      instanceCount: node.instanceCount === null ? null : integer(node.instanceCount),
      catalogPosition: [coordinate(node.x), coordinate(node.y)] };
  });
  const ids = new Set(resources.map((resource) => resource.id));
  if (ids.size !== resources.length) throw new Error("Duplicate full-map identity.");
  const links = array(raw.links, 150000).map((value): RecordedLink => {
    const link = object(value);
    const source = text(link.source);
    const target = text(link.target);
    if (!ids.has(source) || !ids.has(target)) throw new Error("Full-map relationship endpoint is missing.");
    if (link.origin !== "catalog" && link.origin !== "database" && link.origin !== "classification") throw new Error("Unknown relationship origin.");
    return { source, target, type: text(link.type, 256), origin: link.origin,
      evidence: { status: "stored", verification: link.origin, cutoff: capturedAt, complete: true } };
  });
  const countValues = {
    objectTypes: integer(counts.objectTypes), catalogNodes: integer(counts.catalogNodes),
    catalogLinks: integer(counts.catalogLinks), instances: integer(counts.instances),
    storedLinks: integer(counts.storedLinks), resolvedStoredLinks: integer(counts.resolvedStoredLinks),
    unresolvedStoredLinks: integer(counts.unresolvedStoredLinks), history: integer(counts.history),
    historyForCurrentInstances: integer(counts.historyForCurrentInstances), byType,
  };
  const types = resources.filter((resource) => resource.nodeKind === "object_type");
  const databaseInstances = resources.filter((resource) => resource.nodeKind === "instance");
  if (types.length !== countValues.objectTypes || databaseInstances.length !== countValues.instances
    || resources.length - databaseInstances.length !== countValues.catalogNodes
    || Object.values(byType).reduce((sum, count) => sum + count, 0) !== countValues.instances
    || links.filter((link) => link.origin === "catalog").length !== countValues.catalogLinks
    || links.filter((link) => link.origin === "database").length !== countValues.resolvedStoredLinks
    || links.filter((link) => link.origin === "classification").length !== countValues.instances
    || countValues.resolvedStoredLinks + countValues.unresolvedStoredLinks !== countValues.storedLinks) throw new Error("Full ontology export count mismatch.");
  for (const type of types) {
    const actual = databaseInstances.filter((instance) => instance.objectType === type.objectType);
    if (actual.length !== (byType[type.objectType!] ?? 0) || type.instanceCount !== actual.length) throw new Error("An ObjectType instance count is incomplete.");
  }
  for (const instance of databaseInstances) {
    if (!types.some((type) => type.id === instance.typeNode && type.objectType === instance.objectType)) throw new Error("Database instance classification is missing.");
  }
  const events = array(raw.history, 50000).map((value): SnapshotEvent => {
    const event = object(value);
    const completeness = coordinate(event.completeness);
    const effective = timestamp(event.effectiveAt);
    const recorded = timestamp(event.recordedAt);
    if (completeness < 0 || completeness > 1 || Date.parse(effective) > Date.parse(recorded)
      || Date.parse(recorded) > Date.parse(capturedAt)) throw new Error("Invalid retained transition evidence.");
    return {
      id: text(event.id), resourceId: text(event.subject), at: effective,
      recordedAt: recorded, state: nullableText(event.after),
      before: nullableText(event.before), stateType: text(event.stateType), lane: text(event.lane),
      authority: text(event.authority), synthetic: boolean(event.synthetic),
      conflicts: integer(event.conflicts),
      completeness,
    };
  }).sort((a, b) => Date.parse(a.at) - Date.parse(b.at) || a.id.localeCompare(b.id));
  if (events.length !== countValues.history || new Set(events.map((event) => event.id)).size !== events.length) throw new Error("State history accounting is incomplete.");
  if (events.filter((event) => ids.has(event.resourceId)).length !== countValues.historyForCurrentInstances) throw new Error("History subject coverage is incomplete.");
  const root = types.find((type) => type.objectType === "Resource")?.id ?? types[0]?.id;
  if (!root) throw new Error("Full ontology map has no ObjectTypes.");
  return {
    version: 2,
    source: { kind: "local-postgresql", capturedAt, readOnly: true,
      privacy: text(source.privacy), catalogDigest: text(source.catalogDigest), catalogComplete: boolean(source.catalogComplete) },
    counts: countValues,
    startAt: events[0]?.at ?? capturedAt, endAt: events.at(-1)?.at ?? capturedAt,
    graph: { kind: "graph", root, generation: capturedAt, cutoff: capturedAt, complete: true,
      reasons: countValues.unresolvedStoredLinks ? ["stored_links_with_absent_endpoints"] : [], resources, links },
    events,
  };
}

export async function loadOntologySnapshot(signal: AbortSignal): Promise<OntologySnapshot> {
  const response = await fetch("/__neural/ontology", { signal, credentials: "omit", cache: "no-store", redirect: "error" });
  if (!response.ok) throw new Error("The private local ontology export is unavailable. Run npm run snapshot:db.");
  const content = await response.text();
  if (content.length > 50_000_000) throw new Error("Private ontology export exceeds its size bound.");
  return decodeOntologySnapshot(JSON.parse(content));
}
