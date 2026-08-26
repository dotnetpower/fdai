import { describe, expect, it } from "vitest";
import {
  buildInstanceEdgeGeometry,
  buildInstanceGraphLayout,
  buildInstanceTimeline,
  clampInstanceGraphScale,
  countInstanceLinkTypes,
  defaultInstanceLegendLinkTypes,
  instanceGraphFitScale,
  instanceGraphPathNodeIds,
  instanceGraphScrollTarget,
  instanceGraphZoomScrollTarget,
  instanceGraphWheelScale,
  instanceGraphLevels,
  INSTANCE_GRAPH_MAX_SCALE,
  INSTANCE_GRAPH_MIN_SCALE,
  INSTANCE_NODE_HEIGHT,
  showInstanceEdgeLabels,
} from "./ontology-instance-graph.model";
import type {
  OntologyInstanceActivity,
  OntologyInstanceExploration,
  OntologyInstanceLink,
  OntologyInstanceResource,
} from "./ontology-instances.model";

describe("buildInstanceGraphLayout", () => {
  it("moves dense relationship meaning to edge titles and the inspector", () => {
    expect(showInstanceEdgeLabels(20)).toBe(true);
    expect(showInstanceEdgeLabels(21)).toBe(false);
    expect(showInstanceEdgeLabels(79)).toBe(false);
  });

  it("counts dense relationship types in deterministic order", () => {
    const counts = countInstanceLinkTypes([
      link("root", "a", "depends_on"),
      link("root", "b", "contains"),
      link("root", "c", "depends_on"),
    ]);

    expect(counts).toEqual([
      { linkType: "contains", count: 1 },
      { linkType: "depends_on", count: 2 },
    ]);
  });

  it("keeps the default dense legend limited to structural relationship types", () => {
    const counts = countInstanceLinkTypes([
      link("root", "a", "routes_to"),
      link("root", "b", "depends_on"),
      link("root", "c", "contains"),
      link("root", "d", "kubernetes_owned_by"),
      link("root", "e", "attached_to"),
    ]);

    expect(defaultInstanceLegendLinkTypes(counts)).toEqual([
      { linkType: "attached_to", count: 1 },
      { linkType: "contains", count: 1 },
      { linkType: "depends_on", count: 1 },
    ]);
  });

  it("places incoming, root, and outgoing Resources in non-overlapping columns", () => {
    const data = exploration();
    const layout = buildInstanceGraphLayout(data);
    const byId = new Map(layout.nodes.map((node) => [node.resource.id, node]));

    expect(layout.direction).toBe("LR");
    expect(byId.get("incoming")?.x).toBeLessThan(byId.get("root")!.x);
    expect(byId.get("outgoing")?.x).toBeGreaterThan(byId.get("root")!.x);
    expect(byId.get("outgoing")!.x - byId.get("root")!.x)
      .toBeGreaterThanOrEqual(280);
    expect(byId.get("root")).toMatchObject({ distance: 0, emphasis: "root" });
    expect(byId.get("incoming")).toMatchObject({ distance: 1, emphasis: "direct", lane: "dependency" });
    expect(byId.get("outgoing")).toMatchObject({ distance: 1, emphasis: "direct", lane: "dependency" });
    expect(layout.edges).toHaveLength(2);
    expect(layout.edges.every((edge) =>
      edge.lane !== "dependency" || edge.source.x < edge.target.x)).toBe(true);
    expect(layout.hiddenNodeCount).toBe(0);
    expect(layout.hiddenEdgeCount).toBe(0);
    expect(layout.width).toBeGreaterThan(700);
    expect(layout.nodes.every((node) => node.y >= 0 && node.y + INSTANCE_NODE_HEIGHT <= layout.height)).toBe(true);
  });

  it("keeps indirect Resources in stored left-to-right edge direction", () => {
    const data = exploration();
    const sibling = resource("sibling");
    const connected: OntologyInstanceExploration = {
      ...data,
      resources: [...data.resources, sibling],
      links: [...data.links, link("incoming", "sibling", "attached_to")],
    };

    const layout = buildInstanceGraphLayout(connected);
    const byId = new Map(layout.nodes.map((node) => [node.resource.id, node]));

    expect(byId.get("incoming")).toMatchObject({ level: -1, distance: 1, parentId: "root" });
    expect(byId.get("sibling")).toMatchObject({
      level: 1,
      distance: 2,
      emphasis: "indirect",
      lane: "access",
      parentId: "incoming",
    });
    expect(byId.get("sibling")!.x).toBeGreaterThan(byId.get("incoming")!.x);
    expect([...instanceGraphPathNodeIds(layout.nodes, "sibling")]).toEqual([
      "sibling",
      "incoming",
      "root",
    ]);
  });

  it("lays out a stored-direction ingress-to-egress path across signed levels", () => {
    const data = exploration();
    const ingress = resource("ingress");
    const environment = resource("environment");
    const subnet = resource("subnet");
    const egress = resource("egress");
    const connected: OntologyInstanceExploration = {
      ...data,
      resources: [data.resources[0]!, ingress, environment, subnet, egress],
      links: [
        link("ingress", "root", "routes_to"),
        link("root", "environment", "depends_on"),
        link("environment", "subnet", "attached_to"),
        link("subnet", "egress", "attached_to"),
      ],
    };

    const levels = instanceGraphLevels(connected);
    const layout = buildInstanceGraphLayout(connected);
    const byId = new Map(layout.nodes.map((node) => [node.resource.id, node]));

    expect([...levels.entries()]).toEqual([
      ["root", 0],
      ["ingress", -1],
      ["environment", 1],
      ["subnet", 2],
      ["egress", 3],
    ]);
    expect(byId.get("ingress")!.x).toBeLessThan(byId.get("root")!.x);
    expect(byId.get("subnet")!.x).toBeGreaterThan(byId.get("environment")!.x);
    expect(layout.edges.every((edge) =>
      edge.lane !== "dependency" || edge.source.x < edge.target.x)).toBe(true);
    expect(byId.has("egress")).toBe(false);
    expect(layout.hiddenNodeCount).toBe(1);
    expect(layout.hiddenEdgeCount).toBe(1);
  });

  it("keeps direct containment in its own lane instead of dependency context", () => {
    const data = exploration();
    const group = resource("group");
    const contained: OntologyInstanceExploration = {
      ...data,
      resources: [...data.resources, group],
      links: [...data.links, link("group", "root", "contains")],
    };

    const layout = buildInstanceGraphLayout(contained);
    const groupNode = layout.nodes.find((node) => node.resource.id === "group");
    const containsEdge = layout.edges.find((edge) => edge.link.link_type === "contains");

    expect(groupNode).toMatchObject({ level: -2, lane: "containment", emphasis: "direct" });
    expect(containsEdge).toMatchObject({ lane: "containment", graphDirection: "incoming" });
    expect(containsEdge!.source.x).toBeLessThan(containsEdge!.target.x);
    expect(layout.hiddenNodeCount).toBe(0);
    expect(layout.hiddenEdgeCount).toBe(0);
  });

  it("keeps what a root contains below what it is attached to", () => {
    const data = exploration();
    const attached = Array.from({ length: 2 }, (_value, index) =>
      resource(`attached-${index}`, false, "managed-identity"));
    const contained = Array.from({ length: 3 }, (_value, index) =>
      resource(`contained-${index}`, false, "kubernetes.namespace"));
    const connected: OntologyInstanceExploration = {
      ...data,
      resources: [data.resources[0]!, ...attached, ...contained],
      links: [
        ...attached.map((item) => link(data.root_id, item.id, "attached_to")),
        ...contained.map((item) => link(data.root_id, item.id, "contains")),
      ],
    };

    const layout = buildInstanceGraphLayout(connected);
    const byId = new Map(layout.nodes.map((node) => [node.resource.id, node]));
    const rootY = byId.get(data.root_id)!.y;

    contained.forEach((item) => expect(byId.get(item.id)!.y).toBeGreaterThan(rootY));
  });

  it("breaks a shared column between attached and contained Resources", () => {
    const data = exploration();
    const cluster = resource(data.root_id, true, "kubernetes-cluster");
    const namespace = resource("namespace", false, "kubernetes.namespace");
    const service = resource("service", false, "kubernetes.service");
    const pods = Array.from({ length: 2 }, (_value, index) =>
      resource(`pod-${index}`, false, "kubernetes.pod"));
    const connected: OntologyInstanceExploration = {
      ...data,
      resources: [cluster, namespace, service, ...pods],
      links: [
        link(data.root_id, namespace.id, "contains"),
        link(namespace.id, service.id, "attached_to"),
        ...pods.map((pod) => link(namespace.id, pod.id, "contains")),
      ],
    };

    const layout = buildInstanceGraphLayout(connected);
    const byId = new Map(layout.nodes.map((node) => [node.resource.id, node]));
    const serviceNode = byId.get(service.id)!;
    const podYs = pods.map((pod) => byId.get(pod.id)!.y);

    expect(new Set(podYs.concat(serviceNode.y).map(() => serviceNode.level)).size).toBe(1);
    podYs.forEach((podY) => expect(podY).toBeGreaterThan(serviceNode.y));
    // One row alone would read as a single run; the break has to be visible.
    expect(Math.min(...podYs) - serviceNode.y).toBeGreaterThan(80);
  });

  it("separates stored Kubernetes runtime and traffic relationships", () => {    const data = exploration();
    const runtime = resource("runtime", false, "kubernetes.node");
    const traffic = resource("traffic", false, "kubernetes.service");
    const connected: OntologyInstanceExploration = {
      ...data,
      resources: [data.resources[0]!, runtime, traffic],
      links: [
        linkWithMapping(
          data.root_id,
          runtime.id,
          "kubernetes_backed_by",
          "kubernetes.node-backed-by-vmss-vm",
        ),
        linkWithMapping(
          data.root_id,
          traffic.id,
          "routes_to",
          "kubernetes.ingress-routes-to-service",
        ),
      ],
    };

    const layout = buildInstanceGraphLayout(connected);

    expect(layout.edges.find((edge) => edge.link.target === runtime.id)?.lane).toBe("runtime");
    expect(layout.edges.find((edge) => edge.link.target === traffic.id)?.lane).toBe("traffic");
  });

  it("bounds high-cardinality scope roots without expanding each child branch", () => {
    const root = resource("root", true, "resource-group");
    const roleAssignments = Array.from(
      { length: 50 },
      (_value, index) => resource(`role-${index}`, false, "authorization.role-assignment"),
    );
    const workloads = Array.from({ length: 20 }, (_value, index) =>
      resource(`workload-${index}`, false, `service.type-${index % 10}`));
    const indirect = workloads.map((workload) =>
      resource(`indirect-${workload.id}`, false, "network.interface"));
    const connected: OntologyInstanceExploration = {
      ...exploration(),
      root_id: root.id,
      resources: [root, ...roleAssignments, ...workloads, ...indirect],
      links: [
        ...roleAssignments.map((item) => link(root.id, item.id, "contains")),
        ...workloads.map((item) => link(root.id, item.id, "contains")),
        ...workloads.map((item, index) => link(item.id, indirect[index]!.id, "attached_to")),
        link(workloads[0]!.id, workloads[1]!.id, "depends_on"),
        link(workloads[0]!.id, workloads[1]!.id, "attached_to"),
        link(workloads[1]!.id, workloads[2]!.id, "routes_to"),
      ],
    };

    const layout = buildInstanceGraphLayout(connected);
    const visibleIds = new Set(layout.nodes.map((node) => node.resource.id));
    const visibleTypes = new Set(layout.nodes.map((node) => node.resource.resource_type));

    expect(visibleIds.size).toBe(8);
    expect(layout.edges).toHaveLength(8);
    expect(layout.edges.some((edge) =>
      edge.link.source === workloads[0]!.id
      && edge.link.target === workloads[1]!.id
      && edge.link.link_type === "attached_to")).toBe(true);
    expect(layout.edges.some((edge) =>
      edge.link.source === workloads[0]!.id
      && edge.link.target === workloads[1]!.id
      && edge.link.link_type === "depends_on")).toBe(false);
    expect(layout.edges.some((edge) =>
      edge.link.source === workloads[1]!.id
      && edge.link.target === workloads[2]!.id
      && edge.link.link_type === "routes_to")).toBe(false);
    expect([...visibleIds].some((id) => id.startsWith("indirect-"))).toBe(false);
    expect(visibleTypes.has("authorization.role-assignment")).toBe(false);
    expect(Array.from({ length: 7 }, (_value, index) => `service.type-${index}`)
      .every((type) => visibleTypes.has(type))).toBe(true);
    expect(layout.hiddenNodeCount).toBe(83);
    expect(layout.hiddenEdgeCount).toBe(85);
  });

  it("keeps exact VM attachments between visible Resource Group children", () => {
    const group = resource("group", true, "resource-group");
    const virtualMachine = resource("vm", false, "compute.vm");
    const disk = resource("disk", false, "disk");
    const networkInterface = resource("nic", false, "network.interface");
    const connected: OntologyInstanceExploration = {
      ...exploration(),
      root_id: group.id,
      resources: [group, virtualMachine, disk, networkInterface],
      links: [
        link(group.id, virtualMachine.id, "contains"),
        link(group.id, disk.id, "contains"),
        link(group.id, networkInterface.id, "contains"),
        linkWithMapping(
          disk.id,
          virtualMachine.id,
          "attached_to",
          "azure.vm-os-disk-attached-to-vm",
        ),
        linkWithMapping(
          networkInterface.id,
          virtualMachine.id,
          "attached_to",
          "azure.vm-nic-attached-to-vm",
        ),
      ],
    };

    const layout = buildInstanceGraphLayout(connected);
    const byId = new Map(layout.nodes.map((node) => [node.resource.id, node]));
    const attachments = layout.edges.filter((edge) => edge.link.link_type === "attached_to");

    expect(layout.nodes).toHaveLength(4);
    expect(layout.edges).toHaveLength(5);
    expect(attachments.map((edge) => edge.link.evidence.mapping_id)).toEqual([
      "azure.vm-os-disk-attached-to-vm",
      "azure.vm-nic-attached-to-vm",
    ]);
    expect(byId.get(disk.id)!.x).toBeLessThan(byId.get(virtualMachine.id)!.x);
    expect(byId.get(networkInterface.id)!.x).toBeLessThan(byId.get(virtualMachine.id)!.x);
    expect(attachments.every((edge) => edge.source.x < edge.target.x)).toBe(true);
    expect(layout.hiddenNodeCount).toBe(0);
    expect(layout.hiddenEdgeCount).toBe(0);
  });

  it("hides role assignments and indirect branch Resource Groups for a non-scope root", () => {
    const root = resource("root", true, "network.vnet");
    const ownerGroup = resource("owner-group", false, "resource-group");
    const peer = resource("peer", false, "network.vnet");
    const peerGroup = resource("peer-group", false, "resource-group");
    const role = resource("role", false, "authorization.role-assignment");
    const connected: OntologyInstanceExploration = {
      ...exploration(),
      root_id: root.id,
      resources: [root, ownerGroup, peer, peerGroup, role],
      links: [
        link(ownerGroup.id, root.id, "contains"),
        link(root.id, peer.id, "peered_with"),
        link(peerGroup.id, peer.id, "contains"),
        link(role.id, root.id, "attached_to"),
      ],
    };

    const layout = buildInstanceGraphLayout(connected);
    const visibleIds = new Set(layout.nodes.map((node) => node.resource.id));

    expect(visibleIds).toContain(ownerGroup.id);
    expect(visibleIds).not.toContain(peerGroup.id);
    expect(visibleIds).not.toContain(role.id);
    expect(layout.edges.some((edge) => edge.link.source === role.id)).toBe(false);
  });

  it("orders Resource Group and VNet containment around Private Endpoint access context", () => {
    const root = resource("root", true, "postgresql-server");
    const group = resource("group", false, "resource-group");
    const privateEndpoint = resource("private-endpoint", false, "network.private-endpoint");
    const networkInterface = resource("network-interface", false, "network.interface");
    const subnet = resource("subnet", false, "network.subnet");
    const virtualNetwork = resource("vnet", false, "network.vnet");
    const connected: OntologyInstanceExploration = {
      ...exploration(),
      root_id: root.id,
      resources: [root, group, privateEndpoint, networkInterface, subnet, virtualNetwork],
      links: [
        link(group.id, root.id, "contains"),
        link(privateEndpoint.id, root.id, "attached_to"),
        link(group.id, privateEndpoint.id, "contains"),
        link(privateEndpoint.id, networkInterface.id, "attached_to"),
        link(privateEndpoint.id, subnet.id, "attached_to"),
        link(networkInterface.id, subnet.id, "attached_to"),
        link(group.id, virtualNetwork.id, "contains"),
        link(virtualNetwork.id, subnet.id, "contains"),
      ],
    };

    const layout = buildInstanceGraphLayout(connected);
    const byId = new Map(layout.nodes.map((node) => [node.resource.id, node]));

    expect(byId.get(group.id)?.level).toBe(-4);
    expect(byId.get(privateEndpoint.id)?.level).toBe(-1);
    expect(byId.get(root.id)?.level).toBe(0);
    expect(byId.get(virtualNetwork.id)?.level).toBe(-3);
    expect(byId.get(networkInterface.id)?.level).toBe(0);
    expect(byId.get(subnet.id)?.level).toBe(-2);
    expect(layout.nodes.filter((node) => node.resource.id === subnet.id)).toHaveLength(1);
    expect(byId.get(group.id)!.x).toBeLessThan(byId.get(privateEndpoint.id)!.x);
    expect(byId.get(privateEndpoint.id)!.x).toBeLessThan(byId.get(root.id)!.x);
    expect(byId.get(virtualNetwork.id)!.x).toBeLessThan(byId.get(subnet.id)!.x);
    expect(layout.edges.filter((edge) => edge.link.link_type !== "attached_to")
      .every((edge) => edge.source.x < edge.target.x)).toBe(true);
    expect(layout.edges.filter((edge) =>
      edge.link.link_type === "attached_to" && edge.source.x > edge.target.x)).toHaveLength(2);
    expect([...instanceGraphPathNodeIds(layout.nodes, virtualNetwork.id)]).toEqual([
      virtualNetwork.id,
      subnet.id,
      privateEndpoint.id,
      root.id,
    ]);
    expect(layout.hiddenNodeCount).toBe(0);
    expect(layout.hiddenEdgeCount).toBe(0);
  });

  it("orders VNet, Private Endpoint, NIC, and Subnet around a selected VNet", () => {
    const virtualNetwork = resource("vnet", true, "network.vnet");
    const subnet = resource("subnet", false, "network.subnet");
    const privateEndpoint = resource("private-endpoint", false, "network.private-endpoint");
    const networkInterface = resource("network-interface", false, "network.interface");
    const connected: OntologyInstanceExploration = {
      ...exploration(),
      root_id: virtualNetwork.id,
      resources: [virtualNetwork, subnet, privateEndpoint, networkInterface],
      links: [
        link(virtualNetwork.id, subnet.id, "contains"),
        link(privateEndpoint.id, subnet.id, "attached_to"),
        link(privateEndpoint.id, networkInterface.id, "attached_to"),
        link(networkInterface.id, subnet.id, "attached_to"),
      ],
    };

    const layout = buildInstanceGraphLayout(connected);
    const byId = new Map(layout.nodes.map((node) => [node.resource.id, node]));

    expect(byId.get(virtualNetwork.id)?.level).toBe(0);
    expect(byId.get(subnet.id)?.level).toBe(1);
    expect(byId.get(privateEndpoint.id)?.level).toBe(2);
    expect(byId.get(networkInterface.id)?.level).toBe(3);
    expect(layout.nodes.map((node) => node.resource.id).sort()).toEqual([
      networkInterface.id,
      privateEndpoint.id,
      subnet.id,
      virtualNetwork.id,
    ].sort());
    expect(layout.edges.filter((edge) => edge.link.link_type !== "attached_to")
      .every((edge) => edge.source.x < edge.target.x)).toBe(true);
    expect(layout.edges.filter((edge) =>
      edge.link.link_type === "attached_to" && edge.source.x > edge.target.x)).toHaveLength(2);
  });

  it("orders an AKS managed Resource Group before its node infrastructure", () => {
    const cluster = resource("cluster", true, "kubernetes-cluster");
    const ownerGroup = resource("owner-group", false, "resource-group");
    const nodeGroup = resource("node-group", false, "resource-group");
    const scaleSet = resource("aks-nodepool-vmss", false, "compute.vm-scale-set");
    const virtualMachine = resource("aks-nodepool-vm-0", false, "compute.vm");
    const networkInterface = resource("aks-nodepool-nic-0", false, "network.interface");
    const loadBalancer = resource("kubernetes", false, "network.load-balancer");
    const identity = resource("aks-agentpool-identity", false, "managed-identity");
    const publicIp = resource("outbound-public-ip", false, "network.public-ip");
    const connected: OntologyInstanceExploration = {
      ...exploration(),
      root_id: cluster.id,
      resources: [
        cluster,
        ownerGroup,
        nodeGroup,
        scaleSet,
        virtualMachine,
        networkInterface,
        loadBalancer,
        identity,
        publicIp,
      ],
      links: [
        link(ownerGroup.id, cluster.id, "contains"),
        linkWithMapping(
          cluster.id,
          nodeGroup.id,
          "attached_to",
          "azure.aks-attached-to-node-resource-group",
        ),
        link(cluster.id, identity.id, "attached_to"),
        linkWithMapping(
          cluster.id,
          publicIp.id,
          "routes_to",
          "azure.aks-routes-to-effective-outbound-ip",
        ),
        link(nodeGroup.id, scaleSet.id, "contains"),
        linkWithMapping(
          scaleSet.id,
          virtualMachine.id,
          "contains",
          "azure.vm-scale-set-contains-vm",
        ),
        linkWithMapping(
          networkInterface.id,
          virtualMachine.id,
          "attached_to",
          "azure.vm-scale-set-nic-attached-to-vm",
        ),
        link(nodeGroup.id, loadBalancer.id, "contains"),
        link(nodeGroup.id, identity.id, "contains"),
        link(nodeGroup.id, publicIp.id, "contains"),
        link(scaleSet.id, identity.id, "attached_to"),
        linkWithMapping(
          loadBalancer.id,
          publicIp.id,
          "attached_to",
          "azure.load-balancer-attached-to-public-ip",
        ),
      ],
    };

    const layout = buildInstanceGraphLayout(connected);
    const byId = new Map(layout.nodes.map((node) => [node.resource.id, node]));

    expect(byId.get(ownerGroup.id)?.level).toBe(-2);
    expect(byId.get(cluster.id)?.level).toBe(0);
    expect(byId.get(nodeGroup.id)?.level).toBe(1);
    expect(byId.get(scaleSet.id)?.level).toBe(2);
    expect(byId.get(virtualMachine.id)?.level).toBe(3);
    expect(byId.get(virtualMachine.id)?.parentId).toBe(scaleSet.id);
    expect(byId.get(virtualMachine.id)?.emphasis).toBe("direct");
    expect(byId.get(networkInterface.id)?.level).toBe(3);
    expect(byId.get(networkInterface.id)?.parentId).toBe(virtualMachine.id);
    expect(byId.get(networkInterface.id)?.emphasis).toBe("direct");
    expect(byId.get(loadBalancer.id)?.level).toBe(2);
    expect(byId.get(identity.id)?.level).toBe(3);
    expect(byId.get(publicIp.id)?.level).toBe(3);
    expect(byId.get(publicIp.id)?.parentId).toBe(loadBalancer.id);
    // One row, plus the break that separates contained Resources from attached ones.
    expect(Math.abs(byId.get(publicIp.id)!.y - byId.get(loadBalancer.id)!.y))
      .toBeLessThanOrEqual(120);
    expect(byId.get(loadBalancer.id)!.y).toBeGreaterThan(byId.get(scaleSet.id)!.y);
    expect(byId.get(publicIp.id)!.y).toBeGreaterThan(byId.get(identity.id)!.y);
    const publicIpFanIn = layout.edges.filter((edge) => edge.link.target === publicIp.id);
    expect(publicIpFanIn.map((edge) => edge.targetPortOffset)).toEqual([-16, 0, 16]);
    expect(publicIpFanIn.map((edge) => edge.longChannel)).toEqual([
      "outer-above",
      "above",
      "below",
    ]);
    const publicIpPaths = publicIpFanIn.map((edge) => buildInstanceEdgeGeometry(
      edge.source,
      edge.target,
      edge.parallelOffset,
      edge.targetPortOffset,
      edge.longChannel,
    ).path);
    expect(new Set(publicIpPaths).size).toBe(3);
    expect(publicIpPaths).toEqual(publicIpFanIn.map((edge) => expect.stringMatching(
      new RegExp(`${edge.target.x} ${edge.target.y + 34 + edge.targetPortOffset}$`),
    )));
    expect(layout.nodes).toHaveLength(9);
    expect(layout.edges).toHaveLength(12);
    expect(layout.edges.filter((edge) =>
      edge.link.evidence.mapping_id !== "azure.vm-scale-set-nic-attached-to-vm")
      .every((edge) => edge.source.x < edge.target.x)).toBe(true);
  });

  it("does not expand a peered VNet branch into the selected VNet context", () => {
    const virtualNetwork = resource("vnet", true, "network.vnet");
    const subnet = resource("subnet", false, "network.subnet");
    const networkInterface = resource("network-interface", false, "network.interface");
    const peeredVnet = resource("peered-vnet", false, "network.vnet");
    const peeredSubnet = resource("peered-subnet", false, "network.subnet");
    const peeredEndpoint = resource("peered-endpoint", false, "network.private-endpoint");
    const peeredInterface = resource("peered-interface", false, "network.interface");
    const connected: OntologyInstanceExploration = {
      ...exploration(),
      root_id: virtualNetwork.id,
      resources: [
        virtualNetwork,
        subnet,
        networkInterface,
        peeredVnet,
        peeredSubnet,
        peeredEndpoint,
        peeredInterface,
      ],
      links: [
        link(virtualNetwork.id, subnet.id, "contains"),
        link(networkInterface.id, subnet.id, "attached_to"),
        link(virtualNetwork.id, peeredVnet.id, "peered_with"),
        link(peeredVnet.id, virtualNetwork.id, "peered_with"),
        link(peeredVnet.id, peeredSubnet.id, "contains"),
        link(peeredEndpoint.id, peeredSubnet.id, "attached_to"),
        link(peeredEndpoint.id, peeredInterface.id, "attached_to"),
      ],
    };

    const layout = buildInstanceGraphLayout(connected);
    const visibleIds = new Set(layout.nodes.map((node) => node.resource.id));

    expect(visibleIds).toEqual(new Set([
      virtualNetwork.id,
      subnet.id,
      networkInterface.id,
      peeredVnet.id,
    ]));
    expect(layout.nodes.filter((node) => node.resource.id === virtualNetwork.id)).toHaveLength(1);
    expect(layout.nodes.filter((node) => node.resource.id === subnet.id)).toHaveLength(1);
    expect(layout.nodes.filter((node) => node.resource.id === peeredVnet.id)).toHaveLength(1);
    expect(layout.edges.filter((edge) => edge.link.link_type === "peered_with")).toHaveLength(2);
    expect(layout.hiddenNodeCount).toBe(3);
    expect(layout.hiddenEdgeCount).toBe(3);
  });

  it("caps indirect access context per direct branch", () => {
    const data = exploration();
    const attachments = Array.from({ length: 5 }, (_value, index) => resource(`attachment-${index}`));
    const connected: OntologyInstanceExploration = {
      ...data,
      resources: [...data.resources, ...attachments],
      links: [
        ...data.links,
        ...attachments.map((attachment) => link("outgoing", attachment.id, "attached_to")),
      ],
    };

    const layout = buildInstanceGraphLayout(connected);
    const visibleAttachments = layout.nodes.filter((node) => node.resource.id.startsWith("attachment-"));

    expect(visibleAttachments).toHaveLength(3);
    expect(visibleAttachments.every((node) => node.lane === "access")).toBe(true);
    expect(layout.hiddenNodeCount).toBe(2);
    expect(layout.hiddenEdgeCount).toBe(2);
  });

  it("keeps the bounded 80-Resource neighborhood collision free", () => {
    const data = exploration();
    const neighbors = Array.from({ length: 79 }, (_value, index) => resource(`neighbor-${index}`));
    const dense = {
      ...data,
      resources: [data.resources[0]!, ...neighbors],
      links: neighbors.map((neighbor, index) => link(
        index % 2 === 0 ? neighbor.id : "root",
        index % 2 === 0 ? "root" : neighbor.id,
        "depends_on",
      )),
    };

    const layout = buildInstanceGraphLayout(dense);
    const positions = layout.nodes.map((node) => `${node.x}:${node.y}`);
    expect(new Set(positions).size).toBe(80);
    expect(layout.nodes.every((node) => node.y + INSTANCE_NODE_HEIGHT <= layout.height)).toBe(true);
    expect(layout.height).toBeLessThanOrEqual(840);
    const target = instanceGraphScrollTarget(layout, "root", 640, 560);
    expect(target.top).toBeGreaterThanOrEqual(0);
    expect(target.top).toBeLessThanOrEqual(layout.height - 560);
    const root = layout.nodes.find((node) => node.resource.id === "root")!;
    expect(root.x + 176 / 2 - target.left).toBeCloseTo(640 / 2);
  });

  it("centers the root of a one-sided dense graph in a wide viewport", () => {
    const data = exploration();
    const outgoing = Array.from({ length: 35 }, (_value, index) => resource(`outgoing-${index}`));
    const dense = {
      ...data,
      resources: [data.resources[0]!, ...outgoing],
      links: outgoing.map((neighbor) => link("root", neighbor.id, "depends_on")),
    };

    const layout = buildInstanceGraphLayout(dense);
    const root = layout.nodes.find((node) => node.resource.id === "root")!;
    const target = instanceGraphScrollTarget(layout, "root", 944, 560);

    expect(root.x + 176 / 2 - target.left).toBeCloseTo(944 / 2);
  });

  it("clamps zoom and computes a bounded fit scale", () => {
    const layout = buildInstanceGraphLayout(exploration());

    expect(clampInstanceGraphScale(0)).toBe(INSTANCE_GRAPH_MIN_SCALE);
    expect(clampInstanceGraphScale(1)).toBe(1);
    expect(clampInstanceGraphScale(3)).toBe(INSTANCE_GRAPH_MAX_SCALE);
    expect(instanceGraphFitScale(layout, 640, 560)).toBeLessThan(1);
    expect(instanceGraphFitScale(layout, 273, 120)).toBeLessThan(0.2);
    expect(instanceGraphFitScale(layout, 4_000, 2_000)).toBe(1);
  });

  it("preserves the viewport center while zooming a panned canvas", () => {
    const layout = buildInstanceGraphLayout(exploration());
    const target = instanceGraphZoomScrollTarget({
      layout,
      scrollLeft: 120,
      scrollTop: 40,
      viewportWidth: 400,
      viewportHeight: 300,
      currentScale: 1,
      nextScale: 1.5,
    });

    expect((target.left + 200) / 1.5).toBeCloseTo((120 + 200) / 1);
    expect((target.top + 150) / 1.5).toBeCloseTo((40 + 150) / 1);
  });

  it("maps ordinary wheel movement to bounded zoom steps", () => {
    expect(instanceGraphWheelScale(1, -1)).toBe(1.2);
    expect(instanceGraphWheelScale(1, 1)).toBe(0.8);
    expect(instanceGraphWheelScale(INSTANCE_GRAPH_MAX_SCALE, -1))
      .toBe(INSTANCE_GRAPH_MAX_SCALE);
    expect(instanceGraphWheelScale(INSTANCE_GRAPH_MIN_SCALE, 1))
      .toBe(INSTANCE_GRAPH_MIN_SCALE);
  });

  it("never zooms out past the scale the graph first rendered with", () => {    expect(clampInstanceGraphScale(0.2, 0.68)).toBe(0.68);
    expect(clampInstanceGraphScale(1.2, 0.68)).toBe(1.2);
    expect(instanceGraphWheelScale(0.68, 1, 0.68)).toBe(0.68);
    expect(instanceGraphWheelScale(0.88, 1, 0.68)).toBeCloseTo(0.68);
    expect(instanceGraphWheelScale(0.68, -1, 0.68)).toBeCloseTo(0.88);
    // A floor outside the supported range must never widen the range.
    expect(clampInstanceGraphScale(0.5, 0)).toBe(0.5);
    expect(clampInstanceGraphScale(1, 5)).toBe(INSTANCE_GRAPH_MAX_SCALE);
  });

  it("offsets parallel and reciprocal links between the same Resources", () => {
    const data = exploration();
    const parallel = {
      ...data,
      links: [
        link("root", "outgoing", "depends_on"),
        link("root", "outgoing", "attached_to"),
        link("outgoing", "root", "peered_with"),
      ],
    };

    expect(buildInstanceGraphLayout(parallel).edges.map((edge) => edge.parallelOffset))
      .toEqual([-16, 0, 16]);
  });

  it("shares one peer occurrence across reciprocal peering records", () => {
    const data = exploration();
    const reciprocal = {
      ...data,
      resources: [data.resources[0]!, data.resources[2]!],
      links: [
        link("outgoing", "root", "peered_with"),
        link("root", "outgoing", "peered_with"),
      ],
    };

    const layout = buildInstanceGraphLayout(reciprocal);
    const occurrences = layout.nodes.filter((node) => node.resource.id === "outgoing");

    expect(occurrences.map((node) => node.side)).toEqual(["incoming"]);
    expect(layout.edges.map((edge) => edge.graphDirection)).toEqual(["incoming", "outgoing"]);
    expect(layout.edges.filter((edge) => edge.source.x < edge.target.x)).toHaveLength(1);
    expect(layout.edges.filter((edge) => edge.source.x > edge.target.x)).toHaveLength(1);
    expect(layout.edges.map((edge) => [edge.link.source, edge.link.target])).toEqual([
      ["outgoing", "root"],
      ["root", "outgoing"],
    ]);
  });

  it("unrolls a directed cycle into deterministic root-relative occurrences", () => {
    const data = exploration();
    const middle = resource("middle");
    const cyclic = {
      ...data,
      resources: [data.resources[0]!, data.resources[2]!, middle],
      links: [
        link("root", "outgoing", "depends_on"),
        link("outgoing", "middle", "depends_on"),
        link("middle", "root", "depends_on"),
      ],
    };

    const layout = buildInstanceGraphLayout(cyclic);
    const middleOccurrences = layout.nodes.filter((node) => node.resource.id === "middle");

    expect(middleOccurrences.map((node) => node.side)).toEqual(["incoming", "outgoing"]);
    expect(layout.edges.every((edge) => edge.source.x < edge.target.x)).toBe(true);
    expect([...instanceGraphPathNodeIds(layout.nodes, "middle")]).toEqual([
      "middle",
      "outgoing",
      "root",
    ]);
  });

  it("routes links between same-column neighbors outside both nodes", () => {
    const geometry = buildInstanceEdgeGeometry(
      { x: 20, y: 40 },
      { x: 20, y: 140 },
      0,
    );

    expect(geometry.path).toContain(`M${20 + 176} ${40 + 34}`);
    expect(geometry.labelX).toBeGreaterThan(20 + 176);
    expect(geometry.labelY).toBeGreaterThan(40 + 68);
    expect(geometry.labelY).toBeLessThan(140);
  });

  it("routes outer-column links above an occupied middle column", () => {
    const geometry = buildInstanceEdgeGeometry(
      { x: 20, y: 146 },
      { x: 504, y: 146 },
      0,
    );

    expect(geometry.labelY).toBeLessThan(146);
    expect(geometry.path).toContain("C276 98,424 98");
  });

  it("leaves the owner underside for containment and the side for attachment", () => {
    const attachment = buildInstanceEdgeGeometry({ x: 20, y: 40 }, { x: 308, y: 200 }, 0);
    const containment = buildInstanceEdgeGeometry(
      { x: 20, y: 40 },
      { x: 308, y: 200 },
      0,
      0,
      "above",
      "descend",
    );

    expect(attachment.path.startsWith(`M${20 + 176} ${40 + 34}`)).toBe(true);
    expect(containment.path.startsWith(`M${20 + 88} ${40 + 68}`)).toBe(true);
    expect(containment.path).not.toBe(attachment.path);

    // An owner drawn below its child still leaves from the underside.
    const upward = buildInstanceEdgeGeometry(
      { x: 20, y: 400 },
      { x: 308, y: 40 },
      0,
      0,
      "above",
      "descend",
    );
    expect(upward.path.startsWith(`M${20 + 88} ${400 + 68}`)).toBe(true);

    // Distant columns keep the long channel so containment never crosses a node.
    const distant = buildInstanceEdgeGeometry(
      { x: 20, y: 40 },
      { x: 900, y: 40 },
      0,
      0,
      "above",
      "descend",
    );
    expect(distant.path.startsWith(`M${20 + 176} ${40 + 34}`)).toBe(true);
  });
});

describe("buildInstanceTimeline", () => {
  it("keeps non-state activity as an event without manufacturing a state segment", () => {
    const timeline = buildInstanceTimeline([
      activity(2, "2026-08-22T07:30:00Z", { reason: "inventory_confirmed" }),
      activity(1, "2026-08-22T07:00:00Z", { state: "Running" }),
    ], "2026-08-22T08:00:00Z");

    expect(timeline.events).toHaveLength(2);
    expect(timeline.events[1]?.state).toBeNull();
    expect(timeline.segments.map((segment) => segment.state)).toEqual([null, "Running"]);
  });

  it("preserves hover evidence details and explicit unknown state", () => {
    const timeline = buildInstanceTimeline([
      activity(1, "2026-08-22T07:20:00Z", { outcome: "verified" }),
    ], "2026-08-22T08:00:00Z");

    expect(timeline.events[0]).toMatchObject({
      summary: "verified",
      state: null,
      clusterSize: 1,
      activity: { actor: "fdai.system", evidence_ref: "audit:1" },
    });
    expect(timeline.segments).toEqual([
      { state: null, start: 0, width: 100, observedAt: null, evidenceRef: null },
    ]);
  });

  it("clusters identical timestamps and excludes activity beyond the source cutoff", () => {
    const timeline = buildInstanceTimeline([
      activity(4, "2026-08-22T08:01:00Z", { state: "Future" }),
      activity(3, "2026-08-22T07:30:00Z", { reason: "newest_same_time" }),
      activity(2, "2026-08-22T07:30:00Z", { state: "OlderSameTime" }),
      activity(1, "2026-08-22T07:00:00Z", { state: "Running" }),
    ], "2026-08-22T08:00:00Z");

    expect(timeline.events).toHaveLength(2);
    expect(timeline.events[1]).toMatchObject({
      clusterSize: 2,
      summary: "newest_same_time",
      activity: { sequence: 3 },
      state: "OlderSameTime",
      stateActivity: { sequence: 2, evidence_ref: "audit:2" },
    });
    expect(timeline.segments.at(-1)).toMatchObject({
      state: "OlderSameTime",
      evidenceRef: "audit:2",
    });
    expect(timeline.events.some((event) => event.state === "Future")).toBe(false);
  });

  it("collapses nearby event markers while preserving their count", () => {
    const timeline = buildInstanceTimeline([
      activity(3, "2026-08-22T07:02:00Z", { reason: "third" }),
      activity(2, "2026-08-22T07:01:00Z", { reason: "second" }),
      activity(1, "2026-08-22T07:00:00Z", { reason: "first" }),
    ], "2026-08-22T08:00:00Z");

    expect(timeline.events).toHaveLength(1);
    expect(timeline.events[0]).toMatchObject({
      clusterSize: 3,
      summary: "third",
      activity: { sequence: 3 },
    });
    expect(Date.parse(timeline.endAt) - Date.parse(timeline.startAt))
      .toBeGreaterThanOrEqual(6 * 60 * 60 * 1000);
  });
});

function exploration(): OntologyInstanceExploration {
  const resources = [resource("root", true), resource("incoming"), resource("outgoing")];
  return {
    schema_version: "1.3.0",
    ontology_release_digest: `sha256:${"a".repeat(64)}`,
    source_generation: "generation-1",
    source_cutoff: "2026-08-22T08:00:00Z",
    root_id: "root",
    depth: 8,
    link_types: ["contains", "depends_on"],
    resources,
    links: [
      link("incoming", "root", "depends_on"),
      link("root", "outgoing", "depends_on"),
    ],
    timeline: { items: [], complete: true, truncation_reason: null },
    sources: [],
    relationship_drop_reasons: [],
    relationship_drop_classifications: [],
    complete: true,
    truncation_reasons: [],
    execution_authority: false,
    mutation_authority: false,
  };
}

function link(
  source: string,
  target: string,
  linkType: OntologyInstanceLink["link_type"],
): OntologyInstanceLink {
  return {
    source,
    target,
    link_type: linkType,
    evidence: {
      status: "available",
      evidence_kind: "configuration",
      verification_status: "configuration_observed",
      source: "azure-resource-graph",
      source_property_path: "properties.referenceId",
      mapping_id: `test.${linkType}`,
      evidence_method: "deterministic-cross-check",
      cutoff: "2026-08-22T08:00:00Z",
      freshness_ceiling_seconds: 21600,
      complete: true,
      reason: null,
    },
  };
}

function linkWithMapping(
  source: string,
  target: string,
  linkType: OntologyInstanceLink["link_type"],
  mappingId: string,
): OntologyInstanceLink {
  const relationship = link(source, target, linkType);
  return {
    ...relationship,
    evidence: { ...relationship.evidence, mapping_id: mappingId },
  };
}

function resource(
  id: string,
  selected = false,
  resourceType = "compute.container-app",
): OntologyInstanceResource {
  return {
    id,
    object_type: "Resource",
    resource_type: resourceType,
    name: id,
    location: null,
    resource_group: null,
    status: "Running",
    last_seen: null,
    selected,
  };
}

function activity(
  sequence: number,
  recordedAt: string,
  facts: Readonly<Record<string, string>>,
): OntologyInstanceActivity {
  return {
    sequence,
    action_kind: "audit.record",
    actor: "fdai.system",
    recorded_at: recordedAt,
    correlation_id: null,
    facts,
    evidence_ref: `audit:${sequence}`,
  };
}
