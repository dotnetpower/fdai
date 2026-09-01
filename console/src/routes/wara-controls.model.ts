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

export const WARA_LIFECYCLES = ["active", "disabled"] as const;
export const WARA_MAPPING_DISPOSITIONS = [
  "existing_rule",
  "new_rule_candidate",
  "manual_evidence",
  "conditional_not_applicable",
  "ambiguous_or_blocked",
  "unmapped",
] as const;
export const WARA_MAPPING_STATES = ["full", "partial", "unmapped"] as const;
export const WARA_APPLICABILITY = ["applicable", "not_applicable", "unknown"] as const;
export const WARA_EVALUATIONS = ["evaluated", "not_evaluated", "blocked"] as const;
export const WARA_SATISFACTION = [
  "satisfied",
  "failed",
  "not_applicable",
  "unknown",
] as const;

export type WaraLifecycle = (typeof WARA_LIFECYCLES)[number];
export type WaraMappingDisposition = (typeof WARA_MAPPING_DISPOSITIONS)[number];
export type WaraMappingState = (typeof WARA_MAPPING_STATES)[number];
export type WaraApplicability = (typeof WARA_APPLICABILITY)[number];
export type WaraEvaluation = (typeof WARA_EVALUATIONS)[number];
export type WaraSatisfaction = (typeof WARA_SATISFACTION)[number];

export interface WaraControl {
  readonly id: string;
  readonly title: string;
  readonly recommendation_control: string;
  readonly impact: string;
  readonly resource_type: string;
  readonly lifecycle: WaraLifecycle;
  readonly product_group_verified: boolean;
  readonly automation_available: boolean;
  readonly mapping_disposition: WaraMappingDisposition;
  readonly mapping_state: WaraMappingState;
  readonly applicability: WaraApplicability;
  readonly evaluation_status: WaraEvaluation;
  readonly satisfaction: WaraSatisfaction;
  readonly evaluation_scope: string | null;
  readonly evaluated_at: string | null;
  readonly evidence_complete: boolean;
  readonly evidence_refs: readonly string[];
  readonly evidence_digests: readonly string[];
  readonly source_url: string;
  readonly source_revision: string;
  readonly source_version: string;
  readonly retrieved_at: string;
  readonly source_path: string;
  readonly source_digest: string;
  readonly source_license: string;
  readonly learn_more_name: string | null;
  readonly learn_more_url: string | null;
  readonly query_digest: string | null;
  readonly workload_tags: readonly string[];
  readonly limitations: readonly string[];
  readonly execution_authority: false;
}

export interface WaraInventory {
  readonly active_recommendations: number;
  readonly disabled_recommendations: number;
  readonly resource_types: number;
  readonly automated_recommendations: number;
  readonly manual_recommendations: number;
}

export interface WaraResponse {
  readonly total: number;
  readonly filtered_total: number;
  readonly offset: number;
  readonly limit: number;
  readonly facets: Readonly<Record<string, Readonly<Record<string, number>>>>;
  readonly controls: readonly WaraControl[];
  readonly inventory: WaraInventory;
  readonly evaluation_source: string;
  readonly source_revision: string;
  readonly crosswalk_digest: string;
}

export interface WaraFilters {
  readonly resource_type: string;
  readonly recommendation_control: string;
  readonly impact: string;
  readonly lifecycle: string;
  readonly product_group_verified: string;
  readonly automation_available: string;
  readonly mapping_disposition: string;
  readonly applicability: string;
  readonly evaluation_status: string;
  readonly satisfaction: string;
  readonly q: string;
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

function decodeControl(value: unknown, index: number): WaraControl {
  const label = `WARA controls[${index}]`;
  const raw = panelRecord(value, label);
  const executionAuthority = panelBoolean(raw, "execution_authority", label);
  const learnMoreName = panelNullableString(raw, "learn_more_name", label);
  const learnMoreUrl = panelNullableString(raw, "learn_more_url", label);
  if (executionAuthority) {
    throw new OperatorApiError(502, `invalid Operator API response: ${label} cannot grant execution authority`);
  }
  if ((learnMoreName === null) !== (learnMoreUrl === null)) {
    throw new OperatorApiError(502, `invalid Operator API response: ${label} learn-more fields MUST be paired`);
  }
  return {
    id: panelNonEmptyString(raw, "id", label),
    title: panelNonEmptyString(raw, "title", label),
    recommendation_control: panelNonEmptyString(raw, "recommendation_control", label),
    impact: panelNonEmptyString(raw, "impact", label),
    resource_type: panelNonEmptyString(raw, "resource_type", label),
    lifecycle: decodeEnum(panelNonEmptyString(raw, "lifecycle", label), WARA_LIFECYCLES, `${label}.lifecycle`),
    product_group_verified: panelBoolean(raw, "product_group_verified", label),
    automation_available: panelBoolean(raw, "automation_available", label),
    mapping_disposition: decodeEnum(
      panelNonEmptyString(raw, "mapping_disposition", label),
      WARA_MAPPING_DISPOSITIONS,
      `${label}.mapping_disposition`,
    ),
    mapping_state: decodeEnum(
      panelNonEmptyString(raw, "mapping_state", label),
      WARA_MAPPING_STATES,
      `${label}.mapping_state`,
    ),
    applicability: decodeEnum(
      panelNonEmptyString(raw, "applicability", label),
      WARA_APPLICABILITY,
      `${label}.applicability`,
    ),
    evaluation_status: decodeEnum(
      panelNonEmptyString(raw, "evaluation_status", label),
      WARA_EVALUATIONS,
      `${label}.evaluation_status`,
    ),
    satisfaction: decodeEnum(
      panelNonEmptyString(raw, "satisfaction", label),
      WARA_SATISFACTION,
      `${label}.satisfaction`,
    ),
    evaluation_scope: panelNullableString(raw, "evaluation_scope", label),
    evaluated_at: panelNullableString(raw, "evaluated_at", label),
    evidence_complete: panelBoolean(raw, "evidence_complete", label),
    evidence_refs: panelStringArray(raw["evidence_refs"], `${label}.evidence_refs`),
    evidence_digests: panelStringArray(raw["evidence_digests"], `${label}.evidence_digests`),
    source_url: panelNonEmptyString(raw, "source_url", label),
    source_revision: panelNonEmptyString(raw, "source_revision", label),
    source_version: panelNonEmptyString(raw, "source_version", label),
    retrieved_at: panelNonEmptyString(raw, "retrieved_at", label),
    source_path: panelNonEmptyString(raw, "source_path", label),
    source_digest: panelNonEmptyString(raw, "source_digest", label),
    source_license: panelNonEmptyString(raw, "source_license", label),
    learn_more_name: learnMoreName,
    learn_more_url: learnMoreUrl,
    query_digest: panelNullableString(raw, "query_digest", label),
    workload_tags: panelStringArray(raw["workload_tags"], `${label}.workload_tags`),
    limitations: panelStringArray(raw["limitations"], `${label}.limitations`),
    execution_authority: false,
  };
}

export function decodeWaraResponse(value: unknown): WaraResponse {
  const root = panelRecord(value, "WARA controls");
  const total = panelNonNegativeInteger(root, "total", "WARA controls");
  const filteredTotal = panelNonNegativeInteger(root, "filtered_total", "WARA controls");
  const limit = panelNonNegativeInteger(root, "limit", "WARA controls");
  const controls = panelArray(root["controls"], "WARA controls.items").map(decodeControl);
  if (filteredTotal > total || controls.length > filteredTotal || controls.length > limit) {
    throw new OperatorApiError(502, "invalid Operator API response: WARA totals do not reconcile");
  }
  if (new Set(controls.map((item) => item.id)).size !== controls.length) {
    throw new OperatorApiError(502, "invalid Operator API response: WARA ids MUST be unique");
  }
  const facets = panelRecord(root["facets"], "WARA controls.facets");
  const inventory = panelRecord(root["inventory"], "WARA controls.inventory");
  const decodedInventory: WaraInventory = {
    active_recommendations: panelNonNegativeInteger(
      inventory,
      "active_recommendations",
      "WARA controls.inventory",
    ),
    disabled_recommendations: panelNonNegativeInteger(
      inventory,
      "disabled_recommendations",
      "WARA controls.inventory",
    ),
    resource_types: panelNonNegativeInteger(
      inventory,
      "resource_types",
      "WARA controls.inventory",
    ),
    automated_recommendations: panelNonNegativeInteger(
      inventory,
      "automated_recommendations",
      "WARA controls.inventory",
    ),
    manual_recommendations: panelNonNegativeInteger(
      inventory,
      "manual_recommendations",
      "WARA controls.inventory",
    ),
  };
  if (
    decodedInventory.active_recommendations + decodedInventory.disabled_recommendations !== total
    || decodedInventory.automated_recommendations
      + decodedInventory.manual_recommendations
      !== decodedInventory.active_recommendations
  ) {
    throw new OperatorApiError(502, "invalid Operator API response: WARA inventory does not reconcile");
  }
  return {
    total,
    filtered_total: filteredTotal,
    offset: panelNonNegativeInteger(root, "offset", "WARA controls"),
    limit,
    facets: Object.fromEntries(
      Object.entries(facets).map(([key, counts]) => [
        key,
        decodeCountMap(counts, `WARA controls.facets.${key}`),
      ]),
    ),
    controls,
    inventory: decodedInventory,
    evaluation_source: panelNonEmptyString(root, "evaluation_source", "WARA controls"),
    source_revision: panelNonEmptyString(root, "source_revision", "WARA controls"),
    crosswalk_digest: panelNonEmptyString(root, "crosswalk_digest", "WARA controls"),
  };
}

export function decodeWaraDetail(value: unknown): WaraControl {
  return decodeControl(value, 0);
}

export function waraStateFromSearch(search: URLSearchParams): {
  readonly filters: WaraFilters;
  readonly selected: string | null;
  readonly offset: number;
} {
  const rawOffset = Number(search.get("offset"));
  return {
    filters: {
      resource_type: search.get("resource_type") ?? "",
      recommendation_control: search.get("recommendation_control") ?? "",
      impact: search.get("impact") ?? "",
      lifecycle: search.get("lifecycle") ?? "",
      product_group_verified: search.get("product_group_verified") ?? "",
      automation_available: search.get("automation_available") ?? "",
      mapping_disposition: search.get("mapping_disposition") ?? "",
      applicability: search.get("applicability") ?? "",
      evaluation_status: search.get("evaluation_status") ?? "",
      satisfaction: search.get("satisfaction") ?? "",
      q: search.get("q") ?? "",
    },
    selected: panelNullableString(
      { recommendation: search.get("recommendation") },
      "recommendation",
      "WARA URL state",
    ),
    offset: Number.isInteger(rawOffset) && rawOffset >= 0 ? rawOffset : 0,
  };
}

export function waraHref(
  filters: WaraFilters,
  selected: string | null,
  offset = 0,
): string {
  return routeHref("rules", {
    params: {
      view: "controls",
      framework: "azure-wara",
      ...Object.fromEntries(
        Object.entries(filters).map(([key, value]) => [key, value || null]),
      ),
      recommendation: selected,
      offset: offset > 0 ? offset : null,
    },
  });
}
