---
title: Package Assurance
---

# Package Assurance

This document defines the minimum controls for code or artifacts that cross an FDAI package
boundary. Internal workspace code has no package ceremony by default; explicit policy begins only
when a contract, artifact, or evidence set is consumed outside its lockstep build.

> **Authority boundary:** Package discovery, installation, availability, and enablement never grant
> approval, action promotion, executor identity, or execution authority.
>
> **Implementation ledger:** Delivery state and remaining evidence are tracked in the
> [Package Assurance implementation ledger](../../roadmap-implementation/architecture/package-assurance.md).

## Design at a glance

[`config/package-assurance.json`](../../../config/package-assurance.json) lists only explicit
external boundaries and artifact profiles. Unlisted packages remain ordinary workspace code.
[`check-package-assurance.py`](../../../scripts/quality/architecture/check-package-assurance.py)
checks the small constitutional minimum without duplicating package-manager, service-boundary,
capability-lifecycle, review, or promotion policy.

Stronger owner-specific controls remain supported. For example, the shared contract SDK may retain
N-1 tests and an offline release may require an SBOM. Those choices stay with the owner that
actually consumes the evidence; they are not hidden global package requirements.

## Revised design decision

**Initial design:** Encode five fixed assurance levels, an exhaustive package inventory, exact root
dependency mirrors, fixed lifecycle transitions, optional readiness behavior, extension facade
rules, and Cost Governance review-envelope semantics in one package gate.

**Critique:** That policy duplicates the lockfile, package manifests, independent-service checks,
runtime promotion registry, capability lifecycle, and protected review workflows. A package could
not be removed or reclassified without editing both policy and checker code. Recommended controls
such as SBOM and N-1 compatibility became hard requirements even when no released consumer or
offline boundary needed them.

**Revised design:** Workspace code is unconstrained by package ceremony. An explicit boundary keeps
only integrity, provenance, versioning, freshness, dependency closure, authority separation, and
effect-verification requirements that are needed for that boundary.

## Minimum hard constraints

| Constraint | Why it remains |
|------------|----------------|
| Package operations grant no authority | Availability and enablement are independent from access, promotion, approval, and execution. |
| Distributed bytes have an exact digest and provenance | A consumer must know which bytes it received and who produced them. |
| Published contracts are versioned | A cross-release consumer must be able to identify the contract it is decoding. |
| Distributed evidence records freshness | Old evidence cannot silently become current operational truth. |
| Every selected artifact profile declares dependency closure | Missing artifacts stay explicit rather than failing during installation. |
| Offline profiles use a signed root and no public fallback | A disconnected target needs an independent trust anchor and a closed artifact set. |
| State-change success requires independent effect verification | Packaging never weakens the constitutional execution boundary. |

The package policy requires a signed offline trust root, not a specific number of private signing
keys. Release tooling may use separate release and bundle keys as a stronger owner-selected
control. Consolidating or rotating those keys remains an explicit trust-root decision, never an
implicit package-assurance requirement.
Deployment CLI `0.1.1` makes that explicit owner decision only for its development profile: one
dedicated artifact key covers kit and bundle roles, the package admits only the development
channel, framework and license trust stay separate, and production TUF remains a separate owner gate.
That owner contract pins the exact Python ABI required by its wheels while treating the kit's glibc
version as a minimum compatibility floor. A newer glibc runtime is accepted; an older runtime,
another libc family, or a malformed identity remains blocked.
When an offline manifest requires the signed profile root, every derived transport archive carries
both root metadata and signature. A legacy manifest/signature pair cannot silently strip that
owner-required trust layer.

## Explicit package boundaries

Most `services/`, `packages/`, and `extensions/` entries are lockstep workspace code and therefore
need no entry. The policy lists only boundaries with an external consumer:

| Boundary | Minimum controls | Typical use |
|----------|------------------|-------------|
| `published-contract` | `versioned-contract` | Shared SDK or wire schema consumed by another release or process. |
| `distributed-artifact` | `exact-digest`, `provenance` | CLI, extension, image, or other artifact distributed outside the lockstep workspace. |
| `distributed-evidence` | `exact-digest`, `provenance`, `freshness` | Reviewed knowledge or evidence whose age affects operational claims. |

The checker validates ids, paths, optional manifests and facades, declared controls, and any
owner-supplied compatibility file. It does not hard-code package ids or require an exhaustive
inventory. Removing an entry means the surface returns to the workspace default; the owning build,
import, service, and architecture checks still apply.

## Dependency ownership

Each installable distribution owns its runtime dependencies in its own manifest. The repository
root and `uv.lock` coordinate the default development environment and may include dependencies
needed for cross-package test collection.

The package assurance gate no longer maintains a second mirror registry or requires root and owner
version ranges to be textually equal. The package manager, frozen lock, cold-import tests, image
builds, and service-owned dependency checks prove the selected environment. An independently
released package may keep its own lock or constraints when its release process needs one; a single
repository lock is a workspace default, not a constitutional rule.

## Compatibility ownership

Only a published contract is globally required to carry a stable version. N-1 compatibility,
translators, schema immutability, host ranges, and rollback windows are owner-selected contracts
when a deployed peer, retained data, or public consumer needs them.

The `fdai-service-contracts` package continues to use its compatibility manifest and rolling tests.
Cost Governance may continue to qualify an N-1 artifact rollback. The minimum package gate no
longer makes either policy mandatory for unrelated packages.

## Artifact profiles

| Profile | Required controls | Recommended or owner-selected controls |
|---------|-------------------|----------------------------------------|
| `connected` | Declared dependency closure, exact digests, provenance | Compatibility checks and SBOM |
| `offline` | Connected minimum plus signed root and no public fallback | Compatibility checks and SBOM |
| `appliance` | Offline minimum plus digest-pinned container | Compatibility checks and SBOM |

Recommended controls remain first-class release evidence, but omitting one does not fail the
minimum package gate. A release owner can promote a recommendation into that artifact's own
contract. The profile then declares and tests it explicitly.

## Controls returned to their owners

| Removed global package constraint | Authoritative owner |
|-----------------------------------|---------------------|
| Fixed install/enable/disable/revoke/reload/restart list | Capability Bundle Lifecycle and its operational claim |
| Per-capability promotion requirement | Promotion registry for each `ActionType` and `Workflow` |
| Cost Governance multi-target review semantics | Cost Governance review workflow and campaign |
| Optional readiness behavior | Independent runtime axes and capability composition |
| Core-to-extension import rules and facade shape | Independent-service and protected-path checks |
| Root dependency mirror list and range equality | Package manifests, package manager, lock, and owning tests |

This ownership split removes duplicated ceremony without weakening the underlying control.

## Validation

Run the focused policy check after changing the boundary configuration:

```bash
uv run python scripts/quality/architecture/check-package-assurance.py
uv run pytest -q --no-cov tests/integration/scripts/test_package_assurance.py
```

Artifact builders, contract compatibility suites, protected review workflows, deployment checks,
and runtime effect verification remain separate owning gates. Passing package assurance does not
claim a release, deployment, promotion, or operational outcome.

## Related docs

| To learn about | Read |
|----------------|------|
| Constitutional safety and authority | [FDAI Constitution](fdai-constitution.md) |
| Physical package and service ownership | [Multi-Service Repository Layout](multi-service-repository-layout.md) |
| Service graduation gates | [Service Graduation and Data Ownership](service-graduation-and-ownership.md) |
| Capability installation and revocation | [Capability Bundle Lifecycle](capability-bundle-lifecycle.md) |
| Runtime and package preference axes | [ADR-0002](decisions/0002-independent-runtime-axes.md) |
| Deployment artifact profiles | [Installable Deployment CLI](../deployment/installable-deployment-cli.md) |
