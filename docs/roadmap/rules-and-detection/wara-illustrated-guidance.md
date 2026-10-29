---
title: Illustrated WARA guidance
---
# Illustrated WARA guidance

WARA guidance explains the purpose, applicability, configuration and verification of a recommendation
through source-bound prose and an original relationship diagram. It supplements the assessment
catalog without changing any finding, approval, promotion or execution decision.

> **Scope:** All 456 lifecycle recommendations are accounted for. The 393 active entries are
> instructional guidance; 63 disabled entries remain explicitly historical. Illustrative examples
> are not observations of an installation and never imply satisfaction.

## Design at a glance

1. A deterministic authoring build combines the pinned APRL identity and explanation with reviewed
   service/control guidance and per-recommendation semantics.
2. The implementation-free shared package carries strict presentation contracts and the generated
   public corpus. A detail read validates identity, lifecycle and source pins before attaching one
   guide; list reads do not carry the full illustrated corpus.
3. Console renders bounded typed text, comparison lists and a directed diagram. Evaluation and
   source metadata remain separate, with explicit missing, blocked and unavailable states.

No runtime model, provider request, external image download or customer file is involved.

## Content contract

Every guide includes:

- an exact APRL recommendation ID, source revision, source digest and lifecycle;
- a title, summary, expected benefit and explanation of the operating mechanism;
- applicability and exclusions, illustrative before/after configuration;
- implementation steps, verification steps and cautions;
- typed diagram nodes, directed edges, labels, a caption and a text alternative;
- public APRL and Microsoft Learn citations;
- a content digest that covers all these fields.

Text uses an English source and optional Korean localization with explicit English fallback.
Machine identities, digests and serialized tokens stay unchanged across languages.
Per-recommendation source meaning takes precedence over a reusable family illustration.
Titles or shared diagrams alone are not substantive guidance.

The corpus verifies all 456 IDs exactly once, their 393/63 lifecycle split, the exact source
revision, an aggregate digest and per-entry digests. Missing instructional sections, disconnected
diagram nodes, unknown edge endpoints, duplicate IDs and unreviewed document origins fail explicitly.
The installed corpus uses a digest-bound manifest and bounded shards rather than a multi-megabyte
single source file. Each shard is limited to 512 KiB, and the complete read remains limited to 8 MiB.
The GUID hygiene gate admits only exact IDs from the independently pinned public APRL catalog on
the named authoring/generated/regression surfaces; an unknown GUID or modified source pin still fails.

## Presentation benchmark

The bounded benchmark has three recommendations:

| Recommendation | Required distinction |
|----------------|----------------------|
| Private DNS multiregion VNet links | Regional links are not VM autoregistration; successful name resolution does not prove a healthy backend or failover. |
| Dedicated/Isolated VM maintenance | Host, OS image and Guest scopes differ. The canonical Medium impact and held automatic evaluation remain unchanged. |
| Regional AI-service resilience | A governed gateway, primary and alternate deployments, and explicit routing prerequisites are shown. Regional, Data Zone and Global deployment labels do not imply identical processing location or automatic failover. |

A privately inspected presentation supplies the information-hierarchy benchmark, not public content.
Its customer screenshots, environment counts, deployment names and unsupported claims are excluded.
An unrelated citation in a presentation is corrected from official sources rather than preserved.

The acceptance surface explains why the change matters, depicts the actual relationship being
discussed, distinguishes illustrative configuration from current evaluation, and provides actions,
verification and correct public sources. Small text, overlapping connectors or a diagram made of
generic "rule -> check -> pass" boxes do not meet that standard.

## Customer and asset boundaries

The public corpus contains no presentation file, customer screenshot, customer resource identity,
private endpoint, account, environment count or customer-derived result. Examples use neutral role
labels and are explicitly marked illustrative.

Diagrams are repository-authored node/edge data. The renderer never accepts arbitrary SVG, HTML,
JavaScript, a document-provided image URL or a remote endpoint. A later external asset addition
requires individually verified usage rights, attribution, a content digest and privacy review;
public accessibility on Microsoft Learn alone is not redistribution permission.

Links are bounded HTTPS references to the original APRL source, Microsoft Learn, or the exact
reviewed Citrix managed-service limit page. The vendor exception is one origin/path, not a wildcard
for vendor-hosted content. References cannot contain user credentials or an arbitrary origin.
Official documentation changes trigger content review and do not silently change a recommendation's
evaluation semantics.

## Read path and compatibility

The shared package loads its installed immutable catalog, not a requester-controlled path.
`GET /wara-controls/{recommendation_id}` attaches only the matching guide after checking the stored
control's source revision, source digest and lifecycle. A mismatch is a visible unavailable/error
response. An un-authored or legacy recommendation renders the existing explanation and provenance
with an explicit absent-guide state.
The detail response revision binds both the stored catalog revision and the selected guidance
content digest. Updating public explanation alone therefore invalidates its cache identity without
changing assessment results. A guidance digest cannot hide a missing authoritative catalog revision.

The shared contract cannot import Core or Operator implementations. Core continues to own
assessment. The Operator read projection and Console cannot derive applicability, satisfaction or
authority from prose, figures, a product-group verification flag or source availability.

The existing filters, pagination, selected recommendation, direct links and browser history remain
authoritative for navigation. A selected GUID outside a text filter must not resolve to a different
guide. List reads remain bounded and do not embed all guides.

## Public presentation exports

`scripts/catalog/export_wara_guidance.py` exports selected IDs or an explicitly requested `--all`
corpus to public JSON and PPTX. It reads no installation evidence or customer content. The pure
Core report builder uses the same shared guide; the delivery adapter draws native vector nodes
and connectors and paginates body text at 18 points or larger.

The export preserves the guidance content/source digests, lifecycle, complete connection
descriptions and citations. Disabled recommendations have a historical warning. Existing private
assessment exports retain their separate behavior; public examples never acquire a scope digest,
assessment result or operational authority. Console print layout supports the browser's normal
print/PDF path without adding a provider or a new privileged export endpoint.

## Rendering and verification

The diagram uses one coordinate system and bounded graph shapes with a text fallback. Every edge
names valid endpoints, meaningful line styles have labels, and reading order remains available
without interpreting color. Long identifiers and Korean prose wrap without widening the document.

Visual acceptance is desktop-first: 1440 x 900, then constrained desktop around 993 x 641 and mobile
around 390 x 844 for affected states. A screenshot is paired with geometry and interaction checks.
Image/full-view controls preserve focus and keyboard operation when present.

Tests cover source identity, corpus accounting, strict decoding, rendering, localized text,
malformed sources, unavailable guidance and no-authority behavior. Fixture browser evidence is
explicitly fixture evidence and never an authenticated live assessment result.

## Related docs

| To learn about | Read |
|----------------|------|
| Assessment and evidence admission | [WARA assessment](wara-assessment.md) |
| Source preservation | [Rule catalog collection](rule-catalog-collection.md) |
| Implementation state and remaining work | [Implementation ledger](../../roadmap-implementation/rules-and-detection/wara-illustrated-guidance.md) |
