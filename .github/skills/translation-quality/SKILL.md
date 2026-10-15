---
name: translation-quality
description: |
  Judge and repair the quality of Korean technical prose in FDAI docs and
  product text, including `-ko.md` translations. Load this skill when writing,
  revising, or reviewing Korean technical documentation, when Korean sounds
  translated or unnatural, when a `check-translation-quality` finding appears,
  when deciding whether a term stays English, or before bulk term substitution.
  The always-loaded contract is `.github/instructions/language.instructions.md`;
  the sync/catalog workflow is the `i18n-catalog` skill.
version: 1.1.0
scope: repository
---

# Korean Technical Prose Quality

Korean technical prose can be grammatically valid and still be difficult to
read. A `-ko.md` file can also pass every freshness gate while retaining English
word order, excessive nominalization, vague subjects, or misleading certainty.
The failure mode looks like this:

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

## Editing priorities

Apply these priorities in order:

1. Preserve technical accuracy and facts.
2. Preserve the original intent and meaning.
3. Use natural, clear Korean.
4. Improve concision and readability.
5. Keep terminology and voice consistent.

Natural phrasing MUST NOT change technical meaning, safety conditions,
authorization scope, validation strength, implementation status, or confidence.
Do not hide a contradiction by rewriting it. Flag the contradiction for the
author when the source claims cannot both be true.

## Prefer natural, concrete Korean

### Remove translation-shaped phrasing

Review noun chains, copied English passive voice, bureaucratic abstractions,
repeated connectors, and sentences made mostly of abstract nouns. Prefer a
direct Korean verb when it expresses the same action:

| Avoid | Prefer |
|-------|--------|
| 운영 이상에 대한 판단을 수행합니다. | 운영 이상을 파악합니다. |
| 기능의 구현 여부에 대한 확인이 필요합니다. | 기능이 구현되었는지 확인해야 합니다. |
| 작업 결과에 대한 검증을 진행합니다. | 작업 결과를 검증합니다. |
| 해당 기능을 통한 대응의 지원을 제공합니다. | 해당 기능으로 운영자의 대응을 지원합니다. |
| 상태에 대한 모니터링을 수행합니다. | 상태를 모니터링합니다. |
| 구성의 변경을 실시합니다. | 구성을 변경합니다. |
| 평가 기록과의 일치 여부를 확인합니다. | 평가 기록과 일치하는지 확인합니다. |

Keep a nominal form when it is the established technical term or when a title,
table heading, API specification, data model, or requirement identifier needs a
compact noun phrase.

### Name the action and object

Prefer the actual action and object over a generic abstraction:

| Vague | More concrete when supported by the source |
|-------|--------------------------------------------|
| 근거를 바탕으로 판단합니다. | 수집한 정보와 분석 결과를 바탕으로 판단합니다. |
| 증거를 수집합니다. | 관련 로그와 메트릭을 수집합니다. |
| 상태를 확인합니다. | 리소스 상태와 최근 변경 이력을 확인합니다. |
| 문제를 해결합니다. | 오류를 수정합니다. / 서비스를 재시작합니다. / 원인을 분석합니다. |

Never invent an object, operation, data source, or result that the source does
not provide. When the source is nonspecific, improve only the sentence
structure. If a technically important referent such as `해당 기능`, `관련 정보`,
or `이 결과` remains ambiguous, ask the author instead of guessing.

### Use Korean information order

- Do not load one sentence with conditions, actions, exceptions, results, and
  constraints. Split it at meaning boundaries without separating an action
  from its authorization or safety condition.
- Keep the subject and object explicit when omission creates ambiguity.
- Avoid habitual repetition of `또한`, `아울러`, `이와 함께`, `이를 기반으로`,
  `해당`, and `관련`.
- Put the main action where readers can find it quickly. Do not stack a long
  chain of modifiers before the noun.
- Preserve repeated text when each occurrence carries a distinct condition,
  exception, responsibility, or limitation.

For example:

```
운영자가 작업을 직접 승인하거나 유효한 사전 권한을 부여하면 에이전트가
허용된 범위에서 작업을 수행합니다. 작업이 끝나면 결과를 검증하고 감사
기록을 남깁니다.
```

Splitting this sentence must not weaken the logical relationship between
authorization and execution.

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
| planner | 플래너 | evidence in prose | 문맥에 따라 정보, 근거, 증거, 징후 |
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

## Choose words by the promised level

The following words are not interchangeable. Select the word that matches the
actual input, action, and confidence:

| Term | Use |
|------|-----|
| 정보 | Logs, metrics, events, configuration values, and other material used for analysis in general. |
| 근거 | Information that explains why a specific judgment or conclusion is warranted. |
| 증거 | Material that is explicitly evidentiary in a legal, forensic, security-investigation, or similarly strict context. |
| 징후 | A signal that suggests an incident or anomaly without establishing its cause. |
| 확인 결과 | A fact observed through an inspection or test. |
| 판단 이유 | A user-facing explanation of how the conclusion was reached. |
| 증적 | An established receipt or audit artifact, not a generic synonym for information. |

Examples to review in context, not mechanically replace:

| Existing phrase | Prefer when accurate |
|-----------------|----------------------|
| 증거에 따르면 | 확인 결과 / 로그를 보면 / 데이터에 따르면 |
| 증거가 발견되었습니다. | 관련 정보가 확인되었습니다. / 이상 징후가 나타났습니다. |
| 근거가 부족합니다. | 판단에 필요한 정보가 부족합니다. |
| 입증합니다. | 보여 줍니다. / 확인할 수 있습니다. |
| 판단의 근거 | 판단 이유 / 판단에 사용한 정보 |
| 구현 여부에 대한 확인 | 구현 여부를 확인 |
| 담당 기록과 대조 | 담당 평가 기록과 대조 |
| 기능 완성도 | 구현 수준 / 검증 상태 / 기능 준비 상태 |
| 남은 조건 | 미충족 조건 / 추가 확인 사항 |
| 상태명은 정의 절로 연결 | 상태명을 선택하면 해당 정의로 이동 |
| 기능명은 개별 근거로 연결 | 기능명을 선택하면 관련 평가 기록으로 이동 |

Use `확인` to inspect a fact or state, `검증` to compare it with a defined
criterion or expected result, `판단` to reach a conclusion from analyzed
information, `감지` to detect a state or signal, and `추정` to describe a likely
state or cause that has not been sufficiently confirmed. Do not swap these as
stylistic synonyms.

Use `게시용 빌드` only when publishing is the actual operation. Use `배포용 빌드`
for a deployment artifact. Prefer `브라우저에서의 실제 페이지 이동` over
`실제 브라우저 이동` when the intended meaning is browser navigation.

## Preserve technical certainty

Never change any of these distinctions during language editing:

- implemented versus planned functionality
- supported versus unsupported targets
- direct user approval versus standing authorization
- authenticated execution identity versus user credentials
- test success versus validation in a live environment
- observed fact versus inferred cause
- partial support versus complete support
- exact numbers, dates, versions, counts, and test totals
- security policy, permission conditions, exceptions, and safeguards
- the scope supported by sources and assessment records

Forbidden upgrades include:

- `테스트를 통과했습니다.` -> `운영 환경에서 정상 동작합니다.`
- `이상 징후가 확인되었습니다.` -> `원인이 확정되었습니다.`
- `자동 조치를 지원합니다.` -> `모든 조치를 자동 수행합니다.`
- `일부 리소스를 지원합니다.` -> `Azure 리소스를 지원합니다.`
- `구현 후보` -> `구현 완료`

## Apply the document's contract

- **Functional specifications and requirements:** distinguish offered
  functionality from implemented functionality. Preserve the actor, input,
  processing, result, conditions, requirement IDs, acceptance criteria, scope,
  and limitations. Do not mix feature description with implementation status.
- **Architecture and design:** state component responsibilities and interactions
  directly. Keep protocol, API, and data-model names intact. Separate design
  intent from current implementation and proposals from accepted design.
- **Test and assessment reports:** distinguish passed, failed, and not-run tests;
  local, integration, and live validation; and a bounded assessment from overall
  product readiness. Do not broaden what the result guarantees.
- **User guidance and progress updates:** use short, direct sentences. Separate
  what was checked from what remains, reduce ceremonial repetition, and make the
  next expected event clear.

Within one document and project, use one term for one concept. Prefer the
project glossary when it exists. Keep these distinctions stable: `기능` is a
product capability; `요구사항` is a condition to satisfy; `구현` realizes it in
code or configuration; `테스트` is a procedure that checks behavior; `검증`
judges conformance to defined criteria; `운영 확인` observes behavior in the
live environment; `지원 범위` names actual supported targets and operations;
and `준비 상태` reports implementation and validation against defined criteria.

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

Before running tools, review each changed document in this order:

1. Identify its purpose, audience, and document type.
2. Protect technical terms, numbers, identifiers, links, code, and authority conditions.
3. Find translated syntax, awkward order, excessive nominalization, ambiguous references, and repetition.
4. Rewrite for natural Korean without adding facts.
5. Recheck certainty, conditions, exceptions, and technical responsibility.
6. Recheck terminology consistency.
7. Confirm Markdown structure, tables, code blocks, links, IDs, and numbers remain intact.
8. Read the result as a Korean reader would.

When the user requests editing, return the complete corrected document by
default and preserve its headings, sections, tables, lists, links, and IDs where
possible. Leave sentences that need no change alone. Explain a potentially
meaning-changing correction separately. If the user requests only corrected
text, do not append a long rationale.

Select only changed task-owned paths and reuse passing evidence under
[Testing](../../instructions/coding-conventions.instructions.md#testing). Run these checks for a
completed translation batch, not after unrelated edits or merely because a commit was created:

```bash
python3 scripts/quality/localization/check-translation-quality.py <changed-ko-paths>
bash scripts/quality/localization/check-translations.sh <changed-doc-paths>
bash scripts/quality/repository/check-punctuation.sh <changed-files>
python3 scripts/quality/localization/check-readable-hangul.py <changed-files>
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
