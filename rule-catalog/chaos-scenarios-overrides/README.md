# Chaos Scenario Overrides

This fork-owned directory narrows parameters on scenarios declared under
[`../chaos-scenarios/`](../chaos-scenarios/). Upstream intentionally ships no active override.

## Override Contract

- The filename and scenario id identify an existing upstream scenario.
- An override may reduce impact, duration, target scope, or autonomy. It may not broaden the
  scenario, remove required evidence, weaken stop conditions, or bypass human approval.
- Omitted fields retain the upstream value. Historical scenario revisions and evidence remain
  immutable.
- A new scenario belongs in [`../chaos-scenarios-custom/`](../chaos-scenarios-custom/), not here.

The merge and validation rules live in
[`scenario_catalog.py`](../../services/core-control-plane/src/fdai/core/chaos/scenario_catalog.py).
See [`../chaos-scenarios/README.md`](../chaos-scenarios/README.md) for the canonical scenario
contract.
