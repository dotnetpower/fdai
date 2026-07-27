---
title: Override a rule
description: How to narrow, downgrade, or disable an accepted rule for a specific scope without editing the rule catalog itself.
---

# Override a rule

Sometimes an accepted rule is right in general but wrong for one scope. A
production tier may legitimately need a wider threshold, or a dev sandbox may
find a strict guardrail more annoying than useful. Instead of editing the rule
text, which affects everyone, or disabling the rule everywhere, FDAI supports
**scoped overrides** that sit above the automated quality gate.

## What an override can do

An override is a policy-as-code artifact stored next to the rule catalog. On a
given rule and scope, it can do exactly one of these:

- **`disabled`**: the rule stops executing on that scope. Detection keeps running
  in observation mode, so the audit log still records what the rule would have
  flagged and the discovery loop can spot repeated override patterns.
- **`severity-downgrade`**: the rule still fires, but at a lower severity, for
  example `critical` becomes `medium`. The safety check re-evaluates the
  resulting detected issue. An override can lower or suppress execution inside
  its scope, but it cannot get around a hard deny or raise autonomy.
- **`parameter-relaxation`**: it widens a threshold the rule already declares,
  for example a cost anomaly at `> 20%` becomes `> 40%`. Only the rule's declared
  parameters can be relaxed. You cannot rewrite the check logic.

Anything broader, such as disabling a rule everywhere, is not an override. That
is a rule retirement, and it goes through the catalog pipeline with its own
review.

Overrides can only lower autonomy. They never turn human approval into automatic
execution, a denial into an approval request, or observation mode into
enforcement.

## Scope limits

**An override has to stay inside a resource-group-sized grouping or smaller.**
The promotion pipeline rejects anything wider, such as subscription-wide,
tenant-wide, or organization-wide. If you need that reach, what you actually want
is a rule retirement.

Practically this means:

- Fine for a specific resource group.
- Fine for a single resource.
- Rejected for a whole subscription.

## What an override always needs

Every override, regardless of mode, records:

- **Actor**: the operator raising the override.
- **Approver**: a different principal, because self-approval is not allowed.
- **Justification**: why this scope is different. The text is audited and shows
  up on any approval request the override would touch.
- **Target rule, scope, and mode**: machine-readable, so the discovery loop can
  find the entry.

An override can last a long time and does not need an expiry. However, when the
same rule keeps collecting overrides, or one override lives on for a long time,
the discovery loop treats that as a signal to propose revising the rule itself.

## What an override does not suppress

- **The audit record.** Every detected issue the override intercepted is still
  logged, along with the reason it was suppressed. An override never makes an
  event invisible. It changes what FDAI does about it.
- **Rule updates from upstream.** Because the override is a separate artifact,
  upstream rule updates flow through without touching it.

## How to raise one

1. Confirm the rule ID and the current decision. The audit log has both.
2. Draft the override artifact, meaning the mode, the scope, and the
   justification, in the same repository where you edit rules.
3. Open a pull request. The reviewer cannot be you.
4. Once it merges, the override takes effect the next time the affected event
   fires. The audit log then shows both the underlying detected issue and the
   override intercepting it.

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

If you keep raising the same override on the same rule for many scopes, the
discovery loop will notice. That is also a sign the rule itself needs a revision.
Rather than piling up overrides, open a pull request against the rule catalog
with the revised parameters and let it go through the quality gate like any other
rule change.

## Next steps

| To learn about | Read |
|----------------|------|
| What severity, auto, human approval, and deny mean at execution | [../concepts/risk-tiers.md](../concepts/risk-tiers.md) |
| How to see whether your override is taking effect | [read-audit-log.md](read-audit-log.md) |
| The exemption workflow, which is owner-approved and time-boxed | [../../runbooks/exemption-workflow.md](../../runbooks/exemption-workflow.md) |
| The full Human Override design | [../../../.github/instructions/architecture.instructions.md](../../../.github/instructions/architecture.instructions.md) |
