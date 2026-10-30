import { describe, expect, test } from "vitest";
import { fixtureFrameworkGuidance } from "./framework-guidance.fixture";
import {
  cafHref,
  cafStateFromSearch,
  decodeCafDetail,
  decodeCafResponse,
} from "./caf-controls.model";

const CONTROL = {
  control_id: "strategy",
  title: "Strategy",
  description: "Define measurable outcomes.",
  area: "methodology",
  reference_state: "present",
  mapping_state: "partial",
  applicability: "applicable",
  evaluation_status: "not_evaluated",
  satisfaction: "unknown",
  owner_slot: "strategy-owner",
  cadence_days: 90,
  evaluation_scope: null,
  evaluated_at: null,
  profile_id: null,
  profile_digest: null,
  approved_exception: null,
  evidence_complete: false,
  evidence_refs: [],
  evidence_digests: [],
  limitations: ["not_evaluated"],
  source_url: "https://learn.microsoft.com/azure/cloud-adoption-framework/",
  source_version: "2026-08-31",
  source_revision: "a".repeat(40),
  execution_authority: false,
} as const;

function response(controls: readonly unknown[] = [CONTROL]): unknown {
  return {
    total: controls.length,
    filtered_total: controls.length,
    offset: 0,
    limit: 100,
    facets: {
      by_area: { methodology: controls.length },
      by_applicability: { applicable: controls.length },
      by_satisfaction: { unknown: controls.length },
    },
    controls,
    evaluation_source: "not_connected",
    framework_id: "azure-caf",
    framework_version: "2026-08-31",
    catalog_digest: `sha256:${"a".repeat(64)}`,
    source_revision_digest: `sha256:${"b".repeat(64)}`,
    last_profile_id: null,
    last_evaluated_at: null,
  };
}

describe("CAF controls contract", () => {
  test("keeps a disabled guide advisory and binds exact source and control identity", () => {
    const guidance = fixtureFrameworkGuidance("azure-caf", CONTROL.control_id);
    const raw = {
      ...CONTROL, evidence_specifications: [], crosswalk: [], guidance,
      guidance_source_revision: guidance.source_revision, guidance_source_digest: guidance.source_digest,
      enablement: { severity: "medium", default_enabled: true, enabled: false, source: "profile_override", mode: "shadow", execution_authority: false },
      severity_source: "fdai_default",
    };
    const detail = decodeCafDetail(raw, CONTROL.control_id);
    expect(detail.guidance).toEqual(guidance);
    expect(detail.enablement?.enabled).toBe(false);
    expect(detail.satisfaction).toBe("unknown");
    expect(detail.applicability).toBe("applicable");
    expect(detail.execution_authority).toBe(false);
    expect(detail.source_revision).toBe(CONTROL.source_revision);
    expect(() => decodeCafDetail(raw, "govern")).toThrow(/selected control/);
  });
  test("decodes independent assessment states", () => {
    const decoded = decodeCafResponse(response());
    expect(decoded.controls[0]?.reference_state).toBe("present");
    expect(decoded.controls[0]?.applicability).toBe("applicable");
    expect(decoded.controls[0]?.satisfaction).toBe("unknown");
  });

  test("rejects authority-bearing payloads", () => {
    expect(() => decodeCafResponse(response([
      { ...CONTROL, execution_authority: true },
    ]))).toThrow(/cannot grant execution authority/);
  });

  test("decodes evidence specifications and crosswalk detail", () => {
    const detail = decodeCafDetail({
      ...CONTROL,
      evidence_specifications: [{
        requirement_id: "artifact:strategy",
        kind: "artifact",
        source_ref: "strategy",
        authoritative_producer: "governed-framework-evidence",
        blocked_dependency: null,
        scope_contract: "exact-estate",
        generation_contract: "hierarchy",
        freshness_ceiling_seconds: 7_776_000,
        completeness_required: true,
        owner_slot: "strategy-owner",
        approval_roles: ["framework-assessment-approver"],
        failure_behavior: "unknown",
        evidence_role: "decisive",
        process_phase: "procedure",
      }],
      crosswalk: [{
        target_kind: "manual_evidence",
        target_ref: "strategy",
        relationship: "full",
      }],
    });
    expect(detail.evidence_specifications[0]?.process_phase).toBe("procedure");
    expect(detail.crosswalk[0]?.relationship).toBe("full");
  });
});

describe("CAF URL state", () => {
  test("round-trips filters and selected control", () => {
    const filters = {
      area: "methodology",
      mapping_state: "partial",
      applicability: "applicable",
      evaluation_status: "not_evaluated",
      satisfaction: "unknown",
      owner_slot: "strategy-owner",
      q: "strategy",
    };
    const url = new URL(cafHref(filters, "strategy"), "https://console.example");

    expect(cafStateFromSearch(url.searchParams)).toEqual({
      filters,
      selected: "strategy",
    });
    expect(url.searchParams.get("framework")).toBe("azure-caf");
  });
});
