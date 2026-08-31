import { describe, expect, test } from "vitest";
import { decodeWaraResponse, waraHref, waraStateFromSearch } from "./wara-controls.model";

const CONTROL = {
  id: "00000000-0000-0000-0000-000000000001",
  title: "Use availability zones",
  recommendation_control: "HighAvailability",
  impact: "High",
  resource_type: "Microsoft.Compute/virtualMachines",
  lifecycle: "active",
  product_group_verified: true,
  automation_available: false,
  mapping_disposition: "manual_evidence",
  mapping_state: "unmapped",
  applicability: "unknown",
  evaluation_status: "not_evaluated",
  satisfaction: "unknown",
  evaluation_scope: null,
  evaluated_at: null,
  evidence_complete: false,
  evidence_refs: [],
  evidence_digests: [],
  source_revision: "1".repeat(40),
  source_path: "azure-resources/example/recommendations.yaml",
  source_digest: `sha256:${"a".repeat(64)}`,
  query_digest: null,
  workload_tags: [],
  limitations: ["not_evaluated"],
  execution_authority: false,
} as const;

function response(controls: readonly unknown[] = [CONTROL]): unknown {
  return {
    total: controls.length,
    filtered_total: controls.length,
    offset: 0,
    limit: 100,
    facets: {
      by_resource_type: { [CONTROL.resource_type]: controls.length },
      by_lifecycle: { active: controls.length },
      by_automation_available: { false: controls.length },
      by_satisfaction: { unknown: controls.length },
    },
    controls,
    evaluation_source: "not_connected",
    source_revision: "1".repeat(40),
    crosswalk_digest: `sha256:${"b".repeat(64)}`,
  };
}

describe("WARA control contract", () => {
  test("keeps catalog, mapping, evaluation, and satisfaction independent", () => {
    const decoded = decodeWaraResponse(response());
    expect(decoded.controls[0]?.lifecycle).toBe("active");
    expect(decoded.controls[0]?.mapping_disposition).toBe("manual_evidence");
    expect(decoded.controls[0]?.evaluation_status).toBe("not_evaluated");
    expect(decoded.controls[0]?.satisfaction).toBe("unknown");
  });

  test("rejects any execution authority", () => {
    expect(() => decodeWaraResponse(response([{ ...CONTROL, execution_authority: true }]))).toThrow(
      /cannot grant execution authority/,
    );
  });

  test("rejects duplicate recommendation ids", () => {
    expect(() => decodeWaraResponse(response([CONTROL, CONTROL]))).toThrow(/ids MUST be unique/);
  });
});

describe("WARA URL state", () => {
  test("round-trips the complete filter state", () => {
    const filters = {
      resource_type: "Microsoft.Compute/virtualMachines",
      recommendation_control: "HighAvailability",
      impact: "High",
      lifecycle: "active",
      product_group_verified: "true",
      automation_available: "false",
      mapping_disposition: "manual_evidence",
      applicability: "unknown",
      evaluation_status: "not_evaluated",
      satisfaction: "unknown",
      q: "zones",
    };
    const href = waraHref(filters, CONTROL.id);
    const url = new URL(href, "https://console.example");
    expect(waraStateFromSearch(url.searchParams)).toEqual({
      filters,
      selected: CONTROL.id,
    });
  });
});
