import type {
  AnalyzerCoverageResourceView,
  AnalyzerEvaluationState,
} from "./detection-readiness.analyzer-run";

export type CoverageEvaluationFilter = "all" | AnalyzerEvaluationState;
export type CoverageResourceSort = "attention" | "resource_type" | "name";

export interface CoverageResourceControls {
  readonly query: string;
  readonly resourceType: string;
  readonly evaluation: CoverageEvaluationFilter;
  readonly sort: CoverageResourceSort;
  readonly selectedRef: string | null;
}

const EVALUATION_FILTERS: readonly CoverageEvaluationFilter[] = [
  "all",
  "evaluated_no_finding",
  "finding",
  "evaluation_error",
  "unsupported",
];
const SORTS: readonly CoverageResourceSort[] = [
  "attention",
  "resource_type",
  "name",
];

/** Parse URL-backed resource controls while rejecting unsupported values. */
export function parseCoverageResourceControls(
  search: URLSearchParams,
): CoverageResourceControls {
  const evaluation = search.get("state") ?? "all";
  const sort = search.get("sort") ?? "attention";
  return {
    query: search.get("q")?.trim() ?? "",
    resourceType: search.get("type")?.trim() ?? "all",
    evaluation: EVALUATION_FILTERS.includes(
      evaluation as CoverageEvaluationFilter,
    )
      ? evaluation as CoverageEvaluationFilter
      : "all",
    sort: SORTS.includes(sort as CoverageResourceSort)
      ? sort as CoverageResourceSort
      : "attention",
    selectedRef: search.get("resource")?.trim() || null,
  };
}

/** Build a shareable route URL without dropping locale or Sample mode. */
export function coverageResourceHref(
  pathname: string,
  search: URLSearchParams,
  controls: CoverageResourceControls,
  hash = "detection-resources",
): string {
  const params = new URLSearchParams(search);
  setOptional(params, "q", controls.query);
  setOptional(
    params,
    "type",
    controls.resourceType === "all" ? "" : controls.resourceType,
  );
  setOptional(
    params,
    "state",
    controls.evaluation === "all" ? "" : controls.evaluation,
  );
  setOptional(
    params,
    "sort",
    controls.sort === "attention" ? "" : controls.sort,
  );
  setOptional(params, "resource", controls.selectedRef ?? "");
  const query = params.toString();
  return `${pathname}${query ? `?${query}` : ""}#${hash}`;
}

/** Filter and sort only the bounded resources already returned by the server. */
export function filterCoverageResources(
  resources: readonly AnalyzerCoverageResourceView[],
  controls: CoverageResourceControls,
): readonly AnalyzerCoverageResourceView[] {
  const query = controls.query.trim().toLocaleLowerCase();
  return resources
    .filter((resource) =>
      (controls.resourceType === "all"
        || resource.resource_type === controls.resourceType)
      && (controls.evaluation === "all"
        || resource.evaluation_state === controls.evaluation)
      && (
        !query
        || [
          resource.resource_ref,
          resource.resource_type,
          resource.resource_kind,
          ...resource.error_codes,
        ].some((value) => value.toLocaleLowerCase().includes(query))
      )
    )
    .slice()
    .sort((left, right) => compareResources(left, right, controls.sort));
}

function compareResources(
  left: AnalyzerCoverageResourceView,
  right: AnalyzerCoverageResourceView,
  sort: CoverageResourceSort,
): number {
  if (sort === "attention") {
    const difference = attentionRank(left.evaluation_state)
      - attentionRank(right.evaluation_state);
    if (difference !== 0) return difference;
  }
  if (sort === "resource_type") {
    const difference = left.resource_type.localeCompare(right.resource_type);
    if (difference !== 0) return difference;
  }
  return left.resource_ref.localeCompare(right.resource_ref);
}

function attentionRank(state: AnalyzerEvaluationState): number {
  if (state === "evaluation_error") return 0;
  if (state === "finding") return 1;
  if (state === "unsupported") return 2;
  return 3;
}

function setOptional(params: URLSearchParams, key: string, value: string): void {
  if (value) params.set(key, value);
  else params.delete(key);
}
