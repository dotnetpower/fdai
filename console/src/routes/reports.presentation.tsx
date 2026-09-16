import { usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import { EmptyState, StatusPill, type PillKind } from "../components/ui";
import { t } from "../i18n";
import { routeHref } from "../router";
import { ProcessWidget, SUPPORTED_REPORT_WIDGET_TYPES } from "./process-view-renderer";
import type { ReportProvenance, ReportVariable } from "./reporting.model";
import {
  aggregateEvidenceAsOf,
  pdfDownloadAvailable,
  registrySourceReadiness,
  reportHeadlineState,
  reportSourceAvailability,
  reportVariableErrors,
  shouldShowReportVariableErrors,
  type ReportsData,
} from "./reports.model";

export function ReportsBody({
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
  const showVariableErrors = shouldShowReportVariableErrors(data.variables, variableErrors);
  const variablesComplete = data.selected !== null && variableErrors.length === 0;
  const evidenceAsOf = aggregateEvidenceAsOf(data.rendered?.provenance.sources ?? []);
  const headline = reportHeadlineState(data.selected, data.rendered);
  const sourceReadiness = registrySourceReadiness(data.registry);
  const supportedRendererCount = data.registry.widgets
    .filter((type) => SUPPORTED_REPORT_WIDGET_TYPES.has(type)).length;
  const evidenceStatus: ReportPresentationStatus =
    data.rendered?.provenance.availability ?? "not_rendered";
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
    <div class="reports-surface">
      <section class="reports-boundary" role="note">
        <StatusPill kind="neutral" label={t("reports.boundaryLabel")} />
        <p>{t("reports.boundaryText")}</p>
      </section>

      <dl class="reports-summary" aria-label={t("reports.summaryLabel")}>
        <div>
          <dt>{t("reports.summaryTemplates")}</dt>
          <dd>
            <strong>{data.catalog.items.length}</strong>
            <span>{t("reports.summaryCurrentCatalog")}</span>
          </dd>
        </div>
        <div>
          <dt>{t("reports.summarySources")}</dt>
          <dd>
            <strong>{sourceReadiness.available} / {sourceReadiness.total}</strong>
            <span>{t("reports.summaryRegisteredSources", { count: sourceReadiness.total })}</span>
          </dd>
        </div>
        <div>
          <dt>{t("reports.summaryRenderers")}</dt>
          <dd>
            <strong>{supportedRendererCount} / {data.registry.widgets.length}</strong>
            <span>{t("reports.summaryRegisteredWidgets", { count: data.registry.widgets.length })}</span>
          </dd>
        </div>
        <div>
          <dt>{t("reports.summaryEvidence")}</dt>
          <dd>
            <strong>{reportAvailabilityLabel(evidenceStatus)}</strong>
            <span>
              {data.selected
                ? t("reports.summarySelected", { name: data.selected.name })
                : t("reports.summaryNoSelection")}
            </span>
          </dd>
        </div>
      </dl>

      {data.selected ? (
        <form
          class="reports-toolbar"
          aria-label={t("reports.variables")}
          onSubmit={(event) => {
            event.preventDefault();
            void onRender();
          }}
        >
          <div class="reports-toolbar-template">
            <span>{t("reports.template")}</span>
            <strong>{data.selected.name}</strong>
          </div>
          {data.selected.variables.map((variable) => (
            <label key={variable.name}>
              <span>{variable.name}</span>
              {variable.values.length > 0 ? (
                <select
                  required
                  value={data.variables[variable.name] ?? ""}
                  onChange={(event) => onVariableChange(variable.name, event.currentTarget.value)}
                >
                  {variable.values.map((value) => <option key={value} value={value}>{value}</option>)}
                </select>
              ) : (
                <input
                  required
                  value={data.variables[variable.name] ?? ""}
                  onInput={(event) => onVariableChange(variable.name, event.currentTarget.value)}
                  placeholder={variable.description}
                />
              )}
            </label>
          ))}
          <div class="reports-toolbar-actions">
            <button type="submit" class="primary" disabled={refreshing || !variablesComplete}>
              {refreshing ? t("reports.refreshing") : t("reports.refresh")}
            </button>
            {pdfDownloadAvailable(data.catalog.formats, data.registry.formats) ? (
              <button
                type="button"
                disabled={downloading || !variablesComplete || data.rendered === null}
                onClick={() => void onDownload()}
              >
                {downloading ? t("reports.downloadingPdf") : t("reports.downloadPdf")}
              </button>
            ) : null}
          </div>
        </form>
      ) : null}

      {showVariableErrors ? (
        <div class="state-block state-unavailable" role="alert">
          {variableErrors.join("; ")}
        </div>
      ) : null}

      {data.selected && data.selected.variables.length > 0 ? (
        <details class="reports-variable-contract">
          <summary>
            <span>{t("reports.variableContract")}</span>
            <strong>{t("reports.variableBindings", {
              count: data.selected.variables.length,
            })}</strong>
          </summary>
          <dl>
            {data.selected.variables.map((variable) => (
              <div key={variable.name}>
                <dt><code>{variable.name}</code></dt>
                <dd>
                  <strong>{reportVariableConstraint(variable)}</strong>
                  <span>{variable.description}</span>
                </dd>
              </div>
            ))}
          </dl>
        </details>
      ) : null}

      <div class="reports-workspace">
        <aside class="reports-catalog" aria-labelledby="reports-catalog-title">
          <header>
            <div>
              <h2 id="reports-catalog-title">{t("reports.catalogTitle")}</h2>
              <p>{t("reports.catalogDescription")}</p>
            </div>
            <span class="reports-catalog-count">{data.catalog.items.length}</span>
          </header>
          <nav class="reports-list" aria-label={t("reports.listLabel")}>
            {data.catalog.items.map((report) => {
              const availability = reportSourceAvailability(report, data.registry);
              return (
                <a
                  key={report.id}
                  href={routeHref("reports", { segments: [report.id] })}
                  class={data.selected?.id === report.id ? "active" : undefined}
                  aria-current={data.selected?.id === report.id ? "page" : undefined}
                >
                  <strong>{report.name}</strong>
                  <span class="reports-list-meta">
                    <span>{t("reports.widgetCount", { count: report.widget_count })}</span>
                    <span class={`reports-source-state is-${availability}`}>
                      {reportAvailabilityLabel(availability)}
                    </span>
                  </span>
                </a>
              );
            })}
            {data.catalog.items.length === 0 ? (
              <p class="reports-catalog-empty muted">{t("reports.empty")}</p>
            ) : null}
          </nav>
        </aside>

        <section
          class="reports-detail"
          aria-live="polite"
          aria-labelledby={data.selected ? "reports-selected-title" : undefined}
        >
          {data.selected ? (
            <>
              <header class="reports-header">
                <div>
                  <span class="mono small">{data.selected.id} v{data.selected.version}</span>
                  <h2 id="reports-selected-title">{data.selected.name}</h2>
                  <p>{data.selected.description}</p>
                </div>
                <div class="reports-header-meta">
                  {data.rendered ? (
                    <span>{t("reports.renderedAt", { time: data.rendered.generated_at })}</span>
                  ) : null}
                  <StatusPill
                    kind={reportAvailabilityTone(evidenceStatus)}
                    label={reportAvailabilityLabel(evidenceStatus)}
                  />
                </div>
              </header>

              {data.operationError ? (
                <div class="state-block state-error" role="alert">{data.operationError}</div>
              ) : null}
              {data.rendered?.provenance.availability === "unavailable" ? (
                <div class="state-block state-unavailable" role="status">
                  {t("reports.datasourceUnavailable")}
                </div>
              ) : null}

              {data.rendered ? (
                data.rendered.widgets.length > 0 ? (
                  <div class="process-widget-grid reports-widget-grid">
                    {data.rendered.widgets.map((widget) => (
                      <ProcessWidget key={widget.id} widget={widget} />
                    ))}
                  </div>
                ) : (
                  <EmptyState
                    title={t("reports.noWidgets")}
                    body={t("reports.noWidgetsDetail")}
                  />
                )
              ) : (
                <EmptyState
                  title={t("reports.readyHint")}
                  body={t("reports.readyHintDetail")}
                />
              )}

              {data.rendered ? (
                <>
                  <footer class="reports-provenance" aria-label={t("reports.provenance")}>
                    <strong>
                      {data.rendered.provenance.synthetic === true
                        ? t("reports.simulated")
                        : data.rendered.provenance.synthetic === false
                          ? t("reports.measured")
                          : t("reports.provenanceUnknown")}
                    </strong>
                    <span>{reportAvailabilityLabel(data.rendered.provenance.availability)}</span>
                    <span>
                      {evidenceAsOf
                        ? t("reports.asOf", { time: evidenceAsOf })
                        : t("reports.asOfUnavailable")}
                    </span>
                    <span>{t("reports.mutationAuthorityNone")}</span>
                  </footer>
                  {data.rendered.provenance.sources.length > 0 ? (
                    <details class="reports-source-details">
                      <summary>
                        <span>{t("reports.sourceDetails")}</span>
                        <strong>{t("reports.sourceCount", {
                          count: data.rendered.provenance.sources.length,
                        })}</strong>
                      </summary>
                      <dl>
                        {data.rendered.provenance.sources.map((source, index) => (
                          <div key={`${source.datasource}-${index}`}>
                            <dt><code>{source.datasource}</code></dt>
                            <dd>
                              <strong>{source.source}</strong>
                              <span>{reportAvailabilityLabel(source.availability)}</span>
                              <span>
                                {source.as_of
                                  ? t("reports.asOf", { time: source.as_of })
                                  : t("reports.asOfUnavailable")}
                              </span>
                            </dd>
                          </div>
                        ))}
                      </dl>
                    </details>
                  ) : null}
                </>
              ) : null}
            </>
          ) : (
            <EmptyState
              title={data.catalog.items.length === 0 ? t("reports.empty") : t("reports.notFound")}
            />
          )}
        </section>
      </div>

      <p class="reports-registry muted">
        {t("reports.registry", {
          supported: supportedRendererCount,
          total: data.registry.widgets.length,
        })}
      </p>
    </div>
  );
}

type ReportPresentationStatus =
  | ReportProvenance["availability"]
  | "not_rendered";

function reportAvailabilityLabel(status: ReportPresentationStatus): string {
  switch (status) {
    case "available":
      return t("reports.status.available");
    case "partial":
      return t("reports.status.partial");
    case "unavailable":
      return t("reports.status.unavailable");
    case "unknown":
      return t("reports.status.unknown");
    case "not_applicable":
      return t("reports.status.notApplicable");
    case "not_rendered":
      return t("reports.status.notRendered");
  }
}

function reportAvailabilityTone(status: ReportPresentationStatus): PillKind {
  if (status === "available") return "success";
  if (status === "partial") return "warning";
  return "neutral";
}

function reportVariableConstraint(variable: ReportVariable): string {
  if (variable.values.length > 0) {
    return t("reports.variableAllowed", { values: variable.values.join(", ") });
  }
  const defaultValue = variable.default?.trim();
  return defaultValue
    ? t("reports.variableDefault", { value: defaultValue })
    : t("reports.variableRequired");
}
