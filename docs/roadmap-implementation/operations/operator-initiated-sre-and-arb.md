# Operator-Initiated SRE and Architecture Review implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Incident trace identity and correlation opt-out | implemented | `fdai/shared/contracts/models/event.py`; `fdai/core/event_ingest/correlator.py`; routine producers in `fdai/core/scheduler/service.py` and `fdai/delivery/inventory_delta.py`; `tests/core/event_ingest/test_correlator.py` | `correlation_id` remains available when `incident_correlation=none` suppresses Incident creation. |
| Operator-facing Incident number | implemented | `fdai/core/incident/registry.py`; `fdai/shared/providers/state_store.py`; in-memory and PostgreSQL StateStore adapters; Operator Incident projection; Console Incident route; focused Core, PostgreSQL, Operator, and Console checks | New Incidents receive one durable monthly `INC-YYYYMM-NNNN` number from the current UTC allocation month while UUID5 remains the canonical identity. Legacy Incidents can have no number. |
| Operator-confirmed Incident lifecycle and investigation primitives | implemented | `fdai/core/incident/workflow.py`; `fdai/core/investigation/coordinator.py`; `tests/core/incident/test_incident_workflow.py`; `tests/core/investigation/test_coordinator.py` | The bounded primitives exist and pass focused checks. |
| Integrated operator SRE command and progress contract | implemented | `fdai/core/incident/sre_request.py`; `fdai/shared/providers/operator_request.py`; Operator `action_confirmation_runtime.py` and production composition; focused Core and Operator checks | The process-local coordinator proves Incident and progress behavior. Independent Console and ChatOps surfaces durably accept an exact semantic action draft, and production Operator composition drains it to the Core event topic without direct service calls or executor identity. |
| ARB readiness, production gate, and declarative review projection | implemented | `fdai/core/architecture_review/readiness.py`; `fdai/core/architecture_review/projection.py`; `fdai/runtime/control_loop.py`; `rule-catalog/workflows/architecture-review.yaml`; `tests/core/architecture_review/` | The operator surfaces are `/workflow-apps/architecture-review` and `/processes/{process_id}`; there is no `/arb/status` endpoint. |
| Operator workflow submission | implemented | `fdai_operator_service/families/workflow/routes.py`; `services/operator-service/tests/test_operator_workflow_family.py` | `POST /workflows/run` accepts idempotent, revision-bound shadow proposals and rejects `mode=enforce`. |
| Authority-bearing Workflow enforce and local/deployed operational parity | in-progress | `fdai/core/workflow/workflow_step_executor.py` contains governed enforce action dispatch, while the Operator API remains proposal-only and shadow-first. | No governed runtime receipt proves the documented Owner-gated end-to-end enforce path or local/deployed parity. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-13 | in-progress | Adopted the implementation ledger, corrected the ARB surface and Operator workflow authority boundary, and did not reconstruct earlier provenance. | Current change; focused Incident, investigation, ARB, event-correlation, and Operator workflow tests listed in the scope table. | Complete the integrated SRE command/progress path and record governed evidence for authority-bearing Workflow enforce and parity. |
| 2026-08-16 | in-progress | Added the operator SRE request coordinator, the proposal dispatcher seam, and Incident-ID metadata at operator-request normalization, with an end-to-end test that drives one confirmed request through the control loop to a parked HIL approval. | Current change; `176 passed` from `uv run pytest -q --no-cov services/core-control-plane/tests/core/incident/ services/core-control-plane/tests/core/event_ingest/ services/core-control-plane/tests/core/test_control_loop_operator_request.py`. | Bind the dispatcher at the runtime composition root and record governed evidence for authority-bearing Workflow enforce and parity. |
| 2026-08-16 | in-progress | Hardened the progress contract: link templates are validated before any Incident write, every interpolated reference is percent-encoded, a blank resource type is rejected instead of silently dropped, and the published proposal is immutable. | Current change; `182 passed` from `uv run pytest -q --no-cov services/core-control-plane/tests/core/incident/ services/core-control-plane/tests/core/event_ingest/ services/core-control-plane/tests/core/test_control_loop_operator_request.py`. | Unchanged from the row above. |
| 2026-08-24 | implemented | Added an additive operator-facing Incident number without replacing canonical UUID5 identity. StateStore serializes monthly allocation and `incident.open` audit persistence, replay preserves the assigned number, and Operator, Console, and notifications present it while canonical links remain unchanged. | `current change`; focused Core lifecycle and notification checks passed 53 cases, loopback PostgreSQL concurrency passed 1 case, Operator projection passed 8 cases, and Console projection/presentation passed 36 cases. | No implementation work remains for the bounded numbering contract. Legacy Incidents remain explicitly unnumbered. |
| 2026-08-24 | implemented | Corrected the number prefix to use the current UTC allocation month instead of caller-supplied `opened_at`; the event time remains unchanged and an injected clock keeps the behavior deterministic in tests. | `current change`; the focused lifecycle case and loopback PostgreSQL concurrency case each passed, and Ruff passed for the changed Python slice. | Existing append-only Incident records retain their originally assigned numbers. |
| 2026-08-29 | implemented | Corrected the stale in-process dispatcher assumption for the independent Operator topology and bound the existing durable `ActionConfirmationBridge` in production composition. Readiness includes the worker and lifecycle shutdown stops it before Kafka. | `current change`; Operator production composition and focused action-confirmation, completion-composition, and full-composition checks (`17 passed`); Ruff and strict mypy checks. | Retain governed local and deployed Workflow enforce evidence without changing the proposal-only Operator API. |

### Remaining work

- [x] Add an end-to-end focused test proving that one confirmed operator problem-response request
  opens or reuses one Incident, publishes one idempotent typed ActionProposal, preserves one
  correlation across stages, and returns authoritative Incident, Trace, Process, and Approval links
  (`tests/core/incident/test_sre_request.py`).
- [x] Assign each new Incident one durable monthly operator-facing number while preserving UUID5
  as the canonical lifecycle, replay, audit, and deep-link identity.
- [x] Bind the durable `ActionConfirmationBridge` at the independent Operator production composition
  root so Console and ChatOps proposals reach Core through the event bus rather than an in-process
  `OperatorProposalDispatcher` (`17 passed` focused checks).
- [ ] Record a governed local and deployed runtime receipt proving that an approved,
  allowlisted Workflow can enter enforce through the authority-bearing control path while its
  ActionType remains independently gated; keep `POST /workflows/run` proposal-only.
