---
title: ADR-0002 Independent Runtime and Customization Axes
---
# ADR-0002: Independent Runtime and Customization Axes

This record separates the configuration axes that determine where FDAI runs, what evidence it
reads, who may act, whether an action may execute, and how a downstream distribution is customized.
It prevents `local`, `dev`, `shadow`, and `fork` from becoming aliases for one another.

## Status

**Accepted:** 2026-07-20.

## Context

Earlier design text coupled several independent concerns. Local development sometimes implied
test fakes or shadow-only behavior. A downstream fork was often described as a production or
customer environment. Authentication flags also mixed the browser operator, Azure data access,
and the privileged executor.

Those shortcuts make production-parity debugging impossible and hide authorization defects. They
also prevent a fork from representing what it actually is: a distribution that limits or extends
capabilities without deciding where or how that distribution runs.

## Decision

FDAI treats the following axes as independent configuration:

| Axis | Representative values | Authority |
|------|-----------------------|-----------|
| Execution venue | `local`, `deployed` | process launcher |
| Deployment environment | `dev`, `staging`, `production` | deployment configuration |
| Evidence profile | `authoritative`, `fixture` | composition root |
| Action lifecycle | `shadow`, `enforce` | promotion registry per ActionType and Workflow |
| Human identity | Entra principal plus App Roles | browser token and RBAC policy |
| Executor identity | managed workload identity | deployed executor boundary |
| Distribution | `upstream`, `fork` | source and customization boundary |
| Operational safety profile | `mscp-operational-v1` | versioned core policy; never an execution authority |

No value on one axis selects a value on another axis. In particular:

- Local execution does not force shadow mode, test fixtures, anonymous authorization, or local-only
  business logic.
- A development deployment may run promoted actions in enforce mode when the same production risk,
  approval, blast-radius, rollback, and audit gates pass.
- A production deployment may keep any action in shadow mode.
- A fork may have zero or many deployments in any environment. Upstream may also be deployed
  directly.
- Fork detection protects the upstream framework surface. It never changes runtime behavior,
  autonomy, identity, or environment.
- The operational safety profile is venue-, environment-, evidence-, lifecycle-, identity-, and
  distribution-neutral. Its checks may only preserve or lower an existing autonomy decision.

### Interactive local profile

The default interactive local profile is a production-parity control-plane client and runtime:

- The browser uses the same Entra JWT and App Role checks as deployment.
- Azure CLI credentials are confined to local Azure provider adapters that read the development
  data plane. They never replace the browser principal or the executor identity.
- The same agent pantheon, catalogs, promotion registry, risk gate, Process journal, and stage
  events run locally.
- Pantheon startup is default-on. An unset `FDAI_START_PANTHEON` enables all agents; only an
  explicit false value disables them. Event Hubs configuration selects the Azure transport, not
  whether the runtime exists. Without Event Hubs, a local in-process EventBus carries agent
  messages and status while Azure evidence remains unavailable.
- Privileged execution remains behind Thor's deployed managed identity. A local process publishes
  a governed command to the development event bus; it does not execute with the developer's token.
- Missing authoritative providers render unavailable or fail closed. They never select fixtures.

Automated tests and explicit mock applications may choose the `fixture` evidence profile. Offline
interactive work is limited to repository catalogs and reference screens and makes no runtime
claims.

### Shadow and promotion

Shadow-first remains a capability lifecycle invariant, not a development-environment policy. New
ActionTypes and Workflows start in shadow everywhere. After promotion evidence passes, every venue
observes the same authoritative lifecycle state. A local flag cannot promote an action, and local
execution cannot lower a risk or approval decision.

### Fork boundary

A fork is a downstream distribution customization boundary. It may:

- bind different implementations to upstream provider Protocols;
- add or remove capability, catalog, policy, and presentation overlays through supported seams;
- package a narrower or broader product profile while preserving upstream safety invariants.

Deployment values, environment names, tenant identifiers, secrets, and runtime promotion state are
deployment configuration. They may be supplied by a fork-owned deployment repository, but their
existence does not define a fork and a fork does not imply production.

## Alternatives considered

| Alternative | Reason not selected |
|-------------|---------------------|
| Keep local shadow-only | prevents end-to-end debugging of promoted behavior and RBAC |
| Give the local process executor privileges | collapses operator and executor identities |
| Treat every customer deployment as a fork | couples source distribution to tenancy and environment |
| Use instructions alone to preserve the axes | prose cannot deterministically block a conflicting edit |

## Consequences

- Local startup needs real Entra, Azure data-plane bindings, and a dedicated development consumer
  identity by default.
- Local and deployed decision snapshots can be compared for identical inputs and promotion state.
- Test fixtures require an explicit pytest or mock profile.
- Documentation and configuration keys must name the axis they control.
- Instruction and design-document routing needs a machine-readable manifest and edit-time gate.
- Existing `production fork`, `dev-mode fake`, and local shadow-only wording must be migrated.

## Evidence

- [Application Shape](../../../../.github/instructions/app-shape.instructions.md)
- [Dev/Deploy Parity](../../deployment/dev-and-deploy-parity.md)
- [User RBAC and Identity](../../interfaces/user-rbac-and-identity.md)
- [Operator-Initiated SRE and ARB](../../operations/operator-initiated-sre-and-arb.md)
- [Downstream Fork Guide](../../fork-and-sequencing/downstream-fork-guide.md)
- [`design-routes.json`](../../../../scripts/lib/design-routes.json)

## Next steps

| To learn about | Read |
|----------------|------|
| Azure platform baseline | [ADR-0001](0001-azure-day-zero-platform.md) |
| Runtime composition boundaries | [Project Structure](../project-structure.md) |
| ADR process | [Architecture Decision Records](README.md) |
