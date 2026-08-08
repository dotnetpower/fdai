# `rule-catalog/catalog/`

Normalized, version-pinned rule instances (catalog-as-code). One YAML file per
`Rule` instance; the filename mirrors the rule `id` for grep-ability.

Each file MUST validate against the JSON Schema at
[`services/core-control-plane/src/fdai/shared/contracts/rule/schema.json`](../../services/core-control-plane/src/fdai/shared/contracts/rule/schema.json)
(`additionalProperties: false`, `remediates` required) and pass the cross-reference
checks in
[`services/core-control-plane/src/fdai/rule_catalog/schema/rule.py`](../../services/core-control-plane/src/fdai/rule_catalog/schema/rule.py):

- `remediates` MUST resolve to a registered ActionType `name` under
  [`rule-catalog/action-types/`](../action-types/).
- Every entry in `alternatives` MUST resolve the same way.
- `resource_type` MUST be present in the canonical vocabulary
  [`rule-catalog/vocabulary/resource-types.yaml`](../vocabulary/resource-types.yaml).

The catalog has grown beyond the initial P1 seed and spans reliability, security, cost,
configuration, ownership, and operational-summary rules across supported resource types. Do not
use a README count as a completeness contract. The loader and cross-reference tests are the
authoritative inventory, and every rule still resolves its ActionType, resource type, policy or
check reference, and remediation template before it can enter deterministic evaluation.

- Storage layout: [docs/roadmap/rules-and-detection/rule-catalog-collection.md](../../docs/roadmap/rules-and-detection/rule-catalog-collection.md).
- Ontology dispatch: [docs/roadmap/architecture/llm-strategy.md § Rule as Ontology Artifact](../../docs/roadmap/architecture/llm-strategy.md).

New rules land through the collect -> shadow-eval -> regression -> promote/rollback pipeline
in [`rule-catalog/pipeline/`](../../services/core-control-plane/src/fdai/rule_catalog/pipeline/) (Phase 2); a
manual authored rule follows the same schema and cross-reference gates.
