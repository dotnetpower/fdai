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
    "mode": "shadow",
    "trust_tiers": ["a2_operational_alert"],
    "auth_mode": "workload_identity"
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
- **Binding ids are bounded ASCII machine identifiers.** They contain 1-128 letters, digits, `.`,
  `_`, or `-`, start with a letter or digit, and contain no whitespace or path separator.
- **Duplicate JSON keys are invalid at every depth.** A later `mode`, `enabled`, or endpoint
  reference cannot silently replace the value that a reviewer inspected.
- **One binding map contains at most 64 entries.** Startup rejects a larger map before constructing
  adapters or readiness rows.
- **`enabled: true` with incomplete configuration fails startup.** A half-configured channel is a
  deployment defect, not a channel to skip at send time.
- **`enabled: false` is an explicit exclusion.** It removes the channel from every target set and is
  visible in the dispatch record.
- **`mode: "shadow"` renders and records without transport.** Teams and Slack shadow bindings don't
  require an endpoint or HTTP client. `mode: "enforce"` requires the provider endpoint and keeps the
  existing runtime behavior. Omitting `mode` defaults to `enforce` for backward compatibility.
- **Trust tiers stay per binding.** A digest-only room never receives A2 paging traffic.

### URL-only bootstrap

For a deployment with one Teams destination and one Slack destination, you can omit
`FDAI_NOTIFICATION_BINDINGS_JSON` and set only the endpoint variables:

| Environment variable | Default binding ids | Allowed traffic |
|----------------------|---------------------|-----------------|
| `FDAI_TEAMS_OPS_ENDPOINT` | `teams-ops-prd`, `teams-hil-prd` | A2 operational alerts and A4 digests |
| `FDAI_SLACK_OPS_WEBHOOK_URL` | `slack-ops-prd` | A2 operational alerts |

This bootstrap stores no endpoint value in the synthesized binding map. The Teams endpoint uses the
`anyone` workflow authentication mode because a URL alone provides no workload identity
configuration. It does not enable A1 approvals or A3 conversations.

Use `FDAI_NOTIFICATION_BINDINGS_JSON` when you need multiple destinations, different trust tiers,
or Teams workload identity. An explicit binding map is authoritative and is not merged with the
URL-only defaults.

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

The receipt path crosses a service boundary, so it is split by ownership:

| Stage | Owner | Responsibility |
|-------|-------|----------------|
| Public ingress | Operator Service | Verify `X-FDAI-Timestamp` plus HMAC-SHA256 `X-FDAI-Signature`, bound the body, deduplicate, and record the attempt |
| Broker handoff | Operator Service | Publish one schema-validated `notification-delivery-receipt` envelope |
| Delivery transition | Core control plane | Apply `delivered` or `retryable_failed` and append the observation audit |

`POST /runtime/integrations/notifications/delivery-receipt` accepts only `audit_id`, `channel_id`,
`publication_result`, and an optional provider message id. It rejects unsigned, stale, oversized,
or extra-field bodies, and answers `202` without asserting delivery: acceptance of a report is not
the report's effect. The callback secret is deployment-owned and never reaches the Console.

The envelope travels on the logical topic `fdai.notifications.delivery-receipts`, multiplexed over
the existing primary physical topic, and is validated against the packaged
`notification-delivery-receipt` schema on both sides. Core is the only writer of delivery state: it
promotes an `accepted` child to `delivered`, returns a reported failure to
`retryable_failed`, and brackets the change with prepared and completed
`notification.delivery.observed` audit phases. An observation whose delivery is not `accepted` is
refused and dead-lettered rather than rewriting a prior routing decision.

**Saving is a diagnostic, not an activation**

Settings > Integrations provides a bounded public-cloud save-and-test flow for setup. An Owner
can compare the current FDAI identity with a deployment-provided Microsoft 365 account hint, copy
that account, and open Power Automate before pasting the signed URL to send one fixed synthetic
card. Authentication, MFA, consent, and Team/Channel selection remain explicit user actions in the
Microsoft 365 tenant. A deployment uses a dedicated managed identity that can write only the
versioned Teams endpoint secret. The local profile uses an encrypted Operator-owned loopback record
and never writes plaintext to PostgreSQL. FDAI reads the exact saved version back, verifies the URL
digest, and only then sends the test card. Key Vault retains the previous secret version for
rollback.

**A saved and successfully tested endpoint delivers nothing on its own.** The diagnostic proves the
endpoint exists and accepts a card. Runtime delivery starts only when a deployment activates a
binding, and the runtime refuses an activated binding whose endpoint is still the seeded
placeholder.

| Mode | Activation input | Endpoint source |
|------|------------------|-----------------|
| Deployed | `enable_teams_notification_delivery` plus the `teams_notification_binding` object | Key Vault secret reference injected into the control plane with read-only authority |
| Local | `FDAI_TEAMS_NOTIFICATION_ACTIVATION` | The same encrypted Operator-owned record, read through the delivery-side store; no plaintext file or environment copy |

**The saved URL is password-equivalent and is never returned.** The binding read answers with
metadata only - `visible`, `configured`, `binding_version`, the observation time, and a `saved_at`
value when a durable Operator save record proves that exact version. Contributor, Approver, and
Owner roles see that a binding exists; nobody can read it back, and the Console never prefills the
input. An Owner replaces a binding by submitting a new URL. The durable save and test record
contains only the digest, binding version, actor, request id, provider status, and
prepared/completed metadata.

## 6. Boundaries this design does not cross

- A1 approvals keep the authenticated Teams path. A workflow webhook cannot verify an approver, so
  it never carries an approval decision. Binding parsing enforces this: a notification binding of
  any kind may declare only `a2_operational_alert` or `a4_digest`, and a binding that claims
  `a1_hil_approval` or `a3_chat_command` fails to load.
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
| 8 | Authenticated Operator ingress plus schema-validated Core consumer | Signed callback converges an `accepted` child to `delivered` through the broker |
| 9 | Explicit deployed and local activation | An activated binding delivers; a saved-only or placeholder binding does not |

## 8. Capability-state, presentation, and shadow-delivery contracts

A2/A4 channels need one more foundation layer beneath fan-out: a way to describe a binding's
availability without conflating it with health, a fail-closed rendering boundary every renderer
crosses before a vendor call, and a way to introduce a new binding with zero network transport
until it is explicitly promoted.

### 8.1 Capability-state

[`ChannelCapabilityState`](../../../services/core-control-plane/src/fdai/shared/providers/notifications/capability.py)
separates `available` (prerequisites this process could observe are complete), `enabled` (operator
preference), `configured` (startup-validated wiring), and `mode` (`ChannelMode.SHADOW` or
`ChannelMode.ENFORCE`) exactly as
[coding-conventions.instructions.md § Safety](../../../.github/instructions/coding-conventions.instructions.md#safety)
requires for every capability flag. `ready` is `available and enabled and configured`; `mode` never
raises autonomy on its own - composition still gates the fan-out target set on the other three
fields exactly as §1 already does. `to_readiness_row()` renders the same source-attributed shape
[`integration_row`](../../../services/core-control-plane/src/fdai/delivery/integration_readiness.py)
already produces, so a capability-state instance and the Settings readiness projection can never
drift into a different vocabulary for the same channel. Constructing or reading a capability state
performs no I/O; it is never a send-time health probe (§2 above). `channel_id` MUST be non-empty -
the constructor rejects an empty value rather than let a config or composition defect silently
corrupt the readiness row emitted for it.

### 8.2 Presentation boundary

[`render_presentation`](../../../services/core-control-plane/src/fdai/shared/providers/notifications/presentation.py)
is the pre-render, fail-closed boundary every renderer crosses before formatting or a provider
call. It rejects, rather than truncates or silently strips:

| Condition | Outcome |
|-----------|---------|
| Metadata names an interactive-content key (`actions`, `buttons`, `interactive`, ...), compared case-insensitively so `Actions` or `ACTIONS` is caught exactly like `actions` | Rejected - A2/A4 messages never contain approval buttons or executable links (`channels-and-notifications.md § 3`) |
| Title, body, link, or metadata **key or value** exceeds a bounded `PresentationLimits` value | Rejected - never truncated to fit; an unbounded key could smuggle an oversized payload past a check that only looked at values |
| A link `url` is not an absolute `https://` link (any other scheme, including `http://`, `javascript:`, or `data:`) | Rejected - never an executable or unencrypted link |
| Title, body, link, or metadata **key or value** matches a high-signal secret-like pattern (bearer token, API key/secret/password assignment, signed-URL query parameter, private-key header, GitHub/Slack token shape) | Rejected |

A rejection raises `PresentationRejectedError`, a `ChannelDeliveryError` subclass, so the router
treats it exactly like any other failed send and proceeds to the next fallback channel or bounded
retry - it never widens to a partial or unredacted send. The returned
`NotificationPresentationEnvelope.metadata` is a `MappingProxyType` view, not a plain `dict`, so a
renderer cannot mutate the boundary artifact after construction.

### 8.3 Shadow delivery

[`ShadowNotificationChannel`](../../../services/core-control-plane/src/fdai/core/notifications/shadow.py)
is a `NotificationChannel` that composition registers instead of a vendor adapter for any binding
still in `ChannelMode.SHADOW`. Its `send` renders the message through the presentation boundary
above and durably records the bounded envelope through an injected `ShadowDeliveryRecorder` - **no
network call is made**. `NotificationRouter` dispatches to it exactly like a live adapter and
receives `delivered=True`: the shadow channel's complete contractual obligation (render plus
durable local record) is already finished with no unconfirmed external promise outstanding,
matching constitution principle 7 ("New capabilities start in shadow mode - judge and log only, no
execution"). Promotion to `ChannelMode.ENFORCE` is an explicit composition-root change that swaps
the registered adapter; it never mutates `ShadowNotificationChannel` itself, and the router,
fan-out delivery store, and one-audit-entry invariant above are unchanged.

`ShadowDeliveryRecord.record_id` is a deterministic hash of `channel_id` plus the message's
`correlation_id`, `audit_id`, and `category` - never a random value - satisfying the pre-existing
"Adapters MUST implement idempotent `send`" contract in `channels-and-notifications.md § 5`:
`InMemoryShadowDeliveryRecorder` treats a repeated `record_id` as a no-op, and a durable production
recorder MUST do the same (an upsert keyed on `record_id`). `send` also rejects a naive
(timezone-less) `clock()` result with `ValueError` before recording, so `recorded_at` stays
comparable with every other timezone-aware timestamp this service records.

Focused coverage in
[`test_channel_foundation.py`](../../../services/core-control-plane/tests/notifications/test_channel_foundation.py)
proves: an unavailable provider still reaches a deterministic fallback with exactly one audit
entry; a shadowed provider satisfies dispatch without any network call; a rejected presentation
falls back deterministically instead of sending partial content; a repeated fan-out `dispatch()`
call for the same `audit_id` never re-sends an already-terminal target while still writing exactly
one audit entry per call; and a directly repeated `send()` call for the same
`correlation_id + audit_id + category` records exactly one entry and returns the same
`provider_message_id`.

### 8.4 Teams and Slack provider rendering

Teams and Slack use one pure provider renderer in both modes. An enforce adapter passes the message
through `render_presentation`, renders the provider payload, and then invokes its transport. A
shadow adapter runs the same two rendering steps but persists the immutable provider payload through
`StateStoreShadowDeliveryRecorder` and performs no HTTP call.

Provider-specific bounds are narrower than the shared envelope where required:

| Provider | Provider payload contract |
|----------|---------------------------|
| Teams | Adaptive Card 1.4 envelope with `fallbackText` and `speak`, a semantic severity label, centered `ExtraLarge` title, 250-character title, 3000-character body, 28 KB total payload, and a `rendering: truncated` fact when provider-specific text truncation occurs |
| Slack | Severity-colored attachment containing a Block Kit header and sections, 150-character header, 3000-character section, at most 10 facts per section, 40 KB total payload, escaped fact values, and read-only Markdown links instead of interactive action blocks |

The hierarchy follows provider-native card patterns while preserving the same canonical meaning.
Both renderers preserve `correlation_id`, `audit_id`, and sorted bounded metadata. This lets a caller
carry canonical incident ids and the `Huginn -> Forseti -> Thor -> Vidar` responsibility order
without adding vendor-specific fields to `NotificationMessage`. A stable shadow record contains the
generic envelope and the exact provider JSON bytes. Both the in-memory development recorder and the
StateStore recorder fail when the same record id carries different bounded content instead of
overwriting or silently retaining conflicting first-write evidence. The shadow boundary also
rejects a rendered provider payload above 64 KiB even when a custom renderer omits its own bound.

Slack classifies connection establishment failures as unavailable, but a timeout or other HTTP
error after dispatch as ambiguous because the provider may have received the request. The router
doesn't retry an ambiguous acknowledgement through another path.

A Slack webhook HTTP 200 produces `accepted`, not `delivered`. Only an independent publication
observation may promote provider acceptance to delivery, and the Slack capability remains in shadow
until that observation path and its promotion evidence are reviewed.

Teams and Slack rejection errors retain only the provider name and HTTP status. Provider response
bodies are discarded because they are untrusted and may reflect message content; they never enter
router audit text.

## Related docs

| To learn about | Read |
|----------------|------|
| Categories, trust tiers, audience, localization | [channels-and-notifications.md](channels-and-notifications.md) |
| A3 conversation transport and edge runtime | [production-a3-channel-runtime.md](production-a3-channel-runtime.md) |
| Durable outbound conversation replies | [durable-conversation-delivery.md](durable-conversation-delivery.md) |
| Escalation after nobody answers | [escalation-and-standing-authority.md](../decisioning/escalation-and-standing-authority.md) |
| Implementation state and evidence | [multi-channel-notification-delivery.md](../../roadmap-implementation/interfaces/multi-channel-notification-delivery.md) |
