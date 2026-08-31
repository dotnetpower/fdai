---
title: Goals and Metrics
---
# Goals and Metrics

The roadmap optimizes for **autonomy with proof**. Every autonomy claim is backed by a
measured baseline; nothing is asserted from estimation. Improvement factors below (`5×`,
`large reduction`, `1/5`) are **targets**, not achieved results - they may only be stated as
achieved once both the reference baseline and the FDAI treatment have been measured on
the same scenario set (see the [measurement-first rule](#measurement-first-rule)).

This document is the source of truth for KPIs. It aligns with the tier coverage targets in
[architecture.instructions.md](../../../.github/instructions/architecture.instructions.md) and is
operationalized by [phase-0-instrumentation.md](../phases/phase-0-instrumentation.md).

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Deterministic KPI and guard-metric aggregation | implemented | `core/measurement/mttr.py`; `dora.py`; `regression.py`; focused tests under `tests/core/measurement/` | MTTR, change, regression, latency, model, and pattern metrics have executable reducers and fail-closed checks. |
| Promotion and operational evidence evaluation | implemented | `core/measurement/promotion_gate.py`; `operational_promotion.py`; focused promotion tests | Promotion evaluation binds revision, scenario, samples, confidence, guards, and outcome evidence. A result can be ready only when a current shared decision-evidence admission matches the complete batch. Legacy stored receipts remain readable but cannot authorize promotion without receipt and verification-bundle digests. |
| Complete decision boundary admission coverage | implemented | `config/decision-boundary-inventory.json`; `scripts/quality/architecture/check-decision-boundary-coverage.py`; `tests/integration/scripts/test_decision_boundary_coverage.py`; focused boundary tests | All 15 registered positive decision boundaries resolve decision-critical evidence through the shared admission contract and hold for review when the admission is absent or rejected. The guard checks the inventory in both directions, so an intentionally uncovered registered boundary fails. The readiness matrix denies missing, stale, incomplete, conflicting, synthetic, wrong-purpose, and wrong-scope evidence by name. |
| Governed operational coverage claim contract | implemented | `packages/service-contracts/src/fdai_service_contracts/operational_coverage.py`; `packages/service-contracts/tests/test_operational_coverage.py` | Immutable denominator, terminal disposition, freshness, exact basis-point, zero-tolerance, and digest checks prevent an incomplete universe from becoming a 99% claim. The receipt grants no execution authority. |
| Governed baseline and treatment cohort claim | implemented | `packages/service-contracts/src/fdai_service_contracts/baseline_cohort.py`; `services/core-control-plane/src/fdai/core/measurement/baseline_cohort_claim.py`; `tools/cohort_receipt.py`; `tools/baseline_run.py`; focused contract, claim, and runner tests | The receipt binds one pinned revision, the frozen scenario set and its digest, both arm report and provenance digests, per-arm sample counts, confidence intervals with their absolute values, completeness and provenance references, and every zero-threshold guard. Eligibility is only the evaluator's output: it requires a current independent decision-evidence admission and a governed external artifact origin, so no artifact committed here can be eligible. The retained non-synthetic cohort itself is still open. |
| Canonical decision-critical evidence envelope | implemented | `packages/service-contracts/src/fdai_service_contracts/decision_evidence.py`; `schemas/decision-critical-evidence/1.0.0.json`; focused contract tests | The envelope binds the evidence and its authentication proof, authority, scope, purpose, exact producer and method, time, policy-derived freshness, completeness proof, conflict disposition, provenance, and synthetic status. Claim preflight can only reject input or pass it to separate authoritative verification; it never claims live readiness. Existing decision boundaries still require migration. |
| Independent decision-evidence verification | in-progress | `decision_evidence_verification.py`; `core/readiness/decision_evidence.py`; `shared/providers/decision_evidence_verifier.py`; `delivery/azure/decision_evidence.py`; focused contract, readiness, and Azure adapter tests | Five content-addressed proofs and the shared admission are implemented across every boundary in the inventory. Production provider composition and governed live bundles remain open, so each deployed boundary currently holds for review instead of admitting live evidence. |
| Frozen scenario-set accounting | in-progress | `tests/scenarios/manifests/v2026.07.json`; `tests/scenarios/cross-objective/v2026.07-sre.json`; `tests/scenarios/enrichment/v2026.07/sre-cluster-diagnostics-missing-001.json`; `test_frozen.py`; `test_v2026_07_replay.py` | The SRE pack now has all six executable dimensions and is `complete` in the manifest. Its full-loop closure comes from an in-process frozen observation source replayed in shadow, so a deployed-runtime authoritative observation is still open, and the other four packs are also incomplete. |
| Operational intelligence 99% closure evidence | in-progress | `config/azure-discovery-live-evidence.json`; linked governance, RCA, execution, document-ingestion, and deployment ledgers | Azure discovery has a current authority-free coverage receipt. The remaining domains lack one governed exact-revision evidence set, so no aggregate 99% claim is eligible. |
| Live KPI baseline, treatment, and dashboard closure | in-progress | [Data Collection and Telemetry](#data-collection-and-telemetry); `config/constitution-traceability.json` requirement `FDAI-CONST-002` | Runtime records and jobs exist, but no retained full live baseline/treatment cohort proves all success and zero-threshold guard metrics on one pinned revision. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-31 | in-progress | Governed the claim-eligibility decision for a non-synthetic baseline and treatment cohort. `BaselineTreatmentCohortReceipt` embeds one `DecisionCriticalEvidenceReceipt` per arm and binds the frozen scenario-set version and digest, one pinned `fdai_revision`, each arm's report and provenance digest, its sample count, every success metric as a confidence interval that contains its absolute value, the completeness and provenance references, and every zero-threshold guard. The receipt carries no eligibility field: eligibility exists only as the output of `evaluate_cohort_claim`, which fails closed with named reasons for a missing receipt, synthetic evidence, a rejected claim preflight, evidence without a current independent admission, a report or provenance digest mismatch, a revision or scenario-set mismatch, incomplete metrics, intervals, provenance, or guards, a breached guard, a cohort under 30 samples in either arm, and a repository-origin artifact. Admitted receipt digests come from the existing decision-evidence admission rather than from the artifact, so no artifact committed to this repository can evaluate as eligible. `tools/baseline_run.py` gained an optional `--cohort-receipt` preflight and a `--require-claim-eligible` gate that exits 4, and the regenerated `docs/baselines/v2026.07.json` stays a 12-sample synthetic harness that reports `claim_eligible=false`, `receipt_missing`, and the exact external residual. | `current change`; `packages/service-contracts/src/fdai_service_contracts/baseline_cohort.py`; `services/core-control-plane/src/fdai/core/measurement/baseline_cohort_claim.py`; `tools/cohort_receipt.py`; `tools/baseline_run.py`; `docs/baselines/v2026.07.json`; `uv run pytest -q --no-cov packages/service-contracts/tests services/core-control-plane/tests/core/measurement services/core-control-plane/tests/tools services/core-control-plane/tests/scenarios` passed 603 focused cases; the six failures in `tests/core/measurement/test_operational_promotion.py` are identical at `c1cb634d9` without this change. Ruff and strict mypy passed. | The evaluator is proved only against fixtures. Retaining governed non-synthetic baseline and treatment cohorts of at least 30 samples each, on one pinned revision and the identical frozen scenario set, with a current independent decision-evidence admission, requires deployed-runtime evidence and stays open. |
| 2026-08-31 | in-progress | Corrected the full-loop effect evidence recorded below after review. The projection that dropped an observation the contract cannot represent left the verification verdict `verified`, so a real `verify_effect` result whose observation fell inside the prediction window but after `recorded_at` still raised the contract validation error inside dispatch; admissibility now runs before the decision, the shadow effect audit entry, and the projection, and holds that evidence as `observation_not_yet_recorded` while an already-held verdict keeps its own reason. The frozen replay also read wall clock for action creation, dispatch, and recording, so its frozen prediction and observation preceded the action they described; `ControlLoop` and `ActionBuilder` now share one injected clock, the shadow effect entry records the action creation and dispatch window beside the raw value, and the replay asserts the creation, prediction, dispatch, observation, and recording order it claims. | `current change`; `services/core-control-plane/src/fdai/core/mscp_profile/{effect_verification.py,response_outcome.py,shadow_effect.py}`; `services/core-control-plane/src/fdai/core/control_loop/{orchestrator.py,_execution.py}`; `services/core-control-plane/src/fdai/core/executor/action_builder.py`; `services/core-control-plane/tests/scenarios/{test_v2026_07_replay.py,test_frozen.py}`; `uv run pytest -q --no-cov services/core-control-plane/tests/scenarios services/core-control-plane/tests/core/mscp_profile services/core-control-plane/tests/core/executor services/core-control-plane/tests/pipeline` passed. The new frozen `not_yet_recorded` case is mutation-verified: reverting the hold fails it with the contract validation error. | The observation source is still an in-process frozen provider replayed in shadow, so the deployed-runtime observation and the remaining packs stay open. |
| 2026-08-31 | in-progress | Gave the `sre` pack its `successful_full_loop` evidence. The frozen `sre.cluster-diagnostics-missing.001` scenario now replays through the real control loop on the shipped `ShadowExecutor` rather than the self-attesting test executor, with the MSCP expected-effect provider and independent effect observer bound through the shipped seam. The replay may close `executed` / `auto` only because an independent authoritative observation matched the pre-dispatch prediction: the observer receives the action and the prediction and never the executor receipt, the publisher, or the audit store, and unbinding it leaves a published shadow PR that the loop still refuses to call success. Four fail-closed cases - missing, stale, incomplete, and conflicting effect evidence - each end `abstain` with the pinned verification status, reason, and unscorable or mismatch response label, while the terminal dispatch, effect-verification, and measurement audit entries share one action and event lineage and every execution result and published PR stays in shadow. The stale case exposed a defect that is fixed here: an out-of-window or not-yet-recorded observation raised a contract validation error during dispatch instead of failing closed, so the response-outcome projection now drops an observation the contract cannot represent while the shadow effect audit entry keeps the raw value. | `current change`; `services/core-control-plane/src/fdai/core/mscp_profile/response_outcome.py`; `services/core-control-plane/tests/scenarios/enrichment/v2026.07/sre-cluster-diagnostics-missing-001.json`; `services/core-control-plane/tests/scenarios/{test_v2026_07_replay.py,test_frozen.py,manifests/v2026.07.json}`; `uv run pytest -q --no-cov services/core-control-plane/tests/scenarios services/core-control-plane/tests/core/mscp_profile services/core-control-plane/tests/contracts/test_response_outcome.py services/core-control-plane/tests/core/measurement services/core-control-plane/tests/core/workflow/test_outcome_verification.py services/core-control-plane/tests/pipeline/test_unified_control_loop.py services/core-control-plane/tests/pipeline/test_control_loop_e2e.py --deselect services/core-control-plane/tests/core/measurement/test_operational_promotion.py` passed 485 focused cases; that one deselected file was already red at `4da5efd50` before this change. The stale case is mutation-verified: reverting the projection fix fails it with the contract validation error. | The observation source is an in-process frozen provider replayed in shadow, so a deployed-runtime authoritative observation and recurrence closure remain open, as do the four other packs and the non-synthetic baseline and treatment. |
| 2026-08-31 | in-progress | Closed the three remaining cross-objective review findings. The free-form ActionType-to-direction map is gone: every option now carries a typed frozen `objective_effects` record that the conflict schema validates and the new `DomainOptionEvidence` contract admits, and the conflict relation is the independent check `conflicting_objective_effects`, which raises arbitration only when two domains hold opposite-signed utilities on the same governed objective id. A negative control that gives both domains the effects one replay actually produced declines instead, so the relation cannot be satisfied by a recommendation label. Each replay's canonical event id, cited rule ids, terminal audit idempotency key, and dry-run receipt digest now travel as option evidence references into the specialist contributions, the arbitration request, the decision case, and the terminal verdict, and the ingress rejects a payload whose only lineage is a synthetic `specialist:*` marker. The unavailable-owner close is automatic: the composition root binds a runtime availability probe through `runtime_health.bind_availability_probe`, and Forseti closes the request it just published as an explicit `hil` verdict with no ActionType, no initiator, and no winning domain, so no test drives that closure by hand. | `current change`; `services/core-control-plane/src/fdai/core/decision_case/domain.py`; `services/core-control-plane/src/fdai/agents/{forseti.py,_framework/forseti_decision_helpers.py,_framework/runtime_health.py,_framework/runtime.py}`; `services/core-control-plane/src/fdai/core/operational_planning/coordinator.py`; `services/core-control-plane/tests/scenarios/cross-objective/{schema.json,v2026.07-sre.json}`; `services/core-control-plane/tests/scenarios/test_v2026_07_replay.py`; `uv run pytest -q --no-cov services/core-control-plane/tests/scenarios services/core-control-plane/tests/agents/test_arbitration.py services/core-control-plane/tests/core/decision_case services/core-control-plane/tests/core/operational_planning services/core-control-plane/tests/core/operational_context` passed 396 focused cases. | The conflict evidence is still a shadow replay over the in-memory bus, so the deployed-runtime arbitration receipt stays open, and no shipped rule catalog emits signed objective effects yet, so the frozen enrichment still supplies them. |
| 2026-08-31 | in-progress | Corrected the cross-objective conflict evidence recorded below after review. Arbitration no longer receives hand-authored advice or a synthetic target: each option's recommendation is derived from the ActionType its own replay produced, and the contested target is derived from the frozen ontology graph as the one resource both replayed targets reach. Forseti is bound to a materialized operational context admitted through the shared decision-evidence contract, so the arbitration request and the terminal verdict both carry the canonical decision case, its context snapshot identity, and its per-domain evidence references, and Saga retains the terminal verdict in the append-only audit chain. Missing arbitration authority no longer ends without a terminal result: it closes through the shipped `conflicts_require_hil` degradation policy and Forseti's existing no-rule-match judgment as a shadow-only `hil` verdict that carries no ActionType, no initiator, and no action authority, with retained audit evidence and no newly invented authority. The frozen conflict artifact is now inventoried directly by its own id through the manifest `conflict_spec_ids` field, and the frozen schema, GUID, customer-data, ASCII, and duplicate-key guards now cover it. | `current change`; `services/core-control-plane/tests/scenarios/cross-objective/{schema.json,v2026.07-sre.json}`; `services/core-control-plane/tests/scenarios/{test_v2026_07_replay.py,test_frozen.py,manifest.schema.json,manifests/v2026.07.json}`; `uv run pytest -q --no-cov services/core-control-plane/tests/scenarios services/core-control-plane/tests/agents/test_arbitration.py services/core-control-plane/tests/core/operational_planning services/core-control-plane/tests/core/operational_context services/core-control-plane/tests/core/decision_case services/core-control-plane/tests/core/risk_gate/test_precedence.py` passed 404 focused cases. | The evidence is still a shadow replay over the in-memory bus, so a deployed-runtime arbitration receipt on the production bus remains open, as do SRE `successful_full_loop` and the four remaining packs. |
| 2026-08-31 | in-progress | Gave the `sre` pack its `cross_objective_conflict` evidence. A frozen customer-agnostic conflict spec composes three options that each replay a frozen v2026.07 scenario through the real control loop, so eligibility is a runtime property rather than a hand-authored candidate. Two grounded eligible options - Change Safety against Cost Governance - contend for one shared logical target while the Resilience option abstains and contributes `hold`. The conflict then crosses the shipped governed boundary: Forseti raises exactly one `object.arbitration-request` with the correlation, shared target, and every objective at stake, and Odin remains the sole arbitration owner. Because the highest-precedence objective is the one whose evidence stayed unresolved, no eligible option inherits the win and the terminal disposition is an `arbitration_unresolved` HIL verdict carrying no ActionType and no initiator. Removing Odin leaves the conflict raised and unresolved with no decision, no verdict, and no recorded winner, and every grounded execution and published PR stays in shadow in both cases. | `current change`; `services/core-control-plane/tests/scenarios/cross-objective/{schema.json,v2026.07-sre.json}`; `services/core-control-plane/tests/scenarios/test_v2026_07_replay.py`; `manifests/v2026.07.json`; `uv run pytest -q --no-cov services/core-control-plane/tests/scenarios services/core-control-plane/tests/agents/test_arbitration.py services/core-control-plane/tests/core/risk_gate/test_precedence.py` passed 209 focused cases. | `successful_full_loop` still requires independent authoritative recovery and recurrence-closure evidence. The conflict is proved in shadow against the in-memory bus, so a deployed-runtime arbitration receipt on the production bus remains open, as do the other four packs and the non-synthetic baseline and treatment. |
| 2026-08-31 | implemented | Closed the FDAI-CONST-002 boundary inventory. Causal closure, effect-model activation, workflow gates, and workflow outcome acceptance now require a current shared admission bound to their exact evidence, scope, purpose, and source revision, and each holds for review when the admission is absent or rejected. `config/decision-boundary-inventory.json` records the complete inventory, and a new coverage guard checks it in both directions so a registered boundary without the shared admission fails and a source boundary missing from the inventory fails too. The readiness boundary now denies missing, stale, incomplete, conflicting, synthetic, wrong-purpose, and wrong-scope evidence by name. | `current change`; `config/decision-boundary-inventory.json`; `scripts/quality/architecture/check-decision-boundary-coverage.py`; `core/rca/hypothesis.py`; `core/assurance_twin/model_promotion.py`; `core/workflow/gate_resolver.py`; `core/workflow/outcome_verification.py`; focused rca, assurance-twin, persistence, workflow, readiness, and script-integration checks; `check-constitution.py`; Ruff and strict mypy. | Bind production verifier and admission providers in runtime composition and retain governed live bundles before FDAI-CONST-002 can move beyond `partial`. |
| 2026-08-29 | in-progress | Corrected the FDAI-CONST-002 boundary inventory after an independent closure review found additional subsystem receipt gates. The migrated boundaries remain implemented, but rubric and chat-policy promotion, causal closure and Dynamic model activation, current-case T1 reuse, and workflow outcome or approval cannot be counted as shared-contract adoption yet. Standing authority remains an explicit shadow-only, unwired exclusion rather than a hidden completion claim. | `current change`; source inventory across `core/quality_gate`, `core/conversation_assurance`, `core/rca`, `core/tiers/t1_lightweight`, `core/workflow`, and `core/assurance_twin`; traceability remains `partial`. | Migrate or explicitly outer-gate each named positive decision boundary, add an automated coverage guard, bind production providers, and retain governed live bundles. |
| 2026-08-29 | implemented | Migrated the runtime operational-context snapshot used by decision cases and planning. The final replay identity binds the pre-admission graph digest and admission, while missing or rejected admission becomes an explicit conflict and fixes autonomy at `SHADOW_ONLY`. The production pantheon requires admission and has no default-positive provider. | `current change`; context model, materializer, runtime pantheon composition, and focused context, agent, and bootstrap checks; Ruff and strict mypy. | Bind the production context admission provider and retain a governed snapshot bundle. |
| 2026-08-29 | in-progress | Refreshed the FDAI-CONST-002 traceability inventory with the shared receipt, five-proof bundle, migrated qualification, promotion, query, state-bundle, analyzer, startup-readiness, and operational-readiness boundaries and their focused tests. The constitutional status remains `partial`; no local test or adapter path is recorded as governed live evidence. | `current change`; `config/constitution-traceability.json`; constitution and focused boundary checks. | Inventory and migrate remaining direct state consumers, bind production verifier/admission providers, and retain governed live bundles before changing the status to `implemented`. |
| 2026-08-29 | implemented | Migrated operational-readiness review before audit and publication. The exact findings, scope, environment, and source revision require a current admission. Missing or rejected admission preserves the truthful verdict but forces `mode=shadow`, makes `blocks_handoff=false`, and records the effective mode plus rejection references in the audit. | `current change`; readiness report and admission models, application service, focused coordinator, service, checklist, remediation, and runtime-ingest checks; Ruff and strict mypy. | Bind production readiness evidence providers and retain one governed review bundle. Runtime verifier composition and direct-state consumers remain open. |
| 2026-08-29 | implemented | Migrated startup readiness before persistence and transition publication. The coordinator binds the complete reduced report and probe-set revision to a current admission. Missing or rejected admission changes a non-blocked result to `DEGRADED`, caps every capability at `SHADOW`, and persists the rejection reasons instead of a `READY` claim. | `current change`; readiness models, coordinator, runtime composition, focused coordinator and runtime tests; Ruff and strict mypy. | Bind the startup coordinator to the production verifier registry and retain one live report bundle. Migrate operational-readiness and remaining direct-state boundaries. |
| 2026-08-29 | implemented | Migrated analyzer target selection when a projected Resource carries state metadata. The resolver derives exact state and resource-scope digests, requests a trusted admission, and skips the target with `unverified_state_fact` when the provider is absent or the admission does not match. Resources with identity and type but no state claim preserve the existing eligible path. | `current change`; analyzer target resolver and focused routed-tick tests; Ruff and strict mypy. | Bind the analyzer job to the trusted admission provider and migrate the remaining direct-state consumers. |
| 2026-08-29 | implemented | Migrated operational-context state evidence to the shared admission. Each bundle retains the admission in its replay identity, recomputes the exact state-item and scope digests without a circular commitment, and lowers to `SHADOW_ONLY` with an explicit hold when admission is absent, mismatched, or expired. | `current change`; operational evidence models, identity, builder, shared admission mapping, and focused bundle/materializer checks; Ruff and strict mypy. | Bind an authoritative state admission producer and migrate direct state consumers. Readiness and runtime composition remain open. |
| 2026-08-29 | implemented | Migrated secured ontology query consumption to the shared admission contract. Query results may still be retained for diagnosis, but dependency resolution and decision-critical FunctionType verification require a current admission bound to the exact projected result, scope, purpose, ontology release, and source generation. The production admission-provider seam is unbound and therefore fails closed. | `current change`; query authority, source handlers, semantic composition, and focused query and composition checks; Ruff and strict mypy. | Bind the production query admission provider to the trusted verifier registry and retain a cross-service receipt and bundle. Migrate readiness and state boundaries. |
| 2026-08-29 | implemented | Migrated operational promotion readiness to the shared decision-evidence admission. The evaluator binds the exact batch, revision, scenario, ActionType, purpose, and validity window, persists both receipt and verification-bundle digests, and cannot produce a ready receipt without them. Storage reads legacy 1.0 receipts for diagnosis, while both the registry and direct executor reject them for enforcement. | `current change`; operational promotion evaluator, risk registry, persistence codec, direct executor, and focused promotion tests; Ruff and strict mypy. | Bind the production promotion evidence source to the independent verifier registry. Migrate the remaining readiness, query, and state boundaries. |
| 2026-08-29 | implemented | Added a short-lived no-authority admission emitted only by successful independent decision-evidence verification, then migrated ChatOps qualification to derive exact batch evidence and scope digests and fail closed on an absent, mismatched, or expired admission. The standalone qualification CLI remains diagnostic and cannot claim qualification without a verifier binding. | `current change`; shared verifier seam, Core readiness gate, ChatOps qualification reducer, focused unit and CLI checks, Ruff, and strict mypy. | Bind the verifier registry in runtime composition and migrate the remaining readiness, query, state, and promotion decision boundaries. Retain a production qualification receipt and bundle before claiming a validated cohort. |
| 2026-08-29 | implemented | Added the independent verifier contract and readiness gate for all five decision-critical proof classes. Versioned verifier bindings now carry trust anchors, validity windows, and revocation state. Verification fails closed for an absent or stale binding, producer self-verification, receipt or subject mismatch, expired proof, timeout, and synthetic evidence. The Azure adapter authenticates authoritative readback with Managed Identity and never returns or stores the access token. | `current change`; service-contract model and registered Draft 2020-12 schema, provider-neutral verifier seam, Core readiness gate, Azure adapter, and focused contract, readiness, and Azure adapter tests. | Bind the verifier registry in runtime composition and migrate each existing readiness, query, state, promotion, and qualification boundary before changing FDAI-CONST-002 from `partial`. |
| 2026-08-29 | implemented | Added the provider-neutral `DecisionCriticalEvidenceReceipt` foundation required by FDAI-CONST-002. Its canonical digest binds the evidence payload, authentication proof, authority class, source, scope, purpose, producer and method versions, source revision, event and recorded time, policy-derived freshness, completeness and conflict proofs, provenance, synthetic status, and no-authority flag. Review blocked a positive live-eligibility result from self-attested fields, so the contract now only rejects invalid claims or passes them to a separate authoritative verifier. The registered schema boundary also runs the semantic model checks that JSON Schema cannot express. | `current change`; service-contract model, Draft 2020-12 schema plus semantic validation, package registry and exports, traceability record, and focused contract tests. | Implement trusted authentication, evidence, completeness, conflict, and policy verifiers while migrating readiness, query, state, promotion, and qualification boundaries before changing FDAI-CONST-002 from `partial`. |
| 2026-08-29 | in-progress | Added truthful A3-E non-applicability evidence for `sre.slo-signal-source-unmapped.002`. The replay now proves the routing terminal produces no finding or T2 Action, never enters execution-authorization evaluation, emits no execution result or PR, and records the abstain. Review rejected two proposed claims: a publisher's own in-memory record is dispatch evidence rather than independent SRE effect verification, and hand-authored candidates sent directly to `PrecedenceResolver` do not prove runtime arbitration. Those tests and manifest claims were removed before commit. | `current change`; `services/core-control-plane/tests/scenarios/test_v2026_07_replay.py`; `manifests/v2026.07.json`; focused scenario, manifest, Ruff, and strict mypy checks. | `successful_full_loop` still requires independent authoritative recovery and recurrence-closure evidence. `cross_objective_conflict` still requires competing actions produced and audited through the scenario runtime and production arbitration path. The non-synthetic baseline and treatment also remain open. |
| 2026-08-29 | in-progress | Reassessed the operational-intelligence closure boundary. Azure discovery remains authority-free and complete for its recorded canary, and ACL-filtered hybrid document retrieval is implemented, but governance ownership, an approved incident corpus, remediation authority and effect drills, deployment-owned Knowledge inputs, a 30-90 day cohort, and operator connectivity evidence remain open. AWS, GCP, and cross-cloud validation remain blocked by the Azure-only implementation policy and absent approved provider scope. | `current change`; Azure discovery receipt; governance, RCA, execution, document-ingestion, security, and CSP-neutrality ledgers; focused hybrid retrieval checks. | Satisfy the ordered external exit evidence below without using synthetic evidence as operational validation. |
| 2026-08-29 | implemented | Hardening round 1 reviewed 22 coverage-contract lenses and normalized all receipt timestamps to UTC before digesting, so equivalent instants with different offsets share one replay identity. | `current change`; focused operational coverage tests. | Bind authoritative producers and retain governed receipts. |
| 2026-08-28 | implemented | Added one provider-neutral operational coverage receipt for asset inventory, governance evaluation, operating scope, incident diagnosis, remediation effects, and knowledge grounding. It keeps policy outcome separate from evaluability, retains every uncovered item in the denominator, and makes claim eligibility a deterministic result of complete accounting, freshness, an exact basis-point threshold, and zero-tolerance dispositions. | `current change`; `operational_coverage.py`; focused contract tests passed 13 cases; Ruff and strict mypy passed. | Bind each producer to its authoritative denominator and retain governed receipts before making a 99% operational claim. |
| 2026-08-19 | implemented | Regenerated the committed reference baseline, which still described a 9-scenario frozen set after three `sre.*` scenarios made it 12. Every published metric, sample size, and confidence interval therefore described a set that no longer existed; `routed_correctly_rate` was 0.111 and is 0.083. The baseline test now derives the scenario count and the t2 economics from the set instead of pinning `9` and "exactly one t2 scenario", so the next addition fails loudly at the artifact rather than silently in the numbers. | `current change`; `docs/baselines/v2026.07.{json,md}` and the Korean pair regenerated by `tools.baseline_run`; the core and shared-package suites passed 11913 cases with 131 skips, including the previously red `test_baseline_runner` and `test_models_facade_only`. | The baseline remains `synthetic-harness` evidence and is not claim eligible; a live baseline and treatment cohort is still the open item below. |
| 2026-08-19 | in-progress | Gave the `sre` pack its third coverage dimension with asserted evidence rather than a manifest entry. A dedicated test replays `sre.cluster-diagnostics-missing.001` against a publisher that drops the first request, so the effect outcome is genuinely unknown, then proves the run closes a terminal `publish_outcome_unknown` audit entry before the error escapes, records no PR, caches nothing, and that a retry over the same executor publishes exactly one shadow PR. This is the first `partial_failure_recovery` evidence in any pack. | `current change`; `tests/scenarios` and `test_shadow_eval.py` passed 116 focused cases; the new test is mutation-verified - making `_close_unknown_publish` a no-op fails it with `assert 0 == 1`. | `successful_full_loop`, `cross_objective_conflict`, and `a3e_or_non_applicability` remain unevidenced for `sre`. A full-loop claim needs independent effect verification, which shadow execution does not provide, and an A3-E claim needs the unwired standing-authority evaluator. The manifest check still only proves a cited test exists, not that it asserts its dimension. |
| 2026-08-14 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance and separated executable measurement mechanics from unproven outcome claims. | `current change`; measurement source, focused tests, scenario manifest, and constitutional register cited above. | Complete scenario coverage and retain a live baseline/treatment cohort with authoritative outcome closure. |
| 2026-08-18 | in-progress | Gave the `sre` capability pack its first scenarios, so no pack is `missing`. Three frozen scenarios replay through the real control loop with the shipped catalog: an observability precondition that fires `kubernetes-cluster.diagnostic-settings-required` and opens a shadow PR, an error-budget burn on an unmodelled target that abstains and publishes nothing, and telemetry retention above the reviewed ceiling. One scenario per existing domain keeps the balance check satisfied. Only `unknown_or_deny` and `deterministic_replay_with_evidence` are claimed, because the remaining four dimensions have no evidence yet; the pack stays `partial` and the set stays `incomplete`. | `current change`; `tests/scenarios` passed 98 focused cases, including all three new replays through `ControlLoop.process` against the shipped rules, policies, and ActionTypes. | Author the successful-full-loop, cross-objective-conflict, partial-failure-recovery, and A3-E-or-non-applicability cases for every pack. A full-loop claim additionally needs independent effect verification, which shadow execution does not provide. |

### Remaining work

- [x] Evidence the SRE `successful_full_loop` dimension with a replay that closes only from an independent authoritative effect observation and fails closed on missing, stale, incomplete, and conflicting evidence. Evidence: `services/core-control-plane/tests/scenarios/enrichment/v2026.07/sre-cluster-diagnostics-missing-001.json`, the six focused full-loop tests in `test_v2026_07_replay.py`, and the two frozen effect-evidence guards in `test_frozen.py`.
- [ ] Complete SRE `successful_full_loop` closure against a deployed-runtime authoritative observation source and add recurrence-closure evidence, because the current observation is an in-process frozen provider replayed in shadow.
- [x] Complete SRE `cross_objective_conflict` with scenario-produced competing options audited through the shipped Forseti-to-Odin arbitration boundary. Evidence: `services/core-control-plane/tests/scenarios/cross-objective/v2026.07-sre.json`, the five focused conflict tests in `test_v2026_07_replay.py`, including the agreeing-effects negative control and the automatic fail-closed HIL close, and the six frozen conflict guards in `test_frozen.py`.
- [ ] Retain one deployed-runtime arbitration receipt for the SRE cross-objective conflict on the production event bus, because the current evidence is a shadow replay over the in-memory bus.
- [ ] Emit signed objective effects from a shipped rule or planning artifact so the frozen conflict spec no longer has to supply the `objective_effects` enrichment the conflict relation reads.
- [ ] Complete the ARB / Change Safety, FinOps / Cost Governance, DR, and Chaos Engineering packs with all six executable constitutional dimensions.
- [x] Define the governed `BaselineTreatmentCohortReceipt` and its deterministic evaluator, and prove that a claim is eligible only for a governed external cohort with at least 30 non-synthetic samples per arm, one pinned revision, the identical frozen scenario set, complete metrics, intervals, provenance, and zero-threshold guards, and a current independent decision-evidence admission. Evidence: `packages/service-contracts/src/fdai_service_contracts/baseline_cohort.py`, `services/core-control-plane/src/fdai/core/measurement/baseline_cohort_claim.py`, `tools/cohort_receipt.py`, and the focused contract, claim, and runner tests.
- [ ] Retain one reference baseline and FDAI treatment on the identical frozen scenario set with sample sizes, confidence intervals, absolute values, and no unsupported multiplier claim.
- [ ] Bind live incident, change, cost, human-touchpoint, and independently verified outcome records into the KPI projection, then prove all zero-threshold guards remain zero.
- [x] Migrate every registered positive decision boundary, including rubric and chat-policy promotion, causal closure, effect-model activation, current-case T1 reuse, workflow gates, and workflow outcome acceptance, to the shared receipt and admission. Evidence: `config/decision-boundary-inventory.json` and the focused boundary tests it cites.
- [x] Add an automated coverage guard that fails when a registered positive decision boundary lacks the shared admission. Evidence: `scripts/quality/architecture/check-decision-boundary-coverage.py` and `tests/integration/scripts/test_decision_boundary_coverage.py`.
- [ ] Bind the independent verifier registry and admission providers in production composition for every boundary in `config/decision-boundary-inventory.json`, retain one governed live bundle per boundary, then record a passing `python3 scripts/quality/architecture/check-decision-boundary-coverage.py` result alongside a live claim that synthetic or incomplete evidence cannot satisfy.
- [x] Define the provider-neutral `OperationalCoverageReceipt` and prove its denominator,
  disposition, freshness, threshold, zero-tolerance, and digest invariants with focused tests.

#### Operational intelligence 99% closure blockers

Resolve these items in order because each later claim depends on the earlier governed inputs:

1. [ ] Load a department-reviewed Azure governance baseline with explicit scope and accountable
   ownership mapping, then retain a governed live drift receipt for that exact baseline and scope.
2. [ ] Bind an approved APM or service-dependency source and approved incident corpus, implement the
   reviewed deterministic application-versus-infrastructure classification, and retain live
   accuracy, abstention, and latency evidence.
3. [ ] Select a promoted ActionType covered by current human approval or valid standing
   authorization, prove its tested rollback target and independent effect verification drill, then
   retain a governed shadow receipt where live blast evidence produces `winning_axis=live_blast`,
   lowers authority, and causes no mutation.
4. [ ] Bind a deployment-owned document connector and ACL source to the implemented ACL-filtered
   hybrid retrieval path, then retain governed PostgreSQL corpus evidence for authorization,
   citation, deletion, accuracy, and latency.
5. [ ] Observe one pinned deployed revision for the reviewed 30-90 day window and retain the complete
   six-domain 99% KPI receipt with every zero-threshold guard at zero.
6. [ ] Resolve the Kubernetes private DNS path and complete interactive reauthentication for the
   approved customer Azure profile before any scoped read-only live validation.
7. [ ] Keep AWS and GCP implementation and live validation blocked until the Azure-only policy is
   revised and approved account, identity, and ActionType scope exists.
8. [ ] Keep cross-cloud ontology validation blocked until governed AWS and GCP producers exist and
   can supply authoritative evidence.

## Primary Objective

Minimize human intervention in cloud operations across three initial verticals under an
AIOps approach - Resilience, Change Safety, and Cost Governance - by resolving most events
deterministically (T0/T1) and reserving LLM inference (T2) for the residual ambiguous
minority, **without regressing the guard metrics**. Autonomy that improves a success metric
while degrading a guard metric is a failure, not a win.

SRE is the operating model across the three verticals. Disaster recovery and Chaos Engineering
are Resilience capabilities, Architecture Review Board governance applies across domains, and
FinOps is the Cost Governance discipline.

### Accuracy contract

FDAI does not claim that every novel diagnosis is correct. It targets **100% contract-conformant
behavior**: an agent either produces a schema-valid, evidence-supported, authorized result or
records an explicit unknown, no-op, denial, rollback, or human-review outcome. The platform target
is zero unsafe guesses, not forced answers.

The following violations have a release threshold of exactly zero:

- action against the wrong object identity or stale target revision;
- execution outside the registered ActionType, standing authority, or impact scope;
- success claimed from a broker/API receipt without independent effect verification;
- external state asserted from an ontology write rather than an authoritative observation;
- learning output that raises authority without review and promotion evidence.

### Coverage claim contract

FDAI reports operational coverage with one immutable `OperationalCoverageReceipt` per governed
universe. Supported domains are asset inventory, governance evaluation, operating scope, incident
diagnosis, remediation effects, and knowledge grounding.

Each receipt pins the scope, denominator, and evidence by digest. Every denominator item receives
one terminal coverage disposition: `covered`, `unknown`, `stale`, `unsupported`, `inaccessible`,
`conflicting`, or `invalid`. A governance result can be compliant or noncompliant and still be
`covered`; policy outcome is separate from whether FDAI evaluated the item with current evidence.

The receipt computes coverage in integer basis points. It can meet a target only when all
denominator items are accounted for, the evidence is fresh at evaluation time, the covered count
meets the configured threshold, and every configured zero-tolerance disposition has count zero.
The receipt is measurement evidence only and grants no approval, mutation, or execution authority.

### Autonomy before human review

An unresolved event does not immediately become a human task. Within its bounded deadline, FDAI
tries fresh evidence acquisition, an alternate authoritative source, deterministic reevaluation,
verified pattern reuse, a smaller safe plan, no-op, or pre-authorized recovery. Human review begins
only when ambiguity remains, policy mandates approval, or risk exceeds standing authority. Every
attempt shares the event correlation and contributes no additional human touchpoint.

## Definitions

Terms used across all metrics, fixed here to avoid ambiguity:

- **Event**: one normalized, deduplicated item entering the control loop (post `event-ingest`),
  identified by its stable idempotency key. All per-event rates are computed over this unit.
- **Scenario set**: a frozen, versioned collection spanning SRE, ARB / Change Safety, FinOps / Cost
  Governance, DR, and Chaos Engineering capability packs, used identically for baseline and
  treatment. Each release records the scenario-set and per-pack versions (e.g. `v2026.07`).

> **Current coverage gap:** `services/core-control-plane/tests/scenarios/manifests/v2026.07.json` assigns every fixture to SRE,
> ARB / Change Safety, FinOps, DR, or Chaos. A coverage dimension counts only when it cites a
> scenario owned by that pack and an existing executable test. The set remains `incomplete`: SRE
> is now `complete` with all six executable dimensions, while each of the other four packs still
> lacks one or more required cases.
> FDAI must not claim complete domain coverage until all five packs are complete.
- **Reference agent**: the fixed comparison system (documented, single-model, no tiering)
  measured in Phase 0. Its version is pinned per baseline run.
- **Human touchpoint**: any action requiring a human decision or input (HIL approval, manual
  edit, manual rollback). Each uniquely identified action or approval counts once, while repeated
  lifecycle rows for the same action or approval don't add another touchpoint. One event can
  contribute more than one touchpoint. Read-only viewing of the console is **not** a touchpoint.
- **Auto-resolved event**: an event that reaches a terminal, correct outcome with zero human
  touchpoints and no post-hoc rollback within the measurement window. An executor dispatch is
  pending, not resolved, until an explicit `measurement.action_outcome.v1` record closes the
  observation with enforce mode, passed verification, an auto decision, and no rollback.
- **Measurement window**: the fixed observation period per run (default: 30 days rolling, or
  one full scenario-set replay), stated with every reported figure.
- **Contract-conformant outcome**: one terminal result whose target, evidence, authority, action,
  effect verification, and audit records satisfy their exact versioned contracts. An explicit
  unknown or safe no-op is conformant; an unsupported success is not.

## Success Metrics

Each metric fixes a unit, formula, and reporting window. Targets are relative to the reference
agent on the same scenario-set version and are directional targets pending measurement.

| # | Metric | Precise definition | Unit | Direction | Target vs baseline |
|---|--------|--------------------|------|-----------|--------------------|
| 1 | Cost per unit | total attributable spend ÷ units processed, computed separately as `$/incident`, `$/change`, `$/optimization` | USD/unit | lower is better | large reduction (state factor only when measured) |
| 2 | Auto-resolution rate | auto-resolved events ÷ total events, in `[0, 1]` | ratio | higher is better | 5× the baseline ratio (capped at 1.0) |
| 3a | MTTR | mean(resolve_time − detect_time) over resolved incidents | seconds | lower is better | 5× shorter (0.2× baseline) |
| 3b | Change lead time | mean(merge_time − change_request_time) over changes | seconds | lower is better | 5× shorter (0.2× baseline) |
| 4 | Human intervention | human touchpoints ÷ (total events ÷ 100) | touchpoints / 100 events | lower is better | 0.2× baseline (i.e. 1/5) |

Notes:
- Metric 1 cost includes model inference, compute, storage, and event-bus spend attributable to
  processing; it excludes fixed platform overhead shared with non-FDAI workloads.
- MTTR and lead time are reported as **median and p90** alongside the mean, because latency
  distributions are skewed and a mean alone hides tail regressions.
- A `5×` target on a ratio (metric 2) is bounded: report both the multiplier and the absolute
  ratios, since a multiplier is meaningless once the baseline is already high.

## Guard Metrics (must not regress)

Guard metrics veto a promotion: any breach demotes the action from enforce back to shadow. Each
has an explicit threshold, not just a direction.

| Guard metric | Definition | Threshold |
|--------------|------------|-----------|
| Change failure rate (CFR) | changes causing incident/rollback ÷ total changes | ≤ baseline CFR (no increase) |
| False-positive rate | incorrect actions ÷ actions taken | ≤ baseline; alert if > baseline + 1pp |
| False-negative rate | missed true events ÷ true events | ≤ baseline; alert if > baseline + 1pp |
| Rollback rate | actions rolled back ÷ actions executed | ≤ baseline rollback rate |
| Policy-violation escapes | autonomous actions that violate policy and reach enforce | **exactly 0** (any escape blocks release) |
| Wrong-target or stale-revision execution | actions applied to a different object or revision than the approved plan | **exactly 0** |
| Unauthorized execution | actions outside registered type, identity, standing authority, or impact scope | **exactly 0** |
| Unverified success claims | actions reported successful without independent expected-effect closure | **exactly 0** |

Thresholds are evaluated on the same measurement window and scenario-set version as the success
metrics, so a gain and a guard breach are never compared across different data.

## Leading vs Lagging Indicators

Success metrics 1-4 are **lagging** (observable only after enough events resolve). Promotion
decisions also watch **leading** indicators that predict guard-metric health earlier:

- per-tier coverage share (T0 70-80%, T1 15-20%, T2 5-10%) drifting out of band,
- mixed-model disagreement rate (T2 quality gate) trending up,
- verifier abstain/fail rate rising,
- shadow-vs-enforce decision divergence for a candidate action.

Leading indicators trigger investigation before a lagging guard metric regresses.

## Measurement-First Rule

- No autonomy ships without telemetry to measure its effect (metrics 1-4 and all guard metrics).
- Phase 0 establishes the KPI dashboard and the reference baseline **before** any tier goes live
  ([phase-0-instrumentation.md](../phases/phase-0-instrumentation.md)).
- Multiplier claims (2-4) are only stated after the baseline and the treatment are both measured
  under the identical, frozen scenario-set version.
- **Statistical validity**: report each factor with a sample size (event count), a confidence
  interval, and the scenario-set version. Differences within the confidence interval are
  reported as "no measured change", not as an improvement. A zero-sample Wilson interval is
  `[0, 1]` (unknown), never evidence that accuracy is exactly zero.
- **Operational promotion evidence**: bind frozen benchmark and live-shadow samples to one full
  FDAI revision, ActionType digest, scenario case, and authoritative measurement unit. Latest
  corrections replace prior rows without changing cohort, scenario, observation time, or causal
  lineage. Separate frozen/live Wilson 95% lower bounds, distinct live days, zero escapes,
  executed-action rollback and complete recurrence windows, verified causal receipts, and Dynamic
  review must pass. A closed causal receipt counts only with confirmed closure. Raw metrics cannot
  promote; a verified receipt permits a separate review only.
- **Fairness**: baseline and treatment run the same scenarios, the same input distribution, and
  the same measurement window; the reference agent is not deliberately handicapped.

## Data Collection and Telemetry

Every metric maps to a concrete telemetry source so the dashboard is buildable, not aspirational:

- **Structured events + traces** (OpenTelemetry) carry `event_id`, `tier`, `decision`,
  `mode` (shadow/enforce), and timestamps - sourcing metrics 2, 3a/3b, and leading indicators.
- **Append-only audit log** sources human touchpoints (metric 4), rollbacks, and policy escapes.
- **Outcome finalization records** (`measurement.action_outcome.v1`) are the authority for
  auto-resolution. Dispatch-only events remain pending, verified non-rollback outcomes enter the
  finalized denominator, and rollback/adverse outcomes remain visible without becoming successes.
  When an action has corrected finalization rows, only its highest audit sequence is authoritative;
  an explicit verification failure remains a rejected observation rather than disappearing.
- **Explicit metric observations** use the latest row for each `event_id` and metric key. A retry
  or correction for one event replaces that event's earlier value instead of adding statistical
  weight; observations from different events remain independent samples.
- **MTTR (metric 3a)** is computed by the pure aggregator
  [`core/measurement/mttr.py`](../../../services/core-control-plane/src/fdai/core/measurement/mttr.py), which folds resolved
  incidents (`resolved_at - opened_at`) into **mean, median, and p90** seconds; unresolved and
  integrity-violating incidents are counted but excluded, never contributing a `0` or a
  negative duration. The delivery-layer wiring that feeds it live incidents (replacing the
  synthetic dev value in the `/kpi/autonomy` panel) is tracked as follow-up.
- **Cost/usage records** (model tokens, compute time, storage, bus throughput) source metric 1;
  attribution keys spend to the originating `event_id`. Repeated lifecycle rows for one action
  contribute the latest observed savings value once rather than weighting or summing retries.
- All metric inputs are English, secret-free, and customer-agnostic per the repo scope rules.

## Review Cadence

- **Per promotion**: no action moves shadow → enforce without a passing metrics + guard review.
- **Weekly**: dashboard review of leading indicators and guard-metric drift.
- **Per scenario-set version bump**: full baseline re-measurement so targets track a current,
  fair reference rather than a stale one.

## Where the Target Multipliers Would Come From

The mechanisms below are the **hypothesized** sources of the targeted gains; each is only
credited once measured against the baseline. Framing is intentionally "uses the LLM less", not
"a smarter LLM".

| Target | Hypothesized mechanism |
|--------|------------------------|
| Auto-resolution ↑ | T0/T1 deterministically close the ~85-90% majority of events; fewer escalations to T2/HIL. |
| MTTR / lead time ↓ | T0/T1 have no LLM round-trip (ms-s); auto-remediation PRs remove human wait time. |
| Human intervention ↓ | risk gate auto-approves low-risk actions; learned T1 actions avoid repeat human touch. |
| Cost per unit ↓ | only ~5-10% of events reach a frontier model; OSS/CSP-neutral stack; event-driven scale-to-zero. |

> Core insight: the gains are hypothesized to come from a structure that **uses the LLM less**,
> not from a smarter LLM - and this claim stands or falls on the Phase 0 measurement.

## Next steps

| To learn about | Read |
|----------------|------|
| How the baseline is instrumented | [phases/phase-0-instrumentation.md](../phases/phase-0-instrumentation.md) |
| Per-tier coverage targets and the trust router | [../../.github/instructions/architecture.instructions.md](../../../.github/instructions/architecture.instructions.md) |
| Safety invariants that guard-metrics enforce | [../../.github/instructions/coding-conventions.instructions.md](../../../.github/instructions/coding-conventions.instructions.md) |
| The KPI dashboard shipped with P0 | [../dashboards/phase-0-kpi.json](../../dashboards/phase-0-kpi.json) |
