import { isOptionalOperatorApiUnavailable } from "../api";
import { isRfc3339Timestamp } from "../time-format";
import type {
  RenderedReportView,
  ReportList,
  ReportProvenance,
  ReportingRegistry,
  ReportSummary,
} from "./reporting.model";

export interface ReportsData {
  readonly catalog: ReportList;
  readonly registry: ReportingRegistry;
  readonly selected: ReportSummary | null;
  readonly rendered: RenderedReportView | null;
  readonly variables: Readonly<Record<string, string>>;
  readonly operationError: string | null;
}

export type ReportHeadlineState =
  | { readonly kind: "empty" }
  | { readonly kind: "unavailable"; readonly name: string }
  | { readonly kind: "rendered"; readonly name: string; readonly count: number };

export function reportsLoadFailure(error: unknown):
  | { readonly status: "unavailable"; readonly message: string }
  | { readonly status: "error"; readonly message: string } {
  return {
    status: isOptionalOperatorApiUnavailable(error) ? "unavailable" : "error",
    message: error instanceof Error ? error.message : String(error),
  };
}

export function reportHeadlineState(
  selected: Pick<ReportSummary, "name"> | null,
  rendered: Pick<RenderedReportView, "widgets"> | null,
): ReportHeadlineState {
  if (selected === null) return { kind: "empty" };
  if (rendered === null) return { kind: "unavailable", name: selected.name };
  return { kind: "rendered", name: selected.name, count: rendered.widgets.length };
}

export function updateReportVariable(
  data: ReportsData,
  name: string,
  value: string,
): ReportsData {
  return {
    ...data,
    variables: { ...data.variables, [name]: value },
    rendered: null,
    operationError: null,
  };
}

export function reportVariableErrors(
  report: Pick<ReportSummary, "variables"> | null,
  values: Readonly<Record<string, string>>,
): readonly string[] {
  return (report?.variables ?? []).flatMap((variable) => {
    const value = (values[variable.name] ?? "").trim();
    if (!value) return [`${variable.name} is required`];
    if (variable.values.length > 0 && !variable.values.includes(value)) {
      return [`${variable.name} has an unsupported value: ${value}`];
    }
    return [];
  });
}

export function shouldShowReportVariableErrors(
  values: Readonly<Record<string, string>>,
  errors: readonly string[],
): boolean {
  return errors.length > 0 && Object.values(values).some((value) => value.trim().length > 0);
}

export function aggregateEvidenceAsOf(
  sources: readonly { readonly as_of: string | null }[],
): string | null {
  if (sources.length === 0 || sources.some((source) => source.as_of === null)) return null;
  if (sources.some((source) => !isRfc3339Timestamp(source.as_of!))) return null;
  const timestamps = sources.map((source) => ({
    value: source.as_of!,
    epoch: Date.parse(source.as_of!),
  }));
  if (timestamps.some(({ epoch }) => !Number.isFinite(epoch))) return null;
  timestamps.sort((left, right) => left.epoch - right.epoch);
  return timestamps[0]?.value ?? null;
}

export function reportDownloadCanComplete(
  mounted: boolean,
  currentGeneration: number,
  candidateGeneration: number,
): boolean {
  return mounted && currentGeneration === candidateGeneration;
}

export function pdfDownloadAvailable(
  catalogFormats: readonly string[],
  registryFormats: readonly string[],
): boolean {
  return catalogFormats.includes("pdf") && registryFormats.includes("pdf");
}

export function reportSourceAvailability(
  report: Pick<ReportSummary, "datasources">,
  registry: Pick<ReportingRegistry, "datasource_provenance">,
): ReportProvenance["availability"] {
  if (report.datasources.length === 0) return "not_applicable";
  const states = new Set(report.datasources.map((datasource) =>
    registry.datasource_provenance.find((source) => source.datasource === datasource)
      ?.availability ?? "unknown",
  ));
  if (states.size !== 1) return "partial";
  const state = states.values().next().value;
  return state === "available" || state === "unavailable" ? state : "unknown";
}

export function registrySourceReadiness(
  registry: Pick<ReportingRegistry, "datasources" | "datasource_provenance">,
): { readonly available: number; readonly total: number } {
  const availability = new Map(
    registry.datasource_provenance.map((source) => [source.datasource, source.availability]),
  );
  return {
    available: registry.datasources.filter((datasource) =>
      availability.get(datasource) === "available"
    ).length,
    total: registry.datasources.length,
  };
}

export function defaultReport(
  items: readonly ReportSummary[],
  registry?: ReportingRegistry,
): ReportSummary | null {
  const unavailable = new Set(
    registry?.datasource_provenance
      .filter((source) => source.availability === "unavailable")
      .map((source) => source.datasource) ?? [],
  );
  const candidates = items.filter((report) =>
    report.datasources.every((datasource) => !unavailable.has(datasource)),
  );
  const available = candidates.length > 0 ? candidates : items;
  return available.find((report) => report.variables.length > 0 && report.variables.every((variable) =>
      (variable.default ?? variable.values[0] ?? "").trim().length > 0,
    )) ??
    available.find((report) => report.variables.length === 0) ??
    available[0] ??
    null;
}
