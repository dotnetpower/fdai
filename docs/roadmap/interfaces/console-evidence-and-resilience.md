---
title: Console Evidence and Resilience
---

# Console Evidence and Resilience

This document owns the operator console contracts for evidence provenance, localization,
stream recovery, durable replay, and Architecture-map resilience. The conversational tool and
RBAC contract remains in [operator-console.md](operator-console.md).

## Localization boundary

The SPA resolves display locale from the operator preference. Reusable strings come from the main
English-source catalog or a complete route-local English/Korean pair with mandatory English
fallback. Static key coverage, catalog parity, route fallback tests, and the console suite prevent
untranslated display text from returning.

Localization changes presentation labels only. Machine values, workflow ids, serialized records,
provider payloads, and validation results remain unchanged.

## Durable request replay

A completed request is replayed only when principal, conversation, idempotency key, and request
content match. The stored terminal assistant payload is returned without repeating evidence
retrieval, narration, or post-turn review. Changed content or another conversation under the same
key is a conflict. JSON, SSE, and cross-transport retries share this terminal payload.

An optional incident conversation binding carries a bounded incident id, correlation id, and
allowlisted Pantheon agent. The browser and server enforce the same bounds. Invalid persisted
bindings are discarded without deleting the conversation. Agent activity describes bounded
historical audit evidence; missing activity does not prove that an agent has no current task.
A new ephemeral conversation does not query durable history before its first operator turn creates
the server record, so a normal first-open state is not reported as a missing-history error.

## Verified evidence

Read-source provenance, ontology browse, cross-screen operational, and inventory answers are
rendered deterministically from typed evidence. Ontology browse requires a target and browse verb,
forwards only allowlisted identity fields with prompt values up to 256 characters, and renders
duplicate or malformed counts and selections unavailable.

Operational evidence remains one of `matched`, `summary`, `ambiguous`, `none`, or `unavailable`.
For a collection summary request, `summary` renders the bounded matching set immediately without
requiring a single incident selection. Model prose cannot change the selected incident, search
scope, supported cause, collection membership, or absence claim. A source with
`availability=unavailable` never reports `reachable=true`; unconfigured or unprobed sources use
`reachable=null`.

The Trace route publishes `correlation_id`, `load_status`, and an actionable `load_error` when
present, including during an error render. The server may use that correlation only as a selection
hint and rechecks it against the authorized read model before returning operational evidence.
Trace keeps correlated audit rows in sequence order, represents activity without a pipeline stage
as `stage: null`, and derives `terminal_stage` from the last named stage.
When no citation-grounded RCA exists, deterministic verification may quote a recorded failure or
escalation reason from that audit evidence, but labels it as an observation rather than a complete
root-cause conclusion.

Each manifest route has one owner. The SPA strips query and fragment components, matches exact
paths or descendants on a path-segment boundary, and selects the longest owner. Similar prefixes do
not inherit ownership. A panel remains `unknown` when any owned route is absent from the manifest;
only explicitly source-independent panels omit source status.

The production read API loads and validates the operational ownership map before registering
`GET /stewardship`. The console projects that source read-only; draft PR creation and signed merge
processing remain on the separate ingestion/GitOps boundary.

## Stream recovery and authentication

Authenticated live, agent, and provisioning SSE readers cancel after 45 seconds without bytes,
including keepalive comments, then use bounded reconnect. Provisioning also cancels its reader when
event delivery fails. Agent-stream `401` waits for full-screen login recovery; `403` reconnects so a
new App Role can take effect without a page reload.

The agent stream receives health-derived `agent.runtime-state` heartbeats through the same shared
stage transport in local and deployed profiles. A heartbeat establishes current runtime observation
for a live agent but isn't classified as work. Missing or malformed health frames never promote a
declared subscriber binding into an observed state. Each read API replica uses an instance-scoped
consumer group so every connected console receives the complete heartbeat set.

The Command Deck rejects a complete or pending SSE frame above 256 KiB before accumulating `data:`
lines or parsing JSON, then uses the deterministic interrupted-stream fallback. Correlation-filtered
action progress treats a terminal audit frame as completion, reports the 120-second deadline as a
timeout, and propagates other authentication or transport failures.

Before opening console data, bootstrap verifies the principal through authenticated
`GET /iam/self`. Transport failure keeps data closed and offers access-check retry and sign-in. It
does not start an automatic redirect because an unreachable read API would cause a redirect loop.

## Architecture-map resilience

The Architecture route leads with inventory provenance and factual counts. The default isometric
map shows containment and resource shape; top and front views are optional. Simple projections
reflow three or more resource groups into at most two columns, while authored nested layouts keep
their supplied geometry. Selection updates the canonical deep link without reloading inventory and
exposes directional relationships before technical identifiers.

Labels avoid collisions, fit long names, and scale from 13 px to 20 px as the operator zooms; the
selected label may reach 22 px. Zoom steps are reciprocal, colors follow the console theme, and a
keyboard-accessible resource and relationship index is equivalent to the filtered canvas. Pointer
targets are at least 44 px and include containment boundaries. Truncated snapshots show an explicit
partial-inventory notice.

A subscription-scoped cached snapshot renders immediately. Expired or change-invalidated snapshots
are marked stale while a background refresh runs. The browser polls only until the read API
atomically promotes the completed refresh, never upgrades the server freshness verdict, and retries
transient failures with bounded 2-to-30-second backoff while the stale graph remains usable.

## Verification

- Catalog parity and route-local fallback tests cover localization.
- Replay tests cover JSON, SSE, and cross-transport idempotency.
- Provenance tests cover unavailable, unknown, malformed, and route-owner states.
- Stream tests cover inactivity, authentication classification, frame limits, and action timeout.
- Architecture tests cover layout, selection, accessibility, cache freshness, and bounded polling.
