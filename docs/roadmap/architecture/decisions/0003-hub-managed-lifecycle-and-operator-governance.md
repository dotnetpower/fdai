---
title: ADR-0003 Hub-Managed Lifecycle and Operator Governance
---
# ADR-0003: Hub-Managed Lifecycle and Operator Governance

This record adds a third installation path. In this path, a Lifecycle Hub keeps each FDAI
installation on its subscribed release channel and on the configuration that its customer
approved. The record also adapts approval, promotion, and policy administration to installations
that one person usually operates. It amends the [FDAI Constitution](../fdai-constitution.md) and
[ADR-0002](0002-independent-runtime-axes.md).

## Status

**Accepted:** 2026-10-02. This is design authority only. No part of the decision is implemented.
Each owner document links to the ledger that tracks delivery.

## Context

FDAI installs into each customer's own Azure environment. Customers differ in region, network
isolation, model endpoints, capacity type, approval requirements, admission policy, integrations,
and the release they accept. Before this decision, FDAI had two installation paths, the one-command
source deployment and the signed offline package. Neither path keeps a fleet of installations
current. FDAI had no release subscription, no recorded desired configuration per installation, no
reported lifecycle state, and no way to recall a defective release.

Palantir Apollo solves a similar problem with a hub-and-spoke model. A Hub combines a product
catalog, release channels, environment settings, and reported state, and its orchestration engine
issues Plans only when every constraint is satisfied. Agents inside each spoke environment execute
those Plans and report state back
([Apollo overview](https://www.palantir.com/docs/apollo/core/overview),
[Plans and Constraints](https://www.palantir.com/docs/apollo/core/plans-and-constraints)).
Apollo has no single target state per environment. A product is defined by a release channel and
constraints rather than a fixed version.

These forces shaped the decision:

- Constitution Article 1 allowed only two installation paths and treated any added installation
  gate as a defect.
- The pantheon is fixed at 15 agents. Lifecycle work can't add or rebind an agent.
- ADR-0002 keeps runtime, environment, product surface, lifecycle, identity, authorization, and
  distribution as independent axes. Configuration can't grant authority.
- The productization plan doesn't adopt one shared gateway for mutually untrusted tenants.
- Regulated customers require in-country processing, approved endpoints only, and no central
  access to their data. Some sites have no internet access at all.
- Most installations have one operator. The two-person rule for standing authorization made
  emergency mitigation unusable for them.
- Operators need to change approval and admission policy without waiting for a release.

## Decision

### Lifecycle

| # | Decision | Owner document |
|---|----------|----------------|
| L1 | Add the Hub-managed lifecycle as the third installation path. The source deployment and the offline package stay unchanged. | [Hub-Managed Lifecycle](../../deployment/hub-managed-lifecycle.md) |
| L2 | Place the Hub per customer: a central Hub cell for connected customers, an online Target Hub inside the boundary for regulated customers, or an offline Target Hub that imports signed bundles. All three run the same Hub software. | Hub-Managed Lifecycle |
| L3 | The Hub computes Lifecycle Plans only: target Release, configuration revision, constraint results, and a narrowing effect envelope. The installation derives the maximum envelope itself, renders and applies the exact change, and refuses anything outside it. The Hub holds no Azure credential, secret value, or operational data. Installations poll the Hub over an outbound connection. | Hub-Managed Lifecycle |
| L4 | Two installation agents carry the work. A lifecycle agent inside the cluster is installed first, runs independently of Core, applies workloads, and reports state. An infrastructure agent on the execution host applies Azure infrastructure through exact Terraform plans. Neither is a pantheon agent. The pantheon only observes FDAI-owned resources. | Hub-Managed Lifecycle |
| L5 | Every installation applies the newest eligible Release of its channel automatically inside its maintenance windows. A configuration change needs an approved change request. Deleting or replacing an existing Azure resource needs explicit operator confirmation. | [Lifecycle Releases and Channels](../../deployment/lifecycle-releases-and-channels.md) |
| L6 | A Release is a signed set of prebuilt image digests and metadata. Connected installations mirror images into a registry inside their boundary. The offline package stays a first-installation package, and a new signed upgrade bundle carries later Releases. Source builds remain Trial and development builds and count as unverified under the Hub. | Lifecycle Releases and Channels |
| L7 | Release channels use Apollo's default names `DEV`, `RELEASE_CANDIDATE`, and `RELEASE`, and custom channels are allowed. The implemented `development`, `beta`, and `stable` names migrate to them. | Lifecycle Releases and Channels |
| L8 | Configuration layers follow Apollo: Release defaults, then Environment Config, then Entity override blocks per Release version range. A Release without a matching override block isn't deployed. Authority values are never configuration. | [Lifecycle Configuration](../../deployment/lifecycle-configuration.md) |
| L9 | A customer-owned Git repository is the source of desired configuration, and a reviewed merge is the change request. Each merged revision becomes one signed configuration package that the Hub imports. The package names its predecessor so that gaps and reordering are detected. | Lifecycle Configuration |
| L10 | Suppression windows and commands that lower authority take effect immediately and always expire. Break-glass commands apply an emergency change immediately and are reconciled to the approved Git revision when they expire. No override raises authority. | Hub-Managed Lifecycle |
| L11 | Entities are deployment units and Azure platform resources. Agents appear as reported sub-state of the Core Entity. Customer-owned resources such as an existing API Management instance, private DNS zone, or ITSM endpoint are unmanaged Entities that FDAI only observes. | Hub-Managed Lifecycle |
| L12 | Hub records live in a Hub PostgreSQL database for each cell or Target Hub. Installation receipts stay append-only in the installation's Foundation storage. The operating ontology doesn't change. | Hub-Managed Lifecycle |

### Operator governance

| # | Decision | Owner document |
|---|----------|----------------|
| G1 | Add a single-operator production profile. When approval policy selects it, one named operator may satisfy every requester, approver, reviewer, and quorum requirement in that installation. Approver and executor identities stay distinct. | [Operator Governance Profiles](../../decisioning/operator-governance-profiles.md) |
| G2 | An authorized operator may promote an ActionType or Workflow before its promotion gate passes. The promotion is recorded as an attributed operator override. Regression demotion and vendor capability recall take precedence. | Operator Governance Profiles |
| G3 | Authorized operators edit approval policy and admission (OPA/Rego) policy directly in FDAI Console through a policy-administration add-on. Each edit becomes an immutable, digest-pinned, audited revision for later decisions. | Operator Governance Profiles |
| G4 | A regulated installation may run T2 with two distinct models from the same publisher when its residency or endpoint rules prevent a mixed-publisher pair. | [Model Capability Lifecycle](../model-capability-lifecycle.md) |
| G5 | For an on-premises customer, design covers only a version pin and a self-hosted model reachable from Azure. On-premises runtime and local models need separate approval. | Hub-Managed Lifecycle |

### Defaults adopted without a separate question

| # | Default |
|---|---------|
| A1 | A Release declares the database schema range it supports. The Hub checks that range as a constraint. Migrations stay expand/contract and forward-only. |
| A2 | The existing rule for deleting or replacing an Azure resource applies to the Hub path unchanged. Other disruptive updates wait for a downtime maintenance window. |
| A3 | The Hub path supports the AKS runtime only. Container Apps installations keep their existing paths. |
| A4 | An existing installation enrolls first as unmanaged Entities and becomes managed after review. The first Hub upgrade replaces source-built images with signed images. |
| A5 | Channel migration maps `development` to `DEV`, `beta` to `RELEASE_CANDIDATE`, and `stable` to `RELEASE`. Promotion pipelines support labels, soak time, canary health, and recall. |
| A6 | A Console policy revision requires fresh authentication. Mimir validates it, signs it with an installation key, and activates it. Core applies constitutional hard constraints after operator policy, so no revision raises an outcome past them or past a Release maximum. In the multi-operator profile, a relaxing revision needs the profile's governance quorum. |
| A7 | A recalled capability can't be promoted again until a later Release lifts the recall. An operator override never counts as promotion evidence for another installation. |
| A8 | A same-publisher T2 pair needs two different model families or versions on separate deployments. Every T2 decision records which diversity policy applied. |
| A9 | Data residency is a processing-scope constraint on each model binding. A binding that violates it is rejected. |
| A10 | Hub approvers authenticate with the customer's Microsoft Entra ID tenant. |
| A11 | The lifecycle agent has Kubernetes rights in the FDAI namespaces only. The Azure write identity stays on the execution host. |
| A12 | A central Hub cell never enters the operations loop. |
| A13 | A version pin is a version-range subscription. |
| A14 | Customer identifiers and endpoints are sealed to an installation key inside the configuration package. The Hub stores only ciphertext and digests. |
| A15 | Releases carry the vendor release signature and configuration packages carry the customer configuration signature. Installation agents verify both before they act. |
| A16 | Installation agents derive the maximum effect envelope locally from signed inputs, ownership evidence, and local hard policy. A Hub Plan can only narrow it. |
| A17 | Each Plan names its audience, Hub key epoch, source-state digest, sequence, and fencing generation, and agents reject replays. Installations prove key possession at enrollment, and keys rotate and revoke through signed key records. |
| A18 | Catalog metadata follows TUF roles with expiring timestamps, increasing versions, and recall sequence numbers. Expired metadata allows only recall roll-off and returns operator-override promotions to shadow mode. |
| A19 | A local lifecycle authorization receipt binds each exact plan digest to its Plan, Release, configuration revision, and window. It replaces the operator's invocation in the existing exact-plan stages. |
| A20 | A Plan runs as fenced phases, each owned by one agent. Agents and Target Hubs upgrade themselves through two slots. |
| A21 | Signed Foundation receipts and Terraform state identity prove FDAI ownership. The `fdai:managed=true` tag is only a discovery hint. |
| A22 | A break-glass command can bypass only maintenance windows, suppression windows, and version ranges. |
| A23 | Maintenance windows use IANA time zones with a pinned time-zone database, and a Plan starts only when its maximum duration fits. |
| A24 | A central cell receives coarse component health bands, never event content or resource identities. |
| A25 | An operator override promotion is a `governance` ActionType that travels the typed pipeline. Mimir is the single writer of policy revisions. |

## Alternatives considered

| Alternative | Reason not selected |
|-------------|---------------------|
| Keep two installation paths and add only a metadata layer | Can't upgrade, recall, or reconcile a fleet. The Owner selected a full third path. |
| Let a central Hub render exact plans with customer credentials, as an Apollo-style central engine could | Concentrates every customer's Azure write access in one place, and regulated customers prohibit it. |
| Require a Target Hub for every customer | Adds Hub operating cost for customers who accept a vendor-operated cell. |
| Add Deployment, Configuration, Drift, and Policy agents to the pantheon | The pantheon is fixed, and an agent that upgrades its own runtime creates a circular dependency. |
| Use a five-layer linear override (product, environment, policy, entity, runtime) | Couples ADR-0002 axes and lets configuration carry authority. |
| Make Hub storage the source of desired configuration | Customers prefer Git review and history. The Hub keeps an imported copy. |
| Build separate images or branches per customer | Creates product forks and breaks "build once, configure per environment." |
| Require approval for every Release upgrade | The Owner selected automatic upgrades. Channels, pins, maintenance windows, and suppression windows remain the control levers. |
| Keep the two-person rule for standing authorization | Single-operator installations could never use emergency mitigation. |
| Allow promotion only after the gate passes | Operators need direct control over their own installation. |
| Manage policy only through signed bundles in Git | Too slow and strict for routine policy changes. |
| Forbid same-publisher T2 pairs everywhere | A regulated installation could lose T2 entirely. |

## Consequences

**Positive:**

- One Release serves every customer, and customer differences stay in configuration, policy, and
  installation-bound bindings.
- Releases can be promoted, recalled, and reconciled across connected and offline installations.
- Regulated customers keep secrets, credentials, identifiers, and operational data inside their
  boundary.
- Single-operator installations can use emergency mitigation and manage their own policy.

**Negative and risks:**

- **Autonomy widens.** Operator override promotion, single-operator approval, relaxed Console
  policy, and automatic upgrades can combine so that one person enables unattended execution of an
  unproven capability. The seven safeguards, A4 denial, the risk gate's upper bound, regression
  demotion, capability recall, the override marker, and the audit trail remain. They limit the
  effect but don't remove the risk.
- **A compromised Hub** can delay upgrades or withhold Plans. It can't widen the effect envelope,
  forge a Release or configuration package, replay a Plan, or obtain an Azure credential. Agents
  reject a version older than the newest one they applied unless a vendor-signed recall allows it,
  and expired catalog metadata returns operator-override promotions to shadow mode.
- **Automatic upgrades** reach regulated installations unless their channel, pin, or windows hold
  them back.
- **Same-publisher T2 pairs** reduce model independence and can share failure modes.
- **Offline installations** receive recalls only when an operator imports the next bundle.
- **Workload rendering moves** from the Terraform application stage to the lifecycle agent and
  needs a migration.
- The integrity manifest needs a new signature from the key holder because instruction files
  changed.

**Operational and migration:** The vendor operates the release catalog and central Hub cells.
Customers that choose a Target Hub operate it inside their boundary. Existing installations enroll
through the steps in [Hub-Managed Lifecycle](../../deployment/hub-managed-lifecycle.md).

## Constitutional amendment record

| Requirement | Change |
|-------------|--------|
| FDAI-CONST-001 | Adds the Hub-managed lifecycle as the third installation path, places its constraints inside that path, and keeps lifecycle components out of the operations loop. |
| FDAI-CONST-003 | Lets one human hold requester and approver roles under either single-operator profile. |
| FDAI-CONST-004 | Accepts attributed operator override in the promotion registry and operator-authored policy revisions inside hard bounds. |
| FDAI-CONST-007 | Keeps promotion evidence-gated by default and adds the attributed operator override. Recall and regression take precedence. |
| FDAI-CONST-008 | Adds the single-operator production profile and its standing-authorization approval rule. |
| FDAI-CONST-009 | Lets an operator override stand in for workflow simulation and regression evidence, never for structural validation. |

This amendment widens autonomy, so Article 10 requires Owner-level review. The Owner selected each
decision on 2026-10-02. The review record for the change that lands this ADR binds the exact diff
and its focused validation.

## Evidence

- Design: [Hub-Managed Lifecycle](../../deployment/hub-managed-lifecycle.md),
  [Lifecycle Configuration](../../deployment/lifecycle-configuration.md),
  [Lifecycle Releases and Channels](../../deployment/lifecycle-releases-and-channels.md), and
  [Operator Governance Profiles](../../decisioning/operator-governance-profiles.md).
- Critique: an independent design review on 2026-10-02 found gaps in envelope ownership, replay
  protection, catalog freshness, policy-store ownership, and phase coordination. Defaults A16 to
  A25 close them.
- Apollo sources (reviewed 2026-10-02):
  [Environments](https://www.palantir.com/docs/apollo/core/environments),
  [Entities](https://www.palantir.com/docs/apollo/core/entities),
  [Release Channels](https://www.palantir.com/docs/apollo/core/release-channels),
  [Config overrides](https://www.palantir.com/docs/apollo/managing-entities/set-config-overrides),
  [Export and Import](https://www.palantir.com/docs/apollo/export-import/overview).
- Model processing locations:
  [Deployment types for Microsoft Foundry Models](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/concepts/deployment-types).

## Next steps

| To learn about | Read |
|----------------|------|
| Lifecycle architecture, plans, and isolation | [Hub-Managed Lifecycle](../../deployment/hub-managed-lifecycle.md) |
| Configuration layers, packages, and secrets | [Lifecycle Configuration](../../deployment/lifecycle-configuration.md) |
| Releases, channels, bundles, and recall | [Lifecycle Releases and Channels](../../deployment/lifecycle-releases-and-channels.md) |
| Approval profiles, promotion, and policy administration | [Operator Governance Profiles](../../decisioning/operator-governance-profiles.md) |
| Independent runtime axes | [ADR-0002](0002-independent-runtime-axes.md) |
