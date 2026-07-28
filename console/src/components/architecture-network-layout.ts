import {
  architectureViewIsFocused,
  isAuxiliaryArchitectureResource,
  isRegion,
  type InventoryGraphResponse,
  type InventoryResource,
} from "./architecture-map.model";

const VNET_TYPES = new Set(["virtual-network", "network.vnet"]);
const SUBNET_TYPES = new Set(["subnet", "network.subnet"]);
const CELL_WIDTH = 1.65;
const CELL_HEIGHT = 1.2;
const PANEL_GAP = .45;

interface PackedItem<T> {
  readonly item: T;
  readonly x: number;
  readonly y: number;
}

interface RectangleItem {
  readonly width: number;
  readonly height: number;
}

interface SubnetPlan extends RectangleItem {
  readonly subnet: InventoryResource;
  readonly members: readonly InventoryResource[];
}

interface NetworkPlan extends RectangleItem {
  readonly vnet: InventoryResource | null;
  readonly subnets: readonly PackedItem<SubnetPlan>[];
}

interface GroupPlan extends RectangleItem {
  readonly group: InventoryResource;
  readonly networks: readonly PackedItem<NetworkPlan>[];
  readonly unassigned: readonly InventoryResource[];
  readonly unassignedTop: number;
}

export function isArchitectureNetworkPlane(resource: InventoryResource): boolean {
  return isRegion(resource) && (VNET_TYPES.has(resource.type) || SUBNET_TYPES.has(resource.type));
}

export function layoutArchitectureNetworkFloors(
  graph: InventoryGraphResponse,
): InventoryGraphResponse {
  const rawPlanes = graph.resources.filter(
    (resource) => VNET_TYPES.has(resource.type) || SUBNET_TYPES.has(resource.type),
  );
  if (rawPlanes.length === 0 || rawPlanes.some(isRegion)) return graph;

  const subscriptions = graph.resources.filter(
    (resource) => resource.type === "subscription" && isRegion(resource),
  );
  const groups = graph.resources.filter(
    (resource) => resource.type === "resource-group" && isRegion(resource),
  );
  if (subscriptions.length === 0 || groups.length === 0) return graph;

  const membership = architectureSubnetMembership(graph);
  const subnetByVnet = architectureSubnetsByVnet(graph);
  const updates = new Map<string, InventoryResource>();

  for (const subscription of subscriptions) {
    const childGroups = groups.filter((group) => group.parent_id === subscription.id);
    if (childGroups.length === 0) continue;
    const groupPlans = childGroups.map((group) => buildGroupPlan(
      graph,
      group,
      membership,
      subnetByVnet,
    ));
    const packedGroups = packRectangles(groupPlans, layoutTargetWidth(groupPlans), PANEL_GAP);
    const subscriptionX = subscription.x ?? 0;
    const subscriptionY = subscription.y ?? 0;
    const insetX = .45;
    const insetTop = .85;
    for (const placement of packedGroups.items) {
      applyGroupPlan(
        placement.item,
        subscriptionX + insetX + placement.x,
        subscriptionY + insetTop + placement.y,
        updates,
      );
    }
    const fittedWidth = insetX * 2 + packedGroups.width;
    const fittedHeight = insetTop + .4 + packedGroups.height;
    updates.set(subscription.id, {
      ...subscription,
      w: architectureViewIsFocused(graph)
        ? fittedWidth
        : Math.max(subscription.w ?? 0, fittedWidth),
      h: architectureViewIsFocused(graph)
        ? fittedHeight
        : Math.max(subscription.h ?? 0, fittedHeight),
    });
  }

  const byId = new Map(graph.resources.map((resource) => [resource.id, resource]));
  for (const [resourceId, networkPlaneId] of membership) {
    const resource = updates.get(resourceId) ?? byId.get(resourceId);
    if (resource) updates.set(resourceId, { ...resource, network_plane_id: networkPlaneId });
  }

  return {
    ...graph,
    resources: graph.resources.map((resource) => updates.get(resource.id) ?? resource),
  };
}

export function architectureSubnetMembership(
  graph: Pick<InventoryGraphResponse, "resources" | "links">,
): ReadonlyMap<string, string> {
  const subnetIds = new Set(
    graph.resources.filter((resource) => SUBNET_TYPES.has(resource.type)).map((resource) => resource.id),
  );
  const adjacency = new Map<string, Set<string>>();
  for (const link of graph.links.filter((candidate) => candidate.type === "attached_to")) {
    addNeighbor(adjacency, link.source, link.target);
    addNeighbor(adjacency, link.target, link.source);
  }

  const membership = new Map<string, string>();
  for (const resource of graph.resources) {
    if (subnetIds.has(resource.id) || VNET_TYPES.has(resource.type)) continue;
    const nearest = nearestUniqueSubnet(resource.id, subnetIds, adjacency);
    if (nearest) membership.set(resource.id, nearest);
  }
  return membership;
}

function nearestUniqueSubnet(
  resourceId: string,
  subnetIds: ReadonlySet<string>,
  adjacency: ReadonlyMap<string, ReadonlySet<string>>,
): string | null {
  const queue: Array<{ readonly id: string; readonly distance: number }> = [
    { id: resourceId, distance: 0 },
  ];
  const visited = new Set([resourceId]);
  const candidates = new Set<string>();
  let nearestDistance = Number.POSITIVE_INFINITY;
  while (queue.length > 0) {
    const current = queue.shift()!;
    if (current.distance > 2 || current.distance > nearestDistance) continue;
    if (subnetIds.has(current.id)) {
      nearestDistance = current.distance;
      candidates.add(current.id);
      continue;
    }
    for (const neighbor of adjacency.get(current.id) ?? []) {
      if (visited.has(neighbor)) continue;
      visited.add(neighbor);
      queue.push({ id: neighbor, distance: current.distance + 1 });
    }
  }
  return candidates.size === 1 ? [...candidates][0]! : null;
}

function architectureSubnetsByVnet(
  graph: Pick<InventoryGraphResponse, "resources" | "links">,
): ReadonlyMap<string, readonly InventoryResource[]> {
  const byId = new Map(graph.resources.map((resource) => [resource.id, resource]));
  const result = new Map<string, InventoryResource[]>();
  for (const link of graph.links) {
    const source = byId.get(link.source);
    const target = byId.get(link.target);
    if (
      link.type !== "contains"
      || !source
      || !target
      || !VNET_TYPES.has(source.type)
      || !SUBNET_TYPES.has(target.type)
    ) continue;
    const subnets = result.get(source.id) ?? [];
    subnets.push(target);
    result.set(source.id, subnets);
  }
  return result;
}

function buildGroupPlan(
  graph: InventoryGraphResponse,
  group: InventoryResource,
  membership: ReadonlyMap<string, string>,
  subnetByVnet: ReadonlyMap<string, readonly InventoryResource[]>,
): GroupPlan {
  const vnets = graph.resources.filter(
    (resource) => resource.parent_id === group.id && VNET_TYPES.has(resource.type),
  );
  const subnets = graph.resources.filter(
    (resource) => resource.parent_id === group.id && SUBNET_TYPES.has(resource.type),
  );
  const visibleNodes = graph.resources.filter((resource) =>
    resource.parent_id === group.id
    && !isRegion(resource)
    && !VNET_TYPES.has(resource.type)
    && !SUBNET_TYPES.has(resource.type)
    && !isAuxiliaryArchitectureResource(resource));
  const membersBySubnet = new Map<string, InventoryResource[]>();
  const unassigned: InventoryResource[] = [];
  for (const node of visibleNodes) {
    const subnetId = membership.get(node.id);
    if (!subnetId || !subnets.some((subnet) => subnet.id === subnetId)) {
      unassigned.push(node);
      continue;
    }
    const members = membersBySubnet.get(subnetId) ?? [];
    members.push(node);
    membersBySubnet.set(subnetId, members);
  }

  const ownedSubnetIds = new Set<string>();
  const networkPlans: NetworkPlan[] = vnets.map((vnet) => {
    const ownedSubnets = subnetByVnet.get(vnet.id) ?? [];
    ownedSubnets.forEach((subnet) => ownedSubnetIds.add(subnet.id));
    return buildNetworkPlan(vnet, ownedSubnets, membersBySubnet);
  });
  for (const subnet of subnets.filter((candidate) => !ownedSubnetIds.has(candidate.id))) {
    networkPlans.push(buildNetworkPlan(null, [subnet], membersBySubnet));
  }
  const packedNetworks = packRectangles(
    networkPlans,
    layoutTargetWidth(networkPlans),
    PANEL_GAP,
  );
  const unassignedGrid = nodeGrid(unassigned);
  const unassignedTop = packedNetworks.height > 0 ? .85 + packedNetworks.height + .55 : .85;
  return {
    group,
    networks: packedNetworks.items,
    unassigned,
    unassignedTop,
    width: Math.max(4.8, .9 + packedNetworks.width, .9 + unassignedGrid.width),
    height: Math.max(
      3.4,
      unassignedTop + unassignedGrid.height + .4,
      .85 + packedNetworks.height + .4,
    ),
  };
}

function buildNetworkPlan(
  vnet: InventoryResource | null,
  subnets: readonly InventoryResource[],
  membersBySubnet: ReadonlyMap<string, readonly InventoryResource[]>,
): NetworkPlan {
  const subnetPlans = subnets.map((subnet) => buildSubnetPlan(
    subnet,
    membersBySubnet.get(subnet.id) ?? [],
  ));
  if (vnet === null && subnetPlans.length === 1) {
    return { vnet, subnets: [{ item: subnetPlans[0]!, x: 0, y: 0 }], ...subnetPlans[0]! };
  }
  const packedSubnets = packRectangles(
    subnetPlans,
    layoutTargetWidth(subnetPlans),
    .35,
  );
  return {
    vnet,
    subnets: packedSubnets.items.map((placement) => ({
      ...placement,
      x: placement.x + .45,
      y: placement.y + .8,
    })),
    width: Math.max(4.8, packedSubnets.width + .9),
    height: Math.max(3.4, packedSubnets.height + 1.2),
  };
}

function buildSubnetPlan(
  subnet: InventoryResource,
  members: readonly InventoryResource[],
): SubnetPlan {
  const grid = nodeGrid(members);
  return {
    subnet,
    members,
    width: Math.max(4.8, grid.width + .9),
    height: Math.max(3.4, grid.height + 1.15),
  };
}

function applyGroupPlan(
  plan: GroupPlan,
  groupX: number,
  groupY: number,
  updates: Map<string, InventoryResource>,
): void {
  updates.set(plan.group.id, { ...plan.group, x: groupX, y: groupY, w: plan.width, h: plan.height });
  for (const networkPlacement of plan.networks) {
    const networkX = groupX + .45 + networkPlacement.x;
    const networkY = groupY + .85 + networkPlacement.y;
    const network = networkPlacement.item;
    if (network.vnet) {
      updates.set(network.vnet.id, {
        ...network.vnet,
        x: networkX,
        y: networkY,
        w: network.width,
        h: network.height,
      });
    }
    for (const subnetPlacement of network.subnets) {
      const subnetX = networkX + subnetPlacement.x;
      const subnetY = networkY + subnetPlacement.y;
      const subnet = subnetPlacement.item;
      updates.set(subnet.subnet.id, {
        ...subnet.subnet,
        x: subnetX,
        y: subnetY,
        w: subnet.width,
        h: subnet.height,
      });
      placeNodes(subnet.members, subnetX + .45, subnetY + .75, subnet.subnet.id, updates);
    }
  }
  placeNodes(plan.unassigned, groupX + .45, groupY + plan.unassignedTop, null, updates);
}

function placeNodes(
  nodes: readonly InventoryResource[],
  originX: number,
  originY: number,
  networkPlaneId: string | null,
  updates: Map<string, InventoryResource>,
): void {
  const columns = nodeGrid(nodes).columns;
  nodes.forEach((node, index) => {
    const { network_plane_id: _networkPlaneId, ...baseNode } = node;
    const positioned = {
      ...baseNode,
      render_scale: Math.max(1, node.render_scale ?? 1),
      x: originX + (index % columns + .5) * CELL_WIDTH,
      y: originY + (Math.floor(index / columns) + .5) * CELL_HEIGHT,
    };
    updates.set(node.id, networkPlaneId
      ? { ...positioned, network_plane_id: networkPlaneId }
      : positioned);
  });
}

function nodeGrid(nodes: readonly InventoryResource[]): {
  readonly columns: number;
  readonly width: number;
  readonly height: number;
} {
  if (nodes.length === 0) return { columns: 1, width: 0, height: 0 };
  const columns = Math.min(5, Math.max(1, Math.ceil(Math.sqrt(Math.max(1, nodes.length)))));
  const rows = Math.max(1, Math.ceil(nodes.length / columns));
  return { columns, width: columns * CELL_WIDTH, height: rows * CELL_HEIGHT };
}

function packRectangles<T extends RectangleItem>(
  items: readonly T[],
  targetWidth: number,
  gap: number,
): { readonly items: readonly PackedItem<T>[]; readonly width: number; readonly height: number } {
  const placements: PackedItem<T>[] = [];
  let x = 0;
  let y = 0;
  let rowHeight = 0;
  let maximumRight = 0;
  for (const item of [...items].sort((first, second) =>
    second.width * second.height - first.width * first.height)) {
    if (x > 0 && x + item.width > targetWidth) {
      x = 0;
      y += rowHeight + gap;
      rowHeight = 0;
    }
    placements.push({ item, x, y });
    maximumRight = Math.max(maximumRight, x + item.width);
    rowHeight = Math.max(rowHeight, item.height);
    x += item.width + gap;
  }
  return {
    items: placements,
    width: maximumRight,
    height: placements.length === 0 ? 0 : y + rowHeight,
  };
}

function layoutTargetWidth(items: readonly RectangleItem[]): number {
  if (items.length === 0) return 0;
  return Math.max(
    ...items.map((item) => item.width),
    Math.sqrt(items.reduce((total, item) => total + item.width * item.height, 0)) * 1.8,
  );
}

function addNeighbor(adjacency: Map<string, Set<string>>, source: string, target: string): void {
  const neighbors = adjacency.get(source) ?? new Set<string>();
  neighbors.add(target);
  adjacency.set(source, neighbors);
}
