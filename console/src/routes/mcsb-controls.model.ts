import { OperatorApiError } from "../api";
import { routeHref } from "../router";
import {
  panelArray,
  panelNonEmptyString,
  panelNonNegativeInteger,
  panelNullableString,
  panelRecord,
  panelStringArray,
} from "./panel-decode";

export const MCSB_COVERAGES = ["automated", "partial", "manual", "unmapped"] as const;
export type McsbCoverage = (typeof MCSB_COVERAGES)[number];
export type McsbVersion = "v1" | "v2-preview";

export interface McsbPolicyProfile {
  readonly profile_id: string;
  readonly policy_ref_count: number;
}

export interface McsbBenchmarkSummary {
  readonly benchmark_version: McsbVersion;
  readonly title: string;
  readonly status: string;
  readonly control_import_status: string;
  readonly control_count: number;
  readonly coverage_counts: Readonly<Record<string, number>>;
  readonly policy_profiles: readonly McsbPolicyProfile[];
}

export interface McsbControl {
  readonly control_id: string;
  readonly title: string;
  readonly domain: string;
  readonly coverage: McsbCoverage;
  readonly rule_count: number;
  readonly runtime_observation_count: number;
  readonly manual_evidence_count: number;
}

export interface McsbControlDetail extends McsbControl {
  readonly benchmark_version: McsbVersion;
  readonly rule_ids: readonly string[];
  readonly runtime_observation_ids: readonly string[];
  readonly manual_evidence_refs: readonly string[];
  readonly source: Readonly<Record<string, unknown>>;
  readonly evaluation_source: string;
}

export interface McsbControlResponse {
  readonly benchmark: McsbBenchmarkSummary;
  readonly versions: readonly McsbBenchmarkSummary[];
  readonly total: number;
  readonly filtered_total: number;
  readonly offset: number;
  readonly limit: number;
  readonly facets: {
    readonly by_domain: Readonly<Record<string, number>>;
    readonly by_coverage: Readonly<Record<string, number>>;
  };
  readonly controls: readonly McsbControl[];
  readonly evaluation_source: string;
}

export interface McsbFilters {
  readonly domain: string;
  readonly coverage: string;
  readonly q: string;
}

function decodeCoverage(value: string, label: string): McsbCoverage {
  if (!MCSB_COVERAGES.includes(value as McsbCoverage)) {
    throw new OperatorApiError(502, `invalid Operator API response: ${label} has unknown coverage ${value}`);
  }
  return value as McsbCoverage;
}

function decodeCountMap(value: unknown, label: string): Readonly<Record<string, number>> {
  const raw = panelRecord(value, label);
  return Object.fromEntries(
    Object.entries(raw).map(([key, count]) => {
      if (typeof count !== "number" || !Number.isInteger(count) || count < 0) {
        throw new OperatorApiError(502, `invalid Operator API response: ${label}.${key} MUST be a count`);
      }
      return [key, count];
    }),
  );
}

function decodeVersion(value: string, label: string): McsbVersion {
  if (value !== "v1" && value !== "v2-preview") {
    throw new OperatorApiError(502, `invalid Operator API response: ${label} has unknown version ${value}`);
  }
  return value;
}

function decodePolicyProfile(value: unknown, index: number): McsbPolicyProfile {
  const label = `MCSB policy profiles[${index}]`;
  const raw = panelRecord(value, label);
  return {
    profile_id: panelNonEmptyString(raw, "profile_id", label),
    policy_ref_count: panelNonNegativeInteger(raw, "policy_ref_count", label),
  };
}

function decodeBenchmark(value: unknown, label: string): McsbBenchmarkSummary {
  const raw = panelRecord(value, label);
  return {
    benchmark_version: decodeVersion(panelNonEmptyString(raw, "benchmark_version", label), label),
    title: panelNonEmptyString(raw, "title", label),
    status: panelNonEmptyString(raw, "status", label),
    control_import_status: panelNonEmptyString(raw, "control_import_status", label),
    control_count: panelNonNegativeInteger(raw, "control_count", label),
    coverage_counts: decodeCountMap(raw["coverage_counts"], `${label}.coverage_counts`),
    policy_profiles: panelArray(raw["policy_profiles"], `${label}.policy_profiles`).map(
      decodePolicyProfile,
    ),
  };
}

function decodeControl(value: unknown, index: number): McsbControl {
  const label = `MCSB controls[${index}]`;
  const raw = panelRecord(value, label);
  return {
    control_id: panelNonEmptyString(raw, "control_id", label),
    title: panelNonEmptyString(raw, "title", label),
    domain: panelNonEmptyString(raw, "domain", label),
    coverage: decodeCoverage(panelNonEmptyString(raw, "coverage", label), label),
    rule_count: panelNonNegativeInteger(raw, "rule_count", label),
    runtime_observation_count: panelNonNegativeInteger(raw, "runtime_observation_count", label),
    manual_evidence_count: panelNonNegativeInteger(raw, "manual_evidence_count", label),
  };
}

export function decodeMcsbControlResponse(value: unknown): McsbControlResponse {
  const root = panelRecord(value, "MCSB controls");
  const total = panelNonNegativeInteger(root, "total", "MCSB controls");
  const filteredTotal = panelNonNegativeInteger(root, "filtered_total", "MCSB controls");
  const offset = panelNonNegativeInteger(root, "offset", "MCSB controls");
  const limit = panelNonNegativeInteger(root, "limit", "MCSB controls");
  const controls = panelArray(root["controls"], "MCSB controls.items").map(decodeControl);
  if (filteredTotal > total || controls.length > filteredTotal || controls.length > limit) {
    throw new OperatorApiError(502, "invalid Operator API response: MCSB control totals do not reconcile");
  }
  const ids = controls.map((control) => control.control_id);
  if (new Set(ids).size !== ids.length) {
    throw new OperatorApiError(502, "invalid Operator API response: MCSB control ids MUST be unique");
  }
  const facets = panelRecord(root["facets"], "MCSB controls.facets");
  return {
    benchmark: decodeBenchmark(root["benchmark"], "MCSB benchmark"),
    versions: panelArray(root["versions"], "MCSB versions").map((item, index) =>
      decodeBenchmark(item, `MCSB versions[${index}]`),
    ),
    total,
    filtered_total: filteredTotal,
    offset,
    limit,
    facets: {
      by_domain: decodeCountMap(facets["by_domain"], "MCSB controls.facets.by_domain"),
      by_coverage: decodeCountMap(
        facets["by_coverage"],
        "MCSB controls.facets.by_coverage",
      ),
    },
    controls,
    evaluation_source: panelNonEmptyString(root, "evaluation_source", "MCSB controls"),
  };
}

export function decodeMcsbControlDetail(value: unknown): McsbControlDetail {
  const root = panelRecord(value, "MCSB control detail");
  return {
    ...decodeControl(root, 0),
    benchmark_version: decodeVersion(
      panelNonEmptyString(root, "benchmark_version", "MCSB control detail"),
      "MCSB control detail",
    ),
    rule_ids: panelStringArray(root["rule_ids"], "MCSB control detail.rule_ids"),
    runtime_observation_ids: panelStringArray(
      root["runtime_observation_ids"],
      "MCSB control detail.runtime_observation_ids",
    ),
    manual_evidence_refs: panelStringArray(
      root["manual_evidence_refs"],
      "MCSB control detail.manual_evidence_refs",
    ),
    source: panelRecord(root["source"], "MCSB control detail.source"),
    evaluation_source: panelNonEmptyString(
      root,
      "evaluation_source",
      "MCSB control detail",
    ),
  };
}

export function mcsbStateFromSearch(search: URLSearchParams): {
  readonly version: McsbVersion;
  readonly filters: McsbFilters;
  readonly selected: string | null;
} {
  return {
    version: search.get("framework") === "mcsb-v2-preview" ? "v2-preview" : "v1",
    filters: {
      domain: search.get("domain") ?? "",
      coverage: search.get("coverage") ?? "",
      q: search.get("q") ?? "",
    },
    selected: panelNullableString(
      { control: search.get("control") },
      "control",
      "MCSB URL state",
    ),
  };
}

export function mcsbControlsHref(
  version: McsbVersion,
  filters: McsbFilters,
  selected: string | null,
): string {
  return routeHref("rules", {
    params: {
      view: "controls",
      framework: `mcsb-${version}`,
      domain: filters.domain || null,
      coverage: filters.coverage || null,
      q: filters.q || null,
      control: selected,
    },
  });
}
