---
title: Provisioning Execution Profiles
---
# Provisioning Execution Profiles

This document defines how `fdaictl` selects a provisioning host, connectivity mode, command
transport, and access path. It also defines the human approval and workload-identity boundary
that applies before Terraform changes infrastructure or role assignments.

> **Implementation status:** Read-only `fdaictl provision inspect` is implemented. Profile
> persistence, signed offline-kit verification, bootstrap plan/apply orchestration, temporary
> public-access cleanup, and post-provision verification remain target behavior.
>
> **Scope:** Azure is the implemented target. The profiles do not change the Terraform source of
> truth or allow local fallback around a private endpoint.

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

Run inspection before creating a bootstrap plan:

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
| `ready` | An existing host has the required toolchain, connectivity, and workload identity |
| `review` | A managed VM or unverified offline kit is recommended and requires operator review |
| `incomplete` | The explicitly requested profile is missing a required dependency or access path |

An offline-kit directory remains `review` until a later stage verifies its manifest and signature
against the pinned release root. File presence alone never establishes trust.

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

The CLI recommends a managed VM but does not create one during inspection. Bootstrap planning
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
