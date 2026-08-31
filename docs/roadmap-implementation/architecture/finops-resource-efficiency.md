# FinOps Resource Efficiency implementation ledger

This delivery ledger tracks subscription analysis, resource-level SKU decisions, outcome settlement,
and the Console projection without treating shared FinOps foundations as proof that this capability
is implemented.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Subscription and resource analysis projection | in-progress | `scripts/deployment/local/collect-cost-governance-analytics.py`; `fdai_cost_governance/azure_analytics.py`; `cost_governance_analytics_snapshot`; focused analytics, migration, and Operator tests | Bounded Usage Details, Budget, Advisor, and supported Monitor evidence now produce a pseudonymous immutable snapshot. Complete resource relationships and utilization coverage remain open. |
| Ontology profile and service-family sizing profiles | not-started | [Owner design](../../roadmap/architecture/finops-resource-efficiency.md#ontology-profile) | Existing shared declarations and metrics do not form the complete reviewed profile described by this design. |
| Resource and coupled-set decision composition | not-started | [Owner design](../../roadmap/architecture/finops-resource-efficiency.md#eligibility-and-agent-choreography) | No focused implementation proves the ordered target-set contract, fail-closed service mapping, or Njord and Freyr composition. |
| Generic right-size safety baseline | implemented | `services/core-control-plane/src/fdai/core/verticals/cost_governance/finops.py`; `services/core-control-plane/tests/core/verticals/test_finops.py`; `rule-catalog/action-types/remediate.right-size.yaml` | Generic guards and a shadow-first action contract exist, but they do not prove this end-to-end capability. |
| Savings attribution and multi-effect settlement | not-started | [Owner design](../../roadmap/architecture/finops-resource-efficiency.md#savings-attribution-and-effect-settlement) | Shared outcome primitives exist, but no resource-efficiency flow closes cost, capacity, SLO, dependency, and recovery effects together. |
| Cost Governance Console workspace | in-progress | `console/src/routes/cost-governance*.tsx`; focused Vitest, typecheck, build, and four-tab Playwright visual checks | All four workspace layouts consume authoritative analytics or render explicit unavailable states. Governed DecisionCase and settled-outcome sources remain unconnected. |
| Targeted human clarification | not-started | [Owner design](../../roadmap/architecture/finops-resource-efficiency.md#evidence-recovery-and-targeted-human-clarification) | No bounded flow proves automatic evidence recovery, scoped attestation, deterministic reevaluation, expiry, conflict, and approval separation. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-28 | not-started | Defined the focused resource-efficiency, SKU-decision, savings-attribution, and Console workspace design without claiming runtime delivery. | `current change`; owner document, Korean translation, design route, and focused documentation checks. | Implement and validate each bounded scope row below. |
| 2026-08-31 | in-progress | Added pseudonymous retained cost analytics from Usage Details, Budget, Advisor, and optional Monitor metrics, then wired the four-tab Console workspace to those projections. | `current change`; analytics contract, persistence migration, local collector, Operator projection, Console route; focused Python and Console tests, strict mypy, typecheck, build, and Playwright visual checks. | Complete Monitor utilization coverage and connect governed DecisionCase and independently settled outcome projections. |
| 2026-08-31 | in-progress | Bound enabled persisted Cost Governance activation into standard Pantheon bootstrap and published complete service-day observations through the canonical broker path. | `current change`; cost runtime composition, Njord resource-series correction, local collector publisher; focused Pantheon, Njord, package, composition, and live broker lag evidence. | Retain a live anomaly-to-verdict cohort and independently settled outcome before claiming operational validation. |

### Remaining work

- [ ] Produce one exact-cutoff subscription fixture that proves included, excluded, inaccessible,
  stale, conflicting, and truncated resource and relationship coverage.
- [ ] Record supported utilization metrics for every resource-level Advisor candidate, or retain a
  typed per-resource limitation when the provider does not expose a compatible metric.
- [ ] Register reviewed service-family profiles whose exact ids, versions, and digests replay the
  same sizing classification from the same evidence.
- [ ] Prove a resource case and a coupled-set case through Njord, Freyr, Forseti, and Odin without
  creating a subscription-wide mutation or mutable `DecisionCase`.
- [ ] Prove that a decision-critical evidence gap attempts bounded recovery before one scoped
  question, records an expiring attestation, and keeps approval and execution authority separate.
- [ ] Close cost, capacity, SLO, dependency, and recovery effects as verified, failed, censored, or
  unscorable on one pinned action and evidence revision.
- [ ] Connect governed DecisionCase, approval, execution, rollback, and independently settled outcome
  projections to the implemented four-page workspace and exercise each state in focused browser tests.
- [ ] Retain an observation-mode cohort with measured accuracy, zero policy escapes, zero objective
  regressions, complete terminal audit, and independently reviewed promotion evidence.
