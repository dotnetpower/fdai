---
title: Runtime Deployment Profiles
---
# Runtime Deployment Profiles

This document defines Azure Kubernetes Service (AKS) as the default runtime for new FDAI
installations without changing application behavior or deployment authority. Azure Container Apps
remains a supported compatibility profile for existing installations. The selection is part of the
signed `fdaictl` provisioning profile and every exact Terraform plan.

> **Scope:** This contract covers new installations. Moving an existing installation between
> runtime platforms requires a separate migration design and is not an implicit profile update.
>
> **Azure focus:** Both supported runtime platforms use the same Azure provider adapters, signed
> OCI images, Event Hubs Kafka endpoints, Key Vault, workload identities, and PostgreSQL schema.

## Design at a glance

Shared Operator outbox composition preserves the same test-context worker on both platforms.
Its facade grouping creates no AKS observation, Cost Governance activation, or deployment authority.

The host's read-only `verify-source-runtime` command checks pinned source/runtime content, not
runtime or database placement, node sizing, cost, host identity or exact-plan authority. Its evidence
cannot replace a profile-bound plan. Support installation receives an already-admitted artifact root;
missing source support never selects a kit implicitly. See the [source boundary](installable-deployment-cli.md#explicit-source-recovery).

The operator chooses one runtime platform and one database placement. `fdaictl` validates the
combination, estimates its capacity and cost, compiles a platform-specific provisioning graph,
and asks for approval of each exact plan. A retry can verify an uncertain effect, but it cannot
change either choice or repeat an ambiguous apply.

| Axis | Supported values | Default | Meaning |
|------|------------------|---------|---------|
| Runtime platform | `aks`, `container-apps` | `aks` | Hosts FDAI services and scheduled jobs. Container Apps is compatibility-only for new planning. |
| Database placement | `postgres-flex`, `postgres-aks` | `postgres-flex` | Uses Azure Database for PostgreSQL Flexible Server or a PostgreSQL cluster inside AKS. |

`postgres-aks` is accepted only with `runtime_platform=aks`. Production keeps
`postgres-flex` until the in-cluster profile has independent zone-loss, backup, point-in-time
recovery, and upgrade evidence.

## Operator contract

The public command accepts explicit choices for both online and artifact-offline installation. An
omitted runtime selects AKS for a new installation:

```bash
fdaictl provision azure --online \
  --database postgres-flex

fdaictl provision azure --online \
  --runtime container-apps \
  --database postgres-flex \
  --existing-installation

fdaictl provision azure \
  --offline-kit /media/fdai/fdai-deployment-kit.tar.gz \
  --runtime aks \
  --database postgres-aks \
  --system-nodes 3 \
  --user-nodes 4
```

The command remains interactive at each mutating plan boundary. A runtime or database choice never
grants action authority, changes the selected environment, or enables enforcement mode.

### Defaults and validation

| Setting | Validation | Recommended value |
|---------|------------|-------------------|
| AKS system nodes | At least 2. Production requires at least 3. | 3 |
| AKS user nodes | At least 3. | 3 with `postgres-flex` |
| AKS user nodes with `postgres-aks` | At least 4. | 4 for non-production compact use |
| System node SKU | At least 4 vCPUs and 4 GB memory; available in the selected region and subscription. | `Standard_D4as_v5` |
| User node SKU | Region and subscription must report it available. | `Standard_D4as_v5` |
| Availability zones | Every requested zone must exist for both selected SKUs. | Three zones in production |

The node-count floor proves only that the profile is structurally supported. Production planning
also evaluates the declared workload envelope after AKS reservations and per-node DaemonSet
requests:

$$
(N - 1) \times C_{allocatable}
\ge 1.2 \times (C_{services} + C_{jobs} + C_{database}) + C_{daemonsets}
$$

Memory uses the same inequality. A profile that misses either bound is blocked before Terraform
planning. The error reports the requested and allocatable quantities without exposing tenant data.

## State ownership

Connected deployments for both runtime profiles boot the managed host from an exact Azure
Marketplace Ubuntu version and install the checksum-pinned toolchain during Foundation. They do
not build or require a dedicated managed-host image. Artifact-offline deployments can still select
a separately verified prebuilt host image when bootstrap downloads are unavailable.

Tenant provisioning consumes prebuilt service and dependency images only. A complete release's
closed dependency-image set includes both ClamAV and pgvector; neither can be omitted from the
signed kit when one deployment profile does not use it. The provisioner verifies signatures,
provenance, source revision, platform and digest before making the images available to AKS. It does
not invoke Docker, Buildx, ACR Tasks, a remote builder or VM image capture. Release construction is
an upstream supply-chain activity and is never recovered by rebuilding inside a tenant run.

An optional Foundation `application_workload` token can separate the new application group's name
from operations naming without changing the AKS profile. It grants no ownership of an existing group;
partial-state recovery follows the [application group collision contract](installable-deployment-cli.md#application-group-collision-recovery).
The application stage derives the shared Terraform workload token from the exact Foundation handoff
resource-group name and rejects a mismatched environment, region or workload grammar before planning.
The separate `operations_public_ip_tags` input preserves only the exact observed Foundation
Bastion/NAT policy tag; it does not alter AKS node settings or grant lifecycle drift exceptions.

The read-only capacity preflight accepts nonnegative integer quota values and canonical decimal
integer strings returned by Azure CLI. Boolean, fractional, signed, whitespace-padded or oversized
representations remain blocked. Available quota never overrides a SKU restriction, missing zone,
unsupported architecture or missing host encryption; a different target requires a fresh review.

Source execution separately reads the [Azure Retail Prices API](https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices)
after initial settings confirmation and before Foundation planning. It selects exactly one primary
USD hourly Linux consumption meter per selected VM SKU and region; Windows, Spot, Low Priority,
reservation, foreign-service, future-effective and tiered prices cannot substitute. Four complete
pages share one deadline, each body is bounded, and redirects or failed reads never trigger retries.
The partial compute projection uses system nodes plus the user autoscaler maximum for 730 hours.
If that component alone exceeds the monthly ceiling, planning is blocked. Otherwise the result
remains `partial`, with Foundation, control-plane, disk, database, network, registry, storage,
monitoring, messaging, model, tax, surge and setup costs explicitly excluded. It is not a full
installation estimate, setup-cost verification, billing cap or execution authorization.

Runtime selection does not replace one resource type with another in the same state. Each owner
has a distinct backend key so a new installation creates only its selected platform and an existing
installation cannot switch platforms by changing one variable.

| Owner | Backend key pattern |
|-------|---------------------|
| Shared Azure platform and Container Apps default | `fdai-<environment>.tfstate` |
| AKS substrate | `fdai-<environment>-aks-cluster.tfstate` |
| AKS workloads and scheduled jobs | `fdai-<environment>-aks-workloads.tfstate` |
| In-cluster PostgreSQL | `fdai-<environment>-aks-database.tfstate` |

The shared platform continues to own Event Hubs, Key Vault, Azure Container Registry, monitoring,
workload identities, case-history storage, and `postgres-flex`. Case-history content defaults its
active, deletion-due, superseded-version, and change-feed periods to 30 days; operational-history and
decision-evidence metadata keep their separate schedules. The AKS substrate state owns only the
cluster, node pools, cluster identity, networking attachment, and cluster-scoped Azure role
assignments.
AKS consumes the shared root's Key Vault output; overlength candidates use the deterministic
`kv-aip-<8hex>` fallback without creating a second runtime naming rule.
Selecting AKS creates the application VNet plus node and API-server subnets even when detailed
private networking is off. The separate private-networking input controls service private
endpoints, hub peering and private DNS rather than the AKS subnet prerequisite.
The default-disabled dev alert-noise pilot remains a shared-platform prerequisite for either
runtime choice. Its exact target contains only one dedicated Action Group and one metric alert;
runtime selection grants no pilot approval, notification authority, or promotion.
Kubernetes resources are applied only after independent Azure control-plane readback proves that
the cluster reached `Succeeded`, API Server VNet Integration is active and the reviewed management
path is reachable. Basic deployment initially keeps authenticated public API access so an external
coordinator can complete the baseline. The workload state then reads the approved cluster's OIDC
issuer and uses an owner-only kubeconfig on the deployment host.
The Terraform scanner exceptions for this public baseline are resource-local and name the explicit
CIDR allowlist, Microsoft Entra RBAC, disabled local accounts and VNet Integration controls. It
does not suppress other AKS findings or certify the later private transition.
Database and application preparation both convert that owner-only kubeconfig with
[`kubelogin` managed identity authentication](https://learn.microsoft.com/en-us/azure/aks/kubelogin-authentication)
using `--login msi` and the exact managed-host client ID. Credential acquisition pins the
subscription and never requests admin credentials. Local `kubectl config view --minify` readback
must show one exec-only user, `kubelogin get-token`, one matching client and one MSI login option,
without environment overrides. Failed conversion or mismatched readback stops before Kubernetes
operations; neither browser/device-code login nor default/node identity is a fallback.
The common plan-review validator accepts the existing `substrate`, `runtime`, `database` and
`application` stages with the same exact digest, expiry and destructive-confirmation checks.
Accepting an AKS stage never grants it approval or permission to skip an earlier stage.

## Runtime rendering

FDAI services keep one runtime-neutral workload specification containing these fields:

- digest-pinned image, command, arguments, and environment names;
- resource requests and limits;
- startup, liveness, and readiness probes;
- ingress intent and service port;
- sidecars, secret references, workload identity, and scaling bounds.

The Container Apps renderer maps the specification to Container Apps and Container Apps Jobs. The
AKS renderer maps it to typed Kubernetes `Deployment`, `Service`, `ServiceAccount`,
`HorizontalPodAutoscaler`, `PodDisruptionBudget`, `NetworkPolicy`, and `CronJob` resources. The
first AKS implementation keeps two replicas for each long-running service and does not require
Knative or KEDA.

Both renderers bind Core to the `fdai.operating-model` logical topic through
`FDAI_OPERATING_MODEL_TOPIC`. The topic shares the existing semantic physical Event Hub and its
managed-identity transport; it is not another Event Hub entity or authority channel. The AKS
standalone renderer obtains the value from the exact substrate output, while the independent and
legacy Container Apps renderers receive the same typed deployment input.

Operator assignment and human-approval (HIL) transport imports share the existing `iam_composition`
facade within the same Operator Service package and runtime; original adapter and factory objects
are re-exported without wrappers. This grouping changes no topology, workload identity, readiness
behavior, or exact-plan deployment approval requirement for either renderer.

Long-running service containers use `image_pull_policy=Always`, a read-only root filesystem, and
a dedicated `/tmp` temporary volume limited to `1Gi`. Workload validation rejects mutable tags
and malformed image digests before planning. Other writable paths require an explicit workload
contract; making the whole root filesystem writable is not a compatibility fallback.

The five-service AKS baseline enables lexical document retrieval without requiring an embedding
deployment. Document API and Worker use distinct workload identities, role-scoped database DSNs,
the shared ADLS account and the `fdai.pipeline.stages` entity. The Worker Pod includes the existing
digest-pinned ClamAV image as a replica-local TCP sidecar. Its root remains read-only and only the
declared database, run and temporary paths receive size-limited `emptyDir` volumes.

Scheduled jobs use `concurrencyPolicy=Forbid`, one completion, one parallel worker, a bounded active
deadline, a retry limit, and bounded history. Manual jobs are created only by a separately approved
request and are not perpetual desired-state resources.
The AKS baseline renders analyzer, canary, inventory, observation campaign, and operational-history
lifecycle CronJobs. The history job uses the read-only inventory identity, the service-owned state
DSN, and the private archive URL in fixed `shadow` mode. A non-shadow lifecycle requires a separate
protected transition and an exact persisted certification receipt; runtime selection grants neither.

The inventory command preserves read-only failure boundaries on both platforms and locally. Activity
Log recovery fails unavailable without advancing delta cursors or stopping full reconciliation.
Passive model-serving evidence reuses inventory identity and Azure Monitor without model credentials
or inference; bounded failures reduce only its coverage and malformed responses stay redacted.
Reconciliation bounds determine lookback, freshness, points, and timeout, while additive metadata
keeps baseline inventory available during Core-first or Operator-first updates.

The managed host records the selected Deployment names, image references, and replica bounds.
Health readback requires that complete set, current observed generations, ready replicas, and
running Pod image digests from the same source revision. Empty, duplicate, stale, malformed, or
partially healthy responses are unavailable, not success. The expected set must contain all five
baseline services; a renderer that omits one cannot redefine a partial rollout as complete.
This readback does not establish Kafka
round trips, scheduled-job success, Console authentication, or full deployment readiness.
The workload factory binds Operator, isolated Executor, Document API and Document Worker to
`fdai_operator`, `fdai_executor`, `fdai_ingestion_api` and `fdai_ingestion_worker`, respectively,
through `FDAI_DATABASE_ROLE` and matching `PGOPTIONS`. It leaves the caller's environment unchanged.
All rendered services explicitly select the deployed execution venue. Role selection neither grants
database membership nor supplies service-owned DSNs, and never enables Executor authority cutover.

## Identity and secrets

Each FDAI workload keeps its current user-assigned Managed Identity. On AKS, one namespaced
Kubernetes ServiceAccount receives one federated identity credential. The privileged Executor
identity is never shared with the console, Operator Service, jobs, or other workloads.

The five baseline services select the Azure Identity SDK's workload credential when
`AZURE_FEDERATED_TOKEN_FILE` is declared. The projected token path must be absolute, tenant and
client identifiers must be valid, and the federated client must match the service's explicitly
selected identity. Incomplete or conflicting federation blocks startup or token acquisition;
it never falls back to the node identity, Azure CLI, or another service. Without the federation
declaration, the existing attached Managed Identity path remains unchanged.

Operator may explicitly select `FDAI_COMMAND_MI_CLIENT_ID` for its semantic and live Kafka
adapters while `AZURE_CLIENT_ID` remains its primary workload identity. Each identity requires its
own federated credential for the same ServiceAccount subject and its separately scoped roles.
Only the primary or declared command client can be selected; an omitted selection keeps the primary
client, and an invalid or unrelated client fails before token exchange. This does not grant roles
or fall back after a failed exchange.

Core and isolated Executor retain audience-specific caching and request coalescing, bound each
federated token exchange, close its SDK session, and sanitize acquisition failures. Each declares
`azure-core`, `azure-identity`, and the SDK's `aiohttp` transport in its own distribution. Dependency
checks distinguish direct SDK imports from SDK-owned transport use. Operator and document services pass the
SDK's common asynchronous credential contract to their existing adapters. These local integration
checks do not prove deployed federation, Event Hubs access, or service readiness.

For the Container Apps profile, the protected platform-to-Core handoff carries the exact
inventory-reader identity resource and client ids with the observation context. The service
materializer attaches that read-only identity once, removes only that identity when observation is
disabled, and rejects any mismatched binding. Signed scale-out evidence names the FinOps executor
credential lineage, while VM-start evidence names the Resilience executor credential lineage.
Neither identity choice grants execution authority, and local interactive never receives this
binding.

The AKS managed Key Vault CSI provider synchronizes fixed Key Vault references into namespaced
Kubernetes Secrets by using each workload's federated identity. Applications continue to read
environment variables and never call Key Vault directly. Terraform plans contain secret names and
versionless references, not secret values.

The managed CSI provider is enabled with the cluster and is separate from FDAI workload rollout.
The deployment kit includes the Kubernetes provider plus signed `kubectl` and `kubelogin`
binaries. A deployment does not download a provider, tool, or workload image from a public source
after kit verification.

### Cluster security baseline

The shared platform supplies dedicated AKS workload and API-server subnets. Basic deployment enables
API Server VNet Integration at cluster creation and reserves at least a `/28` delegated API-server
subnet so private-cluster mode can be enabled later without replacing the cluster. The cluster state
owns an explicit Standard NAT Gateway, static Standard outbound public IP, and both associations
before AKS creation; its outbound type is `userAssignedNATGateway`, not the
AKS-managed-VNet-only `managedNATGateway`.

The basic profile keeps authenticated public API access enabled and applies the reviewed access
restriction. API-server-to-node traffic still uses the integrated private path. This is the
connected baseline, not a claim of private-cluster, network-isolated, zone-redundant NAT or
firewall/UDR compatibility. A tenant policy that requires private access from the first effect
blocks the public baseline and selects an eligible internal execution host plus an exact private
plan instead of weakening the policy.

The cluster enables Azure Policy, patch-channel Kubernetes upgrades, and NodeImage OS upgrades.
Both node pools enable host encryption and allow 50 pods per node. Confirm the selected
subscription and SKU support host encryption before deployment. The read-only preflight queries
the regional catalog once and uses an exact-name Azure CLI projection so only the distinct selected
SKUs are serialized, then checks their regional restrictions, three required zones, architecture,
host encryption, and family plus total quota. It does not issue a second catalog request for a
different node-pool SKU or retry a failed provider read. Unsupported targets do not disable
encryption. Allocatable workload-envelope validation remains open in the implementation ledger.

The default diskless SKUs retain platform-encrypted Managed OS disks rather than requiring
ephemeral storage. Checkov exceptions stay attached to the affected resource: the pinned scanner
reads retired AzureRM upgrade and encryption attribute names and cannot resolve validated image
map entries. Focused configuration and plan tests cover those controls; no global baseline or
scanner downgrade is used.

### Detailed private-network provisioning

After the authenticated Console and all baseline services are healthy, `/provisioning` can create a
network-hardening request. The request may select existing-VNet or hub peering, route and firewall
bindings, private DNS zones and links, private endpoints, AKS private-cluster mode, registry cache or
private-link changes, and public-access removal. Console stores only the sanitized intent, plan
metadata, approval state and effect evidence. The protected deployment executor owns Terraform and
Azure mutation.

The exact plan orders changes to avoid losing access:

1. Validate every selected address range and prove that peer, service, Pod and Kubernetes service
  ranges do not overlap.
2. Establish peering, routes and DNS, then verify the execution host can resolve and reach the AKS
  API and every selected service endpoint.
3. Create private endpoints and registry paths, verify workload and deployment identities, and run
  baseline health through the new path.
4. Enable AKS private-cluster or network-isolated settings and disable public paths only after the
  private observations pass.
5. Retain rollback and an independently observed terminal receipt. An ambiguous effect is
  verification-only and never triggers the same apply again.

The operator's current VM may be the execution host when exact target, identity, route, DNS, TLS and
backend checks pass. Peering that VM's VNet is a planned network effect, not evidence by itself.

## PostgreSQL profiles

`postgres-flex` remains the default for both runtime platforms. Production uses private networking,
zone-redundant high availability, 35-day backup retention, and geo-redundant backup according to
the production hardening contract.

`postgres-aks` is initially a non-production compact profile. It uses a digest-pinned PostgreSQL
16 pgvector image, a single typed `StatefulSet`, a managed Premium SSD volume, and a private
internal load balancer used by the migration host. The generated DSN is stored in Key Vault and
read by workloads through managed CSI. Client traffic requires TLS with a state-owned certificate.
The minimum four user nodes make this profile schedulable
but do not claim database high availability, backup, or point-in-time recovery.

The Key Vault DSN has no independent fixed expiration. Credential rotation requires coordinated
database and workload updates; expiring only the secret would interrupt access without rotating
the database credential. This resource-local exception does not claim automated rotation evidence.

An in-cluster production profile remains unavailable until it proves three database instances,
synchronous replication, zone and host anti-affinity, disruption budgets, backup immutability,
point-in-time recovery, node upgrade, zone loss, and independent effect verification. That profile
should use a dedicated tainted database node pool unless measured capacity proves a shared pool.

## Provisioning graph

The selected profile compiles a finite dependency graph:

![Provisioning flow from signed-kit verification through runtime and database selection to service deployment and readiness checks.](../../diagrams/generated/fdai-roadmap-deployment-runtime-deployment-profiles-01.en.svg)

Every mutating node has its own exact plan, current human approval, pre-effect claim, timeout,
rollback or recovery reference, and authoritative observer. `deployment_ready=true` requires all
selected services healthy, workload identities effective, Kafka round trips complete, database
migrations current, one canary job successful, and every selected state root at a second
zero-change plan.

## Signed kit requirements

The complete signed kit includes every prebuilt input needed by either profile:

- all Terraform roots and their lock files;
- AzureRM, Kubernetes, Random, and TLS provider mirrors;
- Terraform, OPA, `kubectl`, `kubelogin`, and bounded deployment helpers;
- signed, digest-pinned FDAI and dependency OCI archives that tenant provisioning never rebuilds;
- managed AKS CSI integration and federated identity inputs;
- migration support, Console assets, manifests, signatures, provenance, and software bills of
  materials.

Online and artifact-offline modes execute the same verified bytes. The managed host does not use
ambient Terraform providers, Helm repositories, mutable image tags, or an operator kubeconfig.

## Completion evidence

Implementation is complete only after focused local checks and both operational paths provide
reviewable evidence:

1. Existing Container Apps installation tests remain unchanged and pass.
2. AKS plus `postgres-flex` reaches readiness from one signed online kit.
3. AKS plus `postgres-aks` reaches non-production readiness from one signed online kit.
4. The same two AKS profiles pass artifact-offline kit verification and deployment.
5. Every selected root produces a zero-change second plan.
6. Reusing the same profile is safe to retry and does not create another resource.
7. Changing runtime or database placement stops with a migration-required result.
8. A failed service rollout restores the prior healthy workload and still reports deployment
   failure.
9. Backup and point-in-time restore succeed for each selected database placement.
10. A separately approved Console-originated network plan enables private access without replacing
  the cluster, losing the last verified management path or allowing the browser to mutate Azure.

Source and provider tests prove implementation. Live receipts are required before the AKS path is
classified as validated or advertised as ready for production.

## Related docs

| To learn about | Read |
|----------------|------|
| Implementation progress | [Runtime deployment profile implementation](../../roadmap-implementation/deployment/runtime-deployment-profiles.md) |
| Standalone command behavior | [Installable Deployment CLI](installable-deployment-cli.md) |
| Concrete Azure inventory | [Deploy and Onboard](deploy-and-onboard.md) |
| Production gates | [Production deployment hardening](production-deployment-hardening.md) |
| Runtime portability | [CSP-Neutrality Contracts](../architecture/csp-neutrality.md) |
