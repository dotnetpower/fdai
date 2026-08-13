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
| Read-only inspection and profile initialization commands | not-started | Repository package metadata and the command contracts in this document | No dedicated CLI distribution or `fdaictl` project script currently exists. |
| Managed VM, private backend, and protected runner | implemented | `infra/bootstrap/`, `.github/workflows/deploy-dev.yml`, and focused bootstrap and workflow tests | The durable VNet host, workload identity, private state, protected plan, and exact-apply mechanics exist without the local CLI facade. |
| Offline-kit construction and verification | in-progress | `scripts/deployment/release/build-offline-kit.py` and `stage-offline-kit.sh` | Release scripts exist, but their imported `fdai.deployment_cli.offline_kit` implementation is absent. |
| Temporary public-access cleanup | not-started | The access preference contract in this document | No composed command proves bounded creation, automatic cleanup, incomplete-on-cleanup-failure behavior, and audit closure. |
| Pinned TUF root and rotation | not-started | `docs/runbooks/offline-trust-ceremony.md` | The first root ceremony, package resource, client bootstrap, and rotation evidence remain open. |
| Post-provision verification | in-progress | Protected workflow checks and `docs/roadmap/operations/operating-and-verification.md` | Runner-side convergence, migrations, health, and canary checks exist; the complete CLI-driven lifecycle and disconnected receipt do not. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-14 | in-progress | Adopted the implementation ledger; earlier provenance was not reconstructed. Corrected inspection, profile persistence, and offline verification from implemented to their evidence-backed current states. | current change; package metadata, bootstrap source, release scripts, and focused workflow checks listed in the scope table | Create the CLI package, restore offline verification, complete trust bootstrap, and validate the full lifecycle. |

### Remaining work

- [ ] Implement `provision inspect` and `provision init` in the dedicated CLI package and pass no-mutation, mode-`0600`/`0700`, overwrite, symlink, and stable-JSON tests.
- [ ] Restore offline-kit verification behind an injected release root and pass signature-before-parse, exact-file-set, no-follow digest, compatibility, and bounds tests.
- [ ] Implement temporary public-access creation and cleanup so cleanup failure leaves an incomplete audited operation, then pass CIDR, duration, authentication, rollback, and idempotency tests.
- [ ] Complete the TUF root ceremony and package bootstrap, then retain a governed inspect-to-plan-to-apply-to-cleanup-to-verification receipt.

## Design at a glance

Provisioning treats four choices as independent axes. The command evaluates evidence first and
does not infer authority from environment names such as `dev` or from the machine on which the
operator installed the wheel.

| Axis | Supported values | Selection rule |
|------|------------------|----------------|
| Connectivity | `online`, `offline` | Use online sources only after bounded TLS checks pass; otherwise require a signed offline kit |
| Execution host | `existing-host`, `managed-vm` | Reuse a suitable private-network host; create a managed VM when no suitable host is available |
| Transport | `manual`, `github-actions` | Let a person start the exact-plan flow directly, or submit the same flow through GitHub Actions |
| Ownership | `fdai-managed` | Terraform manages declared resources and role assignments after approval |

## Read-only inspection

The target command runs inspection before creating a bootstrap plan:

```bash
fdaictl provision inspect --output json
```

Inspection checks the local Azure CLI, Terraform, GitHub CLI, bounded online artifact access,
an offline-kit candidate, and the Azure workload identity endpoint. It returns a stable JSON
contract with `mutation_performed=false`, one required human approver, and the selected profile.
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
	--connectivity online \
	--host existing-host \
	--transport manual \
	--access-method internal_ssh
```

The command rejects every `auto` value and writes `.fdai/provisioning/profile.json` with file mode
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

Temporary public access is never a silent fallback. Its plan requires an allowlisted source CIDR,
key- or certificate-only SSH, a bounded access window, and automatic removal of the public IP and
temporary network-security rule. `0.0.0.0/0`, password authentication, and a persistent public IP
are not accepted. Cleanup is part of the operation's success criteria. Failed cleanup leaves the
operation incomplete and writes an audit record.

## Online and offline delivery

Online delivery uses the public `fdai` package from PyPI and a version-matched signed deployment
bundle. The runner may use public sources only after the allowlisted TLS checks pass.

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
