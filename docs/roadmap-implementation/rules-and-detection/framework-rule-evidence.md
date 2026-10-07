# Framework Rule evidence from T0 implementation ledger

This delivery ledger tracks how activated catalog Rules become scope-bound evidence for framework
control assessments without duplicating the normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Ownership and event boundary | not-started | Design only | Forseti owns the `t0-rule-evaluator` producer; no new topic or agent. |
| Version 2 baseline completion | not-started | Design only | Full-inventory expected pairs derived independently of written outcomes; the Rule findings summary migrates to it. |
| Scoped Rule coverage contract | not-started | Design only | T0 dispatch parity, canonical pair keys, scope and activation pinning, ordered limitation codes. |
| Assessment-side activation pin | not-started | Design only | WAF profile or request pins activation generation and Rule catalog digests read from Mimir. |
| Receipt provenance fields | not-started | Design only | Activation generation, member Rule digest, coverage digest, inventory generation. |
| WAF Rule requirement producer | not-started | Design only | First scope: 8 WAF controls with 36 Rule requirements and 31 distinct Rule references. |
| Console Rule coverage view | not-started | Design only | Server-owned coverage and activation state; activation requests use the existing flow. |
| MCSB, CAF, and WARA adoption | not-started | Design only | Each needs its own assessment prerequisite before Rule evidence is decisive. |
| Azure Policy translation pilot | not-started | Design only | Starts only after the feasibility milestone. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-10-07 | not-started | Recorded the reviewed design after an independent critique of the draft plan. A second critique of the design aligned expected pairs with T0 dispatch, replaced the version 1 baseline denominator, added an assessment-side activation pin, and defined ordered outcome precedence. | `current change`; `docs/roadmap/rules-and-detection/framework-rule-evidence.md`; requirement and Rule reference counts from `rule-catalog/framework-assessments/generated/azure-waf.json`, MCSB and WARA counts from `rule-catalog/compliance/` and `rule-catalog/collected/wara-aprl/assessment/`. | Every row in the scope table. |

### Remaining work

- [ ] Review the Forseti baseline worker, read model, and Saga binding, and record that no topic or
  `AgentSpec` ownership changes.
- [ ] Add a version 2 baseline completion whose expected pairs are derived independently of the
  written outcomes, and move the Rule findings summary to it with focused Operator tests.
- [ ] Add versioned scoped coverage, the assessment-side activation pin, and receipt provenance
  models with focused tests that reject mixed scope, activation, and catalog identities.
- [ ] Add a focused dispatch parity test proving that expected pairs equal the pairs T0 evaluates
  through `RuleIndex.rules_for_signal` for the same activation generation.
- [ ] Add focused tests that prove every row of the ordered outcome table, including
  `duplicate_pair`, `conflicting_pair`, `unexpected_pair`, and `activation_catalog_drift`, plus
  deterministic replay.
- [ ] Record a complete local inventory generation in which the 8 WAF controls' Rule requirements
  produce `satisfied` or `failed` receipts.
- [ ] Show server-owned Rule coverage and activation state in the Controls view with a focused
  Playwright check.
- [ ] Meet the MCSB, CAF, and WARA prerequisites listed in the design before their Rule evidence
  becomes decisive.
- [ ] Pass the Azure Policy translation feasibility milestone before any translated candidate
  reaches the Mimir quality gate.
