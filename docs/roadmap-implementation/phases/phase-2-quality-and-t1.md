# Phase 2 - Continuous Rule Update, Quality Gate, and T1 implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Migrated implementation notes

> **Implementation status**: The continuous-rule-pipeline core, T2 quality gate, T1 tier,
> promotion registry, risk gate, and their deterministic tests are implemented. Composition from
> a production source watcher through GitHub PR delivery, measured T1 and auto-resolution exit
> evidence against the P0 baseline, the Assurance Twin model-backed natural-language compiler,
> and discovery-loop binding are incomplete. A T1 reuse with current case, topology, owner,
> policy, dry-run, idempotency, and rollback evidence now becomes a typed Action and passes
> execution authorization plus the unified risk gate; legacy reuse without that receipt remains
> an inert shadow log. A quality-gate-eligible T2 candidate follows the same authorization-before-
> risk order, so a prohibited or unresolved execution profile never reaches risk evaluation.
> Missing risk authority or a missing cited rule produces an explicit audited HIL hold rather
> than a generic shadow outcome.
> Ready operational-promotion receipts have an immutable exact-key StateStore adapter that writes
> state and audit atomically. Measurement still never promotes: an approved Thor-owned governance
> action must consume the exact stored receipt in the promotion path.
> The percentages and Exit Criteria below are targets,
> not claims of current attainment.

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Continuous rule-update core and watcher scheduling | in-progress | `services/core-control-plane/src/fdai/rule_catalog/pipeline/`; `uv run pytest -q --no-cov services/core-control-plane/tests/rule_catalog/pipeline/test_collect.py services/core-control-plane/tests/rule_catalog/pipeline/test_watcher.py services/core-control-plane/tests/rule_catalog/pipeline/test_shadow_eval.py services/core-control-plane/tests/rule_catalog/pipeline/test_regression_gate.py services/core-control-plane/tests/rule_catalog/pipeline/test_orchestrator.py` passed 118 cases | Collection, watch, shadow evaluation, regression, and orchestration pass locally. Catalog-as-code PR delivery and live watcher receipts remain open. |
| T2 quality gate core and runtime binding | in-progress | `services/core-control-plane/src/fdai/core/quality_gate/`; `services/core-control-plane/src/fdai/core/tiers/t2_reasoning/`; `uv run pytest -q --no-cov services/core-control-plane/tests/core/quality_gate/test_gate.py services/core-control-plane/tests/quality_gate/test_mixed_model_cross_check.py services/core-control-plane/tests/quality_gate/test_rule_based_verifier.py services/core-control-plane/tests/quality_gate/test_rag_grounding.py services/core-control-plane/tests/quality_gate/test_rag_grounding_shipped_catalog.py services/core-control-plane/tests/core/tiers/t2_reasoning/test_tier.py` passed 99 cases | Mixed-model comparison, rule verification, grounding, and authorization-before-risk pass. The documented what-if/dry-run and security evidence path remains incomplete. |
| Hallucination rubric and self-consistency controls | implemented | `services/core-control-plane/src/fdai/core/quality_gate/rubric.py`; `self_consistency.py`; `promotion.py`; `uv run pytest -q --no-cov services/core-control-plane/tests/core/quality_gate/test_rubric.py services/core-control-plane/tests/core/quality_gate/test_rubric_gate.py services/core-control-plane/tests/core/quality_gate/test_self_consistency.py services/core-control-plane/tests/core/quality_gate/test_rubric_promotion.py` passed 37 cases | The controls are subtractive and shadow-first. No live enforcement promotion is claimed. |
| T1 lightweight tier and contextual reuse | implemented | `services/core-control-plane/src/fdai/core/tiers/t1_lightweight/`; `uv run pytest -q --no-cov services/core-control-plane/tests/core/tiers/t1_lightweight/test_tier.py services/core-control-plane/tests/core/tiers/t1_lightweight/test_tier_hardening.py services/core-control-plane/tests/core/tiers/t1_lightweight/test_contextual_reuse.py services/core-control-plane/tests/delivery/azure/test_operational_evidence.py services/core-control-plane/tests/core/test_control_loop_t1_wire.py` passed 113 cases | Current case, topology, owner, policy, dry-run, idempotency, rollback, and risk evidence are bound locally. Measured absorption and baseline improvement remain open. |
| Per-action promotion and unified risk gate | in-progress | `services/core-control-plane/src/fdai/core/risk_gate/`; `services/core-control-plane/src/fdai/delivery/promotion.py`; promotion StateStore adapters; `uv run pytest -q --no-cov tests/integration/test_action_promotion_e2e.py services/core-control-plane/tests/core/risk_gate/test_gate.py services/core-control-plane/tests/persistence/test_state_store_action_promotion.py services/core-control-plane/tests/delivery/test_promotion_executor.py services/core-control-plane/tests/core/measurement/test_operational_promotion.py` passed 101 cases | Exact receipt persistence and governance-action consumption pass locally. No protected live promotion or independent effect receipt is claimed. |
| Assurance Twin read-only query slice | in-progress | `services/core-control-plane/src/fdai/core/assurance_twin/query.py`; `uv run pytest -q --no-cov services/core-control-plane/tests/assurance_twin/test_query.py` passed 45 cases | Typed read-only query behavior passes. The model-backed semantic compiler, discovery-loop composition, and governed runtime receipt remain open. |
| Global provider-schema accounting | implemented | `provider-schema-catalog/index.json`; provider-schema watcher, relationship review, review projection, and durable ledger under `services/core-control-plane/src/fdai/delivery/`; `uv run pytest -q --no-cov services/core-control-plane/tests/delivery/test_provider_schema_catalog.py services/core-control-plane/tests/delivery/test_provider_schema_review.py services/core-control-plane/tests/delivery/test_provider_schema_state_ledger.py services/core-control-plane/tests/delivery/test_provider_schema_watcher.py services/core-control-plane/tests/delivery/test_provider_schema_watcher_cli.py` passed 82 cases; `uv run pytest -q --no-cov services/core-control-plane/tests/agents/test_provider_schema_drift.py` passed 4 cases | The bounded content-addressed review records eight reviewed-mapping overlaps and publishes no-authority drift on `object.drift` with `event_type: provider.schema_drift`. Semantic mapping and protected scheduled-run receipts remain separate. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-29 | in-progress | Replaced the placeholder scope row with bounded Phase 2 areas and reran rule-pipeline, T2 quality, rubric, T1, promotion, Assurance Twin, and provider-schema slices. Corrected the current provider-schema account to eight reviewed overlaps and distinguished the `object.drift` topic from `event_type: provider.schema_drift`; Terraform job presence remains deployment definition rather than run evidence. | `current change`; exact commands and outcomes are recorded in the corresponding scope rows: 118, 99, 37, 113, 101, 45, and 82 cases passed, plus 4 provider-schema drift agent cases. | Resolve the integration and evidence issues below before claiming Phase 2 exit metrics or operational validation. |
| 2026-08-24 | in-progress | Migrated the legacy status into the delegated ledger without reconstructing earlier provenance. | current change; preserved owner status from `docs/roadmap/phases/phase-2-quality-and-t1.md`. | Replace the legacy summary with bounded evidence-backed scope rows and observable exits. |
| 2026-08-24 | implemented | Classified 4,707 exact OpenAPI ARM ID references into 908 endpoint pairs, including modeled coverage and seven existing reviewed-mapping overlaps, without inferring LinkType or orientation. | `current change`; relationship review `sha256:f8e8029888b45137902ee4900b644704b60a673fc4c623cfdb968cdcfa70c802`; focused review and shipped-artifact replay checks. | Independently review selected pair semantics and retain protected scheduled-run evidence before any promotion or operational-validation claim. |
| 2026-08-24 | implemented | Added resource bounds to relationship review and durable generations, staged hydration before publication, revision-CAS manifest replacement with atomic audit, and a provider-schema Heimdall-to-Forseti-to-Saga regression. | `current change`; focused review, durable-ledger, and agent-chain checks. | Retain protected exact-revision scheduled-run, durable-generation, Heimdall, and Saga evidence. |

### Remaining work

- [x] Replace the migrated placeholder scope row with bounded rows and rerun all seven focused local validation slices.
- [ ] Complete or explicitly defer collector-to-catalog PR delivery under [issue #340](https://github.com/dotnetpower/fdai/issues/340).
- [ ] Complete the deterministic T2 what-if/dry-run and security verifier path under [issue #345](https://github.com/dotnetpower/fdai/issues/345).
- [ ] Retain measured T1 absorption, auto-resolution, guard, promotion-review, and independent-effect evidence under [issue #343](https://github.com/dotnetpower/fdai/issues/343) and the P0 baseline [issue #76](https://github.com/dotnetpower/fdai/issues/76).
- [ ] Bind the Assurance Twin semantic compiler and discovery loop under [issue #344](https://github.com/dotnetpower/fdai/issues/344).
- [ ] Independently review selected endpoint-pair semantics under [issue #89](https://github.com/dotnetpower/fdai/issues/89) before changing ontology or Rule mappings.
- [ ] Retain protected rule-watcher and provider-schema scheduled-run receipts under [issue #346](https://github.com/dotnetpower/fdai/issues/346).
