# FinOps Resource Efficiency implementation ledger

This delivery ledger tracks subscription analysis, resource-level SKU decisions, outcome settlement,
and the Console projection without treating shared FinOps foundations as proof that this capability
is implemented.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Subscription and resource analysis projection | implemented | `fdai_cost_governance/scheduled_analytics.py`; `cost_governance_analytics_snapshot`; `cost_governance_analytics_run`; additive projection evidence contract; focused contract, analytics, migration, runtime, and Operator tests | One scheduled local/deployed command records bounded run receipts, source windows, freshness, completeness, disclosure, and readiness facets. Complete resource relationships and live utilization coverage remain operational inputs. |
| Ontology profile and service-family sizing profiles | implemented | `default_service_family_profiles`; `ServiceFamilyProfile`; focused optimization tests | Five reviewed provider-neutral profiles cover VM/VMSS, SQL/PostgreSQL, AKS node pools, App Service/Container Apps, and Storage with exact versions, digests, required metrics, evidence age, sample, utilization, headroom, and capacity bounds. Deployment thresholds may narrow these reviewed defaults. |
| Single-resource optimization decision composition | implemented | `ResourceOptimizationPlanner`; `FinOpsGuard`; 15 focused optimization tests | Deterministic right-size and shutdown planning fails closed, pins the exact profile revision, and grants no approval or execution authority. |
| Coupled-set decision composition | in-progress | `CoupledResourceOptimizationEvidence`; `ResourceOptimizationPlanner.plan_coupled`; `pantheon_composition.py`; focused tests | Complete membership, truncation, subscription scope, causal order, logical lock, idempotency, rollback, and every-member eligibility fail closed. Eligible right-size plans compose into the existing Njord candidate contract with exact target, profile, per-resource proposed configuration, freshness, objective-effect, causal-order, and logical-lock lineage; duplicate resource targets and oversized effects or freshness sources fail closed. Runtime Njord publication and full Freyr/Forseti/Odin case assembly remain open. |
| Generic right-size safety baseline | implemented | `services/core-control-plane/src/fdai/core/verticals/cost_governance/finops.py`; `services/core-control-plane/tests/core/verticals/test_finops.py`; `rule-catalog/action-types/remediate.right-size.yaml` | Generic guards and a shadow-first action contract exist, but they do not prove this end-to-end capability. |
| Savings attribution and multi-effect settlement | in-progress | additive settlement contract and PostgreSQL read projection; focused contract, persistence, Operator, and Console tests | The read path requires exact case/action revisions and independent effect statuses before publishing verified savings. No retained live settled resource-efficiency episode proves operational closure. |
| Cost Governance Console workspace | implemented | `console/src/routes/cost-governance*.tsx`; focused Vitest, typecheck, production build, and desktop/mobile Playwright state matrix | The four pages distinguish service summaries, resource candidates, cases, settlements, stale/partial sources, and below-rounding positive amounts. Live content remains limited by authoritative producer state. |
| Targeted human clarification | in-progress | `OptimizationClarificationRequest`; `OptimizationClarificationAttestation`; `evaluate_optimization_attestation`; focused tests | One content-addressed question requires bounded recovery references, exact target/scope, eligible role, response shape, expiry, conflict checks, and a reevaluation key without approval or execution authority. Automatic recovery orchestration and typed pipeline reinjection remain open. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-17 | in-progress | Ran the corrected local scheduled analytics path against the active authoritative Azure read identity and retained a current partial snapshot. | content-free receipt: `partial`, 212 observations, 7 trend points, 2 budgets, 32 recommendations, 0 utilization samples, limitation `utilization_partial`; no provider identity or payload retained in this ledger. | Restore compatible utilization evidence, then retain an authenticated standard-port Console read of the merged revision. |
| 2026-09-17 | implemented | Replaced the scheduled analytics Usage Details list read after a bounded live probe showed that its date-filtered request exhausted the two-minute attempt while the validated Cost Management Query endpoint remained available. | `current change`; failed content-free run receipt `source_unavailable`; bounded endpoint probes; shared Query request/decoder helpers; 36 focused package tests and strict mypy. | Retain a successful current analytics receipt after the merged source is running. |
| 2026-08-28 | not-started | Defined the focused resource-efficiency, SKU-decision, savings-attribution, and Console workspace design without claiming runtime delivery. | `current change`; owner document, Korean translation, design route, and focused documentation checks. | Implement and validate each bounded scope row below. |
| 2026-08-31 | in-progress | Added pseudonymous retained cost analytics from Usage Details, Budget, Advisor, and optional Monitor metrics, then wired the four-tab Console workspace to those projections. | `current change`; analytics contract, persistence migration, local collector, Operator projection, Console route; focused Python and Console tests, strict mypy, typecheck, build, and Playwright visual checks. | Complete Monitor utilization coverage and connect governed DecisionCase and independently settled outcome projections. |
| 2026-08-31 | in-progress | Bound enabled persisted Cost Governance activation into standard Pantheon bootstrap and published complete service-day observations through the canonical broker path. | `current change`; cost runtime composition, Njord resource-series correction, local collector publisher; focused Pantheon, Njord, package, composition, and live broker lag evidence. | Retain a live anomaly-to-verdict cohort and independently settled outcome before claiming operational validation. |
| 2026-09-17 | implemented | Added the shared scheduled analytics runtime, durable run receipts, source/readiness projection, safe below-increment disclosure, explicit observation-mode case and independent-settlement read models, and truthful four-page Console states. | `current change`; #1280; 225 focused Python tests, 22 focused Console tests, strict typecheck, production build, and eight desktop/mobile browser scenarios passed. | Apply the additive migrations, retain a current authoritative analytics run and live case/settlement evidence, then complete authenticated standard-port validation. |
| 2026-10-15 | implemented | Added a deterministic single-resource optimization planner with versioned service profiles, source-qualified evidence bounds, capacity and dependency guards, and authority-neutral right-size or shutdown candidates. | `current change`; `extensions/cost-governance/src/fdai_cost_governance/optimization.py`; `extensions/cost-governance/tests/test_optimization.py`; 15 tests, Ruff, and strict mypy passed. | Register reviewed family-specific profile assets, add coupled-target composition and targeted clarification, and retain a live settled cohort. |
| 2026-10-15 | in-progress | Added five reviewed family profiles, complete-metric and incompatibility checks, all-or-nothing coupled-target planning, and expiring scoped clarification attestations that remain separate from approval. | `current change`; Cost Governance optimization contracts and 22 focused tests; Ruff and strict mypy. | Bind Pantheon case composition, automatic evidence recovery, typed reevaluation, approval/execution, and live effect settlement. |
| 2026-10-15 | in-progress | Added an authority-free composer from eligible coupled right-size plans to the existing Njord-owned cross-vertical candidate payload. It requires a positive cost objective effect, exact target and profile digests, bounded source freshness, and caller-supplied effect lineage; shutdown remains held because no shared ActionType is registered. Candidate and profile lineage share one bounded ref so the maximum 20-member coupled plan stays inside Forseti's 32-ref intake ceiling. | `current change`; `pantheon_composition.py`; 6 focused tests pass the existing Forseti candidate validator and reject unsupported action, malformed or oversized lineage, invalid effects, and future source evidence. | Bind the composer behind Njord publication, then prove the complete Freyr/Forseti/Odin case and typed recovery path. |
| 2026-10-15 | implemented | Bound each coupled candidate to a canonical digest of its complete causal order and logical target lock, and reject incomplete membership before composition. | `current change`; `pantheon_composition.py`; 7 focused composer tests. | Runtime Njord publication and complete Freyr/Forseti/Odin case assembly remain open. |
| 2026-10-15 | implemented | Bound each candidate's resource identity, current and proposed capacity, action kind, and profile into canonical lineage; reject duplicate resource targets and bound effects and freshness-source inputs. | `current change`; `pantheon_composition.py`; 34 focused optimization and composer tests. | Runtime Njord publication and complete Freyr/Forseti/Odin case assembly remain open. |

### Remaining work

- [ ] Produce one exact-cutoff subscription fixture that proves included, excluded, inaccessible,
  stale, conflicting, and truncated resource and relationship coverage.
- [ ] Record supported utilization metrics for every resource-level Advisor candidate, or retain a
  typed per-resource limitation when the provider does not expose a compatible metric.
- [x] Implement a versioned service-family profile contract whose exact id, version, and digest
  replay the same single-resource sizing classification from the same evidence.
- [x] Register reviewed family-specific profile assets for the five declared first-release service
  families with exact versions, digests, and required metric sets.
- [x] Implement a bounded coupled-set contract with complete membership, causal order, one lock,
  one idempotency identity, tested rollback, and every-member eligibility.
- [x] Compose eligible coupled right-size plans into the existing Njord-owned candidate contract
  with exact target, profile, candidate, freshness, objective-effect, causal-order, and logical-lock
  lineage while granting no publication, approval, or execution authority.
- [ ] Prove resource and coupled-set cases through Njord, Freyr, Forseti, and Odin without creating
  a subscription-wide mutation or mutable `DecisionCase`.
- [x] Implement one scoped clarification request and expiring attestation contract after bounded
  recovery evidence, with deterministic conflict and approval-authority separation.
- [ ] Bind automatic evidence recovery, typed conversational reinjection, and deterministic
  reevaluation to the pinned `DecisionCase` revision.
- [ ] Close cost, capacity, SLO, dependency, and recovery effects as verified, failed, censored, or
  unscorable on one pinned action and evidence revision.
- [x] Connect explicit stored DecisionCase, recovery, action-lineage, and independently settled
  outcome projections to the four-page workspace and exercise positive and negative states in
  focused browser tests.
- [ ] Retain live DecisionCase, approval, execution, rollback, and independently settled outcome
  records from the agent-owned runtime path on one exact evidence revision.
- [ ] Retain an observation-mode cohort with measured accuracy, zero policy escapes, zero objective
  regressions, complete terminal audit, and independently reviewed promotion evidence.
