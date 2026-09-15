import { useEffect, useMemo, useState } from "preact/hooks";
import { SearchableSelect, type SearchableSelectOption } from "../components/searchable-select";
import { Tooltip } from "../components/tooltip";
import { ArchitectureInspector } from "../components/architecture-inspector";
import { ArchitectureNetworkPathPanel } from "../components/architecture-network-path-panel";
import { ArchitectureTopologyGraph } from "../components/architecture-topology-graph";
import {
  DEFAULT_ARCHITECTURE_NETWORK_FILTERS,
  architectureNetworkFocusGraph,
  exportArchitectureNetworkSvg,
  filterArchitectureNetworkGraph,
  layoutArchitectureNetworkFocusGraph,
  traceArchitectureNetworkPath,
  type ArchitectureNetworkFilters,
} from "../components/architecture-network-focus";
import { layoutArchitecturePresentation } from "../components/architecture-map-layout";
import {
  resourceTypeLabelOf,
  type ArchitecturePresentationMode,
  type InventoryGraphResponse,
  type InventoryResource,
} from "../components/architecture-map.model";
import { t } from "./i18n/architecture";
import "./architecture-workbench.css";

interface Props {
  readonly graph: InventoryGraphResponse;
  readonly selectedId: string | null;
  readonly mode: ArchitecturePresentationMode;
  readonly sourceLabel: string;
  readonly onSelect: (resource: InventoryResource | null) => void;
  readonly onViewScopeChange: (scope: string) => void;
  readonly onModeChange: (mode: ArchitecturePresentationMode) => void;
}

/** Composes the read-only Architecture toolbar, topology, evidence summary, and Inspector. */
export function ArchitectureWorkbench({
  graph,
  selectedId,
  mode,
  sourceLabel,
  onSelect,
  onViewScopeChange,
  onModeChange,
}: Props) {
  const [inspectorOpen, setInspectorOpen] = useState(
    selectedId !== null || mode === "network",
  );
  const [networkFilters, setNetworkFilters] = useState<ArchitectureNetworkFilters>({
    ...DEFAULT_ARCHITECTURE_NETWORK_FILTERS,
  });
  const [pathSourceId, setPathSourceId] = useState<string | null>(null);
  const [pathTargetId, setPathTargetId] = useState<string | null>(null);
  const selected = graph.resources.find((resource) => resource.id === selectedId) ?? null;
  const networkFocusGraph = useMemo(
    () => architectureNetworkFocusGraph(graph, selectedId),
    [graph, selectedId],
  );
  const filteredNetworkGraph = useMemo(
    () => filterArchitectureNetworkGraph(networkFocusGraph, networkFilters),
    [networkFilters, networkFocusGraph],
  );
  const displayedGraph = useMemo(
    () => mode === "network"
      ? selectedId
        ? layoutArchitectureNetworkFocusGraph(filteredNetworkGraph)
        : layoutArchitecturePresentation(filteredNetworkGraph, null)
      : layoutArchitecturePresentation(graph, selectedId),
    [filteredNetworkGraph, graph, mode, selectedId],
  );
  const networkPath = useMemo(
    () => traceArchitectureNetworkPath(networkFocusGraph, pathSourceId, pathTargetId),
    [networkFocusGraph, pathSourceId, pathTargetId],
  );
  const highlightedIds = networkPath?.status === "found"
    ? new Set(networkPath.resourceIds)
    : undefined;
  const resourceOptions = useMemo<readonly SearchableSelectOption[]>(
    () => [
      {
        value: "",
        label: t("workbench.scopeOverview"),
        description: t("workbench.scopeOverviewDescription"),
      },
      ...graph.resources
        .slice()
        .sort((first, second) => first.name.localeCompare(second.name))
        .map((resource) => ({
          value: resource.id,
          label: resource.name,
          description: resourceTypeLabelOf(resource),
          keywords: [resource.id, resource.type],
        })),
    ],
    [graph.resources],
  );
  const views = graph.views ?? [];

  useEffect(() => {
    if (selectedId !== null || mode === "network") setInspectorOpen(true);
    else setInspectorOpen(false);
  }, [mode, selectedId]);

  const changeResource = (resourceId: string): void => {
    onSelect(graph.resources.find((resource) => resource.id === resourceId) ?? null);
  };

  return (
    <section class="architecture-surface" aria-label={t("workbench.title")}>
      <div class={`architecture-toolbar${views.length === 0 ? " is-scope-less" : ""}`}>
        {views.length > 0 ? (
          <label class="architecture-toolbar-field">
            <span>{t("scope")}</span>
            <select
              value={graph.active_view ?? views[0]?.id ?? ""}
              onChange={(event) => onViewScopeChange(event.currentTarget.value)}
            >
              {(["fdai", "service", "resource_group"] as const).map((kind) => {
                const scopedViews = views.filter((view) => view.kind === kind);
                if (scopedViews.length === 0) return null;
                return (
                  <optgroup label={t(kind === "fdai" ? "viewGroup.fdai" : kind === "service" ? "viewGroup.service" : "viewGroup.resourceGroup")}>
                    {scopedViews.map((view) => <option value={view.id}>{view.label}</option>)}
                  </optgroup>
                );
              })}
            </select>
          </label>
        ) : null}
        <SearchableSelect
          label={t("workbench.resource")}
          value={selectedId ?? ""}
          options={resourceOptions}
          onChange={changeResource}
          placeholder={t("workbench.resourcePlaceholder")}
          emptyLabel={t("workbench.resourceEmpty")}
          helpText={t("workbench.resourceHelp")}
          resultsLabel={(shown, total) => t("workbench.resourceResults", { shown, total })}
        />
        <div class="architecture-mode-control">
          <span>{t("workbench.lens")}</span>
          <div class="segmented-control" role="group" aria-label={t("network.mode")}>
            <button
              type="button"
              class={mode === "topology" ? "active" : ""}
              aria-pressed={mode === "topology"}
              onClick={() => onModeChange("topology")}
            >
              {t("workbench.topology")}
            </button>
            <button
              type="button"
              class={mode === "network" ? "active" : ""}
              aria-pressed={mode === "network"}
              onClick={() => onModeChange("network")}
            >
              {t("network.networkMode")}
            </button>
          </div>
        </div>
        <div class="architecture-toolbar-status">
          <strong>{t("workbench.readOnly")}</strong>
          <span>{sourceLabel} - {graph.freshness}</span>
        </div>
      </div>
      <ArchitectureCoverage graph={graph} displayedGraph={displayedGraph} />
      <div class={`architecture-workbench${inspectorOpen ? "" : " is-inspector-collapsed"}`}>
        <div class="architecture-map-pane">
          <p id="architecture-map-description" class="sr-only">
            {t("mapDescription", {
              resources: displayedGraph.resources.length,
              links: displayedGraph.links.length,
            })}
          </p>
          {!inspectorOpen ? (
            <Tooltip content={t("inspector.show")}>
              <button
                type="button"
                class="architecture-inspector-toggle is-restore"
                aria-label={t("inspector.show")}
                aria-expanded={false}
                aria-controls="architecture-inspector"
                onClick={() => setInspectorOpen(true)}
              >
                <span aria-hidden="true" />
              </button>
            </Tooltip>
          ) : null}
          <ArchitectureTopologyGraph
            graph={displayedGraph}
            selectedId={selected?.id ?? null}
            {...(highlightedIds ? { highlightedIds } : {})}
            onSelect={onSelect}
            descriptionId="architecture-map-description"
            variant={mode}
          />
        </div>
        <ArchitectureInspector
          graph={graph}
          displayedGraph={displayedGraph}
          selected={selected}
          onSelect={onSelect}
          mode={mode}
          sourceLabel={sourceLabel}
          pathContent={(
            <ArchitectureNetworkPathPanel
              graph={networkFocusGraph}
              sourceId={pathSourceId}
              targetId={pathTargetId}
              result={networkPath}
              filters={networkFilters}
              onSourceChange={setPathSourceId}
              onTargetChange={setPathTargetId}
              onToggleFilter={(key) => setNetworkFilters((previous) => ({
                ...previous,
                [key]: !previous[key],
              }))}
              onExportSvg={() => {
                void exportArchitectureNetworkSvg(displayedGraph, networkPath).then((svg) =>
                  downloadTextArtifact("observed-network-topology.svg", "image/svg+xml", svg)
                );
              }}
              onExportPng={() => {
                void exportArchitectureNetworkSvg(displayedGraph, networkPath).then(
                  downloadSanitizedNetworkPng,
                );
              }}
            />
          )}
          hidden={!inspectorOpen}
          onToggle={() => setInspectorOpen(false)}
        />
      </div>
    </section>
  );
}

function ArchitectureCoverage({
  graph,
  displayedGraph,
}: {
  readonly graph: InventoryGraphResponse;
  readonly displayedGraph: InventoryGraphResponse;
}) {
  return (
    <details class="architecture-coverage">
      <summary>
        <span class="architecture-coverage-primary">
          <strong class={graph.truncated ? "is-partial" : "is-complete"}>
            {t(graph.truncated ? "coverage.partial" : "coverage.complete")}
          </strong>
          <span>{t("coverage.summary", {
            returned: graph.resources.length,
            displayed: displayedGraph.resources.length,
          })}</span>
        </span>
        <span class="architecture-coverage-state">
          {graph.freshness}
          {graph.limit ? ` - ${t("coverage.limit", { count: graph.limit })}` : ""}
        </span>
      </summary>
      <div class="architecture-coverage-details" aria-label={t("coverage.title")}>
        <dl>
          <div><dt>{t("coverage.displayedResources")}</dt><dd>{displayedGraph.resources.length.toLocaleString()}</dd></div>
          <div><dt>{t("coverage.returnedResources")}</dt><dd>{graph.resources.length.toLocaleString()}</dd></div>
          <div><dt>{t("coverage.displayedRelationships")}</dt><dd>{displayedGraph.links.length.toLocaleString()}</dd></div>
          <div><dt>{t("coverage.returnedRelationships")}</dt><dd>{graph.links.length.toLocaleString()}</dd></div>
        </dl>
        <p>{t("coverage.note", { time: graph.snapshot_at })}</p>
      </div>
    </details>
  );
}

function downloadTextArtifact(filename: string, mediaType: string, content: string): void {
  const url = URL.createObjectURL(new Blob([content], { type: mediaType }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

async function downloadSanitizedNetworkPng(svg: string): Promise<void> {
  const sourceUrl = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml" }));
  try {
    const image = new Image();
    image.src = sourceUrl;
    await image.decode();
    const canvas = document.createElement("canvas");
    canvas.width = 1200;
    canvas.height = 720;
    const context = canvas.getContext("2d");
    if (!context) return;
    context.drawImage(image, 0, 0, canvas.width, canvas.height);
    const png = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/png"));
    if (!png) return;
    const pngUrl = URL.createObjectURL(png);
    const link = document.createElement("a");
    link.href = pngUrl;
    link.download = "observed-network-topology.png";
    link.click();
    URL.revokeObjectURL(pngUrl);
  } finally {
    URL.revokeObjectURL(sourceUrl);
  }
}
