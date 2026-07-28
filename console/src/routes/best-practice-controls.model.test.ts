import { describe, expect, test } from "vitest";
import {
  bestPracticeHref,
  bestPracticeStateFromSearch,
  decodeBestPracticeDetail,
  decodeBestPracticeResponse,
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
  status: "unknown",
  satisfied_requirement_count: 0,
  evaluation_source: "not_connected",
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
