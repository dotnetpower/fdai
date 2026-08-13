---
translation_of: automation-blueprints.md
translation_source_sha: ac7fc0aac838dac91f40b0d2861285c5c30e6950
translation_revised: 2026-08-11
---
# Reviewable 자동화 Blueprints

자동화 청사진은 반복해서 성공한 운영자 작업을 inert 예약 suggestion으로 바꿉니다.
후보는 evidence-backed, 비활성화된, shadow-only, reviewable 상태이며 authorized 운영자가
수용하고 명시적으로 materialize하기 전에는 scheduled 작업을 만들 수 없습니다.

> **범위:** 버전 1은 스케줄러 작업만 제안합니다. 예약 auto-activation, broad 범위 추론,
> scheduled 실행 또는 검토 대화의 재귀 예약 suggestion은 지원하지 않습니다.

## Design at a glance

결정론적 aggregator는 completed-turn 근거를 정규화된 의도, principal, 리소스 범위,
예약 등급으로 그룹합니다. Recurrence 임계값을 충족하고 권한 필드가 동일하며 모든
결과가 성공하고 같은 키의 스케줄러 이력에 해결되지 않은 실패가 없어야 합니다.

후보는 출처 텍스트 대신 근거 지문을 저장하고 narrow 범위, 예약, 이벤트 타입,
전달 의도, 도구, default-deny 격리, estimated 비용, 확신도, 제안자, 만료를 가집니다.
선택적 off-path drafting은 범위가 제한된 display 텍스트만 변경할 수 있습니다.

## 구현 상태

### 구현 범위

| 영역 | 상태 | 근거 | 참고 |
|------|------|------|------|
| 근거 계약 및 결정론적 반복 집계 | implemented | `services/core-control-plane/src/fdai/core/scheduler/blueprints/models.py`; `services/core-control-plane/src/fdai/core/scheduler/blueprints/aggregator.py`; `services/core-control-plane/tests/core/scheduler/test_blueprint_aggregator.py` | focused test는 inert 기본값, 임계값과 순서 독립성, 중복 제거, 범위와 권한 분리, 결과 안정성, 예약 실패 차단, 재귀 차단, 입력 검증을 다룹니다. |
| 검토, 구체화, 범위가 제한된 초안 작성, 감사 이벤트, 메트릭 집계 | implemented | `services/core-control-plane/src/fdai/core/scheduler/blueprints/review.py`; `services/core-control-plane/src/fdai/core/scheduler/blueprints/text.py`; `services/core-control-plane/tests/core/scheduler/test_blueprint_review.py` | focused test는 권한 확인, 자체 검토 차단, 최종 상태 억제, 만료, 텍스트 한계, 명령을 통한 재시도 안전 구체화, 감사 이벤트, 실제 사용량 집계를 입증합니다. |
| 제안 조정 및 구성 검토 변환 | in-progress | `services/core-control-plane/src/fdai/core/scheduler/blueprints/suggestion.py`; `services/core-control-plane/src/fdai/core/scheduler/blueprints/configuration_review.py` | 별도 경로 제안 서비스와 inert 구성 검토 변환은 있지만, 운영 근거 피드, composition 연결, focused orchestration test는 없습니다. |
| PostgreSQL 내구성 및 compare-and-swap 전환 | in-progress | `alembic/versions/20260720_0043_automation_blueprint.py`; `services/core-control-plane/src/fdai/delivery/persistence/postgres_automation_blueprint.py`; `services/core-control-plane/tests/persistence/test_automation_blueprint.py` | 이행, 저장소, codec이 있고 codec test가 통과합니다. `FDAI_DATABASE_URL`이 설정되지 않아 데이터베이스 기반 영속성 및 compare-and-swap test가 건너뛰어졌으므로 내구성 동작을 implemented로 판단하지 않습니다. |
| 읽기 전용 Console 경로 및 응답 decoder | implemented | `console/src/routes/automation-blueprints.tsx`; `console/src/routes/automation-blueprints.test.ts`; `console/src/panel-sources.ts` | 경로는 inert 후보와 메트릭 필드를 표시하고 모순된 응답을 거부하며 변경 control을 제공하지 않습니다. 이 상태는 end-to-end Operator API 출처를 주장하지 않습니다. |
| Operator API 변환 결과 및 권한이 적용된 ChatOps 검토 경로 | not-started | `console/src/panel-sources.ts`; `services/operator-service/src/fdai_operator_service/` | Console은 `GET /automation-blueprints`를 선언하지만, 일치하는 Operator Service 변환 결과나 ChatOps 수락, 거절, 구체화 경로 factory가 없습니다. |

### 구현 이력

| 날짜 | 상태 | 변경 | 근거 | 남은 작업 |
|------|-------|------|------|-----------|
| 2026-08-14 | in-progress | 이전 출처를 재구성하지 않고 구현 ledger를 도입했습니다. focused test로 뒷받침되는 집계, 검토, 구체화, 초안 작성, 메트릭, Console decoder를 implemented로 기록하고, 연결되지 않은 조정, 입증되지 않은 PostgreSQL 내구성, 누락된 운영자 화면을 분리했습니다. | `current change`; 범위 표에 나열된 소스 및 focused test; `uv run pytest -q --no-cov services/core-control-plane/tests/core/scheduler/test_blueprint_aggregator.py services/core-control-plane/tests/core/scheduler/test_blueprint_review.py services/core-control-plane/tests/persistence/test_automation_blueprint.py` (`FDAI_DATABASE_URL`이 설정되지 않아 `12 passed, 1 skipped`); `npm --prefix console test -- --run src/routes/automation-blueprints.test.ts` (`2 passed`) | `validated`를 주장하기 전에 운영 서비스를 연결하고, 데이터베이스 기반 전환을 입증하고, 거버넌스가 적용된 Operator API 및 ChatOps 경로를 제공하고, 런타임 근거를 수집합니다. |

### 남은 작업

- [ ] 운영 근거 피드, 제안 서비스, PostgreSQL 저장소, 권한 확인기, 감사 게시자,
  `CreateScheduledTaskCommand`를 연결한 뒤, 조건을 충족하는 완료된 운영자 turn 세 개가
  재귀 입력 없이 하나의 inert 영속 후보로 바뀜을 입증하는 통합 테스트를 통과합니다.
- [ ] 일회용 PostgreSQL 데이터베이스에 이행을 적용하고 `FDAI_DATABASE_URL`을 설정하여
  `test_postgres_blueprint_store_persists_and_cas_transitions`를 통과합니다. 이 테스트에는
  동시 또는 오래된 상태의 compare-and-swap 거부가 포함되어야 합니다.
- [ ] Reader 역할로 제한된 Operator Service `GET /automation-blueprints` 변환 결과와 별도로
  권한이 적용된 ChatOps 수락, 거절, 구체화 경로를 추가한 뒤, API 통합 테스트 및 권위 있는
  응답을 대상으로 한 Console decoder 테스트를 통과합니다.
- [ ] 운영 연결에서 문서화된 blueprint 메트릭을 내보내고, 범위 행을 `validated`로 변경하기
  전에 제안, 검토, 구체화, 예약 실행, 실제 사용량 귀속에 대한 거버넌스 적용 런타임 근거를
  기록합니다.

## 근거 and recurrence

`AutomationBlueprintEvidence`는 신원, 예약, 이벤트 타입, 리소스 범위, 전달, 도구,
격리, 결과, 비용, occurrence 시간, 출처를 기록합니다. `operator_turn` 근거만 개수하고
`scheduled_run`과 `blueprint_review`는 개수하지 않습니다. Scheduled 실패는 matching 키를 veto합니다.

기본값 임계값은 unique 지문 3개입니다. Mixed 범위는 별도 그룹입니다. 후보 ID는
dedup 키와 고정된 근거 집합을 연결하므로 순서와 무관하고 거절/만료 후 실제 new 근거가
생기면 후속 후보를 만들 수 있습니다.

## Inert 계약

모든 후보는 `state=draft`, `enabled=false`, `shadow_only=true`, 변경 도구 없음, narrowest
관찰된 범위, default-deny 격리, 30-day 만료로 시작합니다. Policy는 만료를 1 시간부터
90 days로 제한합니다. 컨트롤 character, unsafe ID, 중복 도구, 부정 비용, naive 시각,
권한 표류는 집계 전에 실패합니다.

## 검토 and 구체화

```text
draft -> accepted -> materialized
  |          |
  +-> rejected
  +-> expired <-+
```

검토에는 authorized principal, 사유, 제안자와 다른 검토자가 필요합니다. 거부와 만료는
최종입니다. Same-evidence 재제출은 최종 기록을 반환하고 새 후보에는 strict 지문
superset이 필요합니다.

구체화는 reviewing principal로 `CreateScheduledTaskCommand`를 호출하며 스케줄러 저장소를
직접 쓰지 않습니다. 고정된 작업 ID가 재시도 멱등성을 제공하고 conflicting 내용은 실패합니다.
결과 작업은 기존 trust/risk 경로로 shadow-only 이벤트를 보냅니다.

구성 검토 캠페인도 같은 경로를 사용합니다. Exact cited 실행 세 개는 실행별 지문과
zero 변경 도구를 가진 비활성화된, shadow-only 후보를 제출합니다. 별도 Approver 또는 Owner가
수용한 뒤에만 reviewing principal이 strict weekly 작업을 materialize할 수 있습니다. 표류 근거는
스케줄러 저장소를 직접 쓰지 않습니다.

## 텍스트 drafting

`AutomationBlueprintTextDrafter`는 2000-character 예산에서 `name`과 `prompt`만 반환합니다. 타입이 지정된
출력은 컨트롤 character와 빈/oversized 텍스트를 거부합니다. 범위, 도구, 예약, 격리,
전달, 자율성, risk는 결정론적 필드로 유지됩니다.

## 내구성, 만료, and 보존

이행 `20260720_0043`은 active-dedup 부분 unique 인덱스가 있는
`automation_blueprint_candidate`를 생성합니다. PostgreSQL은 권한 필드, 지문, 상태,
검토 사유, 작업 ID, realized 사용량 개수를 저장하며 상태 변경은 compare-and-swap입니다.

만료는 상태를 바꾸고 근거를 삭제하지 않습니다. 최종 행은 감사와 suppression을 위해
남고 출처 대화가 아니라 해시와 범위가 제한된 메타데이터만 포함합니다. 출처 턴은 별도
대화 보존을 따르며 배포는 집계 메트릭 보존 후 최종 행을 보관할 수 있습니다.

## 검토 surfaces and metrics

`GET /automation-blueprints`는 근거, 비용, 범위, 도구, 격리, 확신도, 만료, 상태를
읽기 전용 카드로 반환하며 검토/materialize 컨트롤이 없습니다. 별도 ChatOps 경로 factory가 injected
principal authorizer 뒤에서 수용/거부 및 materialize를 제공합니다.

메트릭은 proposed, accepted, rejected, 만료된, materialized, 후보 정밀도, acceptance 비율,
거절 사유, actual realized 사용량을 보고합니다. 사용량은 materialized 후보의 scheduled
occurrence가 관찰된 뒤에만 증가합니다.

## 실패 행동

- Below-threshold, mixed-scope, unstable, 해결되지 않은, authority-drift 그룹은 아무것도 만들지 않습니다.
- Scheduled 실행과 검토 대화는 suggestion으로 recurse하지 않습니다.
- 승인되지 않은 또는 self-review는 상태 변경 전에 실패합니다.
- 후보는 accepted 검토와 명시적 구체화 전에 작업을 만들지 않습니다.
- 중복 구체화는 기존 후보와 작업을 반환합니다.

## 검증

커버리지는 recurrence, dedup, 범위, 결과 stability, 스케줄러 veto, 재귀, 주입,
suppression/new 근거, 권한 확인, no-self-review, 만료, 텍스트 한계치, 멱등적
구체화, PostgreSQL codec/CAS, 검토 API, 콘솔 디코딩, metrics를 포함합니다.

## Related docs

| To learn about | 읽기 |
|----------------|------|
| 스케줄러 실행과 격리 | [프로세스 자동화](process-automation-ko.md) |
| Console 및 ChatOps 경계 | [Operator Console](../interfaces/operator-console-ko.md) |
| Post-turn 제안 충족 여부 | [Post-turn Improvement 검토](post-turn-improvement-review-ko.md) |
