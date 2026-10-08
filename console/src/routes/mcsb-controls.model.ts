import { OperatorApiError } from "../api";
import { routeHref } from "../router";
import {
  panelArray,
  panelBoolean,
  panelNonEmptyString,
  panelNonNegativeInteger,
  panelNullableString,
  panelRecord,
  panelStringArray,
} from "./panel-decode";

export const MCSB_COVERAGES = ["automated", "partial", "manual", "unmapped"] as const;
export type McsbCoverage = (typeof MCSB_COVERAGES)[number];
export const MCSB_SATISFACTIONS = ["satisfied", "failed", "not_applicable", "unknown"] as const;
export type McsbSatisfaction = (typeof MCSB_SATISFACTIONS)[number];
export const MCSB_ASSESSMENT_STATUSES = ["evaluated", "not_evaluated", "unavailable", "not_assessed"] as const;
export type McsbAssessmentStatus = (typeof MCSB_ASSESSMENT_STATUSES)[number];
export const MCSB_EVIDENCE_ROLES = ["decisive", "supporting_only"] as const;
export type McsbEvidenceRole = (typeof MCSB_EVIDENCE_ROLES)[number];

/** Server-owned shadow assessment state of one control; the browser never derives it. */
export interface McsbControlAssessment {
  readonly evaluation_status: string;
  readonly satisfaction: McsbSatisfaction;
  readonly evaluated_at: string | null;
  readonly evidence_complete: boolean;
  readonly limitations: readonly string[];
}

export interface McsbAssessmentRequirement {
  readonly kind: string;
  readonly ref: string;
  readonly evidence_role: McsbEvidenceRole;
  readonly status: McsbSatisfaction;
  readonly limitations: readonly string[];
}

export interface McsbControlDetailAssessment extends McsbControlAssessment {
  readonly requirements: readonly McsbAssessmentRequirement[];
}

export interface McsbAssessmentSummary {
  readonly status: McsbAssessmentStatus;
  readonly last_evaluated_at: string | null;
  readonly satisfaction_counts: Readonly<Record<string, number>>;
}
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
  readonly assessment: McsbControlAssessment | null;
}

export interface McsbControlDetail extends Omit<McsbControl, "assessment"> {
  readonly benchmark_version: McsbVersion;
  readonly rule_ids: readonly string[];
  readonly runtime_observation_ids: readonly string[];
  readonly manual_evidence_refs: readonly string[];
  readonly source: Readonly<Record<string, unknown>>;
  readonly evaluation_source: string;
  readonly assessment: McsbControlDetailAssessment | null;
  readonly assessment_summary: McsbAssessmentSummary | null;
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
  readonly assessment_summary: McsbAssessmentSummary | null;
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

function decodeMember<T extends string>(
  value: string,
  allowed: readonly T[],
  label: string,
): T {
  if (!allowed.includes(value as T)) {
    throw new OperatorApiError(502, `invalid Operator API response: ${label} has unknown value ${value}`);
  }
  return value as T;
}

function decodeAssessment(value: unknown, label: string): McsbControlAssessment | null {
  if (value === undefined || value === null) return null;
  const raw = panelRecord(value, label);
  return {
    evaluation_status: panelNonEmptyString(raw, "evaluation_status", label),
    satisfaction: decodeMember(
      panelNonEmptyString(raw, "satisfaction", label),
      MCSB_SATISFACTIONS,
      `${label}.satisfaction`,
    ),
    evaluated_at: panelNullableString(raw, "evaluated_at", label),
    evidence_complete: panelBoolean(raw, "evidence_complete", label),
    limitations: panelStringArray(raw["limitations"], `${label}.limitations`),
  };
}

function decodeRequirement(value: unknown, index: number): McsbAssessmentRequirement {
  const label = `MCSB assessment requirements[${index}]`;
  const raw = panelRecord(value, label);
  return {
    kind: panelNonEmptyString(raw, "kind", label),
    ref: panelNonEmptyString(raw, "ref", label),
    evidence_role: decodeMember(
      panelNonEmptyString(raw, "evidence_role", label),
      MCSB_EVIDENCE_ROLES,
      `${label}.evidence_role`,
    ),
    status: decodeMember(panelNonEmptyString(raw, "status", label), MCSB_SATISFACTIONS, `${label}.status`),
    limitations: panelStringArray(raw["limitations"], `${label}.limitations`),
  };
}

function decodeSummary(value: unknown, label: string): McsbAssessmentSummary | null {
  if (value === undefined || value === null) return null;
  const raw = panelRecord(value, label);
  if (raw["execution_authority"] !== false) {
    throw new OperatorApiError(502, `invalid Operator API response: ${label} MUST carry no authority`);
  }
  return {
    status: decodeMember(panelNonEmptyString(raw, "status", label), MCSB_ASSESSMENT_STATUSES, `${label}.status`),
    last_evaluated_at:
      raw["last_evaluated_at"] === undefined ? null : panelNullableString(raw, "last_evaluated_at", label),
    satisfaction_counts:
      raw["satisfaction_counts"] === undefined
        ? {}
        : decodeCountMap(raw["satisfaction_counts"], `${label}.satisfaction_counts`),
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
    assessment: decodeAssessment(raw["assessment"], `${label}.assessment`),
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
    assessment_summary: decodeSummary(root["assessment_summary"], "MCSB assessment summary"),
  };
}

export function decodeMcsbControlDetail(value: unknown): McsbControlDetail {
  const root = panelRecord(value, "MCSB control detail");
  const control = decodeControl({ ...root, assessment: null }, 0);
  const assessment = decodeAssessment(root["assessment"], "MCSB control detail.assessment");
  return {
    ...control,
    assessment:
      assessment === null
        ? null
        : {
            ...assessment,
            requirements: panelArray(
              panelRecord(root["assessment"], "MCSB control detail.assessment")["requirements"] ?? [],
              "MCSB control detail.assessment.requirements",
            ).map(decodeRequirement),
          },
    assessment_summary: decodeSummary(root["assessment_summary"], "MCSB assessment summary"),
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
