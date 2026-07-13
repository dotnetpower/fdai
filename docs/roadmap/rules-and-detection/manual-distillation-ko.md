---
title: 매뉴얼 증류(Manual Distillation)
translation_of: manual-distillation.md
translation_source_sha: a56f94ce667654aa87f992d4aba2e7741bffc8a8
translation_revised: 2026-07-13
---

# 매뉴얼 증류(Manual Distillation)

FDAI가 도입 회사의 **운영/배포 매뉴얼**을 런타임에 RAG로 *검색*하는 대신, 빌드 타임에
결정론적 규칙/워크플로우/정책으로 *컴파일*해서 흡수하는 방법. 이 문서가 답하는 것:
*산문 매뉴얼이 어떻게 실행 가능한 T0/T1 아티팩트가 되고, 그 증류가 충실한지 실행 전에
어떻게 검증하는가?*

[rule-catalog-collection-ko.md](rule-catalog-collection-ko.md) 의 소스 수집 메커니즘,
[rule-governance-ko.md](rule-governance-ko.md) 의 저작/스코핑/승격 모델,
[architecture.instructions.md](../../../.github/instructions/architecture.instructions.md) 의
품질 게이트 및 living-rules 원칙을 재진술하지 않고 보완. 이 문서가 꽂히는 지속 파이프라인은
[phase-2-quality-and-t1-ko.md](../phases/phase-2-quality-and-t1-ko.md).

> **고객-비종속 스코프(MUST).** 회사의 매뉴얼은 고객 데이터다. 매뉴얼 자체와 거기서 증류된
> 모든 규칙은 **downstream fork**에 살며, 이 리포에는 절대 두지 않는다
> ([generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md),
> [downstream-fork-guide-ko.md](../fork-and-sequencing/downstream-fork-guide-ko.md) 참조).
> Upstream은 일반적인 **증류 메커니즘**(collector 종류 + 검증 파이프라인)만 제공한다.
> 아래 모든 예시는 합성 placeholder를 사용한다.

## 왜 검색이 아니라 컴파일인가

RAG는 매뉴얼 질문에 런타임에 답한다: 쿼리를 임베딩하고, 청크를 검색하고, LLM이 읽고
해석한다. 이 경로는 **확률적이고, 기본적으로 근거 미보장이며, 매 이벤트마다 다시
판단**된다 - FDAI는 이를 T2(프론티어 모델) 비용으로 계산한다. 운영/배포 매뉴얼은 대부분
**반복 가능한 절차, 임계값, 결정 트리**이므로, 매 이벤트에 T2로 태우는 것은
`deterministic-first` 원칙(목표: LLM 추론 ~5-10%)에 어긋난다.

컴파일은 대신 LLM 비용을 **오프라인에서 한 번** 지불해, 매뉴얼을 버전 관리되는 결정론적
아티팩트로 바꾼다. 이 아티팩트는 T0/T1 계층이 무료로 평가하고 audit 추적을 갖는다. RAG는
제거되지 않고 잔여 역할로 강등된다([RAG가 남는 곳](#rag가-남는-곳) 참조).

| | RAG (검색) | 증류 (컴파일) |
|---|---|---|
| LLM 실행 시점 | 매 이벤트 (런타임) | 한 번, 빌드 타임 |
| 계층 | T2 | T0 / T1 |
| 결정론 | 쿼리마다 재판단 | 고정, 버전 관리 아티팩트 |
| Grounding | best-effort | `provenance` 필수 또는 reject |
| Audit / rollback | 기본 없음 | 카탈로그 버저닝 + PR |

## 무엇이 컴파일되는가

매뉴얼은 한 종류의 아티팩트가 아니다. 증류는 각 진술의 형태로 분해해 맞는 슬롯으로 라우팅한다:

| 매뉴얼 속 진술 | 컴파일 대상 | 위치 |
|---|---|---|
| 판단 기준, 임계값, "~하면 안 됨" 조건 | **Rule / policy** | [rule-catalog catalog](rule-catalog-collection-ko.md), OPA/Rego |
| 순서 있는 절차 (재시작 / 스케일 / 롤백) | **Workflow** (runbook-as-code) | [rule-catalog/workflows](../../../rule-catalog/workflows/) |
| 상태를 바꾸는 단일 행동 | **ActionType** (`rollback_contract` 포함) | rule-catalog action-types |
| 배포 절차, 환경 규격 | **IaC + policy-as-code** | Terraform + 배포 게이트 |

각 fragment는 카탈로그 나머지가 쓰는 동일 스키마로 정규화되고 하나의 `provenance`
스탬프(매뉴얼 URL + 섹션 + content hash)를 공유한다. 메커니즘적으로, 도입 회사의 매뉴얼은
[rule-catalog-collection-ko.md](rule-catalog-collection-ko.md#수집-소스) 의 분류 체계에서 그냥
새 **수집 소스**다: 아래 설명하는 distiller를 collector로 갖는 "고객 저작 운영/배포 매뉴얼"
그룹.

## 증류 파이프라인

오프라인, 빌드 타임, 그리고 모든 규칙 후보가 통과하는 동일 게이트 뒤에 단계화된다. 어떤
fragment도 모델의 판단만으로는 enforce 카탈로그에 도달하지 못한다.

```text
manual (PDF / wiki / docs)
  -> ingest + chunk (build time)
  -> LLM extract candidates  (rule | workflow | action-type | policy) + provenance
  -> source-fidelity gates   (grounding, back-translation, mixed-model)
  -> structural gates        (schema load, safety-invariant check)
  -> shadow evaluation       (replay against real history)
  -> regression + human promotion PR
  -> enforce
```

2단계가 LLM이 실행되는 유일한 곳이며, 이벤트마다가 아니라 **매뉴얼 리비전당 한 번** 실행된다.
2단계 이후는 전부 결정론적 검증 + human 게이트다.

## 증류 검증

증류된 fragment는 다섯 가지 방식으로 틀릴 수 있다. 검증은 각 방식에 담당을 두도록 계층화된다:

| 실패 유형 | 예시 | 잡는 곳 |
|---|---|---|
| 날조(hallucination) | 매뉴얼에 없는 규칙 | grounding 게이트 |
| 오독(misread) | `>80%`를 `>=80%`로, 로직 반전 | back-translation, mixed-model |
| 누락(incomplete) | 매뉴얼에 있는데 추출 안 된 규칙 | coverage diff (잔여) |
| 충돌(conflict) | 기존 카탈로그 규칙과 모순 | dedupe + precedence |
| 불안전(unsafe) | 롤백 / stop-condition 없는 action | schema + verifier |

핵심 통찰: **매뉴얼 텍스트는 "제대로 읽었나"의 정답이지만, 회사의 실제 운영 이력은 "이
fragment가 옳게 동작하나"의 정답이다.** 따라서 검증은 2갈래다.

### 갈래 A - 원본 충실도 ("매뉴얼을 제대로 읽었나")

- **Grounding 게이트 (날조 차단).** 모든 후보는 유도된 매뉴얼 섹션을 정확히 인용해야 한다.
  인용 없음 -> reject 및 abstain. 아키텍처의 grounding 규칙(`abstain when unsupported`)을
  증류에 적용한 것.
- **Back-translation 라운드트립 (오독 차단).** *다른* 모델이 컴파일된 YAML에서 자연어 설명을
  재생성하고, 그 결과를 원본 문장과 diff한다. 의미 불일치는 후보를 flag한다. compile ->
  decompile -> compare는 임계값/극성 오류를 잡는 증류 전용 체크다.
- **Mixed-model 교차검증 (오독 차단).** 추출을 2개 이상 다른 모델로 돌리고, 임계값이나 조건에
  대한 불일치는 자동 채택 대신 HIL로 escalate한다. FDAI의 필수 mixed-model 게이트 - 증류는
  T2 판단이므로 이를 따른다.

### 갈래 B - 현실 충실도 ("fragment가 옳게 동작하나")

- **Schema + verifier (불안전/malformed 차단).** 후보는 rule / workflow / action-type 스키마로
  로드돼야 하고, 모든 action은 네 가지 안전 불변식(`rollback_contract`, stop-condition,
  blast-radius, audit)을 가져야 한다. 누락은 첫 dispatch가 아니라 load에서 실패한다.
- **Shadow-mode 리플레이 (경험적 증명).** fragment를 회사의 **실제 과거 이벤트와 audit log**에
  `default_mode: shadow`로 돌린다. 매뉴얼대로라면 발동했어야 할 때 발동했나? shadow 판정이
  운영자가 실제로 한 것과 일치하나? precision / recall을 측정한다 - "텍스트가 그럴듯하다"가
  아니라 "실제 데이터에서 옳게 동작한다". 이것이 `promotion_gate`다.
- **회귀 스위트 (escape 0).** 알려진 매뉴얼 시나리오를 골든 테스트로 만들고, fragment는
  policy-violation escape 0으로 통과해야 하며, 모든 규칙 변경은 회귀 테스트를 추가한다.

enforce 승격은 절대 자동이 아니다: 측정된 shadow 정확도 -> 명시적 human 승인 PR,
[rule-catalog-collection-ko.md](rule-catalog-collection-ko.md) 와
[phase-2-quality-and-t1-ko.md](../phases/phase-2-quality-and-t1-ko.md) 에 문서화된 동일
`collect -> shadow -> regression -> promote` 순서를 따른다.

## 잔여 리스크: false negative

위 게이트들은 **추출된 fragment**를 검증한다. 매뉴얼이 진술했지만 증류가 **추출하지 못한**
규칙은 검증할 수 없다 - 존재하지 않는 fragment는 리플레이할 대상이 없다. 이 커버리지
갭(false negative)은 증류의 정직한 한계이며 완전히 자동화될 수 없다. 제거가 아니라 완화된다:

- **구조적 coverage diff.** 매뉴얼의 섹션 헤딩과 명령형 진술("must", "must not", "shall")을
  세어, 추출된 fragment 수/토픽과 대조하고, 커버 안 된 섹션을 human 리뷰로 flag한다.
- **운영 피드백.** shadow가 규칙 발동 없이 한동안 돌았는데 실제 인시던트가 발생하면, 그 갭은
  discovery loop가 후보로 바꾸는 누락 규칙 신호다
  ([observability-and-detection-ko.md](observability-and-detection-ko.md) 및
  [architecture.instructions.md](../../../.github/instructions/architecture.instructions.md) 의
  living-rules loop 참조).

"매뉴얼이 완전히 증류됐다"는 human 서명이 있는 측정된 커버리지 숫자로 리포트되며, 결코
단언되지 않는다.

## RAG가 남는 곳

증류는 검색을 없애지 않고 범위를 좁힌다. 깔끔하게 컴파일되지 않는 서술형 지식(인시던트
포스트모템, 팀 컨벤션, 근거 산문)은 **T2 품질 게이트가 grounding하는** 인용 청크로 남는다.
주 경로는 컴파일된 결정론적 아티팩트이고, RAG는 잔여 T2 grounding 백업이며, 근거를 인용하지
못하면 계층은 HIL로 abstain한다. 관계 순회가 중요할 때는 평면 벡터 RAG보다 (새 서비스 없이
기존 PostgreSQL state store 위의) 구조적 knowledge-graph 검색이 선호된다.

## 미결 결정

- 각 매뉴얼 포맷(PDF vs wiki vs Markdown)의 **청킹 + 추출 프롬프트**는 fork가 제공하는
  config이며, 다른 프롬프트처럼 버전 관리된다.
- **Coverage-diff 휴리스틱**("명령형 진술"로 무엇을 셀지)은 매뉴얼 스타일별 튜닝이 필요하다;
  보수적으로 시작하고 flag를 human 리뷰한다.
- **매뉴얼 소스 cadence**: watcher가 변경된 매뉴얼 리비전을 얼마나 자주 재증류하는지는
  [rule-catalog-collection-ko.md](rule-catalog-collection-ko.md) 의 source-watcher cadence
  모델을 재사용한다; 매뉴얼 리비전은 content hash를 bump하고 파이프라인에 재진입한다.

## 다음 단계

| 알아볼 것 | 읽을 문서 |
|---|---|
| 규칙이 어디서 오고 YAML 형상은 무엇인가 | [rule-catalog-collection-ko.md](rule-catalog-collection-ko.md) |
| 저작, 스코핑, 예외, 승격 | [rule-governance-ko.md](rule-governance-ko.md) |
| Runbook-as-code 워크플로우 스키마 | [rule-catalog/workflows](../../../rule-catalog/workflows/) |
| 지속 품질 + T1 파이프라인 | [phase-2-quality-and-t1-ko.md](../phases/phase-2-quality-and-t1-ko.md) |
| 고객 매뉴얼과 규칙이 사는 곳 | [downstream-fork-guide-ko.md](../fork-and-sequencing/downstream-fork-guide-ko.md) |
