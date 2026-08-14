import type { OntologyEdge, OntologyNode } from "../components/ontology-graph";
import {
  decodeOntologyKnowledgeGraph,
  type OntologyKnowledgeGraph,
} from "../components/ontology-knowledge-graph.model";
import {
  decodeOntologySemanticModel,
  type OntologySemanticModel,
} from "../components/ontology-semantic-model";

export type OntologyView = "map" | "objects" | "links" | "actions" | "topology";
export type UnknownRecord = Readonly<Record<string, unknown>>;

export interface OntologyActionTypeRecord {
  readonly schema_version: string;
  readonly name: string;
  readonly version: string;
  readonly operation: string;
  readonly interfaces: readonly string[];
  readonly rollback_contract: string;
  readonly irreversible: boolean;
  readonly default_mode: string;
  readonly promotion_gate: UnknownRecord;
  readonly preconditions: readonly UnknownRecord[];
  readonly stop_conditions: readonly UnknownRecord[];
  readonly blast_radius?: UnknownRecord;
  readonly description?: string;
  readonly category?: string;
  readonly trigger_kind?: UnknownRecord;
  readonly execution_path?: string;
  readonly ceiling_by_tier?: UnknownRecord;
  readonly env_scope: string;
  readonly prod_downgrade?: UnknownRecord;
  readonly argument_schema?: UnknownRecord;
  readonly live_probe_ref?: string;
}

export interface OntologyGraphResponse {
  readonly schema_version: "2.0.0";
  readonly _revision: string;
  readonly ontology_release_digest: string;
  readonly mutation_authority: false;
  readonly mermaid: string;
  readonly object_type_count: number;
  readonly link_type_count: number;
  readonly action_type_count?: number;
  readonly object_types: readonly string[];
  readonly link_types: readonly string[];
  readonly action_types?: readonly OntologyActionTypeRecord[];
  readonly interface_type_count: number;
  readonly function_type_count: number;
  readonly interface_types: readonly UnknownRecord[];
  readonly function_types: readonly UnknownRecord[];
  readonly semantic_model: OntologySemanticModel;
  readonly catalog_topology: OntologyKnowledgeGraph;
  readonly nodes?: readonly OntologyNode[];
  readonly edges?: readonly OntologyEdge[];
}

function responseRecord(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("ontology graph response MUST be an object");
  }
  return value as Record<string, unknown>;
}

function responseString(record: Record<string, unknown>, key: string): string {
  const value = record[key];
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`ontology graph response ${key} MUST be a non-empty string`);
  }
  return value;
}

function responseCount(record: Record<string, unknown>, key: string): number {
  const value = record[key];
  if (!Number.isInteger(value) || (value as number) < 0) {
    throw new Error(`ontology graph response ${key} MUST be a non-negative integer`);
  }
  return value as number;
}

function responseArray(record: Record<string, unknown>, key: string): unknown[] {
  const value = record[key];
  if (!Array.isArray(value)) throw new Error(`ontology graph response ${key} MUST be an array`);
  return value;
}

export function decodeOntologyGraphResponse(value: unknown): OntologyGraphResponse {
  const record = responseRecord(value);
  if (record.schema_version !== "2.0.0") {
    throw new Error("ontology graph response schema_version MUST be 2.0.0");
  }
  if (record.mutation_authority !== false) {
    throw new Error("ontology graph response mutation_authority MUST be false");
  }
  const releaseDigest = responseString(record, "ontology_release_digest");
  if (!/^sha256:[a-f0-9]{64}$/.test(releaseDigest)) {
    throw new Error("ontology graph response ontology_release_digest MUST be sha256");
  }
  const objectTypes = responseArray(record, "object_types");
  const linkTypes = responseArray(record, "link_types");
  const actionTypes = responseArray(record, "action_types");
  const interfaceTypes = responseArray(record, "interface_types");
  const functionTypes = responseArray(record, "function_types");
  const counts = {
    objects: responseCount(record, "object_type_count"),
    links: responseCount(record, "link_type_count"),
    actions: responseCount(record, "action_type_count"),
    interfaces: responseCount(record, "interface_type_count"),
    functions: responseCount(record, "function_type_count"),
  };
  if (counts.objects !== objectTypes.length || counts.links !== linkTypes.length
    || counts.actions !== actionTypes.length || counts.interfaces !== interfaceTypes.length
    || counts.functions !== functionTypes.length) {
    throw new Error("ontology graph response declaration counts MUST match their records");
  }
  if (objectTypes.some((item) => typeof item !== "string")
    || linkTypes.some((item) => typeof item !== "string")) {
    throw new Error("ontology graph response declaration names MUST be strings");
  }
  const semanticModel = decodeOntologySemanticModel(record.semantic_model);
  const topology = decodeOntologyKnowledgeGraph(record.catalog_topology);
  if (topology.ontologyReleaseDigest !== releaseDigest) {
    throw new Error("ontology graph response topology release digest MUST match registry release");
  }
  const nodes = responseArray(record, "nodes") as unknown as OntologyNode[];
  const edges = responseArray(record, "edges") as unknown as OntologyEdge[];
  if (nodes.length !== counts.objects || edges.length !== counts.links) {
    throw new Error("ontology graph response node and edge counts MUST match declarations");
  }
  return {
    schema_version: "2.0.0",
    _revision: responseString(record, "_revision"),
    ontology_release_digest: releaseDigest,
    mutation_authority: false,
    mermaid: responseString(record, "mermaid"),
    object_type_count: counts.objects,
    link_type_count: counts.links,
    action_type_count: counts.actions,
    interface_type_count: counts.interfaces,
    function_type_count: counts.functions,
    object_types: objectTypes as string[],
    link_types: linkTypes as string[],
    action_types: actionTypes as unknown as OntologyActionTypeRecord[],
    interface_types: interfaceTypes as UnknownRecord[],
    function_types: functionTypes as UnknownRecord[],
    semantic_model: semanticModel,
    catalog_topology: topology,
    nodes,
    edges,
  };
}

export function ontologyView(value: string | null): OntologyView {
  return value === "objects"
    || value === "links"
    || value === "actions"
    || value === "topology"
    ? value
    : "map";
}

export function recordValue(record: UnknownRecord | undefined, key: string): string | null {
  const value = record?.[key];
  if (value === null || value === undefined) return null;
  return String(value);
}

export function compactRecord(record: UnknownRecord): string {
  return Object.entries(record)
    .map(([key, value]) => `${key}: ${formatUnknown(value)}`)
    .join(" | ");
}

export function formatUnknown(value: unknown): string {
  if (value === null || value === undefined) return "-";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (Array.isArray(value)) return value.map(formatUnknown).join(", ");
  if (typeof value === "object") {
    return Object.entries(value as Record<string, unknown>)
      .map(([key, nested]) => `${key}=${formatUnknown(nested)}`)
      .join(", ");
  }
  return String(value);
}
