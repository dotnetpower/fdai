# Document Lifecycle Governance implementation ledger

This ledger tracks delivery of disposable uploads, governed promotion, artifact lineage, retention,
garbage collection, and independently verified purge.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Typed lifecycle and artifact contracts | implemented | service-contract `document.py`; focused lifecycle tests | Independent disposition, scope, index, retention, artifact manifest, and round-trip-safe purge receipt contracts enforce source/derivative retention and access lineage. |
| Temporary and draft retention | in-progress | lifecycle API delta; temporary quota and reconciliation tests | Server-owned expiry and quota behavior is implemented but awaits Issue #424 shared-path integration; conversation-channel composition remains open. |
| Governed promotion | in-progress | immutable promotion delta; Console confirmation tests | Replay-safe source copying and explicit Console confirmation are implemented but await shared API integration and sensitive-content review binding. |
| Artifact lineage | implemented | worker `artifact_manifest.py`; focused manifest tests | Retained content has real digest/size lineage; memory-only OCR intermediates use exact observed locators without fabricated integrity claims. |
| Tombstone, cleanup, and purge verification | in-progress | worker deletion lifecycle, purge verifier, exclusive stage claims, focused replay tests | Worker cleanup and zero-residue receipts are implemented. Authoritative search joining and shared lifecycle trigger hardening await Issue #424 integration. |
| Console lifecycle controls | implemented | Console ingestion client, upload settings, document library, Vitest and Playwright | Operators choose governed knowledge or expiring draft, see expiry/disposition, and confirm promotion before the request is sent. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-05 | in-progress | Completed eleven independent hardening reviews and fixed non-shared contract, artifact, replay-cleanup, staged-index, claim-fencing, grouping, and promotion-confirmation findings. | `current change`; 36 focused contract/worker tests, 13 Console tests, two Playwright scenarios, Ruff, and strict mypy. | Integrate and harden the reserved Issue #424 API, PostgreSQL, production, migration, and owner-doc hunks before final validation. |
| 2026-09-05 | in-progress | Adopted the approved disposable-by-default lifecycle design after critiquing a TTL-only approach. | `current change`; design owner and current document runtime evidence. | Implement every scope row and complete focused plus hardening validation. |

### Remaining work

- [ ] Complete typed contracts and their invariant tests.
- [ ] Persist retention leases, artifact manifests, cleanup intents, and purge receipts.
- [ ] Wire temporary expiry, immutable promotion, lineage storage, GC, and independent verification.
- [ ] Expose lifecycle controls and evidence in Console.
- [ ] Complete at least ten hardening rounds with no confirmed finding above Low.
