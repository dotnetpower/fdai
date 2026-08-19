import { describe, expect, it } from "vitest";
import {
  compactRecord,
  decodeOntologyDependents,
  decodeOntologyEvidenceHealth,
  decodeOntologyGraphResponse,
  decodeOntologyObjectTypeDetail,
  decodeOntologyReleaseDiff,
  formatUnknown,
  ontologyView,
  recordValue,
} from "./ontology.types";

function objectTypeDetail(): Record<string, unknown> {
  const digest = `sha256:${"a".repeat(64)}`;
  return {
    schema_version: "1.0.0",
    _revision: digest,
    ontology_release_digest: digest,
    declaration_kind: "object_type",
    declaration_name: "Decision",
    mutation_authority: false,
    complete: true,
    incomplete_reasons: [],
    redaction: { redacted_field_count: 0, reasons: [] },
    declaration: {
      schema_version: "1.0.0",
      name: "Decision",
      version: "1.0.0",
      key: "id",
      properties: {
        id: {
          type: "string",
          required: true,
          access_scope: "reader",
          purpose_binding: [],
        },
      },
      description: "Recorded decision.",
    },
    relationships: [{
      schema_version: "1.0.0",
      name: "based_on",
      version: "1.0.0",
      from_type: "Decision",
      to_type: "EvidenceArtifact",
      selected_type_direction: "outgoing",
      cardinality: "many_to_many",
    }],
    related_actions: [],
  };
}

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

  it("decodes one exact-release ObjectType detail without browser-side filtering", () => {
    const detail = objectTypeDetail();
    const decoded = decodeOntologyObjectTypeDetail(detail, detail.ontology_release_digest as string);

    expect(decoded.declaration.name).toBe("Decision");
    expect(Object.keys(decoded.declaration.properties)).toEqual(["id"]);
    expect(decoded.relationships[0]?.selected_type_direction).toBe("outgoing");
    expect(decoded.mutation_authority).toBe(false);
  });

  it("rejects stale release, authority, identity, and reversed relationship claims", () => {
    const digest = `sha256:${"b".repeat(64)}`;
    expect(() => decodeOntologyObjectTypeDetail(objectTypeDetail(), digest)).toThrow(
      "release MUST match registry release",
    );
    expect(() => decodeOntologyObjectTypeDetail({
      ...objectTypeDetail(),
      mutation_authority: true,
    })).toThrow("mutation_authority MUST be false");
    expect(() => decodeOntologyObjectTypeDetail({
      ...objectTypeDetail(),
      declaration_name: "Resource",
    })).toThrow("identity MUST match");
    expect(() => decodeOntologyObjectTypeDetail({
      ...objectTypeDetail(),
      relationships: [{
        ...(objectTypeDetail().relationships as Record<string, unknown>[])[0],
        selected_type_direction: "incoming",
      }],
    })).toThrow("direction MUST match exact endpoints");
  });

  it("decodes bounded exact-release dependents and rejects stale identity", () => {
    const digest = `sha256:${"a".repeat(64)}`;
    const value = {
      schema_version: "1.0.0",
      _revision: digest,
      ontology_release_digest: digest,
      declaration_kind: "object_type",
      declaration_name: "Decision",
      mutation_authority: false,
      complete: true,
      truncated: false,
      truncation_reason: null,
      dependents: [{
        kind: "link_type",
        name: "based_on",
        relationship: "references_object_type",
        evidence_ref: "LinkType:based_on",
      }],
    };

    expect(decodeOntologyDependents(value, digest, "Decision").dependents[0]?.name).toBe(
      "based_on",
    );
    expect(() => decodeOntologyDependents(value, digest, "Resource")).toThrow(
      "identity MUST match",
    );
    expect(() => decodeOntologyDependents({ ...value, truncated: true }, digest, "Decision"))
      .toThrow("MUST be inverse states");
  });

  it("decodes declaration-ref release compatibility without migration authority", () => {
    const candidate = `sha256:${"a".repeat(64)}`;
    const base = `sha256:${"b".repeat(64)}`;
    const value = {
      schema_version: "1.0.0",
      base_release_digest: base,
      candidate_release_digest: candidate,
      mutation_authority: false,
      added: [],
      changed: [],
      removed: [],
      compatibility_verdict: "compatible",
      migration_required: false,
      breaking_change: null,
      historical_schema_detail: "declaration_refs_only",
      unbound_historical_evidence: false,
      diff_digest: candidate,
      registry_truncated: false,
    };

    expect(decodeOntologyReleaseDiff(value, candidate).compatibility_verdict).toBe("compatible");
    expect(() => decodeOntologyReleaseDiff({ ...value, mutation_authority: true }, candidate))
      .toThrow("MUST be read-only");
    expect(() => decodeOntologyReleaseDiff(value, base)).toThrow("candidate MUST match");
  });

  it("keeps unavailable evidence distinct from a measured zero", () => {
    const digest = `sha256:${"a".repeat(64)}`;
    const unavailable = {
      schema_version: "1.0.0",
      _revision: digest,
      ontology_release_digest: digest,
      object_type: "Decision",
      availability: "unavailable",
      unavailable_reason: "object_type_evidence_source_not_bound",
      source: null,
      freshness_state: "unavailable",
      complete: false,
      truncated: false,
      synthetic: null,
      conflicts: [],
      drop_reasons: [],
      visible_instance_count: null,
      visible_link_count: null,
      evidence_refs: [],
      execution_authority: false,
      mutation_authority: false,
    };

    const decoded = decodeOntologyEvidenceHealth(unavailable, digest, "Decision");
    expect(decoded.visible_instance_count).toBeNull();
    expect(() => decodeOntologyEvidenceHealth({
      ...unavailable,
      visible_instance_count: 0,
    }, digest, "Decision")).toThrow("MUST NOT fabricate");
  });
});
