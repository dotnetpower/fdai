import { describe, expect, test } from "vitest";
import { OperatorApiError } from "../api";
import { blastRadiusFailure } from "./blast-radius";
import {
  decodeBlastRadiusResponse,
  blastRadiusHref,
  blastRadiusQueryFromSearch,
  blastRadiusRequestIsCurrent,
} from "./blast-radius.model";

describe("blast-radius route query", () => {
  test("rejects a simulation response superseded by a draft edit", () => {
    expect(blastRadiusRequestIsCurrent(4, 3)).toBe(false);
    expect(blastRadiusRequestIsCurrent(4, 4)).toBe(true);
  });

  test("decodes a shareable simulation query", () => {
    expect(blastRadiusQueryFromSearch(
      "?target=web-api&depth=4&links=contains,attached_to&view=production",
    )).toEqual({
      target: "web-api",
      depth: 4,
      links: ["contains", "attached_to"],
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
    expect(blastRadiusFailure(new OperatorApiError(503, "inventory unavailable")).status)
      .toBe("unavailable");
    expect(blastRadiusFailure(new OperatorApiError(500, "inventory failed"))).toEqual({
      status: "error",
      message: "inventory failed",
    });
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
});
