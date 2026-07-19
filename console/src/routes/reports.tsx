import { useEffect, useRef, useState } from "preact/hooks";
import type { ReadApiClient } from "../api";
import { AsyncBoundary, PageHeader, type AsyncState } from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import { t } from "../i18n";
import { currentRoute, routeHref } from "../router";
import { isRfc3339Timestamp } from "../time-format";
import { ProcessWidget, SUPPORTED_REPORT_WIDGET_TYPES } from "./process-view-renderer";
import type {
  RenderedReportView,
  ReportingRegistry,
  ReportList,
  ReportSummary,
} from "./reporting.model";

interface Props {
  readonly client: ReadApiClient;
}

interface ReportsData {
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

export function triggerBlobDownload(blob: Blob, fileName: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = fileName;
  document.body.append(anchor);
  try {
    anchor.click();
  } finally {
    anchor.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
  }
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

export function ReportsRoute({ client }: Props) {
  const requestedId = currentRoute().segments[0] ?? null;
  const [state, setState] = useState<AsyncState<ReportsData>>({ status: "loading" });
  const [refreshing, setRefreshing] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const renderGeneration = useRef(0);
  const downloadGeneration = useRef(0);
  const mounted = useRef(true);

  useEffect(() => () => {
    mounted.current = false;
    renderGeneration.current += 1;
    downloadGeneration.current += 1;
  }, []);

  useEffect(() => {
    let cancelled = false;
    setRefreshing(false);
    setDownloading(false);
    setState({ status: "loading" });
    void (async () => {
      try {
        const [catalog, registry] = await Promise.all([
          client.reports(),
          client.reportingRegistry(),
        ]);
        const selected = requestedId
          ? catalog.items.find((report) => report.id === requestedId) ?? null
          : defaultReport(catalog.items, registry);
        const queryVariables = new URLSearchParams(window.location.search);
        const variables = Object.fromEntries(
          (selected?.variables ?? []).map((variable) => [
            variable.name,
            queryVariables.get(variable.name) ?? variable.default ?? variable.values[0] ?? "",
          ]),
        );
        const variablesValid = selected !== null
          && reportVariableErrors(selected, variables).length === 0;
        let rendered: RenderedReportView | null = null;
        let operationError: string | null = null;
        if (selected && variablesValid) {
          try {
            rendered = await client.renderReport(selected.id, variables);
          } catch (error) {
            operationError = error instanceof Error ? error.message : String(error);
          }
        }
        if (!cancelled) {
          setState({
            status: "ready",
            data: { catalog, registry, selected, rendered, variables, operationError },
          });
        }
      } catch (error) {
        if (!cancelled) {
          setState({
            status: "error",
            message: error instanceof Error ? error.message : String(error),
          });
        }
      }
    })();
    return () => {
      cancelled = true;
      renderGeneration.current += 1;
      downloadGeneration.current += 1;
    };
  }, [client, requestedId]);

  const updateVariable = (name: string, value: string) => {
    renderGeneration.current += 1;
    setRefreshing(false);
    setState((current) => {
      if (current.status !== "ready") return current;
      const data = updateReportVariable(current.data, name, value);
      if (current.data.selected) {
        window.history.replaceState(
          window.history.state,
          "",
          routeHref("reports", {
            segments: [current.data.selected.id],
            params: data.variables,
          }),
        );
      }
      return {
        status: "ready",
        data,
      };
    });
  };

  const renderSelected = async () => {
    if (state.status !== "ready" || state.data.selected === null || refreshing) return;
    if (reportVariableErrors(state.data.selected, state.data.variables).length > 0) return;
    const generation = renderGeneration.current + 1;
    renderGeneration.current = generation;
    const selectedId = state.data.selected.id;
    const variables = { ...state.data.variables };
    setRefreshing(true);
    setState((current) => current.status === "ready"
      ? { status: "ready", data: { ...current.data, operationError: null } }
      : current);
    try {
      const rendered = await client.renderReport(selectedId, variables);
      if (renderGeneration.current === generation) {
        setState((current) => current.status === "ready" && current.data.selected?.id === selectedId
          ? { status: "ready", data: { ...current.data, rendered } }
          : current);
      }
    } catch (error) {
      if (renderGeneration.current === generation) {
        const message = error instanceof Error ? error.message : String(error);
        setState((current) => current.status === "ready"
          ? { status: "ready", data: { ...current.data, operationError: message } }
          : current);
      }
    } finally {
      if (renderGeneration.current === generation) setRefreshing(false);
    }
  };

  const downloadSelected = async () => {
    if (state.status !== "ready" || state.data.selected === null || downloading) return;
    const generation = downloadGeneration.current + 1;
    downloadGeneration.current = generation;
    const selectedId = state.data.selected.id;
    const variables = { ...state.data.variables };
    setDownloading(true);
    setState((current) => current.status === "ready"
      ? { status: "ready", data: { ...current.data, operationError: null } }
      : current);
    try {
      const blob = await client.downloadReport(
        selectedId,
        "pdf",
        variables,
      );
      if (reportDownloadCanComplete(mounted.current, downloadGeneration.current, generation)) {
        triggerBlobDownload(blob, `${selectedId}.pdf`);
      }
    } catch (error) {
      if (reportDownloadCanComplete(mounted.current, downloadGeneration.current, generation)) {
        const message = error instanceof Error ? error.message : String(error);
        setState((current) => current.status === "ready"
          ? { status: "ready", data: { ...current.data, operationError: message } }
          : current);
      }
    } finally {
      if (reportDownloadCanComplete(mounted.current, downloadGeneration.current, generation)) {
        setDownloading(false);
      }
    }
  };

  return (
    <div class="stack reports-route">
      <PageHeader title={t("route.reports")} subtitle={t("reports.subtitle")} />
      <AsyncBoundary state={state} resourceLabel={t("route.reports")}>
        {(data) => (
          <ReportsBody
            data={data}
            refreshing={refreshing}
            downloading={downloading}
            onVariableChange={updateVariable}
            onRender={renderSelected}
            onDownload={downloadSelected}
          />
        )}
      </AsyncBoundary>
    </div>
  );
}

function ReportsBody({
  data,
  refreshing,
  downloading,
  onVariableChange,
  onRender,
  onDownload,
}: {
  readonly data: ReportsData;
  readonly refreshing: boolean;
  readonly downloading: boolean;
  readonly onVariableChange: (name: string, value: string) => void;
  readonly onRender: () => Promise<void>;
  readonly onDownload: () => Promise<void>;
}) {
  const variableErrors = reportVariableErrors(data.selected, data.variables);
  const variablesComplete = data.selected !== null && variableErrors.length === 0;
  const evidenceAsOf = aggregateEvidenceAsOf(data.rendered?.provenance.sources ?? []);
  const headline = reportHeadlineState(data.selected, data.rendered);
  usePublishViewContext(
    () => ({
      routeId: "reports",
      routeLabel: t("route.reports"),
      purpose: t("reports.viewPurpose"),
      glossary: composeGlossary([TERMS.report, TERMS.widget]),
      headline: headline.kind === "rendered"
        ? t("reports.viewHeadline", { name: headline.name, count: headline.count })
        : headline.kind === "unavailable"
          ? t("reports.viewHeadlineUnavailable", { name: headline.name })
          : t("reports.empty"),
      capturedAt: evidenceAsOf ?? data.rendered?.generated_at ?? new Date().toISOString(),
      facts: [
        { key: "report_count", value: data.catalog.items.length, group: "reports" },
        { key: "selected_report", value: data.selected?.id ?? null, group: "selection" },
        { key: "registered_widget_types", value: data.registry.widgets.length, group: "registry" },
        { key: "evidence_availability", value: data.rendered?.provenance.availability ?? null, group: "evidence" },
        { key: "evidence_synthetic", value: data.rendered?.provenance.synthetic ?? null, group: "evidence" },
        { key: "evidence_as_of", value: evidenceAsOf, group: "evidence" },
      ],
      records: {
        reports: data.catalog.items.map((report) => ({
          id: report.id,
          name: report.name,
          description: report.description,
          widget_count: report.widget_count,
          tags: report.tags,
        })),
      },
    }),
    [data, evidenceAsOf, headline],
  );

  return (
    <div class="reports-workspace">
      <nav class="reports-list" aria-label={t("reports.listLabel")}>
        {data.catalog.items.map((report) => (
          <a
            key={report.id}
            href={routeHref("reports", { segments: [report.id] })}
            class={data.selected?.id === report.id ? "active" : undefined}
            aria-current={data.selected?.id === report.id ? "page" : undefined}
          >
            <strong>{report.name}</strong>
            <span>{t("reports.widgetCount", { count: report.widget_count })}</span>
          </a>
        ))}
        {data.catalog.items.length === 0 ? <p class="muted">{t("reports.empty")}</p> : null}
      </nav>

      <section class="reports-detail" aria-live="polite">
        {data.operationError ? (
          <div class="state-block state-error" role="alert">{data.operationError}</div>
        ) : null}
        {data.selected ? (
          <>
            <header class="reports-header">
              <div>
                <span class="mono small">{data.selected.id} v{data.selected.version}</span>
                <h2>{data.selected.name}</h2>
                <p>{data.selected.description}</p>
              </div>
              {data.rendered ? (
                <span class="muted small">{t("reports.renderedAt", { time: data.rendered.generated_at })}</span>
              ) : null}
            </header>

            {data.rendered ? (
              <div class="analytics-evidence reports-evidence">
                <strong>
                  {data.rendered.provenance.synthetic === true
                    ? t("reports.simulated")
                    : data.rendered.provenance.synthetic === false
                      ? t("reports.measured")
                      : t("reports.provenanceUnknown")}
                </strong>
                <span>{t("reports.availability", {
                  status: data.rendered.provenance.availability,
                })}</span>
                {data.rendered.provenance.sources.map((source) => (
                  <span key={source.datasource}>
                    {source.datasource}: {source.source}
                    {source.as_of ? ` - ${t("reports.asOf", { time: source.as_of })}` : ""}
                  </span>
                ))}
              </div>
            ) : null}
            {data.rendered?.provenance.availability === "unavailable" ? (
              <div class="state-block state-unavailable" role="status">
                {t("reports.datasourceUnavailable")}
              </div>
            ) : null}

            {data.selected.variables.length > 0 ? (
              <div class="reports-variables" aria-label={t("reports.variables")}>
                {variableErrors.length > 0 ? (
                  <div class="state-block state-unavailable" role="alert">
                    {variableErrors.join("; ")}
                  </div>
                ) : null}
                {data.selected.variables.map((variable) => (
                  <label key={variable.name}>
                    <span>{variable.name}</span>
                    {variable.values.length > 0 ? (
                      <select
                        value={data.variables[variable.name] ?? ""}
                        onChange={(event) => onVariableChange(variable.name, event.currentTarget.value)}
                      >
                        {variable.values.map((value) => <option key={value} value={value}>{value}</option>)}
                      </select>
                    ) : (
                      <input
                        value={data.variables[variable.name] ?? ""}
                        onInput={(event) => onVariableChange(variable.name, event.currentTarget.value)}
                        placeholder={variable.description}
                      />
                    )}
                  </label>
                ))}
                <button type="button" class="primary" disabled={refreshing || !variablesComplete} onClick={() => void onRender()}>
                  {refreshing ? t("reports.refreshing") : t("reports.refresh")}
                </button>
                {data.catalog.formats.includes("pdf") ? (
                  <button
                    type="button"
                    disabled={downloading || !variablesComplete || data.rendered === null}
                    onClick={() => void onDownload()}
                  >
                    {downloading ? t("reports.downloadingPdf") : t("reports.downloadPdf")}
                  </button>
                ) : null}
              </div>
            ) : null}

            <div class="reports-registry muted small">
              {t("reports.registry", {
                supported: data.registry.widgets.filter((type) => SUPPORTED_REPORT_WIDGET_TYPES.has(type)).length,
                total: data.registry.widgets.length,
              })}
            </div>
            {data.rendered ? (
              <div class="process-widget-grid reports-widget-grid">
                {data.rendered.widgets.map((widget) => <ProcessWidget key={widget.id} widget={widget} />)}
              </div>
            ) : (
              <div class="state-block state-unavailable" role="status">{t("reports.readyHint")}</div>
            )}
          </>
        ) : (
          <div class="state-block state-unavailable" role="status">{t("reports.notFound")}</div>
        )}
      </section>
    </div>
  );
}
