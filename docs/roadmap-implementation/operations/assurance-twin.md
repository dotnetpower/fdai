# Assurance Twin (queryable, proactive, verifiable review) implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

The deterministic Twin core and its scalar and graph simulation primitives are implemented and
covered by focused tests. Production inventory, natural-language, review-delivery, and dedicated
operator-panel bindings remain incomplete, so no area is claimed as operationally validated.

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Projection, verified query, posture report, and publisher-neutral review core | implemented | [`core/assurance_twin/`](../../../services/core-control-plane/src/fdai/core/assurance_twin), [`tests/assurance_twin/`](../../../services/core-control-plane/tests/assurance_twin) | The in-memory projection, strict typed-query verifier, report fold, and review publisher glue pass focused checks. The default natural-language compiler returns `semantic_model_unavailable`; it does not infer meaning lexically. |
| Scalar Dynamic effect models, fidelity measurement, and bounded runtime coordination | implemented | [`effect_model.py`](../../../services/core-control-plane/src/fdai/core/assurance_twin/effect_model.py), [`fidelity.py`](../../../services/core-control-plane/src/fdai/core/assurance_twin/fidelity.py), [`runtime.py`](../../../services/core-control-plane/src/fdai/core/assurance_twin/runtime.py), and their focused tests | Active models stay immutable, challengers learn only from eligible outcomes, and divergence lowers the result to review. |
| Graph-wide Dynamic trajectories, propagation, invariants, episode closure, and model registry | implemented | [`graph_effect.py`](../../../services/core-control-plane/src/fdai/core/assurance_twin/graph_effect.py), [`graph_runtime.py`](../../../services/core-control-plane/src/fdai/core/assurance_twin/graph_runtime.py), [`graph_closure.py`](../../../services/core-control-plane/src/fdai/core/assurance_twin/graph_closure.py), and focused graph tests | The runtime persists prediction episodes before returning evidence and updates challenger slices only from complete independent observations. |
| Deep Security Assessment feed, deterministic analyzer, and catalog report | implemented | [`core/security/`](../../../services/core-control-plane/src/fdai/core/security), [`security_assessment.py`](../../../services/core-control-plane/src/fdai/core/reporting/datasources/security_assessment.py), [`test_assessment.py`](../../../services/core-control-plane/tests/core/security/test_assessment.py), and [`test_security_assessment_datasource.py`](../../../services/core-control-plane/tests/core/reporting/test_security_assessment_datasource.py) | This is a separate reporting subsystem, not the Twin-specific posture panel described below. |
| Production inventory projection and ambient change-review delivery | not-started | [`projection.py`](../../../services/core-control-plane/src/fdai/shared/providers/projection.py) and [`iac_review.py`](../../../services/core-control-plane/src/fdai/shared/providers/iac_review.py) define provider seams | No production inventory adapter, change-event coordinator, or Checks API publisher is bound upstream. |
| Strict semantic compilation and abstention feedback | implemented | [`query.py`](../../../services/core-control-plane/src/fdai/core/assurance_twin/query.py), [`semantic_query.py`](../../../services/core-control-plane/src/fdai/core/assurance_twin/semantic_query.py), [`runtime/assurance_twin_query.py`](../../../services/core-control-plane/src/fdai/runtime/assurance_twin_query.py), and focused checks (`50 passed`) | Accepted plans require exact input digest, compiler revision, bounded limits, evidence refs, and read-only verification. Abstentions can emit only content-free, no-authority discovery gaps. |
| T1 reuse, ChatOps intake, and governed runtime evidence | in-progress | [`chat.py`](../../../services/core-control-plane/src/fdai/core/assurance_twin/chat.py) and the shared semantic judgment contract | A concrete governed compiler, message routing, T1 reuse, discovery delivery, and authenticated receipt remain open. |
| Authenticated Operator API and Console read surfaces | implemented | `services/operator-service/src/fdai_operator_service/assurance_twin_posture_projection.py`; `services/operator-service/src/fdai_operator_service/runtime_projection_reader.py`; `console/src/routes/assurance-twin.tsx`; focused Core, Operator, and Console tests (`138 passed`, `25 passed`) | The read-only posture, review, evidence-gap, freshness, unavailable, and drill-down surfaces are integrated. This row does not claim an ambient publisher or governed runtime receipt. |
| Governed remediation proposal bridge | not-started | The report and review primitives above provide inputs, but no production action-bridging workflow is bound | Remediation must re-enter the normal risk-gated action path and cannot inherit authority from the Twin read surface. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-31 | implemented | Added provider-neutral strict compiler and discovery seams with explicit unavailable defaults, exact replay identity, evidence citations, result limits, and no mutation authority. | `current change`; 50 focused query and runtime composition checks passed. | Bind governed implementations and retain one authenticated runtime receipt. |
| 2026-08-14 | in-progress | Adopted the implementation ledger and separated tested Twin primitives from unbound delivery surfaces; earlier provenance wasn't reconstructed. | Current change; focused assurance-twin, security-assessment, and reporting tests cited in the scope table. | Bind production evidence and delivery surfaces, then collect governed runtime evidence. |
| 2026-08-21 | in-progress | Removed the lexical natural-language grammar from the default Twin compiler. Unbound compilation now returns `semantic_model_unavailable`, while the deterministic read-only verifier remains authoritative for every injected compiler. | `current change`; focused Assurance Twin checks passed 45 cases and the semantic-routing guard reports no migrate paths. | Bind a Twin-specific model projection and ChatOps intake before describing natural-language compilation as available. |
| 2026-09-12 | implemented | Reconciled the integrated authenticated Operator and Console Assurance Twin read surfaces while preserving the unbound ambient publisher and remediation bridge. | `current change`; integrated commits `970bab837` and `7d680e53d`; focused Core and Operator tests (`138 passed`); focused Console tests (`25 passed`). | Compose a trusted authoritative producer and transactional review publication, then retain one governed runtime receipt. |

### Remaining work

- [ ] Bind an authoritative `Inventory` source to the projection and prove freshness, bounded delta
  handling, and deterministic replay in a focused integration test.
- [x] Implement and test the provider-neutral strict compiler and inert discovery handoff.
- [ ] Bind the concrete model compiler, discovery delivery, and ChatOps intake and retain one
  authenticated runtime receipt.
- [ ] Wire ambient change events to a production `IacReviewPublisher` and record a governed shadow
  receipt that links the change, finding, rule evidence, and published review.
- [ ] Route abstained questions and remediation proposals through the discovery and normal risk-gated
  action paths, with tests proving the Twin never executes or raises authority.
- [x] Add authenticated read-only Twin posture and review APIs plus the Console report, review,
  evidence-gap, freshness, unavailable, and drill-down surfaces (`138 passed`, `25 passed`).
- [ ] Capture a governed runtime receipt for one complete trusted-producer-to-report rendering.
