# Fork profile overrides (fork-only)

File-based overlay layer for the profile catalog. Every `<profile-id>.yaml`
here is loaded AFTER the upstream tree; when both trees declare the
same `id` the overlay wins.

**Upstream ships this directory empty** - the fork model in
[../../.github/instructions/generic-scope.instructions.md](../../.github/instructions/generic-scope.instructions.md)
says customer-specific tightening belongs in a downstream fork.

Overlay recipes:

- **Rename**: create `<upstream-id>.yaml` here with a different `title`
  + `extends: [<upstream-id>]` (the loader treats overlay files with
  the same id as replacements, so keep the id stable and drop your
  changes on top).
- **Extend**: author a fresh profile with `extends: [strict]` and add
  your own rules / severity floors / parameters. Give it a fork-owned
  id (e.g. `acme-baseline`).
- **Disable a rule**: extend the parent and add
  `- id: <rule-id>` with `disabled: true` in your `rules` list.
- **Bind at composition root**: set `FDAI_PROFILE_ID=acme-baseline`
  in the fork's environment; the composition root resolves the
  registry and passes it to `ControlLoop`.

See [../../docs/roadmap/rule-catalog-profiles.md](../../docs/roadmap/rule-catalog-profiles.md)
for the full resolution algorithm and safety invariants.
