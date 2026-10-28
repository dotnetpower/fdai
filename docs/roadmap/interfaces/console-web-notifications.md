---
title: Console Web Notifications
---

# Console Web Notifications

This document owns the client-local `console-web` notification channel, its personal selection
surface, browser capability gates, local delivery ledger, and notification-click acknowledgement.
It does not add a Core notification adapter, a server-side subscription store, or execution
authority.

## Scope and ownership

`console-web` is an authenticated Console convenience channel for the signed-in principal in one
browser profile. Settings > Integrations is the canonical selection surface. The header control is
a synchronized shortcut to the same preference.

Existing Teams, Slack, email, webhook, paging, and SMS A2/A4 bindings remain
organization-managed channel-as-audience routes. They are read-only integration evidence in this
personal Settings section. A later personal channel is selectable only after Operator projects a
verified active endpoint for the principal and its delivery path consumes the same selection.

The browser channel is informational. It never grants approval or execution authority and its
local receipts never satisfy Core `notification.delivery.observed`.

## Capability and selection

The channel is available only when all of these conditions hold:

- The page is in a secure context.
- The Notifications API is available.
- A Service Worker can be registered, or a page-session receiver has passed an explicit display check.
- Web Locks can elect one principal-scoped live-stream leader.

FDAI never requests permission on page load. Selection requires an explicit user gesture. The
preference is keyed by the authenticated principal and stored in the current browser profile.
Same-document custom events and cross-tab storage events synchronize Settings and header controls.

Persisted selection and receiver health are separate states. A worker or leader failure leaves the
selection checked while the status becomes retryable. A browser without a required API reports the
channel unavailable instead of ready.

### Page-session receiver

When worker registration or activation fails, an explicit selection may test the granted native
Notifications API with one clearly labeled connection notification. Only its `show` event qualifies
the page-session receiver. The header and Settings identify this as session delivery: the Console
page must remain open. A tab-session capability receipt may survive reload, but it never grants
permission or selects the channel for another principal.

Both receivers retain the same event admission, Web Locks, principal-scoped selection, rate limit,
claim fencing, and closed click target. A native click focuses its originating page and navigates
through the same token-bound acknowledgement fragment. It cannot reopen a closed page.

Native display tags use the first 128 bits of the canonical event tag's SHA-256 digest as 32
hexadecimal characters, because some native backends do not display notifications with long tags.
The original event tag and claim token remain unchanged in notification data and the delivery
ledger. This changes only the platform display key, never event identity or authority.

This boundary rejects three shortcuts: a permission flag alone is not receiver readiness, an API
constructor alone is not display confirmation, and a connection test is not an operational alert
or a delivery-ledger receipt. Failure of both receivers leaves selection unavailable or retryable.

## Event admission

Analyzer Findings also arrive through authenticated, paginated `GET /findings`, independently of
Incident creation. This derived feed retains distinct signals on one Resource and does not inherit
Sample data. The foreground shows a count, transient notice, and evidence inbox. The selected
background receiver uses a stable Finding identity and notification version for new/reopened
Findings, increased severity, and verified recovery. Repeated polls and reloads do not create new
alerts. Rate-limited updates remain pending and visible in the inbox, including a fault that recovers
before its browser notification can be displayed. A zero count is not proof of detection coverage.

Finding links open the exact record in live Detection coverage. The worker and session receiver
allow this closed destination in addition to Audit and legacy Incident recovery. Bodies remain
generic, selection and leadership remain principal-scoped, and local history errors remain visible.
This feed is the analyzer domain's projection, not a claim that every rule or compliance domain has
joined a single cross-domain Finding store.

The selected leader keeps authenticated `GET /live/stream` connected while the tab is backgrounded.
Only `runtime-observed` approval, denial, and failure frames are eligible. Replay,
synthetic-development, unknown-source, and routine successful frames are rejected.

Notifications contain localized generic text, a bounded opaque event tag, a claim token, and a
same-origin link. An approval alert opens the live approval queue. Denial and failure alerts open
an Audit link filtered by the server-provided correlation identifier. A live frame does not
establish canonical Incident membership: approval and failure events can have audit history
without an Incident. Both routes stay authoritative-only even when the tab prefers Sample.
Notifications contain no raw error, resource identifier, approval control, or execution link.

## Delivery ledger

The principal-scoped browser ledger:

- serializes claim, display, acknowledgement, and release writes through one short-lived Web Lock
  shared by same-origin tabs;
- suppresses one event tag for five minutes;
- limits display to five notifications per minute;
- retains at most 32 receipts for seven days;
- records display only after `showNotification()` resolves or a native notification emits `show`; and
- records acknowledgement only for a matching tag and unpredictable 128-bit claim token.

Legacy entries retain the `at` timestamp alias for rolling-version duplicate suppression. A
tokenless legacy entry cannot create a new acknowledgement. Display completion and failed-send
release require the current claim token, so a stale callback cannot mutate a replacement claim.

The visible status is derived from the newest retained delivery: `Ready`, `Sent`, or
`Sent + opened`. Opening an older notification cannot make a newer unacknowledged notification
appear acknowledged. A valid click that arrives before the display callback atomically records
both timestamps, and the later display write preserves the monotonic result.

## Click acknowledgement

Every notification click navigates the chosen same-origin Console window through a closed
`#fdai-notification-ack` fragment. Fragments do not enter HTTP requests or referrers. The Console
validates and removes the fragment on mount and on `hashchange`, then locates exactly one matching
principal ledger by tag and token. This lets a notification created for one account converge after
the browser switches accounts without attributing it to the active principal. Ambiguous matches
fail closed.

The service worker considers controlled window clients inside its registered scope only. It never
navigates an unrelated same-origin window outside a subpath deployment. It focuses the window
returned by navigation; if navigation cannot produce a window, it opens the same validated target.
It never treats a fire-and-forget `postMessage()` call as acknowledgement delivery.

Navigation admits only the scoped Approvals, Audit, and legacy Incident routes. Previously displayed
notifications retain their original Incident destination. When that live Incident selection is
unavailable, **View related audit history** opens the same correlation in Audit without inventing
an Incident, changing filters, or claiming operational success. Sample selections do not expose
this live-evidence recovery link.

## Failure and recovery

Service-worker registration and readiness each have a ten-second deadline. A page-session display
check has a five-second deadline and runs only during an explicit selection when no verified
receiver is available. Rejected, timed-out, or unobserved checks cannot mark the channel ready.
Permission is checked again before persisting selection. A native display failure invalidates its
session capability receipt, and retry verifies the receiver again. Token generation, required
storage, and Web Locks failures remain explicit unavailable or retry states.
Returning focus with unchanged permission preserves a failed receiver's retry state rather than
starting another automatic worker attempt. Session failures log only closed reason strings,
without notification content, identifiers, or claim tokens.

The current implementation has no Push API subscription or server-side subscription store. A
fully closed browser receives no notification. Closed-browser Web Push requires a separately
authenticated service, encrypted subscription storage, revocation, CSRF protection, and delivery
audit.

## Verification

Focused tests cover source admission, permission and capability gates, principal isolation,
deduplication, rate limits, retention, legacy compatibility, claim fencing, out-of-order callbacks,
cross-account acknowledgement, ambiguous token rejection, fragment parsing, worker navigation, and
leader failures. Console build and bundle-budget checks cover the loaded and lazy presentation
paths. Browser checks cover Settings/header synchronization, same-document fragment handling,
English and Korean labels, 320-pixel layout, and 200% text enlargement.

## Related docs

| To learn about | Read |
|----------------|------|
| Delivery state and remaining work | [Console Web Notifications implementation ledger](../../roadmap-implementation/interfaces/console-web-notifications.md) |
| Shared channel categories and organization routing | [Channels and Notifications](channels-and-notifications.md) |
| Console module ownership | [Operator Console Module Map and Boundaries](operator-console-module-map.md) |
| Console evidence behavior | [Console Evidence and Resilience](console-evidence-and-resilience.md) |
