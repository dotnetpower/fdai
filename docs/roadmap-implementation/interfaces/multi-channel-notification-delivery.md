# Multi-Channel Notification Delivery implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work for
[Multi-Channel Notification Delivery](../../roadmap/interfaces/multi-channel-notification-delivery.md).

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Fan-out delivery design and ownership | implemented | [Multi-Channel Notification Delivery](../../roadmap/interfaces/multi-channel-notification-delivery.md); this ledger | The design is accepted and owned. No runtime behavior changed in this transition. |
| Explicit fan-out route schema | not-started | [`matrix.py`](../../../services/core-control-plane/src/fdai/core/notifications/matrix.py), [`notifications-matrix.yaml`](../../../config/notifications-matrix.yaml) | The loader parses `primary` plus `fallback` only. No delivery-mode field and no channel list exist yet. |
| Channel bindings, enablement, and startup validation | not-started | [`delivery.py`](../../../services/core-control-plane/src/fdai/runtime/delivery.py), [`runtime_settings.py`](../../../services/core-control-plane/src/fdai/delivery/runtime_settings.py) | The registry builder returns an empty registry unless the single email endpoint is configured, and no per-binding enablement record exists. |
| Dispatch plan and per-channel durable delivery | not-started | [`notification_delivery.py`](../../../services/core-control-plane/src/fdai/core/incident/notification_delivery.py), [`durable_notifications.py`](../../../services/core-control-plane/src/fdai/core/incident/durable_notifications.py), [`postgres_incident_notification.py`](../../../services/core-control-plane/src/fdai/delivery/persistence/postgres_incident_notification.py) | Claims are keyed by notification audit id only, so one channel cannot be retried or recovered independently. |
| Router fan-out, failure isolation, and partial outcome | not-started | [`router.py`](../../../services/core-control-plane/src/fdai/core/notifications/router.py), [`test_router.py`](../../../services/core-control-plane/tests/notifications/test_router.py) | `dispatch` returns on the first `delivered=True` receipt and reports one `delivered_channel_id`. Existing tests assert that first-success behavior. |
| Teams Workflows webhook transport | not-started | [`teams.py`](../../../services/core-control-plane/src/fdai/delivery/notifications/teams.py), [`test_adapters.py`](../../../services/core-control-plane/tests/notifications/test_adapters.py) | A connector-era Adaptive Card sender exists with focused tests, but it omits the required `contentUrl` field, has no authentication mode, no size or throttle bound, and is not bound in any runtime registry. |
| Delivery effect verification | not-started | [`_http.py`](../../../services/core-control-plane/src/fdai/delivery/notifications/_http.py) | Any `2xx` is reported as delivered. No independent observation separates provider acceptance from channel publication. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-26 | not-started | Adopted this owner document and ledger after review found that outbound routing stops at the first successful channel, so a deployment with several enabled channels reaches only one. Recorded the fan-out target-set model, per-channel durable delivery, partial-success outcome, and the Teams Workflows webhook binding that replaces the retired Office 365 connector transport. Earlier provenance was not reconstructed. | `current change`; [`router.py`](../../../services/core-control-plane/src/fdai/core/notifications/router.py) first-success return; [`test_router.py`](../../../services/core-control-plane/tests/notifications/test_router.py) fallback assertions; [`notification_delivery.py`](../../../services/core-control-plane/src/fdai/core/incident/notification_delivery.py) audit-id-only claims; [`teams.py`](../../../services/core-control-plane/src/fdai/delivery/notifications/teams.py) connector-shaped payload | Implement the seven sequencing steps in the owner document, starting with the explicit fan-out route schema. |

### Remaining work

- [ ] Add an explicit fan-out delivery mode with a declared channel list to the routing matrix
  schema, and prove that the loader rejects unknown or mixed modes.
- [ ] Add named channel bindings with per-binding enablement and trust tiers, and prove that an
  enabled binding with incomplete configuration or an unresolved secret reference fails startup.
- [ ] Persist one dispatch plan with a frozen target snapshot plus one durable record per target,
  keyed by `audit_id` and `channel_id`, and prove that restart recovery resumes only open children.
- [ ] Send to every target with bounded parallelism and failure isolation, and prove that one
  channel raising neither cancels a sibling send nor suppresses the aggregate result.
- [ ] Report `delivered_all`, `partially_delivered`, `failed_all`, and `no_eligible_channels` in the
  routing result and the single audit entry, with the excluded channels and their reasons.
- [ ] Implement the Teams Workflows adapter with the documented Adaptive Card envelope including
  `contentUrl`, the 28 KB ceiling, bounded `429` backoff, and both authentication modes, and prove
  that no `Authorization` header is sent in the unauthenticated trigger mode.
- [ ] Bind at least two concurrent notification channels at the composition root and prove that one
  notice produces one delivery record per bound channel.
- [ ] Record `delivered` only from an independent observation of channel publication, and keep a
  provider `2xx` at `accepted` until that observation exists.
