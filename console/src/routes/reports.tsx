import { useEffect, useState } from "preact/hooks";
import type { ReadApiClient } from "../api";
import { AsyncBoundary, PageHeader, type AsyncState } from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import { t } from "../i18n";
import { currentRoute, routeHref } from "../router";
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
}

export function ReportsRoute({ client }: Props) {
  const requestedId = currentRoute().segments[0] ?? null;
  const [state, setState] = useState<AsyncState<ReportsData>>({ status: "loading" });
  const [refreshing, setRefreshing] = useState(false);
  const [downloading, setDownloading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    void (async () => {
      try {
        const [catalog, registry] = await Promise.all([
          client.reports(),
          client.reportingRegistry(),
        ]);
        const selected = requestedId
          ? catalog.items.find((report) => report.id === requestedId) ?? null
          : catalog.items[0] ?? null;
        const queryVariables = new URLSearchParams(window.location.search);
        const variables = Object.fromEntries(
          (selected?.variables ?? []).map((variable) => [
            variable.name,
            queryVariables.get(variable.name) ?? variable.default ?? variable.values[0] ?? "",
          ]),
        );
        const complete = selected?.variables.every((variable) =>
          (variables[variable.name] ?? "").trim().length > 0,
        ) ?? false;
        const rendered = selected && complete
          ? await client.renderReport(selected.id, variables)
          : null;
        if (!cancelled) {
          setState({
            status: "ready",
            data: { catalog, registry, selected, rendered, variables },
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
    };
  }, [client, requestedId]);

  const updateVariable = (name: string, value: string) => {
    setState((current) => current.status === "ready"
      ? {
          status: "ready",
          data: { ...current.data, variables: { ...current.data.variables, [name]: value } },
        }
      : current);
  };

  const renderSelected = async () => {
    if (state.status !== "ready" || state.data.selected === null || refreshing) return;
    if (state.data.selected.variables.some((variable) =>
      (state.data.variables[variable.name] ?? "").trim().length === 0,
    )) return;
    setRefreshing(true);
    try {
      const rendered = await client.renderReport(state.data.selected.id, state.data.variables);
      setState((current) => current.status === "ready"
        ? { status: "ready", data: { ...current.data, rendered } }
        : current);
    } catch (error) {
      setState({ status: "error", message: error instanceof Error ? error.message : String(error) });
    } finally {
      setRefreshing(false);
    }
  };

  const downloadSelected = async () => {
    if (state.status !== "ready" || state.data.selected === null || downloading) return;
    setDownloading(true);
    try {
      const blob = await client.downloadReport(
        state.data.selected.id,
        "pdf",
        state.data.variables,
      );
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `${state.data.selected.id}.pdf`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      setState({ status: "error", message: error instanceof Error ? error.message : String(error) });
    } finally {
      setDownloading(false);
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
  const variablesComplete = data.selected?.variables.every((variable) =>
    (data.variables[variable.name] ?? "").trim().length > 0,
  ) ?? false;
  usePublishViewContext(
    () => ({
      routeId: "reports",
      routeLabel: t("route.reports"),
      purpose: t("reports.viewPurpose"),
      glossary: composeGlossary([TERMS.report, TERMS.widget]),
      headline: data.selected
        ? t("reports.viewHeadline", { name: data.selected.name, count: data.rendered?.widgets.length ?? 0 })
        : t("reports.empty"),
      capturedAt: new Date().toISOString(),
      facts: [
        { key: "report_count", value: data.catalog.items.length, group: "reports" },
        { key: "selected_report", value: data.selected?.id ?? null, group: "selection" },
        { key: "registered_widget_types", value: data.registry.widgets.length, group: "registry" },
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
    [data],
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
        {data.selected ? (
          <>
            <header class="reports-header">
              <div>
                <span class="mono small">{data.selected.id} v{data.selected.version}</span>
                <h2>{data.selected.name}</h2>
                <p>{data.selected.description}</p>
              </div>
              {data.rendered ? (
                <span class="muted small">{t("reports.generated", { time: data.rendered.generated_at })}</span>
              ) : null}
            </header>

            {data.selected.variables.length > 0 ? (
              <div class="reports-variables" aria-label={t("reports.variables")}>
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
