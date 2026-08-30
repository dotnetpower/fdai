# Causal Incident Graph implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Migrated implementation notes

> **Implementation status (2026-08-01):** The typed hypothesis lifecycle, weakest-link scoring,
> bounded time-consistent graph materializer, support/refutation and closure links, immutable
> ontology projector, lagged temporal analyzer, runtime coordinator, shadow control-loop caller,
> independent closure classifier, and regression tests are implemented. The control loop analyzes
> and audits in shadow but does not write the ontology as Forseti. Deployments bind bounded temporal
> series, a Forseti-owned projection publisher, independent outcome provider, and causal receipt
> resolver. Pre-routing temporal analysis has a bounded timeout, and only a scope- and time-matched
> verified intervention receipt can confirm closure. No causal result grants execution.

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Hypothesis lifecycle and ontology projection | implemented | `services/core-control-plane/src/fdai/core/rca/hypothesis.py`; `projection.py`; `tests/core/rca/test_hypothesis.py`; `test_hypothesis_lineage_projection.py` | Immutable revisions, closure states, and evidence-only graph projection are covered by focused tests. |
| Time-consistent incident graph | implemented | `services/core-control-plane/src/fdai/core/rca/incident_graph.py`; `tests/core/rca/test_incident_graph.py` | Traversal is bounded by depth, count, time, and size and reports truncation. |
| Candidate generation and causal scoring | implemented | `services/core-control-plane/src/fdai/core/rca/t0.py`; `t1.py`; `evidence.py`; `tests/core/rca/test_coordinator.py`; `test_evidence.py` | Deterministic candidates, weakest-link scoring, support, and refutation paths are implemented. |
| Adaptive observation selection | implemented | `services/core-control-plane/src/fdai/core/rca/discrimination_contract.py`; `discrimination.py`; `tests/core/rca/test_discrimination.py` | Exact-frame candidates are content-addressed and ranked by pair separation. Snapshot mismatch, incomplete coverage, and no discrimination produce explicit held evidence without query or execution authority. |
| Adaptive investigation session | implemented | `core/read_investigation/adaptive*.py`; `core/rca/discrimination*.py`; `core/operational_learning/investigation_strategy*.py`; `core/operational_planning/investigation_handoff.py`; `runtime/adaptive_investigation_runtime.py`; Operator Process projection; Console Investigation Room; focused tests | The bounded session, exact verified-query handoff, active/challenger shadow comparison, Norns-owned inert learning candidate, separate planning handoff, durable Process journal, and read-only UI are implemented. Deployment-owned candidate sources, Forseti reviser binding, governed live cohorts, and selector promotion evidence remain operational work. |
| Shadow runtime and independent closure | implemented | `services/core-control-plane/src/fdai/core/rca/runtime.py`; `tests/core/rca/test_runtime.py`; `test_temporal_causality.py` | The upstream path remains shadow and evidence-only; no result grants execution authority. |
| Grade demotion and shadow retention | implemented | `services/core-control-plane/src/fdai/core/rca/hypothesis.py` (`close_causal_hypothesis`, `causal_action_mode`); `runtime.py` (`CausalRuntimeResult.action_mode`); `tests/core/rca/test_hypothesis.py`; `test_runtime.py` | Unsafe and refuting closure lowers the grade to `association`, no closure except verified `confirmed` may raise a grade, and every unresolved or contested revision resolves to `shadow`. The runtime exposes the derived mode; no promotion or execution consumer binds it yet, because the causal path is still shadow-only. |
| Deployment binding and operational evidence | in-progress | [Delivery slices](../../roadmap/rules-and-detection/causal-incident-graph.md#delivery-slices); current change source audit | Provider and publisher seams exist, but each deployment must bind them and retain governed closure receipts before validation can be claimed. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-14 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance. | `current change`; current source and focused tests listed in the scope table. | Bind the production evidence path and retain governed interventional closure evidence. |
| 2026-08-16 | implemented | Made unsafe closure demote the evidence grade, blocked any non-confirmed closure from raising a grade, and added the deterministic `causal_action_mode` derivation that keeps refuted, unsafe, inconclusive, contested, and weakly graded revisions in `shadow`. | `current change`; `services/core-control-plane/src/fdai/core/rca/hypothesis.py`; `services/core-control-plane/tests/core/rca/test_hypothesis.py`; focused run `pytest services/core-control-plane/tests/core/rca` passed 215 tests. | Bind the deployment evidence path and retain one governed interventional replay. |
| 2026-08-16 | implemented | Exposed the derived mode as `CausalRuntimeResult.action_mode` so the shadow decision is observable on the runtime path, and qualified the scope row: no promotion or execution consumer binds the mode yet. | `current change`; `services/core-control-plane/src/fdai/core/rca/runtime.py`; `services/core-control-plane/tests/core/rca/test_runtime.py`; focused run `pytest services/core-control-plane/tests/core/rca` passed 216 tests. | Bind the deployment evidence path and retain one governed interventional replay. |
| 2026-08-30 | implemented | Added replay-stable adaptive observation selection over exact-frame, pre-verified read-only candidates. Selection maximizes hypothesis-pair separation, records stale or incomplete candidates, and returns authority-free selected or held receipts. | `current change`; `services/core-control-plane/src/fdai/core/rca/discrimination_contract.py`; `discrimination.py`; focused discriminator tests, Ruff, and strict mypy. | Bind candidate production to the verified ontology query path and retain governed investigation evidence before claiming operational validation. |
| 2026-08-30 | implemented | Connected adaptive selection into a bounded Process-backed investigation session. The runtime re-verifies exact query lineage before I/O, blocks late or incomplete results, records active/challenger shadow evidence, routes balanced Muninn cohorts through Norns and Mimir's existing inert review queue, emits only an authority-free proposal to a separate planning Process, and exposes a read-only Investigation Room. | `current change`; adaptive RCA, read-investigation, operational-learning, planning, runtime, Operator, Console, and agent tests; focused validation. | Bind deployment-owned round and Forseti revision sources, retain a governed live cohort, and promote a selector only through a reviewed immutable configuration release. |
| 2026-08-30 | implemented | Closed 22 tracked critique and hardening rounds and one final independent release review with only Low or no findings remaining. | `current change`; 646 Core tests, 46 Operator tests, 19 Console tests, three Playwright viewport scenarios, Ruff, strict mypy, cold import, documentation gates, and final task-only review. | Retain governed live evidence before selector promotion; no deployed validation is claimed. |

### Remaining work

- [ ] Bind bounded temporal series, the Forseti-owned projection publisher, independent outcomes, and causal receipt resolution in a deployment integration test.
- [ ] Retain one governed replay that proves a verified intervention closes or refutes a hypothesis without granting action authority.
- [x] Unsafe or refuting evidence lowers the hypothesis grade and keeps the related action or experiment in `shadow`, evidenced by `close_causal_hypothesis` and `causal_action_mode` in `services/core-control-plane/src/fdai/core/rca/hypothesis.py` and the focused cases in `services/core-control-plane/tests/core/rca/test_hypothesis.py`.
