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

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Private Azure networking and VNet deploy host | implemented | `infra/`, `infra/bootstrap/`, `.github/workflows/deploy-dev.yml`, and focused infrastructure workflow tests | Private endpoints, DNS, the durable deploy host, protected plans, and exact apply are implemented independently of the offline CLI path. |
| Internal mirror and pinned-input controls | implemented | `infra/modules/preflight-toggles/` and `scripts/quality/ci/check-ci-contracts.py` | The repository exposes mirror inputs and rejects mutable or registry-bound base-image references. |
| Offline kit staging and drill harness | in-progress | `scripts/deployment/release/stage-offline-kit.sh`, `build-offline-kit.py`, and `airgap-drill.sh` | The scripts are present, but the builder imports the absent `fdai.deployment_cli.offline_kit` module and the drill cannot complete. |
| Disconnected inspection, bundle verification, and planning commands | not-started | The target command sequence in this document | No current package registers `fdaictl`; the inspect, bundle, provision-plan, and license command paths are unavailable. |
| Pinned offline trust root and release integration | not-started | `docs/runbooks/offline-trust-ceremony.md` | No pinned root ships in a CLI wheel and kit staging is not a passing release workflow. |
| Full-air-gap cloud operation | not-applicable | The full-air-gap boundary in this document | The deterministic core can run from static inputs, but live Azure evidence and cloud mutation are intentionally outside this profile. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-14 | in-progress | Adopted the implementation ledger; earlier provenance was not reconstructed. Corrected the prior end-to-end support claim after the deployment CLI package was removed. | current change; infrastructure, release-script, package-metadata, and focused workflow evidence listed in the scope table | Restore the dedicated offline verifier and CLI, establish the trust root, and pass the air-gap drill. |

### Remaining work

- [ ] Implement and package offline-kit and deployment-bundle verification behind the dedicated CLI boundary, with tamper, symlink, extra-file, missing-file, digest, size, and compatibility tests.
- [ ] Establish and package the offline trust root through the governed ceremony, then prove inspection distinguishes verified, review, and rejected kits without a network call.
- [ ] Make `stage-offline-kit.sh` and `airgap-drill.sh` pass from a clean release checkout inside a namespace with no route or DNS.
- [ ] Prove the manual exact-plan approval and apply path from a private deploy host, including rollback, teardown, and post-provision verification receipts.

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

The private Azure infrastructure path is implemented. The offline distribution and CLI path remains
in progress, as recorded in the ledger above.

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

That layer creates one outbound path by default - a NAT gateway with a static public IP - because a
GitHub-registered runner has to reach GitHub, the management plane, and the identity plane. A closed
network sets `enable_public_egress = false`: no public address is created at all, the host is a
jumpbox rather than a registered runner, and the tenant supplies its own approved route to the
management and identity planes.

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

The release scripts are intended to stage the kit on a connected host with
`scripts/deployment/release/stage-offline-kit.sh`, which collects the `fdai` wheel and every
transitive wheel, the signed deployment bundle, the pinned Terraform binary and provider mirror,
the policy engine binary, and the software bill of materials, then signs the result with
`scripts/deployment/release/build-offline-kit.py`. The manifest is minted from the staged tree, so
it cannot attest to content the verifier would reject, and the release private key never enters the
kit.

The target disconnected command, `fdaictl provision inspect`, verifies the signature before parsing the
manifest, binds the exact CLI and platform version, rejects symlinks and extra files, and streams
every digest. Presence is never trust: an unverified kit stays `candidate`, and rejected content is
`incomplete`.

The kit's CycloneDX document names every file it carries with a SHA-256, which is the half of the
handover that carries the outside supply chain: the Terraform binary, the policy engine binary, and
every mirrored provider with its exact version. A signature proves the document was not altered but
cannot notice a document that describes nothing, so the drill asserts that the SBOM accounts for
every file the manifest lists.

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
installed, and the entry point is the control plane, not a provisioner. The `fdaictl` console
script does not currently ship in any service image or dedicated CLI wheel. The target command
sequence below therefore describes the intended handover, not an available image capability.

A closed-network handover is therefore **two artifacts**: the runtime image, and the signed offline
kit that carries the wheel, the deployment bundle with `infra/`, the pinned Terraform binary and
provider mirror, the policy engine, and the bill of materials.

| # | Step | Tool | State |
|---|------|------|-------|
| 1 | Verify the kit | `fdaictl provision inspect` | not started; dedicated CLI and verifier are absent |
| 2 | Verify the deployment bundle | `fdaictl bundle verify` | not started as a packaged command |
| 3 | Load the runtime image and push it to the tenant registry | container tooling on the VNet host | operator step |
| 4 | Stand up the ops hub: state account, VNet, and the deploy host | `infra/bootstrap` | implemented; run once per tenant |
| 5 | Plan the app layer from the bundle | `fdaictl provision plan` | not started; target behavior |
| 6 | Analyze the plan before applying it | standalone preflight script today; target `fdaictl deploy preflight --terraform-plan` | core and runner path implemented; CLI facade absent |
| 7 | Apply | Terraform on the deploy host | operator-driven |
| 8 | Migrate the state store | a one-off job running the same image | implemented |
| 9 | Inject and check the license token | secret path plus target `fdaictl license inspect` | license contract implemented; CLI command absent ([capability-licensing.md](../fork-and-sequencing/capability-licensing.md)) |
| 10 | Start the control plane | the image entry point | implemented |

Step five is a target replacement for this checklist: unpack the kit, find the Terraform binary, hand-write a provider
mirror configuration, and remember to close the public-registry fallback. `fdaictl provision plan`
owns it instead. It resolves the Terraform binary and the mirror from the *signed manifest*, so a
tree added beside the kit cannot decide what executes; it generates a CLI configuration whose
`direct` block excludes every provider, so a missing mirror entry fails the plan rather than
reaching the public registry; it passes only credential-shaped environment variables through; and
it emits the binary plan, its SHA-256 digest, and the plan JSON that step six consumes.

Executing content from a kit demands stronger evidence than reporting on one. `provision inspect`
still has no trust-root override and still reports `candidate` for an unverified kit, because an
operator can weigh that judgement. `provision plan` cannot: it verifies the kit against a supplied
release root and refuses to plan when that fails. Once the root ships pinned in the wheel,
`--release-root` becomes an override that planning accepts and inspection still does not.

One consequence is worth stating before an operator plans a handover. `fdaictl deploy plan` and
`deploy apply` submit work to a GitHub workflow, so a tenant without that reachability uses the
`manual` transport: `provision plan` for step five, and Terraform on the deploy host for step
seven, whose exact-plan approval binding remains target behavior.

## Rehearsing the whole path with no network

`scripts/deployment/release/airgap-drill.sh` defines the two-phase handover rehearsal a customer
should receive. It does not currently complete because the deployment CLI verifier package is
absent. The stage phase is designed to run the
real `stage-offline-kit.sh` with throwaway keys, so a green drill exercises the release path itself
rather than a second copy of it. The verify phase re-runs every disconnected step inside a network
namespace that has no route and no name resolution.

```bash
bash scripts/deployment/release/airgap-drill.sh
```

The verify phase asserts, in order: the namespace really has no egress or DNS; the signed kit
verifies; the signed bundle verifies; `terraform init` resolves every provider from the kit mirror
alone; `terraform validate` accepts the bundle; `terraform test` evaluates the plan graph through
mocked providers; the same `init` **fails** without the mirror; `fdaictl license inspect` resolves
entitlement; and `fdaictl provision plan` - the command an operator actually runs - reaches the same
place on its own, with deployment input as the only thing still missing. Step seven is the control
that matters: without it, a cached plugin directory could pass the drill while proving nothing.
Step nine requires that an unresolved provider, or any reach toward the public registry, fails the
drill, so a broken mirror pin cannot pass as a missing variable.

The drill is repeatable. `--skip-stage` re-verifies against an existing kit, and the bundle tree is
unpacked on every run because Terraform writes into it - a drill that only passes once is a
demonstration, not a regression check.

## What the verifiers refuse

Both the kit verifier and the bundle verifier read input that is not trusted yet, so both bound
what they read **before** checking a signature rather than after, refuse metadata reached through a
symlink, and fail on a directory they cannot list. That last one matters more than it looks: path
globbing silently returns what it managed to see, which would let a signer attest to a tree missing
whatever sat under an unreadable directory, and let a verifier accept a truncated tree as complete.

The two verifiers are deliberately symmetric. They guard the same handover, so a gap in either one
is a gap in both.

## The tooling does not reach out

The target `fdaictl provision inspect` command decides connectivity by opening TLS connections to three public hosts.
With `--connectivity offline` it skips that entirely, because the operator has already answered the
question. On a closed network an unnecessary probe is three outbound attempts to explain to a
security team, three entries in an egress log, and - where DNS accepts the query but never answers -
a long stall in what was supposed to be a quick local inspection. `auto` still probes, because it
genuinely has not been told.

The drill stops at plan evaluation on purpose. A real `terraform apply` still needs the tenant's
approved private path to the management plane, and pretending to simulate that locally would be the
kind of claim this design is built to avoid. Its signing keys are throwaway keys under the work
directory and never become repository material.

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
| The dedicated deployment CLI package is absent | `fdaictl` inspection, bundle verification, planning, status, apply, and license commands cannot run | [Installable Deployment CLI](installable-deployment-cli.md) |
| The trust-root ceremony has not run, so no pinned public root ships in the wheel | inspection can never report a verified offline kit; it stays `candidate` or `review` | [offline-trust-ceremony.md](../../runbooks/offline-trust-ceremony.md) |
| Kit staging is incomplete | `stage-offline-kit.sh` and the signing script exist, but the missing verifier module blocks a complete staged kit | [provisioning-execution-profiles.md](provisioning-execution-profiles.md) |
| Bootstrap apply orchestration and teardown remain target behavior | the operator drives the exact-plan approval and apply by hand | [installable-deployment-cli.md](installable-deployment-cli.md) |
| No self-hosted model adapter | a site with no cloud reachability has no adaptive path at all | [tech-stack.md](../architecture/tech-stack.md) |

Framework-surface verification is already network-independent. Offline-kit verification targets
the same property, but it remains incomplete until the dedicated verifier and pinned root ship.

## Related docs

| To learn about | Read |
|----------------|------|
| The private-networking Terraform layer and hardening knobs | [deploy-and-onboard.md](deploy-and-onboard.md) |
| Offline kit contracts, build, and verification | [provisioning-execution-profiles.md](provisioning-execution-profiles.md) |
| The CLI facade, signed bundles, and exact-plan apply | [installable-deployment-cli.md](installable-deployment-cli.md) |
| Establishing and rotating the offline trust root | [offline-trust-ceremony.md](../../runbooks/offline-trust-ceremony.md) |
| Recovering from a rejected kit or a blocked plan | [deployment-recovery.md](../../runbooks/deployment-recovery.md) |
