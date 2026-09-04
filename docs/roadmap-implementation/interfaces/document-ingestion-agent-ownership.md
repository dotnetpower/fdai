# Document ingestion agent ownership implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Huginn, Heimdall, Forseti, Saga, Var, and Muninn gate chain | implemented | `services/core-control-plane/tests/agents/test_document_ingestion_agent_chain.py`; `services/core-control-plane/src/fdai/agents/`; document worker audit and index contracts | Focused agent-chain tests prove content-free ingress, verdict, audit, approval, and index-command ownership while Thor ignores non-action document decisions. |
| Independent ingestion API and processing worker | implemented | `services/document-ingestion-api/`; `services/document-processing-worker/`; `packages/service-contracts/src/fdai_service_contracts/document.py` | Separate packages, entry points, contracts, adapters, and focused service tests preserve mechanical process roles. |
| Durable worker claim fencing and recovery | implemented | `services/core-control-plane/src/fdai/core/document_ingestion/`; `services/core-control-plane/tests/core/document_ingestion/`; service-owned worker tests | Focused tests cover gated-state replay, lease and claim ownership, duplicate delivery, and post-decision recovery behavior. |
| Deployed identity, topic RBAC, and restart evidence | in-progress | `config/independent-service-live-evidence-manifest.json`; `infra/`; independent service packages | The topology and bindings are declared and service checks exist, but this owner document has no exact governed receipt for current image identity, topic grants, restart, and no-executor-access probes. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-04 | implemented | Corrected the worker lifecycle route so mechanical inspection facts and Saga/Muninn commands use typed logical channels on the pantheon transport while operational progress stays separate. | `current change`; worker event-boundary tests, Event Hubs role assertions, contract-pin suite, and the document format matrix. | Retain exact deployed identity, transport, restart, and authority-ceiling evidence. |
| 2026-08-14 | in-progress | Adopted the implementation ledger; earlier provenance was not reconstructed. | `current change`; agent-chain, core ingestion, service package, and contract evidence listed in the scope table. | Retain exact deployed identity, transport, restart, and authority-ceiling evidence. |

### Remaining work

- [ ] Retain a governed exact-image receipt proving the API cannot consume worker groups, the worker has only declared receive/send topics, and neither service can obtain Thor's identity or executor roles.
- [ ] Retain restart, duplicate, reorder, lease-expiry, and reconciliation evidence showing that gated states replay facts only and post-decision work converges on one durable stage claim.
- [ ] Record one end-to-end protected and one clear document flow from Huginn ingress through Saga audit and either Var approval or Muninn indexing, with no content copied into transport or audit records.
