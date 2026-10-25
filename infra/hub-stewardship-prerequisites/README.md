# Hub Stewardship Prerequisites

This Terraform root owns only the Azure prerequisites that the Hub lifecycle agent cannot create
for an existing AKS installation. It references the retained resource group, ACR, Key Vault,
Event Hubs, Log Analytics workspace, VNet and AKS cluster. It creates dedicated ingestion,
worker, migration and notification identities; document storage and private endpoints; Document
Intelligence; ACS Email; federated credentials; role bindings; and role-scoped DSN references.

It creates no Container App, Container App Job, Kubernetes workload, namespace or Hub Plan.
Use a separate remote state key and review an exact create-only plan before apply.
