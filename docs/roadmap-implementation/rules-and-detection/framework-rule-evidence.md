# Framework Rule evidence from T0 implementation ledger

This delivery ledger tracks how activated catalog Rules become scope-bound evidence for framework
control assessments without duplicating the normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Ownership and event boundary | not-started | Design only | Forseti owns the `t0-rule-evaluator` producer; no new topic or agent. |
| Version 2 baseline completion | not-started | Design only | Full-inventory expected pairs derived independently of written outcomes; the Rule findings summary migrates to it. |
| Scoped Rule coverage contract | in-progress | `services/core-control-plane/src/fdai/core/framework_rule_evidence/coverage.py`; `services/core-control-plane/tests/core/framework_rule_evidence/` | Pure coverage with T0 dispatch parity, canonical pair keys, workload projection, and every activation member accounted for. Forseti persistence and Saga binding are not started. |
| Assessment-side activation pin | in-progress | `FrameworkRuleActivationPin` in `services/core-control-plane/src/fdai/core/framework_assessment/models.py`; Rule admission in `runtime.py` | Admission rejects unpinned, unprovenanced, and mismatched Rule receipts. The assessment job doesn't yet read Mimir's current generation. |
| Receipt provenance fields | implemented | `FrameworkRuleProvenance` and receipt `limitations` in `models.py`; limitation merge in `runtime.py`; focused tests | Receipts carry activation, member Rule digest, and coverage digest; limitation codes surface in requirement results. |
| WAF Rule requirement producer | in-progress | `services/core-control-plane/src/fdai/core/framework_rule_evidence/receipts.py` | The ordered outcome table builds receipts for all 36 Rule requirements in 8 WAF controls. The Forseti baseline worker that calls it is not started. |
| Console Rule coverage view | not-started | Design only | Server-owned coverage and activation state; activation requests use the existing flow. |
| MCSB, CAF, and WARA adoption | not-started | Design only | Each needs its own assessment prerequisite before Rule evidence is decisive. |
| Azure Policy translation pilot | not-started | Design only | Starts only after the feasibility milestone. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-10-07 | in-progress | Implemented the pure Rule evidence core: T0-dispatch expected pairs, scoped coverage that accounts every activation member, the ordered outcome table, Rule receipt provenance and limitation codes, and the assessment-side activation pin enforced at admission. Fixed a defect found by the tests where an activated Rule with no eligible resource looked not activated. | `current change`; `services/core-control-plane/src/fdai/core/framework_rule_evidence/`; `services/core-control-plane/src/fdai/core/framework_assessment/{models,runtime}.py`; 13 new tests and 88 tests across framework assessment, Forseti baseline, CLI, Azure adapter, catalog, and Operator projection suites passed; new module branch coverage 99%; strict mypy, ruff, and core import checks passed. | Version 2 baseline completion, Forseti worker persistence with Saga binding, Mimir pin wiring, Console coverage, and later frameworks. |
| 2026-10-07 | not-started | Recorded the reviewed design after an independent critique of the draft plan. A second critique of the design aligned expected pairs with T0 dispatch, replaced the version 1 baseline denominator, added an assessment-side activation pin, and defined ordered outcome precedence. | `current change`; `docs/roadmap/rules-and-detection/framework-rule-evidence.md`; requirement and Rule reference counts from `rule-catalog/framework-assessments/generated/azure-waf.json`, MCSB and WARA counts from `rule-catalog/compliance/` and `rule-catalog/collected/wara-aprl/assessment/`. | Every row in the scope table. |

### Remaining work

- [ ] Review the Forseti baseline worker, read model, and Saga binding, and record that no topic or
  `AgentSpec` ownership changes.
- [ ] Add a version 2 baseline completion whose expected pairs are derived independently of the
  written outcomes, and move the Rule findings summary to it with focused Operator tests.
- [x] Added scoped coverage, the assessment-side activation pin, and receipt provenance with
  focused tests that reject foreign generations, non-member pairs, out-of-scope pairs, and
  mismatched activation pins (`services/core-control-plane/tests/core/framework_rule_evidence/`).
- [x] Added a dispatch parity test proving that expected pairs equal the pairs Forseti records
  through `record_baseline_evaluation` with the same Rule index.
- [x] Added focused tests for every row of the ordered outcome table, including
  `duplicate_pair`, `conflicting_pair`, `unexpected_pair`, and `activation_catalog_drift`, plus
  deterministic coverage replay.
- [ ] Persist versioned scoped coverage records from a Forseti baseline worker with Saga audit
  binding, and record a focused test that rejects mixed scope, activation, and catalog identities
  in the persisted record.
- [ ] Have the framework assessment job read `rule_activation` from Mimir's current generation
  independently of Forseti, with a focused CLI test.
- [ ] Record a complete local inventory generation in which the 8 WAF controls' Rule requirements
  produce `satisfied` or `failed` receipts.
- [ ] Show server-owned Rule coverage and activation state in the Controls view with a focused
  Playwright check.
- [ ] Meet the MCSB, CAF, and WARA prerequisites listed in the design before their Rule evidence
  becomes decisive.
- [ ] Pass the Azure Policy translation feasibility milestone before any translated candidate
  reaches the Mimir quality gate.
