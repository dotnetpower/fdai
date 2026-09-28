---
translation_of: ontology-reasoning-compiler.md
translation_source_sha: 50263cb4332fc147eb848c9c28e193cc78f19e65
translation_revised: 2026-09-28
---
# 온톨로지 추론 컴파일러

이 문서는 운영자 질문을 닫힌 타입과 원문 구간에 근거한 질문 논리 형식으로 바꾸고, 그 형식을
결정론적으로 검증된 온톨로지 조회 계획으로 컴파일하는 목표 설계를 담당합니다. 모델은 닫힌 타입
안에서 의미만 분류합니다. 코드는 그 의미를 수용하고, 개념과 앵커를 바인딩하고, 검토된 관계 경로를
고르고, 계획이 의미를 보존함을 증명하고, 답변이 주장할 수 있는 범위를 정합니다.

> **상태:** 2026-09-28에 승인된 설계입니다. Owner가 같은 날 아래 여덟 가지 결정을 승인했습니다. 이
> 문서의 어떤 부분도 아직 구현되지 않았습니다. 현재 런타임은 [계층형 대화 계획](hierarchical-conversation-planning-ko.md)과
> [온톨로지 조회 커버리지 구현 계획](ontology-query-coverage-implementation-plan-ko.md)에 설명되어 있습니다.
> 커버리지 목표와 측정된 한도는 [온톨로지 추론 커버리지](ontology-reasoning-coverage-ko.md)가 담당합니다.
>
> **권한 경계:** 논리 형식, 수용 증적과 컴파일 증적, 앵커 바인딩, 결과 핸들, 계획은 모두
> `execution_authority=false`인 읽기 전용 기록입니다. 명시적인 변경 요청은 여전히 기존의 타입이
> 지정된 액션 초안만 만듭니다.

## 설계 개요

| 단계 | 책임 에이전트 | 출력 | 모델 사용 |
|------|---------------|------|-----------|
| 1. 대화 사전 판별 | Bragi | 사교, 지식, 운영 경로 선택 | T1, 변경 없음 |
| 2. 논리 형식 판단 | Bragi | 제안된 `SemanticQuestionForm` | T1, 한 번 호출과 최대 한 번의 스키마 복구 |
| 3. 수용 | Bragi | 수용된 형식, 명확화 또는 검토 요청 | 선택적 T2 검토 |
| 4. 개념 해석 | Mimir 카탈로그 | 개념 언급마다 영역이 제한된 바인딩 | 없음 |
| 5. 앵커 바인딩 | Muninn | 하나의 스냅샷에 고정된 정확한 식별자 | 없음, 범위가 제한된 읽기 1회 |
| 6. 컴파일과 검증 | Bragi 턴, 기계적 구성 요소 | 계획, 참고용 커버리지 증명, 독립적인 커버리지 검사 | 없음 |
| 7. 실행 | Muninn과 Heimdall 읽기 구성 요소 | 증적, 테이블, 계보, 완전성 | 없음 |
| 8. 인식 상태 평가와 렌더링 | Bragi | 목표별 상태와 이중 언어 답변 | 없음 |

컴파일러와 검증기는 Bragi가 소유한 의미 턴 안의 기계적인 Core 구성 요소입니다. 변경 불가능한
변환 결과를 소비하고, 에이전트를 호출하지 않으며, 아무것도 발행하지 않고, 턴 감사 기록은 Saga가
유지합니다. 지원되는 형식은 기능 이름 기반 의도와 모델이 작성한 프레임과 계획을 대체하며, 지원되지
않는 형식은 가장 가까운 기능 대신 빠진 원자와 이유를 정확히 반환합니다.

## 검증된 기준선

검토에서는 [`semantic_planning.py`](../../../services/core-control-plane/src/fdai/core/conversation/semantic_planning.py)의
`SemanticPlanningService.plan`부터 [`semantic_turn_processor.py`](../../../services/core-control-plane/src/fdai_core_service/semantic_turn_processor.py)의
렌더링까지 한 턴을 추적했습니다.

| 단계 | 현재 추론이 일어나는 곳 | 미비점 |
|------|-------------------------|--------|
| 사전 판별 | T1이 닫힌 운영 계열 9개 또는 `none` 중 하나를 고름 | 관계, 집계, 인식 축이 없어 관계 질문이 목록 또는 현재 상태 계열로 승격될 수 있음 |
| 판단 | T1이 FunctionType 이름을 `primary_intent`로 고르고, 대상 종류와 facet은 자유 토큰임 | FunctionType 이름 밖의 의미를 담을 타입이 없고, `resource_group` 같은 인스턴스 종류를 모델이 추측함 |
| 프레임 | 결정론적 빌더 22개, 없으면 T1 프레임 모델 | `SemanticProblemFrame`에 앵커, 관계, 방향, 집계, 이전 결과 필드가 없음 |
| 계획 | 형태별 컴파일러 32개, 없으면 T1 계획 모델 | 컴파일러가 정규식으로 발화에서 식별자와 구간을 다시 뽑고, 계획 모델은 레시피를 채우며 피연산자를 지어낼 수 있음 |
| 검증기 | 정확한 매니페스트, 끝점 연쇄, 한도, 형태와 노드 정렬 | 의미 보존, 피연산자 출처, 인스턴스와 스키마 구분 검사가 없음 |
| 실행 | 범위가 제한된 보안 ObjectSet, 단일 루트 탐색, 단계별 타입 경로 | 탐색 행에 루트 계보가 없고 링크 근거 속성은 가려짐 |
| 답변 | 형태별 템플릿, 불완전한 증적이 하나라도 있으면 턴 전체를 보류함 | 목표별 인식 상태가 없고, 후속 질문 맥락은 이전 턴 텍스트뿐임 |

2026-09-28에 영어와 한국어 추론 사례 36개로 두 번 실행한 범위가 제한된 실시간 계획 탐침은 관리되는
증적이 아니라 세션 안에서만 쓴 설계 입력이며, 실행마다 6개 사례만 질문대로 답했습니다. 14개에서
16개 사례는 다른 질문에 대한 검증된 계획을 만들었습니다. 이웃 대신 앵커 자신, 인스턴스 질문에 대한
스키마 관계, 뒤집힌 포함 방향, 이름 조각으로 읽힌 리전, 모두 0인 인시던트 식별자가 그 예입니다. 두
실행에서 같은 결과는 23개뿐이었습니다. 로컬 그래프에는 탐침한 앵커의 검증된 링크가 이미 있었으므로
관계 질문 실패는 대부분 컴파일러와 계약의 미비점이며, 측정된 데이터와 용량 한도는
[온톨로지 추론 커버리지](ontology-reasoning-coverage-ko.md#측정된-기준선)에 기록되어 있습니다.

## 근본 원인

| 분류 | 근본 원인 | 관찰된 실패 |
|------|-----------|-------------|
| 계약과 분류 체계 누락 | 닫힌 타입이 의미가 아닌 기능 이름을 가리키고, 관계, 방향, 집계, 리전, 인식 요구, 이전 결과 참조를 담을 닫힌 필드가 없음 | 연결된 리소스, 의존하는 리소스, 포함 관계, 그룹별 개수, `그 중에서`, `첫 번째` |
| 결정론적 컴파일러 부재 | 형태별 레시피가 피연산자를 어휘적으로 다시 뽑고, 관계를 검토된 LinkType 방향이나 경로로 옮기는 구성 요소가 없음 | 명시적 구간이 없는 변경 주체 질문, `안에 무엇이 있나`, `어느 그룹에 포함되나`, 서비스 경로 |
| 프롬프트 | 레시피 프롬프트가 계획 모델에 노드 형태를 베끼게 하지만 프롬프트 문구로는 출처를 강제할 수 없음 | 모두 0인 인시던트 식별자, 지어낸 정규 값 때문에 반복되는 판단 재시도 |
| 데이터와 reader 부재 | 보존된 토폴로지 이력, 워크로드 매핑, 경보나 열린 인시던트 reader, 비용 관측, 선언된 위치 속성, 링크 근거 변환 결과가 없음 | 토폴로지 비교, 서비스 영향, 경보, 열린 인시던트, 리전 필터, 검증 상태 |

프롬프트를 고치면 사례가 가까운 기능 사이를 옮겨 다닐 뿐, 연산자나 컴파일러나 reader가 생기지는
않습니다. 이 설계는 계약과 결정론적 구성 요소를 더하고 프롬프트를 줄입니다.

## 질문 논리 형식

`SemanticQuestionForm` 버전 `1.0.0`은 `SemanticJudgmentProposal` 스키마 `1.3.0`의 추가 필드
`question_form`으로 전달됩니다. 모든 필드는 닫힌 열거형, 범위가 제한된 정수, 언급 참조, 현재 발화의
정확한 원문 구간 중 하나입니다. 모델은 FunctionType, LinkType, ObjectType 피연산자, 객체 식별자,
인스턴스 정규 값을 절대 제공하지 않습니다.

| 필드 | 닫힌 값 |
|------|---------|
| `mentions[].form` | `identifier`, `name`, `concept`, `value`, `anaphor`, `ordinal` |
| `mentions[].domain` | `instance`, `object_type`, `resource_type`, `resource_class`, `state`, `health`, `metric`, `region`, `declaration_kind` |
| `mentions[].qualifier` | 앞선 언급 식별자 하나와 관계 의미, 예를 들어 이름이 지정된 네트워크 안의 서브넷 이름 |
| `goals[].level` | `instance`, `schema` |
| `goals[].operation` | `select`, `count`, `lookup`, `traverse`, `path`, `aggregate`, `rank`, `history`, `compare_windows`, `compare_entities`, `diff_versions`, `impact`, `explain_cause`, `verify_evidence`, `describe_schema`, `diagnose`, `draft_action` |
| `goals[].subject_scope` | `anchor`, `collection`, `prior_result`, `goal_output` |
| `filters[].role` | `type`, `state`, `health`, `region`, `name_fragment`, `scope` |
| `relation.sense` | `containment`, `attachment`, `dependency`, `connectivity`, `traffic`, `classification`, `composition`, `ownership`, `evidence` |
| `relation.scope` | `one_sense`, `all_kinds` |
| `relation.subject_position` | `source`, `target`, `either` |
| `relation.reach` | `one_hop`, `transitive` |
| `measure.kind` | `count`, `state`, `health`, `metric`, `change`, `event`, `forecast`, `cost` |
| `measure.group_by` | `endpoint`, `type`, `container`, `none` |
| `time.kind` | `current`, `window`, `as_of`, `two_windows`, `versions`, `future`, `unspecified` |
| `want` | `fact`, `cause`, `verification`, `completeness` |

하나의 형식에는 언급이 최대 16개, 목표가 최대 4개 들어갑니다. 목표마다 신뢰도와 연산 및 관계의
단서 구간이 있고, 목표는 앞선 목표에 의존할 수 있습니다. 모호성은 대안 최대 세 개로 표현하며, 각
대안은 주 형식과의 원자 차이 최대 6개로만 적고 하나로 합친 형식은 쓰지 않습니다. 직렬화한 형식이
6 KiB를 넘으면 `question_too_complex` 명확화를 반환합니다.

예: `Which resources depend on aks-prod-01?`

```yaml
question_form:
  mentions:
    - {id: m1, form: name, domain: instance, span: [26, 37]}
  goals:
    - id: g1
      level: instance
      operation: traverse
      subject: m1
      subject_scope: anchor
      relation: {sense: dependency, scope: one_sense, subject_position: target, reach: one_hop, cue: [16, 25]}
      time: {kind: current}
      want: fact
      confidence: 0.93
```

모델은 `aks-prod-01`이 의존 관계의 대상이라고만 말합니다. Core는 앵커를 바인딩하고, 검토된
`dependency` 특성으로 `depends_on`을 고르고, 대상 위치를 `incoming` 방향으로 옮깁니다.

## 수용

Bragi는 모든 구간이 현재 발화나 타입이 지정된 맥락 참조와 일치하고, 모든 목표가 설정된 신뢰도 하한을
넘고, 남은 대안 형식이 없고, 수준이 모든 언급 영역과 맞고, 제한 원자마다 단서 구간이 있을 때만
제안된 형식을 수용합니다. 수용에 실패하면 경쟁하는 해석을 나열한 명확화 하나를 반환하거나, 신뢰도가
낮은 수준, 관계, 방향, 지시 대상을 닫힌 필드만 비교하는 독립적인 T2 검토 한 번에 보냅니다. 앵커
바인딩 뒤에 바인딩된 앵커 타입이 가질 수 없는 관계 의미가 나와도 명확화를 반환합니다.

수용은 모델 권한을 제한할 뿐 없애지 않습니다. 틀렸지만 자기모순이 없는 형식은 단서 구간 검토, T2
검토, [보정된 수용](ontology-reasoning-coverage-ko.md#보정된-수용)의 해석 재진술과 확인 우선 칸, 평가
정답으로만 잡힙니다. 모델은 식별자, LinkType, 경로 단계, FunctionType, 답변 주장을 고르지 않습니다.

## 결정론적 컴파일

### 개념 해석

Core는 각 `concept` 또는 `value` 언급을 선언된 영역 안에서만, 검토된 이중 언어 카탈로그와 기존 구간
정규화로 해석합니다. FunctionType과 ActionType은 언어에서 해석하지 않고, 수용된 연산과 계약에서
따라 나옵니다.

- **클래스 폐포**: `resource_class` 언급은 `query.resource_class_closure`를 거쳐 정확한
  `Resource.type` 집합으로 컴파일되고 폐포 증적을 고정합니다.
- **영역 간 일치**: `AKS ObjectType`은 영역을 `object_type`으로 선언하지만 `AKS`는
  `kubernetes-cluster` `Resource.type` 값으로만 존재합니다. Core는 다른 선언으로 바꾸지 않고 그
  후보를 알려 주는 명확화를 반환합니다.
- **모호성**: 한 영역 안에 두 값이 남으면 둘 다 알려 주는 명확화 하나를 반환합니다.

### 앵커 바인딩

영역이 `instance`인 `identifier` 또는 `name` 언급은 앵커가 됩니다. 바인딩은 두 단계 프로토콜입니다.

1. 수용과 매니페스트, 목적, 범위 검사가 끝나면 Core는 단일 노드 해석 계획을 검증합니다. 조건은 정확한
   `id` 또는 `name` 일치, principal 범위, 현재 그래프 기준 시점, 행 7개 한도입니다.
2. 실행기는 스냅샷 하나를 읽습니다. 바인딩 증적은 원본 세대, 객체 리비전, 기준 시점, release,
   매니페스트, 범위 다이제스트를 고정합니다.
3. 컴파일된 계획은 그 증적 다이제스트를 참조하고 정확한 `root_ids` 또는 `object_ids`를 써야 합니다.
   실행기는 활성 원본 세대가 고정된 세대와 같은지 확인합니다. 세대가 바뀌면 기록되는 재바인딩과
   재컴파일을 한 번 허용하고, 그 뒤에는 보류합니다.

| 결과 | 처리 |
|------|------|
| 객체 1개 | 정확한 식별자와 바인딩된 ObjectType, `Resource.type`으로 컴파일 |
| 객체 2개에서 6개 | 범위가 제한된 후보를 담은 명확화 하나 |
| 객체 7개 | 이름을 좁혀 달라고 요청하는 불완전 명확화 |
| 없음, 원본 완전 | 검증된 범위 안의 부재와 범위가 제한된 이름 제안 |
| 없음, 원본 불완전 | 타입이 지정된 완전성 사유와 함께 보류 |

모델은 인스턴스를 리소스 그룹이나 클러스터로 분류하지 않으며, 바인딩된 타입이 그 추측을
대신합니다. `qualifier`가 있는 언급은 한정자를 먼저 바인딩한 뒤 그 한정자의 포함 범위나 타입 범위
안에서만 찾으므로, 기본 서브넷처럼 공유되는 이름도 정확하게 유지됩니다. 재현은 보존된 스냅샷으로
같은 증적을 해석하거나, 바인딩을 재현할 수 없다고 보고합니다.

### 관계 컴파일

관계 의미는 검토된 `semantic_traits`와 바인딩된 앵커 ObjectType으로 LinkType을 고릅니다.
`subject_position`은 `forward_role`과 `reverse_role`을 거쳐 `outgoing` 또는 `incoming` 조회 방향으로
옮겨지며, 저장된 방향은 절대 바꾸지 않습니다. `transitive` 도달은 전이적이고 자기 합성이 가능하다고
선언된 LinkType에만 허용되며 깊이는 최대 5입니다.

| 의미 | 특성 | 현재 LinkType |
|------|------|---------------|
| `containment` | containment | `contains` |
| `attachment` | attachment | `attached_to` |
| `dependency` | dependency | `depends_on` |
| `connectivity` | connectivity | `peered_with`, `routes_to`, `kubernetes_exposes_endpoint_slice` |
| `traffic` | traffic | `routes_to`, `runtime_calls` |
| `classification` | classification | `resource_classified_as`, `resource_type_member_of_class` |
| `evidence` | evidence | `kubernetes_backed_by`, `capacity_forecast_targets_resource`, `cost_observation_targets_resource` |
| `composition` | 새로 검토할 특성 | `implemented_by`, `workload_runs_on` |
| `ownership` | 새로 검토할 특성 | `owns`, `service_owned_by`, `workload_owned_by` |

- **매핑되지 않은 링크**: 검토된 특성이 없는 LinkType은 제외하고 `link_sense_unmapped`로 셉니다.
- **경로**: `path` 목표는 `BusinessService implemented_by Workload workload_runs_on Resource` 같은
  검토되고 버전이 지정된 경로 문법만 씁니다. 매니페스트 조회 방향에 대한 오프라인 탐색은 검토할
  문법을 제안할 수 있지만, 런타임이 스스로 최단 경로를 고르지는 않습니다. 적용 가능한 문법이 둘이면
  둘 다 보여 주는 명확화를 반환합니다.
- **모든 종류**: `연결된` 같은 모호한 표현은 [계층형 대화 계획](hierarchical-conversation-planning-ko.md)이
  요구하는 대로 대안 형식과 명확화 하나를 만듭니다. 모든 관계를 명시적으로 요청할 때만
  `scope: all_kinds`를 수용하며, 이 경우 범위가 제한된 1단계 이웃을 읽고 링크를 LinkType 역할별로
  묶어 보여 줄 뿐 하나의 합친 관계로 표현하지 않습니다.
- **실현 가능성**: 컴파일된 방향이 비어 있고 반대 방향에 링크가 있으면 답변은 그 사실을 제한 사항으로
  알리며 방향을 절대 뒤집지 않습니다.

### 연산자

| 연산 | 컴파일 |
|------|--------|
| `select`, `count`, `rank` | 근거에 기반한 타입, 상태, 건강, 이름 조각, 범위 조건식을 가진 ObjectSet 뒤에 정렬과 한도 노드, 인벤토리 전체 개수는 보안 집계 pushdown 사용 |
| `lookup` | 앵커 ObjectSet과, 선언된 출력이 요청한 측정을 포함하는 FunctionType, 바인딩되면 예측과 비용 reader 포함 |
| `traverse` | `root_ids`와 탐색을 가진 ObjectSet, 또는 끝점 타입이 있는 단계에는 `typed_path` |
| `aggregate` | 탐색이나 ObjectSet 뒤에 집계 노드, `endpoint`와 `container` 그룹화에는 행별 루트 계보가 필요 |
| `history` | 앵커에 대한 `query.resource_change_activity`, `query.resource_state_transitions`, `query.resource_event_history` |
| `compare_windows`, `diff_versions` | `topology_at` 노드 두 개와 `topology_diff`, 또는 `query.ontology_release_diff` |
| `compare_entities` | 같은 ObjectType의 앵커 두 개를 하나의 고정 기준 시점에서 같은 측정으로 읽음 |
| `impact` | 앵커에서 역방향 의존과 구성 폐포, 답변은 관측된 영향이 아닌 가능한 영향으로 표시 |
| `explain_cause` | 증상 측정, 이웃의 변경, 인과 지지 또는 반박 근거 |
| `verify_evidence` | 앵커 관계에 대한 링크 근거 변환 결과, 또는 범위 완전성을 위한 `query.ontology_evidence_health` |
| `describe_schema` | `query.manifest`, `query.ontology_declaration`, `query.ontology_relationships`, `query.resource_class_closure` |
| `diagnose` | 바인딩된 `Resource.type`과 증상 개념으로 고른 검토된 레시피 |

- **계약**: FunctionType 선택은 선언된 입력, 출력, `x-fdai-measure-concepts`, 의존성 전용 인자를
  맞춥니다.
- **집계 식별**: 개수는 서로 다른 객체 식별자를 세고, 경로 사이의 중복을 없애고, 숨겨진 객체는 알리지
  않은 채 합계와 연결에서 빼며, 계보나 관계 커버리지가 불완전하면 불완전 상태를 유지합니다.
- **시간**: 구간은 신뢰할 수 있는 UTC를 쓰고 유효 시간, 이벤트 시간, 기록 시간을 구분합니다.
  `unspecified` 이력 구간은 연산별로 버전이 고정된 서버 기본값을 씁니다.
- **지원되지 않는 원자**: `region` 필터는 선언된 `Resource.location` 속성이 생긴 뒤에만 컴파일되고,
  적용 가능한 레시피가 없는 `diagnose` 목표는 다른 타입의 레시피를 재사용하지 않습니다. 둘 다 이름
  조건식이나 대체 기능 대신 타입이 지정된 지원되지 않는 원자를 반환합니다.

### 후속 질문 참조

Core는 결정론적 렌더링 뒤에 `ResultSetHandle`을 발급하므로 운영자가 본 결과와 일치합니다. 불투명한
서버 측 핸들은 배포 범위, principal, 대화, 목적, 매니페스트 다이제스트, 만료, 렌더링 순서
다이제스트를 묶고, 타입 행 키, 정렬, 페이지, 잘림 메타데이터를 저장합니다. Operator는 핸들을 영속
턴과 함께 저장하고, 협상된 버전 아래에서 최근 핸들 참조를 최대 4개까지 타입이 지정된 요청 맥락으로
보냅니다. `ordinal` 또는 `anaphor` 언급은 재인가 뒤 핸들 행에 바인딩됩니다. `current_rehydrate`는
정확한 식별자를 현재 기준 시점에 다시 읽고 답변을 현재 상태로 표시하며, `snapshot_reference`는
보존된 스냅샷으로만 답합니다. 핸들이 없거나 만료되었거나, 다른 대화의 것이거나, 삭제되었거나,
범위를 벗어나면 명확화 하나를 반환합니다.

## 검증과 근거 의미

컴파일러는 `SemanticCoverageProof`를 참고용 증명으로 내보냅니다. 검증기는 이를 신뢰하지 않습니다. 카탈로그의
버전이 지정된 커버리지 규칙 표와 타입이 지정된 노드 출력 계보로 기대 커버리지를 다시 구성하고,
기존 검사는 모두 유지합니다.

- **V-SEM 커버리지**: 모든 연산, 필터, 관계, 측정, 정렬, 시간, 요구 원자는 규칙이 요구하는 노드
  패턴에 대응해야 합니다. 컴파일할 수 없는 제한 원자는 그 목표와 의존 목표를 막으며, 더 넓은 결과로
  낮추지 않습니다.
- **V-SEM 관계**: 탐색의 LinkType과 방향은 바인딩된 앵커 타입과 주체 위치에 대한 규칙 집합과 같아야
  합니다.
- **V-PROV 피연산자**: 모든 식별자나 리터럴 피연산자는 구간, 바인딩 증적, 결과 핸들, 신뢰할 수 있는
  서버 맥락, 서버 기본값 중 하나를 출처로 가져야 합니다. 모두 0인 식별자에는 출처가 없습니다.
- **V-LEVEL**: 인스턴스 목표는 스키마 전용 함수로 해결될 수 없고, 스키마 목표는 인스턴스를 읽을 수
  없습니다.
- **V-WANT**: `cause` 요구는 [시간과 인과에 관한 질문](hierarchical-conversation-planning-ko.md#시간과-인과에-관한-질문)의
  인과 조건을 충족하고 이름이 붙은 대안을 유지해야 합니다. 그렇지 않으면 목표는 시간 거리로만
  제한되고 원인을 주장할 수 없습니다.

각 목표는 [`epistemic_coverage.py`](../../../services/core-control-plane/src/fdai/core/conversation/epistemic_coverage.py)의
`EpistemicStatus` 어휘로 런타임 상태를 받습니다. `VERIFIED_EMPTY`에는 닫힌 모집단 증명, 즉 완전한
원본, 잘림 없음, 컴파일된 LinkType에 대한 완전한 관계 커버리지가 필요합니다. 그 밖의 빈 결과는
`UNKNOWN_INCOMPLETE`이며 검증된 범위 안에 일치 항목이 없다고만 말합니다. 워크로드 매핑이 없으면
비어 있는 것이 아니라 사용할 수 없는 것입니다. 목표 하나가 실패해도 검증된 형제 목표를 숨기지 않고,
답변은 알 수 없는 원자를 모두 나열합니다. 링크 근거는 `verified`, `verification_method`, 권한 주체,
유효 시간, 신선도 한도, 완전성으로 이루어진 검토된 허용 목록을 쓰며, 보이는 링크가 숨겨진 끝점을
드러낼 수 없다는 규칙은 그대로 유지합니다.

## 모델의 역할

| 결정 | 현재 | 목표 |
|------|------|------|
| 질문 의미 | 기능 이름과 자유 facet 토큰 | 단서 구간과 수용 검사를 갖춘 닫힌 논리 형식 |
| 이름이 붙은 객체의 인스턴스 종류 | 모델이 정한 대상 종류 | 앵커 바인딩 |
| 관계 방향 | 프레임 또는 계획 모델 | 수용된 위치를 검토된 방향으로 대응 |
| 경로와 LinkType 집합 | 계획 모델 또는 고정 레시피 | 검토된 특성과 경로 문법 |
| 피연산자 | 발화 정규식 또는 계획 모델 | 구간, 바인딩, 핸들, 서버 기본값 |
| 답변 주장 | 형태별 템플릿 | 독립적인 커버리지 검사와 인식 상태 |

판단 프롬프트는 보호된 루트를 유지하고, 읽기 목표에는 FunctionType 카탈로그 없이 닫힌 형식, 구간과
단서 규칙, 연산별 이중 언어 예시만 설명합니다. 컴파일된 형식에서는 프레임과 계획 모델 호출을 없애고,
계획 모델은 컴파일되지 않은 형식에 대해서만 shadow로 남아 V-SEM과 V-PROV를 통과해야 합니다. T2는
계획을 작성하지 않으며, 쓰이지 않는 `query.<LinkType>` 의도 경로는 제거합니다.

## 대안과 비평

| 대안 | 결정 | 이유 |
|------|------|------|
| 실패한 질문마다 레시피와 프롬프트 팩 추가 | 기각 | 질문 수만큼 늘어나고, 어휘적 재추출을 유지하며, 모델링되지 않은 원자를 여전히 버림 |
| 도구 호출을 쓰는 에이전트형 T2 탐색 | 기각 | 모델이 경로를 계산하게 되어 결정론, 출처, 재현이 약해짐 |
| 모델이 생성한 그래프 조회 텍스트 | 기각 | 원시 조회 텍스트는 계획 계약 밖에 있고 검증하기 어려움 |
| 개념에 대한 임베딩 권한 | 기각 | 유사도는 후보만 제안할 수 있음 |
| 논리 형식과 결정론적 컴파일러 | 선택 | 모델은 닫힌 분류에 머물고, 바인딩, 경로, 주장은 코드로 옮김 |

초안에 대한 독립 검토가 찾은 결함과 반영 내용은 다음과 같으며, 모두 이 설계의 일부입니다.

| 발견 | 반영 |
|------|------|
| 모델 권한 제거를 과장함 | 수용 검사, 단서 구간, 목표별 신뢰도, 선택적인 닫힌 필드 T2 검토, 좁힌 주장 |
| 어휘적 개념 추론 | `mentions[].domain`, 영역이 제한된 해석, 영역 간 일치에 대한 명확화 |
| 합쳐진 `연결된` 답변 | `any` 의미를 없애고, 모호하면 명확화하며, 명시적 요청만 `all_kinds`를 수용 |
| 스스로 인증하는 커버리지 | 독립적인 규칙 기반 커버리지, 막히는 제한 원자, 완전한 인과 조건 |
| 바인딩 경쟁 조건 | 두 단계 스냅샷 프로토콜, 증적 고정, 행 7개 잘림 감지 |
| 안전하지 않은 핸들 | 대화, 목적, 매니페스트, 렌더링 순서 바인딩과 명시적 모드 |
| 불분명한 소유권과 최단 경로 추측 | 단계별 책임 에이전트와 검토된 경로 문법 |
| 약한 통계와 빠진 전제 조건 | 잠긴 홀드아웃 세트, 독립 정답, 하한, 신뢰 구간, 계약 라운드, 데이터 게이트 |
| 승인 뒤 용량 검토: 중복 이름, 출력 예산, 빠진 질문 형태 | 한정 언급, 원자 차이 대안, 6 KiB 상한, [온톨로지 추론 커버리지](ontology-reasoning-coverage-ko.md#질문-분류-체계-완결)의 분류 추가 |

## 평가

추론 코호트는 실시간 계획 하네스를 확장하고 결정론적 실행 수준을 더합니다.

| 항목 | 계약 |
|------|------|
| 유형 | 폐포, 관계, 검토된 경로, 포함, 시간과 버전, 인과와 상관, 근거 검증, 관계 집계, 후속 질문, 스키마와 인스턴스 |
| 규모 | 유형마다 개발 사례 12개 이상과 잠긴 홀드아웃 사례 8개 이상을 언어별로 나누며, 정직한 부정 사례 3개와 여러 턴 후속 사례를 포함 |
| 정답 | 검토자 두 명이 형식 원자, LinkType 집합과 방향, 노드 종류, 범용 고정 그래프에서의 인식 상태, 금지 결과를 판정 |
| 견고성 | 표현, 언어, 이름, 순서를 바꾼 변형과, 중복 이름, 비어 있거나 잘린 이웃, 가려진 끝점을 넣은 적대적 고정 그래프 |
| 수준 | L1은 실시간 T1 형식 정확도를 측정하고, L2는 모델 없이 고정 그래프에서 수용, 컴파일, 실행을 수행 |
| 절대 0 | 정답 대비 조용한 의미 손실, 출처 없는 피연산자, 잘못된 수준의 답변, 인과 근거 없는 인과 주장, 인가되지 않은 실행 |
| 측정 | 원자 정확도, 형식 안정성, L2 정확도, 정직한 사유의 정밀도, 명확화 정밀도와 재현율, 모델 호출 수, 100턴 이상에서 구한 p95 지연 |

세션 안에서만 쓰던 68개 사례 프롬프트 코퍼스는 수준, 금지 함수, 필수 원자 검사를 더해 저장소로
옮기며, 잘못된 검증 계획은 더 이상 통과하지 못합니다. 현재 프로필의 A/A 실행이 1.5점 차이를 보였으므로, 짝 비교는 반복 3회 이상,
부트스트랩 신뢰 구간, 3점 잡음 구간을 씁니다. 홀드아웃 세트 약 60턴에서 절대 실패가 0이면 95% 신뢰도로
실제 비율의 상한은 약 5%이므로, shadow 운영에서는 승격 전에 실시간 턴도 표본으로 뽑아 사람이
검토합니다.

## 전달 라운드

| 라운드 | 범위 | 종료 근거 |
|--------|------|-----------|
| R0 | 코호트, 홀드아웃 세트, 고정 그래프, 엄격한 정답, 운영과 같은 함수 바인딩을 쓰는 하네스 | 기준선 L1과 L2 증적 |
| R1 | 버전 협상을 갖춘 형식, 수용, 바인딩, 핸들, 커버리지 규칙, 근거 매니페스트, pushdown 계약 | 코덱과 N/N-1 테스트, 동작 변경 없음 |
| R2 | 기존 타입 판단 필드에 대한 임시 V-PROV와 V-LEVEL, 정확한 그룹에서 `contains`로 구하는 리소스 그룹 소속 | 지어낸 식별자 리터럴 0건, 인스턴스 대상에 대한 스키마 답변 0건, 고정 그래프에서 `contains` 폐포와 같은 소속 |
| R3 | shadow 형식 판단과 수용 | 홀드아웃 세트에서 유형별 원자 정확도 90% 이상, 안정성 90% 이상 |
| R4 | 개념 해석기와 앵커 바인딩 프로토콜 | 고정 그래프에서 L2 바인딩 정확도 100% |
| R5 | 특성 검토, 경로 문법, 탐색 루트 계보 뒤의 관계 컴파일러 | shadow 관계와 포함 홀드아웃 세트 85% 이상, 절대 0 유지 |
| R6 | 집계, 순위, 진단 레시피, 위치 속성 출시 뒤의 리전 | shadow 집계와 진단 홀드아웃 세트가 절대 0 유지 |
| R7 | 링크 근거 허용 목록 뒤의 이력, 버전, 원인, 검증 | 이력이 없을 때 타입이 지정된 사용 불가, 인과 근거 없는 인과 주장 0건 |
| R8 | 위협 검토 뒤의 결과 핸들 | 후속 질문 홀드아웃 세트 85% 이상, 대화 간 바인딩 0건 |
| R9 | 승격 레지스트리를 통한 연산 계열별 승격 | 계열별 승격 증적, 승격된 계열의 프레임과 계획 프롬프트 제거 |
| R10 | 승격된 경로에서 어휘적 재추출 제거 | 재현 동등성과 안정적인 롤백 릴리스 1회 |

모든 라운드는 구현하고, 집중 테스트를 실행하고, L1을 2회 이상 반복하고 L2를 실행하고, 회귀를
고치고, 원장에 행을 추가합니다. 형식 경로는 현재 경로 옆에서 shadow로 실행되고 다이제스트와 처리
결과만 기록합니다. 한 계열은 모든 반복과 표본 shadow 턴에서 절대 0이 유지되고, 홀드아웃 세트 정확도가
절대 하한을 넘고 잡음 구간 밖에서 현재 경로보다 좋으며, 영어와 한국어의 차이가 5점 이하이고, p95
지연이 늘지 않고, 68개 사례 코퍼스가 잡음 이상으로 후퇴하지 않을 때만 승격됩니다. 롤백은 이전
레지스트리 항목을 복원하며, 현재 경로는 R10까지 그대로 유지됩니다.
[온톨로지 추론 커버리지](ontology-reasoning-coverage-ko.md#완결-프로그램)의 계열별 레인이 이 라운드들을
제한합니다.

## 승인된 결정

Owner가 2026-09-28에 다음 결정을 승인했습니다.

1. 형식을 같은 판단 호출의 추가 필드로 전달합니다.
2. 컴파일 전에 두 단계 앵커 바인딩 읽기를 허용합니다.
3. 모호한 관계에는 명확화를 유지하고, `all_kinds`는 명시적 요청에만 수용합니다.
4. 상태 구간이 카탈로그에 근거하지 않을 때만 T2 상태 검토를 요구합니다.
5. 버전이 고정된 기본 이력 구간을 설정에서 관리합니다.
6. 검토된 제공자 리전 값 영역과 함께 `Resource.location`을 선언합니다.
7. 검토된 링크 근거 허용 목록을 보안 변환 결과로 노출합니다.
8. 결과 핸들을 영속하고 의미 요청 계약에 추가합니다.

## 관련 문서

| 알아볼 내용 | 문서 |
|-------------|------|
| 전달 상태와 남은 작업 | [구현 원장](../../roadmap-implementation/interfaces/ontology-reasoning-compiler.md) |
| 커버리지 보장, 측정된 한도, 종결 프로그램 | [온톨로지 추론 커버리지](ontology-reasoning-coverage-ko.md) |
| 최상위 설계 권한 | [FDAI 헌법](../architecture/fdai-constitution-ko.md) |
| 현재 의미 턴 경로 | [계층형 대화 계획](hierarchical-conversation-planning-ko.md) |
| 조회 계약과 작업 패키지 | [온톨로지 조회 커버리지 구현 계획](ontology-query-coverage-implementation-plan-ko.md) |
| LinkType 역할, 특성, 타입 경로, 폐포 | [온톨로지 구조 모델](../architecture/ontology-structural-model-ko.md) |
| ObjectSet과 타입 함수 | [FDAI 온톨로지 안전 인프라](../architecture/operating-ontology-platform-ko.md) |
| 그래프 신선도와 완전성 | [연속 운영 인스턴스 그래프](../architecture/continuous-operational-instance-graph-ko.md) |
| 질문 공간과 보증 | [연속 질문 공간](continuous-question-space-ko.md) |
| 프롬프트 프로필과 동적 조립 | [진화하는 시스템 프롬프트](../decisioning/prompt-composition-ko.md) |
