---
name: translation-quality
description: |
  How to judge and repair the *quality* of Korean prose in FDAI `-ko.md`
  docs, as opposed to its freshness. `check-translations.sh` only proves a
  translation is in sync with its English source; it says nothing about
  whether the Korean reads as Korean. Load this skill when writing or
  reviewing a `-ko.md` file, when a `check-translation-quality` finding
  appears, when deciding whether a term stays English, or before running any
  bulk term substitution across docs. The always-loaded contract is
  `.github/instructions/language.instructions.md`; the sync/catalog workflow
  is the `i18n-catalog` skill.
version: 1.0.0
scope: repository
---

# Translation Quality

A `-ko.md` file can pass every existing gate and still be unusable. The
failure mode looks like this:

```
Validator는 알 수 없는 capability, cycle, 해결되지 않은 dependency,
잘못된 argument, scope 날조, confirmation draft 밖의 write를 차단합니다.
```

Only the particles are Korean. A reader who does not already know the English
gets nothing from it. The same sentence after a quality pass:

```
검증기는 알 수 없는 기능, 순환 참조, 해결되지 않은 의존성, 잘못된 인자,
범위 날조, 확인 초안을 벗어난 쓰기를 차단합니다.
```

**Rule: if a word has an ordinary Korean equivalent, translate it. Keep
English only when the English token is itself the identifier.**

## What stays English

| Category | Examples |
|----------|----------|
| Code identifiers, schema values, config keys | `advise_only`, `graph_at`, `truncated`, `FDAI_WEB_SEARCH_ENABLED`, `execution_authority: false` |
| Ontology type names | `ObjectType`, `LinkType`, `FunctionType`, `ObjectSet`, `Interface`, `ActionType`, `ActionRun` |
| Domain vocabulary fixed by the language contract | `shadow`, `shadow-mode`, `trust-router`, `deterministic-engine`, `rule-catalog`, `risk-gate`, `remediation-pr`, `HIL`, `T0`/`T1`/`T2` |
| Product names, in full | `Managed Identity`, `Virtual Network`, `Activity Log`, `Key Vault`, `Container Apps`, `Log Analytics`, `Azure SQL Managed Instance` |
| Filenames and paths, including link display text | `architecture.instructions.md`, `language.instructions.md` |
| Established loanwords in this repo | `principal`, `release` |
| Acronyms | `API`, `JSON`, `SPA`, `RBAC`, `DAG`, `SLO`, `MTTR` |

Everything else is ordinary vocabulary and gets translated.

## Term standard

Reuse these renderings so docs agree with each other.

| English | Korean | English | Korean |
|---------|--------|---------|--------|
| planner | 플래너 | evidence | 근거 |
| validator, verifier | 검증기 | capability | 기능 |
| executor | 실행기 | goal | 목표 |
| compiler | 컴파일러 | task | 작업 |
| coordinator | 조정기 | receipt | 증적 |
| registry | 레지스트리 | projection | 변환 결과 |
| manifest | 매니페스트 | envelope | 묶음 |
| descriptor | 서술자 | disposition | 처리 결과 |
| narrator | 서술기 | clarification | 명확화 |
| bounded | 범위가 제한된 | cutoff | 기준 시점 |
| grounded | 근거에 기반한 | window | 구간 |
| traversal | 탐색 | predicate | 조건식 |
| declaration | 선언 | generation | 세대 |
| control plane | 컨트롤 플레인 | data plane | 데이터 플레인 |

Section headings are translated too (`## Migration` -> `## 이행 계획`,
`## Current gaps` -> `## 현재 미비점`).

Preserve verbatim: fenced code blocks, YAML examples, mermaid blocks, link
targets, and tables of technical values.

## Bulk substitution: four ways it goes wrong

Term substitution across many files is efficient and is how most of
`docs/roadmap` was translated. Every one of these defects happened during
that work, and each is now a `check-translation-quality` rule.

### 1. A product name loses its second word

`Managed Identity` became `Managed 신원`, `Virtual Network` became
`Virtual 네트워크`. Protect multi-word product names as whole phrases before
substituting single words.

```
grep -rnoP '(Managed|Diagnostic|Virtual|Flexible|Cognitive)\s+\p{Hangul}+' docs/ --include='*-ko.md'
```

Expect false positives after a protected phrase, such as `Activity Log 어댑터`,
which is correct.

### 2. Markdown indentation collapses

A "two spaces -> one space" cleanup applied to the whole document, including
protected regions, flattened nested lists in 104 docs. **Never normalize
whitespace globally.** Compare against the English source:

```
python3 scripts/quality/localization/check-translation-quality.py docs/**/*-ko.md
```

If it already happened, the collapse is a non-overlapping `"  " -> " "` pass,
so the inverse is `1 -> 2` and `2 -> 3`. Confirm with a leading-space
histogram of the last intact revision before restoring.

### 3. A fixed domain term gets translated

`shadow` became a Korean word in 459 places. Terms in the domain-vocabulary
row above are identifiers, not prose. Keep them out of the term map.

### 4. An adjective is spliced onto a verb ending

`bounded -> 범위가 제한된` is right in a noun phrase and wrong where the
English used a verb, producing `범위가 제한된하고`, `완전한합니다`,
`있는합니다`. Detect with:

```
grep -rnoP '\p{Hangul}+(된|는|한)(합니다|하고|하며|했습니다)' docs/ --include='*-ko.md'
```

`제한합니다` and `유한하지` are legitimate and already allowlisted.

## Repairing a damaged file

Rebuild from the last revision whose text was still intact, then re-apply the
term pass:

```
git log --format='%H%x09%s' -- <file>     # first commit not authored by the term pass
git show <baseline>:<file> > <file>
```

Two cautions learned the hard way:

- **Check for newer commits by others first.** Rebuilding from an old
  baseline silently reverted another session's published translation in six
  files; `check-translations` caught it as stale. If the English moved after
  the baseline, port that diff by hand and refresh `translation_source_sha`.
- **Never rebuild a file another session is editing.** Wait for their commit.

## Verify

```
python3 scripts/quality/localization/check-translation-quality.py
bash scripts/quality/localization/check-translations.sh
bash scripts/quality/repository/check-punctuation.sh <files>
python3 scripts/quality/localization/check-readable-hangul.py <files>
```

An accepted finding goes in
`scripts/quality/localization/translation-quality-allowlist.txt` as
`<path>:<rule>:<detail>`, with the reason in review.

## Related

- Language contract:
  [.github/instructions/language.instructions.md](../../instructions/language.instructions.md).
- Doc-pair sync, message catalogs, and gate failures:
  [i18n-catalog skill](../i18n-catalog/SKILL.md).
- Documentation tone and structure:
  [documentation-writing skill](../documentation-writing/SKILL.md).
