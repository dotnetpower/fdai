---
translation_of: ontology-query-randomized-assurance.md
translation_source_sha: 31c21bb2c88231e27970a215943b5a7700eb8a24
translation_revised: 2026-08-20
---
# 온톨로지 쿼리 무작위 보증

이 문서는 영어 및 한국어 온톨로지 질문 100개에 대한 2026-08-11 역사적 채점 기준선과
2026-08-20 통제된 live 인증을 보존합니다. 현재 인증은 구문 규칙, 질문별 별칭 또는 고정
답변 템플릿을 추가하지 않고 검증된 의미 런타임을 측정합니다.

> **릴리스 결정:** 검증됨. 중앙 검증된 source
> `4dc5365aaf8d2f6d8c6e0e9aaac4b6374a54f766`이 strict v2 22/22와 seeded 100/100 변경 불가능
> gate를 exact transport, 모든 answered turn의 완전한 근거, capability mismatch 0건,
> unsupported operational claim 0건 및 unauthorized execution 0건으로 통과했습니다.
>
> **근거 경계:** 현재 커밋한 아티팩트는 통과한 live artifact를 repository-safe하게
> 변환한 결과입니다. 통제된 digest, typed result, evidence count 및 hash된 request와
> projection identity를 보존하지만 환경 UUID, 원시 provider payload, token, endpoint,
> screenshot 또는 전체 model response는 포함하지 않습니다.

## 현재 통제 결과

| 측정 항목 | 결과 |
|-----------|------|
| 엄격한 이중 언어 gate | 형식화된 판단 22/22, 완전한 근거가 있는 답변 16/16 |
| Seeded typed judgment | 100/100 통과 |
| 근거가 완전한 답변 | Answered turn 73/73 |
| 통제된 non-answer disposition | Action draft 6개, clarification 9개, evidence hold 2개, unsupported 10개 |
| Exact request 및 projection transport | 각각 100/100 |
| Plan-capability mismatch | 0 |
| Unsupported operational claim | 0 |
| Unauthorized execution | 0 |
| Ambient 또는 incident-bound request | 0 |
| Production ready | `true` |

## 역사적 설계 개요

이 실행은 도구를 비활성화한 모델로 균형 잡힌 질문 집합을 생성하고 수정한 다음, 실제
Console Command Deck을 통해 모든 질문을 제출하고 최종 assistant 카드를 기다렸습니다.
충분성을 서로 독립적으로 평가했습니다.

```mermaid
flowchart LR
    Q[생성된 질문 100개] --> V[질문 집합 기계 검증]
    V --> C[인증된 Console Command Deck]
    C --> T[최종 응답 캡처]
    T --> J[독립적인 근거 인식 judge]
    J --> R[의도 및 답변 성공률]
    R --> D[릴리스 결정 및 조치 원장]
```

## 역사적 방법

- **질문 집합:** 고유 질문 100개이며 영어 50개와 한국어 50개입니다.
- **생성:** 도구 비활성화 모델이 질문 집합을 생성했습니다. 두 번째 모델 통과에서 잘못된
  처리 결과 하나와 언어 비율을 수정했습니다. 이후 기계 검증으로 개수, 고유성, 언어
  균형 및 허용된 처리 결과 집합을 확인했습니다.
- **범위:** 온톨로지 타입, 관계 탐색, 담당 체계, 현재 상태, VNet 라우팅, 프라이빗
  엔드포인트, 과거 토폴로지, 메트릭 비교, 인과 근거, 규칙, 에이전트 권한, 근거 보류,
  명확화, 안전하지 않은 작업 및 초안 전용 변경을 다룹니다.
- **실행:** 모든 질문은 `/architecture`의 인증된 Console에서 `POST /chat/stream`을 통해
  제출했습니다.
- **캡처:** 완료된 assistant 카드가 있어야 최종 응답으로 인정했고 임시 준비 텍스트를
  제외했습니다. 초기에 사용한 약한 draft-card 조건의 결과는 폐기하고 전체 질문 집합을
  다시 실행했습니다.
- **판정:** 별도의 도구 비활성화 모델이 하나의 엄격한 평가 기준을 적용했습니다. 의도 성공은
  요청한 작업, 범위, 시간, 근거 자세 및 읽기와 작업의 구분을 이해해야 합니다. 답변
  성공은 예상 처리 결과와 충분히 인용된 근거도 필요합니다.
- **안전:** 제품에 답변 텍스트, 구문 별칭, 정규식 경로 또는 예상 응답 문장을 추가하지
  않았습니다.

## 역사적 2026-08-11 결과

| 측정 항목 | 결과 |
|-----------|------|
| 최종 완료 | 100/100 (100%) |
| 의도 인식 | 100/100 (100%) |
| 답변 성공 | 20/100 (20%) |
| 영어 답변 성공 | 10/50 (20%) |
| 한국어 답변 성공 | 10/50 (20%) |
| 중앙값 지연 시간 | 2,405 ms |
| p95 지연 시간 | 3,186 ms |
| 최대 지연 시간 | 3,519 ms |
| 기계적으로 검증된 답변 | 0/100 |
| 근거 검사를 포함한 카드 | 0/100 |
| `Unsupported claim` 표시 카드 | 100/100 |

의도 성공률 100%는 서술기가 일반적으로 요청한 작업에 대응했음을 의미합니다. 이 값은
`SemanticProblemFrame`, `OntologyQueryPlan` 또는 검증된 쿼리 DAG가 생성되었음을 의미하지
않습니다. 답변 성공률 20%는 주로 안전한 근거 보류, 안전하지 않은 작업 거절 및 검토
가능한 초안으로 구성됩니다. 프로덕션 온톨로지 쿼리 준비 상태를 입증하지 않습니다.

### 작업별 결과

| 작업 | 질문 수 | 의도 | 답변 |
|------|---------|------|------|
| 초안 전용 작업 | 3 | 100% | 100% |
| 에이전트 권한 | 6 | 100% | 50% |
| 인과 지지 또는 반증 | 8 | 100% | 12.5% |
| 명확화 | 5 | 100% | 40% |
| 과거 토폴로지 | 8 | 100% | 0% |
| 근거 부족 | 4 | 100% | 100% |
| 메트릭 비교 | 8 | 100% | 0% |
| 온톨로지 객체 선택 | 8 | 100% | 25% |
| 담당 체계 | 6 | 100% | 0% |
| 프라이빗 엔드포인트 | 8 | 100% | 0% |
| 관계 탐색 | 8 | 100% | 12.5% |
| 리소스 상태 | 10 | 100% | 0% |
| 규칙 | 6 | 100% | 0% |
| 지원되지 않는 직접 작업 | 4 | 100% | 100% |
| VNet 피어링 및 라우팅 | 8 | 100% | 0% |

## 근본 원인

2026-08-11 측정 당시 독립 Operator 서비스는 로컬 Azure 서술이 활성화되면
[`LocalAzureNarratorAdapters`](../../../services/operator-service/src/fdai_operator_service/adapters/local_narrator.py)를
`chat.stream` 읽기 담당으로 구성합니다. 이 어댑터는 화면 컨텍스트와 함께 모델을 호출하고
`status=unverified`, `checks_completed=0` 및 빈 근거 참조를 내보냅니다.
[`ProductionOperatorComposition`](../../../services/operator-service/src/fdai_operator_service/composition.py)은
Core
[`SemanticConversationRuntime`](../../../services/core-control-plane/src/fdai/core/conversation/semantic_runtime.py)을
바인딩하지 않았습니다.

현재 소스는 authoritative PostgreSQL 저장소와 semantic transport가 구성되면
`SemanticTurnBridge`를 생성합니다. 기준선 이후의 이 구현은 기록된 결과를 바꾸거나 전체
의미 쿼리 경로가 아래 종료 조건을 충족했음을 입증하지 않습니다.

측정된 실패는 언어 범위 문제가 아니라 서비스 구성 차이였습니다. 키워드 경로나 고정 답변을
추가하면 차이를 숨기고 대상 설계를 위반합니다. 완료하려면 다음이 필요합니다.

1. 수락한 각 일반 언어 턴을 버전이 지정된 이벤트 버스 요청 및 응답 계약을 통해 독립
   Operator 서비스에서 Core 런타임으로 전달합니다.
2. 프로덕션 의미 모델, principal 범위로 한정된 서술자 인덱스, 정확한 온톨로지 릴리스, 쿼리
   핸들러, 과거 토폴로지 읽기 담당, 메트릭 프로바이더 및 규칙과 담당 체계 변환 결과를 Core에
   바인딩합니다.
3. 검증된 의도 그래프, 목표 증적, 정확한 근거 참조 및 타입이 지정된 최종 처리 결과를
   기존 Console 스트림 계약으로 반환합니다.
4. Bragi는 최종 표시 translator로 유지합니다. 쿼리 실행을 대체하거나 작업 권한을
   부여하면 안 됩니다.
5. 필수 프로바이더를 사용할 수 없으면 타입이 지정된 보류 또는 명확화로 전환합니다. 모델
   지식이나 화면 요약에서 운영 사실을 추론하지 않습니다.

## 30회 비평 및 조치 라운드

| 라운드 | 관점 | 결과 및 일반화된 조치 |
|--------|------|-----------------------|
| 1 | 질문 집합 무결성 | 완료: 고유하고 변경 불가능한 질문 id 100개를 유지했습니다. |
| 2 | 언어 균형 | 완료: 영어와 한국어를 각각 50개로 독립 측정했습니다. |
| 3 | 처리 결과 스키마 | 완료: 잘못 생성된 처리 결과를 모델로 수정한 뒤 스키마 검증했습니다. |
| 4 | 최종 캡처 | 완료: 임시 초안 카드를 제외하고 최종 조건으로 전체 질문을 다시 실행했습니다. |
| 5 | 완료 | 완료: 최종 전달과 정확성을 구분했습니다. |
| 6 | 지연 시간 | 완료: 속도를 품질로 간주하지 않고 턴별 지연을 기록했습니다. |
| 7 | 경로 출처 | 완료: 모든 턴을 로컬 Azure 서술기 경로에 귀속했습니다. |
| 8 | 의도 인식 | 완료: 의도를 근거 및 답변 성공과 별도로 평가했습니다. |
| 9 | 답변 성공 | 진행 중: 20%이므로 프로덕션 완료 주장을 차단합니다. |
| 10 | 온톨로지 스키마 | 진행 중: 프로덕션 턴에 정확한 principal 범위로 한정된 매니페스트와 릴리스가 필요합니다. |
| 11 | 관계 탐색 | 진행 중: 추론된 관계 경로를 타입이 지정된 DAG 실행으로 교체해야 합니다. |
| 12 | 담당 체계 | 진행 중: 권위 있는 담당 체계 데이터를 바인딩하거나 타입이 지정된 보류를 반환합니다. |
| 13 | 리소스 상태 | 진행 중: 보안 ObjectSet 읽기를 바인딩하고 없는 속성은 알 수 없음으로 유지합니다. |
| 14 | VNet 라우팅 | 진행 중: 토폴로지 및 정확한 리소스 경로 근거를 바인딩합니다. |
| 15 | 프라이빗 엔드포인트 | 진행 중: 정확한 첨부, DNS 및 연결 상태 관측을 바인딩합니다. |
| 16 | 과거 토폴로지 | 진행 중: 신뢰할 수 있는 기준 시점과 bitemporal 읽기 담당을 구성합니다. |
| 17 | 메트릭 의미 | 진행 중: 검토된 개념과 제한된 프로바이더 구간을 구성합니다. |
| 18 | 인과 근거 | 진행 중: 근거 결합을 실행하고 경쟁 설명을 유지합니다. |
| 19 | 규칙 카탈로그 | 진행 중: principal 매니페스트를 통해 검토된 서술자를 노출합니다. |
| 20 | 에이전트 권한 | 진행 중: 권한을 부여하지 않고 타입이 지정된 기능 및 권한 서술자를 변환 결과합니다. |
| 21 | 근거 부족 | 완료: 근거 보류를 유효한 최종 결과로 유지했습니다. |
| 22 | 명확화 | 진행 중: 의미 프레임에서 하나의 중요한 명확화를 생성합니다. |
| 23 | 안전하지 않은 작업 | 완료: 안전하지 않은 직접 요청 4개를 실행 주장 없이 모두 거절했습니다. |
| 24 | 작업 초안 | 완료: 초안 요청 3개를 모두 검토 전용으로 유지했습니다. |
| 25 | 검증 일관성 | 완료: 표시된 출처 링크를 실행 근거로 계산하지 않았습니다. |
| 26 | 출처 참조 무결성 | 진행 중: 검증에 정확한 쿼리 증적 참조를 포함해야 합니다. |
| 27 | 서비스 경계 | 진행 중: Core 구현 가져오기 대신 버전 지정 이벤트 버스 브리지를 추가합니다. |
| 28 | 키워드 강화 제외 | 완료: 구문별 라우팅을 수정 조치에서 제외했습니다. |
| 29 | 답변 템플릿 제외 | 완료: 고정 응답을 제외하고 스키마 기반 생성을 유지했습니다. |
| 30 | 릴리스 결정 | 진행 중: 프로덕션 의미 구성이 실제 증적을 내보낸 뒤에만 다시 실행합니다. |

## 다음 실행의 종료 조건

다음 무작위 실행은 다음 조건을 모두 충족할 때만 릴리스 결정을 변경할 수 있습니다.

- 수락한 모든 일반 언어 질문은 의미 경로 또는 타입이 지정된 사용 불가 사유를 기록합니다.
  로컬 서술기 경로를 의미 실행으로 보고하지 않습니다.
- 답변된 온톨로지 질문은 정확한 온톨로지 릴리스 다이제스트, principal 매니페스트 다이제스트, 검증된
  계획 다이제스트 및 관련 근거 참조를 하나 이상 포함합니다.
- 보류, 명확화, 지원하지 않는, 액션 초안 또는 취소된 결과는 산문에서 추론하지
  않고 타입이 지정된 처리 결과로 나타냅니다.
- 과거, 메트릭, 인과, 규칙, 담당 체계 및 현재 상태 질문 집합은 각각의 권위 있는
  프로바이더를 사용합니다. 프로바이더가 없으면 이를 명시합니다.
- 지원되지 않는 운영 주장과 권한 없는 실행은 0을 유지합니다.
- 예상 답변 텍스트를 재생하지 않고 동일한 100개 질문 절차를 다시 생성합니다.

## 근거 아티팩트

현재 통제된 기준선은
[`ontology-query-randomized-assurance-2026-08-20.json`](../../baselines/ontology-query-randomized-assurance-2026-08-20.json)입니다.
통과한 source revision, 구성, 인증 증명, exact transport count와 topic digest, typed result
100개 및 hash된 request와 projection identity를 결속합니다.

역사적 채점 기준선은
[`ontology-query-randomized-assurance-2026-08-11.json`](../../baselines/ontology-query-randomized-assurance-2026-08-11.json)입니다.
일반 질문 100개, 의도한 작업, 예상 및 관찰 처리 결과, 질문별 의도와 답변 점수, 지연
시간, 실패 범주, 집계 성공률 및 30회 라운드 원장을 포함합니다.

## 구현 상태

### 구현 범위

| 영역 | 상태 | 근거 | 참고 |
|------|------|------|------|
| 2026-08-20 strict-v2 통제 기준선 | validated | [`ontology-query-randomized-assurance-2026-08-20.json`](../../baselines/ontology-query-randomized-assurance-2026-08-20.json) | 중앙 검증된 source `4dc5365aaf8d2f6d8c6e0e9aaac4b6374a54f766`에서 repository-safe하게 변환했습니다. Strict v2는 22/22, seeded는 exact transport, 모든 답변의 완전한 근거 및 safety counter 0건으로 100/100을 통과했습니다. |
| 2026-08-18 통제 무작위 기준선 | validated | [`ontology-query-randomized-assurance-2026-08-18.json`](../../baselines/ontology-query-randomized-assurance-2026-08-18.json) | 중앙 검증된 source `a38922762ed805794b11bb9c6aaef43916f6f6c4`의 통과한 full live artifact를 repository-safe하게 변환했습니다. Strict는 14/14, seeded는 exact transport와 safety counter 0건을 유지하며 100/100을 통과했습니다. |
| 2026-08-11 무작위 기준선 | in-progress | [`ontology-query-randomized-assurance-2026-08-11.json`](../../baselines/ontology-query-randomized-assurance-2026-08-11.json) | 아티팩트는 역사적인 채점 측정값과 차단된 릴리스 결정을 보존하지만 통제된 런타임 증적은 아닙니다. 소스 리비전, 구성 다이제스트, 인증 증명, 정확한 요청 및 응답 증적 참조가 없습니다. |
| 독립 semantic-turn bridge | implemented | [`composition.py`](../../../services/operator-service/src/fdai_operator_service/composition.py), [`semantic_turn_runtime.py`](../../../services/operator-service/src/fdai_operator_service/families/conversation/semantic_turn_runtime.py), [`test_semantic_turn_bridge.py`](../../../services/operator-service/tests/test_semantic_turn_bridge.py) | 운영 composition은 Core 구현을 가져오지 않고 durable event-bus bridge를 바인딩할 수 있습니다. |
| Authoritative 프로바이더 및 증적 종료 | validated | 2026-08-18 통제 기준선과 exact full-gate 요약 | 모든 typed judgment가 통과했습니다. Answered turn은 exact release, principal manifest, verified plan, execution receipt 및 evidence reference를 보존하고 통제된 non-answer disposition은 명시적으로 유지합니다. |
| 격리 보증 child 감독 | implemented | [`run_ontology_assurance.py`](../../../scripts/automation/run_ontology_assurance.py), [`ontology_assurance_supervisor.py`](../../../scripts/automation/ontology_assurance_supervisor.py), [`test_ontology_assurance_supervisor.py`](../../../tests/integration/scripts/test_ontology_assurance_supervisor.py) | 소스에 바인딩된 runner가 전용 Core, Operator, Console 및 Playwright 프로세스 그룹과 실행 범위의 영속 semantic outbox 네임스페이스를 소유합니다. 필수 child가 종료되면 측정 단계를 즉시 중지하고 소스 리비전, PID, 프로세스 그룹, 종료 코드 또는 신호 및 종료 사유를 원자적으로 보존합니다. 이는 runner 메커니즘과 요청 격리를 입증하지만 엄격한 질문 집합 통과를 입증하지는 않습니다. |
| 리포지토리에 안전한 통제 기준선 변환 | validated | [`project_ontology_assurance_baseline.py`](../../../scripts/automation/project_ontology_assurance_baseline.py), [`test_project_ontology_assurance_baseline.py`](../../../tests/integration/scripts/test_project_ontology_assurance_baseline.py) 및 2026-08-18 기준선 | 변환기가 전체 변경 불가능 gate를 다시 검사하고 원본 artifact digest를 결속하며 exact request 및 projection identity를 hash했습니다. 보존 기준선에는 환경 UUID 또는 원시 provider payload가 없습니다. |
| 현재 무작위 릴리스 인증 | validated | [Issue #233](https://github.com/dotnetpower/fdai/issues/233), 실행 `question-space-final-4dc5365aa-20260820-r15`, 2026-08-20 통제 기준선 | Strict v2는 passing typed judgment 22개와 근거가 완전한 답변 16개를 보존했습니다. Seeded는 live 100개, resumed 0개 및 passing typed judgment 100개와 함께 근거가 완전한 답변 73개, exact request 및 projection transport 100/100 및 safety counter 0건을 보존했습니다. |

### 구현 이력

| 날짜 | 상태 | 변경 | 근거 | 남은 작업 |
|------|------|------|------|-----------|
| 2026-08-11 | validated | 의도 인식 100%, 답변 성공 20%, 기계적으로 검증된 답변 0건인 첫 bilingual 100개 질문 무작위 기준선을 보존했습니다. | 위에 연결된 커밋된 기준선 아티팩트 | 의미 경로를 구축하고 같은 절차로 다시 실행해야 합니다. |
| 2026-08-13 | in-progress | 구현 원장을 도입하고 semantic bridge composition이 구현된 뒤 근본 원인을 측정 당시 표현으로 수정했습니다. 이전 구현 출처 이력은 재구성하지 않았습니다. | `current change`; 구현 범위 표에 나열된 현재 composition 및 focused bridge 테스트 | Authoritative 프로바이더를 종료하고 통과한 재생성 기준선을 보존해야 합니다. |
| 2026-08-13 | in-progress | 보존된 채점 측정값은 통제된 런타임 증적이 아니므로 역사적 기준선 상태를 정정했습니다. | `current change`; 기준선에는 소스 리비전, 구성 다이제스트, 인증 증명, 정확한 요청 및 응답 증적 참조가 없으며 카드 100개가 모두 검증되지 않은 상태와 근거 0/0으로 기록되어 있습니다. | 다음 실행 종료 조건을 충족하는 통제된 재실행 아티팩트를 보존해야 합니다. |
| 2026-08-15 | in-progress | 격리된 소스 `e476fa21c5f00c276f651497ef352a3bbfd0e17f`에서 엄격한 영문 및 한국어 14-cell 검사를 한 번 실행했습니다. 외부 종료로 최종 결과 6개 이후 실행이 중단되었고, 출처 이력에 바인딩된 검사점에 fail-closed `turn_error` 결과 2개를 기록했습니다. | [Issue #63](https://github.com/dotnetpower/fdai/issues/63), 실행은 소스, 구성, 작업 공간, 질문 집합 및 부분 결과 바인딩을 보존했습니다. | 엄격한 검사를 열린 상태로 유지합니다. 엄격한 실행에서 근거가 완전한 답변 cell 14개를 보존할 때까지 seed 기반 100-case 검사를 시작하지 않습니다. |
| 2026-08-16 | in-progress | 중앙 검증을 통과한 격리 소스 `91f0e888e5c1d2ce96cb4b1a3e2d5a68e1116e9c`에서 seed `0x0fda1`, 15초 간격, 180초 시도 기한 및 30분 실행 예산으로 엄격한 영문 및 한국어 14-cell 검사를 수행했습니다. 아티팩트는 재개 cell 없이 live cell 14개를 보존했습니다. 3개가 통과했고, 11개는 전송 시도를 두 번 모두 소진해 실패했으며, 답변 cell 1개가 완전한 근거를 포함했습니다. 지원되지 않는 운영 주장, 권한 없는 실행 및 계획 기능 불일치는 모두 0건이었습니다. | [Issue #63](https://github.com/dotnetpower/fdai/issues/63), 아티팩트 스키마 `1.3.0`, 실행 구성 `1.4.0`, 구성 다이제스트 `sha256:a95b52e599f4b975dc8a565d7c0f036b249a3c47484396dc8f087d56b27cc4bd` 및 변경 없는 작업 공간 패치 다이제스트 `sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`를 보존했습니다. Core는 `2026-08-16T03:27:30Z`에 외부 `SIGTERM`을 기록했고 요청 및 변환 결과 토픽의 최대 오프셋은 각각 레코드 4개와 3개에서 멈췄습니다. | 엄격한 검사를 차단 상태로 유지합니다. 근거가 완전한 필수 답변 cell 14개를 보존하지 못했으므로 seed 기반 100-case 검사는 올바르게 시작하지 않았습니다. 소스에 바인딩된 다음 보증 시도 전에 격리 child 감독을 강화해야 합니다. |
| 2026-08-17 | implemented | 필수 child 프로세스 그룹을 감독하고 Core, Operator 또는 Console이 종료되면 측정 단계를 즉시 fail-closed 처리하는 추적 가능한 detached-capable 보증 runner를 추가했습니다. 원자적인 mode-`0600` 상태 레코드에 child 및 runner 출처 이력을 보존하고, 상속받은 환경 값이 프로세스 인자와 상태에 기록되지 않도록 하며, 새로운 엄격한 검사점을 요구하고, 변경 불가능한 엄격한 아티팩트 검사를 통과하기 전에는 seed 기반 질문 집합을 시작할 수 없게 합니다. | `current change`, focused supervisor 검사 6개, 작업 범위 Ruff 및 두 runner 모듈의 strict mypy가 통과했습니다. | 중앙 검증 증적을 확보한 다음 정확히 그 소스 리비전에서 새로운 엄격한 14-cell 실행을 한 번 수행합니다. 엄격한 아티팩트가 기존 조건을 모두 통과한 경우에만 seed `0x0fda1` 기반 100-case 실행을 한 번 시작합니다. |
| 2026-08-17 | implemented | 전용 Kafka 토픽과 consumer group만으로는 PostgreSQL claim을 격리하지 못한다는 사실을 두 번의 새로운 엄격한 실행에서 확인한 뒤 각 보증 실행의 영속 semantic outbox를 격리했습니다. 동시에 실행 중인 표준 Operator가 실행 소유 요청을 claim하고 다른 Core 세대를 통해 게시할 수 있어 한 아티팩트에 두 개의 정확한 온톨로지 release가 섞였습니다. 선택적 네임스페이스는 운영 기본 키를 바꾸지 않고 runner의 append, claim, read 및 변환 결과 소유권을 함께 격리합니다. | `current change`, focused Operator 환경, 저장소 lease 및 runner 검사 11개가 통과했습니다. 실패한 아티팩트는 재시도 없이 live cell 14개를 보존했고 혼합 세대 및 답변 coverage gate에서 seed 기반 집단을 차단했습니다. | 중앙 검증 증적을 확보하고 네임스페이스가 적용된 정확한 소스에서 새로운 엄격한 검사를 다시 실행합니다. 변경 불가능한 엄격한 조건을 모두 통과한 뒤에만 seed 기반 집단을 시작합니다. |
| 2026-08-17 | implemented | 통과한 전체 live 아티팩트 하나를 위한 결정론적이며 리포지토리에 안전한 변환을 추가했습니다. 변환은 현재 변경 불가능한 gate를 다시 확인하고 원본 아티팩트 digest와 통제된 구성, 인증, 요약 및 결과 근거를 보존하며 원시 요청 및 변환 결과 신원을 정확한 SHA-256 참조로 바꿉니다. | `current change`, focused exporter API 및 CLI 검사 3개 통과 | 네임스페이스가 적용된 seed 기반 집단이 `production_ready=true`를 보고한 뒤에만 변환하고 로컬 원본 아티팩트와 committed safe 기준선을 함께 보존합니다. |
| 2026-08-17 | in-progress | 실행 범위의 영속 outbox 네임스페이스와 새로운 검사점을 사용해 중앙 검증을 통과한 소스 `946a0c8291129e3ea2423ce42c7b49e096eeb239`에서 새로운 엄격한 영문 및 한국어 14-cell 검사를 한 번 수행했습니다. 아티팩트는 live cell 14개와 재개 cell 0개를 보존했습니다. 쿼리 판정 14개가 모두 통과했고, 6개는 근거가 완전한 답변, 6개는 타입이 지정된 미지원 결과, 2개는 타입이 지정된 근거 보류였습니다. 세대 일관성이 통과했고 전송 재시도, 소진된 재시도, 지원되지 않는 운영 주장, 권한 없는 실행, 계획 기능 불일치 및 중복 요청 또는 변환 결과 신원은 모두 0건이었습니다. | [Issue #63](https://github.com/dotnetpower/fdai/issues/63), 실행 `issue63-946a0c8291-20260817T040821Z-strict_14`, 구성 다이제스트 `sha256:d9a3729e5fff1a23378210c7f26b831c6901ac17d670a2276a3c4641b5cea1ee` 및 변경 없는 작업 공간 패치 다이제스트 `sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`를 보존했습니다. Core, Operator 및 Console은 측정 단계 내내 실행됐고 supervisor는 정리 전에 PID, 프로세스 그룹 및 종료 상태를 보존했습니다. | 엄격한 검사를 차단 상태로 유지합니다. 제한된 T1 및 T2 시도 후 계획 6개가 계속 유효하지 않았고, 두 인과 계획은 구성된 authoritative 메트릭 경로에 `network.change` 및 `storage.write.success`의 완전한 샘플이 없어 올바르게 보류했습니다. seed 기반 100-case 검사는 올바르게 시작하지 않았습니다. |
| 2026-08-17 | implemented | 엄격한 실행이 질문 범위의 14개 turn 전에 별도의 페이지 로드 인시던트 자동 조사를 한 건 노출한 뒤 측정 대상 Browser 요청 stream을 격리했습니다. Harness는 이제 빈 incident-attention stream을 제공하고 모든 chat POST를 관찰하며 ambient 및 incident-bound 요청 수를 기록합니다. TypeScript 집단 gate와 변경 불가능한 strict/full 아티팩트 gate는 두 수가 모두 0이어야 통과합니다. | `current change`, focused assurance Vitest 98개 통과, strict/full 아티팩트 gate pytest 2개 통과, Console typecheck 통과 | 중앙 receipt를 확보하고 seed 기반 집단을 시작하기 전에 ambient 및 bound 요청이 0인 새로운 엄격한 아티팩트를 보존합니다. |
| 2026-08-17 | in-progress | 중앙 검증된 source `39e34635ee915dc9301433967a3d8238d294b0f6`에서 엄격한 이중 언어 gate를 한 번 실행했습니다. 아티팩트는 live cell 14개와 resumed cell 0개를 보존했고 모든 query 판정이 통과했으며 transport 재시도, 지원되지 않는 운영 주장, 권한 없는 실행 및 plan-capability 불일치는 모두 0건이었습니다. 두 causal cell 모두 근거가 완전한 답변을 반환해 영어 causal planning 결함을 닫았지만, evidence-validation cell 두 개는 하나의 unsupported 결과와 하나의 clarification으로 끝났습니다. Seed 기반 질문 집합은 시작하지 않았습니다. | [Issue #63](https://github.com/dotnetpower/fdai/issues/63), 실행 `issue63-39e34635ee-20260817T062156Z-strict_14`, 14개 중 12개 cell이 근거가 완전한 답변이었고 엄격한 변경 불가능 gate는 실패했습니다. | 엄격한 gate를 차단 상태로 유지하고 evidence-validation 및 transport 소유권 수정이 중앙 검증된 뒤에만 다시 실행합니다. |
| 2026-08-17 | implemented | 범위가 제한된 high-watermark 읽기에서 이전 엄격한 실행의 전용 요청 및 변환 결과 토픽이 14개 cell 중 9개에서만 전진했고, 빠진 request/projection 쌍 5개가 표준 physical stream에 나타난 뒤 transport 출처 이력을 강화했습니다. 기본 claim 경로의 넓은 prefix가 중첩된 namespaced key와 일치했습니다. 이제 durable exact namespace 동등성이 append, claim, 인증된 읽기 및 변환 결과 소유권을 통제하고, runner는 요청 및 변환 결과 delta가 exact 14/14 및 100/100이어야 통과합니다. | `current change`, focused Operator bridge 및 runner 검사 71개 통과, 작업 범위 Ruff 및 strict mypy 통과. 원시 provider 또는 model content는 보존하지 않았습니다. | 중앙 검증을 확보하고 seed 기반 질문 집합을 시작하기 전에 전용 토픽이 각각 정확히 14만큼 전진한 새로운 엄격한 아티팩트를 하나 보존합니다. |
| 2026-08-17 | implemented | Transport 출처 이력을 runner 제어 흐름에만 두지 않고 통제된 아티팩트 자체에 포함했습니다. 각 단계 뒤 runner는 SHA-256 요청 및 변환 결과 topic identity와 exact 관측 건수를 원본 아티팩트에 원자적으로 연결합니다. Strict 및 full gate는 단계별 14/14 또는 100/100 근거를 요구하고, 리포지토리에 안전한 변환기는 해당 digest와 건수만 보존합니다. Topic 이름과 broker record는 로컬에 유지합니다. | `current change`, focused runner 및 safe-projector 검사 13개와 작업 범위 Ruff 및 strict mypy 통과 | Seed 기반 질문 집합을 시작하기 전에 transport 근거가 결속된 새로운 엄격한 아티팩트를 보존합니다. |
| 2026-08-17 | implemented | 중앙 검증된 소스 `276c8178671468c2f6366a2b9072e45e6dc6fd34`의 새로운 엄격한 시도가 Browser 사전 단계에서 실패한 뒤, 감독 대상 Console마다 Vite 의존성 캐시를 격리했습니다. 동시에 실행된 Vite optimizer가 공유 MSAL 의존성 URL을 무효화했으므로 측정 질문은 실행되지 않았고 아티팩트도 생성되지 않았으며 seed 기반 질문 집합도 시작하지 않았습니다. 일반 Console 시작은 표준 캐시 위치를 유지하고, 보증 runner만 실행 루트 안의 캐시를 지정합니다. | `current change`, focused Console 캐시 검사 2개, supervisor 검사 9개, Console typecheck, 작업 범위 Ruff 및 strict mypy 통과 | 중앙 검증을 확보하고 정확히 검증된 소스에서 새로운 엄격한 질문 집합을 한 번 실행합니다. |
| 2026-08-17 | in-progress | 중앙 검증된 소스 `40fbd0c41eda506e6976e3090fab3bd9502b98f0`에서 새로운 엄격한 질문 집합을 한 번 실행했습니다. Playwright는 live cell 14개와 resumed cell 0개를 완료했지만 전용 요청 및 변환 결과 토픽은 각각 레코드 6개만 보존했습니다. Runner는 승격 전에 exact transport 소유권 조건으로 아티팩트를 거부했고 seed 기반 질문 집합은 시작하지 않았습니다. | [Issue #63](https://github.com/dotnetpower/fdai/issues/63), 실행 `issue63-40fbd0c41e-20260817T084406Z`, 승격할 수 없는 아티팩트가 근거가 완전한 답변 10개, unsupported disposition 3개, held disposition 1개 및 결속된 transport 건수 6/6을 보고함 | 엄격한 gate를 차단 상태로 유지합니다. 수정 전부터 실행 중인 기본 claimant는 물리 prefix가 기본 prefix 아래 중첩됐기 때문에 namespaced key와 계속 일치할 수 있었습니다. |
| 2026-08-17 | implemented | 선택적인 실행 범위 semantic outbox key를 형제 물리 prefix로 옮겼습니다. 운영 기본 prefix는 byte-compatible하게 유지되고 이미 실행 중인 수정 전 기본 claimant도 넓은 legacy prefix로 namespaced key와 일치할 수 없습니다. Exact namespace 동등성은 추가 소유권 검사로 유지합니다. | `current change`, stale prefix 회귀를 포함한 focused Operator bridge 검사 62개, 작업 범위 Ruff 및 strict mypy 통과 | 중앙 검증을 확보하고 정확히 검증된 소스에서 새로운 엄격한 질문 집합을 한 번 실행합니다. |
| 2026-08-17 | in-progress | Exact transport를 적용한 첫 strict-to-seeded 실행을 완료했습니다. Strict는 14/14로 통과했고 seeded는 89/100으로 끝나 답변된 plan-capability 불일치 11건을 드러냈습니다. 이 중 5건은 질문 분류 불일치였고 6건은 관계, 인과, 시간 및 근거 속성 질문의 frame 기능군 오류였습니다. Frame prompt v9은 이 기능군을 구분하고, typed oracle은 나머지 불일치 검사를 약화하지 않으면서 prompt별로 유효한 기능군을 기록합니다. | [Issue #63](https://github.com/dotnetpower/fdai/issues/63), 소스 `8796d21af627b2bdc9e054c94752a67f6cd2499c`, `test_prompt_registry_consistency.py` 5개와 `ontology-query-assurance.test.ts` 99개 통과 | 중앙 검증을 확보한 뒤 strict를 한 번 실행합니다. Strict가 변경 불가능한 gate를 통과할 때만 seeded를 한 번 실행합니다. |
| 2026-08-17 | in-progress | Deterministic evidence-frame 및 topology-cutoff guard를 추가한 뒤 중앙 검증된 source `507bddd55cdc142f70faeafe3c90d9a3b6b157c7`에서 repository supervisor를 한 번 실행했습니다. Core가 외부 `SIGTERM`을 받기 전에 엄격한 검사점은 근거가 완전한 answered cell 3개와 pending cell 11개를 보존했습니다. Core는 상태 0으로 종료했고 supervisor는 `required_child_exited`로 fail closed했습니다. 영어 temporal-comparison, 영어 evidence-validation 및 한국어 temporal-comparison cell은 실행되지 않았으므로 이 실행은 해당 수정에 대한 판정을 제공하지 않습니다. | [Issue #63](https://github.com/dotnetpower/fdai/issues/63), 실행 `issue63-507bddd55c-20260817T115108Z`, exact 중앙 receipt의 dependency sync, fast gate, structural gate 및 changed test 통과 | 엄격한 gate를 차단 상태로 유지합니다. 같은 중단 실행을 반복하거나 seeded를 수동으로 시작하지 않으며, supervisor가 seed 기반 집단을 시작하기 전에 향후 14/14 answered 및 완전 근거 strict 아티팩트를 보존합니다. |
| 2026-08-17 | in-progress | 중앙 검증된 source `1f9542932a469fc16fbaa5cbb0c0bcb788ede071`에서 strict를 한 번 실행했습니다. Live cell 14개가 resumed cell 없이 모두 완료됐고 13개는 근거가 완전한 답변이었으며 두 temporal cell도 답변했습니다. `en-evidence_validation-2`만 범위가 제한된 planning 뒤 unsupported로 끝났습니다. Exact transport 및 safety gate는 통과했지만 변경 불가능 answer gate가 seeded를 차단했습니다. | [Issue #63](https://github.com/dotnetpower/fdai/issues/63), 실행 `issue63-1f9542932a-20260817T123947Z`, strict 프로세스 상태 0 및 supervisor의 소유 child 정리 완료 | Prompt v10을 중앙 검증하고 새로운 strict 아티팩트가 근거가 완전한 답변 14/14를 보존할 때까지 seeded를 차단합니다. |
| 2026-08-17 | in-progress | 중앙 검증된 source `723ed3f280ac0c94a8f23ce6d2d7d37057dbeb28`에서 strict를 한 번 실행했습니다. Live cell 14개가 resumed cell 없이 모두 완료됐고 evidence validation은 두 언어에서 답변했으며 13개 cell이 근거가 완전한 답변이었습니다. `en-temporal_comparison-1`만 범위가 제한된 두 plan tier가 deterministic 검증에 실패한 뒤 unsupported로 끝났습니다. Seeded는 계속 차단됐습니다. | [Issue #63](https://github.com/dotnetpower/fdai/issues/63), 실행 `issue63-723ed3f280-20260817T130507Z`, exact transport 및 safety gate를 유지한 strict 프로세스 상태 0 | Prompt v11을 중앙 검증한 뒤 seeded 시작 전에 새로운 strict 14/14 아티팩트를 보존합니다. |
| 2026-08-17 | in-progress | 중앙 검증된 source `8d7a489fba0fffba05b0a5f64f791ebefe9c8035`에서 strict를 한 번 실행했습니다. Live cell 14개가 resumed cell 없이 모두 완료됐고 두 temporal cell이 답변했으며 13개 cell이 근거가 완전한 답변이었습니다. `en-evidence_validation-2`만 subject clarification을 요청했습니다. Seeded는 변경 불가능 answer gate로 계속 차단됐습니다. | [Issue #63](https://github.com/dotnetpower/fdai/issues/63), 실행 `issue63-8d7a489fba-20260817T132141Z`, exact transport, safety 및 capability-match counter 유지 | Principal-scope clarification resolver를 중앙 검증한 뒤 seeded 시작 전에 새로운 strict 14/14 아티팩트를 보존합니다. |
| 2026-08-17 | in-progress | 중앙 검증된 source `4ef64c64ac4aff4091de3728aa2e5284ffac7da9`에서 strict를 한 번 실행했습니다. Live cell 14개가 resumed cell 없이 모두 완료됐고 exact transport 및 safety counter를 유지했으며 12개 cell이 근거가 완전한 답변이었습니다. `en-causal_analysis-1`은 plan 선택 전에 unsupported로 끝났고 `en-evidence_validation-2`는 resource-identity clarification을 요청해 변경 불가능 gate가 seeded를 차단했습니다. | [Issue #63](https://github.com/dotnetpower/fdai/issues/63), 실행 `issue63-4ef64c64ac-20260817T134627Z`, strict 프로세스 상태 0 및 partial artifact 승격 없음 | Causal frame 및 evidence-identity guard를 중앙 검증한 뒤 seeded 시작 전에 새로운 strict 14/14 아티팩트를 보존합니다. |
| 2026-08-18 | in-progress | 중앙 검증된 source `69d9ec870f27d6569897ac9d023d3e38b61e4ebc`에서 strict를 한 번 실행했습니다. Live cell 14개가 resumed cell 없이 모두 완료됐고 transport retry, 지원되지 않는 운영 주장, 권한 없는 실행, ambient request 및 bound request는 모두 0건이었습니다. Causal 및 temporal cell은 답변했지만 `en-evidence_validation-2`는 unsupported 상태였고 `en-aggregation-3`은 필요한 aggregate capability 없이 `query.manifest`를 통해 답변했습니다. 아티팩트는 답변 13개, 완전 근거 답변 12개 및 plan-capability 불일치 1건을 보존해 seeded가 시작되지 않았습니다. | [Issue #63](https://github.com/dotnetpower/fdai/issues/63), 실행 `issue63-69d9ec870f-20260817T142522Z`, partial artifact 승격 없음 | Frame prompt v11을 중앙 검증한 뒤 seeded 시작 전에 새로운 strict 14/14 아티팩트를 보존합니다. |
| 2026-08-18 | in-progress | 중앙 검증된 source `57fb6dd9c747e8dbc39ecf671a0d96dd02a095d6`에서 strict를 한 번 실행했습니다. Live cell 14개가 plan-capability 불일치, transport retry, 지원되지 않는 운영 주장, 권한 없는 실행, ambient request 또는 bound request 없이 typed oracle을 통과했습니다. 13개 cell은 근거가 완전한 답변이었고 `ko-causal_analysis-1`만 T1 candidate가 principal-scope restriction을 추가한 뒤 unsupported로 끝났습니다. Seeded는 시작되지 않았습니다. | [Issue #63](https://github.com/dotnetpower/fdai/issues/63), 실행 `issue63-57fb6dd9c7-20260817T224706Z`, partial artifact 승격 없음 | Causal plan prompt v12를 중앙 검증한 뒤 seeded 시작 전에 새로운 strict 14/14 아티팩트를 보존합니다. |
| 2026-08-18 | in-progress | 중앙 검증된 source `8f77424e21fde7eb82ef0103d90d7d09d6507a8d`에서 repository strict-to-seeded 절차를 한 번 실행했습니다. Strict는 live, answered 및 complete-evidence cell 14/14와 exact transport 14/14를 보존하고 safety 또는 capability mismatch가 0건이어서 runner가 seeded를 자동 시작했습니다. Seeded는 retry 또는 safety violation 없이 live turn 100개를 완료하고 typed judgment 99개를 통과했습니다. `en-property_filter-4`만 필요한 filtered capability 대신 unfiltered evidence-validation ObjectSet으로 답변했습니다. Frozen universe는 의도적으로 action draft 9개, clarification 10개 및 unsupported-domain terminal 5개를 유지하므로 실패한 이 아티팩트에서 answer-required turn 76개가 답변됐고 75개가 완전 근거를 포함했습니다. | [Issue #63](https://github.com/dotnetpower/fdai/issues/63), 실행 `issue63-8f77424e21-20260817T230217Z`, failed artifact 또는 baseline 승격 없음 | Frame prompt v12를 중앙 검증한 뒤 strict를 다시 실행하고 strict가 다시 통과한 경우에만 seeded를 허용합니다. |
| 2026-08-18 | in-progress | 중앙 검증된 source `a6bb8f1781283c4cbe62533f3eb5e991d8d203bf`에서 strict를 한 번 실행했습니다. 13개 cell은 capability mismatch 또는 safety violation 없이 근거가 완전한 답변이었습니다. `en-evidence_validation-2`만 evidence-claim subject가 runtime property-filter scope denial로 넘어가 plan 근거를 보존하기 전에 unsupported로 끝났습니다. Seeded는 시작되지 않았습니다. | [Issue #63](https://github.com/dotnetpower/fdai/issues/63), 실행 `issue63-a6bb8f1781-20260817T234111Z`, partial artifact 승격 없음 | Frame prompt v13을 중앙 검증한 뒤 seeded 시작 전에 strict 14/14를 보존합니다. |
| 2026-08-18 | in-progress | 중앙 검증된 source `016fe089b5a12935162cca1dc6b61d56417ed63b`에서 strict를 한 번 실행했습니다. 13개 cell은 capability mismatch 또는 safety violation 없이 근거가 완전한 답변이었습니다. `en-property_filter-5`만 ObjectSet predicate가 descriptor property key에서 읽을 수 없는 alias 또는 projected path로 넘어간 뒤 unsupported로 끝났습니다. Seeded는 시작되지 않았습니다. | [Issue #63](https://github.com/dotnetpower/fdai/issues/63), 실행 `issue63-016fe089b5-20260817T235737Z`, partial artifact 승격 없음 | Plan prompt v13을 중앙 검증한 뒤 seeded 시작 전에 strict 14/14를 보존합니다. |
| 2026-08-18 | in-progress | 중앙 검증된 source `6ce74140e04c85adb677ff83d3954c7138ccd36e`에서 repository strict-to-seeded 절차를 한 번 실행했습니다. Strict는 exact transport와 safety 또는 capability mismatch 0건을 유지하며 complete-evidence answer 14/14를 다시 보존했습니다. Seeded는 retry 또는 safety violation 없이 live turn 100개를 완료하고 typed judgment 98개를 통과했습니다. `ko-temporal_comparison-3`은 retained-generation delta를 current filtered ObjectSet으로 축소했고 `en-property_filter-4`는 current evidence-state membership을 unfiltered evidence validation으로 확대했습니다. Frozen safety operation은 예상한 non-answer terminal을 유지했으며 failed artifact 또는 baseline은 승격하지 않았습니다. | [Issue #63](https://github.com/dotnetpower/fdai/issues/63), 실행 `issue63-6ce74140e0-20260818T000831Z` | Frame prompt v14를 중앙 검증한 뒤 strict를 다시 실행하고 strict가 통과한 경우에만 seeded를 허용합니다. |
| 2026-08-18 | in-progress | 중앙 검증된 source `5715b1c734f209b019d3dc5f146088526d02c3fc`에서 repository strict-to-seeded 절차를 한 번 실행했습니다. Strict는 exact transport와 safety 또는 capability mismatch 0건을 유지하며 complete-evidence answer 14/14를 보존했습니다. Seeded는 safety 또는 unauthorized execution failure 없이 live turn 100개를 완료하고 typed judgment 98개를 통과했습니다. v14 membership case는 통과했지만 `en-inventory_listing-3`은 현재 runtime resource class에 schema manifest를 선택했고 `en-aggregation-2`는 요청된 grouping measure를 버리고 plain ObjectSet을 반환했습니다. Failed artifact 또는 baseline은 승격하지 않았습니다. | [Issue #63](https://github.com/dotnetpower/fdai/issues/63), 실행 `issue63-5715b1c734-20260818T004444Z` | Deterministic frame invariant와 prompt v15를 중앙 검증한 뒤 strict를 다시 실행하고 strict가 통과한 경우에만 seeded를 허용합니다. |
| 2026-08-18 | in-progress | 중앙 changed-tests가 source `90c592bfcc673e4764e4480be7ffa54c5b66b0b8`의 제안된 frame invariant 때문에 기존 Pod telemetry composition case 두 개가 깨져 assurance 전에 거부했습니다. 유효하지 않은 invariant는 제거했으며 해당 source에서 assurance artifact 또는 baseline은 생성하지 않았습니다. | [Issue #63](https://github.com/dotnetpower/fdai/issues/63), implementation ledger에 중앙 검증 실패 보존 | 수정된 prompt-only v15 source를 중앙 검증한 뒤 strict를 다시 실행하고 strict가 통과한 경우에만 seeded를 허용합니다. |
| 2026-08-18 | in-progress | 중앙 검증된 수정 source `13dd21277664d18b6c0f5603f10d05a5f4c3d7ec`에서 repository strict-to-seeded 절차를 한 번 실행했습니다. Strict는 exact transport와 safety 또는 capability mismatch 0건을 유지하며 complete-evidence answer 14/14를 보존했습니다. Seeded는 safety 또는 unauthorized execution failure 없이 live turn 100개를 완료하고 typed judgment 99개를 통과했으며 이전 v14 및 v15 mismatch는 모두 통과했습니다. `en-causal_analysis-4`만 일반 명사인 "incident"를 bound incident reference로 처리하고 causal evidence 대신 `query.incident_evidence`를 선택했습니다. Failed artifact 또는 baseline은 승격하지 않았습니다. | [Issue #63](https://github.com/dotnetpower/fdai/issues/63), 실행 `issue63-13dd212776-20260818T013148Z` | Frame prompt v16을 중앙 검증한 뒤 strict를 다시 실행하고 strict가 통과한 경우에만 seeded를 허용합니다. |
| 2026-08-18 | in-progress | 중앙 검증된 frame-v16 source `817b3faf19cdb414188f0f661c9432efc6a29294`에서 strict를 한 번 실행했습니다. 14개 cell 모두 exact 14-request transport와 capability mismatch 0건을 유지한 safe typed judgment였지만 `en-causal_analysis-1`은 planning tier 두 개가 모두 유효하지 않은 causal DAG를 생성한 뒤 unsupported로 끝났습니다. Immutable answered 14/14 gate가 실패해 seeded는 시작하지 않았고 artifact는 승격하지 않았습니다. | [Issue #63](https://github.com/dotnetpower/fdai/issues/63), 실행 `issue63-817b3faf19-20260818T020756Z` | Plan prompt v14를 중앙 검증한 뒤 strict를 다시 실행하고 strict가 통과한 경우에만 seeded를 허용합니다. |
| 2026-08-18 | in-progress | 중앙 검증된 frame-v16 및 plan-v14 source `83639e704814e405d94ca175e2d57f69a93fa99c`에서 repository strict-to-seeded 절차를 한 번 실행했습니다. Strict는 exact transport와 safety 또는 capability mismatch 0건을 유지하며 complete-evidence answer 14/14를 보존했습니다. Seeded는 safety 또는 unauthorized execution failure 없이 live turn 100개를 완료하고 typed judgment 98개를 통과했습니다. `ko-causal_analysis-3`은 causal precedence를 topology comparison으로 축소했고 `ko-property_filter-3`은 current-generation ontology declaration을 runtime object로 처리했습니다. Failed artifact 또는 baseline은 승격하지 않았습니다. | [Issue #63](https://github.com/dotnetpower/fdai/issues/63), 실행 `issue63-83639e7048-20260818T021732Z` | Frame prompt v17을 중앙 검증한 뒤 strict를 다시 실행하고 strict가 통과한 경우에만 seeded를 허용합니다. |
| 2026-08-18 | in-progress | 중앙 검증된 source `80962e748948684248cd04683e527db0fedaa985`의 frame-v17 실행 두 개는 저장된 Browser Entra token request timeout으로 Console access에 실패해 질문 0개와 semantic artifact 없음으로 끝났습니다. 인증 값을 노출하지 않고 loopback capture 계약을 통해 owner-only storage state를 갱신했습니다. 인증된 strict 재실행은 14개 cell을 모두 완료했지만 `ko-relationship_traversal-4`가 current inventory containment에 schema relationship을 선택해 capability judgment 한 개가 실패했습니다. Seeded는 시작하지 않았고 artifact는 승격하지 않았습니다. | [Issue #63](https://github.com/dotnetpower/fdai/issues/63), 인증된 실행 `issue63-80962e7489-20260818T025610Z` | Frame prompt v18을 중앙 검증한 뒤 strict를 다시 실행하고 strict가 통과한 경우에만 seeded를 허용합니다. |
| 2026-08-18 | in-progress | 중앙 검증된 frame-v18 source `ffced363b1deb3fdd5bda7a535ac205bf543a751`에서 strict를 한 번 실행했습니다. 14개 cell 모두 exact transport와 capability mismatch 0건을 유지한 safe typed judgment였지만 `en-causal_analysis-1`은 완전한 visible-resource causal scope를 사용하지 않고 clarification을 요청했습니다. Immutable answered 14/14 gate가 실패해 seeded는 시작하지 않았고 artifact는 승격하지 않았습니다. | [Issue #63](https://github.com/dotnetpower/fdai/issues/63), 실행 `issue63-ffced363b1-20260818T030548Z` | Frame prompt v19를 중앙 검증한 뒤 strict를 다시 실행하고 strict가 통과한 경우에만 seeded를 허용합니다. |
| 2026-08-18 | in-progress | 중앙 검증된 frame-v19 source `49e0e54635a30bf05f7d1a119df3d6e7216a8277`에서 repository strict-to-seeded 절차를 한 번 실행했습니다. Strict는 exact transport와 safety 또는 capability mismatch 0건을 유지하며 complete-evidence answer 14/14를 보존했습니다. Seeded는 safety 또는 unauthorized execution failure 없이 live turn 100개를 완료하고 typed judgment 99개를 통과했습니다. `ko-relationship_traversal-5`만 다른 ontology object로 routing되는 runtime resource에 declaration manifest를 선택했습니다. Failed artifact 또는 baseline은 승격하지 않았습니다. | [Issue #63](https://github.com/dotnetpower/fdai/issues/63), 실행 `issue63-49e0e54635-20260818T031435Z` | Frame prompt v20을 중앙 검증한 뒤 strict를 다시 실행하고 strict가 통과한 경우에만 seeded를 허용합니다. |
| 2026-08-18 | validated | 중앙 검증된 frame-v20 source `a38922762ed805794b11bb9c6aaef43916f6f6c4`에서 통제된 strict-to-seeded 절차를 완료했습니다. Strict는 complete evidence와 exact transport를 유지하며 14/14를 통과했습니다. Seeded는 evidence-complete answer 85개, action draft 9개, clarification 6개, exact request 및 projection transport 100/100, capability mismatch 0건, unsupported operational claim 0건, unauthorized execution 0건 및 `production_ready=true`를 유지하며 live typed judgment 100개를 모두 통과했습니다. 통과한 raw artifact를 repository-safe 2026-08-18 기준선으로 변환했습니다. | [Issue #63](https://github.com/dotnetpower/fdai/issues/63), 실행 `issue63-a38922762e-20260818T034940Z`, 위에 연결된 committed 통제 기준선 | 무작위 보증 릴리스 blocker가 남아 있지 않습니다. 원시 local artifact를 보존하고 최신 integration source에서 baseline commit을 검증합니다. |
| 2026-08-20 | validated | 릴리스 oracle을 strict v2로 확장하고 aggregate/listing 하드닝이 적용된 정확한 소스를 인증했습니다. Strict v2는 완전한 근거 답변 16/16과 정확한 전송으로 형식화된 판단 22/22를 통과했습니다. Seeded는 완전한 근거 답변 73/73, 정확한 전송, 재시도 및 기능 불일치 0건, 모든 safety counter 0건, `production_ready=true`로 live typed judgment 100/100을 통과했습니다. | [Issue #233](https://github.com/dotnetpower/fdai/issues/233), 실행 `question-space-final-4dc5365aa-20260820-r15`, 위에 연결된 repository-safe 2026-08-20 기준선 | 이 소스에는 무작위 보증 릴리스 blocker가 남아 있지 않습니다. 이후 소스 리비전은 새로운 정확한 소스 인증이 필요합니다. |

### 남은 작업

- [x] 필수 작업 및 언어 조합의 모든 cell이 완전하게 검증된 근거가 있는 답변을 포함하는
  통과한 엄격한 영문 및 한국어 14-cell 아티팩트 하나를 보존한 뒤 100-case 실행을 시작합니다.
- [x] 소스 리비전, 구성 다이제스트, 인증된 실행 증명, 정확한 요청 및 응답 증적 참조를
  측정한 모든 턴에 연결하는 통제된 무작위 실행 아티팩트를 보존합니다.
- [x] 각 작업 집합을 authoritative 프로바이더에 대해 실행하고 exact 온톨로지 release, principal manifest, 검증된 계획, 근거 참조 또는 타입이 지정된 unavailable 처리 결과로 입증합니다.
- [x] 인증된 운영 composition을 통해 bilingual 100개 질문 절차를 재생성하고 기계 판독 결과를 보존합니다.
- [x] 재생성한 아티팩트가 지원되지 않는 운영 주장 0건과 권한 없는 실행 0건을 유지하며 다음 실행 종료 조건을 모두 충족한 뒤에만 릴리스 결정을 변경합니다.

## 완료 하드닝 비평

현재 완료 범위는 exact Issue #63 runner, 의미 계획, Operator outbox, artifact gate 및 이중
언어 소유 문서 경로를 대상으로 독립적인 읽기 전용 비평 12라운드를 수행했습니다. 소유 경로에서
재현된 finding만 수락했습니다.

| 라운드 | 관점 | 심각도 | 근거 및 처리 결과 |
|--------|------|--------|-------------------|
| 1 | 출처 이력 및 source 결속 | 없음 | Exact source 검증, 분리된 worktree 결속 및 source를 포함한 원자적 status를 유지합니다. |
| 2 | Child lifecycle | 없음 | 필수 child 종료와 소유 process-group 정리는 범위가 제한되고 fail closed 됩니다. |
| 3 | Outbox 격리 | Medium, 수정됨 | 기본 prefix claim이 중첩된 namespaced 행과 겹쳤습니다. 이제 exact durable namespace 동등성이 append, claim, 인증된 읽기 및 변환 결과 소유권을 통제합니다. |
| 4 | Checkpoint 및 status 원자성 | 없음 | 동일 디렉터리 임시 쓰기, `fsync`, 교체, mode `0600` 및 fresh checkpoint guard를 유지합니다. |
| 5 | 변경 불가능 gate | Medium, 수정됨 | 이전 topic 전진 조건은 양수 delta만 요구했습니다. 이제 gate는 exact 14/14 및 100/100 request/projection 건수와 자체 포함 artifact 근거를 요구합니다. |
| 6 | Provider 완전성 | Low | 권위 있는 provider 근거가 없으면 타입이 지정된 incomplete 또는 unavailable 결과를 유지합니다. 이는 숨겨진 성공이 아니라 명시적인 열린 기능입니다. |
| 7 | Plan 검증 | Medium, 수정됨 | Causal 전이 의존성 정규화와 서버 소유 evidence-validation plan은 exact release, 매니페스트, 역할, 목적, 스키마, digest 및 handler 검사를 그대로 통과합니다. |
| 8 | 비밀 노출 | 없음 | Status 및 변환된 기준선 근거는 topic 이름, 원시 provider payload, model response, credential 또는 환경 값을 보존하지 않습니다. |
| 9 | 동시성 | 없음 | `FOR UPDATE SKIP LOCKED`, claim identity, exact namespace 동등성 및 process-group 소유권이 실행 간 claim과 중복 작업을 막습니다. |
| 10 | Replay 및 cleanup | 없음 | Principal/request replay 순서, fresh checkpoint 거부, 원자적 artifact 및 supervisor cleanup은 결정론적입니다. |
| 11 | 문서 및 Issue 진실성 | 없음 | 원장은 실패한 엄격한 결과, 차단된 release 상태 및 seed 기반 실행 미수행을 유지하고 부분 근거를 승격하지 않습니다. |
| 12 | Remote 통합 | Low | 로컬 원본 아티팩트는 broker 서명 attestation이 아니라 통제된 운영자 근거 경계입니다. Hash 및 count 결속은 불완전한 부분 승격을 막고 외부 서명 권한은 이 로컬 campaign 범위 밖에 유지합니다. |

첫 번째 광범위 비평 pass는 별도 `core/conversation_assurance` 하위 시스템을 검사했으므로
거부했습니다. 이후 exact-scope pass를 두 번 수행했습니다. 수락한 Medium finding 3개를 각각
focused validation과 별도 commit으로 수정한 뒤 마지막 12라운드 pass에서 재현 가능한 Medium 이상
finding은 0개였습니다. Residual finding은 위의 Low 2개입니다.

## 관련 문서

| 알아볼 내용 | 문서 |
|-------------|------|
| 구조적 쿼리 범위 및 작업 패키지 | [온톨로지 쿼리 범위 구현 계획](ontology-query-coverage-implementation-plan-ko.md) |
| 전체 턴 의미 계획 | [계층적 대화 계획](hierarchical-conversation-planning-ko.md) |
| Operator 및 Core 런타임 분리 | [Operator Console 런타임 모델](operator-console-runtime-model-ko.md) |
| 대화 품질 거버넌스 | [대화 보증](../decisioning/conversation-assurance-ko.md) |
