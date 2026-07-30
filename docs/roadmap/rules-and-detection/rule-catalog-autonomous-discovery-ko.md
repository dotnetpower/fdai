---
title: 자율 규칙 발견(Autonomous Rule Discovery)
translation_of: rule-catalog-autonomous-discovery.md
translation_source_sha: 0b32a0ee60fd529a287875b64f77e1e314f2d7cc
translation_revised: 2026-07-30
---

# 자율 규칙 발견(Autonomous Rule Discovery)

이 문서는 상류 및 운영 신호에서 규칙 후보를 제안, 검증, 통합하는 카탈로그 발견 루프를 다룹니다.
수집 소스와 정규화는 [규칙 카탈로그 수집](rule-catalog-collection-ko.md)에서 계속 설명합니다.

## 설계 개요

수집은 "상류 소스 읽기" 뿐이 아님. 카탈로그는 **운영 신호** 에서도 성장하고 self-correct,
그래서 결정론 레이어가 사람이 모든 규칙을 손으로 만들지 않고 환경에 발맞춤. 이것은
[architecture.instructions.md](../../../.github/instructions/architecture.instructions.md) 의
"Living rules" 원칙.

## 루프

Long-horizon 루프가 무한 반복; 모든 사이클이 같은 공유 세계 모델(정규화된 카탈로그, 감사 로그,
인시던트 라이브러리, provenance 저장소) 을 유지 - 사이클이 처음부터 재시작하지 않고 서로 위에
빌드:

```text
sources + operational signals ─► observe ─► hypothesize ─► verify ─► integrate
                                                            (quality gate)
```

- **observe** - 루프는 하나씩이 아니라 세 피드를 나란히 읽음:
  1. **상류 소스** 위 컬렉터 파이프라인 경유(새/변경 컨트롤).
  2. **운영 신호** - 최근 감사 로그 엔트리, HIL 승인 패턴, shadow-mode 결과, 롤백, **override
     이벤트** ([rule-governance-ko.md](rule-governance-ko.md)).
  3. **현재 카탈로그** - 기존 규칙, provenance, 측정된 정확도.
- **hypothesize** - 추론 스테이지(LLM 스테이지, 어떤 T2 출력처럼 취급) 가 세 형상의 **후보**
  엔트리 제안:
  - **new-rule**: 아직 커버되지 않은 컨트롤, 반복되는 인시던트/HIL 패턴 또는 새로 발행된 상류
    컨트롤에 의해 동기.
  - **revision**: 상류 소스가 바뀌었거나(그 `content_hash` 가 이동) shadow 정확도가 임계
    아래로 drift한 기존 규칙.
  - **retirement**: 반복적으로 override되거나 shadow 결과가 실제 환경에 poor fit임을 보이는
    기존 규칙.
- **verify** - 모든 후보는 표준 **quality gate** 통과할 때까지 inert 데이터:
  1. 엄격 JSON Schema (`additionalProperties: false`);
  2. Provenance 검사 - `source_url`, `resolved_ref`, `content_hash`, `license`,
     `redistribution` 모두 존재하고 검증 가능 (grounded provenance 없는 후보는 즉시 거부);
  3. **Mixed-model 교차 검사** - 두 번째 모델(다른 패밀리/벤더) 이 같은 후보를 재도출하거나 재
     승인; 불일치는 HIL로 escalate, 절대 auto-resolve 아님
     ([architecture.instructions.md](../../../.github/instructions/architecture.instructions.md));
  4. 결정론 verifier - Rego 파싱, 중복 `id` 없음, 더 엄격한 컨트롤을 조용히 약화시킬 기존 규칙과
     충돌 없음;
  5. 회귀 스위트 - 기존 픽스처가 여전히 통과;
  6. Shadow-mode dwell - 후보가 설정된 최소 기간과 표본 크기 동안 실제 트래픽에 judge-and-log-only
     실행, 임계 위 정확도와 정책 위반 escape 0.
- **integrate** - 게이트 통과한 후보는 [rule-governance-ko.md](rule-governance-ko.md) 의 할당/
  effect 라이프사이클에 따라 승격(new-rule/revision은 먼저 audit effect로 랜딩; retirement는
  tombstone으로 랜딩). 카탈로그는 오직 머지된 catalog-as-code PR로만 변형, 절대 루프에 의해
  직접 아님.

## 후보 요건 (MUST)

- 모든 후보는 **grounded provenance** 인용해야 함 - 상류 문서 URL + resolved revision/hash,
  또는 특정 인시던트/HIL/override 이벤트 id, 또는 특정 취약성/권고 id. "모델이 그것을 생각했음"
  은 provenance가 아님.
- 모든 후보는 CSP-중립 `resource_type` 어휘 대상, 절대 벤더 경로 아님.
- Reference-only 소스 텍스트는 후보에 붙여넣기되어선 안 됨;
  [Licensing](rule-catalog-collection-ko.md#라이선싱-소스-추가-전-읽기) 규칙에 따라 authored
  `check_logic` + 인용만.
- 어떤 게이트 스텝을 실패하는 후보는 **abstain** 이 됨 - 사유와 함께 로그되어 다음 사이클이
  revisit할 수 있지만, 절대 부분적으로 적용되지 않음.

## Override 피드백

Override는 루프의 first-class 입력, dead-end 아님. 규칙이 스코프에 걸쳐 long-lived 또는 반복
override를 누적할 때, observe 스테이지가 플래그하고 hypothesize 스테이지가 **revision** (override
가 불필요하도록 규칙 좁힘) 또는 **retirement** (규칙이 체계적으로 poor fit) 제안. 어느 쪽이든
제안은 여전히 전체 quality gate 통과. Override는 카탈로그를 직접 변형하지 않음 - 신호만 공급.

## 안전과 신뢰

- 루프는 **후보 생성기** , executor 아님. 라이브 카탈로그를 변형할 수 없고, 할당을 enforce로
  flip할 수 없으며, [rule-governance-ko.md](rule-governance-ko.md) 의 승격 승인을 우회할 수
  없음.
- 이 루프의 어떤 LLM 스테이지도 T2 호출이며
  [architecture.instructions.md](../../../.github/instructions/architecture.instructions.md) 의
  T2 quality gate(mixed-model, verifier, grounding, abstain-when-unsupported) 준수.
- 루프 자체의 처리량(사이클당 후보, gate 통과율, override-트리거된 제안률, retirement률) 은
  계측되고 [goals-and-metrics-ko.md](../architecture/goals-and-metrics-ko.md) 에 보고 - 측정 가능, assert
  아님.

## Candidate Guard (업스트림 구현)

`fdai.agents._framework.candidate_guard.CandidateGuard` 는 Mimir 가 모든 `RuleCandidate` 를 pending
목록에 넣기 전에 실행하는 결정론적 게이트다 - 위의 Candidate Requirements 강제 지점이자
discovery 루프의 poisoning 방어다. 아무것도 promote 하지 않으며(그건 quality gate 소관),
**accept** 대 **quarantine** 을 결정하고 이유를 기록해, 거부된 후보를 조용히 버리지 않고
audit 용으로 보존한다. 검사는 순수하다(I/O 없음, model 호출 없음):

- **Provenance** - `proposed_by` 와 알려진 `proposal_kind`
  (`new` / `new-scenario` / `revision` / `retirement` / `threshold_adjustment`) 가 필수.
- **Grounding** - 비어있지 않은 `evidence` 매핑이 필수; 근거 없는 후보는 quarantine 된다
  ("모델이 그렇게 생각했다"는 evidence 가 아니다).
- **Range sanity** - 수치 evidence 는 범위 안이어야 한다(`rollback_rate` 가 `[0, 1]` 밖이거나
  count 가 비양수면 손상되거나 위조된 신호다).
- **Flood 감지** - 동일 후보 fingerprint 가 반복 상한을 넘으면 poisoning flood 의심으로
  quarantine 된다(Norns 가 정당한 제안은 이미 dedup 하므로 반복 burst 는 이상이다).
