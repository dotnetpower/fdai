---
description: "Use when editing Python, TypeScript, JavaScript, shell, or Terraform source. Covers bilingual literals, ASCII identifiers, stable machine records, and product strings."
applyTo: "**/*.{py,ts,tsx,js,sh,tf}"
---

# Source Language Policy

This concise contract applies language and localization rules to source code without loading the
full documentation, translation-pair, and catalog authoring reference. The detailed policy remains
in [language.instructions.md](language.instructions.md).

## Source text

- English is the canonical source and mandatory fallback. Korean is fully supported in comments,
  docstrings, string values, logs, tests, fixtures, and regular expressions. Korean is never a
  defect merely because it is Korean.
- Identifiers, filenames, and branch names MUST stay ASCII. Use Korean in natural-language values,
  never in code symbols or paths.
- Use ASCII punctuation only: `-`, `"`, `'`, and `...`. Smart quotes, Unicode dashes, the Unicode
  ellipsis, and no-break spaces are blocked by the repository punctuation gate.
- Commit Korean literals as readable NFC UTF-8. Do not replace Hangul with `\uXXXX`, HTML,
  percent-encoded, or byte escapes unless the code explicitly tests Unicode or wire-format
  behavior and the escape is allowlisted.
- Do not hand-edit generated or vendored code. Fix the generator and regenerate its output.

## Runtime and machine output

- Audit fields, event payloads, serialized decisions, log keys, rule ids, config keys, and canonical
  contract tokens SHOULD remain English for replay and cross-system correlation.
- Runtime errors MUST be English, actionable, and free of secrets or customer-identifying values.
- Reusable product strings SHOULD use the English-source message catalog with Korean overlay and
  mandatory English fallback. Inline Korean remains valid for one-off internal text.
- Keep canonical tokens such as `verdict`, `hil`, and `stewardship` in identifiers and serialized
  values. Map them to plain localized labels on user-facing surfaces.
- Bragi renders the final answer in the operator locale, while typed intent, tool calls, decisions,
  and audit records remain canonical English machine records.
- Machine timestamps use ISO 8601 / RFC 3339, decimal values use `.`, and machine-readable numbers
  use no digit grouping.

## Collaboration

GitHub issue titles, bodies, and comments MUST be English. Live maintainer chat may use English or
Korean. Load [language.instructions.md](language.instructions.md) and the i18n catalog skill when a
source change also modifies documentation pairs or localization catalogs.
