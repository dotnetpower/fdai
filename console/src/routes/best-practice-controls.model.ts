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

export const CONTROL_STATUSES = [
  "satisfied",
  "failed",
  "stale",
  "unknown",
  "not_applicable",
] as const;
export type ControlStatus = (typeof CONTROL_STATUSES)[number];
export type CatalogStatus = "present";
export type MappingStatus = "mapped" | "partially_mapped" | "unmapped";
export type EvaluationStatus = "not_evaluated" | "evaluated";
export type RulesCatalogView = "rules" | "controls";

export interface BestPracticeControl {
  readonly id: string;
  readonly version: string;
  readonly framework: string;
  readonly control_id: string;
  readonly title: string;
  readonly rationale: string;
  readonly severity: string;
  readonly category: string;
  readonly pillar: string;
  readonly requirement_mode: string;
  readonly requirement_count: number;
  readonly owner: string | null;
  readonly cadence_days: number;
  readonly catalog_status: CatalogStatus;
  readonly mapping_status: MappingStatus;
  readonly evaluation_status: EvaluationStatus;
  readonly applicability: ControlStatus;
  readonly satisfaction: ControlStatus;
  readonly evaluation_scope: string | null;
  readonly evaluated_at: string | null;
  readonly status: ControlStatus;
  readonly satisfied_requirement_count: number;
  readonly evaluation_source: string;
  readonly profile_id: string | null;
  readonly profile_digest: string | null;
  readonly approved_exception: ApprovedException | null;
  readonly evidence_refs: readonly string[];
  readonly evidence_digests: readonly string[];
  readonly limitations: readonly string[];
  readonly tradeoffs: readonly Readonly<Record<string, unknown>>[];
  readonly execution_authority: false;
}

export interface ApprovedException {
  readonly justification: string;
  readonly approved_by: string;
  readonly approved_at: string;
  readonly expires_at: string;
}

export interface BestPracticeRequirementView {
  readonly kind: string;
  readonly ref: string;
  readonly freshness_days: number | null;
  readonly status: ControlStatus;
  readonly evidence_refs: readonly string[];
  /** Server-owned codes explaining an unknown requirement, such as an unactivated Rule. */
  readonly limitations: readonly string[];
  /** Server-owned scoped Rule coverage counts; `null` when the server attached none. */
  readonly coverage: RequirementRuleCoverage | null;
}

export type RequirementRuleCoverage =
  | { readonly activated: false }
  | {
      readonly activated: true;
      readonly eligible: number;
      readonly covered: number;
      readonly compliant: number;
      readonly violated: number;
      readonly held_for_review: number;
      readonly missing: number;
      readonly duplicate: number;
      readonly conflicting: number;
      readonly unexpected: number;
      readonly revision_mismatch: number;
    };

export const RULE_COVERAGE_STATUSES = ["current", "stale", "unavailable"] as const;
export type RuleCoverageStatus = (typeof RULE_COVERAGE_STATUSES)[number];

/** The scoped Rule coverage read model behind the requirement counts. */
export interface RuleCoverageSummary {
  readonly status: RuleCoverageStatus;
  readonly reason: string | null;
  readonly scope_digest: string | null;
  readonly resource_count: number | null;
  readonly inventory_generation: string | null;
  readonly recorded_at: string | null;
  readonly rule_activation_generation_id: string | null;
  readonly matches_assessment_scope: boolean | null;
}

export interface BestPracticeDetail extends BestPracticeControl {
  readonly requirements: readonly BestPracticeRequirementView[];
  readonly provenance: Readonly<Record<string, unknown>>;
  readonly rule_coverage: RuleCoverageSummary | null;
}

export interface BestPracticeResponse {
  readonly total: number;
  readonly filtered_total: number;
  readonly offset: number;
  readonly limit: number;
  readonly facets: {
    readonly by_pillar: Readonly<Record<string, number>>;
    readonly by_status: Readonly<Record<string, number>>;
    readonly by_severity: Readonly<Record<string, number>>;
  };
  readonly controls: readonly BestPracticeControl[];
  readonly evaluation_source: string;
}

export interface BestPracticeFilters {
  readonly pillar: string;
  readonly status: string;
  readonly q: string;
}

function decodeStatus(value: string, label: string): ControlStatus {
  if (!CONTROL_STATUSES.includes(value as ControlStatus)) {
    throw new OperatorApiError(502, `invalid Operator API response: ${label} has unknown status ${value}`);
  }
  return value as ControlStatus;
}

function decodeEnum<T extends string>(
  value: string,
  allowed: readonly T[],
  label: string,
): T {
  if (!allowed.includes(value as T)) {
    throw new OperatorApiError(502, `invalid Operator API response: ${label} has unknown value ${value}`);
  }
  return value as T;
}

function nullableInteger(
  value: Readonly<Record<string, unknown>>,
  key: string,
  label: string,
): number | null {
  if (value[key] === null) return null;
  return panelNonNegativeInteger(value, key, label);
}

function decodeControl(value: unknown, index: number): BestPracticeControl {
  const label = `best practices.controls[${index}]`;
  const row = panelRecord(value, label);
  const requirementCount = panelNonNegativeInteger(row, "requirement_count", label);
  const satisfiedCount = panelNonNegativeInteger(row, "satisfied_requirement_count", label);
  const executionAuthority = panelBoolean(row, "execution_authority", label);
  if (executionAuthority) {
    throw new OperatorApiError(502, `invalid Operator API response: ${label} cannot grant execution authority`);
  }
  const exceptionValue = row["approved_exception"];
  const approvedException = exceptionValue === null
    ? null
    : (() => {
        const item = panelRecord(exceptionValue, `${label}.approved_exception`);
        return {
          justification: panelNonEmptyString(item, "justification", `${label}.approved_exception`),
          approved_by: panelNonEmptyString(item, "approved_by", `${label}.approved_exception`),
          approved_at: panelNonEmptyString(item, "approved_at", `${label}.approved_exception`),
          expires_at: panelNonEmptyString(item, "expires_at", `${label}.approved_exception`),
        };
      })();
  if (satisfiedCount > requirementCount) {
    throw new OperatorApiError(
      502,
      `invalid Operator API response: ${label}.satisfied_requirement_count exceeds requirement_count`,
    );
  }
  return {
    id: panelNonEmptyString(row, "id", label),
    version: panelNonEmptyString(row, "version", label),
    framework: panelNonEmptyString(row, "framework", label),
    control_id: panelNonEmptyString(row, "control_id", label),
    title: panelNonEmptyString(row, "title", label),
    rationale: panelNonEmptyString(row, "rationale", label),
    severity: panelNonEmptyString(row, "severity", label),
    category: panelNonEmptyString(row, "category", label),
    pillar: panelNonEmptyString(row, "pillar", label),
    requirement_mode: panelNonEmptyString(row, "requirement_mode", label),
    requirement_count: requirementCount,
    owner: panelNullableString(row, "owner", label),
    cadence_days: panelNonNegativeInteger(row, "cadence_days", label),
    catalog_status: decodeEnum(
      panelNonEmptyString(row, "catalog_status", label),
      ["present"] as const,
      `${label}.catalog_status`,
    ),
    mapping_status: decodeEnum(
      panelNonEmptyString(row, "mapping_status", label),
      ["mapped", "partially_mapped", "unmapped"] as const,
      `${label}.mapping_status`,
    ),
    evaluation_status: decodeEnum(
      panelNonEmptyString(row, "evaluation_status", label),
      ["not_evaluated", "evaluated"] as const,
      `${label}.evaluation_status`,
    ),
    applicability: decodeStatus(
      panelNonEmptyString(row, "applicability", label),
      `${label}.applicability`,
    ),
    satisfaction: decodeStatus(
      panelNonEmptyString(row, "satisfaction", label),
      `${label}.satisfaction`,
    ),
    evaluation_scope: panelNullableString(row, "evaluation_scope", label),
    evaluated_at: panelNullableString(row, "evaluated_at", label),
    status: decodeStatus(panelNonEmptyString(row, "status", label), label),
    satisfied_requirement_count: satisfiedCount,
    evaluation_source: panelNonEmptyString(row, "evaluation_source", label),
    profile_id: panelNullableString(row, "profile_id", label),
    profile_digest: panelNullableString(row, "profile_digest", label),
    approved_exception: approvedException,
    evidence_refs: panelStringArray(row["evidence_refs"], `${label}.evidence_refs`),
    evidence_digests: panelStringArray(row["evidence_digests"], `${label}.evidence_digests`),
    limitations: panelStringArray(row["limitations"], `${label}.limitations`),
    tradeoffs: panelArray(row["tradeoffs"], `${label}.tradeoffs`).map((item, tradeoffIndex) =>
      panelRecord(item, `${label}.tradeoffs[${tradeoffIndex}]`)
    ),
    execution_authority: false,
  };
}

function decodeFacet(value: unknown, label: string): Readonly<Record<string, number>> {
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

export function decodeBestPracticeResponse(value: unknown): BestPracticeResponse {
  const root = panelRecord(value, "best practices");
  const total = panelNonNegativeInteger(root, "total", "best practices");
  const filteredTotal = panelNonNegativeInteger(root, "filtered_total", "best practices");
  const offset = panelNonNegativeInteger(root, "offset", "best practices");
  const limit = panelNonNegativeInteger(root, "limit", "best practices");
  const controls = panelArray(root["controls"], "best practices.controls").map(decodeControl);
  if (filteredTotal > total || controls.length > filteredTotal || controls.length > limit) {
    throw new OperatorApiError(502, "invalid Operator API response: best practice totals do not reconcile");
  }
  const ids = controls.map((control) => control.id);
  const controlIds = controls.map((control) => control.control_id);
  if (new Set(ids).size !== ids.length || new Set(controlIds).size !== controlIds.length) {
    throw new OperatorApiError(502, "invalid Operator API response: best practice ids MUST be unique");
  }
  const facets = panelRecord(root["facets"], "best practices.facets");
  return {
    total,
    filtered_total: filteredTotal,
    offset,
    limit,
    facets: {
      by_pillar: decodeFacet(facets["by_pillar"], "best practices.facets.by_pillar"),
      by_status: decodeFacet(facets["by_status"], "best practices.facets.by_status"),
      by_severity: decodeFacet(facets["by_severity"], "best practices.facets.by_severity"),
    },
    controls,
    evaluation_source: panelNonEmptyString(root, "evaluation_source", "best practices"),
  };
}

export function decodeBestPracticeDetail(value: unknown): BestPracticeDetail {
  const root = panelRecord(value, "best practice detail");
  const base = decodeControl(root, 0);
  const requirements = panelArray(root["requirements"], "best practice requirements").map(
    (item, index) => {
      const label = `best practice requirements[${index}]`;
      const row = panelRecord(item, label);
      return {
        kind: panelNonEmptyString(row, "kind", label),
        ref: panelNonEmptyString(row, "ref", label),
        freshness_days: nullableInteger(row, "freshness_days", label),
        status: decodeStatus(panelNonEmptyString(row, "status", label), label),
        evidence_refs: panelStringArray(row["evidence_refs"], `${label}.evidence_refs`),
        limitations: row["limitations"] === undefined
          ? []
          : panelStringArray(row["limitations"], `${label}.limitations`),
        coverage: row["coverage"] === undefined
          ? null
          : decodeRequirementCoverage(row["coverage"], `${label}.coverage`),
      };
    },
  );
  if (requirements.length !== base.requirement_count) {
    throw new OperatorApiError(502, "invalid Operator API response: requirement count does not reconcile");
  }
  return {
    ...base,
    requirements,
    provenance: panelRecord(root["provenance"], "provenance"),
    rule_coverage: root["rule_coverage"] === undefined
      ? null
      : decodeRuleCoverageSummary(root["rule_coverage"]),
  };
}

function decodeRequirementCoverage(value: unknown, label: string): RequirementRuleCoverage {
  const row = panelRecord(value, label);
  if (!panelBoolean(row, "activated", label)) return { activated: false };
  const count = (key: string): number => panelNonNegativeInteger(row, key, label);
  const coverage = {
    activated: true as const,
    eligible: count("eligible"),
    covered: count("covered"),
    compliant: count("compliant"),
    violated: count("violated"),
    held_for_review: count("held_for_review"),
    missing: count("missing"),
    duplicate: count("duplicate"),
    conflicting: count("conflicting"),
    unexpected: count("unexpected"),
    revision_mismatch: count("revision_mismatch"),
  };
  // Reject counts that do not reconcile instead of displaying an inconsistent record.
  if (
    coverage.covered !== coverage.compliant + coverage.violated + coverage.held_for_review
    || coverage.eligible
      !== coverage.covered + coverage.missing + coverage.duplicate + coverage.conflicting
  ) {
    throw new OperatorApiError(502, `invalid Operator API response: ${label} counts do not reconcile`);
  }
  return coverage;
}

function decodeRuleCoverageSummary(value: unknown): RuleCoverageSummary {
  const label = "best practice rule_coverage";
  const row = panelRecord(value, label);
  const optionalString = (key: string): string | null =>
    row[key] === undefined ? null : panelNullableString(row, key, label);
  return {
    status: decodeEnum(panelNonEmptyString(row, "status", label), RULE_COVERAGE_STATUSES, `${label}.status`),
    reason: optionalString("reason"),
    scope_digest: optionalString("scope_digest"),
    resource_count: row["resource_count"] === undefined
      ? null
      : panelNonNegativeInteger(row, "resource_count", label),
    inventory_generation: optionalString("inventory_generation"),
    recorded_at: optionalString("recorded_at"),
    rule_activation_generation_id: optionalString("rule_activation_generation_id"),
    matches_assessment_scope: row["matches_assessment_scope"] === undefined
      ? null
      : panelBoolean(row, "matches_assessment_scope", label),
  };
}

/**
 * Decode the WAF Controls whose requirements cite one catalog Rule. Returns `null` when the server
 * did not confirm the exact citation filter, so an older unfiltered list is never shown as citations.
 */
export function decodeRuleCitingControls(
  value: unknown,
  ruleId: string,
): readonly BestPracticeControl[] | null {
  const root = panelRecord(value, "best practices");
  if (root["rule_filter"] !== ruleId) return null;
  const response = decodeBestPracticeResponse(value);
  if (response.controls.length !== response.filtered_total) {
    throw new OperatorApiError(502, "invalid Operator API response: Rule citation list is truncated");
  }
  return response.controls;
}

export function rulesCatalogViewFromSearch(search: URLSearchParams): RulesCatalogView {
  return search.get("view") === "controls" ? "controls" : "rules";
}

export function bestPracticeStateFromSearch(search: URLSearchParams): {
  readonly filters: BestPracticeFilters;
  readonly selected: string | null;
} {
  return {
    filters: {
      pillar: search.get("pillar") ?? "",
      status: search.get("control_status") ?? "",
      q: search.get("q") ?? "",
    },
    selected: search.get("control"),
  };
}

export function bestPracticeHref(
  filters: BestPracticeFilters,
  selected: string | null,
): string {
  return routeHref("rules", {
    params: {
      view: "controls",
      pillar: filters.pillar || null,
      control_status: filters.status || null,
      q: filters.q || null,
      control: selected,
    },
  });
}
