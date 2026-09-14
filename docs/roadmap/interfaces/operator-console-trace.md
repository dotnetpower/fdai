---
title: Operator Console Trace
---

# Operator Console Trace

The Trace route reconstructs one correlation from durable audit evidence without replaying the
recorded work. It keeps recent discovery, decision-first summaries, ordered stages, exact
provenance, and responsive evidence review in one read-only Console workspace.

> This focused owner document was extracted from
> [FDAI Console Conversations](operator-console.md). It owns Trace reconstruction and presentation,
> not audit storage, incident state, approval, or execution authority.

## Design at a glance

You can open Trace from an audit-backed activity or enter a correlation id directly. The route
uses the existing bounded Audit page to discover recent correlations and the selected Trace
response to describe one exact correlation. Browser grouping helps navigation only. It cannot
raise completeness, create evidence, or grant authority.

Trace keeps the summary, correlation lookup, ordered stage rail, selected evidence detail,
action-attempt lifecycle, and complete audit timeline in one bounded workspace across idle,
loading, ready, empty, unavailable, and error states. Selecting a stage changes presentation only.
Localized stage, action, status, and time labels retain the canonical raw values and exact
timestamp for evidence review.

## Evidence invariants

Trace applies these checks before presenting evidence:

- The response correlation id exactly matches the requested correlation.
- Every audit sequence is a positive integer before it becomes an ordered stage or evidence link.
- Human approval stages use only explicit request, decision, approved, rejected, timeout, or
  resolution records. Delivery, reminder, and notification events cannot imply approval.
- The server joins executor records through the correlated event id and probes one record beyond
  the 500-record limit. An over-limit Trace becomes unavailable instead of silently truncating.
- When both `pipeline_stage` and `stage` are recorded, they identify the same stage.
- Top-level and workflow action attempt numbers are positive and agree when both are present.
- Nullable stage, decision, reason, and terminal-stage fields are either `null` or non-empty.
- Every joined step preserves its source event id and source correlation id. The requested
  correlation does not overwrite a joined row's recorded provenance.
- Every step preserves its entry hash and previous entry hash. The route displays these references
  without claiming to verify the complete audit ledger chain.
- Event id, entry hash, and previous entry hash remain required because the audit ledger stores
  them as non-null provenance.
- Optional stage, decision, reason, action, execution, outcome, workflow, and attempt fields are
  validated when present. Invalid values cannot become "Not recorded."
- The PostgreSQL boundary accepts each audit `entry` only as a JSON object.
- Every step preserves the recorded actor. The stage rail uses a readable label, while evidence
  detail retains the canonical action kind and actor.
- The browser checks Trace kind, action-attempt count, effect-observation count, and root-cause
  evidence against the ordered steps before using those values in summaries.
- Server metadata identifies `operator-audit-log` as the selected Trace source. An unknown source
  token cannot appear as verified provenance.

Invalid, contradictory, incomplete, or oversized evidence produces an explicit unavailable state.
The route does not choose a convenient producer field or downgrade malformed evidence to absence.

## Recent discovery

The Console reuses `GET /audit?limit=500` as its recent discovery sample. It groups exact
correlation ids, orders them by their latest sequence, and displays at most 25 correlations.
Sentinel values such as `None` and `null` are excluded.

`next_cursor` tells the route that older audit records exist. In that case, the route labels the
result as a recent sample instead of complete history. Each discovery row can show its latest
actor, action kind, decision, mode, unambiguous target, and sampled Incident or root-cause
evidence. These flags describe sampled rows only. They do not guarantee that another destination
projection is available.

Type filters cover all, read, decision or action, and other correlations. A filter with no matches
shows an explicit empty state instead of an unexplained blank list.

## Selected Trace summary

`GET /audit/{correlation_id}/trace` remains authoritative for the selected detail. In addition to
ordered steps, the response provides:

- Trace kind and canonical source authority.
- Completeness and first and last recorded time.
- Latest sequence, activity stage, action kind, actor, decision, outcome, and mode.
- Terminal named stage.
- Exact target when one target is unambiguous, plus the unique target count.
- Action-attempt and independent effect-observation counts.
- Recorded Incident and root-cause evidence presence.

The first four summary cards answer response decision, operational effect, completeness, and
terminal-versus-latest activity. They distinguish not applicable, not recorded, pending, failed,
and independently observed states. A technical read with no action identity becomes one compact
"No action path" statement and does not invent proposal, approval, dispatch, or effect evidence.

Copy actions preserve the canonical correlation, event, and hash values. They show bounded success
or failure feedback. Related Incident, Audit, and root-cause destinations state whether supporting
evidence was recorded before the operator follows the link.

## Responsive and accessible presentation

At wide widths, the route uses a 1,320 pixel reading measure, a 276 pixel stage rail, and one
toolbar row. At constrained desktop widths, the two-column workbench remains intact while the
surrounding context reflows.

At 390 and 320 pixels:

- Decision summaries use a 2 by 2 grid.
- Detailed context starts collapsed.
- Copy and refresh actions each keep a full readable row.
- Related evidence links use a bounded two-column grid.
- The workbench starts before two viewport heights.
- Interactive controls retain at least 44 pixels of height.
- Long canonical action kinds and the compact stage path wrap inside the workbench.
- The exact audit table keeps semantic table markup and reflows each record into labeled vertical
  facts without horizontal scrolling.
- The read-only explanation stacks below its title.

The stage rail supports keyboard selection and visible focus. Dark mode, forced colors, reduced
motion, 200 percent equivalent width, and user text spacing preserve the same evidence meaning.

## Related docs

| To learn about | Read |
|----------------|------|
| Delivery status, validation, and remaining evidence | [Trace implementation ledger](../../roadmap-implementation/interfaces/operator-console-trace.md) |
| Parent conversation and Console boundaries | [FDAI Console Conversations](operator-console.md) |
| Audit, CLI, approval, and ontology wire contracts | [Operator Console Data and Wire Contracts](operator-console-wire-contracts.md) |
| Incident and delivery evidence resilience | [Console Evidence and Resilience](console-evidence-and-resilience.md) |
