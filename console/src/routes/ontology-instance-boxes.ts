import {
  INSTANCE_KUBERNETES_CHILD_PRIORITY,
  INSTANCE_NODE_HEIGHT,
  INSTANCE_NODE_WIDTH,
} from "./ontology-instance-graph.model";
import type {
  OntologyInstanceExploration,
  OntologyInstanceResource,
} from "./ontology-instances.model";

/** Space between a box border and what it contains. */
export const INSTANCE_BOX_PADDING = 16;
/** Room at the top of a box for the owner's own name. */
export const INSTANCE_BOX_HEADER = 30;
export const INSTANCE_BOX_GAP = 12;
export const INSTANCE_BOX_MAX_CHILDREN = 12;
export const INSTANCE_BOX_MAX_DEPTH = 3;

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
    if (depth >= maxDepth || declared.length === 0 || visiting.has(resource.id)) {
      return leafBox(resource, depth);
    }
    visiting.add(resource.id);
    const ordered = [...declared].sort(compareBoxChildren);
    const kept = ordered.slice(0, maxChildren);
    const children = kept.map((child) => build(child, depth + 1));
    visiting.delete(resource.id);
    return packBox(resource, depth, children, ordered.length - kept.length);
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

function leafBox(resource: OntologyInstanceResource, depth: number): InstanceBox {
  return {
    resource,
    depth,
    x: 0,
    y: 0,
    width: INSTANCE_NODE_WIDTH,
    height: INSTANCE_NODE_HEIGHT,
    children: [],
    omittedChildren: 0,
  };
}

function packBox(
  resource: OntologyInstanceResource,
  depth: number,
  children: readonly InstanceBox[],
  omittedChildren: number,
): InstanceBox {
  // A near-square grid is what makes nesting cheaper than a one-column outline.
  const columns = Math.max(1, Math.ceil(Math.sqrt(children.length)));
  const columnWidth = Math.max(...children.map((child) => child.width));
  const rowCount = Math.ceil(children.length / columns);
  const rowHeights = Array.from({ length: rowCount }, (_value, row) =>
    Math.max(...children
      .slice(row * columns, row * columns + columns)
      .map((child) => child.height)));
  const rowOffsets = rowHeights.reduce<number[]>((offsets, height, row) => {
    offsets.push(row === 0 ? 0 : offsets[row - 1]! + rowHeights[row - 1]! + INSTANCE_BOX_GAP);
    return offsets;
  }, []);
  const placed = children.map((child, index) => ({
    ...child,
    x: (index % columns) * (columnWidth + INSTANCE_BOX_GAP),
    y: rowOffsets[Math.floor(index / columns)]!,
  }));
  const contentWidth = columns * columnWidth + (columns - 1) * INSTANCE_BOX_GAP;
  const contentHeight = rowHeights.reduce((total, height) => total + height, 0)
    + (rowCount - 1) * INSTANCE_BOX_GAP;
  return {
    resource,
    depth,
    x: 0,
    y: 0,
    width: Math.max(INSTANCE_NODE_WIDTH, contentWidth + INSTANCE_BOX_PADDING * 2),
    height: INSTANCE_BOX_HEADER + contentHeight + INSTANCE_BOX_PADDING,
    children: placed,
    omittedChildren,
  };
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
