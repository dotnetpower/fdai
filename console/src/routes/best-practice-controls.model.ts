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

export const CONTROL_STATUSES = [
  "satisfied",
  "failed",
  "stale",
  "unknown",
  "not_applicable",
] as const;
export type ControlStatus = (typeof CONTROL_STATUSES)[number];
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
  readonly status: ControlStatus;
  readonly satisfied_requirement_count: number;
  readonly evaluation_source: string;
}

export interface BestPracticeRequirementView {
  readonly kind: string;
  readonly ref: string;
  readonly freshness_days: number | null;
  readonly status: ControlStatus;
  readonly evidence_refs: readonly string[];
}

export interface BestPracticeDetail extends BestPracticeControl {
  readonly requirements: readonly BestPracticeRequirementView[];
  readonly provenance: Readonly<Record<string, unknown>>;
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
    status: decodeStatus(panelNonEmptyString(row, "status", label), label),
    satisfied_requirement_count: satisfiedCount,
    evaluation_source: panelNonEmptyString(row, "evaluation_source", label),
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
      };
    },
  );
  if (requirements.length !== base.requirement_count) {
    throw new OperatorApiError(502, "invalid Operator API response: requirement count does not reconcile");
  }
  return { ...base, requirements, provenance: panelRecord(root["provenance"], "provenance") };
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
