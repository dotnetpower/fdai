# Custom Chaos Scenarios

This fork-owned directory adds chaos or detection-validation scenarios without editing the
upstream catalog under [`../chaos-scenarios/`](../chaos-scenarios/). Upstream intentionally ships
no active custom scenario here.

## Fork Contract

- Add only new scenario ids. Use [`../chaos-scenarios-overrides/`](../chaos-scenarios-overrides/)
  to narrow an upstream scenario.
- Validate every entry against the scenario schema and the same signal, injector, evidence, and
  promotion gates as upstream scenarios.
- New scenarios start without enforcement authority. Human approval, promotion evidence, bounded
  impact, stop conditions, and recovery remain mandatory where applicable.
- Keep customer identifiers and raw operational evidence outside the repository.

The composition rules are implemented by
[`scenario_catalog.py`](../../services/core-control-plane/src/fdai/core/chaos/scenario_catalog.py).
See [`../chaos-scenarios/README.md`](../chaos-scenarios/README.md) for layout and validation.
