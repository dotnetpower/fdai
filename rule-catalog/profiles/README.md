# Rule Catalog Profiles

Profiles are named, versioned bundles that select and configure atomic rules for a deployment
posture. The shipped `baseline`, `recommended`, and `strict` profiles form an inheritance chain;
all included rules remain subject to their own promotion and authority gates.

## Contract

- `extends` composes upstream profiles deterministically and rejects cycles.
- A profile may select rules and narrow mode, severity, or supported parameters. It does not edit
  the underlying Rule or ActionType.
- Fork overlays belong in [`../profiles-overrides/`](../profiles-overrides/) and may not raise
  autonomy above the upstream declaration.
- A profile id is a stable governance reference. Renames require migration of deployment bindings.

[`ProfileRegistry`](../../services/core-control-plane/src/fdai/core/rule_catalog_profiles/registry.py)
loads, merges, and validates profiles against the shared
[`profile schema`](../../services/core-control-plane/src/fdai/shared/contracts/profile/schema.json).
