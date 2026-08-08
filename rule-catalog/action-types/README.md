# `rule-catalog/action-types/`

Catalog-as-code ActionType instances referenced from rules'
`remediates` field.

Every YAML file validates against the JSON Schema at
[`services/core-control-plane/src/fdai/shared/contracts/ontology/action-type.json`](../../services/core-control-plane/src/fdai/shared/contracts/ontology/action-type.json)
and is loaded by
[`services/core-control-plane/src/fdai/rule_catalog/schema/action_type.py`](../../services/core-control-plane/src/fdai/rule_catalog/schema/action_type.py).

## Rules on adding an ActionType

1. `default_mode` MUST be `shadow` in the upstream repo (see
   [../../docs/roadmap/architecture/llm-strategy.md#actiontype-contract](../../docs/roadmap/architecture/llm-strategy.md#actiontype-contract)).
2. `promotion_gate` MUST specify measurable criteria - a shadow-mode
   ActionType is not promotable without them.
3. `rollback_contract` MUST NOT be `none`; the enum
   (`pr_revert` / `scripted` / `pitr` / `snapshot_restore` /
   `state_forward_only`) is exhaustive. Genuinely one-way mutations set
   `irreversible: true` and let risk-classification route them HIL+quorum.
4. Each ActionType is added via a governance PR reviewed by
   `aw-approvers` with the same quorum rules as risk-classification.
