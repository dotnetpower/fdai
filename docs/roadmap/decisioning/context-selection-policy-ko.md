---
translation_of: context-selection-policy.md
translation_source_sha: 79546aaf3b865c9f621845ddcdf8e43edb30da82
translation_revised: 2026-08-11
---
# 컨텍스트 선택 정책

이 문서는 경계가 있는 working 맥락 선택을 둘러싼 정책 경계를 소유합니다. 기존 결정론적
작성기를 활성 기본값으로 유지하면서, 검토된 후보를 명시적인 근거 기반 승격 전에 그림자
모드에서 측정할 수 있게 합니다.

> **범위.** 정책은 미리 추정된 항목 id를 선택하고 매니페스트를 생성합니다. 대화 기록 지속성,
> summarization, 수집, 토큰 추정, 프롬프트 렌더링, 모델 호출, 답변 세대는 이 경계
> 밖에 유지됩니다.
>
> **기본값.** `deterministic-tiered-v1@1.0.0`은 불변이며 권위 있는합니다. 승격된 후보가
> 없으면 선택 항목과 `ContextManifest`는 이전 `compose_working_context` 동작과 byte-for-byte로
> 동일하게 유지됩니다.

## 설계 요약

`ContextSelectionInput`은 후보 항목, trust 등급, 토큰 예산, 모델 기능 메타데이터를
고정합니다. `ContextSelectionPolicy`는 정렬된 선택 항목 id와 `ContextManifest`만 반환할 수
있습니다. 필수 래퍼는 정확히 같은 입력으로 정책을 두 번 실행하고 모든 불변식을 검증한
뒤, 선택된 불변 항목을 재구성합니다. 어떤 정책도 저장소, retriever, summarizer, 렌더러,
모델 클라이언트, 도구 또는 실행기를 받지 않습니다.

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

모든 활성 또는 그림자 결과는 같은 검증기를 통과합니다. 검증기는 다음을 거부합니다:

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
2. **그림자 활성화.** 후보는 측정 가능해지지만 활성 출력에는 영향을 줄 수 없습니다.
3. **명시적 승격.** 승격은 정확한 후보 버전, 하나 이상의 샘플과 불변식 실패 0을
 가진 timezone-aware 근거 구간, 그리고 현재 활성 정책을 롤백 대상으로 지정합니다.
4. **Demote 또는 kill.** 검토된 회귀는 demote할 수 있습니다. 불변식 위반은 정책별 kill
 전환을 자동 engage하고 롤백합니다. stale 개정 번호는 갱신 race에서 패배합니다.

권한은 자동 승격하지 않습니다. 또한 도구, 역할, ActionType, 작업 흐름, 모델 권한 또는
실행기 신원을 넓힐 수 없습니다.

## 그림자 평가 및 근거

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

## 재생 및 콘솔

`replay_approved_context_fixtures`는 approved 표시된 고정본만 실행하고 전체 ordered 출력과
매니페스트를 비교합니다. 재생은 실제 운영 선택과 같은 double-execution 불변식 검증을
수행하므로 unreplayable 정책은 offline 근거를 통과할 수 없습니다.

Console 경로 `GET /context-selection-comparisons`는 Reader-gated `ReadPanel`입니다. 토큰 사용량,
overlap, omission, pinned preservation, 지연 시간, 정확한 실패를 표시합니다. SPA에는 install,
활성화, promote, demote, 롤백 또는 비상 정지 컨트롤이 없습니다. 거버넌스 전이는
계속 서버 측에 있고 소유 명령 경로를 통해 감사됩니다.

## 실패 자세

- 누락되거나 잘못된 정책 출력은 프롬프트 렌더링 전에 실패 시 차단합니다.
- 후보 exception 또는 시간 초과는 근거일 뿐 활성 선택을 바꾸지 않습니다.
- 레지스트리 갱신 race는 새 개정 번호를 요구하며 last-writer-wins를 지원하지 않습니다.
- Killed 정책은 별도로 구현된 검토된 복구 경로 없이는 그림자에 다시 진입할 수 없습니다.
- Built-in 결정론적 정책은 대체 경로 롤백 대상으로 유지됩니다. 이 정책이 불변식을
 위반하더라도 검증을 우회하지 않고 선택이 실패 시 차단합니다.

## 관련 문서

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| Working-context 계층과 프롬프트 계층 | [진화하는 시스템 프롬프트](prompt-composition-ko.md) |
| 대화 지속성 및 assembly | [오퍼레이터 콘솔](../interfaces/operator-console-ko.md) |
| 모듈 및 DI 경계 | [프로젝트 구조](../architecture/project-structure-ko.md) |
| 그림자 및 승격 안전 | [보안 및 ID](../architecture/security-and-identity-ko.md) |
