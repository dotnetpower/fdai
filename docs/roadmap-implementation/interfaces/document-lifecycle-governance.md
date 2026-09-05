# Document Lifecycle Governance implementation ledger

This ledger tracks delivery of disposable uploads, governed promotion, artifact lineage, retention,
garbage collection, and independently verified purge.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Typed lifecycle and artifact contracts | implemented | service-contract `document.py`; focused lifecycle tests | Independent disposition, scope, index, retention, artifact manifest, and round-trip-safe purge receipt contracts enforce source/derivative retention and access lineage. |
| Temporary and draft retention | implemented | ingestion API retention policy, quota/reconciliation tests, and `155 passed` integrated lifecycle suite | Server-owned expiry, quota accounting, and bounded reconciliation are composed with the native SharePoint connector. |
| Governed promotion | implemented | immutable promotion service and two-step Console confirmation tests | Promotion creates a new governed version, rechecks the source and destination boundary, and remains explicit at the Console. |
| Artifact lineage | implemented | worker `artifact_manifest.py`; focused manifest tests | Retained content has real digest/size lineage; memory-only OCR intermediates use exact observed locators without fabricated integrity claims. |
| Tombstone, cleanup, and purge verification | implemented | worker deletion lifecycle, purge verifier, migration guards, and `168 passed` exact-diff suite | Search joins authoritative version state. Cleanup uses tombstone-first convergence, legacy deletion repair, and independently checked zero-residue receipts. |
| Console lifecycle controls | implemented | Console ingestion client, upload settings, document library, Vitest and Playwright | Operators choose governed knowledge or expiring draft, see expiry/disposition, and confirm promotion before the request is sent. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-05 | implemented | Integrated lifecycle behavior with the FDAI-native SharePoint connector, closed legacy purge and migration authorization gaps, and completed sixteen critique/hardening rounds with no confirmed finding above Low. | Commits `3d6d3f9f7`, `900188ed9`, and `83db60a11`; `155 passed` integrated lifecycle suite; `65 passed` migration inventory suite; `168 passed` exact-diff suite; two Playwright scenarios; Ruff and strict mypy. | No remaining work in this ledger's bounded implementation scope. Production rollout and operational receipts remain release activities. |
| 2026-09-05 | in-progress | Completed eleven independent hardening reviews and fixed non-shared contract, artifact, replay-cleanup, staged-index, claim-fencing, grouping, and promotion-confirmation findings. | `current change`; 36 focused contract/worker tests, 13 Console tests, two Playwright scenarios, Ruff, and strict mypy. | Integrate and harden the reserved Issue #424 API, PostgreSQL, production, migration, and owner-doc hunks before final validation. |
| 2026-09-05 | in-progress | Adopted the approved disposable-by-default lifecycle design after critiquing a TTL-only approach. | `current change`; design owner and current document runtime evidence. | Implement every scope row and complete focused plus hardening validation. |

### Remaining work

- [x] Completed the bounded lifecycle implementation with focused contract, service, migration,
  Console, browser, and sixteen-round hardening evidence recorded above.
