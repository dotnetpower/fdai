---
title: MSCP Operational Profile
translation_of: mscp-operational-profile.md
translation_source_sha: 7e5326c1a60a62bfd0c9254f23c22e6c6b9c2469
translation_revised: 2026-08-06
---
# MSCP Operational Profile

`mscp-operational-v1` 프로파일은
[Minimal Self-Consciousness Protocol(MSCP)](https://github.com/dotnetpower/mscp)에서 선택한
아이디어를 FDAI의 운영 안전 모델에 맞게 적용합니다. 출처 provenance를 유지하지만 FDAI가 모든
MSCP 레벨을 구현하거나 전체 MSCP conformance를 충족한다고 주장하지 않습니다.

> MSCP 원본 저장소는 이 구현과 독립적이며 변경되지 않습니다. FDAI는 검토한 원본 revision
> `b66401cb4d3b43ee8d66e6ce106c51defd4c6d3a`를 코드에 고정합니다.

> 이 프로파일은 실행 authority가 아닙니다. Trust router, quality gate, risk gate, 사람 승인,
> executor, rollback principal, promotion registry 및 audit store는 기존 ownership을 유지합니다.

## 한눈에 보는 설계

이 프로파일은 `src/fdai/core/mscp_profile/` 아래에 결정론적이고 I/O가 없는 policy primitive를
제공합니다. Caller는 이미 수집한 observation, limit 및 component digest를 제공합니다. 프로파일은
typed verification 또는 hold decision을 반환하며 provider 호출, resource 변경, audit entry 쓰기,
capability promotion 또는 rule 편집을 수행하지 않습니다.

Runtime identifier에는 의도적으로 MSCP 레벨을 넣지 않습니다. FDAI는 여러 레벨에서 선택한 개념을
결합하며, 각 module docstring과 아래 mapping에서 level별 설계 provenance를 유지합니다.

## 프로파일 계약

| 필드 | 값 | 의미 |
|------|----|------|
| Profile id | `mscp-operational-v1` | MSCP 레벨 label과 독립적인 versioned FDAI adaptation |
| Source repository | `https://github.com/dotnetpower/mscp` | 차용한 개념의 공개 원본 |
| Source revision | `b66401cb4d3b43ee8d66e6ce106c51defd4c6d3a` | 검토한 source snapshot |
| Full conformance | `false` | FDAI는 완전한 MSCP 구현 또는 인증을 주장하지 않음 |

Profile id는 structured evidence에서 `safety_profile`로 나타날 수 있습니다. FDAI action kind, event
topic, ontology type, API route, database table 및 product label은 MSCP 용어가 아니라 운영 domain
vocabulary를 계속 사용합니다.

## 차용한 메커니즘

| FDAI 메커니즘 | MSCP provenance | FDAI adaptation | v1 상태 |
|---------------|-----------------|-----------------|---------|
| Profile provenance | Cross-level protocol versioning | 불변 profile id, source revision 및 non-conformance 선언 | 구현됨 |
| Effect verification | Level 3 prediction gating | 예상 metric 범위를 독립적으로 관찰한 correlation 및 시간 제한 값과 비교 | Optional shadow runtime wiring 및 `ResponseOutcome` projection 구현됨 |
| Cycle guard | Level 3 meta-escalation, oscillation 및 cognitive budget | Caller가 소유한 cycle, 경과 시간, cost, rollback 또는 sign-change limit에 도달하면 hold | Pure policy 구현, runtime wiring 연기 |
| Runtime integrity | Level 3 identity continuity | 사전 hash된 runtime component의 canonical manifest 비교, persona 또는 mutable identity model 없음 | Pure policy 구현, runtime wiring 연기 |
| Decision context | Level 2 persistent world model | 새로운 system of record를 만들지 않고 authoritative ontology, incident, workflow 및 audit state를 projection | 계획됨 |

MSCP에 게시된 수치 임계값은 프로파일에 복사하지 않습니다. FDAI caller는 governed configuration
또는 ActionType contract로 limit을 제공하고 promotion evidence에 사용하는 동일한 frozen scenario
set에서 검증합니다.

## Authority 경계

| Decision 또는 side effect | Authoritative FDAI owner | Profile 역할 |
|---------------------------|--------------------------|--------------|
| Context 및 state 획득 | Ontology, incident, workflow, audit 및 provider owner | Immutable projection만 소비 |
| Prediction quality history | Assurance Twin 및 measurement | Typed comparison result 하나 생성 |
| Auto, 사람 승인, hold 또는 deny | Risk gate | Autonomy를 높일 authority 없음 |
| Resource mutation | Executor 및 Thor | 실행하지 않음 |
| 사람 승인 | 사람 승인 경로 및 Var | 승인하지 않음 |
| Recovery | Vidar 및 rollback adapter | Mismatch 또는 hold를 보고하고 직접 rollback하지 않음 |
| Promotion 및 demotion | Promotion registry 및 measurement runner | Profile 존재가 capability를 promote하지 않음 |
| Audit durability | Audit store 및 Saga | Optional provenance field만 제공 |
| Rule 또는 policy 변경 | Norns-to-Mimir governed candidate path | Accepted policy를 직접 update하지 않음 |

예상하지 못한 input, stale observation, 맞지 않는 correlation, 소진된 budget, oscillation 및 runtime
drift는 모두 hold 형태의 result를 반환합니다. Caller는 autonomy를 shadow mode로 낮추거나 사람
승인으로 route할 수 있습니다. Profile result를 risk gate를 우회하는 permission으로 해석할 수
없습니다.

## 활성화 및 runtime 동작

MSCP effect observation은 기본적으로 비활성 상태입니다.
`Container.mscp_expected_effect_provider`와 `Container.mscp_effect_observer`는 모두 `None`이
기본값이며, binding하지 않은 ControlLoop는 추가 호출이나 audit write를 수행하지 않습니다.
Composition root는 두 collaborator를 모두 넣은 새 immutable container를 만들어 shadow
observation을 활성화합니다.

```python
container = dataclasses.replace(
	container,
	mscp_expected_effect_provider=expected_effect_provider,
	mscp_effect_observer=independent_effect_observer,
)
```

일부만 binding하면 container 생성 시점과 ControlLoop 직접 생성 시점에 모두 실패합니다. Headless
runtime builder는 완전한 pair를 ControlLoop로 전달합니다. 이후 loop는 모든 PR-native, direct-API,
tool-call dispatch에서 다음 순서를 유지합니다.

```text
expected-effect provider -> existing executor -> independent observer -> shadow audit
```

Observer는 executor receipt가 아니라 Action과 ExpectedEffect를 받습니다. 따라서 실행 component의
자체 성공 주장을 독립 evidence로 취급하지 않습니다. 각 deployment는 PR receipt projection,
tool-side post-condition 또는 authoritative substrate metric처럼 delivery path에 적합한 effect를
선택합니다.

Provider failure, 누락된 prediction 또는 observation, target mismatch, stale observation 및 value
mismatch는 `hold` 또는 `mismatch` shadow evidence를 생성합니다. Executor result, risk decision,
terminal ControlLoop outcome은 변경하지 않습니다. Shadow audit write failure도 log만 남기고 primary
result를 유지합니다.

같은 observation은 이제 strict `ResponseOutcome`을 `measurement.action_outcome.v1`로 기록합니다.
계약은 resource reference 대신 target digest를 저장하고 누락되거나 stale한 evidence를
`unscorable`로 표시하며 scheduled Dynamic challenger-learning pass가 소비하는 독립 watermark를
제공합니다. 이 추가 record는 계속 shadow evidence입니다. Effect model을 promote하거나 execution
authority를 변경할 수 없습니다.

두 durable audit record가 모두 기록된 뒤 선택적 composition-owned sink가 strict contract를 raw
ingress로 다시 publish합니다. Audit failure는 relay를 중단하므로 unaudited outcome이 learning에
진입할 수 없습니다. 이후 Huginn과 Muninn이 governed operating-pattern cohort path에 공급합니다.
Sink failure는 log에 남지만 executor result를 변경할 수 없습니다. 이 relay는 shadow outcome을
reusable로 만들지 않으며 cohort projector는 verified enforce outcome만 positive evidence로 수락합니다.

Shadow observation에서 gating으로 전환하는 작업은 별도의 향후 governed change입니다. Measured
evidence window, rollback target 및 profile이 기존 authority decision을 유지하거나 낮출 수만 있다는
증명이 필요합니다.

순수 `combine_mscp_authority` 함수는 이 never-raising proof surface를 제공합니다. `preserve`,
`human_approval`, `hold`, `deny` ceiling을 canonical FDAI authority ladder에 매핑하고 `min(existing
FDAI authority, MSCP ceiling)`을 적용합니다. Immutable result는 complete unified risk decision을
보존하고 profile, existing decision, ceiling, reason, final decision 및 authority 감소 여부가 포함된
audit projection을 추가합니다. 함수는 I/O를 수행하지 않으며 risk gate, human approval, executor,
rollback 또는 audit owner를 우회할 수 없습니다. Measured readiness window와 governed profile
lifecycle이 없는 동안에는 ControlLoop에 연결하지 않습니다.

## 독립적인 축

이 프로파일은 [ADR-0002](decisions/0002-independent-runtime-axes-ko.md)의 runtime axis와
독립적입니다. 실행 위치, deployment environment, evidence profile, action lifecycle, identity 및
distribution은 safety profile을 선택하거나 변경하지 않습니다. 특히 다음 계약을 적용합니다.

- Local 실행은 profile check를 비활성화하지 않습니다.
- Production은 profile result가 실행 가능함을 의미하지 않습니다.
- Fork는 profile id를 사용해 autonomy를 높이거나 framework integrity를 우회할 수 없습니다.
- Shadow 및 enforce는 MSCP state가 아니라 ActionType 및 Workflow lifecycle state입니다.

## 검증

`tests/core/mscp_profile/` 아래의 focused test는 다음 항목을 검증합니다.

- 레벨 비종속 profile identity 및 필수 non-conformance 선언
- 안정적이고 source가 고정된 audit provenance
- 예상 effect와 관찰 effect의 time, target, metric 및 correlation 검사
- Strict `ResponseOutcome` schema parity 및 privacy-minimized audit projection
- Default-off composition, pair-only activation 및 predict-execute-observe 순서
- Mismatch, provider failure 또는 shadow audit failure에서도 변경되지 않는 executor result
- 모든 finite-domain 조합에서 MSCP ceiling이 unified authority를 높이지 않는다는 증명
- Caller 소유 cycle budget 및 bounded sign-change detection
- 순서와 독립적인 runtime manifest hashing 및 component drift reporting
- non-finite value, malformed digest 및 invalid limit의 fail-closed validation

v1 profile은 optional shadow observation으로만 연결됩니다. Enforce decision path에는 연결되지
않았습니다. 향후 gating 변경은 어떤 profile outcome도 기존 risk decision을 높이지 않음을
입증하는 것이 좋습니다.

## 관련 문서

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| Control-loop 및 module boundary | [프로젝트 구조](project-structure-ko.md) |
| 안전 및 identity invariant | [보안과 아이덴티티](security-and-identity-ko.md) |
| Promotion evidence 및 guard metric | [목표와 메트릭](goals-and-metrics-ko.md) |
| 독립적인 runtime axis | [ADR-0002](decisions/0002-independent-runtime-axes-ko.md) |
