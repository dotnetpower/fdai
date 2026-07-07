# ActionType overlays (fork-only)

File-based overlay layer for the ActionType catalog. Every `<name>.yaml`
here is deep-merged onto the upstream `../action-types/<name>.yaml`
before the pydantic model is validated. The overlay wins on every key
it declares; upstream stays for every key the overlay omits. Lists are
replaced wholesale (see the loader tests for the exact semantics).

**Upstream ships this directory empty** — the fork model in
[../../.github/instructions/generic-scope.instructions.md](../../.github/instructions/generic-scope.instructions.md)
says customer-specific tightening belongs in a downstream fork.
Overlay precedence lives at
[../../docs/roadmap/action-ontology.md § 7.5](../../docs/roadmap/action-ontology.md).

Example (a fork downgrading the `remediate.tag-add` T0 ceiling to HIL):

```yaml
name: remediate.tag-add
ceiling_by_tier:
  t0:
    max_autonomy: enforce_hil
```

Only include the fields you want changed. Omit `schema_version`,
`operation`, `promotion_gate`, etc. — those inherit from upstream.

Rules:

- The overlay file MUST declare `name` and it MUST match the upstream
  file. An orphan overlay (typo) is a fatal load error.
- Duplicate overlay `name` across two overlay files is a fatal load
  error.
- A file whose top level is not a mapping is a fatal load error.
- Lists in the overlay REPLACE the upstream list; there is no merge
  or concat semantics.
