---
name: documentation-writing
description: |
  Comprehensive guide for writing FDAI documentation with the tone,
  structure, and terminology of Microsoft Learn (learn.microsoft.com). Use
  this skill when authoring, reviewing, or correcting any tracked markdown
  file in the repository. Complements
  `.github/instructions/documentation-style.instructions.md` (which is the
  short, always-loaded contract) and
  `.github/instructions/language.instructions.md` (which is the language +
  translation contract).
version: 1.0.0
scope: repository
---

# Documentation Writing (FDAI)

This skill is the long-form authoring guide for every markdown doc in the
repo. It defines the doc tiers, structural patterns, Microsoft-Learn-inspired
tone, terminology glosses, and a pre-publish checklist.

The short-form contract lives in
[../../instructions/documentation-style.instructions.md](../../instructions/documentation-style.instructions.md)
and is loaded automatically for every `**/*.md` edit. This skill is invoked
by hand when you want the full guidance.

## When to Use This Skill

Use this skill when you:

- Author a new markdown doc (any tier).
- Restructure an existing doc into the Tier A / B / C shape.
- Do a tone-correction pass to bring a doc closer to Microsoft Learn style.
- Review a PR that touches user-facing docs.

Do NOT use this skill for:

- YAML front-matter or code-only edits.
- Instruction files under `.github/instructions/**` (they intentionally
  keep RFC 2119 normative language and stay dense).

## Doc Tiers (recap)

| Tier | Where | Voice | Normative language |
|------|-------|-------|--------------------|
| A - entry points | root `README.md`, `docs/user-guide/get-started.md`, doc-set indexes | Reader-directed ("you"), short paragraphs, Example lines, Next steps table. | Soft ("we recommend", "should", "avoid"). |
| B - technical reference | `docs/roadmap/*.md`, phase docs, runbooks | System-plus-reader mix. Dense but scannable. | Normative allowed where operationally required; still gloss jargon on first mention. |
| C - subsystem READMEs | `src/**/README.md`, `console/README.md`, `infra/README.md`, `rule-catalog/README.md`, `site/README.md` | Engineer-facing, task-oriented. | Neutral. |
| Instructions (out of scope) | `.github/instructions/*.md` | Contract. | RFC 2119 MUST / SHOULD / MAY. Don't soften. |

## Tier A: Required Layout

Every Tier A doc opens with, in order:

1. `# Title` (H1) and a **hero paragraph of 2-3 sentences** stating what
   the system or page is and one differentiator. No marketing adjectives.
2. `## What can you achieve?` (or an equivalent outcome-oriented H2). List
   the concrete outcomes as H3 blocks, each with:
   - one short paragraph (what the reader gets),
   - one `Example:` line with a concrete before-to-after flow.
3. `## Works across your stack` (or `## Works with`) - bulleted integrations.
4. `## How it works` - a **numbered 3-step flow**, followed by a small `text`
   code block or a `mermaid` diagram if it helps.
5. `## Grows with your environment` (or an equivalent maturity section):
   Day 1 / Week 1 / Month 1 bullets.
6. `## Get started` - 3-5 links to the next docs.
7. `## Next steps` - a **table** with two columns (`| To learn about | Read |`).

Canonical Tier A example: [../../../README.md](../../../README.md) and
[../../../docs/roadmap/README.md](../../../docs/roadmap/README.md).

## Tier B: Required Layout

Tier B is denser but still scannable. Required sections:

1. `# Title` and a **1-3 sentence hero** stating the doc's job in the roadmap.
2. Callout `>` blockquotes for scope / implementation-focus reminders,
   never inline parentheticals.
3. `## Design at a glance` OR `## What this doc covers` - one paragraph.
4. Body H2 sections for each major concept. Prefer short paragraphs +
   bullets + tables over walls of prose. If a section is more than ~15 lines
   of prose, break it into H3s or a table.

Optional (SHOULD when they fit):

- `## Next steps` or `## Related docs` - a table of follow-on reading.
- `## Open questions` / `## Decisions` - ADR-style entries for in-flight design.

## Tier C: Required Layout

Short and task-oriented. A subsystem `README.md` opens with:

1. `# Title` and a hero paragraph stating what the subsystem does and where
   it sits in the control loop.
2. `## Layout` or `## Files` - table when useful.
3. Optional: `## Running locally`, `## Testing`, `## Contracts`.

## Microsoft-Learn Tone (mandatory across all tiers)

We match the tone of [learn.microsoft.com](https://learn.microsoft.com/):
reader-directed, soft advice, terms glossed on first mention. The following
tables come from a paired reading of 10 Azure docs (English + Korean pairs
for Container Apps, AKS, WAF Reliability, Azure Monitor, Managed Identities).

### 1. Normative language

In user-facing docs (Tier A / B / C) the RFC 2119 verbs are softened.
Instruction files under `.github/instructions/**` keep RFC 2119 as-is.

| Our default (Tier A/B/C) | Preferred phrasing |
|--------------------------|--------------------|
| `MUST` | `should` / `we recommend` / `always` |
| `MUST NOT` | `avoid` / `don't` / `not supported` |
| `is prohibited` / `forbidden` | `isn't supported` / `not allowed` |
| `Rejected` / `vetoed` | `not accepted` / `blocked` |
| `stop-ship` | `blocks release` / `must be resolved before release` |
| `not mergeable` / `won't merge` | `the PR won't merge until the check passes` |
| `code that violates X is a defect` | `code that doesn't follow X needs a fix` |
| `no exceptions` | `always required` |

### 2. System-centric to reader-centric voice

Move from "The X does Y" (third person about the system) to "You can use X
to do Y" (second person, reader-directed) wherever a reader is the audience.

| Third-person | Reader-directed |
|--------------|-----------------|
| `The trust router computes a confidence and routes the event.` | `FDAI picks the lowest tier that can decide the event.` |
| `Every event flows through a trust router.` | `You send an event, and the trust router picks the right tier.` |
| `The core sits behind provider adapters.` | `Azure calls go through provider adapters so you can swap the cloud later without a rewrite.` |
| `FDAI resolves the repeatable majority.` | `FDAI helps you resolve the repeatable majority of events with rules, and reserves LLM inference for the ambiguous minority.` |

### 3. Hard-line phrases

Soften without losing precision. Keep the operational meaning; drop the
courtroom tone.

| Hard | Soft |
|------|------|
| `Fail toward safety.` | `Choose the safer default when the outcome is uncertain.` |
| `Autonomy is never unconditional.` | `Autonomy always runs with guardrails.` |
| `This is not an override - it is a definitional gate.` | `This is a required check, not an option.` |
| `abstain` | `hold for review` / `pass to a human` |
| `regression demotes it back to shadow` | `if a regression appears, the action moves back to shadow mode automatically` |
| `LLMs generate; the verifier disposes.` | `The LLM proposes an action, and the verifier decides whether it can run.` |
| `hot-patch` | `emergency fix` |

### 4. Jargon gloss on first mention

Every domain term is glossed the first time it appears in a doc. After the
first gloss you can use the bare term freely in that same doc. Instruction
files are exempt.

| Term (bare) | First-mention form |
|-------------|--------------------|
| `HIL` | `human-in-the-loop (HIL)` |
| `T0 / T1 / T2` | `T0 (deterministic rules), T1 (lightweight similarity reuse), T2 (grounded LLM reasoning)` at the first tiering paragraph |
| `remediation PR` | `remediation pull request (a PR that applies the fix)` |
| `trust router` | `trust router (picks the tier that decides the event)` |
| `quality gate` | `quality gate (a set of checks the model output must pass)` |
| `CSP-neutral` | `cloud-provider-neutral (CSP-neutral)` |
| `policy-as-code` | `policy-as-code (policies expressed as machine-readable rules)` |
| `idempotent` | `safe to retry (idempotent)` |
| `blast-radius` | `blast radius (the scope a change can affect)` |
| `shadow mode` | `shadow mode, where the system observes and logs but doesn't act` |
| `promotion / demotion` | `promotion (turning enforcement on) / demotion (turning it back off)` |
| `least privilege` | `minimum permissions (least privilege)` |
| `discovery loop` | `discovery loop (the pipeline that proposes new or revised rules)` |

### 5. Sentence rhythm and connectors

- Prefer periods to em-dash-equivalents. Two short sentences beat one
  clause-stacked sentence.
- When contrasting, use "In contrast," or "By comparison,", not " - ".
- When introducing a list, use a full lead-in sentence ending in a colon:
  `Common uses of FDAI include:`.

### 6. Korean-side tone (KO docs)

Match Microsoft Learn Korean docs. In particular:

| Our default (KO) | Preferred (KO) |
|------------------|----------------|
| `~해야 한다` (terse duty) | `~하는 것이 좋습니다` / `~을 권장합니다` |
| `~한다.` / `~한다` in bullet ends | `~합니다.` (consistent 존댓말 종결) |
| `금지` | `지원되지 않음` / `허용되지 않음` |
| `거부` | `차단됩니다` / `수락되지 않습니다` |
| `머지 불가` | `병합되지 않습니다` |
| `사람 개입` (부정 뉘앙스) | `사람 검토` / `사람 승인` |
| `~를 참조합니다.` | `~를 참조하세요.` (폴라이트 명령형) |
| `실패 -> 안전` | `불확실할 때는 안전한 쪽을 선택합니다` |

Within a single doc, keep verb endings consistent. Do not mix `~한다`
and `~합니다` in the same bullet list.

## Universal Rules (already enforced elsewhere; recap)

- ASCII punctuation only. No em-dash `—`, en-dash `–`, ellipsis `…`, smart
  quotes, or no-break space. See
  [`../../instructions/language.instructions.md`](../../instructions/language.instructions.md).
  CI: `scripts/quality/repository/check-punctuation.sh`.
- Korean is allowed in docs (FDAI is fully bilingual); there is no english-only
  gate. See same file.
- Bilingual pair: every `docs/**/*.md` and root `README.md` has a matching
  `-ko.md` with valid front-matter and current `translation_source_sha`.
  CI: `scripts/quality/localization/check-translations.sh`. Auto-refresh:
  `python3 scripts/quality/localization/refresh-translation-sha.py`.
- Every link resolves to a real file or a stable public URL. Do not link
  to files that "will exist".
- Diagrams: mermaid over ASCII art. When ASCII art is unavoidable, wrap it
  in a fenced `text` block.

## Anti-Patterns

Do not:

- Open a doc with a code block, a table, or a diagram. Start with a
  sentence.
- Reintroduce em-dash or en-dash. `scripts/quality/repository/check-punctuation.sh` will
  block the PR.
- Copy the Tier A template into a technical reference. Not every doc needs
  "What can you achieve?".
- Use marketing adjectives ("lightning-fast", "world-class",
  "cutting-edge"). State facts and measurements.
- Leave a section as a wall of prose over ~15 lines. Break it up.
- Add a `-ko.md` translation without matching front-matter, or leave its
  `translation_source_sha` stale relative to the English source.
- Soften RFC 2119 verbs inside `.github/instructions/**`. That's the
  contract. Soften only in user-facing docs.

## Pre-Publish Checklist

Before merging a PR that touches a `.md` file:

1. Tier: which tier is this doc? Confirm the layout matches.
2. Hero: first paragraph is 1-3 sentences, no code / table / diagram before it.
3. Sections: H2 boundaries clear, no wall-of-prose H2 over ~15 lines.
4. Jargon gloss: every domain term glossed on first mention in this doc.
5. Voice: user-facing docs are reader-directed; RFC 2119 verbs softened.
6. Next steps: user-facing docs end with a `Next steps` (or `Related docs`)
   table linking to real files.
7. Bilingual pair: `-ko.md` updated with translated prose (not just the
   English left in place) and its front-matter SHA refreshed via
   `python3 scripts/quality/localization/refresh-translation-sha.py`.
8. CI gates: run locally before pushing:

    ```bash
    bash scripts/quality/repository/check-punctuation.sh
    bash scripts/quality/localization/check-translations.sh
    ```

9. Links: every relative link resolves; no `will exist` placeholders.
10. Anti-patterns: none of the items in the [Anti-Patterns](#anti-patterns)
    section slipped in.

## Where to Look for Reference

- Tier A canonical: [../../../README.md](../../../README.md) and
  [../../../docs/roadmap/README.md](../../../docs/roadmap/README.md).
- Tier B canonical: any of the numbered reference docs 1-18 under
  [../../../docs/roadmap/](../../../docs/roadmap/README.md).
- Tier C canonical: [../../../src/fdai/core/README.md](../../../src/fdai/core/README.md).
- Tone reference: paired Microsoft Learn overview pages (Container Apps,
  AKS, Azure Monitor, Managed Identities, WAF Reliability) at
  [learn.microsoft.com](https://learn.microsoft.com/).
