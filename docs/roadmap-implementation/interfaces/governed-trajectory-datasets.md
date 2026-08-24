# Governed Trajectory Datasets implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Envelope and projection | implemented | `services/core-control-plane/src/fdai/core/trajectory/`; `services/core-control-plane/tests/core/trajectory/` | Focused tests cover bounded records, projection, version policy, retention decisions, and authorization-before-read. |
| Scanning, export, and offline validation | implemented | `services/core-control-plane/src/fdai/core/trajectory/scanning.py`; `validation.py`; `services/core-control-plane/src/fdai/delivery/trajectory/exporter.py`; `services/core-control-plane/tests/core/trajectory/test_export_and_validation.py` | Focused tests cover scanner findings without echoing the matched value, quarantine with no published artifact, cancellation cleanup, purpose and scope mismatch, record, manifest, and dataset checksums, and judge-only replay order and source mapping. Generated artifacts stay untracked through `.gitignore`. |
| Metadata persistence, retention, and Owner-only read routes | implemented | trajectory migrations; `services/core-control-plane/src/fdai/delivery/persistence/postgres_trajectory.py`; `services/core-control-plane/tests/persistence/test_postgres_trajectory.py`; `services/operator-service/src/fdai_operator_service/families/workflow/`; `services/operator-service/tests/test_operator_workflow_family.py` | The PostgreSQL adapter enforces exact duplicate metadata, scope-bound reads, due ordering, monotonic legal holds, a durable `deleting` claim, late-hold rejection, retryable artifact or tombstone failure, and a live downgrade guard. Governed runtime custody and deletion evidence remains open. |
| Offline CLI validation | not-started | [Administrative surfaces](../../roadmap/interfaces/governed-trajectory-datasets.md#administrative-surfaces) | The command contract is designed, but no packaged `fdaictl trajectory validate` implementation is registered. |
| Reviewed Norns intake | implemented | `services/core-control-plane/src/fdai/agents/norns.py`; `services/core-control-plane/tests/agents/test_norns_trajectory.py` | Norns accepts only `ReviewedTrajectoryDataset`, deduplicates by digest, and receives no raw record or automatic training authority. |
| Operational artifact custody and deletion | in-progress | `services/core-control-plane/src/fdai/core/trajectory/datasets.py`; `services/core-control-plane/src/fdai/delivery/trajectory/service.py` | Retention and cleanup behavior exist in code, but no governed runtime receipt proves end-to-end artifact deletion, legal-hold preservation, and retry after provider failure. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-14 | in-progress | Adopted the implementation ledger; earlier provenance was not reconstructed. | `current change`; current source and focused checks listed in the scope table. | Close the PostgreSQL, packaged CLI, and governed artifact-custody evidence below. |
| 2026-08-14 | implemented | Added the missing PostgreSQL trajectory metadata adapter and proved retention semantics against a live database. | `current change`; `test_postgres_trajectory.py` passed three cases with zero skips against a disposable supported database. | Add focused export and packaged CLI checks, then retain governed artifact-custody evidence. |
| 2026-08-14 | implemented | Hardened retention with a durable `deleting` claim and idempotent crash recovery before tombstone. | `current change`; focused core, PostgreSQL, and migration checks passed 186 cases. | Retain governed artifact-custody evidence over the same claim protocol. |
| 2026-08-14 | implemented | Blocked schema downgrade while any external deletion claim is active instead of guessing an unsafe completed state. | `current change`; focused Core, PostgreSQL, and migration checks passed 187 cases. | Reconcile active claims before an intentional downgrade. |
| 2026-08-14 | implemented | Executed the exact migration downgrade guard against an active PostgreSQL deletion claim and verified SQLSTATE `55000`. | `current change`; focused Core, PostgreSQL, and migration checks passed 188 cases. | Keep the guard in the migration-focused validation lane. |
| 2026-08-15 | implemented | Added focused exporter, scanner, quarantine, checksum, offline-validation, and judge-only replay checks over generated JSONL and manifest artifacts. | `current change`; `services/core-control-plane/tests/core/trajectory/test_export_and_validation.py`; `pytest services/core-control-plane/tests/core/trajectory/test_export_and_validation.py` (19 passed). | The packaged offline CLI command and governed runtime custody evidence remain open. |

### Remaining work

- [x] Run the focused PostgreSQL trajectory suite against the supported local database with no skips, including legal-hold compare-and-set, retryable deletion failure, and live downgrade guard coverage.
- [x] Focused exporter, scanner, quarantine, checksum, offline-validation, and judge-only replay checks exist in `services/core-control-plane/tests/core/trajectory/test_export_and_validation.py`, and `.gitignore` keeps every generated export, manifest, and partial artifact outside source control.
- [ ] Implement and pass a packaged `fdaictl trajectory validate` check over generated JSONL and manifest artifacts, including purpose and access-scope mismatch cases.
- [ ] Record a governed end-to-end receipt that exports, validates, reviews, retains, and deletes one dataset while proving that legal hold blocks deletion and no raw record reaches Norns.
