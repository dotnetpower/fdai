---
title: One-Command Source Deployment
---

# One-Command Source Deployment

Anyone who clones the FDAI repository can deploy every FDAI resource to their own Azure
subscription with one command line after `az login`. This document defines that command, the
artifacts it may and may not create, and how it selects a 30-day Trial or a full entitlement. It
owns the first installation path in
[Constitution Article 1](../architecture/fdai-constitution.md#article-1-purpose-and-scope).

> **Status:** This is the target contract. The source run now continues from the verified
> Foundation handoff into the shared AKS application stage without a signed kit. It transfers the
> pinned source snapshot to the managed host, builds service images with the deployment registry,
> resolves Terraform providers from the public registry under committed lock files, runs
> migrations and catalogs from the checkout, and keeps the same health, inventory, and second
> zero-change checks. The
> [implementation ledger](../../roadmap-implementation/deployment/source-deployment.md)
> records the current state and the ordered remaining work.
>
> **Scope:** Runtime and provisioning topology, Trial and token semantics, and the signed offline
> package stay with the owners listed in [Related docs](#related-docs).

## Design at a glance

| Concern | Decision |
|---------|----------|
| Who can deploy | Anyone with a clone, an interactive `az login`, and rights to create resources and role assignments in the target subscription |
| Entry points | One line, `git clone https://github.com/dotnetpower/fdai.git && fdai/scripts/deployment/azure/fdai-up.sh --region <region>`, or `fdaictl provision azure --source <checkout> --region <region>`; both run one coordinator |
| Artifact source | One clean committed checkout; service images are built from it into the deployment's own registry |
| Release artifacts created | None: no signed kit, bundle, control package, wheelhouse, appliance, host image, SBOM, provenance, attestation, or published release |
| Keys required | None. A signing key is never an installation input |
| No integrity signing key | One durable 30-day Trial anchored to the installation's creation time |
| `secrets/integrity-signing-key.pem` | A full-catalog installation entitlement without expiry, bound to that installation |
| After the Trial | Acting work is blocked, observation continues, and every Console view shows a persistent expiry watermark |
| Approval | The invocation approves each plan it shows; deleting or replacing an existing resource needs one typed confirmation |
| Teardown | Source teardown removes only resource groups proven by retained source intent, preparation, and Foundation handoff evidence, after one typed confirmation and absence readback |
| Success | `deployment_ready=true` only after service health and a second zero-change plan |

## Design and critique

**Initial design:** Treat any private key under `secrets/` as proof of full entitlement, deploy
observation-only otherwise, and keep building a signed kit from the checkout before deployment.

**Critique:**

- A filename or an arbitrary key is not proof: an empty or mismatched file passes a presence
  check, and the offline-package signing key authenticates artifacts, not usage rights.
- The deployed runtime must never read a private key.
- Observation-only is not a Trial. A new user could never evaluate the acting capabilities.
- A Trial that only blocks acting work in the background goes unnoticed, and an expiry that a
  setting, a deleted record, or a redeployment can hide or reset is not an evaluation boundary.
- A 30-day token on the key holder's own installation degrades it unless the key holder redeploys,
  which is a Trial in everything but name.
- Building and signing a kit to deploy from source creates artifacts that nobody else verifies and
  requires a signing key that a new user does not have.

**Revised contract:** Only the upstream integrity signing key, proven by matching the tracked
integrity public key, selects full mode, and the workstation turns it into a signed installation
entitlement. The Owner chose that key on 2026-10-01, so one key now protects framework integrity
and licensing, and domain-separated documents keep a signature for one purpose from verifying for
the other. Without that key, the deployment initializes one durable Trial anchored to the
installation's creation time, and after it ends every Console view shows a persistent expiry
watermark that no setting hides. The source path builds images directly into the deployment and
creates no signed release artifact. A present but unusable key stops the run before the first Azure
effect instead of silently selecting Trial.

When the source deployment selects `read-only-console` or `enterprise-identity-governance`, it also
checks tenant-local Entra display names before Foundation preparation. FDAI binds to one shared
tenant-local set of exact display names. Duplicate `fdai-*` application or `aw-*` group names stop
the source run with a fixed ambiguity reason before any Azure effect. The command does not guess,
create installation-scoped names, or accept an unreviewed binding file.

**Application continuation revision:** The first implementation option was to route a completed
source Foundation into signed-kit adoption. That preserved the existing application code, but it
would have required a kit archive, provider mirror, runtime release manifest, support wheelhouse,
and Console archive. Those inputs would reintroduce the release artifact that the source path is
designed to avoid. The source path instead reuses the standalone application coordinator and swaps
only the artifact input seam:

- the managed host receives the verified source transport archive and installs the deployment CLI
  from that source snapshot;
- Terraform roots and migration support come from the snapshot, while providers resolve directly
  from public registries under the committed `.terraform.lock.hcl` files. Because no prebuilt
  wheelhouse exists, the workstation exports the committed `uv.lock` closure of the runtime
  packages as one hashed requirements file, the host reads back its digest, installs it as
  binary-only hashed packages, adds the snapshot's workspace packages without dependency
  resolution, and records a receipt;
- the host acquires the kit's pinned `kubectl` and `kubelogin` releases and keeps them only when the
  committed digests match;
- service image references come from the source image stage receipt after substrate apply creates
  the deployment registry;
- the Console archive is built from the local checkout only when the Console add-on is selected;
- `--evidence-verifier-input` may carry the reviewed independent operational evidence verifier
  binding into the same application continuation; omitting it leaves source deployment values
  unchanged and the verifier off;
- every receipt records `operator-selected-source` and `release_signature_verified=false`.

Signed-kit adoption remains available only for recovered Foundations that explicitly continue with
an offline package.

**Guarded teardown revision:** Teardown originally could have reused Terraform destroy from the
current work tree. That would be too broad for source deployment because retained state can be
partial, recovered, or absent after a failed run. The source path instead derives a teardown review
only from retained source evidence: the source intent, source preparation receipt, Genesis marker,
and verified Foundation state handoff. The review names only the application and operations
resource groups from that proof, binds them to the target binding and source run binding, requires
one typed confirmation, deletes only those groups, and then reads back their absence. If any
resource name, digest, target, source, or handoff field cannot be proven, teardown refuses before
any delete call. A partial deletion returns a partial-failure receipt and keeps live teardown
evidence open for operator review.

## Run the command

```bash
git clone https://github.com/dotnetpower/fdai.git && fdai/scripts/deployment/azure/fdai-up.sh --region koreacentral
```

The line works from any directory because `fdai-up.sh` resolves its own checkout. Sign in with
`az login` first; when no Azure CLI session exists, the command starts that interactive sign-in
itself. `fdai-up.sh` prepares the checkout's locked environment and invokes
`fdaictl provision azure --source <checkout>` with the remaining options. Both entry points run the
same coordinator and produce the same result. Running the command again resumes or upgrades the
same installation.

The workstation needs Bash, `git`, Azure CLI, and `uv`. Selecting the Console add-on also needs
Node.js and npm to build the Console from the committed lockfile. No container engine, GitHub
account, repository secret, workflow, or registered runner is required.

## Entitlement selection

The coordinator selects the entitlement mode once, on the workstation, before any Azure effect:

| Workstation state | Deployment receives | After 30 days |
|-------------------|---------------------|---------------|
| No `secrets/integrity-signing-key.pem` | One Trial record anchored to the installation's creation time | New acting work is blocked and the expiry watermark appears; observation, diagnosis, audit, and export continue |
| Usable integrity signing key | A full-catalog installation entitlement | No change; the entitlement has no expiry |
| Integrity key present but unusable | Nothing; the run stops before any Azure effect | Not applicable |

A usable key is the fixed `secrets/integrity-signing-key.pem` file in the checkout's ignored
`secrets/` directory, the same file that re-signs the framework surface at commit time. It must be
a current-UID, mode-`0600` regular file whose Ed25519 public key matches the tracked
`security/integrity/upstream-signing-key.pub`. Running
`scripts/deployment/release/check-signing-key.py --scan secrets` reports the role each key
satisfies without printing key material. The offline-package signing key never selects full mode.

- **Key custody:** The private key never leaves the workstation. It never enters an image,
  Terraform input or state, a command-line value, a log, or Key Vault. Only the signed entitlement
  moves, through a Key Vault file input under a digest-derived secret name.
- **Binding:** The entitlement and the Trial record bind the installation and deployment digests,
  not the source revision or image digest. Upgrades and restarts neither invalidate a full
  entitlement nor renew a Trial, and a lost Trial record returns with its original activation time.
- **Shared key:** The same key signs the framework-surface manifest and licensing documents. Its
  compromise affects both, and after a rotation the key holder reruns the deployment to re-issue
  the entitlement.
- **Mode change:** A later run with a usable key replaces Trial with the full entitlement without
  reinstalling. A later run without a key keeps an installed entitlement; omission never revokes it.
- **Authority:** Entitlement moves only the capability `available` axis. Promotion, RBAC, risk,
  human approval, executor identity, and effect verification stay independent, as
  [Capability Licensing](../fork-and-sequencing/capability-licensing.md#the-rule-that-makes-this-safe)
  requires.

## After the Trial ends

When the Trial ends, Core blocks new acting work at the next decision without a restart, while
observation, diagnosis, audit, and export continue. Every Console view then shows a persistent
watermark in the lower-right corner, like an unactivated desktop operating system, and every
Operator API response carries the same state. No setting, data change, or redeployment hides it;
only a full entitlement does. [Capability Licensing](../fork-and-sequencing/capability-licensing.md#trial-expiry-watermark)
owns the exact contract.

## What the command builds

| Input | Source path behavior |
|-------|----------------------|
| Service images | Built from a `git archive` of the exact commit by the registry build service of the deployment's own registry, tagged `sha-<commit>`, and deployed by digest |
| Dependency images | Imported by pinned digest into the deployment's registry |
| Console | Built from the checkout and published only when the Console add-on is selected |
| Terraform | Uses `terraform` on `PATH` only when it matches the committed binary digest; otherwise downloads the pinned `linux_amd64` release once and keeps it only when both the archive and binary digests in `infra/genesis-runner-image/toolchain.json` match |
| Runtime support environment | The committed `uv.lock` closure exported on the workstation, installed on the managed host as hashed binary packages, plus the snapshot's workspace packages |
| Kubernetes client tools | The kit's pinned `kubectl` and `kubelogin` releases, downloaded on the managed host and kept only when the committed digests match |
| Terraform providers | Resolved from the public Terraform registry under the committed lock files |
| Database | Migrations and authoritative catalogs from the checkout, followed by Trial initialization |
| Provenance | Recorded in the private run receipt as `operator-selected-source`, never as a signed release |

The source path never creates a signed kit, deployment bundle, bundle signature,
deployment-control package, signed wheelhouse, runtime release manifest, appliance, runner or host
image, SBOM, provenance or attestation statement, TUF metadata, or published release or image. It
never requires a protected branch, CI result, public GHCR package, or maintainer. The signed
offline package in [Disconnected Deployment](disconnected-deployment.md) is the only installation
artifact that FDAI signs. [Installable Deployment CLI](installable-deployment-cli.md#source-image-stage)
owns the image stage's claim, readback, and recovery rules.

## Stage order

1. Read the human target from the active `az login` session and confirm the subscription.
2. Admit one clean committed checkout and pin its snapshot.
3. Select the entitlement mode on the workstation.
4. Run the read-only provider, policy, quota, and SKU preflight.
5. Plan and apply the platform under the selected runtime and provisioning profiles.
6. Build the service images, import the dependency images, and read back every digest.
7. Run migrations and catalogs, and initialize the Trial record at the installation's anchored
   activation time when none exists.
8. In full mode, issue the installation entitlement and store it through Key Vault.
9. Plan and apply the services by digest, and publish the Console when it is selected.
10. Verify health, run the initial inventory, and require a second zero-change plan.
11. Report `deployment_ready`, the entitlement mode, and the Trial end date without secret values.

Independent reads and builds may run concurrently. Approval, apply, migration, entitlement writes,
and activation stay serial. Every apply keeps the claim-before-effect, verification-only recovery,
and no-repeated-ambiguous-apply rules in
[Installable Deployment CLI](installable-deployment-cli.md#approval-and-recovery).

## Honest limits

- **Tamper-evident, not tamper-proof:** The Trial check and the watermark's decision and rendering
  belong to the signed framework surface, so changing them requires modifying signed code, which
  verification against the upstream-signed manifest exposes. The Console shell that mounts the
  watermark is ordinary Console code, and nothing stops an operator who controls the source and
  runtime from running modified code. The Trial is an evaluation boundary, not copy protection.
- **No reinstall detection:** Tearing down an installation and deploying a new one starts a new
  Trial. FDAI runs no global activation service.
- **Builder availability:** Remote image builds need the registry build service in the target
  subscription. When it is unavailable, the run stops with fixed guidance before any service apply
  rather than falling back to another image source.
- **Operator-selected source:** A source installation proves which commit the operator selected,
  not that a publisher released it.

## Related docs

| To learn about | Read |
|----------------|------|
| Delivery status and remaining work | [Implementation ledger](../../roadmap-implementation/deployment/source-deployment.md) |
| Installation paths and their limits | [FDAI Constitution Article 1](../architecture/fdai-constitution.md#article-1-purpose-and-scope) |
| Trial, tokens, and the installation entitlement | [Capability Licensing](../fork-and-sequencing/capability-licensing.md) |
| `fdaictl` commands, approval, and recovery | [Installable Deployment CLI](installable-deployment-cli.md) |
| AKS or Container Apps and database placement | [Runtime Deployment Profiles](runtime-deployment-profiles.md) |
| Where Terraform runs and how it is reached | [Provisioning Execution Profiles](provisioning-execution-profiles.md) |
| The signed offline package | [Disconnected Deployment](disconnected-deployment.md) |
| Step-by-step user instructions | [Deploy Quickstart](../../user-guide/deploy-quickstart.md) |
