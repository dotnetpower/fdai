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
- A Service Worker can be registered.
- Web Locks can elect one principal-scoped live-stream leader.

FDAI never requests permission on page load. Selection requires an explicit user gesture. The
preference is keyed by the authenticated principal and stored in the current browser profile.
Same-document custom events and cross-tab storage events synchronize Settings and header controls.

Persisted selection and receiver health are separate states. A worker or leader failure leaves the
selection checked while the status becomes retryable. A browser without a required API reports the
channel unavailable instead of ready.

## Event admission

The selected leader keeps authenticated `GET /live/stream` connected while the tab is backgrounded.
Only `runtime-observed` approval, denial, and failure frames are eligible. Replay,
synthetic-development, unknown-source, and routine successful frames are rejected.

Notifications contain localized generic text, a bounded opaque event tag, a claim token, and a
same-origin Audit link filtered by the server-provided correlation identifier. A live frame does
not establish canonical Incident membership: approval and failure events can have audit history
without an Incident. Audit remains an authoritative-only route even when the tab prefers Sample.
Notifications contain no raw error, resource identifier, approval control, or execution link.

## Delivery ledger

The principal-scoped browser ledger:

- serializes claim, display, acknowledgement, and release writes through one short-lived Web Lock
  shared by same-origin tabs;
- suppresses one event tag for five minutes;
- limits display to five notifications per minute;
- retains at most 32 receipts for seven days;
- records display only after `showNotification()` resolves; and
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

Navigation admits only the scoped Audit route and the legacy Incident route. Previously displayed
notifications retain their original Incident destination. When that live Incident selection is
unavailable, **View related audit history** opens the same correlation in Audit without inventing
an Incident, changing filters, or claiming operational success. Sample selections do not expose
this live-evidence recovery link.

## Failure and recovery

Service-worker registration and readiness each have a ten-second deadline. Timeout, token
generation failure, storage failure, and Web Locks acquisition failure become explicit unavailable
or retry states. None silently enables delivery.

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
