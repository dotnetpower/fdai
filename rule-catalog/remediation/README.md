# `rule-catalog/remediation/`

Remediation templates referenced by each rule's `remediation.template_ref` in
[`rule-catalog/catalog/`](../catalog/). One template family per resource-type
folder - matches the [`policies/`](../../policies/) layout so a reviewer can
step from the deny rule to its remediation in a straight line.

## Layout

```text
remediation/
├── object_storage/
│   ├── disable_public_access.tftpl        # remediate.disable-public-access
│   └── tag_owner.tftpl                    # remediate.tag-add
├── compute/
│   └── vmss_right_size.tftpl              # remediate.right-size
├── secret_store/
│   └── rotate_secret.tftpl                # remediate.rotate-secret
└── sql_database/
    └── enable_tde.tftpl                   # remediate.enable-tde
```

## Template contract

- **Format** - Terraform `${var}` interpolation. Templates are pure text; the
  renderer substitutes `${...}` placeholders from `Action.params` at execution
  time. Missing placeholders fail the render (fail-closed).
- **Idempotent by construction** - every template represents the *target*
  state, not a diff. Re-rendering with the same inputs produces the same
  text, so a re-delivered event never authors a duplicate change.
- **Rollback pair** - the shadow PR body includes the prior desired-state
  revision, so a rollback is a follow-up PR that reverts the same block.
  This lives outside the template body (in the PR body renderer) so a
  template stays declarative.
- **No secrets, no customer values** - placeholders reference generic
  identifiers only (`resource_id`, `tag_name`, `sku`). Concrete values are
  supplied per-tenant at execution time via config + inventory adapter, per
  [generic-scope.instructions.md](../../.github/instructions/generic-scope.instructions.md).

## Consumption

The executor loads a template through
[`fdai.core.executor.renderer`](../../services/core-control-plane/src/fdai/core/executor/renderer.py),
substitutes safe `Action.params` values, and hands the rendered text to a
[`RemediationPrPublisher`](../../services/core-control-plane/src/fdai/shared/providers/remediation_pr.py)
adapter - which opens a **shadow-labeled draft PR** in P1. Actual merge is
gated off; phase-2 promotes an action to enforce after the shadow-mode
metrics clear the promotion gate declared on its `ActionType`.
