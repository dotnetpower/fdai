/** Generic Sample stories aligned with the static Live specimen, never runtime evidence. */
export const LIVE_SAMPLE_STORIES = [
  { key: "publicBlob", resourceType: "object-storage", actionType: "remediate.disable-public-access", target: "sample-web-storage", scope: "rg-webapp", vertical: "change", rule: "sample.storage.public-blob.deny", impact: "one sample storage account" },
  { key: "restore", resourceType: "postgresql-server", actionType: "remediate.enable-backup-protection", target: "sample-billing-database", scope: "rg-billing", vertical: "resilience", rule: "sample.database.pitr.required", impact: "one sample database" },
  { key: "autoscale", resourceType: "compute.container-app", actionType: "ops.scale-out", target: "sample-web-service", scope: "rg-web-eu", vertical: "resilience", rule: "sample.compute.autoscale.floor", impact: "one sample service" },
  { key: "certificate", resourceType: "certificate", actionType: "ops.rotate-cert", target: "sample-identity-service", scope: "rg-core", vertical: "change", rule: "sample.identity.cert.expiry", impact: "one sample certificate" },
  { key: "rightsize", resourceType: "compute.vm-scale-set", actionType: "remediate.right-size", target: "sample-worker-pool", scope: "rg-batch", vertical: "cost", rule: "sample.cost.rightsize.candidate", impact: "one sample worker pool" },
  { key: "firewall", resourceType: "network.firewall", actionType: "ops.delete-network-rule", target: "sample-shared-network", scope: "rg-net", vertical: "change", rule: "sample.network.firewall.orphan-rule", impact: "one sample firewall rule" },
  { key: "clusterAccess", resourceType: "kubernetes-cluster", actionType: "remediate.right-size-role", target: "sample-kubernetes", scope: "aks-prod", vertical: "change", rule: "sample.k8s.rbac.cluster-admin.narrow", impact: "one sample binding" },
  { key: "dns", resourceType: "network.dns-resolver", actionType: "remediate.restrict-network-access", target: "sample-network-resolver", scope: "rg-net", vertical: "change", rule: "sample.network.dns.public-resolver.deny", impact: "one sample resolver" },
  { key: "vault", resourceType: "secret-store", actionType: "remediate.right-size-role", target: "sample-secrets-vault", scope: "rg-ident", vertical: "change", rule: "sample.keyvault.access.grant-narrow", impact: "one sample grant" },
  { key: "retention", resourceType: "log-workspace", actionType: "remediate.set-retention-policy", target: "sample-operations-workspace", scope: "rg-obs", vertical: "change", rule: "sample.observability.log.retention", impact: "one sample table" },
  { key: "disk", resourceType: "disk", actionType: "remediate.remove-orphan-resource", target: "sample-legacy-workload", scope: "rg-legacy", vertical: "cost", rule: "sample.cost.orphan-disk.cleanup", impact: "one sample disk" },
  { key: "replica", resourceType: "postgresql-server", actionType: "ops.failover-primary", target: "sample-database-replica", scope: "rg-db-eu", vertical: "resilience", rule: "sample.reliability.replica-lag.alert", impact: "one sample replica" },
] as const;

/** Resolve an explicit synthetic story; Live callers must not apply these presentation labels. */
export function liveSampleStory(rule: string | undefined) {
  return LIVE_SAMPLE_STORIES.find(story => story.rule === rule);
}
