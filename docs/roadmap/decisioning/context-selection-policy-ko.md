---
translation_of: context-selection-policy.md
translation_source_sha: e3a3b0f5f15d70aa361564693003180842deae61
translation_revised: 2026-08-14
---
# 컨텍스트 선택 정책

이 문서는 경계가 있는 working 맥락 선택을 둘러싼 정책 경계를 소유합니다. 기존 결정론적
작성기를 활성 기본값으로 유지하면서, 검토된 후보를 명시적인 근거 기반 승격 전에 shadow
모드에서 측정할 수 있게 합니다.

> **범위.** 정책은 미리 추정된 항목 id를 선택하고 매니페스트를 생성합니다. 대화 기록 지속성,
> summarization, 수집, 토큰 추정, 프롬프트 렌더링, 모델 호출, 답변 세대는 이 경계
> 밖에 유지됩니다.
>
> **기본값.** `deterministic-tiered-v1@1.0.0`은 불변이며 권위를 가집니다. 승격된 후보가
> 없으면 선택 항목과 `ContextManifest`는 이전 `compose_working_context` 동작과 byte-for-byte로
> 동일하게 유지됩니다.

## 설계 요약

`ContextSelectionInput`은 후보 항목, trust 등급, 토큰 예산, 모델 기능 메타데이터를
고정합니다. `ContextSelectionPolicy`는 정렬된 선택 항목 id와 `ContextManifest`만 반환할 수
있습니다. 필수 래퍼는 정확히 같은 입력으로 정책을 두 번 실행하고 모든 불변식을 검증한
뒤, 선택된 불변 항목을 재구성합니다. 어떤 정책도 저장소, retriever, summarizer, 렌더러,
모델 클라이언트, 도구 또는 실행기를 받지 않습니다.

## 구현 상태

### 구현 범위

| 영역 | 상태 | 근거 | 참고 |
|------|------|------|------|
| 결정론적 정책 계약, 계층형 어댑터, 불변식 래퍼 | implemented | `services/core-control-plane/src/fdai/core/working_context/`; `services/core-control-plane/tests/core/working_context/test_policy_validation.py`; `services/core-control-plane/tests/core/working_context/test_working_context.py` | 고정된 입력, 이중 실행, 매니페스트 검사, 고정 항목 검사, 실패 시 차단 동작에 focused test가 있습니다. |
| 정책 레지스트리 및 거버넌스 전환 | implemented | `services/core-control-plane/src/fdai/core/working_context/governance.py`; `services/core-control-plane/tests/core/working_context/test_policy_governance.py`; `services/core-control-plane/tests/core/capability_catalog/test_runtime.py` | 자동 승격 없이 설치, shadow 활성화, 명시적 승격, 강등, 비상 정지, 롤백, 개정 번호 compare-and-set이 구현되어 있습니다. |
| 범위가 제한된 shadow 평가, 비교 저장 어댑터, 승인된 고정본 재생 | implemented | `services/core-control-plane/src/fdai/core/working_context/shadow.py`; `services/core-control-plane/src/fdai/core/working_context/evidence.py`; `services/core-control-plane/src/fdai/core/working_context/replay.py`; `services/core-control-plane/tests/core/working_context/test_policy_shadow.py`; `services/core-control-plane/tests/core/working_context/test_evidence.py` | 구성 요소와 실패 격리가 focused test를 통과합니다. 이 상태는 운영 composition에 해당 요소가 연결되었다고 주장하지 않습니다. |
| 운영 shadow composition 및 영속 비교 저장 | implemented | `services/core-control-plane/src/fdai/composition/wire_context_selection.py`; `services/core-control-plane/src/fdai/composition/_helpers.py`; `services/core-control-plane/tests/composition/test_wire_context_selection.py` | `bind_context_selection_shadow`가 `StateStore` 비교 저장소를 직접 소유하는 실행기 하나를 연결하고, 번들 설치는 갱신된 권한으로 실행기를 다시 연결하며, 일반적인 turn assembly가 범위가 제한된 비교 한 건을 저장합니다. |
| Reader 비교 API 및 Console 화면 | implemented | `services/operator-service/src/fdai_operator_service/context_selection_projection.py`; `services/operator-service/src/fdai_operator_service/families/workflow/manifest.py`; `services/operator-service/tests/test_operator_workflow_family.py`; `console/src/routes/context-selection-comparisons.test.ts` | Reader 역할로 제한된 `GET /context-selection-comparisons` 경로가 범위가 제한된 영속 기록을 투영하고, 손상된 기록은 실패 시 차단되며, Console decoder가 권위 있는 페이로드를 수용합니다. |
| 범위가 제한된 비교 보관 | implemented | `services/core-control-plane/src/fdai/shared/providers/state_store.py`; `services/core-control-plane/src/fdai/core/working_context/evidence.py`; `services/core-control-plane/src/fdai/core/working_context/shadow.py`; `services/core-control-plane/tests/core/working_context/test_policy_shadow.py`; `services/core-control-plane/tests/persistence/test_state_store_retention.py` | `ContextShadowConfig.retain_evaluations`가 영속 비교 행을 제한합니다. 보관 정리는 각 shadow 배치 뒤 요청 밖에서 실행되며, 범위가 제한된 최신순 읽기가 반환하지 않는 행만 제거하고, 정리가 실패해도 방금 기록한 비교를 버리지 않습니다. `delete_states_beyond` 원시 연산은 키를 지정할 수 없고 빈 접두사를 거부하며 멱등이고 이웃 접두사를 건들지 않으므로, 권위 있는 기록이나 감사 항목을 지울 수 없습니다. |

### 구현 이력

| 날짜 | 상태 | 변경 | 근거 | 남은 작업 |
|------|------|------|------|-----------|
| 2026-08-13 | in-progress | 이전 출처를 재구성하지 않고 구현 ledger를 도입했습니다. focused test로 뒷받침되는 core 정책, 거버넌스, shadow, 저장 어댑터, 재생 구성 요소를 구현됨으로 기록하고, 누락된 운영 composition과 Operator API 제공을 분리했습니다. | `current change`; 범위 표에 나열된 소스 및 focused test; `uv run pytest -q --no-cov services/core-control-plane/tests/core/working_context services/core-control-plane/tests/core/capability_catalog/test_runtime.py services/core-control-plane/tests/core/conversation/test_context_bridge.py services/core-control-plane/tests/core/conversation/test_assemble_turn_context.py` (`70 passed`); `npm --prefix console test -- --run src/routes/context-selection-comparisons.test.ts` (`3 passed`) | `validated`를 주장하기 전에 영속적인 운영 shadow 평가를 연결하고 입증하며, Reader 역할로 제한된 비교 경로를 제공하고, 거버넌스가 적용된 런타임 근거를 수집합니다. |
| 2026-08-14 | implemented | `bind_context_selection_shadow` composition 경계와 짝을 이루는 `Container` 불변식을 추가하고, 기존 tracked-state 접두사 위에 Reader 역할로 제한된 Operator Service `GET /context-selection-comparisons` 투영을 추가했습니다. | `current change`; `wire_context_selection.py`, `context_selection_projection.py`, workflow route 매니페스트; focused check가 core composition 53건, Operator 34건, Console decoder 5건을 통과했고 작업 범위 Ruff와 strict mypy가 통과했습니다. | 범위 행을 `validated`로 올리기 전에 적격 shadow 평가 하나가 영속 저장과 Operator API 조회까지 이어짐을 추적하는 거버넌스 적용 런타임 근거를 기록합니다. |
| 2026-08-14 | implemented | 키를 지정할 수 없는 접두사 범위 `delete_states_beyond` 원시 연산으로 영속 비교 보관을 제한해, shadow 평가를 tracked-state 무한 증가 없이 켜 둘 수 있게 했습니다. | `current change`; `state_store.py`, `testing/state_store.py`, `persistence/postgres.py`, `evidence.py`, `shadow.py`, `test_policy_shadow.py`; 집중 working-context, composition, provider 검사 187건이 통과했고 strict mypy가 소스 1421개를 통과했습니다. | 범위 행을 `validated`로 올리기 전에 적격 shadow 평가 하나가 영속 저장과 Operator API 조회까지 이어짐을 추적하는 거버넌스 적용 런타임 근거를 기록합니다. |

### 남은 작업

- [x] `bind_context_selection_shadow`로 범위가 제한된 운영 shadow 평가를 구성했고, 일반적인
   turn assembly가 범위가 제한된 후보 평가를 예약하고 `StateStore`를 통해 비교를 저장함을
   통합 테스트로 입증했습니다.
- [x] Reader 역할로 제한된 Operator Service `GET /context-selection-comparisons` 경로를 workflow
   route family 매니페스트에 등록했고, 권위 있는 응답을 대상으로 API 통합 테스트와 Console
   decoder 테스트를 통과했습니다.
- [ ] 범위 행을 `validated`로 변경하기 전에 적격 shadow 평가 하나가 영속 저장과 Operator API
   조회까지 이어짐을 추적하는 거버넌스 적용 런타임 근거를 기록합니다.
- [x] `ContextShadowConfig.retain_evaluations`가 영속 비교 행을 제한합니다. 보관 정리는 각 shadow
   배치 뒤 요청 밖에서 실행되어 읽힐 수 있는 최신 행만 정확히 남기며, 정리가 실패해도 방금
   기록한 비교를 버리지 않습니다.

## 계약 경계

Core 계약은 `services/core-control-plane/src/fdai/core/working_context/`에 있습니다:

| 타입 | 책임 |
|------|------|
| `ContextSelectionInput` | 불변의 사전 추정 항목, trust 등급, 예산, 모델 메타데이터 |
| `ContextSelectionOutput` | 정렬된 선택 id와 기존 매니페스트 |
| `ContextSelectionPolicy` | 순수 `select(input) -> output` 프로토콜 |
| `DeterministicTieredPolicy` | 기존 tiered 작성기 어댑터 |
| `execute_context_selection_policy` | 필수 결정론적 재생 및 불변식 래퍼 |

호출자가 계속 모든 I/O를 소유합니다. `assemble_turn_context`는 기존 수집 및
operator-memory 경계로 항목을 준비하고 하나의 입력을 고정하며, 권위 있는 선택을
얻은 뒤 활성 결과가 완료된 후 후보 평가를 예약할 수 있습니다.

## 필수 불변식

모든 활성 또는 shadow 결과는 같은 검증기를 통과합니다. 검증기는 다음을 거부합니다:

- 누락, 불완전 또는 순서가 바뀐 pinned 제약;
- invented id, 중복 선택 id 또는 여러 매니페스트 계층에 할당된 id;
- 선택 항목과 맞지 않거나 `history_budget`을 넘는 토큰 합계;
- trust-class 불일치 또는 pinned/계층 순서를 위반하는 프롬프트 순서;
- 불완전한 omission 메타데이터 또는 정확히 하나의 불변 입력 항목으로 해석되지 않는 id;
- 같은 고정된 입력의 두 번째 실행에서 달라진 출력;
- 모든 정책 exception.

불변식 오류는 현재 요청을 실패 시 차단합니다. 승격된 후보가 원인이면 정책 권한이 해당
정책의 kill 전환을 engage하고 이후 요청을 위해 명시된 롤백 대상을 복원합니다. 실패
출력은 프롬프트 렌더링이나 모델에 절대 도달하지 않습니다.

## 레지스트리 및 승격

정책 신원은 불변 쌍 `(policy_id, version)`입니다. `CapabilityRuntime`은
`context_selection_policy` 참조 연결을 가지므로 기존 기능 레지스트리가 installation
권한으로 유지됩니다. 정확한 정책 참조만 등록하며 Python을 부하하거나 패키지를 download하거나
도구 또는 실행 기능을 부여하지 않습니다.

`ContextSelectionPolicyAuthority`는 프로세스 잠금 아래 개정 번호 compare-and-set을 적용합니다:

1. **비활성화된 설치.** 정확한 기능 연결과 정책 참조가 이미 활성여야 합니다.
2. **Shadow 활성화.** 후보는 측정 가능해지지만 활성 출력에는 영향을 줄 수 없습니다.
3. **명시적 승격.** 승격은 정확한 후보 버전, 하나 이상의 샘플과 불변식 실패 0을
   가진 timezone-aware 근거 구간, 그리고 현재 활성 정책을 롤백 대상으로 지정합니다.
4. **Demote 또는 kill.** 검토된 회귀는 demote할 수 있습니다. 불변식 위반은 정책별 kill
   전환을 자동 engage하고 롤백합니다. stale 개정 번호는 갱신 race에서 패배합니다.

권한은 자동 승격하지 않습니다. 또한 도구, 역할, ActionType, 작업 흐름, 모델 권한 또는
실행기 신원을 넓힐 수 없습니다.

## Shadow 평가 및 근거

`ContextSelectionShadowRunner`는 제한된 수의 후보를 `asyncio.to_thread`와 후보별 시간 초과로
실행합니다. 예약은 비동기 조립 경계에서 즉시 반환됩니다. 실행기는 기준선과 같은
`ContextSelectionInput` 객체를 사용하며 후보 결과를 활성 프롬프트 경로에 교체, 변경 또는 반환하지
않습니다.

각 영속 비교는 다음을 기록합니다:

- 기준선/후보 정책 참조, 매니페스트 및 토큰 사용량;
- 입력 지문, 선택 id overlap, omission 및 pinned preservation;
- 선택 관련성 평균과 선택적인 answer-quality evaluation 연결;
- 측정 지연 시간과 정확한 exception, 시간 초과 또는 불변식 실패 사유.

운영 어댑터는 기존 `StateStore` tracked-state 접두사 아래에 이 기록을 저장합니다. PostgreSQL
내구성과 atomic 생성 의미 규칙을 재사용하므로 새 표이나 Alembic 이행이 필요하지
않습니다. 동시 확산, pending 실행, 시간 초과는 모두 제한됩니다.

`bind_context_selection_shadow`는 실행기를 연결하는 composition 경계입니다. 실행기가 영속 저장소를
직접 소유하므로, 기록할 곳 없이 평가만 예약하는 배포는 불가능합니다.
모든 capability 번들을 먼저 설치하십시오. 이후의 `install_capability_bundle`은 갱신된 정책 권한
위에 실행기를 다시 만들고 같은 저장소를 유지합니다.

비교 행은 추가 전용이므로 트래픽이 많은 대화 화면에서 경계를 켜면 turn당 후보마다 한 행씩
늘어납니다. 보관 정책이 그 증가를 제한합니다. 각 shadow 배치 뒤에 실행기가
`ContextShadowConfig.retain_evaluations`(기본 500행)를 넘는 행을 정리하므로, 측정 기간만
켜 두는 대신 계속 켜 둘 수 있습니다. 보관 정리는 범위가 제한된 최신순 읽기가 어찌해도
반환하지 않는 행만 제거하며, 키를 지정할 수 없으므로 권위 있는 기록이나 감사 항목을
지울 수 없습니다.

## 재생 및 콘솔

`replay_approved_context_fixtures`는 approved 표시된 고정본만 실행하고 전체 ordered 출력과
매니페스트를 비교합니다. 재생은 실제 운영 선택과 같은 double-execution 불변식 검증을
수행하므로 unreplayable 정책은 offline 근거를 통과할 수 없습니다.

Console 경로 `GET /context-selection-comparisons`는 Reader-gated `ReadPanel`입니다. 토큰 사용량,
overlap, omission, pinned preservation, 지연 시간, 정확한 실패를 표시합니다. SPA에는 install,
활성화, promote, demote, 롤백 또는 비상 정지 컨트롤이 없습니다. 거버넌스 전이는
계속 서버 측에 있고 소유 명령 경로를 통해 감사됩니다.

Operator Service는 workflow route family에서 이 화면을 제공합니다. tracked-state 접두사 아래의
최신 기록을 범위를 제한해 읽고, 표시용 필드 11개만 투영하며, 항상 `read_only`와
`mutation_controls: false`를 선언하므로 브라우저는 거버넌스 컨트롤을 암시하는 응답을 거부할 수
있습니다. 결과가 비어 있는 것은 사용 불가가 아니라 권위 있는 답이며, 손상된 영속 기록은 부분
화면 대신 HTTP 503으로 차단됩니다.

## 실패 자세

- 누락되거나 잘못된 정책 출력은 프롬프트 렌더링 전에 실패 시 차단합니다.
- 후보 exception 또는 시간 초과는 근거일 뿐 활성 선택을 바꾸지 않습니다.
- 레지스트리 갱신 race는 새 개정 번호를 요구하며 last-writer-wins를 지원하지 않습니다.
- Killed 정책은 별도로 구현된 검토된 복구 경로 없이는 shadow에 다시 진입할 수 없습니다.
- Built-in 결정론적 정책은 대체 경로 롤백 대상으로 유지됩니다. 이 정책이 불변식을
  위반하더라도 검증을 우회하지 않고 선택이 실패 시 차단합니다.

## 관련 문서

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| Working-context 계층과 프롬프트 계층 | [진화하는 시스템 프롬프트](prompt-composition-ko.md) |
| 대화 지속성 및 assembly | [오퍼레이터 콘솔](../interfaces/operator-console-ko.md) |
| 모듈 및 DI 경계 | [프로젝트 구조](../architecture/project-structure-ko.md) |
| Shadow 및 승격 안전 | [보안 및 ID](../architecture/security-and-identity-ko.md) |
