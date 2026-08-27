# Multi-Channel Notification Delivery implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work for
[Multi-Channel Notification Delivery](../../roadmap/interfaces/multi-channel-notification-delivery.md).

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Fan-out delivery design and ownership | implemented | [Multi-Channel Notification Delivery](../../roadmap/interfaces/multi-channel-notification-delivery.md); this ledger | The design is accepted and owned. No runtime behavior changed in this transition. |
| Explicit fan-out route schema | implemented | [`matrix.py`](../../../services/core-control-plane/src/fdai/core/notifications/matrix.py), [`notifications-matrix.yaml`](../../../config/notifications-matrix.yaml), [`test_matrix.py`](../../../services/core-control-plane/tests/notifications/test_matrix.py) | A2/A4 routes use explicit `fanout` plus `channels`; legacy A1/A3 failover remains compatible. Unknown, duplicate, and mixed route shapes fail load. |
| Channel bindings, enablement, and startup validation | implemented | [`bindings.py`](../../../services/core-control-plane/src/fdai/delivery/notifications/bindings.py), [`delivery.py`](../../../services/core-control-plane/src/fdai/runtime/delivery.py), [`runtime_settings.py`](../../../services/core-control-plane/src/fdai/delivery/runtime_settings.py), [`test_bindings.py`](../../../services/core-control-plane/tests/notifications/test_bindings.py) | Named JSON bindings carry enablement and trust tiers while secret-bearing values resolve through named environment variables. Enabled incomplete bindings fail startup. |
| Dispatch plan and per-channel durable delivery | implemented | [`delivery.py`](../../../services/core-control-plane/src/fdai/core/notifications/delivery.py), [`postgres_notification_delivery.py`](../../../services/core-control-plane/src/fdai/delivery/persistence/postgres_notification_delivery.py), [`durable_notifications.py`](../../../services/core-control-plane/src/fdai/core/incident/durable_notifications.py), [`test_fanout_delivery.py`](../../../services/core-control-plane/tests/notifications/test_fanout_delivery.py) | Frozen parent plans and stable per-channel child rows preserve leases, attempt ceilings, accepted confirmation deadlines, and terminal state across re-entry. Incident checkpoints wait for terminal fan-out state. |
| Router fan-out, failure isolation, and partial outcome | implemented | [`router.py`](../../../services/core-control-plane/src/fdai/core/notifications/router.py), [`test_fanout_delivery.py`](../../../services/core-control-plane/tests/notifications/test_fanout_delivery.py) | The router sends all eligible targets with bounded concurrency, isolates channel failures, and audits aggregate outcomes plus exclusions. |
| Teams Workflows webhook transport | implemented | [`teams.py`](../../../services/core-control-plane/src/fdai/delivery/notifications/teams.py), [`test_adapters.py`](../../../services/core-control-plane/tests/notifications/test_adapters.py) | The Workflows envelope includes `contentUrl`, enforces 28 KB, bounds `429` backoff, supports unauthenticated or workload-identity modes, and reports provider success as `accepted`. |
| Delivery effect verification | implemented | [`receipt.py`](../../../services/core-control-plane/src/fdai/delivery/notifications/receipt.py), [`test_workflow_receipts.py`](../../../services/core-control-plane/tests/notifications/test_workflow_receipts.py) | A bounded HMAC-authenticated receipt handler independently promotes `accepted` to `delivered` or returns it to retryable failure and appends a separate observation audit entry. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-26 | not-started | Adopted this owner document and ledger after review found that outbound routing stops at the first successful channel, so a deployment with several enabled channels reaches only one. Recorded the fan-out target-set model, per-channel durable delivery, partial-success outcome, and the Teams Workflows webhook binding that replaces the retired Office 365 connector transport. Earlier provenance was not reconstructed. | `current change`; [`router.py`](../../../services/core-control-plane/src/fdai/core/notifications/router.py) first-success return; [`test_router.py`](../../../services/core-control-plane/tests/notifications/test_router.py) fallback assertions; [`notification_delivery.py`](../../../services/core-control-plane/src/fdai/core/incident/notification_delivery.py) audit-id-only claims; [`teams.py`](../../../services/core-control-plane/src/fdai/delivery/notifications/teams.py) connector-shaped payload | Implement the seven sequencing steps in the owner document, starting with the explicit fan-out route schema. |
| 2026-08-27 | implemented | Added explicit fan-out routes, named fail-closed bindings, frozen per-channel delivery state, bounded concurrent dispatch and retries, Teams Workflows transport, and authenticated independent publication receipts. Preserved legacy A1/A3 failover and made incident replay wait for terminal channel state. | `current change`; notification, incident checkpoint, and runtime settings tests passed 162 cases; Ruff passed the task-owned Python files; strict mypy passed the 14 changed notification source files. | Capture governed Teams and PostgreSQL runtime receipts before promoting this scope from `implemented` to `validated`. |

### Remaining work

- [x] Implement the bounded source behavior in the seven sequencing steps and retain focused
  evidence in `test_matrix.py`, `test_bindings.py`, `test_fanout_delivery.py`,
  `test_adapters.py`, and `test_workflow_receipts.py`.
- [ ] Capture a governed runtime receipt that proves a real Teams Workflow accepted a card, posted
  it, returned an authenticated publication receipt, and converged the PostgreSQL child to
  `delivered`.
