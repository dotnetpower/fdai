---
title: Disconnected Deployment
---
# Disconnected Deployment

This document is the single owner for deploying FDAI into a network that blocks public internet
egress - a regulated financial tenant, a sovereign enclave, or a fully air-gapped site. It states
what the repository already supports, what an operator must supply, and which gaps still block a
fully disconnected install.

> **Scope:** Azure is the implemented target. This document does not restate the private-networking
> Terraform layer ([deploy-and-onboard.md](deploy-and-onboard.md)), the artifact contracts
> ([installable-deployment-cli.md](installable-deployment-cli.md)), or the profile selection rules
> ([provisioning-execution-profiles.md](provisioning-execution-profiles.md)). It sequences them.

## Design at a glance

"Disconnected" is not one setting. Two independent properties decide how much of this document
applies, and a tenant can sit anywhere in the resulting grid.

| Property | Values | What it decides |
|----------|--------|-----------------|
| **Azure reachability** | private endpoints, or none at all | whether the control plane can call the management plane, the secret store, the event bus, and the state store |
| **Public artifact egress** | allow-listed, mirrored, or none | whether the public package index, the Terraform registry, and public container registries are reachable |

Most regulated tenants land on **private Azure reachability with no public artifact egress**: the
control plane works normally over private endpoints, while every build and install input must come
from an internal mirror or signed media. A true air gap - no Azure reachability either - is a
narrower profile covered under [Full air gap](#full-air-gap).

## Private Azure, no public egress

This is the profile the repository supports end to end.

### 1. Provision every service privately

Set `enable_private_networking = true`. The deploy provisions a virtual network, private endpoints,
and linked private DNS for the secret store, both event-bus shards, the state store, blob and data
lake storage, and the model endpoint. Add `enable_private_postgres = true` for the delegated-subnet
state-store mode.

Set `acr_sku = "Premium"` as well. Private link is a Premium-only registry capability, so a Basic or
Standard registry deliberately stays public: closing it without a private path would break every
image pull. With Premium, the registry loses public network access and receives its own private
endpoint.

The core engine and executor have no public inbound endpoint in any profile. Ingress is the event
bus, and egress is default-deny with an allow list
([security-and-identity.md](../architecture/security-and-identity.md)).

### 2. Deploy from inside the network

A private-only secret store and a private state account are unreachable from an operator
workstation. `terraform apply` MUST run from a host with network line-of-sight to those endpoints -
a self-hosted runner or a jumpbox inside the virtual network. The `infra/bootstrap` layer stands up
that durable hub, and `scripts/deployment/azure/check-runner-egress.py` records which allow-listed
hosts the runner can actually reach, so a plan carries evidence of its own network position instead
of an assumption.

Build and push the runtime image from the same host once the registry is private.

### 3. Point every build input at an internal mirror

| Input | Mechanism |
|-------|-----------|
| Base container images | `--build-arg BASE_IMAGE_REGISTRY=<mirror>`. The sha256 digests stay pinned in the `Dockerfile`, so a mirror changes where bytes come from, never which bytes are accepted |
| Python packages | `infra/modules/preflight-toggles/python_index_url` emits the package-index configuration for an internal feed |
| Registry pulls at deploy time | `infra/modules/preflight-toggles/registry_source` switches from the public default to an internal registry mirror |
| Terraform providers | the offline kit ships a pinned provider mirror, and offline mode blocks fallback to the public registry |

`scripts/quality/ci/check-ci-contracts.py` fails the build when a base image loses its digest pin or
hardcodes a registry host, so the mirror seam cannot decay into an unpinned pull.

### 4. Deliver the CLI and bundle as a signed offline kit

Release engineering stages the kit on a connected host - the `fdai` wheel and every transitive
wheel, the signed deployment bundle, the pinned Terraform binary and provider mirror, the policy
engine binary, and the software bill of materials - then signs it with
`scripts/deployment/release/build-offline-kit.py`. The manifest is minted from the staged tree, so
it cannot attest to content the verifier would reject, and the release private key never enters the
kit.

On the disconnected side, `fdaictl provision inspect` verifies the signature before parsing the
manifest, binds the exact CLI and platform version, rejects symlinks and extra files, and streams
every digest. Presence is never trust: an unverified kit stays `candidate`, and rejected content is
`incomplete`.

### 5. Keep the rule catalog fresh without public egress

The signed deployment bundle already carries the rule-catalog schema, the deployment profiles, and
the risk classification, so a catalog refresh is delivered the same way the code is: as a new signed
bundle. When a tenant wants to run the collection pipeline itself, the fetchers accept a local
directory or a git remote, so an internal mirror of the upstream sources is a supported input.
Public source URLs are not required at run time
([rule-catalog-collection.md](../rules-and-detection/rule-catalog-collection.md)).

### 6. Expect degraded evidence, not fabricated evidence

Restricted egress changes what the control plane can observe, and every fallback is ordered and
fails closed:

- **Inventory**: the resource-graph query path first, then a validated private-link management
  route, sharded management list operations, an authoritative scoped inventory, activity-log
  continuity, and finally a signed declarative snapshot. A failed path keeps the last complete graph
  and marks it stale; it never publishes an empty graph.
- **Identity**: override `FDAI_ENTRA_JWKS_URI` when the tenant discovery endpoint is unreachable
  ([user-rbac-and-identity.md](../interfaces/user-rbac-and-identity.md)).
- **Adaptive decisions**: when the model path is unavailable, adaptive capabilities report
  unavailable and the affected work stays deterministic-only. Autonomy degrades; it never fails open.

## Provisioning an image-delivered distribution

A distribution that hands over an image still has to create the Azure inventory first, and the
runtime image cannot do it. `infra/` is excluded from the build context, no Terraform binary is
installed, and the entry point is the control plane, not a provisioner. The `fdaictl` console script
does exist inside the image because it ships with the `fdai` package, which makes the gap easy to
misread: the command is present, the infrastructure source and the Terraform binary are not.

A closed-network handover is therefore **two artifacts**: the runtime image, and the signed offline
kit that carries the wheel, the deployment bundle with `infra/`, the pinned Terraform binary and
provider mirror, the policy engine, and the bill of materials.

| # | Step | Tool | State |
|---|------|------|-------|
| 1 | Verify the kit | `fdaictl provision inspect` | implemented; reports `candidate` until the trust root ships |
| 2 | Verify the deployment bundle | `fdaictl bundle verify` | implemented |
| 3 | Load the runtime image and push it to the tenant registry | container tooling on the VNet host | operator step |
| 4 | Stand up the ops hub: state account, VNet, and the deploy host | `infra/bootstrap` | implemented; run once per tenant |
| 5 | Plan the app layer from the bundle | the kit's pinned Terraform against the bundle `infra/` | operator-driven; the CLI does not orchestrate it |
| 6 | Analyze the plan before applying it | `fdaictl deploy preflight --terraform-plan` | implemented and network-free |
| 7 | Apply | Terraform on the deploy host | operator-driven |
| 8 | Migrate the state store | a one-off job running the same image | implemented |
| 9 | Inject and check the license token | secret path plus `fdaictl license inspect` | implemented ([capability-licensing.md](../fork-and-sequencing/capability-licensing.md)) |
| 10 | Start the control plane | the image entry point | implemented |

Two consequences are worth stating before an operator plans a handover. `fdaictl deploy plan` and
`deploy apply` submit work to a GitHub workflow, so a tenant without that reachability uses the
`manual` transport and runs Terraform on the deploy host directly. And steps 5 and 7 are the
operator's, not the CLI's: bootstrap plan and apply orchestration remain target behavior, so the
sequence above is a checklist a person follows rather than one command.

## Full air gap

A site with no Azure reachability at all can still run the deterministic core. The policy engine is
a static binary inside the image, the rule catalog and ontology are files, and the declarative
inventory adapter serves a hand-authored resource graph through the same `Inventory` contract the
cloud adapter satisfies. What that site does not get is live cloud evidence, so autonomous action on
cloud resources is out of scope by construction.

This profile is **reference only** until the trust root below is established, and a sovereign
deployment additionally requires its own regulatory and residency review
([architecture-review-board.md](../architecture/architecture-review-board.md)).

## What still blocks a fully disconnected install

| Gap | Effect today | Owning document |
|-----|--------------|-----------------|
| The trust-root ceremony has not run, so no pinned public root ships in the wheel | inspection can never report a verified offline kit; it stays `candidate` or `review` | [offline-trust-ceremony.md](../../runbooks/offline-trust-ceremony.md) |
| Kit staging is a manual release task | no automated job collects the wheels, bundle, Terraform binary, provider mirror, policy engine, and bill of materials | [provisioning-execution-profiles.md](provisioning-execution-profiles.md) |
| Bootstrap plan and apply orchestration and teardown remain target behavior | the operator drives the sequence by hand | [installable-deployment-cli.md](installable-deployment-cli.md) |
| No self-hosted model adapter | a site with no cloud reachability has no adaptive path at all | [tech-stack.md](../architecture/tech-stack.md) |

Signing and verification are already independent of the network. The framework-surface manifest and
the offline kit both verify with a committed public key, with no revocation lookup and no
certificate chain.

## Related docs

| To learn about | Read |
|----------------|------|
| The private-networking Terraform layer and hardening knobs | [deploy-and-onboard.md](deploy-and-onboard.md) |
| Offline kit contracts, build, and verification | [provisioning-execution-profiles.md](provisioning-execution-profiles.md) |
| The CLI facade, signed bundles, and exact-plan apply | [installable-deployment-cli.md](installable-deployment-cli.md) |
| Establishing and rotating the offline trust root | [offline-trust-ceremony.md](../../runbooks/offline-trust-ceremony.md) |
| Recovering from a rejected kit or a blocked plan | [deployment-recovery.md](../../runbooks/deployment-recovery.md) |
