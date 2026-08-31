---
title: "Phase 2 - 지속적 규칙 업데이트, Quality Gate, T1"
translation_of: phase-2-quality-and-t1.md
translation_source_sha: 16d8f4f56b03089c23507c4620149eec4bde5d51
translation_revised: 2026-08-31
---

# 단계 2 - 지속적 규칙 업데이트, Quality 게이트, T1

**목표**: 결정론 레이어를 신선하게 유지, LLM(T2) 출력을 신뢰할 만하고 안전하게, T1 경량 티어
추가, P0 베이스라인 대비 auto-resolution 비율 검증 - 그다음 특정 액션을 shadow에서 강제 적용으로
승격. 이 단계는
[architecture.instructions.md](../../../.github/instructions/architecture.instructions.md) 의
티어/게이트 규칙과 [llm-strategy-ko.md](../architecture/llm-strategy-ko.md) 의 모델-티어 설계 확장.
커버리지 수치(T1 ~15-20%) 는 보장이 아니라 **검증할 목표**
([goals-and-metrics-ko.md](../architecture/goals-and-metrics-ko.md)).

## 산출물

- **지속적 규칙-업데이트 파이프라인**(living 룰), catalog-as-code PR로 딜리버리.
  결정론 프로세스 내 스테이지는
  [`services/core-control-plane/src/fdai/rule_catalog/pipeline/`](../../../services/core-control-plane/src/fdai/rule_catalog/pipeline)
  에 랜딩: `ShadowEvaluator` 는 후보 룰 집합 을 시나리오 세트에 judge-and-log 로 재생,
  `RegressionGate` 는 policy-violation escape 0 + 커버리지 ratio 하한 + missing-expected-rules
  상한 을 강제, `RulePromotionController` 는 promote/롤백 을 hash-chained 감사 기록,
  `ContinuousRulePipeline` 오케스트레이터가 셋을 조합. 외부 배선(출처 watcher + GitHub App
  PR 전달)은 `core/` 편집 없이 이 스테이지에 꽂힘.
- T2를 방어하는 **LLM quality 게이트**: mixed-model 교차 검사, 결정론 검증기, grounding. 실행
  자격은 검증기가 부여, **절대 모델이 아님**.
  [`services/core-control-plane/src/fdai/core/quality_gate/`](../../../services/core-control-plane/src/fdai/core/quality_gate) 에 세 DI
  프로토콜(`CrossCheckModel`, `VerifierPolicy`, `GroundingSource`) + `QualityGate`
  오케스트레이터 배송(`eligible | abstain | disagree | deny` 발행). 모든 심의 in-memory
  가짜 는
  [`quality_gate/testing.py`](../../../services/core-control-plane/src/fdai/core/quality_gate/testing.py)
  에 있어 포크 가 실제 운영 LLM 없이 조립 루트 를 smoke.
- **평가 기준 hallucination 필터** (subtractive): 선택적
  [`RubricEvaluator`](../../../services/core-control-plane/src/fdai/core/quality_gate/rubric.py)가 T2 후보의
  `reasoning_trace`를 고정 criterion으로 채점하고 게이트는 최저 점수를 `min()`으로 확신도에
  반영합니다(가산하지 않음). Shadow-first, 실패 시 차단이며 판정자는 제안자와 구별됩니다.
  `SelfConsistencySampler`는 `action_stability` 신호를 추가합니다. 전체 설계는
  [hallucination-rubric-gate-ko.md](../decisioning/hallucination-rubric-gate-ko.md)에 있습니다.
- **T1 경량 티어**: 임베딩 유사도 + 안전 재검증된 학습된-액션 재사용.
  [`services/core-control-plane/src/fdai/core/tiers/t1_lightweight/`](../../../services/core-control-plane/src/fdai/core/tiers/t1_lightweight)
  가 `T1Tier` 오케스트레이터 + `EmbeddingModel` / `PatternLibrary` 심을 배송; 페이크
  `DeterministicEmbeddingModel` + `InMemoryPatternLibrary` 는
  [`t1_lightweight/testing.py`](../../../services/core-control-plane/src/fdai/core/tiers/t1_lightweight/testing.py)
  에 있어 real 임베딩 모델 / pgvector 없이 재현 가능한 유닛 테스트 가능.
- **Shadow → 강제 적용 승격**, 액션별, 정책 escape 0으로 측정된 메트릭에 게이팅.
  [`services/core-control-plane/src/fdai/core/risk_gate/`](../../../services/core-control-plane/src/fdai/core/risk_gate) 가
  `ActionPromotionRegistry.consider_promotion(metrics)` 를 구현 -
  ActionType 의 `promotion_gate` (min_shadow_days / min_samples / min_accuracy /
  max_policy_escapes) 를 측정된 `PromotionMetrics` 에 대해 평가하고 결정된 모드 를 기록.
  `RiskGate.evaluate` 는 그 레지스트리를 읽기 - shadow-mode ActionType 은 `hil` 반환,
  enforce-mode + clean invariants 면 `auto`, 어떤 불변식 miss (blast-radius over 상한,
  stale precondition, irreversible ActionType) 든 모드 에 관계없이 `hil` 강제.
- **어슈어런스 트윈 (조회 슬라이스)**: 인벤토리로부터 투영된 읽기 전용 온톨로지 트윈으로,
  계층과 이 단계의 quality 게이트를 거치는 검증된 text-to-query 응답; 근거 댓 수 없는 질문은
  abstain하고 규칙 발견 루프로 투입. 전체 설계는 [assurance-twin-ko.md](../operations/assurance-twin-ko.md);
  주변 리뷰와 그래프 전체 시뮬레이션은 P3에 랜딩.

## 지속적 규칙 업데이트 파이프라인

```text
source watcher → collect/normalize → shadow eval → regression gate → promote | rollback
```

모든 스테이지가 감사 엔트리를 씀; 규칙 변경 자체가 변경이며 **catalog-as-code PR** (out-of-band
auto-edit 절대 아님) 로 shadow 기본으로 나감.

- **출처 watcher**: 피드 존재하면 구독, 아니면 설정된 주기로 폴(소스별); 상류 규칙/정책 소스,
  리소스 프로바이더 스키마 버전, 보안 권고 감시. 규칙 `id` 로 중복제거, `source`/`version`
  출처 이력 캡처, 소스별 주기와 엔드포인트를 설정에 유지.
- **Collect/normalize**: 각 후보를 P1 정규화 스키마
  (`id, version, source, severity, category, resource-type, check-logic, remediation`) 로 매핑;
  심각도 다음 출처 priority로 충돌 해결, ties → HIL (
  [architecture.instructions.md](../../../.github/instructions/architecture.instructions.md) 에
  따라).
- **Shadow eval**: 후보 규칙 세트를 고정 시나리오 세트와 최근 실제 이벤트에 대해 **judge-and-log**
  모드로 리플레이(실행 없음); 커버리지 델타, false-positive와 false-negative 비율, 정책 위반
  escape 측정.
- **회귀 게이트**: 세트가 승격되기 전 P1 회귀 스위트가 **정책 위반 escape 0** 과 가드-메트릭
  회귀 없이 통과해야 함 ([goals-and-metrics-ko.md](../architecture/goals-and-metrics-ko.md)); 실패한 회귀는
  승격 블록.
- **Promote | 롤백**: 승격은 명시적, 리뷰된 catalog-as-code 머지; **롤백 트리거** 는 실패한
  회귀, shadow-eval escape, 또는 사후 승격 가드 위반이며, 마지막-good 버전된 세트로 되돌림.
- **수집기 인계**: Phase 1 수집 검토 패키지는 이 단계의 비활성 입력입니다. Mimir가 검토된
  후보 전환을 소유합니다. 승격 컨트롤러는 shadow 승격 또는 롤백 근거만 기록하고, 별도로
  권한이 부여된 catalog-as-code 병합이 활성 개정을 변경합니다. 스냅샷 저장, 검토 패키지 병합,
  컨트롤러 출력만으로는 규칙이 활성화되지 않습니다.
- **새 리소스 타입**: 프로바이더 스키마 변경 감지, 커버되지 않은 리소스 타입 식별, **shadow-only
  및 HIL-리뷰로 출시되는 규칙 stub 생성** - stub은 절대 auto-enforce 아님.

### 전역 프로바이더 스키마 집계

프로바이더 스키마 발견은 모든 upstream 타입을 운영 `ResourceType` vocabulary에 추가하지 않고
별도의 content-addressed 근거 카탈로그를 사용합니다. 전역 카탈로그는 사용하지 않거나 관찰되지
않은 타입, preview-only, read-only 및 지원하지 않는 타입을 포함해 하나의 완전하고 변경할 수 없는
source revision에 있는 모든 타입을 집계합니다. 운영 vocabulary와 관계 mapping은 계속 검토된
의미 subset으로 유지합니다.

Azure source는 변경할 수 없는 commit에 고정된 `Azure/bicep-types-az` generated type index입니다.
내부 mirror 또는 서명된 offline bundle이 같은 tree를 제공할 수 있으며 같은 snapshot digest를
생성해야 합니다. Watcher는 현재 subscription에 등록된 provider를 전역 corpus 대신 사용하지
않습니다. 그렇게 하면 deployment가 사용하지 않는 타입이 숨겨지기 때문입니다.

범위가 제한된 각 실행은 다음 명시적 상태 중 하나로 종료합니다.

| 상태 | 의미 | 승격 영향 |
|------|------|-----------|
| `not_due` | 마지막 완전 검사가 policy cadence 안에 있습니다. | 이전 완전 snapshot을 유지합니다. |
| `unchanged` | 완전한 source revision이 현재 digest를 생성합니다. | 검사를 기록하고 proposal을 만들지 않습니다. |
| `compatible` | 안정된 surface를 제거하지 않고 타입 또는 API version이 추가됐습니다. | drift 근거를 append하며 의미 작업은 비활성 review candidate로 유지합니다. |
| `breaking` | 타입이나 stable API version이 제거됐거나 비호환 변경과 추가가 함께 있습니다. | 고정된 의미 surface를 보류하고 통제된 검토를 요구합니다. |
| `policy_blocked` | network policy가 primary와 mirror access를 모두 허용하지 않습니다. | 외부 호출 없이 마지막 완전 snapshot을 유지하고 stale 또는 unavailable 근거를 보고합니다. |
| `unavailable` | 허용된 모든 source가 무결성, 완전성, timeout 또는 I/O 검사에 실패했습니다. | 마지막 완전 snapshot을 유지하고 의미 proposal을 만들지 않습니다. |

관계 후보 새로 고침은 변경된 프로바이더 타입과 이에 의존하는 전이 관계 참조 구성 요소만
무효화합니다. 관련 없는 프로바이더 구성 요소는 재사용할 수 있습니다. D4 검토 원장은 변경할 수
없는 이전 및 정렬 후 맥락, 정확한 비교, 회귀 증적 및 서로 다른 검토자의 결과를 보존합니다.
승인은 catalog pull request 제안만 만들 수 있으며 mapping을 활성화하거나 그래프를 변경할 수
없습니다. 활성 제안 포인터는 내용 기반 세대 산출물이 계속 존재할 때만 유효합니다.

결정론적 diff는 정규화한 type identity와 stable/preview API-version 집합을 비교합니다. 제거는
근거 ledger의 tombstone이며 ontology 또는 rule catalog에서 즉시 삭제되지 않습니다. 중요하고
policy gate를 통과한 drift package만 기존 agent 및 architecture review 흐름에 들어갑니다.
Mechanical watcher는 `ResourceType`, `LinkType`, 관계 mapping, rule 또는 policy를 수정하지 않으며
provider-schema record는 관찰, 승인 또는 실행 권한을 부여하지 않습니다.

구현된 Azure 경로는 두 근거 plane을 모두 고정합니다. `Azure/bicep-types-az`는 전역 resource
type 3,405개를 집계하고 `Azure/azure-rest-api-specs`는 명시적인 ARM ID reference 6,896개와
Azure resource-definition marker 5,382개를 제공합니다. Exact target과 unresolved target은
분리되어 유지됩니다. Content-addressed review는 LinkType이나 orientation을 추론하지 않고 exact
reference 4,707개를 endpoint pair 908개로 분류합니다. 기존에 검토된 mapping ID와 겹치는 항목
8개를 기록하고 의미 검토 필요 상태를 유지하며 automatic promotion을 false로 고정합니다.
Terraform은 daily Container Apps Job을 정의하며 런타임 경로는 private PostgreSQL StateStore를
통해 append-only ledger를 복원하고 보존할 수 있습니다. Material drift는 Heimdall이 검증하고
shadow `object.drift` topic에 `event_type: provider.schema_drift`로만 발행합니다. 운영 검증
전에는 보호된 scheduled-run 증적이 더 필요합니다.

## LLM Quality 게이트 (T2 - [llm-strategy-ko.md](../architecture/llm-strategy-ko.md) 참조)

T2 입력은 **신뢰할 수 없는** ([security-and-identity-ko.md](../architecture/security-and-identity-ko.md));
검증기와 정책 재검사가 권위, 모델 텍스트 아님.

- **Mixed-model 교차 검사**: **2개 이상 독립 모델** 실행(서로 다른 프로바이더/가중치, 한 base
  모델의 두 엔드포인트 아님 - correlated 에러가 검사 무력화). 합의는 정규화 구조화 액션에 대해;
  N ≥ 3 인 경우 설정된 정족수 요구. 어떤 불일치도 **HIL로 escalate**, 절대 auto-resolve 아님.
- **검증기**: 어떤 모델과도 독립적인 결정론 검사가 후보 액션을 policy-as-code와 what-if/예행 실행
  에 대해 재검증. 검증기 통과만이 액션을 execution-eligible로 만듦.
- **필수 근거 집합**: 런타임 조립 경로는 `simulation_engine` 권한의 `what_if` 근거와
  `security_scanner` 권한의 `security` 근거를 모두 요구합니다. 각 버전 있는 레코드는 Core가
  소유한 후보 다이제스트, 생산자, 관측 및 만료 시각, 근거 참조, 충돌 상태, 합성 상태를
  연결합니다. 누락, 만료, 충돌, 미래 시점, 후보 불일치, 합성 근거는 모델 교차 검사 전에
  보류됩니다. 명시적으로 실패한 근거는 후보를 차단합니다. 포크는 프로바이더 중립 검증기 두
  개를 함께 주입해야 하며 부분 연결은 조립 시 실패합니다.
- **Grounding (RAG)**: 정당화 규칙/정책 인용 강제, **각 인용 항목이 규칙 카탈로그에 존재하고
  실제로 주장을 지지하는지 검증**(fabricated 인용 방어); ungrounded 시 **HIL로 abstain**.
- **임계 게이팅**: 스키마, 정책, what-if, 보안-스캔 검사가 모두 통과해야 하고 검증기/교차 검사
  신호에서 파생된(모델의 self-report 아님) **신뢰도** 가 설정된 임계 통과 필요; 임계 아래는
  HIL로 라우팅. 결과는 타입되고 감사됨: `eligible | abstain | disagree | deny`.

첫 설계에서는 선택적 what-if 및 보안 콜백으로 규칙 검증기를 확장하는 방안을 검토했습니다.
이 형태는 연결되지 않은 콜백을 조용히 건너뛰거나 한 구성 요소가 여러 근거 계열을 자체 증명하게
할 수 있습니다. 수정된 설계는 규칙 권한 확인을 분리하고 각 결정론적 근거 계열에 고정 권한
분류를 부여합니다. 운영 런타임은 실제 생산자 두 개가 모두 주입될 때까지 명시적인 사용 불가
검증기를 연결합니다. 격리된 호환성 테스트는 QualityGate를 직접 구성할 수 있지만, 출시된
런타임은 현재 독립 레코드 두 개 없이는 적격 T2 후보를 만들 수 없습니다. 합성 레코드는
메커니즘만 테스트하며 라이브 승격을 충족하지 않습니다.

## T1 경량 티어

- **유사도 매칭**: 각 정규화 이벤트를 임베드하고 패턴 라이브러리에 매칭; 매칭은 유사도 스코어가
  **설정된 임계** 를 통과해야 함(임계는 구성, 하드코딩 아님), false 매칭 방어.
- **Abstain 경로**: 규칙 매칭 없음, 임계 아래 유사도, 또는 적용 가능한 학습된 액션 없음
  → **T2로 abstain** ([llm-strategy-ko.md](../architecture/llm-strategy-ko.md) 의 T1→T2 경계에 따라).
- **학습된-액션 재사용 (출처 이력 + 안전)**: 재사용 액션은 출처 이력(출처 인시던트 id, 역사적
  성공률) 를 운반하고 **실행 전 검증기와 리스크 게이트를 통해 재검증** - 재사용은 auto-trust
  아님.
- **근거 한계**: 유사도는 finite이며 `[-1, 1]` 범위여야 하고 성공 비율은 `[0, 1]`
  범위여야 합니다. Reuse 개수와 필수 액션 출처 이력도 valid해야 하며 malformed pattern-library
  근거는 reuse 후보가 되지 않고 abstain합니다.
- 목표: 프론티어 왕복 없이 ~15-20% 이벤트 흡수, **측정으로 검증**.

## 승격 (shadow → 강제 적용)

- **액션별** 승격, 명시적·별도 리뷰 - 절대 능력의 첫 PR과 강제 적용 번들링 안 함.
- Auto-resolution 비율(메트릭 2) 과 **가드-메트릭 회귀 없음** 게이트, 같은 고정 시나리오 세트
  버전에서 측정되고 **표본 크기와 신뢰구간** 과 함께 보고
  ([goals-and-metrics-ko.md](../architecture/goals-and-metrics-ko.md)); shadow에서 **정책 위반 escape 0**
  필요.
- **강등**: 어떤 가드-메트릭 위반 또는 정책 위반 escape는 액션을 강제 적용에서 shadow로 자동 강등;
  선행 지표(disagreement 비율, 검증기 abstain/fail 비율) 는 후행 가드가 회귀하기 전 조사 트리거.

## 테스트 가능성

- 리스크 게이트와 quality 게이트에 속성 테스트: "high-risk는 절대 auto-execute 안 함",
  "shadow 모드는 절대 변형 안 함", "abstain/disagree/거부는 절대 실행 안 함".
- 액션별 shadow-mode 테스트가 변형 없이 판단·로그함 증명; 규칙 변경별 회귀 테스트
  ([coding-conventions.instructions.md](../../../.github/instructions/coding-conventions.instructions.md)).
- Quality-gate 회귀가 ungrounded, fabricated-citation, disagreeing 출력이 실행 전에 블록됨
  증명. 테스트는 결정론(seeded, 라이브 네트워크 없음).

## Exit 기준

- Auto-resolution 비율 개선이 같은 시나리오 세트 버전에서 P0 베이스라인 대비 측정, 표본 크기와
  신뢰구간과 함께.
- Quality 게이트가 실행 전 ungrounded, fabricated-citation, disagreeing T2 출력을 명시적으로 블록
  (회귀 테스트로 증명).
- 규칙 업데이트가 watcher → shadow eval → 회귀 을 통해 감사된, 버전된 롤백과 함께 흐름.
- T1이 측정된 이벤트 비율을 흡수하고 임계 아래 T2로 깨끗이 abstain.

## 의존성

- P0 베이스라인, 원격측정, 가드-메트릭 대시보드
  ([phase-0-instrumentation-ko.md](phase-0-instrumentation-ko.md)).
- Shadow에서 실행 중인 P1 규칙 카탈로그와 T0 엔진
  ([phase-1-rule-catalog-t0-ko.md](phase-1-rule-catalog-t0-ko.md)).
- 통합 컨트롤 루프로 공급 ([phase-3-integrated-loop-ko.md](phase-3-integrated-loop-ko.md)).

## 관련 문서

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| 구현 상태 및 남은 작업 | [구현 원장](../../roadmap-implementation/phases/phase-2-quality-and-t1.md) |
