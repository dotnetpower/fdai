---
name: i18n-catalog
description: |
  FDAI i18n catalog workflow. FDAI is fully bilingual: English and Korean
  are both allowed in any natural-language text anywhere in the repo (there
  is no english-only gate). This skill covers the structured-localization
  mechanisms: L1 developer docs ship `.md` + `-ko.md` pairs under a SHA
  gate, L2 product surfaces (console, CLI, chatops, notifications, site)
  localize via English-source message catalogs with mandatory English
  fallback, L3 the Bragi narrator renders in the operator's locale.
  Machine records (audit / events / log keys / config keys) SHOULD stay
  English for replay. Load this skill when adding, editing, or reviewing
  localized strings, message catalogs (`messages.{en,ko}.json`), bilingual
  doc pairs, or when a check-catalog-parity / check-translations gate fails.
version: 1.0.0
scope: repository
---

# i18n Catalog Workflow

The short-form contract is
[.github/instructions/language.instructions.md](../../instructions/language.instructions.md)
(always loaded). This skill is the runnable workflow that operationalizes
the four-layer policy across the code, docs, product catalogs, and CI
gates.

## The Layers (recap)

FDAI is **fully bilingual** - Korean is allowed anywhere in natural-language
text; there is no english-only gate. The layers below are **localization
mechanisms** (and a machine-record recommendation), not permission gates.

| Layer | Surface | Mechanism |
|-------|---------|-----------|
| **L0** | code, identifiers, logs, audit entries, event payloads, Rego, config keys | Korean is allowed, but machine records **SHOULD** stay English for replay / correlation. Identifiers / filenames / branch names MUST be ASCII. |
| **L1** | root `README.md` + `docs/**/*.md` | English `.md` + `-ko.md` sibling with a SHA-parity gate. |
| **L2** | operator console, CLI, chatops cards, notifications, docs site | Inline Korean, or English-source message catalogs + `ko` overlay with mandatory English fallback. |
| **L3** | Bragi narrator | Renders in operator locale. |

## L1: Doc Pair (`.md` + `-ko.md`)

Every user-facing markdown doc ships bilingual. Scope = root `README.md`
+ everything under `docs/**/*.md`. `.github/**` and `docs/internals/**`
are English canonical (no required `-ko.md` pair).

### File pair convention

- English is canonical: `foo.md`.
- Korean is a sibling: `foo-ko.md` (never Korean-only).
- The `-ko.md` file carries YAML front-matter:
  ```yaml
  ---
  translation_of: foo.md
  translation_source_sha: <git blob sha of foo.md at translation time>
  translation_revised: 2026-07-05
  ---
  ```
- Compute the SHA with `git hash-object foo.md`.

### Paired-update rule (MUST)

- **Any edit to `foo.md` MUST update `foo-ko.md` in the same PR**, and
  vice versa. Adding a new user-facing `foo.md` MUST add `foo-ko.md`.
- CI enforces this via [`scripts/quality/localization/check-translations.sh`](../../../scripts/quality/localization/check-translations.sh):
  compares `git hash-object foo.md` against the `translation_source_sha`
  recorded in `foo-ko.md`.
- After editing English docs, run
  [`scripts/quality/localization/refresh-translation-sha.py`](../../../scripts/quality/localization/refresh-translation-sha.py)
  to re-sync all pair SHAs at once (only files whose SHA changed are
  rewritten).

### Content rules

- Same information, structure, headings. Translation, not rewrite.
- Preserve unchanged: code blocks, tables of technical values, links,
  filenames, domain vocabulary in backticks (`T0`, `T1`, `T2`, `HIL`,
  `trust-router`, `deterministic-engine`, `rule-catalog`, `risk-gate`,
  `remediation-pr`, `shadow-mode`).
- Cross-references point language-consistently: `foo-ko.md` links to
  `bar-ko.md` (not `bar.md`), unless the target is English-only
  (`.github/**`).

## L2: Message Catalogs

Every L2 surface exposes one catalog pair. English is the source of
truth; Korean MAY lag.

### Where they live

- CLI: [`cli/src/i18n/messages.{en,ko}.json`](../../../cli/src/i18n/)
- Console: [`console/src/i18n/messages.{en,ko}.json`](../../../console/src/i18n/)
- Notifications core:
  [`src/fdai/core/notifications/messages.{en,ko}.json`](../../../src/fdai/core/notifications/)
- Site (Astro Starlight): built-in `locales: { root: {lang: en},
  ko: {lang: ko} }` in `astro.config.mjs` - no separate JSON pair.

### Runtime contract

- **Bilingual source is allowed; catalogs are recommended.** A user-visible
  string MAY be authored in Korean (or English) inline anywhere, or as an
  English key in the catalog. Catalogs are **recommended** for reusable strings
  because they give a mandatory English fallback and keep `en` / `ko` in parity;
  inline Korean is permitted for surface-specific presentation text (there is no
  english-only gate).
- **English fallback is MANDATORY** for catalog strings. A missing or empty
  `ko` key MUST render the English source, never blank / key-name / error.
- Locale resolution order:
  `UserPreference.locale` -> `Accept-Language` -> default `en`.
- Helper contract (mirrors `cli/src/i18n/index.ts`):
  `t(key, locale="en", params?)` with `{name}` interpolation and
  dot-path lookup.

### Catalog-parity gate

- CI runs [`scripts/quality/localization/check-catalog-parity.sh`](../../../scripts/quality/localization/check-catalog-parity.sh):
  every key in `<name>.ko.json` MUST exist in `<name>.en.json`. Orphan
  `ko` keys are blocked; `en` is the source of truth. `ko` MAY be a
  subset (fallback covers it).

### Language gates (there is no english-only gate)

Korean is allowed anywhere in natural-language text; **no CI check blocks it**
(`scripts/check-english-only.sh` has been retired). The language-adjacent gates
that remain are about tooling and structure, not about which language you write:

- **`check-punctuation.sh`** - ASCII punctuation only (no em-dash / en-dash /
  smart quotes / ellipsis char / no-break space), everywhere including `-ko.md`
  and `.ko.json`.
- **`check-translations.sh`** - `foo.md` <-> `foo-ko.md` SHA parity for the L1
  doc-pair convention.
- **`check-catalog-parity.sh`** - `ko` keys are a subset of `en` keys.

Two conventions to keep in mind (not gated): identifiers / filenames / branch
names MUST be ASCII, and an L0 machine record (audit entry, event payload, log
key, config key, identifier, serialized verdict) SHOULD stay English for replay
and cross-fork search - localize the labels around it, not the record itself.

## L3: Bragi Narrator

- Bragi renders the final natural-language answer in
  `UserPreference.locale`. Everything beneath the answer (intent,
  tool calls, verdict, audit entry) stays English (L0).
- A localized phrasing MUST NOT change what the typed pipeline
  decides. The narrator is a presentation translator, never a judge.

## Punctuation and Formats

- **ASCII punctuation only** (blocked by
  [`scripts/quality/repository/check-punctuation.sh`](../../../scripts/quality/repository/check-punctuation.sh)):
  `-`, `"`, `'`, `...`. No em-dash / en-dash / smart quotes /
  ellipsis character / no-break space. This applies inside `-ko.md`
  and inside `.ko.json` too.
- Auto-fix: `python3 scripts/quality/localization/normalize-punctuation.py` (fence-aware
  for `.md`; add `--whole-file` for source files whose content is
  entirely code).
- Timestamps: ISO 8601 / RFC 3339. Decimal separator `.`; no digit
  grouping in machine values.

## Common Failure Modes

- **Catalog-parity failure**: a `ko` key without an `en` peer. Fix by
  adding the English source key first, then translating (or removing
  the orphan `ko` key). Never invent `ko` keys the `en` catalog
  doesn't have.
- **Translation-pair failure**: `git hash-object foo.md` does not
  match the `translation_source_sha` in `foo-ko.md`. Update the
  Korean file to reflect the English edit, then run
  `refresh-translation-sha.py`.
- **English-only failure**: Hangul or CJK appeared in a `.py` / `.ts`
  / `.yaml` / test file. Move it to the correct `.ko.json` or
  `-ko.md` sibling, or escape it (`\uXXXX`) if it is a literal
  fixture that must stay in code.
- **Punctuation failure**: an em-dash or smart quote snuck in via
  copy-paste. Run `normalize-punctuation.py`.

## Verify

Before every commit that touches L1 or L2:

```
bash scripts/verify.sh --fast
```

The `--fast` bundle runs all four gates: `english-only`,
`punctuation`, `translations`, `catalog-parity` (plus ruff + guids).

## Related

- Language contract:
  [.github/instructions/language.instructions.md](../../instructions/language.instructions.md).
- Repo-scoped implementation notes:
  [`/memories/repo/i18n.md`](../../../.github/copilot-instructions.md) (memory listing).
- Runnable prompt:
  [.github/prompts/verify.prompt.md](../../prompts/verify.prompt.md).
