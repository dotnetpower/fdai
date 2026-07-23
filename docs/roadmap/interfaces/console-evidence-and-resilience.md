---
title: Console Evidence and Resilience
---

# Console Evidence and Resilience

This document owns the operator console contracts for evidence provenance, localization,
stream recovery, durable replay, and Architecture-map resilience. The conversational tool and
RBAC contract remains in [operator-console.md](operator-console.md).

## Navigation context

Selecting an Activity Bar domain opens its Explorer and navigates to the first visible panel under
the operator's local order and visibility preferences. This navigation remains active when the
Command Deck is closed or floating; a full-workspace Deck closes before the route changes.

The shared page title renders the domain and panel labels when they differ, including
`Overview / Dashboard`. A domain root whose panel title repeats the domain label and a standalone
utility keep a single title.

Every data-bearing card across the console drills down. The complete card surface uses a native
keyboard-accessible link to the narrowest analytical or filtered-evidence destination that owns the
datum. A card with independent controls exposes a visible primary detail link instead. Dashboard
posture, evidence metadata, measured or unavailable outcomes, distribution legends, attention facts,
vertical statistics, and collapsed operational counts follow the same rule. Section headings and
explanatory copy remain non-interactive. An unavailable value still opens its owner view so the
operator can see which source or sample is missing. Structural groups, forms, editors, and bounded
tools without a detail destination use panel or section semantics rather than card styling or names.
Unavailable metric cards use a subdued whole-surface background, no elevation shadow, and compact
muted value text so they don't read as measured results. They remain focusable drill-down links and
retain a complete-border focus or hover cue; the visual treatment never sets disabled semantics.
The console card contract test checks shared KPI destinations, rejects nested whole-card links,
requires raw data cards to expose a link or explicit detail control, and blocks structural card names.

Operating Outcomes publishes the selected metric, current value, baseline, measurement window,
sample size, confidence, and source provenance as a bounded Command Deck view snapshot. It includes
vertical records only for Auto-resolution, the one metric view that renders that measured
breakdown. The narrator receives only rendered evidence facts; it does not infer unavailable values
or replace the route's authoritative source. Snapshot headlines use the same metric formatter as the
visible cards, and auto-resolution values retain ratio semantics so displayed percentage claims can
be checked at the same rounded precision the operator sees.

Each Operating Outcomes route keeps a metric-specific analysis surface. Auto-resolution shows its
observed event and auto-resolved record counts, vertical rates, and guard context. Human touchpoints,
MTTR, change lead time, and cost per resolved event each reserve their own analysis and breakdown
sections. When the read projection does not provide touchpoint types, latency percentiles, delivery
stages, or cost composition, the section renders unavailable instead of reusing an unrelated vertical
table or deriving values in the browser. Cost views also state that displayed amounts use standard
prices and can differ from billed amounts after discounts, commitments, credits, taxes, exchange
rates, and provider billing adjustments.

## Loading presentation

Every route, panel, and bounded content region renders a skeleton from its first loading frame.
The shared skeleton replaces spinner-only and text-only waits, while a route can provide a shape
that preserves its final layout dimensions. Dashboard uses a posture block followed by metric,
distribution, attention, and vertical placeholders so loading does not collapse the report. One
screen-reader status announces loading; decorative blocks stay hidden. Shimmer stops under reduced
motion while the static skeleton remains visible.
The shared fallback uses heading, summary-card, and body-panel placeholders; an owned route shape
replaces that fallback only when it preserves a more accurate final layout.

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
`GET /stewardship`. The console projects that source read-only. Its Handover form can submit
structured person or group assignments to the separate ingestion boundary, but it cannot apply the
map or hold Git credentials. Draft PR creation and signed merge processing remain on the
ingestion/GitOps boundary, and the returned draft includes the persisted idempotent PR receipt.
The browser renders a receipt URL as a link only when it is an absolute HTTPS URL without embedded
credentials; otherwise it displays the PR reference as non-clickable text.
Content upload keeps the API bearer token only for same-origin ingestion proxy targets. A
cross-origin direct-upload target receives the content headers but never the read API credential.

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
