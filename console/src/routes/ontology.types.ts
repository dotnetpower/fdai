import type { OntologyEdge, OntologyNode } from "../components/ontology-graph";
import type { OntologyKnowledgeGraph } from "../components/ontology-knowledge-graph.model";
import type { OntologySemanticModel } from "../components/ontology-semantic-model";

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
