import { useEffect, useState } from "preact/hooks";
import type { ReadApiClient } from "../api";
import { AsyncBoundary, EmptyState, PageHeader, StatusPill, type AsyncState } from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import { t } from "../i18n";
import { ProcessWidget, RenderedRegion } from "./process-view-renderer";
import {
  decodeProcessList,
  decodeRenderedProcessView,
  defaultProcessId,
  processHref,
  processIdFromHash,
  processListFailure,
  processTone,
  type ProcessListResponse,
  type ProcessSummary,
  type RenderedProcessView,
} from "./processes.model";

interface Props { readonly client: ReadApiClient }

export function ProcessesRoute({ client }: Props) {
  const [listState, setListState] = useState<AsyncState<ProcessListResponse>>({ status: "loading" });
  const [selectedId, setSelectedId] = useState<string | null>(() => processIdFromHash(window.location.hash));
  const [viewState, setViewState] = useState<AsyncState<RenderedProcessView>>({ status: "idle" });

  useEffect(() => {
    const sync = () => setSelectedId(processIdFromHash(window.location.hash));
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
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
          return;
        }
        setListState({ status: "ready", data });
        const defaultId = defaultProcessId(data.items, window.location.hash);
        if (!processIdFromHash(window.location.hash) && defaultId) {
          window.history.replaceState(window.history.state, "", processHref(defaultId));
          setSelectedId(defaultId);
        }
      },
      (error: unknown) => {
        if (cancelled) return;
        setListState(processListFailure(error));
      },
    );
    return () => { cancelled = true; };
  }, [client]);

  useEffect(() => {
    if (!selectedId) { setViewState({ status: "idle" }); return; }
    if (listState.status === "ready") {
      const selected = listState.data.items.find((item) => item.id === selectedId);
      if (selected && !selected.has_view) {
        setViewState({ status: "unavailable", message: "No dynamic view is registered for this workflow." });
        return;
      }
    }
    let cancelled = false;
    setViewState({ status: "loading" });
    client.panel<unknown>(`/views/process/${encodeURIComponent(selectedId)}`).then(
      (payload) => {
        if (cancelled) return;
        try {
          setViewState({ status: "ready", data: decodeRenderedProcessView(payload) });
        } catch (error) {
          setViewState({ status: "error", message: error instanceof Error ? error.message : String(error) });
        }
      },
      (error: unknown) => { if (!cancelled) setViewState({ status: "error", message: error instanceof Error ? error.message : String(error) }); },
    );
    return () => { cancelled = true; };
  }, [client, selectedId, listState]);

  return (
    <div class="stack process-route">
      <PageHeader title={t("route.processes")} subtitle="Workflow runtime state rendered from ontology projections and declarative ViewSpecs." />
      <AsyncBoundary state={listState} resourceLabel="processes">
        {(data) => <ProcessWorkspace processes={data.items} selectedId={selectedId} viewState={viewState} />}
      </AsyncBoundary>
    </div>
  );
}

function ProcessWorkspace({ processes, selectedId, viewState }: {
  readonly processes: readonly ProcessSummary[];
  readonly selectedId: string | null;
  readonly viewState: AsyncState<RenderedProcessView>;
}) {
  const selected = processes.find((item) => item.id === selectedId) ?? null;
  usePublishViewContext(
    () => ({
      routeId: "processes",
      routeLabel: "Processes",
      purpose: "Read-only workflow Process snapshots and ontology-backed dynamic views.",
      glossary: composeGlossary([TERMS.process, TERMS.viewSpec]),
      headline: `${processes.length} process(es)${selected ? ` - ${selected.workflow_ref}: ${selected.status}` : ""}`,
      capturedAt: selected?.updated_at ?? new Date().toISOString(),
      facts: [
        { key: "process_count", value: processes.length, group: "process" },
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
    [processes, selected],
  );
  if (processes.length === 0) {
    return <EmptyState title="No workflow processes" body="Process runs appear here after the workflow runtime records them." />;
  }
  const hasRenderableProcess = processes.some((process) => process.has_view);
  return (
    <div class="process-workspace">
      <aside class="process-list" aria-label="Workflow processes">
        {processes.map((process) => process.has_view ? (
          <a key={process.id} href={processHref(process.id)} class={`process-list-entry ${process.id === selectedId ? "is-active" : ""}`}>
            <ProcessListLabel process={process} />
          </a>
        ) : (
          <div key={process.id} class="process-list-entry is-disabled" aria-disabled="true">
            <ProcessListLabel process={process} unavailable />
          </div>
        ))}
      </aside>
      <section class="process-view-stage">
        <AsyncBoundary state={viewState} resourceLabel="process view" idle={<p class="muted">{hasRenderableProcess ? "Select a process." : "No dynamic process views are available."}</p>}>
          {(view) => <RenderedProcess view={view} />}
        </AsyncBoundary>
      </section>
    </div>
  );
}

function ProcessListLabel({ process, unavailable = false }: {
  readonly process: ProcessSummary;
  readonly unavailable?: boolean;
}) {
  return (
    <>
      <div>
        <strong>{process.workflow_ref}</strong>
        <small>{process.current_step || "terminal"}{unavailable ? " - no view" : ""}</small>
      </div>
      <StatusPill kind={processTone(process.status)} label={process.status} />
    </>
  );
}

function RenderedProcess({ view }: { readonly view: RenderedProcessView }) {
  return (
    <div class="stack">
      <header class="process-view-header">
        <div><span class="eyebrow">{view.process.workflow_ref}</span><h2>{view.name}</h2><p class="muted">{view.description}</p></div>
        <div class="process-view-status"><StatusPill kind={processTone(view.process.status)} label={view.process.status} /><span class="mono">{view.process.current_step || "terminal"}</span></div>
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
