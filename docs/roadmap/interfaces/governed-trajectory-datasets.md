---
title: Governed Trajectory Datasets
---

# Governed Trajectory Datasets

This document defines how FDAI joins observable runtime records into versioned,
access-scoped trajectory datasets for offline quality review. The contract preserves failures
and source provenance while excluding hidden reasoning, unrestricted payloads, and credentials.

> Trajectory export is an evidence operation, not a training or promotion action. The console
> remains read-only, and Norns receives only explicitly reviewed aggregates.

## Design at a glance

The export path authorizes the principal, purpose, and access scope before any source provider is
called. It then joins immutable source snapshots in canonical order, scans every projected record,
streams deterministic JSONL, and publishes the data file and manifest only after both complete.

```mermaid
flowchart LR
    REQUEST[Purpose + access scope] --> AUTH[Authorize]
    AUTH --> SOURCES[Immutable source snapshots]
    SOURCES --> JOIN[Canonical join + projection]
    JOIN --> SCAN[Secret, identifier, injection scan]
    SCAN -->|clean| EXPORT[JSONL + checksums + manifest]
    SCAN -->|uncertain| QUARANTINE[Quarantine metadata]
    EXPORT --> VALIDATE[Offline validate + replay check]
    VALIDATE --> REVIEW[Human review]
    REVIEW --> NORNS[Norns aggregate intake]
```

## Stable envelope

Schema version `1.0` is the current write version. A reader accepts only versions explicitly
listed by `TrajectoryVersionPolicy`; readable versions share the current major version. Writers
always emit the current version, and offline validation rejects an unsupported manifest or record.

Each `TrajectoryEnvelope` contains:

| Field group | Required data |
|-------------|---------------|
| Identity | Schema version, trajectory id, trace id, correlation id |
| Time | Timezone-aware start and completion timestamps |
| Runtime | Environment, evidence profile, model capability id |
| Access | Principal-scope SHA-256 digest, never a credential or token |
| Completion | One of `completed`, `failed`, `cancelled`, `timed_out`, `abstained`, `ambiguous` |
| Governance | Purpose, retention, deletion due date, legal-hold state and reference |
| Redaction | Redaction-policy version used for projection |
| Provenance | Sorted immutable source record ids and SHA-256 digests |
| Observations | Contiguous zero-based steps and catalog-shaped tool statistics |

The final step is always one `terminal_outcome` whose value matches `completion_status`. Failed,
cancelled, timed-out, abstained, and ambiguous runs remain first-class records; export never drops
them to improve a success metric.

## Observable steps

The projection admits only these step kinds:

- `normalized_input_reference`
- `routing_decision`
- `assistant_output`
- `tool_request` and `tool_receipt`
- `action_request` and `action_receipt`
- `verifier_result` and `risk_result`
- `approval`
- `terminal_outcome`
- `rollback_state`

Each kind has its own byte cap from 4 KiB to 16 KiB. A source provider returns a bounded excerpt or
reference, not a raw record body. Recursive payload validation blocks hidden reasoning,
chain-of-thought, raw prompts, credentials, tokens, authorization headers, unrestricted tool
output, raw cloud payloads, and attachments. Non-JSON values and oversized excerpts fail closed.

Tool statistics are generated from the complete server-owned tool catalog. Every catalog tool
gets one lexically ordered column, including tools with zero requests, so columns do not shift
between batches. An observed tool absent from the catalog blocks projection.

## Source providers and authorization

`shared/providers/trajectory.py` defines separate async snapshot Protocols for audit,
conversation, tool, approval, and terminal-outcome sources. Each provider returns frozen metadata
with a source digest. Provider implementations retain their existing authority and storage model;
the trajectory join does not become another system of record.

`TrajectoryJoinService` first calls `TrajectoryAccessAuthorizer.authorize(principal_id,
access_scope, purpose)`. No provider method runs before authorization succeeds. The built-in
allowlist authorizer denies unknown principal/scope/purpose triples and computes the scope digest;
a deployment can inject a policy-backed authorizer without changing core projection logic.

Batch filters are explicit and server-side:

- timezone-aware start and end time
- vertical
- action type
- tier
- terminal outcome
- evidence profile

## Deterministic export

`TrajectoryJsonlExporter` requires a gitignored `.trajectory.jsonl` filename and writes to its
`.partial` sibling with canonical sorted-key JSON. Every JSONL
line wraps one record and its SHA-256 checksum. The exporter hashes the exact line bytes into a
dataset checksum and writes a separate canonical manifest containing dataset id, schema version,
purpose, scope digest, record count, outcome counts, dataset checksum, and manifest checksum.

Data and manifest are renamed into place only after both are complete. Cancellation, an exception,
an empty dataset, or a quarantine finding removes partial files. The exporter never writes a
partially trusted dataset at the final path. Every record must use the current schema and match the
request's purpose and authorized scope digest before the first byte is accepted.

The scanner quarantines a dataset when any record has an uncertain secret pattern, non-placeholder
identifier, resource id, non-example email address, or prompt-injection marker. Quarantine stores
only finding codes and trajectory identity. It never echoes the matched sensitive value.

## Offline validation and replay

`validate_export` runs without network or cloud credentials. It rejects:

- missing, empty, malformed, or unsupported-version exports
- record, dataset, or manifest checksum mismatches
- record and outcome counts that disagree with the manifest
- non-contiguous step order or multiple/missing terminal outcomes
- non-canonical trajectory ordering or duplicate trajectory identities
- a step whose source digest is absent from the envelope source map
- payloads incompatible with the current redaction and excerpt policy

`replay_check` is judge-only. It verifies mapping and order and never invokes a tool, action,
training job, promotion, or executor.

## Retention and legal hold

Alembic revisions `20260720_0048` and `20260814_0084` store dataset metadata, quarantine codes,
and the deletion claim state, not exported record bodies. `TrajectoryRetentionService` first
compare-and-sets an eligible completed record to `deleting`. That claim rejects legal hold and
prevents a hold from being added after external deletion begins. The injected artifact deletion
contract is idempotent, so a crash after artifact deletion resumes the same `deleting` claim. A
provider or tombstone failure stays retryable, and only a claimed record can clear its storage
reference and become `deleted`. Schema downgrade is blocked while any deletion claim remains active,
because the database cannot infer whether an external artifact was already removed.

Customer-scoped JSONL and manifests are runtime artifacts. The exporter-enforced suffix is ignored
by git, and these files are never committed to this repository.

## Administrative surfaces

The Operator API optionally registers Owner-only GET routes:

- `GET /admin/trajectory-datasets?purpose=...&access_scope=...`
- `GET /admin/trajectory-datasets/{dataset_id}?purpose=...&access_scope=...`

Both parameters are required. Scope denial returns not found, and responses omit storage paths.
POST is not registered. Responses explicitly report that training and promotion actions are not
available.

The planned `fdaictl trajectory validate` command will require `--dataset`, `--manifest`,
`--purpose`, and `--access-scope`. No packaged CLI command is registered yet. When implemented, it
will run the same offline validator and replay checks, then verify that the manifest purpose and
scope digest match the operator request.

## Norns boundary

Norns accepts `ReviewedTrajectoryDataset`, which contains a human review receipt, manifest
checksum, outcome counts, and tool request counts. It does not accept raw trajectory records.
Consumption is digest-deduplicated and records behavior telemetry only; it creates no candidate by
itself and has no automatic training or promotion path. Any later proposal remains inert and uses
the existing Norns-to-Mimir quality gate.

## Code and tests

| Responsibility | Location |
|----------------|----------|
| Envelope, projection, review, validation | `services/core-control-plane/src/fdai/core/trajectory/` |
| Source and dataset provider contracts | `services/core-control-plane/src/fdai/shared/providers/trajectory.py` |
| JSONL exporter and scanner quarantine | `services/core-control-plane/src/fdai/delivery/trajectory/` |
| PostgreSQL metadata adapters | `services/core-control-plane/src/fdai/delivery/persistence/postgres_trajectory.py` |
| Read-only admin routes | `services/operator-service/src/fdai_operator_service/` |
| Offline CLI | Not implemented |
| Migrations | `alembic/versions/20260720_0048_trajectory_dataset.py`; `alembic/versions/20260814_0084_trajectory_deletion_claim.py` |
| Focused tests | `services/core-control-plane/tests/core/trajectory/`, `services/core-control-plane/tests/persistence/test_postgres_trajectory.py`, `services/core-control-plane/tests/composition/test_trajectory.py`, `services/core-control-plane/tests/agents/test_norns_trajectory.py` |

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Envelope and projection | implemented | `services/core-control-plane/src/fdai/core/trajectory/`; `services/core-control-plane/tests/core/trajectory/` | Focused tests cover bounded records, projection, version policy, retention decisions, and authorization-before-read. |
| Scanning, export, and offline validation | in-progress | `services/core-control-plane/src/fdai/core/trajectory/scanning.py`; `services/core-control-plane/src/fdai/core/trajectory/validation.py`; `services/core-control-plane/src/fdai/delivery/trajectory/` | Implementations exist, but no focused exporter, quarantine, checksum, or replay-validation tests were found in the current tree. |
| Metadata persistence, retention, and Owner-only read routes | implemented | trajectory migrations; `services/core-control-plane/src/fdai/delivery/persistence/postgres_trajectory.py`; `services/core-control-plane/tests/persistence/test_postgres_trajectory.py`; `services/operator-service/src/fdai_operator_service/families/workflow/`; `services/operator-service/tests/test_operator_workflow_family.py` | The PostgreSQL adapter enforces exact duplicate metadata, scope-bound reads, due ordering, monotonic legal holds, a durable `deleting` claim, late-hold rejection, retryable artifact or tombstone failure, and a live downgrade guard. Governed runtime custody and deletion evidence remains open. |
| Offline CLI validation | not-started | [Administrative surfaces](#administrative-surfaces) | The command contract is designed, but no packaged `fdaictl trajectory validate` implementation is registered. |
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

### Remaining work

- [x] Run the focused PostgreSQL trajectory suite against the supported local database with no skips, including legal-hold compare-and-set, retryable deletion failure, and live downgrade guard coverage.
- [ ] Add focused exporter, scanner, quarantine, checksum, offline validation, and judge-only replay checks, then keep every generated artifact outside source control.
- [ ] Implement and pass a packaged `fdaictl trajectory validate` check over generated JSONL and manifest artifacts, including purpose and access-scope mismatch cases.
- [ ] Record a governed end-to-end receipt that exports, validates, reviews, retains, and deletes one dataset while proving that legal hold blocks deletion and no raw record reaches Norns.

## Related docs

| To learn about | Read |
|----------------|------|
| Module and DI boundaries | [Project structure](../architecture/project-structure.md) |
| Read-only operator surfaces | [Operator console](operator-console.md) |
| Norns role and permissions | [Agent pantheon](../agents/agent-pantheon.md) |
| Audit and identity controls | [Security and identity](../architecture/security-and-identity.md) |
