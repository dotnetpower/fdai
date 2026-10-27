# Hub Operational Ownership Prerequisites

This Terraform root owns only the Azure and Kubernetes prerequisites that must remain outside the
Hub lifecycle agent for an existing AKS installation. It references the retained resource group,
ACR, Key Vault, Event Hubs, Log Analytics workspace, VNet, AKS cluster, and namespace.

The root creates:

- dedicated ingestion, worker, migration, notification, Operator API, and command identities with
  federated identity credentials;
- document storage and private endpoints, Document Intelligence, ACS Email, role bindings, and
  role-scoped DSN references;
- secret-scoped `Key Vault Secrets User` assignments for the Operator API identity's exact three
  generated secret bindings;
- the exact missing ServiceAccounts and environment ConfigMaps from full-topology generation; and
- SecretProviderClasses whose CSI `secretObjects` bind generated environment variables to Key
  Vault secret names, plus the three bootstrap Kubernetes Secrets required before the managed
  pods start.

Pass deployment-specific resource names, tenant values, kubeconfig, generated ConfigMap data, and
secret-name bindings through private variables. The `topology_generation` output supplies the
identity and prerequisite bindings used to regenerate the full topology. The
`retained_ownership` output records the Terraform-owned prerequisite inventory separately from
the Lifecycle Agent-owned workload kinds.

Secret values are read directly from Key Vault during the reviewed plan and apply. They are never
variables or outputs. Use protected remote state because Terraform retains sensitive resource
data. After creation, Terraform ignores Secret data changes so the Key Vault CSI provider can
synchronize rotations while Terraform continues to own Secret metadata and existence.

The root creates no namespace, Deployment, Service, HorizontalPodAutoscaler, CronJob, Container
App, Container App Job, or Hub Plan. Use a separate remote state key and review an exact
create-only plan before apply.
