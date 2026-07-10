---
title: "Phase 2 - 지속적 규칙 업데이트, Quality Gate, T1"
translation_of: phase-2-quality-and-t1.md
translation_source_sha: e7e729e82603d93a66e7c2396787cf854f04cf32
translation_revised: 2026-07-11
---

# Phase 2 - 지속적 규칙 업데이트, Quality Gate, T1

**목표**: 결정론 레이어를 신선하게 유지, LLM(T2) 출력을 신뢰할 만하고 안전하게, T1 경량 티어
추가, P0 베이스라인 대비 auto-resolution 비율 검증 - 그다음 특정 액션을 shadow에서 enforce로
승격. 이 phase는
[architecture.instructions.md](../../../.github/instructions/architecture.instructions.md) 의
티어/게이트 규칙과 [llm-strategy-ko.md](../llm-strategy-ko.md) 의 모델-티어 설계 확장.
커버리지 수치(T1 ~15-20%) 는 보장이 아니라 **검증할 목표**
([goals-and-metrics-ko.md](../goals-and-metrics-ko.md)).

## 산출물

- **지속적 규칙-업데이트 파이프라인**(living rules), catalog-as-code PR로 딜리버리.
  결정론 in-process 스테이지는
  [`src/fdai/rule_catalog/pipeline/`](../../../src/fdai/rule_catalog/pipeline/)
  에 랜딩: `ShadowEvaluator` 는 후보 rule set 을 시나리오 세트에 judge-and-log 로 replay,
  `RegressionGate` 는 policy-violation escape 0 + coverage ratio floor + missing-expected-rules
  cap 을 강제, `RulePromotionController` 는 promote/rollback 을 hash-chained audit 기록,
  `ContinuousRulePipeline` 오케스트레이터가 셋을 조합. 외부 배선(source watcher + GitHub App
  PR delivery)은 `core/` 편집 없이 이 스테이지에 꽂힘.
- T2를 방어하는 **LLM quality gate**: mixed-model 교차 검사, 결정론 verifier, grounding. 실행
  자격은 verifier가 부여, **절대 모델이 아님**.
  [`src/fdai/core/quality_gate/`](../../../src/fdai/core/quality_gate/) 에 세 DI
  Protocol(`CrossCheckModel`, `VerifierPolicy`, `GroundingSource`) + `QualityGate`
  오케스트레이터 배송(`eligible | abstain | disagree | deny` emit). 모든 심의 in-memory
  fake 는
  [`quality_gate/testing.py`](../../../src/fdai/core/quality_gate/testing.py)
  에 있어 fork 가 live LLM 없이 composition root 를 smoke.
- **T1 경량 티어**: 임베딩 유사도 + 안전 재검증된 학습된-액션 재사용.
  [`src/fdai/core/tiers/t1_lightweight/`](../../../src/fdai/core/tiers/t1_lightweight/)
  가 `T1Tier` 오케스트레이터 + `EmbeddingModel` / `PatternLibrary` 심을 배송; 페이크
  `DeterministicEmbeddingModel` + `InMemoryPatternLibrary` 는
  [`t1_lightweight/testing.py`](../../../src/fdai/core/tiers/t1_lightweight/testing.py)
  에 있어 real embedding 모델 / pgvector 없이 재현 가능한 유닛 테스트 가능.
- **Shadow → enforce 승격**, 액션별, 정책 escape 0으로 측정된 메트릭에 게이팅.
  [`src/fdai/core/risk_gate/`](../../../src/fdai/core/risk_gate/) 가
  `ActionPromotionRegistry.consider_promotion(metrics)` 를 구현 -
  ActionType 의 `promotion_gate` (min_shadow_days / min_samples / min_accuracy /
  max_policy_escapes) 를 측정된 `PromotionMetrics` 에 대해 평가하고 결정된 mode 를 기록.
  `RiskGate.evaluate` 는 그 레지스트리를 read - shadow-mode ActionType 은 `hil` 반환,
  enforce-mode + clean invariants 면 `auto`, 어떤 invariant miss (blast-radius over cap,
  stale precondition, irreversible ActionType) 든 mode 에 관계없이 `hil` 강제.
- **어슈어런스 트윈 (query 슬라이스)**: inventory로부터 투영된 읽기 전용 온톨로지 트윈으로,
  계층과 이 phase의 quality gate를 거치는 검증된 text-to-query 응답; 근거 댓 수 없는 질문은
  abstain하고 규칙 발견 루프로 투입. 전체 설계는 [assurance-twin-ko.md](../assurance-twin-ko.md);
  ambient 리뷰와 그래프 전체 시뮬레이션은 P3에 랜딩.

## 지속적 규칙 업데이트 파이프라인

```text
source watcher → collect/normalize → shadow eval → regression gate → promote | rollback
```

모든 스테이지가 감사 엔트리를 씀; 규칙 변경 자체가 변경이며 **catalog-as-code PR** (out-of-band
auto-edit 절대 아님) 로 shadow 기본으로 나감.

- **Source watcher**: 피드 존재하면 구독, 아니면 설정된 주기로 폴(소스별); 상류 규칙/정책 소스,
  리소스 프로바이더 스키마 버전, 보안 권고 감시. 규칙 `id` 로 중복제거, `source`/`version`
  provenance 캡처, 소스별 주기와 엔드포인트를 설정에 유지.
- **Collect/normalize**: 각 후보를 P1 정규화 스키마
  (`id, version, source, severity, category, resource-type, check-logic, remediation`) 로 매핑;
  severity 다음 source priority로 충돌 해결, ties → HIL (
  [architecture.instructions.md](../../../.github/instructions/architecture.instructions.md) 에
  따라).
- **Shadow eval**: 후보 규칙 세트를 고정 시나리오 세트와 최근 실제 이벤트에 대해 **judge-and-log**
  모드로 리플레이(실행 없음); 커버리지 델타, false-positive와 false-negative 비율, 정책 위반
  escape 측정.
- **Regression gate**: 세트가 승격되기 전 P1 회귀 스위트가 **정책 위반 escape 0** 과 가드-메트릭
  회귀 없이 통과해야 함 ([goals-and-metrics-ko.md](../goals-and-metrics-ko.md)); 실패한 회귀는
  승격 블록.
- **Promote | rollback**: 승격은 명시적, 리뷰된 catalog-as-code 머지; **롤백 트리거** 는 실패한
  회귀, shadow-eval escape, 또는 사후 승격 가드 위반이며, 마지막-good 버전된 세트로 되돌림.
- **새 리소스 타입**: 프로바이더 스키마 변경 감지, 커버되지 않은 리소스 타입 식별, **shadow-only
  및 HIL-리뷰로 출시되는 규칙 stub 생성** - stub은 절대 auto-enforce 아님.

## LLM Quality Gate (T2 - [llm-strategy-ko.md](../llm-strategy-ko.md) 참조)

T2 입력은 **untrusted** ([security-and-identity-ko.md](../security-and-identity-ko.md));
verifier와 정책 재검사가 권위, 모델 텍스트 아님.

- **Mixed-model 교차 검사**: **2개 이상 독립 모델** 실행(distinct 프로바이더/가중치, 한 base
  모델의 두 엔드포인트 아님 - correlated 에러가 검사 무력화). 합의는 정규화 구조화 액션에 대해;
  N ≥ 3 인 경우 설정된 quorum 요구. 어떤 불일치도 **HIL로 escalate**, 절대 auto-resolve 아님.
- **Verifier**: 어떤 모델과도 독립적인 결정론 검사가 후보 액션을 policy-as-code와 what-if/dry-run
  에 대해 재검증. Verifier 통과만이 액션을 execution-eligible로 만듦.
- **Grounding (RAG)**: 정당화 규칙/정책 인용 강제, **각 인용 항목이 규칙 카탈로그에 존재하고
  실제로 주장을 지지하는지 검증**(fabricated 인용 방어); ungrounded 시 **HIL로 abstain**.
- **임계 게이팅**: 스키마, 정책, what-if, 보안-스캔 검사가 모두 통과해야 하고 verifier/교차 검사
  신호에서 파생된(모델의 self-report 아님) **신뢰도** 가 설정된 임계 통과 필요; 임계 아래는
  HIL로 라우팅. 결과는 타입되고 감사됨: `eligible | abstain | disagree | deny`.

## T1 경량 티어

- **유사도 매칭**: 각 정규화 이벤트를 임베드하고 패턴 라이브러리에 매칭; 매칭은 유사도 스코어가
  **설정된 임계** 를 통과해야 함(임계는 config, 하드코딩 아님), false 매칭 방어.
- **Abstain 경로**: 규칙 매칭 없음, 임계 아래 유사도, 또는 적용 가능한 학습된 액션 없음
  → **T2로 abstain** ([llm-strategy-ko.md](../llm-strategy-ko.md) 의 T1→T2 경계에 따라).
- **학습된-액션 재사용 (provenance + 안전)**: 재사용 액션은 provenance(source 인시던트 id, 역사적
  성공률) 를 운반하고 **실행 전 verifier와 리스크 게이트를 통해 재검증** - 재사용은 auto-trust
  아님.
- 목표: 프론티어 왕복 없이 ~15-20% 이벤트 흡수, **측정으로 검증**.

## 승격 (shadow → enforce)

- **액션별** 승격, 명시적·별도 리뷰 - 절대 능력의 첫 PR과 enforce 번들링 안 함.
- Auto-resolution 비율(metric 2) 과 **가드-메트릭 회귀 없음** 게이트, 같은 고정 시나리오 세트
  버전에서 측정되고 **표본 크기와 신뢰구간** 과 함께 보고
  ([goals-and-metrics-ko.md](../goals-and-metrics-ko.md)); shadow에서 **정책 위반 escape 0**
  필요.
- **강등**: 어떤 가드-메트릭 위반 또는 정책 위반 escape는 액션을 enforce에서 shadow로 자동 강등;
  선행 지표(disagreement 비율, verifier abstain/fail 비율) 는 후행 가드가 회귀하기 전 조사 트리거.

## 테스트 가능성

- 리스크 게이트와 quality gate에 property 테스트: "high-risk는 절대 auto-execute 안 함",
  "shadow 모드는 절대 변형 안 함", "abstain/disagree/deny는 절대 실행 안 함".
- 액션별 shadow-mode 테스트가 변형 없이 판단·로그함 증명; 규칙 변경별 회귀 테스트
  ([coding-conventions.instructions.md](../../../.github/instructions/coding-conventions.instructions.md)).
- Quality-gate 회귀가 ungrounded, fabricated-citation, disagreeing 출력이 실행 전에 블록됨
  증명. 테스트는 결정론(seeded, 라이브 네트워크 없음).

## Exit 기준

- Auto-resolution 비율 개선이 같은 시나리오 세트 버전에서 P0 베이스라인 대비 측정, 표본 크기와
  신뢰구간과 함께.
- Quality gate가 실행 전 ungrounded, fabricated-citation, disagreeing T2 출력을 명시적으로 블록
  (회귀 테스트로 증명).
- 규칙 업데이트가 watcher → shadow eval → regression 을 통해 감사된, 버전된 롤백과 함께 흐름.
- T1이 측정된 이벤트 비율을 흡수하고 임계 아래 T2로 깨끗이 abstain.

## 의존성

- P0 베이스라인, 원격측정, 가드-메트릭 대시보드
  ([phase-0-instrumentation-ko.md](phase-0-instrumentation-ko.md)).
- Shadow에서 실행 중인 P1 규칙 카탈로그와 T0 엔진
  ([phase-1-rule-catalog-t0-ko.md](phase-1-rule-catalog-t0-ko.md)).
- 통합 컨트롤 루프로 공급 ([phase-3-integrated-loop-ko.md](phase-3-integrated-loop-ko.md)).
