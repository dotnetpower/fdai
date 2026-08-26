import {
  ontologyInstancePresentationLinks,
  type OntologyInstanceActivity,
  type OntologyInstanceExploration,
  type OntologyInstanceLink,
  type OntologyInstanceResource,
} from "./ontology-instances.model";

export interface InstanceGraphNode {
  readonly key: string;
  readonly resource: OntologyInstanceResource;
  readonly level: number;
  readonly distance: number;
  readonly emphasis: "root" | "direct" | "indirect";
  readonly lane: InstanceGraphLane;
  readonly side: InstanceGraphSide;
  readonly parentId: string | null;
  /** How many times this one Resource is drawn; layering repeats it to keep edges directed. */
  readonly occurrences: number;
  /** The selected cluster owns this Resource's lifecycle, so it is not a peer scope. */
  readonly clusterManaged: boolean;
  readonly x: number;
  readonly y: number;
}

export interface InstanceGraphEdge {
  readonly link: OntologyInstanceLink;
  readonly source: InstanceGraphNode;
  readonly target: InstanceGraphNode;
  readonly emphasis: "direct" | "indirect";
  readonly lane: InstanceGraphLane;
  readonly graphDirection: "incoming" | "outgoing" | "path";
  readonly parallelOffset: number;
  readonly targetPortOffset: number;
  readonly longChannel: "above" | "outer-above" | "below";
}

export type InstanceGraphLane = "traffic" | "dependency" | "runtime" | "access" | "containment";
export type InstanceGraphSide = "incoming" | "selected" | "outgoing";

export interface InstanceGraphLayout {
  readonly direction: "LR";
  readonly width: number;
  readonly height: number;
  readonly nodes: readonly InstanceGraphNode[];
  readonly edges: readonly InstanceGraphEdge[];
  readonly hiddenNodeCount: number;
  readonly hiddenEdgeCount: number;
}

export interface InstanceEdgeGeometry {
  readonly path: string;
  readonly labelX: number;
  readonly labelY: number;
}

export interface InstanceLinkTypeCount {
  readonly linkType: OntologyInstanceLink["link_type"];
  readonly count: number;
}

const DEFAULT_INSTANCE_LEGEND_LINK_TYPES = new Set<OntologyInstanceLink["link_type"]>([
  "attached_to",
  "contains",
  "depends_on",
]);

export interface InstanceGraphScrollTarget {
  readonly left: number;
  readonly top: number;
}

export interface InstanceGraphZoomRequest {
  readonly layout: InstanceGraphLayout;
  readonly scrollLeft: number;
  readonly scrollTop: number;
  readonly viewportWidth: number;
  readonly viewportHeight: number;
  readonly currentScale: number;
  readonly nextScale: number;
}

export interface InstanceTimelineEvent {
  readonly activity: OntologyInstanceActivity;
  readonly position: number;
  readonly summary: string;
  readonly state: string | null;
  readonly stateActivity: OntologyInstanceActivity | null;
  readonly clusterSize: number;
}

export interface InstanceTimelineSegment {
  readonly state: string | null;
  readonly start: number;
  readonly width: number;
  readonly observedAt: string | null;
  readonly evidenceRef: string | null;
}

export interface InstanceTimelineModel {
  readonly startAt: string;
  readonly endAt: string;
  readonly events: readonly InstanceTimelineEvent[];
  readonly segments: readonly InstanceTimelineSegment[];
}

export const INSTANCE_NODE_WIDTH = 176;
export const INSTANCE_NODE_HEIGHT = 68;
export const INSTANCE_GRAPH_MIN_SCALE = 0.1;
export const INSTANCE_GRAPH_MAX_SCALE = 1.8;
export const INSTANCE_GRAPH_SCALE_STEP = 0.2;
const INSTANCE_COLUMN_GAP = 112;
const INSTANCE_COLUMN_WIDTH = INSTANCE_NODE_WIDTH + INSTANCE_COLUMN_GAP;
const INSTANCE_FOCUS_MARGIN = 350;
// Rows are cheaper than columns: the viewport is taller than one column is wide.
const INSTANCE_MAX_ROWS = 10;
const INSTANCE_ROW_GAP = 12;
const INSTANCE_ROW_HEIGHT = INSTANCE_NODE_HEIGHT + INSTANCE_ROW_GAP;
const INSTANCE_INDIRECT_BRANCH_LIMIT = 3;
const INSTANCE_CONTAINMENT_ANCESTOR_LIMIT = 3;
// How much of a scope a root summarizes is a reading decision, not a row-packing one.
const INSTANCE_SCOPE_DIRECT_LIMIT = 7;
const INSTANCE_SCOPE_INTERNAL_LINK_LIMIT = 12;
const INSTANCE_AKS_VM_LIMIT_PER_SCALE_SET = 12;
const INSTANCE_AKS_NIC_LIMIT_PER_VM = 2;
const INSTANCE_KUBERNETES_NAMESPACE_CHILD_LIMIT = 6;
// A namespace contains far more than a viewport holds, so declared workloads outrank derived ones.
const INSTANCE_KUBERNETES_CHILD_PRIORITY: readonly string[] = [
  "kubernetes.deployment",
  "kubernetes.stateful-set",
  "kubernetes.daemon-set",
  "kubernetes.service",
  "kubernetes.cron-job",
  "kubernetes.job",
  "kubernetes.ingress",
  "kubernetes.pod",
];
const INSTANCE_OUTER_EDGE_CLEARANCE = 150;
// Attachment and containment must not read as one run of Resources in the same column.
const INSTANCE_CONTAINMENT_GROUP_GAP = 40;
const INSTANCE_NETWORK_CONTEXT_TYPES = new Set([
  "network.interface",
  "network.private-endpoint",
  "network.subnet",
  "network.vnet",
]);
// The chart is at least 600px wide, so 4.5% keeps 24px marker targets from overlapping.
const MIN_EVENT_MARKER_GAP_PERCENT = 4.5;

/** Keeps fixed relationship labels readable while every dense-graph edge path remains visible. */
export function showInstanceEdgeLabels(edgeCount: number): boolean {
  return edgeCount <= 20;
}

/** Counts stored relationship types deterministically for dense-graph summaries. */
export function countInstanceLinkTypes(
  links: readonly OntologyInstanceLink[],
): readonly InstanceLinkTypeCount[] {
  const counts = new Map<OntologyInstanceLink["link_type"], number>();
  links.forEach((link) => counts.set(link.link_type, (counts.get(link.link_type) ?? 0) + 1));
  return [...counts.entries()]
    .sort(([first], [second]) => first.localeCompare(second))
    .map(([linkType, count]) => ({ linkType, count }));
}

/** Selects the structural relationships shown before the dense legend is expanded. */
export function defaultInstanceLegendLinkTypes<T extends InstanceLinkTypeCount>(
  counts: readonly T[],
): readonly T[] {
  return counts.filter((item) => DEFAULT_INSTANCE_LEGEND_LINK_TYPES.has(item.linkType));
}

/** Centers one Resource while keeping the scroll target inside the graph canvas. */
export function instanceGraphScrollTarget(
  layout: InstanceGraphLayout,
  resourceId: string,
  viewportWidth: number,
  viewportHeight: number,
  scale = 1,
  horizontalAnchor = 0.5,
): InstanceGraphScrollTarget {
  const node = layout.nodes.find((item) => item.resource.id === resourceId);
  if (!node) return { left: 0, top: 0 };
  const scaledWidth = layout.width * scale;
  const scaledHeight = layout.height * scale;
  const boundedHorizontalAnchor = Math.max(0, Math.min(1, horizontalAnchor));
  return {
    left: Math.max(0, Math.min(
      scaledWidth - viewportWidth,
      (node.x + INSTANCE_NODE_WIDTH / 2) * scale - viewportWidth * boundedHorizontalAnchor,
    )),
    top: Math.max(0, Math.min(
      scaledHeight - viewportHeight,
      (node.y + INSTANCE_NODE_HEIGHT / 2) * scale - viewportHeight / 2,
    )),
  };
}

/** Clamps one operator-selected canvas scale to the supported readable range. */
export function clampInstanceGraphScale(
  scale: number,
  minScale: number = INSTANCE_GRAPH_MIN_SCALE,
): number {
  const floor = Math.max(INSTANCE_GRAPH_MIN_SCALE, Math.min(INSTANCE_GRAPH_MAX_SCALE, minScale));
  return Math.max(floor, Math.min(INSTANCE_GRAPH_MAX_SCALE, scale));
}

/** Fits the complete canvas into one viewport without enlarging above 100%. */
export function instanceGraphFitScale(
  layout: InstanceGraphLayout,
  viewportWidth: number,
  viewportHeight: number,
  padding = 32,
): number {
  const availableWidth = Math.max(1, viewportWidth - padding);
  const availableHeight = Math.max(1, viewportHeight - padding);
  return clampInstanceGraphScale(Math.min(
    1,
    availableWidth / layout.width,
    availableHeight / layout.height,
  ));
}

/** Preserves the current viewport center while changing the rendered canvas scale. */
export function instanceGraphZoomScrollTarget(
  request: InstanceGraphZoomRequest,
): InstanceGraphScrollTarget {
  const currentScale = clampInstanceGraphScale(request.currentScale);
  const nextScale = clampInstanceGraphScale(request.nextScale);
  const centerX = (request.scrollLeft + request.viewportWidth / 2) / currentScale;
  const centerY = (request.scrollTop + request.viewportHeight / 2) / currentScale;
  const scaledWidth = request.layout.width * nextScale;
  const scaledHeight = request.layout.height * nextScale;
  return {
    left: Math.max(0, Math.min(
      scaledWidth - request.viewportWidth,
      centerX * nextScale - request.viewportWidth / 2,
    )),
    top: Math.max(0, Math.min(
      scaledHeight - request.viewportHeight,
      centerY * nextScale - request.viewportHeight / 2,
    )),
  };
}

/** Maps one ordinary wheel direction to a single bounded graph zoom step. */
export function instanceGraphWheelScale(
  currentScale: number,
  deltaY: number,
  minScale?: number,
): number {
  if (deltaY === 0) return clampInstanceGraphScale(currentScale, minScale);
  return clampInstanceGraphScale(currentScale + (
    deltaY < 0 ? INSTANCE_GRAPH_SCALE_STEP : -INSTANCE_GRAPH_SCALE_STEP
  ), minScale);
}

/** Returns the deterministic shortest focus path from one rendered Resource to the root. */
export function instanceGraphPathNodeIds(
  nodes: readonly InstanceGraphNode[],
  resourceId: string,
): ReadonlySet<string> {
  const byId = new Map(nodes.map((node) => [node.resource.id, node]));
  const path = new Set<string>();
  let current: string | null = resourceId;
  while (current !== null && !path.has(current)) {
    path.add(current);
    current = byId.get(current)?.parentId ?? null;
  }
  return path;
}

/** Routes horizontal and same-column links without crossing a Resource node. */
export function buildInstanceEdgeGeometry(
  source: Pick<InstanceGraphNode, "x" | "y">,
  target: Pick<InstanceGraphNode, "x" | "y">,
  parallelOffset: number,
  targetPortOffset = 0,
  longChannel: "above" | "outer-above" | "below" = "above",
  orientation: "side" | "descend" = "side",
): InstanceEdgeGeometry {
  const sourceY = source.y + INSTANCE_NODE_HEIGHT / 2;
  const targetY = target.y + INSTANCE_NODE_HEIGHT / 2 + targetPortOffset;
  // Containment reads as a hierarchy, so it leaves the owner's underside rather than its side.
  if (orientation === "descend" && Math.abs(source.x - target.x) <= 300) {
    const sourceX = source.x + INSTANCE_NODE_WIDTH / 2 + parallelOffset;
    const sourceBottom = source.y + INSTANCE_NODE_HEIGHT;
    const movingRight = target.x >= source.x;
    const targetX = movingRight ? target.x : target.x + INSTANCE_NODE_WIDTH;
    const approach = movingRight ? -72 : 72;
    const dropY = sourceBottom + 36 + parallelOffset;
    return {
      path: `M${sourceX} ${sourceBottom} C${sourceX} ${dropY},${targetX + approach} ${targetY},${targetX} ${targetY}`,
      labelX: (sourceX + targetX) / 2,
      labelY: (dropY + targetY) / 2 - 8,
    };
  }
  if (Math.abs(source.x - target.x) > 300) {
    const movingRight = target.x > source.x;
    const sourceX = movingRight ? source.x + INSTANCE_NODE_WIDTH : source.x;
    const targetX = movingRight ? target.x : target.x + INSTANCE_NODE_WIDTH;
    const direction = movingRight ? 1 : -1;
    const targetControlInset = longChannel === "outer-above" ? 24 : 80;
    const channelY = longChannel === "below"
      ? Math.max(source.y + INSTANCE_NODE_HEIGHT, target.y + INSTANCE_NODE_HEIGHT)
        + 48 + parallelOffset + targetPortOffset
      : longChannel === "outer-above"
        ? Math.max(18, Math.min(source.y, target.y) - INSTANCE_OUTER_EDGE_CLEARANCE - parallelOffset)
        : Math.max(18, Math.min(source.y, target.y) - 48 - parallelOffset);
    return {
      path: `M${sourceX} ${sourceY} C${sourceX + direction * 80} ${channelY},${targetX - direction * targetControlInset} ${channelY},${targetX} ${targetY}`,
      labelX: (sourceX + targetX) / 2,
      labelY: channelY - 8,
    };
  }
  if (source.x === target.x) {
    const edgeX = source.x + INSTANCE_NODE_WIDTH;
    const channelX = edgeX + 24 + parallelOffset;
    return {
      path: `M${edgeX} ${sourceY} C${channelX} ${sourceY},${channelX} ${targetY},${edgeX} ${targetY}`,
      labelX: channelX,
      labelY: (sourceY + targetY) / 2 - 8,
    };
  }
  let sourceX = source.x + INSTANCE_NODE_WIDTH;
  let targetX = target.x;
  if (target.x < source.x) {
    sourceX = source.x;
    targetX = target.x + INSTANCE_NODE_WIDTH;
  }
  const middleX = (sourceX + targetX) / 2;
  const controlSourceY = sourceY + parallelOffset;
  const controlTargetY = targetY + parallelOffset;
  return {
    path: `M${sourceX} ${sourceY} C${middleX} ${controlSourceY},${middleX} ${controlTargetY},${targetX} ${targetY}`,
    labelX: middleX,
    labelY: (sourceY + targetY) / 2 + parallelOffset - 8,
  };
}

/** Builds deterministic signed ingress and egress levels from stored relationship direction. */
export function buildInstanceGraphLayout(data: OntologyInstanceExploration): InstanceGraphLayout {
  const root = data.resources.find((resource) => resource.id === data.root_id);
  if (!root) throw new Error("Ontology instance graph root is missing");
  const focus = instanceGraphFocus(data);
  const focusData = { ...data, resources: focus.resources, links: focus.links };
  const ranks = instanceGraphRanks(focusData);
  const occurrences = instanceGraphOccurrences(focusData, ranks);
  const resourcesByLevel = new Map<number, InstanceGraphOccurrence[]>();
  occurrences.nodes.forEach((occurrence) => {
    const resources = resourcesByLevel.get(occurrence.rank.level) ?? [];
    resources.push(occurrence);
    resourcesByLevel.set(occurrence.rank.level, resources);
  });
  // Containment by some distant scope is not what this column shows: only the owner drawn here.
  const containedIds = new Set(focus.links
    .filter((link) =>
      link.link_type === "contains" && ranks.get(link.target)?.parentId === link.source)
    .map((link) => link.target));
  resourcesByLevel.forEach((resources) => resources.sort((first, second) =>
    Number(containedIds.has(first.resource.id)) - Number(containedIds.has(second.resource.id))
    ||
    graphLaneOrder(first.rank.lane) - graphLaneOrder(second.rank.lane)
    ||
    (first.rank.parentId ?? "").localeCompare(second.rank.parentId ?? "")
    ||
    (first.resource.name ?? first.resource.resource_type).localeCompare(
      second.resource.name ?? second.resource.resource_type,
    )
    || first.key.localeCompare(second.key)));
  const orderedLevels = [...resourcesByLevel].sort(([first], [second]) => first - second);
  const columnsByLevel = new Map(orderedLevels.map(([level, resources]) => [
    level,
    Math.max(1, Math.ceil(resources.length / INSTANCE_MAX_ROWS)),
  ]));
  const columnCount = [...columnsByLevel.values()].reduce((total, count) => total + count, 0);
  const packedWidth = 40 + columnCount * INSTANCE_COLUMN_WIDTH - INSTANCE_COLUMN_GAP;
  const baseWidth = Math.max(700, packedWidth);
  const contentOffset = Math.max(0, (baseWidth - packedWidth) / 2);
  const rootColumn = orderedLevels
    .filter(([level]) => level < 0)
    .reduce((total, [level]) => total + columnsByLevel.get(level)!, 0);
  const rootCenter = 20 + contentOffset + rootColumn * INSTANCE_COLUMN_WIDTH
    + INSTANCE_NODE_WIDTH / 2;
  const focusMargin = columnCount > 4 ? 600 : INSTANCE_FOCUS_MARGIN;
  const leadingGutter = Math.max(0, focusMargin - rootCenter);
  const trailingGutter = Math.max(0, focusMargin - (baseWidth - rootCenter));
  const width = baseWidth + leadingGutter + trailingGutter;
  const rowCount = Math.max(
    ...orderedLevels.map(([, resources]) => Math.min(INSTANCE_MAX_ROWS, resources.length)),
    1,
  );
  const groupedLevel = orderedLevels.some(([, resources]) =>
    resources.some((occurrence) => containedIds.has(occurrence.resource.id))
    && resources.some((occurrence) => !containedIds.has(occurrence.resource.id)));
  const height = Math.max(568, 40 + rowCount * INSTANCE_ROW_HEIGHT)
    + (groupedLevel ? INSTANCE_CONTAINMENT_GROUP_GAP : 0);
  let columnCursor = leadingGutter + 20 + contentOffset;
  const occurrenceCounts = new Map<string, number>();
  occurrences.nodes.forEach((occurrence) => {
    const id = occurrence.resource.id;
    occurrenceCounts.set(id, (occurrenceCounts.get(id) ?? 0) + 1);
  });
  const clusterManagedIds = new Set(focus.links
    .filter((link) =>
      link.source === data.root_id
      && link.evidence.mapping_id === "azure.aks-attached-to-node-resource-group")
    .map((link) => link.target));
  // Levels advance left to right, so an owner already has a row when its children are placed.
  const ownerY = new Map<string, number>();
  const nodes = orderedLevels.flatMap(([level, resources]) => {
    const levelColumns = columnsByLevel.get(level)!;
    const parentRow = (occurrence: InstanceGraphOccurrence): number =>
      occurrence.rank.parentId === null
        ? Number.MAX_SAFE_INTEGER
        : ownerY.get(occurrence.rank.parentId) ?? Number.MAX_SAFE_INTEGER;
    const ordered = [...resources].sort((first, second) =>
      Number(containedIds.has(first.resource.id)) - Number(containedIds.has(second.resource.id))
      || graphLaneOrder(first.rank.lane) - graphLaneOrder(second.rank.lane)
      || parentRow(first) - parentRow(second)
      || (first.rank.parentId ?? "").localeCompare(second.rank.parentId ?? "")
      || (first.resource.name ?? first.resource.resource_type).localeCompare(
        second.resource.name ?? second.resource.resource_type,
      )
      || first.key.localeCompare(second.key));
    const positioned = columnNodes(
      ordered,
      level,
      columnCursor,
      levelColumns,
      height,
      occurrenceCounts,
      clusterManagedIds,
      containedIds,
    );
    positioned.forEach((node) => {
      if (!ownerY.has(node.resource.id)) ownerY.set(node.resource.id, node.y);
    });
    columnCursor += levelColumns * INSTANCE_COLUMN_WIDTH;
    return positioned;
  });
  // The owner has to sit above what it contains for the underside port to read as ownership.
  const rootContainedTop = Math.min(...nodes
    .filter((node) => node.parentId === data.root_id && containedIds.has(node.resource.id))
    .map((node) => node.y));
  const placedNodes = Number.isFinite(rootContainedTop)
    ? nodes.map((node) => node.resource.id === data.root_id
      ? {
        ...node,
        y: Math.max(24, Math.min(
          rootContainedTop - INSTANCE_ROW_HEIGHT,
          height - INSTANCE_NODE_HEIGHT - 24,
        )),
      }
      : node)
    : nodes;
  const byId = new Map(placedNodes.map((node) => [node.key, node]));
  const parallelCounts = new Map<string, number>();
  focus.links.forEach((link) => {
    const key = edgePairKey(link);
    parallelCounts.set(key, (parallelCounts.get(key) ?? 0) + 1);
  });
  const parallelIndexes = new Map<string, number>();
  const aksEdgeRouting = aksOutboundEdgeRouting(focusData);
  const edges = focus.links.flatMap((link) => {
    const assignment = occurrences.edges.get(instanceGraphLinkKey(link));
    const source = assignment ? byId.get(assignment.sourceKey) : undefined;
    const target = assignment ? byId.get(assignment.targetKey) : undefined;
    if (!source || !target) return [];
    const key = edgePairKey(link);
    const index = parallelIndexes.get(key) ?? 0;
    parallelIndexes.set(key, index + 1);
    const count = parallelCounts.get(key) ?? 1;
    const routing = aksEdgeRouting.get(instanceGraphLinkKey(link));
    const targetPortOffset = routing?.targetPortOffset ?? 0;
    return [{
      link,
      source,
      target,
      emphasis: source.distance === 0 || target.distance === 0 ? "direct" as const : "indirect" as const,
      lane: instanceGraphLinkLane(link),
      graphDirection: link.target === data.root_id
        ? "incoming" as const
        : link.source === data.root_id ? "outgoing" as const : "path" as const,
      parallelOffset: (index - (count - 1) / 2) * 16,
      targetPortOffset,
      longChannel: routing?.longChannel ?? "above",
    }];
  });
  return {
    direction: "LR",
    width,
    height,
    nodes: placedNodes,
    edges,
    hiddenNodeCount: data.resources.length
      - new Set(placedNodes.map((node) => node.resource.id)).size,
    hiddenEdgeCount: data.links.length - focus.links.length,
  };
}

/** Assigns root-focused signed distance without rewriting stored edge direction. */
export function instanceGraphLevels(
  data: OntologyInstanceExploration,
): ReadonlyMap<string, number> {
  return new Map([...instanceGraphRanks(data)].map(([id, rank]) => [id, rank.level]));
}

interface InstanceGraphRank {
  readonly level: number;
  readonly distance: number;
  readonly lane: InstanceGraphLane;
  readonly parentId: string | null;
}

interface InstanceGraphOccurrence {
  readonly key: string;
  readonly resource: OntologyInstanceResource;
  readonly rank: InstanceGraphRank;
}

interface InstanceGraphEdgeOccurrence {
  readonly sourceKey: string;
  readonly targetKey: string;
}

function instanceGraphOccurrences(
  data: OntologyInstanceExploration,
  ranks: ReadonlyMap<string, InstanceGraphRank>,
): {
  readonly nodes: readonly InstanceGraphOccurrence[];
  readonly edges: ReadonlyMap<string, InstanceGraphEdgeOccurrence>;
} {
  const resources = new Map(data.resources.map((resource) => [resource.id, resource]));
  const nodes = new Map<string, InstanceGraphOccurrence>();
  const byResource = new Map<string, InstanceGraphOccurrence[]>();
  const addOccurrence = (
    resourceId: string,
    rank: InstanceGraphRank,
  ): InstanceGraphOccurrence => {
    const key = occurrenceKey(resourceId, rank.level);
    const existing = nodes.get(key);
    if (existing) return existing;
    const resource = resources.get(resourceId);
    if (!resource) throw new Error("Ontology instance graph occurrence Resource is missing");
    const occurrence = { key, resource, rank };
    nodes.set(key, occurrence);
    const resourceOccurrences = byResource.get(resourceId) ?? [];
    resourceOccurrences.push(occurrence);
    byResource.set(resourceId, resourceOccurrences);
    return occurrence;
  };

  ranks.forEach((rank, resourceId) => addOccurrence(resourceId, rank));
  data.links.forEach((link) => {
    if (link.link_type === "peered_with") return;
    const lane = instanceGraphLinkLane(link);
    const levelStep = lane === "containment" ? 2 : 1;
    if (link.target === data.root_id) {
      const existing = ranks.get(link.source);
      addOccurrence(link.source, {
        level: existing && existing.level < 0 ? existing.level : -levelStep,
        distance: 1,
        lane,
        parentId: data.root_id,
      });
    }
    if (link.source === data.root_id) {
      const existing = ranks.get(link.target);
      addOccurrence(link.target, {
        level: existing && existing.level > 0 ? existing.level : levelStep,
        distance: 1,
        lane,
        parentId: data.root_id,
      });
    }
  });

  const edges = new Map<string, InstanceGraphEdgeOccurrence>();
  [...data.links].sort(compareInstanceGraphLinks).forEach((link) => {
    let sourceCandidates = byResource.get(link.source) ?? [];
    let targetCandidates = byResource.get(link.target) ?? [];
    const reverseForNetworkHierarchy = isReverseNetworkPresentationLink(link, resources);
    const coLocatedVmssNic = link.evidence.mapping_id
      === "azure.vm-scale-set-nic-attached-to-vm";
    const selectPair = link.link_type === "peered_with"
      ? closestSeparatedPair
      : coLocatedVmssNic
        ? closestSameLevelPair
        : reverseForNetworkHierarchy ? closestRightToLeftPair : closestLeftToRightPair;
    let pair = selectPair(sourceCandidates, targetCandidates);
    if (!pair) {
      const anchorCandidates = reverseForNetworkHierarchy ? targetCandidates : sourceCandidates;
      const anchor = [...anchorCandidates].sort(compareOccurrences)[0];
      if (!anchor) throw new Error("Ontology instance graph edge anchor is missing");
      const candidateLevel = anchor.rank.level + 1;
      addOccurrence(reverseForNetworkHierarchy ? link.source : link.target, {
        level: candidateLevel === 0 ? 1 : candidateLevel,
        distance: anchor.rank.distance + 1,
        lane: instanceGraphLinkLane(link),
        parentId: anchor.resource.id,
      });
      sourceCandidates = byResource.get(link.source) ?? [];
      targetCandidates = byResource.get(link.target) ?? [];
      pair = selectPair(sourceCandidates, targetCandidates);
    }
    if (!pair) throw new Error("Ontology instance graph edge cannot satisfy presentation direction");
    edges.set(instanceGraphLinkKey(link), {
      sourceKey: pair[0].key,
      targetKey: pair[1].key,
    });
  });
  return { nodes: [...nodes.values()], edges };
}

function closestLeftToRightPair(
  sources: readonly InstanceGraphOccurrence[],
  targets: readonly InstanceGraphOccurrence[],
): readonly [InstanceGraphOccurrence, InstanceGraphOccurrence] | null {
  const pairs = sources.flatMap((source) => targets.flatMap((target) =>
    source.rank.level < target.rank.level ? [[source, target] as const] : []));
  return pairs.sort((first, second) =>
    Math.abs(first[0].rank.level) + Math.abs(first[1].rank.level)
      - Math.abs(second[0].rank.level) - Math.abs(second[1].rank.level)
    || first[0].rank.level - second[0].rank.level
    || first[1].rank.level - second[1].rank.level
    || first[0].key.localeCompare(second[0].key)
    || first[1].key.localeCompare(second[1].key))[0] ?? null;
}

function closestRightToLeftPair(
  sources: readonly InstanceGraphOccurrence[],
  targets: readonly InstanceGraphOccurrence[],
): readonly [InstanceGraphOccurrence, InstanceGraphOccurrence] | null {
  const pairs = sources.flatMap((source) => targets.flatMap((target) =>
    source.rank.level > target.rank.level ? [[source, target] as const] : []));
  return pairs.sort((first, second) =>
    Math.abs(first[0].rank.level) + Math.abs(first[1].rank.level)
      - Math.abs(second[0].rank.level) - Math.abs(second[1].rank.level)
    || first[1].rank.level - second[1].rank.level
    || first[0].rank.level - second[0].rank.level
    || first[0].key.localeCompare(second[0].key)
    || first[1].key.localeCompare(second[1].key))[0] ?? null;
}

function closestSameLevelPair(
  sources: readonly InstanceGraphOccurrence[],
  targets: readonly InstanceGraphOccurrence[],
): readonly [InstanceGraphOccurrence, InstanceGraphOccurrence] | null {
  const pairs = sources.flatMap((source) => targets.flatMap((target) =>
    source.rank.level === target.rank.level ? [[source, target] as const] : []));
  return pairs.sort((first, second) =>
    Math.abs(first[0].rank.level) - Math.abs(second[0].rank.level)
    || first[0].key.localeCompare(second[0].key)
    || first[1].key.localeCompare(second[1].key))[0] ?? null;
}

function closestSeparatedPair(
  sources: readonly InstanceGraphOccurrence[],
  targets: readonly InstanceGraphOccurrence[],
): readonly [InstanceGraphOccurrence, InstanceGraphOccurrence] | null {
  const pairs = sources.flatMap((source) => targets.flatMap((target) =>
    source.rank.level !== target.rank.level ? [[source, target] as const] : []));
  return pairs.sort((first, second) =>
    Math.abs(first[0].rank.level - first[1].rank.level)
      - Math.abs(second[0].rank.level - second[1].rank.level)
    || Math.abs(first[0].rank.level) + Math.abs(first[1].rank.level)
      - Math.abs(second[0].rank.level) - Math.abs(second[1].rank.level)
    || first[0].key.localeCompare(second[0].key)
    || first[1].key.localeCompare(second[1].key))[0] ?? null;
}

function compareOccurrences(
  first: InstanceGraphOccurrence,
  second: InstanceGraphOccurrence,
): number {
  return first.rank.distance - second.rank.distance
    || Math.abs(first.rank.level) - Math.abs(second.rank.level)
    || first.rank.level - second.rank.level
    || first.key.localeCompare(second.key);
}

function occurrenceKey(resourceId: string, level: number): string {
  return `${resourceId}\u0000${level}`;
}

function instanceGraphRanks(
  data: OntologyInstanceExploration,
): ReadonlyMap<string, InstanceGraphRank> {
  const resourcesById = new Map(data.resources.map((resource) => [resource.id, resource]));
  const ranks = new Map<string, InstanceGraphRank>([[
    data.root_id,
    { level: 0, distance: 0, lane: "dependency", parentId: null },
  ]]);
  const adjacency = new Map<string, {
    readonly id: string;
    readonly direction: -1 | 1;
    readonly lane: InstanceGraphLane;
  }[]>();
  [...data.links]
    .sort((first, second) =>
      first.source.localeCompare(second.source)
      || first.target.localeCompare(second.target)
      || first.link_type.localeCompare(second.link_type))
    .forEach((link) => {
      const lane = instanceGraphLinkLane(link);
      const outgoing = adjacency.get(link.source) ?? [];
      outgoing.push({ id: link.target, direction: 1, lane });
      adjacency.set(link.source, outgoing);
      const incoming = adjacency.get(link.target) ?? [];
      incoming.push({ id: link.source, direction: -1, lane });
      adjacency.set(link.target, incoming);
    });
  const queue = [data.root_id];
  while (queue.length > 0) {
    const current = queue.shift()!;
    const currentRank = ranks.get(current)!;
    if (
      current !== data.root_id
      && isScopeResourceType(resourcesById.get(current)?.resource_type)
    ) {
      continue;
    }
    for (const neighbor of adjacency.get(current) ?? []) {
      if (ranks.has(neighbor.id)) continue;
      const distance = currentRank.distance + 1;
      const levelStep = currentRank.distance === 0 && neighbor.lane === "containment" ? 2 : 1;
      const candidateLevel = currentRank.level + neighbor.direction * levelStep;
      const level = candidateLevel === 0 ? neighbor.direction : candidateLevel;
      ranks.set(neighbor.id, {
        level,
        distance,
        lane: currentRank.distance === 0
          ? neighbor.lane
          : currentRank.lane === "access" || neighbor.lane === "access"
            ? "access"
            : "dependency",
        parentId: current,
      });
      queue.push(neighbor.id);
    }
  }
  stabilizeAcyclicGraphRanks(data, ranks);
  applyNetworkPresentationRanks(data, ranks);
  applyAksPresentationRanks(data, ranks);
  const outerLevel = Math.max(1, ...[...ranks.values()].map((rank) => Math.abs(rank.level))) + 1;
  data.resources
    .filter((resource) => !ranks.has(resource.id))
    .sort((first, second) => first.id.localeCompare(second.id))
    .forEach((resource) => ranks.set(resource.id, {
      level: outerLevel,
      distance: outerLevel,
      lane: "access",
      parentId: null,
    }));
  return ranks;
}

function stabilizeAcyclicGraphRanks(
  data: OntologyInstanceExploration,
  ranks: Map<string, InstanceGraphRank>,
): void {
  const resourcesById = new Map(data.resources.map((resource) => [resource.id, resource]));
  const directed = new Map<string, string[]>();
  data.links.forEach((link) => {
    const targets = directed.get(link.source) ?? [];
    targets.push(link.target);
    directed.set(link.source, targets);
  });
  directed.forEach((targets) => targets.sort());
  const acyclicLinks = [...data.links]
    .filter((link) =>
      link.link_type !== "peered_with"
      &&
      !isReverseNetworkPresentationLink(link, resourcesById)
      && !hasDirectedPath(link.target, link.source, directed))
    .sort(compareInstanceGraphLinks);
  const semanticConstraints = networkSemanticConstraints(data);
  for (let pass = 0; pass < data.resources.length; pass++) {
    let changed = false;
    for (const constraint of [
      ...acyclicLinks.map((link) => ({ sourceId: link.source, targetId: link.target })),
      ...semanticConstraints,
    ]) {
      const source = ranks.get(constraint.sourceId);
      const target = ranks.get(constraint.targetId);
      if (!source || !target || source.level < target.level) continue;
      if (source.level >= 0 && target.level > 0 && constraint.targetId !== data.root_id) {
        ranks.set(constraint.targetId, { ...target, level: source.level + 1 });
        changed = true;
      } else if (
        source.level < 0
        && target.level <= 0
        && constraint.sourceId !== data.root_id
      ) {
        ranks.set(constraint.sourceId, { ...source, level: target.level - 1 });
        changed = true;
      }
    }
    if (!changed) return;
  }
}

function networkSemanticConstraints(
  data: OntologyInstanceExploration,
): readonly { readonly sourceId: string; readonly targetId: string }[] {
  const resourcesById = new Map(data.resources.map((resource) => [resource.id, resource]));
  const vnetsBySubnet = new Map<string, string[]>();
  const privateEndpointsBySubnet = new Map<string, string[]>();
  data.links.forEach((link) => {
    const sourceType = resourcesById.get(link.source)?.resource_type;
    const targetType = resourcesById.get(link.target)?.resource_type;
    if (
      link.link_type === "contains"
      && sourceType === "network.vnet"
      && targetType === "network.subnet"
    ) {
      const vnets = vnetsBySubnet.get(link.target) ?? [];
      vnets.push(link.source);
      vnetsBySubnet.set(link.target, vnets);
    } else if (
      link.link_type === "attached_to"
      && sourceType === "network.private-endpoint"
      && targetType === "network.subnet"
    ) {
      const endpoints = privateEndpointsBySubnet.get(link.target) ?? [];
      endpoints.push(link.source);
      privateEndpointsBySubnet.set(link.target, endpoints);
    }
  });
  const constraints: { sourceId: string; targetId: string }[] = [];
  [...vnetsBySubnet].sort(([first], [second]) => first.localeCompare(second))
    .forEach(([subnetId, vnets]) => {
      const endpoints = privateEndpointsBySubnet.get(subnetId) ?? [];
      vnets.sort().forEach((vnetId) => endpoints.sort().forEach((endpointId) => {
        constraints.push({ sourceId: vnetId, targetId: endpointId });
      }));
    });
  return constraints;
}

function applyNetworkPresentationRanks(
  data: OntologyInstanceExploration,
  ranks: Map<string, InstanceGraphRank>,
): void {
  const branch = selectedNetworkBranch(data);
  const rootType = branch.resourcesById.get(data.root_id)?.resource_type;
  const setRank = (
    resourceId: string,
    level: number,
    parentId: string | null,
    lane: InstanceGraphLane,
  ): void => {
    const rank = ranks.get(resourceId);
    if (!rank) return;
    ranks.set(resourceId, { ...rank, level, lane, parentId });
  };

  if (rootType === "network.vnet") {
    branch.subnets.forEach((subnetId) => setRank(subnetId, 1, data.root_id, "containment"));
    branch.privateEndpoints.forEach((endpointId) => {
      const subnetId = branch.subnetByPrivateEndpoint.get(endpointId) ?? data.root_id;
      setRank(endpointId, 2, subnetId, "access");
    });
    branch.networkInterfaces.forEach((interfaceId) => {
      const endpointId = branch.privateEndpointByInterface.get(interfaceId);
      const subnetId = branch.subnetByInterface.get(interfaceId);
      setRank(interfaceId, endpointId ? 3 : 2, endpointId ?? subnetId ?? data.root_id, "access");
    });
    return;
  }

  const subnetLevel = rootType === "network.subnet"
    ? 0
    : rootType === "network.private-endpoint" ? -1 : -2;
  branch.subnets.forEach((subnetId) => {
    const parentId = branch.privateEndpoints.find((endpointId) =>
      branch.subnetByPrivateEndpoint.get(endpointId) === subnetId) ?? data.root_id;
    setRank(subnetId, subnetLevel, parentId, "access");
  });
  branch.vnets.forEach((vnetId) => {
    const subnetId = branch.subnets.find((id) => branch.vnetBySubnet.get(id) === vnetId);
    setRank(vnetId, subnetLevel - 1, subnetId ?? data.root_id, "containment");
  });
  branch.privateEndpoints.forEach((endpointId) => {
    if (endpointId !== data.root_id) setRank(endpointId, subnetLevel + 1, data.root_id, "access");
  });
  branch.networkInterfaces.forEach((interfaceId) => {
    const endpointId = branch.privateEndpointByInterface.get(interfaceId) ?? data.root_id;
    setRank(interfaceId, subnetLevel + 2, endpointId, "access");
  });
  branch.vnets.forEach((vnetId) => {
    data.links.filter((link) =>
      link.link_type === "contains"
      && link.target === vnetId
      && isScopeResourceType(branch.resourcesById.get(link.source)?.resource_type))
      .forEach((link) => setRank(link.source, subnetLevel - 2, vnetId, "containment"));
  });
}

function applyAksPresentationRanks(
  data: OntologyInstanceExploration,
  ranks: Map<string, InstanceGraphRank>,
): void {
  const resourcesById = new Map(data.resources.map((resource) => [resource.id, resource]));
  if (resourcesById.get(data.root_id)?.resource_type !== "kubernetes-cluster") return;
  const nodeGroupLink = [...data.links].sort(compareInstanceGraphLinks).find((link) =>
    link.source === data.root_id
    && link.link_type === "attached_to"
    && link.evidence.mapping_id === "azure.aks-attached-to-node-resource-group"
    && resourcesById.get(link.target)?.resource_type === "resource-group");
  if (!nodeGroupLink) return;

  const nodeGroupId = nodeGroupLink.target;
  const childLinks = data.links.filter((link) =>
    link.source === nodeGroupId
    && link.link_type === "contains");
  const childIds = new Set(childLinks.map((link) => link.target));
  const childLevels = new Map([...childIds].map((id) => [id, 2]));
  const childParents = new Map([...childIds].map((id) => [id, nodeGroupId]));
  const childLanes = new Map<string, InstanceGraphLane>(
    [...childIds].map((id) => [id, "containment"]),
  );
  const internalAdjacency = new Map<string, string[]>();
  const internalLinks = data.links.filter((link) =>
    childIds.has(link.source)
    && childIds.has(link.target)
    && link.link_type !== "contains"
    && link.link_type !== "peered_with");
  internalLinks.forEach((link) => {
    const targets = internalAdjacency.get(link.source) ?? [];
    targets.push(link.target);
    internalAdjacency.set(link.source, targets);
  });
  const acyclicInternalLinks = internalLinks
    .filter((link) => !hasDirectedPath(link.target, link.source, internalAdjacency))
    .sort(compareInstanceGraphLinks);
  for (let pass = 0; pass < childIds.size; pass += 1) {
    let changed = false;
    acyclicInternalLinks.forEach((link) => {
      const sourceLevel = childLevels.get(link.source);
      const targetLevel = childLevels.get(link.target);
      if (sourceLevel === undefined || targetLevel === undefined || sourceLevel < targetLevel) return;
      childLevels.set(link.target, sourceLevel + 1);
      childParents.set(link.target, link.source);
      childLanes.set(link.target, instanceGraphLinkLane(link));
      changed = true;
    });
    if (!changed) break;
  }
  const nodeGroupRank = ranks.get(nodeGroupId);
  if (nodeGroupRank) {
    ranks.set(nodeGroupId, {
      ...nodeGroupRank,
      level: 1,
      distance: 1,
      lane: "access",
      parentId: data.root_id,
    });
  }
  childLevels.forEach((level, childId) => {
    const rank = ranks.get(childId) ?? {
      level,
      distance: level,
      lane: "containment" as const,
      parentId: nodeGroupId,
    };
    ranks.set(childId, {
      ...rank,
      level,
      distance: 1,
      lane: childLanes.get(childId) ?? "containment",
      parentId: childParents.get(childId) ?? nodeGroupId,
    });
  });
  data.links.filter((link) =>
    childIds.has(link.source)
    && link.link_type === "contains"
    && link.evidence.mapping_id === "azure.vm-scale-set-contains-vm")
    .sort(compareInstanceGraphLinks)
    .forEach((vmLink) => {
      const vmLevel = (childLevels.get(vmLink.source) ?? 2) + 1;
      const vmRank = ranks.get(vmLink.target) ?? {
        level: vmLevel,
        distance: vmLevel,
        lane: "containment" as const,
        parentId: vmLink.source,
      };
      ranks.set(vmLink.target, {
        ...vmRank,
        level: vmLevel,
        distance: 1,
        lane: "containment",
        parentId: vmLink.source,
      });
      data.links.filter((link) =>
        link.target === vmLink.target
        && link.link_type === "attached_to"
        && link.evidence.mapping_id === "azure.vm-scale-set-nic-attached-to-vm")
        .sort(compareInstanceGraphLinks)
        .forEach((nicLink) => {
          const nicRank = ranks.get(nicLink.source) ?? {
            level: vmLevel,
            distance: vmLevel + 1,
            lane: "access" as const,
            parentId: vmLink.target,
          };
          ranks.set(nicLink.source, {
            ...nicRank,
            level: vmLevel,
            distance: 1,
            lane: "access",
            parentId: vmLink.target,
          });
        });
    });
}

function aksOutboundEdgeRouting(
  data: OntologyInstanceExploration,
): ReadonlyMap<string, {
  readonly targetPortOffset: number;
  readonly longChannel: "above" | "outer-above" | "below";
}> {
  const resourcesById = new Map(data.resources.map((resource) => [resource.id, resource]));
  if (resourcesById.get(data.root_id)?.resource_type !== "kubernetes-cluster") return new Map();
  const nodeGroupLink = data.links.find((link) =>
    link.source === data.root_id
    && link.link_type === "attached_to"
    && link.evidence.mapping_id === "azure.aks-attached-to-node-resource-group"
    && resourcesById.get(link.target)?.resource_type === "resource-group");
  if (!nodeGroupLink) return new Map();

  const routing = new Map<string, {
    readonly targetPortOffset: number;
    readonly longChannel: "above" | "outer-above" | "below";
  }>();
  data.links.filter((link) =>
    link.source === data.root_id
    && link.link_type === "routes_to"
    && link.evidence.status === "available"
    && link.evidence.complete
    && link.evidence.mapping_id === "azure.aks-routes-to-effective-outbound-ip"
    && resourcesById.get(link.target)?.resource_type === "network.public-ip")
    .sort(compareInstanceGraphLinks)
    .forEach((outboundLink) => {
      const loadBalancerLink = data.links.find((link) =>
        link.target === outboundLink.target
        && link.link_type === "attached_to"
        && link.evidence.status === "available"
        && link.evidence.complete
        && link.evidence.mapping_id === "azure.load-balancer-attached-to-public-ip"
        && resourcesById.get(link.source)?.resource_type === "network.load-balancer");
      const containmentLink = data.links.find((link) =>
        link.source === nodeGroupLink.target
        && link.target === outboundLink.target
        && link.link_type === "contains"
        && link.evidence.status === "available"
        && link.evidence.complete);
      if (!loadBalancerLink || !containmentLink) return;
      routing.set(instanceGraphLinkKey(outboundLink), {
        targetPortOffset: -16,
        longChannel: "outer-above",
      });
      routing.set(instanceGraphLinkKey(loadBalancerLink), {
        targetPortOffset: 0,
        longChannel: "above",
      });
      routing.set(instanceGraphLinkKey(containmentLink), {
        targetPortOffset: 16,
        longChannel: "below",
      });
    });
  return routing;
}

function hasDirectedPath(
  start: string,
  target: string,
  adjacency: ReadonlyMap<string, readonly string[]>,
): boolean {
  const queue = [start];
  const visited = new Set<string>();
  while (queue.length > 0) {
    const current = queue.shift()!;
    if (current === target) return true;
    if (visited.has(current)) continue;
    visited.add(current);
    queue.push(...(adjacency.get(current) ?? []));
  }
  return false;
}

/** Projects audit facts into a recent timeline without inventing provider events or prior state. */
export function buildInstanceTimeline(
  items: readonly OntologyInstanceActivity[],
  sourceCutoff: string,
): InstanceTimelineModel {
  const end = Date.parse(sourceCutoff);
  const ordered = [...items]
    .filter((item) => Date.parse(item.recorded_at) <= end)
    .sort((first, second) => Date.parse(first.recorded_at) - Date.parse(second.recorded_at));
  const earliest = ordered[0] ? Date.parse(ordered[0].recorded_at) : end;
  const start = Math.min(earliest, end - 6 * 60 * 60 * 1000);
  const duration = Math.max(1, end - start);
  const position = (recordedAt: string): number =>
    Math.max(0, Math.min(100, ((Date.parse(recordedAt) - start) / duration) * 100));
  const grouped = new Map<string, OntologyInstanceActivity[]>();
  ordered.forEach((activity) => {
    const existing = grouped.get(activity.recorded_at) ?? [];
    existing.push(activity);
    grouped.set(activity.recorded_at, existing);
  });
  const exactEvents = [...grouped.values()].map((cluster): InstanceTimelineEvent => {
    const newestFirst = [...cluster].sort((first, second) => second.sequence - first.sequence);
    const activity = newestFirst[0]!;
    const stateActivity = newestFirst.find((item) => item.facts.state !== undefined) ?? null;
    return {
      activity,
      position: position(activity.recorded_at),
      summary: activitySummary(activity),
      state: stateActivity?.facts.state ?? null,
      stateActivity,
      clusterSize: cluster.length,
    };
  });
  const stateEvents = exactEvents.filter((event) => event.state !== null);
  const segments: InstanceTimelineSegment[] = [];
  const firstStatePosition = stateEvents[0]?.position ?? 100;
  if (firstStatePosition > 0) {
    segments.push({ state: null, start: 0, width: firstStatePosition, observedAt: null, evidenceRef: null });
  }
  stateEvents.forEach((event, index) => {
    const next = stateEvents[index + 1];
    segments.push({
      state: event.state,
      start: event.position,
      width: (next?.position ?? 100) - event.position,
      observedAt: event.stateActivity?.recorded_at ?? null,
      evidenceRef: event.stateActivity?.evidence_ref ?? null,
    });
  });
  if (segments.length === 0) {
    segments.push({ state: null, start: 0, width: 100, observedAt: null, evidenceRef: null });
  }
  const events = exactEvents.reduce<InstanceTimelineEvent[]>((clusters, event) => {
    const previous = clusters.at(-1);
    if (previous === undefined || event.position - previous.position >= MIN_EVENT_MARKER_GAP_PERCENT) {
      clusters.push(event);
      return clusters;
    }
    const stateActivity = event.stateActivity ?? previous.stateActivity;
    clusters[clusters.length - 1] = {
      ...event,
      state: stateActivity?.facts.state ?? null,
      stateActivity,
      clusterSize: previous.clusterSize + event.clusterSize,
    };
    return clusters;
  }, []);
  return {
    startAt: new Date(start).toISOString(),
    endAt: new Date(end).toISOString(),
    events,
    segments,
  };
}

function columnNodes(
  resources: readonly InstanceGraphOccurrence[],
  level: number,
  x: number,
  columnCount: number,
  height: number,
  occurrenceCounts: ReadonlyMap<string, number>,
  clusterManagedIds: ReadonlySet<string>,
  containedIds: ReadonlySet<string>,
): InstanceGraphNode[] {
  const rows = Math.min(INSTANCE_MAX_ROWS, resources.length);
  // Contained Resources sit last in a column, so the break needs its own visible gap.
  const columnBreak = (index: number): number => {
    const columnStart = Math.floor(index / INSTANCE_MAX_ROWS) * INSTANCE_MAX_ROWS;
    const columnEnd = Math.min(columnStart + INSTANCE_MAX_ROWS, resources.length);
    for (let row = columnStart; row < columnEnd; row += 1) {
      if (containedIds.has(resources[row]!.resource.id)) {
        return row > columnStart && index >= row ? INSTANCE_CONTAINMENT_GROUP_GAP : 0;
      }
    }
    return 0;
  };
  const maxBreak = resources.reduce(
    (widest, _occurrence, index) => Math.max(widest, columnBreak(index)),
    0,
  );
  const contentHeight = rows * INSTANCE_ROW_HEIGHT - (rows > 0 ? INSTANCE_ROW_GAP : 0)
    + maxBreak;
  const startY = Math.max(24, Math.round((height - contentHeight) / 2));
  return resources.map((occurrence, index) => ({
    key: occurrence.key,
    resource: occurrence.resource,
    level,
    distance: occurrence.rank.distance,
    emphasis: occurrence.rank.distance === 0
      ? "root"
      : occurrence.rank.distance === 1 ? "direct" : "indirect",
    lane: occurrence.rank.lane,
    side: graphSide(level),
    parentId: occurrence.rank.parentId,
    occurrences: occurrenceCounts.get(occurrence.resource.id) ?? 1,
    clusterManaged: clusterManagedIds.has(occurrence.resource.id),
    x: x + (level < 0
      ? columnCount - 1 - Math.floor(index / INSTANCE_MAX_ROWS)
      : Math.floor(index / INSTANCE_MAX_ROWS)) * INSTANCE_COLUMN_WIDTH,
    y: startY + index % INSTANCE_MAX_ROWS * INSTANCE_ROW_HEIGHT + columnBreak(index),
  }));
}

function instanceGraphFocus(data: OntologyInstanceExploration): {
  readonly resources: readonly OntologyInstanceResource[];
  readonly links: readonly OntologyInstanceLink[];
} {
  const ordered = [...ontologyInstancePresentationLinks(data)].sort(compareInstanceGraphLinks);
  const resourcesById = new Map(data.resources.map((resource) => [resource.id, resource]));
  const scopeRoot = isScopeResourceType(resourcesById.get(data.root_id)?.resource_type);
  const direct = scopeRoot
    ? boundedScopeDirectLinks(data.root_id, ordered, resourcesById)
    : ordered.filter((link) => link.source === data.root_id || link.target === data.root_id);
  const directIds = new Set<string>([data.root_id]);
  direct.forEach((link) => {
    directIds.add(link.source);
    directIds.add(link.target);
  });
  const selected = new Map(direct.map((link) => [instanceGraphLinkKey(link), link]));
  if (!scopeRoot) {
    for (const branchId of [...directIds].filter((id) => id !== data.root_id).sort()) {
      if (isScopeResourceType(resourcesById.get(branchId)?.resource_type)) continue;
      if (INSTANCE_NETWORK_CONTEXT_TYPES.has(resourcesById.get(branchId)?.resource_type ?? "")) {
        continue;
      }
      const candidates = ordered.filter((link) => {
        if (link.link_type === "contains") return false;
        if (selected.has(instanceGraphLinkKey(link))) return false;
        if (link.source !== branchId && link.target !== branchId) return false;
        const other = link.source === branchId ? link.target : link.source;
        return other !== data.root_id;
      });
      for (const link of candidates.slice(0, INSTANCE_INDIRECT_BRANCH_LIMIT)) {
        selected.set(instanceGraphLinkKey(link), link);
      }
    }
  }
  const selectedResourceIds = new Set<string>([data.root_id]);
  selected.forEach((link) => {
    selectedResourceIds.add(link.source);
    selectedResourceIds.add(link.target);
  });
  expandNetworkContext({
    data: { ...data, links: ordered },
    selected,
    selectedResourceIds,
  });
  expandAksInfrastructureContext({
    data: { ...data, links: ordered },
    selected,
    selectedResourceIds,
  });
  expandKubernetesNamespaceContext({
    data: { ...data, links: ordered },
    selected,
    selectedResourceIds,
  });
  if (!scopeRoot) {
    const ancestorQueue = [{ id: data.root_id, depth: 0 }];
    while (ancestorQueue.length > 0) {
      const current = ancestorQueue.shift()!;
      if (current.depth >= INSTANCE_CONTAINMENT_ANCESTOR_LIMIT) continue;
      const parent = ordered.find((link) =>
        link.link_type === "contains"
        && link.target === current.id
        && !selected.has(instanceGraphLinkKey(link)));
      if (!parent) continue;
      selected.set(instanceGraphLinkKey(parent), parent);
      selectedResourceIds.add(parent.source);
      const parentType = resourcesById.get(parent.source)?.resource_type;
      if (parentType !== "resource-group" && parentType !== "subscription") {
        ancestorQueue.push({ id: parent.source, depth: current.depth + 1 });
      }
    }
  }
  const internalLinks = ordered.filter((link) =>
    selectedResourceIds.has(link.source)
    && selectedResourceIds.has(link.target)
    && !selected.has(instanceGraphLinkKey(link)));
  const selectedInternalLinks = scopeRoot
    ? internalLinks.filter(isScopeSummaryLink).slice(0, INSTANCE_SCOPE_INTERNAL_LINK_LIMIT)
    : internalLinks;
  selectedInternalLinks.forEach((link) => selected.set(instanceGraphLinkKey(link), link));
  const links = [...selected.values()].sort(compareInstanceGraphLinks);
  const resourceIds = new Set<string>([data.root_id]);
  links.forEach((link) => {
    resourceIds.add(link.source);
    resourceIds.add(link.target);
  });
  return {
    resources: data.resources.filter((resource) => resourceIds.has(resource.id)),
    links,
  };
}

function isScopeSummaryLink(link: OntologyInstanceLink): boolean {
  return link.link_type === "attached_to";
}

function boundedScopeDirectLinks(
  rootId: string,
  ordered: readonly OntologyInstanceLink[],
  resourcesById: ReadonlyMap<string, OntologyInstanceResource>,
): readonly OntologyInstanceLink[] {
  const direct = ordered.filter((link) => link.source === rootId || link.target === rootId);
  if (direct.length <= INSTANCE_SCOPE_DIRECT_LIMIT) return direct;
  const linksByType = new Map<string, OntologyInstanceLink[]>();
  direct.forEach((link) => {
    const resourceId = link.source === rootId ? link.target : link.source;
    const resourceType = resourcesById.get(resourceId)?.resource_type ?? "unclassified-resource";
    const links = linksByType.get(resourceType) ?? [];
    links.push(link);
    linksByType.set(resourceType, links);
  });
  const groups = [...linksByType].sort(([first], [second]) =>
    scopeResourceTypePriority(first) - scopeResourceTypePriority(second)
    || first.localeCompare(second));
  const selected: OntologyInstanceLink[] = [];
  for (let index = 0; selected.length < INSTANCE_SCOPE_DIRECT_LIMIT; index += 1) {
    let found = false;
    for (const [, links] of groups) {
      const link = links[index];
      if (!link) continue;
      selected.push(link);
      found = true;
      if (selected.length === INSTANCE_SCOPE_DIRECT_LIMIT) break;
    }
    if (!found) break;
  }
  return selected.sort(compareInstanceGraphLinks);
}

function scopeResourceTypePriority(resourceType: string): number {
  if (resourceType === "authorization.role-assignment") return 2;
  return resourceType === "unclassified-resource" ? 1 : 0;
}

function expandNetworkContext({
  data,
  selected,
  selectedResourceIds,
}: {
  readonly data: OntologyInstanceExploration;
  readonly selected: Map<string, OntologyInstanceLink>;
  readonly selectedResourceIds: Set<string>;
}): void {
  const branch = selectedNetworkBranch(data);
  const branchIds = new Set([
    ...branch.vnets,
    ...branch.subnets,
    ...branch.privateEndpoints,
    ...branch.networkInterfaces,
  ]);
  data.links.forEach((link) => {
    if (!branchIds.has(link.source) || !branchIds.has(link.target)) return;
    selected.set(instanceGraphLinkKey(link), link);
    selectedResourceIds.add(link.source);
    selectedResourceIds.add(link.target);
  });
}

function expandAksInfrastructureContext({
  data,
  selected,
  selectedResourceIds,
}: {
  readonly data: OntologyInstanceExploration;
  readonly selected: Map<string, OntologyInstanceLink>;
  readonly selectedResourceIds: Set<string>;
}): void {
  const resourcesById = new Map(data.resources.map((resource) => [resource.id, resource]));
  if (resourcesById.get(data.root_id)?.resource_type !== "kubernetes-cluster") return;
  const nodeGroupLink = data.links.find((link) =>
    link.source === data.root_id
    && link.link_type === "attached_to"
    && link.evidence.mapping_id === "azure.aks-attached-to-node-resource-group"
    && resourcesById.get(link.target)?.resource_type === "resource-group");
  if (!nodeGroupLink) return;

  const scaleSetLinks = data.links
    .filter((link) =>
      link.source === nodeGroupLink.target
      && link.link_type === "contains"
      && resourcesById.get(link.target)?.resource_type === "compute.vm-scale-set")
    .sort(compareInstanceGraphLinks);
  for (const scaleSetLink of scaleSetLinks) {
    selected.set(instanceGraphLinkKey(scaleSetLink), scaleSetLink);
    selectedResourceIds.add(scaleSetLink.source);
    selectedResourceIds.add(scaleSetLink.target);
    const vmLinks = data.links
      .filter((link) =>
        link.source === scaleSetLink.target
        && link.link_type === "contains"
        && link.evidence.mapping_id === "azure.vm-scale-set-contains-vm"
        && resourcesById.get(link.target)?.resource_type === "compute.vm")
      .sort(compareInstanceGraphLinks)
      .slice(0, INSTANCE_AKS_VM_LIMIT_PER_SCALE_SET);
    for (const vmLink of vmLinks) {
      selected.set(instanceGraphLinkKey(vmLink), vmLink);
      selectedResourceIds.add(vmLink.target);
      data.links
        .filter((link) =>
          link.target === vmLink.target
          && link.link_type === "attached_to"
          && link.evidence.mapping_id === "azure.vm-scale-set-nic-attached-to-vm"
          && resourcesById.get(link.source)?.resource_type === "network.interface")
        .sort(compareInstanceGraphLinks)
        .slice(0, INSTANCE_AKS_NIC_LIMIT_PER_VM)
        .forEach((nicLink) => {
          selected.set(instanceGraphLinkKey(nicLink), nicLink);
          selectedResourceIds.add(nicLink.source);
        });
    }
  }
}

/** Adds a bounded, declared-workload-first sample of what each cluster namespace holds. */
function expandKubernetesNamespaceContext({
  data,
  selected,
  selectedResourceIds,
}: {
  readonly data: OntologyInstanceExploration;
  readonly selected: Map<string, OntologyInstanceLink>;
  readonly selectedResourceIds: Set<string>;
}): void {
  const resourcesById = new Map(data.resources.map((resource) => [resource.id, resource]));
  if (resourcesById.get(data.root_id)?.resource_type !== "kubernetes-cluster") return;
  const namespaceIds = data.links
    .filter((link) =>
      link.source === data.root_id
      && link.link_type === "contains"
      && resourcesById.get(link.target)?.resource_type === "kubernetes.namespace")
    .map((link) => link.target);
  for (const namespaceId of namespaceIds) {
    data.links
      .filter((link) =>
        link.source === namespaceId
        && link.link_type === "contains"
        && INSTANCE_KUBERNETES_CHILD_PRIORITY.includes(
          resourcesById.get(link.target)?.resource_type ?? ""))
      .sort((first, second) => {
        const rank = (link: OntologyInstanceLink): number =>
          INSTANCE_KUBERNETES_CHILD_PRIORITY.indexOf(
            resourcesById.get(link.target)?.resource_type ?? "");
        return rank(first) - rank(second) || compareInstanceGraphLinks(first, second);
      })
      .slice(0, INSTANCE_KUBERNETES_NAMESPACE_CHILD_LIMIT)
      .forEach((childLink) => {
        selected.set(instanceGraphLinkKey(childLink), childLink);
        selectedResourceIds.add(childLink.source);
        selectedResourceIds.add(childLink.target);
      });
  }
}

function selectedNetworkBranch(data: OntologyInstanceExploration): {  readonly resourcesById: ReadonlyMap<string, OntologyInstanceResource>;
  readonly vnets: readonly string[];
  readonly subnets: readonly string[];
  readonly privateEndpoints: readonly string[];
  readonly networkInterfaces: readonly string[];
  readonly vnetBySubnet: ReadonlyMap<string, string>;
  readonly subnetByPrivateEndpoint: ReadonlyMap<string, string>;
  readonly privateEndpointByInterface: ReadonlyMap<string, string>;
  readonly subnetByInterface: ReadonlyMap<string, string>;
} {
  const resourcesById = new Map(data.resources.map((resource) => [resource.id, resource]));
  const rootType = resourcesById.get(data.root_id)?.resource_type;
  const subnets = new Set<string>();
  const privateEndpoints = new Set<string>();
  const networkInterfaces = new Set<string>();
  const vnets = new Set<string>();
  const vnetBySubnet = new Map<string, string>();
  const subnetByPrivateEndpoint = new Map<string, string>();
  const privateEndpointByInterface = new Map<string, string>();
  const subnetByInterface = new Map<string, string>();

  if (rootType === "network.vnet") vnets.add(data.root_id);
  if (rootType === "network.subnet") subnets.add(data.root_id);
  if (rootType === "network.private-endpoint") privateEndpoints.add(data.root_id);
  if (rootType === "network.interface") networkInterfaces.add(data.root_id);
  data.links.forEach((link) => {
    if (
      resourcesById.get(link.source)?.resource_type === "network.private-endpoint"
      && (link.source === data.root_id || link.target === data.root_id)
    ) privateEndpoints.add(link.source);
    if (
      rootType === "network.vnet"
      && link.source === data.root_id
      && link.link_type === "contains"
      && resourcesById.get(link.target)?.resource_type === "network.subnet"
    ) subnets.add(link.target);
  });
  if (rootType === "network.vnet" || rootType === "network.subnet") {
    data.links.forEach((link) => {
      if (!subnets.has(link.target) || link.link_type !== "attached_to") return;
      const sourceType = resourcesById.get(link.source)?.resource_type;
      if (sourceType === "network.private-endpoint") privateEndpoints.add(link.source);
      if (sourceType === "network.interface") networkInterfaces.add(link.source);
    });
  }
  data.links.forEach((link) => {
    if (!privateEndpoints.has(link.source) || link.link_type !== "attached_to") return;
    const targetType = resourcesById.get(link.target)?.resource_type;
    if (targetType === "network.subnet") subnets.add(link.target);
    if (targetType === "network.interface") networkInterfaces.add(link.target);
  });
  data.links.forEach((link) => {
    const sourceType = resourcesById.get(link.source)?.resource_type;
    const targetType = resourcesById.get(link.target)?.resource_type;
    if (
      link.link_type === "contains"
      && sourceType === "network.vnet"
      && targetType === "network.subnet"
      && subnets.has(link.target)
    ) {
      vnets.add(link.source);
      vnetBySubnet.set(link.target, link.source);
    }
    if (
      link.link_type === "attached_to"
      && sourceType === "network.private-endpoint"
      && targetType === "network.subnet"
      && privateEndpoints.has(link.source)
      && subnets.has(link.target)
    ) subnetByPrivateEndpoint.set(link.source, link.target);
    if (
      link.link_type === "attached_to"
      && sourceType === "network.private-endpoint"
      && targetType === "network.interface"
      && privateEndpoints.has(link.source)
      && networkInterfaces.has(link.target)
    ) privateEndpointByInterface.set(link.target, link.source);
    if (
      link.link_type === "attached_to"
      && sourceType === "network.interface"
      && targetType === "network.subnet"
      && networkInterfaces.has(link.source)
      && subnets.has(link.target)
    ) subnetByInterface.set(link.source, link.target);
  });
  return {
    resourcesById,
    vnets: [...vnets].sort(),
    subnets: [...subnets].sort(),
    privateEndpoints: [...privateEndpoints].sort(),
    networkInterfaces: [...networkInterfaces].sort(),
    vnetBySubnet,
    subnetByPrivateEndpoint,
    privateEndpointByInterface,
    subnetByInterface,
  };
}

function isReverseNetworkPresentationLink(
  link: OntologyInstanceLink,
  resourcesById: ReadonlyMap<string, OntologyInstanceResource>,
): boolean {
  if (link.link_type !== "attached_to") return false;
  const sourceType = resourcesById.get(link.source)?.resource_type;
  const targetType = resourcesById.get(link.target)?.resource_type;
  if (
    link.evidence.mapping_id === "azure.vm-scale-set-nic-attached-to-vm"
    && sourceType === "network.interface"
    && targetType === "compute.vm"
  ) return true;
  return targetType === "network.subnet" && (
    sourceType === "network.private-endpoint" || sourceType === "network.interface"
  );
}

function instanceGraphLinkLane(
  link: OntologyInstanceLink,
): InstanceGraphLane {
  if (link.link_type === "routes_to" || link.link_type === "runtime_calls") return "traffic";
  if (link.evidence.mapping_id?.startsWith("kubernetes.")) return "runtime";
  if (link.link_type === "contains") return "containment";
  return link.link_type === "depends_on"
    ? "dependency"
    : "access";
}

function graphLaneOrder(lane: InstanceGraphLane): number {
  return lane === "traffic" ? 0
    : lane === "dependency" ? 1
      : lane === "runtime" ? 2
        : lane === "access" ? 3 : 4;
}

function graphSide(level: number): InstanceGraphSide {
  return level < 0 ? "incoming" : level > 0 ? "outgoing" : "selected";
}

function isScopeResourceType(resourceType: string | undefined): boolean {
  return resourceType === "resource-group" || resourceType === "subscription";
}

function compareInstanceGraphLinks(
  first: OntologyInstanceLink,
  second: OntologyInstanceLink,
): number {
  return graphLaneOrder(instanceGraphLinkLane(first))
    - graphLaneOrder(instanceGraphLinkLane(second))
    || first.source.localeCompare(second.source)
    || first.target.localeCompare(second.target)
    || first.link_type.localeCompare(second.link_type);
}

function instanceGraphLinkKey(link: OntologyInstanceLink): string {
  return `${link.source}\u0000${link.link_type}\u0000${link.target}`;
}

function activitySummary(item: OntologyInstanceActivity): string {
  return item.facts.reason
    ?? item.facts.outcome
    ?? item.facts.verdict
    ?? item.facts.decision
    ?? item.facts.action_type
    ?? item.action_kind;
}

function edgePairKey(link: OntologyInstanceLink): string {
  return [link.source, link.target].sort().join("\u0000");
}
