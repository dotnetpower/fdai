---
title: Live and Audit Presentation
---
# Live and Audit Presentation

This document defines the read-only presentation contract for the Live cockpit and Audit
record-review workspace. The static specimens guide layout, not operational facts or authority.

> **Boundary:** Sample stories never enter the runtime. Missing measurements, decisions,
> independent observations, and integrity checks remain explicitly unavailable or not verified.

## Design at a glance

Both routes use a 1232 px desktop content grid. Live keeps a chronological card workspace;
Audit keeps a bounded record rail beside the selected record. Neither route truncates
loaded evidence merely to match the smaller synthetic specimen.

## Live cards and controls

- Control cards show a 3 px meter for the recorded pipeline stage, not elapsed time or verified
  effect. Source-read cards have no invented stage percentage.
- Grid and List share card content, selection, and right-side details. Lifecycle updates do not
  reorder a retained event. Status text remains visible without relying on color or animation.
- KPI cards use shared typography, a compact SVG gate ring, and tier tracks. Throughput still
  distinguishes control-stage messages from source reads; [metric denominators](live-cockpit-metrics.md)
  do not change to imitate synthetic values.
- Fullscreen expands only the activity workspace. Native fullscreen and the explicitly labeled
  expanded fallback preserve keyboard access, Escape dismissal, and focus restoration.
  Details and tooltips render within the active fullscreen element.

## Repeatable Sample comparison

Replay Sample restores twelve representative stories with approval, automatic decision,
held, denied, and failed examples. Story resource and action identifiers come from the
declared catalogs; localized display labels apply only in explicitly selected Sample mode.
The synthetic 60-second metric warmup retains 180 modeled loops independently of the card pool.
Subsequent Sample loops start twice per second and distribute stages across 2.4, 3.4, or 4.8
seconds for T0 (deterministic rules), T1 (similarity reuse), or T2 (grounded reasoning).
Replay cancels old timers and queued frames, resets measurements
and selection, and preserves the current filter. It never reads or writes runtime evidence.

## Audit record review

At 1440 x 900, the review workspace is 1232 x 620 px with a 290 px record rail.
The rail and detail pane scroll within the bounded desktop workspace, so selecting a later
record does not leave its details above the page viewport. All loaded rows remain available,
and pagination still appends rather than replacing records. Narrow layouts stack the panes
and bound the record list while allowing detail content to follow normal page scrolling.

Context facts, query controls, and record details keep visible provenance and search-scope
explanations. Recorded hashes alone do not verify ledger integrity; source-only evidence
does not become an independently verified effect.

## Related docs

| To learn about | Read |
|----------------|------|
| Measurement semantics | [Live cockpit metrics](live-cockpit-metrics.md) |
| Source and evidence boundaries | [Console evidence and resilience](console-evidence-and-resilience.md) |
| Delivery and verification | [Implementation ledger](../../roadmap-implementation/interfaces/live-audit-presentation.md) |
