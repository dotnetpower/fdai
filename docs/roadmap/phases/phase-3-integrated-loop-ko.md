---
title: Phase 3 - 통합 컨트롤 루프 (Resilience · Change Safety · Cost Governance)
translation_of: phase-3-integrated-loop.md
translation_source_sha: 6e2b52cfa9b7c146b1f87f0d83b7f1901d1495b4
translation_revised: 2026-07-11
---

# Phase 3 - 통합 컨트롤 루프 (Resilience · Change Safety · Cost Governance)

**목표**: 세 초기 버티컬을 하나의 컨트롤 루프 아래 통합하고 자율-운영 MVP 딜리버리 - Resilience,
Change Safety, Cost Governance를 단일 리스크-게이팅 루프를 통해 종단으로 실행하는 첫 릴리스 -
스케줄된 DR/chaos 테스트와 비용 auto-actions 포함. 이 phase는 새 티어를 추가하지 않음;
P2에서 딜리버리된 T0/T1/T2 라우터, quality gate, 리스크 게이트
([phase-2-quality-and-t1-ko.md](phase-2-quality-and-t1-ko.md) 참조) 를 하나의 루프로
구성하고, [architecture.instructions.md](../../../.github/instructions/architecture.instructions.md)
에 정의된 안전 불변식과 컨트롤 루프 배선을 강제.

여기의 모든 RPO/RTO, 절감, lead-time 수치는 **명시된 목표에 대해 고정 시나리오 세트와 측정
윈도우에서 보고된 측정값** - 절대 추정치나 unbaselined 배수 아님
([goals-and-metrics-ko.md](../goals-and-metrics-ko.md) 참조).

## 산출물

각 산출물은 아래 섹션에 매핑. 모듈 참조는 [`src/fdai/`](../project-structure-ko.md)에서
해당 산출물을 담고 있는 주요 Python 패키지를 가리킴.

- Resilience, Change Safety, Cost Governance에 걸친 **통합 컨트롤 루프** - 하나의 `trust-router` →
  `risk-gate` → `executor` → `audit` 경로, 리소스별 순서/락과 크로스-버티컬 충돌 처리
  ([통합 컨트롤 루프](#통합-컨트롤-루프)).
  모듈: [core/control_loop.py](../../../src/fdai/core/control_loop.py),
  [core/risk_gate/precedence.py](../../../src/fdai/core/risk_gate/precedence.py).
- 윈도우-기반 테스트 failover / game day, 딥 DB-DR 처리, 측정된 RPO/RTO 보고 있는 **DR/Chaos
  스케줄러** ([#dr--chaos--스케줄된-주기-테스트](#dr--chaos--스케줄된-주기-테스트)).
  모듈: [core/verticals/resilience.py](../../../src/fdai/core/verticals/resilience.py).
- Remediation PR로 딜리버리되는 리스크-게이팅 자율성 있는 **FinOps auto-actions**
  ([FinOps](#finops)).
  모듈: [core/verticals/finops.py](../../../src/fdai/core/verticals/finops.py).
- 저위험 auto-merge/reconcile, 고위험 HIL 로의 **통합 Change Safety**
  ([Change Safety](#change-safety-integrated)).
  모듈:
  [core/verticals/change_safety.py](../../../src/fdai/core/verticals/change_safety.py).
- **어슈어런스 트윈 (ambient + 시뮬레이션)** - 변경 이벤트에서의 선제적 변경별 리뷰,
  Change Safety(blast radius) · Resilience(RPO/RTO replay) · Cost Governance(비용 델타)가
  공유하는 그래프 전체 what-if, shadow remediation-PR 제안, 그리고 온디맨드
  `PostureAssessmentReport` 패널. 설계는 [assurance-twin-ko.md](../assurance-twin-ko.md);
  각 시뮬레이션 finding은 enforce 전에 shadow-first로 측정.

## 통합 컨트롤 루프

- **단일 경로**: 모든 도메인 이벤트는 `event-ingest` 에서 정규화되고 공유 `trust-router` 로
  라우팅되며 `executor` 가 액션하기 전에 같은 `risk-gate` 를 통과. 도메인은 규칙과 아이덴티티에서
  다름, 루프 구조가 아님.
- **버티컬별 아이덴티티**: Resilience, Change Safety, Cost Governance는 각각 자체 액션 화이트리스트에
  범위된 **별개 user-assigned Managed Identity** 하에 실행, blast radius가 버티컬로 bound되고 어떤
  버티컬도 다른 버티컬의 아이덴티티를 assume할 수 없음 ([security-and-identity-ko.md](../security-and-identity-ko.md)).
- **순서와 락**: 같은 리소스를 변형하는 액션은 리소스별 키에 직렬화; `executor` 는 액션 윈도우
  전체에 대해 리소스별 락 보유. 한 리소스의 동시 변형은 도메인 간 상호 배제.
- **크로스-버티컬 충돌 처리**: 두 버티컬이 같은 윈도우에 같은 리소스를 대상으로 할 때(예:
  비용 idle-shutdown vs DR failover rehearsal, 변경 reconcile vs rightsizing PR),
  루프는 **Resilience safety hold > Change Safety > Cost Governance** 우선순위로 해결; 낮은 우선순위 액션은
  연기·재평가되거나 안전하게 연기될 수 없으면 HIL로 escalate. 충돌은 절대 racing으로 해결되지 않음.
- **멱등**: 모든 P3 액션은 안정 idempotency 키를 사용; 재전달된 이벤트와 재시도된 액션은 이미
  적용된 상태에서 no-op.
- **감사**: 모든 종단 결과 - auto-apply, HIL approve/reject/timeout, defer, abstain, 모든 스케줄
  DR 실행과 FinOps 액션 - 이 이벤트 id, 도메인, 티어, 결정, 아이덴티티, 모드(shadow/enforce),
  롤백 참조 있는 append-only 감사 엔트리를 씀.
- **Shadow first**: 각 새 P3 액션(DR 실험 타입, FinOps 액션, 크로스-도메인 규칙) 은 **shadow
  모드**(judge-and-log, 변형 없음) 로 출시되고 정책 위반 escape 0으로 측정된 검증 후에만
  액션별로 enforce로 승격.

## DR / Chaos - 스케줄된 주기 테스트

- **윈도우-기반 스케줄러**: DR failover와 Chaos 실험을 승인된 유지 윈도우(테스트 failover /
  game day) 안에서만 실행. 스케줄러는 **freeze/quiet 기간** 과 리소스별 **opt-out 태그** 존중,
  **동시 실험** 상한(blast-radius limit), 각 실행 전후 운영자 알림.
- **RPO/RTO 보고**: 각 실행에 대해 명시된 목표 대비 **측정된 RPO** (failover 데이터 손실) 와
  **측정된 RTO** (복원된 서비스까지 wall-clock) 를 실행에 대한 median과 p90으로 고정 측정 윈도우에
  보고 ([goals-and-metrics-ko.md](../goals-and-metrics-ko.md)). RPO/RTO가 목표를 위반한 실행은
  조용히 평균되지 않고 플래그.

### DR 안전 불변식 (모든 실험)

각 실험 경로는 네 불변식 모두 충족해야 함, 아니면 출시 안 됨
([architecture.instructions.md](../../../.github/instructions/architecture.instructions.md)):

- **Stop-condition**: 실험을 auto-halt하는 명시적 abort 트리거(헬스 프로브 실패, 에러율/지연
  임계, 실행 시간 박스 초과).
- **Blast-radius limit**: 스코프, 배치 크기, 동시성 상한; 실험은 bounded 리소스 세트 대상,
  한 번에 전체 환경 아님.
- **Rollback**: stop 또는 실패 시 이전 상태 복원하는 테스트된 자동 롤백; 롤백은 enforce 전
  shadow에서 실행.
- **Isolation**: 프로덕션은 절대 chaos 대상 아님 - 실험은 non-prod 또는 격리된 복원 환경에 대해
  실행(Deep DB-DR 참조). 프로덕션 리소스의 chaos는 기본 거부, 불가피한 곳에서는 HIL 승인 +
  명시적 격리 필요.

### Deep DB-DR (stateful - 전용 설계)

Stateful 서비스는 stateless처럼 "kill and revive" 될 수 없으므로, DB-DR은 라이브 프로덕션 DB가
아니라 격리된 사본에서 실행.

- **Replication/backup**: point-in-time restore (PITR / continuous restore), geo-replication
  (active geo-replication / read replica), 주기 backup-restore rehearsal.
- **테스트 방법** (모든 스텝 필요, 순서대로):
  1. **격리 환경으로 restore** - replica/snapshot을 프로덕션으로 write path 없는 네트워크-격리
     환경으로 restore; 테스트 후 환경 tear down.
  2. **결정론적으로 무결성 검증** - verifier가 소스 스냅샷 대비 row/record 카운트, 암호화 컨텐트
     체크섬, referential/constraint 일관성 검사; 어떤 mismatch도 실행 실패.
  3. **앱-레벨 smoke 테스트** - 복원된 사본에 대해 대표 read와 write 작업 실행하여 애플리케이션-
     레벨 복구 가능성 확인.
- **RPO 방법론**: replication lag를 지속 측정(p50/p95/max 보고), forced-failover rehearsal에서
  failover 시점의 **실제 데이터 손실** 측정; 둘 다 같은 윈도우에서 RPO 목표와 비교.
- **RTO 방법론**: **failover 트리거부터 검증된 복원 서비스까지 wall-clock** 측정(restore +
  failover + integrity pass + smoke pass); median과 p90 보고, RTO 목표와 비교. Large-DB
  restore RTO는 가정이 아니라 측정.
- **승격 게이트**: DB-DR은 무결성 검증과 smoke 테스트가 시나리오 세트에서 무결성 mismatch 0으로
  통과할 때까지 shadow에 유지.

## FinOps

- **트리거**: 비용 이벤트 / 이상(네이티브 이상 감지가 후보를 루프에 표면화).
- **라우팅과 자율성**: 후보 액션(idle shutdown, rightsizing, spot/autoscale) 은 공유
  `trust-router` 로 라우팅되고 `risk-gate` 게이팅 - **non-prod, 저위험 액션은 auto-execute;
  프로덕션-영향 액션은 HIL**.
- **딜리버리**: 액션은 **remediation PR** (GitOps) 로 딜리버리, 감사·리뷰·롤백이 git에서 옴 -
  out-of-band API 변형 아님.
- **가드레일** (모든 FinOps 액션에 필요):
  - **exclusion/opt-out 태그** 존중, 자동 scale-down이나 shutdown으로부터 **프로덕션** 리소스
    보호;
  - **최소-용량 floor** 와 **의존성 검사** 준수 - shutdown이 의존 워크로드를 고아로 만들 수 없음;
  - **멱등** 이고 **가역** (shut-down된 리소스는 재시작 가능; rightsizing PR은 revert 가능);
  - **stop-condition**(예상치 못한 영향 시 abort) 과 **감사 엔트리** 운반.
- **결과**: 단위-비용 가시성 + 저위험 액션에 대한 자동 절감 루프; 보고된 절감은 **측정** 값,
  projected 아님.

## Change 관리 (통합)

- 저위험 변경은 **auto-merge/reconcile**; 고위험은 **HIL** 로 이동, 사람이 승인·거부·요청 timeout
  (reject와 timeout은 여전히 감사하는 no-op). 승인과 실행은 별개 principal 유지
  ([security-and-identity-ko.md](../security-and-identity-ko.md)).
- **Change lead time** 은 같은 시나리오 세트에서 P0 reference agent 대비 **측정** 감소로 보고
  (median과 p90), [goals-and-metrics-ko.md](../goals-and-metrics-ko.md) 에 따라 - unbaselined
  "주 단위 → 시간 단위" 주장 없음.

## 테스트 가능성

- 각 도메인의 `risk-gate` 라우팅과 크로스-도메인 우선순위/연기 로직 단위 테스트; 불변식
  "high-risk는 절대 auto-execute 안 함", "shadow 모드는 절대 변형 안 함", "액션 재적용은 no-op",
  "한 리소스의 동시 액션은 직렬화" property 테스트.
- 모든 P3 액션 경로는 **shadow-mode 테스트**(변형 없이 판단·로그) 와 **rollback 테스트**(롤백이
  이전 상태 복원) 가짐; DB-DR은 픽스처 스냅샷에 **integrity-verification 회귀 테스트** 추가.
- DR 스케줄, FinOps 후보, 규칙 엔트리 픽스처는 영문·시크릿 없음, 정규화 규칙 스키마 따름
  ([coding-conventions.instructions.md](../../../.github/instructions/coding-conventions.instructions.md)).

## Exit 기준

각 기준은 고정 시나리오 세트와 측정 윈도우에서 측정 가능
([goals-and-metrics-ko.md](../goals-and-metrics-ko.md)):

- 자율 MVP가 세 버티컬 모두에 걸쳐 네 안전 불변식 강제와 **정책 위반 escape 0** 으로 운영.
- DR/Chaos가 승인된 윈도우 내 스케줄에 실행, 목표 대비 측정된 RPO/RTO(median과 p90) 보고, 자동
  롤백 검증됨.
- Deep DB-DR이 restore-into-isolated-env를 **무결성 mismatch 0** 과 앱-레벨 smoke 테스트 통과로
  완료; 프로덕션 DB는 절대 chaos 대상 아님.
- FinOps가 저위험 액션에 대해 측정된 절감으로 자동 절감 루프 폐쇄, 가드레일 강제, 프로덕션 리소스
  자동 수정 없음.
- 공유 리소스의 크로스-도메인 충돌이 우선순위/락으로 이중 변형 없이 해결, **가드 메트릭이 P0
  베이스라인 대비 회귀 안 함**.

## Open Questions (각각 소유자 필요)

- 안전 failover 윈도우와 large-DB restore RTO 목표 - 소유자: DR/Chaos 리드.
- 초기 risk-classification 정책(auto vs HIL) 과 크로스-도메인 우선순위 튜닝 - 소유자: risk-gate/
  정책 소유자.
- Freeze/quiet-period 캘린더와 game-day opt-out 거버넌스 - 소유자: 운영 소유자.

## 의존성

- **P2가 검증되어야 함** ([phase-2-quality-and-t1-ko.md](phase-2-quality-and-t1-ko.md)): LLM
  quality gate (T2 방어), T1 경량 티어, 지속적 규칙-업데이트 파이프라인이 shadow에서 실행되고
  측정되어야 함. P3는 이들을 하나의 루프로 구성하며 신뢰할 만해질 때까지 시작할 수 없음.
- P3 RPO/RTO, 절감, lead-time 수치가 reference 대비 비교되도록 P0 베이스라인 존재.
- **P4** ([phase-4-scale-ko.md](phase-4-scale-ko.md)) 로 공급: 통합 자율 MVP가 Azure 베이스라인
  에서 지속 측정, 패턴-라이브러리 성장, 모델 추적을 위한 P4의 시작점. **멀티 클라우드 확장은
  TBD**
  ([Implementation Focus](../../../.github/copilot-instructions.md#implementation-focus-must)
  참조).
