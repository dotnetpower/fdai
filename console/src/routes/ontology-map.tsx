import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { isOptionalReadApiUnavailable, type ReadApiClient } from "../api";
import {
  ArchitectureMap,
  type ArchitectureMapHandle,
} from "../components/architecture-map";
import { architectureCanvasHeight } from "../components/architecture-map.geometry";
import {
  DEFAULT_ARCHITECTURE_DISPLAY_OPTIONS,
  type InventoryGraphResponse,
  type InventoryResource,
} from "../components/architecture-map.model";
import { layoutArchitecturePresentation } from "../components/architecture-map-layout";
import { ArchitectureRelationIndex } from "../components/architecture-relation-index";
import { AsyncBoundary, type AsyncState } from "../components/ui";
import { navigate, routeHref } from "../router";
import { formatDateTime, t } from "./i18n/ontology";

const MAP_DEPTH = 2;
const MAP_LIMIT = 200;
const MAP_LINKS = "contains,attached_to,depends_on";
const MAX_ROOT_LENGTH = 512;

type PanelClient = Pick<ReadApiClient, "panel">;

export function normalizeOntologyMapRoot(value: string | null): string | null {
  const normalized = value?.trim() ?? "";
  return normalized && normalized.length <= MAX_ROOT_LENGTH ? normalized : null;
}

export function loadOntologyMapGraph(
  client: PanelClient,
  root: null,
): Promise<null>;
export function loadOntologyMapGraph(
  client: PanelClient,
  root: string,
): Promise<InventoryGraphResponse>;
export async function loadOntologyMapGraph(
  client: PanelClient,
  root: string | null,
): Promise<InventoryGraphResponse | null> {
  if (root === null) return null;
  const graph = await client.panel<InventoryGraphResponse>("/inventory/graph", {
    root,
    depth: String(MAP_DEPTH),
    limit: String(MAP_LIMIT),
    include: MAP_LINKS,
  });
  if (!graph.resources.some((resource) => resource.id === root)) {
    throw new Error("requested inventory root is absent");
  }
  return graph;
}

export function OntologyMapView({ client }: { readonly client: ReadApiClient }) {
  const routeRoot = normalizeOntologyMapRoot(new URLSearchParams(window.location.search).get("root"));
  const [root, setRoot] = useState<string | null>(routeRoot);
  const [draftRoot, setDraftRoot] = useState(routeRoot ?? "");
  const [state, setState] = useState<AsyncState<InventoryGraphResponse>>({ status: "loading" });
  const [selectedId, setSelectedId] = useState<string | null>(routeRoot);

  useEffect(() => {
    const sync = () => {
      const nextRoot = normalizeOntologyMapRoot(new URLSearchParams(window.location.search).get("root"));
      setRoot(nextRoot);
      setDraftRoot(nextRoot ?? "");
      setSelectedId(nextRoot);
    };
    window.addEventListener("popstate", sync);
    window.addEventListener("fdai:route-changed", sync);
    return () => {
      window.removeEventListener("popstate", sync);
      window.removeEventListener("fdai:route-changed", sync);
    };
  }, []);

  useEffect(() => {
    if (root === null) return;
    let cancelled = false;
    setState({ status: "loading" });
    loadOntologyMapGraph(client, root).then(
      (data) => {
        if (!cancelled) {
          setSelectedId(root);
          setState({ status: "ready", data });
        }
      },
      (error: unknown) => {
        if (cancelled) return;
        setState(isOptionalReadApiUnavailable(error)
          ? { status: "unavailable", message: t("ontology.map.unavailable") }
          : { status: "error", message: t("ontology.map.error") });
      },
    );
    return () => {
      cancelled = true;
    };
  }, [client, root]);

  const openRoot = (resourceId: string): void => {
    navigate(routeHref("ontology", { params: { view: "map", root: resourceId } }));
  };
  const submitRoot = (event: Event): void => {
    event.preventDefault();
    const nextRoot = normalizeOntologyMapRoot(draftRoot);
    if (nextRoot) openRoot(nextRoot);
  };

  return (
    <section class="ontology-runtime-map" aria-labelledby="ontology-map-title">
      <div class="ontology-map-query">
        <div>
          <h3 id="ontology-map-title">{t("ontology.map.title")}</h3>
          <p>{t("ontology.map.description")}</p>
        </div>
        <form onSubmit={submitRoot}>
          <label>
            <span>{t("ontology.map.rootLabel")}</span>
            <input
              type="text"
              value={draftRoot}
              maxLength={MAX_ROOT_LENGTH}
              placeholder={t("ontology.map.rootPlaceholder")}
              onInput={(event) => setDraftRoot(event.currentTarget.value)}
            />
          </label>
          <button type="submit" class="btn" disabled={normalizeOntologyMapRoot(draftRoot) === null}>
            {t("ontology.map.open")}
          </button>
        </form>
      </div>

      {root === null ? (
        <div class="ontology-map-idle">
          <strong>{t("ontology.map.idleTitle")}</strong>
          <p>{t("ontology.map.idleDescription")}</p>
        </div>
      ) : (
        <AsyncBoundary state={state} resourceLabel={t("ontology.map.loadingLabel")}>
          {(graph) => (
            <OntologyMapGraph
              graph={graph}
              root={root}
              selectedId={selectedId}
              onSelect={(resource) => setSelectedId(resource?.id ?? null)}
              onCenter={openRoot}
            />
          )}
        </AsyncBoundary>
      )}
    </section>
  );
}

function OntologyMapGraph({
  graph,
  root,
  selectedId,
  onSelect,
  onCenter,
}: {
  readonly graph: InventoryGraphResponse;
  readonly root: string;
  readonly selectedId: string | null;
  readonly onSelect: (resource: InventoryResource | null) => void;
  readonly onCenter: (resourceId: string) => void;
}) {
  const mapRef = useRef<ArchitectureMapHandle>(null);
  const [zoomPercent, setZoomPercent] = useState(100);
  const presentedGraph = useMemo(
    () => layoutArchitecturePresentation(graph, selectedId),
    [graph, selectedId],
  );
  const selected = graph.resources.find((resource) => resource.id === selectedId) ?? null;
  const rootResource = graph.resources.find((resource) => resource.id === root) ?? null;

  return (
    <div class="ontology-map-result">
      <dl class="ontology-map-metadata">
        <div><dt>{t("ontology.map.source")}</dt><dd>{graph.source ?? t("ontology.map.unknown")}</dd></div>
        <div><dt>{t("ontology.map.freshness")}</dt><dd>{t(`ontology.map.freshnessValue.${graph.freshness}`)}</dd></div>
        <div><dt>{t("ontology.map.snapshot")}</dt><dd>{formatDateTime(graph.snapshot_at)}</dd></div>
        <div><dt>{t("ontology.map.scope")}</dt><dd>{t("ontology.map.scopeValue", { depth: graph.depth, limit: graph.limit ?? MAP_LIMIT })}</dd></div>
      </dl>
      {graph.truncated ? (
        <div class="ontology-map-truncated" role="status">
          <strong>{t("ontology.map.truncated")}</strong>
          <span>{(graph.truncation_reasons ?? []).map(ontologyMapTruncationReasonLabel).join(", ")}</span>
        </div>
      ) : null}
      <div class="ontology-map-stage">
        <div
          class="architecture-canvas-shell"
          style={`--architecture-canvas-height: ${architectureCanvasHeight(presentedGraph)}px`}
        >
          <p id="ontology-map-description" class="sr-only">
            {t("ontology.map.canvasDescription", {
              resources: presentedGraph.resources.length,
              links: presentedGraph.links.length,
            })}
          </p>
          <ArchitectureMap
            ref={mapRef}
            graph={presentedGraph}
            selectedId={selectedId}
            onSelect={onSelect}
            options={DEFAULT_ARCHITECTURE_DISPLAY_OPTIONS}
            onZoomChange={setZoomPercent}
            descriptionId="ontology-map-description"
          />
          <div class="architecture-zoom-controls" role="group" aria-label={t("ontology.map.zoomControls")}>
            <button type="button" onClick={() => mapRef.current?.zoomIn()} aria-label={t("ontology.map.zoomIn")}>+</button>
            <output aria-label={t("ontology.map.zoomLevel")} aria-live="polite">{zoomPercent}%</output>
            <button type="button" onClick={() => mapRef.current?.zoomOut()} aria-label={t("ontology.map.zoomOut")}>-</button>
            <button type="button" onClick={() => mapRef.current?.fit()}>{t("ontology.map.fit")}</button>
          </div>
        </div>
        <aside class="ontology-map-inspector" aria-live="polite">
          {selected ? (
            <>
              <span class="eyebrow">{selected.type}</span>
              <h3>{selected.name}</h3>
              <dl>
                <dt>{t("ontology.map.resourceId")}</dt><dd><code>{selected.id}</code></dd>
                <dt>{t("ontology.map.status")}</dt><dd>{selected.status}</dd>
                <dt>{t("ontology.map.relationships")}</dt>
                <dd>{graph.links.filter((link) => link.source === selected.id || link.target === selected.id).length}</dd>
              </dl>
              <button type="button" class="btn" onClick={() => onCenter(selected.id)}>
                {t("ontology.map.centerHere")}
              </button>
            </>
          ) : rootResource ? (
            <button type="button" class="architecture-text-button" onClick={() => onSelect(rootResource)}>
              {t("ontology.map.selectRoot")}
            </button>
          ) : null}
        </aside>
      </div>
      <ArchitectureRelationIndex graph={presentedGraph} onSelect={onSelect} />
    </div>
  );
}

export function ontologyMapTruncationReasonLabel(reason: string): string {
  const knownReasons = new Set([
    "resource_limit",
    "adjacent_edge_limit",
    "internal_edge_limit",
    "source_limit",
  ]);
  if (!knownReasons.has(reason)) {
    return t("ontology.map.truncation.unknown", { reason });
  }
  const key = `ontology.map.truncation.${reason}`;
  return t(key);
}
