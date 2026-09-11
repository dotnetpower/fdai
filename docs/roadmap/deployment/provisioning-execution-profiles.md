---
title: Provisioning Execution Profiles
---
# Provisioning Execution Profiles

This document defines how the planned `fdaictl` distribution selects a provisioning host, connectivity mode, command
transport, and access path. It also defines the human approval and workload-identity boundary
that applies before Terraform changes infrastructure or role assignments.

> **Scope:** Azure is the implemented target. The profiles do not change the Terraform source of
> truth or allow local fallback around a private endpoint.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Read-only inspection and profile initialization commands | implemented | `packages/deployment-cli`; focused profile, target, tool, and productization tests | The dedicated distribution registers `fdaictl`, writes private target-bound profiles, and returns review until execution-host evidence exists. |
| Managed VM, private backend, and protected runner | implemented | `infra/bootstrap/`, `.github/workflows/deploy-dev.yml`, and focused bootstrap and workflow tests | The durable VNet host, workload identity, private state, protected plan, and exact application-apply mechanics exist. |
| Fresh-subscription local coordinator | implemented | `fdaictl provision azure`; `fdai-up.sh`; signed-kit, Foundation, Bastion, managed-host, approval, license, migration, and convergence modules; routed lifecycle tests | One `dev` process derives the target from the active Azure CLI user, uses bounded concurrency only for independent preparation and read or request siblings, and keeps stateful transitions serial. GitHub Actions remains an optional transport. A governed Azure receipt and complete readiness evidence remain open. |
| Offline-kit construction and verification | validated | `fdai_deployment_cli.offline_kit`; locked release scripts; successful network-isolated air-gap drill | Signature-first verification, exact files, SBOM coverage, ABI/libc binding, private snapshots, and shipped-wheel installation pass. |
| Temporary public-access cleanup | not-started | The access preference contract in this document | No composed command proves bounded creation, automatic cleanup, incomplete-on-cleanup-failure behavior, and audit closure. |
| Pinned TUF root and rotation | not-started | `docs/runbooks/offline-trust-ceremony.md` | The first root ceremony, package resource, client bootstrap, and rotation evidence remain open. |
| Post-provision verification | in-progress | Managed-host exact-plan apply receipts, ACR digest readback, migrations, health readback, and second zero-change plan; routed lifecycle tests | The implementation exists, but the complete CLI-driven Azure lifecycle and artifact-offline operational receipt remain open. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-14 | in-progress | Adopted the implementation ledger; earlier provenance was not reconstructed. Corrected inspection, profile persistence, and offline verification from implemented to their evidence-backed current states. | current change; package metadata, bootstrap source, release scripts, and focused workflow checks listed in the scope table | Create the CLI package, restore offline verification, complete trust bootstrap, and validate the full lifecycle. |
| 2026-08-29 | validated | Added target-bound inspection and private profiles, restored signed offline verification, and completed the shipped-wheel network-isolated drill. | Campaign commits from `dd28b64d9`; focused tests and successful `airgap-drill.sh` | Complete managed-host Azure execution and retain protected post-provision receipts. |
| 2026-09-05 | implemented | Routed exclusive RCA reader identity apply and verification resume through an allowlisted bot-owned request. The downstream apply remains bound to a protected GitHub Environment and validates its reviewer policy from protected `main` before mutation. | `current change`; focused deployment CLI, workflow, and Environment policy tests | Retain one independently approved exact apply and effect receipt. |
| 2026-09-05 | implemented | Extracted the read-only inventory change accelerators from the scheduled inventory entry point while preserving the venue-selected workload identity, private runner transport, per-scope locks, durable cursor fencing, and complete-reconciliation authority. | `current change`; inventory accelerator and job tests, strict mypy, and enforced file-size gate. | Retain the integrated change-feed timing receipt tracked by the operating-instance owner. |
| 2026-09-06 | implemented | Added an installed inventory wrapper that accepts only positional `once` or `loop` modes for exact-image Container Apps rehearsals. It translates to the existing CLI without changing collection, projection, identity, or execution authority. | `current change`; focused inventory CLI tests, strict mypy, package build, and entrypoint discovery. | Retain one exact-image inventory projection refresh receipt before operational-history certification. |
| 2026-09-06 | implemented | Added a deadline-bounded active-generation projection release migration to the protected OI-16 execution profile. It performs no provider read, preserves the prior manifest and journal fences, and refuses incomplete or changed content before writing. | `current change`; focused replay CLI, projection, persistence, workflow, and package checks. | Retain one successful exact-release migration receipt from the protected dev campaign. |
| 2026-09-11 | implemented | Added bounded parallel execution for independent local artifact lanes, Foundation input discovery, provider inspection and registration requests, policy-probe resource operations, and tenant-directory reads. Stateful applies, approvals, cleanup, handoffs, repository writes, and protected application transitions remain serial. | `current change`; focused Genesis, provider-mirror, preparation, Entra, and productization tests | Retain timing evidence from the next exact-main supervised deployment without treating elapsed time as readiness. |
| 2026-09-11 | implemented | Added online and artifact-offline installed-package deployment from the active `az login` target without requiring GitHub Actions. Complete signed kits, a no-GitHub managed host, exact application approvals, operator-issued or Trial licensing, image readback, pre-activation migrations, and convergence checks share one path. | `current change`; deployment CLI and Genesis source; strict mypy; package build and cold install; routed deployment and Genesis tests | Build the complete signed release kit from a clean snapshot and retain online and artifact-offline Azure convergence receipts. |
| 2026-09-12 | implemented | Completed 16 standalone deployment critique and hardening rounds. Transport reuse now binds the exact signed kit, trust roots require Ed25519, destructive plans require a second exact confirmation, ambiguous applies resume by verification only, retained Foundation and Entra context is exact, provider fallback remains blocked, and license, migration, image, revision-health, and zero-change effects require independent readback. | `current change`; deployment CLI, release builder, ShellCheck, strict mypy, focused package and Genesis tests, and independent post-fix critiques | Build and reverify the clean signed kit, then retain online and artifact-offline Azure convergence receipts before raising validation state. |

### Remaining work

- [x] Implement `provision inspect` and `provision init` in the dedicated CLI package and pass no-mutation, mode-`0600`/`0700`, overwrite, symlink, and stable-JSON tests.
- [x] Restore offline-kit verification behind an injected release root and pass signature-before-parse, exact-file-set, no-follow digest, compatibility, and bounds tests.
- [ ] Implement temporary public-access creation and cleanup so cleanup failure leaves an incomplete audited operation, then pass CIDR, duration, authentication, rollback, and idempotency tests.
- [ ] Complete the TUF root ceremony and package bootstrap, with signed root and rotation evidence accepted by the offline trust ceremony.
- [ ] Build and reverify one complete signed kit from a clean snapshot, then cold-install its CLI and acquire the same kit through both online and local artifact paths.
- [ ] Retain target-bound Foundation and application convergence receipts from both active-login modes without claiming whole-subscription readiness.

## Design at a glance

Provisioning treats four choices as independent axes. The command evaluates evidence first and
does not infer authority from environment names such as `dev` or from the machine on which the
operator installed the wheel.

| Axis | Supported values | Selection rule |
|------|------------------|----------------|
| Connectivity | `online`, `offline` | Use online sources only after bounded TLS checks pass; otherwise require a signed offline kit |
| Execution host | `existing-host`, `managed-vm` | Reuse a suitable private-network host; create a managed VM when no suitable host is available |
| Transport | `manual`, `github-actions` | Use `manual` for the default installed-package flow. GitHub Actions is an optional repository-owned CI/CD transport, not a subscription deployment prerequisite. |
| Ownership | `fdai-managed` | Terraform manages declared resources and role assignments after approval |

### Standalone active-login deployment

The installed package supports one default subscription deployment boundary after `az login`:

```bash
fdaictl provision azure --online
fdaictl provision azure --offline-kit /media/fdai/fdai-kit.tar
# Source-checkout convenience wrapper; online is the default.
scripts/deployment/azure/fdai-up.sh
```

Both commands derive the tenant and subscription only from the active Azure CLI user context. They
do not require a source checkout, Git remote, GitHub account, GitHub repository, required CI check,
repository variable, repository secret, workflow dispatch, or GitHub runner registration. Online
mode downloads one versioned complete kit over bounded HTTPS. Offline mode reads that same kit
format from a local path and blocks every public artifact fallback. Offline means artifact-offline,
not disconnected from the selected Azure control plane or Bastion endpoint.

The package pins the release and bundle verification roots independently from the kit. A complete
kit contains the deployment bundle, Terraform and OPA, the provider mirror, runtime OCI archives,
Console content, migration support, and their software bills of materials. Signature, exact-file,
platform, source-revision, and runtime-content verification completes before Azure mutation.
The current managed-host image and complete-kit builder support Linux x86_64. Other host
architectures fail before kit acquisition rather than crossing an untested execution boundary.

For a private route, the signed-in human performs only the bounded Foundation control-plane apply.
The resulting Bastion-reachable VM uses a user-assigned managed identity and a manual-host image
that contains no GitHub runner software. It verifies the kit again, creates the private application
backend and registry path through a separate exact plan, imports and reads back the verified OCI
archives, installs the deployment-bound license, runs migrations before application activation,
and then runs the application plan, apply, health checks, and second zero-change plan.
Private data-plane work never falls back to the operator workstation.

Every mutating checkpoint retains exact-plan approval, an immutable pre-effect claim, a bounded
stop and cleanup path, target locking, stable idempotency, and independent effect readback. The
default standalone `dev` path accepts one current local human approval per exact plan. Staging and
production continue to require the configured independent quorum and approved execution host.
If an apply outcome is ambiguous, the next invocation runs a zero-change plan and authoritative
readback only. It never repeats the apply from the retained claim. A changed Foundation run,
network/state handoff, Entra binding, provider configuration, or signed kit requires a distinct
prepared context.

The command discovers an operator-held mode-`0600` license issuer key from an explicit option or the
documented user configuration path. When the key exists, it issues a deployment- and image-bound
token without copying the key. Otherwise it requires a pre-issued mode-`0600` Trial token file from
the terminal. The token crosses Bastion through standard input and is written to Key Vault by the
managed identity; it never appears in arguments, Terraform state, portable status, or logs.

## Read-only inspection

The target command runs inspection before creating a bootstrap plan:

```bash
fdaictl provision inspect --output json
```

Inspection checks the local Azure CLI, Terraform, GitHub CLI, bounded online artifact access,
an offline-kit candidate, and the Azure workload identity endpoint. It returns a stable JSON
contract with `mutation_performed=false`, the required approval policy and quorum, and the selected profile.
It never installs a tool, writes configuration, creates a resource, registers a runner, or applies
Terraform.

The result uses these states:

| State | Meaning |
|-------|---------|
| `ready` | An existing host has its toolchain, workload identity, and online access or a verified offline kit |
| `review` | A managed VM or offline kit without a pinned verifier requires operator review |
| `incomplete` | The explicitly requested profile is missing a required dependency or access path |

File presence alone never establishes trust. With a composition-injected pinned verifier,
inspection checks signature, compatibility, exact files, digests, and bounds, then returns only
non-secret manifest metadata. Rejected content is `incomplete`; verified content can make a
complete existing-host profile `ready`. Until the public root ceremony packages that verifier,
the target CLI must keep offline directories at `candidate` / `review`.

## Profile initialization

The target initialization command saves a reviewed profile with explicit, resolved values:

```bash
fdaictl provision init \
	--target-binding <sha256> \
	--connectivity online \
	--host existing-host \
	--transport manual \
	--access-method internal_ssh
```

The target binding is a deployment-local digest of the intended tenant and subscription pair, not
either raw identifier. The command rejects every `auto` value and writes `.fdai/provisioning/profile.json` with file mode
`0600` in a mode-`0700` directory. Offline profiles require `--artifact-source`. Temporary public
SSH requires a canonical source CIDR narrower than the entire address space and an access window
of 5-60 minutes. GitHub Actions transport requires the matching `github_actions` access method.

An existing destination blocks initialization unless `--force` is explicit. Force never follows
a symbolic link or replaces a non-file destination. Profile initialization changes no Azure
resource and reports `mutation_performed=false` in JSON output.

## Execution hosts

### Existing host

Use `existing-host` for a jumpbox or deployment host that already has:

- network and private DNS reachability to every required private endpoint;
- Azure CLI and Terraform;
- a distinct workload identity with the approved deployment roles;
- durable access to the protected Terraform backend and plan store.

Manual execution means that the operator starts `fdaictl` on this host. It does not mean that
Terraform uses the operator's interactive Azure identity. A host without a workload identity is
reported as incomplete.

### Managed VM

Use `managed-vm` when the operator laptop is outside the private network, the existing jumpbox is
unsuitable, or policy requires a dedicated deployment host. The VM remains durable but is normally
deallocated. Protected state, plans, approvals, and audit records remain in private storage so VM
start, stop, or rebuild does not change deployment authority.

The target CLI recommends a managed VM but does not create one during inspection. Bootstrap planning
shows the VM, network, identity, role, access, cost, stop, and cleanup effects before approval.

## Access preference

The managed-host access order is fixed:

1. Approved internal SSH.
2. Temporary public-IP SSH when Azure Policy and the deployment profile allow it.
3. GitHub Actions on a self-hosted runner.
4. Azure Bastion.
5. Azure Run Command as an audited emergency path.

Fresh-subscription Genesis doesn't fall through this list. A profile with `access_method=bastion`
selects the exact Standard Bastion native tunnel created by Foundation. Enrollment material then
travels only through SSH standard input, and state handoff uses the same pinned host-key boundary.

Temporary public access is never a silent fallback. Its plan requires an allowlisted source CIDR,
key- or certificate-only SSH, a bounded access window, and automatic removal of the public IP and
temporary network-security rule. `0.0.0.0/0`, password authentication, and a persistent public IP
are not accepted. Cleanup is part of the operation's success criteria. Failed cleanup leaves the
operation incomplete and writes an audit record.

## Online and offline delivery

Online delivery uses the public `fdai-deployment-cli` package and a version-matched complete signed
deployment kit. The managed host consumes only the kit's authenticated binaries, providers,
runtime images, and migration wheels.

The target release workflow builds the wheel and source distribution once in a read-only job, checks that
the Python and bundle versions match, and publishes that exact artifact through PyPI Trusted
Publishing only after the matching signed bundle is published. Only the publish job receives the
GitHub OIDC permission; no long-lived PyPI token is stored.

The public PyPI release line starts at `0.1.0`. Existing repository tags `v0.1.1` through
`v0.1.12` are pre-PyPI engineering milestones and are not rewritten. The first public release tags
the exact publication commit as `v0.1.0`. An installation with an active pre-PyPI bundle state
above `0.1.0` uses a fresh public release state or an explicit migration; it is not treated as a
semantic-version upgrade to `0.1.0`.

Disconnected delivery uses the same `fdai` wheel and command contracts in a platform-specific
offline kit. The kit contains:

- the FDAI wheel and all transitive Python wheels;
- the signed deployment bundle;
- a pinned Terraform binary and provider mirror;
- OPA and required helper binaries;
- an SBOM, SHA-256 manifest, signatures, and the release trust metadata.

Complete staging builds the signed deployment bundle first, then assembles runtime v2 from a
private digest-bound descriptor against those exact bundle bytes before signing the outer kit.
An independently prebuilt runtime remains supported only when it already binds that exact bundle.

Offline mode blocks fallback to PyPI, GitHub, and the public Terraform registry. The artifact
source may be an approved internal mirror or removable media. The installer and `fdaictl` verify
the same pinned release root in both cases.

The target `verify_offline_kit` implementation checks an Ed25519 signature before parsing the manifest, binds exact CLI and
platform versions, rejects symlinks and extra files, streams every file digest, and requires the
wheel, signed deployment bundle, Terraform binary and provider mirror, OPA, and SBOM. The release
root is injectable for tests, release construction, and pinned inspection composition only.
Artifact hashing uses a no-follow descriptor open so a path swap cannot redirect it. `fdaictl`
does not expose a
`--release-root` override; inspection remains `review` until a public root is pinned in the wheel.

Executing kit content demands stronger evidence than reporting on it. `provision plan` runs the
kit's Terraform binary, so it verifies the kit against a release root the operator supplies and
refuses to plan when that verification fails. Both paths resolve every artifact from the signed
manifest rather than from a directory convention. When the pinned root ships, `--release-root`
becomes a planning override that inspection still does not accept.

`build_offline_kit_manifest` is the intended release-side inverse of that verifier. It reads the staged kit
with the same scan, so it refuses to describe a symlink, a non-regular entry, or an out-of-bound
tree, and it derives the file list from the stage rather than from an operator-supplied list. A
declared artifact role that is absent from the stage fails before anything is signed, and two
builds of identical content produce one identical signable byte string.
`scripts/deployment/release/build-offline-kit.py` is intended to add signing after the verifier
module is restored: it loads an operator-held Ed25519
private key, removes any stale signature before writing the new manifest so an interrupted run
leaves an unverifiable kit rather than a plausible one, and re-verifies the written kit against
the public release root before reporting. The private key never enters the kit, the repository,
or any log line.

### Trust root and rotation

The final offline authority uses The Update Framework (TUF) 1.0 through Python-TUF 7. The wheel
ships the initial signed `root.json` through an out-of-band trust bootstrap. Root private keys stay
offline. CI may use delegated online keys for targets, snapshot, and timestamp metadata, but it
never receives a root private key.

Clients update root metadata one version at a time and require each new root to satisfy both the
old and new root thresholds. TUF metadata expiry and monotonic versions provide freeze, rollback,
and mix-and-match protection. The metadata threshold and key ceremony are release-security policy;
they are independent from the one-person approval required for a provisioning apply.

The current exact-content verifier remains defense in depth after TUF authenticates the target.
Python-TUF integration and the first root ceremony remain blocked until the offline root is created
and backed up outside CI. No generated private key is committed or transferred through `fdaictl`.

## Approval and apply

Every operator-initiated infrastructure or role-assignment apply requires one authenticated human
approval bound to the exact binary-plan digest. The executor is a distinct workload identity. A
changed or expired plan invalidates approval, and apply accepts neither `-auto-approve` nor
caller-supplied Terraform arguments.

Delete, replacement, role change, state-backend change, temporary-access creation, and
temporary-access cleanup are highlighted separately in human and JSON output. They use the same
one-approver provisioning policy. This deployment policy does not reduce the existing quorum rule
for high-impact autonomous runtime actions.

The target lifecycle is:

```text
inspect -> profile init -> bootstrap plan -> human approval -> exact apply
	-> access cleanup -> post-provision verification
```

## Related docs

| To learn about | Read |
|----------------|------|
| Install and command contracts | [Installable Deployment CLI](installable-deployment-cli.md) |
| Azure inventory and bootstrap resources | [Deploy and Onboard](deploy-and-onboard.md) |
| Plan, release, and rollback lifecycle | [Deployment](deployment.md) |
| Executor and human identity separation | [Security and Identity](../architecture/security-and-identity.md) |
