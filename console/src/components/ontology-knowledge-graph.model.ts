export const ONTOLOGY_NODE_KINDS = [
  "object_type",
  "interface_type",
  "function_type",
  "resource_type",
  "rule",
  "action_type",
  "workflow",
  "agent",
  "signal_type",
  "property",
] as const;

export const ONTOLOGY_EDGE_KINDS = [
  "link_type",
  "interface",
  "instance_of",
  "rule_dispatch",
  "workflow",
  "agent",
] as const;

export type OntologyKnowledgeNodeKind = (typeof ONTOLOGY_NODE_KINDS)[number];
export type OntologyKnowledgeEdgeKind = (typeof ONTOLOGY_EDGE_KINDS)[number];

export interface OntologyKnowledgeNode {
  readonly id: string;
  readonly label: string;
  readonly kind: OntologyKnowledgeNodeKind;
  readonly group: string;
  readonly detail: string;
  readonly community: number;
  readonly degree: number;
  x: number;
  y: number;
}

export interface OntologyKnowledgeEdge {
  readonly id: string;
  readonly source: string;
  readonly target: string;
  readonly kind: OntologyKnowledgeEdgeKind;
  readonly label: string;
}

export interface OntologyKnowledgeGraph {
  readonly schemaVersion: string;
  readonly generatedFrom: string;
  readonly ontologyReleaseDigest: string;
  readonly mutationAuthority: false;
  readonly nodes: readonly OntologyKnowledgeNode[];
  readonly edges: readonly OntologyKnowledgeEdge[];
}

export interface OntologyKnowledgeGraphSummary {
  readonly nodes: number;
  readonly edges: number;
  readonly communities: number;
  readonly actions: number;
  readonly agents: number;
  readonly topHub: OntologyKnowledgeNode | null;
}

type UnknownRecord = Record<string, unknown>;

function isRecord(value: unknown): value is UnknownRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function requiredString(record: UnknownRecord, key: string): string {
  const value = record[key];
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`ontology knowledge graph ${key} MUST be a non-empty string`);
  }
  return value;
}

function requiredNumber(record: UnknownRecord, key: string): number {
  const value = record[key];
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`ontology knowledge graph ${key} MUST be a finite number`);
  }
  return value;
}

function requiredFalse(record: UnknownRecord, key: string): false {
  if (record[key] !== false) {
    throw new Error(`ontology knowledge graph ${key} MUST be false`);
  }
  return false;
}

function decodeNode(value: unknown): OntologyKnowledgeNode {
  if (!isRecord(value)) throw new Error("ontology knowledge graph node MUST be an object");
  const kind = requiredString(value, "kind");
  if (!ONTOLOGY_NODE_KINDS.includes(kind as OntologyKnowledgeNodeKind)) {
    throw new Error(`unsupported ontology knowledge node kind: ${kind}`);
  }
  return {
    id: requiredString(value, "id"),
    label: requiredString(value, "label"),
    kind: kind as OntologyKnowledgeNodeKind,
    group: requiredString(value, "group"),
    detail: requiredString(value, "detail"),
    community: requiredNumber(value, "community"),
    degree: requiredNumber(value, "degree"),
    x: requiredNumber(value, "x"),
    y: requiredNumber(value, "y"),
  };
}

function decodeEdge(value: unknown): OntologyKnowledgeEdge {
  if (!isRecord(value)) throw new Error("ontology knowledge graph edge MUST be an object");
  const kind = requiredString(value, "kind");
  if (!ONTOLOGY_EDGE_KINDS.includes(kind as OntologyKnowledgeEdgeKind)) {
    throw new Error(`unsupported ontology knowledge edge kind: ${kind}`);
  }
  return {
    id: requiredString(value, "id"),
    source: requiredString(value, "source"),
    target: requiredString(value, "target"),
    kind: kind as OntologyKnowledgeEdgeKind,
    label: requiredString(value, "label"),
  };
}

export function decodeOntologyKnowledgeGraph(value: unknown): OntologyKnowledgeGraph {
  if (!isRecord(value) || !Array.isArray(value.nodes) || !Array.isArray(value.edges)) {
    throw new Error("ontology knowledge graph payload MUST contain node and edge arrays");
  }
  const nodes = value.nodes.map(decodeNode);
  const nodeIds = new Set(nodes.map((node) => node.id));
  if (nodeIds.size !== nodes.length) throw new Error("ontology knowledge graph node ids MUST be unique");
  const edges = value.edges.map(decodeEdge);
  for (const edge of edges) {
    if (!nodeIds.has(edge.source) || !nodeIds.has(edge.target)) {
      throw new Error(`ontology knowledge graph edge ${edge.id} has a missing endpoint`);
    }
  }
  return {
    schemaVersion: requiredString(value, "schemaVersion"),
    generatedFrom: requiredString(value, "generatedFrom"),
    ontologyReleaseDigest: requiredString(value, "ontologyReleaseDigest"),
    mutationAuthority: requiredFalse(value, "mutationAuthority"),
    nodes,
    edges,
  };
}

export function ontologyKnowledgeGraphSummary(
  graph: OntologyKnowledgeGraph,
): OntologyKnowledgeGraphSummary {
  return {
    nodes: graph.nodes.length,
    edges: graph.edges.length,
    communities: new Set(graph.nodes.map((node) => node.community)).size,
    actions: graph.nodes.filter((node) => node.kind === "action_type").length,
    agents: graph.nodes.filter((node) => node.kind === "agent").length,
    topHub: graph.nodes.reduce<OntologyKnowledgeNode | null>(
      (top, node) => top === null || node.degree > top.degree ? node : top,
      null,
    ),
  };
}
