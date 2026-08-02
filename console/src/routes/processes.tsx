import { useEffect, useReducer, useState } from "preact/hooks";
import type { OperatorApiClient } from "../api";
import { AsyncBoundary, EmptyState, PageHeader, StatusPill, type AsyncState } from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import { t } from "../i18n";
import { currentRoute, routeHref } from "../router";
import { formatConsoleTimestamp } from "../time-format";
import { ProcessWidget, RenderedRegion } from "./process-view-renderer";
import { schedulerRunsText } from "./scheduler-runs.i18n";
import { SchedulerRunsRoute } from "./scheduler-runs";
import {
  decodeProcessList,
  decodeProcessJournal,
  decodeRenderedProcessView,
    assertProcessDetailSelection,
    displayValue,
    INITIAL_PROCESS_REFRESH,
    type ProcessDetailData,
    type ProcessEvent,
  defaultProcessId,
  processHref,
  processEventHref,
  processIdFromHash,
  processListFailure,
  processTone,
  reduceProcessRefresh,
  type ProcessListResponse,
  type ProcessSummary,
  type RenderedProcessView,
} from "./processes.model";

interface Props { readonly client: OperatorApiClient }

interface LoadedProcessList {
  readonly response: ProcessListResponse;
  readonly generation: number;
}

export function ProcessesRoute({ client }: Props) {
  if (currentRoute().segments[0] === "scheduler-runs") {
    return <SchedulerRunsRoute client={client} />;
  }
  return <ProcessRuntimeRoute client={client} />;
}

function ProcessRuntimeRoute({ client }: Props) {
  const [listState, setListState] = useState<AsyncState<LoadedProcessList>>({ status: "loading" });
  const [selectedId, setSelectedId] = useState<string | null>(() => currentRoute().segments[0] ?? null);
  const [detailState, setDetailState] = useState<AsyncState<ProcessDetailData>>({ status: "idle" });
  const [refreshCycle, dispatchRefresh] = useReducer(reduceProcessRefresh, INITIAL_PROCESS_REFRESH);

  useEffect(() => {
    const sync = () => setSelectedId(currentRoute().segments[0] ?? null);
    window.addEventListener("popstate", sync);
    window.addEventListener("fdai:route-changed", sync);
    return () => {
      window.removeEventListener("popstate", sync);
      window.removeEventListener("fdai:route-changed", sync);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    client.panel<unknown>("/views/process").then(
      (payload) => {
        if (cancelled) return;
        let data: ProcessListResponse;
        try {
          data = decodeProcessList(payload);
        } catch (error) {
          setListState(processListFailure(error));
          dispatchRefresh({ type: "finish", generation: refreshCycle.generation });
          return;
        }
        setListState({
          status: "ready",
          data: { response: data, generation: refreshCycle.generation },
        });
        const defaultId = currentRoute().segments[0] ?? defaultProcessId(data.items, "");
        if (!currentRoute().segments[0] && defaultId) {
          window.history.replaceState(window.history.state, "", processHref(defaultId));
          setSelectedId(defaultId);
        } else if (!defaultId) {
          dispatchRefresh({ type: "finish", generation: refreshCycle.generation });
        }
      },
      (error: unknown) => {
        if (cancelled) return;
        setListState(processListFailure(error));
        dispatchRefresh({ type: "finish", generation: refreshCycle.generation });
      },
    );
    return () => { cancelled = true; };
  }, [client, refreshCycle.generation]);

  useEffect(() => {
    if (listState.status !== "ready") return;
    const generation = listState.data.generation;
    if (!selectedId) {
      setDetailState({ status: "idle" });
      dispatchRefresh({ type: "finish", generation });
      return;
    }
    let cancelled = false;
    setDetailState({ status: "loading" });
    const encodedId = encodeURIComponent(selectedId);
    void (async () => {
      try {
        const journalPayload = await client.panel<unknown>(`/views/process/${encodedId}/events`);
        const journal = decodeProcessJournal(journalPayload);
        const viewPayload = journal.process.has_view
          ? await client.panel<unknown>(`/views/process/${encodedId}`)
          : null;
        const view = viewPayload === null ? null : decodeRenderedProcessView(viewPayload);
        assertProcessDetailSelection(selectedId, journal, view);
        if (!cancelled) {
          setDetailState({
            status: "ready",
            data: {
              journal,
              view,
            },
          });
        }
      } catch (error) {
        if (!cancelled) {
          setDetailState({ status: "error", message: error instanceof Error ? error.message : String(error) });
        }
      } finally {
        if (!cancelled) dispatchRefresh({ type: "finish", generation });
      }
    })();
    return () => { cancelled = true; };
  }, [client, selectedId, listState]);

  return (
    <div class="stack process-route">
      <PageHeader
        title={t("route.processes")}
        subtitle={t("processesView.subtitle")}
        actions={
          <>
            <a class="btn btn-small" href={routeHref("scheduler-runs")}>
              {schedulerRunsText("title")}
            </a>
            <button
              type="button"
              class="btn btn-small"
              disabled={refreshCycle.refreshing || listState.status === "loading" || detailState.status === "loading"}
              aria-busy={refreshCycle.refreshing}
              onClick={() => dispatchRefresh({ type: "start" })}
            >
              {refreshCycle.refreshing ? t("processesView.refreshing") : t("processesView.refresh")}
            </button>
          </>
        }
      />
      <AsyncBoundary state={listState} resourceLabel={t("processesView.resourceLabel")}>
        {(data) => <ProcessWorkspace processList={data.response} selectedId={selectedId} detailState={detailState} />}
      </AsyncBoundary>
    </div>
  );
}

function ProcessWorkspace({ processList, selectedId, detailState }: {
  readonly processList: ProcessListResponse;
  readonly selectedId: string | null;
  readonly detailState: AsyncState<ProcessDetailData>;
}) {
  const processes = processList.items;
  const selected = processes.find((item) => item.id === selectedId) ?? null;
  usePublishViewContext(
    () => ({
      routeId: "processes",
      routeLabel: t("route.processes"),
      purpose: t("processesView.viewPurpose"),
      glossary: composeGlossary([TERMS.process, TERMS.viewSpec]),
      headline: selected
        ? t("processesView.viewHeadlineSelected", { count: processes.length, workflow: selected.workflow_ref, status: selected.status })
        : t("processesView.viewHeadline", { count: processes.length }),
      capturedAt: selected?.updated_at ?? new Date().toISOString(),
      facts: [
        { key: "process_count", value: processes.length, group: "process" },
        { key: "source", value: processList.source, group: "process" },
        { key: "synthetic", value: processList.synthetic, group: "process" },
        { key: "durable", value: processList.durable, group: "process" },
        { key: "selected", value: selected?.id ?? "-", group: "process" },
        { key: "status", value: selected?.status ?? "-", group: "process" },
      ],
      records: {
        processes: processes.map((process) => ({
          id: process.id,
          workflow_ref: process.workflow_ref,
          workflow_version: process.workflow_version,
          status: process.status,
          current_step: process.current_step,
          target_resource_id: process.target_resource_id,
          updated_at: process.updated_at,
          has_view: process.has_view,
        })),
      },
    }),
    [processList, processes, selected],
  );
  if (processes.length === 0) {
    return <EmptyState title={t("processesView.emptyTitle")} body={t("processesView.emptyBody")} />;
  }
  const hasRenderableProcess = processes.some((process) => process.has_view);
  return (
    <div class="stack process-status-workspace">
      <div class="filter-summary" aria-label={t("processesView.provenanceLabel")}>
        <span>{t("processesView.source")}: <strong>{processList.source}</strong></span>
        <span>{t("processesView.evidence")}: <strong>
          {processList.synthetic === true ? t("processesView.synthetic") : processList.synthetic === false ? t("processesView.observed") : t("processesView.unknown")}
        </strong></span>
        <span>{t("processesView.storage")}: <strong>
          {processList.durable === true ? t("processesView.durable") : processList.durable === false ? t("processesView.volatile") : t("processesView.unknown")}
        </strong></span>
      </div>
      <ProcessStatusSummary processes={processes} />
      <div class="process-workspace">
        <aside class="process-list" aria-label={t("processesView.listLabel")}>
          {processes.map((process) => (
          <a key={process.id} href={processHref(process.id)} class={`process-list-entry ${process.id === selectedId ? "is-active" : ""}`}>
            <ProcessListLabel process={process} />
          </a>
          ))}
        </aside>
        <section class="process-view-stage">
          <AsyncBoundary state={detailState} resourceLabel={t("processesView.detailResourceLabel")} idle={<p class="muted">{hasRenderableProcess ? t("processesView.select") : t("processesView.selectJournal")}</p>}>
            {(detail) => <ProcessDetail detail={detail} />}
          </AsyncBoundary>
        </section>
      </div>
    </div>
  );
}

function ProcessListLabel({ process }: {
  readonly process: ProcessSummary;
}) {
  return (
    <>
      <div>
        <strong>{process.workflow_ref}</strong>
        <small>{process.current_step || t("processesView.terminal")}{process.has_view ? "" : ` - ${t("processesView.runtime")}`}</small>
      </div>
      <StatusPill kind={processTone(process.status)} label={process.status} />
    </>
  );
}

function ProcessStatusSummary({ processes }: { readonly processes: readonly ProcessSummary[] }) {
  const active = processes.filter((process) => ["pending", "running", "waiting", "compensating"].includes(process.status)).length;
  const failed = processes.filter((process) => ["failed", "cancelled", "timed_out"].includes(process.status)).length;
  const completed = processes.length - active - failed;
  return (
    <div class="process-status-summary" aria-label={t("processesView.summaryLabel")}>
      <span><strong>{processes.length}</strong> {t("processesView.runs")}</span>
      <span><strong>{active}</strong> {t("processesView.active")}</span>
      <span><strong>{completed}</strong> {t("processesView.completed")}</span>
      <span class={failed > 0 ? "is-danger" : undefined}><strong>{failed}</strong> {t("processesView.failed")}</span>
    </div>
  );
}

function ProcessDetail({ detail }: { readonly detail: ProcessDetailData }) {
  const { process, events } = detail.journal;
  return (
    <div class="stack process-detail">
      <header class="process-view-header">
        <div>
          <span class="eyebrow">{process.workflow_ref} <span class="mono">v{process.workflow_version}</span></span>
          <h2>{process.target_resource_id}</h2>
          <p class="muted">{t("processesView.process")} <span class="mono">{process.id}</span></p>
        </div>
        <div class="process-view-status">
          <StatusPill kind={processTone(process.status)} label={process.status} />
          <span class="mono">{process.current_step || t("processesView.terminal")}</span>
        </div>
      </header>
      <dl class="process-runtime-meta">
        <div><dt>{t("processesView.started")}</dt><dd>{formatConsoleTimestamp(process.started_at)}</dd></div>
        <div><dt>{t("processesView.updated")}</dt><dd>{formatConsoleTimestamp(process.updated_at)}</dd></div>
        <div><dt>{t("processesView.revision")}</dt><dd>{process.revision}</dd></div>
        <div><dt>{t("processesView.journalEvents")}</dt><dd>{detail.journal.count}</dd></div>
      </dl>
      <ProcessJournal processId={process.id} events={events} />
      {detail.view ? <RenderedProcess view={detail.view} compactHeader /> : (
        <p class="process-generic-note muted">{t("processesView.noViewSpec")}</p>
      )}
    </div>
  );
}

function ProcessJournal({
  processId,
  events,
}: {
  readonly processId: string;
  readonly events: readonly ProcessEvent[];
}) {
  const selectedEvent = currentRoute().search.get("event");
  return (
    <section class="process-journal" aria-labelledby="process-journal-title">
      <div class="process-section-heading">
        <div><span class="eyebrow">{t("processesView.executionJournal")}</span><h3 id="process-journal-title">{t("processesView.stepTimeline")}</h3></div>
        <span class="muted">{t("processesView.oldestToNewest")}</span>
      </div>
      <ol class="process-timeline">
        {events.map((event) => (
          <li key={event.event_id}>
            <span class="process-timeline-marker" aria-hidden="true" />
            <div>
              <div class="process-event-head">
                <strong>{event.kind.replaceAll(".", " ")}</strong>
                <a
                  class="mono small"
                  href={processEventHref(processId, event.event_id)}
                >
                  {event.event_id}
                </a>
                <time dateTime={event.recorded_at}>{formatConsoleTimestamp(event.recorded_at)}</time>
              </div>
              <p>{event.step_id ? <span class="mono">{event.step_id}</span> : t("processesView.lifecycle")}{eventSummary(event) ? ` - ${eventSummary(event)}` : ""}</p>
              <details class="process-event-detail" open={selectedEvent === event.event_id}>
                <summary class="details-summary">{t("processesView.recordedEvent")}</summary>
                <dl>
                  <div><dt>{t("processesView.eventId")}</dt><dd><code>{event.event_id}</code></dd></div>
                  <div><dt>{t("processesView.correlation")}</dt><dd><code>{event.correlation_id}</code></dd></div>
                  <div><dt>{t("processesView.causation")}</dt><dd><code>{event.causation_id ?? "-"}</code></dd></div>
                  <div><dt>{t("processesView.attempt")}</dt><dd>{event.attempt}</dd></div>
                </dl>
                <pre class="mono small entry-json">{JSON.stringify(event.payload, null, 2)}</pre>
              </details>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}

function eventSummary(event: ProcessEvent): string {
  for (const key of ["reason", "outcome", "decision", "terminal_outcome", "branch"]) {
    if (event.payload[key] !== undefined) return displayValue(event.payload[key]);
  }
  return "";
}

function RenderedProcess({ view, compactHeader = false }: { readonly view: RenderedProcessView; readonly compactHeader?: boolean }) {
  return (
    <div class="stack process-domain-view">
      <header class={compactHeader ? "process-section-heading" : "process-view-header"}>
        <div><span class="eyebrow">{view.process.workflow_ref}</span><h2>{view.name}</h2><p class="muted">{view.description}</p></div>
        {!compactHeader ? <div class="process-view-status"><StatusPill kind={processTone(view.process.status)} label={view.process.status} /><span class="mono">{view.process.current_step || t("processesView.terminal")}</span></div> : null}
      </header>
      <div class="process-region-grid">
        {view.regions.map((region) => (
          <RenderedRegion key={region.id} span={region.column_span}>
            <div class="process-widget-grid">
              {region.report.widgets.map((widget) => <ProcessWidget key={widget.id} widget={widget} />)}
            </div>
          </RenderedRegion>
        ))}
      </div>
    </div>
  );
}
