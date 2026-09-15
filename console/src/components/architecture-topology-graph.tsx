import { useEffect, useId, useMemo, useRef, useState } from "preact/hooks";
import { t } from "../routes/i18n/architecture";
import { ArchitectureTopologyControls } from "./architecture-topology-controls";
import { handleArchitectureTopologyKeyDown } from "./architecture-topology-keyboard";
import { architectureResourceAbbreviation } from "./architecture-resource-abbreviations";
import { architectureNetworkIconForResourceType } from "./architecture-network-icons";
import {
  ARCHITECTURE_TOPOLOGY_SCALE_STEP,
  architectureTopologyActiveIds,
  architectureTopologyBounds,
  architectureTopologyCanvasSize,
  architectureTopologyFitScale,
  architectureTopologyLabelLines,
  architectureTopologyLinkRoute,
  architectureTopologyRegionDepth,
  architectureTopologyResourcePoint,
  architectureTopologyZoomScrollTarget,
  clampArchitectureTopologyScale,
} from "./architecture-topology-graph.model";
import {
  ARCHITECTURE_TOPOLOGY_HIT_TARGET_SIZE,
  architectureTopologyNodeDimensions,
} from "./architecture-topology-dimensions";
import {
  isRegion,
  resourceTypeLabelOf,
  type InventoryGraphResponse,
  type InventoryResource,
} from "./architecture-map.model";
import { useArchitectureTopologyPan } from "./use-architecture-topology-pan";
import "./architecture-topology-graph.css";

interface Props {
  readonly graph: InventoryGraphResponse;
  readonly selectedId: string | null;
  readonly highlightedIds?: ReadonlySet<string>;
  readonly onSelect?: (resource: InventoryResource) => void;
  readonly descriptionId?: string;
  readonly variant?: "topology" | "network" | "impact";
  readonly allowFullscreen?: boolean;
}

/** Renders one bounded inventory projection as an accessible pannable SVG topology. */
export function ArchitectureTopologyGraph({
  graph,
  selectedId,
  highlightedIds,
  onSelect,
  descriptionId,
  variant = "topology",
  allowFullscreen = true,
}: Props) {
  const frameRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const fitScaleRef = useRef(1);
  const scaleRef = useRef(1);
  const pendingScrollRef = useRef<{ readonly left: number; readonly top: number } | null>(null);
  const {
    panning,
    suppressRegionClickRef,
    startPan,
    movePan,
    finishPan,
  } = useArchitectureTopologyPan();
  const markerSeed = useId().replaceAll(/[^a-zA-Z0-9_-]/g, "");
  const markerId = `architecture-arrow-${markerSeed}`;
  const [scale, setScale] = useState(1);
  const [fullscreen, setFullscreen] = useState(false);
  const byId = useMemo(
    () => new Map(graph.resources.map((resource) => [resource.id, resource])),
    [graph.resources],
  );
  const activeIds = architectureTopologyActiveIds(graph, highlightedIds);
  const bounds = useMemo(() => architectureTopologyBounds(graph.resources), [graph.resources]);
  const canvas = useMemo(() => architectureTopologyCanvasSize(bounds), [bounds]);
  const regions = graph.resources.filter(isRegion).sort(
    (first, second) =>
      architectureTopologyRegionDepth(first, byId) - architectureTopologyRegionDepth(second, byId),
  );
  const nodes = graph.resources.filter((resource) => !isRegion(resource));
  const focusOrder = [...nodes, ...[...regions].reverse()];
  const focusableId = selectedId && byId.has(selectedId)
    ? selectedId
    : focusOrder[0]?.id ?? null;
  const active = (resourceId: string) => !activeIds || activeIds.has(resourceId);

  const changeScale = (requestedScale: number, fit = false): void => {
    const scroll = scrollRef.current;
    if (!scroll) return;
    const nextScale = clampArchitectureTopologyScale(requestedScale);
    pendingScrollRef.current = fit
      ? { left: 0, top: 0 }
      : architectureTopologyZoomScrollTarget({
          scrollLeft: scroll.scrollLeft,
          scrollTop: scroll.scrollTop,
          viewportWidth: scroll.clientWidth,
          viewportHeight: scroll.clientHeight,
          currentScale: scaleRef.current,
          nextScale,
        });
    if (nextScale === scaleRef.current) {
      const pending = pendingScrollRef.current;
      pendingScrollRef.current = null;
      if (pending) {
        scroll.scrollLeft = pending.left;
        scroll.scrollTop = pending.top;
      }
      return;
    }
    scaleRef.current = nextScale;
    setScale(nextScale);
  };

  useEffect(() => {
    const scroll = scrollRef.current;
    if (!scroll) return;
    const resize = () => {
      const fit = architectureTopologyFitScale(
        canvas,
        scroll.clientWidth,
        scroll.clientHeight,
      );
      fitScaleRef.current = fit;
      if (scaleRef.current === 1 || scaleRef.current < fit) {
        scaleRef.current = fit;
        setScale(fit);
      }
    };
    const observer = new ResizeObserver(resize);
    observer.observe(scroll);
    resize();
    return () => observer.disconnect();
  }, [canvas]);

  useEffect(() => {
    const scroll = scrollRef.current;
    const pending = pendingScrollRef.current;
    if (!scroll || !pending) return;
    pendingScrollRef.current = null;
    scroll.scrollLeft = pending.left;
    scroll.scrollTop = pending.top;
  }, [scale]);

  useEffect(() => {
    const sync = () => setFullscreen(document.fullscreenElement === frameRef.current);
    document.addEventListener("fullscreenchange", sync);
    return () => document.removeEventListener("fullscreenchange", sync);
  }, []);

  const toggleFullscreen = async (): Promise<void> => {
    if (!allowFullscreen || !frameRef.current) return;
    if (document.fullscreenElement === frameRef.current) await document.exitFullscreen();
    else await frameRef.current.requestFullscreen();
  };

  return (
    <div
      ref={frameRef}
      class={`architecture-topology-graph is-${variant}${fullscreen ? " is-fullscreen" : ""}`}
    >
      <ArchitectureTopologyControls
        scale={scale}
        fullscreen={fullscreen}
        allowFullscreen={allowFullscreen}
        onZoomOut={() => changeScale(scale - ARCHITECTURE_TOPOLOGY_SCALE_STEP)}
        onZoomIn={() => changeScale(scale + ARCHITECTURE_TOPOLOGY_SCALE_STEP)}
        onFit={() => changeScale(fitScaleRef.current, true)}
        onToggleFullscreen={() => void toggleFullscreen()}
      />
      <div
        ref={scrollRef}
        class={`architecture-topology-scroll${panning ? " is-panning" : ""}`}
        onPointerDown={startPan}
        onPointerMove={movePan}
        onPointerUp={finishPan}
        onPointerCancel={finishPan}
        onWheel={(event) => {
          event.preventDefault();
          changeScale(scaleRef.current + (
            event.deltaY < 0
              ? ARCHITECTURE_TOPOLOGY_SCALE_STEP
              : -ARCHITECTURE_TOPOLOGY_SCALE_STEP
          ));
        }}
      >
        <svg
          class="architecture-topology-svg"
          viewBox={`${bounds.x} ${bounds.y} ${bounds.width} ${bounds.height}`}
          role="group"
          aria-label={t(
            variant === "network" ? "network.mapAriaLabel" : "mapAriaLabel",
            { count: graph.resources.length },
          )}
          aria-describedby={descriptionId}
          style={{
            width: `${canvas.width * scale}px`,
            minWidth: `${canvas.width * scale}px`,
            height: `${canvas.height * scale}px`,
            minHeight: `${canvas.height * scale}px`,
          }}
        >
          <defs>
            <marker id={markerId} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
              <path d="M0 1L9 5L0 9z" />
            </marker>
          </defs>
          <g class="architecture-topology-regions">
            {regions.map((resource) => (
              <g
                key={resource.id}
                class={`architecture-topology-resource architecture-topology-region${selectedId === resource.id ? " is-selected" : ""}${active(resource.id) ? "" : " is-muted"}`}
                data-resource-id={resource.id}
                data-region-depth={architectureTopologyRegionDepth(resource, byId)}
                data-resource-type={resource.type}
                role={onSelect ? "button" : undefined}
                tabindex={onSelect && focusableId === resource.id ? 0 : -1}
                aria-label={`${resource.name}. ${resourceTypeLabelOf(resource)}`}
                onClick={(event) => {
                  if (suppressRegionClickRef.current) {
                    event.preventDefault();
                    return;
                  }
                  onSelect?.(resource);
                }}
                onKeyDown={(event) => handleArchitectureTopologyKeyDown(
                  event,
                  resource,
                  focusOrder,
                  onSelect,
                )}
              >
                <title>{resource.name}</title>
                <rect
                  x={resource.x ?? 0}
                  y={resource.y ?? 0}
                  width={resource.w ?? 2}
                  height={resource.h ?? 2}
                  rx=".16"
                />
                <text x={(resource.x ?? 0) + .2} y={(resource.y ?? 0) + .38}>
                  {resource.name}
                </text>
              </g>
            ))}
          </g>
          <g class="architecture-topology-links">
            {graph.links.map((link, index) => {
              const source = byId.get(link.source);
              const target = byId.get(link.target);
              if (!source || !target || link.type === "contains") return null;
              const route = architectureTopologyLinkRoute(source, target, graph.resources, link.type);
              const pathActive = active(source.id) && active(target.id);
              return (
                <g
                  key={`${link.source}:${link.type}:${link.target}:${index}`}
                  class={`architecture-topology-link is-${link.type}${pathActive ? "" : " is-muted"}`}
                >
                  <title>{`${source.name} - ${link.type} - ${target.name}`}</title>
                  <path class="architecture-topology-link-halo" d={route.path} />
                  <path
                    class="architecture-topology-link-path"
                    d={route.path}
                    markerEnd={link.type === "depends_on" || link.type === "peered_with"
                      ? `url(#${markerId})`
                      : undefined}
                    markerStart={link.type === "peered_with" ? `url(#${markerId})` : undefined}
                  />
                  {link.type === "attached_to" ? (
                    <>
                      <circle class="architecture-topology-endpoint-halo" cx={route.end.x} cy={route.end.y} r=".16" />
                      <circle class="architecture-topology-endpoint" cx={route.end.x} cy={route.end.y} r=".09" />
                    </>
                  ) : null}
                </g>
              );
            })}
          </g>
          {onSelect ? (
            <g class="architecture-topology-node-targets" aria-hidden="true">
              {nodes.map((resource) => {
                const position = architectureTopologyResourcePoint(resource);
                return (
                  <rect
                    key={resource.id}
                    class="architecture-topology-node-target"
                    data-resource-id={resource.id}
                    x={position.x - ARCHITECTURE_TOPOLOGY_HIT_TARGET_SIZE / 2}
                    y={position.y - ARCHITECTURE_TOPOLOGY_HIT_TARGET_SIZE / 2}
                    width={ARCHITECTURE_TOPOLOGY_HIT_TARGET_SIZE}
                    height={ARCHITECTURE_TOPOLOGY_HIT_TARGET_SIZE}
                    rx=".16"
                    onClick={() => onSelect(resource)}
                  />
                );
              })}
            </g>
          ) : null}
          <g class="architecture-topology-nodes">
            {nodes.map((resource) => {
              const position = architectureTopologyResourcePoint(resource);
              const { width: nodeWidth, height: nodeHeight } =
                architectureTopologyNodeDimensions(resource.render_scale);
              const icon = architectureNetworkIconForResourceType(resource.type);
              const lines = architectureTopologyLabelLines(resource.name);
              return (
                <g
                  key={resource.id}
                  class={`architecture-topology-resource architecture-topology-node${icon ? " has-official-icon" : ""}${selectedId === resource.id ? " is-selected" : ""}${active(resource.id) ? "" : " is-muted"}`}
                  data-resource-id={resource.id}
                  data-status={resource.status.toLowerCase()}
                  role={onSelect ? "button" : undefined}
                  tabindex={onSelect ? (focusableId === resource.id ? 0 : -1) : undefined}
                  aria-label={`${resource.name}. ${resourceTypeLabelOf(resource)}. ${resource.status}`}
                  transform={`translate(${position.x} ${position.y})`}
                  onClick={() => onSelect?.(resource)}
                  onKeyDown={(event) => handleArchitectureTopologyKeyDown(
                    event,
                    resource,
                    focusOrder,
                    onSelect,
                  )}
                >
                  <title>{`${resource.name}. ${resourceTypeLabelOf(resource)}. ${resource.status}`}</title>
                  <rect
                    class="architecture-topology-node-surface"
                    x={-nodeWidth / 2}
                    y={-nodeHeight / 2}
                    width={nodeWidth}
                    height={nodeHeight}
                    rx=".14"
                  />
                  {icon ? (
                    <image
                      class="architecture-topology-node-icon"
                      href={icon}
                      x={-nodeWidth / 2 + .18}
                      y={-nodeHeight / 2 + .16}
                      width=".5"
                      height=".5"
                    />
                  ) : (
                    <text
                      class="architecture-topology-node-glyph"
                      x={-nodeWidth / 2 + .43}
                      y={-nodeHeight / 2 + .45}
                    >
                      {architectureResourceAbbreviation(resource.type)}
                    </text>
                  )}
                  <text class="architecture-topology-node-name">
                    {lines.map((line, lineIndex) => (
                      <tspan
                        key={`${resource.id}:${lineIndex}`}
                        x={-nodeWidth / 2 + .78}
                        y={-nodeHeight / 2 + .34 + lineIndex * .3}
                      >
                        {line}
                      </tspan>
                    ))}
                  </text>
                  <text
                    class="architecture-topology-node-type"
                    x={-nodeWidth / 2 + .18}
                    y={nodeHeight / 2 - .18}
                  >
                    {resourceTypeLabelOf(resource)}
                  </text>
                  {(resource.collapsed_count ?? 0) > 0 ? (
                    <g
                      class="architecture-topology-node-count"
                      transform={`translate(${nodeWidth / 2 - .26} ${-nodeHeight / 2 + .24})`}
                    >
                      <circle r=".23" />
                      <text y=".05">+{resource.collapsed_count}</text>
                    </g>
                  ) : null}
                </g>
              );
            })}
          </g>
        </svg>
      </div>
      <div class="architecture-topology-legend" aria-label={t("relationshipLegend")}>
        <span><i class="is-dependency" aria-hidden="true" />{t("relationship.dependsOn")}</span>
        <span><i class="is-attachment" aria-hidden="true" />{t("relationship.attachedTo")}</span>
        <span><i class="is-peering" aria-hidden="true" />{t("relationship.peersWith")}</span>
        <span><i class="is-boundary" aria-hidden="true" />{t("relationship.boundary")}</span>
      </div>
    </div>
  );
}
