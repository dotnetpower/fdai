import { OperatorApiError } from "../api";
import { routeHref } from "../router";
import { decodeControlEnablement, decodeSeveritySource, type ControlEnablement, type SeveritySource } from "./control-enablement.model";
import { decodeFrameworkGuidance, type FrameworkGuidance } from "./framework-guidance.model";
import { decodeControlRemediation, type ControlRemediation } from "./control-remediation.model";
import {
  panelArray,
  panelBoolean,
  panelNonEmptyString,
  panelNonNegativeInteger,
  panelNullableString,
  panelRecord,
  panelStringArray,
} from "./panel-decode";

export const CAF_REFERENCE_STATES = ["present"] as const;
export const CAF_MAPPING_STATES = ["full", "partial", "unmapped"] as const;
export const CAF_APPLICABILITY = ["applicable", "not_applicable", "unknown"] as const;
export const CAF_EVALUATIONS = ["evaluated", "not_evaluated", "blocked"] as const;
export const CAF_SATISFACTION = ["satisfied", "failed", "not_applicable", "unknown"] as const;

export type CafReferenceState = (typeof CAF_REFERENCE_STATES)[number];
export type CafMappingState = (typeof CAF_MAPPING_STATES)[number];
export type CafApplicability = (typeof CAF_APPLICABILITY)[number];
export type CafEvaluation = (typeof CAF_EVALUATIONS)[number];
export type CafSatisfaction = (typeof CAF_SATISFACTION)[number];

export interface CafApprovedException {
  readonly justification: string;
  readonly approved_by: string;
  readonly approved_at: string;
  readonly expires_at: string;
}

export interface CafEvidenceSpecification {
  readonly requirement_id: string;
  readonly kind: string;
  readonly source_ref: string;
  readonly authoritative_producer: string | null;
  readonly blocked_dependency: string | null;
  readonly scope_contract: string;
  readonly generation_contract: string;
  readonly freshness_ceiling_seconds: number;
  readonly completeness_required: boolean;
  readonly owner_slot: string;
  readonly approval_roles: readonly string[];
  readonly failure_behavior: string;
  readonly evidence_role: string;
  readonly process_phase: string;
}

export interface CafCrosswalkReference {
  readonly target_kind: string;
  readonly target_ref: string | null;
  readonly relationship: string;
}

export interface CafControl {
  readonly enablement?: ControlEnablement | null;
  readonly severity_source?: SeveritySource | null;
  readonly control_id: string;
  readonly title: string;
  readonly title_ko?: string | null;
  readonly description: string;
  readonly area: string;
  readonly reference_state: CafReferenceState;
  readonly mapping_state: CafMappingState;
  readonly applicability: CafApplicability;
  readonly evaluation_status: CafEvaluation;
  readonly satisfaction: CafSatisfaction;
  readonly owner_slot: string;
  readonly cadence_days: number;
  readonly evaluation_scope: string | null;
  readonly evaluated_at: string | null;
  readonly profile_id: string | null;
  readonly profile_digest: string | null;
  readonly approved_exception: CafApprovedException | null;
  readonly evidence_complete: boolean;
  readonly evidence_refs: readonly string[];
  readonly evidence_digests: readonly string[];
  readonly limitations: readonly string[];
  readonly source_url: string;
  readonly source_version: string;
  readonly source_revision: string;
  readonly execution_authority: false;
}

export interface CafControlDetail extends CafControl {
  readonly guidance?: FrameworkGuidance | null;
  readonly guidance_unavailable_reason?: string | null;
  readonly remediation?: ControlRemediation | null;
  readonly evidence_specifications: readonly CafEvidenceSpecification[];
  readonly crosswalk: readonly CafCrosswalkReference[];
}

export interface CafResponse {
  readonly total: number;
  readonly filtered_total: number;
  readonly offset: number;
  readonly limit: number;
  readonly facets: Readonly<Record<string, Readonly<Record<string, number>>>>;
  readonly controls: readonly CafControl[];
  readonly evaluation_source: string;
  readonly framework_id: "azure-caf";
  readonly framework_version: string;
  readonly catalog_digest: string;
  readonly source_revision_digest: string;
  readonly last_profile_id: string | null;
  readonly last_evaluated_at: string | null;
}

export interface CafFilters {
  readonly area: string;
  readonly mapping_state: string;
  readonly applicability: string;
  readonly evaluation_status: string;
  readonly satisfaction: string;
  readonly owner_slot: string;
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

function decodeApprovedException(
  value: unknown,
  label: string,
): CafApprovedException | null {
  if (value === null) return null;
  const raw = panelRecord(value, label);
  return {
    justification: panelNonEmptyString(raw, "justification", label),
    approved_by: panelNonEmptyString(raw, "approved_by", label),
    approved_at: panelNonEmptyString(raw, "approved_at", label),
    expires_at: panelNonEmptyString(raw, "expires_at", label),
  };
}

function decodeControl(value: unknown, index: number): CafControl {
  const label = `CAF controls[${index}]`;
  const raw = panelRecord(value, label);
  const executionAuthority = panelBoolean(raw, "execution_authority", label);
  if (executionAuthority) {
    throw new OperatorApiError(502, `invalid Operator API response: ${label} cannot grant execution authority`);
  }
  return {
    control_id: panelNonEmptyString(raw, "control_id", label),
    enablement: decodeControlEnablement(raw["enablement"]),
    severity_source: decodeSeveritySource(raw["severity_source"]),
    title: panelNonEmptyString(raw, "title", label),
    ...(raw["title_ko"] === undefined ? {} : { title_ko: panelNullableString(raw, "title_ko", label) }),
    description: panelNonEmptyString(raw, "description", label),
    area: panelNonEmptyString(raw, "area", label),
    reference_state: decodeEnum(panelNonEmptyString(raw, "reference_state", label), CAF_REFERENCE_STATES, `${label}.reference_state`),
    mapping_state: decodeEnum(panelNonEmptyString(raw, "mapping_state", label), CAF_MAPPING_STATES, `${label}.mapping_state`),
    applicability: decodeEnum(panelNonEmptyString(raw, "applicability", label), CAF_APPLICABILITY, `${label}.applicability`),
    evaluation_status: decodeEnum(panelNonEmptyString(raw, "evaluation_status", label), CAF_EVALUATIONS, `${label}.evaluation_status`),
    satisfaction: decodeEnum(panelNonEmptyString(raw, "satisfaction", label), CAF_SATISFACTION, `${label}.satisfaction`),
    owner_slot: panelNonEmptyString(raw, "owner_slot", label),
    cadence_days: panelNonNegativeInteger(raw, "cadence_days", label),
    evaluation_scope: panelNullableString(raw, "evaluation_scope", label),
    evaluated_at: panelNullableString(raw, "evaluated_at", label),
    profile_id: panelNullableString(raw, "profile_id", label),
    profile_digest: panelNullableString(raw, "profile_digest", label),
    approved_exception: decodeApprovedException(raw["approved_exception"], `${label}.approved_exception`),
    evidence_complete: panelBoolean(raw, "evidence_complete", label),
    evidence_refs: panelStringArray(raw["evidence_refs"], `${label}.evidence_refs`),
    evidence_digests: panelStringArray(raw["evidence_digests"], `${label}.evidence_digests`),
    limitations: panelStringArray(raw["limitations"], `${label}.limitations`),
    source_url: panelNonEmptyString(raw, "source_url", label),
    source_version: panelNonEmptyString(raw, "source_version", label),
    source_revision: panelNonEmptyString(raw, "source_revision", label),
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

export function decodeCafResponse(value: unknown): CafResponse {
  const root = panelRecord(value, "CAF controls");
  const total = panelNonNegativeInteger(root, "total", "CAF controls");
  const filteredTotal = panelNonNegativeInteger(root, "filtered_total", "CAF controls");
  const limit = panelNonNegativeInteger(root, "limit", "CAF controls");
  const controls = panelArray(root["controls"], "CAF controls.controls").map(decodeControl);
  if (filteredTotal > total || controls.length > filteredTotal || controls.length > limit) {
    throw new OperatorApiError(502, "invalid Operator API response: CAF totals do not reconcile");
  }
  const ids = controls.map((item) => item.control_id);
  if (new Set(ids).size !== ids.length) {
    throw new OperatorApiError(502, "invalid Operator API response: CAF control ids MUST be unique");
  }
  const facets = panelRecord(root["facets"], "CAF controls.facets");
  const frameworkId = panelNonEmptyString(root, "framework_id", "CAF controls");
  if (frameworkId !== "azure-caf") {
    throw new OperatorApiError(502, "invalid Operator API response: CAF framework identity mismatch");
  }
  return {
    total,
    filtered_total: filteredTotal,
    offset: panelNonNegativeInteger(root, "offset", "CAF controls"),
    limit,
    facets: Object.fromEntries(
      Object.entries(facets).map(([key, counts]) => [
        key,
        decodeFacet(counts, `CAF controls.facets.${key}`),
      ]),
    ),
    controls,
    evaluation_source: panelNonEmptyString(root, "evaluation_source", "CAF controls"),
    framework_id: "azure-caf",
    framework_version: panelNonEmptyString(root, "framework_version", "CAF controls"),
    catalog_digest: panelNonEmptyString(root, "catalog_digest", "CAF controls"),
    source_revision_digest: panelNonEmptyString(root, "source_revision_digest", "CAF controls"),
    last_profile_id: panelNullableString(root, "last_profile_id", "CAF controls"),
    last_evaluated_at: panelNullableString(root, "last_evaluated_at", "CAF controls"),
  };
}

export function decodeCafDetail(value: unknown, selectedId?: string): CafControlDetail {
  const root = panelRecord(value, "CAF control detail");
  const base = decodeControl(root, 0);
  if (selectedId !== undefined && base.control_id !== selectedId) {
    throw new OperatorApiError(502, "invalid Operator API response: CAF detail does not match the selected control");
  }
  const evidenceSpecifications = panelArray(
    root["evidence_specifications"],
    "CAF evidence specifications",
  ).map((item, index) => {
    const label = `CAF evidence specifications[${index}]`;
    const raw = panelRecord(item, label);
    return {
      requirement_id: panelNonEmptyString(raw, "requirement_id", label),
      kind: panelNonEmptyString(raw, "kind", label),
      source_ref: panelNonEmptyString(raw, "source_ref", label),
      authoritative_producer: panelNullableString(raw, "authoritative_producer", label),
      blocked_dependency: panelNullableString(raw, "blocked_dependency", label),
      scope_contract: panelNonEmptyString(raw, "scope_contract", label),
      generation_contract: panelNonEmptyString(raw, "generation_contract", label),
      freshness_ceiling_seconds: panelNonNegativeInteger(raw, "freshness_ceiling_seconds", label),
      completeness_required: panelBoolean(raw, "completeness_required", label),
      owner_slot: panelNonEmptyString(raw, "owner_slot", label),
      approval_roles: panelStringArray(raw["approval_roles"], `${label}.approval_roles`),
      failure_behavior: panelNonEmptyString(raw, "failure_behavior", label),
      evidence_role: panelNonEmptyString(raw, "evidence_role", label),
      process_phase: panelNonEmptyString(raw, "process_phase", label),
    };
  });
  const crosswalk = panelArray(root["crosswalk"], "CAF crosswalk").map((item, index) => {
    const label = `CAF crosswalk[${index}]`;
    const raw = panelRecord(item, label);
    return {
      target_kind: panelNonEmptyString(raw, "target_kind", label),
      target_ref: panelNullableString(raw, "target_ref", label),
      relationship: panelNonEmptyString(raw, "relationship", label),
    };
  });
  return {
    ...base, evidence_specifications: evidenceSpecifications, crosswalk,
    remediation: decodeControlRemediation(root["remediation"]),
    guidance: decodeFrameworkGuidance(root["guidance"], {
      framework_id: "azure-caf", control_id: base.control_id,
      source_revision: root["guidance_source_revision"], source_digest: root["guidance_source_digest"],
    }),
    guidance_unavailable_reason: root["guidance_unavailable_reason"] === undefined ? null
      : panelNullableString(root, "guidance_unavailable_reason", "CAF control detail"),
  };
}

export function cafStateFromSearch(search: URLSearchParams): {
  readonly filters: CafFilters;
  readonly selected: string | null;
} {
  return {
    filters: {
      area: search.get("caf_area") ?? "",
      mapping_state: search.get("caf_mapping") ?? "",
      applicability: search.get("caf_applicability") ?? "",
      evaluation_status: search.get("caf_evaluation") ?? "",
      satisfaction: search.get("caf_satisfaction") ?? "",
      owner_slot: search.get("caf_owner") ?? "",
      q: search.get("q") ?? "",
    },
    selected: search.get("caf_control"),
  };
}

export function cafHref(filters: CafFilters, selected: string | null): string {
  return routeHref("rules", {
    params: {
      view: "controls",
      framework: "azure-caf",
      caf_area: filters.area || null,
      caf_mapping: filters.mapping_state || null,
      caf_applicability: filters.applicability || null,
      caf_evaluation: filters.evaluation_status || null,
      caf_satisfaction: filters.satisfaction || null,
      caf_owner: filters.owner_slot || null,
      q: filters.q || null,
      caf_control: selected,
    },
  });
}
