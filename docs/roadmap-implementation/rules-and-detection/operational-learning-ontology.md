# Operational Learning Ontology implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Migrated implementation notes

> **Implementation status (2026-08-01):** O0 through O7 core contracts and runtime injection seams
> are implemented. Immutable operational-case
> inputs compile allowlisted audit, action, response-outcome, and evaluation receipt facts into
> canonical sources, then the existing case-history writer seals `ACTION` and `INCIDENT` revisions.
> Muninn groups the sealed projections by failure fingerprint, and Norns emits balanced inert
> candidates through its existing consensus and rate limits. Operational T1 reuse requires current
> evidence, causal and Dynamic grades require authoritative receipts, and promotion requires a
> verified immutable O7 receipt. O3 now binds a deterministic frozen-scenario validator and an
> inert draft-PR publisher when its complete deployment configuration is available. O7 has a
> strict immutable-file evidence source, manifest-bound causal and unit verifiers, durable receipt
> sink, and one-shot measurement job. Heimdall now has a typed terminal ActionRun observation path
> and an Azure Container Apps `ops.scale-out` collector, while deployments still supply its signed
> context issuer, complete Forseti-owned lineage inputs, and action-specific live evidence. Mimir emits
> review outcomes on its owned rule topic, and Saga seals them on its owned audit topic.
> Reproduced semantic-retrieval failures enter through Huginn, become Heimdall-owned independent
> validation evidence audited by Saga, and are materialized by Muninn on the context-index topic.
> Norns persists challenger-only StateStore records with shadow audit and reuses the ordinary
> consensus and Mimir candidate guard. Raw query text and online ranking mutation remain excluded.

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| O0-O1 case contracts and projection | implemented | `services/core-control-plane/src/fdai/core/case_history/`; `core/operational_learning/eligible_outcome.py`; focused case and governed-loop tests | Immutable inputs retain the pinned release, exact source identity, cutoff, action, effect, audit lineage, completeness, synthetic status, and conflicts. |
| O2 cohort learning | implemented | `services/core-control-plane/src/fdai/core/operational_learning/patterns.py`; `services/core-control-plane/tests/agents/test_operating_pattern_learning_e2e.py`; `test_norns_operating_pattern.py` | Muninn seals bounded cohorts and Norns publishes only balanced, complete, fresh, conflict-free, non-synthetic-live candidates through consensus and the event bus. |
| O3 catalog compilation | implemented | `services/core-control-plane/src/fdai/core/operational_learning/catalog.py`; `services/core-control-plane/src/fdai/delivery/gitops_pr/catalog_validator.py`; `catalog_review.py`; `services/core-control-plane/src/fdai/runtime/operational_catalog_review.py`; focused O3 tests | Mimir independently revalidates case review records and the pinned release before deterministic replay, regression, policy checks, and content-addressed inert draft publication. Publication grants no authority. |
| O4 current-evidence T1 reuse | implemented | `services/core-control-plane/tests/core/tiers/t1_lightweight/test_contextual_reuse.py`; `tests/core/test_control_loop_t1_wire.py` | Missing, stale, changed, or unsafe current evidence holds for review without mutation. |
| O5-O6 Azure evidence bindings | validated | [Delivery plan](../../roadmap/rules-and-detection/operational-learning-ontology.md#delivery-plan); `services/core-control-plane/src/fdai/delivery/azure/operational_evidence.py`; focused delivery tests | Repository-recorded non-production AKS and read-only Azure drills provide the required operational evidence without a production claim. |
| O7 promotion measurement | implemented | `services/core-control-plane/src/fdai/core/measurement/operational_promotion.py`; `operational_promotion_runner.py`; `services/core-control-plane/src/fdai/delivery/measurement/{operational_promotion_evidence.py,operational_promotion_batch.py}`; `measurement_runner_cli.py`; `infra/modules/measurement-runners/`; focused O7 tests and Terraform validation | The exact-digest consumer, governed frozen-benchmark plus live-shadow batch producer, verifiers, durable receipt sink, and opt-in job are implemented. Action-specific live days, confidence samples, and authenticated runtime receipts remain operational evidence work. |
| Reviewed-replay promotion authority | implemented | `core/operational_learning/promotion_review.py`; `delivery/persistence/state_store_action_promotion.py`; `tests/agents/test_governed_learning_loop.py`; frozen `v2026.08` scenario | Only an independently approved exact candidate, package, replay, release, scenario set, and O7 evidence digest can move the authoritative registry. Restart revalidates attribution; duplicate, rollback evidence, release mismatch, and demotion remain fail-closed. |
| Evaluation-adapter case intake | deferred | [Benchmark adapter dormant status](../../roadmap/interfaces/benchmark-adapters.md#dormant-status) | No current EvaluationHost or adapter runtime can emit case inputs. The semantic golden dataset remains outside case history and learning. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-31 | implemented | Completed the bounded case-to-candidate-to-reviewed-promotion composition on one pinned release without granting authority from publication. | `current change`; focused Story #370 regression passed 119 cases, including the frozen `v2026.08` restart, duplicate, rollback, mismatch, and demotion scenario. | Retain action-specific live evidence and a governed deployment receipt before claiming operational validation. |
| 2026-08-14 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance. | `current change`; delivery-plan evidence and focused source/tests listed in the scope table. | Complete deployment bindings and O7 action-specific evidence thresholds. |
| 2026-08-21 | deferred | Corrected evaluation intake after the host integration was found absent from the current tree. Kept the new semantic golden dataset outside operational-case and promotion authority. | `current change`; benchmark adapter dormant-status decision; `eval/golden-dataset/`; focused dataset contract checks. | Reopen adapter intake only with a restored governed host and canonical case-input receipts. |
| 2026-08-23 | implemented | Bound O3 to the existing Rule loader, shadow evaluator, regression gate, and draft-only GitOps adapter. The published artifact is content-addressed and cannot activate its draft Rule or ActionType. | `current change`; `delivery/gitops_pr/{catalog_validator,catalog_review}.py`; `runtime/operational_catalog_review.py`; focused O3 tests passed. | Retain a governed draft-PR receipt from a configured deployment. |
| 2026-08-23 | in-progress | Added an exact-digest O7 evidence consumer, manifest-bound causal and unit verifiers, durable receipt persistence, and an opt-in `operational-promotion` Container Apps Job. | `current change`; `delivery/measurement/operational_promotion_evidence.py`; `delivery/measurement_runner_cli.py`; `infra/modules/measurement-runners/`; focused O7 tests and Terraform validation passed. | Implement the governed live-batch producer, then supply action-specific batches and close their observation and recurrence windows. |
| 2026-08-24 | implemented | Reconciled the one-to-many `expects` relationship with runtime lineage by preserving an ordered complete `expected_effect_refs` set and requiring one independent ObservedOutcome per effect. A singular-only stored record reads as one effect, dual-field ambiguity fails closed, and new writes use the plural field. | `current change`; `hypothesis_lineage.py`; `ActionOption.yaml`; focused lineage and operational-hypothesis competency checks passed 15 cases. | Supply the remaining real lineage properties and runtime producer before binding the projector. |

### Remaining work

- [x] Bind the O3 production validator and pull-request publisher. Focused compiler, Mimir,
  publisher, retry, audit, and idempotency checks prove the local end-to-end path; deployed PR
  evidence remains operational validation rather than implementation work.
- [ ] Bind the deployment-owned signed-context issuer and preserve the missing planning properties
  required by the Forseti-owned causal lineage projection. The exact-plan resolver, Heimdall typed
  producer, Azure scale-out collector, verified mailbox, O7 source, and receipt verifiers are
  implemented, but no runtime producer can yet materialize the complete lineage records.
- [x] Reconcile the catalog's one-to-many `expects` relationship with runtime lineage. New lineage
  writes require the ordered complete `expected_effect_refs` set and one independent outcome per
  effect. Singular-only stored records retain one-effect read compatibility, while simultaneous
  singular and plural fields fail closed. Focused catalog-backed tests preserve every selected
  option effect without choosing or fabricating one metric.
- [ ] Accumulate the O7 per-action live days, sample sizes, complete recurrence windows, Wilson bounds, and zero-escape evidence required for promotion review.
- [x] Complete [issue #370](https://github.com/dotnetpower/fdai/issues/370) with one pinned-release
  immutable case, event-bus candidate, independent review, and authoritative registry path.
- [ ] If evaluation host integration is reactivated, prove that adapter results enter only through
  canonical operational-case receipts and cannot treat golden-answer success as promotion evidence.
