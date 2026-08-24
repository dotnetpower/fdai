# Security and Identity implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Workload identities and approval/execution separation | validated | `config/independent-service-live-evidence-manifest.json`; `infra/services/`; `shared/providers/workload_identity.py`; SD-08 and IS-09 evidence | Five-service deployment evidence proves distinct identities and makes the isolated Executor the sole eligible effect holder after cutover. |
| Executor safeguards and independent effect closure | in-progress | `core/executor/`; `core/risk_gate/`; `tests/core/executor/`; `config/constitution-traceability.json` requirement `FDAI-CONST-007` | Lock, idempotency, dry-run, pre-effect and terminal audit, rollback, and risk checks are executable. One shared contract does not yet prove equivalent guarantees across every execution path. |
| Global kill switch and break-glass controls | implemented | `core/rbac/kill_switch_command.py`; `core/control_loop/_execution.py`; `core/conversation/_write_break_glass_tool.py`; focused RBAC and control-loop tests | Revision-safe state, fail-closed refresh, authority ceiling, time-bound activation, audit, and paging paths exist. A retained operational drill remains open. |
| Data protection and privacy evidence | in-progress | [Data Governance implementation status](data-governance.md#implementation-status); redaction and retention paths cited there | Major boundaries implement minimization and redaction, but a shared pre-model receipt and deployment privacy approval are incomplete. |
| Standing human authorization (A3-E) | not-started | `config/constitution-traceability.json` requirement `FDAI-CONST-008`; [Escalation and Standing Authority](../../roadmap/decisioning/escalation-and-standing-authority.md) | The shadow non-response supervisor exists, but no standing-authorization catalog, evaluator, or promotion path grants executable A3-E authority. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-14 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance and aligned security claims with the service cutover, safeguard implementation, kill switch, privacy, and A3-E evidence boundaries. | `current change`; deployment manifests, source, focused tests, and constitutional register cited above. | Close the shared safeguard contract, operational drills, privacy gate, and standing-authorization implementation. |

### Remaining work

- [ ] Define one shared execution receipt contract and prove all PR-native, direct-API, tool-call, workflow, and isolated-Executor paths enforce the seven safeguards plus independent effect closure.
- [ ] Retain governed kill-switch, break-glass, rollback, identity-recertification, and audit-anchor drill receipts on one pinned deployment revision.
- [ ] Complete the data-governance production gate and shared pre-model minimization receipt before claiming privacy validation.
- [ ] Implement and shadow-evaluate A3-E standing authorization with quorum, expiry, revocation, handover, scope, evidence, and no-silence authority tests before any promotion.
