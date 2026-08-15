# Baselines

Two distinct artifact kinds that share only the word "baseline". They keep
separate schemas, separate id namespaces, and separate stores, and neither is
ever loaded into the Rule catalog.

| Store | Kind | Schema | Loader |
|-------|------|--------|--------|
| [`configuration/`](configuration) | `config-baseline` | [`configuration_baseline.schema.json`](../../services/core-control-plane/src/fdai/rule_catalog/schema/configuration_baseline.schema.json) | `load_configuration_baseline_catalog` |
| [`measurement/`](measurement) | `measurement-baseline` | [`measurement_baseline.schema.json`](../../services/core-control-plane/src/fdai/rule_catalog/schema/measurement_baseline.schema.json) | `load_measurement_baseline_catalog` |

Both loaders live in
[`baseline_catalog.py`](../../services/core-control-plane/src/fdai/rule_catalog/schema/baseline_catalog.py)
and are fail-closed: one invalid document fails the whole store, so a partially
valid store never reaches an evaluator. A missing directory loads as empty.

The design contract is
[rule-catalog-collection.md](../../docs/roadmap/rules-and-detection/rule-catalog-collection.md).
