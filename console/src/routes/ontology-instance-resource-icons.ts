import appServicePlans from "../../../tools/architecture-diagrams/assets/azure/app-service-plans.svg?url";
import apiManagementServices from "../../../tools/architecture-diagrams/assets/azure/api-management-services.svg?url";
import alerts from "../../../tools/architecture-diagrams/assets/azure/alerts.svg?url";
import azureOpenAi from "../../../tools/architecture-diagrams/assets/azure/azure-openai.svg?url";
import cacheRedis from "../../../tools/architecture-diagrams/assets/azure/cache-redis.svg?url";
import containerApps from "../../../tools/architecture-diagrams/assets/azure/container-apps.svg?url";
import containerRegistry from "../../../tools/architecture-diagrams/assets/azure/container-registry.svg?url";
import communicationServices from "../../../tools/architecture-diagrams/assets/azure/communication-services.svg?url";
import cosmosDb from "../../../tools/architecture-diagrams/assets/azure/cosmos-db.svg?url";
import dataCollectionRules from "../../../tools/architecture-diagrams/assets/azure/data-collection-rules.svg?url";
import disks from "../../../tools/architecture-diagrams/assets/azure/disks.svg?url";
import diskSnapshots from "../../../tools/architecture-diagrams/assets/azure/disk-snapshots.svg?url";
import dnsPrivateResolver from "../../../tools/architecture-diagrams/assets/azure/dns-private-resolver.svg?url";
import dnsZones from "../../../tools/architecture-diagrams/assets/azure/dns-zones.svg?url";
import eventHubs from "../../../tools/architecture-diagrams/assets/azure/event-hubs.svg?url";
import eventGridTopics from "../../../tools/architecture-diagrams/assets/azure/event-grid-topics.svg?url";
import functionApps from "../../../tools/architecture-diagrams/assets/azure/function-apps.svg?url";
import keyVault from "../../../tools/architecture-diagrams/assets/azure/key-vault.svg?url";
import kubernetesServices from "../../../tools/architecture-diagrams/assets/azure/kubernetes-services.svg?url";
import kubernetesCronJob from "../../../tools/architecture-diagrams/assets/kubernetes/cronjob.svg?url";
import kubernetesDaemonSet from "../../../tools/architecture-diagrams/assets/kubernetes/ds.svg?url";
import kubernetesDeployment from "../../../tools/architecture-diagrams/assets/kubernetes/deploy.svg?url";
import kubernetesEndpoints from "../../../tools/architecture-diagrams/assets/kubernetes/ep.svg?url";
import kubernetesIngress from "../../../tools/architecture-diagrams/assets/kubernetes/ing.svg?url";
import kubernetesJob from "../../../tools/architecture-diagrams/assets/kubernetes/job.svg?url";
import kubernetesNamespace from "../../../tools/architecture-diagrams/assets/kubernetes/ns.svg?url";
import kubernetesNode from "../../../tools/architecture-diagrams/assets/kubernetes/node.svg?url";
import kubernetesPod from "../../../tools/architecture-diagrams/assets/kubernetes/pod.svg?url";
import kubernetesReplicaSet from "../../../tools/architecture-diagrams/assets/kubernetes/rs.svg?url";
import kubernetesService from "../../../tools/architecture-diagrams/assets/kubernetes/svc.svg?url";
import kubernetesStatefulSet from "../../../tools/architecture-diagrams/assets/kubernetes/sts.svg?url";
import logicApps from "../../../tools/architecture-diagrams/assets/azure/logic-apps.svg?url";
import managedIdentity from "../../../tools/architecture-diagrams/assets/azure/managed-identity.svg?url";
import monitor from "../../../tools/architecture-diagrams/assets/azure/monitor.svg?url";
import mysqlServer from "../../../tools/architecture-diagrams/assets/azure/mysql-server.svg?url";
import nat from "../../../tools/architecture-diagrams/assets/azure/nat.svg?url";
import postgresql from "../../../tools/architecture-diagrams/assets/azure/postgresql.svg?url";
import privateEndpoint from "../../../tools/architecture-diagrams/assets/azure/private-endpoint.svg?url";
import resourceGraph from "../../../tools/architecture-diagrams/assets/azure/resource-graph.svg?url";
import resourceGroups from "../../../tools/architecture-diagrams/assets/azure/resource-groups.svg?url";
import serviceBus from "../../../tools/architecture-diagrams/assets/azure/service-bus.svg?url";
import sqlDatabase from "../../../tools/architecture-diagrams/assets/azure/sql-database.svg?url";
import sqlServer from "../../../tools/architecture-diagrams/assets/azure/sql-server.svg?url";
import staticWebApp from "../../../tools/architecture-diagrams/assets/azure/static-web-app.svg?url";
import storageAccount from "../../../tools/architecture-diagrams/assets/azure/storage-account.svg?url";
import subscriptions from "../../../tools/architecture-diagrams/assets/azure/subscriptions.svg?url";
import virtualNetwork from "../../../tools/architecture-diagrams/assets/azure/virtual-network.svg?url";
import vmScaleSets from "../../../tools/architecture-diagrams/assets/azure/vm-scale-sets.svg?url";
import { architectureNetworkIconForResourceType } from "../components/architecture-network-icons";

const ICON_BY_RESOURCE_TYPE: Readonly<Record<string, string>> = Object.freeze({
  "compute.container-app": containerApps,
  "compute.container-app-environment": containerApps,
  "compute.container-app-job": containerApps,
  "compute.vm-scale-set": vmScaleSets,
  "compute.vm-shutdown-schedule": architectureNetworkIconForResourceType("compute.vm") ?? resourceGraph,
  "action-group": monitor,
  "alert-rule": alerts,
  "application-insights": monitor,
  "api-gateway": apiManagementServices,
  "app-service-plan": appServicePlans,
  "communication-service": communicationServices,
  "compute.function": functionApps,
  "container-app": containerApps,
  "container-registry": containerRegistry,
  "data.object-storage": storageAccount,
  "data.postgresql": postgresql,
  "data-collection-rule": dataCollectionRules,
  "disk": disks,
  "disk-snapshot": diskSnapshots,
  "delivery.container-registry": containerRegistry,
  "email-domain": communicationServices,
  "email-service": communicationServices,
  "event-hub": eventHubs,
  "event-hubs": eventHubs,
  "event-grid-topic": eventGridTopics,
  "key-vault": keyVault,
  "log-workspace": monitor,
  "llm-endpoint": azureOpenAi,
  "managed-identity": managedIdentity,
  "metrics-workspace": monitor,
  "messaging.event-stream": eventHubs,
  "mysql-server": mysqlServer,
  "microsoft.app/containerapps": containerApps,
  "microsoft.app/managedenvironments": containerApps,
  "microsoft.containerregistry/registries": containerRegistry,
  "microsoft.dbforpostgresql/flexibleservers": postgresql,
  "microsoft.eventhub/namespaces": eventHubs,
  "microsoft.insights/components": monitor,
  "microsoft.keyvault/vaults": keyVault,
  "microsoft.operationalinsights/workspaces": monitor,
  "microsoft.storage/storageaccounts": storageAccount,
  "network.private-endpoint": privateEndpoint,
  "network.nat-gateway": nat,
  "network.dns-zone": dnsZones,
  "network.private-dns-zone": dnsZones,
  "network.private-dns-zone-group": dnsZones,
  "network.private-dns-zone-link": dnsZones,
  "network.dns-resolver": dnsPrivateResolver,
  "network.dns-resolver-inbound-endpoint": dnsPrivateResolver,
  "network.virtual-network": virtualNetwork,
  "object-storage": storageAccount,
  "nosql-database": cosmosDb,
  "observability.workspace": monitor,
  "postgresql": postgresql,
  "postgresql-server": postgresql,
  "private-endpoint": privateEndpoint,
  "resource-group": resourceGroups,
  "redis-enterprise": cacheRedis,
  "security.secret-store": keyVault,
  "secret-store": keyVault,
  "service-bus-namespace": serviceBus,
  "kubernetes-cluster": kubernetesServices,
  "kubernetes-node-pool": vmScaleSets,
  "kubernetes.cron-job": kubernetesCronJob,
  "kubernetes.daemon-set": kubernetesDaemonSet,
  "kubernetes.deployment": kubernetesDeployment,
  "kubernetes.endpoints": kubernetesEndpoints,
  // Upstream publishes no EndpointSlice or IngressClass glyph; see the catalog NOTICE.
  "kubernetes.endpoint-slice": kubernetesEndpoints,
  "kubernetes.ingress": kubernetesIngress,
  "kubernetes.ingress-class": kubernetesIngress,
  "kubernetes.job": kubernetesJob,
  "kubernetes.namespace": kubernetesNamespace,
  "kubernetes.node": kubernetesNode,
  "kubernetes.pod": kubernetesPod,
  "kubernetes.replica-set": kubernetesReplicaSet,
  "kubernetes.service": kubernetesService,
  "kubernetes.stateful-set": kubernetesStatefulSet,
  "storage-account": storageAccount,
  "static-web-app": staticWebApp,
  "sql-database": sqlDatabase,
  "sql-server": sqlServer,
  "subscription": subscriptions,
  "virtual-network": virtualNetwork,
  "workflow.logic-app": logicApps,
});

/** Returns a reviewed Azure icon for a Resource type, with a neutral Azure resource fallback. */
export function ontologyInstanceIconForResourceType(type: string): string {
  const normalized = type.trim().toLowerCase();
  return ICON_BY_RESOURCE_TYPE[normalized]
    ?? architectureNetworkIconForResourceType(normalized)
    ?? resourceGraph;
}
