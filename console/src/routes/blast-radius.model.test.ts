import { describe, expect, test } from "vitest";
import { OperatorApiError } from "../api";
import {
  blastRadiusFailure,
  inventoryGraphContainsImpact,
  inventoryGraphContainsImpactTarget,
  inventoryGraphMatchesImpact,
} from "./blast-radius";
import {
  decodeBlastRadiusResponse,
  blastRadiusHref,
  blastRadiusQueryFromSearch,
  blastRadiusRequestIsCurrent,
  blastRadiusResponseMatchesQuery,
  impactEdgeEvidenceState,
} from "./blast-radius.model";

describe("blast-radius route query", () => {
  test("rejects a simulation response superseded by a draft edit", () => {
    expect(blastRadiusRequestIsCurrent(4, 3)).toBe(false);
    expect(blastRadiusRequestIsCurrent(4, 4)).toBe(true);
  });

  test("binds a simulation response to the exact submitted query", () => {
    const response = decodeBlastRadiusResponse(impactResponse());
    const query = {
      target: "root",
      depth: 1,
      links: ["contains"],
      architectureView: null,
    };

    expect(blastRadiusResponseMatchesQuery(response, query)).toBe(true);
    expect(blastRadiusResponseMatchesQuery(response, {
      ...query,
      target: "other",
    })).toBe(false);
    expect(blastRadiusResponseMatchesQuery(response, {
      ...query,
      links: ["runtime_calls"],
    })).toBe(false);
  });

  test("decodes a shareable simulation query", () => {
    expect(blastRadiusQueryFromSearch(
      "?target=web-api&depth=4&links=contains,attached_to,runtime_calls&view=production",
    )).toEqual({
      target: "web-api",
      depth: 4,
      links: ["contains", "attached_to", "runtime_calls"],
      architectureView: "production",
    });
  });

  test("bounds depth and removes unsupported links", () => {
    expect(blastRadiusQueryFromSearch("?depth=99&links=unknown")).toEqual({
      target: null,
      depth: 2,
      links: ["contains", "depends_on"],
      architectureView: null,
    });
  });

  test("builds a clean URL that round-trips", () => {
    const href = blastRadiusHref({
      target: "database-primary",
      depth: 3,
      links: ["depends_on"],
      architectureView: null,
    });
    expect(href).toBe("/blast-radius?target=database-primary&depth=3&links=depends_on");
    expect(blastRadiusQueryFromSearch(new URL(href, "http://localhost").search).target)
      .toBe("database-primary");
  });

  test("preserves draft tabs and an explicitly empty link selection", () => {
    const href = blastRadiusHref({
      target: "database-primary",
      depth: 2,
      links: [],
      architectureView: "production",
    }, "map");

    expect(href).toBe(
      "/blast-radius?target=database-primary&depth=2&links=none&view=production&result=map",
    );
    expect(blastRadiusQueryFromSearch(new URL(href, "http://localhost").search).links)
      .toEqual([]);
  });

  test("distinguishes an unwired simulator from operational failures", () => {
    expect(blastRadiusFailure(new OperatorApiError(404, "Not Found")).status).toBe("unavailable");
    expect(blastRadiusFailure(new OperatorApiError(501, "Not Implemented")).status).toBe("unavailable");
    expect(blastRadiusFailure(new OperatorApiError(400, "invalid target"))).toEqual({
      status: "error",
      message: "invalid target",
    });
    expect(blastRadiusFailure(
      new OperatorApiError(503, "inventory unavailable", "projection-unavailable"),
    ).status)
      .toBe("unavailable");
    expect(blastRadiusFailure(new OperatorApiError(500, "inventory failed"))).toEqual({
      status: "error",
      message: "inventory failed",
    });
  });

  test("binds the optional map to the impact inventory snapshot", () => {
    const impact = {
      source_generation: "generation-1",
      source_cutoff: "2026-08-19T00:00:00+00:00",
    };

    expect(inventoryGraphMatchesImpact({
      snapshot_id: "generation-1",
      snapshot_at: "2026-08-19T00:30:00+00:00",
    }, impact)).toBe(true);
    expect(inventoryGraphMatchesImpact({
      snapshot_id: "generation-2",
      snapshot_at: "2026-08-19T00:00:00+00:00",
    }, impact)).toBe(false);
    expect(inventoryGraphMatchesImpact({
      snapshot_at: "2026-08-19T00:00:00Z",
    }, impact)).toBe(true);
    expect(inventoryGraphMatchesImpact({
      snapshot_at: "2026-08-19T00:30:00Z",
    }, impact)).toBe(false);
    expect(inventoryGraphMatchesImpact({
      snapshot_at: "2026-02-31T00:00:00Z",
    }, {
      source_generation: "generation-1",
      source_cutoff: "2026-03-03T00:00:00Z",
    })).toBe(false);
    expect(inventoryGraphContainsImpactTarget({
      resources: [{
        id: "root",
        type: "compute.container-app",
        name: "Root",
        status: "Ready",
      }],
    }, "root")).toBe(true);
    expect(inventoryGraphContainsImpactTarget({
      resources: [{
        id: "other",
        type: "compute.container-app",
        name: "Other",
        status: "Ready",
      }],
    }, "root")).toBe(false);
    const graph = {
      resources: [
        { id: "root", type: "compute.container-app", name: "Root", status: "Ready" },
        { id: "child", type: "compute.container-app", name: "Child", status: "Ready" },
      ],
      links: [{ source: "root", target: "child", type: "runtime_calls" as const }],
    };
    const impactGraph = {
      target: "root",
      reached: [
        { resource_id: "root", depth: 0, via_link_type: null },
        { resource_id: "child", depth: 1, via_link_type: "runtime_calls" },
      ],
      edges: [{
        source: "root",
        target: "child",
        link_type: "runtime_calls",
        depth: 1,
        verification_status: "verified" as const,
        evidence: null,
      }],
    };
    expect(inventoryGraphContainsImpact(graph, impactGraph)).toBe(true);
    expect(inventoryGraphContainsImpact(
      { ...graph, links: [] },
      impactGraph,
    )).toBe(false);
  });

  test("decodes an exact-release no-authority impact projection", () => {
    const digest = `sha256:${"a".repeat(64)}`;
    const decoded = decodeBlastRadiusResponse({
      schema_version: "1.0.0",
      ontology_release_digest: digest,
      source_generation: "generation-1",
      source_cutoff: "2026-08-19T00:00:00+00:00",
      target: "root",
      traversal_depth: 1,
      traversal_links: ["contains"],
      reached: [
        { resource_id: "root", depth: 0, via_link_type: null },
        { resource_id: "child", depth: 1, via_link_type: "contains" },
      ],
      edges: [{
        source: "root",
        target: "child",
        link_type: "contains",
        depth: 1,
        verification_status: "unverified",
      }],
      affected_count: 1,
      complete: true,
      truncated_at_depth: false,
      truncation_reasons: [],
      execution_authority: false,
      mutation_authority: false,
    });

    expect(decoded.affected_count).toBe(1);
    expect(decoded.mutation_authority).toBe(false);
    expect(decoded.relationship_evidence_complete).toBeNull();
    expect(impactEdgeEvidenceState(decoded.edges[0]!)).toBe("legacy_unverified");
  });

  test("decodes current configuration and independent relationship evidence", () => {
    const configurationEvidence = relationshipEvidence("configuration");
    const observationEvidence = relationshipEvidence("observation");
    const decoded = decodeBlastRadiusResponse({
      ...impactResponse(),
      edges: [
        {
          source: "root",
          target: "child",
          link_type: "contains",
          depth: 1,
          verification_status: "verified",
          evidence: configurationEvidence,
        },
        {
          source: "root",
          target: "observer",
          link_type: "contains",
          depth: 1,
          verification_status: "verified",
          evidence: observationEvidence,
        },
      ],
      reached: [
        { resource_id: "root", depth: 0, via_link_type: null },
        { resource_id: "child", depth: 1, via_link_type: "contains" },
        { resource_id: "observer", depth: 1, via_link_type: "contains" },
      ],
      affected_count: 2,
      relationship_evidence_complete: true,
      relationship_source_coverage: {
        materialized: 2,
        reviewed_unavailable: 0,
        unclassified: 0,
        total_candidates: 2,
        complete: true,
      },
    });

    expect(decoded.schema_version).toBe("1.1.0");
    expect(impactEdgeEvidenceState(decoded.edges[0]!)).toBe("configuration_observed");
    expect(impactEdgeEvidenceState(decoded.edges[1]!)).toBe("independently_verified");
  });

  test("keeps stale relationship evidence unresolved", () => {
    const decoded = decodeBlastRadiusResponse({
      ...impactResponse(),
      edges: [{
        source: "root",
        target: "child",
        link_type: "contains",
        depth: 1,
        verification_status: "unverified",
        evidence: {
          ...relationshipEvidence("configuration"),
          status: "stale",
          complete: false,
          reason: "relationship_evidence_stale",
        },
      }],
      relationship_evidence_complete: false,
    });

    expect(impactEdgeEvidenceState(decoded.edges[0]!)).toBe("stale");
  });

  test("preserves configuration provenance when source coverage is unavailable", () => {
    const decoded = decodeBlastRadiusResponse({
      ...impactResponse(),
      edges: [{
        source: "root",
        target: "child",
        link_type: "contains",
        depth: 1,
        verification_status: "unverified",
        evidence: {
          ...relationshipEvidence("configuration"),
          status: "unavailable",
          complete: false,
          reason: "relationship_source_coverage_unavailable",
        },
      }],
      relationship_evidence_complete: false,
      relationship_source_coverage: null,
    });

    expect(impactEdgeEvidenceState(decoded.edges[0]!)).toBe("coverage_unavailable");
    expect(decoded.edges[0]?.evidence?.source).toBe("azure-resource-graph");
    expect(decoded.edges[0]?.evidence?.mapping_id).toBe("test.relationship");
  });

  test("preserves configuration provenance when the relationship source is incomplete", () => {
    const decoded = decodeBlastRadiusResponse({
      ...impactResponse(),
      edges: [{
        source: "root",
        target: "child",
        link_type: "contains",
        depth: 1,
        verification_status: "unverified",
        evidence: {
          ...relationshipEvidence("configuration"),
          status: "unavailable",
          complete: false,
          reason: "relationship_source_incomplete",
        },
      }],
      relationship_evidence_complete: false,
      relationship_source_coverage: {
        materialized: 1,
        reviewed_unavailable: 0,
        unclassified: 1,
        total_candidates: 2,
        complete: false,
      },
    });

    expect(impactEdgeEvidenceState(decoded.edges[0]!)).toBe("source_incomplete");
    expect(decoded.edges[0]?.evidence?.source).toBe("azure-resource-graph");
    expect(decoded.edges[0]?.evidence?.mapping_id).toBe("test.relationship");
  });

  test("rejects contradictory current relationship evidence", () => {
    expect(() => decodeBlastRadiusResponse({
      ...impactResponse(),
      edges: [{
        source: "root",
        target: "child",
        link_type: "contains",
        depth: 1,
        verification_status: "unverified",
        evidence: relationshipEvidence("configuration"),
      }],
    })).toThrow("verification_status MUST match current evidence");

    expect(() => decodeBlastRadiusResponse({
      ...impactResponse(),
      edges: [{
        source: "root",
        target: "child",
        link_type: "contains",
        depth: 1,
        verification_status: "verified",
        evidence: {
          ...relationshipEvidence("configuration"),
          verification_status: "independently_verified",
        },
      }],
    })).toThrow("verification class MUST match its evidence kind");

    expect(() => decodeBlastRadiusResponse({
      ...impactResponse(),
      relationship_evidence_complete: false,
    })).toThrow("completeness MUST match every edge");

    expect(() => decodeBlastRadiusResponse({
      ...impactResponse(),
      edges: [{
        source: "root",
        target: "child",
        link_type: "contains",
        depth: 1,
        verification_status: "verified",
        evidence: {
          ...relationshipEvidence("configuration"),
          unexpected: true,
        },
      }],
    })).toThrow("relationship evidence fields MUST match schema");

    expect(() => decodeBlastRadiusResponse({
      ...impactResponse(),
      edges: [{
        source: "root",
        target: "child",
        link_type: "contains",
        depth: 1,
        verification_status: "verified",
        evidence: {
          ...relationshipEvidence("configuration"),
          cutoff: "2026-08-19T00:00:01Z",
        },
      }],
    })).toThrow("MUST carry the future-cutoff stale reason");

    expect(() => decodeBlastRadiusResponse({
      ...impactResponse(),
      edges: [{
        source: "root",
        target: "child",
        link_type: "contains",
        depth: 1,
        verification_status: "unverified",
        evidence: {
          ...relationshipEvidence("configuration"),
          status: "stale",
          complete: false,
          cutoff: "2026-08-19T00:00:01Z",
          reason: "relationship_evidence_stale",
        },
      }],
      relationship_evidence_complete: false,
    })).toThrow("MUST carry the future-cutoff stale reason");

    expect(() => decodeBlastRadiusResponse({
      ...impactResponse(),
      relationship_source_coverage: {
        materialized: 1,
        reviewed_unavailable: 1,
        unclassified: 0,
        total_candidates: 1,
        complete: true,
      },
    })).toThrow("source coverage counts MUST reconcile");
  });

  test("rejects arrays above the server traversal bounds before graph validation", () => {
    expect(() => decodeBlastRadiusResponse({
      ...impactResponse(),
      reached: Array.from({ length: 1_002 }, (_, index) => ({
        resource_id: `resource-${index}`,
        depth: index === 0 ? 0 : 1,
        via_link_type: index === 0 ? null : "contains",
      })),
    })).toThrow("reached exceeds the 1001 Resource bound");

    expect(() => decodeBlastRadiusResponse({
      ...impactResponse(),
      edges: Array.from({ length: 1_001 }, (_, index) => ({
        source: "root",
        target: `resource-${index}`,
        link_type: "contains",
        depth: 1,
        verification_status: "verified",
        evidence: relationshipEvidence("configuration"),
      })),
    })).toThrow("edges exceed the 1000 relationship bound");
  });

  test("rejects authority and contradictory completeness", () => {
    const base = {
      schema_version: "1.0.0",
      ontology_release_digest: `sha256:${"a".repeat(64)}`,
      source_generation: "generation-1",
      source_cutoff: "2026-08-19T00:00:00+00:00",
      target: "root",
      traversal_depth: 1,
      traversal_links: ["contains"],
      reached: [{ resource_id: "root", depth: 0, via_link_type: null }],
      edges: [],
      affected_count: 0,
      complete: true,
      truncated_at_depth: false,
      truncation_reasons: [],
      execution_authority: false,
      mutation_authority: false,
    };

    expect(() => decodeBlastRadiusResponse({ ...base, mutation_authority: true }))
      .toThrow("MUST be read-only");
    expect(() => decodeBlastRadiusResponse({
      ...base,
      complete: true,
      truncation_reasons: ["edge_limit"],
    })).toThrow("MUST match truncation reasons");
  });

  function relationshipEvidence(
    kind: "configuration" | "observation",
  ): Record<string, unknown> {
    return {
      status: "available",
      evidence_kind: kind,
      verification_status: kind === "configuration"
        ? "configuration_observed"
        : "independently_verified",
      source: kind === "configuration" ? "azure-resource-graph" : "runtime-telemetry",
      source_property_path: "properties.parent",
      mapping_id: "test.relationship",
      evidence_method: "deterministic-cross-check",
      cutoff: "2026-08-19T00:00:00Z",
      freshness_ceiling_seconds: 3_600,
      complete: true,
      reason: null,
    };
  }

  function impactResponse(): Record<string, unknown> {
    return {
      schema_version: "1.1.0",
      ontology_release_digest: `sha256:${"a".repeat(64)}`,
      source_generation: "generation-1",
      source_cutoff: "2026-08-19T00:00:00Z",
      target: "root",
      traversal_depth: 1,
      traversal_links: ["contains"],
      reached: [
        { resource_id: "root", depth: 0, via_link_type: null },
        { resource_id: "child", depth: 1, via_link_type: "contains" },
      ],
      edges: [{
        source: "root",
        target: "child",
        link_type: "contains",
        depth: 1,
        verification_status: "verified",
        evidence: relationshipEvidence("configuration"),
      }],
      affected_count: 1,
      complete: true,
      relationship_evidence_complete: true,
      relationship_source_coverage: {
        materialized: 1,
        reviewed_unavailable: 0,
        unclassified: 0,
        total_candidates: 1,
        complete: true,
      },
      truncated_at_depth: false,
      truncation_reasons: [],
      execution_authority: false,
      mutation_authority: false,
    };
  }

  test("rejects impact edges outside the reached projection", () => {
    expect(() => decodeBlastRadiusResponse({
      schema_version: "1.0.0",
      ontology_release_digest: `sha256:${"a".repeat(64)}`,
      source_generation: "generation-1",
      source_cutoff: "2026-08-19T00:00:00+00:00",
      target: "root",
      traversal_depth: 1,
      traversal_links: ["contains"],
      reached: [{ resource_id: "root", depth: 0, via_link_type: null }],
      edges: [{
        source: "root",
        target: "orphan",
        link_type: "contains",
        depth: 1,
        verification_status: "unverified",
      }],
      affected_count: 0,
      complete: true,
      truncated_at_depth: false,
      truncation_reasons: [],
      execution_authority: false,
      mutation_authority: false,
    })).toThrow("endpoints MUST reference reached identities");
  });

  test.each([
    {
      label: "source discovered in the same wave",
      reached: [
        { resource_id: "root", depth: 0, via_link_type: null },
        { resource_id: "source", depth: 1, via_link_type: "contains" },
        { resource_id: "target", depth: 1, via_link_type: "contains" },
      ],
      edge: {
        source: "source",
        target: "target",
        link_type: "contains",
        depth: 1,
        verification_status: "unverified",
      },
    },
    {
      label: "target deeper than the edge wave",
      reached: [
        { resource_id: "root", depth: 0, via_link_type: null },
        { resource_id: "target", depth: 2, via_link_type: "contains" },
      ],
      edge: {
        source: "root",
        target: "target",
        link_type: "contains",
        depth: 1,
        verification_status: "unverified",
      },
    },
  ])("rejects impossible breadth-first edge depth: $label", ({ reached, edge }) => {
    expect(() => decodeBlastRadiusResponse({
      schema_version: "1.0.0",
      ontology_release_digest: `sha256:${"a".repeat(64)}`,
      source_generation: "generation-1",
      source_cutoff: "2026-08-19T00:00:00+00:00",
      target: "root",
      traversal_depth: 2,
      traversal_links: ["contains"],
      reached,
      edges: [edge],
      affected_count: reached.length - 1,
      complete: true,
      truncated_at_depth: false,
      truncation_reasons: [],
      execution_authority: false,
      mutation_authority: false,
    })).toThrow("edge depth MUST follow the reached breadth-first depths");
  });

  test.each([
    {
      label: "non-null root origin",
      reached: [
        { resource_id: "root", depth: 0, via_link_type: "contains" },
        { resource_id: "child", depth: 1, via_link_type: "contains" },
      ],
      edges: [{
        source: "root",
        target: "child",
        link_type: "contains",
        depth: 1,
        verification_status: "unverified",
      }],
      message: "target root via_link_type MUST be null",
    },
    {
      label: "orphan reached node",
      reached: [
        { resource_id: "root", depth: 0, via_link_type: null },
        { resource_id: "child", depth: 1, via_link_type: "contains" },
      ],
      edges: [],
      message: "matching traversal edge provenance",
    },
    {
      label: "mismatched discovery link",
      reached: [
        { resource_id: "root", depth: 0, via_link_type: null },
        { resource_id: "child", depth: 1, via_link_type: "depends_on" },
      ],
      edges: [{
        source: "root",
        target: "child",
        link_type: "contains",
        depth: 1,
        verification_status: "unverified",
      }],
      message: "matching traversal edge provenance",
    },
  ])("rejects invalid reached-node provenance: $label", ({ reached, edges, message }) => {
    expect(() => decodeBlastRadiusResponse({
      schema_version: "1.0.0",
      ontology_release_digest: `sha256:${"a".repeat(64)}`,
      source_generation: "generation-1",
      source_cutoff: "2026-08-19T00:00:00+00:00",
      target: "root",
      traversal_depth: 1,
      traversal_links: ["contains", "depends_on"],
      reached,
      edges,
      affected_count: reached.length - 1,
      complete: true,
      truncated_at_depth: false,
      truncation_reasons: [],
      execution_authority: false,
      mutation_authority: false,
    })).toThrow(message);
  });

  test("rejects duplicate impact relationships", () => {
    const edge = {
      source: "root",
      target: "child",
      link_type: "contains",
      depth: 1,
      verification_status: "unverified",
    };

    expect(() => decodeBlastRadiusResponse({
      schema_version: "1.0.0",
      ontology_release_digest: `sha256:${"a".repeat(64)}`,
      source_generation: "generation-1",
      source_cutoff: "2026-08-19T00:00:00+00:00",
      target: "root",
      traversal_depth: 1,
      traversal_links: ["contains"],
      reached: [
        { resource_id: "root", depth: 0, via_link_type: null },
        { resource_id: "child", depth: 1, via_link_type: "contains" },
      ],
      edges: [edge, edge],
      affected_count: 1,
      complete: true,
      truncated_at_depth: false,
      truncation_reasons: [],
      execution_authority: false,
      mutation_authority: false,
    })).toThrow("MUST NOT contain duplicate relationships");
  });

  test("rejects a self-referential impact relationship", () => {
    expect(() => decodeBlastRadiusResponse({
      schema_version: "1.0.0",
      ontology_release_digest: `sha256:${"a".repeat(64)}`,
      source_generation: "generation-1",
      source_cutoff: "2026-08-19T00:00:00Z",
      target: "root",
      traversal_depth: 1,
      traversal_links: ["contains"],
      reached: [{ resource_id: "root", depth: 0, via_link_type: null }],
      edges: [{
        source: "root",
        target: "root",
        link_type: "contains",
        depth: 1,
        verification_status: "unverified",
      }],
      affected_count: 0,
      complete: true,
      truncated_at_depth: false,
      truncation_reasons: [],
      execution_authority: false,
      mutation_authority: false,
    })).toThrow("MUST NOT be a self-link");
  });
});
