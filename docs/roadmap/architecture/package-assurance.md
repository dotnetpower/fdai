---
title: Package Assurance
---

# Package Assurance

This document assigns FDAI packages and distributable artifacts the smallest assurance contract
that matches their actual boundary. It keeps constitutional safety controls on effect-bearing and
independently released surfaces without imposing release ceremonies on internal lockstep code.

> **Authority boundary:** Package availability, installation, enablement, user access, action mode,
> approval, execution identity, and effect verification remain independent. A package operation
> never grants runtime authority.
>
> **Implementation ledger:** Delivery state and remaining evidence are tracked in the
> [Package Assurance implementation ledger](../../roadmap-implementation/architecture/package-assurance.md).

## Design at a glance

FDAI classifies each package or artifact by what crosses its boundary. The machine-readable policy
in [`config/package-assurance.json`](../../../config/package-assurance.json) records the
classification, while
[`check-package-assurance.py`](../../../scripts/quality/architecture/check-package-assurance.py)
prevents a lower-assurance class from weakening an effect-bearing, published-contract, or
knowledge-evidence boundary.

The level is a minimum assurance bundle, not a replacement for independent runtime axes. A package
can add a stronger compatibility scope, such as the Cost Governance N-1 artifact rollback
contract, without changing its effect-bearing classification.

## Revised design decision

**Initial design:** Apply independent release, N/N-1 compatibility, one complete signed kit, one
live lifecycle run, and one review request per target to every package-shaped surface.

**Critique:** That design confuses repository organization with process, trust, evidence, and
authority boundaries. It duplicates dependency declarations, makes connected delivery carry
offline-only content, and turns independent review decisions into repeated ceremony. The extra
work does not add safety for an internal library or authority-neutral metadata package.

**Revised design:** Classify the boundary first, then apply only the controls required by that
class. Customer-agnostic scope, artifact integrity, authority separation, exact-plan approval,
rollback, and independent effect verification remain unchanged where they apply.

## Assurance levels

| Level | Use it for | Required assurance |
|-------|------------|--------------------|
| `workspace-internal` | Code that stays inside one distribution and process | Owning tests and dependency checks. No independent release or N/N-1 obligation. |
| `lockstep-shared` | A separately packaged library released with its consumers | Own manifest, stable import surface, and lockstep tests. No rolling compatibility claim unless it crosses a deployed boundary. |
| `independent-contract` | Published SDKs and cross-process or durable wire contracts | Immutable published schemas, N/N-1 compatibility, translators, and producer-consumer evidence. |
| `effect-bearing` | Deployment tools or optional packages that can lead to durable state or managed-resource effects | Signed release, linked lifecycle evidence, per-capability promotion, rollback, approval separation, and independent effect verification. |
| `knowledge-evidence` | Reviewed knowledge or evidence packages | Signed content, provenance, freshness, review, retention, revocation, and independently observed activation. It does not inherit executor authority. |

A filesystem package boundary does not imply a new service. The
[service graduation gates](service-graduation-and-ownership.md) still decide whether a package
needs an independent process, identity, data owner, transport, and rollback plan.

## Dependency ownership

Each runtime dependency has one owning distribution manifest. The non-installable repository root
can mirror a dependency only when root test collection imports the owning package directly.

The policy records each permitted mirror with:

- the dependency name;
- the owning manifest;
- the root-test reason.

The checker compares the root and owner requirement ranges. An unlisted mirror or unsupported
version drift fails validation. A policy entry can permit a stricter root-test lower bound while
the owner keeps a wider supported runtime range; the root cannot widen beyond the owner. Workspace
members are checked separately against their own project name and version. This keeps the root
environment usable without turning duplicate text into a second source of truth.

## Compatibility scope

N/N-1 and immutable-schema requirements apply when a contract is:

- published for an independently released consumer;
- exchanged across a deployed process boundary; or
- retained durably and read by another release.

Internal lockstep records can change with their only consumer when no released peer or retained
data depends on the old shape. Moving an internal record into a cross-process, durable, or public
surface first changes its assurance level and establishes a versioned compatibility contract.

The `fdai-service-contracts` package remains `independent-contract`. Its published schemas,
compatibility manifest, generated views, and rolling-transition evidence remain unchanged.

## Signed artifact profiles

Each profile has its own complete trust closure. Connected source delivery is bound by protected
source identity and an approved exact-revision image manifest; it does not need an offline-kit
root. Offline delivery uses a signed deployment root that binds the exact legacy kit manifest.
An appliance wraps that verified offline closure in a separately attested container.

| Profile | Trust root | Complete closure |
|---------|------------|------------------|
| `connected` | Protected source revision and signed image manifest | Exact image and support manifests, compatibility, software bill of materials (SBOM), provenance, and immutable digests. A complete offline wheelhouse or provider mirror is not required. |
| `offline` | `deployment-root.json` and release signing root | The connected artifact controls plus every required wheel, binary, Terraform provider, runtime image, Console artifact, migration input, and no-public-fallback proof. |
| `appliance` | Verified offline root plus container attestation | The offline closure plus a digest-pinned container, embedded-kit binding, provenance, SBOM, and no-public-fallback entry point. |

New offline kits carry `deployment-root.json` and its detached signature. The root lists sorted,
unique kit profile names and binds the exact `offline-kit.json` bytes. Kit acquisition verifies the
root when present. New legacy-format manifests also mark the root as required, so removing both
root files cannot downgrade a new release into the fallback path. Older manifests without that
marker remain valid through the existing manifest and signature. This additive migration preserves
old releases while connected source delivery remains independent from offline-only artifact
construction.

## Linked lifecycle evidence

Install, enable, disable, revoke, reload, and restart evidence can come from separate bounded runs
when every receipt carries the same:

- artifact digest;
- release revision;
- environment identity; and
- audit correlation identity.

The evidence set must contain every required transition and preserve ordering, actor identity,
idempotency, and audit lineage. A missing or conflicting link keeps the lifecycle incomplete. A
single monolithic live run is accepted, but it is no longer the only valid proof shape.

## Multi-target review envelopes

One bounded review envelope can carry up to six Cost Governance target decisions. Each entry names
one package activation, `ActionType`, or `Workflow`, plus its own decision and rationale.

The batch recorder decomposes the envelope into existing single-target records. Stable child
request ids use the batch id, target kind, and target id, so a retry replays each target
independently. Every child retains its own campaign digest, reviewer, decision, rationale, evidence
references, and review time. Partial completion is explicit and safe to retry.

A review envelope has no approval, execution, or promotion authority. Later activation and
promotion remain separate target-specific transactions.

## Optional package readiness

Optional package state remains capability-scoped:

- an unavailable disabled package can leave the unrelated base runtime ready;
- an enabled package with a missing required binding fails closed for that capability;
- independently complete read, deny, and observation paths may continue;
- availability never enables a package; and
- enablement never raises action authority.

Readiness reports the unavailable reason instead of converting missing optional configuration into
a startup-wide failure. A dependency required by an enabled or effect-bearing path remains a hard
failure for that path.

## Extension package facades

An optional package can expose a documented authority-neutral facade for factories, resource
loaders, readiness types, and reviewed adapters. Public export changes discoverability only.

Core still cannot import an optional package. The composition root selects and binds the package,
and the existing dependency-direction checks enforce that boundary. Provider clients, judgment,
approval, execution identity, and promotion authority do not move into the facade.

## Controls that do not relax

Package assurance never relaxes these requirements:

- upstream artifacts stay customer-agnostic and free of credentials and tenant values;
- signed artifacts preserve exact digests, provenance, SBOMs, compatibility, and dependency
  closure;
- package activation stays separate from user access, `ActionType` and `Workflow` mode, approval,
  execution, rollback, and effect verification;
- every managed-resource or external state change keeps the seven autonomous-action safeguards;
- published cross-process and durable contracts remain versioned and compatible; and
- agent ownership, event-bus communication, single-writer state, and human-executor separation
  remain unchanged.

## Related docs

| To learn about | Read |
|----------------|------|
| Repository package and dependency ownership | [Project Structure](project-structure.md) |
| Service extraction gates | [Service Graduation and Data Ownership](service-graduation-and-ownership.md) |
| Capability installation and activation | [Capability bundle lifecycle](capability-bundle-lifecycle.md) |
| Signed deployment artifacts | [Installable Deployment CLI](../deployment/installable-deployment-cli.md) |
| Optional Cost Governance package | [Ontology-Grounded FinOps Package Architecture](finops-package-architecture.md) |
| Downstream extension seams | [Downstream Fork Guide](../fork-and-sequencing/downstream-fork-guide.md) |
