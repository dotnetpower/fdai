# Hub-Managed Entitlement Continuity implementation ledger

This ledger separates the delivery decision, bounded source implementation and installed qualification.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Published transport-only entitlement decision | implemented | #2343; `current change`; [English/Korean owner](../../roadmap/deployment/hub-managed-lifecycle-entitlement.md), source/offline owners and current runtime/Trial store references; scoped documentation gates | The Hub is not an issuer. Original installation/deployment binding, Trial anchor, expiry and clock restrictions remain authoritative. |
| Direct/offline full-entitlement transport and local owner | implemented | #2352; `current change`; shared pure carrier, real producer CLI, Core importer/private PostgreSQL acceptance and optional runtime source; 188 focused source/actual PostgreSQL checks | Existing original full grant only; immutable record/audit, same duplicate receipt, no timestamp winner or issuer override, unchanged Trial state. Fresh-process metadata uses synthetic issuer injection, not packaged-production trust. |
| Hub API/Plan handoff and separately governed rotation | not-started | Parent #1824; owner remaining obligations | Hub still cannot mint or reinterpret a grant. No automatic replacement, clear or delete API is implemented. |
| Actual connected/offline entitlement continuity | not-started | Parent #1824; existing source/offline acceptance boundaries | Requires approved installation-bound inputs and independent operational observations. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-10-21 | implemented | Added entitlement-only X25519/HKDF/AES-GCM carrier, private real CLI output, local licensing-owner verification, atomic original-token/audit acceptance and optional off-loop runtime reads. A real concurrent duplicate race against a non-arbiter unique index was reproduced; native conflict handling now covers all unique constraints without retries. Added independent safe receipt inspection for uncertain commit outcomes. | `current change`; 188 focused tests, including actual isolated PostgreSQL, native ACLs, Trial anchor/revision/clock preservation, audit rollback, duplicate concurrency, wrong bindings, and true fresh producer/importer/inspection processes; seven changed-source mypy checks passed. | Additional public CLI help and immutable delivery gates are recorded in the PR; complete Hub API/Plan integration, trusted rotation, real key onboarding/packaged issuer acceptance, old-binary compatibility and connected/offline installation/drill qualification remain open. No live operation or Trial activation. |
| 2026-10-21 | implemented | Selected installation-local authority and persistence with opaque transport-only Hub mediation; documented original Trial/clock continuity and compatibility across upgrade, rollback, recovery and offline import. | #2343; `current change`; owner pair and actual licensing/source references; scoped documentation gates | Implement the carrier/local handoff and qualify current-source, clock, replay and connected/offline effects without inventing an issuer or renewing a Trial. |

### Remaining work

- [x] Publish the entitlement delivery decision and critique separately from runtime capability.
- [x] Implement the bounded direct/offline transport, local verification and immutable acceptance
  source in #2352; existing source/offline omission and all authority boundaries remain.
- [ ] Implement actual Hub transport/Plan wiring and a separately governed rotation contract.
- [ ] Retain exact authorized connected/offline continuity, expiry, clock and recovery evidence.
