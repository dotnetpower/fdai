import { describe, expect, it } from "vitest";
import { buildOntologyNeighborhood } from "./ontology-graph.model";
import type { OntologyEdge, OntologyNode } from "./ontology-graph.types";

const node = (name: string): OntologyNode => ({
  name,
  key: "id",
  property_count: 0,
  properties: [],
  description: null,
});

const edge = (name: string, fromType: string, toType: string): OntologyEdge => ({
  name,
  from_type: fromType,
  to_type: toType,
  cardinality: "many_to_one",
  is_transitive: false,
  is_causal: false,
  temporal_order: false,
  forward_role: null,
  reverse_role: null,
  semantic_traits: [],
  description: null,
});

describe("buildOntologyNeighborhood", () => {
  it("separates incoming, outgoing, and self links around the selected type", () => {
    const result = buildOntologyNeighborhood(
      [node("Agent"), node("Conversation"), node("Resource")],
      [
        edge("conducted_by", "Conversation", "Agent"),
        edge("owns", "Agent", "Resource"),
        edge("reports_to", "Agent", "Agent"),
      ],
      "Agent",
    );

    expect(result.focus?.name).toBe("Agent");
    expect(result.incoming.flatMap(({ edges }) => edges.map((relation) => relation.name))).toEqual(["conducted_by"]);
    expect(result.outgoing.flatMap(({ edges }) => edges.map((relation) => relation.name))).toEqual(["owns"]);
    expect(result.selfLinks.map((relation) => relation.name)).toEqual(["reports_to"]);
    expect([...result.nodeNames].sort()).toEqual(["Agent", "Conversation", "Resource"]);
  });

  it("falls back to the first node and ignores edges with unknown endpoints", () => {
    const result = buildOntologyNeighborhood(
      [node("Rule"), node("Resource")],
      [edge("applies_to", "Rule", "Resource"), edge("unknown", "Rule", "Missing")],
      "NotRegistered",
    );

    expect(result.focus?.name).toBe("Rule");
    expect(result.outgoing.map(({ node: target }) => target.name)).toEqual(["Resource"]);
  });

  it("groups multiple links to the same neighboring type", () => {
    const result = buildOntologyNeighborhood(
      [node("Resource"), node("Rule")],
      [edge("applies_to", "Rule", "Resource"), edge("targets", "Rule", "Resource")],
      "Resource",
    );

    expect(result.incoming).toHaveLength(1);
    expect(result.incoming[0]?.node.name).toBe("Rule");
    expect(result.incoming[0]?.edges.map((relation) => relation.name)).toEqual(["applies_to", "targets"]);
  });

  it("returns an empty neighborhood when no object types are registered", () => {
    const result = buildOntologyNeighborhood([], [], null);

    expect(result.focus).toBeNull();
    expect(result.nodeNames.size).toBe(0);
  });
});
