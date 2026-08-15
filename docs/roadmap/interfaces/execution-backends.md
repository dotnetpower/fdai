---
title: Governed Execution Backends
---

# Governed Execution Backends

This document defines the provider-neutral lifecycle used to run an already-approved command or
task on an isolated execution venue. It keeps eligibility, judgment, human approval, rollback, and
audit ownership outside the backend while giving every submission a durable, bounded lifecycle.

> New profiles start disabled. A profile and adapter can run shadow feasibility probes before
> selection, but profile presence never promotes a capability or enables enforcement.

> Azure Container Apps Job is the only new deployed backend in this design. Live Azure evidence is
> still required before any profile can be considered for promotion.

## Design at a glance

FDAI validates a command or task against its existing sandbox catalog first. It then intersects the
validated authority with an immutable server-owned `ExecutionBackendProfile`. The backend receives
only the effective request and performs lifecycle I/O. It never decides whether the action should
run.

```mermaid
flowchart LR
    THOR[Thor dispatch] --> SANDBOX[Existing sandbox validation]
    SANDBOX --> INTERSECT[No-widening profile intersection]
    INTERSECT --> LEDGER[Durable submission claim]
    LEDGER --> BACKEND[ExecutionBackend]
    BACKEND --> STATUS[Status, receipt, cleanup]
    STATUS --> LEDGER
```

## Authority boundary

| Concern | Owner | Backend role |
|---------|-------|--------------|
| Eligibility and action judgment | Forseti, deterministic verifier, risk gate | No authority |
| Human approval | Var and the existing approval path | Consumes already-approved dispatch only |
| Privileged dispatch | Thor | Retains `owner_trace` evidence on every submission |
| Resource lock and blast radius | Existing executor path | No lock or blast-radius decision |
| Rollback | Vidar and the ActionType rollback contract | Reports lifecycle state; never selects rollback |
| Audit durability | Saga and the audit store | Carries an `audit_ref`; never writes or judges audit |
| Narration | Bragi | No credential, profile-selection, or execution role |

Mutation operations still pass the existing risk decision, promotion state, approval, resource
lock, rollback availability, and audit checks before a backend request exists. Adding a backend
does not create a fifth execution path. It is a venue behind an existing governed path.

## Provider-neutral protocol

`ExecutionBackend` in `shared/providers/execution_backend.py` exposes these asynchronous
operations:

- **`plan`**: validates backend shape without starting work.
- **`submit`**: starts one idempotent plan.
- **`status`**: reconciles provider state.
- **`cancel`**: requests bounded cancellation and reports races honestly.
- **`collect_receipt`**: returns terminal provider evidence.
- **`cleanup`**: removes owned artifacts or records provider-retention behavior.
- **`capabilities`**: reports lifecycle support without granting authority.
- **`health`**: reports reachable, degraded, or unavailable state.

Every request requires a stable idempotency key, immutable artifact digest, Thor owner trace, stop
condition, audit reference, profile id and version, region, and scope. The contract has no raw
credential field. Azure adapters receive an injected `WorkloadIdentity`; console and narrator
principals never enter the request.

## Server-owned profiles

An `ExecutionBackendProfile` is frozen and versioned. It contains:

- backend kind and allowed command or task ids;
- workspace mode and network profiles;
- credential profile references, never credential values;
- timeout, output, CPU, memory, ephemeral storage, and concurrency ceilings;
- persistence mode, allowed regions and scopes, and cancellation guarantee; and
- for Container Apps Job only, a server-owned template reference and pinned image digest.

Profile documents have no `enabled` or `promoted` field. Startup config selects enabled profile ids
in a separate top-level list. Unknown fields, unknown enabled ids, duplicate values, malformed
references, or missing adapter bindings fail startup.

## No-widening intersection

The existing `SandboxProfileCatalog` and `VmTaskSandboxCatalog` remain authoritative. Adapters first
call their existing `constrain` operation, then apply `intersect_execution_profile`. The backend
profile must be a subset of the validated authority for workload ids, network, credential refs,
region, and scope. Workspace rank and every numeric ceiling must be equal or lower.

A request, generated task, installed skill, profile file, or downstream distribution cannot add a
command, credential, network path, writable workspace, resource allowance, region, or scope. A
widening attempt fails before provider I/O.

## Durable lifecycle ledger

Alembic `0049` adds `execution_submission` and `execution_submission_attempt`. The submission row
is keyed by idempotency key and preserves immutable request evidence, provider refs, status,
cancellation intent, cleanup state, retention deadline, and a CAS revision. The attempt table keeps
ordered submit, status, cancel, receipt, and cleanup attempts.

The coordinator handles these cases:

- **Duplicate submit or restart**: returns the existing ledger receipt and does not re-submit.
- **Missing profile after restart**: requires the exact recorded profile id and version for status,
  cancellation, receipt, and cleanup. An unavailable or changed profile records `ambiguous` and
  performs no provider lifecycle call.
- **Submit transport loss**: records `ambiguous`; it does not assume success or retry blindly.
- **Lost status**: records terminal `ambiguous` so autonomy fails closed.
- **Timeout**: requests cancellation when the server-owned deadline expires.
- **Cancel race**: preserves a provider-observed terminal success or failure instead of rewriting it
  as cancelled.
- **Cleanup**: runs only after terminal state and records completed or provider-retention cleanup.

## Adapter behavior

> **Current adapter status:** `BubblewrapExecutionBackend` and `VmTaskExecutionBackend` are
> implemented under the `ExecutionBackend` protocol in
> [`delivery/execution_backend/adapters.py`](../../../services/core-control-plane/src/fdai/delivery/execution_backend/adapters.py).
> Both wrap their existing sandbox catalog and can only narrow it. Their plan and receipt maps
> are process-local, released by coordinator cleanup, and reported through
> `durable_provider_state`. Governed shadow receipts and
> composition binding are still outstanding. `AzureContainerAppsJobExecutionBackend` is not
> implemented. The existing `delivery/azure/vm_task.py` provider remains a lower-level VM
> capability, not the governed lifecycle adapter described here.

### Bubblewrap local read

`BubblewrapExecutionBackend` preserves the existing offline, credential-free, read-only workspace
contract. The command catalog and sandbox profile validate the typed `CommandPlan`; the backend
profile can only lower timeout and output limits. Submit returns after the local process is
terminal, and process timeout remains the cancellation mechanism.

### Governed VM task

`VmTaskExecutionBackend` preserves content-addressed Python task validation, declared capability
checks, target opt-in, and Managed Run Command lifecycle behavior. It can only lower the task
timeout and the server-owned execution envelope.

### Azure Container Apps Job

`AzureContainerAppsJobExecutionBackend` starts a pre-provisioned Job through ARM HTTPS using an
injected `WorkloadIdentity` and `httpx` client. The request cannot supply an image, command,
environment variable, or credential. The adapter sends an empty start body and resolves the Job
resource from a server-owned template map.

Health discovery reads the Job and verifies that its configured image uses the expected pinned
digest. Requests use bounded timeout, retry count, `Retry-After`, and the shared circuit breaker.
Status, stop, and receipt calls validate the ARM host and Job execution path.

Container Apps retains execution metadata according to provider policy. Cleanup therefore confirms
terminal or stop behavior and records `provider_retention`; it does not claim that Azure deleted an
execution record.

## Cost and failure posture

- **Cost ceiling**: CPU, memory, ephemeral storage, concurrency, timeout, and region are profile
  values selected by the server. A request cannot raise them.
- **Failure posture**: ambiguous submission or status is terminal and requires operator review.
  Circuit-open health is unavailable, not healthy-by-default.
- **Cleanup posture**: local receipts are released, VM Run Command resources are removed through
  the existing cancellation path, and Container Apps Job history follows provider retention.
- **Retention**: the ledger keeps a server-owned deadline for reconciliation and cleanup policy.

## Shadow probes and promotion residual

Disabled profiles may run `health`, `capabilities`, and `plan` through `shadow_probe`. The probe does
not create a ledger submission and never calls `submit`. Profile selection and ActionType promotion
remain separate controls.

Before an Azure Container Apps Job profile can move beyond disabled shadow observation, operators
still need live evidence for identity scope, ARM reachability, pinned-image health, duplicate start
behavior, timeout and stop races, receipt completeness, provider retention, and measured cost. That
evidence remains deployment follow-up; unit tests and mock HTTP evidence do not count as promotion
evidence.

## Code map

| Responsibility | Source | Tests |
|----------------|--------|-------|
| Protocol and ledger records | `services/core-control-plane/src/fdai/shared/providers/execution_backend.py` | provider and focused lifecycle tests |
| Profiles, registry, coordinator | `services/core-control-plane/src/fdai/core/execution_backend/` | `services/core-control-plane/tests/core/execution_backend/` |
| Bubblewrap and VM adapters | `services/core-control-plane/src/fdai/delivery/execution_backend/adapters.py` | `services/core-control-plane/tests/delivery/test_execution_backend_adapters.py` |
| Azure Container Apps Job | Not implemented | No focused adapter tests |
| PostgreSQL ledger | `services/core-control-plane/src/fdai/delivery/persistence/postgres_execution_backend.py` | `services/core-control-plane/tests/persistence/test_execution_backend_ledger.py` |
| Startup binding | `services/core-control-plane/src/fdai/composition/wire_execution_backends.py` | `services/core-control-plane/tests/composition/test_execution_backends.py` |

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Provider protocol, profiles, no-widening checks, and coordinator | implemented | `services/core-control-plane/src/fdai/shared/providers/execution_backend.py`; `services/core-control-plane/src/fdai/core/execution_backend/`; `services/core-control-plane/tests/core/execution_backend/` | Focused tests cover profile bounds, lifecycle transitions, idempotency, ambiguity, cancellation, cleanup, and shadow probes. |
| PostgreSQL ledger | implemented | `alembic/versions/20260721_0049_execution_backend.py`; `services/core-control-plane/src/fdai/delivery/persistence/postgres_execution_backend.py`; `services/core-control-plane/tests/persistence/test_execution_backend_ledger.py` | The durable path, restart read, idempotent duplicate handling, attempt history, and CAS conflict behavior pass focused tests. The PostgreSQL ledger suite passed two cases with zero skips against a disposable supported database. |
| Startup binding | in-progress | `services/core-control-plane/src/fdai/composition/wire_execution_backends.py`; `services/core-control-plane/tests/composition/test_execution_backends.py` | The seam exists and `bind_execution_backends` has a focused test, but no runtime path calls it: `grep -rn bind_execution_backends` matches only the definition, the `composition` facade re-export, and that test. `load_execution_backend_registry_file` has zero callers anywhere, including tests, so the registry document it validates is never loaded and no such document exists in `config/` or `infra/`. The test also binds `object()` and an in-memory ledger rather than the real adapters and the PostgreSQL ledger. |
| Bubblewrap and governed VM adapters | implemented | `services/core-control-plane/src/fdai/delivery/execution_backend/adapters.py`; `services/core-control-plane/tests/delivery/test_execution_backend_adapters.py` | Both adapters call their existing sandbox `constrain` first, then `intersect_execution_profile`, so a widening profile fails before provider I/O. Bubblewrap declares no cancellation and refuses to fake it; the VM adapter maps status, cancel, and provider retention. Composition binding and governed shadow receipts remain open. |
| Azure Container Apps Job adapter | not-started | [Azure Container Apps Job](#azure-container-apps-job) | No governed Job backend implementation or focused adapter test is present. |
| Live shadow and promotion evidence | not-started | [Shadow probes and promotion residual](#shadow-probes-and-promotion-residual) | Mock lifecycle checks do not prove identity, ARM reachability, races, receipt completeness, retention, or measured cost. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-14 | in-progress | Adopted the implementation ledger and corrected stale adapter code-map paths; earlier provenance was not reconstructed. | `current change`; current protocol, core, persistence, composition, and focused checks listed in the scope table. | Implement the three delivery adapters and retain durable and live lifecycle evidence. |
| 2026-08-14 | implemented | Promoted the PostgreSQL ledger and startup binding after proving restart reconciliation against PostgreSQL. | `current change`; `test_execution_backend_ledger.py` passed two cases with zero skips against a disposable supported database. | Implement the three delivery adapters and retain governed live lifecycle evidence. |
| 2026-08-15 | implemented | Added the `BubblewrapExecutionBackend` and `VmTaskExecutionBackend` adapters over the `ExecutionBackend` protocol, narrowing only through the existing sandbox catalogs. | `current change`; `services/core-control-plane/src/fdai/delivery/execution_backend/adapters.py`; `pytest services/core-control-plane/tests/delivery/test_execution_backend_adapters.py` (20 passed). | Composition binding, the Azure Container Apps Job adapter, and governed shadow receipts remain open. |
| 2026-08-16 | in-progress | Corrected the 2026-08-14 promotion row above. It promoted "the PostgreSQL ledger and startup binding" together, but its cited evidence (`test_execution_backend_ledger.py`) only exercises the ledger. The startup binding was never promotable: no runtime path calls `bind_execution_backends`, and `load_execution_backend_registry_file` has zero callers including tests. The scope table now carries `PostgreSQL ledger` and `Startup binding` as separate rows with separate states, which also removes this document's contradiction with its own "Composition binding and governed shadow receipts remain open" note and its unchecked binding item. | `current change`; `grep -rn bind_execution_backends --include=*.py services/` matches only the definition, the `composition` facade, and `tests/composition/test_execution_backends.py`; `grep -rn load_execution_backend_registry_file` matches only the definition and the facade. | Bind both adapters through deployment composition, and give the registry loader a caller and a focused test. |

### Remaining work

- [x] Run the focused PostgreSQL ledger cases against the supported local database with no skips and retain a process-restart reconciliation receipt.
- [x] `BubblewrapExecutionBackend` and `VmTaskExecutionBackend` are implemented and focused-tested without widening their existing sandbox authority, proven by `services/core-control-plane/tests/delivery/test_execution_backend_adapters.py`.
- [ ] Bind both adapters through deployment composition and retain a focused startup and restart check.
- [ ] Give `load_execution_backend_registry_file` at least one caller and one focused test. It currently has zero of both, so the validation it performs on a server-owned registry document is unproven, and no registry document exists in `config/` or `infra/` for it to load.
- [ ] Implement and focused-test `AzureContainerAppsJobExecutionBackend` with pinned-image, idempotency, host/path validation, retry, circuit-breaker, cancel-race, receipt, and provider-retention behavior.
- [ ] Retain governed shadow receipts for identity scope, ARM reachability, duplicate start, timeout and stop races, receipt completeness, provider retention, and measured cost before promotion review.

## Related docs

| To learn about | Read |
|----------------|------|
| Eligibility, risk, and executor paths | [Execution Model](../decisioning/execution-model.md) |
| Identity and rollback ownership | [Security and Identity](../architecture/security-and-identity.md) |
| Local and deployed parity | [Runtime Parity](../deployment/dev-and-deploy-parity.md) |
| Module and composition boundaries | [Project Structure](../architecture/project-structure.md) |
