# Measurement baselines

Recorded KPI values for one reference agent on a frozen scenario set, compared
against the targets in
[goals-and-metrics.md](../../../docs/roadmap/architecture/goals-and-metrics.md).
One YAML document per baseline, `kind: measurement-baseline`, validated against
[`measurement_baseline.schema.json`](../../../services/core-control-plane/src/fdai/rule_catalog/schema/measurement_baseline.schema.json).

Ids live in their own `baseline.*` namespace so a measurement baseline can never
collide with a Rule id.

This repository never commits customer-measured values. Upstream ships this
store empty; real numbers are recorded at measurement time in the operating
environment that produced them.
