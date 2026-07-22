---
title: Override a rule
description: How to narrow, downgrade, or disable an accepted rule for a specific scope without editing the rule catalog itself.
---

# Override a rule

Sometimes an accepted rule is right in general but wrong for a specific
scope - a production tier that legitimately needs a wider threshold, a
dev sandbox where a strict guardrail is more annoying than useful. Rather
than editing the rule text (which affects everyone) or disabling the rule
globally, FDAI supports **scoped overrides** that sit above the
automated quality gate.

## What an override can do

Overrides are policy-as-code artefacts stored alongside the rule catalog.
An override on a rule at a given scope can do exactly one of:

- **`disabled`** - the rule stops executing on that scope. Detection still
  runs in shadow (the audit log continues to record what the rule *would*
  have flagged), so the discovery loop can spot recurring override patterns.
- **`severity-downgrade`** - the rule still fires but with a lower severity
  (e.g. `critical -> medium`). The safety check re-evaluates the resulting
  detected issue; an override can lower or suppress execution for its scope, but it
  cannot bypass a hard deny or raise autonomy.
- **`parameter-relaxation`** - a widening of a threshold the rule itself
  declares (e.g. cost anomaly `> 20%` becomes `> 40%`). Only the rule's
  declared parameters can be relaxed; the check logic cannot be rewritten.

Anything broader - a global disable across all scopes - is not an override.
It is a rule retirement and must go through the catalog pipeline with its
own review.

Overrides are downgrade-only controls. They never turn human approval into AUTO, DENY
into human approval, or shadow into enforce.

## Scope limits

**An override MUST be bounded to a `resource-group`-equivalent grouping or
narrower.** Wider overrides (subscription-wide, tenant-wide, organisation-
wide) are rejected by the promotion pipeline. If you need that breadth, you
are asking for a rule retirement.

Practically this means:

- Fine for a specific resource group.
- Fine for a single resource.
- Rejected for a whole subscription.

## What an override always needs

Every override, regardless of mode, records:

- **Actor** - the operator raising the override.
- **Approver** - a distinct principal (no self-approval).
- **Justification** - the reason this scope is different. This text is
  audited and surfaces on any human approval request that the override would touch.
- **Target rule + scope + mode** - machine-readable so the discovery loop
  can find the entry.

Overrides may be long-lived. They are not required to carry an expiry, but
recurring or long-lived overrides on the same rule are treated by the
discovery loop as a signal to propose a revision of the rule itself.

## What an override does *not* suppress

- **The audit record.** Every detected issue that the override intercepted is
  still logged with the reason it was suppressed. Overrides never make an
  event invisible; they change what FDAI does about it.
- **Rule updates from upstream.** Because the override is a separate
  artefact, upstream rule updates flow through without touching the
  override.

## How to raise one

1. Confirm the rule id and the current decision (the audit log has both).
2. Draft the override artefact (mode, scope, justification) in the same
   repo you edit rules in.
3. Open a PR. The reviewer must not be you.
4. On merge, the override takes effect the next time the affected event
   fires. The audit log shows both the underlying detected issue and the override
   intercepting it.

## Verify the override

After the PR merges, verify one fresh evaluation in the target scope:

1. Confirm the audit entry names the expected rule ID, override ID, mode, and
  bounded scope.
2. Confirm detection still records the underlying detected issue, including for a
  `disabled` override.
3. Confirm the resulting severity, parameters, or execution suppression match
  the override without raising autonomy.
4. Confirm a neighboring resource outside the scope still receives the normal
  rule behavior.

If the override does not match, remove or correct the separate override
artifact. Do not edit the source rule to make the local exception appear to
work.

## When to retire the rule instead

If you find yourself raising the same override on the same rule for many
scopes, that's the discovery loop's job - but it is also a signal that the
rule itself may need a revision. Rather than accumulate overrides, open a
PR against the rule catalog with the revised parameters and let it flow
through the quality gate the same way any rule change does.

## Next steps

| To learn about | Read |
|----------------|------|
| What severity and auto/human approval/DENY mean at execution | [../concepts/risk-tiers.md](../concepts/risk-tiers.md) |
| How to see whether your override is taking effect | [read-audit-log.md](read-audit-log.md) |
| The exemption workflow (owner-approved, time-boxed) | [../../runbooks/exemption-workflow.md](../../runbooks/exemption-workflow.md) |
| The full Human Override design | [../../../.github/instructions/architecture.instructions.md](../../../.github/instructions/architecture.instructions.md) |
