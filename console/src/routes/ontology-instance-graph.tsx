import type { JSX } from "preact";
import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { createPortal } from "preact/compat";
import { Tooltip } from "../components/tooltip";
import { recordedStateValueText, recordedText } from "../components/recorded-state-text";
import { routeHref } from "../router";
import { formatDateTime, formatNumber, t } from "./i18n/ontology";
import {
  buildInstanceEdgeGeometry,
  buildInstanceGraphLayout,
  buildInstanceTimeline,
  clampInstanceGraphScale,
  countInstanceLinkTypes,
  defaultInstanceLegendLinkTypes,
  INSTANCE_NODE_HEIGHT,
  INSTANCE_NODE_WIDTH,
  instanceGraphPathNodeIds,
  instanceGraphScrollTarget,
  instanceGraphWheelScale,
  instanceGraphZoomScrollTarget,
  showInstanceEdgeLabels,
  type InstanceTimelineEvent,
  type InstanceTimelineSegment,
} from "./ontology-instance-graph.model";
import { nestInstanceContainment } from "./ontology-instance-boxes";
import { ontologyInstanceIconForResourceType } from "./ontology-instance-resource-icons";
import {
  ontologyInstanceCapacityKind,
  ontologyInstanceNodeState,
  ontologyInstancePresentationCoverage,
  ontologyInstanceStatusTone,
  ontologyInstanceTrafficDirection,
  type OntologyInstanceExploration,
} from "./ontology-instances.model";

interface Props {
  readonly data: OntologyInstanceExploration;
  readonly onSelect: (resourceId: string | null) => void;
}

type HistoryPreview =
  | { readonly kind: "event"; readonly event: InstanceTimelineEvent }
  | { readonly kind: "segment"; readonly segment: InstanceTimelineSegment };

interface InstanceGraphTooltipState {
  readonly x: number;
  readonly y: number;
  readonly title: string;
  readonly detail: string;
  readonly status?: string;
  readonly note?: string;
}

interface InstanceGraphPanState {
  readonly pointerId: number;
  readonly clientX: number;
  readonly clientY: number;
  readonly scrollLeft: number;
  readonly scrollTop: number;
}

const AKS_INITIAL_GRAPH_SCALE = 0.68;
const AKS_INITIAL_HORIZONTAL_ANCHOR = 0.02;

/** Renders one bounded Resource neighborhood and its authority-preserving audit history. */
export function OntologyInstanceGraph({ data, onSelect }: Props) {
  const nested = useMemo(
    () => nestInstanceContainment(buildInstanceGraphLayout(data), data),
    [data],
  );
  const layout = nested.layout;
  const isAksRoot = data.resources.find((resource) => resource.id === data.root_id)
    ?.resource_type === "kubernetes-cluster";
  const timeline = useMemo(
    () => buildInstanceTimeline(data.timeline.items, data.source_cutoff),
    [data.source_cutoff, data.timeline.items],
  );
  const graphRef = useRef<HTMLDivElement>(null);
  const graphScrollRef = useRef<HTMLDivElement>(null);
  const graphScaleRef = useRef(1);
  // Zooming below the first render only shrinks nodes; it never reveals another relationship.
  const minScaleRef = useRef(1);
  const pendingScrollRef = useRef<{ readonly left: number; readonly top: number } | null>(null);
  const panStateRef = useRef<InstanceGraphPanState | null>(null);
  const [preview, setPreview] = useState<HistoryPreview | null>(null);
    const [graphTooltip, setGraphTooltip] = useState<InstanceGraphTooltipState | null>(null);
  const [focusedResourceId, setFocusedResourceId] = useState<string | null>(null);
  const [graphScale, setGraphScale] = useState(1);
  const [isPanning, setIsPanning] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);
  const [showAllRelationshipTypes, setShowAllRelationshipTypes] = useState(false);
  const showEdgeLabels = showInstanceEdgeLabels(layout.edges.length);
  const focusedPath = useMemo(
    () => focusedResourceId === null
      ? new Set<string>()
      : instanceGraphPathNodeIds(layout.nodes, focusedResourceId),
    [focusedResourceId, layout.nodes],
  );
  const linkTypeCounts = useMemo(() => {
    // A nested relationship left the canvas as a line but is still drawn, so it still counts.
    const shown = [...layout.edges.map((edge) => edge.link), ...nested.absorbedLinks];
    const displayed = new Map(
      countInstanceLinkTypes(shown).map((item) => [item.linkType, item.count]),
    );
    return countInstanceLinkTypes(data.links).map((item) => ({
      ...item,
      displayed: displayed.get(item.linkType) ?? 0,
    }));
  }, [data.links, layout.edges, nested.absorbedLinks]);
  const defaultLinkTypeCounts = defaultInstanceLegendLinkTypes(linkTypeCounts);
  const visibleLinkTypeCounts = showAllRelationshipTypes ? linkTypeCounts : defaultLinkTypeCounts;
  const hiddenLinkTypeCount = linkTypeCounts.length - defaultLinkTypeCounts.length;
  const defaultPreview = timeline.events.length > 0
    ? { kind: "event", event: timeline.events[timeline.events.length - 1]! } as const
    : null;
  const visiblePreview = preview ?? defaultPreview;
  const rootNode = layout.nodes.find((node) => node.resource.id === data.root_id)!;
  const rootBox = nested.boxes.find((box) => box.resource.id === data.root_id) ?? null;
  const presentationCoverage = useMemo(
    () => ontologyInstancePresentationCoverage(
      data,
      layout.nodes.map((node) => node.resource.id),
      [...layout.edges.map((edge) => edge.link), ...nested.absorbedLinks],
    ),
    [data, layout.edges, layout.nodes, nested.absorbedLinks],
  );
  const selectedLeft = rootBox?.x ?? rootNode.x;
  const selectedWidth = rootBox?.width ?? INSTANCE_NODE_WIDTH;
  const omittedByOwner = new Map(nested.boxes
    .filter((box) => box.omittedChildren > 0)
    .map((box) => [box.resource.id, box.omittedChildren]));

  const changeScale = (requestedScale: number, fit = false): void => {
    const scroll = graphScrollRef.current;
    if (!scroll) return;
    const nextScale = clampInstanceGraphScale(requestedScale, minScaleRef.current);
    if (nextScale === graphScaleRef.current && !fit) return;
    pendingScrollRef.current = fit
      ? { left: 0, top: 0 }
      : instanceGraphZoomScrollTarget({
          layout,
          scrollLeft: scroll.scrollLeft,
          scrollTop: scroll.scrollTop,
          viewportWidth: scroll.clientWidth,
          viewportHeight: scroll.clientHeight,
          currentScale: graphScaleRef.current,
          nextScale,
        });
    graphScaleRef.current = nextScale;
    setGraphScale(nextScale);
  };

  const startPan = (event: JSX.TargetedPointerEvent<HTMLDivElement>): void => {
    if (event.button !== 0 || !(event.target instanceof Element)) return;
    if (event.target.closest(".ontology-instance-node")) return;
    const scroll = event.currentTarget;
    panStateRef.current = {
      pointerId: event.pointerId,
      clientX: event.clientX,
      clientY: event.clientY,
      scrollLeft: scroll.scrollLeft,
      scrollTop: scroll.scrollTop,
    };
    scroll.setPointerCapture(event.pointerId);
    setIsPanning(true);
    event.preventDefault();
  };

  const movePan = (event: JSX.TargetedPointerEvent<HTMLDivElement>): void => {
    const pan = panStateRef.current;
    if (!pan || pan.pointerId !== event.pointerId) return;
    event.currentTarget.scrollLeft = pan.scrollLeft - (event.clientX - pan.clientX);
    event.currentTarget.scrollTop = pan.scrollTop - (event.clientY - pan.clientY);
    event.preventDefault();
  };

  const finishPan = (event: JSX.TargetedPointerEvent<HTMLDivElement>): void => {
    const pan = panStateRef.current;
    if (!pan || pan.pointerId !== event.pointerId) return;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    panStateRef.current = null;
    setIsPanning(false);
  };

  useEffect(() => {
    const sync = (): void => setFullscreen(document.fullscreenElement === graphRef.current);
    document.addEventListener("fullscreenchange", sync);
    return () => document.removeEventListener("fullscreenchange", sync);
  }, []);

  useEffect(() => {
    const scroll = graphScrollRef.current;
    if (!scroll) return;
    const initialScale = isAksRoot ? AKS_INITIAL_GRAPH_SCALE : 1;
    minScaleRef.current = initialScale;
    graphScaleRef.current = initialScale;
    setGraphScale(initialScale);
    const centerSelected = (): void => {
      const target = instanceGraphScrollTarget(
        layout,
        data.root_id,
        scroll.clientWidth,
        scroll.clientHeight,
        graphScaleRef.current,
        isAksRoot ? AKS_INITIAL_HORIZONTAL_ANCHOR : 0.5,
      );
      scroll.scrollLeft = target.left;
      scroll.scrollTop = target.top;
    };
    centerSelected();
    const observer = new ResizeObserver(centerSelected);
    observer.observe(scroll);
    return () => observer.disconnect();
  }, [data.root_id, isAksRoot, layout]);

  useEffect(() => {
    const scroll = graphScrollRef.current;
    const pending = pendingScrollRef.current;
    if (!scroll || !pending) return;
    const frame = requestAnimationFrame(() => {
      scroll.scrollLeft = pending.left;
      scroll.scrollTop = pending.top;
      pendingScrollRef.current = null;
    });
    return () => cancelAnimationFrame(frame);
  }, [graphScale]);

  const toggleFullscreen = async (): Promise<void> => {
    const graph = graphRef.current;
    if (!graph) return;
    if (document.fullscreenElement === graph) {
      await document.exitFullscreen();
      return;
    }
    if (document.fullscreenElement !== null) await document.exitFullscreen();
    await graph.requestFullscreen({ navigationUI: "hide" });
  };

  return (
    <div class="ontology-instance-graph" ref={graphRef}>
      <section
        class="ontology-instance-presentation-coverage"
        aria-label={t("ontology.instances.presentationCoverageTitle")}
      >
        <header>
          <strong>{t("ontology.instances.presentationCoverageTitle")}</strong>
          <span class={presentationCoverage.graphConsistent ? "is-complete" : "is-incomplete"}>
            {t(presentationCoverage.graphConsistent
              ? "ontology.instances.presentationCoverageConsistent"
              : "ontology.instances.presentationCoverageInconsistent")}
          </span>
        </header>
        <dl>
          <div>
            <dt>{t("ontology.instances.coverageResponse")}</dt>
            <dd>{t("ontology.instances.coverageResourceLinkCounts", {
              resources: formatNumber(presentationCoverage.responseResources),
              links: formatNumber(presentationCoverage.responseLinks),
            })}</dd>
          </div>
          <div>
            <dt>{t("ontology.instances.coverageFocusGraph")}</dt>
            <dd>{t("ontology.instances.coverageResourceLinkCounts", {
              resources: formatNumber(presentationCoverage.graphResources),
              links: formatNumber(presentationCoverage.graphLinks),
            })}</dd>
          </div>
          <div>
            <dt>{t("ontology.instances.coverageInspectorOnly")}</dt>
            <dd>{formatNumber(presentationCoverage.inspectorOnlyLinks)}</dd>
          </div>
          <div>
            <dt>{t("ontology.instances.coverageIamDelegated")}</dt>
            <dd>{t("ontology.instances.coverageResourceLinkCounts", {
              resources: formatNumber(presentationCoverage.delegatedResources),
              links: formatNumber(presentationCoverage.delegatedLinks),
            })}</dd>
          </div>
        </dl>
        {data.relationship_coverage ? (
          <p>
            {t("ontology.instances.sourceCandidateCoverage", {
              total: formatNumber(data.relationship_coverage.total_candidates),
              materialized: formatNumber(data.relationship_coverage.materialized),
              unavailable: formatNumber(data.relationship_coverage.reviewed_unavailable),
              unclassified: formatNumber(data.relationship_coverage.unclassified),
            })}
          </p>
        ) : null}
      </section>
      <p id="ontology-instance-map-description" class="sr-only">
        {t("ontology.instances.mapDescription", {
          depth: formatNumber(data.depth),
          graphResources: formatNumber(presentationCoverage.graphResources),
          presentationResources: formatNumber(presentationCoverage.presentationResources),
          graphLinks: formatNumber(presentationCoverage.graphLinks),
          presentationLinks: formatNumber(presentationCoverage.presentationLinks),
          responseResources: formatNumber(presentationCoverage.responseResources),
          responseLinks: formatNumber(presentationCoverage.responseLinks),
        })}
      </p>
      <div class="ontology-instance-graph-viewport">
        <div class="ontology-instance-legend-dock">
          <div class="ontology-instance-graph-key" aria-label={t("ontology.instances.graphLegend") }>
            <span><i class="is-direction" aria-hidden="true" />{t("ontology.instances.storedDirection")}</span>
            <span><i class="is-traffic" aria-hidden="true" />{t("ontology.instances.verifiedTrafficPath")}</span>
            <span><i class="is-runtime" aria-hidden="true" />{t("ontology.instances.runtimeContext")}</span>
            <span><i class="is-access" aria-hidden="true" />{t("ontology.instances.accessContext")}</span>
            <span><i class="is-containment" aria-hidden="true" />{t("ontology.instances.containmentContext")}</span>
          </div>
          {!showEdgeLabels ? (
            <div class="ontology-instance-dense-legend" aria-label={t("ontology.instances.relationshipTypes") }>
              <span>
                {t("ontology.instances.relationshipTypes")} ·{" "}
                {layout.edges.length + nested.absorbedLinks.length}/{data.links.length}
              </span>
              <ul id="ontology-instance-relationship-types">
                {visibleLinkTypeCounts.map((item) => (
                  <li key={item.linkType}>
                    <i class={`is-${item.linkType}`} aria-hidden="true" />
                    <strong>{t(`ontology.instances.link.${item.linkType}`)}</strong>
                    <span>{item.displayed}/{item.count}</span>
                  </li>
                ))}
              </ul>
              {hiddenLinkTypeCount > 0 ? (
                <button
                  type="button"
                  aria-controls="ontology-instance-relationship-types"
                  aria-expanded={showAllRelationshipTypes}
                  onClick={() => setShowAllRelationshipTypes((current) => !current)}
                >
                  {t(showAllRelationshipTypes
                    ? "ontology.instances.showBasicRelationshipTypes"
                    : "ontology.instances.showMoreRelationshipTypes", {
                      count: hiddenLinkTypeCount,
                    })}
                </button>
              ) : null}
            </div>
          ) : null}
        </div>
        <div class="ontology-instance-graph-tools" aria-label={t("ontology.instances.graphControls") }>
          <Tooltip content={t(fullscreen
            ? "ontology.instances.exitFullscreen"
            : "ontology.instances.fullscreen")}>
            <button
              type="button"
              aria-label={t(fullscreen
                ? "ontology.instances.exitFullscreen"
                : "ontology.instances.fullscreen")}
              aria-pressed={fullscreen}
              onClick={() => void toggleFullscreen()}
            >
              <span aria-hidden="true">{fullscreen ? "×" : "⛶"}</span>
            </button>
          </Tooltip>
        </div>
        <div
          class={`ontology-instance-graph-scroll${isPanning ? " is-panning" : ""}`}
          ref={graphScrollRef}
          aria-label={t("ontology.instances.graphViewport")}
          tabIndex={0}
          onPointerDown={startPan}
          onPointerMove={movePan}
          onPointerUp={finishPan}
          onPointerCancel={finishPan}
          onWheel={(event) => {
            event.preventDefault();
            changeScale(instanceGraphWheelScale(
              graphScaleRef.current,
              event.deltaY,
              minScaleRef.current,
            ));
          }}
        >
        <svg
          class={`ontology-instance-graph-canvas${focusedResourceId === null ? "" : " has-focus-path"}`}
          data-layout-direction={layout.direction}
          data-graph-scale={graphScale.toFixed(2)}
          viewBox={`0 0 ${layout.width} ${layout.height}`}
          role="group"
          aria-label={t("ontology.instances.graphTitle")}
          aria-describedby="ontology-instance-map-description"
          style={{
            width: `${layout.width * graphScale}px`,
            minWidth: `${layout.width * graphScale}px`,
            height: `${layout.height * graphScale}px`,
            minHeight: `${layout.height * graphScale}px`,
          }}
        >
          <defs>
            <marker id="ontology-instance-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto">
              <path d="M0 0L10 5L0 10z" />
            </marker>
          </defs>
          <g class="ontology-instance-direction-bands" aria-hidden="true">
            <rect class="is-incoming" x="0" y="0" width={selectedLeft} height={layout.height} />
            <rect class="is-selected" x={selectedLeft} y="0" width={selectedWidth} height={layout.height} />
            <rect class="is-outgoing" x={selectedLeft + selectedWidth} y="0" width={Math.max(0, layout.width - selectedLeft - selectedWidth)} height={layout.height} />
            <text x={Math.max(70, selectedLeft / 2)} y="19">
              {t("ontology.instances.graphTowardSelection")}
            </text>
            <text x={selectedLeft + selectedWidth / 2} y="19">{t(rootBox === null
              ? "ontology.instances.selectedResource"
              : "ontology.instances.selectedResourceAndContents")}</text>
            <text x={selectedLeft + selectedWidth + Math.max(70, (layout.width - selectedLeft - selectedWidth) / 2)} y="19">
              {t("ontology.instances.graphAwayFromSelection")}
            </text>
          </g>
          <g class="ontology-instance-boxes" aria-hidden="true">
            {nested.boxes.map((box) => (
              <g key={`box:${box.resource.id}`}>
                <rect
                  class="ontology-instance-box"
                  data-box-id={box.resource.id}
                  data-box-depth={box.depth}
                  x={box.x}
                  y={box.y}
                  width={box.width}
                  height={box.height}
                  rx="12"
                />
                {box.omittedChildren > 0 ? (
                  <text
                    class="ontology-instance-box-omitted"
                    x={box.x + box.width - 12}
                    y={box.y + box.height - 8}
                  >
                    {t("ontology.instances.nodeOmittedChildrenShort", {
                      count: String(box.omittedChildren),
                    })}
                  </text>
                ) : null}
              </g>
            ))}
          </g>
          {layout.edges.map((edge) => {
            const geometry = buildInstanceEdgeGeometry(
              edge.source,
              edge.target,
              edge.parallelOffset,
              edge.targetPortOffset,
              edge.longChannel,
              edge.link.link_type === "contains" ? "descend" : "side",
            );
            const trafficDirection = ontologyInstanceTrafficDirection(edge.link, data.root_id);
            const relationshipLabel = t(`ontology.instances.link.${edge.link.link_type}`);
            const label = trafficDirection === null
              ? relationshipLabel
              : `${relationshipLabel} - ${t(`ontology.instances.verified.${trafficDirection}`)}`;
            const onFocusedPath = focusedPath.has(edge.source.resource.id)
              && focusedPath.has(edge.target.resource.id)
              && (
                edge.source.parentId === edge.target.resource.id
                || edge.target.parentId === edge.source.resource.id
              );
            const showLabel = showEdgeLabels || edge.emphasis === "direct" || onFocusedPath;
            const sourceName = edge.source.resource.name ?? edge.source.resource.resource_type;
            const targetName = edge.target.resource.name ?? edge.target.resource.resource_type;
            return (
              <g
                key={`${edge.link.source}:${edge.link.link_type}:${edge.link.target}`}
                onPointerEnter={(event) => setGraphTooltip({
                  x: event.clientX + 12,
                  y: event.clientY + 12,
                  title: label,
                  detail: `${sourceName} -> ${targetName} - ${edge.link.evidence.mapping_id ?? t("ontology.instances.mappingNotReported")}`,
                })}
                onPointerMove={(event) => setGraphTooltip((current) => current === null ? null : {
                  ...current,
                  x: event.clientX + 12,
                  y: event.clientY + 12,
                })}
                onPointerLeave={() => setGraphTooltip(null)}
              >
                <path
                  class={`ontology-instance-edge is-${edge.link.link_type} is-${edge.emphasis} is-${edge.lane}-lane is-${edge.graphDirection}${trafficDirection === null ? "" : ` is-verified-${trafficDirection}`}${onFocusedPath ? " is-focus-path" : ""}`}
                  data-source-id={edge.link.source}
                  data-target-id={edge.link.target}
                  data-source-x={edge.source.x}
                  data-target-x={edge.target.x}
                  data-graph-direction={edge.graphDirection}
                  data-traffic-direction={trafficDirection ?? "unverified"}
                  d={geometry.path}
                />
                {showLabel ? (
                  <text
                    class={`ontology-instance-edge-label is-${edge.emphasis}${onFocusedPath ? " is-focus-path" : ""}`}
                    x={geometry.labelX}
                    y={geometry.labelY}
                  >
                    {label}
                  </text>
                ) : null}
              </g>
            );
          })}
          {layout.nodes.map((node) => {
            const resource = node.resource;
            const displayName = resource.name ?? resource.resource_type;
            const onFocusedPath = focusedPath.has(resource.id);
            const omittedChildren = omittedByOwner.get(resource.id) ?? 0;
            // A box that holds back children states it on the owner, not only as a drawn label.
            const nodeNotice = [
              node.occurrences > 1
                ? t("ontology.instances.nodeRepeated", { count: String(node.occurrences) })
                : null,
              omittedChildren > 0
                ? t("ontology.instances.nodeOmittedChildren", { count: String(omittedChildren) })
                : null,
            ].filter((notice): notice is string => notice !== null).join(", ") || null;
            const baseTypeCaption = node.clusterManaged
              ? t("ontology.instances.nodeClusterManaged", { type: resource.resource_type })
              : node.distance > 1
                ? t("ontology.instances.nodeIndirectHops", {
                  type: resource.resource_type,
                  count: String(node.distance),
                })
                : resource.resource_type;
            const capacityKind = ontologyInstanceCapacityKind(resource.resource_type);
            const capacityCaption = resource.capacity === null
              || resource.capacity === undefined
              || capacityKind === null
              ? null
              : capacityKind === "node"
                ? t("ontology.instances.nodeCountShort", {
                  count: formatNumber(resource.capacity),
                })
                : t("ontology.instances.instanceCountShort", {
                  count: formatNumber(resource.capacity),
                });
            const typeCaption = capacityCaption === null
              ? baseTypeCaption
              : `${baseTypeCaption} - ${capacityCaption}`;
            const state = ontologyInstanceNodeState(resource);
            const stateText = state
              ? `${recordedText(state.axis)}: ${recordedStateValueText(state.fact)}`
              : resource.status ?? t("ontology.instances.stateNotReported");
            const stateTone = state
              ? state.fact.freshness === "stale" || state.fact.conflicts.length > 0
                ? "warning"
                : "neutral"
              : ontologyInstanceStatusTone(resource.status);
            return (
              <g
                key={node.key}
                data-node-key={node.key}
                data-resource-id={resource.id}
                data-side={node.side}
                data-level={node.level}
                transform={`translate(${node.x} ${node.y})`}
              >
                <a
                  class={`ontology-instance-node is-${node.emphasis} is-${node.lane}-lane${nested.nestedIds.has(resource.id) ? " is-nested" : ""}${resource.id === data.root_id ? " is-selected" : ""}${onFocusedPath ? " is-focus-path" : ""}`}
                  href={routeHref("ontology", { params: { view: "instances", instance: resource.id } })}
                  aria-label={`${displayName}, ${typeCaption}, ${stateText}${nodeNotice ? `, ${nodeNotice}` : ""}`}
                  onPointerEnter={(event) => {
                    setFocusedResourceId(resource.id);
                    setGraphTooltip({
                      x: event.clientX + 12,
                      y: event.clientY + 12,
                      title: displayName,
                      detail: typeCaption,
                      status: stateText,
                      ...(nodeNotice ? { note: nodeNotice } : {}),
                    });
                  }}
                  onPointerMove={(event) => setGraphTooltip({
                    x: event.clientX + 12,
                    y: event.clientY + 12,
                    title: displayName,
                    detail: typeCaption,
                    status: stateText,
                    ...(nodeNotice ? { note: nodeNotice } : {}),
                  })}
                  onPointerLeave={() => {
                    setFocusedResourceId(null);
                    setGraphTooltip(null);
                  }}
                  onFocus={(event) => {
                    const rect = event.currentTarget.getBoundingClientRect();
                    setFocusedResourceId(resource.id);
                    setGraphTooltip({
                      x: rect.right + 8,
                      y: rect.top,
                      title: displayName,
                      detail: typeCaption,
                      status: stateText,
                      ...(nodeNotice ? { note: nodeNotice } : {}),
                    });
                  }}
                  onBlur={() => {
                    setFocusedResourceId(null);
                    setGraphTooltip(null);
                  }}
                  onClick={(event) => {
                    event.preventDefault();
                    onSelect(resource.id);
                  }}
                >
                  <rect width={INSTANCE_NODE_WIDTH} height={INSTANCE_NODE_HEIGHT} rx="5" />
                  <image href={ontologyInstanceIconForResourceType(resource.resource_type)} x="12" y="14" width="22" height="22" aria-hidden="true" />
                  {node.occurrences > 1 ? (
                    <g class="ontology-instance-node-repeat" aria-hidden="true">
                      <circle cx={INSTANCE_NODE_WIDTH - 12} cy="12" r="8" />
                      <text x={INSTANCE_NODE_WIDTH - 12} y="15" text-anchor="middle">
                        {`\u00d7${node.occurrences}`}
                      </text>
                    </g>
                  ) : null}
                  <foreignObject x="43" y="8" width="121" height="54" aria-hidden="true">
                    <div class="ontology-instance-node-copy">
                      <strong>{displayName}</strong>
                      <span>{typeCaption}</span>
                      <span class={`ontology-instance-node-state ontology-instance-state-badge is-${stateTone}`}>
                        {stateText}
                      </span>
                    </div>
                  </foreignObject>
                </a>
              </g>
            );
          })}
        </svg>
        </div>
      </div>
      <InstanceGraphTooltip state={graphTooltip} />
      <section class="ontology-instance-history" aria-labelledby="ontology-instance-history-title">
        <header>
          <div>
            <span>{t("ontology.instances.historyEyebrow")}</span>
            <h4 id="ontology-instance-history-title">{t("ontology.instances.historyTitle")}</h4>
          </div>
          <HistoryPreview preview={visiblePreview} />
        </header>
        <div class="ontology-instance-history-scroll">
          <div class="ontology-instance-history-chart">
            <div class="ontology-instance-history-axis" aria-hidden="true">
              <span>{formatShortTime(timeline.startAt)}</span>
              <span>{formatShortTime(new Date((Date.parse(timeline.startAt) + Date.parse(timeline.endAt)) / 2).toISOString())}</span>
              <span>{formatShortTime(timeline.endAt)}</span>
            </div>
            <div class="ontology-instance-history-row">
              <span>{t("ontology.instances.stateLane")}</span>
              <div class="ontology-instance-history-track">
                {timeline.segments.map((segment, index) => (
                  <button
                    key={`${segment.observedAt ?? "unknown"}:${index}`}
                    type="button"
                    class={`ontology-instance-state-segment${segment.state === null ? " is-unknown" : ""}`}
                    style={{ left: `${segment.start}%`, width: `${segment.width}%` }}
                    aria-label={segmentLabel(segment)}
                    onMouseEnter={() => setPreview({ kind: "segment", segment })}
                    onMouseLeave={() => setPreview(null)}
                    onFocus={() => setPreview({ kind: "segment", segment })}
                    onBlur={() => setPreview(null)}
                    onClick={() => setPreview({ kind: "segment", segment })}
                  >
                    {segment.width >= 9 ? segment.state ?? t("ontology.instances.unknownState") : ""}
                  </button>
                ))}
              </div>
            </div>
            <div class="ontology-instance-history-row">
              <span>{t("ontology.instances.eventLane")}</span>
              <div class="ontology-instance-history-track is-events">
                {timeline.events.map((event) => (
                  <button
                    key={event.activity.sequence}
                    type="button"
                    class="ontology-instance-event-marker"
                    style={{ left: `${event.position}%` }}
                    aria-label={`${formatDateTime(event.activity.recorded_at)} - ${event.summary} - ${t("ontology.instances.historyEventCount", { count: event.clusterSize })}`}
                    onMouseEnter={() => setPreview({ kind: "event", event })}
                    onMouseLeave={() => setPreview(null)}
                    onFocus={() => setPreview({ kind: "event", event })}
                    onBlur={() => setPreview(null)}
                    onClick={() => setPreview({ kind: "event", event })}
                  />
                ))}
              </div>
            </div>
          </div>
        </div>
        {!data.timeline.complete ? <p>{t("ontology.instances.timelineTruncated")}</p> : null}
      </section>
    </div>
  );
}

function InstanceGraphTooltip({ state }: { readonly state: InstanceGraphTooltipState | null }) {
  if (state === null || typeof document === "undefined") return null;
  const left = Math.max(16, Math.min(state.x, window.innerWidth - 336));
  const top = Math.max(16, Math.min(state.y, window.innerHeight - 112));
  return createPortal(
    <span
      role="tooltip"
      class="app-tooltip ontology-instance-graph-tooltip"
      data-state="instant-open"
      data-side="right"
      style={{ left: `${left}px`, top: `${top}px` }}
    >
      <strong>{state.title}</strong>
      <span>{state.detail}</span>
      {state.status ? <span>{state.status}</span> : null}
      {state.note ? <span>{state.note}</span> : null}
    </span>,
    document.body,
  );
}

function HistoryPreview({ preview }: { readonly preview: HistoryPreview | null }) {
  if (preview === null) {
    return (
      <div class="ontology-instance-history-preview" aria-live="polite">
        <strong>{t("ontology.instances.noEvents")}</strong>
        <span>{t("ontology.instances.noStateEvidence")}</span>
      </div>
    );
  }
  if (preview.kind === "segment") {
    const segment = preview.segment;
    return (
      <div class="ontology-instance-history-preview" aria-live="polite">
        <strong>{segment.state ?? t("ontology.instances.unknownState")}</strong>
        <span>{segment.observedAt ? formatDateTime(segment.observedAt) : t("ontology.instances.noStateEvidence")}</span>
        {segment.evidenceRef ? <code>{segment.evidenceRef}</code> : null}
      </div>
    );
  }
  const event = preview.event;
  return (
    <div class="ontology-instance-history-preview" aria-live="polite">
      <strong>{event.summary}</strong>
      <span>{formatDateTime(event.activity.recorded_at)} - {event.activity.actor} - {t("ontology.instances.historyEventCount", { count: event.clusterSize })}</span>
      <a href={routeHref("audit", {
        params: { from_seq: String(event.activity.sequence), through_seq: String(event.activity.sequence) },
      })}>{event.activity.evidence_ref}</a>
    </div>
  );
}

function segmentLabel(segment: InstanceTimelineSegment): string {
  const state = segment.state ?? t("ontology.instances.unknownState");
  return segment.observedAt ? `${state} - ${formatDateTime(segment.observedAt)}` : state;
}

function formatShortTime(value: string): string {
  return new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}
