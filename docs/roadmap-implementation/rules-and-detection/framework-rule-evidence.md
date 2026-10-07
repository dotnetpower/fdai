# Framework Rule evidence from T0 implementation ledger

This delivery ledger tracks how activated catalog Rules become scope-bound evidence for framework
control assessments without duplicating the normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Ownership and event boundary | implemented | `services/core-control-plane/src/fdai/agents/_framework/forseti_baseline_worker.py`; `services/core-control-plane/src/fdai/delivery/persistence/postgres_promoted_inventory_reader.py`; `services/core-control-plane/src/fdai/runtime/baseline_evaluation.py`; `tests/agents/test_forseti_baseline_worker.py` | Forseti's maintenance tick starts at most one bounded run per interval. The run claims each inventory observation and activation generation atomically and writes Forseti-attributed audit store entries. It never calls Saga and adds no topic, subscription, or `AgentSpec` change. |
| Version 2 baseline completion | implemented | `BaselineEvaluationCoverage` in `packages/service-contracts/src/fdai_service_contracts/baseline_evaluation.py`; `services/operator-service/src/fdai_operator_service/workflow_rule_projection.py`; `services/operator-service/tests/test_rule_findings_summary_admission.py` | Expected pairs come from the decision T0 index. The Rule findings summary reads only the latest version 2 pointer and reports incomplete coverage as not evaluated with its limitations. |
| Scoped Rule coverage contract | in-progress | `services/core-control-plane/src/fdai/core/framework_rule_evidence/coverage.py`; `services/core-control-plane/src/fdai/delivery/framework_rule_evidence_source.py` | The assessment job projects a verified complete version 2 baseline onto the workload, and each receipt carries the scoped coverage digest. A standalone persisted scoped coverage record is not implemented. |
| Assessment-side activation pin | implemented | `FrameworkRuleActivationPin` in `services/core-control-plane/src/fdai/core/framework_assessment/models.py`; `services/core-control-plane/src/fdai/delivery/framework_assessment_cli.py` | The assessment job reads the current Rule activation generation from the activation ledger independently of Forseti and pins it on the WAF profile. Admission rejects unpinned, unprovenanced, and mismatched Rule receipts. |
| Receipt provenance fields | implemented | `FrameworkRuleProvenance` and receipt `limitations` in `models.py`; limitation merge in `runtime.py`; focused tests | Receipts carry activation, member Rule digest, and coverage digest; limitation codes surface in requirement results. |
| WAF Rule requirement producer | in-progress | `services/core-control-plane/src/fdai/core/framework_rule_evidence/receipts.py`; `services/core-control-plane/tests/delivery/test_framework_rule_evidence_source.py` | A fixture inventory turns violated and compliant Rules into `failed` and `satisfied` WAF requirements end to end. A complete local inventory generation run is not recorded yet. |
| Console Rule coverage view | in-progress | `console/src/routes/best-practice-controls-detail.tsx`; `console/tests/e2e/rule-control-crosslinks.spec.ts` | Control detail lists each requirement's server-owned limitation codes, such as `rule_not_activated`. Per-Rule coverage counts are not shown. |
| MCSB, CAF, and WARA adoption | not-started | Design only | Each needs its own assessment prerequisite before Rule evidence is decisive. |
| Azure Policy translation pilot | not-started | Design only | Starts only after the feasibility milestone. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-10-07 | in-progress | Implemented the baseline trigger and version 2 coverage. Forseti's bounded worker reads the promoted inventory read-only, claims each observation and activation pair, and records dispatch-derived coverage with a latest pointer and status record. The Rule findings summary reads version 2 only. The WAF assessment job pins the activation and builds Rule receipts from a verified complete baseline. Control detail shows requirement limitation codes. Fixed a defect where Forseti digested the outcome set in evaluation order while readers sorted it. | `current change`; `forseti_baseline_worker.py`; `postgres_promoted_inventory_reader.py`; `runtime/baseline_evaluation.py`; `framework_rule_evidence_source.py`; `framework_assessment_cli.py`; `workflow_rule_projection.py`; focused suites passed: 15 worker, 8 runtime binding, 6 reader integration on local PostgreSQL, 20 findings summary, 5 workload projection, 11 assessment projection, 11 Console model tests, and 4 Playwright checks; strict mypy and ruff passed. | Persisted scoped coverage record, a complete local inventory run, per-Rule coverage counts in the Console, and later frameworks. |
| 2026-10-07 | not-started | Designed the baseline trigger after finding that no runtime path calls Forseti's baseline evaluation. A critique removed the proposed marker event (no ordering guarantee, fields dropped by Huginn), replaced the direct Saga binder call with Forseti-attributed audit store entries, and added an atomic claim per inventory observation and activation generation. | `current change`; `docs/roadmap/rules-and-detection/framework-rule-evidence.md#baseline-trigger`; `services/core-control-plane/src/fdai/agents/forseti.py` (`evaluate_baseline_generation` has no runtime caller). | Implement the bounded Forseti baseline worker and read-only reader. |
| 2026-10-07 | in-progress | Implemented the pure Rule evidence core: T0-dispatch expected pairs, scoped coverage that accounts every activation member, the ordered outcome table, Rule receipt provenance and limitation codes, and the assessment-side activation pin enforced at admission. Fixed a defect found by the tests where an activated Rule with no eligible resource looked not activated. | `current change`; `services/core-control-plane/src/fdai/core/framework_rule_evidence/`; `services/core-control-plane/src/fdai/core/framework_assessment/{models,runtime}.py`; 13 new tests and 88 tests across framework assessment, Forseti baseline, CLI, Azure adapter, catalog, and Operator projection suites passed; new module branch coverage 99%; strict mypy, ruff, and core import checks passed. | Version 2 baseline completion, Forseti worker persistence with Saga binding, Mimir pin wiring, Console coverage, and later frameworks. |
| 2026-10-07 | not-started | Recorded the reviewed design after an independent critique of the draft plan. A second critique of the design aligned expected pairs with T0 dispatch, replaced the version 1 baseline denominator, added an assessment-side activation pin, and defined ordered outcome precedence. | `current change`; `docs/roadmap/rules-and-detection/framework-rule-evidence.md`; requirement and Rule reference counts from `rule-catalog/framework-assessments/generated/azure-waf.json`, MCSB and WARA counts from `rule-catalog/compliance/` and `rule-catalog/collected/wara-aprl/assessment/`. | Every row in the scope table. |

### Remaining work

- [x] Implemented the bounded Forseti baseline worker with a read-only
  `PromotedInventoryGenerationReader`, an atomic claim, and audit store entries, with focused tests
  proving no Saga call, no duplicate audit on retry, and stale-claim resumption
  (`services/core-control-plane/tests/agents/test_forseti_baseline_worker.py`).
- [x] Added version 2 baseline coverage whose expected pairs come from T0 dispatch, and moved the
  Rule findings summary to it (`services/operator-service/tests/test_rule_findings_summary_admission.py`).
- [x] Added scoped coverage, the assessment-side activation pin, and receipt provenance with
  focused tests that reject foreign generations, non-member pairs, out-of-scope pairs, and
  mismatched activation pins (`services/core-control-plane/tests/core/framework_rule_evidence/`).
- [x] Added a dispatch parity test proving that expected pairs equal the pairs Forseti records
  through `record_baseline_evaluation` with the same Rule index.
- [x] Added focused tests for every row of the ordered outcome table, including
  `duplicate_pair`, `conflicting_pair`, `unexpected_pair`, and `activation_catalog_drift`, plus
  deterministic coverage replay.
- [ ] Persist a versioned scoped coverage record for each assessed workload, with a focused test
  that rejects mixed scope, activation, and catalog identities in the persisted record.
- [x] The framework assessment job reads the current activation generation independently of
  Forseti and pins it on the WAF profile
  (`services/core-control-plane/tests/delivery/test_framework_rule_evidence_source.py`).
- [ ] Record a complete local inventory generation in which the 8 WAF controls' Rule requirements
  produce `satisfied` or `failed` receipts.
- [ ] Show per-Rule coverage counts in the Controls view with a focused Playwright check.
  Requirement limitation codes, including `rule_not_activated`, are already shown
  (`console/tests/e2e/rule-control-crosslinks.spec.ts`).
- [ ] Meet the MCSB, CAF, and WARA prerequisites listed in the design before their Rule evidence
  becomes decisive.
- [ ] Pass the Azure Policy translation feasibility milestone before any translated candidate
  reaches the Mimir quality gate.
