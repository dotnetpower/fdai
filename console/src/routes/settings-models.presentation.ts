import type {
  GptModelCatalogEntryView,
  T2ModelChoiceView,
} from "./settings-models.model";

export type ModelStatusTone = "success" | "warning" | "neutral";

export interface ModelStatusPresentation {
  readonly label:
    | "availableStatus"
    | "resolvedStatus"
    | "recoveredStatus"
    | "unavailableStatus"
    | "approvalOnlyStatus"
    | "needsReviewStatus";
  readonly tone: ModelStatusTone;
}

export function presentModelStatus(status: string): ModelStatusPresentation {
  switch (status.trim().toLowerCase()) {
    case "available":
    case "ready":
    case "enabled":
      return { label: "availableStatus", tone: "success" };
    case "resolved":
      return { label: "resolvedStatus", tone: "success" };
    case "recovered":
      return { label: "recoveredStatus", tone: "success" };
    case "hil-only":
    case "approval-only":
      return { label: "approvalOnlyStatus", tone: "warning" };
    case "unavailable":
    case "unhealthy":
    case "failed":
    case "disabled":
      return { label: "unavailableStatus", tone: "warning" };
    default:
      return { label: "needsReviewStatus", tone: "neutral" };
  }
}

export function filterCatalogModels(
  models: readonly GptModelCatalogEntryView[],
  query: string,
): readonly GptModelCatalogEntryView[] {
  const normalized = query.trim().toLocaleLowerCase();
  if (normalized === "") return models;
  return models.filter((model) => [
    model.publisher,
    model.family,
    model.version,
    model.lifecycle,
    model.status,
    ...model.deployments,
    ...model.skus.map((sku) => sku.name),
  ].join(" ").toLocaleLowerCase().includes(normalized));
}

export function formatTpm(value: number): string {
  return `${new Intl.NumberFormat().format(value)} TPM`;
}

export function independentSecondaryCandidates(
  primary: T2ModelChoiceView | null,
  candidates: readonly T2ModelChoiceView[],
): readonly T2ModelChoiceView[] {
  if (primary === null) return candidates;
  return candidates.filter((candidate) => candidate.publisher !== primary.publisher);
}

export function matchesModelQuery(query: string, values: readonly unknown[]): boolean {
  const normalized = query.trim().toLocaleLowerCase();
  if (normalized === "") return true;
  return values
    .filter((value): value is string | number => typeof value === "string" || typeof value === "number")
    .some((value) => String(value).toLocaleLowerCase().includes(normalized));
}

export function formatDisplayTimestamp(
  value: string,
  locale?: string,
  timeZone?: string,
): string {
  return new Intl.DateTimeFormat(locale, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
    timeZone,
    timeZoneName: "short",
  }).format(new Date(value));
}
