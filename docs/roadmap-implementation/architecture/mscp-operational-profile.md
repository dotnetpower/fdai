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
| Decision-context projection and governed gating | not-started | [Adopted mechanisms](../../roadmap/architecture/mscp-operational-profile.md#adopted-mechanisms); [Activation and runtime behavior](../../roadmap/architecture/mscp-operational-profile.md#activation-and-runtime-behavior) | The current runtime has no profile lifecycle, measured readiness window, or authority-gating integration. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-14 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance and separated implemented shadow observation from unimplemented gating. | `current change`; profile source and focused tests listed in the scope table. | Retain a measured readiness window and implement the bounded decision-context and gating work below. |
| 2026-08-23 | implemented | Recorded the ordering boundary between immutable rule governance and optional post-dispatch MSCP effect observation. | `current change`; focused governance and MSCP composition checks. | The existing measured-readiness and governed-gating work remains unchanged. |

### Remaining work

- [ ] Project authoritative ontology, incident, workflow, and audit state into one immutable decision context, then prove missing or conflicting inputs produce a hold.
- [ ] Retain a pinned shadow evidence window that measures profile matches, mismatches, holds, audit failures, and unchanged executor outcomes.
- [ ] Add a governed profile lifecycle and connect the never-raising ceiling only after focused tests prove rollback, replay, and unchanged risk, approval, execution, and audit ownership.
