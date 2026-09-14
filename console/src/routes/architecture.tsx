import { useEffect, useRef, useState } from "preact/hooks";
import { isOptionalOperatorApiUnavailable, OperatorApiError, type OperatorApiClient } from "../api";
import {
  architectureHrefWithRouteState,
  architecturePresentationModeFromHash,
  architectureViewFromHash,
  selectedResourceIdFromHash,
  type ArchitecturePresentationMode,
  type InventoryGraphResponse,
  type InventoryResource,
} from "../components/architecture-map.model";
import { AsyncBoundary, PageHeader, type AsyncState } from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import { navigate, replaceRouteState } from "../router";
import { ArchitectureWorkbench } from "./architecture-workbench";
import { t } from "./i18n/architecture";

interface Props {
  readonly client: OperatorApiClient;
}

export function architectureResourceExists(
  resources: readonly Pick<InventoryResource, "id">[],
  requestedId: string | null,
): boolean {
  return requestedId === null || resources.some((resource) => resource.id === requestedId);
}

export function architectureViewExists(
  graph: Pick<InventoryGraphResponse, "active_view" | "views">,
  requestedView: string | null,
): boolean {
  if (requestedView === null) return true;
  if (graph.active_view === requestedView) return true;
  return graph.views?.some((view) => view.id === requestedView) ?? false;
}

export function architectureSourceLabel(source?: string): string {
  if (!source) return t("sourceUnavailable");
  if (source === "azure-cli-local") return t("azureCliInventory");
  return source.replaceAll(/[._-]+/g, " ").replace(/^./, (character) => character.toUpperCase());
}

export function architectureContextRecords(
  graph: Pick<InventoryGraphResponse, "resources" | "links">,
  selected: InventoryResource | null,
) {
  return {
    resources: graph.resources.map((resource) => ({
      id: resource.id,
      type: resource.type,
      status: resource.status,
      parent_id: resource.parent_id ?? null,
    })),
    links: graph.links.map((link) => ({
      source: link.source,
      target: link.target,
      type: link.type,
    })),
    selected_resource: selected
      ? [{
          id: selected.id,
          name: selected.name,
          type: selected.type,
          status: selected.status,
          parent_id: selected.parent_id ?? null,
        }]
      : [],
  };
}

export async function loadArchitectureGraph(
  client: Pick<OperatorApiClient, "panel">,
  requestedView: string | null,
): Promise<InventoryGraphResponse> {
  const params = {
    depth: "4",
    include: "contains,attached_to,depends_on,peered_with,runtime_calls",
  };
  if (requestedView === null) {
    return client.panel<InventoryGraphResponse>("/inventory/graph", params);
  }
  try {
    return await client.panel<InventoryGraphResponse>("/inventory/graph", {
      ...params,
      scope: requestedView,
    });
  } catch (error) {
    if (!(error instanceof OperatorApiError) || error.status !== 404) throw error;
    return client.panel<InventoryGraphResponse>("/inventory/graph", params);
  }
}

export function architectureCacheRefreshPending(graph: InventoryGraphResponse): boolean {
  return graph.cache?.status === "refreshing" || graph.cache?.status === "stale";
}

export function architectureCachePollDelay(attempt: number): number {
  return Math.min(30_000, 2_000 * 2 ** Math.min(Math.max(0, attempt), 4));
}

export function ArchitectureRoute({ client }: Props) {
  const [state, setState] = useState<AsyncState<InventoryGraphResponse>>({ status: "loading" });
  const [selectedId, setSelectedId] = useState<string | null>(
    () => selectedResourceIdFromHash(window.location.search),
  );
  const [viewScope, setViewScope] = useState<string | null>(
    () => architectureViewFromHash(window.location.search),
  );
  const [mode, setMode] = useState<ArchitecturePresentationMode>(
    () => architecturePresentationModeFromHash(window.location.search),
  );
  const cachePollAttemptRef = useRef(0);

  useEffect(() => {
    const syncRoute = () => {
      setSelectedId(selectedResourceIdFromHash(window.location.search));
      setViewScope(architectureViewFromHash(window.location.search));
      setMode(architecturePresentationModeFromHash(window.location.search));
    };
    window.addEventListener("popstate", syncRoute);
    window.addEventListener("fdai:route-changed", syncRoute);
    return () => {
      window.removeEventListener("popstate", syncRoute);
      window.removeEventListener("fdai:route-changed", syncRoute);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    cachePollAttemptRef.current = 0;
    setState({ status: "loading" });
    loadArchitectureGraph(client, viewScope).then(
      (data) => {
        if (!cancelled) setState({ status: "ready", data });
      },
      (error: unknown) => {
        if (cancelled) return;
        const message = error instanceof Error ? error.message : String(error);
        setState(isOptionalOperatorApiUnavailable(error)
          ? { status: "unavailable", message: t("graphUnavailable") }
          : { status: "error", message });
      },
    );
    return () => {
      cancelled = true;
    };
  }, [client, viewScope]);

  useEffect(() => {
    if (state.status !== "ready" || !architectureCacheRefreshPending(state.data)) return;
    let cancelled = false;
    let timer: number | undefined;
    const schedule = () => {
      timer = window.setTimeout(() => {
        loadArchitectureGraph(client, viewScope).then(
          (data) => {
            if (cancelled) return;
            cachePollAttemptRef.current = architectureCacheRefreshPending(data)
              ? cachePollAttemptRef.current + 1
              : 0;
            setState({ status: "ready", data });
          },
          () => {
            if (cancelled) return;
            cachePollAttemptRef.current += 1;
            schedule();
          },
        );
      }, architectureCachePollDelay(cachePollAttemptRef.current));
    };
    schedule();
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [client, state, viewScope]);

  const selectResource = (resource: InventoryResource | null): void => {
    setSelectedId(resource?.id ?? null);
    replaceRouteState(currentArchitectureHref(resource?.id, viewScope, mode));
  };

  const changeMode = (nextMode: ArchitecturePresentationMode): void => {
    setMode(nextMode);
    replaceRouteState(currentArchitectureHref(selectedId ?? undefined, viewScope, nextMode));
  };

  return (
    <div class="stack architecture-route">
      <PageHeader title={t("route.architecture")} subtitle={t("subtitle")} />
      <AsyncBoundary state={state} resourceLabel={t("loadingLabel")}>
        {(data) => (
          <ArchitectureReady
            graph={data}
            requestedView={viewScope}
            selectedId={selectedId}
            mode={mode}
            onSelect={selectResource}
            onViewScopeChange={(scope) => {
              setSelectedId(null);
              setViewScope(scope);
              setMode("topology");
              navigate(currentArchitectureHref(undefined, scope, "topology"));
            }}
            onModeChange={changeMode}
          />
        )}
      </AsyncBoundary>
    </div>
  );
}

function ArchitectureReady({
  graph,
  requestedView,
  selectedId,
  mode,
  onSelect,
  onViewScopeChange,
  onModeChange,
}: {
  readonly graph: InventoryGraphResponse;
  readonly requestedView: string | null;
  readonly selectedId: string | null;
  readonly mode: ArchitecturePresentationMode;
  readonly onSelect: (resource: InventoryResource | null) => void;
  readonly onViewScopeChange: (scope: string) => void;
  readonly onModeChange: (mode: ArchitecturePresentationMode) => void;
}) {
  const selected = graph.resources.find((resource) => resource.id === selectedId) ?? null;
  usePublishViewContext(
    () => ({
      routeId: "architecture",
      routeLabel: t("route.architecture"),
      purpose: t("contextPurpose"),
      glossary: composeGlossary([TERMS.blastRadius]),
      headline: t("contextHeadline", {
        resources: graph.resources.length,
        links: graph.links.length,
        freshness: graph.freshness,
      }),
      capturedAt: graph.snapshot_at,
      facts: [
        { key: "snapshot_freshness", value: graph.freshness, group: "inventory" },
        { key: "source", value: graph.source ?? "inventory", group: "inventory" },
        { key: "realtime_pending_changes", value: graph.realtime?.pending_changes ?? 0, group: "inventory" },
        { key: "realtime_latest_at", value: graph.realtime?.latest_at ?? "none", group: "inventory" },
        { key: "truncated", value: graph.truncated, group: "inventory" },
        { key: "presentation_mode", value: mode, group: "presentation" },
      ],
      records: architectureContextRecords(graph, selected),
    }),
    [graph, mode, selected],
  );

  if (!architectureViewExists(graph, requestedView) && requestedView !== null) {
    return (
      <div class="state-block state-unavailable" role="alert">
        <span class="state-icon" aria-hidden="true">?</span>
        <div>
          <strong>{t("viewUnavailable")}</strong>
          <p>{t("viewNotRegistered", { view: requestedView })}</p>
          {(graph.views ?? []).length > 0 ? (
            <nav class="analytics-links" aria-label={t("availableViews")}>
              {(graph.views ?? []).map((view) => (
                <a key={view.id} href={currentArchitectureHref(undefined, view.id, "topology")}>{view.label}</a>
              ))}
            </nav>
          ) : (
            <a href={currentArchitectureHref(undefined, null, "topology")}>{t("openDefault")}</a>
          )}
        </div>
      </div>
    );
  }

  if (!architectureResourceExists(graph.resources, selectedId) && selectedId) {
    return (
      <div class="state-block state-unavailable" role="alert">
        <span class="state-icon" aria-hidden="true">?</span>
        <div>
          <strong>{t("resourceUnavailable")}</strong>
          <p>{t("resourceNotPresent", { resource: selectedId })}</p>
          <a href={currentArchitectureHref(undefined, graph.active_view, "topology")}>{t("openCurrent")}</a>
        </div>
      </div>
    );
  }

  return (
    <ArchitectureWorkbench
      graph={graph}
      selectedId={selectedId}
      mode={mode}
      sourceLabel={architectureSourceLabel(graph.source)}
      onSelect={onSelect}
      onViewScopeChange={onViewScopeChange}
      onModeChange={onModeChange}
    />
  );
}

export function formatAge(timestamp: string, now = Date.now()): string {
  const seconds = Math.max(0, Math.round((now - Date.parse(timestamp)) / 1000));
  if (seconds < 60) return t("age.seconds", { count: seconds });
  if (seconds < 3600) return t("age.minutes", { count: Math.round(seconds / 60) });
  return t("age.hours", { count: Math.round(seconds / 3600) });
}

function currentArchitectureHref(
  resourceId: string | undefined,
  viewId: string | null | undefined,
  mode: ArchitecturePresentationMode,
): string {
  return architectureHrefWithRouteState(resourceId, viewId, mode, window.location.search);
}
