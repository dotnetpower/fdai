/** Bounded presentation data. A snapshot never grants operational authority. */

export interface RecordedFact {
  readonly value: string | null;
  readonly source_path: string | null;
  readonly observed_at: string | null;
  readonly recorded_at: string | null;
  readonly freshness: "fresh" | "stale" | "unknown";
  readonly completeness: number | null;
  readonly conflicts: readonly string[];
  readonly reason: string | null;
}
export type RecordedAxis = "operational" | "provisioning" | "availability";
export interface RecordedResource {
  readonly id: string;
  readonly name: string | null;
  readonly resourceType: string;
  readonly incarnation: string | null;
  readonly states: Readonly<Record<RecordedAxis, RecordedFact>> | null;
  readonly presentationState?: string | null;
  readonly nodeKind?: string;
  readonly objectType?: string | null;
  readonly instanceCount?: number | null;
  readonly catalogPosition?: readonly [number, number];
  readonly typeNode?: string;
  readonly community?: number;
  readonly detail?: string;
  readonly revision?: number;
  readonly storedState?: {
    readonly value: string | null;
    readonly lane: string;
    readonly effectiveAt: string | null;
    readonly recordedAt: string | null;
    readonly synthetic: boolean | null;
  };
}
export interface RecordedLink {
  readonly source: string;
  readonly target: string;
  readonly type: string;
  readonly origin?: "catalog" | "database" | "classification";
  readonly evidence: {
    readonly status: string;
    readonly verification: string;
    readonly cutoff: string | null;
    readonly complete: boolean;
  };
}
export interface RecordedDirectory {
  readonly kind: "directory";
  readonly generation: string;
  readonly cutoff: string;
  readonly complete: boolean;
  readonly resources: readonly RecordedResource[];
}
export interface RecordedGraph {
  readonly kind: "graph";
  readonly root: string;
  readonly generation: string;
  readonly cutoff: string;
  readonly complete: boolean;
  readonly reasons: readonly string[];
  readonly resources: readonly RecordedResource[];
  readonly links: readonly RecordedLink[];
}

function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Malformed recorded ontology response.");
  return value as Record<string, unknown>;
}
function text(value: unknown, maximum = 2048): string {
  if (typeof value !== "string" || !value.trim() || value.length > maximum) throw new Error("Malformed recorded ontology text.");
  return value;
}
function nullableText(value: unknown) { return value === null ? null : text(value); }
function timestamp(value: unknown) {
  const raw = text(value, 64);
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(raw) || !Number.isFinite(Date.parse(raw))) throw new Error("Malformed recorded ontology timestamp.");
  return raw;
}
function boolean(value: unknown) {
  if (typeof value !== "boolean") throw new Error("Malformed recorded ontology flag.");
  return value;
}
function array(value: unknown, max: number): unknown[] {
  if (!Array.isArray(value) || value.length > max) throw new Error("Recorded ontology response exceeds its bounded contract.");
  return value;
}


function decodeFact(value: unknown): RecordedFact {
  const raw = record(value);
  if (!["fresh", "stale", "unknown"].includes(String(raw.freshness))) throw new Error("Invalid recorded freshness.");
  const completeness = raw.completeness;
  if (completeness !== null && (typeof completeness !== "number" || !Number.isFinite(completeness) || completeness < 0 || completeness > 1)) throw new Error("Invalid recorded completeness.");
  const observed = raw.observed_at === null ? null : timestamp(raw.observed_at);
  const recorded = raw.recorded_at === null ? null : timestamp(raw.recorded_at);
  if (observed && recorded && Date.parse(observed) > Date.parse(recorded)) throw new Error("Reversed recorded fact times.");
  const result = {
    value: nullableText(raw.value), source_path: nullableText(raw.source_path),
    observed_at: observed, recorded_at: recorded,
    freshness: raw.freshness as RecordedFact["freshness"], completeness,
    conflicts: array(raw.conflicts, 64).map((entry) => text(entry)),
    reason: nullableText(raw.reason),
  };
  if (result.value !== null && result.source_path === null) throw new Error("Recorded state lacks its source field.");
  return result;
}

function decodeResource(value: unknown): RecordedResource {
  const raw = record(value);
  const facts = raw.states === null ? null : record(raw.states);
  return {
    id: text(raw.id, 1024), name: nullableText(raw.name), resourceType: text(raw.resourceType, 128),
    incarnation: nullableText(raw.incarnation),
    ...(raw.presentationState !== undefined ? { presentationState: nullableText(raw.presentationState) } : {}),
    states: facts ? { operational: decodeFact(facts.operational), provisioning: decodeFact(facts.provisioning), availability: decodeFact(facts.availability) } : null,
  };
}

/** Validate snapshot shape and strip unknown fields, including capabilities. */
export function decodeRecordedPayload(value: unknown): RecordedDirectory | RecordedGraph {
  const raw = record(value);
  if (raw.kind !== "directory" && raw.kind !== "graph") throw new Error("Unknown recorded ontology payload.");
  const resources = array(raw.resources, 200).map(decodeResource);
  const ids = new Set(resources.map((resource) => resource.id));
  if (ids.size !== resources.length) throw new Error("Duplicate recorded resource identity.");
  const common = { generation: text(raw.generation), cutoff: timestamp(raw.cutoff), complete: boolean(raw.complete), resources };
  if (raw.kind === "directory") return { kind: "directory", ...common };
  const root = text(raw.root, 1024);
  if (!ids.has(root)) throw new Error("Recorded graph root is absent.");
  const links = array(raw.links, 4000).map((value): RecordedLink => {
    const link = record(value);
    const evidence = record(link.evidence);
    const source = text(link.source, 1024);
    const target = text(link.target, 1024);
    if (!ids.has(source) || !ids.has(target)) throw new Error("Recorded relationship endpoint is absent.");
    return {
      source, target, type: text(link.type, 128),
      evidence: {
        status: text(evidence.status, 64), verification: text(evidence.verification, 64),
        cutoff: evidence.cutoff === null ? null : timestamp(evidence.cutoff), complete: boolean(evidence.complete),
      },
    };
  });
  return { kind: "graph", root, ...common, links, reasons: array(raw.reasons, 32).map((reason) => text(reason, 128)) };
}
