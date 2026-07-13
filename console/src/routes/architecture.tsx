import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { ReadApiError, type ReadApiClient } from "../api";
import { ArchitectureMap, type ArchitectureMapHandle } from "../components/architecture-map";
import {
  ARCHITECTURE_LAYERS,
  architectureHref,
  architectureViewFromHash,
  graphSubset,
  layerOf,
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

interface Props { readonly client: ReadApiClient }

const LAYER_LABELS: Readonly<Record<ArchitectureLayer, string>> = {
  scope: "Scope",
  network: "Network",
  security: "Security",
  compute: "Compute",
  data: "Data",
};

const CAMERA_LABELS: Readonly<Record<ArchitectureCameraView, string>> = {
  iso: "Iso",
  top: "Top",
  front: "Front",
};

export function ArchitectureRoute({ client }: Props) {
  const [state, setState] = useState<AsyncState<InventoryGraphResponse>>({ status: "loading" });
  const [selectedId, setSelectedId] = useState<string | null>(() => selectedResourceIdFromHash(window.location.hash));
  const [visibleLayers, setVisibleLayers] = useState<Set<ArchitectureLayer>>(new Set(ARCHITECTURE_LAYERS));
  const [viewScope, setViewScope] = useState<string | null>(() => architectureViewFromHash(window.location.hash));
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
    const syncHash = () => {
      setSelectedId(selectedResourceIdFromHash(window.location.hash));
      setViewScope(architectureViewFromHash(window.location.hash));
    };
    window.addEventListener("hashchange", syncHash);
    return () => window.removeEventListener("hashchange", syncHash);
  }, []);

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    const params: Record<string, string> = {
      depth: "4",
      include: "contains,attached_to,depends_on",
    };
    if (viewScope) params.scope = viewScope;
    client.panel<InventoryGraphResponse>("/inventory/graph", params).then(
      (data) => { if (!cancelled) setState({ status: "ready", data }); },
      (error: unknown) => {
        if (cancelled) return;
        const message = error instanceof Error ? error.message : String(error);
        setState(error instanceof ReadApiError && error.status === 404
          ? { status: "unavailable", message: "The inventory graph is not wired on this deployment." }
          : { status: "error", message });
      },
    );
    return () => { cancelled = true; };
  }, [client, viewScope]);

  function selectResource(resource: InventoryResource | null): void {
    setSelectedId(resource?.id ?? null);
    window.location.hash = architectureHref(resource?.id, viewScope);
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
            selectedId={selectedId}
            visibleLayers={visibleLayers}
            onSelect={selectResource}
            onToggleLayer={toggleLayer}
            onViewScopeChange={(scope) => {
              mapRef.current?.setView("iso");
              setCameraView("iso");
              setSelectedId(null);
              setViewScope(scope);
              window.location.hash = architectureHref(undefined, scope);
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
  const filtered = useMemo(
    () => graphSubset(graph, visibleLayers),
    [graph, visibleLayers],
  );
  const selected = graph.resources.find((resource) => resource.id === selectedId) ?? null;
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
        { key: "freshness", value: graph.freshness, group: "inventory" },
        { key: "source", value: graph.source ?? "inventory", group: "inventory" },
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
          <span />{graph.freshness} <small>{formatAge(graph.snapshot_at)}</small>
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
            <h3>Layers</h3>
            <div class="architecture-layer-filters" aria-label="Architecture layers">
              {ARCHITECTURE_LAYERS.map((layer) => (
                <button
                  type="button"
                  class={visibleLayers.has(layer) ? "is-active" : ""}
                  onClick={() => onToggleLayer(layer)}
                >
                  <i class={`architecture-swatch is-${layer}`} />{LAYER_LABELS[layer]}
                </button>
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
                <a class="btn" href={`#/blast-radius?target=${encodeURIComponent(selected.id)}&view=${encodeURIComponent(graph.active_view ?? "")}`}>View blast radius</a>
              </>
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

function formatAge(timestamp: string): string {
  const seconds = Math.max(0, Math.round((Date.now() - Date.parse(timestamp)) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  return `${Math.round(seconds / 3600)}h ago`;
}