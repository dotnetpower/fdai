---
translation_of: document-ontology-distillation.md
translation_source_sha: bb5396629d1d4e7aa4bb721b0d6b9a32a6dad32e
translation_revised: 2026-08-14
---
# 문서 온톨로지 증류

이 문서는 FDAI가 승인된 운영 문서를 근거 기반 온톨로지 변경 제안으로 변환하는 방법을 정의합니다.
모델 출력은 비활성 상태를 유지합니다. 모델은 점유를 식별하고 타입이 지정된 그래프 변경을 제안할 수 있지만,
결정론적 검증과 책임 있는 검토만 온톨로지 개정 번호 반영 여부를 결정합니다.

> **권위 경계:** 문서는 승인된 출처 권한 범위 안에서 의도, 담당 체계, 절차 및 과거 증거를
> 선언할 수 있습니다. 현재 프로바이더 상태, 텔레메트리, 실행 권한 또는 외부 효과 성공을 증명할 수는
> 없습니다.
>
> **안전 경계:** 증류는 그래프, 카탈로그, 정책 또는 프로바이더를 직접 변경하지 않습니다.
> `OntologyChangeProposal`을 생성하며, 모호하거나 근거가 없거나 오래되거나 충돌하거나 불완전한
> 제안은 검토 대기 상태가 됩니다.
>
> **고객 경계:** 업로드된 문서, 추출된 텍스트, 배포 신원 및 제안된 인스턴스는 승인된
> 배포 저장소에만 남습니다. 업스트림은 범용 계약, 결정론적 게이트 및 프로바이더 경계만
> 제공합니다.
>
> **구현 상태(2026-08-03):** D0-D4 계약, 점유 인벤토리, strict 제안 compilation,
> 결정론적 게이트, 검토 패키지, 수명 주기 계획 및 frozen-corpus 채점을 구현했습니다. D4b는
> 정본 `DocumentEnvelope` 출처 이력 브리지, 구조화된 Office/PDF 위치 지정자, OCR 대체 경로 및
> synthetic cross-format conformance를 추가합니다. D4c는 real-document 파싱, 프로바이더
> conformance 및 annotated public-corpus evaluation을 추가합니다. D4b 결과만으로 운영
> 추출 품질을 증명하지 않습니다. D4d는 blind 투표, 결정론적 합의 및 범위가 제한된
> disagreement 근거를 사용하는 tool-free T2 온톨로지 모델 council을 추가합니다. D5 승격
> 평가는 evidence-only이며 live-shadow 근거 또는 automatic 승격을 달성했다고
> 주장하지 않습니다.

## 한눈에 보는 설계

파이프라인은 추출 전에 점유 인벤토리를 만들어 누락된 문장을 측정할 수 있게 합니다. 그런 다음 각
점유를 기존 온톨로지 선언에 대응하고, 정확한 출처 근거와 권위 있는 외부
근거를 검증한 뒤 검토 가능한 그래프 차이를 단계합니다. 승인된 제안은 새로운 변경할 수 없는
개정 번호를 만들며, 조정은 승인된 의도와 관측된 외부 사실을 분리합니다.

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

## 제안 계약

`OntologyChangeProposal`은 내용 기반 주소를 가진 proposal-only 기록입니다. 다음 내용을 포함합니다.

- 제안 id, 출처 문서 id, 변경할 수 없는 문서 개정 번호, 내용 해시 및 추출 실행
- 대상 온톨로지 release와 예상 그래프 개정 번호
- 객체 또는 링크에 대한 add, 갱신, remove 또는 대체 연산 하나
- 섹션 및 1-based inclusive 줄 범위가 있는 정확한 출처 근거
- 점유 권한 등급, effective 간격 및 최신성 정책
- 범위가 제한된 entity-resolution 후보와 해석에 성공한 정본 신원
- 독립적인 추출기 또는 검토자의 정규화된 표결
- 결정론적 게이트 증적, 충돌 참조 및 제안 다이제스트
- 검토, 변환 결과, 조정, supersession, 거절 및 롤백 계보

수명 주기는 단조롭게 진행합니다.

```text
candidate -> validated -> review_required -> approved -> projected -> reconciled
                  |              |
                  +-> denied     +-> rejected
projected -> superseded | rolled_back
```

같은 출처 개정 번호, 점유, 연산 및 대상 release로 재시도하면 같은 제안 신원이
생성됩니다. 출처 또는 대상 개정 번호가 바뀌면 이전 기록을 변경하지 않고 새 제안을
생성합니다.

## 점유 인벤토리

커버리지는 온톨로지 추출 전에 시작합니다. 점유 인벤토리는 다음과 같이 운영 의미를 담을 수
있는 모든 문장을 기록합니다.

- normative 용어, 임계값, 단위, prohibition 및 conditional 가지
- 서비스, 워크로드, 리소스, 환경 및 소유자 참조
- 의존성, containment, 구현 및 에스컬레이션 관계
- procedure, 액션, 롤백 단계, stop 조건 및 예상 효과
- event-time 관측, historical 인시던트 및 declared effective 간격

각 점유는 `mapped`, `ignored_with_reason` 또는 `needs_review` 중 정확히 하나로 종료합니다. 중복 점유
id, 처리 결과 누락, 서로 모순되는 중복 처리 결과 및 알 수 없는 점유를 참조하는 후보는
검증에 실패합니다. Structural heuristic과 model-backed detector가 모두 점유를 제안할 수 있지만,
결정론적 원장이 완전성 accounting을 수행합니다.

하위 호환성을 위해 각 점유는 `kind`에 하나의 기본 `ClaimKind`를 유지하고, 감지된 모든 의미
등급을 순서가 있는 `signals` 튜플에 기록합니다. 인벤토리는 제한된 영어와 한국어 normative,
관계, 임계값 및 imperative 표현을 인식합니다. Technical 버전과 URL 주변의 sentence
경계를 보존하고 분류 전에 tag, comment 및 출처 shortcode를 제거하므로 markup이 점유
텍스트가 되지 않습니다.

## 권한 등급

출처 권한이 조건을 충족한 제안 연산을 결정합니다.

| 권한 등급 | 문서 사용 | 필요한 조정 |
|-----------------|-----------|-------------------------|
| `declared_intent` | 목표, 소유권, 제약, 서비스 지도 | 승인된 의도 출처 및 effective 간격 |
| `procedure` | 룰, 작업 흐름, ActionType 후보 | 카탈로그 스키마, 안전성 불변식, shadow 재생, 검토 |
| `historical_evidence` | 인시던트, 결과, lesson | 변경할 수 없는 사례 또는 감사 근거 |
| `provider_observation` | 리소스 및 토폴로지 구문 | fresh 인벤토리 또는 프로바이더 관측 |
| `telemetry_observation` | 메트릭 및 상태 구문 | 이벤트 시간이 있는 fresh 텔레메트리 근거 |
| `execution_authority` | 권한 또는 자율성 구문 | 문서로 부여하지 않으며 approved 정책이 계속 권위 있는함 |

출처 precedence는 모델 확신도가 아니라 권한 등급과 범위로 구성합니다. 낮은 권한
출처는 높은 권한 출처를 덮어쓸 수 없습니다. 같은 권한의 disagreement는 명시적
충돌로 유지하고 검토 대상으로 보냅니다.

## 추출 및 신원 해석

추출기는 제한 없는 문서 바이트가 아니라 범위가 제한된 structural 단위를 받습니다. 스키마로 제한한
데이터를 반환해야 하며 출처 텍스트를 instruction이 아닌 신뢰할 수 없는 데이터로 처리합니다.

1. 추출 중 heading, 표, 페이지, slide, cell 및 줄 출처 이력을 보존합니다.
2. Pinned 온톨로지 release의 정확한 기존 ObjectType 또는 LinkType만 matching합니다.
3. 식별자, 값, 단위, polarity, 비교 및 effective 시간을 normalize합니다.
4. Fuzzy 후보를 사용하기 전에 고정된 id와 구성된 별칭으로 개체를 해석합니다.
5. Unique 신원이 없으면 범위가 제한된 모호한 집합을 반환하며 인스턴스 id를 만들지 않습니다.
6. 기존 타입으로 supported 점유를 표현할 수 없으면 inert 스키마 변경을 제안합니다.

Exact stable-id 일치는 우선 적용되며 자동으로 해석합니다. 구성된 별칭은
`VerificationContext`에서 알려진 개체 하나에만 대응될 때 해석하며 제안은 해당 정본
신원을 연결하고 `method: alias`를 기록합니다. 여러 개체에 대응되는 별칭은 정렬되고 제한된
후보 집합을 유지하며 `review_required`를 생성합니다. 알 수 없음 add도 review-only로 유지합니다.
갱신, remove 및 대체 연산에는 exact 또는 unique-alias 신원 하나가 필요합니다. Fuzzy
matching은 신원을 자동 해석하지 않으며 향후 review-only 후보 발견으로 남습니다.
해석 메서드와 후보는 내용 기반 주소를 가진 제안 신원에 포함됩니다.

## 묶음 출처 이력 브리지

온톨로지 정제는 안전성 검사를 통과한 `DocumentEnvelope`를 소비하며 uploaded 바이트를 다시
parse하지 않습니다. 브리지는 비어 있지 않은 structural 단위 하나를 정규화된 수동 줄 하나로
만들고 해당 줄의 출처 format, 단위 id 및 위치 지정자를 기록합니다. 점유 근거, 제안 근거,
review-package 다이제스트 및 재생 다이제스트가 이 튜플을 모두 보존하므로 인용이 다른 paragraph, 형태,
표 cell, 페이지 블록 또는 speaker note로 이동할 수 없습니다.

위치 지정자는 결정론적 grammar와 1-based ordinal을 사용합니다.

- **DOCX:** `docx/paragraph:{n}`, `docx/heading:{level}:{n}` 또는
  `docx/table:{table}/row:{row}/cell:{cell}`. Heading 아래 paragraph 내용에는
  `/context:heading:{level}:{ordinal}` ancestry 접미사를 추가합니다.
- **PPTX:** `pptx/slide:{slide}/shape:{shape}`, multi-paragraph 형태의 선택적
  `/paragraph:{paragraph}` 접미사, `/table:{table}/row:{row}/cell:{cell}` 접미사 또는
  `pptx/slide:{slide}/notes:{paragraph}`. Single-paragraph 형태 위치 지정자는 변경하지 않습니다.
- **XLSX:** `xlsx/sheet:{sheet}/cell:{address}`는 출처 cell 주소를 보존하고 범위가 제한된
  shared-string 참조를 해석합니다.
- **PDF:** native 텍스트는 `pdf/page:{page}/block:{block}`, OCR 대체 경로는
  `pdf/page:{page}/ocr:{block}`

`StructuralUnit.table_cell_role`은 선택적이며 하위 호환됩니다. DOCX와 PPTX cell은 OOXML 표
메타데이터가 헤더 행을 선언한 경우에만 `header`를 사용하고 다른 표 행은 `body`를 사용합니다.
Worksheet cell 주소만으로 헤더 의미를 증명할 수 없으므로 XLSX cell에서는 이 필드를
설정하지 않습니다. PDF OCR은 프로바이더의 긍정 페이지/블록 ordinal을 보존하고 위치 지정자를
canonicalize하기 전에 중복, reorder 또는 output-budget 초과분을 거부합니다.

각 PDF 페이지는 근거 경로를 정확히 하나만 선택합니다. Native 텍스트가 있으면 이를 사용하고, 없으면
injected 페이지 OCR 프로바이더가 범위가 제한된 cited 블록을 반환해야 합니다. OCR 부재, encrypted 입력, 파서
damage, 지원하지 않는 압축, 페이지/개수 한도 또는 extracted-character 한도 초과는 실패 시 차단하며
검토 패키지를 만들지 않습니다. OCR은 근거 추출만 수행하며 실행기 신원을 받지
않습니다.
Native 파싱은 strict 모드의 `pypdf`를 사용하고 `pdf/page:{page}/block:{block}` 위치 지정자를
유지합니다. 바이트, 페이지, 객체, 단위 및 character 상한은 FDAI가 소유하는 경계로 유지하며,
library 오류는 문서 내용을 포함하지 않도록 normalize합니다.

고정된 synthetic 말뭉치는 같은 operational 점유를 Markdown, DOCX, PPTX, native 텍스트 PDF 및 scanned
PDF로 표현합니다. Conformance는 source-format과 위치 지정자 필드만 다를 수 있도록 허용하고 정규화된
점유, 제안 및 그래프 연산을 비교합니다. release에는 critical 점유 accounting 100%, 의미
또는 인용 오류 0건, 정규화된 그래프 difference 0건, critical-claim 재현율과 개체/링크 정밀도
각 0.98 이상 및 모든 format의 replay-stable 다이제스트가 필요합니다.

## 실제 말뭉치 품질 계약

Synthetic 고정본은 결정론적 계약과 인용 전달을 증명합니다. 독립적으로 작성된 운영
매뉴얼을 추출기 또는 모델이 얼마나 잘 처리하는지는 측정하지 못합니다. 따라서 D4c는 안전성과
quality 근거를 분리합니다.

- **구조:** Markdown, HTML-like 출처, Office, native PDF 및 OCR 입력은 범위가 제한된 paragraph,
  heading, 목록, 표, slide, 페이지 또는 코드 단위를 만듭니다. Markup은 점유 텍스트가 되지 않습니다.
- **프로바이더:** 업스트림 기본값은 안전하게 abstain할 수 있지만, 연결된 `Distiller`가 동일 말뭉치
  계약을 통과하기 전에는 배포가 온톨로지 추출을 available로 보고할 수 없습니다.
- **말뭉치:** Versioned 매니페스트는 공개 출처 URL, 내용 다이제스트, license, format, 언어,
  annotated critical 점유 및 예상 객체/링크 변환 결과를 고정합니다. License가 재배포를
  허용하지 않으면 출처 텍스트는 패키지와 저장소 밖에 둡니다.
- **메트릭:** 보고는 detected-claim accounting과 mapped-claim 재현율, 개체/링크 정밀도,
  인용 accuracy, abstention, 파서 거절, 지연 시간 및 비용을 구분합니다. 후보 0개의
  결정론적 재생은 안전하지만 추출 성공으로 계산하지 않습니다.
- **release:** 필요한 format/언어 파티션이 각각 임계값을 통과합니다. 집계 점수로
  지원하지 않는 PDF 파서, unbound 프로바이더 또는 weak Korean 파티션을 숨길 수 없습니다.

`ontology_corpus_gate.py`는 비율을 계산하기 전에 정수 근거를 기록합니다. 필요한 각
`(source_format, language)` 파티션은 사례와 extraction-success 개수, detected/accounted 점유,
예상/mapped critical 점유, predicted/correct 개체/링크 사실, 인용 오류, 파서 거절,
프로바이더 abstention, 재생 mismatch, 의미 오류 및 지연 시간/비용 관측을 유지합니다. 누락된
denominator는 그대로 드러납니다. 후보 0개의 abstention은 결정론적 재생이 고정된해도
extraction-success 비율이 0입니다.

release 평가는 세 가지 결정을 사용합니다.

| 결정 | 의미 |
|----------|------|
| `pass` | 필요한 모든 파티션이 구성된 정확한 임계값을 충족하고 지연 시간과 비용 근거를 가집니다. |
| `review` | 근거가 누락되거나, 추출이 abstain하거나, 파서가 입력을 거부하거나, 커버리지 임계값을 충족하지 못했습니다. |
| `deny` | 추출된 출력에 인용, 재생, 의미, 개체 또는 링크 오류가 있습니다. |

사유 코드는 `pdf:ko:critical_recall_below_threshold`와 같이 파티션 키를 유지합니다. 전체
평가에서는 `deny`가 `review`보다 우선하고 `review`가 `pass`보다 우선합니다. 이 게이트는
evidence-only이자 review-only입니다. 통과 결과는 실행 권한을 부여하거나 온톨로지 변경을 promote하거나
기능 모드를 변경하지 않습니다.

Public-corpus 실행 장치는 `services/core-control-plane/tests/evaluation/` 아래 머신 매니페스트를 읽습니다. 각 출처 항목은 고정된
id, HTTPS URL, SHA-256, license id와 license 출처, format, 언어, 출처 바이트/줄 개수 및 예상
점유 신호가 포함된 critical source-line 해시를 두 개 이상 고정합니다. 출처 본문은 저장소 밖에
둡니다. 호출자가 temporary 또는 캐시 디렉터리를 선택합니다.

`scripts/evaluation/document_ontology_public_corpus.py`는 정확한 출처 호스트 허용 목록만 허용하고,
redirect를 비활성화하며, 최종 URL을 확인하고, 시간 초과/바이트 상한을 적용하고, 캐시 전에 고정된 바이트
개수와 SHA-256을 검사합니다. 그런 다음 protection 점검, standard 추출, 묶음 출처 이력
브리지 및 점유 인벤토리를 실행합니다. 보고에는 id, 다이제스트, 개수, 상태 코드 및 파티션 메타데이터만
포함되며 출처 또는 점유 텍스트를 포함하지 않습니다. 테스트는 로컬 가져오기 도구를 inject하며 네트워크를 사용하지
않습니다. 기본값 보고는 프로바이더를 `unbound`로 기록하고 abstention 1건과 추출 성공 0건을
계상합니다. 고정된 빈 재생은 이 결과를 바꾸지 않습니다.

프로바이더 conformance는 하나의 명시적 `VerificationContext`와 annotated 온톨로지 사실이 포함된 prepared
`ConformanceCase`를 사용합니다. 평가기는 각 사례에서 연결된 `Distiller`를 두 번 호출하고 injected
단조 증가 시계로 두 호출을 측정하며, 실제 검토 패키지를 만들고 후보 개수, abstention 사유,
critical 재현율, 개체/링크 정밀도, 인용/의미 오류 및 재생 다이제스트를 비교합니다. 테스트는 비용
근거를 별도로 inject합니다. 비용 측정 부재는 추론된 zero-cost 성공이 아니라 누락된
근거로 남습니다.

연결은 선택적 `DescribedDistiller` 프로토콜을 구현하여 versioned
`DistillerCapabilityDescriptor`를 반환할 수 있습니다. 기존 `Distiller` 프로토콜은 하위 호환됩니다.
서술자가 없는 연결은 사용 불가로 해석하고, `AbstainingDistiller`는 `provider_unbound` 사유와
함께 abstaining으로 식별됩니다. Pure `resolve_ontology_extraction_capability()` 함수는 서술자가 현재
conformance 계약을 대상으로 하고 필요한 모든 파티션이 통과한 경우에만 추출 available을
보고합니다. 이 해석은 가용성만 변경합니다. Feature를 활성화하거나 review-only 모드를
변경하거나 실행 권한을 부여할 수 없습니다.

`DocumentParserPolicy`는 로컬 파싱을 위한 하나의 변경할 수 없는, injectable hard 상한 집합입니다.
입력 바이트, structural 단위, extracted character, Markdown 토큰/중첩, SGML 블록 중첩, OOXML
구성원 개수, expanded 바이트, 압축 ratio, XML 구성원 바이트/깊이, PDF 페이지, 객체, raw/decoded
content-stream 바이트 및 OCR 페이지/단위/character를 제한합니다. Standard inspector와 추출기는 같은 정책을
공유합니다. Azure OCR은 이에 대응하는 변경할 수 없는 출처, 응답, 페이지, 줄 및 character 한도를
사용합니다. 중복 또는 reordered OCR 인용은 실패 시 차단합니다.

OOXML은 문서 타입과 개체 선언을 거부하고 depth-limited 트리 빌더로 XML을 parse합니다.
SGML 파싱은 외부 개체를 해석하지 않습니다. 파서/정책 오류는 범위가 제한된 category 메시지를
사용하고 출처 텍스트를 포함하지 않습니다. Markdown, SGML, XML, PDF 및 OCR adversarial 고정본이 상한과
정제된 결과를 검증합니다.

Native PDF 추출은 strict `pypdf`를 유지하며 FDAI는 PDF decoder를 직접 구현하지 않습니다. FDAI는
decoded 데이터를 요청하기 전에 compressed raw content-stream 바이트를 합산하고 각 `pypdf` decode 직후
decoded-byte 상한을 적용한 다음 페이지, 객체, 단위 및 character 상한을 적용합니다. `pypdf`는 할당
전에 정확한 decoded-byte 임계값에서 decompression을 멈출 수 있는 프로세스 내 콜백을 제공하지
않습니다. 이 잔여 때문에 운영에서 신뢰할 수 없는 PDF를 추출할 때는 독립적인 기억, CPU 및 wall-time
한도가 있는 isolated 워커를 사용하는 것이 좋습니다. 프로세스 내 검사는 defense in 깊이이며 격리를
대체하지 않습니다.

D4c의 10개 교정 라운드는 structure, 점유 의미, PDF, Office/OCR 출처 이력, 신원
해석, 커버리지/release 게이트, public-corpus 재생, 프로바이더 conformance, 리소스/security 한계
및 최종 독립적인 비평을 다룹니다. 각 라운드는 구현을 수락하기 전에 falsifying 고정본을
추가합니다.

## T2 온톨로지 모델 위원회

D4d는 `t2.ontology.council.alpha`, `t2.ontology.council.beta`,
`t2.ontology.council.gamma` 기능 자리 세 개가 모두 available일 때만 ontology-aware
`Distiller`를 연결합니다. 세 자리는 서로 다른 OpenAI 모델 계열로 해석됩니다. 이는
single-publisher 추출 council이며 mixed-publisher council이 아닙니다. 실행 T2의
mixed-publisher quality 게이트를 충족하거나 완화하지 않습니다. Critical 점유는 blind 투표 세 개를
사용합니다. 필요한 blind 투표가 모두 끝나기 전에는 어떤 모델도 다른 표결을 볼 수 없으므로 한
답이 다른 모델을 anchoring하지 못합니다. Council은 Norns 내부 candidate-generation 단계이며 새
에이전트, 권한 채널 또는 실행 경로가 아닙니다.

런타임 연결에는 resolved 기능 세 개와 structured-output 엔드포인트 연결 세 개가 모두
필요합니다. 각 엔드포인트 연결은 null이 아닌 exact 모델 버전, 배포, Entra authentication,
경로, API style 및 검증된 resource-reference 다이제스트를 고정합니다. 이 다이제스트가 모델 신원의 fault
도메인이 됩니다. 다이제스트가 같으면 계정 또는 게이트웨이 fault 도메인을 공유하므로 infrastructure risk가
correlated되었음을 나타냅니다. Council 기록이 하나도 없으면 backward 호환성을 위해 기본
abstaining distiller를 유지합니다. 부분, `hil-only`, mismatched, unversioned, non-Entra 또는 그 밖의
잘못된 council 구성은 온톨로지 추출을 사용 불가로 만들고 시작 연결을
실패시킵니다. 실행 T2 풀을 빌려 쓰거나 기존 실행 quality 게이트를 degrade하지 않습니다.

각 모델은 다음 변경할 수 없는 점유 packet을 동일하게 받습니다.

- 점유 id, exact 출처 assertion, 출처 위치 지정자 및 내용 다이제스트
- pinned 온톨로지 release, allowed 객체/링크 선언 및 범위가 제한된 개체 후보
- 출처 권한 등급과 대상 계약에서 허용한 속성만 포함한 목록
- 도구, web 접근, 운영자 기억, 프로바이더 자격 증명 또는 실행기 신원 없음

표결은 API-level Azure strict `json_schema`와 고정된 12-field 형태를 사용합니다. 모든 필드가 항상
존재합니다. `unsupported`와 `abstain`에서는 제안 필드와 의미 규칙이 null이고 `properties`는
비어 있습니다. `propose`에서는 연산, 대상 종류/타입, 대상 신원, 권한 및 의미 규칙이
null이 아니며 객체 엔드포인트는 null이고 링크 엔드포인트는 null이 아닙니다. Azure-supported 스키마는
nullable fixed 자리를 허용하고 내용이 없는 파서는 스키마 검증 뒤에 처리 결과와 엔드포인트의
cross-field 룰을 적용합니다. 파서는 제안 속성과 의미 문자열 array가 각각 sorted,
unique인지도 검증합니다. 프롬프트는 점유 id와 인용 다이제스트를 정확히 echo하고 supplied 타입,
신원, 엔드포인트, 권한 및 속성 이름만 사용하도록 요구합니다. 제안은 id, 타입, 링크,
속성 이름, 권한 또는 외부 관측을 만들 수 없습니다.
정본 링크 `target_identity`는 resolved `from_identity`이므로 엔드포인트 선택이 의미 없는 모델
disagreement를 만들 수 없습니다. 결정론적 집약기는 점유,
인용, 연산, 대상 종류/타입, 신원, 속성, number, 단위, 비교기, negation, 엔드포인트 및
effective 시간을 비교합니다.

Council 결과는 다음과 같습니다.

| 결과 | 의미 | 후보 동작 |
|---------|------|----------------|
| `consensus` | 필요한 모든 blind 표결의 의미 지문이 같음 | Inert 후보 하나를 만들고 기존 결정론적 게이트 실행 |
| `contested` | Majority가 있지만 하나 이상의 valid 표결이 다름 | Accepted 후보를 만들지 않고 범위가 제한된 필드 difference를 검토에 보존 |
| `unsupported` | 모든 모델이 pinned 온톨로지에 대응할 수 없다고 판단함 | 점유를 `needs_review`로 유지하고 covered로 계산하지 않음 |
| `unresolved` | 정족수 없음, malformed 출력, 시간 초과, 예산 exhaustion 또는 불완전한 맥락 | 점유를 `needs_review`로 유지함 |

구성된 blind 투표 세 개가 모두 필요합니다. 모델 하나라도 시간 초과, 실패, 예산 초과 또는 잘못된
표결을 반환하면 나머지 두 표결이 정확히 일치해도 해당 라운드는 `unresolved`입니다.

Blind 비교 뒤 disputed 점유는 field-difference 비평 한 라운드에 들어갈 수 있습니다. 각
모델은 `keep`, `revise`, `abstain`만 선택하며 original 점유만 인용할 수 있습니다. Raw reasoning과
hidden 추론 과정은 요청하거나 저장하지 않습니다. 비평 packet은 disputed 필드에 대해서만
정본 digest-verified 대안을 포함하고, 세 blind 표결이 이미 합의한 필드에는 정본
기준선을 포함합니다. Critical 점유는 최종 3-of-3 exact agreement가 필요합니다. 2-of-3 결과는
`contested`로 남으며 Judge 모델이 합의로 바꿀 수 없습니다.

`OntologyCouncilReceipt`는 모델 발행기/계열/버전, 배포 연결, 프롬프트/스키마 다이제스트,
온톨로지 release, 점유 packet 다이제스트, initial/revised 표결 다이제스트, 정책, 사용량, 지연 시간, 결과 및
사유 코드를 고정합니다. 모델 실패 텍스트와 출처 텍스트는 증적에 들어가지 않습니다. 모델,
프롬프트, 스키마, 온톨로지 또는 council 정책이 바뀌면 이전 conformance 근거는 무효가 됩니다.
Distiller conformance `binding_version`은 정책과 세 모델 신원의 결정론적 다이제스트이며 정책
다이제스트에는 프롬프트와 스키마 다이제스트가 포함됩니다. 따라서 모델, 프롬프트, 스키마 또는 정책이 바뀌면
이전 conformance 통과를 재사용할 수 없습니다.
가용성은 format/언어 파티션별로 해석하며 council unbound, same-family-only, over 예산,
stale 또는 말뭉치 임계값 미달이면 false를 유지합니다.

## 검증 게이트

검증기는 실행기를 호출하거나 출처를 변경하지 않고 제안 하나를 평가합니다.

| 게이트 | 필요한 증거 | 실패 결과 |
|------|-------------|-----------|
| 형태 | 스키마, enum, 줄 범위, 다이제스트 및 대상 release가 valid함 | `denied` |
| Grounding | cited 텍스트가 존재하고 정규화된 점유를 지원함 | `denied` |
| 점유 accounting | 점유가 존재하고 처리 결과가 정확히 하나임 | `denied` |
| 의미 fidelity | polarity, 비교, number, 단위, 범위 및 시간이 보존됨 | `review_required` |
| 신원 | 정본 대상 하나가 증명됨 | `review_required` |
| 권한 | 출처가 해당 범위에서 이 사실 등급을 주장할 수 있음 | `denied` 또는 `review_required` |
| 충돌 | precedence가 결정론적이고 해결되지 않은 동점이 보임 | `review_required` |
| 외부 truth | 프로바이더 또는 텔레메트리 구문에 fresh 권위 있는 근거가 있음 | `review_required` |
| 안전성 | 룰, 작업 흐름 및 액션이 완전한 안전성 계약을 충족함 | `denied` |
| 커버리지 | 모든 점유에 처리 결과가 있고 critical 재현율이 release 게이트를 통과함 | `review_required` |

모델 self-reported 확신도는 권한 신호가 아닙니다. Computed 확신도는 grounding,
독립적인 agreement, 신원 해석, 최신성 및 historical performance를 요약할 수 있지만
충족 여부를 낮출 수만 있습니다. 정규화된 critical 필드에 대한 독립적인 모델 disagreement는
검토 대상으로 보냅니다.

## 수명 주기 및 롤백

문서와 그래프 수명 주기는 변경할 수 없는 다이제스트로 연결됩니다.

- **개정 번호:** 내용 또는 curation 변경은 영향받은 점유와 제안만 다시 처리합니다.
- **Deletion:** 확인된 출처 deletion은 범위가 제한된 tombstone 제안을 생성합니다. 비어 있지 않은 스냅샷에
  대한 빈 listing은 suspected 출처 장애이며 그래프 상태를 대량 삭제할 수 없습니다.
- **접근 변경:** 더 좁아진 출처 ACL은 derived 읽기를 즉시 차단하고 영향받은 산출물의 제거 또는
  재보호를 예약합니다.
- **충돌:** 나중의 conflicting 출처는 accepted 이력을 다시 쓰지 않습니다. 이전 개정 번호와
  충돌 증적에 연결된 새 제안을 만듭니다.
- **Supersession:** Approved 의도는 historical 결정 맥락을 변경하지 않고 이전 effective
  간격을 교체합니다.
- **Rollback:** 변환 결과 실패 또는 later 거절은 exact 이전 그래프 개정 번호를 복원하고 실패한
  제안 다이제스트를 기록합니다.

변환 결과와 조정은 별개입니다. Declared 의도를 수락하면 통제된 의도 변환 결과를
갱신할 수 있습니다. Provider-observed 구문은 fresh 외부 관측과 일치한 뒤에만 현재
truth가 됩니다.

## 에이전트 소유권

기존 pantheon이 새 조정기 없이 파이프라인을 소유합니다.

| 단계 | 책임 에이전트 | 출력 |
|-------|------------|--------|
| Ingress | Huginn | 문서 이벤트 |
| 안전성 및 출처 관측 | Heimdall | 범위가 제한된 발견 사항 |
| 반입 판단 | Forseti | 반입 허용, 보류 또는 거부 결정 |
| Structural 인덱스 및 점유 원장 | Muninn | 변경할 수 없는 맥락 인덱스 |
| Inert 제안 creation | Norns | 제안 후보 |
| 카탈로그 및 온톨로지 수명 주기 | Mimir | 검토된 변경 패키지 |
| Human 승인 | Var | 독립적인 승인 |
| 충돌 중재 | Odin | 중재 결정 |
| 감사 | Saga | 추가 전용 수명 주기 근거 |
| Rollback | Vidar | 롤백 결과 |

어떤 단계도 다른 에이전트를 직접 호출하지 않습니다. Authority-bearing 전이는 타입이 지정된 이벤트를
사용하며 그래프와 카탈로그 변경은 검토된 거버넌스 제안으로 남기 때문에 문서 경로는 Thor에
도달하지 않습니다.

## 평가 및 승격

평가는 licensed 또는 synthetic 문서, annotated 점유, 예상 그래프 차이, adversarial instruction,
검사, 표, conflicting 개정 번호, deletion 및 출처 장애를 포함하는 고정된 versioned 말뭉치를
사용합니다. Human annotation은 검토자 신원과 disagreement 해석을 기록합니다.

release 게이트는 다음과 같습니다.

- 지원하지 않는 critical 점유 0건
- critical 점유의 number, 단위, polarity 또는 비교 변경 0건
- critical 점유 처리 결과 accounting 100%
- 고정된 말뭉치에서 critical-claim 재현율 0.98 이상 및 개체/링크 정밀도 0.98 이상
- competency-query, 재생, 롤백, deletion 및 ACL 회귀 통과 비율 100%
- 권한 violation, 정책 escape, wrong-target 변환 결과 및 검증되지 않은 truth 점유 0건

초기 기능은 review-only입니다. 이후 승격은 최소 30일의 서로 다른 live-shadow 일과 500개의
조건을 충족한 검토된 제안, 가드 violation 0건 및 0.99 이상의 Wilson 95% 정밀도 lower 한계를
충족한 low-risk 대응에만 적용을 검토할 수 있습니다. 소유권, 목표, 제약, 룰,
정책, 작업 흐름, ActionType, 권한, 자율성, 스키마 변경, 충돌 및 모호한 신원은 항상
책임 있는 검토가 필요합니다.

D4d council 합의는 이 수명 주기 전체에서 inert review-only 제안으로 유지됩니다. Conformance
또는 shadow 근거와 관계없이 그래프를 변경하거나 실행 권한을 부여하거나 기존
결정론적 검증기와 책임 있는 검토를 우회하지 않습니다.

## 제공 순서

| Wave | Deliverable | 종료 기준 |
|------|-------------|-----------|
| D0 | 제안, 점유, 근거, 권한, 증적 및 수명 주기 계약 | 잘못된 신원, 범위, 다이제스트, 상태 및 권한 고정본이 실패 시 차단함 |
| D1 | 점유 인벤토리 및 타입이 지정된 추출 어댑터 | 모든 detected 점유가 정확히 하나의 처리 결과를 받음 |
| D2 | Grounding, 의미, 신원, 권한, 충돌 및 커버리지 게이트 | adversarial 및 모호함 고정본이 거부 또는 검토로만 종료함 |
| D3 | Incremental 개정 번호, deletion, ACL, supersession 및 롤백 계획 수립 | 장애가 mass deletion을 만들 수 없고 재생이 exact 개정 번호를 복원함 |
| D4 | 검토 패키지 및 evaluation 보고 | 검토자가 그래프 차이, 출처 근거, 게이트 증적 및 해결되지 않은 점유를 확인함 |
| D4b | 묶음 출처 이력 및 cross-format 추출 | 구조화된 위치 지정자가 검토까지 보존되고 synthetic 말뭉치의 정규화된 그래프 차이가 일치함 |
| D4c | 실제 말뭉치 추출 품질 | 필요한 format/언어 파티션이 프로바이더 conformance와 annotated-corpus 게이트를 통과함 |
| D4d | T2 온톨로지 모델 council | blind 모델 표결, 결정론적 합의, disagreement 근거, 모델 증적 및 실제 운영 conformance가 권한 추가 없이 통과함 |
| D5 | Shadow 측정 및 limited 승격 근거 | 권한을 넓히지 않고 statistical 및 zero-violation 게이트를 통과함 |

## 하드닝 기록

43개의 adversarial 라운드가 제안 경로, 묶음 브리지, 실제 말뭉치 후속 구현 및 온톨로지 모델
council을 검토했습니다.

| 라운드 | Focus | 결과 |
|-------|-------|--------|
| 1 | 변경할 수 없는 계약 및 재생 다이제스트 | 범위가 제한된 식별자, scalar 값 및 후보 계보 |
| 2 | 점유 완전성 | 프로바이더/Korean 점유, percent 임계값, fence, exact 점유 accounting |
| 3 | 신뢰할 수 없는 모델 출력 | source-revision pinning, strict 키, authority-bound 신원, 크기 한도 |
| 4 | 검증기 행동 | unknown-link 비정상 종료, stale 개정 번호, 비교기 정규화, 안전성 denial |
| 5 | 개체 및 링크 무결성 | declared 엔드포인트 타입, target-resolution 연결, 연산 의미 |
| 6 | 충돌 및 외부 truth | 출처 개정 번호, UTC 시간, 최신성 정책, 근거/충돌 출처 이력 |
| 7 | 검토 privacy | 출처 access-policy 계보, exact 내용 다이제스트, 패키지 한계 |
| 8 | 수명 주기 및 롤백 | projection-only 개정 번호 변경, exact 롤백, 중복 retirement 거절 |
| 9 | 승격 통계 | 타입이 지정된 risk 등급, as-of 기준 시점, unique 근거, future-observation 거절 |
| 10 | 통합 경계 | 패키지 불변식, 맥락 한계, correct mixed fence 처리 |
| 11 | 조정 격리 | proposal-bound 증적 및 restored 현재 그래프 개정 번호 |
| 12 | 경계 format | 온톨로지 release 다이제스트, RFC 3339 UTC 근거, 범위가 제한된 참조 |
| 13 | executable 종결 | focused 테스트 156개, 가지 커버리지 90.62%, Ruff 및 strict mypy 통과 |
| 14-23 | 묶음 및 format 강화 | 위치 지정자 신원, Office/PDF/OCR 실패 시 차단 파싱, 의미 동등성, 재생, 한계 및 E2E. Focused 테스트 238개와 가지 커버리지 90.63% 통과 |
| 24 | 구조화된 텍스트 | Markdown/SGML 블록 파싱으로 public-corpus 단위를 6190개에서 1299개, markup 단위를 2084개에서 21개, fragmented 경계를 2112개에서 169개로 줄임 |
| 25 | 점유 의미 | multi-signal normative, 임계값, 관계 및 procedure 인벤토리가 annotated 공개 점유 22/22를 검출함 |
| 26 | 운영 PDF | strict `pypdf`가 페이지, 객체, 스트림, 단위 및 character 상한 아래에서 xref와 객체 스트림을 지원함 |
| 27 | Office 및 OCR 출처 이력 | heading 맥락, slide paragraph, 표 역할, XLSX cell 및 exact OCR 페이지/블록 위치 지정자가 추출을 통과함 |
| 28 | 개체 해석 | exact/unique 구성된 별칭만 해석하며 알 수 없음, 타입 mismatch 및 모호한 별칭은 범위가 제한된 unselected 상태로 남음 |
| 29 | 파티션 게이트 | zero-candidate, zero-citation, zero-prediction, missing-format, weak-language, 의미, 인용 및 재생 근거가 vacuous 통과할 수 없음 |
| 30 | 공개 말뭉치 | HTTPS 출처 11개를 SHA-256, license, format, 언어, 크기 및 내용이 없는 annotation 22개로 고정하고 출처 본문은 저장소 밖에 유지함 |
| 31 | 프로바이더 conformance | 실제 연결을 사례마다 두 번 호출하고 파티션별로 측정하며 사용 불가/abstaining 연결은 추출 available을 보고할 수 없음 |
| 32 | 파서 security | shared 한도가 입력, 중첩, XML, 보관, PDF, OCR, 단위 및 character를 제한하고 오류는 내용이 없는 상태를 유지함 |
| 33 | 독립적인 종결 | 독립 adversarial 감사 3개로 범위가 제한된 별칭, 캐시, SGML 깊이, vacuous 게이트, 기억 정규화 및 고정본 escaping 발견 사항을 닫음. Annotation 22/22, 파서 거절 0, 재생 mismatch 0, focused 테스트 372개 및 가지 커버리지 93.51% 통과 |
| 34-43 | 모델 council 종결 | 부분 시간 초과, stale conformance 신원, 명시적 모델/사용량 증적, 개정 번호 실패와 필드 범위, malformed 값, 계열/발행기 independence, compromised 신원, digest-verified 비평, 정본 링크 대상 및 실제 운영 말뭉치 재생을 검증함. Focused 테스트 290개 및 가지 커버리지 90.62% 통과 |

D4c 방식과 공개 인벤토리 말뭉치는 검증된 Medium 이상 발견 사항 없이 닫혔습니다. 업스트림
`AbstainingDistiller`는 11개 수동 모두에서 후보 0개를 반환하므로 연결된 프로바이더가
conformance 말뭉치를 통과할 때까지 온톨로지 추출 가용성은 false입니다. Checked-in 공개
말뭉치는 현재 English Markdown과 SGML을 다룹니다. 배포가 PDF, Office, OCR 및 Korean 프로바이더
파티션을 지원한다고 주장하려면 licensed 또는 synthetic annotation이 더 필요합니다. 신뢰할 수 없는 PDF
decompression에는 문서화된 isolated-worker 요구사항도 남습니다. 이 잔여는 기능을
review-only로 유지하며 권한을 높일 수 없습니다.

D4d 실제 운영 검사는 세 pinned 배포 모두에서 Entra-authenticated strict 구조화된 출력을
검증했습니다. 객체 대응 2개와 링크 대응 2개를 포함한 pinned 공개 Markdown 점유 4개를 각각
두 번 평가했습니다. Cost-optional 평가에서 점유 accounting, critical 재현율, 개체 정밀도 및
링크 정밀도는 모두 100%였고 인용, 의미 및 재생 오류와 abstention은 모두 0건이었습니다.
모든 제안은 결정론적 review-only 상태를 유지했고 각 호출의 provider-reported 사용량을
기록했습니다. Azure retail pricing에서 이 모델 버전의 검증된 계측을 제공하지 않았으므로 pricing
근거가 생길 때까지 정본 cost-required 평가와 배포 가용성은 통과하지 않은
상태로 유지합니다.

## 검증 매트릭스

| 관심사 | 필요한 증거 |
|---------|-------------|
| Grounding | 모든 accepted 변경이 변경할 수 없는 출처 텍스트와 문서 개정 번호로 해석됨 |
| 완전성 | 모든 critical 점유에 처리 결과가 하나 있고 omission이 보임 |
| 신원 | 모호한 또는 stale 대상이 자동으로 project되지 않음 |
| 권한 | 문서가 현재 외부 상태를 주장하거나 실행 권한을 부여할 수 없음 |
| Security | 신뢰할 수 없는 텍스트가 프롬프트, 도구, 정책 또는 실행 신원을 바꿀 수 없음 |
| 재생 | 같은 입력과 release가 같은 제안 및 게이트 다이제스트를 생성함 |
| 수명 주기 | 개정 번호, deletion, 장애, ACL, supersession 및 롤백이 범위가 제한된되고 audited됨 |
| Customer 격리 | 업스트림 코드, 고정본 및 docs에 배포 문서 내용이 없음 |

## 구현 상태

### 구현 범위

| 영역 | 상태 | 근거 | 참고 |
|------|------|------|------|
| 제안, 점유 인벤토리, 결정론적 게이트 | implemented | `services/core-control-plane/src/fdai/rule_catalog/pipeline/distill/ontology_claims.py`; `ontology_verify.py`; `ontology_review.py`; `tests/rule_catalog/pipeline/distill/`의 집중 테스트 | D0-D4 계약과 실패 시 차단되는 검토 패키지가 구현되어 있습니다. |
| 묶음 출처 이력 및 형식 동등성 | implemented | `services/core-control-plane/src/fdai/rule_catalog/pipeline/distill/ontology_ingestion.py`; `ontology_evaluation.py`; `tests/rule_catalog/pipeline/distill/test_ontology_format_equivalence.py` | 구조화된 위치와 정규화된 제안 신원을 합성 교차 형식 근거로 검증합니다. |
| 실제 말뭉치 추출 적합성 | in-progress | `services/core-control-plane/src/fdai/rule_catalog/pipeline/distill/ontology_conformance.py`; `ontology_corpus_gate.py`; `tests/rule_catalog/pipeline/distill/test_ontology_conformance.py` | 영어 Markdown 및 SGML 구획은 검증됐습니다. 필수 PDF, Office, OCR, 한국어 주석은 남아 있습니다. |
| T2 온톨로지 모델 위원회 | implemented | `services/core-control-plane/src/fdai/rule_catalog/pipeline/distill/ontology_council.py`; `ontology_council_reducer.py`; `tests/rule_catalog/pipeline/distill/test_ontology_council.py` | 블라인드 투표, 결정론적 합의, 불일치 근거, 범위가 제한된 증적이 권한 없이 구현되어 있습니다. |
| Shadow 측정 및 승격 평가 | in-progress | `services/core-control-plane/src/fdai/rule_catalog/pipeline/distill/ontology_evaluation.py`; [평가 및 승격](#평가-및-승격) | 평가는 검토 전용입니다. 필수 live-shadow 기간, 제안 수, 가격 근거, 자동 승격 제외가 명시적 게이트로 남아 있습니다. |

### 구현 이력

| 날짜 | 상태 | 변경 | 근거 | 남은 작업 |
|------|------|------|------|-----------|
| 2026-08-14 | in-progress | 이전 출처를 재구성하지 않고 구현 원장을 도입했습니다. | `current change`; 구현 범위 표의 현재 소스, 하드닝 기록, 집중 테스트. | 누락된 말뭉치 구획을 닫고 관리되는 shadow 근거를 보존합니다. |

### 남은 작업

- [ ] 필수 PDF, Office, OCR, 한국어 구획에 라이선스가 허용된 주석 또는 합성 주석을 추가하고 연결된 프로바이더로 말뭉치 게이트를 통과합니다.
- [ ] 문서화된 격리 작업자 경계에서 신뢰할 수 없는 PDF 압축 해제를 실행하고 실패 시 차단되는 적합성 근거를 보존합니다.
- [ ] 승격 검토 전에 최소 30개의 서로 다른 live-shadow 일자와 적격 검토 제안 500건을 방어 규칙 위반 없이 보존합니다.
- [ ] 비용이 필수 위원회 게이트인 경우 검증 가능한 모델 가격 근거를 제공하고, 그렇지 않으면 배포 가용성을 미통과로 유지합니다.

## 관련 문서

| 알아볼 내용 | 문서 |
|-------------|------|
| 업로드 protection 및 통제된 저장소 | [문서 수집](../interfaces/document-ingestion-ko.md) |
| 기존 수동 compilation 파이프라인 | [수동 증류](manual-distillation-ko.md) |
| Shared 의미 및 권한 모델 | [FDAI 운영 온톨로지](../architecture/operating-ontology-ko.md) |
| Proposal-only 온톨로지 기본 요소 | [FDAI 온톨로지 안전 인프라](../architecture/operating-ontology-platform-ko.md) |
