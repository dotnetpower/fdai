---
description: Language and naming policy for all AIOpsPilot artifacts.
applyTo: "**"
---

# Language Policy

## Scope

This policy governs everything **committed to this repository** and everything the
control plane **emits at runtime** (logs, error strings, audit records, generated PRs).
It does not govern live maintainer chat. Related rules live in
[coding-conventions.instructions.md](coding-conventions.instructions.md) (commits/PRs)
and [generic-scope.instructions.md](generic-scope.instructions.md) (no customer data).

## Rule

- **English is the only allowed natural language** for everything committed to this
  repository. Any other natural language (Korean, etc.) is a defect unless it falls
  under [Allowed Exceptions](#allowed-exceptions) or the
  [User-Facing Doc Translations](#user-facing-doc-translations-ko) carve-out below.
  This applies to:
  - source code, identifiers, comments, and docstrings
  - `.github/**` (copilot-instructions, instructions/*, workflows, issue/PR templates) —
    **English-only, no translations, no exceptions**
  - commit messages, branch names, PR titles and descriptions
  - tests, fixtures, sample data, and config files
  - log messages, error strings, audit entries, and source strings for user-facing text
- **Identifiers, filenames, and branch names must be ASCII** (`a-z A-Z 0-9 _ - .`).
  No accented letters, CJK, or emoji in code symbols or paths.
- **Korean is allowed only in interactive maintainer chat** and in the
  `-ko.md` translation files defined below. It must never appear in code, config,
  commits, tests, or `.github/**`.

## Allowed Exceptions

Non-English or non-ASCII text is permitted **only** in these cases:

- **Proper nouns**: third-party product, library, vendor, or standards names spelled as
  their owners spell them.
- **Quoted data**: a non-English string that is the literal subject under test (parser,
  encoding, i18n fixtures). Encode it explicitly (`\uXXXX` or UTF-8 bytes) and add a
  one-line English comment or an allowlist marker explaining why it is present.
- **Vendored / generated code**: files under a clearly marked third-party or generated
  path are exempt; do not hand-edit them to translate comments.
- **Localization**: product UI may ship translations, but the **source strings are
  English** and translations live in dedicated resource files (e.g., `messages.<locale>.json`),
  never inline in code.
- **Emoji**: not allowed in code, identifiers, commit messages, or PR titles; allowed in
  docs only when they add meaning, never as a substitute for words.

## User-Facing Doc Translations (`-ko.md`)

User-facing Markdown documentation ships bilingually. This is the **only** place in the
repository where a natural language other than English is permitted in committed text.

**Scope (translatable)**

- Root `README.md`
- Everything under `docs/**/*.md`

**Out of scope (English-only, no translation)**

- Everything under `.github/**` — `copilot-instructions.md`, `instructions/*.md`,
  workflows, issue and PR templates. These are project guidelines, not user docs.
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

## Formats (machine-parseable)

- Dates and timestamps use **ISO 8601 / RFC 3339** (`2026-07-03`, `2026-07-03T09:15:00Z`).
- Use `.` as the decimal separator and no digit-grouping in machine-read values.
- Prefer plain ASCII punctuation (`-`, `"`, `'`) over smart quotes and em-dashes in code
  and config; unicode typography in prose is discouraged where it affects diff or grep.

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
- Bad: a comment or commit body written in Korean, or a non-ASCII identifier.
- Good fixture: `{"input": "\uD55C\uAE00", "note": "non-ASCII parse case"}` (encoded + explained).
- Bad fixture: a raw non-English sentence with no encoding or explanation.

## Automation & Review Check

- **Automated gate**: a CI / pre-commit check should flag non-ASCII natural-language runs
  outside the allowlist. A practical detector is any match of Hangul (`\uAC00-\uD7A3`,
  `\u1100-\u11FF`) or CJK (`\u4E00-\u9FFF`) ranges in tracked text files, **excluding**
  the `-ko.md` translation files defined above.
- **Translation-pair gate**: `scripts/check-translations.sh` runs in CI and enforces
  the [paired-update rule](#user-facing-doc-translations-ko): every in-scope `foo.md`
  has a `foo-ko.md`, every `foo-ko.md` has front-matter with `translation_of` and
  `translation_source_sha`, and each `translation_source_sha` matches the current
  `git hash-object` of the source file.
- **PR review**: if any non-English text appears in a diff outside live chat, the
  [Allowed Exceptions](#allowed-exceptions), or a `-ko.md` file, treat it as a defect
  and correct it before merge, per
  [coding-conventions.instructions.md](coding-conventions.instructions.md).

> One line: English is canonical; `docs/**/*.md` and root `README.md` ship as
> `.md` + `-ko.md` pairs; `.github/**` and code stay English-only.
