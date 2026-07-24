---
description: "Use when editing prose, identifiers, serialized records, localization catalogs, docs, or user-facing strings. Covers bilingual content and ASCII tooling rules."
applyTo: "**/*.{md,py,ts,tsx,js,json,yaml,yml,sh,tf}"
---

# Language Policy

> **Related on-demand skill**:
> [`.github/skills/i18n-catalog/SKILL.md`](../skills/i18n-catalog/SKILL.md)
> is the runnable workflow for L1 `.md` + `-ko.md` doc pairs, L2 message
> catalog authoring, and the SHA / parity / punctuation gates. Load it when
> you are editing catalogs, translations, or a gate failure sends you here.

## Scope

This policy governs everything **committed to this repository** and everything the
control plane **emits at runtime** (logs, error strings, audit records, generated PRs).
It does not govern live maintainer chat. Related rules live in
[coding-conventions.instructions.md](coding-conventions.instructions.md) (commits/PRs)
and [generic-scope.instructions.md](generic-scope.instructions.md) (no customer data).

## Bilingual policy (English + Korean)

FDAI is **fully bilingual: English and Korean are both first-class** and MAY be
used in natural-language repository text - source comments, docstrings, string
literals, logs, error messages, tests, fixtures, `.github/**`, and docs. **Korean
is never a defect on the basis of being Korean; there is no repository-wide
english-only gate.** GitHub issues are the narrow exception described below.

Only two constraints remain, and they are about **tooling compatibility**, not
about which human language you may write:

- **Identifiers, filenames, and branch names MUST be ASCII** (`a-z A-Z 0-9 _ - .`).
  Code symbols (variable / function / class / module names), file paths, and git
  branch names stay ASCII for cross-language, cross-platform, and tooling
  compatibility. Write Korean in comments, docstrings, and string **values** -
  never in a name or a path.
- **ASCII punctuation only** (still enforced by `scripts/quality/repository/check-punctuation.sh`):
  use `-`, `"`, `'`, `...`; never em-dash, en-dash, smart quotes, the ellipsis
  character, or a no-break space - those break `grep`, `diff`, and search
  regardless of language.

### GitHub issue language (English-only)

GitHub issues are shared project-tracking artifacts, not localized product or
documentation surfaces. Issue titles, bodies, and comments **MUST be English**
and are never translated. This rule matches
[`CONTRIBUTING.md`](../../CONTRIBUTING.md#opening-issues) and applies whether an
issue is opened manually, by an agent, or by an automated handoff. Live
maintainer chat remains outside this policy and MAY use either language.

### Surfaces and localization mechanisms (optional, recommended)

The layered surfaces still exist as **localization mechanisms** you MAY use for
structured bilingual delivery; none of them forbids Korean anywhere:

| Surface | Recommended mechanism |
|---------|-----------------------|
| **Developer docs** (root `README.md`, `docs/**/*.md`) | `foo.md` + `foo-ko.md` sibling pairs, kept in sync by `check-translations.sh` (see [-ko.md](#user-facing-doc-translations-ko)). |
| **Product surfaces** (console, CLI, ChatOps, notifications, site) | English-source message catalogs + `ko` overlay with English fallback, parity-gated by `check-catalog-parity.sh` (see [Product i18n](#product-i18n-l2)). Inline Korean is also fine. |
| **Bragi narrator** | Renders in the operator's locale; inline Korean is fine. |

Use these mechanisms for anything reusable or externally shipped - they give an
English fallback, translation-freshness tracking, and searchable catalogs. For
one-off internal strings, inline Korean (or English) is perfectly acceptable.

### Machine-record recommendation (SHOULD)

Audit entries, event payloads, serialized verdicts, log keys, rule ids, and
config keys are consumed by **tooling** (deterministic replay, correlation,
cross-fork search). Keeping those stable keys and machine records **English**
keeps them grep-able and replayable across forks and clouds - a strong
recommendation (**SHOULD**), no longer a hard gate. Localize the human-facing
**labels around** a machine record freely; think twice before translating the
record's own stable keys or a serialized enum value.

## Specific constraints

Identifiers and paths stay ASCII. Machine records SHOULD stay English for replay. Encode non-English
parser fixtures as readable UTF-8 when clarity benefits, and never hand-edit generated or vendored code.
Emoji may appear in prose only when it adds meaning.

### Readable Korean source literals

Korean prose, labels, matching tokens, tests, fixtures, and regular-expression alternatives MUST
use readable NFC UTF-8 text instead of Hangul `\uXXXX` escapes. Escaped Korean makes debugging,
review, search, and translation maintenance unnecessarily opaque without changing runtime value.

An escape MAY remain only when the code explicitly reasons about Unicode code points, character
block boundaries, malformed input, or normalization behavior. Every retained Hangul escape MUST
be an exact, rationale-bearing entry in
`scripts/quality/localization/readable-hangul-allowlist.txt`. Generated artifacts MUST be fixed at
their generator and regenerated, never hand-edited. Run
`python3 scripts/quality/localization/check-readable-hangul.py --fix` for mechanical conversion.

## User-Facing Doc Translations (`-ko.md`)

User-facing Markdown documentation ships bilingually via `foo.md` + `foo-ko.md`
sibling pairs. This is the **doc-pair convention** for structured bilingual docs;
Korean is allowed elsewhere too (see the [Bilingual policy](#bilingual-policy-english--korean-everywhere)),
but the paired-file mechanism below - with its freshness (SHA) gate - applies to
the scope named here.

**Scope (paired `-ko.md` required)**

- Root `README.md`
- Everything under `docs/**/*.md`

**Out of scope for the pair convention (English canonical by convention)**

- Everything under `.github/**` - `copilot-instructions.md`, `instructions/*.md`,
  workflows, issue and PR templates. These are project guidelines, not user docs,
  and stay English canonical (no required `-ko.md` pair).
- Everything under `docs/internals/**` - internal engineering notes (gap
  analyses, summaries of external material, working design memos). Team-facing
  engineering artifacts, English canonical; a `-ko.md` sibling is permitted but
  never required.
- Anything under `mocks/**`, `examples/**`, and any future third-party or vendored path.

**File-pair convention**

- The English file is the **canonical source of truth**: `foo.md`.
- The Korean translation is a sibling with the `-ko.md` suffix: `foo-ko.md`.
- A `-ko.md` file **must not exist without** a matching English `foo.md`. Korean-only
  documents are prohibited.
- A `-ko.md` file **must** carry YAML front-matter identifying its source and its
  translation-source SHA:

  ```yaml
  ---
  translation_of: foo.md
  translation_source_sha: <git blob sha of foo.md at translation time>
  translation_revised: 2026-07-05
  ---
  ```

  Compute the SHA with `git hash-object foo.md`.

**Paired-update rule (MUST)**

- **Any change to `foo.md` MUST update `foo-ko.md` in the same PR**, and vice versa.
  A PR that touches only one side is not mergeable. The CI translation check enforces
  this by comparing `git hash-object foo.md` against the `translation_source_sha`
  recorded in `foo-ko.md`.
- If the translator has not yet reflected an English update, the SHA in `-ko.md` will
  no longer match `foo.md` → CI fails → the PR must update both sides before merge.
- Adding a **new** `foo.md` in scope MUST create `foo-ko.md` in the same PR.
- Removing `foo.md` MUST remove `foo-ko.md` in the same PR.

**Content rules**

- The two files carry the **same information, structure, and headings**. The Korean
  file is a translation, not a rewrite or an editorial re-org.
- Preserve unchanged: code blocks, tables of technical values, links, filenames, and
  domain vocabulary in backticks (`T0`, `T1`, `T2`, `HIL`, `trust-router`,
  `deterministic-engine`, `rule-catalog`, `risk-gate`, `remediation-pr`, `shadow-mode`).
  Only translate natural-language prose.
- Cross-references between docs should point language-consistently: links in
  `foo-ko.md` to sibling docs point to their `-ko.md` counterparts; links to
  `.github/**` (English-only) stay pointing to the English file.
- Formats stay identical: ISO 8601 dates, ASCII punctuation, no smart quotes.

## Product i18n (L2)

Reusable product strings SHOULD use an English-source catalog plus a Korean overlay. English is the
mandatory fallback; Korean keys may lag but MUST NOT invent keys absent from English. Locale order is
explicit preference, request `Accept-Language`, then `en`. Presentation localizes labels around L0
machine records and never rewrites serialized values. Human-facing approval labels use `Approvals`
rather than bare `HIL` unless explaining the raw verdict. Load the
[i18n-catalog skill](../skills/i18n-catalog/SKILL.md) for catalog changes.

Treat contract vocabulary and display vocabulary as separate layers. Keep canonical tokens such as
`verdict`, `hil`, and `stewardship` in identifiers, serialized records, schemas, and API examples.
In user-facing prose and labels, lead with plain English or Korean such as `Decision` / `결정`,
`Human approval` / `사람 승인`, and `Ownership` / `담당 체계`. Show the canonical term in
parentheses only when readers need to correlate the display with a technical contract. Never expose
a raw enum value as the primary label when a localized display mapping exists.

### L3 - conversational (Bragi narrator)

Bragi renders its final natural-language answer in the operator's locale
(`UserPreference.locale`), but everything beneath the answer - the intent it translates
into, the tool calls, the verdict, and the audit entry - stays L0 English. The narrator
is a **presentation translator**, matching its "translator only" role in
[architecture.instructions.md](architecture.instructions.md); a localized phrasing MUST
NOT change what the typed pipeline decides.

## Formats (machine-parseable)

- Dates and timestamps use **ISO 8601 / RFC 3339** (`2026-07-03`, `2026-07-03T09:15:00Z`).
- Use `.` as the decimal separator and no digit-grouping in machine-read values.
- **ASCII punctuation only (MUST, CI-enforced).** Use `-`, `"`, `'`, and `...`. The
  following Unicode characters are BLOCKED in every tracked text file by
  `scripts/quality/repository/check-punctuation.sh`:
  - U+2014 EM DASH  and  U+2013 EN DASH  -> use ASCII `-`
  - U+2026 HORIZONTAL ELLIPSIS  -> use `...`
  - U+201C / U+201D smart double quotes  -> use ASCII `"`
  - U+2018 / U+2019 smart single quotes  -> use ASCII `'`
  - U+00A0 NO-BREAK SPACE (invisible; breaks grep/diff)  -> use a normal space
  Auto-fix: `python3 scripts/quality/localization/normalize-punctuation.py` (fence-aware for `.md`;
  add `--whole-file` for source files where the whole content is code).

## Naming and automation

Use canonical English identifiers and the shared vocabulary (`T0`, `T1`, `T2`, `HIL`,
`trust-router`, `risk-gate`, `shadow-mode`). Repository prose remains bilingual.

CI enforces ASCII punctuation, translation pairs, and catalog key parity through:

- `scripts/quality/repository/check-punctuation.sh`
- `scripts/quality/localization/check-readable-hangul.py`
- `scripts/quality/localization/check-translations.sh`
- `scripts/quality/localization/check-catalog-parity.sh`

A non-ASCII identifier or path is a defect. Korean prose is not. GitHub issues remain the only
English-only collaboration surface.
