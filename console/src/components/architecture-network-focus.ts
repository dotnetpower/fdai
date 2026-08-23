import type {
  NetworkEvidencePosture,
  NetworkPathStatus,
} from "@fdai/network-topology-contracts";
import {
  isRegion,
  resourceTypeLabelOf,
  type InventoryGraphResponse,
  type InventoryLink,
  type InventoryResource,
} from "./architecture-map.model";
import { architectureResourceAbbreviation } from "./architecture-resource-abbreviations";
import { architectureNetworkIconDataUriForResourceType } from "./architecture-network-icons";
import {
  architectureNetworkOrthogonalRoute,
  architectureNetworkPeeringRoute,
  architectureNetworkRoutePath,
  type ArchitectureNetworkRouteBox,
} from "./architecture-network-route";
import { architectureSubnetMembership } from "./architecture-network-layout";

const VNET_TYPES = new Set(["virtual-network", "network.vnet"]);
const SUBNET_TYPES = new Set(["subnet", "network.subnet"]);
const PATH_LINK_TYPES = new Set<InventoryLink["type"]>([
  "attached_to",
  "depends_on",
  "peered_with",
]);

export interface ArchitectureNetworkFilters {
  readonly publicExposure: boolean;
  readonly privateResources: boolean;
  readonly security: boolean;
  readonly gateways: boolean;
  readonly dns: boolean;
  readonly privateEndpoints: boolean;
}

export const DEFAULT_ARCHITECTURE_NETWORK_FILTERS: ArchitectureNetworkFilters = {
  publicExposure: true,
  privateResources: true,
  security: true,
  gateways: true,
  dns: true,
  privateEndpoints: true,
};

/** Chooses the observed VNet with the most contained subnets, then stable name order. */
export function defaultArchitectureNetworkFocusId(
  graph: Pick<InventoryGraphResponse, "links" | "resources">,
): string | null {
  const candidates = graph.resources.filter((resource) => VNET_TYPES.has(resource.type));
  const subnetIds = new Set(
    graph.resources.filter((resource) => SUBNET_TYPES.has(resource.type)).map((resource) => resource.id),
  );
  const score = (resourceId: string) => graph.links.filter(
    (link) => link.type === "contains" && link.source === resourceId && subnetIds.has(link.target),
  ).length;
  return [...candidates].sort(
    (first, second) => score(second.id) - score(first.id) || first.name.localeCompare(second.name),
  )[0]?.id ?? null;
}

export interface ArchitectureNetworkPathHop {
  readonly source: string;
  readonly target: string;
  readonly link: InventoryLink;
  readonly evidencePosture: Exclude<NetworkEvidencePosture, "expected">;
}

export interface ArchitectureNetworkPathResult {
  readonly status: NetworkPathStatus;
  readonly resourceIds: readonly string[];
  readonly hops: readonly ArchitectureNetworkPathHop[];
  readonly evidencePosture: Exclude<NetworkEvidencePosture, "expected">;
}

/** Selects the smallest evidence-backed network scope while retaining required ancestors. */
export function architectureNetworkFocusGraph(
  graph: InventoryGraphResponse,
  selectedId: string | null,
): InventoryGraphResponse {
  if (!selectedId) return graph;
  const byId = new Map(graph.resources.map((resource) => [resource.id, resource]));
  const selected = byId.get(selectedId);
  if (!selected) return graph;
  const focusRoot = networkFocusRoot(graph, selected) ?? selected;
  const visibleIds = new Set<string>();
  addAncestors(byId, focusRoot, visibleIds);
  visibleIds.add(focusRoot.id);

  const queue = [focusRoot.id];
  while (queue.length > 0) {
    const current = queue.shift()!;
    for (const child of graph.resources.filter((resource) => resource.parent_id === current)) {
      if (visibleIds.has(child.id)) continue;
      visibleIds.add(child.id);
      queue.push(child.id);
    }
    for (const link of graph.links.filter(
      (candidate) => candidate.type === "contains" && candidate.source === current,
    )) {
      if (visibleIds.has(link.target)) continue;
      visibleIds.add(link.target);
      queue.push(link.target);
    }
  }

  const visiblePlaneIds = new Set(
    graph.resources
      .filter((resource) => visibleIds.has(resource.id) && (VNET_TYPES.has(resource.type) || SUBNET_TYPES.has(resource.type)))
      .map((resource) => resource.id),
  );
  for (const resource of graph.resources) {
    if (resource.network_plane_id && visiblePlaneIds.has(resource.network_plane_id)) {
      visibleIds.add(resource.id);
    }
  }
  for (const link of graph.links.filter((candidate) => candidate.type !== "contains")) {
    if (visibleIds.has(link.source) || visibleIds.has(link.target)) {
      visibleIds.add(link.source);
      visibleIds.add(link.target);
    }
  }

  const visibleVnetIds = new Set(
    graph.resources
      .filter((resource) => visibleIds.has(resource.id) && VNET_TYPES.has(resource.type))
      .map((resource) => resource.id),
  );
  const peerSubnetIds = new Set(
    graph.links
      .filter(
        (link) => link.type === "contains" &&
          visibleVnetIds.has(link.source) &&
          SUBNET_TYPES.has(byId.get(link.target)?.type ?? ""),
      )
      .map((link) => link.target),
  );
  for (const subnetId of peerSubnetIds) visibleIds.add(subnetId);
  for (const resource of graph.resources) {
    if (resource.network_plane_id && peerSubnetIds.has(resource.network_plane_id)) {
      visibleIds.add(resource.id);
    }
  }
  for (const link of graph.links.filter((candidate) => candidate.type === "attached_to")) {
    if (peerSubnetIds.has(link.source)) visibleIds.add(link.target);
    if (peerSubnetIds.has(link.target)) visibleIds.add(link.source);
  }

  const focusViewId = "network-focus";

  return {
    ...graph,
    active_view: focusViewId,
    views: [
      ...(graph.views ?? []).filter((view) => view.id !== focusViewId),
      {
        id: focusViewId,
        label: "Network focus",
        kind: "service",
        classification: "service_tag",
        description: "Presentation-only observed network focus",
        root_resource_id: focusRoot.id,
      },
    ],
    resources: graph.resources
      .filter((resource) => visibleIds.has(resource.id))
      .map(resetNetworkFocusGeometry),
    links: graph.links.filter((link) => visibleIds.has(link.source) && visibleIds.has(link.target)),
  };
}

/** Applies presentation-only category filters without changing the authoritative graph. */
export function filterArchitectureNetworkGraph(
  graph: InventoryGraphResponse,
  filters: ArchitectureNetworkFilters,
): InventoryGraphResponse {
  const resources = graph.resources.filter((resource) => isRegion(resource) || networkResourceIsVisible(resource, filters));
  const ids = new Set(resources.map((resource) => resource.id));
  return {
    ...graph,
    resources,
    links: graph.links.filter((link) => ids.has(link.source) && ids.has(link.target)),
  };
}

/** Lays out observed VNet and subnet containment as a compact 2D reference map. */
export function layoutArchitectureNetworkFocusGraph(
  graph: InventoryGraphResponse,
): InventoryGraphResponse {
  const byId = new Map(graph.resources.map((resource) => [resource.id, resource]));
  const updates = new Map<string, InventoryResource>();
  const membership = architectureSubnetMembership(graph);
  const vnets = graph.resources.filter((resource) => VNET_TYPES.has(resource.type));
  const networkGap = .8;
  let networkX = 1.2;
  let networkBottom = 1;

  for (const vnet of vnets) {
    const subnets = graph.links
      .filter((link) => link.type === "contains" && link.source === vnet.id)
      .map((link) => byId.get(link.target))
      .filter((resource): resource is InventoryResource => Boolean(resource && SUBNET_TYPES.has(resource.type)));
    const subnetPlans = subnets.map((subnet) => {
      const members = graph.resources.filter(
        (resource) => !isRegion(resource) && membership.get(resource.id) === subnet.id,
      );
      const columns = Math.min(3, Math.max(1, Math.ceil(Math.sqrt(Math.max(1, members.length)))));
      const rows = Math.max(1, Math.ceil(members.length / columns));
      return { subnet, members, columns, width: Math.max(5.2, columns * 2.2 + 1), height: Math.max(3.2, rows * 1.7 + 1.4) };
    });
    const subnetColumns = Math.min(2, Math.max(1, Math.ceil(Math.sqrt(Math.max(1, subnetPlans.length)))));
    const columnWidth = Math.max(4.4, ...subnetPlans.map((plan) => plan.width));
    const rowHeight = Math.max(2.8, ...subnetPlans.map((plan) => plan.height));
    const subnetRows = Math.max(1, Math.ceil(subnetPlans.length / subnetColumns));
    const vnetWidth = subnetColumns * columnWidth + (subnetColumns + 1) * .4;
    const vnetHeight = subnetRows * rowHeight + (subnetRows + 1) * .4 + .5;
    updates.set(vnet.id, { ...vnet, x: networkX, y: 1.2, w: vnetWidth, h: vnetHeight });
    subnetPlans.forEach((plan, subnetIndex) => {
      const column = subnetIndex % subnetColumns;
      const row = Math.floor(subnetIndex / subnetColumns);
      const subnetX = networkX + .4 + column * columnWidth;
      const subnetY = 1.9 + row * rowHeight;
      updates.set(plan.subnet.id, {
        ...plan.subnet,
        x: subnetX,
        y: subnetY,
        w: plan.width - .3,
        h: plan.height - .3,
      });
      plan.members.forEach((resource, memberIndex) => {
        const memberColumn = memberIndex % plan.columns;
        const memberRow = Math.floor(memberIndex / plan.columns);
        updates.set(resource.id, {
          ...resource,
          network_plane_id: plan.subnet.id,
          x: subnetX + 1.3 + memberColumn * 2.8,
          y: subnetY + 1.35 + memberRow * 1.9,
        });
      });
    });
    networkX += vnetWidth + networkGap;
    networkBottom = Math.max(networkBottom, 1.2 + vnetHeight);
  }

  const unplaced = graph.resources.filter(
    (resource) => !isRegion(resource) && !updates.has(resource.id) && !VNET_TYPES.has(resource.type) && !SUBNET_TYPES.has(resource.type),
  );
  unplaced.forEach((resource, index) => {
    updates.set(resource.id, {
      ...resource,
      x: 1.8 + (index % 5) * 2.2,
      y: networkBottom + 1.2 + Math.floor(index / 5) * 1.7,
    });
  });
  const contentRight = Math.max(7, networkX - networkGap + .4);
  const contentBottom = networkBottom + (unplaced.length ? 2 + Math.ceil(unplaced.length / 5) * 1.25 : .6);
  const groups = graph.resources.filter((resource) => resource.type === "resource-group");
  for (const group of groups) {
    updates.set(group.id, { ...group, x: .7, y: .6, w: contentRight, h: contentBottom });
  }
  for (const subscription of graph.resources.filter((resource) => resource.type === "subscription")) {
    updates.set(subscription.id, { ...subscription, x: .2, y: .1, w: contentRight + 1, h: contentBottom + 1 });
  }

  return {
    ...graph,
    resources: graph.resources.map((resource) => updates.get(resource.id) ?? resource),
  };
}

/** Traces a shortest typed path and keeps incomplete negative results unknown. */
export function traceArchitectureNetworkPath(
  graph: Pick<InventoryGraphResponse, "freshness" | "included_link_types" | "links" | "resources" | "truncated">,
  sourceId: string | null,
  targetId: string | null,
): ArchitectureNetworkPathResult | null {
  if (!sourceId || !targetId || sourceId === targetId) return null;
  const resourceIds = new Set(graph.resources.map((resource) => resource.id));
  if (!resourceIds.has(sourceId) || !resourceIds.has(targetId)) {
    return emptyPathResult("unknown", graphEvidencePosture(graph));
  }
  const adjacency = new Map<string, Array<{ target: string; link: InventoryLink }>>();
  for (const link of graph.links) {
    if (!PATH_LINK_TYPES.has(link.type)) continue;
    addPathNeighbor(adjacency, link.source, link.target, link);
    if (link.type !== "depends_on" || link.direction === "bidirectional") {
      addPathNeighbor(adjacency, link.target, link.source, link);
    }
  }
  const queue = [sourceId];
  const previous = new Map<string, { source: string; link: InventoryLink }>();
  const visited = new Set([sourceId]);
  while (queue.length > 0 && !visited.has(targetId)) {
    const current = queue.shift()!;
    for (const neighbor of adjacency.get(current) ?? []) {
      if (visited.has(neighbor.target)) continue;
      visited.add(neighbor.target);
      previous.set(neighbor.target, { source: current, link: neighbor.link });
      queue.push(neighbor.target);
    }
  }
  if (!visited.has(targetId)) {
    const complete = !graph.truncated
      && graph.freshness === "fresh"
      && [...PATH_LINK_TYPES].every((type) => graph.included_link_types.includes(type));
    return emptyPathResult(complete ? "no_observed_path" : "unknown", graphEvidencePosture(graph));
  }

  const hops: ArchitectureNetworkPathHop[] = [];
  const path = [targetId];
  let current = targetId;
  while (current !== sourceId) {
    const step = previous.get(current);
    if (!step) return emptyPathResult("unknown", graphEvidencePosture(graph));
    const evidencePosture = step.link.evidence_posture ?? graphEvidencePosture(graph);
    hops.push({ source: step.source, target: current, link: step.link, evidencePosture });
    current = step.source;
    path.push(current);
  }
  hops.reverse();
  path.reverse();
  return {
    status: "found",
    resourceIds: path,
    hops,
    evidencePosture: graphEvidencePosture(graph),
  };
}

/** Produces an identifier-free SVG report of the current observed focus. */
export async function exportArchitectureNetworkSvg(
  graph: InventoryGraphResponse,
  path: ArchitectureNetworkPathResult | null,
): Promise<string> {
  const width = 1200;
  const height = 720;
  const padding = 64;
  const drawable = graph.resources.filter((resource) => resource.x !== undefined && resource.y !== undefined);
  const minimumX = Math.min(0, ...drawable.map((resource) => resource.x ?? 0));
  const minimumY = Math.min(0, ...drawable.map((resource) => resource.y ?? 0));
  const maximumX = Math.max(1, ...drawable.map((resource) => (resource.x ?? 0) + (resource.w ?? 1)));
  const maximumY = Math.max(1, ...drawable.map((resource) => (resource.y ?? 0) + (resource.h ?? 1)));
  const scale = Math.min(
    (width - padding * 2) / Math.max(1, maximumX - minimumX),
    (height - 150) / Math.max(1, maximumY - minimumY),
  );
  const point = (resource: InventoryResource) => ({
    x: padding + ((resource.x ?? 0) - minimumX) * scale,
    y: 108 + ((resource.y ?? 0) - minimumY) * scale,
  });
  const byId = new Map(graph.resources.map((resource) => [resource.id, resource]));
  const highlighted = new Set(path?.resourceIds ?? []);
  const iconByType = new Map(
    await Promise.all(
      [...new Set(graph.resources.filter((resource) => !isRegion(resource)).map((resource) => resource.type))]
        .map(async (type) => [type, await architectureNetworkIconDataUriForResourceType(type)] as const),
    ),
  );
  const box = (resource: InventoryResource) => {
    const position = point(resource);
    if (isRegion(resource)) {
      return {
        x: position.x,
        y: position.y,
        width: Math.max(80, (resource.w ?? 2) * scale),
        height: Math.max(56, (resource.h ?? 2) * scale),
      };
    }
    return { x: position.x - 48, y: position.y - 36, width: 96, height: 72 };
  };
  const routeBox = (resource: InventoryResource): ArchitectureNetworkRouteBox => ({
    id: resource.id,
    ...box(resource),
  });
  const routeObstacles = graph.resources.filter((resource) => !isRegion(resource)).map(routeBox);
  const edges = graph.links.filter((link) => link.type !== "contains").map((link, index) => {
    const source = byId.get(link.source);
    const target = byId.get(link.target);
    if (!source || !target) return "";
    const sourceBox = routeBox(source);
    const targetBox = routeBox(target);
    const routePoints = link.type === "peered_with" && isRegion(source) && isRegion(target)
      ? architectureNetworkPeeringRoute(sourceBox, targetBox)
      : architectureNetworkOrthogonalRoute(sourceBox, targetBox, routeObstacles);
    const end = routePoints.at(-1)!;
    const route = architectureNetworkRoutePath(
      routePoints.map((point) => ({ x: Number(point.x.toFixed(1)), y: Number(point.y.toFixed(1)) })),
    );
    const active = highlighted.size === 0 || (highlighted.has(source.id) && highlighted.has(target.id));
    const color = link.type === "attached_to" ? "#12715a" : "#315f82";
    const directional = link.type === "depends_on" || link.type === "peered_with";
    const markerEnd = directional ? ' marker-end="url(#network-arrow)"' : "";
    const markerStart = link.type === "peered_with" ? ' marker-start="url(#network-arrow-start)"' : "";
    const endpoint = link.type === "attached_to"
      ? `<circle cx="${end.x.toFixed(1)}" cy="${end.y.toFixed(1)}" r="5" fill="#ffffff"/><circle cx="${end.x.toFixed(1)}" cy="${end.y.toFixed(1)}" r="3" fill="${color}"/>`
      : "";
    return `<g data-edge-index="${index}" data-relationship-type="${link.type}" opacity="${active ? "1" : ".24"}"><title>Relationship ${index + 1}: ${link.type}</title><path d="${route}" fill="none" stroke="#ffffff" stroke-width="7" stroke-linecap="round" stroke-linejoin="round"/><path d="${route}" fill="none" stroke="${color}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"${markerStart}${markerEnd}/>${endpoint}</g>`;
  }).join("");
  const nodes = graph.resources.map((resource, index) => {
    const position = point(resource);
    const label = escapeXml(resourceTypeLabelOf(resource));
    if (isRegion(resource)) {
      return `<g data-region-index="${index}"><rect x="${position.x.toFixed(1)}" y="${position.y.toFixed(1)}" width="${Math.max(80, (resource.w ?? 2) * scale).toFixed(1)}" height="${Math.max(56, (resource.h ?? 2) * scale).toFixed(1)}" fill="none" stroke="#6f8ba4" stroke-dasharray="6 4"/><text x="${(position.x + 10).toFixed(1)}" y="${(position.y + 20).toFixed(1)}">${label}</text></g>`;
    }
    const bounds = box(resource);
    const icon = iconByType.get(resource.type);
    const glyph = escapeXml(architectureResourceAbbreviation(resource.type));
    return `<g data-node-index="${index}"><rect x="${bounds.x.toFixed(1)}" y="${bounds.y.toFixed(1)}" width="${bounds.width}" height="${bounds.height}" rx="8" fill="#ffffff" stroke="${highlighted.has(resource.id) ? "#0f6cbd" : "#6f8ba4"}" stroke-width="${highlighted.has(resource.id) ? "3" : "1.5"}"/>${icon ? `<image href="${icon}" x="${(position.x - 17).toFixed(1)}" y="${(position.y - 28).toFixed(1)}" width="34" height="34"/>` : `<text x="${position.x.toFixed(1)}" y="${(position.y - 7).toFixed(1)}" text-anchor="middle" font-weight="700">${glyph}</text>`}<text x="${position.x.toFixed(1)}" y="${(position.y + 22).toFixed(1)}" text-anchor="middle" font-weight="650">${label}</text></g>`;
  }).join("");
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="img" aria-labelledby="title description"><title id="title">Observed network topology</title><desc id="description">Read-only observed topology. Resource identifiers and names are omitted.</desc><defs><marker id="network-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 1L9 5L0 9z" fill="#315f82"/></marker><marker id="network-arrow-start" viewBox="0 0 10 10" refX="1" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M10 1L1 5L10 9z" fill="#315f82"/></marker></defs><rect width="${width}" height="${height}" fill="#f7f9fb"/><text x="${padding}" y="42" font-size="24" font-weight="700">Observed network topology</text><text x="${padding}" y="70" font-size="13">Read-only observed topology | ${escapeXml(graph.freshness)} | ${escapeXml(graph.snapshot_at)} | ${graph.truncated ? "partial" : "complete"}</text><g font-family="Noto Sans, Segoe UI, sans-serif" font-size="12" fill="#263543">${edges}${nodes}<g transform="translate(${padding} 690)"><path d="M0 0H34" fill="none" stroke="#315f82" stroke-width="3" marker-end="url(#network-arrow)"/><text x="44" y="4">Depends on</text><path d="M144 0H178" fill="none" stroke="#12715a" stroke-width="3"/><text x="188" y="4">Attached to</text><path d="M292 0H326" fill="none" stroke="#315f82" stroke-width="3" marker-start="url(#network-arrow-start)" marker-end="url(#network-arrow)"/><text x="336" y="4">Peered with</text><rect x="440" y="-9" width="28" height="16" fill="none" stroke="#6f8ba4" stroke-dasharray="6 4"/><text x="478" y="4">Boundary</text></g></g></svg>\n`;
}

function networkFocusRoot(
  graph: Pick<InventoryGraphResponse, "links" | "resources">,
  selected: InventoryResource,
): InventoryResource | undefined {
  const byId = new Map(graph.resources.map((resource) => [resource.id, resource]));
  if (selected.type === "resource-group" || VNET_TYPES.has(selected.type)) return selected;
  const plane = selected.network_plane_id ? byId.get(selected.network_plane_id) : undefined;
  const subnet = SUBNET_TYPES.has(selected.type) ? selected : plane && SUBNET_TYPES.has(plane.type) ? plane : undefined;
  if (subnet) {
    const vnetId = graph.links.find(
      (link) => link.type === "contains" && link.target === subnet.id && VNET_TYPES.has(byId.get(link.source)?.type ?? ""),
    )?.source;
    if (vnetId) return byId.get(vnetId);
  }
  let current: InventoryResource | undefined = selected;
  while (current?.parent_id) {
    current = byId.get(current.parent_id);
    if (current?.type === "resource-group") return current;
  }
  return selected;
}

function resetNetworkFocusGeometry(resource: InventoryResource): InventoryResource {
  if (resource.type === "subscription" || resource.type === "resource-group") return resource;
  const {
    x: _x,
    y: _y,
    w: _w,
    h: _h,
    render_scale: _renderScale,
    ...semanticResource
  } = resource;
  return semanticResource;
}

function addAncestors(
  byId: ReadonlyMap<string, InventoryResource>,
  resource: InventoryResource,
  ids: Set<string>,
): void {
  let current: InventoryResource | undefined = resource;
  while (current) {
    ids.add(current.id);
    current = current.parent_id ? byId.get(current.parent_id) : undefined;
  }
}

function networkResourceIsVisible(
  resource: InventoryResource,
  filters: ArchitectureNetworkFilters,
): boolean {
  const type = resource.type;
  if (!filters.publicExposure && ["front-door", "network.public-ip"].includes(type)) return false;
  if (!filters.privateEndpoints && type === "network.private-endpoint") return false;
  if (!filters.privateResources && (type.includes("private") || type === "network.private-endpoint")) return false;
  if (!filters.security && ["firewall", "network.firewall", "network.nsg", "network-security-group", "nsg"].includes(type)) return false;
  if (!filters.gateways && (type.includes("gateway") || type.includes("load-balancer"))) return false;
  if (!filters.dns && type.includes("dns")) return false;
  return true;
}

function graphEvidencePosture(
  graph: Pick<InventoryGraphResponse, "freshness" | "truncated">,
): Exclude<NetworkEvidencePosture, "expected"> {
  if (graph.truncated) return "partial";
  if (graph.freshness === "stale") return "stale";
  if (graph.freshness === "fresh") return "observed";
  return "unknown";
}

function emptyPathResult(
  status: Exclude<NetworkPathStatus, "found">,
  evidencePosture: Exclude<NetworkEvidencePosture, "expected">,
): ArchitectureNetworkPathResult {
  return { status, resourceIds: [], hops: [], evidencePosture };
}

function addPathNeighbor(
  adjacency: Map<string, Array<{ target: string; link: InventoryLink }>>,
  source: string,
  target: string,
  link: InventoryLink,
): void {
  const neighbors = adjacency.get(source) ?? [];
  neighbors.push({ target, link });
  adjacency.set(source, neighbors);
}

function escapeXml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&apos;");
}
