---
title: Hub-Managed Lifecycle
---
# Hub-Managed Lifecycle

This document defines FDAI's third installation path. A Lifecycle Hub keeps each installation on
its subscribed release channel and on the configuration that its customer approved, following the
hub-and-spoke model of Palantir Apollo. It owns the lifecycle architecture, the plan and state
loop, and the customer isolation boundary.

> **Status:** Design only. No Hub, installation agent, Lifecycle Plan, or upgrade bundle exists
> yet. The [implementation ledger](../../roadmap-implementation/deployment/hub-managed-lifecycle.md)
> tracks delivery. [ADR-0003](../architecture/decisions/0003-hub-managed-lifecycle-and-operator-governance.md)
> records the decisions.
>
> **Scope:** This path manages FDAI's own lifecycle: installation, upgrade, configuration, drift,
> and recall. It never manages customer resources, which stay with the operations loop.
> [Lifecycle Configuration](lifecycle-configuration.md) owns configuration layers and secrets, and
> [Lifecycle Releases and Channels](lifecycle-releases-and-channels.md) owns Releases, channels,
> bundles, and recall.

## Design at a glance

| Concern | Decision |
|---------|----------|
| Product versus installation | One signed Release serves every customer. An installation differs only in configuration, policy, and bindings to its own environment. |
| Hub placement | A central Hub cell per connected customer, or a Target Hub inside the customer boundary that syncs online or imports signed bundles offline |
| Desired state | No single target state. The Hub derives the target from a channel subscription, version range, configuration revision, and constraints. |
| Plan computation | The Hub computes Lifecycle Plans. Installation agents derive the maximum effect envelope locally, and a Plan can only narrow it. |
| Installation agents | A lifecycle agent inside the cluster for workloads, and an infrastructure agent on the execution host for exact Terraform plans. Neither is a pantheon agent. |
| Upgrades | Automatic inside maintenance windows. Configuration changes need an approved change request, and deleting or replacing an Azure resource needs confirmation. |
| Data boundary | The Hub holds no Azure credential, secret value, or operational data. Only lifecycle metadata crosses the boundary. |
| Records | Hub PostgreSQL per cell or Target Hub, and append-only installation receipts in Foundation storage |

## Core concepts

Four concepts carry the whole design. Keeping them apart is what lets one product serve every
customer without a fork.

| Concept | What it is | Owner | Changes through | Lives in |
|---------|------------|-------|-----------------|----------|
| Product | FDAI itself, shipped as signed Releases that are identical for every customer | Vendor | Release pipeline, channel promotion, and recall | Release catalog |
| Installation | One FDAI deployment inside one customer boundary, which Apollo calls an Environment. A customer can have several. | Customer | Enrollment, channel subscription, and Entity settings | Hub `installation` and `entity` tables |
| Configuration | Desired values for one installation: Environment Config and Entity override blocks. It never carries authority. | Customer | Reviewed merge in customer Git, delivered as a signed package | Customer Git, then Hub configuration tables |
| Runtime state | What the installation actually runs and observes: reported state, receipts, policy and authority state, and operational data | Installation | Agents and governed authority paths only | Installation stores. The Hub sees lifecycle metadata only. |

## Design and critique

**Initial design:** A central control plane stores one desired state per customer, a five-layer
override stack resolves configuration, and new Deployment, Configuration, Drift, and Policy agents
run the rollout.

**Critique:**

- Apollo doesn't keep one target state per environment. A product follows a release channel and
  constraints, and the target emerges from them
  ([Apollo overview](https://www.palantir.com/docs/apollo/core/overview)).
- The pantheon is fixed. An agent that upgrades the runtime it runs on also creates a circular
  dependency.
- A central engine that renders exact plans needs every customer's Azure credentials, which
  regulated customers prohibit.
- A linear override stack lets configuration change authority, which ADR-0002 forbids.
- Offline sites can't poll a central service.

**Revised contract:** The Hub orchestrates. Signed artifacts and installation-side agents decide
what can actually change. Authority stays in policy and the promotion registry, and offline sites
run their own Target Hub.

## Apollo concepts in FDAI terms

| Apollo concept | FDAI equivalent | Difference |
|----------------|-----------------|------------|
| [Product, Release](https://www.palantir.com/docs/apollo/core/products-releases-versions) | FDAI Release: signed image digests and metadata | One product. Services aren't released separately. |
| [Release Channel](https://www.palantir.com/docs/apollo/core/release-channels) | `DEV`, `RELEASE_CANDIDATE`, `RELEASE`, and custom channels | Same model. See [Lifecycle Releases and Channels](lifecycle-releases-and-channels.md). |
| [Hub, Orchestration Engine](https://www.palantir.com/docs/apollo/core/overview) | Lifecycle Hub | Computes Plans but never renders exact infrastructure changes |
| [Environment](https://www.palantir.com/docs/apollo/core/environments) | Installation | One installation per environment. A customer can have several. |
| [Spoke Control Plane](https://www.palantir.com/docs/apollo/core/spoke-control-plane) | Lifecycle agent and infrastructure agent | Azure writes stay on the existing execution host |
| [Entity, Reported State](https://www.palantir.com/docs/apollo/core/entities) | Entity, reported state | Agents are sub-state of the Core Entity |
| [Environment Config](https://www.palantir.com/docs/apollo/managing-environments/environment-config), [config overrides](https://www.palantir.com/docs/apollo/managing-entities/set-config-overrides) | Environment Config, Entity override blocks | Authority values are excluded |
| [Change Requests](https://www.palantir.com/docs/apollo/managing-changes/change-requests) | Reviewed merge in customer Git, delivered as a signed configuration package | Git is the source of desired configuration |
| [Plans and Constraints](https://www.palantir.com/docs/apollo/core/plans-and-constraints) | Lifecycle Plans and constraints | Adds data residency and destructive-change confirmation |
| [Export and Import](https://www.palantir.com/docs/apollo/export-import/overview) | Upgrade bundle imported into a Target Hub | Configuration packages keep the customer signature |
| [Secrets](https://www.palantir.com/docs/apollo/managing-secrets/add-edit-delete-secrets) | Key Vault references only | The Hub never receives a secret value |

## Architecture

![Architecture. The main stages are Vendor release catalog / signed Releases, channels, recalls, Lifecycle Hub / central Hub cell or Target Hub, Customer Git / desired configuration, Lifecycle agent / workloads and reported state, Infrastructure agent / exact Terraform plans, FDAI services / operations loop, Azure resources.](../../diagrams/generated/fdai-roadmap-deployment-hub-managed-lifecycle-01.en.svg)

| Component | Runs in | Identity | Holds | Never holds |
|-----------|---------|----------|-------|-------------|
| Release catalog | Vendor | Vendor release key, kept offline | Signed Releases, channel membership, recalls, promotion pipelines | Customer data |
| Lifecycle Hub | Central Hub cell or Target Hub | Hub service identity. Approvers sign in with the customer's Entra ID. | Installation settings, imported configuration packages, reported state, Plans, constraint results, audit | Azure credentials, secret values, clear-text sealed values, operational data |
| Lifecycle agent | Installation AKS cluster, own namespace | Workload identity with Kubernetes rights in FDAI namespaces only | Rendered workload manifests and workload receipts | Azure write identity, executor identity |
| Infrastructure agent | Existing execution host | Existing deployment managed identity | Exact Terraform plans, Foundation state, infrastructure receipts | Executor identity, operational data |
| FDAI services | Installation | Existing service identities | Operations-loop state | Lifecycle authority |

### Hub placement

| Placement | Location | Catalog source | Operated by | Typical customer |
|-----------|----------|----------------|-------------|------------------|
| Central Hub cell | Vendor subscription, in a region agreed with the customer. Each customer gets an isolated cell with its own database and customer-managed key. | Release catalog directly | Vendor | Connected, no boundary restriction |
| Online Target Hub | Customer operations resource group | Sync from the catalog over an allowlisted outbound path | Customer | Regulated and connected |
| Offline Target Hub | Customer operations resource group | Signed upgrade bundles that an operator imports | Customer | No internet access |

A Hub cell is a per-customer isolation unit of the central Hub. It's unrelated to the streaming
cells in [Hyperscale Cell Architecture](../architecture/hyperscale-cell-architecture.md).

### Trust boundaries

- The vendor release key signs Releases, catalog metadata, recall notices, and upgrade bundles.
  [Catalog integrity](lifecycle-releases-and-channels.md#catalog-integrity) defines freshness and
  ordering.
- The customer configuration key signs configuration packages. It stays in the customer's Key
  Vault or HSM.
- Each installation holds a non-exportable installation key in its Key Vault. It proves possession
  of that key at enrollment, then uses it to unwrap sealed values and sign receipts.
- Each Hub cell or Target Hub has its own Hub key. Hub and installation keys rotate through signed
  key records, and revoking a key invalidates every Plan it signed.
- Installation agents derive the maximum effect envelope locally from the signed Release, the
  configuration package, ownership evidence, and local hard policy. A Hub Plan can only narrow it.
- Only lifecycle metadata crosses the boundary: versions, digests, coarse component health,
  constraint results, and sanitized plan summaries. Event content, resource identities, ontology
  content, audit content, secrets, credentials, and clear-text identifiers stay inside the
  installation.

## Lifecycle loop

### Desired inputs

The Hub derives each installation's target from these inputs:

- channel subscription and an optional version range;
- current configuration revision: Environment Config and Entity override blocks;
- catalog facts: Releases, channel membership, recalls, product dependencies, and schema ranges;
- constraints and the latest reported state.

The target is the newest non-recalled Release on the subscribed channel inside the version range
that passes every constraint. It deploys with the override block whose version range matches that
Release most specifically.

### Entities and reported state

| Entity kind | Examples | Managed |
|-------------|----------|---------|
| Workload | Core, Operator API, Document Ingestion API, Document Processing Worker, isolated Executor, Console, CronJobs, lifecycle agent | Yes |
| Platform | AKS cluster, PostgreSQL, Event Hubs namespace, Key Vault, container registry, storage, network | Yes |
| Unmanaged | Customer-owned API Management, private DNS zones, ITSM endpoints | Observed only |

Reported state includes the Release version, image digests, configuration digest, coarse health,
and the last Plan result. The Core Entity adds a band for each agent: running, degraded, or stopped,
with bounded consumer-lag and idle-time bands. Event content and per-event times stay inside the
installation. Platform Entities add digests of Terraform state lineage, serial, and resource
identities. As in Apollo, an Entity with settings and reported state is managed, and an Entity with
reported state only is unmanaged. Reported state is append-only and keeps event and recorded time.

### Lifecycle Plans

Plan types are install, upgrade, configuration change, recall roll-off, drift reconciliation, and
uninstall. Uninstall always needs operator confirmation. Each Plan names its installation as the
audience, the Hub key epoch, the reported-state digest it was computed from, a sequence number that
increases per installation, a fencing generation, the target Release, the configuration revision,
the Entity set, constraint results, a narrowing envelope, and an expiry. Agents durably reject a
Plan whose sequence, generation, or source-state digest is stale.

A Plan runs as a fenced sequence of phases. The infrastructure agent owns the infrastructure phase,
and the lifecycle agent owns the workload phase. A phase starts only after the previous phase's
receipt is recorded. A failure compensates completed phases in reverse order when the Release
allows it, and otherwise holds the installation for the operator.

1. An agent polls the Hub and verifies the Plan signature, audience, sequence, and generation.
2. The agent verifies the Release and configuration signatures. It rejects a Release older than
   the newest one it applied unless a vendor-signed recall allows the roll-back.
3. The infrastructure agent renders the exact Terraform plan with sealed values decrypted locally.
   The lifecycle agent renders workload manifests.
4. The agent compares the exact change with its locally derived envelope as narrowed by the Plan.
   It refuses any change outside that envelope and holds the deletion or replacement of an existing
   Azure resource for an operator confirmation bound to the same exact plan digest.
5. The agent writes a local lifecycle authorization receipt that binds the exact plan digest to the
   Plan, Release, configuration revision, and open window. That receipt stands in for the
   operator's invocation in the existing exact-plan claim, apply, and verification-only recovery
   stages. The agent reports the digest and a sanitized summary to the Hub.
6. Success requires healthy workloads, a second zero-change plan, and independent readback. The
   receipt is appended to Foundation storage, and the Hub records the result.

The lifecycle agent, the infrastructure agent, and a Target Hub upgrade themselves through two
slots. The new version starts beside the old one, passes health checks, and then takes over. The
old slot stays as the rollback target.

### Constraints

| Constraint | Set by | Blocks |
|------------|--------|--------|
| Maintenance window, no-downtime or downtime | Customer, in an IANA time zone with the time-zone database version pinned by the Release | Plans whose declared maximum duration doesn't fit inside the remaining window. Overlapping windows of one class merge, and the trusted UTC clock decides. |
| Suppression window | Operator, or automatic after a failure | Plans in its scope. A failure suppression doesn't block the rollback of the failed Plan. |
| Version range | Customer | Releases outside the range |
| Product dependency and schema range | Release metadata | Incompatible upgrades and roll-backs |
| Artifact availability | Installation registry | Plans whose images aren't inside the boundary |
| Override coverage | Customer | Releases without a matching override block |
| Data residency | Environment Config | Releases or model bindings that process data outside the allowed scope |
| Recall | Vendor | Proposing a recalled Release. It also triggers a roll-off. |
| Destructive change | Constitution | Deleting or replacing an existing Azure resource until confirmed |

### Failure, drift, and reconciliation

- A failed Plan places an automatic suppression window on its Entity. When failures cross a
  configured threshold, the whole installation is suppressed, as in Apollo. A rollback Plan to the
  previous Release runs when the schema range allows. Otherwise the installation holds for the
  operator.
- Lifecycle drift is a difference between reported state and the desired inputs, such as a manual
  change to a Deployment or Terraform refresh drift. The Hub issues a reconciliation Plan for the
  next matching window.
- The Hub recomputes Plans when reported state, Entity settings, the configuration revision,
  channel membership, or a recall changes, and when a Plan stays blocked past a bounded threshold.

### Commands and overrides

Apollo has no runtime-override layer. Its closest concepts are suppression windows, maintenance
window overrides, and break-glass commands. FDAI keeps that split:

| Command | Who | Effect | Expiry |
|---------|-----|--------|--------|
| Suppression window | Lifecycle operator | Stops new Plans in its scope immediately | Required |
| Authority-lowering command | Installation operator | Demotes an ActionType, lowers an autonomy ceiling, or engages the kill switch immediately | Required. The operator gets notice before expiry and can extend it. |
| Break-glass command | Break-glass role with fresh authentication | Applies an emergency configuration change, such as a scale-out, or bypasses a maintenance window, suppression window, or version range | Required. At expiry, the Hub reconciles to the approved Git revision unless a merged change adopted it. |

No command raises authority. A break-glass command can bypass only maintenance windows,
suppression windows, and version ranges. It still passes signature checks, the local envelope, the
exact plan, the lock, idempotency, audit intent, recall, destructive-change confirmation, recovery,
and independent readback. The installation's own kill switch route keeps its existing behavior.

## Separation from the operations loop

- The lifecycle loop changes only resources that FDAI provably owns. Proof is a signed Foundation
  creation receipt with a matching Terraform state identity. The `fdai:managed=true` tag is only a
  discovery hint, because anyone with tag rights can set it.
- The operations loop never proposes an action that targets a proven FDAI-owned resource, and the
  risk gate denies such a target. Heimdall may still report drift on those resources as advisory
  evidence.
- Lifecycle agents never publish authority-bearing events. Saga may cite lifecycle receipts as
  evidence references only.

## Customer isolation and data residency

| Requirement | How the design meets it | How to verify |
|-------------|-------------------------|---------------|
| Data stays in Korea | Target Hub and installation in Korea Central, and the Hub stores metadata only | Azure Policy allowed locations and reported binding scope |
| No overseas endpoints | Allowlisted catalog sync, or offline bundles | Egress firewall logs and the [network matrix](network-connectivity-matrix.md) |
| Approved model endpoints only | Model-binding allowlist and a residency constraint in Environment Config | Binding validation at startup |
| PTU required | Model bindings with capacity type `ptu` | Settings model inventory |
| Isolated network | Private endpoints, and agents poll a Target Hub inside the boundary | Network matrix scenario |
| No central access to data | Target Hub inside the boundary. Even a central cell holds no operational data and only sealed identifiers. | Hub data model review and audit |

Azure model deployment types differ in where prompts are processed. Global types may use any
region, Data Zone types stay inside a zone such as Asia Pacific, and Standard or Regional
Provisioned types stay inside the resource's geography
([deployment types](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/concepts/deployment-types)).
In-country processing with PTU therefore needs Regional Provisioned, which isn't offered for every
model.

### If a Hub is compromised

A compromised Hub can delay upgrades or withhold Plans. It can't widen the effect envelope, forge a
Release or configuration package, replay a Plan to another installation, read sealed values, or
obtain an Azure credential. Agents refuse a version roll-back without a vendor-signed recall, and
expired catalog metadata lowers authority as described in
[Catalog integrity](lifecycle-releases-and-channels.md#catalog-integrity). A compromised cell can't
affect another customer's cell, because each cell has its own key, database, and customer-managed
key.

### Vendor support

Support staff see only the metadata of central cells. A Target Hub's records stay with the
customer unless the customer exports a sanitized support bundle. Access to an installation uses a
time-bound role that the customer grants in its own tenant. The Hub grants none.

## Enrollment and migration

1. An operator creates the Foundation with their own sign-in, as in the other paths, or starts
   from an existing installation. An offline site installs its Target Hub and first Release from
   the signed offline package.
2. The operator installs the lifecycle agent and infrastructure agent from a signed Release.
3. The installation proves possession of its installation key to the Hub, and a customer approver
   accepts the enrollment.
4. Entities start unmanaged. An Entity becomes managed only after its ownership is proven and the
   operator adds its settings.
5. The first Plan replaces any source-built images with signed images.

Today the Terraform application stage renders workloads. The Hub path moves the rendering of
namespaced workload objects to the lifecycle agent, as
[Workload rendering migration](#workload-rendering-migration) defines. Terraform keeps Azure
resources, cluster-scoped objects, and authority-granting role bindings.

## Workload rendering migration

This section defines how a Hub-managed installation moves workload rendering from the Terraform
application stage to the lifecycle agent, and how that move is rolled back. The one-command source
deployment and the signed offline package keep the Terraform application stage unchanged.

### Current rendering

The deployment CLI builds a `workloads` map and a `scheduled_jobs` map from substrate outputs,
image digests, and the product profile. It then applies one Terraform root,
`infra/runtimes/aks/workloads`, through the exact-plan claim, apply, and verification-only recovery
stages. That root writes three kinds of objects:

- namespaced Kubernetes objects for each workload and scheduled job;
- cluster-scoped Kubernetes objects and role bindings that grant FDAI identities their reach;
- Azure resources: federated identity credentials, the API Management browser gateway, and its
  network security rule.

### Design and critique

**Initial design:** Run the whole Terraform workloads root inside the lifecycle agent.

**Critique:**

- The root writes Azure resources, but ADR-0003 A11 keeps the Azure write identity on the
  execution host.
- The root creates the namespace and a cluster role. The lifecycle agent holds Kubernetes rights
  in FDAI namespaces only.
- API Management reads its backend address from the external LoadBalancer Services. If the agent
  owned those Services, the infrastructure phase would depend on the workload phase.
- Workload values mix product content, such as images, probes, and security settings, with
  installation identifiers, such as client IDs and endpoints. A Release can't carry the
  identifiers, and the Hub must never see them.
- Removing addresses with `terraform state rm` changes state outside a reviewed exact plan.

**Revised contract:** Split ownership by object kind. The lifecycle agent renders only namespaced
workload objects from three separately signed inputs. Terraform releases and readopts those
objects only through exact plans that use `removed` and `import` blocks.

### Object ownership on the Hub path

| Objects | Scope | Owner |
|---------|-------|-------|
| Deployment, HorizontalPodAutoscaler, PodDisruptionBudget, NetworkPolicy, internal Service, ServiceAccount, SecretProviderClass, CronJob, and the identity-bridge ConfigMap | FDAI namespace | Lifecycle agent |
| External LoadBalancer Services for the Operator API and the Document Ingestion API | FDAI namespace | Infrastructure agent, because API Management binds to their addresses |
| Executor external-scale Roles and RoleBindings | Exact target namespaces outside FDAI | Infrastructure agent, because they grant authority |
| Namespace, and the inventory-reader ClusterRole and ClusterRoleBinding | Cluster | Infrastructure agent |
| Federated identity credentials, the API Management browser gateway with its APIs and operations, and its network security rule | Azure | Infrastructure agent |

The lifecycle agent never creates or changes a role binding, so a workload apply can't widen any
identity's reach.

Two rules keep the lifecycle agent from fighting another writer over the same field:

- **No Executor effects inside the FDAI namespace.** On the existing paths, the isolated Executor
  can patch and scale Deployments and delete pods in the FDAI namespace. On the Hub path, the
  infrastructure agent doesn't bind that role, because the lifecycle agent would revert those
  changes and the operations loop must not target FDAI-owned resources, as
  [Separation from the operations loop](#separation-from-the-operations-loop) requires. As a result,
  Kubernetes ActionTypes such as pod restart and Deployment scale aren't available against FDAI's
  own workloads on the Hub path. Executor scale targets in other namespaces are unchanged.
- **The autoscaler owns the replica count.** When a workload has a HorizontalPodAutoscaler, the
  agent omits `spec.replicas` from the Deployment it applies, as the Terraform root does today with
  `ignore_changes`. Replica override values set the autoscaler's minimum and maximum instead.

### Render inputs

The lifecycle agent renders from three inputs. Each has its own signer and its own visibility.

| Input | Content | Signed by | Hub sees |
|-------|---------|-----------|----------|
| Workload template in the Release | Images by component, commands, ports, probes, security context, sidecars, default sizing, and environment keys with their value sources | Vendor release key | Digest |
| Entity override values | Replicas, CPU, and memory inside the template's bounds | Customer configuration key | Value |
| Installation binding | Identity client and resource IDs, the container registry login server, Kafka and PostgreSQL endpoints, Event Hubs topic names, the Key Vault name, secret names, the installation and license bindings, and sealed identifiers decrypted locally | Installation key | Digest only |

The infrastructure agent writes the installation binding inside the installation after its phase.
It combines the outputs of its own Terraform roots with the sealed identifiers that it decrypts from
the configuration package, as [Lifecycle Configuration](lifecycle-configuration.md#value-classes)
defines. Each environment entry in the template declares its
value source: a literal, a configuration key, or a binding key. The renderer rejects an unknown key
and any other value source, so a template can't carry an endpoint and a Plan never needs a binding
value.

### Phases of an upgrade Plan

1. **Infrastructure:** The infrastructure agent applies only additive and in-place changes to Azure
   resources, cluster-scoped objects, role bindings, and external Services, and creates a federated
   identity credential for every workload and job in the target Release. It then writes the
   installation binding and its receipt.
2. **Schema expand:** The Release ships its database migration as a Kubernetes Job template that
   uses the Core image, which already contains the migration and catalog tools. The Job runs the
   legacy migrations, the service-owned migrations in their declared order, and the authoritative
   catalog materialization, as the managed host's migration step does today. It runs only the
   revisions that the Release classifies as expand, and it rejects a revision that drops or renames
   schema. Contract revisions run in a later fenced Plan after the restore checkpoint that
   [Lifecycle Releases and Channels](lifecycle-releases-and-channels.md#schema-compatibility)
   requires. Only revisions added after an installation's enrollment baseline need a
   classification, because earlier revisions are already applied. Some existing upgrades drop
   tables, so a Hub-managed upgrade runs no new revision without one. The existing migration locks
   are separate transaction locks per step, and catalog materialization has none, so the Job holds
   one installation-wide migration lease across all three steps and its receipt. The lifecycle agent
   runs the Job in the FDAI namespace with a dedicated migration identity before any workload
   switches.
3. **Workloads:** The lifecycle agent renders the objects, compares them with its locally derived
   envelope, and applies them with server-side apply under its own field manager.
4. **Verify:** Both agents require healthy workloads, a second zero-change render, a zero-change
   plan for the remaining Terraform roots, and independent readback.
5. **Infrastructure cleanup:** After readback shows that the workloads a target Release dropped are
   gone, the infrastructure agent removes the external Services, API Management routes, role
   grants, and federated identity credentials that served them.

A workload that is new in a Release receives its federated identity credential in phase 1, before
its pod exists in phase 3. On the existing paths, the managed host keeps running migrations
directly before the application stage.

### Ownership handoff for an existing installation

An enrolled installation moves its workload objects to the lifecycle agent in four steps. Each step
needs a local lifecycle authorization receipt, and no step deletes or recreates a running object.

Two exact plans prepare the handoff and run before step 1:

- **Split the Service resource.** A Terraform `removed` block addresses a whole resource without
  instance keys, but internal and external Services share one resource block today. A refactor
  with `moved` blocks splits it into an internal and an external Service resource. It applies on
  every installation path as a zero-change plan.
- **Remove the Executor role from the FDAI namespace.** On the Hub path, a separate plan destroys
  the Executor Kubernetes-effect Role and RoleBinding in the FDAI namespace. It lowers authority, and
  it's the only destroy that the handoff allows.

1. **Shadow parity:** The agent renders the objects and compares them with the live objects without
   writing. Differences that come only from server defaults and binding order are normalized. The
   step passes after the configured number of consecutive zero-difference reports.
2. **Release from Terraform:** The infrastructure agent applies an exact plan of the Hub variant
   of the workloads root, which the Release ships. A `removed` block requires its resource block to
   be absent, so that variant replaces each agent-owned resource block with a `removed` block with
   `destroy = false`. Terraform 1.7 and later support these blocks, and the pinned toolchain is
   1.9.8. The plan must show no destroy and no update.
3. **Adopt:** The agent applies the same render with server-side apply under the
   `fdai-lifecycle-agent` field manager. It forces conflicts only on fields that the Terraform field
   manager owns, and stops on any other conflict. It adopts one object at a time and records a
   per-object receipt with the object UID, resource version, and render digest, so an interrupted
   adoption resumes from the last receipt. Each object records the Release ID and render digest in
   annotations.
4. **Verify:** A second render shows zero changes, workloads stay healthy, and the remaining
   Terraform roots plan zero changes.

After step 2, the installation records a local Hub ownership marker. Every deployment CLI entry
point that would plan the full workloads root refuses to run or uses the Hub variant, including the
ordinary application stage, per-service update, and historical reconciliation. So Terraform and the
agent never write the same object.

**Rollback:** First, the agent stops reconciling the adopted objects, releases its reconciliation
lease, and records the release. Then the infrastructure agent applies an exact plan with `import`
blocks for the same addresses, and a following zero-change plan proves that Terraform state matches
the live objects. A failure in step 2 or 3 changes at most field ownership and annotations on
already adopted objects. It never deletes or recreates a running object, so rollback never needs a
recreate.

### Render parity

Until a single renderer exists, the Terraform root and the lifecycle agent implement one workload
template contract. A focused test feeds the same input matrix to both renderers and compares the
planned Terraform values with the agent output. The matrix covers product profiles, add-ons, the
identity bridge, and executor scale targets. The comparison reuses the deployment CLI's existing
rules that drop Kubernetes server defaults and normalize secret-provider bindings. It also checks
the protected CronJob template digests, and that the selectors of the infrastructure agent's
external Services match the pod labels that the agent renders. Any difference fails the test.

On the Hub path, the one-shot Job execution that runs catalog review and the initial inventory
derives its protected CronJob template digests from the agent's render receipt instead of from
Terraform input.

### Decisions on earlier open questions

The Hub-managed lifecycle owner decided these points on 2026-10-07.

- **Migration identity:** The schema-expand Job runs under a dedicated migration ServiceAccount and
  managed identity that no workload shares. In the MVP, that identity reads the same Key Vault
  database secret that the managed host's migration step uses today. That secret holds the server
  administrator login, because migrations create service roles and backfill data. A later change
  replaces it with a dedicated migration database role that has only the privileges migrations
  need, after object ownership moves from the administrator to that role.
- **One renderer:** The Terraform root and the agent renderer both stay, behind the render parity
  check, until the MVP is validated. After that, the Terraform workloads root applies the
  agent-rendered manifests, so every installation path uses one renderer and the parity check
  retires.

### Open questions

- Which component runs the post-deployment steps that the managed host runs today after the
  application stage: Trial activation, the initial inventory, and catalog review.
- How the infrastructure agent keeps running when the execution host uses the optional daily
  auto-shutdown (`runner_auto_shutdown_time`).
- Which agent owns the in-cluster PostgreSQL namespace when an installation selects the
  `postgres-aks` database placement.

## Example installations

| Setting | Customer A | Customer B | Customer C |
|---------|------------|------------|------------|
| Hub | Online or offline Target Hub in Korea Central | Central Hub cell in East US | Central Hub cell or Target Hub |
| Channel | `RELEASE`, or a custom channel with manual promotion | `RELEASE_CANDIDATE` | `RELEASE` with range `>=1.4.0 <1.5.0` |
| Windows | Weekly downtime window and nightly no-downtime window | Daily windows | As agreed |
| Model | Regional Provisioned PTU on approved endpoints | Standard pay-as-you-go | Self-hosted model reachable from Azure through API Management |
| Governance | Policy holds every state change for approval | Single-operator production profile with operator-promoted actions and standing authorization | Per-execution approval |

[Lifecycle Configuration](lifecycle-configuration.md#examples) shows the configuration for these
installations. Customer C's on-premises runtime and local model need separate approval and an ADR.

## Hub data model

| Table | Key | Purpose | Time fields | Mutability |
|-------|-----|---------|-------------|------------|
| `installation` | `installation_id` | Enrollment, Hub placement, channel, version range, windows | `enrolled_at`, `recorded_at` | Revisioned |
| `entity` | `installation_id`, `entity_id` | Kind, managed flag, settings revision | `effective_from`, `recorded_at` | Revisioned |
| `entity_reported_state` | `installation_id`, `entity_id`, `observed_at` | Version, digests, health, agent sub-state | `observed_at`, `recorded_at` | Append-only |
| `lifecycle_plan` | `plan_id` | Type, target Release, configuration revision, envelope, expiry | `created_at`, `issued_at`, `expires_at` | Status changes in `lifecycle_plan_event` |
| `plan_evaluation` | `evaluation_id` | One recompute: outcome, target Release, and the issued Plan if any | `evaluated_at` | Append-only |
| `plan_constraint_result` | `evaluation_id`, candidate Release, `constraint` | Result and reason | `evaluated_at` | Append-only |
| `plan_execution_report` | `plan_id`, `attempt` | Exact plan digest, sanitized summary, outcome | `reported_at` | Append-only |
| `lifecycle_command` | `command_id` | Suppression, lowering, or break-glass command with scope and actor | `starts_at`, `expires_at`, `recorded_at` | Revocable |
| `hub_audit` | `sequence` | Hash-chained record of every Hub change | `recorded_at` | Append-only |

A recompute that waits or finds no eligible Release issues no Plan, so constraint results belong to
the evaluation rather than to a Plan.

Release tables belong to [Lifecycle Releases and Channels](lifecycle-releases-and-channels.md), and
configuration tables belong to [Lifecycle Configuration](lifecycle-configuration.md).

## Honest limits

- Only the Lifecycle Hub's Plan computation, storage, and agent API run today, in observation mode
  (shadow mode) on loopback ([Lifecycle Hub](../../../lifecycle/hub/README.md)). Everything else in
  this document is design only.
- Workload rendering outside Terraform is designed in
  [Workload rendering migration](#workload-rendering-migration). The agent renderer, the render
  parity test, and the ownership handoff aren't implemented.
- The dual-slot self-upgrade of agents and Target Hubs needs its own failure analysis.
- How entitlement reaches a Hub-managed installation is an open question. A Hub upgrade never
  renews a Trial.
- Offline installations receive recalls only when an operator imports the next bundle.
- The Hub path supports AKS only, and on-premises runtimes are out of scope.

## Related docs

| To learn about | Read |
|----------------|------|
| Decision record | [ADR-0003](../architecture/decisions/0003-hub-managed-lifecycle-and-operator-governance.md) |
| Configuration layers, packages, and secrets | [Lifecycle Configuration](lifecycle-configuration.md) |
| Releases, channels, bundles, and recall | [Lifecycle Releases and Channels](lifecycle-releases-and-channels.md) |
| Approval profiles and policy administration | [Operator Governance Profiles](../decisioning/operator-governance-profiles.md) |
| Existing installation paths | [One-Command Source Deployment](source-deployment.md), [Disconnected Deployment](disconnected-deployment.md) |
| Exact-plan apply and recovery | [Installable Deployment CLI](installable-deployment-cli.md) |
| Delivery status and remaining work | [Implementation ledger](../../roadmap-implementation/deployment/hub-managed-lifecycle.md) |
