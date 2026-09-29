---
title: 자율 규칙 발견(Autonomous Rule Discovery)
translation_of: rule-catalog-autonomous-discovery.md
translation_source_sha: 381f4fbac70a93fad690d9f7dfae634486535511
translation_revised: 2026-09-29
---

# 자율 규칙 발견(자율 Rule 발견)

이 문서는 상류 및 운영 신호에서 규칙 후보를 제안, 검증, 통합하는 카탈로그 발견 루프를 다룹니다.
수집 소스와 정규화는 [규칙 카탈로그 수집](rule-catalog-collection-ko.md)에서 계속 설명합니다.

## 설계 개요

수집은 "상류 소스 읽기" 뿐이 아님. 카탈로그는 **운영 신호** 에서도 성장하고 self-correct,
그래서 결정론 레이어가 사람이 모든 규칙을 손으로 만들지 않고 환경에 발맞춤. 이것은
[architecture.instructions.md](../../../.github/instructions/architecture.instructions.md) 의
"Living 룰" 원칙.

## 루프

Long-horizon 루프가 무한 반복; 모든 사이클이 같은 공유 세계 모델(정규화된 카탈로그, 감사 로그,
인시던트 라이브러리, 출처 이력 저장소) 을 유지 - 사이클이 처음부터 재시작하지 않고 서로 위에
빌드:

```text
sources + operational signals ─► observe ─► hypothesize ─► verify ─► integrate
                                                            (quality gate)
```

- **observe** - 루프는 하나씩이 아니라 세 피드를 나란히 읽음:
  1. **상류 소스** 위 컬렉터 파이프라인 경유(새/변경 컨트롤).
  2. **운영 신호** - 최근 감사 로그 엔트리, HIL 승인 패턴, shadow-mode 결과, 롤백, **재정의
     이벤트** ([rule-governance-ko.md](rule-governance-ko.md)).
  3. **현재 카탈로그** - 기존 규칙, 출처 이력, 측정된 정확도.
- **hypothesize** - 추론 스테이지(LLM 스테이지, 어떤 T2 출력처럼 취급) 가 세 형상의 **후보**
  엔트리 제안:
  - **new-rule**: 아직 커버되지 않은 컨트롤, 반복되는 인시던트/HIL 패턴 또는 새로 발행된 상류
    컨트롤에 의해 동기.
  - **개정 번호**: 상류 소스가 바뀌었거나(그 `content_hash` 가 이동) shadow 정확도가 임계
    아래로 표류한 기존 규칙.
  - **retirement**: 반복적으로 재정의되거나 shadow 결과가 실제 환경에 poor fit임을 보이는
    기존 규칙.
- **verify** - 모든 후보는 표준 **quality 게이트** 통과할 때까지 inert 데이터:
  1. 엄격 JSON 스키마 (`additionalProperties: false`);
  2. 출처 이력 검사 - `source_url`, `resolved_ref`, `content_hash`, `license`,
     `redistribution` 모두 존재하고 검증 가능 (근거에 기반한 출처 이력 없는 후보는 즉시 거부);
  3. **Mixed-model 교차 검사** - 두 번째 모델(다른 패밀리/벤더) 이 같은 후보를 재도출하거나 재
     승인; 불일치는 HIL로 escalate, 절대 auto-resolve 아님
     ([architecture.instructions.md](../../../.github/instructions/architecture.instructions.md));
  4. 결정론 검증기 - Rego 파싱, 중복 `id` 없음, 더 엄격한 컨트롤을 조용히 약화시킬 기존 규칙과
     충돌 없음;
  5. 회귀 스위트 - 기존 픽스처가 여전히 통과;
  6. Shadow-mode dwell - 후보가 설정된 최소 기간과 표본 크기 동안 실제 트래픽에 judge-and-log-only
     실행, 임계 위 정확도와 정책 위반 escape 0.
- **integrate** - 게이트 통과한 후보는 [rule-governance-ko.md](rule-governance-ko.md) 의 할당/
  효과 라이프사이클에 따라 승격(new-rule/개정 번호는 먼저 감사 효과로 랜딩; retirement는
  tombstone으로 랜딩). 카탈로그는 오직 머지된 catalog-as-code PR로만 변형, 절대 루프에 의해
  직접 아님.

## 후보 요건 (MUST)

- 모든 후보는 **근거에 기반한 출처 이력** 인용해야 함 - 상류 문서 URL + resolved 개정 번호/해시,
  또는 특정 인시던트/HIL/재정의 이벤트 id, 또는 특정 취약성/권고 id. "모델이 그것을 생각했음"
  은 출처 이력이 아님.
- 모든 후보는 CSP-중립 `resource_type` 어휘 대상, 절대 벤더 경로 아님.
- Reference-only 소스 텍스트는 후보에 붙여넣기되어선 안 됨;
  [Licensing](rule-catalog-collection-ko.md#라이선싱-소스-추가-전-읽기) 규칙에 따라 authored
  `check_logic` + 인용만.
- 어떤 게이트 스텝을 실패하는 후보는 **abstain** 이 됨 - 사유와 함께 로그되어 다음 사이클이
  revisit할 수 있지만, 절대 부분적으로 적용되지 않음.

## 재정의 피드백

재정의는 루프의 일급 입력, dead-end 아님. 규칙이 스코프에 걸쳐 수명이 긴 또는 반복
재정의를 누적할 때, observe 스테이지가 플래그하고 hypothesize 스테이지가 **개정 번호** (재정의
가 불필요하도록 규칙 좁힘) 또는 **retirement** (규칙이 체계적으로 poor fit) 제안. 어느 쪽이든
제안은 여전히 전체 quality 게이트 통과. 재정의는 카탈로그를 직접 변형하지 않음 - 신호만 공급.

## 안전과 신뢰

- 루프는 **후보 생성기** , 실행기 아님. 라이브 카탈로그를 변형할 수 없고, 할당을 강제 적용으로
  flip할 수 없으며, [rule-governance-ko.md](rule-governance-ko.md) 의 승격 승인을 우회할 수
  없음.
- 이 루프의 어떤 LLM 스테이지도 T2 호출이며
  [architecture.instructions.md](../../../.github/instructions/architecture.instructions.md) 의
  T2 quality 게이트(mixed-model, 검증기, grounding, abstain-when-unsupported) 준수.
- 루프 자체의 처리량(사이클당 후보, 게이트 통과율, override-트리거된 제안률, retirement률) 은
  계측되고 [goals-and-metrics-ko.md](../architecture/goals-and-metrics-ko.md) 에 보고 - 측정 가능, assert
  아님.

## 후보 가드 (업스트림 구현)

`fdai.agents._framework.candidate_guard.CandidateGuard` 는 Mimir 가 모든 `RuleCandidate` 를 pending
목록에 넣기 전에 실행하는 결정론적 게이트다 - 위의 후보 Requirements 강제 지점이자
발견 루프의 poisoning 방어다. 아무것도 promote 하지 않으며(그건 quality 게이트 소관),
**수용** 대 **격리 구역** 을 결정하고 이유를 기록해, 거부된 후보를 조용히 버리지 않고
감사 용으로 보존한다. 검사는 순수하다(I/O 없음, 모델 호출 없음):

- **출처 이력** - `proposed_by` 와 알려진 `proposal_kind`
  (`new` / `new-scenario` / `revision` / `retirement` / `threshold_adjustment`) 가 필수.
- **Grounding** - 비어있지 않은 `evidence` 매핑이 필수; 근거 없는 후보는 격리 구역 된다
  ("모델이 그렇게 생각했다"는 근거 가 아니다).
- **범위 sanity** - 수치 근거 는 범위 안이어야 한다(`rollback_rate` 가 `[0, 1]` 밖이거나
  개수 가 비양수면 손상되거나 위조된 신호다).
- **Flood 감지** - 동일 후보 지문 가 반복 상한을 넘으면 poisoning flood 의심으로
  격리 구역 된다(Norns 가 정당한 제안은 이미 dedup 하므로 반복 burst 는 이상이다).

## Shadow dwell 근거(상류 구현)

`fdai.core.operational_learning.shadow_dwell` 은 품질 게이트 6단계의 결정론적 부분이다.
후보 대상별로 judge-and-log-only 관측을 보존하고, 이를 스스로 검증하는
`ShadowDwellEvidence` 레코드(관측 구간, 표본 수, 검토 및 동의 건수, 정책 위반 탈출 건수)로
집계한 뒤, 그 레코드가 설정된 `ShadowDwellThresholds` 를 충족하는지 판정한다. 아무것도
promote 하지 않고 카탈로그도 건드리지 않는다.

이것을 형식이 아니라 게이트로 만드는 성질은 세 가지다:

- **근거 부재는 동의가 아니다.** dwell 레코드가 없는 후보는 부적격이다. 누락으로 통과할 수 없다.
- **근거는 스스로를 검증한다.** 레코드는 Norns 에서 Mimir 로 이벤트에 실려 오므로, 서로
  모순되는 개수, 뒤집힌 구간, timezone 없는 시각은 신뢰하지 않고 즉시 거부한다. 다른 대상을
  가리키는 레코드는 이 후보를 보증할 수 없다.
- **탈출 허용치는 설정 항목이 아니다.** 설계가 0건이라고 정했고, 조정 가능한 탈출 예산은
  납기 압박에서 가장 먼저 돌려지는 손잡이다.

Norns 는 shadow 감사 결과를 버리는 대신 dwell 관측으로 보존하되, shadow 결과가 실제
rollback 비율 학습기에 섞이지 않도록 유지하고, 산출된 근거를 자신이 게시하는 후보에
첨부한다. Mimir 는 그 이벤트 근거에서 판정을 다시 유도한다. `Mimir.promotion_ready_candidates()`
는 dwell 을 입증하지 못한 후보를 제외하고, `Mimir.promote()` 는 대기 중인 발견 루프 후보가
임계 미달인 규칙의 승격을 거부한다. 적격은 여전히 승격이 아니다. 카탈로그는 머지된
catalog-as-code PR 로만 바뀐다.

## 범위가 제한된 주기 런타임(상류 구현)

`fdai.core.operational_learning.discovery_cycle` 은 한 번에 하나의 시간 구간 주기를 실행합니다.
기계적 스케줄러는 `StateStore` 에서 안정적인 주기 ID를 선점하고, 각 단계를 리비전
비교 후 설정 방식으로 보존합니다. 이미 종료된 레코드를 재생할 때는 모델이나 게시자를 다시
호출하지 않습니다.

주기는 발견 경계를 다음과 같이 명시적으로 유지합니다.

- **관측:** 주입된 소스가 상류, 운영, 재정의, 카탈로그 신호가 포함된 하나의 완전하고 범위가
  제한된 구간을 반환합니다.
- **가설 수립:** 구성된 하나의 경로 외부 T2 모델이 비활성 후보를 제안합니다.
- **검증:** ID와 계열이 다른 모델을 하나 이상 사용해 각 정규 후보를 다시 승인합니다. 다이제스트
  불일치, 모델 간 불일치, 불완전한 소스 구간, 시간 초과 또는 결정론적 검증기 실패는 보존된
  사람 검토 보류나 거부 결과를 만듭니다.
- **통합:** 주입된 통합기는 검토가 필요한 비활성 아티팩트만 게시할 수 있습니다. 주기 레코드와
  모든 메트릭은 `grants_authority: false` 를 기록합니다. 카탈로그 변경에는 기존과 같이
  catalog-as-code PR 병합이 필요합니다.

스케줄러는 신호 수, 후보 수, 경과 시간, 보존할 주기 이력을 제한합니다. 또한 주기당 후보 수,
게이트 통과율, 재정의 유발률, 폐기율을 감사된 상태 변환 결과로 게시합니다. `override` 신호
종류는 기존 재정의 피드백 경로를 위한 이벤트 버스 외부 연결입니다. `object.override` 는 계속
지원되지 않습니다.

## 사람 shadow 검토 완료(상류 구현)

shadow 결과는 기존 에이전트 소유권을 통해 검토 미비점을 해소합니다. Saga는 안정적인 shadow
관측 ID와 정책 위반 탈출 표시를 포함한 초기 `object.audit-entry` 를 게시합니다. Var는 해당
레코드를 별도 사람 검토자의 대기열에 넣고 결과를 `object.approval` 로 게시합니다. Saga는
검토된 감사 항목을 다시 게시하고, Norns는 두 번째 표본을 세는 대신 ID로 기존 관측의 검토
상태를 갱신합니다.

검토자는 작업 시작자와 달라야 합니다. 재생되었거나 이미 검토한 관측은 표본 수나 검토 건수를
늘리지 않으며, 검토는 최초 shadow 결과에 기록된 정책 위반 탈출 사실을 변경할 수 없습니다.


## 관련 문서

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| 구현 상태 및 남은 작업 | [구현 원장](../../roadmap-implementation/rules-and-detection/rule-catalog-autonomous-discovery.md) |
