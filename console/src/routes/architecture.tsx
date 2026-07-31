import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { isOptionalReadApiUnavailable, ReadApiError, type ReadApiClient } from "../api";
import { ArchitectureInspector } from "../components/architecture-inspector";
import { ArchitectureMap, type ArchitectureMapHandle } from "../components/architecture-map";
import { ArchitectureOverviewPanel } from "../components/architecture-overview-panel";
import { architectureCanvasHeight } from "../components/architecture-map.geometry";
import { layoutArchitecturePresentation } from "../components/architecture-map-layout";
import { ArchitectureRelationIndex } from "../components/architecture-relation-index";
import {
  DEFAULT_ARCHITECTURE_CAMERA_VIEW,
  DEFAULT_ARCHITECTURE_DISPLAY_OPTIONS,
  architectureHref,
  architectureViewFromHash,
  selectedResourceIdFromHash,
  type ArchitectureCameraView,
  type ArchitectureDisplayOptions,
  type InventoryGraphResponse,
  type InventoryResource,
} from "../components/architecture-map.model";
import { AsyncBoundary, PageHeader, type AsyncState } from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import { navigate, replaceRouteState } from "../router";
import { t } from "./i18n/architecture";

interface Props { readonly client: ReadApiClient }

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
  client: Pick<ReadApiClient, "panel">,
  requestedView: string | null,
): Promise<InventoryGraphResponse> {
  const params = { depth: "4", include: "contains,attached_to,depends_on" };
  if (requestedView === null) {
    return client.panel<InventoryGraphResponse>("/inventory/graph", params);
  }
  try {
    return await client.panel<InventoryGraphResponse>("/inventory/graph", {
      ...params,
      scope: requestedView,
    });
  } catch (error) {
    if (!(error instanceof ReadApiError) || error.status !== 404) throw error;
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
  const [selectedId, setSelectedId] = useState<string | null>(() => selectedResourceIdFromHash(window.location.search));
  const [viewScope, setViewScope] = useState<string | null>(() => architectureViewFromHash(window.location.search));
  const [cameraView, setCameraView] = useState<ArchitectureCameraView>(
    DEFAULT_ARCHITECTURE_CAMERA_VIEW,
  );
  const [zoomPercent, setZoomPercent] = useState(100);
  const [displayOptions, setDisplayOptions] = useState<ArchitectureDisplayOptions>({
    ...DEFAULT_ARCHITECTURE_DISPLAY_OPTIONS,
  });
  const mapRef = useRef<ArchitectureMapHandle>(null);
  const cachePollAttemptRef = useRef(0);

  useEffect(() => {
    const syncRoute = () => {
      setSelectedId(selectedResourceIdFromHash(window.location.search));
      setViewScope(architectureViewFromHash(window.location.search));
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
      (data) => { if (!cancelled) setState({ status: "ready", data }); },
      (error: unknown) => {
        if (cancelled) return;
        const message = error instanceof Error ? error.message : String(error);
        setState(isOptionalReadApiUnavailable(error)
          ? { status: "unavailable", message: t("graphUnavailable") }
          : { status: "error", message });
      },
    );
    return () => { cancelled = true; };
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

  function selectResource(resource: InventoryResource | null): void {
    setSelectedId(resource?.id ?? null);
    replaceRouteState(architectureHref(resource?.id, viewScope));
  }

  function changeView(view: ArchitectureCameraView): void {
    setCameraView(view);
    mapRef.current?.setView(view);
  }

  function toggleDisplay(key: keyof ArchitectureDisplayOptions): void {
    setDisplayOptions((previous) => ({ ...previous, [key]: !previous[key] }));
  }

  return (
    <div class="stack architecture-route">
      <PageHeader
        title={t("route.architecture")}
        subtitle={t("subtitle")}
      />
      <AsyncBoundary state={state} resourceLabel={t("loadingLabel")}>
        {(data) => (
          <ArchitectureBody
            graph={data}
            requestedView={viewScope}
            selectedId={selectedId}
            onSelect={selectResource}
            onViewScopeChange={(scope) => {
              mapRef.current?.setView(DEFAULT_ARCHITECTURE_CAMERA_VIEW);
              setCameraView(DEFAULT_ARCHITECTURE_CAMERA_VIEW);
              setSelectedId(null);
              setViewScope(scope);
              navigate(architectureHref(undefined, scope));
            }}
            mapRef={mapRef}
            cameraView={cameraView}
            onCameraViewChange={changeView}
            zoomPercent={zoomPercent}
            onZoomChange={setZoomPercent}
            displayOptions={displayOptions}
            onToggleDisplay={toggleDisplay}
          />
        )}
      </AsyncBoundary>
    </div>
  );
}

function ArchitectureBody({
  graph,
  requestedView,
  selectedId,
  onSelect,
  onViewScopeChange,
  mapRef,
  cameraView,
  onCameraViewChange,
  zoomPercent,
  onZoomChange,
  displayOptions,
  onToggleDisplay,
}: {
  readonly graph: InventoryGraphResponse;
  readonly requestedView: string | null;
  readonly selectedId: string | null;
  readonly onSelect: (resource: InventoryResource | null) => void;
  readonly onViewScopeChange: (scope: string) => void;
  readonly mapRef: { current: ArchitectureMapHandle | null };
  readonly cameraView: ArchitectureCameraView;
  readonly onCameraViewChange: (view: ArchitectureCameraView) => void;
  readonly zoomPercent: number;
  readonly onZoomChange: (percent: number) => void;
  readonly displayOptions: ArchitectureDisplayOptions;
  readonly onToggleDisplay: (key: keyof ArchitectureDisplayOptions) => void;
}) {
  const presentedGraph = useMemo(
    () => layoutArchitecturePresentation(graph, selectedId),
    [graph, selectedId],
  );
  const visibleSelectedId = architectureResourceExists(presentedGraph.resources, selectedId)
    ? selectedId
    : null;
  const selected = presentedGraph.resources.find((resource) => resource.id === visibleSelectedId) ?? null;
  const requestedViewExists = architectureViewExists(graph, requestedView);
  const requestedResourceExists = architectureResourceExists(graph.resources, selectedId);
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
      ],
      records: architectureContextRecords(graph, selected),
    }),
    [graph, selected],
  );
  if (!requestedViewExists && requestedView !== null) {
    return (
      <div class="state-block state-unavailable" role="alert">
        <span class="state-icon" aria-hidden="true">?</span>
        <div>
          <strong>{t("viewUnavailable")}</strong>
          <p>{t("viewNotRegistered", { view: requestedView })}</p>
          {(graph.views ?? []).length > 0 ? (
            <nav class="analytics-links" aria-label={t("availableViews")}>
              {(graph.views ?? []).map((view) => (
                <a key={view.id} href={architectureHref(undefined, view.id)}>{view.label}</a>
              ))}
            </nav>
          ) : (
            <a href={architectureHref()}>{t("openDefault")}</a>
          )}
        </div>
      </div>
    );
  }
  if (!requestedResourceExists && selectedId) {
    return (
      <div class="state-block state-unavailable" role="alert">
        <span class="state-icon" aria-hidden="true">?</span>
        <div>
          <strong>{t("resourceUnavailable")}</strong>
          <p>{t("resourceNotPresent", { resource: selectedId })}</p>
          <a href={architectureHref(undefined, graph.active_view)}>{t("openCurrent")}</a>
        </div>
      </div>
    );
  }
  return (
    <div class="architecture-workspace">
      <div class={`architecture-stage${selected ? " has-selection" : ""}`}>
        <div
          class="architecture-canvas-shell"
          style={`--architecture-canvas-height: ${architectureCanvasHeight(presentedGraph)}px`}
        >
          <p id="architecture-map-description" class="sr-only">
            {t("mapDescription", {
              resources: presentedGraph.resources.length,
              links: presentedGraph.links.length,
            })}
          </p>
          <ArchitectureMap
            ref={mapRef}
            graph={presentedGraph}
            selectedId={visibleSelectedId}
            onSelect={onSelect}
            options={displayOptions}
            onZoomChange={onZoomChange}
            descriptionId="architecture-map-description"
          />
          <ArchitectureOverviewPanel
            graph={graph}
            onViewScopeChange={onViewScopeChange}
          />
          <div class="architecture-zoom-controls" role="group" aria-label={t("zoomControls")}>
            <button type="button" onClick={() => mapRef.current?.zoomIn()} aria-label={t("zoomIn")}>+</button>
            <output aria-label={t("zoomLevel")} aria-live="polite">{zoomPercent}%</output>
            <button type="button" onClick={() => mapRef.current?.zoomOut()} aria-label={t("zoomOut")}>-</button>
            <button type="button" onClick={() => mapRef.current?.fit()} aria-label={t("fitMap")}>{t("fit")}</button>
          </div>
          <div class="architecture-edge-legend" aria-label={t("relationshipLegend")}>
            <span><i class="is-dependency" aria-hidden="true" />{t("relationship.dependsOn")}</span>
            <span><i class="is-attachment" aria-hidden="true" />{t("relationship.attachedTo")}</span>
            <span><i class="is-boundary" aria-hidden="true" />{t("relationship.boundary")}</span>
          </div>
        </div>
        <ArchitectureInspector
          graph={graph}
          selected={selected}
          onSelect={onSelect}
          cameraView={cameraView}
          onCameraViewChange={onCameraViewChange}
          displayOptions={displayOptions}
          onToggleDisplay={onToggleDisplay}
        />
      </div>
      <ArchitectureRelationIndex graph={presentedGraph} onSelect={onSelect} />
    </div>
  );
}

export function formatAge(timestamp: string, now = Date.now()): string {
  const seconds = Math.max(0, Math.round((now - Date.parse(timestamp)) / 1000));
  if (seconds < 60) return t("age.seconds", { count: seconds });
  if (seconds < 3600) return t("age.minutes", { count: Math.round(seconds / 60) });
  return t("age.hours", { count: Math.round(seconds / 3600) });
}
