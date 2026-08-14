import { describe, expect, it } from "vitest";
import type { OntologyEdge, OntologyNode } from "./ontology-graph";
import {
  buildOntologySemanticProjection,
  relationshipsForSemanticNode,
  type OntologySemanticModel,
} from "./ontology-semantic-model";

const nodes: readonly OntologyNode[] = [
  { name: "BusinessService", key: "service", property_count: 0, properties: [], description: null },
  { name: "Workload", key: "workload", property_count: 0, properties: [], description: null },
  { name: "Resource", key: "resource", property_count: 0, properties: [], description: null },
];
const edges: readonly OntologyEdge[] = [
  {
    name: "implemented_by",
    from_type: "BusinessService",
    to_type: "Workload",
    cardinality: "one_to_many",
    is_transitive: false,
    is_causal: false,
    temporal_order: false,
    description: null,
  },
  {
    name: "runs_on",
    from_type: "Workload",
    to_type: "Resource",
    cardinality: "many_to_many",
    is_transitive: false,
    is_causal: false,
    temporal_order: false,
    description: null,
  },
];
const model: OntologySemanticModel = {
  schema_version: "1.0.0",
  bands: [
    {
      id: "operating_scope",
      label: "Operating scope",
      object_types: nodes.map((node) => node.name),
    },
    { id: "operating_intent", label: "Operating intent", object_types: [] },
    { id: "operating_reality", label: "Operating reality", object_types: [] },
    { id: "decision_and_learning", label: "Decision and learning", object_types: [] },
  ],
  lenses: ["object", "relationship", "state", "context", "action"],
  mutation_authority: false,
};

describe("ontology semantic model", () => {
  it("preserves reviewed bands and canonical relationship direction", () => {
    const projection = buildOntologySemanticProjection(model, nodes, edges);
    const selected = relationshipsForSemanticNode(projection.relations, "Workload");

    expect(projection.bands[0]?.nodes.map((node) => node.name)).toEqual([
      "BusinessService",
      "Workload",
      "Resource",
    ]);
    expect(selected.incoming.map((relation) => `${relation.from}->${relation.to}`)).toEqual([
      "BusinessService->Workload",
    ]);
    expect(selected.outgoing.map((relation) => `${relation.from}->${relation.to}`)).toEqual([
      "Workload->Resource",
    ]);
  });

  it("rejects duplicate or unknown ObjectType membership", () => {
    expect(() => buildOntologySemanticProjection({
      ...model,
      bands: [
        { id: "operating_scope", label: "Scope", object_types: ["Workload"] },
        { id: "operating_intent", label: "Intent", object_types: ["Workload"] },
        { id: "operating_reality", label: "Reality", object_types: [] },
        { id: "decision_and_learning", label: "Decision", object_types: [] },
      ],
    }, nodes, edges)).toThrow("MUST belong to one band");
    expect(() => buildOntologySemanticProjection({
      ...model,
      bands: [
        { id: "operating_scope", label: "Scope", object_types: ["Missing"] },
        { id: "operating_intent", label: "Intent", object_types: [] },
        { id: "operating_reality", label: "Reality", object_types: [] },
        { id: "decision_and_learning", label: "Decision", object_types: [] },
      ],
    }, nodes, edges)).toThrow("unknown ObjectType Missing");
  });
});
