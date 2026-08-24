# Service Decomposition Execution Plan implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| SD-00 through SD-09 service decomposition | validated | `config/service-decomposition.json`; [Evidence log](../../roadmap/architecture/service-decomposition-execution-plan.md#evidence-log), including the SD-09 centralized validation receipt | All ten work packages are complete, and the authority cutover, exact topology, rollback, and structural closure have retained evidence. |
| IS-00 through IS-09 independent service extraction | validated | `config/independent-services.json`; `config/independent-service-live-evidence-manifest.json`; `config/independent-service-remote-evidence.attestation.jsonl`; [IS evidence log](../../roadmap/architecture/service-decomposition-execution-plan.md#evidence-log) | Five independently releasable distributions, service roots, migration branches, protected transitions, and remote N/N-1/N proof are retained. |
| Five-service ownership and isolated execution authority | validated | SD-08 and IS-09 evidence rows; `services/`; `packages/service-contracts/`; `service-migrations/branches/` | Core, Operator, Ingestion API, Processing Worker, and Isolated Executor have distinct process, identity, transport, health, and data ownership boundaries. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-14 | validated | Adopted the required implementation ledger by summarizing the existing append-only SD and IS evidence without rewriting prior transitions. | `current change`; machine manifests and the retained local, remote, rollback, and attestation records cited above. | No remaining work for the bounded SD or IS programs; later service candidates use the separate graduation decision process. |

### Remaining work

- [x] No work remains for SD-00 through SD-09 or IS-00 through IS-09; the machine manifests, evidence log, remote attestation, and focused program checks record completion.
