# Hub-Managed Entitlement Continuity implementation ledger

This ledger records the delivery decision without upgrading licensing transport or installation status.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Published transport-only entitlement decision | implemented | #2343; `current change`; [English/Korean owner](../../roadmap/deployment/hub-managed-lifecycle-entitlement.md), source/offline owners and current runtime/Trial store references; scoped documentation gates | The Hub is not an issuer. Original installation/deployment binding, Trial anchor, expiry and clock restrictions remain authoritative. |
| Hub carrier and local verification handoff | not-started | Owner remaining implementation obligations; parent #1824 | No token, key, activation, schema or licensing authority change is introduced. |
| Actual connected/offline entitlement continuity | not-started | Parent #1824; existing source/offline acceptance boundaries | Requires approved installation-bound inputs and independent operational observations. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-10-21 | implemented | Selected installation-local authority and persistence with opaque transport-only Hub mediation; documented original Trial/clock continuity and compatibility across upgrade, rollback, recovery and offline import. | #2343; `current change`; owner pair and actual licensing/source references; scoped documentation gates | Implement the carrier/local handoff and qualify current-source, clock, replay and connected/offline effects without inventing an issuer or renewing a Trial. |

### Remaining work

- [x] Publish the entitlement delivery decision and critique separately from runtime capability.
- [ ] Implement purpose-distinct transport and local verification with existing licensing authority.
- [ ] Retain exact authorized connected/offline continuity, expiry, clock and recovery evidence.
