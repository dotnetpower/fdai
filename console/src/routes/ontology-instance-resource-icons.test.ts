import { describe, expect, it } from "vitest";
import appServicePlans from "../../../tools/architecture-diagrams/assets/azure/app-service-plans.svg?url";
import apiManagementServices from "../../../tools/architecture-diagrams/assets/azure/api-management-services.svg?url";
import disks from "../../../tools/architecture-diagrams/assets/azure/disks.svg?url";
import diskSnapshots from "../../../tools/architecture-diagrams/assets/azure/disk-snapshots.svg?url";
import containerRegistry from "../../../tools/architecture-diagrams/assets/azure/container-registry.svg?url";
import dnsPrivateResolver from "../../../tools/architecture-diagrams/assets/azure/dns-private-resolver.svg?url";
import dnsZones from "../../../tools/architecture-diagrams/assets/azure/dns-zones.svg?url";
import logicApps from "../../../tools/architecture-diagrams/assets/azure/logic-apps.svg?url";
import monitor from "../../../tools/architecture-diagrams/assets/azure/monitor.svg?url";
import nat from "../../../tools/architecture-diagrams/assets/azure/nat.svg?url";
import postgresqlIcon from "../../../tools/architecture-diagrams/assets/azure/postgresql.svg?url";
import privateEndpointIcon from "../../../tools/architecture-diagrams/assets/azure/private-endpoint.svg?url";
import resourceGraph from "../../../tools/architecture-diagrams/assets/azure/resource-graph.svg?url";
import resourceGroups from "../../../tools/architecture-diagrams/assets/azure/resource-groups.svg?url";
import staticWebApp from "../../../tools/architecture-diagrams/assets/azure/static-web-app.svg?url";
import sqlDatabase from "../../../tools/architecture-diagrams/assets/azure/sql-database.svg?url";
import sqlServer from "../../../tools/architecture-diagrams/assets/azure/sql-server.svg?url";
import subscriptions from "../../../tools/architecture-diagrams/assets/azure/subscriptions.svg?url";
import vmScaleSets from "../../../tools/architecture-diagrams/assets/azure/vm-scale-sets.svg?url";
import kubernetesEndpoints from "../../../tools/architecture-diagrams/assets/kubernetes/ep.svg?url";
import kubernetesIngress from "../../../tools/architecture-diagrams/assets/kubernetes/ing.svg?url";
import kubernetesNode from "../../../tools/architecture-diagrams/assets/kubernetes/node.svg?url";
import kubernetesPod from "../../../tools/architecture-diagrams/assets/kubernetes/pod.svg?url";
import kubernetesService from "../../../tools/architecture-diagrams/assets/kubernetes/svc.svg?url";
import { ontologyInstanceIconForResourceType } from "./ontology-instance-resource-icons";

describe("ontologyInstanceIconForResourceType", () => {
  it("maps neutral inventory aliases to distinct official Azure icons", () => {
    const resourceGroup = ontologyInstanceIconForResourceType("resource-group");
    const postgresql = ontologyInstanceIconForResourceType("postgresql-server");
    const registry = ontologyInstanceIconForResourceType("container-registry");
    const privateEndpoint = ontologyInstanceIconForResourceType("network.private-endpoint");

    expect(resourceGroup).toBe(resourceGroups);
    expect(postgresql).toBe(postgresqlIcon);
    expect(registry).toBe(containerRegistry);
    expect(privateEndpoint).toBe(privateEndpointIcon);
    expect(new Set([resourceGroup, postgresql, registry, privateEndpoint]).size).toBe(4);
    expect(ontologyInstanceIconForResourceType("compute.container-app-job"))
      .toBe(ontologyInstanceIconForResourceType("compute.container-app"));
    expect(ontologyInstanceIconForResourceType("static-web-app")).toBe(staticWebApp);
    expect(ontologyInstanceIconForResourceType("app-service-plan")).toBe(appServicePlans);
    expect(ontologyInstanceIconForResourceType("compute.vm-scale-set")).toBe(vmScaleSets);
    expect(ontologyInstanceIconForResourceType("network.private-dns-zone")).toBe(dnsZones);
    expect(ontologyInstanceIconForResourceType("network.dns-zone")).toBe(dnsZones);
    expect(ontologyInstanceIconForResourceType("network.private-dns-zone-group")).toBe(dnsZones);
    expect(ontologyInstanceIconForResourceType("network.private-dns-zone-link")).toBe(dnsZones);
    expect(ontologyInstanceIconForResourceType("disk")).toBe(disks);
    expect(ontologyInstanceIconForResourceType("network.dns-resolver")).toBe(dnsPrivateResolver);
    expect(ontologyInstanceIconForResourceType("network.dns-resolver-inbound-endpoint"))
      .toBe(dnsPrivateResolver);
    expect(ontologyInstanceIconForResourceType("api-gateway")).toBe(apiManagementServices);
    expect(ontologyInstanceIconForResourceType("disk-snapshot")).toBe(diskSnapshots);
    expect(ontologyInstanceIconForResourceType("metrics-workspace")).toBe(monitor);
    expect(ontologyInstanceIconForResourceType("network.nat-gateway")).toBe(nat);
    expect(ontologyInstanceIconForResourceType("sql-database")).toBe(sqlDatabase);
    expect(ontologyInstanceIconForResourceType("sql-server")).toBe(sqlServer);
    expect(ontologyInstanceIconForResourceType("subscription")).toBe(subscriptions);
    expect(ontologyInstanceIconForResourceType("workflow.logic-app")).toBe(logicApps);
  });

  it("keeps unknown and unclassified types on the explicit generic Azure fallback", () => {
    expect(ontologyInstanceIconForResourceType("provider.unknown/type")).toBe(resourceGraph);
    expect(ontologyInstanceIconForResourceType("authorization.role-assignment")).toBe(resourceGraph);
    expect(ontologyInstanceIconForResourceType("data-collection-endpoint")).toBe(resourceGraph);
    expect(ontologyInstanceIconForResourceType("unclassified-resource")).toBe(resourceGraph);
  });

  it("separates collected Kubernetes runtime types from the generic fallback", () => {
    const collected = [
      "kubernetes.namespace",
      "kubernetes.node",
      "kubernetes.pod",
      "kubernetes.service",
      "kubernetes.endpoints",
      "kubernetes.endpoint-slice",
      "kubernetes.ingress",
      "kubernetes.ingress-class",
      "kubernetes.job",
      "kubernetes.cron-job",
      "kubernetes.deployment",
      "kubernetes.replica-set",
      "kubernetes.daemon-set",
      "kubernetes.stateful-set",
    ].map(ontologyInstanceIconForResourceType);

    expect(collected).not.toContain(resourceGraph);
    expect(ontologyInstanceIconForResourceType("kubernetes.pod")).toBe(kubernetesPod);
    expect(ontologyInstanceIconForResourceType("kubernetes.service")).toBe(kubernetesService);
    expect(ontologyInstanceIconForResourceType("kubernetes.node")).toBe(kubernetesNode);
    expect(ontologyInstanceIconForResourceType("kubernetes.endpoint-slice"))
      .toBe(kubernetesEndpoints);
    expect(ontologyInstanceIconForResourceType("kubernetes.ingress-class")).toBe(kubernetesIngress);
    // 14 declared types minus the two documented glyph reuses.
    expect(new Set(collected).size).toBe(12);
    expect(ontologyInstanceIconForResourceType("kubernetes-node-pool")).toBe(vmScaleSets);
  });
});
