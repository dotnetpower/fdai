---
description: Language and naming policy for all FDAI artifacts.
applyTo: "**"
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

## Notes on specific cases

Korean is broadly allowed (see the [Bilingual policy](#bilingual-policy-english--korean-everywhere)
above). A few specific cases still need care:

- **Identifiers and paths stay ASCII.** Non-ASCII in a variable / function / class /
  module / file name or a git branch name is still a defect (tooling compatibility),
  even though Korean is fine in comments and string **values**.
- **Machine records SHOULD stay English.** An audit entry, event payload, serialized
  verdict, log key, rule id, or config key is machine-consumed; keep those English so
  deterministic replay, correlation, and cross-fork search stay reliable (SHOULD, not
  gated).
- **Quoted data**: when a non-English string is the literal subject under test (a
  parser or encoding fixture), encoding it explicitly (`\uXXXX` or UTF-8 bytes) with a
  one-line note stays good practice for clarity.
- **Vendored / generated code**: do not hand-edit third-party or generated files to
  translate their comments.
- **Emoji**: not in identifiers, paths, or branch names; in prose only when it adds
  meaning, never as a substitute for words.

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

L2 surfaces (operator console, CLI, ChatOps cards, notifications, the docs site) are
**bilingual**. This operationalizes the [Localization](#allowed-exceptions) exception:

- **Bilingual source is allowed.** A user-facing string on an L2 surface MAY be
  written in Korean (or English) **inline**, or authored as an English key in a
  message catalog. Catalogs are **recommended** for reusable strings - they give a
  mandatory English fallback and keep `en` / `ko` in parity - but inline Korean is
  permitted for surface-specific presentation text. There is no english-only gate,
  so Korean on any surface (or anywhere else) does not fail CI.
- **Approval terminology:** human-facing L2 labels and default L3 prose SHOULD use
  `Approvals`, `Approval required`, or `Pending approval` instead of the bare `HIL`
  acronym. `HIL` MAY appear when explaining the raw `hil` verdict, in a technical
  glossary, or when an operator asks about the term explicitly. L0 identifiers and
  values such as `hil`, `/hil-queue`, schemas, types, events, and audit records keep
  the canonical machine vocabulary; presentation code never renames serialized values.
- **One catalog pair per surface.** `messages.en.json` (source) + `messages.ko.json`
  (translation), or the surface's native i18n format (e.g. Astro Starlight locales for
  the docs site). Catalogs live in a dedicated resource path.
- **English fallback is mandatory** for catalog strings. A missing or empty translation
  key renders the English source - never a blank, the key name, or an error. A partial
  `ko` catalog ships fine.
- **Locale resolution order:** explicit user preference (`UserPreference.locale`) ->
  request `Accept-Language` -> default `en`.
- **Catalog parity (CI):** every key in `messages.ko.json` MUST exist in
  `messages.en.json` (no orphan translations); the `en` catalog is the source of truth,
  mirroring the `-ko.md` SHA gate. A `ko` catalog MAY lag (fallback covers it) but MUST
  NOT invent keys the `en` catalog does not have.
- **Machine records SHOULD stay English** even on an L2 surface. A `ko` catalog value
  is fine, but an audit entry, event payload, log key, or config key that a resource
  file carries SHOULD stay English for replay / correlation - localize the labels
  around it, not the record.
- **Do NOT localize L0 in place.** When an L0 record (audit entry, log line, event
  payload, PR body, Rego, error code, identifier) surfaces inside a localized L2 view,
  the view localizes the **labels around it**, never the machine record itself.

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

## Why

- The control plane is designed to be **CSP-neutral** (cloud-provider-neutral) and
  portable across teams and clouds.
- Mixed-language artifacts break searchability, reviewability, and tooling (linters,
  policy engines, LLM grounding).
- A single language keeps the rule catalog and audit logs machine-parseable.

## Naming

- Use clear, descriptive English identifiers. "Avoid transliterated abbreviations" means:
  do not romanize non-English words into code (write `approval-queue`, not a phonetic
  spelling of a foreign term).
- Domain vocabulary is defined canonically in
  [architecture.instructions.md](architecture.instructions.md); reuse those terms:
  `trust-router`, `deterministic-engine`, `rule-catalog`, `risk-gate`, `remediation-pr`,
  `shadow-mode`, `HIL` (human-in-the-loop).
- Casing: tiers and acronyms are uppercase (`T0`, `T1`, `T2`, `HIL`); code symbols follow
  their language convention (e.g., kebab-case configs, snake_case Python, camelCase JS).

## Examples

- Good: `// retry the remediation-pr when the risk-gate abstains`
- Also good: `// risk-gate가 abstain하면 remediation-pr을 재시도` (Korean comment is fine).
- Bad: a **non-ASCII identifier** (`def 실행():`) or a Korean git branch name.
- Fixture: `{"input": "\uD55C\uAE00", "note": "non-ASCII parse case"}` - encoding a
  string-under-test explicitly stays good practice for clarity.

## Automation & Review Check

- **No repository-wide english-only gate.** Korean is allowed in natural-language
  repository text; there is no CI check that blocks it.
  (`scripts/check-english-only.sh` has been retired.) GitHub issue language is
  enforced by author and reviewer discipline.
- **Punctuation gate**: `scripts/quality/repository/check-punctuation.sh` runs in CI and enforces the
  ASCII-only punctuation rule above; it blocks em-dash, en-dash, ellipsis,
  smart-quotes, and no-break-space anywhere in a tracked text file (including inside
  `-ko.md`, code blocks, and comments) - regardless of language.
- **Translation-pair gate**: `scripts/quality/localization/check-translations.sh` runs in CI and enforces
  the [paired-update rule](#user-facing-doc-translations-ko) for docs that use the
  pair convention: every in-scope `foo.md` has a `foo-ko.md`, every `foo-ko.md` has
  front-matter with `translation_of` and `translation_source_sha`, and each
  `translation_source_sha` matches the current `git hash-object` of the source file.
- **Catalog-parity gate**: `scripts/quality/localization/check-catalog-parity.sh` runs in CI and enforces
  the [Product i18n](#product-i18n-l2) rule for L2 message catalogs: for every
  `<name>.en.json` / `<name>.ko.json` sibling pair, the `ko` keys MUST be a subset of
  the `en` keys (no orphan translations; `en` is the source of truth, `ko` MAY lag
  under English fallback). No catalogs present is a pass, so it is safe before any
  catalog exists.
- **Review guidance**: an identifier / filename / branch name that is not ASCII, or an
  L0 machine record (audit entry, event payload, log key, config key, serialized
  verdict) written in Korean, is worth flagging in review - the first breaks tooling,
  the second weakens replay / correlation (SHOULD keep English). Korean prose anywhere
  else is fine.

> One line: **FDAI repository prose is fully bilingual; GitHub issues are the
> English-only project-tracking exception.** The other hard constraints are ASCII
> identifiers / filenames / branch names and ASCII punctuation (all tooling or
> collaboration concerns). Machine records (audit / events / log keys / config keys)
> SHOULD stay English for replay and cross-fork search. The `-ko.md` doc pairs and L2
> message catalogs remain the recommended mechanisms for structured bilingual
> delivery.
