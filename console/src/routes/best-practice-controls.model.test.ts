import { describe, expect, test } from "vitest";
import {
  bestPracticeHref,
  bestPracticeStateFromSearch,
  decodeBestPracticeDetail,
  decodeBestPracticeResponse,
  decodeRuleCitingControls,
  rulesCatalogViewFromSearch,
} from "./best-practice-controls.model";

const CONTROL = {
  id: "azure-waf.reliability.re-09",
  version: "1.0.0",
  framework: "azure-waf",
  control_id: "RE:09",
  title: "Implement tested disaster recovery plans",
  rationale: "Recovery must be rehearsed.",
  severity: "critical",
  category: "reliability",
  pillar: "reliability",
  requirement_mode: "all",
  requirement_count: 2,
  owner: "resilience-owner",
  cadence_days: 30,
  catalog_status: "present",
  mapping_status: "mapped",
  evaluation_status: "not_evaluated",
  applicability: "unknown",
  satisfaction: "unknown",
  evaluation_scope: null,
  evaluated_at: null,
  status: "unknown",
  satisfied_requirement_count: 0,
  evaluation_source: "not_connected",
  profile_id: null,
  profile_digest: null,
  approved_exception: null,
  evidence_refs: [],
  evidence_digests: [],
  limitations: ["not_evaluated"],
  tradeoffs: [],
  execution_authority: false,
} as const;

function response(controls: readonly unknown[] = [CONTROL]): unknown {
  return {
    total: controls.length,
    filtered_total: controls.length,
    offset: 0,
    limit: 100,
    facets: {
      by_pillar: { reliability: controls.length },
      by_status: { unknown: controls.length },
      by_severity: { critical: controls.length },
    },
    controls,
    evaluation_source: "not_connected",
  };
}

describe("best practice controls contract", () => {
  test("decodes an evidence-honest control list", () => {
    const decoded = decodeBestPracticeResponse(response());
    expect(decoded.controls[0]?.control_id).toBe("RE:09");
    expect(decoded.controls[0]?.status).toBe("unknown");
    expect(decoded.controls[0]?.catalog_status).toBe("present");
    expect(decoded.controls[0]?.evaluation_status).toBe("not_evaluated");
    expect(decoded.evaluation_source).toBe("not_connected");
  });

  test("rejects duplicate best-practice ids", () => {
    expect(() => decodeBestPracticeResponse(response([
      CONTROL,
      { ...CONTROL, control_id: "RE:10" },
    ]))).toThrow(/ids MUST be unique/);
  });

  test("rejects impossible satisfied requirement counts", () => {
    expect(() => decodeBestPracticeResponse(response([
      { ...CONTROL, satisfied_requirement_count: 3 },
    ]))).toThrow(/exceeds requirement_count/);
  });

  test("rejects authority-bearing assessment payloads", () => {
    expect(() => decodeBestPracticeResponse(response([
      { ...CONTROL, execution_authority: true },
    ]))).toThrow(/cannot grant execution authority/);
  });

  test("reconciles detail requirements with the declared count", () => {
    expect(() => decodeBestPracticeDetail({
      ...CONTROL,
      requirements: [{
        kind: "drill",
        ref: "disaster-recovery-drill",
        freshness_days: 90,
        status: "unknown",
        evidence_refs: [],
      }],
      provenance: { source_url: "https://learn.microsoft.com/" },
    })).toThrow(/requirement count does not reconcile/);
  });

  test("decodes server-owned requirement limitations and tolerates their absence", () => {
    const requirement = {
      kind: "rule",
      ref: "cache.zone-redundant",
      freshness_days: 1,
      status: "unknown",
      evidence_refs: [],
    };
    const detail = decodeBestPracticeDetail({
      ...CONTROL,
      requirement_count: 2,
      requirements: [
        { ...requirement, limitations: ["decisive_evidence_unavailable", "rule_not_activated"] },
        { ...requirement, ref: "cache.other" },
      ],
      provenance: {},
    });
    expect(detail.requirements[0]!.limitations).toEqual(["decisive_evidence_unavailable", "rule_not_activated"]);
    expect(detail.requirements[1]!.limitations).toEqual([]);
    expect(() => decodeBestPracticeDetail({
      ...CONTROL,
      requirement_count: 1,
      requirements: [{ ...requirement, limitations: [3] }],
      provenance: {},
    })).toThrow();
  });

  test("decodes server-owned rule coverage and rejects counts that do not reconcile", () => {
    const counts = {
      activated: true,
      eligible: 3,
      covered: 2,
      compliant: 1,
      violated: 1,
      held_for_review: 0,
      missing: 1,
      duplicate: 0,
      conflicting: 0,
      unexpected: 0,
      revision_mismatch: 0,
    };
    const requirement = {
      kind: "rule",
      ref: "cache.zone-redundant",
      freshness_days: 1,
      status: "unknown",
      evidence_refs: [],
      limitations: ["pair_missing"],
    };
    const payload = (coverage: unknown) => ({
      ...CONTROL,
      requirement_count: 2,
      requirements: [
        { ...requirement, coverage },
        { ...requirement, ref: "cache.other", coverage: { activated: false } },
      ],
      rule_coverage: { status: "current", reason: null, scope_digest: "sha256:scope", resource_count: 3 },
      provenance: {},
    });

    const detail = decodeBestPracticeDetail(payload(counts));

    expect(detail.requirements[0]!.coverage).toEqual(counts);
    expect(detail.requirements[1]!.coverage).toEqual({ activated: false });
    expect(detail.rule_coverage?.status).toBe("current");
    expect(detail.rule_coverage?.matches_assessment_scope).toBeNull();
    expect(() => decodeBestPracticeDetail(payload({ ...counts, missing: 0 }))).toThrow(/do not reconcile/);
    expect(() => decodeBestPracticeDetail({
      ...payload(counts),
      rule_coverage: { status: "certified" },
    })).toThrow(/unknown value certified/);
    const legacy = decodeBestPracticeDetail({
      ...CONTROL,
      requirement_count: 1,
      requirements: [requirement],
      provenance: {},
    });
    expect(legacy.rule_coverage).toBeNull();
    expect(legacy.requirements[0]!.coverage).toBeNull();
  });
});

describe("Rule citation lookup", () => {
  test("returns Controls only for the server-confirmed Rule filter", () => {
    const value = { ...(response() as Record<string, unknown>), rule_filter: "cache.zone-redundant" };
    expect(decodeRuleCitingControls(value, "cache.zone-redundant")?.map((item) => item.control_id))
      .toEqual(["RE:09"]);
  });

  test("treats an unfiltered or mismatched list as unavailable", () => {
    expect(decodeRuleCitingControls(response(), "cache.zone-redundant")).toBeNull();
    expect(decodeRuleCitingControls(
      { ...(response() as Record<string, unknown>), rule_filter: "other.rule" },
      "cache.zone-redundant",
    )).toBeNull();
  });

  test("rejects a truncated citation list", () => {
    const value = {
      ...(response() as Record<string, unknown>),
      total: 2,
      filtered_total: 2,
      rule_filter: "cache.zone-redundant",
    };
    expect(() => decodeRuleCitingControls(value, "cache.zone-redundant")).toThrow(/truncated/);
  });
});

describe("best practice controls URL state", () => {
  test("defaults unknown views to atomic rules", () => {
    expect(rulesCatalogViewFromSearch(new URLSearchParams("view=other"))).toBe("rules");
  });

  test("round-trips filters and selected control", () => {
    const href = bestPracticeHref(
      { pillar: "reliability", status: "unknown", q: "RE:09" },
      "azure-waf.reliability.re-09",
    );
    const url = new URL(href, "https://console.example");
    expect(rulesCatalogViewFromSearch(url.searchParams)).toBe("controls");
    expect(bestPracticeStateFromSearch(url.searchParams)).toEqual({
      filters: { pillar: "reliability", status: "unknown", q: "RE:09" },
      selected: "azure-waf.reliability.re-09",
    });
  });
});
