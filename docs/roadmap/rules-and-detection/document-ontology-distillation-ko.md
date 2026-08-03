---
translation_of: document-ontology-distillation.md
translation_source_sha: 6524fd338ded248cf29e37b728b4c4690a895148
translation_revised: 2026-08-03
---
# 문서 온톨로지 증류

이 문서는 FDAI가 승인된 운영 문서를 근거 기반 온톨로지 변경 제안으로 변환하는 방법을 정의합니다.
모델 출력은 비활성 상태를 유지합니다. 모델은 claim을 식별하고 typed graph 변경을 제안할 수 있지만,
결정론적 검증과 책임 있는 검토만 온톨로지 revision 반영 여부를 결정합니다.

> **권위 경계:** 문서는 승인된 source authority 범위 안에서 의도, 담당 체계, 절차 및 과거 증거를
> 선언할 수 있습니다. 현재 provider 상태, telemetry, 실행 권한 또는 외부 effect 성공을 증명할 수는
> 없습니다.
>
> **안전 경계:** 증류는 graph, catalog, policy 또는 provider를 직접 변경하지 않습니다.
> `OntologyChangeProposal`을 생성하며, 모호하거나 근거가 없거나 오래되거나 충돌하거나 불완전한
> proposal은 검토 대기 상태가 됩니다.
>
> **고객 경계:** 업로드된 문서, 추출된 text, deployment identity 및 제안된 instance는 승인된
> deployment storage에만 남습니다. Upstream은 generic contract, 결정론적 gate 및 provider seam만
> 제공합니다.
>
> **구현 상태(2026-08-03):** D0-D4 contract, claim inventory, strict proposal compilation,
> deterministic gate, review package, lifecycle plan 및 frozen-corpus scoring을 구현했습니다. D4b는
> canonical `DocumentEnvelope` provenance bridge, 구조화된 Office/PDF locator, OCR fallback 및
> synthetic cross-format conformance를 추가합니다. D4c는 real-document parsing, provider
> conformance 및 annotated public-corpus evaluation을 추가합니다. D4b 결과만으로 production
> extraction 품질을 증명하지 않습니다. D5 promotion assessment는 evidence-only이며 live-shadow
> evidence 또는 automatic promotion을 달성했다고 주장하지 않습니다.

## 한눈에 보는 설계

Pipeline은 추출 전에 claim inventory를 만들어 누락된 문장을 측정할 수 있게 합니다. 그런 다음 각
claim을 기존 ontology declaration에 mapping하고, 정확한 source 근거와 authoritative external
evidence를 검증한 뒤 검토 가능한 graph diff를 stage합니다. 승인된 proposal은 새로운 immutable
revision을 만들며, reconciliation은 승인된 의도와 관측된 외부 사실을 분리합니다.

```mermaid
flowchart LR
    D[승인된 문서] --> I[Claim inventory]
    I --> E[Typed extraction]
    E --> V[결정론적 검증]
    V --> P[Ontology change proposal]
    P --> H[책임 있는 검토]
    H --> R[Immutable ontology revision]
    R --> C[Authority reconciliation]
    C --> S[Shadow measurement]
```

## Proposal contract

`OntologyChangeProposal`은 content-addressed proposal-only record입니다. 다음 내용을 포함합니다.

- proposal id, source document id, immutable document revision, content hash 및 extraction run
- target ontology release와 expected graph revision
- object 또는 link에 대한 add, update, remove 또는 supersede operation 하나
- section 및 1-based inclusive line range가 있는 정확한 source evidence
- claim authority class, effective interval 및 freshness policy
- bounded entity-resolution candidate와 resolution에 성공한 canonical identity
- independent extractor 또는 reviewer의 normalized vote
- deterministic gate receipt, conflict reference 및 proposal digest
- review, projection, reconciliation, supersession, rejection 및 rollback lineage

Lifecycle은 단조롭게 진행합니다.

```text
candidate -> validated -> review_required -> approved -> projected -> reconciled
                  |              |
                  +-> denied     +-> rejected
projected -> superseded | rolled_back
```

같은 source revision, claim, operation 및 target release로 재시도하면 같은 proposal identity가
생성됩니다. Source 또는 target revision이 바뀌면 이전 record를 변경하지 않고 새 proposal을
생성합니다.

## Claim inventory

Coverage는 ontology extraction 전에 시작합니다. Claim inventory는 다음과 같이 운영 의미를 담을 수
있는 모든 문장을 기록합니다.

- normative term, threshold, unit, prohibition 및 conditional branch
- service, workload, resource, environment 및 owner reference
- dependency, containment, implementation 및 escalation relationship
- procedure, action, rollback step, stop condition 및 expected effect
- event-time observation, historical incident 및 declared effective interval

각 claim은 `mapped`, `ignored_with_reason` 또는 `needs_review` 중 정확히 하나로 종료합니다. 중복 claim
id, disposition 누락, 서로 모순되는 중복 disposition 및 알 수 없는 claim을 참조하는 candidate는
검증에 실패합니다. Structural heuristic과 model-backed detector가 모두 claim을 제안할 수 있지만,
결정론적 ledger가 completeness accounting을 수행합니다.

하위 호환성을 위해 각 claim은 `kind`에 하나의 primary `ClaimKind`를 유지하고, 감지된 모든 semantic
class를 순서가 있는 `signals` tuple에 기록합니다. Inventory는 제한된 영어와 한국어 normative,
relationship, threshold 및 imperative 표현을 인식합니다. Technical version과 URL 주변의 sentence
boundary를 보존하고 classification 전에 tag, comment 및 source shortcode를 제거하므로 markup이 claim
text가 되지 않습니다.

## Authority class

Source authority가 eligible proposal operation을 결정합니다.

| Authority class | 문서 사용 | 필요한 reconciliation |
|-----------------|-----------|-------------------------|
| `declared_intent` | objective, ownership, constraint, service map | 승인된 intent source 및 effective interval |
| `procedure` | rule, workflow, ActionType candidate | catalog schema, safety invariant, shadow replay, review |
| `historical_evidence` | incident, outcome, lesson | immutable case 또는 audit evidence |
| `provider_observation` | resource 및 topology statement | fresh Inventory 또는 provider observation |
| `telemetry_observation` | metric 및 health statement | event time이 있는 fresh telemetry evidence |
| `execution_authority` | permission 또는 autonomy statement | 문서로 부여하지 않으며 approved policy가 계속 authoritative함 |

Source precedence는 model confidence가 아니라 authority class와 scope로 구성합니다. 낮은 authority
source는 높은 authority source를 덮어쓸 수 없습니다. 같은 authority의 disagreement는 explicit
conflict로 유지하고 검토 대상으로 보냅니다.

## Extraction 및 identity resolution

Extractor는 제한 없는 document byte가 아니라 bounded structural unit을 받습니다. Schema-constrained
data를 반환해야 하며 source text를 instruction이 아닌 untrusted data로 처리합니다.

1. Extraction 중 heading, table, page, slide, cell 및 line provenance를 보존합니다.
2. Pinned ontology release의 정확한 기존 ObjectType 또는 LinkType만 matching합니다.
3. Identifier, value, unit, polarity, comparison 및 effective time을 normalize합니다.
4. Fuzzy candidate를 사용하기 전에 stable id와 configured alias로 entity를 resolve합니다.
5. Unique identity가 없으면 bounded ambiguous set을 반환하며 instance id를 만들지 않습니다.
6. 기존 type으로 supported claim을 표현할 수 없으면 inert schema change를 제안합니다.

Exact stable-id match는 우선 적용되며 자동으로 resolve합니다. Configured alias는
`VerificationContext`에서 알려진 entity 하나에만 mapping될 때 resolve하며 proposal은 해당 canonical
identity를 bind하고 `method: alias`를 기록합니다. 여러 entity에 mapping되는 alias는 정렬되고 제한된
candidate set을 유지하며 `review_required`를 생성합니다. Unknown add도 review-only로 유지합니다.
Update, remove 및 supersede operation에는 exact 또는 unique-alias identity 하나가 필요합니다. Fuzzy
matching은 identity를 자동 resolve하지 않으며 향후 review-only candidate discovery로 남습니다.
Resolution method와 candidate는 content-addressed proposal identity에 포함됩니다.

## Envelope provenance bridge

Ontology distillation은 safety check를 통과한 `DocumentEnvelope`를 소비하며 uploaded byte를 다시
parse하지 않습니다. Bridge는 비어 있지 않은 structural unit 하나를 normalized manual line 하나로
만들고 해당 line의 source format, unit id 및 locator를 기록합니다. Claim evidence, proposal evidence,
review-package digest 및 replay digest가 이 tuple을 모두 보존하므로 citation이 다른 paragraph, shape,
table cell, page block 또는 speaker note로 이동할 수 없습니다.

Locator는 deterministic grammar와 1-based ordinal을 사용합니다.

- **DOCX:** `docx/paragraph:{n}`, `docx/heading:{level}:{n}` 또는
  `docx/table:{table}/row:{row}/cell:{cell}`. Heading 아래 paragraph content에는
  `/context:heading:{level}:{ordinal}` ancestry suffix를 추가합니다.
- **PPTX:** `pptx/slide:{slide}/shape:{shape}`, multi-paragraph shape의 optional
  `/paragraph:{paragraph}` suffix, `/table:{table}/row:{row}/cell:{cell}` suffix 또는
  `pptx/slide:{slide}/notes:{paragraph}`. Single-paragraph shape locator는 변경하지 않습니다.
- **XLSX:** `xlsx/sheet:{sheet}/cell:{address}`는 source cell address를 보존하고 bounded
  shared-string reference를 resolve합니다.
- **PDF:** native text는 `pdf/page:{page}/block:{block}`, OCR fallback은
  `pdf/page:{page}/ocr:{block}`

`StructuralUnit.table_cell_role`은 optional이며 하위 호환됩니다. DOCX와 PPTX cell은 OOXML table
metadata가 header row를 선언한 경우에만 `header`를 사용하고 다른 table row는 `body`를 사용합니다.
Worksheet cell address만으로 header semantic을 증명할 수 없으므로 XLSX cell에서는 이 field를
설정하지 않습니다. PDF OCR은 provider의 positive page/block ordinal을 보존하고 locator를
canonicalize하기 전에 duplicate, reorder 또는 output-budget overflow를 거부합니다.

각 PDF page는 evidence path를 정확히 하나만 선택합니다. Native text가 있으면 이를 사용하고, 없으면
injected page OCR provider가 bounded cited block을 반환해야 합니다. OCR 부재, encrypted input, parser
damage, unsupported compression, page/count limit 또는 extracted-character limit 초과는 fail closed하며
review package를 만들지 않습니다. OCR은 evidence extraction만 수행하며 executor identity를 받지
않습니다.
Native parsing은 strict mode의 `pypdf`를 사용하고 `pdf/page:{page}/block:{block}` locator를
유지합니다. Byte, page, object, unit 및 character ceiling은 FDAI가 소유하는 boundary로 유지하며,
library error는 document content를 포함하지 않도록 normalize합니다.

Frozen synthetic corpus는 같은 operational claim을 Markdown, DOCX, PPTX, native text PDF 및 scanned
PDF로 표현합니다. Conformance는 source-format과 locator field만 다를 수 있도록 허용하고 normalized
claim, proposal 및 graph operation을 비교합니다. Release에는 critical claim accounting 100%, semantic
또는 citation error 0건, normalized graph difference 0건, critical-claim recall과 entity/link precision
각 0.98 이상 및 모든 format의 replay-stable digest가 필요합니다.

## 실제 corpus 품질 계약

Synthetic fixture는 deterministic contract와 citation 전달을 증명합니다. 독립적으로 작성된 운영
매뉴얼을 extractor 또는 model이 얼마나 잘 처리하는지는 측정하지 못합니다. 따라서 D4c는 safety와
quality evidence를 분리합니다.

- **구조:** Markdown, HTML-like source, Office, native PDF 및 OCR input은 bounded paragraph,
  heading, list, table, slide, page 또는 code unit을 만듭니다. Markup은 claim text가 되지 않습니다.
- **Provider:** Upstream default는 안전하게 abstain할 수 있지만, binding된 `Distiller`가 동일 corpus
  contract를 통과하기 전에는 deployment가 ontology extraction을 available로 보고할 수 없습니다.
- **Corpus:** Versioned manifest는 public source URL, content digest, license, format, language,
  annotated critical claim 및 expected object/link projection을 고정합니다. License가 재배포를
  허용하지 않으면 source text는 package와 repository 밖에 둡니다.
- **Metric:** Report는 detected-claim accounting과 mapped-claim recall, entity/link precision,
  citation accuracy, abstention, parser rejection, latency 및 cost를 구분합니다. Candidate 0개의
  deterministic replay는 안전하지만 extraction 성공으로 계산하지 않습니다.
- **Release:** 필요한 format/language partition이 각각 threshold를 통과합니다. Aggregate score로
  unsupported PDF parser, unbound provider 또는 weak Korean partition을 숨길 수 없습니다.

`ontology_corpus_gate.py`는 rate를 계산하기 전에 integer evidence를 기록합니다. 필요한 각
`(source_format, language)` partition은 case와 extraction-success count, detected/accounted claim,
expected/mapped critical claim, predicted/correct entity/link fact, citation error, parser rejection,
provider abstention, replay mismatch, semantic error 및 latency/cost observation을 유지합니다. 누락된
denominator는 그대로 드러납니다. Candidate 0개의 abstention은 deterministic replay가 stable해도
extraction-success rate가 0입니다.

Release assessment는 세 가지 decision을 사용합니다.

| Decision | 의미 |
|----------|------|
| `pass` | 필요한 모든 partition이 구성된 정확한 threshold를 충족하고 latency와 cost evidence를 가집니다. |
| `review` | Evidence가 누락되거나, extraction이 abstain하거나, parser가 input을 거부하거나, coverage threshold를 충족하지 못했습니다. |
| `deny` | 추출된 output에 citation, replay, semantic, entity 또는 link error가 있습니다. |

Reason code는 `pdf:ko:critical_recall_below_threshold`와 같이 partition key를 유지합니다. 전체
assessment에서는 `deny`가 `review`보다 우선하고 `review`가 `pass`보다 우선합니다. 이 gate는
evidence-only이자 review-only입니다. 통과 결과는 실행 권한을 부여하거나 ontology change를 promote하거나
capability mode를 변경하지 않습니다.

Public-corpus harness는 `tests/evaluation/` 아래 machine manifest를 읽습니다. 각 source entry는 stable
id, HTTPS URL, SHA-256, license id와 license source, format, language, source byte/line count 및 expected
claim signal이 포함된 critical source-line hash를 두 개 이상 고정합니다. Source body는 repository 밖에
둡니다. Caller가 temporary 또는 cache directory를 선택합니다.

`scripts/evaluation/document_ontology_public_corpus.py`는 정확한 source host allowlist만 허용하고,
redirect를 비활성화하며, final URL을 확인하고, timeout/byte ceiling을 적용하고, cache 전에 고정된 byte
count와 SHA-256을 검사합니다. 그런 다음 protection inspection, standard extraction, envelope provenance
bridge 및 claim inventory를 실행합니다. Report에는 id, digest, count, status code 및 partition metadata만
포함되며 source 또는 claim text를 포함하지 않습니다. Test는 local fetcher를 inject하며 network를 사용하지
않습니다. Default report는 provider를 `unbound`로 기록하고 abstention 1건과 extraction success 0건을
계상합니다. Stable empty replay는 이 결과를 바꾸지 않습니다.

Provider conformance는 하나의 명시적 `VerificationContext`와 annotated ontology fact가 포함된 prepared
`ConformanceCase`를 사용합니다. Evaluator는 각 case에서 binding된 `Distiller`를 두 번 호출하고 injected
monotonic clock으로 두 호출을 측정하며, 실제 review package를 만들고 candidate count, abstention reason,
critical recall, entity/link precision, citation/semantic error 및 replay digest를 비교합니다. Test는 cost
evidence를 별도로 inject합니다. Cost measurement 부재는 추론된 zero-cost success가 아니라 missing
evidence로 남습니다.

Binding은 optional `DescribedDistiller` Protocol을 구현하여 versioned
`DistillerCapabilityDescriptor`를 반환할 수 있습니다. 기존 `Distiller` Protocol은 하위 호환됩니다.
Descriptor가 없는 binding은 unavailable로 resolve하고, `AbstainingDistiller`는 `provider_unbound` reason과
함께 abstaining으로 식별됩니다. Pure `resolve_ontology_extraction_capability()` 함수는 descriptor가 현재
conformance contract를 대상으로 하고 필요한 모든 partition이 통과한 경우에만 extraction available을
보고합니다. 이 resolution은 availability만 변경합니다. Feature를 enable하거나 review-only mode를
변경하거나 실행 권한을 부여할 수 없습니다.

`DocumentParserPolicy`는 local parsing을 위한 하나의 immutable, injectable hard ceiling 집합입니다.
Input byte, structural unit, extracted character, Markdown token/nesting, SGML block nesting, OOXML
member count, expanded byte, compression ratio, XML member byte/depth, PDF page, object, raw/decoded
content-stream byte 및 OCR page/unit/character를 제한합니다. Standard inspector와 extractor는 같은 policy를
공유합니다. Azure OCR은 이에 대응하는 immutable source, response, page, line 및 character limit를
사용합니다. Duplicate 또는 reordered OCR citation은 fail closed합니다.

OOXML은 document type과 entity declaration을 거부하고 depth-limited tree builder로 XML을 parse합니다.
SGML parsing은 external entity를 resolve하지 않습니다. Parser/policy error는 bounded category message를
사용하고 source text를 포함하지 않습니다. Markdown, SGML, XML, PDF 및 OCR adversarial fixture가 ceiling과
sanitized outcome을 검증합니다.

Native PDF extraction은 strict `pypdf`를 유지하며 FDAI는 PDF decoder를 직접 구현하지 않습니다. FDAI는
decoded data를 요청하기 전에 compressed raw content-stream byte를 합산하고 각 `pypdf` decode 직후
decoded-byte ceiling을 적용한 다음 page, object, unit 및 character ceiling을 적용합니다. `pypdf`는 allocation
전에 정확한 decoded-byte threshold에서 decompression을 멈출 수 있는 in-process callback을 제공하지
않습니다. 이 residual 때문에 production에서 untrusted PDF를 추출할 때는 독립적인 memory, CPU 및 wall-time
limit가 있는 isolated worker를 사용하는 것이 좋습니다. In-process check는 defense in depth이며 isolation을
대체하지 않습니다.

D4c의 10개 remediation round는 structure, claim semantic, PDF, Office/OCR provenance, identity
resolution, coverage/release gate, public-corpus replay, provider conformance, resource/security bound
및 final independent critique를 다룹니다. 각 round는 구현을 수락하기 전에 falsifying fixture를
추가합니다.

## 검증 gate

Verifier는 executor를 호출하거나 source를 변경하지 않고 proposal 하나를 평가합니다.

| Gate | 필요한 증거 | 실패 결과 |
|------|-------------|-----------|
| Shape | schema, enum, line range, digest 및 target release가 valid함 | `denied` |
| Grounding | cited text가 존재하고 normalized claim을 지원함 | `denied` |
| Claim accounting | claim이 존재하고 disposition이 정확히 하나임 | `denied` |
| Semantic fidelity | polarity, comparison, number, unit, scope 및 time이 보존됨 | `review_required` |
| Identity | canonical target 하나가 증명됨 | `review_required` |
| Authority | source가 해당 scope에서 이 fact class를 주장할 수 있음 | `denied` 또는 `review_required` |
| Conflict | precedence가 deterministic이고 unresolved tie가 보임 | `review_required` |
| External truth | provider 또는 telemetry statement에 fresh authoritative evidence가 있음 | `review_required` |
| Safety | rule, workflow 및 action이 complete safety contract를 충족함 | `denied` |
| Coverage | 모든 claim에 disposition이 있고 critical recall이 release gate를 통과함 | `review_required` |

Model self-reported confidence는 authority signal이 아닙니다. Computed confidence는 grounding,
independent agreement, identity resolution, freshness 및 historical performance를 요약할 수 있지만
eligibility를 낮출 수만 있습니다. Normalized critical field에 대한 independent model disagreement는
검토 대상으로 보냅니다.

## Lifecycle 및 rollback

Document와 graph lifecycle은 immutable digest로 연결됩니다.

- **Revision:** Content 또는 curation 변경은 영향받은 claim과 proposal만 다시 처리합니다.
- **Deletion:** 확인된 source deletion은 bounded tombstone proposal을 생성합니다. Non-empty snapshot에
  대한 empty listing은 suspected source outage이며 graph state를 대량 삭제할 수 없습니다.
- **Access change:** 더 좁아진 source ACL은 derived read를 즉시 차단하고 영향받은 artifact의 제거 또는
  재보호를 예약합니다.
- **Conflict:** 나중의 conflicting source는 accepted history를 다시 쓰지 않습니다. Prior revision과
  conflict receipt에 연결된 새 proposal을 만듭니다.
- **Supersession:** Approved intent는 historical decision context를 변경하지 않고 prior effective
  interval을 교체합니다.
- **Rollback:** Projection failure 또는 later rejection은 exact prior graph revision을 복원하고 failed
  proposal digest를 기록합니다.

Projection과 reconciliation은 별개입니다. Declared intent를 수락하면 governed intent projection을
update할 수 있습니다. Provider-observed statement는 fresh external observation과 일치한 뒤에만 current
truth가 됩니다.

## Agent ownership

기존 pantheon이 새 coordinator 없이 pipeline을 소유합니다.

| Stage | 책임 agent | Output |
|-------|------------|--------|
| Ingress | Huginn | document event |
| Safety 및 source observation | Heimdall | bounded finding |
| Admissibility | Forseti | admit, hold 또는 deny decision |
| Structural index 및 claim ledger | Muninn | immutable context index |
| Inert proposal creation | Norns | proposal candidate |
| Catalog 및 ontology lifecycle | Mimir | reviewed change package |
| Human approval | Var | independent approval |
| Conflict arbitration | Odin | arbitration decision |
| Audit | Saga | append-only lifecycle evidence |
| Rollback | Vidar | rollback outcome |

어떤 stage도 다른 agent를 직접 호출하지 않습니다. Authority-bearing transition은 typed event를
사용하며 graph와 catalog 변경은 reviewed governance proposal로 남기 때문에 document path는 Thor에
도달하지 않습니다.

## 평가 및 promotion

평가는 licensed 또는 synthetic document, annotated claim, expected graph diff, adversarial instruction,
scan, table, conflicting revision, deletion 및 source outage를 포함하는 frozen versioned corpus를
사용합니다. Human annotation은 reviewer identity와 disagreement resolution을 기록합니다.

Release gate는 다음과 같습니다.

- unsupported critical claim 0건
- critical claim의 number, unit, polarity 또는 comparison 변경 0건
- critical claim disposition accounting 100%
- frozen corpus에서 critical-claim recall 0.98 이상 및 entity/link precision 0.98 이상
- competency-query, replay, rollback, deletion 및 ACL regression pass rate 100%
- authority violation, policy escape, wrong-target projection 및 unverified truth claim 0건

초기 capability는 review-only입니다. 이후 promotion은 최소 30일의 distinct live-shadow day와 500개의
eligible reviewed proposal, guard violation 0건 및 0.99 이상의 Wilson 95% precision lower bound를
충족한 low-risk mapping에만 적용을 검토할 수 있습니다. Ownership, objective, constraint, rule,
policy, workflow, ActionType, permission, autonomy, schema change, conflict 및 ambiguous identity는 항상
책임 있는 검토가 필요합니다.

## 제공 순서

| Wave | Deliverable | 종료 기준 |
|------|-------------|-----------|
| D0 | Proposal, claim, evidence, authority, receipt 및 lifecycle contract | invalid identity, range, digest, state 및 authority fixture가 fail closed함 |
| D1 | Claim inventory 및 typed extraction adapter | 모든 detected claim이 정확히 하나의 disposition을 받음 |
| D2 | Grounding, semantic, identity, authority, conflict 및 coverage gate | adversarial 및 ambiguity fixture가 deny 또는 review로만 종료함 |
| D3 | Incremental revision, deletion, ACL, supersession 및 rollback planning | outage가 mass deletion을 만들 수 없고 replay가 exact revision을 복원함 |
| D4 | Review package 및 evaluation report | reviewer가 graph diff, source evidence, gate receipt 및 unresolved claim을 확인함 |
| D4b | Envelope provenance 및 cross-format extraction | 구조화된 locator가 review까지 보존되고 synthetic corpus의 normalized graph diff가 일치함 |
| D4c | 실제 corpus extraction 품질 | 필요한 format/language partition이 provider conformance와 annotated-corpus gate를 통과함 |
| D5 | Shadow measurement 및 limited promotion evidence | authority를 넓히지 않고 statistical 및 zero-violation gate를 통과함 |

## 하드닝 기록

33개의 adversarial round가 proposal path, envelope bridge 및 실제 corpus 후속 구현을 검토했습니다.

| Round | Focus | Result |
|-------|-------|--------|
| 1 | immutable contract 및 replay digest | bounded identifier, scalar value 및 candidate lineage |
| 2 | claim completeness | provider/Korean claim, percent threshold, fence, exact claim accounting |
| 3 | untrusted model output | source-revision pinning, strict key, authority-bound identity, size limit |
| 4 | verifier behavior | unknown-link crash, stale revision, comparator normalization, safety denial |
| 5 | entity 및 link integrity | declared endpoint type, target-resolution binding, operation semantic |
| 6 | conflict 및 external truth | source revision, UTC time, freshness policy, evidence/conflict provenance |
| 7 | review privacy | source access-policy lineage, exact content digest, package bound |
| 8 | lifecycle 및 rollback | projection-only revision change, exact rollback, duplicate retirement rejection |
| 9 | promotion statistics | typed risk class, as-of cutoff, unique evidence, future-observation rejection |
| 10 | integration boundary | package invariant, context bound, correct mixed fence handling |
| 11 | reconciliation isolation | proposal-bound receipt 및 restored current graph revision |
| 12 | boundary format | ontology release digest, RFC 3339 UTC evidence, bounded reference |
| 13 | executable closure | focused test 156개, branch coverage 90.62%, Ruff 및 strict mypy 통과 |
| 14-23 | envelope 및 format hardening | locator identity, Office/PDF/OCR fail-closed parsing, semantic equivalence, replay, bound 및 E2E. Focused test 238개와 branch coverage 90.63% 통과 |
| 24 | structured text | Markdown/SGML block parsing으로 public-corpus unit을 6190개에서 1299개, markup unit을 2084개에서 21개, fragmented boundary를 2112개에서 169개로 줄임 |
| 25 | claim semantic | multi-signal normative, threshold, relationship 및 procedure inventory가 annotated public claim 22/22를 검출함 |
| 26 | production PDF | strict `pypdf`가 page, object, stream, unit 및 character ceiling 아래에서 xref와 object stream을 지원함 |
| 27 | Office 및 OCR provenance | heading context, slide paragraph, table role, XLSX cell 및 exact OCR page/block locator가 extraction을 통과함 |
| 28 | entity resolution | exact/unique configured alias만 resolve하며 unknown, type mismatch 및 ambiguous alias는 bounded unselected 상태로 남음 |
| 29 | partition gate | zero-candidate, zero-citation, zero-prediction, missing-format, weak-language, semantic, citation 및 replay evidence가 vacuous pass할 수 없음 |
| 30 | public corpus | HTTPS source 11개를 SHA-256, license, format, language, size 및 content-free annotation 22개로 고정하고 source body는 repository 밖에 유지함 |
| 31 | provider conformance | 실제 binding을 case마다 두 번 호출하고 partition별로 측정하며 unavailable/abstaining binding은 extraction available을 보고할 수 없음 |
| 32 | parser security | shared limit가 input, nesting, XML, archive, PDF, OCR, unit 및 character를 제한하고 error는 content-free 상태를 유지함 |
| 33 | independent closure | 독립 adversarial audit 3개로 bounded alias, cache, SGML depth, vacuous gate, memory normalization 및 fixture escaping finding을 닫음. Annotation 22/22, parser rejection 0, replay mismatch 0, focused test 372개 및 branch coverage 93.51% 통과 |

D4c mechanism과 public inventory corpus는 검증된 Medium 이상 finding 없이 닫혔습니다. Upstream
`AbstainingDistiller`는 11개 manual 모두에서 candidate 0개를 반환하므로 binding된 provider가
conformance corpus를 통과할 때까지 ontology extraction availability는 false입니다. Checked-in public
corpus는 현재 English Markdown과 SGML을 다룹니다. Deployment가 PDF, Office, OCR 및 Korean provider
partition을 지원한다고 주장하려면 licensed 또는 synthetic annotation이 더 필요합니다. Untrusted PDF
decompression에는 문서화된 isolated-worker requirement도 남습니다. 이 residual은 capability를
review-only로 유지하며 authority를 높일 수 없습니다.

## 검증 매트릭스

| Concern | 필요한 증거 |
|---------|-------------|
| Grounding | 모든 accepted change가 immutable source text와 document revision으로 resolve됨 |
| Completeness | 모든 critical claim에 disposition이 하나 있고 omission이 보임 |
| Identity | Ambiguous 또는 stale target이 자동으로 project되지 않음 |
| Authority | 문서가 current external state를 주장하거나 execution permission을 부여할 수 없음 |
| Security | Untrusted text가 prompt, tool, policy 또는 execution identity를 바꿀 수 없음 |
| Replay | 같은 input과 release가 같은 proposal 및 gate digest를 생성함 |
| Lifecycle | Revision, deletion, outage, ACL, supersession 및 rollback이 bounded되고 audited됨 |
| Customer isolation | Upstream code, fixture 및 docs에 deployment document content가 없음 |

## 관련 문서

| 알아볼 내용 | 문서 |
|-------------|------|
| Upload protection 및 governed storage | [문서 수집](../interfaces/document-ingestion-ko.md) |
| 기존 manual compilation pipeline | [Manual 증류](manual-distillation-ko.md) |
| Shared semantic 및 authority model | [FDAI 운영 온톨로지](../architecture/operating-ontology-ko.md) |
| Proposal-only ontology primitive | [FDAI 온톨로지 안전 인프라](../architecture/operating-ontology-platform-ko.md) |
