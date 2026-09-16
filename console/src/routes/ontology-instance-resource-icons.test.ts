import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { ontologyInstanceIconForResourceType } from "./ontology-instance-resource-icons";

const iconSource = readFileSync(
  fileURLToPath(new URL("./ontology-instance-resource-icons.ts", import.meta.url)),
  "utf8",
);
const azureIcon = (name: string): string =>
  new URL(`../../../tools/architecture-diagrams/assets/azure/${name}.svg`, import.meta.url).href;
const kubernetesIcon = (name: string): string =>
  new URL(`../../../tools/architecture-diagrams/assets/kubernetes/${name}.svg`, import.meta.url).href;

const appServicePlans = azureIcon("app-service-plans");
const apiManagementServices = azureIcon("api-management-services");
const disks = azureIcon("disks");
const diskSnapshots = azureIcon("disk-snapshots");
const containerRegistry = azureIcon("container-registry");
const dnsPrivateResolver = azureIcon("dns-private-resolver");
const dnsZones = azureIcon("dns-zones");
const logicApps = azureIcon("logic-apps");
const monitor = azureIcon("monitor");
const nat = azureIcon("nat");
const postgresqlIcon = azureIcon("postgresql");
const privateEndpointIcon = azureIcon("private-endpoint");
const resourceGraph = azureIcon("resource-graph");
const resourceGroups = azureIcon("resource-groups");
const staticWebApp = azureIcon("static-web-app");
const sqlDatabase = azureIcon("sql-database");
const sqlServer = azureIcon("sql-server");
const subscriptions = azureIcon("subscriptions");
const vmScaleSets = azureIcon("vm-scale-sets");
const kubernetesEndpoints = kubernetesIcon("ep");
const kubernetesIngress = kubernetesIcon("ing");
const kubernetesNode = kubernetesIcon("node");
const kubernetesPod = kubernetesIcon("pod");
const kubernetesService = kubernetesIcon("svc");

describe("ontologyInstanceIconForResourceType", () => {
  it("does not request every icon through eager Vite URL modules", () => {
    expect(iconSource).not.toContain(".svg?url");
    expect(iconSource).not.toContain('from "../components/architecture-network-icons"');
    expect(iconSource).toContain('from "../components/architecture-network-icon-urls"');
  });

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
