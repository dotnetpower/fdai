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

The five rules here quote the initial ActionType set (`remediate.disable-public-access`,
`remediate.tag-add`, `remediate.right-size`, `remediate.rotate-secret`,
`remediate.enable-tde`) so P1 W-2 exercises every ActionType at least once. The
Rego / IaC-patch templates the `check_logic.reference` / `remediation.template_ref`
fields point at are stubbed - the actual Rego bodies land with the T0 engine wiring in
P1 W-3.

- Storage layout: [docs/roadmap/rules-and-detection/rule-catalog-collection.md](../../docs/roadmap/rules-and-detection/rule-catalog-collection.md).
- Ontology dispatch: [docs/roadmap/architecture/llm-strategy.md § Rule as Ontology Artifact](../../docs/roadmap/architecture/llm-strategy.md).

New rules land through the collect → shadow-eval → regression → promote/rollback pipeline
in [`rule-catalog/pipeline/`](../../services/core-control-plane/src/fdai/rule_catalog/pipeline/) (Phase 2); a
manual authored rule follows the same schema and cross-reference gates.
