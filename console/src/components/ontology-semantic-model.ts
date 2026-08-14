import type { OntologyEdge, OntologyNode } from "./ontology-graph";

export const ONTOLOGY_SEMANTIC_LENSES = [
  "object",
  "relationship",
  "state",
  "context",
  "action",
] as const;

export const ONTOLOGY_SEMANTIC_BANDS = [
  "operating_scope",
  "operating_intent",
  "operating_reality",
  "decision_and_learning",
] as const;

export type OntologySemanticLens = (typeof ONTOLOGY_SEMANTIC_LENSES)[number];

export interface OntologySemanticBand {
  readonly id: string;
  readonly label: string;
  readonly object_types: readonly string[];
}

export interface OntologySemanticModel {
  readonly schema_version: "1.0.0";
  readonly bands: readonly OntologySemanticBand[];
  readonly lenses: readonly OntologySemanticLens[];
  readonly mutation_authority: false;
}

export interface OntologySemanticRelation {
  readonly name: string;
  readonly from: string;
  readonly to: string;
  readonly cardinality: string;
  readonly isCausal: boolean;
  readonly isTransitive: boolean;
  readonly isTemporal: boolean;
}

export interface OntologySemanticBandProjection {
  readonly id: string;
  readonly label: string;
  readonly nodes: readonly OntologyNode[];
}

export interface OntologySemanticProjection {
  readonly bands: readonly OntologySemanticBandProjection[];
  readonly relations: readonly OntologySemanticRelation[];
}

export function buildOntologySemanticProjection(
  model: OntologySemanticModel,
  nodes: readonly OntologyNode[],
  edges: readonly OntologyEdge[],
): OntologySemanticProjection {
  if (model.mutation_authority !== false) {
    throw new Error("ontology semantic model MUST NOT grant mutation authority");
  }
  if (model.lenses.join("\u001f") !== ONTOLOGY_SEMANTIC_LENSES.join("\u001f")) {
    throw new Error("ontology semantic model lenses MUST match the canonical order");
  }
  if (model.bands.map((band) => band.id).join("\u001f") !== ONTOLOGY_SEMANTIC_BANDS.join("\u001f")) {
    throw new Error("ontology semantic model MUST contain four canonical bands in order");
  }
  const nodeByName = new Map(nodes.map((node) => [node.name, node]));
  const assigned = new Set<string>();
  const bands = model.bands.map((band) => ({
    id: band.id,
    label: band.label,
    nodes: band.object_types.map((name) => {
      if (assigned.has(name)) {
        throw new Error(`ontology semantic model ObjectType ${name} MUST belong to one band`);
      }
      const node = nodeByName.get(name);
      if (!node) {
        throw new Error(`ontology semantic model references unknown ObjectType ${name}`);
      }
      assigned.add(name);
      return node;
    }),
  }));
  const relations = edges
    .filter((edge) => assigned.has(edge.from_type) && assigned.has(edge.to_type))
    .map((edge) => ({
      name: edge.name,
      from: edge.from_type,
      to: edge.to_type,
      cardinality: edge.cardinality,
      isCausal: edge.is_causal,
      isTransitive: edge.is_transitive,
      isTemporal: edge.temporal_order,
    }))
    .sort((left, right) =>
      left.from.localeCompare(right.from)
      || left.to.localeCompare(right.to)
      || left.name.localeCompare(right.name));
  return { bands, relations };
}

export function decodeOntologySemanticModel(value: unknown): OntologySemanticModel {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("ontology semantic model MUST be an object");
  }
  const record = value as Record<string, unknown>;
  if (record.schema_version !== "1.0.0") {
    throw new Error("ontology semantic model schema_version MUST be 1.0.0");
  }
  if (record.mutation_authority !== false) {
    throw new Error("ontology semantic model mutation_authority MUST be false");
  }
  if (!Array.isArray(record.lenses) || record.lenses.some((item) => typeof item !== "string")) {
    throw new Error("ontology semantic model lenses MUST be strings");
  }
  if (!Array.isArray(record.bands)) {
    throw new Error("ontology semantic model bands MUST be an array");
  }
  const bands = record.bands.map((item) => {
    if (typeof item !== "object" || item === null || Array.isArray(item)) {
      throw new Error("ontology semantic band MUST be an object");
    }
    const band = item as Record<string, unknown>;
    if (typeof band.id !== "string" || typeof band.label !== "string"
      || !Array.isArray(band.object_types)
      || band.object_types.some((name) => typeof name !== "string")) {
      throw new Error("ontology semantic band fields are invalid");
    }
    return {
      id: band.id,
      label: band.label,
      object_types: band.object_types as string[],
    };
  });
  const decoded = {
    schema_version: "1.0.0",
    bands,
    lenses: record.lenses as OntologySemanticLens[],
    mutation_authority: false,
  } satisfies OntologySemanticModel;
  if (decoded.lenses.join("\u001f") !== ONTOLOGY_SEMANTIC_LENSES.join("\u001f")) {
    throw new Error("ontology semantic model lenses MUST match the canonical order");
  }
  if (decoded.bands.map((band) => band.id).join("\u001f") !== ONTOLOGY_SEMANTIC_BANDS.join("\u001f")) {
    throw new Error("ontology semantic model MUST contain four canonical bands in order");
  }
  return decoded;
}

export function relationshipsForSemanticNode(
  relations: readonly OntologySemanticRelation[],
  selectedName: string | null,
): {
  readonly incoming: readonly OntologySemanticRelation[];
  readonly outgoing: readonly OntologySemanticRelation[];
} {
  if (selectedName === null) return { incoming: [], outgoing: [] };
  return {
    incoming: relations.filter((relation) => relation.to === selectedName),
    outgoing: relations.filter((relation) => relation.from === selectedName),
  };
}
