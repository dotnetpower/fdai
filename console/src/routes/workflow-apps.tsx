import { useEffect, useState } from "preact/hooks";
import { isOptionalOperatorApiUnavailable, type OperatorApiClient } from "../api";
import { EvidenceRefresh } from "../components/evidence-refresh";
import {
  AsyncBoundary,
  DataTable,
  EmptyState,
  KpiCard,
  KpiGrid,
  PageHeader,
  StatusPill,
  type AsyncState,
  type Column,
} from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import { getLocale, t } from "../i18n";
import { currentRoute, navigate, routeHref } from "../router";
import { formatDateTimeValue, formatNumber, statusLabel } from "./i18n/workflow";
import { decodeProcessList, processHref, processTone, type ProcessListResponse, type ProcessSummary } from "./processes.model";
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
  const [refreshRevision, setRefreshRevision] = useState(0);
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
  }, [client, refreshRevision]);

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
    <div class="stack cs-workspace-route">
      <PageHeader
        title={t("route.workflowApps")}
        subtitle={t("workflowApps.subtitle")}
        actions={
          <EvidenceRefresh
            loading={state.status === "loading"}
            onRefresh={() => setRefreshRevision((revision) => revision + 1)}
          />
        }
      />
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
  const appColumns: readonly Column<WorkflowAppEntry>[] = [
    {
      key: "app",
      header: t("workflowApps.app"),
      render: (app) => (
        <div>
          <a href={workflowAppHref(app.id, currentRoute().search)}><strong>{app.label[locale]}</strong></a>
          <br />
          <span class="muted small">{app.description[locale]}</span>
        </div>
      ),
    },
    {
      key: "workflow",
      header: t("workflowApps.workflow"),
      render: (app) => <code>{app.workflow_ref}</code>,
    },
    {
      key: "lifecycle",
      header: t("workflowApps.lifecycle"),
      render: (app) => <StatusPill kind={workflowAppLifecycleTone(app.lifecycle)} label={statusLabel(app.lifecycle)} />,
    },
  ];
  const listHref = `${routeHref("workflow-apps")}#workflow-app-list-title`;
  return (
    <div class="stack">
      <KpiGrid>
        <KpiCard href={listHref} label={t("workflowApps.listLabel")} value={formatNumber(data.items.length)} />
        <KpiCard href={listHref} label={t("workflowApps.app")} value={selected?.label[locale] ?? "-"} />
        <KpiCard href={listHref} label={t("workflowApps.workflow")} value={selected?.workflow_ref ?? "-"} />
      </KpiGrid>
      <div class={`cs-workspace-split${selected ? " has-selection" : ""}`}>
        <section class="stack-section cs-workspace-main" aria-labelledby="workflow-app-list-title">
          <h3 id="workflow-app-list-title" class="section-title">{t("workflowApps.listLabel")}</h3>
          <DataTable
            columns={appColumns}
            rows={data.items}
            keyOf={(app) => app.id}
            onRowClick={(app) => navigate(workflowAppHref(app.id, currentRoute().search))}
            isRowActive={(app) => app.id === selected?.id}
            scrollRegionLabel={t("workflowApps.listLabel")}
          />
        </section>
        {selected ? (
          <aside class="cs-inspector-pane" aria-label={selected.label[locale]}>
            <header class="cs-inspector-head">
              <div>
                <span class="cs-inspector-kicker">{selected.id}</span>
                <h3>{selected.label[locale]}</h3>
                <p>{selected.description[locale]}</p>
              </div>
              <StatusPill kind={workflowAppLifecycleTone(selected.lifecycle)} label={statusLabel(selected.lifecycle)} />
            </header>
            <dl class="cs-facts-grid">
              <div><dt>{t("workflowApps.workflow")}</dt><dd><code>{selected.workflow_ref}</code></dd></div>
              <div><dt>View</dt><dd><code>{selected.view_ref}</code></dd></div>
              <div><dt>Route</dt><dd><code>{selected.route}</code></dd></div>
            </dl>
          </aside>
        ) : null}
      </div>
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
  const runColumns: readonly Column<ProcessSummary>[] = [
    {
      key: "target",
      header: t("workflowApps.target"),
      render: (process) => (
        <div>
          <a href={processHref(process.id)}>{process.target_resource_id}</a>
          <br />
          <code class="small">{process.id}</code>
        </div>
      ),
    },
    {
      key: "step",
      header: t("workflowApps.step"),
      render: (process) => process.current_step || t("workflowApps.terminal"),
    },
    {
      key: "status",
      header: t("workflowApps.status"),
      render: (process) => <StatusPill kind={processTone(process.status)} label={statusLabel(process.status)} />,
    },
    {
      key: "updated",
      header: t("workflowApps.updated"),
      render: (process) => <time dateTime={process.updated_at}>{formatDateTimeValue(process.updated_at)}</time>,
    },
  ];
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
              <DataTable
                columns={runColumns}
                rows={rows}
                keyOf={(process) => process.id}
                scrollRegionLabel={t("workflowApps.runs")}
              />
            </>
          );
        }}
      </AsyncBoundary>
    </section>
  );
}
