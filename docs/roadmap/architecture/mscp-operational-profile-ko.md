---
title: MSCP Operational Profile
translation_of: mscp-operational-profile.md
translation_source_sha: 56b6e291c656e30b1323fbf5c85094c4f2638873
translation_revised: 2026-08-11
---
# MSCP Operational 프로파일

`mscp-operational-v1` 프로파일은
[Minimal Self-Consciousness 프로토콜(MSCP)](https://github.com/dotnetpower/mscp)에서 선택한
아이디어를 FDAI의 운영 안전 모델에 맞게 적용합니다. 출처 출처 이력을 유지하지만 FDAI가 모든
MSCP 레벨을 구현하거나 전체 MSCP conformance를 충족한다고 주장하지 않습니다.

> MSCP 원본 저장소는 이 구현과 독립적이며 변경되지 않습니다. FDAI는 검토한 원본 개정 번호
> `b66401cb4d3b43ee8d66e6ce106c51defd4c6d3a`를 코드에 고정합니다.

> 이 프로파일은 실행 권한이 아닙니다. Trust 라우터, quality 게이트, risk 게이트, 사람 승인,
> 실행기, 롤백 principal, 승격 레지스트리 및 감사 저장소는 기존 소유권을 유지합니다.

## 한눈에 보는 설계

이 프로파일은 `services/core-control-plane/src/fdai/core/mscp_profile/` 아래에 결정론적이고 I/O가 없는 정책 기본 요소를
제공합니다. 호출자는 이미 수집한 관측, 한도 및 컴포넌트 다이제스트를 제공합니다. 프로파일은
타입이 지정된 검증 또는 보류 결정을 반환하며 프로바이더 호출, 리소스 변경, 감사 항목 쓰기,
기능 승격 또는 룰 편집을 수행하지 않습니다.

런타임 식별자에는 의도적으로 MSCP 레벨을 넣지 않습니다. FDAI는 여러 레벨에서 선택한 개념을
결합하며, 각 모듈 docstring과 아래 대응에서 수준별 설계 출처 이력을 유지합니다.

## 프로파일 계약

| 필드 | 값 | 의미 |
|------|----|------|
| 프로파일 id | `mscp-operational-v1` | MSCP 레벨 라벨과 독립적인 versioned FDAI adaptation |
| 출처 저장소 | `https://github.com/dotnetpower/mscp` | 차용한 개념의 공개 원본 |
| 출처 개정 번호 | `b66401cb4d3b43ee8d66e6ce106c51defd4c6d3a` | 검토한 출처 스냅샷 |
| Full conformance | `false` | FDAI는 완전한 MSCP 구현 또는 인증을 주장하지 않음 |

프로파일 id는 구조화된 근거에서 `safety_profile`로 나타날 수 있습니다. FDAI 액션 종류, 이벤트
토픽, 온톨로지 타입, API 경로, 데이터베이스 표 및 product 라벨은 MSCP 용어가 아니라 운영 도메인
vocabulary를 계속 사용합니다.

## 차용한 메커니즘

| FDAI 메커니즘 | MSCP 출처 이력 | FDAI adaptation | v1 상태 |
|---------------|-----------------|-----------------|---------|
| 프로파일 출처 이력 | Cross-level 프로토콜 versioning | 불변 프로파일 id, 출처 개정 번호 및 non-conformance 선언 | 구현됨 |
| 효과 검증 | 수준 3 prediction gating | 예상 메트릭 범위를 독립적으로 관찰한 상관관계 및 시간 제한 값과 비교 | 선택적 shadow 런타임 배선 및 `ResponseOutcome` 변환 결과 구현됨 |
| Cycle 가드 | 수준 3 meta-escalation, oscillation 및 cognitive 예산 | 호출자가 소유한 cycle, 경과 시간, 비용, 롤백 또는 sign-change 한도에 도달하면 보류 | Pure 정책 구현, 런타임 배선 연기 |
| 런타임 무결성 | 수준 3 신원 continuity | 사전 해시된 런타임 컴포넌트의 정본 매니페스트 비교, persona 또는 변경 가능한 신원 모델 없음 | Pure 정책 구현, 런타임 배선 연기 |
| 결정 맥락 | 수준 2 persistent 세계 모델 | 새로운 system of 기록을 만들지 않고 권위 있는 온톨로지, 인시던트, 작업 흐름 및 감사 상태를 변환 결과 | 계획됨 |

MSCP에 게시된 수치 임계값은 프로파일에 복사하지 않습니다. FDAI 호출자는 통제된 구성
또는 ActionType 계약으로 한도를 제공하고 승격 근거에 사용하는 동일한 고정된 시나리오
집합에서 검증합니다.

## 권한 경계

| 결정 또는 side 효과 | 권위 있는 FDAI 소유자 | 프로파일 역할 |
|---------------------------|--------------------------|--------------|
| 맥락 및 상태 획득 | 온톨로지, 인시던트, 작업 흐름, 감사 및 프로바이더 소유자 | 변경할 수 없는 변환 결과만 소비 |
| Prediction quality 이력 | Assurance Twin 및 측정 | 타입이 지정된 비교 결과 하나 생성 |
| Auto, 사람 승인, 보류 또는 거부 | Risk 게이트 | 자율성을 높일 권한 없음 |
| Resource 변경 | 실행기 및 Thor | 실행하지 않음 |
| 사람 승인 | 사람 승인 경로 및 Var | 승인하지 않음 |
| 복구 | Vidar 및 롤백 어댑터 | Mismatch 또는 보류를 보고하고 직접 롤백하지 않음 |
| 승격 및 demotion | 승격 레지스트리 및 측정 실행기 | 프로파일 존재가 기능을 promote하지 않음 |
| 감사 내구성 | 감사 저장소 및 Saga | 선택적 출처 이력 필드만 제공 |
| Rule 또는 정책 변경 | Norns-to-Mimir 통제된 후보 경로 | Accepted 정책을 직접 갱신하지 않음 |

예상하지 못한 입력, stale 관측, 맞지 않는 상관관계, 소진된 예산, oscillation 및 런타임
표류는 모두 보류 형태의 결과를 반환합니다. 호출자는 자율성을 shadow 모드로 낮추거나 사람
승인으로 경로할 수 있습니다. 프로파일 결과를 risk 게이트를 우회하는 권한으로 해석할 수
없습니다.

## 활성화 및 런타임 동작

MSCP 효과 관측은 기본적으로 비활성 상태입니다.
`Container.mscp_expected_effect_provider`와 `Container.mscp_effect_observer`는 모두 `None`이
기본값이며, 연결하지 않은 ControlLoop는 추가 호출이나 감사 쓰기를 수행하지 않습니다.
조립 루트는 두 collaborator를 모두 넣은 새 변경할 수 없는 컨테이너를 만들어 shadow
관측을 활성화합니다.

```python
container = dataclasses.replace(
	container,
	mscp_expected_effect_provider=expected_effect_provider,
	mscp_effect_observer=independent_effect_observer,
)
```

일부만 연결하면 컨테이너 생성 시점과 ControlLoop 직접 생성 시점에 모두 실패합니다. Headless
런타임 빌더는 완전한 쌍을 ControlLoop로 전달합니다. 이후 루프는 모든 PR-native, direct-API,
tool-call 전달에서 다음 순서를 유지합니다.

```text
expected-effect provider -> existing executor -> independent observer -> shadow audit
```

Observer는 실행기 증적이 아니라 액션과 ExpectedEffect를 받습니다. 따라서 실행 컴포넌트의
자체 성공 주장을 독립 근거로 취급하지 않습니다. 각 배포는 PR 증적 변환 결과,
tool-side post-condition 또는 권위 있는 기반 메트릭처럼 전달 경로에 적합한 효과를
선택합니다.

프로바이더 실패, 누락된 prediction 또는 관측, 대상 mismatch, stale 관측 및 값
mismatch는 `hold` 또는 `mismatch` shadow 근거를 생성합니다. 실행기 결과, risk 결정,
최종 ControlLoop 결과는 변경하지 않습니다. shadow 감사 쓰기 실패도 로그만 남기고 기본
결과를 유지합니다.

같은 관측은 이제 strict `ResponseOutcome`을 `measurement.action_outcome.v1`로 기록합니다.
계약은 리소스 참조 대신 대상 다이제스트를 저장하고 누락되거나 stale한 근거를
`unscorable`로 표시하며 scheduled Dynamic challenger-learning 통과가 소비하는 독립 watermark를
제공합니다. 이 추가 기록은 계속 shadow 근거입니다. 효과 모델을 promote하거나 실행
권한을 변경할 수 없습니다.

두 영속 감사 기록이 모두 기록된 뒤 선택적 composition-owned 싱크가 strict 계약을 raw
유입으로 다시 publish합니다. 감사 실패는 중계를 중단하므로 unaudited 결과가 learning에
진입할 수 없습니다. 이후 Huginn과 Muninn이 통제된 operating-pattern 집단 경로에 공급합니다.
싱크 실패는 로그에 남지만 실행기 결과를 변경할 수 없습니다. 이 중계는 shadow 결과를
reusable로 만들지 않으며 집단 projector는 검증된 강제 적용 결과만 긍정 근거로 수락합니다.

shadow 관측에서 gating으로 전환하는 작업은 별도의 향후 통제된 변경입니다. Measured
근거 구간, 롤백 대상 및 프로파일이 기존 권한 결정을 유지하거나 낮출 수만 있다는
증명이 필요합니다.

순수 `combine_mscp_authority` 함수는 이 never-raising 증명 표면을 제공합니다. `preserve`,
`human_approval`, `hold`, `deny` 상한을 정본 FDAI 권한 단계 구조에 매핑하고 `min(기존
FDAI 권한, MSCP 상한)`을 적용합니다. 변경할 수 없는 결과는 완전한 unified risk 결정을
보존하고 프로파일, 기존 결정, 상한, 사유, 최종 결정 및 권한 감소 여부가 포함된
감사 변환 결과를 추가합니다. 함수는 I/O를 수행하지 않으며 risk 게이트, human 승인, 실행기,
롤백 또는 감사 소유자를 우회할 수 없습니다. Measured 준비 상태 구간과 통제된 프로파일
수명 주기가 없는 동안에는 ControlLoop에 연결하지 않습니다.

## 독립적인 축

이 프로파일은 [ADR-0002](decisions/0002-independent-runtime-axes-ko.md)의 런타임 축과
독립적입니다. 실행 위치, 배포 환경, 근거 프로파일, 액션 수명 주기, 신원 및
분포는 안전성 프로파일을 선택하거나 변경하지 않습니다. 특히 다음 계약을 적용합니다.

- 로컬 실행은 프로파일 검사를 비활성화하지 않습니다.
- 운영은 프로파일 결과가 실행 가능함을 의미하지 않습니다.
- 포크는 프로파일 id를 사용해 자율성을 높이거나 framework 무결성을 우회할 수 없습니다.
- shadow 및 강제 적용은 MSCP 상태가 아니라 ActionType 및 작업 흐름 수명 주기 상태입니다.

## 검증

`services/core-control-plane/tests/core/mscp_profile/` 아래의 focused 테스트는 다음 항목을 검증합니다.

- 레벨 비종속 프로파일 신원 및 필수 non-conformance 선언
- 안정적이고 출처가 고정된 감사 출처 이력
- 예상 효과와 관찰 효과의 시간, 대상, 메트릭 및 상관관계 검사
- Strict `ResponseOutcome` 스키마 동등성 및 privacy-minimized 감사 변환 결과
- Default-off 조립, pair-only activation 및 predict-execute-observe 순서
- Mismatch, 프로바이더 실패 또는 shadow 감사 실패에서도 변경되지 않는 실행기 결과
- 모든 finite-domain 조합에서 MSCP 상한이 unified 권한을 높이지 않는다는 증명
- 호출자 소유 cycle 예산 및 범위가 제한된 sign-change detection
- 순서와 독립적인 런타임 매니페스트 hashing 및 컴포넌트 표류 reporting
- non-finite 값, malformed 다이제스트 및 잘못된 한도의 실패 시 차단 검증

v1 프로파일은 선택적 shadow 관측으로만 연결됩니다. 강제 적용 결정 경로에는 연결되지
않았습니다. 향후 gating 변경은 어떤 프로파일 결과도 기존 risk 결정을 높이지 않음을
입증하는 것이 좋습니다.

## 관련 문서

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| Control-loop 및 모듈 경계 | [프로젝트 구조](project-structure-ko.md) |
| 안전 및 신원 불변식 | [보안과 아이덴티티](security-and-identity-ko.md) |
| 승격 근거 및 가드 메트릭 | [목표와 메트릭](goals-and-metrics-ko.md) |
| 독립적인 런타임 축 | [ADR-0002](decisions/0002-independent-runtime-axes-ko.md) |
