# Restricted-network Azure inventory implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Restricted-network discovery and ordered source fallback | in-progress | Azure inventory adapters under `delivery/azure/`; deployment preflight and connectivity contracts; [Issue #361](https://github.com/dotnetpower/fdai/issues/361) | The bounded adapters and failure classes exist. This document does not retain one exact-revision protected deployment proving every fallback rung. |
| Isolated restricted-network certification | implemented | `inventory_network_certification.py`; `inventory_network_certification_cli.py`; `infra/inventory-network-certification/`; exact create and cleanup plan verifier; focused Core and integration checks | The mechanism binds one exact image and source revision to a task-owned sandbox, uses distinct campaign and verifier identities, preserves the active generation during primary failure, and fails closed before cleanup. No governed Azure run is claimed yet. |
| Snapshot authority and stale-state handling | implemented | Inventory sync, projection, and reconciliation tests cited by [CSP-Neutrality Contracts](csp-neutrality.md#implementation-status) | Partial collection cannot replace the last complete promoted generation or authorize an absence claim. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-27 | implemented | Closed the exact Terraform security-scan gap before publication by adding infrastructure encryption, default-deny storage rules, Blob diagnostics, PostgreSQL audit settings, and one NSG across every sandbox subnet. | `current change`; exact CI finding `AZU-0061`; local Trivy 0 findings above Low; Checkov 0 failed checks; exact plan-gate tests passed 5 cases. | Publish the corrected head, require exact-head CI, then run and clean up the governed campaign. |
| 2026-09-27 | implemented | Added the isolated local-coordinator certification mechanism selected by the operator: task-owned private networking and state, separate workload and verifier identities, source-specific ARG fault injection with one ARM fallback, active-generation retention, ARG recovery, private receipt readback, and exact create/delete plan gates. | `current change`; Core certification and endpoint-boundary tests passed 17 cases; Terraform formatting and validation passed; plan-gate Ruff passed. | Merge the exact source revision, publish/import its prebuilt image, run the governed sandbox campaign, verify recovery and task-only cleanup, then retain the sanitized receipt under #361. |
| 2026-08-29 | in-progress | Assigned the remaining token, network, query, private-write, failover, stale-retention, and recovery proof to one exact-revision protected evidence issue without changing adapter behavior or authority. | `current change`; [Issue #361](https://github.com/dotnetpower/fdai/issues/361); current adapter and snapshot evidence in the scope table. | Retain the governed fallback and recovery receipt before changing this area to validated. |
| 2026-08-21 | in-progress | Moved the existing restricted-network inventory design into a focused owner document without changing runtime behavior or authority. | `current change`; document-size, translation, route, and link checks. | Retain exact-revision protected evidence for the effective network path and at least one failover and recovery transition. |

### Remaining work

- [ ] Under [Issue #361](https://github.com/dotnetpower/fdai/issues/361), retain an exact-revision protected deployment receipt that proves token, DNS, TCP/TLS, bounded ARG query, private projection write, one unavailable-source fallback, stale retention, and successful recovery without widening discovery or executor identity.
