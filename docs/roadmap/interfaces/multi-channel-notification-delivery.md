---
title: Multi-Channel Notification Delivery
---
# Multi-Channel Notification Delivery

This document owns how one outbound operational alert or digest reaches **every** notification
channel an operator enabled and configured, instead of stopping at the first channel that accepts
it. It also specifies the Microsoft Teams Workflows webhook binding that replaces the retired
Office 365 connector transport.

> **Scope:** A2 operational alerts and A4 digests carried by `NotificationChannel` are in scope.
> A1 approvals (`HilChannel`) and A3 conversations (`ConversationChannelAdapter`) keep their
> existing contracts and are explicitly out of scope.
>
> **Owner boundary:** [Channels and notifications](channels-and-notifications.md) remains
> authoritative for categories, trust tiers, audience derivation, and localization. This document
> refines only the delivery semantics and the channel binding model beneath them.

## Design at a glance

Today the router walks `primary -> fallback[0] -> fallback[1]` and returns as soon as one channel
reports delivery, so a deployment with a Teams channel, a Slack channel, and an on-call mailbox
reaches only the first healthy one. Operators read that as lost notifications, not as a successful
failover.

Fan-out delivery replaces the single winner with an explicit target set, one durable delivery
record per target, independent retries, and an aggregate outcome that can report partial success.
The trust-tier gate, the redaction rules, and the escalation-on-total-failure behavior are
unchanged.

```text
notice
  -> resolve route (category -> trust tier + declared channels)
  -> compute target set (declared AND enabled AND configured AND trust-allowed)
  -> persist dispatch plan (frozen target snapshot)
  -> send to every target with bounded parallelism
  -> per-target durable state (accepted / delivered / retryable / ambiguous / abandoned)
  -> aggregate outcome + one audit entry
  -> escalate only when no target reached a human-visible channel
```

## 1. Target selection

A notification is delivered to the intersection of four independent conditions:

$$
Targets = Declared \cap Enabled \cap Configured \cap TrustAllowed
$$

| Condition | Meaning | Where it is decided |
|-----------|---------|---------------------|
| `Declared` | The route for this category names the channel. | Routing matrix |
| `Enabled` | An operator turned the channel on. | Channel binding config |
| `Configured` | Required settings and secret references resolved at startup. | Composition root |
| `TrustAllowed` | The channel declares the message's trust tier. | Adapter contract |

**Registry membership alone never grants delivery.** A channel that exists in the registry but is
absent from the route is not a target, so adding an adapter cannot silently widen the audience of a
governance digest to an operations room.

An empty target set is a configuration fault, not a quiet success. The dispatch records
`no_eligible_channels`, escalates to the human-review sink, and leaves the notice unresolved.

## 2. Channel bindings

Channel configuration moves from one implicit environment triple per vendor to a named binding map,
so one deployment can run several Teams rooms, several webhooks, or several mailboxes.

`FDAI_NOTIFICATION_BINDINGS_JSON` carries the named binding map. Secret-bearing fields name
environment variables populated by the deployment secret provider; they never contain endpoint or
credential values in the JSON itself.

```json
{
  "teams-ops-primary": {
    "kind": "teams_workflow",
    "enabled": true,
    "trust_tiers": ["a2_operational_alert"],
    "auth_mode": "workload_identity",
    "endpoint_env": "FDAI_TEAMS_OPS_PRIMARY_ENDPOINT"
  },
  "email-oncall": {
    "kind": "acs_email",
    "enabled": false,
    "trust_tiers": ["a2_operational_alert", "a4_digest"]
  }
}
```

Rules:

- **Binding ids are placeholders upstream.** Endpoint values, tenant values, and room identity live
  in deployment secret configuration, never in this repository.
- **`enabled: true` with incomplete configuration fails startup.** A half-configured channel is a
  deployment defect, not a channel to skip at send time.
- **`enabled: false` is an explicit exclusion.** It removes the channel from every target set and is
  visible in the dispatch record.
- **Trust tiers stay per binding.** A digest-only room never receives A2 paging traffic.

### Availability is not a send-time health probe

The design deliberately rejects a per-send `is_ready()` network probe. A provider outage must
surface as a failed delivery with a retry, not as a silent removal from the target set. Otherwise
the audit trail claims every enabled channel was served while an operator saw nothing.

| Condition | Effect |
|-----------|--------|
| Disabled by operator | Excluded from targets, recorded as excluded |
| Enabled, configuration invalid | Startup fails |
| Enabled, provider failing at send time | Target retained, delivery marked failed and retried |
| Binding changed after dispatch started | Frozen snapshot wins until that dispatch is terminal |

## 3. Dispatch plan and per-channel delivery

One notice produces one parent dispatch plan and one child delivery record per target.

```text
dispatch:<audit_id>            targets = [teams-ops-primary, slack-ops, email-oncall]
  delivery:<audit_id>:teams-ops-primary
  delivery:<audit_id>:slack-ops
  delivery:<audit_id>:email-oncall
```

- The target set is **frozen at dispatch creation** so a mid-flight configuration edit cannot make
  a retry diverge from the original decision.
- The stable child key is `audit_id + channel_id`, which keeps re-delivery of the same source event
  idempotent per channel.
- Sends run with **bounded parallelism**; one channel raising never cancels a sibling send.
- Only the failed children are retried, under the existing bounded-attempt and abandonment ceiling.
- After a restart, recovery resumes the non-terminal children only.
- An `accepted` child has a bounded confirmation deadline. Expiry changes it to `ambiguous` without
  an automatic resend, and the incident replay worker continues checking non-terminal plans until
  they converge.

Per-channel state:

| State | Meaning |
|-------|---------|
| `pending` | Target selected, not yet attempted |
| `sending` | Attempt leased by one worker |
| `accepted` | Provider accepted the request, human visibility unconfirmed |
| `delivered` | An independent observation confirmed the message reached the channel |
| `retryable_failed` | Definitive provider rejection or transport failure, eligible for retry |
| `ambiguous` | Acknowledgement lost after dispatch; never auto-retried |
| `abandoned` | Attempt ceiling reached |

`accepted` and `delivered` stay distinct because an HTTP success from a workflow trigger proves
acceptance of a request, not publication of a message.

## 4. Aggregate outcome

| Outcome | Condition | Follow-up |
|---------|-----------|-----------|
| `delivered_all` | Every target reached a terminal success | None |
| `partially_delivered` | At least one success and at least one non-terminal or failed target | Retry the failed children, record channel health |
| `failed_all` | No target succeeded | Escalate to the human-review sink |
| `no_eligible_channels` | Target set empty | Escalate and report a configuration fault |

Partial success is never rounded up to success. It is also never re-announced through the same A2
route, because a delivery failure notice that uses the failing route can loop; it surfaces through
channel-health metrics and the incident surface instead.

The router writes exactly one route audit entry per dispatch call. The entry includes the frozen
target list, current per-channel results, and exclusion reasons. A later workflow callback writes a
separate `notification.delivery.observed` audit entry, so the append-only audit chain never mutates a
prior routing decision.

## 5. Teams Workflows webhook binding

Office 365 connectors, including the classic Teams incoming webhook, were progressively disabled
between 2026-05-18 and 2026-05-22. The supported replacement is a Power Automate workflow started by
the **When a Teams webhook request is received** trigger, which posts a message or an Adaptive Card
into a channel or chat.

**Request contract**

- `POST` only, `application/json`.
- Body is the Adaptive Card envelope: `type: "message"` plus an `attachments` array whose entries
  carry `contentType: "application/vnd.microsoft.card.adaptive"`, `contentUrl: null`, and `content`.
- Message size ceiling is 28 KB; the adapter fails closed before the provider call rather than
  emitting a truncated card.
- More than four requests per second is throttled, so `429` uses bounded exponential backoff.

**Authentication**

| Trigger mode | FDAI use | Requirement |
|--------------|----------|-------------|
| `Anyone` | Local validation and short transition windows only | No `Authorization` header may be sent, or the request fails |
| `Any user in my tenant` | Allowed | Entra bearer token |
| `Specific users in my tenant` | Recommended for deployment | Entra bearer token for the FDAI notification identity |

Deployment binds the FDAI notification managed identity as an allowed caller and requests a token
for the public-cloud flow-service audience `https://service.flow.microsoft.com/`. The webhook URL
stays a secret reference, never a plain Terraform variable or a log value.

**Operational constraints**

- A workflow is owned by a **user**, not by the team or channel, so every FDAI-facing workflow needs
  at least one co-owner to avoid an orphaned flow when a person leaves.
- Messages post under the default Workflows bot identity; custom bot name and icon are unavailable.
- Message Card payloads render without interactive buttons, so FDAI keeps Adaptive Cards.

**Effect verification**

Until the workflow reports back, a `2xx` closes the child at `accepted` only. Confirming
`delivered` requires the workflow to call an authenticated FDAI receipt endpoint with the delivery
id and its publication result. That callback carries no message body and no webhook URL.

The receipt handler accepts only `audit_id`, `channel_id`, `publication_result`, and an optional
provider message id. It verifies `X-FDAI-Timestamp` plus an HMAC-SHA256 `X-FDAI-Signature`, rejects
stale or oversized requests, and records either `delivered` or `retryable_failed`. Prepared and
completed observation audit phases bracket that state change. The callback secret is
deployment-owned.

## 6. Boundaries this design does not cross

- A1 approvals keep the authenticated Teams path. A workflow webhook cannot verify an approver, so
  it never carries an approval decision.
- A3 conversations keep the Operator-owned channel edge described in
  [Production A3 channel runtime](production-a3-channel-runtime.md).
- Fan-out changes delivery breadth only. It never raises autonomy, relaxes redaction, or lets a
  lower-trust channel receive a higher-trust category.

## 7. Delivery sequencing

| Step | Work | Exit evidence |
|------|------|---------------|
| 1 | Matrix schema gains an explicit fan-out delivery mode with a channel list | Loader tests reject mixed or unknown modes |
| 2 | Channel bindings, enablement, and startup validation | Startup rejects enabled-but-incomplete bindings |
| 3 | Dispatch plan plus per-channel durable records | Restart recovery test resumes only open children |
| 4 | Router fan-out with bounded parallelism and failure isolation | Partial-failure and total-failure tests |
| 5 | Teams Workflows adapter with both authentication modes | Schema, size, throttle, and header tests |
| 6 | Multiple concurrent bindings wired at the composition root | Two Teams rooms plus mail receive one notice |
| 7 | Delivery callback and `delivered` promotion | Independent observation recorded in audit |

## Related docs

| To learn about | Read |
|----------------|------|
| Categories, trust tiers, audience, localization | [channels-and-notifications.md](channels-and-notifications.md) |
| A3 conversation transport and edge runtime | [production-a3-channel-runtime.md](production-a3-channel-runtime.md) |
| Durable outbound conversation replies | [durable-conversation-delivery.md](durable-conversation-delivery.md) |
| Escalation after nobody answers | [escalation-and-standing-authority.md](../decisioning/escalation-and-standing-authority.md) |
| Implementation state and evidence | [multi-channel-notification-delivery.md](../../roadmap-implementation/interfaces/multi-channel-notification-delivery.md) |
