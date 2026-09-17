# FinOps Resource Efficiency implementation ledger

This delivery ledger tracks subscription analysis, resource-level SKU decisions, outcome settlement,
and the Console projection without treating shared FinOps foundations as proof that this capability
is implemented.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Subscription and resource analysis projection | implemented | `fdai_cost_governance/scheduled_analytics.py`; `cost_governance_analytics_snapshot`; `cost_governance_analytics_run`; additive projection evidence contract; focused contract, analytics, migration, runtime, and Operator tests | One scheduled local/deployed command records bounded run receipts, source windows, freshness, completeness, disclosure, and readiness facets. Complete resource relationships and live utilization coverage remain operational inputs. |
| Ontology profile and service-family sizing profiles | not-started | [Owner design](../../roadmap/architecture/finops-resource-efficiency.md#ontology-profile) | Existing shared declarations and metrics do not form the complete reviewed profile described by this design. |
| Resource and coupled-set decision composition | not-started | [Owner design](../../roadmap/architecture/finops-resource-efficiency.md#eligibility-and-agent-choreography) | No focused implementation proves the ordered target-set contract, fail-closed service mapping, or Njord and Freyr composition. |
| Generic right-size safety baseline | implemented | `services/core-control-plane/src/fdai/core/verticals/cost_governance/finops.py`; `services/core-control-plane/tests/core/verticals/test_finops.py`; `rule-catalog/action-types/remediate.right-size.yaml` | Generic guards and a shadow-first action contract exist, but they do not prove this end-to-end capability. |
| Savings attribution and multi-effect settlement | in-progress | additive settlement contract and PostgreSQL read projection; focused contract, persistence, Operator, and Console tests | The read path requires exact case/action revisions and independent effect statuses before publishing verified savings. No retained live settled resource-efficiency episode proves operational closure. |
| Cost Governance Console workspace | implemented | `console/src/routes/cost-governance*.tsx`; focused Vitest, typecheck, production build, and desktop/mobile Playwright state matrix | The four pages distinguish service summaries, resource candidates, cases, settlements, stale/partial sources, and below-rounding positive amounts. Live content remains limited by authoritative producer state. |
| Targeted human clarification | not-started | [Owner design](../../roadmap/architecture/finops-resource-efficiency.md#evidence-recovery-and-targeted-human-clarification) | No bounded flow proves automatic evidence recovery, scoped attestation, deterministic reevaluation, expiry, conflict, and approval separation. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-17 | in-progress | Ran the corrected local scheduled analytics path against the active authoritative Azure read identity and retained a current partial snapshot. | content-free receipt: `partial`, 212 observations, 7 trend points, 2 budgets, 32 recommendations, 0 utilization samples, limitation `utilization_partial`; no provider identity or payload retained in this ledger. | Restore compatible utilization evidence, then retain an authenticated standard-port Console read of the merged revision. |
| 2026-09-17 | implemented | Replaced the scheduled analytics Usage Details list read after a bounded live probe showed that its date-filtered request exhausted the two-minute attempt while the validated Cost Management Query endpoint remained available. | `current change`; failed content-free run receipt `source_unavailable`; bounded endpoint probes; shared Query request/decoder helpers; 36 focused package tests and strict mypy. | Retain a successful current analytics receipt after the merged source is running. |
| 2026-08-28 | not-started | Defined the focused resource-efficiency, SKU-decision, savings-attribution, and Console workspace design without claiming runtime delivery. | `current change`; owner document, Korean translation, design route, and focused documentation checks. | Implement and validate each bounded scope row below. |
| 2026-08-31 | in-progress | Added pseudonymous retained cost analytics from Usage Details, Budget, Advisor, and optional Monitor metrics, then wired the four-tab Console workspace to those projections. | `current change`; analytics contract, persistence migration, local collector, Operator projection, Console route; focused Python and Console tests, strict mypy, typecheck, build, and Playwright visual checks. | Complete Monitor utilization coverage and connect governed DecisionCase and independently settled outcome projections. |
| 2026-08-31 | in-progress | Bound enabled persisted Cost Governance activation into standard Pantheon bootstrap and published complete service-day observations through the canonical broker path. | `current change`; cost runtime composition, Njord resource-series correction, local collector publisher; focused Pantheon, Njord, package, composition, and live broker lag evidence. | Retain a live anomaly-to-verdict cohort and independently settled outcome before claiming operational validation. |
| 2026-09-17 | implemented | Added the shared scheduled analytics runtime, durable run receipts, source/readiness projection, safe below-increment disclosure, explicit observation-mode case and independent-settlement read models, and truthful four-page Console states. | `current change`; #1280; 225 focused Python tests, 22 focused Console tests, strict typecheck, production build, and eight desktop/mobile browser scenarios passed. | Apply the additive migrations, retain a current authoritative analytics run and live case/settlement evidence, then complete authenticated standard-port validation. |

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
- [x] Connect explicit stored DecisionCase, recovery, action-lineage, and independently settled
  outcome projections to the four-page workspace and exercise positive and negative states in
  focused browser tests.
- [ ] Retain live DecisionCase, approval, execution, rollback, and independently settled outcome
  records from the agent-owned runtime path on one exact evidence revision.
- [ ] Retain an observation-mode cohort with measured accuracy, zero policy escapes, zero objective
  regressions, complete terminal audit, and independently reviewed promotion evidence.
