# Prediction Learning and Case History implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| P2: Public test-context schemas and SDK exports | implemented | `packages/service-contracts/tests/test_test_context_schema.py`; `scripts/quality/contracts/generate_test_context_schemas.py` | Three standalone version `1.0.0` schemas preserve typed semantics and false execution authority. This does not certify producer/consumer N/N-1 transport or independent proof issuance. |
| Forecast detector, agent pub/sub runtime, and single-writer enforcement | implemented | [Forecast outcome contract](../../roadmap/rules-and-detection/prediction-learning-and-case-history.md#forecast-outcome-contract), pantheon single-writer registry | Shadow findings only; no execution authority. |
| Governed trajectory serialization, scanning, checksum, and retention primitives | implemented | [Retention and deletion](../../roadmap/rules-and-detection/prediction-learning-and-case-history.md#retention-and-deletion) | Reused rather than reimplemented. |
| `ForecastOutcome` schema, episode closer, transactional outbox, and the positive, negative, and held-for-review ledger | implemented | [Learning and promotion](../../roadmap/rules-and-detection/prediction-learning-and-case-history.md#learning-and-promotion) | Held episodes stay inert. |
| StateStore authority, PostgreSQL shadow dual-write, and the episode, revision, chunk, migration-marker, and tombstone tables | implemented | [Target PostgreSQL hot index](../../roadmap/rules-and-detection/prediction-learning-and-case-history.md#target-postgresql-hot-index), [Immutable artifact](../../roadmap/rules-and-detection/prediction-learning-and-case-history.md#immutable-artifact) | Full-chain keyset backfill and the zero-mismatch cutover gate are included. |
| Operational receipt compiler and action/incident case intake | implemented | [Retrieval for analysis](../../roadmap/rules-and-detection/prediction-learning-and-case-history.md#retrieval-for-analysis) | |
| Azure private artifact adapter, mechanical forecast tick Job, and read-only console health view | implemented | [Immutable artifact](../../roadmap/rules-and-detection/prediction-learning-and-case-history.md#immutable-artifact) | Deployment stays opt-in. |
| Muninn case materialization, scheduled retention, fingerprint-keyed cohorts, and inert Norns candidate choreography | in-progress | [Learning and promotion](../../roadmap/rules-and-detection/prediction-learning-and-case-history.md#learning-and-promotion) | Implemented through O2; raw response outcomes remain insufficient mechanism evidence. |
| Durable `Pattern` publication | implemented | `agents/{muninn,norns}.py`; `core/operational_learning/{cohort_retention,legacy_suffix_retention}.py`; `core/ontology_platform/pattern_queries.py`; focused Pattern, persistence, and runtime tests; [#1025 deployed retention readback](https://github.com/dotnetpower/fdai/issues/1025#issuecomment-5864351096) | Inert publication, current-case recompiled retention, independent principal-to-case-scope query admission, late runtime binding, new-layout purge, and legacy base/suffixed row deletion are locally tested. Repository-owned downstream retention and pinned-runtime broker recovery are implemented (#1491, #1495, #1501, #1507). A read-only 2026-09-28 readback found 11 primary Event Hubs with one-day and 7 DLQ Event Hubs with seven-day retention in the development namespaces. The owner removed the deployed redrive receipt from #1025 because that deployment stopped before migrations; pinned-runtime redrive remains the recovery evidence, and no deployed qualification is claimed. |
| P0: Context-aware design and delivery contract | not-applicable | [Context-aware decision contract](../../roadmap/rules-and-detection/prediction-learning-and-case-history.md#context-aware-decision-contract) | Design only. Six conclusions remain independent; no new authority is granted. |
| P1: Bounded metric observation admission | implemented | `core/detection/forecast_observation.py`; `tests/core/detection/test_forecast_observation.py`: 43 passing tests, 97.48% branch-inclusive coverage; focused Ruff and mypy checks | Applies minimum distinct samples, span coverage, maximum gaps, exact source, single-series identity, conflict rejection, timeout, point cap, stream cleanup, and scoped evidence digests. |
| P1: Intervention joins | in-progress | `core/detection/{forecast_context,forecast_history}.py`; `delivery/persistence/state_store_forecast_context.py`; `runtime/forecast_learning.py`; source/configuration tests: 124 passed, 92.70% collector branch coverage | Automatic collection reads four normalized source histories with positive coverage, all-state queries, bounded initial-state reconstruction, and independent admissions. Real PostgreSQL collection and unknown-state rejection pass. Raw authoritative source producers and independent proof issuance remain open. |
| P1: External-change journal witness | implemented | `delivery/{forecast_change_history.py,persistence/postgres_forecast_change_history.py}`; `tests/{delivery/test_forecast_change_history.py,persistence/test_postgres_forecast_change_history.py}`; focused tests | Exact scope/subject/known-at journal rows retain revisions and original observation references with bounded pagination and explicit incomplete coverage. Now restated by the `changes` source producer with its incomplete limitation; still not a scoring input. Start-of-window coverage, other sources, and #1022 independent proof remain open. |
| P1: Forecast source history producers | in-progress | `core/detection/{forecast_history_source,forecast_history_chain,forecast_history_producer,forecast_history_ingress}.py`; `delivery/{forecast_history_sources,forecast_history_configuration,forecast_history_readiness}.py`; `delivery/persistence/postgres_forecast_lifecycle_history.py`; `runtime/forecast_history_producers.py`; focused deterministic tests and two loopback PostgreSQL tests over the real Core migrations | Transitions are appended only from clean reads with a positive, current checkpoint and only when every stored transition in the window is re-asserted; withdrawn or revised records, contradicting restatements, stale knowledge, and same-instant state conflicts hold coverage. Incomplete reads store coverage only. Grid-aligned `checkpoint` anchors are shared by overlapping episodes. `changes` and `resource_lifecycle` are bound but incomplete; `actions` and `excluded_windows` are unavailable. The Settings row is never ready or available and the Console renders only its status, mode, source, and reason. No positive source checkpoint or #1022 proof exists, so scoring stays held. |
| P1: Non-prediction closure evidence | implemented | `core/detection/forecast_closure.py`; `delivery/persistence/postgres_forecast_episode.py`; `service-migrations/branches/core-control-plane/versions/20260914_core_forecast_closure_observation.py`; focused seven-file suite: 89 passed, zero skipped | Real loopback PostgreSQL tests prove isolated migration, restart readback, exact duplicate handling, conflict rejection, completeness counts, and downgrade. This does not establish deployed migration or runtime qualification. |
| P2: Governed operator context lifecycle | in-progress | `semantic_test_context.py`; shared `test_context.py`; Operator `test_context_runtime.py`; `test_operational_context_verdict.py`; real PostgreSQL result/outbox tests; Console candidate/status checks | Saga-audited application results bind to the exact original command, remain principal-isolated, and never imply current authorization. Source probe/cleanup deadlines, explicit failed-worker restart, and direct/multiplexed DLQ behavior are tested. Console displays strict source drafts and reads existing principal-owned command metadata, but cannot bind a lookup to the displayed draft. Reviewed scope/policy choices, submission controls, and independent proof production remain open. |
| P3: Six-axis decision and runtime context read | in-progress | `test_context.py`; `test_context_dispatch.py`; Forseti and Thor bindings; `test_runtime.py`; `test_operational_context_verdict.py` | Forseti rechecks current context after admission; ActionRun persists its exact context binding, and Thor rechecks source/admission immediately before executor I/O. Changed, expired, unavailable, and unbound context blocks dispatch. Console command metadata is historical and does not project P3 current authorization. Actual queued runtime and in-flight stop/recovery qualification remain open. |
| P4: Deletion-fenced derived projections | implemented | `core/case_history/derived.py`; `runtime/case_history.py`; source, Pattern, and real PostgreSQL tests | New cohorts, frozen snapshots, Pattern bodies, and emission markers share a scope-bound CAS boundary. Purge precedes source tombstoning, including initially empty scopes; first creation uses atomic create-and-audit. Muninn no longer caches copied case bodies. Legacy experimental keys, broker payloads, and downstream candidates/embeddings remain separate deletion scope. |
| P4: Legacy base-cohort deletion fence | implemented | `core/operational_learning/cohort_retention.py`; Muninn key derivation; runtime retention composition; focused Pattern, case-history, runtime, and layout tests | Source deletion derives both legacy synthetic-source partitions, removes matching case bodies with audited CAS, retains a bounded content-free fence, verifies readback, and refuses late recreation after restart. Legal holds and missing deletion intent fail closed. Suffixed rows are tracked separately; broker payloads remain open. |
| P4: Legacy suffixed StateStore row cleanup | implemented | `core/operational_learning/legacy_suffix_retention.py`; `delivery/persistence/postgres.py`; focused Pattern, runtime, and real PostgreSQL keyset tests | Historical snapshots, Pattern bodies, and linked emission markers are cleaned under the source deletion claim with audited bounded cursors, second-pass scanning, CAS, retired replay fences, and independent readback. Held/unrelated bodies survive. Later #1025 increments cover broker payload retention and pinned-runtime redrive; orphan emission markers carry no case body and are skipped by design (`legacy_suffix_retention.py`), and deployed Event Hubs expiry readback remains open. |
| P4: Case-aware broker redelivery fence | implemented | `agents/norns.py`; `agents/_framework/{norns_case_history,runtime_operational_agents}.py`; `tests/providers/test_case_history_broker_recovery.py`; Event Hubs module plan tests | Production Norns rechecks every exact cohort case through the bound materializer before learning and before flushing queued operational work. The pinned Redpanda and real PostgreSQL matrix proves throttling, DLQ, restart, durable recovery, redrive, and post-deletion rejection. Event Hubs plans retain one-day primary and seven-day DLQ expiry; deployed property readback remains open. |
| P4: Durable Norns candidate recovery | implemented | `agents/_framework/{norns_candidate_delivery,norns_case_history,runtime_operational_agents}.py`; `agents/norns.py`; focused throttling, restart, and deletion regressions | Operational candidates and paired Pattern envelopes are durably recorded before acknowledgement, restored in bounded shared-store batches, and removed after publication, source invalidation, or consensus hold. No catalog, promotion, approval, or execution authority is added. |
| P4: Durable Mimir review recovery | implemented | `agents/_framework/{mimir_catalog_identity,mimir_catalog_recovery,runtime_operational_agents}.py`; `agents/mimir.py`; focused Mimir restart and source-invalidation tests | Pending operational review candidates are written with audit and independently read back before publication. Restart recompiles and rechecks current cases; publication or source invalidation CAS-replaces candidate material with digest-only lineage. No Rule activation or new authority is introduced. |
| P4: Current T1 evidence boundary | implemented | `core/tiers/t1_lightweight/{tier,contextual_reuse}.py`; `core/control_loop/orchestrator.py`; `runtime/bootstrap_pantheon.py`; focused T1/control-loop checks | Exact current source revision is required before and after independent verification, then admission freshness is reassessed. Provider errors abstain and legacy unscoped operational cases remain held. This does not establish the approved retained Pattern-to-T1 catalog producer. |
| P4: T1 copied-vector deletion | implemented | `delivery/persistence/pgvector_pattern_library.py`; `core/case_history/derived.py`; runtime bindings; isolated real PostgreSQL/pgvector regression | Source-owned purge commits digest-only case/signature fences with bounded batches, blocks late writes after restart, preserves other cases, and refuses holds. A DB failure rolls back the vector batch and leaves source deletion pending. The actual T1 DSN is explicit. Later #1025 increments cover the remaining repository-owned downstream and legacy cohort stores; deployed Event Hubs expiry readback remains open. |
| P4: Retained-copy and immutable-reference inventory | implemented | [Retained-copy inventory](../../roadmap/rules-and-detection/prediction-learning-and-case-history.md#retained-copy-inventory); source, persistence, agent, broker, and GitOps publisher paths cited by the inventory | Twelve current, legacy, transient, broker, and review surfaces are classified by retained material, writer, hold behavior, deletion fence, and delivery status. Repository-owned bodies, pending work, and local broker recovery are covered; deployed transport expiry readback remains open. |
| P4-P5: Correction-aware reuse and candidate qualification integration | in-progress | [Operational learning ontology](../../roadmap/rules-and-detection/operational-learning-ontology.md) | Existing O3-O7 components are not equivalent to the complete context-aware integration. Do not infer production qualification from their presence. |
| P6: Context-aware operational qualification | in-progress | [Connected validation handoff](../../roadmap/rules-and-detection/prediction-learning-and-case-history.md#connected-validation-handoff) | Repeatable local commands and stage-specific connected checks are documented. Live execution is intentionally deferred by the operator; no target-specific runtime or model receipt exists for this change. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-29 | in-progress | Reconciled delivery status with GitHub. Recorded that #718, #1021, #1023, #1024, and #1026 were closed as not planned on 2026-09-28 and that this ledger is their resumable record; checked #1022 criterion 1 and the owner-boundary issuance item against their evidence; closed the blocking item after the owner re-evaluated the three dependent issues; and marked durable `Pattern` publication `implemented` after #1025 closed with a deployed retention readback. No implementation or runtime state changed. | `current change`; this ledger; [#1022 owner decision record](https://github.com/dotnetpower/fdai/issues/1022#issuecomment-5863412337), [PR #1649](https://github.com/dotnetpower/fdai/pull/1649), and the [#1025 readback](https://github.com/dotnetpower/fdai/issues/1025#issuecomment-5864351096); `check-roadmap-implementation-tracking.py` and doc-link checks. | Raw forecast sources, forecast-purpose proofs, P2-P6 integration, and connected qualification stay open below. |
| 2026-09-29 | implemented | Added `ForecastOutcome` schema `1.2.0`. When the independent verifier recorded an explicit class for a forecast-context or history-slice rejection, Heimdall's closure excludes scoring with that `operational_evidence_*` class and cites the rejection record through exactly one `operational-evidence-rejection:` evidence reference; the typed model and JSON Schema refuse either without the other, and an unavailable verifier keeps the `1.1.0` `intervention_history_unavailable` exclusion. Earlier versions keep their shapes, and no exclusion makes an outcome scorable. | `current change`; `shared/contracts/forecast-outcome/schema-1.2.0.json`, `shared/contracts/models/forecast_outcome.py`, `core/detection/{forecast_context,forecast_outcome}.py`, `delivery/persistence/{state_store_forecast_context,postgres_forecast_episode}.py`; `pytest tests/contracts/test_forecast_outcome_evidence_classes.py tests/contracts/test_forecast_outcome.py tests/agents/test_operational_evidence_owner_records.py tests/core/detection` | Forecast-history and forecast-context readbacks stay with [#1022](https://github.com/dotnetpower/fdai/issues/1022) and raw sources with #1021, so today only `unavailable` reaches the scoring join outside tests. |
| 2026-09-28 | in-progress | Recorded the reviewable source-specific design for independent operational evidence issuance (#1022 criterion 1) in a focused owner and linked it from the completion design. It names the separate verifier identity, invocation path, proof layout, typed rejection records with class-specific owner outcomes, trust and grant registries, and rejection matrix for every admission purpose this owner consumes. Accountability stays with each consuming boundary agent. It was revised before publication to resolve two rounds of independent critique (6 Medium and 3 Low findings). Design only: no consumer behavior, issuer, contract, or authority changed. | `current change`; `docs/roadmap/rules-and-detection/independent-operational-evidence.md`, `prediction-learning-and-case-history.md`, their Korean pairs, and the [issuance ledger](independent-operational-evidence.md); changed-path translation, translation-quality, readable-Hangul, roadmap-tracking, design-route, doc-link, punctuation, and document-size checks. | Owner review of #1022 criterion 1, then criteria 2-7 before any operational admission exists; #1023, #1024, and #1026 stay blocked on implemented issuance. |
| 2026-09-28 | in-progress | Added reviewed forecast source producers that restate existing journal and confirmed-tombstone incarnation records as derived, authority-free state transitions. Transitions are stored only from clean, positively checkpointed reads with current knowledge time, and only when the stored window is re-asserted; withdrawn or revised records, contradicting restatements, and order-independent same-instant conflicts hold coverage. Added lookback-grid `checkpoint` restatements accepted by the collector, per-source deadlines with concurrent per-kind budgets, Heimdall composition through `FDAI_FORECAST_HISTORY_PRODUCERS_JSON`, one configuration parser shared with a Settings `forecast-history` row that is never ready or available, and Console labels. No source write, scoring, or execution authority was added. | `current change`; `core/detection/forecast_history_{source,chain,producer,ingress}.py`, `delivery/forecast_history_{sources,configuration,readiness}.py`, `delivery/persistence/postgres_forecast_lifecycle_history.py`, `runtime/forecast_history_producers.py`; focused forecast, collector, settings, runtime, bootstrap, and layout suite: 498 passed, including both new loopback PostgreSQL tests over the real Core migrations; Ruff, strict mypy, file-size, Core import, fan-out, independent-services, design-impact, translation, and catalog-parity checks; Console i18n/settings tests: 22 passed, route-selected Console tests: 5 passed, and typecheck passed. | #1021 still needs attested positive checkpoints for changes and lifecycle, bounded action and excluded-window readers, a rendered and audited Settings capability control, and #1022 independent proofs. No issue-wide criterion is complete; no live or connected validation occurred. |
| 2026-09-27 | implemented | Corrected the broker qualification to consume the supported public Pantheon facade and added the framework-layout guard to the route-selected checks after exact-head CI identified the private import. | `current change`; `tests/providers/test_case_history_broker_recovery.py`; exact framework-layout reproducer and fake/real provider checks passed. | No runtime role, topic, authority, or recovery behavior changed; deployed Event Hubs qualification remains open. |
| 2026-09-27 | implemented | Pinned the local Kafka-wire runtime to Redpanda v26.2.2 by multi-platform manifest digest, fixed Event Hubs primary/DLQ expiry at one/seven days with plan assertions, and qualified throttling through DLQ, restart, durable recovery, redrive, and source-deletion rejection. | `current change`; `infra/local/docker-compose.yml`; Event Hubs module plan test: 5 passed; `tests/providers/test_case_history_broker_recovery.py`: fake checks and 4 real Redpanda/PostgreSQL matrix cases passed. | Read back the retention properties and repeat the bounded redrive scenario on an exact deployed application revision; broader P4-P6 qualification remains open. |
| 2026-09-27 | implemented | Added bounded durable recovery for throttled Norns operational candidates and paired Pattern envelopes, with independent readback, current-case restart admission, digest-only terminal lineage, and non-blocking shared overflow. | `current change`; `agents/_framework/norns_candidate_delivery.py`, Norns/runtime binding, focused restart/source-deletion tests, Ruff, strict mypy, and Agent layout checks. | #1025 still needs physical broker/DLQ expiry, pinned-runtime restart/redrive evidence, and final shared/cohort legal-hold qualification. |
| 2026-09-27 | implemented | Added bounded durable Mimir review recovery with exact candidate/package identity, independent readback, restart recompilation, current-case revalidation, idempotent publication retry, and content-free terminal records after publication or source invalidation. | `current change`; `agents/_framework/{mimir_catalog_identity,mimir_catalog_recovery}.py`, Mimir/runtime composition, focused restart/source-deletion regressions, Ruff, strict mypy, and Agent layout checks. | #1025 still needs physical broker expiry, pinned-runtime DLQ/restart evidence, Norns durable throttled-work recovery, and final shared/cohort legal-hold qualification. |
| 2026-09-27 | implemented | Added a second current-case check at Norns flush so a throttled operational candidate and its paired Pattern envelope are discarded when source deletion starts before publication. | `current change`; queued-candidate deletion regression and private Norns case-history helper. | Persist current pending work across restart and retain broker expiry plus pinned-runtime DLQ evidence. |
| 2026-09-27 | implemented | Bound current-case admission into production Norns before operational cohort compilation, preventing broker redelivery or DLQ redrive from rematerializing deleted case bodies while preserving current-case restart recovery. | `current change`; Norns/runtime wiring and operating-Pattern restart/redelivery regressions. | Retain physical broker expiry plus throttling, restart, DLQ, and redrive evidence on a pinned runtime. |
| 2026-09-27 | implemented | Bound historical suffixed snapshot, Pattern, and linked emission cleanup to source retention; added bounded audited keyset checkpoints, retired old-key replay fences, a second scan, and physical deletion readback while preserving held/unrelated cases. | `current change`; `core/operational_learning/legacy_suffix_retention.py`, `shared/providers/state_store.py`, `delivery/persistence/postgres.py`, `runtime/case_history.py`; focused Pattern, runtime, and real PostgreSQL keyset tests; Ruff and strict mypy. | #1025 still needs broker/DLQ payload retention and pinned redrive evidence, downstream candidates and caches, cross-case hold semantics, and full retained-copy physical deletion. No issue-wide criterion is complete. |
| 2026-09-27 | in-progress | Added candidate rendering and principal-owned historical command status without raising P2/P3 authority; excluded proposal and review controls while reviewed selection and proof mappings are absent. | `current change`; `console/src/deck/test-context-review.tsx`, `test-context-status.ts`, `console/tests/e2e/test-context-candidate.spec.ts`, `services/operator-service/tests/test_operator_service_full_composition.py`; focused Console and Operator checks. | Issue #1023 still needs reviewed choices, independent review/revocation controls, current authorization, and connected validation; #1022 must supply independent proofs and principal-to-case mapping. |
| 2026-09-26 | implemented | Added source-owned deletion and restart-safe late-writer fencing for legacy top-level cohort bodies without changing Muninn ownership or Pattern authority. | `current change`; `cohort_retention.py`, shared Muninn key derivation, runtime downstream binding, and 77 focused Pattern, case-history, runtime, and agent-layout tests; Ruff and strict mypy. | Qualify historical suffixed snapshot/Pattern/emission cleanup, case-aware broker/DLQ redrive, downstream candidate recovery, and governed runtime receipts under #1025. |
| 2026-09-26 | implemented | Added a separate, read-only external-change journal witness with fixed-watermark keyset pages, strict admission, pending/duplicate/conflict handling, correction lineage, and incomplete coverage even for zero rows. No transition state, scoring eligibility, or authority is inferred. | `current change`; `delivery/forecast_change_history.py`; `delivery/persistence/postgres_forecast_change_history.py`; focused delivery, persistence, forecast, and journal checks. | #1021 still needs positively proven start-of-window coverage, remaining three source histories, bounded recovery, and honest capability binding. Independent proofs belong to #1022. |
| 2026-09-15 | implemented | Reproduced three missing public schema lookups, then added deterministic draft/command/application schema generation, SDK exports, and existing-model semantic validation. No wire fields or runtime authority changed. | `current change`; #1026; 16 focused registration/roundtrip/negative/parity cases, 89 shared-validator and compatibility cases; two-source strict mypy; independent read-only review found no confirmed Medium-or-higher defect after CI collection and import-path concerns were disproved. | Local source only; publication remains separate. Full broker compatibility, rollout, raw sources/proofs, UI, retention, and P0-P6 qualification remain open. |
| 2026-09-15 | implemented | Reconciled the not-yet-deployed forecast closure migration with the newly integrated Core human-access head and matched its rollback predecessor. Replaced literal Console fixture GUIDs with runtime-generated synthetic UUIDv4 identities. | `current change`; PR #1029, failed CI 34932558225 attempt 1, jobs 104263699615 and 104263699663; exact local Console tests: 20 passed; single-head inventory and disposable-database migration round trip: 2 passed. | Publish the repaired local commit and require fresh exact-head CI before protected merge. Residual #1021-#1026 and connected qualification remain open. |
| 2026-09-14 | implemented | Preserved actual evaluator ETA and band confidence in the existing forecast outbox for exact-source approval timing. PostgreSQL time normalization preserves source identity and equivalent instants without rewriting episodes. | `current change`; `test_forecast_evaluation.py`, `test_forecast_urgency.py`, actual forecast agent chain and SQL checks; 104 related tests plus 31 subsequent source/timezone tests passed. | Operational calibration and urgency cohorts remain separate; no forecast outcome or promotion is inferred. |
| 2026-08-15 | in-progress | Adopted the implementation ledger from the existing status table without reconstructing earlier provenance, and renamed the owned learning object to `Pattern`. | Current source and the sections referenced in the scope table. | Complete the observable exit conditions below. |
| 2026-09-14 | in-progress | Added the context-aware P0-P6 design, migrated duplicated owner status with the history-preserving repository tool, and hardened bounded metric observation admission. Separated O3-O7 component presence from end-to-end completion rather than extending the older O2 claim. | `current change`; `forecast_observation.py`; 43 focused observation tests, 97.48% branch-inclusive coverage; the adjacent closure/outcome/runtime/agent check passed 26 tests before the final stream hardening; ledger and paired-document checks passed. | Complete intervention-aware closure, governed context admission and decisions, durable patterns, correction-aware qualification, and operational validation. The requested post-implementation hardening completion condition has not been met. |
| 2026-09-14 | in-progress | Carried exact observations through negative and abstained closure, added nullable Core-owned PostgreSQL retention and completeness counts, and rejected changed retry content or contradictory observations before storage. Added an isolated-loopback migration/restart/rollback regression. | `current change`; seven focused forecast test files: 83 passed, 6 PostgreSQL-dependent checks skipped; Core migration branch validation passed; Ruff and mypy passed. | Configure the local validation binding and execute the six PostgreSQL checks before treating persistence as verified. P2-P6 and full-scope repeated hardening remain open. No database migration, live model validation, or deployment was performed. |
| 2026-09-14 | implemented | Resolved the previously reported local database blocker by reusing the already-running validation container and injecting its existing configuration into the test process without disclosing connection values. The first full run identified a missing legacy publication-counter migration in temporary schema preparation; adding the existing migration resolved that preparation defect. | `current change`; three isolated restart/rollback cases passed, followed by all seven focused forecast test files: 89 passed, zero skipped. Temporary schema cleanup was independently queried and confirmed. | This transition completes local closure persistence verification only. Existing application schemas were not migrated; intervention joins, P2-P6, and the requested full-scope hardening condition remain open. |
| 2026-09-14 | implemented | Made every PostgreSQL forecast test use one shared fixture that creates its own schema, applies the existing forecast and publication-counter DDL plus the new Core column migration, and verifies cleanup. Configured the current task terminal with the standard PostgreSQL URI without persisting credentials. | `current change`; direct execution of `tests/persistence/test_postgres_forecast_episode.py`: 17 passed; Ruff and editor diagnostics passed. | The database test file no longer requires manually preparing a shared schema. Full service migration, intervention joins, P2-P6, and full-scope hardening remain separate work. |
| 2026-09-14 | in-progress | Added versioned scoring exclusions, independently admitted forecast history reads, runtime reader composition, six-axis test-context evaluation, scoped atomic cohorts, immutable snapshots, and Norns-to-Muninn Pattern retention. Missing history never means no intervention. | `current change`; combined contracts, forecast, case-history, agent, persistence, and T1 regression: 495 passed, including real loopback PostgreSQL. Four new boundary modules reached 94%-100% branch-inclusive coverage in the five-module measurement. | Implement authoritative history production, the P2 lifecycle, dispatch revalidation, copied-data retention, Pattern-to-T1 read integration, and P5/P6 qualification. |
| 2026-09-14 | in-progress | Hardened queue acknowledgement, Pattern fields and versions, Forseti monotonic ceilings, separate observation admission, total forecast/T1 deadlines, decision-time T1 expiry, exact event/action binding, and Azure admission composition. | `current change`; Pattern/layout slice: 31 passed; context/Forseti slice: 35 passed; final composed T1 slice: 122 passed. T1 context coverage rose from 77% to 98.51% in 47 focused tests before adding two deadline/cancellation regressions. Counts overlap and are not additive. | The two local review batches below do not establish the requested full P0-P6 convergence. Known implementation and operational evidence gaps remain above Low. |
| 2026-09-15 | in-progress | Added the reviewed completion design, source-deletion-fenced derived storage, empty/existing-scope race protection, real atomic first creation, no copied-body process cache, and runtime retention binding. Added independently admitted context proposal/review/revocation revisions, temporal and overlap rejection, signal-scoped runtime reads, and actual Pantheon injection. | `current change`; integrated focused regression: 650 passed with no skips, including isolated loopback PostgreSQL projection deletion, context restart/revocation, and audit-chain verification. New lifecycle coverage initially failed at 86.62%, then reached 94.65% across 97 focused tests before two extra temporal tests. Source lint and strict mypy passed for 34 changed files before the final documentation pass. | Complete authenticated command ingress and Var-to-Mimir event ownership, approved independent evidence producers, source coverage aggregation, authorized Pattern-to-T1/read selection, downstream deletion, dispatch revalidation, and P5/P6 operational qualification. No live model, Azure operation, commit, push, or deployment was performed. |
| 2026-09-15 | in-progress | Connected authenticated Operator commands, Var/Mimir/Saga lifecycle, source-grounded chat drafts, admitted Pattern queries, T1 source correction fences, Thor dispatch revalidation, and immutable forecast-history amendments. Repaired real psycopg LIKE parsing, legacy revision conversion, malformed nested command handling, and context-review leakage into Thor's action approval handler. | `current change`; real outbox: 9 passed before 10 numeric cases; fake/real history: 15 passed before 11 ingress cases; durable/runtime: 144 passed; final five-boundary coverage: 130 passed, 94.16%; seven-source strict mypy passed. Counts overlap. | Automatic source/proof production, remaining operator presentation, approved Pattern-to-T1 enrollment, downstream deletion, and frozen qualification integration remain open. Connected live testing is deferred by operator request. |
| 2026-09-15 | implemented | Preserved `case_scope` from Norns through Mimir catalog identity and checked current revisions before accepting or publishing review packages. Applied the context dispatch guard to shadow as well as enforce so a revoked shadow action cannot report success. | `current change`; scoped catalog/Mimir/Pattern checks: 64 passed; shadow/enforce and durable Thor checks: 89 passed; actual semantic judgment boundary: 1 passed; real HTTP context authorization and identity rejection: 10 passed; five-source mypy and task-scoped Ruff passed. | Approved Pattern-to-T1 enrollment still needs verified action parameters and independent temporal holdout evidence; direct Pattern publication supplies neither. Existing P1-P6 integration and deferred live evidence remain open. |
| 2026-09-15 | in-progress | Added principal-isolated context command delivery status without conflating broker acceptance with policy application. Preserved frozen learning review rejection ordering after current-case checks were added, and extracted source-review/context parsing into existing helpers to meet agent size limits. | `current change`; integrated local boundary regression: 694 passed, zero skipped; changed production types: 60 modules passed; frozen learning/Mimir/Pattern: 56 passed; semantic generated inventory and composition structure: 43 passed; current Operator command/family/HTTP slice: 77 passed; extracted helper slice: 77 passed. | Policy result projection, full selection UI, automatic source/proof production, approved T1 enrollment, and downstream deletion remain implementation work. Connected validation remains intentionally deferred. |
| 2026-09-15 | in-progress | Added automatic normalized forecast-history collection, exact Saga-audited application result relay and persistence, bounded explicit result-worker recovery, and strict Console draft/replay propagation. Hardened all-state SQL, start-boundary semantics, source mappings, typed history conflicts, provider-error metric retention, and result DLQ permissions. | `current change`; seven-file Python integration: 206 passed before added source cases; collector/configuration: 124 passed at 92.70% branch coverage; existing state queries: 13 passed; Console: 128 passed and production/test typechecks; seven production files passed Ruff and strict mypy. Counts overlap. | Raw source producers, independent operational proof issuance, authenticated selection/submission UI, approved T1 enrollment, legacy/downstream deletion, and P5 integration remain above Low. Connected testing stays deferred; no live or delivery completion is claimed. |
| 2026-09-15 | implemented | Added source-owned pgvector retention with durable case/signature fences, exact T1 DSN binding, immutable operational upsert identity, and resumable 1,000-row batches. Real DB failure preserves pending source state, while retry and restart cannot restore deleted vectors. | `current change`; case/runtime/vector batch: 63 passed with five legacy shared-schema tests deliberately deselected; composed retention coverage: 56 passed at 94.34%; final isolation SQL checks: 2 passed; four source modules passed Ruff/mypy; draft microsecond/date checks: 20 passed plus Console typechecks. | Only the T1 vector copy store is closed by this row. Raw source/proof issuance, authenticated UI, approved T1 intake, other downstream cleanup, and P5/P6 remain open. No commit, push, live model, Azure call, or deployment was performed. |
| 2026-09-26 | implemented | Inventoried every current, legacy, transient, broker, and GitOps case-copy or immutable-reference surface and recorded its writer, content class, legal-hold behavior, deletion fence, and residual status. | `current change`; canonical retained-copy table; direct source review of case-history stores, derived projections, T1 pgvector, Norns, Mimir, EventBusBridge, and GitOps review publication. | Implement legacy top-level key migration and purge, durable Norns/Mimir recovery, and case-aware broker/DLQ replay before checking the remaining retention criteria. |

### Remaining work

Publication is tracked by [#1020](https://github.com/dotnetpower/fdai/issues/1020).
Its merge closes only the implemented foundation, not the following residual packages.

- [x] Inventory every retained case-body copy and immutable reference, including authoritative
  artifacts and metadata, current and legacy projections, T1 vectors, broker payloads, process
  buffers, and GitOps review packages. Record the single writer, legal-hold behavior, deletion
  fence, and residual status in the canonical retained-copy table.

| Remaining package | Tracking issue | Completion boundary |
|-------------------|----------------|---------------------|
| Authoritative raw history and positive source coverage | [#1021](https://github.com/dotnetpower/fdai/issues/1021) (closed as not planned) | Actual four-source producers, bounded recovery, current checkpoints, and honest capability availability. |
| Independent operational proof issuance and trust mappings | [#1022](https://github.com/dotnetpower/fdai/issues/1022) | Independent authenticated readback, five proofs, exact purposes and principal-to-case authorization; no deployment-policy substitution. Design: [issuance owner](../../roadmap/rules-and-detection/independent-operational-evidence.md); status: [issuance ledger](independent-operational-evidence.md). |
| Authenticated test-context selection, review, and status UI | [#1023](https://github.com/dotnetpower/fdai/issues/1023) (closed as not planned) | Server-owned choices, independent review/revocation, separate delivery/application/current-authority states, bilingual accessible workflow. |
| Approved Pattern-to-T1 intake and P5 qualification | [#1024](https://github.com/dotnetpower/fdai/issues/1024) (closed as not planned) | Canonical action parameters, frozen holdout/replay, current-case fences, shadow-first intake, existing promotion/demotion gates. |
| Legacy/downstream case copies and broker recovery | [#1025](https://github.com/dotnetpower/fdai/issues/1025) (closed as completed) | Complete. Repository-owned physical deletion, late-writer fences, legal holds, resumable cleanup, T1 vector cleanup, and pinned-runtime broker redrive are implemented (#1484, #1491, #1495, #1501, #1507), and the [deployed retention readback](https://github.com/dotnetpower/fdai/issues/1025#issuecomment-5864351096) matches the one-day primary and seven-day DLQ plan. The owner removed the deployed redrive receipt from the criteria. |
| Full P0-P6 integration and connected qualification | [#1026](https://github.com/dotnetpower/fdai/issues/1026) (closed as not planned) | Complete integrations, repeated ten-concern hardening rounds, no unresolved Medium-or-higher defects, and separately authorized exact-SHA operational evidence. |

The owner closed [#718](https://github.com/dotnetpower/fdai/issues/718), #1021, #1023, #1024, and
#1026 as not planned on 2026-09-28 to limit the open backlog to work that could land then. The rows
above and the unchecked items below are their resumable record; no replacement issue exists. The #718
forecast promotion observation window remains independent. Registering these issues authorizes no deployment or live model/Azure test.

The external-change journal witness and the `changes` and `resource_lifecycle` source producers are locally implemented with incomplete coverage. Earlier
normalized-history collection, Saga-audited policy results, result-worker recovery, and strict
Console draft decoding/replay remain at their tested boundaries. Complete raw source coverage,
independent proofs, UI completion, approved T1 enrollment, deployed broker expiry readback, and
deployed qualification remain unavailable.

- [x] Publish `Pattern` from Norns on `object.pattern` with Muninn registered as its consumer;
  `test_operating_pattern_learning_e2e.py`, topic, runtime, and document-parity checks pass.
- [x] Prove broker dead-letter recovery after publication throttling and restart on pinned
  Redpanda v26.2.2 with the same scenario passing against real PostgreSQL durable state.
- [x] Apply source retention, deletion, and legal-hold rules to copied cohort cases, frozen
  snapshots, patterns, and emission markers; focused CAS, restart, and real PostgreSQL tests
  preserve held and unrelated bodies while physically removing claimed bodies.
- [x] Bind new-layout cohort/snapshot/Pattern/emission deletion to Muninn's existing source-retention
  tick. Prove empty/existing-scope write races, restart, readback, and actual PostgreSQL body removal.
- [x] Purge legacy top-level cohort bodies through the source deletion claim, retain a bounded
  content-free fence, verify readback, preserve legal holds, and block replay after restart.
- [x] Qualify repository-owned historical suffixed snapshot/Pattern/emission cleanup with
  source-claim gating, audited bounded retry, held-peer preservation, and independent readback.
- [x] Bind `object.context-index` redelivery, explicit DLQ redrive, and queued operational-candidate
  flush to exact current-case admission; deleted or pending-deletion bodies cannot recreate candidates.
- [x] Persist Mimir operational review work before publication, recover it after restart with exact
  current-case revalidation, and replace candidate material with digest-only lineage after publication
  or source invalidation.
- [x] Persist throttled Norns operational candidates with their exact Pattern envelopes before
  acknowledgement, recover a bounded shared-store batch after restart, and scrub source-invalidated
  or held work to digest-only lineage.
- [x] Retain the one-day primary and seven-day DLQ expiry plan plus throttling, restart, DLQ, and
  redrive evidence on pinned Redpanda v26.2.2. The read-only
  [deployed Event Hubs property readback](https://github.com/dotnetpower/fdai/issues/1025#issuecomment-5864351096)
  matches the plan; it is not a deployed redrive or operational qualification.
- [ ] Supply mechanism evidence strong enough to promote raw response outcomes beyond O2.
- [ ] P1: Bind complete, exact-target, event-time intervention/deletion/excluded-window evidence at
  runtime. Prove unavailable history is unknown rather than no intervention, and preserve honest
  telemetry completeness separately from context eligibility.
- [ ] #1021: Retain a positive, authenticated start-of-window external-change checkpoint and
  bounded recovery receipt for the exact scope and subject before claiming complete change
  coverage; prove the other three source slices independently before exposing scoring.
- [ ] #1021: Bind the `actions` producer to a bounded, target-scoped reader over existing Thor and
  Saga records whose watermark proves event-time completeness, with a reviewed intervention-outcome
  mapping and no second writer. The current audit record time and pre-lock entry construction cannot
  prove it.
- [ ] #1021: Bind the `excluded_windows` producer to an attested, revisioned reviewed `ChangeWindow`
  history with merged intervals and a positive initial state; current objects cannot prove absence.
- [ ] #1021: Attest post-window complete reconciliation for the exact subject so the lifecycle
  producer can issue positive coverage; unconfirmed tombstones remain incomplete.
- [ ] #1021: Render availability, the deployment opt-in, prerequisites, and per-source binding in
  Settings with English and Korean strings and tests, and add an audited Settings preference separate
  from deployment configuration before claiming the capability-flag contract.
- [x] P1: Run `test_closure_observation_survives_restart_and_rejects_conflicting_retry` against
  loopback PostgreSQL and prove migration, restart readback, exact duplicate handling, conflicting
  retry rejection, completeness counts, and rollback. All three completeness cases passed.
- [ ] Apply the Core closure-observation migration through its governed deployment path before
  deploying the changed readers and writers. Legacy missing observations remain unknown.
- [ ] P2-P3: Connect semantic context proposals to authenticated exact-target review, bounded
  governance activation, expiry/revocation, Forseti decisions, Saga audit, and dispatch revalidation.
  Test expected load, unexpected symptoms, production dependencies, and conflicting statements.
- [x] Bind structured authenticated commands through the Operator outbox and Var/Mimir/Saga bus,
  carry source-grounded chat drafts through Core/Operator, and persist/recheck context at Thor dispatch.
- [ ] Complete Operator scope/policy selection and lifecycle status presentation, independent runtime
  proof production, and live queued/in-flight safety qualification before closing P2-P3.
- [x] Collect all four normalized histories automatically with complete checkpoints, exact source
  mappings, bounded reads, initial-state handling, and independent admission before retention.
- [x] Return Saga-audited application status to the original Operator principal, preserve historical
  replay without reactivation, and test failed-worker restart and direct/multiplexed DLQ isolation.
- [x] Bind source-owned T1 vector cleanup to the actual library DSN and prove atomic failure,
  restart, legacy-unscoped cleanup, bounded-batch progress, and concurrent late-writer rejection.
- [ ] P4-P5: Prove one eligible revision per case, frozen replay sets, correction/deletion lineage,
  access-scoped cohorts, restart-safe Pattern publication/consumption, and independently qualified
  candidate promotion/demotion without bypassing ActionType-specific gates.
- [ ] P6: Verify read-only explanations, deadlines, recovery, and subscriber isolation, then retain
  separately authorized non-production drill receipts for the exact deployed revision and scope.
- [ ] After implementation, repeat critique/hardening rounds with at least ten reviewed concerns
  per round until no known unresolved finding above Low remains across P0-P6. Local observation
  hardening does not satisfy this full-scope exit condition.
- [x] #1022 criterion 1: the owner reviewed the
  [independent issuance design](../../roadmap/rules-and-detection/independent-operational-evidence.md)
  and recorded a decision for each open item in the
  [owner decision record](https://github.com/dotnetpower/fdai/issues/1022#issuecomment-5863412337); the
  [issuance ledger](independent-operational-evidence.md) tracks criteria 2-7.
- [x] #1022: call the issuance seam from this owner's boundaries (Var and Mimir command handling, Mimir
  transitions, Forseti and Thor context checks, Heimdall history retention and scoring, the Pattern read,
  and T1 reuse). Done in [PR #1649](https://github.com/dotnetpower/fdai/pull/1649) (`4c3fb8066`):
  `test_operational_evidence_owners.py` and `test_operational_evidence_owner_records.py` show each
  boundary holds for every rejection class, records that class with the rejection digest, and keeps its
  generic reason only for `unavailable`.
- [x] #1023, #1024, #1026: keep proposal and review controls, approved T1 intake, and connected
  qualification blocked until the issuance ledger shows the verifier and both registries
  `implemented` with focused tests and the issuance seam is called from every boundary; then
  re-evaluate each issue. Both conditions hold, and the owner re-evaluated all three issues on
  2026-09-28 and closed them as not planned. Their residual stays open in the P2-P3, P4-P5, P6, and
  hardening items above.

### Observation hardening evidence

Three local edit-and-check iterations addressed the observation slice. These are not the requested
post-implementation full-scope rounds. Severity describes the consequence before the local repair;
successful checks establish only the stated boundary.

| Concern | Severity | Evidence and disposition |
|---------|----------|--------------------------|
| A single endpoint labels a whole horizon complete | High | Fixed; endpoint-only and duplicate-count tests return partial. |
| Internal gaps hide an unobserved breach | High | Fixed; maximum-gap tests return partial. |
| Clustered samples pass when the gap ceiling exceeds the horizon | High | Fixed; minimum span coverage is independently checked. |
| Conflicting samples are treated as one trustworthy series | High | Fixed; conflicting equal-time values return unavailable. |
| Wrong target or metric enters scoring | High | Fixed; unfiltered-provider regressions reject mismatched identities. |
| Different dimensions manufacture temporal coverage | Medium | Fixed; mixed-series regression returns unavailable. |
| An oversized provider result is unbounded or silently truncated | Medium | Fixed; point-limit regression returns unavailable. |
| A stalled query holds the closure worker indefinitely | Medium | Fixed for cooperative async providers; deadline regression returns unavailable. |
| Early exit leaves the provider iterator open | Medium | Fixed; invalid-input and point-limit tests assert stream closure. |
| Task cancellation becomes a terminal observation | Medium | Preserved invariant; external cancellation propagates and closes the stream. |
| Order, duplicate samples, timezone representation, or signed zero changes identity | Medium | Fixed; canonical evidence tests preserve identity for equivalent input. |
| Evidence identity can be reused across scopes or targets | Medium | Fixed; evidence identity binds scope, target, series labels, and the observation window. |
| Grace-window samples replace the horizon value | Medium | Preserved invariant; the late breach remains separate from the horizon observation. |
| Missing intervention history produces an untreated forecast label | High | Open in P1 runtime composition; not solved by metric coverage. |
| Negative incomplete episodes lose the actual observation detail | High | Fixed in the local propagation/storage implementation; real PostgreSQL migration, restart, conflicting retry, completeness-count, and rollback regressions passed for all three completeness values. Deployment remains separate. |

### Context and reuse hardening evidence

These are local implementation reviews, not full-scope completion rounds. Each batch reviewed at
least twelve distinct concerns. A fixed row means the named focused boundary passed, not that its
missing producer, deployed dependency, or complete user workflow was qualified.

| Batch | Concern | Initial severity | Disposition and focused evidence |
|-------|---------|------------------|----------------------------------|
| Context | Missing history silently permits untreated scoring | High | Fixed at the consumer; missing binding, missing record, and unavailable admission yield versioned unscorable results. Producer remains open. |
| Context | Complete metrics are incorrectly relabeled missing after intervention | Medium | Fixed; metrics and scoring exclusions are independent in schema, model, closure, and retained observation. |
| Context | Adding 1.1 selects the latest schema for legacy 1.0 payloads | High | Fixed; declared and explicitly pinned versions must agree, and the validator cache keys the selected version. Contract regression passed. |
| Context | Complete-but-unscorable outcome crosses an unversioned boundary | Medium | Fixed; 1.0 serialized shape stays unchanged and exclusions require 1.1. |
| Context | Wrong scope or horizon history enters scoring | High | Fixed; exact identity/window checks precede admission and evidence inclusion. |
| Context | Self-declared history completeness becomes trusted evidence | High | Fixed; an independent exact-digest admission is mandatory. |
| Context | History expires during provider I/O | Medium | Fixed; completion-time freshness checks reject the response. |
| Context | Negative or abstained intervention-affected episode becomes a false negative | High | Fixed; closure retains observations without generating scored false negatives. |
| Context | Cohorts merge scope, purpose, release, scenario, or source classes | High | Fixed; versioned cohort keys partition each axis. |
| Context | Concurrent cohort writes lose one case | Medium | Fixed; bounded CAS plus audit and a forced two-reader race preserve both cases. |
| Context | Repeated delivery counts the same revision twice | Medium | Fixed; one current revision per case, exact-retry comparison, and immutable conflict rejection. |
| Context | Delayed Pattern reads a later mutable cohort | Medium | Fixed; publication names a content-addressed frozen snapshot. |
| Reuse | Throttled Pattern candidate is acknowledged while only in memory | Medium | Fixed at handler boundary; raise for pending scoped publication, repeat on duplicate, reconstruct after restart. Broker qualification remains open. |
| Reuse | Unknown Pattern fields or versions are accepted | Medium | Fixed; strict body and broker-envelope checks reject injected authority. First check exposed the required envelope field; corrected and rerun. |
| Reuse | Stored candidate tampering survives a read | High | Fixed; recompile and compare complete candidate content before returning it. |
| Reuse | Corrected or deleted source cases remain current pattern evidence | High | Fixed at read boundary; current revision and artifact digest are rechecked. Physical copied-data deletion remains open. |
| Reuse | Fresh operational context raises an existing deny/HIL ceiling | High | Fixed; use the most restrictive ceiling, with all three verdict states tested. |
| Reuse | Approved test claim self-attests absence of service impact | High | Fixed; separately admit exact observation, impact, and protected-signal classification before expected-signal suppression. |
| Reuse | Serial forecast stages lack a total deadline | Medium | Fixed; one total deadline retains already measured metrics and cancellation propagates. |
| Reuse | T1 checks expiry against the historical observation time | High | Fixed; injected decision clock is sampled after provider I/O. |
| Reuse | T1 accepts the exact expiry instant | Medium | Fixed; validity ends exclusively at expiry. |
| Reuse | T1 admission omits target, parameters, rule, and signature | High | Fixed; complete event and exact action enter the scope digest; mutation matrix rejects prior admission. |
| Reuse | Azure T1 verifier never supplies independent admission | Medium | Fixed; existing container provider reaches the adapter, and the exact request is tested. Missing independent receipts still hold. |
| Reuse | Stalled T1 provider blocks the worker | Medium | Fixed for cooperative async providers; total timeout abstains and external cancellation propagates. |

Known unresolved delivery concerns remain: authoritative forecast-history production (High),
authenticated context intake/review/activation/revocation and dispatch revalidation (High), copied
case-data retention/deletion (High), current Pattern-to-T1/authorized explanation integration
(Medium), and independent P5/P6 qualification (High readiness gap). None is reclassified as Low
because local tests passed. No protected merge, deployment, Azure call, or live model call occurred.

### September 15 lifecycle review

This additional local round reviewed twelve concerns. It is not a declaration that the full P0-P6
workflow has converged below Medium. The final lifecycle suite passed 102 cases at 94.03% combined
branch-inclusive coverage (derived projections 98%, context lifecycle 91%). The final real-PostgreSQL,
runtime, role, and retention slice passed 112 cases. These overlap the earlier 650-test regression.

| Concern | Initial severity | Result |
|---------|------------------|--------|
| PostgreSQL CAS cannot create the first cohort although the fake can | High | Fixed using atomic create-and-audit; actual PostgreSQL create and update passed. |
| Source tombstone completes while derived bodies remain | High | Fixed for the new layout; purge is a completion barrier and failure remains pending. |
| A write races deletion in an existing scope | High | Fixed; shared scope CAS forces source revalidation after contention. |
| First-ever projection write races deletion in an empty scope | High | Fixed; even empty deletion advances the scope revision. |
| Process caches retain case bodies after durable deletion | Medium | Fixed; removed redundant case-body and Pattern caches. |
| Mutable cohort growth invalidates old emission-marker lineage | Medium | Fixed; markers bind frozen snapshots rather than the current cohort. |
| Corrupt source references evade derived purge | High | Fixed; stored lineage is checked against projection bodies before mutation. |
| Oversized or contended state permits unbounded work | Medium | Fixed; count/byte/retry bounds and malformed-state tests pass. |
| Review changes the proposed scope, range, source, or policy | High | Fixed at transition boundary; immutable-envelope rejection matrix passes. |
| Self-review, overlap, or replay reactivates revoked context | High | Fixed at transition boundary; distinct review, overlap rejection, terminal revocation, and no-op duplicate tests pass. |
| Future-recorded current context is interpreted as no context | High | Fixed; temporal conflict holds instead of returning absence. |
| Context expires during verification or contains a broken revision chain | High | Fixed; completion-time interval checks and complete chain validation reject it. |

### Validation boundary

#### September 15 integration review

This round reviewed sixteen concrete concerns. Focused fixes do not establish full P0-P6 completion.

| Concern | Initial severity | Disposition and evidence |
|---------|------------------|--------------------------|
| Real psycopg interprets literal LIKE percent as a placeholder | High | Fixed with a bound prefix; actual PostgreSQL outbox claim and lease recovery passed. |
| Two workers publish the same live claim | Medium | Concurrent real PostgreSQL claim test observes one publisher and a replay-stable command. |
| A retry changes the authenticated actor or original request time | High | Exact durable principal and accepted time are retained; HTTP actor injection is rejected. |
| Contributor can review a test-context proposal | High | Real HTTP role matrix rejects review/revoke and permits the distinct Approver/Owner route. |
| Boolean or nonfinite expected bounds become measurements | High | Strict numeric boundary rejects them before outbox acceptance. |
| Malformed nested request crashes before schema validation | Medium | Var and Mimir validate complete typed commands before selecting operation. |
| Context review reaches Thor's unrelated action approval handler | High | Explicit non-action exclusion; handler never invoked even with a matching correlation. |
| Context commands pollute anomaly observation | Medium | Heimdall excludes governance commands from signal detection. |
| Corrected source remains usable after T1 verifier I/O | High | Current-case checks run before and after verification; source errors abstain. |
| T1 admission expires during final source read | High | Reassess current evidence after all source I/O. |
| Queued or restored action ignores context revocation | High | Durable exact binding plus Thor current-source/admission guard; missing and expired paths reject. |
| Shadow reports success without exercising the context guard | Medium | Shadow/enforce matrix passes the same current-context guard without shadow mutation. |
| Pattern query assumes principal and case digests are interchangeable | High | Independent exact principal/scope/purpose/arguments/release admission precedes state access. |
| Pattern query returns a source changed during reading | High | Current-source recheck before return; bounded deadline and explicit unavailable status. |
| Immutable history window prevents late corrections or renewal | Medium | Predecessor-bound revision CAS preserves old evidence and ignores stale replay; real legacy CAS verified. |
| Mimir candidate loses case scope before catalog review | High | Scope and purpose enter candidate digest; cross-scope rejection and current-source checks pass. |

Open implementation concerns remain above Low: automatic authoritative history acquisition and
independent operational proof production; operator selection/status workflow; approved Pattern-to-T1
enrollment with actual action metadata and frozen holdout evidence; downstream/legacy deletion;
and complete P5 qualification integration. The connected handoff documents how to validate the
implemented boundaries, but is not a claim that these missing implementations are configuration.

#### September 15 continuation

The command and read integration gaps described below now have local implementation: typed
authenticated outbox commands, Var/Mimir/Saga ownership, admitted Pattern queries, and late-bound
current-source checks. Independent receipts still require governed source/proof producers; these
changes do not make the deployment-only verifier policy suitable for operational context.
The operator explicitly deferred actual connected testing to a suitable environment. That decision
does not close remaining code integrations or lower their severity.

The 2026-09-15 completion design identified three unresolved binding decisions. Each needs an
explicit reviewed contract before a producer can issue trusted runtime evidence:

1. Which authoritative source/checkpoint covers all internal action attempts, external changes,
  deletions, and excluded experiment/maintenance windows for the exact forecast target and period?
2. Which authenticated operator and Var review messages, role policy, and independent verifier
  issue `test-context-transition`, `operational-test-context`, and
  `operational-test-observation` evidence? A caller-written actor string is not that evidence.
3. How does the authenticated principal's scope digest map to authorized case-history scopes and
  purposes for read-only Pattern explanations and current T1 selection? Equal-looking digests are
  not an authorization mapping.

`StateStoreDecisionEvidenceAdmissionProvider` resolves existing verified receipts only. The
repository's inspected deployment policy is purpose-bound to `deployment-apply`; it cannot be
reinterpreted as approval of test contexts or source completeness. Until the above bindings exist,
the new lifecycle is locally tested and its reader is composed, but command activation and complete
history scoring remain unavailable. These are not completed P2/P5/P6 outcomes or Low residuals.

The missing shell variables were a recoverable setup gap, not an unavailable PostgreSQL service.
The existing validation container's loopback binding and running state were checked before its
configuration was loaded privately into process-local `FDAI_VALIDATION_DATABASE_URL` and
`FDAI_DATABASE_URL`. No credential was printed or committed. Tests used isolated schemas with the
existing forecast-episode and publication-failure-count migrations plus the new Core column
migration; the case-history retention table was a minimal aggregate-query fixture, not a full
service migration. The committed `forecast_database` fixture now performs this preparation for
each PostgreSQL test, including the existing publication-counter migration. The current task
terminal retains both environment variables in the standard `postgresql+psycopg` URI format;
no credential-bearing file was created. Cleanup removed only task-owned schemas and was verified afterward.
This establishes focused local database behavior, not complete service deployment qualification.

P6 additionally requires an explicitly selected non-production target and separately authorized
live validation. That missing operational evidence is not a passing test or a Low-severity residual.

#### September 15 source and result review

This round reviewed the following sixteen concerns. The seven-file integrated Python check passed
206 tests before the additional hostile-row matrix; source/configuration coverage then passed 124
tests at 92.70% for the collector. The owning Console checks passed 128 tests plus both TypeScript
compilers. Existing state-transition compatibility passed 13 tests. These counts overlap.

| Concern | Initial severity | Disposition and evidence |
|---------|------------------|--------------------------|
| Destination-state filters hide unreviewed history | High | Fixed; explicit all-state query and actual PostgreSQL unknown-transition rejection; existing filtered reads still pass. |
| A pre-horizon exclusion is omitted | High | Active/inactive reconstruction covers retained pre-horizon state; missing initial state holds. |
| Deactivation exactly at horizon start still excludes the interval | Medium | Fixed; inclusive start-state evaluation passes active/inactive boundary cases. |
| Unordered reviewed states fail the PostgreSQL query contract | Medium | Fixed; canonical sorted state tuples. |
| Duplicate or unbounded active mappings survive validation | Medium | Fixed; unique bounded active states and proper active/inactive subset required. |
| Duplicate JSON keys silently change a reviewed source binding | Medium | Fixed; startup rejects duplicate object keys before source construction. |
| Wrong source, target, revision, conflict, truncation, or synthetic record enters history | High | Hostile typed-record matrix rejects all cases; no truncated-success fallback. |
| Unknown mapping or initial state implies absence | High | Missing four-source mapping rejects startup; unknown initial state holds collection. |
| History database errors discard complete measured telemetry | Medium | Fixed; provider boundary records a redacted failure and retains metrics with a scoring exclusion. |
| Admission I/O failures or cancellation become valid scoring | High | Errors exclude scoring; cancellation propagates rather than becoming a result. |
| Result-source startup or cleanup stalls indefinitely | Medium | Fixed for cooperative async providers; five-second bounds, timeout and cancellation tests. |
| Calling start cannot recover a failed worker | Medium | Fixed; explicit restart replaces terminal workers only; no duplicate live task or automatic poison retry. |
| Worker failure is unobserved or leaks provider error details | Medium | Done callbacks retrieve terminal errors and log only worker name and error type. |
| Result-topic invalid JSON cannot reach DLQ | Medium | Fixed for direct and multiplexed transports; sanitized DLQ acceptance precedes commit. |
| Allowing result DLQ accidentally grants result publication | High | Normal result publication remains denied by the Operator adapter in both transport layouts. |
| Draft replay drops data or browser date normalization changes the interval | Medium | Fixed; positive server/local round-trip, no-receipt rejection, invalid date, and authority-injection checks pass. |

Full P0-P6 convergence remains blocked by implementation, not connectivity: raw source producers,
independent operational proof issuance and trust mappings, authenticated scope/policy selection UI,
approved Pattern-to-T1 enrollment with real action and holdout evidence, legacy/downstream physical
deletion, and complete P5 integration. The selected separate read-only verifier workload is a design
direction only; no source-binding policy, workload, or proof issuer was implemented or deployed.

#### September 15 vector retention review

This round covers the T1 library, not every downstream store. The real regression uses the private
forecast schema fixture, an existing pgvector extension, and actual SQL; it does not run the legacy
shared-database `alembic upgrade head` tests. In-memory source metadata and artifacts exercise the
existing retention service around the real vector database, so this is not full service deployment.

| Concern | Initial severity | Disposition and evidence |
|---------|------------------|--------------------------|
| Context-free upsert changes action but keeps an unrelated case | High | Atomic conflict predicate rejects rule/action/parameter/incident substitution with or without incoming context. |
| Same signature moves to another case or scope | High | Existing contextual identity is immutable; actual SQL rejects changed case/scope. |
| Statistics-only maintenance loses compatibility | Medium | Same-action context-free update preserves the original case and updates statistics. |
| Retention deletes from the case-metadata database instead of the T1 database | High | Separate `pattern_library_dsn` binds the actual configured T1 DSN; distinct-database runtime regression. |
| Legal hold or missing source claim reaches a downstream deleter | High | Composite and library reject before downstream or database work. |
| Cleanup removes another case's vectors | High | Exact case matching preserves the unrelated scoped row in real PostgreSQL. |
| Legacy unscoped copies survive deletion | High | Same global case identity is deleted even without old scope fields. |
| Concurrent write resurrects a deleted case | High | Shared transaction lock and permanent case fence; concurrent writer/purge regression. |
| Context-free retry resurrects the old signature after restart | High | Permanent signature fence rejects the replay through a new library instance. |
| DB failure leaves partial markers or premature source tombstone | High | Trigger-injected failure rolls back both SQL changes; source remains pending until successful retry. |
| More than 1,000 vectors permanently block deletion | Medium | Committed bounded batches make progress; 1,002 linked vectors are deleted across two calls without premature source completion. |
| Duplicate purge recreates data or changes source state | Medium | Exact duplicate purge after cleanup is idempotent; source retention returns no new deletion. |
| A stalled connection or lock blocks retention indefinitely | Medium | Total 15-second write/purge deadlines; cancellation propagates, and no unbounded retry loop is added. |
| Retention markers disclose copied case bodies | Medium | Real persisted marker assertions contain digests and no case identifier or execution authority. |

The database-wide write/purge advisory lock is a bounded serialization tradeoff; search remains
unlocked. Measure contention on the connected target before changing its partitioning. Full P0-P6
completion remains open for raw source/proof issuance, authenticated UI workflow, approved T1 intake,
other downstream cleanup, and independent P5/P6 qualification.
