---
translation_of: README.md
translation_source_sha: 55624c5ac5d1302f6c9ef97989700b55f6409edf
translation_revised: 2026-07-05
---

# AIOpsPilot 로드맵

자율 클라우드 운영 컨트롤 플레인을 구축하기 위한 단계별 상세 계획 — **AIOps** 접근이며
초기 버티컬은 **Resilience**, **Change Safety**, **Cost Governance** 입니다. 다른 AIOps
도메인(posture management, SRE/SLO 등)도 같은 아키텍처에 맞으며 향후 범위입니다. 이 폴더는
[copilot-instructions.md](../../.github/copilot-instructions.md) 의 요약 원칙과
[architecture.instructions.md](../../.github/instructions/architecture.instructions.md) 의
컨트롤 루프 설계를, 목표·구조부터 배포·스케일-아웃까지 이어지는 실행 가능한 엔지니어링
로드맵으로 확장합니다.

> 범위 안내: 이 저장소는 **범용이며 고객-비종속(customer-agnostic)** 입니다. 여기의
> 모든 것은 파라미터화되어 있으며, 고객별 값은 포크에 있습니다.
> [generic-scope.instructions.md](../../.github/instructions/generic-scope.instructions.md)
> 를 참조하세요.
>
> **구현 초점:** Azure가 유일한 구현 대상입니다. 비-Azure 프로바이더와 Phase 4의
> 멀티 클라우드 확장은 **TBD** 입니다 — 이 문서들의 CSP-중립 추상화는 향후 어댑터가
> 추가적으로 붙을 수 있게 하기 위한 것이지, 납품 약속이 아닙니다.
> [copilot-instructions.md](../../.github/copilot-instructions.md#implementation-focus-must)
> 를 참조하세요.

## 이 폴더 읽는 법

레퍼런스 문서(1–13)는 시스템을 설명하고, 페이즈 문서(P0–P4)는 빌드 순서를 정합니다.
레퍼런스를 먼저 읽고 페이즈를 순서대로 읽으세요.

| # | 문서 | 다루는 내용 |
|---|------|-------------|
| 1 | [goals-and-metrics-ko.md](goals-and-metrics-ko.md) | 성공 기준, KPI, 측정 우선 규칙 |
| 2 | [project-structure-ko.md](project-structure-ko.md) | 저장소 레이아웃, 모듈 경계, 컨트롤 루프 배선 |
| 3 | [tech-stack-ko.md](tech-stack-ko.md) | 언어, 프레임워크, 데이터 저장소, 이벤트 버스 |
| 4 | [csp-neutrality-ko.md](csp-neutrality-ko.md) | 코어를 CSP-중립으로 유지하는 와이어 수준 계약 (이벤트버스 / 런타임 / 시크릿 / 워크로드 아이덴티티) |
| 5 | [llm-strategy-ko.md](llm-strategy-ko.md) | 티어별 모델 선택, mixed-model 게이트, 추상화 |
| 6 | [security-and-identity-ko.md](security-and-identity-ko.md) | 최소권한 아이덴티티, 시크릿, 안전 불변식 |
| 7 | [deployment-ko.md](deployment-ko.md) | IaC, CI/CD, 환경, 릴리스/롤백 |
| 8 | [rule-catalog-collection-ko.md](rule-catalog-collection-ko.md) | 규칙/체크리스트/베이스라인의 출처와 YAML 스키마 |
| 9 | [rule-governance-ko.md](rule-governance-ko.md) | 관리자가 규칙을 작성·범위 지정·활성화·예외 처리하는 방법 (Azure Policy-유사) |
| 10 | [observability-and-detection-ko.md](observability-and-detection-ko.md) | 이벤트 상관관계, 이상 감지, 예측, 근본원인 분석 |
| 11 | [deploy-and-onboard-ko.md](deploy-and-onboard-ko.md) | 구체적인 Azure 리소스 인벤토리, 부트스트랩 순서, 포크 ↔ 코어 분리 |
| 12 | [startup-and-lifecycle-ko.md](startup-and-lifecycle-ko.md) | 콜드 스타트, 첫날 카탈로그, shadow-first 롤아웃, 디스커버리 루프 시동 |
| 13 | [operating-and-verification-ko.md](operating-and-verification-ko.md) | 자체 헬스 신호, 카나리 이벤트, 스모크 테스트, 알림 라우팅, 런북 |
| 14 | [cost-model-ko.md](cost-model-ko.md) | 최소 리소스 인벤토리 기준 예시 월간 비용 범위, T2 LLM 비용 분해, 트래픽 스케일링 트리거 |
| 15 | [user-rbac-and-identity-ko.md](user-rbac-and-identity-ko.md) | 사람 사용자 롤(Reader/Contributor/Approver/Owner + Break-Glass), Entra ID 아티팩트, 콘솔→PR 아이덴티티 흐름 |
| 16 | [channels-and-notifications-ko.md](channels-and-notifications-ko.md) | 비-웹-UI 채널(Teams / Slack / email / webhook / pager / SMS), 카테고리 & 신뢰 티어 매트릭스, 라우팅 정책 |
| 17 | [risk-classification-ko.md](risk-classification-ko.md) | auto vs HIL vs deny 분류: 차원, 초기 규칙 테이블, 환경 감지, 변경 프로세스 |

## 설계 한눈에 보기

결정론적 우선(deterministic-first), 이벤트-기반, 리스크-게이팅. 3-티어 신뢰 라우터는
규칙과 정책으로(T0) 반복 가능한 이벤트를 해결하고, 경량 유사도 재사용(T1)으로 처리하며,
프론티어 모델 추론(T2)은 모호한 잔여에만 사용합니다. T0/T1 커버리지 비율과 모든 자율성
배수는 **주장 가능해지기 전에 측정된 베이스라인이 필요한 설계 목표**입니다
([goals-and-metrics-ko.md](goals-and-metrics-ko.md) 와
[architecture.instructions.md](../../.github/instructions/architecture.instructions.md)
참조).

## 페이즈 타임라인

```mermaid
timeline
    title AIOpsPilot Delivery Phases
    P0 Instrumentation : KPI telemetry : Baseline vs reference agent : Unblock identity and policy
    P1 Rule Catalog and T0 : Normalize checklists : Policy-as-code gate : Auto remediation PR : Out-of-band detection
    P2 Quality and T1 : Continuous rule update : LLM quality gate and mixed-model : Embedding pattern reuse : Shadow to enforce
    P3 Integrated Loop : Unified control loop : DR-Chaos scheduler and DB DR : FinOps auto-actions
    P4 Scale : Continuous measurement : Pattern-library and model tracking : Scalability : Multi-cloud expansion (TBD)
```

페이즈는 **엄격한 순차 진행** 입니다 — P0 → P1 → P2 → P3 → P4 — 각 페이즈 문서는
*Dependencies* 섹션에서 선행 페이즈를 명시합니다. 버티컬 커버리지는 점진적으로 도착합니다:
Change Safety는 P1, Resilience와 Cost Governance는 P3. **P4의 멀티 클라우드는 TBD**
입니다 (Azure만 구현 대상 —
[Implementation Focus](../../.github/copilot-instructions.md#implementation-focus-must)
참조).

## 페이즈 요약

Exit 컬럼은 각 페이즈의 **주요 게이트** 입니다. 완전한 exit 기준과 의존성은 각 페이즈
문서에 있습니다.

| 페이즈 | 목표 | 핵심 산출물 | 주요 exit 게이트 |
|--------|------|-------------|------------------|
| **[P0](phases/phase-0-instrumentation-ko.md)** | 계측 & 언블록 | KPI 대시보드, 베이스라인 리포트, 아이덴티티/정책 블로커 해소 | 재현 가능한 베이스라인 존재 |
| **[P1](phases/phase-1-rule-catalog-t0-ko.md)** | 결정론적 코어 | 규칙 카탈로그, T0 엔진, 정책 게이트, 리메디에이션 PR | Change 게이트가 shadow에서 실행 |
| **[P2](phases/phase-2-quality-and-t1-ko.md)** | 품질 & 경량 티어 | 규칙-업데이트 파이프라인, LLM 품질 게이트(T2 방어), T1 유사도 재사용 | 자동 해결률이 P0 베이스라인 대비 검증됨 |
| **[P3](phases/phase-3-integrated-loop-ko.md)** | 통합 자율성 | 통합 루프, DR/chaos 스케줄러, 비용 auto-actions | 3개 버티컬에 걸친 자율 MVP |
| **[P4](phases/phase-4-scale-ko.md)** | 스케일 아웃 (Azure) | 지속 측정, 패턴 라이브러리와 모델 추적, 확장성; **멀티 클라우드 어댑터 TBD** | Azure 베이스라인에서 가드 메트릭 안정 |

## 전 구간에 적용되는 가드레일

- **측정 우선**: 원격측정 없이 자율성 없음. 측정된 베이스라인 없이 배수·커버리지 주장 없음.
- **enforce 전 shadow**: 모든 신규 액션은 judge-only로 출시되고, 액션별로 명시적 승격. 회귀는 자동 강등.
- **안전 방향으로 실패**: 낮은 신뢰도, 검증 실패, 예산/속도 초과는 HIL로 강등 — 게이트 없는 auto-action으로 절대 강등하지 않음.
- **모든 액션의 안전 불변식**: stop-condition, rollback path, blast-radius limit, audit-log entry ([security-and-identity-ko.md](security-and-identity-ko.md)).
- **멱등 액션(idempotent)**: 재전달된 이벤트와 재시도된 액션은 절대 이중 적용되지 않음.
- **직무 분리(separation of duties)**: 승인과 실행은 별개의 주체(principal). 콘솔은 읽기 전용 ([security-and-identity-ko.md](security-and-identity-ko.md)).
- **영문-only, 고객-비종속 아티팩트** ([generic-scope.instructions.md](../../.github/instructions/generic-scope.instructions.md)); 한국어는 유지관리자 채팅과 `-ko.md` 번역 파일에만.
