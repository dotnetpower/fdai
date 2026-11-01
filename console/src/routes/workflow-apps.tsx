import { useEffect, useState } from "preact/hooks";
import { isOptionalOperatorApiUnavailable, type OperatorApiClient } from "../api";
import {
  AsyncBoundary,
  EmptyState,
  PageHeader,
  StatusPill,
  type AsyncState,
  type PillKind,
} from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import { getLocale, t } from "../i18n";
import { currentRoute, routeHref } from "../router";
import { formatDateTimeValue, formatNumber, statusLabel } from "./i18n/workflow";
import { decodeProcessList, processHref, processTone, type ProcessListResponse } from "./processes.model";
import {
  decodeWorkflowApps,
  workflowAppHref,
  workflowAppLifecycleTone,
  workflowRunStatusCounts,
  type WorkflowAppEntry,
  type WorkflowAppsResponse,
} from "./workflow-apps.model";

interface Props { readonly client: OperatorApiClient }

export function WorkflowAppsRoute({ client }: Props) {
  const [state, setState] = useState<AsyncState<WorkflowAppsResponse>>({ status: "loading" });
  const [selectedId, setSelectedId] = useState<string | null>(() => currentRoute().segments[0] ?? null);

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    client.panel<unknown>("/views/workflow-apps").then(
      (value) => {
        if (cancelled) return;
        try {
          setState({ status: "ready", data: decodeWorkflowApps(value) });
        } catch (error) {
          setState({ status: "error", message: error instanceof Error ? error.message : String(error) });
        }
      },
      (error: unknown) => {
        if (!cancelled) setState({ status: isOptionalOperatorApiUnavailable(error) ? "unavailable" : "error", message: error instanceof Error ? error.message : String(error) });
      },
    );
    return () => { cancelled = true; };
  }, [client]);

  useEffect(() => {
    const sync = () => setSelectedId(currentRoute().segments[0] ?? null);
    window.addEventListener("popstate", sync);
    window.addEventListener("fdai:route-changed", sync);
    return () => {
      window.removeEventListener("popstate", sync);
      window.removeEventListener("fdai:route-changed", sync);
    };
  }, []);

  return (
    <div class="stack">
      <PageHeader title={t("route.workflowApps")} subtitle={t("workflowApps.subtitle")} />
      <AsyncBoundary state={state} resourceLabel={t("workflowApps.resourceLabel")}>
        {(data) => <WorkflowAppsWorkspace client={client} data={data} selectedId={selectedId} />}
      </AsyncBoundary>
    </div>
  );
}

function WorkflowAppsWorkspace({ client, data, selectedId }: {
  readonly client: OperatorApiClient;
  readonly data: WorkflowAppsResponse;
  readonly selectedId: string | null;
}) {
  const locale = getLocale();
  const selected = selectedId === null
    ? (data.items[0] ?? null)
    : (data.items.find((app) => app.id === selectedId) ?? null);
  usePublishViewContext(
    () => ({
      routeId: "workflow-apps",
      routeLabel: t("route.workflowApps"),
      purpose: t("workflowApps.viewPurpose"),
      glossary: composeGlossary([TERMS.process, TERMS.viewSpec]),
      headline: selected
        ? t("workflowApps.viewHeadlineSelected", { name: selected.label[locale] })
        : t("workflowApps.viewHeadline", { count: data.count }),
      capturedAt: new Date().toISOString(),
      facts: [
        { key: "app_count", value: data.count, group: "workflow_app" },
        { key: "selected_app", value: selected?.id ?? "-", group: "workflow_app" },
      ],
      records: {
        workflow_apps: data.items.map((app) => ({
          id: app.id,
          workflow_ref: app.workflow_ref,
          view_ref: app.view_ref,
          lifecycle: app.lifecycle,
          route: app.route,
        })),
      },
    }),
    [data, selected, locale],
  );
  if (data.items.length === 0) {
    return <EmptyState title={t("workflowApps.emptyTitle")} body={t("workflowApps.emptyBody")} />;
  }
  return (
    <div class="stack">
      <section class="stack-section" aria-labelledby="workflow-app-list-title">
        <h3 id="workflow-app-list-title" class="section-title">{t("workflowApps.listLabel")}</h3>
        <div class="scroll">
          <table class="data-table">
            <thead><tr><th>{t("workflowApps.app")}</th><th>{t("workflowApps.workflow")}</th><th>{t("workflowApps.lifecycle")}</th></tr></thead>
            <tbody>{data.items.map((app) => (
              <tr key={app.id} class={app.id === selected?.id ? "row-active" : undefined}>
                <td><a href={workflowAppHref(app.id, currentRoute().search)}><strong>{app.label[locale]}</strong></a><br /><span class="muted small">{app.description[locale]}</span></td>
                <td><code>{app.workflow_ref}</code></td>
                <td><StatusPill kind={workflowAppLifecycleTone(app.lifecycle)} label={statusLabel(app.lifecycle)} /></td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      </section>
      {selectedId !== null && selected === null ? (
        <div class="state-block state-unavailable" role="alert">{t("workflowApps.notFound")}</div>
      ) : null}
      {selected ? <WorkflowAppRuns client={client} app={selected} /> : null}
    </div>
  );
}

function WorkflowAppRuns({ client, app }: { readonly client: OperatorApiClient; readonly app: WorkflowAppEntry }) {
  const [state, setState] = useState<AsyncState<ProcessListResponse>>({ status: "loading" });
  const [statusFilter, setStatusFilter] = useState<string>("");
  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    const query = new URLSearchParams({ workflow_ref: app.workflow_ref });
    client.panel<unknown>(`/views/process?${query.toString()}`).then(
      (value) => {
        if (cancelled) return;
        try {
          setState({ status: "ready", data: decodeProcessList(value) });
        } catch (error) {
          setState({ status: "error", message: error instanceof Error ? error.message : String(error) });
        }
      },
      (error: unknown) => {
        if (!cancelled) {
          setState({
            status: isOptionalOperatorApiUnavailable(error) ? "unavailable" : "error",
            message: error instanceof Error ? error.message : String(error),
          });
        }
      },
    );
    return () => { cancelled = true; };
  }, [client, app.workflow_ref]);
  useEffect(() => setStatusFilter(""), [app.workflow_ref]);
  return (
    <section class="stack-section workflow-app-runs" aria-labelledby="workflow-app-runs-title">
      <div class="workflow-app-runs-head">
        <h3 id="workflow-app-runs-title" class="section-title">{t("workflowApps.runs")}</h3>
        <a href={routeHref("workflow-builder", { params: { workflow: app.workflow_ref } })}>
          {t("workflowApps.openDefinition")}
        </a>
      </div>
      <AsyncBoundary state={state} resourceLabel={t("workflowApps.runsResourceLabel")}>
        {(data) => {
          if (data.items.length === 0) {
            return <EmptyState title={t("workflowApps.noRuns")} body={t("workflowApps.noRunsBody")} />;
          }
          const counts = workflowRunStatusCounts(data.items);
          const rows = [...data.items]
            .filter((process) => statusFilter === "" || process.status === statusFilter)
            .sort((left, right) => right.updated_at.localeCompare(left.updated_at));
          return (
            <>
              <div class="segmented-control workflow-app-status-filter" role="group" aria-label={t("workflowApps.statusFilter")}>
                <button
                  type="button"
                  class={statusFilter === "" ? "active" : undefined}
                  aria-pressed={statusFilter === ""}
                  onClick={() => setStatusFilter("")}
                >
                  {t("workflowApps.allStatuses")} <strong>{formatNumber(data.items.length)}</strong>
                </button>
                {counts.map(({ status, count }) => (
                  <button
                    type="button"
                    key={status}
                    class={statusFilter === status ? "active" : undefined}
                    aria-pressed={statusFilter === status}
                    onClick={() => setStatusFilter(status)}
                  >
                    {statusLabel(status)} <strong>{formatNumber(count)}</strong>
                  </button>
                ))}
              </div>
              <div class="scroll"><table class="data-table"><thead><tr><th>{t("workflowApps.target")}</th><th>{t("workflowApps.step")}</th><th>{t("workflowApps.status")}</th><th>{t("workflowApps.updated")}</th></tr></thead><tbody>
                {rows.map((process) => <tr key={process.id}>
                  <td><a href={processHref(process.id)}>{process.target_resource_id}</a><br /><code class="small">{process.id}</code></td>
                  <td>{process.current_step || t("workflowApps.terminal")}</td>
                  <td><StatusPill kind={processTone(process.status)} label={statusLabel(process.status)} /></td>
                  <td><time dateTime={process.updated_at}>{formatDateTimeValue(process.updated_at)}</time></td>
                </tr>)}
              </tbody></table></div>
            </>
          );
        }}
      </AsyncBoundary>
    </section>
  );
}
