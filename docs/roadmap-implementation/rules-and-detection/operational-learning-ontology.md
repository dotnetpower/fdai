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
| O0-O1 case contracts and projection | implemented | `services/core-control-plane/src/fdai/core/case_history/`; `services/core-control-plane/tests/core/case_history/test_operational_case.py`; `test_service.py` | Immutable inputs, canonical fingerprints, negative outcomes, revisions, and persistence are covered. |
| O2 cohort learning | implemented | `services/core-control-plane/src/fdai/core/operational_learning/patterns.py`; `services/core-control-plane/tests/agents/test_operating_pattern_learning_e2e.py`; `test_norns_operating_pattern.py` | Muninn seals bounded cohorts and Norns emits only balanced inert candidates through consensus. |
| O3 catalog compilation | implemented | `services/core-control-plane/src/fdai/core/operational_learning/catalog.py`; `services/core-control-plane/src/fdai/delivery/gitops_pr/catalog_validator.py`; `catalog_review.py`; `services/core-control-plane/src/fdai/runtime/operational_catalog_review.py`; focused O3 tests | Complete configuration binds existing Rule schema validation, deterministic frozen replay, regression and policy checks, and a content-addressed inert draft PR. Missing or partial configuration stays unavailable or fails startup. |
| O4 current-evidence T1 reuse | implemented | `services/core-control-plane/tests/core/tiers/t1_lightweight/test_contextual_reuse.py`; `tests/core/test_control_loop_t1_wire.py` | Missing, stale, changed, or unsafe current evidence holds for review without mutation. |
| Scoped Pattern retention and current admission integration | in-progress | `agents/{norns,muninn}.py`; `core/operational_learning/cohort_retention.py`; `core/tiers/t1_lightweight/`; `delivery/azure/operational_evidence.py`; focused Pattern and composed T1 checks | Frozen snapshots, current-case checks, CAS, exact event/action admission, current-clock expiry, total deadlines, and Azure admission composition pass locally. Copied-data lifecycle, retained Pattern-to-T1 selection, and operational qualification are not complete. |
| O5-O6 Azure evidence bindings | validated | [Delivery plan](../../roadmap/rules-and-detection/operational-learning-ontology.md#delivery-plan); `services/core-control-plane/src/fdai/delivery/azure/operational_evidence.py`; focused delivery tests | Repository-recorded non-production AKS and read-only Azure drills provide the required operational evidence without a production claim. |
| Signed observation and complete lineage runtime | implemented | `services/core-control-plane/src/fdai/runtime/observation_evidence.py`; `delivery/{prospective_lineage,operational_lineage}.py`; focused runtime, agent-chain, and delivery tests | Complete deployed configuration binds the signed Heimdall observer. Forseti prospective records, Muninn materialization, Saga sealing, and terminal reconciliation preserve every selected expected effect without treating provider acceptance as observed success. Governed live receipts remain operational evidence. |
| O7 promotion measurement | implemented | `services/core-control-plane/src/fdai/core/measurement/operational_promotion.py`; `operational_promotion_runner.py`; `services/core-control-plane/src/fdai/delivery/measurement/{operational_promotion_evidence.py,operational_promotion_batch.py}`; `measurement_runner_cli.py`; `infra/modules/measurement-runners/`; focused O7 tests and Terraform validation | The exact-digest consumer, manifest verifiers, durable receipt sink, opt-in job, and governed batch producer are implemented. The producer requires immutable frozen-benchmark records and composes them with live-shadow records without changing promotion state. Action-specific observation days, confidence samples, and authenticated runtime receipts remain incomplete. |
| Governed case-to-promotion composition | implemented | `core/operational_learning/{eligible_outcome,patterns,catalog,promotion_review}.py`; `tests/agents/test_governed_learning_loop.py`; frozen `v2026.08` scenario | Exact source and receipt lineage is sealed into immutable cases, Norns and Mimir independently reject the complete negative matrix, candidate publication remains inert, and only independently reviewed replay can authorize the durable promotion registry. |
| Evaluation-adapter case intake | deferred | [Benchmark adapter dormant status](../../roadmap/interfaces/benchmark-adapters.md#dormant-status) | No current EvaluationHost or adapter runtime can emit case inputs. The semantic golden dataset remains outside case history and learning. |
| Reviewed-replay promotion authority | implemented | `core/operational_learning/promotion_review.py`; `delivery/persistence/state_store_action_promotion.py`; `tests/agents/test_governed_learning_loop.py`; frozen `v2026.08` scenario | Only an independently approved exact candidate, package, replay, release, scenario set, and O7 evidence digest can move the authoritative registry. Restart revalidates attribution; duplicate, rollback evidence, release mismatch, and demotion remain fail-closed. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-31 | implemented | Composed eligible outcomes, immutable cases, event-bus candidate publication, independent Norns/Mimir review, and reviewed-replay promotion on one pinned release. Publication remains authority-free; restart, duplicate, rollback evidence, release mismatch, and demotion stay fail-closed. | `current change`; focused Story #370 regression passed 119 cases, including the frozen `v2026.08` scenario. | Retain action-specific live evidence and a governed deployment receipt before claiming operational validation. |
| 2026-08-14 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance. | `current change`; delivery-plan evidence and focused source/tests listed in the scope table. | Complete deployment bindings and O7 action-specific evidence thresholds. |
| 2026-08-21 | deferred | Corrected evaluation intake after the host integration was found absent from the current tree. Kept the new semantic golden dataset outside operational-case and promotion authority. | `current change`; benchmark adapter dormant-status decision; `eval/golden-dataset/`; focused dataset contract checks. | Reopen adapter intake only with a restored governed host and canonical case-input receipts. |
| 2026-08-23 | implemented | Bound O3 to the existing Rule loader, shadow evaluator, regression gate, and draft-only GitOps adapter. The published artifact is content-addressed and cannot activate its draft Rule or ActionType. | `current change`; `delivery/gitops_pr/{catalog_validator,catalog_review}.py`; `runtime/operational_catalog_review.py`; focused O3 tests passed. | Retain a governed draft-PR receipt from a configured deployment. |
| 2026-08-23 | in-progress | Added an exact-digest O7 evidence consumer, manifest-bound causal and unit verifiers, durable receipt persistence, and an opt-in `operational-promotion` Container Apps Job. | `current change`; `delivery/measurement/operational_promotion_evidence.py`; `delivery/measurement_runner_cli.py`; `infra/modules/measurement-runners/`; focused O7 tests and Terraform validation passed. | Implement the governed live-batch producer, then supply action-specific batches and close their observation and recurrence windows. |
| 2026-08-24 | implemented | Reconciled the one-to-many `expects` relationship with runtime lineage by preserving an ordered complete `expected_effect_refs` set and requiring one independent ObservedOutcome per effect. A singular-only stored record reads as one effect, dual-field ambiguity fails closed, and new writes use the plural field. | `current change`; `hypothesis_lineage.py`; `ActionOption.yaml`; focused lineage and operational-hypothesis competency checks passed 15 cases. | Supply the remaining real lineage properties and runtime producer before binding the projector. |
| 2026-08-27 | implemented | Added a governed live-shadow batch producer that emits canonical batch and manifest files consumable by the existing O7 exact-digest source without touching promotion state. | `current change`; `delivery/measurement/operational_promotion_batch.py` and focused producer/consumer checks passed. | Supply deployment-owned action evidence and retain complete live days, recurrence, confidence, and authenticated review receipts. |
| 2026-08-27 | implemented | Added immutable frozen-benchmark cohort composition to the live batch producer while preserving the live-shadow classification and exact-digest consumer contract. | `current change`; focused O7 producer/consumer checks passed. | Supply deployment-owned action evidence and retain complete live days, recurrence, confidence, and authenticated review receipts. |
| 2026-08-27 | implemented | Hardened the producer so benchmark evidence is required, immutable, and never relabeled as live-shadow evidence. | `current change`; focused adversarial O7 producer/consumer checks passed. | Supply deployment-owned action evidence and retain complete live days, recurrence, confidence, and authenticated review receipts. |
| 2026-08-28 | implemented | Hardened the O7 live-batch producer so a retry with a real, advancing clock can no longer be mistaken for a conflicting publish. It now reuses an already-sealed batch's `sealed_at` instead of minting a new one on every attempt, publishes the batch and its manifest through an atomic temp-file rename instead of a raw exclusive write that could leave a torn file on a crash, and serializes the publish sequence for one ActionType behind an exclusive per-stem lock. | `current change`; `delivery/measurement/operational_promotion_batch.py`; focused O7 batch retry, atomic-publish, and conflict checks (`4 passed`); Ruff, formatter, and strict mypy. | Supply deployment-owned action evidence and retain complete live days, recurrence, confidence, and authenticated review receipts. |
| 2026-08-31 | implemented | Completed the bounded case-to-candidate-to-reviewed-promotion composition on one pinned release without granting authority from publication. | `current change`; focused Story #370 regression passed 119 cases, including the frozen `v2026.08` restart, duplicate, rollback, mismatch, and demotion scenario. | Retain action-specific live evidence and a governed deployment receipt before claiming operational validation. |
| 2026-09-13 | implemented | Reconciled the migrated ledger with the deployed signed-observation binding and complete prospective-to-observed multi-effect lineage runtime that landed after the prior open item was recorded. | `current change`; `runtime/observation_evidence.py`; `delivery/{prospective_lineage,operational_lineage}.py`; focused local validation passed 28 tests: 12 lineage and runtime checks, 15 ledger migration regressions, and one adjacent runtime regression. | Retain protected-runner action receipts, 100 live-shadow samples across 14 distinct days, and complete recurrence evidence before claiming O7 operational validation. |


| 2026-09-14 | in-progress | Added scoped durable Pattern handoff and hardened current T1 admission against stale/future evidence, exact-expiry reuse, changed targets/parameters, missing Azure admission composition, and unbounded provider work. | `current change`; Pattern/layout: 31 passed; composed T1 adapter/composition/tier/control-loop checks: 122 passed; T1 context branch-inclusive coverage: 98.51% before two additional timeout/cancellation tests. | Complete copied-data retention, current Pattern-to-T1 selection, and the context-aware qualification in the prediction-learning ledger; no live evidence was collected. |

| 2026-09-15 | in-progress | Moved new derived learning records into one deletion-fenced scope CAS store, corrected first-write semantics for PostgreSQL, removed copied-body caches, and bound the existing Muninn retention tick to physical derived-body purge. | `current change`; integrated focused regression: 650 passed, including concurrent deletion, replay, actual PostgreSQL body removal, and audit-chain checks. | Legacy experimental keys, broker and downstream candidate/embedding retention, authorized Pattern-to-T1 selection, and operational qualification remain open. |

### Remaining work

- [ ] Complete scoped Pattern-data retention and authorized Pattern-to-T1 selection with current
  revisions, then close the [prediction-learning ledger](prediction-learning-and-case-history.md)
  integration criteria without treating local fixtures as production evidence.

- [x] Bind the O3 production validator and pull-request publisher. Focused compiler, Mimir,
  publisher, retry, audit, and idempotency checks prove the local end-to-end path; deployed PR
  evidence remains operational validation rather than implementation work.
- [x] Bind the deployment-owned signed-context issuer and preserve the Forseti-owned planning
  properties through complete causal lineage. Focused runtime, agent-chain, materialization, and
  terminal reconciliation tests prove the configured code path without claiming live deployment
  receipts.
- [x] Reconcile the catalog's one-to-many `expects` relationship with runtime lineage. New lineage
  writes require the ordered complete `expected_effect_refs` set and one independent outcome per
  effect. Singular-only stored records retain one-effect read compatibility, while simultaneous
  singular and plural fields fail closed. Focused catalog-backed tests preserve every selected
  option effect without choosing or fabricating one metric.
- [ ] Accumulate O7 per-action live days, sample sizes, complete recurrence windows, Wilson bounds, and zero-escape evidence required for promotion review.
- [x] Complete [issue #370](https://github.com/dotnetpower/fdai/issues/370) with one pinned-release
  case-to-candidate-to-reviewed-promotion path and restart, duplicate, rollback, release-mismatch,
  and demotion evidence.
- [ ] If evaluation host integration is reactivated, prove that adapter results enter only through
  canonical operational-case receipts and cannot treat golden-answer success as promotion evidence.
