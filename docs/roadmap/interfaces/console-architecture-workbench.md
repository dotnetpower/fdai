---
title: Console Architecture Workbench
---
# Console Architecture Workbench

This document defines the read-only Governance Architecture workbench. It owns bounded Landscape,
Resource focus, Network path, Impact presentation, and generated SVG geometry without changing
inventory evidence or execution authority.

> **Authority boundary:** Presentation coordinates, grouping, filtering, and selection are local
> view operations. They do not create Resources or relationships, prove reachability, or grant
> approval, mutation, or execution authority.
>
> **Evidence boundary:** The Operator API owns the returned inventory page, snapshot, freshness,
> completeness, and typed links. A bounded presentation never becomes a complete tenant claim.

## Design at a glance

The workbench uses progressive disclosure:

1. **Landscape** summarizes returned Subscription and Resource Group containment.
2. **Resource focus** opens the smallest reported containing scope around one selected Resource.
3. **Network and Impact** reuse the same orthographic SVG while preserving their own evidence
   semantics.

Search continues to use the complete returned inventory page even when the map shows a smaller
presentation.

## Landscape and Resource focus

The default Landscape derives Subscription, Resource Group, VNet, and Subnet containment from
canonical Resource types, `parent_id`, and reported `contains` links. It does not require
presentation coordinates from the API.

- At most 8 Resource Group summaries are shown, ranked by returned descendant count with stable
  name and identity tie-breakers.
- Subscription remains a neutral outer boundary.
- Each Resource Group becomes a compact summary card with descendant and cross-scope relationship
  counts.
- If no Resource Group is returned, at most 8 stably ordered actual Resources plus required
  ancestors are shown.
- Incoming summary coordinates and dimensions are discarded before compact placement.
- Visible counts and accessible names use the same localized summary.

Resource focus retains reported ancestor boundaries and direct relationships, then fills the
smallest containing scope with at most 36 type-diverse returned records. Direct children and
relationship endpoints consume that budget before unrelated scope filler. Reservation spans the
complete returned page and excludes the selected Resource and already-required ancestors.

When direct context exceeds the focus budget, the coverage summary reports the number of returned
direct link records outside the map. The Inspector still lists the complete returned direct
relationship set.

## Geometry and relationship integrity

The Console creates finite presentation geometry before rendering. Boundary classification uses
canonical Resource types and reported containment rather than optional `x`, `y`, `w`, or `h`
fields.

Every visible Resource should have generated geometry:

- rendered boundaries require finite `x`, `y`, `w`, and `h`;
- rendered cards require finite `x` and `y`;
- missing geometry produces an explicit unavailable presentation;
- coordinate zero is never an implicit missing-value fallback;
- shared card dimensions drive placement, containment, routing, and hit regions.

Landscape boundaries count reported non-containment relationships that cross Resource Group scope,
but they do not rewrite those links onto aggregate endpoints. Exact source, target, type, and
direction appear only when the original records are visible in Resource focus.

## Network and Impact

The Network lens keeps the complete returned graph as evidence. Its default overview shows at most
2 ranked VNet boundaries, 4 related Subnet boundaries, 4 related network-role Resources, and
required ancestors. It does not repeat the complete raw Resource set.
VNet ranking and Subnet selection use the same canonical `contains` then `parent_id` precedence as
the rest of the workbench. Subnets are allocated round-robin in ranked VNet order before another
Subnet is taken from the same VNet. Network roles retain presentation-only inferred Subnet
membership when a connector Resource is outside the overview limit and after a found path expands
the presentation.
The default Network overview uses a wider compound-packing aspect than Resource focus so the two
ranked VNet scopes remain side-by-side when the available pane can contain them.

Path tracing walks only reported `attached_to`, stored-direction `depends_on`, and symmetric
`peered_with` relationships. It uses the complete returned evidence graph rather than the bounded
overview. A found path adds its exact Resources, ancestors, and stored links after category filters
apply, so a filter cannot remove a current path hop from the map or export. Incomplete negative
results remain `unknown`.

The Impact map requests an unscoped graph projection at the simulation snapshot. It verifies every
target and reached Resource identity before rendering and infers observed Subnet membership before
generating geometry. Snapshot mismatch or omitted identity makes the map unavailable instead of
understating impact.

## Information hierarchy and interaction

The `/architecture` route remains available through explicit direct URLs and contextual Resource
drill-downs. The Governance Explorer and every other Console screen intentionally omit dedicated
actions labeled Architecture, including Live, Onboarding, Rules, and Impact scope. Hiding those
actions does not remove contextual Resource links, the panel registration, or its read-only
authority.

One toolbar owns registered scope, bounded Resource search, `Topology | Network`, and read-only
source state. The coverage disclosure is collapsed by default and leads with complete or partial
state, freshness, returned and displayed Resource counts, and any page limit. Snapshot and
relationship totals remain available when expanded.

The SVG viewport owns pan, wheel zoom, Fit, full screen, and roving keyboard navigation. A new
Landscape or scope starts at its fitted origin. Reset identity includes visible Resource identities
and geometry, so equal-sized scopes cannot retain stale zoom or scroll. Resize within the same
canvas preserves operator-selected zoom. A canvas that is still in auto-Fit recalculates Fit when
the Inspector or viewport changes its available size.

The Inspector owns Overview, Links, Path, and Sources. It remains adjacent on desktop and moves
below the graph at constrained widths without discarding selection or path state. Mobile controls
and node hit regions are at least 44 CSS pixels. Reduced motion and forced colors preserve meaning.

Reviewed Resource icons use a URL-only resolver on interactive graphs. Raw SVG source remains
isolated to self-contained export generation, so entering an instance or topology view does not
load every reviewed icon or its export source before the selected graph can render.
The loopback Vite server permits reads only within the repository root so those reviewed shared
assets remain available during local development without widening the browser or deployment
boundary.

## Verification

Architecture verification includes:

- a geometry-less, truncated 500-record projection with 40 Resource Groups;
- a geometry-less 500-record projection without Resource Groups;
- bounded Landscape, Resource focus, and Network overview counts;
- unique finite positions and zero implicit origin fallback;
- direct endpoint reservation and exact omitted-link accounting;
- path restoration after category filtering;
- visible and accessible summary parity;
- default desktop Fit of at least 75% for dense Landscape and 50% for dense Network overview;
- fitted dense overview scroll dimensions no larger than the graph viewport;
- desktop `1440x900`, constrained `993x641`, mobile `390x844`, and minimum `320x844`;
- independent review with no confirmed Medium-or-higher finding.

Synthetic browser evidence validates mechanics only. Exact-source authenticated rendering remains
separate evidence.

## Related docs

| To learn about | Read |
|----------------|------|
| Implementation state and delivery evidence | [Architecture workbench implementation](../../roadmap-implementation/interfaces/console-architecture-workbench.md) |
| Network relationship and export semantics | [Network Topology Visualization](network-topology-visualization.md) |
| Console source, localization, and recovery | [Console Evidence and Resilience](console-evidence-and-resilience.md) |
