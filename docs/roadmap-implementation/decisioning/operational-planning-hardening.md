# Operational Planning Hardening Evidence implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Planning, simulation, durability, and handoff mechanics | implemented | [Implementation evidence](../../roadmap/decisioning/operational-planning-hardening.md#implementation-evidence), [Review rounds](../../roadmap/decisioning/operational-planning-hardening.md#review-rounds) | Twelve adversarial rounds retain focused implementation and regression evidence without granting execution authority. |
| Frozen scenario coverage | in-progress | [Residual risk](../../roadmap/decisioning/operational-planning-hardening.md#residual-risk) | The manifest remains `partial` because partial-execution recovery still uses an explicit release-evidence proxy. |
| Fail-closed live shadow observation | validated | [Live shadow proof](../../roadmap/decisioning/operational-planning-hardening.md#live-shadow-proof) | The retained 2026-08-03 observation reproduced an ineligible result with zero mutation; it does not validate enforcement. |
| Enforcement readiness | in-progress | [Residual risk](../../roadmap/decisioning/operational-planning-hardening.md#residual-risk) | The pre-dispatch kinetic writer, the verified independent observer, and the production graph and executor bindings exist. Protected-runner recovery, the non-synthetic planning receipt, and live-shadow samples remain open. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-29 | in-progress | Made this ledger authoritative by migrating the owner's inline status, and corrected enforcement readiness from `not-started`. The pre-dispatch kinetic writer (bound 2026-08-14), the Heimdall-owned verified scale-out observer, and the production graph and executor bindings recorded by the Operational Planning ledger already exist. | `current change`; `runtime/control_loop.py`; `runtime/observation_evidence.py`; `uv run pytest -q --no-cov` over the kinetic-safety and observation suites passed 31 cases. | Protected-runner recovery drill, a non-synthetic planning receipt, and 100 live-shadow samples. |
| 2026-08-14 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance and separated validated shadow evidence from enforcement readiness. | `current change`; review rounds, live shadow proof, and residual-risk evidence in this document. | Complete the three release-evidence exits below. |
| 2026-08-14 | in-progress | Corrected the Lane F contract to expose the missing pre-dispatch exact-plan writer and verified independent effect-observation adapter instead of treating them as implied by the executor and graph bindings. | `current change`; `config/ohl-scale-out-evidence.json`, the runbook gate, and focused manifest checks. | Bind both exact sources before starting the protected live mutation phase. |

### Remaining work

- [x] Bind the kinetic receipt writer before provider dispatch and a Heimdall-owned verified
    independent effect-observation adapter; prove neither source is reconstructed or substituted.
    Both bind when governed execution is selected; `test_kinetic_safety.py` rejects a missing,
    late, or substituted proposal, and the observation tests reject substituted or forged sources.
- [ ] Complete the protected-runner partial-execution recovery drill and retain authenticated
    compensation, independent closure, rollback, and cleanup receipts.
- [ ] Retain a complete, non-synthetic planning receipt from production graph Dynamic evidence
    bound to one exact ontology release. The production binding is recorded in the
    [Operational Planning ledger](operational-planning.md).
- [ ] Retain 100 live-shadow `ops.scale-out` samples across 14 days with zero policy escapes and a
    verified rollback sequence before promotion review. The production executor binding is recorded
    in the [Operational Planning ledger](operational-planning.md).
