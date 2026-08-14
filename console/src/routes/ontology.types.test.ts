import { describe, expect, it } from "vitest";
import {
  compactRecord,
  decodeOntologyGraphResponse,
  formatUnknown,
  ontologyView,
  recordValue,
} from "./ontology.types";

function graphResponse(): Record<string, unknown> {
  const digest = `sha256:${"a".repeat(64)}`;
  const semanticModel = {
    schema_version: "1.0.0",
    bands: [
      { id: "operating_scope", label: "Scope", object_types: ["Resource"] },
      { id: "operating_intent", label: "Intent", object_types: [] },
      { id: "operating_reality", label: "Reality", object_types: [] },
      { id: "decision_and_learning", label: "Decision", object_types: [] },
    ],
    lenses: ["object", "relationship", "state", "context", "action"],
    mutation_authority: false,
  };
  return {
    schema_version: "2.0.0",
    _revision: digest,
    ontology_release_digest: digest,
    mutation_authority: false,
    mermaid: "classDiagram\n",
    object_type_count: 1,
    link_type_count: 0,
    action_type_count: 0,
    interface_type_count: 0,
    function_type_count: 0,
    object_types: ["Resource"],
    link_types: [],
    action_types: [],
    interface_types: [],
    function_types: [],
    nodes: [{
      name: "Resource",
      key: "resource",
      property_count: 0,
      properties: [],
      description: null,
    }],
    edges: [],
    semantic_model: semanticModel,
    catalog_topology: {
      schemaVersion: "2.0.0",
      generatedFrom: "operator ontology projection",
      ontologyReleaseDigest: digest,
      mutationAuthority: false,
      nodes: [{
        id: "ot:Resource",
        label: "Resource",
        kind: "object_type",
        group: "ObjectTypes",
        detail: "Resource",
        community: 1,
        degree: 0,
        x: 0,
        y: 0,
      }],
      edges: [],
    },
  };
}

describe("ontology view model", () => {
  it("normalizes unsupported views to the Semantic model", () => {
    expect(ontologyView(null)).toBe("map");
    expect(ontologyView("unknown")).toBe("map");
    expect(ontologyView("links")).toBe("links");
    expect(ontologyView("actions")).toBe("actions");
    expect(ontologyView("map")).toBe("map");
    expect(ontologyView("topology")).toBe("topology");
  });

  it("formats nested safety contract records without inventing fields", () => {
    expect(compactRecord({ kind: "provider_api_error_streak", count: 3 })).toBe(
      "kind: provider_api_error_streak | count: 3",
    );
    expect(formatUnknown({ max_autonomy: "enforce_hil", min_role: "approver" })).toBe(
      "max_autonomy=enforce_hil, min_role=approver",
    );
    expect(recordValue({ kind: "both" }, "kind")).toBe("both");
    expect(recordValue(undefined, "kind")).toBeNull();
  });

  it("decodes one exact-release read-only ontology response", () => {
    const decoded = decodeOntologyGraphResponse(graphResponse());

    expect(decoded.mutation_authority).toBe(false);
    expect(decoded.catalog_topology.ontologyReleaseDigest).toBe(
      decoded.ontology_release_digest,
    );
  });

  it("rejects authority, release, band, edge identity, and numeric violations", () => {
    expect(() => decodeOntologyGraphResponse({
      ...graphResponse(),
      mutation_authority: true,
    })).toThrow("mutation_authority MUST be false");
    expect(() => decodeOntologyGraphResponse({
      ...graphResponse(),
      mutation_authority: null,
    })).toThrow("mutation_authority MUST be false");

    const mismatched = graphResponse();
    mismatched.catalog_topology = {
      ...(mismatched.catalog_topology as Record<string, unknown>),
      ontologyReleaseDigest: `sha256:${"b".repeat(64)}`,
    };
    expect(() => decodeOntologyGraphResponse(mismatched)).toThrow("release digest MUST match");

    const wrongBands = graphResponse();
    wrongBands.semantic_model = {
      ...(wrongBands.semantic_model as Record<string, unknown>),
      bands: (wrongBands.semantic_model as { bands: unknown[] }).bands.slice(0, 3),
    };
    expect(() => decodeOntologyGraphResponse(wrongBands)).toThrow("four canonical bands");

    const duplicateEdges = graphResponse();
    duplicateEdges.catalog_topology = {
      ...(duplicateEdges.catalog_topology as Record<string, unknown>),
      edges: [
        { id: "duplicate", source: "ot:Resource", target: "ot:Resource", kind: "link_type", label: "self" },
        { id: "duplicate", source: "ot:Resource", target: "ot:Resource", kind: "link_type", label: "self" },
      ],
    };
    expect(() => decodeOntologyGraphResponse(duplicateEdges)).toThrow("edge ids MUST be unique");

    const negativeDegree = graphResponse();
    const topology = negativeDegree.catalog_topology as { nodes: Record<string, unknown>[] };
    negativeDegree.catalog_topology = {
      ...(negativeDegree.catalog_topology as Record<string, unknown>),
      nodes: [{ ...topology.nodes[0], degree: -1 }],
    };
    expect(() => decodeOntologyGraphResponse(negativeDegree)).toThrow("degree MUST be non-negative");
  });
});
