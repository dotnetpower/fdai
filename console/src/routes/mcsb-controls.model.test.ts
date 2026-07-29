import { describe, expect, test } from "vitest";
import {
  decodeMcsbControlDetail,
  decodeMcsbControlResponse,
  mcsbControlsHref,
  mcsbStateFromSearch,
} from "./mcsb-controls.model";

const CONTROL = {
  control_id: "DP-3",
  title: "Encrypt sensitive data in transit",
  domain: "DP",
  coverage: "partial",
  rule_count: 3,
  runtime_observation_count: 1,
  manual_evidence_count: 0,
} as const;

const BENCHMARK = {
  benchmark_version: "v1",
  title: "Microsoft Cloud Security Benchmark v1",
  status: "stable",
  control_import_status: "complete",
  control_count: 86,
  coverage_counts: { partial: 16, manual: 9, unmapped: 61 },
  policy_profiles: [{ profile_id: "mcsb-v1", policy_ref_count: 222 }],
} as const;

function response(controls: readonly unknown[] = [CONTROL]): unknown {
  return {
    benchmark: BENCHMARK,
    versions: [BENCHMARK],
    total: controls.length,
    filtered_total: controls.length,
    offset: 0,
    limit: 100,
    facets: { by_domain: { DP: controls.length }, by_coverage: { partial: controls.length } },
    controls,
    evaluation_source: "catalog_crosswalk",
  };
}

describe("MCSB controls contract", () => {
  test("decodes coverage without inventing compliance status", () => {
    const decoded = decodeMcsbControlResponse(response());
    expect(decoded.controls[0]?.control_id).toBe("DP-3");
    expect(decoded.controls[0]?.coverage).toBe("partial");
    expect(decoded.evaluation_source).toBe("catalog_crosswalk");
  });

  test("rejects unknown coverage and duplicate ids", () => {
    expect(() => decodeMcsbControlResponse(response([{ ...CONTROL, coverage: "passed" }]))).toThrow(
      /unknown coverage/,
    );
    expect(() => decodeMcsbControlResponse(response([CONTROL, CONTROL]))).toThrow(/ids MUST be unique/);
  });

  test("decodes detail crosswalk references", () => {
    const detail = decodeMcsbControlDetail({
      ...CONTROL,
      benchmark_version: "v1",
      rule_ids: ["object-storage.https-only.required"],
      runtime_observation_ids: ["mysql-tls"],
      manual_evidence_refs: [],
      source: { source_url: "https://learn.microsoft.com/" },
      evaluation_source: "catalog_crosswalk",
    });
    expect(detail.rule_ids).toEqual(["object-storage.https-only.required"]);
  });
});

describe("MCSB controls URL state", () => {
  test("round-trips version, filters, and selection", () => {
    const href = mcsbControlsHref(
      "v2-preview",
      { domain: "AI", coverage: "unmapped", q: "platform" },
      "AI-1",
    );
    const url = new URL(href, "https://console.example");
    expect(mcsbStateFromSearch(url.searchParams)).toEqual({
      version: "v2-preview",
      filters: { domain: "AI", coverage: "unmapped", q: "platform" },
      selected: "AI-1",
    });
  });
});
