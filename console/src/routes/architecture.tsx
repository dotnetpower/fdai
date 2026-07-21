import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { isOptionalReadApiUnavailable, ReadApiError, type ReadApiClient } from "../api";
import { ArchitectureInspector } from "../components/architecture-inspector";
import { ArchitectureMap, type ArchitectureMapHandle } from "../components/architecture-map";
import { ArchitectureRelationIndex } from "../components/architecture-relation-index";
import {
  ARCHITECTURE_LAYERS,
  DEFAULT_ARCHITECTURE_CAMERA_VIEW,
  architectureHref,
  architectureViewFromHash,
  constrainGraph,
  graphSubset,
  isRegion,
  layerOf,
  relatedResourceIds,
  selectedResourceIdFromHash,
  type ArchitectureCameraView,
  type ArchitectureDisplayOptions,
  type ArchitectureLayer,
  type InventoryGraphResponse,
  type InventoryResource,
} from "../components/architecture-map.model";
import { AsyncBoundary, PageHeader, type AsyncState } from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import { navigate, replaceRouteState } from "../router";
import { t } from "./i18n/architecture";

interface Props { readonly client: ReadApiClient }

const LAYER_LABELS: Readonly<Record<ArchitectureLayer, string>> = {
  scope: "layer.scope",
  network: "layer.network",
  security: "layer.security",
  runtime: "layer.runtime",
  data: "layer.data",
  messaging: "layer.messaging",
  observability: "layer.observability",
};

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
  const [visibleLayers, setVisibleLayers] = useState<Set<ArchitectureLayer>>(new Set(ARCHITECTURE_LAYERS));
  const [viewScope, setViewScope] = useState<string | null>(() => architectureViewFromHash(window.location.search));
  const [cameraView, setCameraView] = useState<ArchitectureCameraView>(
    DEFAULT_ARCHITECTURE_CAMERA_VIEW,
  );
  const [zoomPercent, setZoomPercent] = useState(100);
  const [displayOptions, setDisplayOptions] = useState<ArchitectureDisplayOptions>({
    showConnections: true,
    showReflections: false,
    showLabels: true,
    showGrid: false,
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

  function toggleLayer(layer: ArchitectureLayer): void {
    setVisibleLayers((previous) => {
      const next = new Set(previous);
      if (next.has(layer)) next.delete(layer); else next.add(layer);
      return next;
    });
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
            visibleLayers={visibleLayers}
            onSelect={selectResource}
            onToggleLayer={toggleLayer}
            onViewScopeChange={(scope) => {
              mapRef.current?.setView(DEFAULT_ARCHITECTURE_CAMERA_VIEW);
              setCameraView(DEFAULT_ARCHITECTURE_CAMERA_VIEW);
              setSelectedId(null);
              setVisibleLayers(new Set(ARCHITECTURE_LAYERS));
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
  visibleLayers,
  onSelect,
  onToggleLayer,
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
  readonly visibleLayers: ReadonlySet<ArchitectureLayer>;
  readonly onSelect: (resource: InventoryResource | null) => void;
  readonly onToggleLayer: (layer: ArchitectureLayer) => void;
  readonly onViewScopeChange: (scope: string) => void;
  readonly mapRef: { current: ArchitectureMapHandle | null };
  readonly cameraView: ArchitectureCameraView;
  readonly onCameraViewChange: (view: ArchitectureCameraView) => void;
  readonly zoomPercent: number;
  readonly onZoomChange: (percent: number) => void;
  readonly displayOptions: ArchitectureDisplayOptions;
  readonly onToggleDisplay: (key: keyof ArchitectureDisplayOptions) => void;
}) {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const ageMs = Math.max(0, now - Date.parse(graph.snapshot_at));
    const timer = window.setTimeout(
      () => setNow(Date.now()),
      ageMs < 60_000 ? 1_000 : 60_000,
    );
    return () => window.clearTimeout(timer);
  }, [graph.snapshot_at, now]);
  const laidOutGraph = useMemo(() => constrainGraph(graph), [graph]);
  const filtered = useMemo(
    () => graphSubset(laidOutGraph, visibleLayers),
    [laidOutGraph, visibleLayers],
  );
  const layerCounts = useMemo(
    () => new Map(ARCHITECTURE_LAYERS.map((layer) => [
      layer,
      graph.resources.filter((resource) => layerOf(resource) === layer).length,
    ])),
    [graph],
  );
  const visibleSelectedId = architectureResourceExists(filtered.resources, selectedId)
    ? selectedId
    : null;
  const selected = filtered.resources.find((resource) => resource.id === visibleSelectedId) ?? null;
  const highlightedIds = useMemo(
    () => relatedResourceIds(filtered, visibleSelectedId),
    [filtered, visibleSelectedId],
  );
  const requestedViewExists = architectureViewExists(graph, requestedView);
  const requestedResourceExists = architectureResourceExists(graph.resources, selectedId);
  const dependencyCount = graph.links.filter((link) => link.type !== "contains").length;
  const boundaryCount = graph.resources.filter(isRegion).length;
  const unavailableStatusCount = graph.resources.filter(
    (resource) => resource.status.trim().toLowerCase() === "unknown",
  ).length;
  const populatedLayers = ARCHITECTURE_LAYERS.filter((layer) => (layerCounts.get(layer) ?? 0) > 0);
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
      records: {
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
      },
    }),
    [graph],
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
      <div class="architecture-toolbar">
        <label class="architecture-view-picker">
          <span>{t("scope")}</span>
          <select
            value={graph.active_view ?? graph.views?.[0]?.id ?? ""}
            aria-describedby="architecture-view-description"
            onChange={(event) => onViewScopeChange((event.target as HTMLSelectElement).value)}
          >
            {(["fdai", "service", "resource_group"] as const).map((kind) => {
              const views = (graph.views ?? []).filter((view) => view.kind === kind);
              if (views.length === 0) return null;
              return (
                <optgroup label={t(kind === "fdai" ? "viewGroup.fdai" : kind === "service" ? "viewGroup.service" : "viewGroup.resourceGroup")}>
                  {views.map((view) => <option value={view.id}>{view.label}</option>)}
                </optgroup>
              );
            })}
          </select>
          <small id="architecture-view-description">
            {graph.views?.find((view) => view.id === graph.active_view)?.description}
          </small>
        </label>
        <div class="architecture-provenance" aria-label={t("inventoryProvenance")}>
          <div class={`inventory-freshness is-${graph.freshness}`}>
            <span aria-hidden="true" />{t("snapshot", { freshness: graph.freshness })} <small>{formatAge(graph.snapshot_at, now)}</small>
          </div>
          <dl>
            <div><dt>{t("source")}</dt><dd>{architectureSourceLabel(graph.source)}</dd></div>
            <div><dt>{t("pendingChanges")}</dt><dd>{graph.realtime?.pending_changes ?? 0}</dd></div>
          </dl>
          {(graph.realtime?.pending_changes ?? 0) > 0 || architectureCacheRefreshPending(graph) ? (
            <span class="architecture-pending-note">{t("refreshInProgress")}</span>
          ) : null}
        </div>
      </div>
      {graph.truncated ? (
        <div class="architecture-partial-notice" role="status">
          <strong>{t("partialTitle")}</strong>
          <span>{t("partialDescription")}</span>
        </div>
      ) : null}
      <section class="architecture-summary" aria-label={t("summary")}>
        <div><strong>{graph.resources.length}</strong><span>{t("resources")}</span></div>
        <div><strong>{dependencyCount}</strong><span>{t("dependencies")}</span></div>
        <div><strong>{boundaryCount}</strong><span>{t("boundaries")}</span></div>
        <div><strong>{unavailableStatusCount}</strong><span>{t("statusUnavailable")}</span></div>
      </section>
      <div class="architecture-layer-bar" role="group" aria-label={t("visibleLayers")}>
        {populatedLayers.map((layer) => (
          <button
            type="button"
            class={visibleLayers.has(layer) ? "is-active" : ""}
            aria-pressed={visibleLayers.has(layer)}
            onClick={() => onToggleLayer(layer)}
          >
            <span>{t(LAYER_LABELS[layer])}</span>
            <small>{layerCounts.get(layer)}</small>
          </button>
        ))}
        <output class="architecture-filter-summary" aria-live="polite">
          {t("filterSummary", {
            visibleResources: filtered.resources.length,
            totalResources: graph.resources.length,
            visibleLinks: filtered.links.length,
            totalLinks: graph.links.length,
          })}
        </output>
      </div>
      <div class={`architecture-stage${selected ? " has-selection" : ""}`}>
        <div class="architecture-canvas-shell">
          <p id="architecture-map-description" class="sr-only">
            {t("mapDescription", {
              resources: filtered.resources.length,
              links: filtered.links.length,
            })}
          </p>
          <ArchitectureMap
            ref={mapRef}
            graph={filtered}
            selectedId={visibleSelectedId}
            {...(highlightedIds ? { highlightedIds } : {})}
            onSelect={onSelect}
            options={displayOptions}
            onZoomChange={onZoomChange}
            descriptionId="architecture-map-description"
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
      <ArchitectureRelationIndex graph={filtered} onSelect={onSelect} />
    </div>
  );
}

export function formatAge(timestamp: string, now = Date.now()): string {
  const seconds = Math.max(0, Math.round((now - Date.parse(timestamp)) / 1000));
  if (seconds < 60) return t("age.seconds", { count: seconds });
  if (seconds < 3600) return t("age.minutes", { count: Math.round(seconds / 60) });
  return t("age.hours", { count: Math.round(seconds / 3600) });
}
