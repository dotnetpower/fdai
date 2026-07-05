# `policies/`

OPA / Rego policy-as-code.

Consumed by T0 (`src/aiopspilot/core/tiers/t0_deterministic/`) and by the T2 verifier
(`src/aiopspilot/core/quality_gate/`). Policies are data, not code paths — adding a
policy MUST NOT require an engine change.
