# Console Settings and Component Presentation

This reference defines shared controls, IAM stages, component documentation, and authority
boundaries for FDAI Console settings and static mocks.

## Shared controls

Console settings and static mocks share Calm Slate control tokens and presentation primitives.
Desktop forms use 34 px standard controls and 28 px compact actions; touch targets use 44 px.
Browser-local preferences, account preferences, deployment policy, evidence, and authority remain
visually distinct without changing persistence or authorization contracts.

## Model settings loading

The Models workspace and navigation prefetch use `GET /models/settings?view=summary`.
This reads authoritative configuration without discovering the Azure model catalog.
The existing full GET remains available. Narrator and web-search saves can request the same
summary response without changing their role, revision, or audit checks. Invalid view options
are rejected before a mutation, and save responses retain the authenticated management capabilities.

Catalog discovery starts when you select its workspace. Its loading, failure, and retry states
do not replace working configuration or unsaved policy drafts. Independent model, deployment,
and quota reads run concurrently after the configured account is resolved; a failed attempt
cancels remaining reads. The catalog displays its actual observation time, never an inferred
inference-readiness claim. Summary and full responses have separate 60-second client-memory
caches that are invalidated together after a change or forced refresh.

The selected workspace uses the `model-view` URL parameter. Search covers the returned catalog,
while each page renders at most 12 cards. Unavailable data isn't reported as an observed zero.
Governance selections still prepare drafts and do not deploy, invoke, or activate a model.

## Recovery across settings

Forms preserve newer drafts across asynchronous saves and distinguish partial persistence from
verified readback. Local filters show their applied scope and loaded counts without inventing
server-wide totals. Diagnostic reads settle independently and show their actual completion time
and local request duration, not a service-level objective or provider health guarantee.

The complete menu-by-menu change inventory is in the
[Console Settings Improvement Inventory](console-settings-review.md).

## IAM presentation

`/settings/iam` uses route-owned bilingual messages and responsive styles. It distinguishes the
verified FDAI Owner role from tenant administration, presents request, review, protected apply,
and fresh verification as separate stages, and links operational assignment review to Agent
oversight.

Rolling Console and Operator API upgrades preserve safe role and capability facts while marking
missing directory metadata as unknown. IAM response decoders load with the first IAM request
instead of increasing the initial Console bundle.

## Component gallery

The static component gallery reads its documented component contracts from
`mocks/ui/assets/component-registry.json`. Each bounded category view presents the specimen before
its owner, source, states, usage guidance, responsive behavior, accessibility contract, and product
references.

A missing or invalid registry blocks documented status instead of inferring that a specimen is
canonical. The gallery remains synthetic presentation evidence and grants no Console, Operator API,
or executor authority.

## Related docs

| To learn about | Read |
|----------------|------|
| Operations design | [Console Operations](../roadmap/interfaces/console-operations.md) |
