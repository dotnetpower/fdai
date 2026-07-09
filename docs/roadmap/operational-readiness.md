---
title: Operational Readiness Review (dev-to-ops handoff gate)
---
# Operational Readiness Review (dev-to-ops handoff gate)

Before a dev-owned scope (a resource group, a workload, an environment) becomes
the operations team's responsibility, the **Operational Readiness Review** (ORR)
runs automatically: it evaluates the whole scope against the governance,
security, RBAC, and reliability rules that ops depends on, grounds each finding
in the exact rule that produced it, and returns one verdict - `clear`,
`needs_review`, or `blocked` - keyed to the ownership-transfer event. It is the
[deployment-preflight](deployment-preflight.md) pass and the
[assurance-twin](assurance-twin.md) posture assessment, composed into a single
handoff gate so nothing crosses the dev-to-ops boundary un-reviewed.

This closes a class of failures that a per-change review misses: a workload can
be individually compliant on every merge yet still arrive at ops with an
over-privileged managed identity, a guest principal holding Owner, no diagnostic
settings, or no backup - because no single change introduced the whole gap. The
ORR reviews the **accumulated posture of the scope at the moment of handoff**,
not one diff.

> **Customer-agnostic**: the trigger label, the required-rule set, and the
> severity that gates a handoff are all config or fork-supplied. Upstream ships
> the machinery and the generic ReadinessReport shape, never a customer's
> specific handoff policy
> ([generic-scope.instructions.md](../../.github/instructions/generic-scope.instructions.md)).

> **Where it sits**: the ORR is a **read-only review** built on the assurance
> twin. It holds no privileged identity and executes nothing. Every proposed fix
> still flows through `risk-gate -> executor -> delivery`, preserving the
> read-only surface rule in
> [app-shape.instructions.md](../../.github/instructions/app-shape.instructions.md).

## Why a distinct gate

The pieces already exist; what was missing is the **handoff as a first-class
milestone**. Three surfaces overlap but none of them, alone, is the dev-to-ops
gate:

| Existing surface | What it reviews | Why it is not the handoff gate |
|------------------|-----------------|--------------------------------|
| [deployment-preflight](deployment-preflight.md) | one deploy: can this change land in the target scope | scoped to a single `terraform apply` / remediation PR, not the accumulated posture |
| [assurance-twin](assurance-twin.md) proactive review | one change event: does this diff violate a rule | per-diff; a scope can pass every diff and still fail as a whole |
| [assurance-twin](assurance-twin.md) `PostureAssessmentReport` | the whole estate on demand | not bound to an ownership-transfer event; nobody is required to run it before ops takes over |

The ORR binds the whole-scope assessment to the ownership-transfer event and
makes it a required, audited, shadow-first gate.

## Where it sits in the loop

The ORR is triggered, not polled. When a scope is proposed for handoff, an
`ownership_transfer` signal enters `event-ingest`, is normalized like any event,
and drives one review pass:

```text
ownership_transfer signal
  -> event-ingest (normalize)
  -> assurance-twin: run every applicable rule over the scope projection
  -> deploy-preflight: run the feasibility probes over the scope
  -> compose -> ReadinessReport (clear | needs_review | blocked)
  -> blocked + enforce mode -> gate the handoff, route fixes to risk-gate/HIL
  -> audit (Saga)
```

Both inputs are **deterministic-first** (T0-flavored): static evaluation over
the twin projection resolves most findings; bounded, read-only probes confirm
the rest. Nothing in the pass mutates anything.

## Trigger

The `ownership_transfer` signal is the CSP-neutral event that starts the review.
It is emitted by whatever the fork wires as the handoff moment:

- a pull-request label (`ops-handoff-requested`) on the IaC repo, or
- a resource tag applied to the scope (`lifecycle-stage: handoff`), or
- an explicit operator request through the console (`request_ops_handoff`).

The signal carries the target scope (resource-group-equivalent or narrower, the
same scope hierarchy the [rule-governance](rule-governance.md) overrides use),
the submitter identity, and the target environment. It never carries a role or a
privileged token.

## Review dimensions

The ORR runs the full applicable rule set over the scope, but four dimensions
are the ones ops most depends on and that a per-change review most often misses:

| Dimension | Representative check | Sourced from |
|-----------|----------------------|--------------|
| `policy_guardrail` | disallowed resource types, public access, missing encryption | [rule-catalog-collection.md](rule-catalog-collection.md) |
| `identity_rbac` | over-privileged workload identity, guest holding Owner, standing privileged access, wildcard-action role, Owner-count over limit | the workload RBAC least-privilege rule pack (`managed-identity.role-assignment.*`, `subscription.role-assignment.*`, `resource-group.role-assignment.*`) |
| `reliability` | no backup / PITR, no diagnostic settings, no zone redundancy | catalog reliability rules |
| `dependency_ordering` | required links (private endpoint, NSG, diagnostic settings) present before handoff | [deployment-preflight](deployment-preflight.md) probe |

The `identity_rbac` dimension is the one the ORR adds that neither preflight nor
per-change review covered before: preflight's `identity_rbac` probe checks the
**executor's** permission to deploy, while the ORR checks the **workload's own**
least-privilege posture using the authored RBAC rules. See
[architecture.instructions.md § Rule Catalog](../../.github/instructions/architecture.instructions.md#rule-catalog).

## ReadinessReport

The pass assembles findings into a `ReadinessReport` - a generalization of the
`PostureAssessmentReport` ([assurance-twin.md](assurance-twin.md)) bound to an
ownership-transfer event. Each finding keeps the same three required parts:

- **evidence** - a CSP-neutral citation of the rule that produced it. A finding
  that cannot cite a source is a defect, the same rule the T2 verifier and the
  preflight probes follow.
- **severity** - `blocking` (gates an enforce-mode handoff) or `warning`
  (surfaces but never gates).
- **resolution** - how to clear it, mapped to a concrete remediation ActionType
  (for the RBAC dimension, `remediate.right-size-role`) or to guidance when no
  autofix exists.

### Verdict semantics

| Verdict | Meaning |
|---------|---------|
| `clear` | no findings |
| `needs_review` | findings exist but none is blocking (warnings only) |
| `blocked` | at least one blocking finding |

The report always records the **truthful** verdict. Whether that verdict *gates*
the handoff is a separate flag, `blocks_handoff`, true only when the ORR ran in
`enforce` mode - the same truthful-verdict / separate-gate split the
[deployment-preflight](deployment-preflight.md) `blocks_deploy` flag uses.

### Shadow-first

Every ORR ships in **shadow mode**: it reports blockers truthfully but
`blocks_handoff` stays `false`, so an unproven review can never wrongly stop a
real handoff on a false positive. Promotion to `enforce` is per-environment and
gated on a measured false-positive rate on the frozen scenario set, the same
promotion discipline the [ActionType contract](llm-strategy.md) and the
preflight probes apply.

## Action bridging

A `blocked` ORR does not just list problems. Each finding with an autofix carries
a **shadow remediation-PR proposal** built from the rule's remediation
ActionType, exactly as the assurance twin does. For the identity dimension that
is `remediate.right-size-role`, which narrows an over-broad grant to least
privilege; because RBAC changes carry a `resource_group` blast radius and
`AsymmetricRollback`, they route to HIL through
[risk-classification.md](risk-classification.md) and never auto-execute. The ORR
proposes; a human approves; the executor applies. The console and ChatOps remain
read-only surfaces.

## Environment promotion

The ORR is the enforcement point for environment promotion (dev -> staging ->
prod). The `ownership_transfer` signal carries the target environment, and the
gate tightens with it: a promotion into `prod` treats any `critical` finding as
blocking regardless of the profile default, reusing the prod-downgrade posture
that every mutating ActionType already declares
([risk-classification.md](risk-classification.md)). The environment model itself
is specified in [scope-expansion.md](scope-expansion.md); the ORR consumes it,
it does not define it.

## Module placement

The ORR introduces no new privileged surface and minimal new code: it composes
the existing `core/assurance_twin/` and `core/deploy_preflight/` subsystems and
adds a thin coordinator plus one normalized signal.

| Component | Responsibility |
|-----------|----------------|
| `ownership_transfer` signal | normalized event (scope + submitter + target environment) that triggers the review; emitted by a fork-wired handoff moment |
| `core/assurance_twin/report` | run every applicable rule over the scope projection (reused) |
| `core/deploy_preflight` | run the feasibility probes over the scope (reused) |
| ORR coordinator | compose the two into a `ReadinessReport`, apply the environment gate, set `blocks_handoff` |
| delivery intent | post the report as a Checks API annotation / console `ReadPanel`; attach shadow remediation-PR proposals |

The coordinator imports only `shared/` contracts and providers, like every other
core subsystem ([project-structure.md](project-structure.md#module-boundaries)).
It holds no cloud SDK and no privileged identity.

## Safety posture

- **Read-only review, gated execution**: the ORR and every finding are
  read-only; the only path to a mutation is a proposal that enters
  `risk-gate -> executor`, with the four safety invariants (stop-condition,
  rollback, blast-radius limit, audit entry) enforced there.
- **Approval and execution stay distinct**: a handoff is requested by the
  submitter and approved by a distinct principal (Var), never self-approved -
  the same no-self-approval rule the rest of the control plane holds.
- **Fail closed**: a stale twin (inventory freshness beyond `freshness_ttl`)
  refuses to certify a handoff rather than certify on stale state; an
  ungroundable finding abstains; an unproven review stays shadow.
- **Audited**: every ORR verdict, its `blocks_handoff` flag, the submitter, the
  approver, and the target scope are an append-only audit entry through Saga.

## Next steps

| To learn about | Read |
|----------------|------|
| The whole-graph review the ORR composes | [assurance-twin.md](assurance-twin.md) |
| The single-deploy feasibility pass it reuses | [deployment-preflight.md](deployment-preflight.md) |
| The RBAC least-privilege rules the identity dimension fires | [rule-catalog-collection.md](rule-catalog-collection.md) |
| The cross-agent workflow that runs the gate | [agent-workflows.md § 11](agent-workflows.md#11-operational-readiness-handoff) |
| The environment model the gate consumes | [scope-expansion.md](scope-expansion.md) |
| The risk classification each proposed fix resolves against | [risk-classification.md](risk-classification.md) |
