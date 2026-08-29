# Security and Identity implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Workload identities and approval/execution separation | validated | `config/independent-service-live-evidence-manifest.json`; `infra/services/`; `shared/providers/workload_identity.py`; SD-08 and IS-09 evidence | Five-service deployment evidence proves distinct identities and makes the isolated Executor the sole eligible effect holder after cutover. |
| Executor safeguards and independent effect closure | in-progress | `core/executor/`; `core/executor/safeguards.py`; `core/risk_gate/`; `tests/core/executor/`; `config/constitution-traceability.json` requirement `FDAI-CONST-007`; issue `#81` | PR-native, direct-API, and tool-call execution share one pre-dispatch safeguard receipt contract. Workflow and isolated-Executor paths still need equivalent end-to-end receipt and independent effect-closure coverage before this area can move past `in-progress`. |
| Global kill switch and break-glass controls | implemented | `core/rbac/kill_switch_command.py`; `core/control_loop/_execution.py`; `core/conversation/_write_break_glass_tool.py`; focused RBAC and control-loop tests | Revision-safe state, fail-closed refresh, authority ceiling, time-bound activation, audit, and paging paths exist. A retained operational drill remains open. |
| Data protection and privacy evidence | in-progress | [Data Governance implementation status](data-governance.md#implementation-status); redaction and retention paths cited there; issue `#371` | Major boundaries now implement shared minimization and redaction, but deployment privacy approval and retained production evidence remain open. |
| Standing human authorization (A3-E) | not-started | `config/constitution-traceability.json` requirement `FDAI-CONST-008`; [Escalation and Standing Authority](../../roadmap/decisioning/escalation-and-standing-authority.md) | The shadow non-response supervisor exists, but no standing-authorization catalog, evaluator, or promotion path grants executable A3-E authority. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-29 | in-progress | Reconciled the security ledger with the shared executor safeguard contract, the completed model-bound minimization receipt, and explicit issue handoff for the remaining live drill, privacy, and A3-E evidence. | `core/executor/safeguards.py`; `tests/core/executor/test_safeguard_contract.py`; [Data Governance implementation status](data-governance.md#implementation-status); issues `#81`, `#331`, `#371`, and `#372` | Extend equivalent safeguard and independent-effect receipts to workflow and isolated-Executor paths, then retain governed live evidence. |
| 2026-08-14 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance and aligned security claims with the service cutover, safeguard implementation, kill switch, privacy, and A3-E evidence boundaries. | `current change`; deployment manifests, source, focused tests, and constitutional register cited above. | Close the shared safeguard contract, operational drills, privacy gate, and standing-authorization implementation. |

### Remaining work

- [ ] Extend one shared execution receipt contract so workflow and isolated-Executor paths enforce the same seven safeguards plus independent effect closure already used by PR-native, direct-API, and tool-call paths. Tracked by issue `#81`.
- [ ] Retain governed kill-switch, break-glass, rollback, identity-recertification, and audit-anchor drill receipts on one pinned deployment revision. Tracked by issue `#372`.
- [ ] Complete the data-governance production gate before claiming privacy validation. Tracked by issue `#371`.
- [ ] Implement and shadow-evaluate A3-E standing authorization with quorum, expiry, revocation, handover, scope, evidence, and no-silence authority tests before any promotion. Tracked by issue `#331`.
