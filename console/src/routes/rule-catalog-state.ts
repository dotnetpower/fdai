import { ReadApiError } from "../api";
import { routeHref } from "../router";

export interface RuleDetailData {
  readonly id: string;
}

export type DetailState<T extends RuleDetailData = RuleDetailData> =
  | { readonly status: "loading" }
  | { readonly status: "ready"; readonly data: T }
  | { readonly status: "unavailable"; readonly ruleId: string }
  | { readonly status: "error"; readonly message: string };

export interface RuleFilters {
  readonly origin: string;
  readonly category: string;
  readonly severity: string;
  readonly source: string;
  readonly q: string;
}

export interface RuleSelection {
  readonly id: string;
  readonly origin: string;
}

export type RuleLifecycleStatus = "active" | "promoted" | "candidate" | null;

export function ruleDetailFailure<T extends RuleDetailData>(
  error: unknown,
  ruleId: string,
): DetailState<T> {
  return error instanceof ReadApiError && error.status === 404
    ? { status: "unavailable", ruleId }
    : { status: "error", message: error instanceof Error ? error.message : String(error) };
}

export function ruleLifecycleStatusFromSearch(
  search: URLSearchParams,
): RuleLifecycleStatus | "invalid" {
  const value = search.get("status");
  if (value === null || value === "") return null;
  return value === "active" || value === "promoted" || value === "candidate"
    ? value
    : "invalid";
}

export function ruleListStateFromSearch(
  search: URLSearchParams,
): { readonly filters: RuleFilters; readonly offset: number } {
  const rawOffset = Number(search.get("offset"));
  const legacyDetailOrigin = search.has("rule") && !search.has("rule_origin");
  const lifecycleStatus = ruleLifecycleStatusFromSearch(search);
  return {
    filters: {
      origin: legacyDetailOrigin
        ? ""
        : search.get("origin") ?? (lifecycleStatus === "active" ? "active" : ""),
      category: search.get("category") ?? "",
      severity: search.get("severity") ?? "",
      source: search.get("source") ?? "",
      q: search.get("q") ?? "",
    },
    offset: Number.isInteger(rawOffset) && rawOffset >= 0 ? rawOffset : 0,
  };
}

export function ruleCatalogHref(
  filters: RuleFilters,
  offset: number,
  selection: RuleSelection | null,
): string {
  return routeHref("rules", {
    params: {
      origin: filters.origin || null,
      rule_origin: selection?.origin || null,
      category: filters.category || null,
      severity: filters.severity || null,
      source: filters.source || null,
      q: filters.q || null,
      offset: offset > 0 ? offset : null,
      rule: selection?.id ?? null,
    },
  });
}

export function ruleSelectionFromSearch(params: URLSearchParams): RuleSelection | null {
  const id = params.get("rule");
  if (!id) return null;
  return { id, origin: params.get("rule_origin") ?? params.get("origin") ?? "" };
}
