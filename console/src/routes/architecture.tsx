import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { isOptionalReadApiUnavailable, ReadApiError, type ReadApiClient } from "../api";
import { ArchitectureMap, type ArchitectureMapHandle } from "../components/architecture-map";
import {
  ARCHITECTURE_LAYERS,
  RESOURCE_COLOR_TOKENS,
  architectureHref,
  architectureViewFromHash,
  graphSubset,
  layerOf,
  resourceColorTokenOf,
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
import { navigate, routeHref } from "../router";

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

const CAMERA_LABELS: Readonly<Record<ArchitectureCameraView, string>> = {
  iso: "Iso",
  top: "Top",
  front: "Front",
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
  const [cameraView, setCameraView] = useState<ArchitectureCameraView>("iso");
  const [zoomPercent, setZoomPercent] = useState(100);
  const [displayOptions, setDisplayOptions] = useState<ArchitectureDisplayOptions>({
    showConnections: true,
    showReflections: true,
    showLabels: true,
    showGrid: true,
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
    navigate(architectureHref(resource?.id, viewScope));
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
              mapRef.current?.setView("iso");
              setCameraView("iso");
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
  const resourceColorTokens = useMemo(
    () => [...new Set(
      graph.resources
        .map(resourceColorTokenOf),
    )],
    [graph],
  );
  const selected = graph.resources.find((resource) => resource.id === selectedId) ?? null;
  const requestedViewExists = architectureViewExists(graph, requestedView);
  const requestedResourceExists = architectureResourceExists(graph.resources, selectedId);
  const parent = selected?.parent_id
    ? graph.resources.find((resource) => resource.id === selected.parent_id)
    : null;
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
  return (
    <div class="architecture-workspace">
      <div class="architecture-toolbar">
        <label class="architecture-view-picker">
          <span>Architecture view</span>
          <select
            value={graph.active_view ?? graph.views?.[0]?.id ?? ""}
            onChange={(event) => onViewScopeChange((event.target as HTMLSelectElement).value)}
          >
            {(graph.views ?? []).map((view) => (
              <option value={view.id}>{view.kind === "fdai" ? "FDAI - " : "App - "}{view.label}</option>
            ))}
          </select>
          <small>{graph.views?.find((view) => view.id === graph.active_view)?.description}</small>
        </label>
        <div class={`inventory-freshness is-${graph.freshness}`}>
          <span />snapshot {graph.freshness} <small>{formatAge(graph.snapshot_at, now)}</small>
          {(graph.realtime?.pending_changes ?? 0) > 0 ? (
            <small>
              {graph.realtime?.pending_changes} real-time change
              {graph.realtime?.pending_changes === 1 ? "" : "s"}
            </small>
          ) : null}
        </div>
      </div>
      <div class="architecture-stage">
        <div class="architecture-canvas-shell">
          <ArchitectureMap
            ref={mapRef}
            graph={filtered}
            selectedId={selectedId}
            onSelect={onSelect}
            options={displayOptions}
            onZoomChange={onZoomChange}
          />
          <div class="architecture-zoom-controls" aria-label="Map zoom controls">
            <button type="button" onClick={() => mapRef.current?.zoomIn()} aria-label="Zoom in">+</button>
            <output aria-label="Zoom level">{zoomPercent}%</output>
            <button type="button" onClick={() => mapRef.current?.zoomOut()} aria-label="Zoom out">-</button>
            <button type="button" onClick={() => mapRef.current?.fit()} aria-label="Fit map">Fit</button>
          </div>
        </div>
        <aside class="architecture-inspector">
          <section class="map-controls-section">
            <span class="eyebrow">Map controls</span>
            <h3>View</h3>
            <div class="architecture-camera-control" role="group" aria-label="Camera view">
              {(["iso", "top", "front"] as const).map((view) => (
                <button
                  type="button"
                  class={cameraView === view ? "is-active" : ""}
                  onClick={() => onCameraViewChange(view)}
                >
                  {CAMERA_LABELS[view]}
                </button>
              ))}
            </div>
            <h3>Layer filter</h3>
            <div class="architecture-layer-filters" aria-label="Architecture layers">
              {ARCHITECTURE_LAYERS.map((layer) => (
                <button
                  type="button"
                  class={visibleLayers.has(layer) ? "is-active" : ""}
                  aria-pressed={visibleLayers.has(layer)}
                  aria-label={`${LAYER_LABELS[layer]} layer (${formatResourceCount(layerCounts.get(layer) ?? 0)})`}
                  disabled={(layerCounts.get(layer) ?? 0) === 0}
                  onClick={() => onToggleLayer(layer)}
                >
                  <i class="architecture-filter-mark" aria-hidden="true" />
                  <span>{LAYER_LABELS[layer]}</span>
                  <small>{layerCounts.get(layer) ?? 0}</small>
                </button>
              ))}
            </div>
            <h3>Resource colors</h3>
            <div class="architecture-color-legend" aria-label="Azure-aligned resource colors">
              {resourceColorTokens.map((token) => (
                <span>
                  <i style={{ backgroundColor: RESOURCE_COLOR_TOKENS[token].color }} />
                  {RESOURCE_COLOR_TOKENS[token].label}
                </span>
              ))}
            </div>
            <h3>Display</h3>
            <div class="architecture-display-options">
              {([
                ["showConnections", "Connections"],
                ["showReflections", "Reflections"],
                ["showLabels", "Labels"],
                ["showGrid", "Grid points"],
              ] as const).map(([key, label]) => (
                <label><input type="checkbox" checked={displayOptions[key]} onChange={() => onToggleDisplay(key)} />{label}</label>
              ))}
            </div>
          </section>
          <section class="architecture-selection-section">
            {selected ? (
              <>
                <span class="eyebrow">{LAYER_LABELS[layerOf(selected)]}</span>
                <h3>{selected.name}</h3>
                <dl>
                  <dt>Type</dt><dd>{selected.type}</dd>
                  <dt>Status</dt><dd class={`status-${selected.status}`}>{selected.status}</dd>
                  <dt>Parent</dt><dd>{parent?.name ?? "Tenant"}</dd>
                  <dt>Resource id</dt><dd class="mono">{selected.id}</dd>
                </dl>
                <a class="btn" href={routeHref("blast-radius", { params: { target: selected.id, view: graph.active_view } })}>View blast radius</a>
              </>
            ) : !requestedResourceExists && selectedId ? (
              <div class="state-block state-unavailable" role="alert">
                <span class="state-icon" aria-hidden="true">?</span>
                <div>
                  <strong>Resource unavailable</strong>
                  <p><code>{selectedId}</code> is not present in this architecture view.</p>
                  <a href={architectureHref(undefined, graph.active_view)}>Open current architecture</a>
                </div>
              </div>
            ) : (
              <div class="architecture-empty-inspector">
                <strong>Select a resource</strong>
                <p>Inspect its type, status, parent boundary, and safety context.</p>
              </div>
            )}
          </section>
        </aside>
      </div>
    </div>
  );
}

export function formatAge(timestamp: string, now = Date.now()): string {
  const seconds = Math.max(0, Math.round((now - Date.parse(timestamp)) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  return `${Math.round(seconds / 3600)}h ago`;
}

function formatResourceCount(count: number): string {
  return `${count} ${count === 1 ? "resource" : "resources"}`;
}
