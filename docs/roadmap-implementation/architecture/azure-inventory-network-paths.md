# Restricted-network Azure inventory implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Restricted-network discovery and ordered source fallback | in-progress | Azure inventory adapters under `delivery/azure/`; deployment preflight and connectivity contracts | The bounded adapters and failure classes exist. This document does not retain one exact-revision protected deployment proving every fallback rung. |
| Snapshot authority and stale-state handling | implemented | Inventory sync, projection, and reconciliation tests cited by [CSP-Neutrality Contracts](csp-neutrality.md#implementation-status) | Partial collection cannot replace the last complete promoted generation or authorize an absence claim. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-21 | in-progress | Moved the existing restricted-network inventory design into a focused owner document without changing runtime behavior or authority. | `current change`; document-size, translation, route, and link checks. | Retain exact-revision protected evidence for the effective network path and at least one failover and recovery transition. |

### Remaining work

- [ ] Retain an exact-revision protected deployment receipt that proves token, DNS, TCP/TLS,
  bounded ARG query, private projection write, one unavailable-source fallback, stale retention,
  and successful recovery without widening discovery or executor identity.
