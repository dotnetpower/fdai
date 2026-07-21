import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { isOptionalReadApiUnavailable, ReadApiError, type ReadApiClient } from "../api";
import { ArchitectureInspector } from "../components/architecture-inspector";
import { ArchitectureMap, type ArchitectureMapHandle } from "../components/architecture-map";
import { ArchitectureRelationIndex } from "../components/architecture-relation-index";
import {
  ARCHITECTURE_LAYERS,
  architectureHref,
  architectureViewFromHash,
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
import { t } from "../i18n";
import { navigate, replaceRouteState } from "../router";

interface Props { readonly client: ReadApiClient }

const LAYER_LABELS: Readonly<Record<ArchitectureLayer, string>> = {
  scope: "Scope",
  network: "Network",
  security: "Security",
  runtime: "Runtime",
  data: "Data",
  messaging: "Messaging",
  observability: "Observability",
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
  if (!source) return "Source unavailable";
  if (source === "azure-cli-local") return "Azure CLI inventory";
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

export function ArchitectureRoute({ client }: Props) {
  const [state, setState] = useState<AsyncState<InventoryGraphResponse>>({ status: "loading" });
  const [selectedId, setSelectedId] = useState<string | null>(() => selectedResourceIdFromHash(window.location.search));
  const [visibleLayers, setVisibleLayers] = useState<Set<ArchitectureLayer>>(new Set(ARCHITECTURE_LAYERS));
  const [viewScope, setViewScope] = useState<string | null>(() => architectureViewFromHash(window.location.search));
  const [cameraView, setCameraView] = useState<ArchitectureCameraView>("top");
  const [zoomPercent, setZoomPercent] = useState(100);
  const [displayOptions, setDisplayOptions] = useState<ArchitectureDisplayOptions>({
    showConnections: true,
    showReflections: false,
    showLabels: true,
    showGrid: false,
  });
  const mapRef = useRef<ArchitectureMapHandle>(null);

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
    setState({ status: "loading" });
    loadArchitectureGraph(client, viewScope).then(
      (data) => { if (!cancelled) setState({ status: "ready", data }); },
      (error: unknown) => {
        if (cancelled) return;
        const message = error instanceof Error ? error.message : String(error);
        setState(isOptionalReadApiUnavailable(error)
          ? { status: "unavailable", message: "The inventory graph is not wired on this deployment." }
          : { status: "error", message });
      },
    );
    return () => { cancelled = true; };
  }, [client, viewScope]);

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
        subtitle="Deployed resources, containment boundaries, and runtime dependencies from the read-only inventory projection."
      />
      <AsyncBoundary state={state} resourceLabel="inventory graph">
        {(data) => (
          <ArchitectureBody
            graph={data}
            requestedView={viewScope}
            selectedId={selectedId}
            visibleLayers={visibleLayers}
            onSelect={selectResource}
            onToggleLayer={toggleLayer}
            onViewScopeChange={(scope) => {
              mapRef.current?.setView("top");
              setCameraView("top");
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
  const filtered = useMemo(
    () => graphSubset(graph, visibleLayers),
    [graph, visibleLayers],
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
      routeLabel: "Architecture",
      purpose: "The deployed resource inventory, scope containment, and runtime dependency graph. Read-only.",
      glossary: composeGlossary([TERMS.blastRadius]),
      headline: `${graph.resources.length} resources - ${graph.links.length} links - ${graph.freshness}`,
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
          <strong>Architecture view unavailable</strong>
          <p><code>{requestedView}</code> is not registered in this inventory projection.</p>
          {(graph.views ?? []).length > 0 ? (
            <nav class="analytics-links" aria-label="Available architecture views">
              {(graph.views ?? []).map((view) => (
                <a key={view.id} href={architectureHref(undefined, view.id)}>{view.label}</a>
              ))}
            </nav>
          ) : (
            <a href={architectureHref()}>Open default architecture</a>
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
          <strong>Resource unavailable</strong>
          <p><code>{selectedId}</code> is not present in this architecture view.</p>
          <a href={architectureHref(undefined, graph.active_view)}>Open current architecture</a>
        </div>
      </div>
    );
  }
  return (
    <div class="architecture-workspace">
      <div class="architecture-toolbar">
        <label class="architecture-view-picker">
          <span>Scope</span>
          <select
            value={graph.active_view ?? graph.views?.[0]?.id ?? ""}
            aria-describedby="architecture-view-description"
            onChange={(event) => onViewScopeChange((event.target as HTMLSelectElement).value)}
          >
            {(["fdai", "service", "resource_group"] as const).map((kind) => {
              const views = (graph.views ?? []).filter((view) => view.kind === kind);
              if (views.length === 0) return null;
              return (
                <optgroup label={kind === "fdai" ? "FDAI control planes" : kind === "service" ? "Services" : "Resource groups"}>
                  {views.map((view) => <option value={view.id}>{view.label}</option>)}
                </optgroup>
              );
            })}
          </select>
          <small id="architecture-view-description">
            {graph.views?.find((view) => view.id === graph.active_view)?.description}
          </small>
        </label>
        <div class="architecture-provenance" aria-label="Inventory provenance">
          <div class={`inventory-freshness is-${graph.freshness}`}>
            <span aria-hidden="true" />Snapshot {graph.freshness} <small>{formatAge(graph.snapshot_at, now)}</small>
          </div>
          <dl>
            <div><dt>Source</dt><dd>{architectureSourceLabel(graph.source)}</dd></div>
            <div><dt>Pending changes</dt><dd>{graph.realtime?.pending_changes ?? 0}</dd></div>
          </dl>
          {(graph.realtime?.pending_changes ?? 0) > 0 ? (
            <span class="architecture-pending-note">Inventory refresh in progress</span>
          ) : null}
        </div>
      </div>
      {graph.truncated ? (
        <div class="architecture-partial-notice" role="status">
          <strong>Partial inventory graph</strong>
          <span>The server limited this snapshot. Counts and relationships describe only the returned records.</span>
        </div>
      ) : null}
      <section class="architecture-summary" aria-label="Architecture summary">
        <div><strong>{graph.resources.length}</strong><span>Resources</span></div>
        <div><strong>{dependencyCount}</strong><span>Dependencies</span></div>
        <div><strong>{boundaryCount}</strong><span>Boundaries</span></div>
        <div><strong>{unavailableStatusCount}</strong><span>Status unavailable</span></div>
      </section>
      <div class="architecture-layer-bar" role="group" aria-label="Visible architecture layers">
        {populatedLayers.map((layer) => (
          <button
            type="button"
            class={visibleLayers.has(layer) ? "is-active" : ""}
            aria-pressed={visibleLayers.has(layer)}
            onClick={() => onToggleLayer(layer)}
          >
            <span>{LAYER_LABELS[layer]}</span>
            <small>{layerCounts.get(layer)}</small>
          </button>
        ))}
        <output class="architecture-filter-summary" aria-live="polite">
          Showing {filtered.resources.length} of {graph.resources.length} resources and {filtered.links.length} of {graph.links.length} relationships
        </output>
      </div>
      <div class={`architecture-stage${selected ? " has-selection" : ""}`}>
        <div class="architecture-canvas-shell">
          <p id="architecture-map-description" class="sr-only">
            Read-only map of {filtered.resources.length} visible resources and {filtered.links.length} reported relationships. Use the resource selector or the resource and relationship index for keyboard navigation.
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
          <div class="architecture-zoom-controls" role="group" aria-label="Map zoom controls">
            <button type="button" onClick={() => mapRef.current?.zoomIn()} aria-label="Zoom in">+</button>
            <output aria-label="Zoom level" aria-live="polite">{zoomPercent}%</output>
            <button type="button" onClick={() => mapRef.current?.zoomOut()} aria-label="Zoom out">-</button>
            <button type="button" onClick={() => mapRef.current?.fit()} aria-label="Fit map">Fit</button>
          </div>
          <div class="architecture-edge-legend" aria-label="Relationship legend">
            <span><i class="is-dependency" aria-hidden="true" />Depends on</span>
            <span><i class="is-attachment" aria-hidden="true" />Attached to</span>
            <span><i class="is-boundary" aria-hidden="true" />Boundary</span>
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
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  return `${Math.round(seconds / 3600)}h ago`;
}
