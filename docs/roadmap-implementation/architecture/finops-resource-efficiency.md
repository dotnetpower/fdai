# FinOps Resource Efficiency implementation ledger

This delivery ledger tracks subscription analysis, resource-level SKU decisions, outcome settlement,
and the Console projection without treating shared FinOps foundations as proof that this capability
is implemented.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Subscription and resource analysis projection | not-started | [Owner design](../../roadmap/architecture/finops-resource-efficiency.md#analysis-scope-and-action-granularity) | No exact-cutoff subscription projection reports resource, relationship, cost, utilization, and omission coverage together. |
| Ontology profile and service-family sizing profiles | not-started | [Owner design](../../roadmap/architecture/finops-resource-efficiency.md#ontology-profile) | Existing shared declarations and metrics do not form the complete reviewed profile described by this design. |
| Resource and coupled-set decision composition | not-started | [Owner design](../../roadmap/architecture/finops-resource-efficiency.md#eligibility-and-agent-choreography) | No focused implementation proves the ordered target-set contract, fail-closed service mapping, or Njord and Freyr composition. |
| Generic right-size safety baseline | implemented | `services/core-control-plane/src/fdai/core/verticals/cost_governance/finops.py`; `services/core-control-plane/tests/core/verticals/test_finops.py`; `rule-catalog/action-types/remediate.right-size.yaml` | Generic guards and a shadow-first action contract exist, but they do not prove this end-to-end capability. |
| Savings attribution and multi-effect settlement | not-started | [Owner design](../../roadmap/architecture/finops-resource-efficiency.md#savings-attribution-and-effect-settlement) | Shared outcome primitives exist, but no resource-efficiency flow closes cost, capacity, SLO, dependency, and recovery effects together. |
| Cost Governance Console workspace | not-started | [Owner design](../../roadmap/architecture/finops-resource-efficiency.md#console-information-architecture) | The existing vertical route has no resource-efficiency, optimization-case, or settled-outcome projection. |
| Targeted human clarification | not-started | [Owner design](../../roadmap/architecture/finops-resource-efficiency.md#evidence-recovery-and-targeted-human-clarification) | No bounded flow proves automatic evidence recovery, scoped attestation, deterministic reevaluation, expiry, conflict, and approval separation. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-28 | not-started | Defined the focused resource-efficiency, SKU-decision, savings-attribution, and Console workspace design without claiming runtime delivery. | `current change`; owner document, Korean translation, design route, and focused documentation checks. | Implement and validate each bounded scope row below. |

### Remaining work

- [ ] Produce one exact-cutoff subscription fixture that proves included, excluded, inaccessible,
  stale, conflicting, and truncated resource and relationship coverage.
- [ ] Register reviewed service-family profiles whose exact ids, versions, and digests replay the
  same sizing classification from the same evidence.
- [ ] Prove a resource case and a coupled-set case through Njord, Freyr, Forseti, and Odin without
  creating a subscription-wide mutation or mutable `DecisionCase`.
- [ ] Prove that a decision-critical evidence gap attempts bounded recovery before one scoped
  question, records an expiring attestation, and keeps approval and execution authority separate.
- [ ] Close cost, capacity, SLO, dependency, and recovery effects as verified, failed, censored, or
  unscorable on one pinned action and evidence revision.
- [ ] Render the four Cost Governance workspace pages from authoritative projections with unavailable,
  empty, held, failed, rollback, and settled states.
- [ ] Retain an observation-mode cohort with measured accuracy, zero policy escapes, zero objective
  regressions, complete terminal audit, and independently reviewed promotion evidence.
