---
title: 인과 incident graph
translation_of: causal-incident-graph.md
translation_source_sha: bac451939f333f602c305fd76360da7bfa75ea59
translation_revised: 2026-09-04
---
# 인과 인시던트 그래프

이 문서는 FDAI가 운영 인시던트의 인과 주장을 표현하고 평가하고 종결하는 방법을 정의합니다.
Event 상관관계와 root-cause analysis(RCA)를 온톨로지 기반의 time-consistent 그래프로 확장하면서
실행 권한은 기존 컨트롤 루프에 유지합니다.

> **권한 경계:** Causal 그래프는 결정을 위한 근거이며 실행 허가가 아닙니다. Rule 검증기,
> 안전성 검사, 승인 정책, 실행기, 감사 원장이 계속 권한을 가집니다.
>
> **구현 상태(2026-08-01):** 타입이 지정된 가설 수명 주기, weakest-link 채점, 범위가 제한된
> time-consistent 그래프 materializer, support/refutation 및 종결 링크, 변경할 수 없는 온톨로지
> projector, lagged temporal analyzer, 런타임 조정기, shadow control-loop 호출자,
> 독립적인 종결 classifier 및 회귀 테스트를 구현했습니다. 컨트롤 루프는 shadow에서
> 분석하고 감사하지만 Forseti 대신 온톨로지를 쓰지 않습니다. 배포는 범위가 제한된 temporal
> series, Forseti-owned 변환 결과 발행기, 독립적인 결과 프로바이더, causal 증적 해석기를
> 연결합니다. Pre-routing temporal analysis에는 범위가 제한된 시간 초과가 있으며 범위와 시간이 일치하는
> 검증된 intervention 증적만 종결을 confirm할 수 있습니다. Causal 결과는 실행을 허가하지 않습니다.

## 설계 개요

FDAI는 하나의 근거 기준 시점을 기준으로 인시던트 subgraph를 구성하고, 범위가 제한된 root-cause
가설을 생성하며, 각 가설을 지지하고 반박하는 근거를 모두 탐색합니다. 이후 네
가지 causal 근거 grade 중 하나를 기록합니다. 시간 순서만으로는 association만 나타낼 수
있습니다. 통제된 intervention 또는 동등한 복구 reversal만 interventional 근거를
입증할 수 있습니다.

![설계 개요. 주요 단계는 Event 및 observation, Correlated incident, Dependency topology, Time-consistent incident graph, CausalHypothesis candidate, Supporting evidence, Refuting evidence, Deterministic causal verifier, DecisionCase, Recovery plan, Observed outcome입니다.](../../diagrams/generated/fdai-roadmap-rules-and-detection-causal-incident-graph-01.ko.svg)

## 역량 질문

Graph는 다음 질문에 결정론적으로 답하거나 명시적인 알 수 없음을 반환하는 것이 좋습니다.

1. 어떤 변경, 실패 또는 외부 조건이 관측된 symptom을 설명할 수 있습니까?
2. 어떤 의존성 경로가 해당 원인을 영향받은 서비스 목표까지 전파할 수 있습니까?
3. 각 후보 원인과 모순되는 근거는 무엇입니까?
4. 어떤 관측이 남은 후보를 구분할 수 있습니까?
5. 승인된 복구 액션이 선언된 구간 안에서 예측된 효과를 반전시켰습니까?
6. 승인된 chaos intervention이 범위를 넘지 않고 예측된 효과를 재현했습니까?

이 질문이 필요한 그래프와 조회 테스트를 정의합니다. 새로운 온톨로지 타입이나 링크는 visualization만
개선하기 위해 추가하지 않는 것이 좋습니다.

## 온톨로지 계약

이 설계는 operating 온톨로지의 `Incident`, `Finding`, `Observation`, `Change`, `Experiment`,
`Resource`, `Workload`, `BusinessService`, `ServiceObjective`, `DecisionCase`, `ActionRun`,
`ObservedOutcome`을 재사용합니다. 영속 의미 객체 하나를 추가합니다.

### `CausalHypothesis` ObjectType

`CausalHypothesis`는 기계가 평가할 수 있는 하나의 causal 점유에 대한 변경할 수 없는 개정 번호입니다.
나중에 들어온 관측은 이전 결정에 사용한 점유를 덮어쓰지 않고 새 개정 번호를 만듭니다.

| Property | 타입 | 의미 |
|----------|------|------|
| `id` | 문자열 | 인시던트, claimed 원인, claimed 효과, 메서드 버전, 근거 기준 시점에서 파생한 고정된 id입니다. |
| `incident_id` | 문자열 | 가설이 symptom을 설명하는 인시던트입니다. |
| `status` | 문자열 | `candidate`, `supported`, `refuted`, `inconclusive`, `closed` 중 하나입니다. |
| `cause_ref` | 문자열 | 원인으로 주장하는 타입이 지정된 객체 또는 이벤트입니다. |
| `effect_ref` | 문자열 | 설명 대상 발견 사항, 목표 breach 또는 인시던트 효과입니다. |
| `mechanism` | 문자열 | 검토된 카탈로그의 범위가 제한된 방식 코드이며 free-form 권한이 아닙니다. |
| `evidence_grade` | 문자열 | `association`, `predictive_precedence`, `quasi_experimental`, `interventional` 중 하나입니다. |
| `confidence` | number | 모호함과 evidence-completeness penalty를 반영한 `[0, 1]` 점수입니다. |
| `ambiguity` | 정수 | 기준 시점 시점에 실질적으로 경쟁하는 루트 후보 수입니다. |
| `graph_revision` | 문자열 | 탐색에 사용한 인벤토리와 operating-model 개정 번호입니다. |
| `evidence_cutoff` | datetime | 점유에 사용할 수 있는 가장 늦은 이벤트 시간입니다. |
| `method_version` | 문자열 | 결정론적 scorer 또는 검토된 reasoner 버전입니다. |
| `created_at` | datetime | FDAI가 이 개정 번호를 수락한 시간입니다. |
| `closure` | 문자열 | 선택적 최종 결과인 `confirmed`, `refuted`, `inconclusive`, `unsafe` 중 하나입니다. |

객체는 식별자와 점수만 저장합니다. 근거 본문은 권위 있는 저장소에 남고 opaque
참조로 인용합니다.

### Causal LinkType

현재 LinkType 스키마는 타입이 지정된 엔드포인트와 `is_causal` 또는 `temporal_order` 플래그로 다음 관계를
표현할 수 있습니다.

| LinkType | 엔드포인트 | 플래그 | 의미 |
|----------|----------|------|------|
| `hypothesis_explains_finding` | CausalHypothesis -> 발견 사항 | `is_causal` | 가설이 설명하려는 효과입니다. |
| `hypothesis_claims_change` | CausalHypothesis -> 변경 | `is_causal` | 루트 또는 contributing 원인으로 주장하는 변경입니다. |
| `hypothesis_claims_experiment` | CausalHypothesis -> 실험 | `is_causal` | 방식 검증에 사용한 intervention입니다. |
| `evidence_supports_hypothesis` | EvidenceArtifact -> CausalHypothesis | - | 예측 방식과 일치하는 근거입니다. |
| `evidence_refutes_hypothesis` | EvidenceArtifact -> CausalHypothesis | - | 필수 prediction과 모순되는 근거입니다. |
| `hypothesis_precedes_hypothesis` | CausalHypothesis -> CausalHypothesis | `temporal_order` | 개정 번호 또는 좁히기 순서이며 자체로 causal 증명이 아닙니다. |
| `outcome_tests_hypothesis` | ObservedOutcome -> CausalHypothesis | `is_causal` | 종결에 사용한 독립적인 post-action 또는 실험 관측입니다. |

Physical LinkType 선언은 하나의 구체적인 출처와 대상 ObjectType을 유지합니다.
배포는 임의 객체 사이에 untyped `caused_by` 간선을 사용하지 않습니다.

## Time-consistent 인시던트 subgraph

Muninn은 인시던트의 근거 기준 시점을 기준으로 그래프를 materialize합니다. 범위가 제한된 탐색은
다음을 포함합니다.

- 영향받은 서비스, 워크로드, 리소스
- 들어오는 및 나가는 `depends_on`, `runs_on`, `implemented_by`, `contains` 링크
- Correlated 발견 사항, 관측, 변경, 배포, 실험, 액션 실행
- 활성 서비스 목표 및 복구 목표
- 토폴로지 최신성, 출처 출처 이력, 해결되지 않은 충돌

기본값 탐색은 failing 워크로드 또는 리소스에서 깊이 2입니다. 구성은 깊이나
노드 상한을 낮출 수 있지만 조용히 높일 수는 없습니다. 노드, 간선, 시간 또는 바이트 상한에
도달하면 그래프를 `truncated`로 표시합니다. 잘린 그래프는 자율 복구를 지원할 수
없습니다.

Late 이벤트는 새 그래프 개정 번호를 만듭니다. 재생은 항상 원래 카탈로그 버전, 토폴로지
개정 번호, 근거 기준 시점을 해석합니다.

## 후보 생성

후보 생성은 deterministic-first이며 범위가 제한된입니다.

1. **T0 direct 원인:** Matched 룰이 declared 방식과 교정을 제공합니다.
2. **T1 temporal 경로:** 같은 리소스 또는 의존성 경로의 preceding 변경이 구성된
   방식 구간 안에 있으면 후보가 됩니다.
3. **T1 resolved-case reuse:** 이전 인시던트는 리소스 타입, 신호 지문, 토폴로지 역할,
   방식이 여전히 일치할 때만 후보를 제공합니다.
4. **T2 근거에 기반한 제안:** T0와 T1이 계속 모호한하면 reasoner는 범위가 제한된 그래프 안에 있는
   후보와 인용만 순위할 수 있습니다. 객체, 링크 또는 액션을 새로 만들 수 없습니다.

모든 경로는 `no_known_cause` 옵션을 유지합니다. 후보 생성은 구성된 개수에서
중지합니다. 초과분에서는 결정론적 점수가 높은 항목만 유지하고 잘림을 기록합니다.

## 적응형 관측 선택

둘 이상의 인과 가설이 활성 상태로 남으면 FDAI는 가설을 가장 잘 구분하는 다음 관측을 선택할 수
있습니다. 선택기는 미리 검증된 읽기 전용 조회 후보만 받습니다. 선택기 자체는 공급자를 조회하지
않으며 조회, 액션, 변경 또는 승격 권한을 부여할 수 없습니다.

변경할 수 없는 판별 프레임은 인시던트, 그래프 개정 번호, 근거 기준 시점, 활성 가설 집합, 활성
집합 증적 및 비용 모델 다이제스트를 고정합니다. 내용 기반 주소가 지정된 각 후보는 동일한 관측이
각 활성 가설을 지지하거나 반박하거나 어느 쪽에도 영향을 주지 않을지를 예측합니다. 다른 프레임의
후보나 활성 가설을 빠뜨린 후보는 명시적인 제외 근거로 남습니다.

선택기는 예측 결과가 서로 다른 가설 쌍의 수를 최대화합니다. 결과가 같으면 비교 가능한 비용이 더
낮은 후보를 우선하고, 이후 내용 식별자로 순서를 정합니다. 활성 가설이 둘보다 적거나, 적합한 후보가
없거나, 가설을 구분할 관측이 없으면 타입이 지정된 판단 보류 결과를 반환합니다. 재생 증적은 전체
후보 집합, 제외 결과, 가설 쌍 수, 선택된 후보 또는 보류 사유, 스키마 및 메서드 버전을 고정합니다.
호출자는 선택된 관측을 실행할 때 별도로 검증된 읽기 조회 경로를 사용해야 합니다.

## 적응형 조사 세션

적응형 조사는 두 번째 인과관계 또는 실행 시스템을 만들지 않고 관측 선택을 반복하는, 범위가 제한된
읽기 전용 `Process`입니다. Forseti가 workflow의 최종 책임을 맡고, 기계적인 기록기가 Process 개정
번호 비교 후 설정으로 상태를 진행합니다. Heimdall만 관측 및 완전성 근거를 제공하고, Forseti만 가설
개정 번호와 최종 인과 판단을 수락하며, Saga는 기존 이벤트 경계에서 각 최종 전이를 감사합니다.

각 반복은 다음과 같은 변경할 수 없는 계보를 연결합니다.
`Process 및 반복 -> 프레임 다이제스트 -> 선택 증적 -> 후보 다이제스트 -> 검증 증적 ->
OntologyQueryPlan 다이제스트 -> 실행 증적 및 결과 다이제스트 -> Forseti 개정 번호`. 이 계보는
workflow 및 리듀서 버전, 온톨로지 및 조회 매니페스트 다이제스트, principal 범위, 역할, 목적, 근거
기준 시점, 소스 세대, 완전성, 잘림, 채점기 버전 및 실제 리소스 사용량도 고정합니다. 검증과 dispatch는
하나의 실패 시 닫히는 게이트웨이 작업이며 검증 성공 전에는 공급자 I/O를 시작하지 않습니다.

모든 Forseti 개정 번호는 이전 활성 집합 증적, 이전 프레임, 정확한 관측 증적, 채점기 버전, 새 그래프
개정 번호 및 새 근거 기준 시점을 인용합니다. Process 개정 번호 비교 후 설정은 완전한 다음 활성 집합
하나만 수락합니다. 늦거나 경쟁하는 개정 번호는 감사 근거로 남지만 세션을 진행할 수 없습니다.

Forseti 소유 채점기가 실질적으로 지지되는 가설 하나만 남기거나, 모든 후보가 반박되거나, 남은 후보를
구분할 조회가 없거나, 반복 횟수, 조회 수, 시간 또는 비용 예산이 소진되면 세션을 중지합니다. 생성
시점에는 절대 UTC 마감, 단조 경과 시간 정책, 모든 제한과 단위 및 예산 정책 다이제스트를 고정합니다.
게이트웨이는 dispatch 전에 조회 수와 예상 비용을 예약하고 실제 사용량을 한 번 정산합니다. 취소는 새
반복을 차단하고 진행 중 조회에 신호를 보내며 최종 Process 비교 후 설정에서 경쟁합니다. 늦은 결과는
감사할 수 있지만 취소되었거나 최종 상태인 세션을 진행할 수 없습니다. Process `cancelled`와
`timed_out`은 `cost_exhausted` 같은 조사 판단 보류와 구분합니다.

재생 리듀서는 추가 전용 `Process` 근거 이벤트에서 같은 세션을 복원하며 변경된 계보, 순서, 증적,
구성 또는 최종 다이제스트를 차단합니다. 재생은 보존된 내용 기반 주소 결과만 사용합니다. 공급자를
호출하거나 조회를 실행하거나 예산을 소비하거나 학습 후보를 발행하거나 계획을 시작하거나 권한을
변경하지 않습니다.

실제로 관측을 실행할 수 있는 정책은 활성 선택기뿐입니다. 도전 선택기는 동일한 동결 프레임에서
shadow 모드로 실행하며, 도전 선택 결과를 조회 경로에 반환하지 않은 채 일치 여부, 가설 쌍 구분 수,
비용 및 판단 보류 결과를 측정합니다. 서로 다른 조회를 선택하면 구분 능력과 비용은 반사실적
예측입니다. 두 정책이 같은 조회를 선택하거나 별도의 관리되는 활성 정책 집단에서 나온 경우에만 실제
근거로 계산합니다. Saga가 비교를 기록하고, Muninn이 균형 잡힌 집단을 봉인하며, Norns만 비활성 조사
전략 후보를 컴파일하고 발행하고, Mimir가 이를 검토합니다. 활성화는 검토된 변경할 수 없는 구성
release를 사용하고 새 세션에만 적용되며 실행 중인 세션에 고정된 선택기를 바꿀 수 없습니다.

조건을 충족한 세션이 종결되면 최종 세션 다이제스트와 근거를 참조하는 권한 없는 타입 지정 계획 요청
이벤트를 발행할 수 있습니다. Forseti는 별도의 계획 Process를 시작하고 현재 컨텍스트와 대상 개정
번호를 다시 수집하며, 필수 `no_action` 기준선과 처리 후보, 제약 조건 및 시뮬레이션을 소유합니다.
취소, 시간 초과, 전체 반박, 불완전 또는 잘린 조사는 처리 계획을 자동 요청하지 않습니다. 조사 근거는
Operational Planning, 안전성 검토, 사람 승인, Thor 실행, 독립 효과 관측, Saga 감사 또는 Vidar
복구를 우회하지 않습니다.

Operator API는 GET 전용이며 RBAC, 테넌트, 목적 및 principal 범위가 적용된 Process 판독기를 통해
적응형 세션 이벤트를 변환합니다. 원시 조회 결과 대신 범위가 제한되고 정제된 요약과 불투명 근거
참조를 반환합니다. 변환 결과에는 Process 개정 번호, 근거 기준 시점, 소스 watermark, release
다이제스트, 최신성, 잘림, 사용할 수 없음 증적 및 명시적인 `mutation_controls: false`가 포함됩니다.
Console은 Process 상세 화면 안의 조사 공간에 활성 가설, 지지 및 반박 수, 누락 근거, 선택된 관측,
shadow 비교, 예산 및 최종 사유를 표시합니다.

## Causal 채점 및 refutation

각 후보는 네 가지 독립 factor로 평가합니다.

- **Temporal precedence:** 원인이 방식 구간 안에서 효과보다 먼저 발생했습니다.
- **Topological 도달 가능성:** 타입이 지정된 의존성 경로가 원인과 효과를 연결합니다.
- **방식 fit:** 관측된 direction과 symptom pattern이 검토된 방식과 일치합니다.
- **Intervention 일관성:** 이전 또는 현재 액션이 prediction과 같은 방향으로 효과를
  바꿨습니다.

체인 점수는 가장 약한 홉 점수에 근거 완전성과 모호함 penalty를 곱합니다. 높은
평균으로 지원하지 않는 홉 하나를 숨길 수 없습니다. 임계값과 가중치는 versioned 구성이며
가설과 함께 재생합니다.

검증기는 supporting 조회마다 최소 하나의 refutation 조회를 실행합니다. 예시는 다음과 같습니다.

| 후보 | Supporting 검사 | Refuting 검사 |
|-----------|------------------|----------------|
| Bad 배포가 오류를 유발함 | 영향받은 인스턴스에서 오류 rise가 배포 이후 발생했습니다. | 변경되지 않은 인스턴스에도 배포 전부터 같은 rise가 있습니다. |
| 데이터베이스 포화가 지연 시간을 유발함 | 의존성 경로에서 조회 지연 시간과 CPU가 서비스 지연 시간보다 먼저 상승했습니다. | 서비스 지연 시간이 상승했지만 데이터베이스 지연 시간과 연결은 정상입니다. |
| 네트워크 delay가 게이트웨이 지연 시간을 유발함 | 내부/외부 경로 차이가 영향받은 간선과 일치합니다. | 두 경로가 동일하게 변했거나 의존성 간선이 healthy입니다. |
| 할당량 pressure가 429를 유발함 | 요청이 관측된 할당량 구간을 초과했습니다. | 할당량 이하에서 429가 발생했거나 provider-wide 실패가 더 잘 설명합니다. |

누락된 refutation 데이터는 `unknown`이며 후보를 지지하는 근거가 아닙니다.

## 근거 grade

FDAI는 기존 `CausalEvidenceGrade` 값을 재사용합니다.

| Grade | 최소 근거 | 최대 사용 범위 |
|-------|---------------|----------------|
| `association` | 상관관계 또는 temporal co-occurrence만 있습니다. | Explanation 및 조사 계획 수립입니다. |
| `predictive_precedence` | 후보가 효과에 반복적으로 선행하고 direction을 예측합니다. | Shadow 또는 사람 승인을 받는 복구 제안입니다. |
| `quasi_experimental` | Comparable untreated 집단, natural 실험 또는 difference-in-differences 근거가 있습니다. | 다른 안전성 검사가 모두 통과한 범위가 제한된 복구 충족 여부입니다. |
| `interventional` | 승인된 chaos intervention 또는 복구 reversal이 predicted 효과를 재현하거나 제거합니다. | 승격 근거 입력이며 단독 권한이 아닙니다. |

Refuting 근거가 도착하면 근거 grade가 낮아질 수 있습니다. 낮은 grade는 새 가설
개정 번호를 만들고 관련 액션 또는 chaos 시나리오를 shadow 모드로 demote할 수 있습니다.

종결은 결정론적이고 단조로운 demotion 규칙을 적용합니다. 검증된 interventional 증적을 갖춘
`confirmed` 종결만 grade를 올릴 수 있고, 나머지 종결은 grade를 유지하거나 낮춥니다.

| 종결 | 결과 grade | 관련 액션 또는 실험 모드 |
|------|-----------|--------------------------|
| `confirmed` | `interventional` | `gated`: 기존 위험, 승인, 실행, 롤백 게이트에 들어갈 수 있습니다. |
| `refuted` | `association` | `shadow` |
| `unsafe` | `association` | `shadow` |
| `inconclusive` | 유지하며 절대 올리지 않습니다 | `shadow` |

이 모드는 권한으로 저장하지 않고 불변 개정 번호에서 도출합니다. Refuting 참조가 하나라도
있거나 상태가 확정되지 않았거나 grade가 `quasi_experimental`보다 낮은 개정 번호는 `shadow`에
남습니다. `gated`는 기존 안전 경로에 들어갈 자격을 뜻할 뿐 허가가 아닙니다.

개정 번호를 `shadow` 위로 올리는 것은 긍정적 결정이므로, 이 도출에는 해당 개정 번호와 인과
범위, 소스 개정에 정확히 연결된 최신 공유 의사 결정 핵심 근거 승인 결과도 필요합니다. 런타임
조정기가 승인 결과를 요청해 결과에 함께 담습니다. 승인 프로바이더가 연결되지 않았거나 승인
결과가 일치하지 않으면 모드는 `shadow`로 유지됩니다.

## 복구 및 chaos를 통한 종결

복구 또는 실험은 실행 전에 예상 관측을 선언합니다. Heimdall은 Thor가
실행하거나 Loki의 승인된 실험이 실행된 뒤 효과를 독립적으로 측정합니다. 종결은
관찰된 direction, magnitude, affected 집합, 시간 구간을 prediction과 비교합니다.
검증된 intervention 실행 시간은 가설 근거 기준 시점보다 엄격히 이후여야 합니다.
같은 시각이면 pre-intervention 근거 구간이 분리되지 않았으므로 inconclusive입니다.

- **Confirmed:** 필수 효과가 일치하고 prohibited 효과가 발생하지 않았습니다.
- **Refuted:** 완전한 텔레메트리에서 필수 효과가 반대 방향으로 움직이거나 나타나지
  않았습니다.
- **Inconclusive:** 근거가 stale, 불완전한, censored이거나 declared 구간 밖에 있습니다.
- **Unsafe:** 관찰된 affected 집합 또는 목표 성능 저하가 approved 묶음을 넘었습니다.

Unsafe 결과는 실험 stop 조건과 Vidar 복구 경로를 트리거합니다. Original causal
가설이 맞더라도 승격을 차단합니다.

## 에이전트 소유권

고정 pantheon은 single-writer 소유권을 유지합니다.

| 에이전트 | Responsibility |
|-------|----------------|
| Huginn | Event, 관측, 변경, 실험 증적을 normalize합니다. |
| Heimdall | 발견 사항과 독립적인 support/refutation 관측을 발행합니다. |
| Forseti | `CausalHypothesis` 개정 번호와 이를 사용하는 결정을 소유합니다. |
| Loki | 범위가 제한된 실험을 propose하며 자체 실험 결과를 평가하지 않습니다. |
| Thor | 승인된 액션 또는 실험 계획만 execute합니다. |
| Vidar | Rollback 및 forward-recovery 컨트롤을 소유하고 Thor 실행을 요청하며 복구 결과를 기록합니다. |
| Saga | 가설, 근거, 결정, 액션, 종결 참조를 덧붙이기합니다. |
| Muninn | Time-consistent 그래프 개정 번호를 materialize합니다. |
| Mimir | 방식, 룰, 액션 카탈로그 버전을 govern합니다. |

Synchronous 에이전트 호출은 도입하지 않습니다. 각 쓰기는 타입이 지정된 pub/sub를 통하고 safe to 재시도하게
유지됩니다.

## 실패 동작

Causal 경로는 불확실할 때 더 안전한 결과를 선택합니다.

- Stale 토폴로지, 누락된 목표, 잘린 탐색, conflicting 소유권 또는 불완전한
  텔레메트리는 근거 grade를 낮추고 automatic 복구를 차단합니다.
- 충분한 support를 가진 후보가 없으면 `inconclusive`를 반환하고 조사를 요청합니다.
- Graph 밖의 reasoner 인용은 fabricated 인용으로 차단합니다.
- 변환 결과 실패는 권위 있는 이벤트 또는 감사 기록을 지울 수 없습니다.
- Graph 조회 시간 초과는 범위가 제한된 실패를 기록하며 unbounded 검색으로 전환하지 않습니다.

## 전달 구획

구현은 독립적으로 테스트할 수 있는 구획으로 진행할 수 있습니다.

1. `CausalHypothesis`와 7개 LinkType을 로더 및 competency-query 테스트와 함께 추가합니다.
2. 기존 구조화된 T1 causal 체인을 변경할 수 없는 가설 개정 번호로 project합니다.
3. Support/refutation 조회 계약과 evidence-completeness 채점을 추가합니다.
4. 운영 조립에 `IncidentMemberSource`와 의존성 그래프를 연결합니다. 이제 Azure 배포 이력이
   T1 변경 root를 제공하며 더 넓은 시계열 경로는 계속 남아 있습니다.
5. `ObservedOutcome`의 독립적인 종결과 refutation 또는 unsafe 영향에 따른 demotion을
   추가합니다.
6. 자율성을 높이지 않으면서 조건을 충족한 causal 근거를 복구와 chaos 승격에
   제공합니다.

## 구현 상태

### 구현 범위

| 영역 | 상태 | 근거 | 참고 |
|------|------|------|------|
| 가설 수명 주기 및 온톨로지 변환 결과 | implemented | `services/core-control-plane/src/fdai/core/rca/hypothesis.py`; `projection.py`; `tests/core/rca/test_hypothesis.py`; `test_hypothesis_lineage_projection.py` | 불변 수정본, 종결 상태, 근거 전용 그래프 변환 결과를 집중 테스트로 검증합니다. |
| Time-consistent 인시던트 그래프 | implemented | `services/core-control-plane/src/fdai/core/rca/incident_graph.py`; `tests/core/rca/test_incident_graph.py` | 탐색은 깊이, 개수, 시간, 크기로 제한되며 잘림을 보고합니다. |
| 후보 생성 및 causal 채점 | implemented | `services/core-control-plane/src/fdai/core/rca/t0.py`; `t1.py`; `evidence.py`; `tests/core/rca/test_coordinator.py`; `test_evidence.py` | 결정론적 후보, 최약 연결 채점, 지지 및 반증 경로가 구현되어 있습니다. |
| 적응형 관측 선택 | implemented | `services/core-control-plane/src/fdai/core/rca/discrimination_contract.py`; `discrimination.py`; `tests/core/rca/test_discrimination.py` | 정확한 프레임에 속한 후보를 내용 기반 주소로 식별하고, 조회 또는 실행 권한을 부여하지 않은 채 가설 쌍 구분 능력으로 순위를 정합니다. |
| 적응형 조사 세션 및 검토 화면 | implemented | `core/read_investigation/adaptive*.py`; `core/rca/discrimination_shadow.py`; `core/operational_learning/investigation_strategy*.py`; `core/operational_planning/investigation_handoff.py`; `runtime/adaptive_investigation_runtime.py`; Operator 및 Console Process 변환 결과 | 통합 세션은 범위가 제한되고 재생 가능하며 shadow 비교를 지원하고 권한을 부여하지 않습니다. 기존 인증된 Process 경로에서 확인할 수 있습니다. 이는 구현 근거이며 관리되는 실시간 검증 주장이 아닙니다. |
| Shadow 런타임 및 독립 종결 | implemented | `services/core-control-plane/src/fdai/core/rca/runtime.py`; `tests/core/rca/test_runtime.py`; `test_temporal_causality.py` | 업스트림 경로는 shadow 및 근거 전용으로 유지되며 어떤 결과도 실행 권한을 부여하지 않습니다. |
| 등급 demotion 및 shadow 유지 | implemented | `services/core-control-plane/src/fdai/core/rca/hypothesis.py`(`close_causal_hypothesis`, `causal_action_mode`); `runtime.py`(`CausalRuntimeResult.action_mode`); `tests/core/rca/test_hypothesis.py`; `test_runtime.py` | 안전하지 않거나 반증하는 종결은 등급을 `association`으로 낮추고, 검증된 `confirmed` 외에는 어떤 종결도 등급을 올릴 수 없으며, 확정되지 않았거나 다투는 개정 번호는 모두 `shadow`로 귀결됩니다. 런타임은 도출된 모드를 노출하지만, causal 경로가 아직 shadow 전용이므로 승격이나 실행 소비자는 연결되어 있지 않습니다. |
| Azure T1 배포 연결 | implemented | `delivery/azure/deployment_history.py`, `runtime/rca_bindings.py`, topology history, Azure, 런타임 및 control-loop 테스트 | Event-time 인벤토리 신원과 bitemporal topology history가 세대가 일치하는 Incident 맥락 하나를 만듭니다. Canonical lifecycle 매칭, 전용 읽기 신원, sovereign cloud 연결 및 전체 deadline이 실패 시 차단됩니다. |
| 운영 인과 종결 근거 | in-progress | [전달 구획](#전달-구획), 현재 변경의 소스 감사 | 검증 완료를 주장하려면 범위가 제한된 시계열, 게시자, 결과 및 증적 경계를 배포에서 연결하고 관리되는 종결 증적을 보존해야 합니다. |

### 구현 이력

| 날짜 | 상태 | 변경 | 근거 | 남은 작업 |
|------|------|------|------|-----------|
| 2026-09-04 | implemented | Startup에 고정된 T1 topology를 이벤트 기준 시각의 `IncidentRcaContext`로 교체했습니다. Historical 인벤토리 신원, append-only topology, lifecycle 재개 구간 및 프로바이더 멤버는 한 세대를 공유해야 하며, 하나의 timeout이 읽기, 분석 및 감사를 포함합니다. | `current change`; 집중 topology, 프로바이더, lifecycle, timeout, identity hydration, plan guard, Ruff, strict mypy 및 Terraform 검사. | 더 넓은 시계열 종결 경로를 연결하고 관리되는 개입 근거를 보존합니다. |
| 2026-09-04 | implemented | Azure T1 변경 root 연결과 현재 의존성 세대 보호를 추가했습니다. 프로바이더 신원은 delivery 안에 유지하고 성공한 정확한 범위의 변경만 변경 이벤트가 되며, 그래프가 바뀌면 범위 없는 상관관계를 허용하지 않고 T1을 비활성화합니다. | `current change`; 집중 배포 이력, 의존성 세대, 멤버 출처 및 control-loop 테스트 28건, Ruff, strict mypy가 통과했습니다. | 더 넓은 시계열 종결 경로를 연결하고 관리되는 개입 근거를 보존합니다. |
| 2026-08-14 | in-progress | 이전 출처를 재구성하지 않고 구현 원장을 도입했습니다. | `current change`; 구현 범위 표의 현재 소스와 집중 테스트. | 운영 근거 경로를 연결하고 관리되는 개입 종결 근거를 보존합니다. |
| 2026-08-16 | implemented | 안전하지 않은 종결이 근거 등급을 낮추도록 만들고, `confirmed`가 아닌 종결이 등급을 올리지 못하게 막았으며, 반증·안전하지 않음·미확정·다툼·낮은 등급 개정 번호를 `shadow`에 유지하는 결정론적 `causal_action_mode` 도출을 추가했습니다. | `current change`; `services/core-control-plane/src/fdai/core/rca/hypothesis.py`; `services/core-control-plane/tests/core/rca/test_hypothesis.py`; 집중 실행 `pytest services/core-control-plane/tests/core/rca` 215개 통과. | 배포 근거 경로를 연결하고 관리되는 개입 재현 기록 하나를 보존합니다. |
| 2026-08-16 | implemented | 도출된 모드를 `CausalRuntimeResult.action_mode`로 노출해 shadow 판단을 런타임 경로에서 관찰할 수 있게 했고, 아직 어떤 승격·실행 소비자도 이 모드를 연결하지 않는다는 점을 구현 범위 행에 명시했습니다. | `current change`; `services/core-control-plane/src/fdai/core/rca/runtime.py`; `services/core-control-plane/tests/core/rca/test_runtime.py`; 집중 실행 `pytest services/core-control-plane/tests/core/rca` 216개 통과. | 배포 근거 경로를 연결하고 관리되는 개입 재현 기록 하나를 보존합니다. |
| 2026-08-30 | implemented | 정확한 프레임에 속하고 미리 검증된 읽기 전용 후보를 대상으로 재생 가능한 적응형 관측 선택을 추가했습니다. 선택기는 가설 쌍 구분 능력을 최대화하고, 오래되었거나 불완전한 후보를 기록하며, 권한이 없는 선택 또는 보류 증적을 반환합니다. | `current change`; `services/core-control-plane/src/fdai/core/rca/discrimination_contract.py`; `discrimination.py`; 판별 선택기 집중 테스트, Ruff 및 strict mypy. | 운영 검증을 주장하기 전에 후보 생성을 검증된 온톨로지 조회 경로에 연결하고 관리되는 조사 근거를 보존합니다. |
| 2026-08-30 | implemented | 범위가 제한된 적응형 조사 런타임, Process journal, 정확한 검증 조회 게이트웨이, 활성 및 도전 선택기 비교, Norns에서 Mimir로 이어지는 비활성 전략 검토 경로, 별도 계획 제안, Operator 변환 결과 및 Console 조사 공간을 추가했습니다. | `current change`; 집중 core, agent, runtime, Operator, Console 및 Playwright 검사. | 선택기를 승격하기 전에 배포 소유 후보 및 개정 번호 소스를 연결하고 관리되는 실시간 근거를 보존합니다. |
| 2026-08-30 | implemented | 추적된 비평 및 하드닝 22라운드와 최종 독립 release 검토를 완료했습니다. 변경할 수 없는 신원, 마감, 취소, 조회 권한, Process 재생, shadow 격리, 학습 집단, 계획 전달, Operator 변환 결과, Console 오버플로, 대규모 결과 해시, cold import 및 at-least-once 중복 제거를 Low 이하의 결과만 남을 때까지 보강했습니다. | `current change`; Core 테스트 646개, Operator 테스트 46개, Console 테스트 19개, Playwright viewport 시나리오 3개, Ruff, strict mypy 및 최종 작업 범위 검토. | 선택기를 승격하기 전에 관리되는 실시간 근거를 보존합니다. 로컬 구현 근거는 배포 검증을 의미하지 않습니다. |

### 남은 작업

- [ ] 범위가 제한된 시계열, Forseti 소유 변환 결과 게시자, 독립 결과, causal 증적 해석을 배포 통합 테스트에서 연결합니다.
- [ ] 검증된 개입이 실행 권한을 부여하지 않으면서 가설을 확정하거나 반증하는 관리되는 재현 기록 하나를 보존합니다.
- [x] 안전하지 않거나 반증하는 근거가 가설 등급을 낮추고 관련 작업 또는 실험을 `shadow`로 유지합니다. 근거는 `services/core-control-plane/src/fdai/core/rca/hypothesis.py`의 `close_causal_hypothesis`와 `causal_action_mode`, 그리고 `services/core-control-plane/tests/core/rca/test_hypothesis.py`의 집중 사례입니다.

## 관련 문서

| 알아볼 내용 | 문서 |
|-------------|------|
| 공유 operational 객체와 소유권 | [FDAI 운영 온톨로지](../architecture/operating-ontology-ko.md) |
| Detection, 상관관계 및 현재 RCA | [관측성 및 감지](observability-and-detection-ko.md) |
| 액션 안전성과 실행 계약 | [액션 온톨로지](../decisioning/action-ontology-ko.md) |
| Multi-step 통제된 실행 | [프로세스 자동화](../decisioning/process-automation-ko.md) |
