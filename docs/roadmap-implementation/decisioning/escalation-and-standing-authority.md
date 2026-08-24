# Escalation and Standing Authority (the supervised OODA loop) implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Durable shadow escalation supervisor | implemented | [`escalation_supervisor.py`](../../../services/core-control-plane/src/fdai/core/hil_resume/escalation_supervisor.py), [`test_escalation_supervisor.py`](../../../services/core-control-plane/tests/core/hil_resume/test_escalation_supervisor.py) | Bounded scans, delivery claims, and would-escalate observations are implemented without advancing approval or execution authority. |
| HIL resume and delegated-rung verification | implemented | [`coordinator.py`](../../../services/core-control-plane/src/fdai/core/hil_resume/coordinator.py), [`test_delegation.py`](../../../services/core-control-plane/tests/core/hil_resume/test_delegation.py) | Resume snapshots and rung eligibility are verified before the typed path continues. |
| Escalation ladder and urgency catalogs | in-progress | [`escalation_ladder.py`](../../../services/core-control-plane/src/fdai/rule_catalog/schema/escalation_ladder.py), [`test_escalation_ladder_catalog.py`](../../../services/core-control-plane/tests/rule_catalog/test_escalation_ladder_catalog.py), [`rule-catalog/escalation-ladders/`](../../../rule-catalog/escalation-ladders/README.md) | Reviewed ladder and urgency-policy instances ship with a fail-closed loader and pure schedule functions, and focused checks cover expiry, fallback delivery, starvation prevention, and deterministic replay. The supervisor does not yet read the catalog, and no measured urgency-compression evidence from a running cohort exists. |
| A3-E standing human authorization | in-progress | [`standing-authorization.json`](../../../services/core-control-plane/src/fdai/shared/contracts/authority/standing-authorization.json), [`record.py`](../../../services/core-control-plane/src/fdai/core/standing_authority/record.py), [`evaluator.py`](../../../services/core-control-plane/src/fdai/core/standing_authority/evaluator.py), [`test_evaluator.py`](../../../services/core-control-plane/tests/core/standing_authority/test_evaluator.py) | The catalog schema, the typed record, and the deterministic evaluator exist and reject every constitutional condition with an exact reason code. The evaluator is unwired by design and a focused test fails if a decision path imports it; `mode` accepts only `shadow`, so no promotion path exists. Silence never grants authority. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-19 | in-progress | Made the "every constitutional condition has a failing case" claim self-enforcing instead of hand-kept. The suite now reads every reason code the evaluator source can return through an AST scan and fails when one has no case. It immediately found one: `action_type_outside_envelope` was unreachable in the existing table because the pin check runs first, so an action type the envelope never allowed but a pin does allow had no test. That case now exists. This is the first artifact a promotion review would need; it is an offline decision cohort over synthetic delegations, not runtime shadow evidence. | `current change`; `tests/core/standing_authority` passed 40 focused cases; the exhaustiveness test is self-verifying - it failed with `reason codes with no case: ['action_type_outside_envelope']` before the missing case was added; task-scoped Ruff and format passed. | A governed runtime shadow cohort with zero envelope escapes, an independent promotion review, and a runtime revocation store all remain absent, so no decision path may consult the evaluator. |
| 2026-08-14 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance and corrected the prior broad status summary. | `current change`; current source, focused tests, and constitutional traceability listed in the scope table. | Deliver catalog-backed urgency and standing-authorization evaluation, then retain governed shadow evidence. |
| 2026-08-14 | in-progress | Shipped reviewed escalation-ladder and urgency-policy catalog instances with a fail-closed loader, deterministic first-match selection, and pure schedule functions. | `current change`; [`escalation_ladder.py`](../../../services/core-control-plane/src/fdai/rule_catalog/schema/escalation_ladder.py), [`test_escalation_ladder_catalog.py`](../../../services/core-control-plane/tests/rule_catalog/test_escalation_ladder_catalog.py); focused catalog checks passed 37 cases and the whole rule-catalog suite passed 1251 cases; strict mypy passed. | Bind the supervisor to the catalog and retain measured urgency-compression evidence from a governed shadow cohort. |
| 2026-08-18 | in-progress | Made A3-E executable without making it usable. `authority/standing-authorization.json` is the catalog schema, `record.py` parses and canonicalizes a document and rejects anything malformed instead of defaulting, and `evaluator.py` answers eligibility only when every constitutional condition holds, always naming the first failure. Absent, unparsable, or naive-clock input is ineligible rather than permissive. The schema admits only `mode: shadow` and only resource or resource-group scope, so neither enforce nor a wider blast radius can be expressed. Nothing consumes the evaluator, and a test parses the risk-gate, executor, HIL-resume, and control-loop trees and fails if any of them imports it. | `current change`; `tests/core/standing_authority` passed 38 focused cases covering one positive path plus a negative case per condition with its exact reason code; task-scoped Ruff, format, and strict mypy passed; the core import boundary gate passed. | Retain a governed shadow cohort with zero envelope escapes, then take an independent promotion review before any decision path may consult the evaluator. Revocation propagation and renewal-as-new-revision are represented in the schema but have no runtime store. |

### Remaining work

- [x] Reviewed escalation-ladder and urgency-policy catalog instances ship with a fail-closed
  loader, and focused checks cover expiry, fallback delivery, starvation prevention, and
  deterministic replay.
- [ ] Bind the escalation supervisor to the catalog and retain measured urgency-compression
  evidence from a running cohort.
- [ ] Implement the A3-E standing-authorization schema and evaluator with quorum, revocation,
  validity, responder confirmation, exact envelope, and no-self-approval negative tests.
- [ ] Retain a governed shadow cohort with zero envelope escapes before any independent promotion
  review; keep the supervisor observe-only until that evidence exists.
