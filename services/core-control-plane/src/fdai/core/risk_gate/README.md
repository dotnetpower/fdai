# `src/fdai/core/risk_gate`

Risk classification per [risk-classification.md](../../../../docs/roadmap/decisioning/risk-classification.md).
First-match rule table; default is HIL. Enforces stop-condition, rollback,
blast-radius, and audit-log invariants.

Fail-closed blast radius: `BlastRadius.count` is optional. The ActionBuilder
always fills it, but a partial Action with `count=None` MUST NOT fail open - a
single-resource scope is inherently bounded and stays eligible, while any
broader scope (`resource_group` / `subscription`) with an unknown count routes
to HIL. This mirrors the defense-in-depth on missing `stop_condition` /
`citing_rules`.
