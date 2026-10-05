---
title: Operator Governance Profiles
---
# Operator Governance Profiles

This document defines how an installation approves actions, promotes capabilities, and administers
approval and admission policy when one person or several people operate it. It owns the
single-operator production profile, attributed operator override promotion, and policy
administration in FDAI Console.

> **Status:** Partially implemented. The multi-operator profile and the full-authority development
> profile exist today. Core decision rules for the single-operator production profile, the runtime
> approval path through Forseti, Var, the HIL resume coordinator, and the Operator API callback,
> the single-operator standing authorization, `promotion_kind`, and the never-raising operator
> policy input are implemented. Policy administration in FDAI Console is planned. The
> [implementation ledger](../../roadmap-implementation/decisioning/operator-governance-profiles.md)
> tracks delivery. [ADR-0003](../architecture/decisions/0003-hub-managed-lifecycle-and-operator-governance.md)
> records the decisions.
>
> **Safety focus:** No profile in this document changes risk classes, A4 denial, the seven
> safeguards, independent effect verification, or the separation of the approval principal (Var)
> from the executor (Thor).

## Design at a glance

| Concern | Decision |
|---------|----------|
| Approval profiles | Multi-operator by default, single-operator production, and single-operator development (full-authority) |
| Single operator | One named operator satisfies every requester, approver, reviewer, and quorum requirement. The audit records the original quorum and an effective quorum of one. |
| Standing authorization | The single operator can approve it when they hold both the service-owner and Owner roles |
| Promotion | Evidence-gated by default. An authorized operator may also record an attributed override. |
| Policy administration | Approval and admission (OPA/Rego) policy is edited in FDAI Console and stored as immutable revisions |
| Hard bounds | Constitutional hard constraints and Release maximums can't be relaxed |

## Design and critique

**Initial design:** Keep the two-person rule for standing authorization, promote only after the
gate passes, and change policy only through signed bundles reviewed in Git.

**Critique:**

- Most installations have one operator, so two-person standing authorization is unusable there.
- Operators accept risk for their own installation and need to decide when a capability runs.
- Git-only policy changes are too slow for routine adjustments.
- Plain self-approval, however, would blur the line with the development profile and hide the
  reduced separation of duties.

**Revised contract:** Each profile is selected explicitly, the audit records the reduced quorum
honestly, overrides stay visible and recallable, and policy edits stay inside hard bounds.

## Approval profiles

| Profile | Selected by | Scope | Approver | Effective quorum | Standing authorization (A3-E) | Category denial |
|---------|-------------|-------|----------|------------------|-------------------------------|-----------------|
| Multi-operator | Default | Installation | Distinct humans. The requester is ineligible. | Configured, and at least two for irreversible actions | At least two distinct humans, including the service owner and an Owner | Unchanged |
| Single-operator production | Approval policy revision that names one operator | One installation | The named operator | One, with the original quorum recorded | The named operator, holding both roles | Unchanged. A4 still denies. |
| Single-operator development | Reviewed deployment configuration with an exact test scope and expiry | Dedicated test scope | The sole Owner | One, with the original quorum recorded | Not needed | No categorical prohibition |

[Risk Classification](risk-classification.md) owns the development profile.
[Escalation and Standing Authority](escalation-and-standing-authority.md) owns the standing
authorization contract that both production profiles use.

## Single-operator production profile

### Selection

- An approval policy revision declares `approval_profile: single-operator-production` and binds
  one normalized human principal from Microsoft Entra ID as the installation operator.
- Deployment composition supplies the active immutable `ApprovalProfileRevision` from
  `FDAI_APPROVAL_PROFILE_JSON` or `FDAI_APPROVAL_PROFILE_PATH`. `policy_digest` is
  content-addressed: it equals `sha256:` plus the SHA-256 of the canonical JSON, using sorted keys
  and compact separators, for `revision_id`, `approval_profile`, `executor_principal`,
  `effective_from`, and `operator_principal`. Malformed input, unknown fields, a missing or
  mismatched digest, a not-yet-effective `effective_from`, a named operator that equals the
  executor principal, or configuring it together with the full-authority development profile fails
  closed. When no revision is supplied, FDAI uses the multi-operator default.
- A change into or out of the profile follows the governance rule of the active profile. Moving
  from multi-operator to single-operator needs the multi-operator governance quorum. The single
  operator can move the installation back to multi-operator.

### What the operator can do

- Satisfy the requester, approver, reviewer, and quorum requirement of every approval in the
  installation.
- Approve a standing authorization when they hold the service-owner and Owner roles. The
  `standing-authority-promotion` change class accepts their single Owner approval as a recorded
  self-review with original quorum two and effective quorum one. Other governance change classes
  keep their existing quorum, role, phishing-resistant authentication, and no-self-approval rules
  unless this design explicitly changes them later.
- Promote with an attributed override and administer policy, as described in the next sections.

### What stays the same

- Each approval needs fresh phishing-resistant authentication and explicit confirmation of the
  exact action, target, revision, scope, and dry-run digest.
- Var and Thor stay distinct principals, and the operator never receives the executor credential.
- Risk classes and A4 denial still apply. An irreversible action still needs current approval for
  each execution and never qualifies for standing authorization. Chaos injection never runs under
  standing authorization.
- The seven safeguards, independent effect verification, and append-only audit still apply.
- Post-action review is still required. The audit records it as a self-review.

Audit entries carry `approval_profile`, `original_quorum`, `effective_quorum`, the operator
principal, and `self_review`, so a reviewer can always see the reduced separation of duties.

## Attributed operator override promotion

An installation operator with the promotion role may move an ActionType or Workflow from shadow
mode to enforce mode before its promotion gate passes. In the multi-operator profile, the
override follows the profile's governance quorum.

- **Preconditions:** The capability is registered and structurally valid. It declares all seven
  safeguards, isn't under a capability recall, and stays inside the Release's maximum mode. A
  Workflow composes only registered ActionTypes.
- **Path:** The override is a `governance` ActionType request that travels the normal typed
  pipeline. Forseti judges it, the operator's approval satisfies Var under the active profile, Thor
  applies the registry change, and Saga audits it.
- **Record:** The promotion registry stores `promotion_kind: operator_override`, the gate status
  at that time (passed, failed, or insufficient evidence) with its evidence digest, the operator,
  the reason, and the time. Every surface that shows the mode marks it as an operator override.
- **Runtime effect:** Promotion stays an upper bound. The risk gate, approval policy, and every
  per-execution check still apply.
- **Precedence:** Automatic regression demotion and a vendor capability recall override the
  promotion. A recalled capability can't be promoted again until a later Release lifts the recall.
- **Evidence:** An override receipt never counts as promotion evidence for another installation,
  for upstream claims, or for production readiness.

## Policy administration in FDAI Console

### Add-on and roles

A new product add-on, `policy-administration`, requires the `read-only-console` and
`enterprise-identity-governance` add-ons. Selecting it grants no authority. The customer assigns a
`policy-admin` App Role to the people who may edit policy. FDAI Console submits typed
policy-revision requests through the Operator API, which authenticates the principal and forwards
each request as a typed event. Mimir, the single writer of Policy, validates and activates every
revision. The Operator API never writes the policy store and never judges or executes a
managed-resource action.

### Editable policy

| Policy | Examples | Limit |
|--------|----------|-------|
| Approval policy | Approval profile, approver groups, quorum, escalation ladder rungs and deadlines | Quorum can't go below the catalog minimum in the multi-operator profile |
| Admission (OPA/Rego) policy | Installation rules that deny an ActionType, require approval, or allow it by scope, tag, time, or environment | Can't exceed the Release maximum for an ActionType |

### Validation and activation

1. The Operator API authenticates the principal, checks the `policy-admin` role and fresh
   authentication, and publishes a typed policy-revision request.
2. Mimir validates the schema, compiles the Rego in a restricted profile with bounded built-ins, no
   network access, and resource limits, and runs the policy tests that ship with the Release.
3. Mimir rejects any revision that exceeds a Release maximum for an ActionType.
4. In the multi-operator profile, a relaxing revision waits for the profile's governance quorum
   through Var, and a tightening revision applies immediately. In the single-operator production
   profile, every valid revision applies immediately.
5. Mimir stores the revision as immutable and content-addressed, signs it with a non-exportable
   installation policy key in Key Vault, and publishes it. The revision applies only to decisions
   that start after activation. Decisions already in flight keep their pinned policy digest for
   replay.
6. Saga records the author, diff digest, and validation results.
7. A rollback selects an earlier revision and creates a new revision with the same content.

Validation catches mistakes early, but it doesn't prove that arbitrary Rego is safe. The bound comes
from evaluation order instead. Core evaluates operator policy as one input and then applies the
constitutional hard constraints on its own: the seven safeguards, A4 denial, tenant and identity
boundaries, approver and executor separation, per-execution approval for irreversible actions, and
the Chaos rules. The combination never raises an outcome past those constraints or past a Release
maximum, so a revision can relax installation policy only inside them.

A Release upgrade re-validates every active revision against the new baseline inside the
installation. The installation reports a signed result that contains no policy content. If a
revision no longer compiles or exceeds a new maximum, the Hub holds the upgrade as a failed
constraint until the operator updates the revision.

## Data model

| Table | Key | Purpose | Time fields | Mutability |
|-------|-----|---------|-------------|------------|
| `approval_profile_revision` | `revision_id` | Profile, operator principal, author, digest | `effective_from`, `recorded_at` | Append-only |
| `policy_revision` | `revision_id` | Kind, content reference, digest, signature, parent, author, validation result | `created_at`, `activated_at` | Append-only |
| `policy_activation` | `policy_kind` | Current revision pointer with compare-and-set | `activated_at` | Revisioned |
| `promotion_record` | `record_id` | Capability, mode, `promotion_kind`, gate status, evidence digest, actor, reason | `recorded_at` | Append-only |

These tables live in the installation's PostgreSQL database. Mimir is the single writer of
`policy_revision` and `policy_activation`, and Thor writes `promotion_record` through the
`governance` ActionType. The Lifecycle Hub sees only digests.

## Honest limits

- The approval profile, the quorum reduction, and the operator policy input exist as Core decision
  rules in `fdai.core.risk_gate.approval_profile` and `evaluate_execution_authority`. Forseti, Var,
  the HIL resume coordinator, and the Operator API pass the active profile revision for HIL
  approvals. No `approval_profile_revision` or `policy_revision` table exists yet, and the active
  profile still comes from `FDAI_APPROVAL_PROFILE_JSON` or `FDAI_APPROVAL_PROFILE_PATH` rather than
  policy administration.
- The standing-authorization schema and evaluator accept one approval only under the
  single-operator production profile. The `standing-authority-promotion` change class doesn't
  accept the single Owner approval yet.
- The promotion registry records `promotion_kind`, honors a capability recall, and accepts an
  override only after an injected verifier confirms the Var approval receipt. The `governance`
  ActionType path that produces that receipt doesn't exist yet.
- The Operator API has no policy-revision routes, and no `policy-administration` add-on exists.
- The single-operator production profile reduces separation of duties by design. Customers that
  need it keep the multi-operator profile.

## Related docs

| To learn about | Read |
|----------------|------|
| Decision record | [ADR-0003](../architecture/decisions/0003-hub-managed-lifecycle-and-operator-governance.md) |
| Risk classes and the development profile | [Risk Classification](risk-classification.md) |
| Standing authorization contract | [Escalation and Standing Authority](escalation-and-standing-authority.md) |
| Promotion and approval integrity | [Security and Identity](../architecture/security-and-identity.md) |
| Operator API request boundary | [Console Operations](../interfaces/console-operations.md) |
| Authorization policy evaluation | [Execution Authorization Ontology](execution-authorization-ontology.md) |
| Delivery status and remaining work | [Implementation ledger](../../roadmap-implementation/decisioning/operator-governance-profiles.md) |
