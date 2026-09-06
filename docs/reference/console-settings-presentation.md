# Console Settings and Component Presentation

This reference defines shared controls, IAM stages, component documentation, and authority
boundaries for FDAI Console settings and static mocks.

## Shared controls

Console settings and static mocks share Calm Slate control tokens and presentation primitives.
Desktop forms use 34 px standard controls and 28 px compact actions; touch targets use 44 px.
Browser-local preferences, account preferences, deployment policy, evidence, and authority remain
visually distinct without changing persistence or authorization contracts.

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
