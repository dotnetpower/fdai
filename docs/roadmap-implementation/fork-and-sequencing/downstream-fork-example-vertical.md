# Fork Example Vertical: New Business Object End-to-End implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Shipped `ChangeSummary` reference scaffold | implemented | Six catalog, policy, and indexing artifacts linked by the owner; `services/core-control-plane/tests/verticals/test_change_summary_example.py`; focused checks (`6 passed`) | The upstream reference loads its ObjectType, LinkType, ActionType, rule, Rego policy, and remediation template; retains shadow and rollback invariants; indexes under `resource-group`; fires only for the explicit synthetic request marker. |
| Generic ObjectType rule targeting | implemented | `services/core-control-plane/src/fdai/shared/contracts/models/rule.py`; `services/core-control-plane/src/fdai/shared/contracts/rule/schema.json`; `services/core-control-plane/src/fdai/rule_catalog/schema/rule.py`; `services/core-control-plane/tests/rule_catalog/test_rule_target_object_type.py` (`5 passed`) | `Rule.target_object_type` and `SubmissionCriterionKind.OBJECT_TYPE_REGISTERED` allow rules to target arbitrary registered `ObjectType` declarations with fail-closed loader cross-reference validation while preserving backward compatibility for `ResourceType` rules. |
| `GovernanceProposal` downstream lifecycle walkthrough | not-applicable | `docs/roadmap/fork-and-sequencing/downstream-fork-example-vertical.md` | Apart from the separately tracked generic ObjectType targeting gap, the proposal, reviewer, publication, and read-panel flow is a procedural downstream design example, not an upstream executable capability or authority grant. |
| Downstream adapter, promotion, and operational evidence | not-applicable | `.github/instructions/generic-scope.instructions.md`; owner section 9 | A downstream distribution owns its business-object implementation, principals, deployment bindings, shadow evidence, promotion, rollback drill, and operational receipts. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-11-01 | implemented | Updated `RuleIndex` and `T0Engine` (`core/tiers/t0_deterministic/{index,engine}.py`) to index and dispatch rules over custom `target_object_type` instances directly and added `test_t0_engine_dispatches_rule_over_custom_target_object_type` (`7 passed`). | `current change`; `services/core-control-plane/src/fdai/core/tiers/t0_deterministic/{index,engine}.py`; `services/core-control-plane/tests/rule_catalog/test_rule_target_object_type.py` (`7 passed`). | Downstream distributions retain their own business-object runtime and promotion evidence. |
| 2026-08-24 | not-started | Adopted the delegated ledger; earlier provenance was not reconstructed. | current change; `docs/roadmap/fork-and-sequencing/downstream-fork-example-vertical.md`. | Assess bounded source and test evidence before raising any scope state. |
| 2026-09-12 | in-progress | Replaced the unassessed placeholder with the verified shipped `ChangeSummary` scaffold, retained the upstream generic ObjectType targeting gap, and separated the remaining design-only walkthrough plus downstream-owned operational evidence. | `current change`; focused change-summary example tests (`6 passed`); owner section 5.1 caveat; generic-scope boundary. | Design and implement generic ObjectType rule targeting upstream; downstream distributions retain their own lifecycle implementation and promotion evidence. |
| 2026-11-01 | implemented | Added `Rule.target_object_type` and `object_type_registered` submission-criterion support to the rule schema and catalog loader with fail-closed cross-reference validation against registered `ObjectType` declarations, and updated section 5.1 of the owner design. | `current change`; `services/core-control-plane/src/fdai/shared/contracts/models/rule.py`; `services/core-control-plane/src/fdai/shared/contracts/rule/schema.json`; `services/core-control-plane/src/fdai/rule_catalog/schema/rule.py`; `services/core-control-plane/tests/rule_catalog/test_rule_target_object_type.py`; `uv run pytest -q --no-cov services/core-control-plane/tests/rule_catalog/test_rule_target_object_type.py services/core-control-plane/tests/verticals/test_change_summary_example.py` (`11 passed`). | None for the upstream reference scaffold and generic ObjectType rule-targeting contract; downstream distributions own their business-object runtime and promotion evidence. |

### Remaining work

- [x] Verify the shipped six-artifact `ChangeSummary` scaffold with its focused catalog, policy,
  and indexing checks (`6 passed`), while leaving downstream implementation and promotion outside
  upstream scope.
- [x] Complete the upstream design for `Rule.target_object_type`, implement loader cross-reference
  validation for arbitrary registered ObjectTypes, and record passing schema and rule-loader tests
  (`test_rule_target_object_type.py`: `5 passed`) before removing the documented ResourceType
  workaround.
