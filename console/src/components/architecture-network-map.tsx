import { t } from "../routes/i18n/architecture";
import { architectureResourceAbbreviation } from "./architecture-resource-abbreviations";
import { architectureNetworkIconForResourceType } from "./architecture-network-icons";
import {
  architectureNetworkOrthogonalRoute,
  architectureNetworkPeeringRoute,
  architectureNetworkRoutePath,
  type ArchitectureNetworkRouteBox,
} from "./architecture-network-route";
import {
  isRegion,
  resourceColorOf,
  resourceTypeLabelOf,
  type InventoryGraphResponse,
  type InventoryResource,
} from "./architecture-map.model";

interface Props {
  readonly graph: InventoryGraphResponse;
  readonly selectedId: string | null;
  readonly highlightedIds?: ReadonlySet<string>;
  readonly onSelect: (resource: InventoryResource | null) => void;
  readonly descriptionId?: string;
}

interface NetworkBounds {
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly height: number;
}

/** Computes a stable world box for the focused 2D network projection. */
export function architectureNetworkMapBounds(
  resources: readonly InventoryResource[],
): NetworkBounds {
  const boxes = resources.map((resource) => isRegion(resource)
    ? {
        left: resource.x ?? 0,
        top: resource.y ?? 0,
        right: (resource.x ?? 0) + (resource.w ?? 2),
        bottom: (resource.y ?? 0) + (resource.h ?? 2),
      }
    : {
      left: (resource.x ?? 0) - .95,
      top: (resource.y ?? 0) - .8,
      right: (resource.x ?? 0) + .95,
      bottom: (resource.y ?? 0) + .8,
      });
  const left = Math.min(0, ...boxes.map((box) => box.left)) - .5;
  const top = Math.min(0, ...boxes.map((box) => box.top)) - 3.5;
  const right = Math.max(1, ...boxes.map((box) => box.right)) + .5;
  const bottom = Math.max(1, ...boxes.map((box) => box.bottom)) + .5;
  return { x: left, y: top, width: right - left, height: bottom - top };
}

export function ArchitectureNetworkMap({
  graph,
  selectedId,
  highlightedIds,
  onSelect,
  descriptionId,
}: Props) {
  const byId = new Map(graph.resources.map((resource) => [resource.id, resource]));
  const activeIds = architectureNetworkActiveIds(graph, highlightedIds);
  const bounds = architectureNetworkMapBounds(graph.resources);
  const regions = graph.resources.filter(isRegion).sort(
    (first, second) => regionDepth(first, byId) - regionDepth(second, byId),
  );
  const nodes = graph.resources.filter((resource) => !isRegion(resource));
  const active = (resourceId: string) => !activeIds || activeIds.has(resourceId);
  return (
    <div class="architecture-map-frame architecture-network-map-frame">
      <svg
        class="architecture-network-map-svg"
        viewBox={`${bounds.x} ${bounds.y} ${bounds.width} ${bounds.height}`}
        role="img"
        aria-label={t("network.mapAriaLabel", { count: graph.resources.length })}
        aria-describedby={descriptionId}
        preserveAspectRatio="xMidYMin meet"
      >
        <defs>
          <marker id="architecture-network-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
            <path d="M0 1L9 5L0 9z" />
          </marker>
        </defs>
        <g class="architecture-network-regions">
          {regions.map((resource) => (
            <g
              class={`architecture-network-region${selectedId === resource.id ? " is-selected" : ""}${active(resource.id) ? "" : " is-muted"}`}
              data-resource-type={resource.type}
              role="button"
              tabIndex={0}
              aria-label={`${resource.name}. ${resourceTypeLabelOf(resource)}`}
              onClick={() => onSelect(resource)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") onSelect(resource);
              }}
            >
              <title>{resource.name}</title>
              <rect
                x={resource.x ?? 0}
                y={resource.y ?? 0}
                width={resource.w ?? 2}
                height={resource.h ?? 2}
                fill={resourceColorOf(resource)}
              />
              <text x={(resource.x ?? 0) + .18} y={(resource.y ?? 0) + .34}>{resource.name}</text>
            </g>
          ))}
        </g>
        <g class="architecture-network-links">
          {graph.links.map((link) => {
            const source = byId.get(link.source);
            const target = byId.get(link.target);
            if (!source || !target || link.type === "contains") return null;
            const route = architectureNetworkLinkRoute(source, target, graph.resources, link.type);
            const path = route.path;
            const pathActive = active(source.id) && active(target.id);
            return (
              <g class={`architecture-network-link is-${link.type}${pathActive ? "" : " is-muted"}`}>
                <title>{`${source.name} - ${link.type} - ${target.name}`}</title>
                <path class="architecture-network-link-halo" d={path} />
                <path
                  class="architecture-network-link-path"
                  d={path}
                  markerEnd={link.type === "depends_on" || link.type === "peered_with" ? "url(#architecture-network-arrow)" : undefined}
                  markerStart={link.type === "peered_with" ? "url(#architecture-network-arrow)" : undefined}
                />
                {link.type === "attached_to" ? <>
                  <circle class="architecture-network-link-endpoint-halo" cx={route.end.x} cy={route.end.y} r=".22" />
                  <circle class="architecture-network-link-endpoint" cx={route.end.x} cy={route.end.y} r=".13" />
                </> : null}
              </g>
            );
          })}
        </g>
        <g class="architecture-network-nodes">
          {nodes.map((resource) => {
            const position = resourcePoint(resource);
            const icon = architectureNetworkIconForResourceType(resource.type);
            const labelLines = networkNodeLabelLines(resourceTypeLabelOf(resource));
            return (
              <g
                class={`architecture-network-node${icon ? " has-official-icon" : ""}${selectedId === resource.id ? " is-selected" : ""}${active(resource.id) ? "" : " is-muted"}`}
                role="button"
                tabIndex={0}
                aria-label={`${resource.name}. ${resourceTypeLabelOf(resource)}`}
                transform={`translate(${position.x} ${position.y})`}
                onClick={() => onSelect(resource)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") onSelect(resource);
                }}
              >
                <title>{resource.name}</title>
                <rect class="architecture-network-node-hit" x="-1.25" y="-1.25" width="2.5" height="2.5" rx=".16" />
                <rect class="architecture-network-node-surface" x="-1.2" y="-.9" width="2.4" height="1.9" rx=".14" fill={resourceColorOf(resource)} />
                {icon
                  ? <image class="architecture-network-node-icon" href={icon} x="-.575" y="-.78" width="1.15" height="1.15" />
                  : <text class="architecture-network-node-glyph" y="-.2">{architectureResourceAbbreviation(resource.type)}</text>}
                <text class="architecture-network-node-label">
                  {labelLines.map((line, index) => <tspan x="0" y={.58 + index * .27}>{line}</tspan>)}
                </text>
              </g>
            );
          })}
        </g>
      </svg>
      <label class="architecture-resource-picker">
        <span class="sr-only">{t("selectArchitectureResource")}</span>
        <select
          aria-label={t("selectArchitectureResource")}
          value={selectedId ?? ""}
          onChange={(event) => onSelect(byId.get(event.currentTarget.value) ?? null)}
        >
          <option value="">{t("selectResourceOption")}</option>
          {graph.resources
            .slice()
            .sort((first, second) => first.name.localeCompare(second.name))
            .map((resource) => (
              <option value={resource.id}>{resource.name} - {resourceTypeLabelOf(resource)}</option>
            ))}
        </select>
      </label>
    </div>
  );
}

/** Retains the containment context needed to interpret a highlighted relationship path. */
export function architectureNetworkActiveIds(
  graph: Pick<InventoryGraphResponse, "links" | "resources">,
  highlightedIds: ReadonlySet<string> | undefined,
): ReadonlySet<string> | undefined {
  if (!highlightedIds) return undefined;
  const active = new Set(highlightedIds);
  const byId = new Map(graph.resources.map((resource) => [resource.id, resource]));
  let changed = true;
  while (changed) {
    changed = false;
    for (const resourceId of [...active]) {
      const resource = byId.get(resourceId);
      for (const ancestorId of [resource?.network_plane_id, resource?.parent_id]) {
        if (ancestorId && !active.has(ancestorId)) {
          active.add(ancestorId);
          changed = true;
        }
      }
    }
    for (const link of graph.links) {
      if (link.type === "contains" && active.has(link.target) && !active.has(link.source)) {
        active.add(link.source);
        changed = true;
      }
    }
  }
  return active;
}

function resourcePoint(resource: InventoryResource): { readonly x: number; readonly y: number } {
  return {
    x: (resource.x ?? 0) + (isRegion(resource) ? (resource.w ?? 0) / 2 : 0),
    y: (resource.y ?? 0) + (isRegion(resource) ? (resource.h ?? 0) / 2 : 0),
  };
}

/** Routes an orthogonal relationship between current visual boundaries. */
export function architectureNetworkLinkPath(
  source: InventoryResource,
  target: InventoryResource,
  resources: readonly InventoryResource[] = [source, target],
): string {
  return architectureNetworkLinkRoute(source, target, resources).path;
}

function architectureNetworkLinkRoute(
  source: InventoryResource,
  target: InventoryResource,
  resources: readonly InventoryResource[],
  relationshipType?: "contains" | "attached_to" | "depends_on" | "peered_with",
): {
  readonly path: string;
  readonly end: { readonly x: number; readonly y: number };
} {
  const resourceBox = (resource: InventoryResource): ArchitectureNetworkRouteBox => {
    const position = resourcePoint(resource);
    if (isRegion(resource)) {
      return {
        id: resource.id,
        x: resource.x ?? 0,
        y: resource.y ?? 0,
        width: resource.w ?? 2,
        height: resource.h ?? 2,
      };
    }
    return { id: resource.id, x: position.x - 1.2, y: position.y - .9, width: 2.4, height: 1.9 };
  };
  const sourceBox = resourceBox(source);
  const targetBox = resourceBox(target);
  const points = relationshipType === "peered_with" && isRegion(source) && isRegion(target)
    ? architectureNetworkPeeringRoute(sourceBox, targetBox)
    : architectureNetworkOrthogonalRoute(
        sourceBox,
        targetBox,
        resources.filter((resource) => !isRegion(resource)).map(resourceBox),
      );
  const end = points.at(-1) ?? resourcePoint(target);
  return {
    path: architectureNetworkRoutePath(points),
    end,
  };
}

function networkNodeLabelLines(label: string): readonly string[] {
  if (label.length <= 12 || !label.includes(" ")) return [label];
  const words = label.split(" ");
  let bestIndex = 1;
  let bestDifference = Number.POSITIVE_INFINITY;
  for (let index = 1; index < words.length; index += 1) {
    const first = words.slice(0, index).join(" ");
    const second = words.slice(index).join(" ");
    const difference = Math.abs(first.length - second.length);
    if (difference < bestDifference) {
      bestIndex = index;
      bestDifference = difference;
    }
  }
  return [words.slice(0, bestIndex).join(" "), words.slice(bestIndex).join(" ")];
}

function regionDepth(
  resource: InventoryResource,
  byId: ReadonlyMap<string, InventoryResource>,
): number {
  let depth = 0;
  let current = resource;
  while (current.parent_id && byId.has(current.parent_id)) {
    depth += 1;
    current = byId.get(current.parent_id)!;
  }
  return depth;
}
