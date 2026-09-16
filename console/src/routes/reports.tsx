import { useEffect, useRef, useState } from "preact/hooks";
import type { OperatorApiClient } from "../api";
import { triggerBlobDownload } from "../blob-download";
import { AsyncBoundary, PageHeader, type AsyncState } from "../components/ui";
import { t } from "../i18n";
import { currentRoute, routeHref } from "../router";
import type { RenderedReportView } from "./reporting.model";
import {
  defaultReport,
  reportDownloadCanComplete,
  reportVariableErrors,
  reportsLoadFailure,
  updateReportVariable,
  type ReportsData,
} from "./reports.model";
import { ReportsBody } from "./reports.presentation";
import "./reports.css";

interface Props {
  readonly client: OperatorApiClient;
}

export { triggerBlobDownload } from "../blob-download";
export {
  aggregateEvidenceAsOf,
  defaultReport,
  pdfDownloadAvailable,
  registrySourceReadiness,
  reportDownloadCanComplete,
  reportHeadlineState,
  reportSourceAvailability,
  reportsLoadFailure,
  reportVariableErrors,
  shouldShowReportVariableErrors,
  updateReportVariable,
} from "./reports.model";

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
          setState(reportsLoadFailure(error));
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

  const headerActions = state.status === "ready" ? (
    <div class="reports-page-meta">
      <span>{t("reports.headerCatalog")}</span>
      <strong>{t("reports.headerSummary", {
        templates: state.data.catalog.items.length,
        widgets: state.data.catalog.items.reduce((total, report) => total + report.widget_count, 0),
      })}</strong>
    </div>
  ) : undefined;

  return (
    <div class="stack reports-route">
      <PageHeader
        title={t("route.reports")}
        subtitle={t("reports.subtitle")}
        actions={headerActions}
      />
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
