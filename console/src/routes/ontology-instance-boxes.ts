import {
  INSTANCE_KUBERNETES_CHILD_PRIORITY,
  INSTANCE_NODE_HEIGHT,
  INSTANCE_NODE_WIDTH,
} from "./ontology-instance-graph.model";
import type { InstanceGraphLayout } from "./ontology-instance-graph.model";
import type {
  OntologyInstanceExploration,
  OntologyInstanceResource,
} from "./ontology-instances.model";

/** Space between a box border and what it contains. */
export const INSTANCE_BOX_PADDING = 16;
export const INSTANCE_BOX_GAP = 12;
/** An owner keeps its own card, with its status and evidence, at the top of its box. */
export const INSTANCE_BOX_HEADER = INSTANCE_BOX_PADDING + INSTANCE_NODE_HEIGHT + INSTANCE_BOX_GAP;
export const INSTANCE_BOX_MAX_CHILDREN = 12;
export const INSTANCE_BOX_MAX_DEPTH = 3;
/** How much taller than wide a box may get before it earns another column. */
export const INSTANCE_BOX_MAX_ASPECT = 2.5;

export interface InstanceBox {
  readonly resource: OntologyInstanceResource;
  readonly depth: number;
  /** Top-left corner, relative to the containing box's content origin. */
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly height: number;
  readonly children: readonly InstanceBox[];
  /** Children the bound left out; a box that hides them must not read as an empty owner. */
  readonly omittedChildren: number;
}

export interface InstanceBoxOptions {
  readonly maxChildren?: number;
  readonly maxDepth?: number;
  /** Limits nesting to Resources the layout already draws, without hiding that it did so. */
  readonly isVisible?: (resourceId: string) => boolean;
}

/**
 * Groups the containment forest below the selected Resource into nested boxes.
 *
 * Containment is drawn as nesting rather than as an edge, so an owner can never be
 * drawn beside or below what it contains. Returns `null` when the root contains nothing.
 */
export function buildInstanceContainmentBoxes(
  data: OntologyInstanceExploration,
  options: InstanceBoxOptions = {},
): InstanceBox | null {
  const maxChildren = options.maxChildren ?? INSTANCE_BOX_MAX_CHILDREN;
  const maxDepth = options.maxDepth ?? INSTANCE_BOX_MAX_DEPTH;
  const isVisible = options.isVisible ?? (() => true);
  const resourcesById = new Map(data.resources.map((resource) => [resource.id, resource]));
  const root = resourcesById.get(data.root_id);
  if (root === undefined) return null;

  const childrenByOwner = new Map<string, OntologyInstanceResource[]>();
  for (const link of data.links) {
    if (link.link_type !== "contains") continue;
    const child = resourcesById.get(link.target);
    if (child === undefined) continue;
    childrenByOwner.set(link.source, [...(childrenByOwner.get(link.source) ?? []), child]);
  }
  if ((childrenByOwner.get(data.root_id) ?? []).length === 0) return null;

  // The response is a boundary, so a malformed containment cycle must not recurse forever.
  const visiting = new Set<string>();

  const build = (resource: OntologyInstanceResource, depth: number): InstanceBox => {
    const declared = childrenByOwner.get(resource.id) ?? [];
    if (depth >= maxDepth || visiting.has(resource.id)) return leafBox(resource, depth, 0);
    visiting.add(resource.id);
    // Counting against everything declared keeps a drawn box from claiming it holds the whole owner.
    const ordered = [...declared].sort(compareBoxChildren);
    const kept = ordered.filter((child) => isVisible(child.id)).slice(0, maxChildren);
    const children = kept.map((child) => build(child, depth + 1));
    visiting.delete(resource.id);
    return children.length === 0
      ? leafBox(resource, depth, ordered.length)
      : packBox(resource, depth, children, ordered.length - kept.length);
  };

  return build(root, 0);
}

/** Returns every box in the tree with coordinates resolved against the canvas origin. */
export function flattenInstanceBoxes(
  box: InstanceBox,
  originX = 0,
  originY = 0,
): readonly InstanceBox[] {
  const placed: InstanceBox = { ...box, x: originX + box.x, y: originY + box.y };
  const contentX = placed.x + INSTANCE_BOX_PADDING;
  const contentY = placed.y + INSTANCE_BOX_HEADER;
  return [
    placed,
    ...box.children.flatMap((child) => flattenInstanceBoxes(child, contentX, contentY)),
  ];
}

/** Where a box draws the owner's own card. A box that holds nothing is only that card. */
export function instanceBoxCardPosition(box: InstanceBox): { readonly x: number; readonly y: number } {
  return box.children.length === 0
    ? { x: box.x, y: box.y }
    : { x: box.x + INSTANCE_BOX_PADDING, y: box.y + INSTANCE_BOX_PADDING };
}

export interface NestedInstanceGraph {
  readonly layout: InstanceGraphLayout;
  /** Owners worth a border, outermost first. Empty when nothing nests. */
  readonly boxes: readonly InstanceBox[];
  /** Resources whose distance the drawing now states by position. */
  readonly nestedIds: ReadonlySet<string>;
}

/**
 * Redraws containment as nesting over a layout that already decided what to show.
 *
 * Nesting is a reading arrangement: it moves cards and removes the lines it absorbs, and it
 * never adds a Resource the layout left out or asserts containment the evidence did not report.
 */
export function nestInstanceContainment(
  layout: InstanceGraphLayout,
  data: OntologyInstanceExploration,
  options: InstanceBoxOptions = {},
): NestedInstanceGraph {
  const drawn = new Set(layout.nodes.map((node) => node.resource.id));
  const root = buildInstanceContainmentBoxes(data, {
    ...options,
    isVisible: (id) => drawn.has(id) && (options.isVisible?.(id) ?? true),
  });
  const rootNode = layout.nodes.find((node) => node.resource.id === data.root_id);
  if (root === null || root.children.length === 0 || rootNode === undefined) {
    return { layout, boxes: [], nestedIds: new Set() };
  }

  const boxes = flattenInstanceBoxes(
    root,
    rootNode.x - INSTANCE_BOX_PADDING,
    Math.max(24, rootNode.y - INSTANCE_BOX_PADDING),
  );
  const cardById = new Map(boxes.map((box) => [box.resource.id, instanceBoxCardPosition(box)]));
  const nestedIds = new Set(cardById.keys());

  // One Resource cannot sit in two places, so a nested Resource keeps only its placement in the box.
  const ownerOf = new Map<string, string>();
  const collect = (box: InstanceBox): void => {
    box.children.forEach((child) => {
      ownerOf.set(child.resource.id, box.resource.id);
      collect(child);
    });
  };
  collect(root);

  const claimed = new Set<string>();
  const kept = layout.nodes.filter((node) => {
    if (!nestedIds.has(node.resource.id)) return true;
    if (claimed.has(node.resource.id)) return false;
    claimed.add(node.resource.id);
    return true;
  });

  // Everything drawn to the right of the selected Resource has to clear the box it now spans.
  const rootBox = boxes[0]!;
  const shift = Math.max(0, rootBox.x + rootBox.width - (rootNode.x + INSTANCE_NODE_WIDTH));
  const nodes = kept.map((node) => {
    const card = cardById.get(node.resource.id);
    if (card !== undefined) return { ...node, x: card.x, y: card.y };
    return node.x > rootNode.x ? { ...node, x: node.x + shift } : node;
  });

  const byId = new Map(nodes.map((node) => [node.resource.id, node]));
  const edges = layout.edges.flatMap((edge) => {
    if (edge.link.link_type === "contains" && ownerOf.get(edge.link.target) === edge.link.source) {
      return [];
    }
    const source = byId.get(edge.source.resource.id);
    const target = byId.get(edge.target.resource.id);
    return source === undefined || target === undefined ? [] : [{ ...edge, source, target }];
  });

  const right = Math.max(
    ...nodes.map((node) => node.x + INSTANCE_NODE_WIDTH),
    ...boxes.map((box) => box.x + box.width),
  );
  const bottom = Math.max(
    ...nodes.map((node) => node.y + INSTANCE_NODE_HEIGHT),
    ...boxes.map((box) => box.y + box.height),
  );
  return {
    layout: {
      ...layout,
      width: right + INSTANCE_BOX_PADDING * 2,
      height: bottom + INSTANCE_BOX_PADDING * 2,
      nodes,
      edges,
      hiddenNodeCount: data.resources.length - new Set(nodes.map((node) => node.resource.id)).size,
      hiddenEdgeCount: data.links.length - edges.length,
    },
    boxes: boxes.filter((box) => box.children.length > 0),
    nestedIds,
  };
}

function leafBox(
  resource: OntologyInstanceResource,
  depth: number,
  omittedChildren: number,
): InstanceBox {
  return {
    resource,
    depth,
    x: 0,
    y: 0,
    width: INSTANCE_NODE_WIDTH,
    height: INSTANCE_NODE_HEIGHT,
    children: [],
    omittedChildren,
  };
}

function packBox(
  resource: OntologyInstanceResource,
  depth: number,
  children: readonly InstanceBox[],
  omittedChildren: number,
): InstanceBox {
  const columns = packColumns(children);
  const rowCount = Math.ceil(children.length / columns);
  const rowOf = (index: number): number => Math.floor(index / columns);
  // Per-column widths, because one wide child must not widen every column beside it.
  const columnWidths = Array.from({ length: columns }, (_value, column) =>
    Math.max(...children
      .filter((_child, index) => index % columns === column)
      .map((child) => child.width)));
  const rowHeights = Array.from({ length: rowCount }, (_value, row) =>
    Math.max(...children.filter((_child, index) => rowOf(index) === row).map((child) => child.height)));
  const offsets = (sizes: readonly number[]): number[] =>
    sizes.reduce<number[]>((totals, size, index) => {
      totals.push(index === 0 ? 0 : totals[index - 1]! + sizes[index - 1]! + INSTANCE_BOX_GAP);
      return totals;
    }, []);
  const columnOffsets = offsets(columnWidths);
  const rowOffsets = offsets(rowHeights);
  const placed = children.map((child, index) => ({
    ...child,
    x: columnOffsets[index % columns]!,
    y: rowOffsets[rowOf(index)]!,
  }));
  const span = (sizes: readonly number[]): number =>
    sizes.reduce((total, size) => total + size, 0) + (sizes.length - 1) * INSTANCE_BOX_GAP;
  return {
    resource,
    depth,
    x: 0,
    y: 0,
    width: Math.max(INSTANCE_NODE_WIDTH, span(columnWidths) + INSTANCE_BOX_PADDING * 2),
    height: INSTANCE_BOX_HEADER + span(rowHeights) + INSTANCE_BOX_PADDING,
    children: placed,
    omittedChildren,
  };
}

/**
 * Picks the narrowest column count whose box does not become a tower.
 *
 * Width and height are not equally priced here. Width competes with the incoming and outgoing
 * bands and with every Resource the box pushes sideways, while height only costs a scroll, so a
 * square box would spend the scarce axis. Falls back to the least tall option when none fits.
 */
function packColumns(children: readonly InstanceBox[]): number {
  const total = children.length;
  const width = children.reduce((sum, child) => sum + child.width, 0) / total + INSTANCE_BOX_GAP;
  const height = children.reduce((sum, child) => sum + child.height, 0) / total + INSTANCE_BOX_GAP;
  const ratio = (columns: number): number =>
    (Math.ceil(total / columns) * height) / (columns * width);
  for (let columns = 1; columns <= total; columns += 1) {
    if (ratio(columns) <= INSTANCE_BOX_MAX_ASPECT) return columns;
  }
  return total;
}

function compareBoxChildren(
  first: OntologyInstanceResource,
  second: OntologyInstanceResource,
): number {
  const rank = (resource: OntologyInstanceResource): number => {
    const index = INSTANCE_KUBERNETES_CHILD_PRIORITY.indexOf(resource.resource_type);
    return index === -1 ? INSTANCE_KUBERNETES_CHILD_PRIORITY.length : index;
  };
  return rank(first) - rank(second)
    || first.resource_type.localeCompare(second.resource_type)
    || (first.name ?? "").localeCompare(second.name ?? "")
    || first.id.localeCompare(second.id);
}
