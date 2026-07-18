---
description: Documentation style. Apply to every user-facing markdown doc.
applyTo: "docs/**/*.md,README.md,README-ko.md,**/README.md"
---

# Documentation Style

Every markdown doc committed to this repo follows the same layout family. The
goal is fast orientation: a reader who lands on any page sees, within a screen,
what the page is about and where to go next. This is the style established for
the root [README.md](../../README.md) and
[docs/roadmap/README.md](../../docs/roadmap/README.md), extended to every
user-facing doc.

> **Full guide**: this file is the short-form contract loaded automatically
> for every `.md` edit. The complete authoring reference (tiering, tone
> tables, before-and-after examples, jargon-gloss table, pre-publish
> checklist) lives in the
> [documentation-writing skill](../skills/documentation-writing/SKILL.md).
> Open the skill when you are authoring a new doc or doing a tone-correction
> pass.

## Scope

- **MUST**: every doc under `docs/**/*.md` and the root `README.md` +
  `README-ko.md` follow this layout. The bilingual pair rule in
  [language.instructions.md](language.instructions.md) applies unchanged.
- **SHOULD**: `.github/instructions/*.md` follow the same shape where it fits.
  Instruction files can be denser (they are engineering rules), but they still
  MUST open with a short orientation paragraph and use H2 sections.
- **MAY**: subsystem `**/README.md` files under `src/`, `console/`, `infra/`,
  `rule-catalog/`, `site/`, etc. keep a lighter, task-oriented shape; the
  ASCII-punctuation rule still applies (Korean prose is fine).

## Doc Tiers

Not every doc is a product overview. Pick the tier that matches the doc's job.

### Tier A: Entry points and user-facing overviews

Docs that a new reader might land on first: root `README.md`, roadmap `README.md`,
`docs/user-guide/get-started.md`, section indexes.

Required sections, in this order:

1. **`# Title`** and a **2-3 sentence hero paragraph**. State what the system
   (or page) is and what makes it different. No marketing adjectives.
2. **`## What can you achieve?`** (or an equivalent outcome-oriented H2).
   List the concrete outcomes the reader can get. For each outcome, use a
   short H3 + one paragraph + a `Example:` one-liner with a concrete flow.
3. **`## Works across your stack`** (or `## Works with`) - bulleted list of
   integration points (Azure resources, event bus, delivery channel, etc.).
4. **`## How it works`** - a **numbered 3-step flow** ("Ingest -> Route ->
   Gate and act" is the canonical example), followed by a small `text` code
   block or mermaid diagram if it adds clarity.
5. **`## Grows with your environment`** or an equivalent maturity section:
   Day 1 / Week 1 / Month 1 bullets that describe what the reader can expect
   over time.
6. **`## Get started`** - 3-5 links to the next docs to read. No prose walls.
7. **`## Next steps`** - a **table** with two columns (`| To learn about |
   Read |`). Every row links to a real, existing doc in the repo.

### Tier B: Technical reference / roadmap docs

Docs that specify a subsystem, contract, or phase: everything else under
`docs/roadmap/*.md`, phase docs, runbooks.

Required sections (order matters, headings can vary):

1. **`# Title`** and a **short hero paragraph (1-3 sentences)** that states
   the doc's job in the roadmap.
2. **Callout block(s)** as needed (scope reminder, implementation focus, TBD
   notes) - use the `>` blockquote style, not inline parentheticals.
3. **`## Design at a glance`** or **`## What this doc covers`** - a one-paragraph
   orientation before the deep dive. Optional when the hero paragraph already
   does this job.
4. **Body H2 sections** for each major concept. Prefer **short paragraphs +
   bulleted lists + tables** over walls of prose. A section that runs longer
   than ~15 lines of prose SHOULD be broken into H3 subsections or a table.

Optional but SHOULD when they fit:

- **`## Next steps`** or **`## Related docs`** - a table linking to the
  docs a reader should move to after this one. Use when the doc is a
  landing page or a deep intro; skip when the doc is a pure reference
  (e.g. schema, decision log) where the reader landed by searching for a
  specific fact.
- **`## Open questions`** or **`## Decisions`** - lists of TBD items or
  ADR-style entries when the doc records in-flight design work.

### Tier C: Subsystem READMEs (light shape)

`src/**/README.md`, `console/README.md`, `infra/README.md`, and similar.

- **Hero paragraph** stating what the subsystem does and where it sits in the
  control loop.
- **`## Layout`** or **`## Files`** table where useful.
- **Optional `## Testing`, `## Running locally`, `## Contracts`** sections
  as needed.
- No `What can you achieve?` marketing scaffolding here - these are
  engineer-facing.

## Universal Rules

These apply to **every** tier:

- **ASCII punctuation only** ([language.instructions.md](language.instructions.md#formats-machine-parseable)).
  Use `-`, `"`, `'`, `...`. Never em-dash, en-dash, smart quotes, ellipsis
  character, or no-break space. CI blocks these via `scripts/quality/repository/check-punctuation.sh`.
- **Bold lead-ins**: bulleted lists in Tier A / B docs use a `**Bold key**:`
  lead-in when practical, so the eye can scan.
- **Concrete examples**: any capability described in prose SHOULD have an
  `Example:` line with a plausible concrete flow (event -> tier -> decision ->
  action -> audit).
- **Links must resolve**: every link points to a real file / anchor in the
  repo or a published, stable URL. Do not link to files that "will exist".
- **No orphan sections**: if you introduce a section, either fill it or
  remove it. Placeholder text (`TODO`, `TBD content`) is not allowed in
  committed docs; use a `>` blockquote to declare the gap and link the issue
  or the doc that will land the content.
- **Diagrams**: prefer mermaid over ASCII art. When ASCII art is unavoidable,
  wrap it in a fenced `text` block so it does not get reflowed by editors.
- **Tables at the end**: the `## Next steps` (or `## Related docs`) table is
  the canonical way to hand the reader off to the next doc; it is NOT a
  substitute for real prose in the body.
- **Bilingual pair**: a change to `foo.md` MUST update `foo-ko.md` in the
  same PR and refresh `translation_source_sha`
  ([language.instructions.md](language.instructions.md#user-facing-doc-translations-ko)).
  Use `python3 scripts/quality/localization/refresh-translation-sha.py` after editing English
  docs to re-sync all pairs.

## Anti-Patterns

Do not:

- Open a doc with a code block, a table, or a diagram. The reader needs a
  sentence first.
- Use marketing adjectives ("lightning-fast", "world-class", "cutting-edge").
  State facts and measurements.
- Copy the Tier A template into a technical reference doc. Not every doc
  needs "What can you achieve?".
- Leave a section as a wall of prose > 15 lines. Break it up.
- Reintroduce em-dash, en-dash, or smart quotes. CI will block the PR.
- Add a `-ko.md` translation without matching front-matter, or leave its
  SHA stale relative to the English source.

## Where to Look for Reference

- Tier A canonical: [README.md](../../README.md) and
  [docs/roadmap/README.md](../../docs/roadmap/README.md).
- Tier B canonical: [docs/roadmap/architecture-adjacent](../../docs/roadmap/README.md)
  (any of the numbered reference docs 1-18).
- Tier C canonical: [src/fdai/core/README.md](../../src/fdai/core/README.md).
