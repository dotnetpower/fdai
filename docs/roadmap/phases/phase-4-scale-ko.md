---
translation_of: phase-4-scale.md
translation_source_sha: e592ab3bcfb0a479e5e6f5113c57c807100b27c6
translation_revised: 2026-07-05
---

# Phase 4 — 스케일 (Azure); 멀티 클라우드 (TBD)

**목표**: 시스템이 스케일할 때 Azure 베이스라인을 정직하게 유지 — 지속 측정, 패턴-라이브러리
성장, 모델 cost/quality 추적, 성능/확장성 — 그래서 목표 배수가 assert되지 않고 **측정된 베이스라인
대비 검증** 유지. 여기서 어떤 배수도 주장되지 않음; Phase 4는 시스템이 스케일할 때 Phase 0 증거를
current하게 유지. **멀티 클라우드 확장은 연기(TBD)** ; 아래 *TBD (deferred)* 표시된 섹션은
전방-지향 설계로 보존되며 비-Azure 대상이 명시적으로 스코프될 때까지 이 로드맵에서 구축되지 않음
([Implementation Focus](../../../.github/copilot-instructions.md#implementation-focus-must)
참조).

이 phase는 Phase 0–3 코어 위에 구축되고 변경하지 않음.
[architecture.instructions.md](../../../.github/instructions/architecture.instructions.md) 와
[app-shape.instructions.md](../../../.github/instructions/app-shape.instructions.md) 의
CSP-중립 원칙을 **설계 불변식**(어댑터 표면, 정규화 스키마) 로 실현하여 향후 비-Azure 어댑터가
추가적이도록; [tech-stack-ko.md](../tech-stack-ko.md) 의 스택과 어댑터 경계 재사용, 엄격히
[goals-and-metrics-ko.md](../goals-and-metrics-ko.md) 로 측정, [security-and-identity-ko.md](../security-and-identity-ko.md)
의 아이덴티티와 shadow-mode 규칙 상속.

## 산출물

- 자동 회귀 강등 있는 Azure 베이스라인의 지속 측정/개선 루프.
- 오버피팅 방지 가드 있는 패턴-라이브러리(T1) 성장.
- 측정-주도 스왑 있는 모델 cost/quality 추적.
- Azure에서 확장성/성능 검증(티어별 지연 예산, 이벤트-기반 scale-to-zero 보존).
- **TBD (deferred)**: **provider 어댑터** 를 통한 정책과 실행의 멀티 클라우드 확장(새 코어 없음),
  크로스-CSP rule-catalog 정규화, per-CSP 실행 아이덴티티, 멀티 클라우드 이벤트 버스 결정
  ([tech-stack-ko.md](../tech-stack-ko.md) 의 OD-3). 이 항목들은 비-Azure 작업이 스코프될
  때까지 설계 형상으로만 남음.

## Provider 어댑터 경계 (TBD — deferred)

> 이 섹션은 향후 비-Azure 대상을 위한 **설계 불변식** 으로 보존. 이 phase에서 **구축되지 않음** ;
> [Implementation Focus](../../../.github/copilot-instructions.md#implementation-focus-must)
> 참조.

코어 엔진은 CSP-중립 유지; 새 클라우드는 어댑터 구현으로 추가되지 절대 코어 포크로 추가되지
않음. 어댑터 표면은 고정되고 각 어댑터는 기존 인터페이스 뒤에 추가됨
([project-structure-ko.md](../project-structure-ko.md) 참조):

- **Policy 어댑터** — 프로바이더-파라미터화된 입력으로 같은 OPA/Rego 정책 평가; per-cloud 정책
  포크 없음.
- **IaC / executor 어댑터** — Terraform/OpenTofu 프로바이더로 remediation 적용; remediation PR
  emit, CSP당 네 안전 불변식(stop-condition, rollback, blast-radius, audit) 준수.
- **Identity 어댑터** — 범위된 실행 principal 공급(아래 참조).
- **Event-source / bus 어댑터** — 프로바이더 이벤트를 인그레스에서 버전된 내부 스키마로 정규화.
- **State-store 어댑터** — audit/pattern-library/KPI 저장을 이식 가능하게 유지.

엄격도 요건(비-Azure 어댑터가 결국 스코프될 때 적용):

- 코어 엔진은 벤더 SDK를 import 하지 않음; SDK 호출은
  [coding-conventions.instructions.md](../../../.github/instructions/coding-conventions.instructions.md)
  에 따라 어댑터 안에만 존재.
- 모든 어댑터는 CSP 간 동일한 외부 관측 동작(같은 정규화 이벤트 → 같은 티어 결정 → 같은 액션
  형상) 을 증명하는 **contract/parity 테스트** 와 함께 나감.
- Provider 선택은 코어의 코드 브랜치가 아니라 설정.

## 멀티 클라우드 규칙 카탈로그 (TBD — deferred)

> 비-Azure 대상이 스코프될 때까지 연기. Azure만 유일한 구현 카탈로그 대상;
> [rule-catalog-collection-ko.md](../rule-catalog-collection-ko.md) 참조.

- 소스 추가: **AWS** (Well-Architected, Config managed rules, CIS AWS) 와 **GCP** (Recommender,
  Policy Controller / Gatekeeper constraints, CIS GCP), [phase-1-rule-catalog-t0-ko.md](phase-1-rule-catalog-t0-ko.md)
  의 기존 Azure와 OSS 소스와 함께.
- 모든 규칙을 공통 CSP-중립 스키마(`id, version, source, severity, category, resource-type,
  check-logic, remediation, provenance`) 로 **정규화** 하여 규칙이 원본 클라우드와 무관하게
  같게 읽힘.
- **크로스-CSP 충돌 처리**: 다른 클라우드나 소스의 규칙이 하나의 이벤트에 매칭될 때, `id` 로
  중복제거, severity 다음 source priority로 우선순위 해결, tie는 auto-pick 대신 **HIL로
  escalate**. Provenance는 origin 소스와 버전을 기록하여 규칙 변경이 추적·역방향 가능.
- 새 소스는 기존 업데이트 파이프라인(`source watcher → collect → shadow eval → regression →
  promote / rollback`, [phase-2-quality-and-t1-ko.md](phase-2-quality-and-t1-ko.md)) 을 통해
  흐름; 승격은 정책 위반 escape 0으로 회귀 스위트 통과 필요.

## Per-CSP 아이덴티티와 최소권한 (TBD — deferred)

> 연기; Azure 아이덴티티 모델이 오늘 적용(user-assigned Managed Identity, 액션 화이트리스트,
> 별개 approval/execution principal — [security-and-identity-ko.md](../security-and-identity-ko.md)
> 참조).

- 각 클라우드는 자체 **범위된 실행 아이덴티티** (예: Azure user-assigned Managed Identity, AWS
  IAM 롤, GCP 서비스 계정), 각각 액션 화이트리스트로 제한. 어떤 아이덴티티도 클라우드 간이나
  레이어 간 공유되지 않음.
- 모든 클라우드에서 **승인과 실행은 별개 principal** — no self-approval,
  [security-and-identity-ko.md](../security-and-identity-ko.md) 에 따라.
- Blast-radius limit(스코프/배치/속도 상한) 은 CSP별로 강제; 잘못 설정된 어댑터는 화이트리스트를
  초과할 수 없음.

## 이벤트 버스 이식성 (TBD — deferred)

> 연기; Azure에서 버스는 Service Bus + Event Grid
> ([tech-stack-ko.md](../tech-stack-ko.md#od-3-멀티-클라우드-이벤트-버스-phase-4--tbd) 참조).

- Phase 0–3 버스(Service Bus + Event Grid)가 멀티 클라우드 필요를 충족하는지 아니면 이식 가능
  log/queue(Kafka 또는 NATS JetStream) 가 필요한지 검증하여 OD-3 결정.
- 결정 기준: 클라우드 간 **순서, dead-letter, 리플레이, idempotency 패리티**, 운영 비용, CSP
  중립성 — 버스 어댑터는 backend와 무관하게 리소스별 순서와 at-least-once + 멱등 처리 보존해야
  함.
- 결과를 결정 기록으로 기록하고 [tech-stack-ko.md](../tech-stack-ko.md) OD-3 업데이트.

## 안전과 Shadow-First 롤아웃

- 새로 추가된 어떤 능력도 shadow 정확도가 정책 위반 escape 0으로 측정될 때까지 **shadow 모드**
  (judge-and-log, 실행 없음) 로 출시; enforce로의 승격은 명시적·액션별,
  [architecture.instructions.md](../../../.github/instructions/architecture.instructions.md)
  와 매칭. 비-Azure 어댑터가 결국 스코프될 때(TBD), 같은 shadow-first 규칙이 어댑터의 첫
  액션에 적용.
- 어떤 회귀는 영향받은 액션을 자동으로 shadow로 강등.

## 지속 측정과 개선

- 고정 버전 시나리오 세트에서 주기적으로 **베이스라인 vs 트리트먼트** 재실행; **회귀** 는
  가드-메트릭 위반 또는 보고된 신뢰구간 넘는 성공-메트릭 하락, 그리고 자동 shadow 강등 트리거
  ([goals-and-metrics-ko.md](../goals-and-metrics-ko.md)).
- 가드 메트릭(CFR, false-positive/negative, rollback rate, **정확히 0** 정책 위반 escape) 는
  성공 메트릭과 같은 측정 윈도우와 시나리오 세트 버전에서 평가, 그래서 이득과 위반이 다른
  데이터에서 비교되지 않음.
- 후행 가드 메트릭이 이동하기 전 회귀가 잡히도록 **환경별** 선행 지표(티어별 커버리지 drift,
  mixed-model 불일치, verifier abstain/fail) 감시. Per-cloud 분해는 **TBD** 설계 불변식,
  비-Azure 어댑터가 스코프될 때만 활성화.
- 목표가 current, fair reference를 추적하도록 모든 시나리오 세트 버전 bump에 re-baseline.

## 패턴 라이브러리 성장 (T1)

- 패턴 라이브러리는 **auto-resolved, non-rolled-back, verified** 프로덕션 결과에서만 공급;
  실패, revert, HIL-override된 액션은 재사용 가능한 패턴이 되어선 안 됨.
- 새 패턴은 **shadow** 에서 진입하고 T1 액션을 주도할 수 있기 전 shadow-평가됨 — 라이브러리는
  self-promote 할 수 없음.
- 피드백-루프 오버피팅 방어: 시간적 holdout(cutoff 전에 학습된 패턴, 이후 테스트) 에서 후보
  패턴 검증, T1 false-positive 비율을 가드로 모니터; 상승하는 비율은 offending 패턴 강등. 성장은
  가드 메트릭을 회귀시키지 **않고** auto-resolution을 올려야 함.

## 모델 Cost/Quality 추적

- [goals-and-metrics-ko.md](../goals-and-metrics-ko.md) 의 cost/usage와 원격측정 소스에서
  모델별 비용과 품질을 시간에 걸쳐 추적; T2 reasoner 모델을 **측정된 결과로 스왑, 가정 아님**,
  모델 ID와 임계값을 [llm-strategy-ko.md](../llm-strategy-ko.md) 에 따라 config로 유지.
- 모델 폐기/가격 변경 플래그, enforce에 도달하는 어떤 스왑 전에 시나리오 세트에서 mixed-model
  교차 검사 재검증.

## 확장성과 성능

- 이벤트 볼륨이 커질 때 Azure에서 티어별 지연 예산과 이벤트-기반, scale-to-zero 자세 보존.
  멀티 클라우드 성능 패리티는 TBD(연기).
- 코퍼스나 recall/latency 목표가 요구할 때 T1 벡터 검색을 pgvector에서 전용 vector store로
  졸업([tech-stack-ko.md](../tech-stack-ko.md) 의 기준); state 어댑터가 이를 코어에 투명하게
  유지.

## Exit 기준

- 지속 측정이 명시된 Azure 측정 윈도우에서 어떤 가드 메트릭에도 **회귀 없음** 표시, 정책 위반
  escape가 정확히 0으로 유지.
- 배수 목표(메트릭 1–4) 가 Azure 베이스라인 대비 **통계적 증거로 시연** (표본 크기, 신뢰구간,
  시나리오 세트 버전) — 배수와 절대값으로 보고, 절대 assert 아님.
- 패턴-라이브러리 성장이 시간적 holdout에서 가드 메트릭을 회귀시키지 **않고** auto-resolution
  을 올림.
- **멀티 클라우드 이식성은 이 phase의 exit 기준이 아님** — 연기(TBD) 되며 향후 phase에서
  스코프될 예정
  ([Implementation Focus](../../../.github/copilot-instructions.md#implementation-focus-must)
  참조).

## Open Questions

- Vector-store 졸업 기준과 마이그레이션 경로(pgvector → 전용 store).
- Azure 지속 측정 루프의 회귀-윈도우와 신뢰-구간 설정.
- **TBD (deferred)**: 어떤 두 번째 클라우드를 먼저 온보딩할지와 그 shadow-to-enforce 시퀀싱;
  OD-3이 나중에 새 backend 선택할 시 이벤트-버스 마이그레이션 경로; 메트릭 1의 크로스-CSP 비용
  귀속과 통화 정규화.

## 의존성

- 세 버티컬 모두에 걸쳐 안전 불변식이 강제되는 P3 통합 자율 MVP
  ([phase-3-integrated-loop-ko.md](phase-3-integrated-loop-ko.md)).
