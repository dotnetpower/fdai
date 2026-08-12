---
description: "Use when editing roadmap documents. Requires truthful implementation scope, append-only evidence history, and resumable remaining work."
applyTo: "docs/roadmap/**/*.md"
---

# Roadmap Implementation Tracking

Roadmap owner documents keep design intent and delivery state together. A reader
should be able to tell what is implemented, what evidence supports that claim,
and what observable work remains without reconstructing the answer from git
history or unrelated plans.

## Required Ledger

Every canonical English roadmap owner document MUST contain one
`## Implementation status` section with these H3 subsections:

1. `### Implementation scope`
2. `### Implementation history`
3. `### Remaining work`

The ledger MAY sit near the opening orientation or after the design body. Keep
normative design in its owning sections; the ledger summarizes delivery and
links to evidence instead of duplicating the design.

Index documents, Korean translations, the FDAI Constitution, and immutable
architecture decision records are exempt. Korean translations of a tracked
owner document MUST still carry the same translated ledger content under the
normal pair and SHA rules.

## Implementation Scope

Use a table with the columns `Area`, `State`, `Evidence`, and `Notes`. Each row
MUST describe a bounded part of the document's design rather than the whole
product. Allowed states are:

- `not-started`: accepted design with no implementation evidence.
- `in-progress`: implementation exists but the documented exit evidence is incomplete.
- `implemented`: the behavior exists and focused checks pass.
- `validated`: implementation plus the required runtime or operational evidence exists.
- `deferred`: deliberately postponed with an issue or decision reference.
- `not-applicable`: design-only material that has no executable implementation.

Use the strongest state the cited evidence proves, not the state the author
expects soon. A path alone proves implementation location, not runtime
validation. Split rows when different parts of the design have different
states.

## Implementation History

Use an append-only table with the columns `Date`, `State`, `Change`, `Evidence`,
and `Remaining`. Add a row whenever implementation scope changes state, lands a
material capability, gains operational evidence, regresses, or is superseded.

Evidence MUST be reviewable and repository-safe. Cite one or more of:

- source, catalog, migration, or test paths;
- an exact focused validation command and its outcome;
- an issue, pull request, commit, validation receipt, or governed runtime evidence reference.

A commit cannot contain its own final SHA. For work recorded in the same
commit, use `current change` and cite the task-owned paths plus the focused
checks. Do not replace that marker with a guessed SHA.

History is append-only after adoption. Correct an inaccurate prior row with a
new dated row that explains the correction. Do not silently rewrite or delete
past implementation transitions.

When reliable prior history is unavailable, do not reconstruct it from memory.
Add an adoption row that says earlier provenance was not reconstructed, then
describe only the current state supported by repository evidence.

## Remaining Work

Use Markdown task-list items. Every open item MUST state an observable exit
condition and SHOULD link to its owner issue, design section, or expected
evidence surface. Keep partially delivered work open until the cited evidence
exists.

When nothing remains for this document's bounded scope, use one checked item
that says so and cites the evidence supporting completion. Never use an empty
section, `TBD`, or an unsupported completion claim.

## Update Rules

- Update the ledger in the same change as an implementation transition.
- Keep English and Korean document pairs semantically aligned and refresh the
  translation source SHA.
- Record regressions and rollbacks as new history rows and reopen affected work.
- Do not use branch names, local paths, customer identifiers, or uncommitted
  external state as durable evidence.
- Do not bulk backfill dates, authors, commits, validation outcomes, or runtime
  status that the repository cannot prove.
- Use the
  [roadmap implementation tracking skill](../skills/roadmap-implementation-tracking/SKILL.md)
  for adoption, review, or multi-document maintenance.

## Review Check

Before completion, verify that scope states match their evidence, the newest
history row explains the current transition, open work has observable exit
criteria, translations match, and focused checks pass. If evidence is missing,
lower the state or leave the work open.
