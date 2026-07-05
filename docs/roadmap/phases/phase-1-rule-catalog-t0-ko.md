---
translation_of: phase-1-rule-catalog-t0.md
translation_source_sha: 95d405695343d115cebddf965924dd802d4c6fd8
translation_revised: 2026-07-05
---

# Phase 1 — 규칙 카탈로그와 T0 결정론적 엔진

**목표**: LLM 없이 이벤트의 다수를 해결하는 결정론적 코어(T0) 를 세우고, 첫 자율 버티컬 —
Change Safety — 를 완전히 **shadow 모드**(judge와 log, 실행 없음) 로 딜리버리. 이 phase는
커버리지와 측정을 구축, 강제(enforcement) 아님; enforce 승격은 범위 밖이며
[phase-2-quality-and-t1-ko.md](phase-2-quality-and-t1-ko.md) 소속.

이 phase는
[architecture.instructions.md](../../../.github/instructions/architecture.instructions.md) 에
정의된 T0 티어와 규칙 카탈로그를,
[coding-conventions.instructions.md](../../../.github/instructions/coding-conventions.instructions.md)
의 안전과 코딩 규칙, [generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md)
의 고객-비종속 범위 하에 구현. [phase-0-instrumentation-ko.md](phase-0-instrumentation-ko.md)
가 딜리버리하는 원격측정, 베이스라인, 아이덴티티/정책 언블록을 소비하고
[phase-2-quality-and-t1-ko.md](phase-2-quality-and-t1-ko.md) 로 공급.

## 범위

- **범위 내**: 규칙 카탈로그 스키마와 컬렉터, T0 결정론 엔진(policy-as-code + what-if + drift),
  shadow-mode remediation-PR 생성, Change Safety를 위한 out-of-band 변경 감지.
- **범위 밖**: 어떤 enforce-mode 실행, auto-revert, T1/T2 티어, LLM quality gate, 지속적 규칙-
  업데이트 파이프라인 — 모두 Phase 2로 연기.

## 산출물

- **규칙 카탈로그** (catalog-as-code) — 정규화된 CSP-중립 스키마 + 각 소스를 그 스키마로 매핑하는
  멀티-소스 컬렉터.
- **T0 결정론 엔진**: policy-as-code 게이트(OPA/Rego) + what-if(dry-run) + drift 감지, 모든
  이벤트에 대해 판정과 인용 규칙 id emit.
- **Shadow remediation-PR** 경로 — GitOps 딜리버리 어댑터 통해(생성되지만 머지 안 됨).
- **Out-of-band 변경 감지** — 콘솔/수동 변경, 명시적 false-positive 억제 전략과 함께.
- **픽스처와 회귀 스위트** — 초기 규칙 세트와 감지 경로 커버.

## 규칙 카탈로그

### 정규화 스키마

모든 규칙은 소스를 병합·중복제거·버전 관리할 수 있도록 공통 CSP-중립 스키마로 정규화. 필수
필드:

| 필드 | 타입 | 의미 |
|------|------|------|
| `id` | 안정 문자열 | 전역 유일, 소스 독립 규칙 아이덴티티(dedup 기반) |
| `version` | semver | 변경이 추적·역방향 가능; rule set이 규칙 버전 고정 |
| `source` | enum | 원본 카탈로그(Sources 참조) + 고정된 source-priority 랭크 |
| `severity` | enum | `critical` > `high` > `medium` > `low` (우선순위 주도) |
| `category` | enum | 도메인 그룹(예: `security`, `reliability`, `cost`, `config-drift`) |
| `resource-type` | CSP-중립 문자열 | 벤더 특이 ARM 경로가 아닌 정규화된 대상 타입 |
| `check-logic` | ref/expr | 결정론적 predicate (OPA/Rego 모듈 ref 또는 표현식) |
| `remediation` | ref | IaC/PR diff 생산하는 remediation 템플릿 |
| `provenance` | object | 소스 URL/커밋, imported-at 타임스탬프, 매핑 저자 |

`provenance` 는 감사가능성과 롤백을 위해 필수; `version` 은 나쁜 규칙 세트가 되돌려질 수 있도록
필수(Versioning 참조). 필드는 고객 식별 값을 운반하지 않음; 예시는
[generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md) 에
따라 placeholder만 사용.

### 소스

Azure WAF / AKS Baseline / MCSB / Azure Policy / Advisor, CIS Benchmarks, OPA/Gatekeeper
라이브러리, IaC 스캐너(Checkov, tfsec, KICS, Trivy), kube-bench, 정적 분석기. 각 소스는 네이티브
포맷을 정규화 스키마로 매핑하고 `provenance` 를 기록하는 컬렉터를 가짐. `resource-type` 은
CSP-중립 어휘로 정규화되어 한 프로바이더용으로 작성된 규칙이 다른 곳의 등가 리소스에 대해 평가될
수 있음; 벤더 특이는 규칙이 아니라 provider 어댑터 뒤에 유지.

각 소스가 어디 있는지, 어떻게 fetch되는지, 라이선스 제약, YAML 형상은
[rule-catalog-collection-ko.md](../rule-catalog-collection-ko.md) 에 상세.

### 중복제거, 충돌, 우선순위

여러 소스가 하나의 이벤트에 대해 겹치는 규칙을 발행하는 것은 흔함. 해결은 결정론적:

1. **`id` 로 중복제거** ; 여러 소스로부터의 동일 로직은 병합된 `provenance` 있는 하나의 규칙으로
   접힘.
2. **우선순위** — distinct 규칙이 같은 이벤트에 매칭될 때: `severity` 순으로, 다음 `source`
   priority 랭크로; 남은 tie는 더 높은 `version` 으로.
3. **미해결 tie 또는 모순 remediation** (한 규칙이 다른 규칙이 적용한 것을 되돌림) 은 auto-select
   대신 **abstain 후 HIL로 escalate** — 안전 방향으로 실패.

충돌 결과는 경쟁 규칙 id와 함께 로그되어 우선순위 결정이 감사 가능.

### 버전 관리

카탈로그는 **catalog-as-code** 로 저장; 각 승격은 rule-set 버전을 고정, 나쁜 세트는 버전으로
되돌릴 수 있음. (*지속적* 수집 → shadow-eval → 회귀 → 승격 파이프라인은 Phase 2; Phase 1은
버전된 수동 리뷰 카탈로그를 로드.)

## T0 엔진

엔진은 각 정규화·중복제거된 이벤트(post `event-ingest`) 를 평가하고 판정 + 인용 규칙 id 산출.
세 결정론 검사:

- **정책 평가** — 이벤트에 대해 `check-logic` (OPA/Rego) 과 체크리스트 실행; 매칭이 규칙 id
  있는 위반 산출.
- **What-if (dry-run)** — 후보 remediation의 예상 효과를 *적용 없이* 시뮬레이션, 위반을 해결하는지
  확인하고 blast radius(스코프, 개수, 영향받은 리소스 속도) 계산.
- **Drift 감지** — 관측된 리소스 상태를 선언된 IaC/desired 상태와 비교; drift 델타(추가/제거/
  변경된 속성) 보고.

위반 시 엔진은 직접 실행 대신 **remediation PR** emit; 감사, 롤백, 승인은 git에서 무료. Phase 1
에서 모든 판정은 **shadow only** — PR 머지 안 됨, 상태 변형 안 됨.

## Remediation PR (shadow 모드)

Phase 1에서 아무것도 머지되지 않지만, 각 생성된 PR은
[coding-conventions.instructions.md](../../../.github/instructions/coding-conventions.instructions.md)
의 네 안전 불변식을 이미 운반해야 함 — Phase 2가 승격할 때 아티팩트가 enforce-ready:

- **멱등** — 이벤트의 안정 idempotency 키에 keyed; 같은 이벤트에 재생성은 같은 diff, 절대 중복
  변경 아님.
- **롤백 경로** — PR이 이전 desired-state revision을 참조하여 변경이 단일 후속 PR로 되돌릴 수
  있음.
- **Blast-radius 제한** — what-if 계산 스코프/개수/속도가 PR에 기록되고 상한; 상한 초과 변경은
  HIL-only 표시.
- **감사 엔트리** — 모든 생성된 PR(no-op과 abstain 결과 포함) 이 append-only 감사 기록을 씀:
  이벤트 id, 티어(`T0`), 결정, 인용 규칙 id, idempotency 키, 모드(`shadow`), 롤백 참조.

PR은 `shadow` 라벨되고 draft로(또는 shadow 브랜치에 대해) 오픈되어 리뷰 가능하지만 정상 흐름으로
머지 불가.

## Out-of-Band 감지 (Change Safety)

- **신호**: Activity Log, Resource Graph, Change Analysis, Deployment Stacks deny-assignment
  이벤트, IaC drift. 단일 피드를 믿는 대신 신호 간 상관관계.
- **귀속**: 각 감지된 변경을 authorized(머지된 remediation PR / 알려진 파이프라인 principal에서
  발원) 또는 out-of-band(수동/콘솔) 로 분류, actor 아이덴티티와 correlation id 사용하여 파이프라인-
  주도 변경이 오플래그되지 않도록.
- **False-positive 컨트롤**: 궁극적으로 일관된 것과 조정 노이즈(전파 지연, provider-측 auto-heal,
  tag/system-metadata churn) 를 debounce/settling 윈도우로 억제, 변경이 out-of-band 로 선언되기
  전; 억제 사유 기록.
- **False negative**: 신호 피드는 lag하거나 드롭 가능; 감지 완전성은 측정된 가드(Exit 기준 참조),
  가정 아님.
- **응답 (shadow)**: 정책 위반 리소스의 out-of-band 변경은 *shadow* revert-or-reconcile PR과
  알림 생성; 판단·로그만. Auto-revert와 reconcile-to-IaC 실행은 Phase 2 검증까지 게이팅 오프.

## 자율성 레벨

- 모든 것이 **shadow 모드** 로 출시: 엔진은 판단하고 로그; enforce 경로 없음.
- 저위험 auto-merge/reconcile과 고위험 HIL 라우팅은 `risk-gate` 를 통해 배선되지만 Phase 2 승격
  까지 게이팅 오프.
- 이 phase에 property-level 불변식 성립: **shadow 모드는 절대 상태 변형 안 함** — PR 머지 안
  됨, 리소스 변경 안 됨, 테스트에서 단언.

## 테스트 가능성

- **픽스처** 는 정규화 규칙 스키마와 `event-ingest` 이벤트 스키마 따름; 리포 범위 규칙에 따라
  영문·시크릿 없음. Dedup과 우선순위를 실행하는 다중-소스 오버랩 픽스처, escalate해야 하는
  모순-remediation 픽스처 포함.
- **회귀 스위트** 커버: 정책 판정, what-if blast-radius 계산, drift 델타, 충돌/우선순위 해결,
  out-of-band 귀속, false-positive 억제.
- **안전-코어 커버리지**: 결정론 엔진과 `risk-gate` 경로가 coding-conventions가 요구하는 높은
  커버리지 바 충족.
- **Property 테스트**: "shadow는 절대 변형 안 함", "remediation은 멱등(재적용은 no-op)", "미해결
  규칙 충돌은 절대 auto-select 안 함".

## Exit 기준

각 기준은 서사가 아니라 Phase 0 원격측정과 시나리오 세트에 대해 측정 가능:

- Change 게이트가 고정 Phase 0 시나리오 세트에 대해 **shadow** 에서 실행되고 모든 결정 로그됨
  (이벤트 id, 티어, 판정, 인용 규칙 id, 모드).
- 규칙 카탈로그가 정의된 초기 대상 세트(소스별 열거) 를 커버하고 버전 고정; dedup/우선순위가
  픽스처 충돌 케이스를 미해결 auto-select 0으로 해결.
- Remediation PR이 생성되고, 네 안전 불변식 모두 운반하며, 리뷰 가능; shadow에서 어떤 PR도
  머지 불가.
- Out-of-band 감지가 라벨된 픽스처 세트에 대한 **precision과 recall** 을 보고, false-positive
  억제 비율 기록 — Phase 2가 회귀시키면 안 되는 감지 베이스라인 확립.
- 모든 종단 경로(위반, no-op, abstain, HIL-route) 가 감사 엔트리를 씀; 감사 완전성 단언.

## 의존성

- **Phase 0** ([phase-0-instrumentation-ko.md](phase-0-instrumentation-ko.md)): 원격측정 백본
  (이벤트 스키마, audit/state/KPI 저장소), 고정 시나리오 세트와 reference 베이스라인, 해결된
  아이덴티티/인가 및 정책-예외 블로커 ([security-and-identity-ko.md](../security-and-identity-ko.md)).
  T0 shadow 결정은 Phase 0 감사 저장소를 통해 로그; 그것 없이 exit 기준은 측정 불가.
