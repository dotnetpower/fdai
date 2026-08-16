# Configuration baselines

Hardened reference sets of control ids for one resource type, used by T0 drift
and what-if evaluation. One YAML document per baseline, `kind: config-baseline`,
validated against
[`configuration_baseline.schema.json`](../../../services/core-control-plane/src/fdai/rule_catalog/schema/configuration_baseline.schema.json).

`controls` lists control ids, not inline check logic. A baseline records what a
hardened reference set contains; the executable check stays in the Rule catalog.

Upstream ships this store empty. A fork or a collector run lands documents here
with grounded `provenance`. Do not commit tenant identifiers, endpoints, or any
customer-specific value.

This is the collected catalog artifact. The runtime drift snapshot is the
distinct `FrozenConfigurationBaseline` under
`services/core-control-plane/src/fdai/core/detection/`.
