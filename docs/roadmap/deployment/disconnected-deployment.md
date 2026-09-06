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
| Offline toolchain kit staging and drill harness | validated | [Deployment CLI implementation ledger](../../roadmap-implementation/deployment/installable-deployment-cli.md) | The dedicated CLI and shipped-wheel toolchain drill were restored. This is not a complete runtime deployment drill. |
| Disconnected bundle verification and planning commands | implemented | `packages/deployment-cli`; artifact and productization tests | The package registers `fdaictl` and verifies signed local inputs. Planning does not complete a new subscription. |
| Runtime release staging and local preparation | implemented | `runtime_release.py`, `runtime_stage.py`, `offline_prepare.py`; 251 focused tests; issue #461 | Local archives, source and bundle binding, private snapshots, and a non-ready preparation record pass focused checks. Azure installation remains open. |
| Offline VM bootstrap | implemented | `infra/bootstrap/`; 16 mocked Terraform plans | Explicit offline mode selects a prebuilt image without network cloud-init. Image production, attestation, access, and state handoff remain external prerequisites. |
| Installation-time Console bindings | implemented | `console/src/runtime-config.ts`; `console_config.py`; focused configuration tests and generic build | A generic build accepts public API/Entra bindings without rebuilding and disables authentication bypasses. Publication and authenticated access remain separate checks. |
| Runtime support wheel installation | implemented | `stage-runtime-wheelhouse.py`; `support_install.py`; focused tests and network-isolated real-wheel installation | Seven current distributions, including the shared GitHub auth library, install with hashes and package readback. No runtime service is started. |
| Initial database credential generation | implemented | `infra/initial_postgres_credential.tf`; eight mocked Terraform cases and one root-wiring regression | Explicit fresh-install generation retains a sensitive credential in private state. Supplied-password defaults remain unchanged; enabling it later is a reviewed rotation. |
| Pinned offline trust root and release integration | not-started | `docs/runbooks/offline-trust-ceremony.md` | No pinned root ships in a CLI wheel and kit staging is not a passing release workflow. |
| Full-air-gap cloud operation | not-applicable | The full-air-gap boundary in this document | The deterministic core can run from static inputs, but live Azure evidence and cloud mutation are intentionally outside this profile. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-14 | in-progress | Adopted the implementation ledger; earlier provenance was not reconstructed. Corrected the prior end-to-end support claim after the deployment CLI package was removed. | current change; infrastructure, release-script, package-metadata, and focused workflow evidence listed in the scope table | Restore the dedicated offline verifier and CLI, establish the trust root, and pass the air-gap drill. |
| 2026-09-06 | implemented | Corrected the obsolete missing-CLI claim and added runtime inventory staging, private offline preparation, and a guard against the public-artifact workflow. | `current change`; 251 focused tests, strict type checks, and an installed-wheel preparation drill with synthetic signed payloads in network and filesystem namespaces; issue #461 | Retain a complete eligible signed release and approved new-subscription Console and inventory receipts. |
| 2026-09-06 | implemented | Added prebuilt-image bootstrap and tenant-neutral Console builds with installation-time public configuration. | `current change`; mocked bootstrap plans, Python/Console configuration tests, Console typecheck and offline build; issue #461 | Connect the actual first-install executor, private image publication, initial discovery, and independent Console readback. |
| 2026-09-06 | implemented | Added locked runtime-wheel staging and authenticated offline support installation without changing active service environments. | `current change`; focused staging/installation tests and a network-isolated installation of real wheels with all five service entry modules importing successfully | Wire the support payload to approved migrations and application execution; retain actual Azure and Console receipts. |
| 2026-09-06 | implemented | Added opt-in initial PostgreSQL credential generation without a plaintext input or new password output. | `current change`; nine mocked Terraform cases cover default behavior, ambiguous inputs, sensitivity and the real state-store module binding | Retain approved private-host apply and persistent-state readback; do not treat mock evidence as cloud installation. |
| 2026-09-06 | implemented | Corrected the credential-test evidence after the CI-compatible plan harness moved root binding to a separate regression. | `current change`; eight mocked Terraform cases and one root-wiring regression passed. | Retain approved private-host apply and persistent-state readback; do not treat mock evidence as cloud installation. |

### Remaining work

- [x] Restore the dedicated CLI verifier and toolchain drill, as recorded in the [deployment CLI ledger](../../roadmap-implementation/deployment/installable-deployment-cli.md).
- [ ] Establish and package the offline trust root through the governed ceremony, then prove inspection distinguishes verified, review, and rejected kits without a network call.
- [ ] Stage actual runtime archives from a clean eligible release revision and pass a cache-free installed-wheel preparation drill with no route or DNS.
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

### Prepare a complete local artifact set

Use an independently trusted installation of `fdaictl` and verification keys delivered through
the approved trust process. Keys supplied with an untrusted kit cannot bootstrap trust in that kit.
The production root ceremony and release eligibility remain separate prerequisites.

```bash
fdaictl offline prepare \
  --offline-kit /media/fdai-kit \
  --release-root /trusted/release-root.pub \
  --bundle-public-key /trusted/bundle-key.pub \
  --profile /private/offline-profile.json \
  --source-commit <git-sha> \
  --work-dir /private/fdai-preparation \
  --output json
```

The profile selects `offline`, a target binding, and a positive monthly cost ceiling. The work
directory must not exist. Preparation makes no Azure, registry, model, or workflow calls and never
executes an archive. A toolchain-only kit is rejected.

The signed kit includes `runtime/release.json` with schema `fdai.runtime-release.v1`:

| Field | Required content |
|-------|------------------|
| `source_commit`, `platform_tag` | Exact source revision and supported Linux CPU platform |
| `deployment_bundle_sha256` | Digest of the matching signed deployment bundle archive |
| `services` | Exactly Core, Operator, ingestion API, document worker, and isolated Executor |
| Each service | Local archive, SBOM, provenance paths and their SHA-256 digests; OCI image digest |
| `console`, `deployment_support` | Local archives and SBOMs with SHA-256 digests |

Every payload path is under `runtime/`. Missing, extra, linked, duplicate, mismatched, and
oversized inputs are rejected. Existing kit limits remain 512 MiB per file and 8 GiB total;
larger release layouts need a reviewed format change, not disabled bounds. OCI identity,
provenance contents, archive layout, Console configuration, and migration completeness remain
release-producer assertions until their own independent validation. Hash checks alone do not
prove those properties.

Release engineering passes `--runtime-release <directory>` to `stage-offline-kit.sh` to include
this inventory and its real local payloads before the kit SBOM and signature are generated.
This option requires a clean checkout matching the inventory revision. It does not download or
build runtime images, generate their provenance, or replace the protected release gate.

Only a fully checked private snapshot is published at `prepared/`. Its `preparation.json` binds
the profile, target, cost ceiling, source, kit, runtime inventory, deployment bundle, and genesis
manifest. `state=prepared` and `subscription_ready=false` mean inputs are prepared, not installed.
Preparation does not estimate cost or produce an executable approved Terraform plan.

Offline profiles are blocked before authentication or dispatch through the existing `deploy`
and live `onboard guided` GitHub workflow path because that workflow still uses public artifacts.
The full installation still needs approved foundation creation, private state handoff, application
deployment, database initialization, authenticated Console readback, complete initial resource
discovery, and independent final readiness. See [Subscription Genesis Provisioning](subscription-genesis-provisioning.md).

The packaging host can add `--with-runtime-wheels` to include the locked support interpreter
inputs under `support/python/`. `fdaictl offline install-support` authenticates those inputs,
installs them without package indexes or caches, and verifies actual installed versions.
This is deployment tooling, not a co-hosted replacement for the five runtime services.
See the [CLI installation commands](../../../packages/deployment-cli/README.md).

### Bind a generic Console build at installation

The packaging host runs `npm --prefix console run build:offline`. The output is
`console/dist/offline/`; local env files and process `VITE_*` values are excluded. The build
requires installation-time bindings and does not fall back to local API defaults when they are
absent. The installer host does not need npm to configure these prebuilt files.

Copy the build to a current-user mode-`0700` staging directory and prepare a mode-`0600` settings
file under a private directory. Then run:

```bash
fdaictl offline configure-console \
  --directory /private/console \
  --settings /private/console-settings.json \
  --output json
```

The settings schema is `fdai.console-runtime.v1`, with exactly `operator_api_base_url`,
`ingestion_api_base_url`, `tenant_id`, `spa_client_id`, and `api_scope` in addition to
`schema_version`. API URLs use HTTPS without credentials or query strings, identifiers are UUIDs,
and the scope uses `api://<API-application-id>/<scope>`. These values are public configuration,
not secrets or role grants. The [CLI README](../../../packages/deployment-cli/README.md) includes
a synthetic example.

The command atomically replaces only the shipped `fdai-config.js` placeholder. An identical
repeat is a no-op; a tenant or endpoint change requires a fresh build copy. The runtime overlay
forces Entra authentication even if old build-time bypass flags are present, and the hosting
configuration marks this file `no-store`. Configuring bytes does not create Entra registrations,
publish the site, configure API CORS, or verify authenticated access.

### Boot an offline execution host

Set `runner_bootstrap_mode = "offline"` and supply a version-specific `runner_source_image_id`
in the bootstrap inputs. Both GitHub registration fields remain empty. Offline mode uses the
prebuilt image with no cloud-init downloads; online defaults are unchanged. The image needs the
approved toolchain and must contain no cached credentials. Network access and image attestation
still require independent checks. `enable_public_egress` remains a separate, explicit choice.
See the [bootstrap README](../../../infra/bootstrap/README.md).

Fresh platform plans may set `generate_initial_postgres_password = true` with a null
`postgres_admin_password`. A sensitive 32-character credential is generated only by the approved
private-host apply and retained in private state. Keep this selection stable; changing an existing
server to generated credentials is a separately reviewed rotation, not a silent first-install retry.

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
`scripts/deployment/release/stage-offline-kit.sh`, which collects the `fdai-deployment-cli` wheel and every
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
should receive for the toolchain. The dedicated CLI verifier is available; prior drill evidence is
recorded in the deployment CLI ledger. The stage phase runs the
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
| A complete eligible runtime release has not been published | Local preparation supports real payload inventories, but cannot manufacture approved images, Console delivery inputs, or their evidence | [Installable Deployment CLI](installable-deployment-cli.md) |
| The trust-root ceremony has not run, so no pinned public root ships in the wheel | inspection can never report a verified offline kit; it stays `candidate` or `review` | [offline-trust-ceremony.md](../../runbooks/offline-trust-ceremony.md) |
| Offline application execution is not composed | Public-artifact workflow dispatch is blocked; a verified snapshot alone cannot deploy the application | [subscription-genesis-provisioning.md](subscription-genesis-provisioning.md) |
| Bootstrap apply orchestration and teardown remain target behavior | the operator drives the exact-plan approval and apply by hand | [installable-deployment-cli.md](installable-deployment-cli.md) |
| No self-hosted model adapter | a site with no cloud reachability has no adaptive path at all | [tech-stack.md](../architecture/tech-stack.md) |

Framework-surface and offline artifact verification are network-independent. Production trust
bootstrap and complete new-subscription runtime installation remain separate, open requirements.

## Related docs

| To learn about | Read |
|----------------|------|
| The private-networking Terraform layer and hardening knobs | [deploy-and-onboard.md](deploy-and-onboard.md) |
| Offline kit contracts, build, and verification | [provisioning-execution-profiles.md](provisioning-execution-profiles.md) |
| The CLI facade, signed bundles, and exact-plan apply | [installable-deployment-cli.md](installable-deployment-cli.md) |
| Establishing and rotating the offline trust root | [offline-trust-ceremony.md](../../runbooks/offline-trust-ceremony.md) |
| Recovering from a rejected kit or a blocked plan | [deployment-recovery.md](../../runbooks/deployment-recovery.md) |
