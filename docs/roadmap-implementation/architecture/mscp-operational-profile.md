# MSCP Operational Profile implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Profile identity and deterministic policy primitives | implemented | `core/mscp_profile/profile.py`; `cycle_guard.py`; `runtime_integrity.py`; focused tests under `tests/core/mscp_profile/` | Source provenance, non-conformance, bounded cycle checks, and runtime-manifest comparison are implemented as pure policy. |
| Optional effect observation and `ResponseOutcome` projection | implemented | `core/mscp_profile/effect_verification.py`; `response_outcome.py`; `test_control_loop_shadow.py`; `test_response_outcome.py` | Pair-only composition preserves executor outcomes and writes shadow evidence without adding authority. |
| Never-raising authority ceiling | implemented | `core/mscp_profile/authority_ceiling.py`; `test_authority_ceiling.py` | Exhaustive finite-domain tests prove that the profile can only preserve or lower the existing FDAI decision. The ceiling is not connected to the enforce path. |
| Rule-governance coexistence | implemented | `runtime/control_loop.py`; `core/control_loop/_process.py`; focused governance safety-path tests | Assignment observation and exemption holds occur before dispatch. They do not activate MSCP effect observation, synthesize a `ResponseOutcome`, or alter the profile lifecycle. |
| Immutable decision-context projection and replay | implemented | `core/mscp_profile/decision_context.py`; `decision_context_store.py`; `tests/core/mscp_profile/test_decision_context.py` (`20 passed`); owning MSCP tests (`140 passed`) | Four owner-injected read-only observations join only for one candidate, decision, subject, and cutoff. Missing, conflicting, incomplete, stale, future, unverified, and unavailable sources hold. A content digest and first-write atomic audit fence survive restart without creating a new authority; actual runtime owner bindings remain open. |
| Governed profile gating | not-started | [Activation and runtime behavior](../../roadmap/architecture/mscp-operational-profile.md#activation-and-runtime-behavior); `core/mscp_profile/readiness.py`; `profile_lifecycle.py` | Readiness and default-shadow lifecycle primitives exist, but no measured window or ControlLoop gating binding exists. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-14 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance and separated implemented shadow observation from unimplemented gating. | `current change`; profile source and focused tests listed in the scope table. | Retain a measured readiness window and implement the bounded decision-context and gating work below. |
| 2026-08-23 | implemented | Recorded the ordering boundary between immutable rule governance and optional post-dispatch MSCP effect observation. | `current change`; focused governance and MSCP composition checks. | The existing measured-readiness and governed-gating work remains unchanged. |
| 2026-09-27 | implemented | Added a bounded, content-addressed four-owner decision context and audit-atomic first-write/restart replay, with explicit holds for missing, conflicting, stale, unverified, and unavailable evidence. Corrected the prior combined status row: default-shadow lifecycle primitives already exist, but the profile is not activated. | `current change`; `core/mscp_profile/{decision_context,decision_context_store}.py`; `tests/core/mscp_profile/test_decision_context.py` (`20 passed`); `uv run pytest -q --no-cov services/core-control-plane/tests/core/mscp_profile` (`140 passed`); focused Ruff and mypy. | Bind real authoritative readers in the runtime, retain a measured shadow window, and separately govern any gating integration. |

### Remaining work

- [x] Project owner-supplied ontology, incident, workflow, and audit observations into one immutable, audit-atomic decision context; focused tests prove missing and conflicting inputs hold and a retry cannot rewrite the durable record (`20 passed`).
- [ ] Bind the four actual authoritative owner readers in a governed runtime and retain a pinned decision receipt before claiming operational context availability.
- [ ] Retain a pinned shadow evidence window that measures profile matches, mismatches, holds, audit failures, and unchanged executor outcomes.
- [ ] Add a governed profile lifecycle and connect the never-raising ceiling only after focused tests prove rollback, replay, and unchanged risk, approval, execution, and audit ownership.
