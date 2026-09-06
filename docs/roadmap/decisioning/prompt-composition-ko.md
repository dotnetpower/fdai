---
title: 진화하는 시스템 프롬프트
translation_of: prompt-composition.md
translation_source_sha: c29321e2e0d5c4b0eb575dcb974bc7c5794ee740
translation_revised: 2026-09-06
---

# 진화하는 시스템 프롬프트

T2 계층과 quality 게이트는 하드코딩된 단일 문자열이 아니라 **조립 가능한
catalog-as-code 프롬프트**를 소비합니다. 이 문서는 설계의 원본입니다. 레이어가 어떻게
조립되고, 각 아티팩트가 어디에 살며, 조립 루트가 어떤 경계를 배선하고, 모델이
우리가 보낸 것을 실제로 읽었는지 어떻게 측정하는지를 다룹니다.
[llm-strategy-ko.md](../architecture/llm-strategy-ko.md#t2---reasoning-tier-quality-gate-required)의
LLM 계약과
[architecture.instructions.md](../../../.github/instructions/architecture.instructions.md)의
trust 라우팅을 확장합니다.

> **범위.** 업스트림은 범용 · Azure-first입니다. 웹 검색은 검토된 Azure Responses
> 어댑터를 통해 배포별로 명시적 선택합니다. 고객별 오버라이드는 포크 전용이며 코어는
> 기본 비활성 가짜를 배포합니다
> ([generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md)).
>
## 적응형 대화 조립

적응형 대화는 카탈로그가 소유한 `adaptive-common` 기본 지침 하나와 계획, 답변, 검토, 보강,
재검증 팩 중 정확히 하나를 사용합니다. 각 턴은 고정된 Pantheon 역할 하나와 언어를 추가하며,
사용자와 도구 문장은 신뢰하지 않는 데이터 묶음에 유지합니다. 서버는 명시적으로 선택한 에이전트와
선택적 담당 관계를 별도로 확인합니다. Operator는 현재 소유권과 디렉터리 근거를 검증하고 만료형
증명을 사용자와 대상에 결속하며, Core는 역할 기반 대화 전에 이를 다시 확인합니다.
신원 식별자와 원본 리비전 문자열은 시스템 지침에 넣지 않습니다. 관계가 불명확하거나 만료되어도
선택한 역할은 유지하되 검증된 관계로 표현하지 않습니다.

배포 조립은 모델이나 엔드포인트를 하드코딩하지 않고 결정된 모델 슬롯을 사용합니다. 작성기와
검토기를 위한 `conversation.adaptive.*` 키 5개는 프롬프트 전용입니다. 계획과 답변은 선택된 T1
서술 모델, 검토와 재검증은 사용 가능한 독립 T1 서술 모델, 선택적 보강만 `t2.reasoner.primary`를 사용하며 모델 배포를
만들지 않습니다. 역할과 수명 주기 타입은 에이전트와 모델의 공개 인터페이스를 사용합니다. 작성기와
검토기는 독립적으로 구성된 모델이어야 하며 선택적 보강 한 번도 독립 검토를 다시 거칩니다.
no-T2 요청 프로필은 기존 비적응형 경로를 유지합니다. 모든 단계는 동일한 실행 권한 없음 경계를
보존합니다. 스키마, 바이트, 시간, 호출, 토큰 예산을 적용하며 선택적 조회는 유용한 답변과 검토에
필요한 시간과 호출 2회를 남겨 둡니다. 내부 조회 모델 요청도 같은 사용량 제한과 취소 범위를
따릅니다. 역할 프로필과 모델 추적은 운영 근거와 분리하며 전체 답변의 검증 배지를 만들 수 없습니다.

비평과 수정: T2 보조 모델을 필수 조건으로 두면 단일 공급자를 사용하는 로컬 환경에서 일반 설명이
꺼지고 지식 질문이 운영 조회 계획으로 넘어갑니다. 따라서 T2 연결이 없어도 T1 작성과 독립된 T1
검토를 사용할 수 있게 합니다. 공급자와 모델 계열은 정확한 배포 메타데이터에서만 확인하며
이름으로 추정하지 않습니다. 보류되었거나 출처를 알 수 없는 후보는 제외하고 독립적인 보강 모델이
없으면 보강만 비활성화합니다. 구성된 경우 공급자의 구조화 출력을 사용하고 그렇지 않으면 정확한
스키마를 요청에 첨부한 뒤 반환된 JSON을 애플리케이션에서 검증합니다. 근거 검증과 별도의 운영
T2 다중 공급자 품질 검사는 완화하지 않습니다.

[Core mini 지연 시간 라우터](../interfaces/narrator-routing-and-latency-ko.md#core-소유-mini-후보-선택)는
지연 실행 단계를 포함해 턴마다 작성/검토 모델 쌍을 한 번만 고정합니다. 명시적으로 활성화한 탐색에는
합성 `OK` 요청만 넣고, 이 프롬프트 팩이나 운영자 내용은 넣지 않습니다. 라우팅은 선택적 T2 보강이나
판정자/비평자 연결을 바꾸지 않습니다. 구현 및 검증 상태는 해당 라우팅 문서에서 관리합니다.

### 지연 시간 한도

지연 개선에서도 독립 검토와 실행 권한 없음 경계를 유지합니다. 검증을 없애면 빠르지만 신뢰할 수
없는 응답이 되므로 중복 모델 작업, 스키마 준비, 무관한 맥락, 불필요한 보강 및 검증 후 표시 대기를
줄입니다. v2 계획 팩은 완전한 지식 전용 계획에만 초안을 포함해 일반 모델 호출을 3회에서 2회로
줄입니다. 운영 설명은 여전히 운영 조회 뒤에 작성합니다.
독립적으로 지지된 부분만 표시하며 선택적 보강은 독립 재검증에 필요한 시간과 호출 수를 남깁니다.
짧은 검토 단계는 GPT-5 mini 및 GPT-5.4 mini의 검토와 재검증에 `low` 추론 설정을 사용합니다.
작성 단계, 다른 모델 계열 및 T2 추론 설정은 유지합니다.

본문 없는 단계 로그에는 경과 시간, 남은 시간, 상태 및 예약한 호출 시도 수를 기록합니다.
시도나 예약만으로 공급자가 실제 요청을 수락했다고 볼 수는 없습니다. 스키마 캐시는
사용자 입력을 보관하지 않습니다. 준비된 검증기 캐시도 크기를 제한하고 모든 응답은 원본과 구성된
공급자 스키마로 다시 검증합니다. 기존 자격 증명 캐시를 재사용합니다. 오프라인 호출 수와 시계
테스트는 처리 방식의 변화를 입증할 뿐 실제 모델 품질이나 운영 속도 개선율을 입증하지 않습니다.
새로운 실제 비교 호출에는 명시적 승인이 필요합니다.

### 지연 개선 10라운드 (2026-09-06)

| 라운드 | 변경 | 집중 검증 근거 |
|--------|------|----------------|
| 1 | 본문 없는 단계 시간 계측 | `859618b68`; 경과 시간과 남은 시간 검증 |
| 2 | 불변 Pydantic 스키마 재사용 | `e0c590c85`; 턴마다 세 번 생성하던 스키마를 캐시에서 재사용 |
| 3 | 크기가 제한된 어댑터 검증기 재사용 | `00f9db010`; 이후 잘못된 응답도 검증에서 차단 |
| 4 | 경량 검토의 낮은 추론 강도 | `18b8a0e97`; 지원되는 검토와 재검증 요청만 변경 |
| 5 | 지식 전용 계획과 초안 통합 | `145d472ac`; 독립 검토를 유지하며 호출 3회를 2회로 축소 |
| 6 | 맥락 독립적 검토 입력 | `ad3afa42f`; 무관한 이력은 제외하고 이전 대화에 의존하면 보존 |
| 7 | 보강 전에 재검증 한도 확보 | `fdc221366`; 지지된 설명을 버리지 않고 끝낼 수 없는 보강을 생략 |
| 8 | 필수 근거 누락 시 설명 재시도 방지 | `ad83b6bdd`; 필수 목표는 보류하고 답변 품질은 제한 상태로 유지 |
| 9 | 검증된 자문 응답 즉시 표시 | `5a3901de7`; 인위적인 표시 프레임 최대 60회 제거 |
| 10 | 최종 결과 저장 후 스트림 깨우기 | `0d3eeb66a`; 크기 제한과 경합 보호를 적용해 1초 재조회 대기 제거 |

최종 집중 검증에서 Python 342개, Console 76개, 양 언어 브라우저 시나리오 12개, strict mypy 및
Console 프로덕션 빌드가 통과했습니다. 공급자 시간을 고정한 오프라인 전후 비교에서 답변 해시,
품질 및 목표 상태가 같았습니다. 지식 응답은 3 -> 2회, 늦은 보강과 근거 누락은 5 -> 3회로
줄었습니다. 늦은 보강 시뮬레이션은 55 -> 35초였습니다. 이는 처리 방식의 측정이며 실제 속도
개선율 주장이 아닙니다. 실제 공급자 기준선은 이전 두 턴의 51.431초와 53.841초뿐이며 새 실제
호출은 수행하지 않았습니다.

## 구현 상태

### 구현 범위

| 영역 | 상태 | 근거 | 참고 |
|------|------|------|------|
| 10라운드 지연 최적화 | implemented | [라운드 근거](#지연-개선-10라운드-2026-09-06) | 검토를 우회하지 않고 불필요한 작업을 줄였습니다. 실제 공급자 지연과 품질 비교는 승인된 측정이 필요합니다. |
| 적응형 역할 및 담당 관계 프롬프트 조립 | implemented | `adaptive_prompt.py`, `wire_adaptive_conversation.py`, `adaptive_relationship.py`, 조립 검사 20개와 연결된 역할 및 증명 검사 통과 | 공통 단계 정책, 고정된 선택 역할 및 권한 없는 현재 담당 관계를 사용합니다. 최종 오프라인 검증과 집중 비평 11회의 근거는 계층형 대화 계획에 기록했습니다. |
| 카탈로그 레지스트리, 작성기, 도구 및 런타임 스킬 | implemented | [`test_composer.py`](../../../services/core-control-plane/tests/core/prompts/test_composer.py) | 카탈로그 로드, 결정론적 레이어 조립, 도구 매니페스트, 스킬, canary 및 시작 대체 경로에 집중 테스트가 있습니다. |
| 경로별 대화 prompt | implemented | `conversation-preflight.v1.yaml`, `semantic-judgment.v5.yaml`, 집중 composer 및 Azure adapter 검사 | 시작 시 compact T1 preflight와 전체 운영 의미 판단을 별도로 조립합니다. 조건에 맞는 순수 social 턴은 compact prompt와 schema만 사용합니다. 혼합, 맥락 의존, 모호함 및 운영 턴은 기능을 인식하는 전체 prompt로 계속 진행됩니다. |
| 승인된 외부 skill-source fetch | implemented | [`skill_source.py`](../../../services/core-control-plane/src/fdai/delivery/github/skill_source.py); [`test_skill_source.py`](../../../services/core-control-plane/tests/delivery/github/test_skill_source.py) | GitHub delivery 어댑터는 불변 commit을 해석하고 범위가 제한된 exact 파일만 반환합니다. Fetch는 prompt eligibility를 부여하지 않으며 격리, publisher 검증, 승인, disabled-first installation이 계속 권위 있는 경계입니다. |
| 운영자 기억, 토론 및 QualityGate 통합 | implemented | [`test_prompt_deliberation.py`](../../../services/core-control-plane/tests/agents/test_prompt_deliberation.py), [`test_gate.py`](../../../services/core-control-plane/tests/core/quality_gate/test_gate.py) | 제한된 기억과 1회 비평자/Judge 토론은 권한을 부여하지 않고 결정론적 검증기에 근거를 제공합니다. |
| 답변 연속성과 프롬프트 ablation | implemented | `services/core-control-plane/src/fdai/core/prompts/`, `services/core-control-plane/src/fdai_core_service/semantic_turn_processor.py`, `services/operator-service/src/fdai_operator_service/postgres_iam.py`, 집중 Python 검사 312개 및 콘솔 검사 6개 | 감사되는 런타임 토글, 보호된 프롬프트 레이어 ablation, 재실행 근거, 유용한 안전 보류 렌더링 및 리비전으로 보호된 Operator 지속성이 구현되었습니다. 런타임 검증 전까지 통제된 shadow 근거 보존은 열려 있습니다. |
| 검토된 웹 검색 및 코어 T2 프롬프트 통합 | in-progress | [`test_web_search.py`](../../../services/core-control-plane/tests/core/web_search/test_web_search.py), [Wave 5 alpha](#wave-5-alpha---무엇이-배포되었나) | 안전한 프로바이더 경계와 검토된 어댑터가 있지만 스니펫은 코어 T2 도구 매니페스트에 연결되지 않았습니다. |
| 포크 우선 두 번째 승인 채널 | in-progress | [`hil_pipeline.py`](../../../services/core-control-plane/src/fdai/core/operator_memory/hil_pipeline.py), [`test_hil_pipeline.py`](../../../services/core-control-plane/tests/core/operator_memory/test_hil_pipeline.py) | 업스트림 도메인 단계가 서로 다른 principal, 자기 승인 방지, 범위가 제한된 승인 창, 재실행을 입증합니다. 재전달된 승인은 두 번째 항목을 만드는 대신 `already_materialized` 로 거부하며, 증명할 수 없거나 만료된 창은 절대 구체화되지 않습니다. 그것을 호출하는 채널은 포크 우선으로 남아 미구현이므로 파이프라인 구획은 비활성 상태입니다. |

### 구현 이력

| 날짜 | 상태 | 변경 | 근거 | 남은 작업 |
|------|------|------|------|-----------|
| 2026-09-06 | implemented | 적응형 계획, 스키마 준비, 검토 한도, 표시 및 최종 결과 전달에 걸쳐 지연 개선 10라운드를 완료했습니다. | 위의 라운드 커밋과 통합 검증. 공급자 시간을 고정한 비교에서 답변과 품질 결과를 그대로 유지했습니다. | 종단 간 속도 개선을 주장하려면 승인된 실제 공급자 전후 비교가 필요합니다. |
| 2026-09-06 | implemented | 일반 적응형 조립에서 T2 검토자를 필수 조건으로 두지 않도록 수정했습니다. 독립적으로 구성된 T1 서술 모델이 작성과 검토를 맡고 선택적 T2 기본 모델만 보강합니다. 잘못되었거나 사용할 수 없는 보강 연결은 T1을 비활성화하지 않습니다. 공급자 스키마 지원이 구성되지 않았으면 애플리케이션에서 JSON을 검증합니다. | `current change`; 조립, 전송, 스키마, 예산, 런타임 및 프롬프트 레지스트리 집중 검사 115개 통과. 수정한 원본 모듈 두 개의 strict mypy 통과. 비교 회귀 검사는 모의 모델을 사용하되 실제 조립과 전송을 거치며 운영 조회를 하지 않습니다. | 실제 답변 품질을 주장하려면 명시적으로 승인된 실질문 증적이 필요합니다. 엄격한 no-T2 캠페인 동작과 운영 품질 검사는 변경하지 않았습니다. |
| 2026-09-06 | implemented | 독립적으로 검토된 답변과 프로바이더의 사용량 제한 전파를 포함한 고정 역할 및 담당 관계 조립을 완료했습니다. 운영 카탈로그가 잘못되어도 독립적으로 유효한 일반 설명 서비스는 유지합니다. | `current change`; 조립 검사 20개와 연결된 Python 검사 653개 통과. 집중 비평 11회는 계층형 대화 계획에 기록했습니다. | 실제 모델 품질과 승격 근거에는 별도 승인이 필요합니다. |
| 2026-09-06 | in-progress | 적응형 공통 단계 정책, 고정 역할 조립, 만료되는 담당 관계 맥락 및 내부 프로바이더의 사용량 제한 전파를 추가했습니다. | `current change`; `test_wire_adaptive_conversation.py` 19개와 `test_adaptive_provider_budget.py` 10개가 통과했습니다. | 계층형 대화 계획에서 연결 비평 근거를 완료합니다. 실제 승격을 주장하지 않습니다. |
| 2026-09-02 | implemented | 답변 연속성 및 프롬프트 ablation 구획을 추가했습니다. 구현은 보장되는 종결 응답의 유용성을 사실 검증과 분리하고, 권한에 영향을 주는 프롬프트 레이어를 ablation에서 보호하고, 제외 항목을 재실행 시 볼 수 있게 하며, 리비전으로 보호된 설정을 단일 시작 스냅샷으로 적용합니다. 10회의 비평 및 강화 라운드에서 Medium 결함 4개와 Low 결함 5개를 닫았고 마지막 라운드에는 Low 초과 지적이 없었습니다. | `current change`, 집중 Python 검사 312개, 콘솔 검사 6개, 작업 범위 Ruff, 소스 파일 18개의 strict mypy 및 문서 gate가 통과했습니다. | 런타임 검증을 주장하기 전에 통제된 shadow 근거를 보존합니다. |
| 2026-08-29 | implemented | 강화 라운드 8에서 대화 사전 검사 관점 23개를 검토하고 social profile 범위 검사를 안전한 대체 경계 안으로 옮겼습니다. 이제 너무 큰 profile은 narrator 호출 전에 보류되며 turn 밖으로 예외를 전파하지 않습니다. | `current change`; 집중 대화 사전 검사 테스트. | 관리되는 실제 social 응답 근거를 보존합니다. |
| 2026-08-28 | implemented | Temperature 0인 social 분류, temperature 0.3인 페르소나 narration 및 전체 운영 의미 판단을 별도의 조립 prompt 기능으로 분리했습니다. Social narration은 공통 base와 greeting, thanks, farewell 또는 self-introduction용 타입 기반 enforce pack 하나를 조합합니다. 분류기와 narrator는 온톨로지 기능 카탈로그를 받지 않고 narrator는 운영 맥락도 받지 않으며, social 문장은 narrator schema만 전달할 수 있습니다. | `current change`, 집중 prompt, adapter, routing 및 processor 검사 608개 통과, 인증된 자기소개 변형은 이전 전체 social 입력 5,819토큰과 비교해 두 호출에서 전체 약 1.7K-1.9K토큰을 사용했습니다. 조립 검사는 act pack이 서로 섞이지 않음을 입증합니다. | 인증된 pack별 waterfall 근거를 보존하고 더 큰 이중 언어 corpus에서 충돌률, 적절성 및 지연을 측정합니다. |
| 2026-08-14 | in-progress | 이전 출처 이력을 재구성하지 않고 구현 원장을 도입하고 기존의 T2 완전 실제 운영 주장을 바로잡았습니다. | `current change`; 구현 범위 표의 현재 소스와 집중 테스트입니다. | 코어 T2 웹 근거 확인, 두 번째 승인 및 통제된 런타임 근거를 완료해야 합니다. |
| 2026-08-14 | implemented | 격리, 승인, runtime prompt eligibility를 변경하지 않고 범위가 제한된 GitHub skill-source delivery 어댑터를 추가했습니다. | `current change`; 구현 범위 표의 구체 어댑터와 focused 거부 경로 테스트입니다. | Scheduled source owner를 조립하고 governed refresh, 승인, 철회 근거를 보존합니다. |
| 2026-08-14 | implemented | 격리 및 disabled-first prompt eligibility를 유지하면서 strict ETag 검증과 정제된 credential-provider 실패로 외부 source delivery를 강화했습니다. | `current change`; focused skill-source adapter 테스트 `28 passed`. | Scheduled 조립과 governed lifecycle 근거는 남아 있습니다. |
| 2026-08-14 | in-progress | 포크 우선 채널이 의존하는 업스트림 두 번째 승인 근거를 추가했습니다. 범위가 제한된 승인 창, 승인에서 파생된 재실행 안전 항목 식별자, 자기 승인 방지 전수 커버리지입니다. | `current change`; [`hil_pipeline.py`](../../../services/core-control-plane/src/fdai/core/operator_memory/hil_pipeline.py), [`test_hil_pipeline.py`](../../../services/core-control-plane/tests/core/operator_memory/test_hil_pipeline.py); 집중 operator-memory 및 bridge 검사 76건이 통과했고 strict mypy와 작업 범위 Ruff가 통과했습니다. | materializer를 호출하는 포크 우선 채널을 만든 뒤 파이프라인 구획을 활성화합니다. |

### 남은 작업

- [ ] 정제되고 허용 목록으로 제한된 웹 스니펫을 정확한 소스 증적, 프롬프트 다이제스트 재실행
  및 부정 주입 테스트와 함께 코어 T2 도구 매니페스트에 연결합니다.
- [x] 업스트림 두 번째 승인 단계가 서로 다른 principal, 자기 승인 방지, 범위가 제한된 승인 창,
  재실행을 입증합니다. 재전달은 `already_materialized` 로 거부하고 구체화는 정확히 한 번만
  일어납니다.
- [ ] 두 번째 승인 단계를 호출하는 포크 우선 채널을 만든 뒤 해당 파이프라인 구획을
  활성화합니다.
- [ ] 하나의 고정 카탈로그 리비전에서 조립된 프롬프트, 토론, 인용, 최종 검증기 결과 및 실행
  권한 0을 증명하는 통제된 종단 간 T2 증적을 보존합니다.
- [ ] 적합한 각 프롬프트 레이어를 ablation하고, 정확한 활성 및 제외 레이어 매니페스트를
  기록하고, 근거 없는 운영 주장을 0으로 유지하며, 엄격한 보류 응답보다 측정된 유용성 향상을
  입증하는 통제된 답변 연속성 shadow 캠페인을 보존합니다.

## 한눈에 보는 설계

프롬프트는 코드 안의 리터럴이 아니라 **데이터**입니다. 조립 루트가 부팅 시
`rule-catalog/prompts/`에서 로드하고, 기능으로 인덱싱한 뒤, 해석된 본문을
Azure OpenAI 어댑터에 넘깁니다. 런타임 레이어(rule-catalog 인용,
운영자 기억 항목, 도구 출력, web 스니펫, 토론 대화 기록)는 모두
`trusted="false"` XML 태그로 감싸져 모델이 이를 데이터로 취급하도록 합니다.
**결정론적 검증기가 유일한 실행 권한**로 남습니다 - 추가된 역할, 툴,
레이어는 모두 그 검증기를 위한 재료를 생산할 뿐, 우회로가 아닙니다.

대화 routing은 두 개의 별도 prompt 기능을 조립합니다. Compact
`conversation.preflight` prompt는 기능 매니페스트를 로드하기 전에 순수 social, 혼합, 운영 및
맥락 의존 턴을 구분합니다. 조건에 맞는 새 social 턴만 이 단계에서 종료할 수 있습니다. 그 밖의
모든 결과는 전체 `semantic.judgment` prompt를 호출하므로 prompt 축소가 운영 근거 확인을
우회하지 않습니다.

## 역할 x 계층 매트릭스

프롬프트는 두 축을 가집니다. **레이어**는 조립된 프롬프트를 구성하는 콘텐츠 타입이며,
**역할**은 어떤 base / 묶음 / 도구 집합이 적용될지 결정합니다. 카탈로그는 검토자,
제안자, 비평자, Judge, 평가 기준 base 프롬프트를 모두 배포합니다.

| 계층 \\ 역할 | 제안자 | 비평자 | Judge |
|--------------|----------|--------|-------|
| Base (역할 스켈레톤) | `base/t2-proposer.v1.yaml` | `base/t2-critic.v1.yaml` | `base/t2-judge.v1.yaml` |
| 작업 스킬 묶음 | `packs/<capability>.proposer.vN.yaml` | `packs/<capability>.critic.vN.yaml` | (보통 제안자 묶음과 공유) |
| 도구 매니페스트 | 도구 + 선택적 `web.search` | 도구(읽기 전용) | 없음 (Judge는 툴 호출 금지) |
| 도메인 맥락 (RAG) | 룰 / 과거 인시던트 인용 | 동일 | 동일 |
| Web Snippets | 제안자가 가져온 경우 | 읽기 전용 | 읽기 전용 |
| Operator Memory | 범위 제한 | 범위 제한 | 범위 제한 |
| 토론 대화 기록 | (첫 턴엔 비어 있음) | 제안자 출력 | 제안자 + 비평자 출력 |

2-model 검토자가 기본 T2 경로입니다. 제안자 / 비평자 / Judge 토론은 설정된
disagreement에서만 라우터를 통해 실행됩니다.

네 번째 역할인 **평가 기준** 판정자는 Base 레이어(`base/t2-rubric.vN.yaml`)와 도메인
맥락 레이어를 재사용합니다; 제안자의 추론을 고정 기준으로 채점하며 툴을 호출할 수
없습니다. 권위가 아니라 빼기 전용 환각 필터입니다 -
[hallucination-rubric-gate-ko.md](hallucination-rubric-gate-ko.md) 참조.

## 레이어 카탈로그

각 레이어는 고정된 역할과 고정된 저장 티어를 가집니다.

- **Base** - 짧고 불변인 역할 스켈레톤 (출력 계약, verifier-as-authority 리마인드,
  JSON-only 출력 규칙). Wave 1 목표: <= 128 토큰.
- **작업 스킬 묶음** - capability-scoped 지시 (예: RCA grounding, 액션 제안,
  novelty 분류). 각 묶음은 기능이 참조할 수 있는 rule-catalog 항목을 인용합니다.
- **도구 매니페스트** - 이 역할이 호출할 수 있는 툴의 부분집합. base 프롬프트 밖에서
  선언하는 이유는 base를 짧고 캐시 친화적으로 유지하기 위함입니다.
- **도메인 맥락 (RAG)** - 이벤트별로 선택된 룰 발췌와 과거 인시던트 참조.
  프롬프트 옆에 영구 저장하지 않고, 감사에는 인용된 id와 vector-hit 점수만 기록.
- **Web Snippets** - [웹 검색 정책](#web-search-policy) 하에서만 가져옵니다.
  `<web_snippet trusted="false" url="..." hash="...">...</web_snippet>`로 wrap.
- **Operator Memory** - 운영자 피드백(HIL 거부, 재정의 사유,
  ChatOps 선호 설정, PR 리뷰)에서 나온 범위 제한, HIL-승인된 노트.
  절대 global 아님. [Operator 기억 파이프라인](#operator-memory-pipeline) 참조.
- **토론 대화 기록** - 이전 역할들의 출력이 다음 역할에게 읽기 전용 컨텍스트로 전달.

## 저장

### Catalog-as-code (git 추적)

```text
rule-catalog/
  prompts/
    schema/
      prompt.schema.json          # 모든 아티팩트가 검증되는 JSON Schema
    base/
      t2-cross-check.v1.yaml      # Wave 1 (배포됨)
      t2-proposer.v1.yaml         # Wave 3 (배포됨, shadow)
      t2-critic.v1.yaml           # 배포됨, shadow
      t2-judge.v1.yaml            # 배포됨, shadow
      t2-rubric.v1.yaml           # 루브릭 환각 필터 (배포됨, shadow)
    packs/                        # Wave 2+
    tools/                        # Wave 2.5+
```

### 런타임 데이터 (Postgres, 해시 주소 블롭)

  다음은 목표 영속성 모델입니다. `operator_memory`는 배포됐고 전용
  `agent_transcript`와 `web_evidence` 테이블은 아직 계획 단계입니다. Operator API는 현재
  정제된 web 근거를 영속 대화 턴에 첨부합니다.

```sql
CREATE TABLE operator_memory (
  id            uuid PRIMARY KEY,
  scope_kind    text NOT NULL,     -- 'resource-group' | 'resource' | 'vertical'
  scope_ref     text NOT NULL,
  category      text NOT NULL,
  body          text NOT NULL,     -- 주입 시 <operator_note>로 wrap
  source_event  text NOT NULL,     -- 'hil.reject' | 'override.create' | ...
  source_ref    text NOT NULL,     -- audit id / PR url / message id
  author        text NOT NULL,
  approved_by   text NOT NULL,     -- self-approval 금지
  created_at    timestamptz NOT NULL,
  superseded_by uuid,
  ttl           interval
);

CREATE TABLE agent_transcript (
  id             uuid PRIMARY KEY,
  event_id       text NOT NULL,
  round          smallint NOT NULL,
  role           text NOT NULL,    -- 'proposer' | 'critic' | 'judge'
  model_id       text NOT NULL,
  prompt_hash    text NOT NULL,
  layer_manifest jsonb NOT NULL,   -- 정렬된 layer ref + version + token 수
  tool_calls     jsonb NOT NULL,
  response_hash  text NOT NULL,
  cost_usd       numeric NOT NULL,
  latency_ms     integer NOT NULL,
  created_at     timestamptz NOT NULL
);

CREATE TABLE web_evidence (
  content_hash    text PRIMARY KEY,
  url             text NOT NULL,
  fetched_at      timestamptz NOT NULL,
  intent          text NOT NULL,
  sanitized_text  text NOT NULL,
  injection_flags jsonb NOT NULL
);
```

Global 범위의 운영자 기억은 쓰기 시점에 거부됩니다 - 이 설계가 상속하는
[Human 재정의](../../../.github/instructions/architecture.instructions.md#human-override)
정책 기준으로 너무 넓기 때문입니다.

## 프로바이더 protocols (DI 경계)

코어는 프로토콜 뒤에 남고, Azure 어댑터가 경계당 한 구현을 제공합니다. 이 설계의
현재 및 계획된 경계는 다음과 같습니다:

| 경계 | 종류 | Wave | 역할 |
|------|------|------|------|
| `PromptRegistry` | sync | 1 (배포됨) | 프롬프트 YAML 로드 / 인덱스 |
| `PromptComposer` | 비동기 | 2 | 이벤트별 역할 x 계층 조립 |
| `ToolRegistry` | sync | 2.5 | 도구 YAML 매니페스트 로드 |
| `ToolExecutor` | 비동기 | 2.5 | 모델이 발행한 도구 호출 디스패치 |
| `ProgrammaticPipelineRunner` | 비동기 | 범위가 제한된 파이프라인 | 검토된 도구 루프를 isolated venue에서 실행 |
| `OperatorMemoryStore` | 비동기 | 3 | scope-bounded 노트 읽기 / 덧붙이기 |
| `WebSearchProvider` | 비동기 | 5 | 허용 목록 뒤 아웃바운드 HTTP |
| `EvidenceStore` | 비동기 | 5 (계획됨) | hash-addressed 웹 스냅샷 저장 |
| `AgentTranscriptStore` | 비동기 | 4.5 (계획됨) | 추가 전용 토론 행 |
| `DebateOrchestrator` | 비동기 | 4.5 | 제안자 -> 비평자 -> Judge 루프 |

I/O-bound 경계는
[coding-conventions.instructions.md](../../../.github/instructions/coding-conventions.instructions.md#safety)
가 선언한 프로바이더 프로토콜의 async-by-default 규칙을 따릅니다.

## 도구 use 서브시스템

툴은 룰 카탈로그를 미러링한 catalog-as-code입니다. 각 YAML이 설명, 호출 스키마,
기능 게이트, 허용 목록, 출력 래퍼를 선언합니다.

- **기능과 예산**: `llm-registry`가 짧은 제안자/비평자 허용 목록을 선택하고, 각 도구의
  `cost_budget_usd_per_call`이 이벤트별 상한에 반영됩니다.
- **신뢰할 수 없는 출력**: `<tool_result trusted="false" ...>`는 검증기와 정책 re-check용 데이터로
  남습니다. Judge는 도구를 받지 않으므로 두 번째 제안자로 붕괴하지 않습니다.
- **Programmatic 루프**: 검토된 읽기/필터/집계 Python은 다이제스트, 샌드박스, 실행 기능,
  바이트/호출 한도, 증적 검사를 거쳐 생성된 클라이언트로 범위가 제한된 subset을 호출합니다. 프로바이더
  자격 증명, 재귀 권한, 변경 권한은 받지 않습니다.
  [프로그래밍 방식 도구 파이프라인](../interfaces/programmatic-tool-pipelines-ko.md)을 참조하세요.

### 검토된 런타임 스킬

런타임 스킬은 이미 등록된 도구 사용법을 에이전트에게 알려주는 portable Markdown instruction입니다. 저장소 coding-agent 스킬과 별개이며 도구, 신원, 역할, 실행 권한을 부여하지 않습니다. FDAI Console은 `설치됨`, `활성화됨`, `로드 적격`을 load-readiness 상태로 표시하고 권한 승격은 해당 없음으로 표시합니다.
기능 선언은 결정론적 운영자 요청 경로를 별도로 표시하며 변경 선언은 스킬 충족 여부나 카탈로그 존재로 승격을 추론하지 않고 측정된 ActionType 승격 근거로 연결합니다.

- **3단계:** 범위가 제한된 인덱스에는 메타데이터만 포함됩니다. `load_skill`은 완전한 `SKILL.md` 하나를, `read_skill_reference`는 support 산출물 하나를 반환합니다. `list_skills`, `describe_skill`도 읽기 담당 연산이며 수명 주기를 변경하지 않습니다.
- **Signed 산출물 매니페스트:** YAML front matter는 신원, 버전, 출처 이력, 본문 다이제스트, 필수 도구, allowed 에이전트, 내용 기반 주소를 가진 참조를 포함합니다. Unsafe 경로, undeclared/부분 파일, symlink-shaped 메타데이터, 다이제스트 mismatch, 예산 초과분은 실패 시 차단합니다.
- **충족 여부와 재생:** 매 부하는 활성화된 상태, 도구 가용성, 에이전트 허용 목록, stored 바이트, 발행기 서명, 참조 다이제스트를 다시 확인합니다. 프롬프트 재생은 연산,
  스킬 이름/버전, 본문/raw 다이제스트, 참조 다이제스트, 선택된/rejected 상태, 사유를 기록합니다.
- **Progressive 프롬프트:** 인덱스는 선택 본문 및 참조보다 먼저 들어갑니다. 본문은 검증 후에만 trusted 검토된 instruction이며 참조는 신뢰할 수 없는 데이터로 남습니다. 기존 reference-free
  single-file 스킬은 같은 파서와 effective 내용을 변경 없이 사용합니다. 명시적 multi-skill 조립은 [통제된 스킬 Bundles](governed-skill-bundles-ko.md)가 소유합니다.
- **측정 벤치마크:** 고정 16-skill 카탈로그의 네트워크 인시던트, 비용 spike, 배포 실패 시나리오에서 full 변환 결과 8194 estimated 토큰이 완전한 본문 하나 선택 시 1544-1546으로 줄어 81.1-81.2% 감소했습니다.
- **Dynamic 코드 없음:** 런타임 스킬은 binary 설치, 환경 시크릿 주입, 프로바이더 부하,
  도구 카탈로그 및 risk 게이트 bypass를 할 수 없습니다.
- **Audited 제안 workshop:** `SkillWorkshop`은 에이전트 초안을 validate하고 inert
  내용 기반 주소를 가진 데이터로 저장합니다. Injected human authorizer가 사유와 함께 approve 또는
  거부해야 하며 제안자는 self-review할 수 없습니다. 모든 전이는 Markdown 본문을
  포함하지 않고 추가 전용 감사 싱크로 전송됩니다. PostgreSQL 영속성은 재시작 후에도
  유지되며 검토 및 구체화에 expected-state compare-and-swap을 적용합니다. 승격은
  다이제스트 및 발행기 trust 검증을 다시 실행한 뒤 활성 프롬프트 변경 없이 approved
  산출물을 비활성화된 상태로 install합니다.
- **승인된 출처 새로 고침:** 등록된 GitHub 출처는 ETag 상태로 변경할 수 없는 커밋을 해석하고
  declared 파일만 가져와 exact 바이트를 격리 구역에 저장합니다. 통과한 내용은 비활성화된
  후보가 됩니다. Approver installation은 disabled-first를 유지하고 Owner 철회는
  출처 이력을 삭제하지 않고 출처와 영속 산출물을 비활성화합니다. 구체 delivery 어댑터는
  격리 구역에 바이트를 전달하기 전에 redirect, path substitution, symlink, malformed 또는
  oversized content, authentication 실패, rate limit을 거부합니다.
  [스킬 소스 관리](../interfaces/skill-source-management-ko.md)를 참조하세요.

### Operator-memory 검토 및 compaction

Operator-memory 저장소는 활성, 만료된, 대체된 항목을 범위, 출처 이벤트/참조, 작성자,
서로 다른 승인자, TTL-derived 만료, supersession 포인터와 함께 범위가 제한된 검토 변환 결과로
제공합니다. Settings > Operator 기억 콘솔 화면은 GET-only입니다. 변경은 계속 approved HIL
또는 ChatOps 작업 흐름으로 진입합니다.

`MemoryCompactionService`는 범위 및 category가 같고 출처 이력 참조를 가진 활성 unique 출처
항목 2개 이상에서만 더 짧은 항목을 제안할 수 있습니다. 후보 텍스트는 주입 screening을
통과하고 서로 다른 authorized 검토자가 approve하기 전까지 inert합니다. PostgreSQL 승격은
compacted 항목 덧붙이기, 출처 id/참조 보존, original supersession을 atomic하게 수행합니다. Rollback은
본문을 삭제하지 않고 original 출처 항목을 복원하며 compacted 항목을 inactive로 만듭니다.
Compaction은 역할, 도구, 액션, 실행 권한을 부여하지 않습니다.

## 웹 검색 정책

웹 검색은 최후의 수단 툴입니다. 배포별 명시적 선택이며 절대 grounding 출처가
아닙니다.

- **기본 off**: 업스트림은 no-op `WebSearchProvider`를 배포합니다.
  `FDAI_WEB_SEARCH_ENABLED=true`와 curated 도메인 허용 목록을 설정하면 Azure
  Responses 어댑터가 활성화됩니다. 프로덕션은 Operator API managed 신원을
  재사용하며 대화 표면에 검색 API 키를 추가하지 않습니다.
- **언제 실행 가능**: T2 케이스, novelty 점수가 임계값 초과, 기능의
  도구 허용 목록이 `web.search`를 포함, 이벤트당 조회 / 비용 예산이 소진되지
  않음. 이 결정은 산문이 아니라 순수 · 결정론적
  [`decide_web_search`](../../../services/core-control-plane/src/fdai/core/web_search/policy.py) 정책
  (`WebSearchPolicyConfig` + `WebSearchSignals` -> `SEARCH` / `SKIP`)이며,
  `escalation_ladder`를 미러링합니다. deny-first 게이트(비활성화된 -> 프로바이더
  없음 -> 기능 허용 목록 미포함 -> reasoning-tier 아님 -> 조회 예산
  -> 비용 예산 -> grounding-gap 필요 -> novelty 임계값)를 평가하고 건너뜀
  사유를 감사 로그에 기록하므로, "언제 웹 검색이 실행되는가"는 문단이
  아니라 테스트로 답합니다.
- **도메인 허용 목록**: 기본 출처만 사용합니다(벤더 docs, RFC, NVD, CVE 레지스트리). 허용 목록 도메인은 DNS 하위 도메인을 포함하지만 라벨 경계 검사는 suffix-confusion 호스트를 차단합니다. 블로그, 포럼 및 소셜 미디어는 지원되지 않습니다.
- **스니펫 처리**: HTML strip. prompt-유사 패턴(`ignore previous`, `system:` 등)
  탐지 및 플래그. inject 전에 `<web_snippet trusted="false">...</web_snippet>`
  로 wrap.
- **Grounding 출처가 아님**: `cited_rule_ids`는 여전히 rule-catalog 항목으로
  해석되어야 합니다. 유용한 웹 발견은 rule-catalog 발견 루프로 흘러가며,
  현재 이벤트의 grounding 요구를 만족시키지 않습니다.
- **재생 결정성**: 결과는 `web_evidence`에 `(content_hash, url, fetched_at)`
  로 저장. 감사 엔트리는 해시를 참조. 재생은 저장된 스냅샷을 읽으며 다시 fetch
  하지 않으므로 과거 실행이 재현 가능하게 유지됩니다.
- **통제된 Azure Responses 어댑터**: Azure-first 구현은 managed `web_search`를 `WebSearchProvider`
  뒤에 감쌉니다. Direct Responses는 매 요청에 `allowed_domains`를 보내고, 선택적 Foundry
  prompt-agent 경로는 정확한 배포 허용 목록을 사용하며 런타임 표류를 거부합니다. 두 경로
  모두 `web_search_call`을 검증하고 off-allowlist 인용을 거부하며 정제된 근거 스냅샷을 영속
  대화 턴에 저장합니다. 제한된 운영자 조회만 FDAI 밖으로 나가며
  화면 스냅샷과 대화 이력은 검색 호출에 전송되지 않습니다. 프로바이더 실패는 `tool_blocked`, `provider_unauthorized`, `provider_rate_limited` 같은 제한된 사유 코드로 변환하며 raw 응답 본문은 대화에 포함하지 않습니다. 조직 전체 차단 및 권한 확인 실패는 모델 장애 조치를 중단하고 transient 실패만 다음 배포를 시도합니다.
- **지연 기반 모델 풀**: 검색 후보는 `resolved-models.json`의
  전용 `t1.web_search` 레지스트리 기능에서 가져와 `web_search_candidates`로
  serialize합니다. Narrator 후보는 대체 경로로 사용하지 않습니다. 시작은 후보별
  managed-tool 검색을 실제로 한 번 보내고 실패 후보를 serving 전에 제외합니다. 이후
  주기적 모델 지식만 쓴 탐색은 검색 비용 없이 지연 시간을 갱신합니다. 검색 호출은 rolling p50이
  가장 낮은 후보를 선택하고 오류 시 다음 후보로 장애 조치합니다. 선택 배포,
  p50/p95 이력, 실제 검색 지연 시간을 출처 이력으로 반환합니다. 탐색은 웹 검색을
  호출하지 않으므로 주기적 상태 측정에는 검색 툴 비용이 발생하지 않습니다.
- **외부 데이터 경계**: Azure `web_search`는 Grounding with Bing을 사용합니다.
  이 전송에는 Microsoft 데이터 Protection Addendum가 적용되지 않으며 데이터가
  배포의 compliance 및 geography 경계 밖으로 나갈 수 있습니다. 따라서
  명시적으로 활성화하고 도메인을 허용 목록으로 제한합니다. GUID, Azure 리소스
  ID, 이메일 주소, 비공개 IP 주소가 포함된 질의는 전송 전에 차단합니다.

## 토론 오케스트레이터 (제안자 / 비평자 / Judge)

토론은 라우터가 요청할 때만 실행됩니다 - 보통 high-severity, high novelty,
또는 명시적인 operator-memory 지침. 기본 T2 경로는 여전히
[llm-strategy-ko.md](../architecture/llm-strategy-ko.md)에 문서화된 2-model 교차 검증입니다.

```text
Proposer  -- candidate + citation + confidence
   |
   v
Critic    -- objection: [{severity, cited_rule_id, alt_action?}]
   |
   v
Judge     -- decision in {accept, revise_and_retry (<=1), escalate_hil}
   |
   +--> accept       -> 결정론적 verifier -> risk gate
   +--> revise       -> Proposer 1회 재시도 (total round <= 2)
   +--> escalate_hil -> 종료
```

이벤트당 하드 리밋: `debate.max_rounds <= 2`, `debate.max_wall_seconds`,
`debate.max_cost_usd`. 초과 시 HIL로 abort. 비평자는 제안자와 다른 발행기
모델이어야 합니다 (mixed-model distinctness 규칙 확장,
[llm-strategy-ko.md](../architecture/llm-strategy-ko.md#t2---reasoning-tier-quality-gate-required)).
Judge는 더 작고 저렴한 모델이어도 됩니다.

비평자의 역할은 "다른 의견"이 아니라, 7개 안전조건(stop-condition, 롤백, blast-radius,
예행 실행, 잠금, 멱등성, audit-log)에 대한 체크리스트 + 인용 validity + 운영자 기억
와의 모순 여부입니다.

## Operator 기억 파이프라인

Operator 피드백은 두 단계 게이트를 거쳐 기억이 됩니다:

```text
HIL reject / approve reason -----\\
Override create / modify event  --+--> operator-memory 후보
ChatOps preference message      --|         |
PR review comment on rem PR     --/         v
                                     HIL 2차 승인 (self-approval 금지)
                                             |
                                             v
                                  operator_memory 행 (append-only)
```

- **범위는 resource-group 이하여야 합니다.** 더 넓은 범위는 재정의가 아닌
  룰 변경이며, 카탈로그 파이프라인을 통과해야 합니다.
- **주입 시 sanitize + wrap**: 기억 본문은
  `<operator_note author="..." scope="..." trusted="false">...</operator_note>`
  태그 안으로 들어가며, base 프롬프트는 해당 태그 안의 지시를 따르는 것을
  금지합니다.
- **발견 신호**: 같은 룰에 대한 장기 재정의 또는 유사한 기억 행의 다수는
  rule-catalog 발견 루프에 개정 번호 / retirement 후보로 흘러갑니다.

> Working-context 선택은 [컨텍스트 선택 정책](context-selection-policy-ko.md)이 별도로 소유합니다:
> 불변 `deterministic-tiered-v1@1.0.0`, 필수 검증, shadow 근거, 재생 및 롤백.

## 인식 측정

긴 프롬프트는 조용히 지시를 흘립니다. "모델이 우리가 보낸 것을 실제로 읽었는가"를
1급 KPI로 다루며, 프롬프트를 강제 적용으로 승격하기 전에 게이트합니다.

- **하드 토큰 예산** - 작성기가 조립된 프롬프트당 토큰을 추정. 초과 시 HIL로
  abort하고 `prompt.token_budget.exceeded_rate`를 증가. 우선순위가 낮은 레이어
  (가장 오래된 운영자 기억부터)는 감사에 보이는 이유와 함께 명시적으로 폐기.
- **Canary 토큰** - 작성기가 태그된 레이어 마커
  (`<layer id="pack.rca.v3">...</layer>`)를 삽입. 역할들은 어느 레이어를
  인식했는지 보고. 인식되지 않은 고우선순위 레이어는 결함으로 surfacing.
- **Adherence 비율** - JSON 스키마 위반, 필수 필드 누락, citation-rule-id
  validity를 매 프롬프트 버전 bump마다 고정 시나리오 세트에서 측정.
- **Position 민감도** - 통제된 고정본이 동일한 지시를 base vs. 묶음
  vs. 끝에 배치하고 adherence를 비교. 특정 위치의 지속적 dip은 base 재작성
  신호.
- **Mixed-model agreement 비율** - 기존 quality-gate disagreement 비율을
  프롬프트 버전별로 추적하여 리그레션을 즉시 노출.
- **토론 economics** - 토론 오케스트레이터 랜딩 후
  `debate.rounds.p95`, `debate.cost_usd.p95`, `debate.timeout_to_hil_rate`,
  `critic.reversal_rate`를 추적.

승격 게이트 (초기값, 기능별로 튜닝): `adherence >= 0.95`,
`citation_f1 >= 0.9`, `web.grounding_leak == 0`, `토론.timeout_to_hil_rate
<= 5%`, `비평자.reversal_rate in [1%, 15%]`.

## 답변 연속성과 프롬프트 ablation

답변 연속성은 수락된 대화 턴을 위한 구성 가능한 표현 정책입니다. 올바른 진단을 약속하지
않습니다. 검증된 답변을 제공할 수 없으면 범위가 제한된 실패 원인을 밝히고, 확인된 사실과
알 수 없는 부분을 구분하고, 정확히 부족한 근거를 나열하며, 등록된 읽기 또는 시뮬레이션
기능만 제안하는 유용한 안전 보류 응답을 반환합니다.

흐름은 계속 `T0 -> T1 -> verification -> bounded T2 -> deterministic verification`입니다.
연속성을 켜도 계층을 건너뛰거나 점수를 변경하거나 검색 순위를 신뢰도로 취급하거나 실행
권한을 부여하지 않습니다. 품질이 낮은 T2 결과는 보류 설명을 개선할 수 있지만, 근거 없는
주장을 답변으로 바꿀 수 없습니다.

### 런타임 정책

리비전 기반 런타임 설정 표면은 서로 독립적인 두 control을 소유합니다.

- `conversation.answer_continuity.enabled`는 재시작 후 유용한 안전 보류 렌더링을 켭니다.
  기본값은 `false`입니다.
- `conversation.prompt_ablation.profile`은 검토된 평가 profile 하나를 선택합니다. 프로덕션
  기본값은 `none`입니다. 다른 profile은 task pack, tool manifest, operator memory,
  runtime skill 또는 모든 선택적 context를 제거할 수 있습니다.

배포 설정은 상한입니다. 요청 텍스트, 모델 출력, 실험 또는 사용자 선호는 런타임 정책이
선택하지 않은 profile을 켤 수 없습니다. 모든 업데이트는 기존 리비전 검사와 추가 전용
설정 감사를 사용합니다.

### 보호 및 ablation 가능 레이어

| 분류 | 레이어 | Ablation 동작 |
|------|--------|---------------|
| 보호 | base 역할, Critic, Judge, rubric, role header | 제거할 수 없습니다. Profile이 이를 대상으로 지정하면 시작 또는 조립 단계에서 안전하게 차단됩니다. |
| 적합 | task pack, tool manifest, operator memory, skill index/body/reference/bundle | 검토된 profile만 제거할 수 있습니다. 작성기는 ablation된 저장소나 카탈로그를 읽지 않고 제외된 각 레이어 또는 아티팩트를 기록합니다. |
| 외부 권한 | tool call-site 정책, RBAC, 검증기, risk gate, 승인, 실행기 | 프롬프트 밖에 있으며 ablation할 수 없습니다. 매니페스트 누락은 권한 제어가 아닙니다. |

각 `ComposedPrompt`와 `PromptReplayManifest`는 ablation profile과 순서가 있는 제외 레이어
참조를 전달합니다. Canary는 제외 후에만 주입되므로 인식 메트릭이 제거된 레이어를 읽지 않은
것으로 계산하지 않습니다. Ablation된 도구 매니페스트는 실행기의 기본 차단 분류를 변경하지
않습니다.

### 유용한 안전 보류

답변 연속성이 켜져 있어도 `held`와 `unsupported` 턴은 원래 처리 결과와 사유 코드를
유지합니다. 지역화된 답변만 달라지며 다음을 포함합니다.

1. 근거로 지원되는 가장 강한 상태
2. 범위가 제한된 정확한 사유 코드
3. 운영 변경이 승인되지 않았다는 설명
4. 부족한 범위를 요청하거나 등록된 읽기 전용 조사를 안내하는 안전한 다음 단계
5. 의미 또는 모델 근거가 불완전한 경우 낮은 신뢰도 안내

결정적 사실이 없으면 가설도 만들지 않습니다. 응답은 계속 보류이며 콘솔은
`verification.status=unverified`를 계속 표시합니다.

## 안전 불변식 (확장)

[coding-conventions.instructions.md](../../../.github/instructions/coding-conventions.instructions.md#safety)
의 8개 불변식에 이 설계 랜딩과 함께 10개가 추가됩니다:

1. 웹 검색 출력은 **절대** `cited_rule_id`가 아님.
2. 도구 결과와 web 스니펫은 **항상** `trusted="false"` XML로 wrap.
3. 토론 루프는 하드 `max_rounds`, `max_wall_seconds`, `max_cost_usd`
   상한을 가지며, 초과 시 HIL로 abort.
4. 비평자와 제안자의 발행기는 **달라야** 하며, 같은 발행기 쌍은 단일
   voter로 붕괴함.
5. Judge는 툴을 호출**해서는 안 됨**. Judgment와 세대는 분리.
6. Web 근거는 해시 주소 변경할 수 없는이며, 재생은 스냅샷을 읽고 다시 fetch
   하지 않음.
7. 프롬프트 ablation은 base 역할, Critic, Judge, rubric, role header, 결정적 검증기,
   RBAC 검사 또는 도구 호출 시점 정책을 제거하지 않습니다.
8. Ablation된 모든 레이어 또는 아티팩트는 재실행 근거에 남습니다. 조용한 제외는 지원하지
   않습니다.
9. Ablation된 선택적 원본은 읽지 않으며 다른 레이어를 통해 모델 context로 유출될 수
   없습니다.
10. 답변 연속성은 원래 종결 처리 결과를 유지하며 검증되지 않은 응답을 `answered`로
    승격하지 않습니다.

## 롤아웃 waves

모든 wave는 shadow first로 랜딩. 승격은 이전 wave의 승격 게이트가 유지되어야 함.

| Wave | Deliverable | 배포됨 |
|------|-------------|--------|
| 1 | Base 프롬프트 카탈로그 외부화 + `PromptRegistry` + 조립 배선 | yes |
| 2 | `PromptComposer` 비동기 프로토콜 + `DefaultPromptComposer` (Base + 작업 묶음) + `ComposedPrompt` / `LayerRef` 인식 프리미티브 + `AzureOpenAICrossCheckModelConfig`의 `system_prompt` 필수 전환 | yes |
| 2.5-A | `DefaultPromptComposer`의 shadow-vs-enforce 필터 + 배포된 shadow 모드 작업 묶음 + `tool.schema.json` + `FileSystemToolRegistry` | yes |
| 2.5-B 단계 1 | 작성기가 선택적 도구 매니페스트 레이어 발행 + 배포된 shadow 모드 도구 YAML (`rule.query` / `state.query` / `audit.query`) + `trusted="false"` 래퍼 강제 | yes |
| 2.5-B 단계 2a | 비동기 `ToolExecutor` + `ToolProvider` 경계 + 스키마 검증, shadow 가드, 래퍼 강제, 5개의 타입이 지정된 실패 시 차단 에러 (`UnknownToolError`, `ShadowToolBlockedError`, `ToolArgumentValidationError`, `MissingProviderError`, `ProviderCallError`)를 가진 `DefaultToolExecutor` | yes |
| 2.5-B 단계 2b | `AzureOpenAICrossCheckModel`이 강제 적용 모드 도구에 대해 `tools=[...]`를 발행하고, 범위가 제한된 multi-turn 루프로 모델 발행 `tool_calls`를 실행기로 라우팅하며, 알 수 없는 함수명 / 잘못된 arguments / half-wired 설정을 실패 시 차단으로 거부 | yes |
| 3 단계 A | `core/operator_memory/` 타입 + 비동기 `OperatorMemoryStore` 프로토콜 + `InMemoryOperatorMemoryStore` + `wrap_operator_note` / `detect_injection_markers` sanitizer + 쓰기 시점 정책 강제(범위 <= resource-group, 서로 다른 승인자, 추가 전용 대체, 선택적 TTL, 주입 마커 거부) | yes |
| 3 단계 B 저장소 | `PostgresOperatorMemoryStore` + alembic 이행 `20260706_0006_operator_memory` (추가 전용 테이블, Python 정책을 미러링한 검사 제약, `(scope_kind, scope_ref)` scope-lookup 인덱스, `InMemoryOperatorMemoryStore`와 TTL + 대체 시맨틱 동등성, `FDAI_DATABASE_URL` unset 시 스킵되는 통합 테스트) | yes |
| 3 단계 B 파이프라인 구획 1 | `HilResponse(decision=REJECT, reason=...)` + 별개의 `second_approver`를 주입된 `OperatorMemoryStore`를 통해 저장된 `OperatorMemoryEntry`로 변환하는 `HilRejectMaterializer` 코어 모듈; 7개의 pipeline-level 오류 코드 (`wrong_decision`, `empty_reason`, `missing_first_approver`, `missing_second_approver`, `same_principal`, `missing_response_time`, `approval_expired`)가 저장소 접근 전에 fail-fast, 재전달은 `already_materialized`로 표면, 다른 store-side 정책 오류(주입 표시)는 그대로 표면 | yes |
| 3 단계 B 파이프라인 구획 2 | Composition-root wire: `_build_operator_memory_store()`가 `FDAI_OPERATOR_MEMORY_DSN`으로 Postgres를 선택하거나 기본값으로 in-memory 가짜를 사용하고, `_finalize_llm_bindings`가 저장소를 `DefaultPromptComposer`에 인계하므로 operator-memory 레이어가 데이터베이스 없이도 종단 간으로 도달 가능 (포크가 `HilRejectMaterializer`로 덧붙이기한 항목이 즉시 작성기에 보임) | yes |
| 3 단계 B 파이프라인 구획 3 | 실제로 materializer를 invoke하는 second-approval 채널 (Teams Adaptive 카드 / git PR / fork-authored CLI). 승인 채널은 배포마다 다르므로 fork-first 유지; 업스트림은 `HilRejectMaterializer` 경계와 operator-memory 저장소만 배포하고 특정 UI는 배포하지 않음 | 계획됨 |
| 3 단계 C-1 | `DefaultPromptComposer`가 선택적 `operator_memory_store` + `scope`를 받고 operator-memory 레이어를 발행. 각 항목은 `wrap_operator_note`로 wrap. 계층 해석은 resource-group note를 리소스 note 앞에 배치 | yes |
| 3 단계 C-2 | `AzureOpenAICrossCheckModel`이 시작 시 한 번이 아니라 per-event로 작성기를 호출 (포크가 제공하는 선택적 `ScopeResolver`가 후보에서 `OperatorScope`를 도출)하므로 운영자 기억이 실제로 모델에 도달 | yes |
| 3 단계 D-1 | Recognition-probe 프리미티브 (`RequiredField`, `ExpectedResponse`, `CitationScores`, `RecognitionResult`) + 순수 평가기 함수 (`evaluate_adherence`, `evaluate_canary_echoes`, `evaluate_citations`, `score_recognition`) - `core/measurement/prompt_probe.py` | yes |
| 3 단계 D-2a | `CanaryGenerator` 프로토콜 + `SecretsCanaryGenerator` / `DeterministicCanaryGenerator` + `ComposedPrompt.canary_tokens` 필드 + 작성기 레이어별 head-marker 주입 (`canary_generator=` 파라미터 명시적 선택. 기본값은 빈 대응이므로 프로덕션 동작 무변화) | yes |
| 3 단계 D-2b-i | `RecognitionKpiSummary` 데이터 클래스 + `summarize_recognition` 집계 (adherence 통과 비율, per-code violation counts, per-layer canary echo 비율 - measured denominator 사용, 스코어된 샘플만 대상으로 하는 인용 F1 mean) | yes |
| 3 단계 D-2b-ii-alpha | `RecognitionScenario` / `RecognitionSample` / `RecognitionRunReport` + `ScenarioResponder` 프로토콜 + `score_batch` (순수) + `run_scenarios` (작성기 + 응답자 오케스트레이션. 작성기 canary가 자동으로 스코어링에 승격) | yes |
| 3 단계 D-2b-ii-beta | `rule-catalog/prompts/scenarios/` scaffold + `scenario.schema.json` + `load_scenarios(catalog_root)` 파일시스템 로더 (aggregate-error 표면, 파일명 `<id>.v<version>.yaml`, 빈 카탈로그 합법) | yes |
| 3 단계 D-2b-ii-gamma-1 | `emit_kpi_rows(report)` target-neutral KPI 행 emitter + `KpiRow` / `RowUnit` 타입 + 안정된 메트릭 이름 상수 (`prompt.recognition.*`) | yes |
| 3 단계 D-2b-ii-gamma-2 | recognition 메트릭 이름에 wire된 CLI 실행기 + 대시보드 패널 | 계획됨 |
| 4 alpha | 비평자 역할 스캐폴딩: `CriticStance` / `CriticSeverity` / `CriticObjection` / `CriticOutput` / `CriticVerdict` 타입 + `CriticModel` 프로토콜 + `evaluate_critic_output()` 순수 평가기 + `rule-catalog/prompts/base/t2-critic.v1.yaml` (`default_mode: shadow`, `applies_to: [t2.critic]`). QualityGate에 실제 운영 wire 없음; Wave 4.5가 토론 오케스트레이터를 랜딩할 때까지 dormant | yes |
| 4 beta-1 | `AzureOpenAICriticModel` httpx 어댑터가 Azure OpenAI ``채팅/completions`` 구조화된 JSON 출력을 통해 `CriticModel` 프로토콜을 구현; strict 실패 시 차단 파서 (알 수 없음 stance / 심각도 / 누락 필드 / non-string 인용 / blank description 모두 raise). 아직 조립 루트에 wire되지 않음 - 배포된 카탈로그 시드는 `default_mode: shadow` 유지 | yes |
| 4 beta-2 | `rule-catalog/llm-registry.yaml`에 `t2.critic` 기능을 추가 (`invocation: on_disagreement`, Anthropic-first 선호 설정으로 제안자와 발행기 구분). `LlmBindings`가 선택적 `critic_model` 필드를 갖고, `bind_azure_llm_bindings`가 기능 해석 + `critic_system_prompt` 공급 모두 만족될 때 `AzureOpenAICriticModel`을 바인딩. 시작 로그에 `critic_prompt_composed` 구조화 엔트리 추가 | yes |
| 4.5 alpha | Judge 역할 스캐폴딩: `JudgeDecision` / `JudgeOutput` / `JudgeVerdict` 타입 + `JudgeModel` 프로토콜 + `evaluate_judge_output()` 순수 평가기 + `rule-catalog/prompts/base/t2-judge.v1.yaml` (`default_mode: shadow`, `applies_to: [t1.judge]`). 토론 오케스트레이터 설계에 따라 Judge는 smaller / cheaper 모델 유지 | yes |
| 4.5 beta | `AzureOpenAIJudgeModel` httpx 어댑터가 `JudgeModel` 프로토콜을 구현; 비평자 어댑터와 동일한 형태의 strict 실패 시 차단 파서 | yes |
| 4.5 gamma | `DebateOrchestrator` 코어 모듈이 `max_rounds = 1`로 제안자 / 비평자 / Judge를 orchestration; 모든 어댑터 예외에 실패 시 차단 (`error_class`가 보존된 `DebateVerdict.ABORT` 반환), 감사 로그용 토론 대화 기록을 `DebateOutcome`에 보존, 비평자가 이미 ABORT하면 Judge를 short-circuit (token-cost 보호) | yes |
| 4.5 delta-1 | Composition-root wire: `LlmBindings`가 선택적 `judge_model`과 `debate_orchestrator` 필드를 갖게 됨. `bind_azure_llm_bindings(judge_system_prompt=)`가 `t1.judge` 기능 해석 + 프롬프트 공급 시 `AzureOpenAIJudgeModel` 바인딩. `critic_model` AND `judge_model` 둘 다 바인딩되면 `DebateOrchestrator(max_rounds=1)` 자동 생성; `__post_init__`이 일관성 없는 수동 생성 거부. `__main__`이 shipped 시드에서 `t2.judge` 프롬프트 조립을 `LookupError`-graceful 성능 저하로 처리 | yes |
| 4.5 delta-2a | `core/quality_gate/debate_router.py`의 `DebateRouter` 순수 정책 모듈: `DebateRoutingDecision` + `DebateRouterConfig` (`enabled` 킬스위치, `on_cross_check_disagreement` 축, `always_for_action_types` / `never_for_action_types` 허용/거부 리스트) + `decide_debate_route()` 실패 시 차단 술어. 오케스트레이터 미이용 시 건너뜀 short-circuit; 킬스위치가 허용 목록 지배; denylist가 허용 목록 이김 | yes |
| 4.5 delta-2b | `QualityGate`가 선택적 `debate_orchestrator` + `debate_router_config` 수용. 교차 검증 disagreement 시 `decide_debate_route()` 호출; `DEBATE`면 기본 교차 검증 모델을 재호출하는 no-directive `retry_proposer`와 함께 오케스트레이터 실행. `DebateOutcome.PROCEED`가 disagreement를 `ELIGIBLE`로 flip (다른 soft issue가 없는 한); `ABORT`는 `DISAGREE` 유지. Half-wiring (두 파라미터 중 하나만) 은 construction 시점에 raise | yes |
| 5 alpha | `core/web_search/`의 웹 검색 경계: `WebSearchQuery` / `WebSnippet` / `WebSearchResult` 타입, `WebSearchProvider` 비동기 프로토콜, `NoOpWebSearchProvider` 기본 비활성 가짜 (모든 쿼리에서 zero snippets + `reasons=("no_op_provider",)` 반환), 그리고 off-allowlist 도메인과 주입 표시를 거부한 후 `<web_snippet trusted="false" ...>...</web_snippet>` 묶음을 생성하는 sanitizer 헬퍼 (`validate_snippet_domain`, `detect_snippet_injection_markers`, `wrap_web_snippet`) | yes |
| 5 beta-A | Azure Responses 프로바이더 + latency-routed 모델 풀 + Operator API 채팅 명시적 선택 배선 | yes |
| 5 beta-B | 정책에 따라 정제된 스니펫을 도구 매니페스트에 threading하는 코어 T2 조립 wire | 계획됨 |

### Wave 4.5 delta-2a - 무엇이 배포되었나

위 rollout 표에서 이 배포를 기록합니다. 현재 라우팅 계약은
[토론 오케스트레이터](#토론-오케스트레이터-제안자--비평자--judge)를 참조하세요.

## 관련 문서

| 목적 | 시작 지점 |
|------|-----------|
| Tier 경계와 quality 게이트 | [llm-strategy-ko.md](../architecture/llm-strategy-ko.md) |
| Trust 라우팅과 컨트롤 루프 | [../../.github/instructions/architecture.instructions.md](../../../.github/instructions/architecture.instructions.md) |
| 이 설계가 확장하는 Human 재정의 정책 | [../../.github/instructions/architecture.instructions.md#human-override](../../../.github/instructions/architecture.instructions.md#human-override) |
| 안전 불변식과 코딩 컨벤션 | [../../.github/instructions/coding-conventions.instructions.md](../../../.github/instructions/coding-conventions.instructions.md) |
| Prompt-injection 위협 모델 | [security-and-identity-ko.md](../architecture/security-and-identity-ko.md) |
| Rule 카탈로그와 출처 이력 규칙 | [rule-catalog-collection-ko.md](../rules-and-detection/rule-catalog-collection-ko.md) |
