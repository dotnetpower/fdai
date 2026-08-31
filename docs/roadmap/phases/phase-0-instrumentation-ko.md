---
title: Phase 0 - 계측과 언블록
translation_of: phase-0-instrumentation.md
translation_source_sha: d27edcb3739c707d6c16f1d8ca4706f255b6f974
translation_revised: 2026-08-31
---

# 단계 0 - 계측과 언블록

**목표**: 측정을 확립하고 어떤 자율성도 출시되지 못하게 막을 블로커를 제거. P0에서 자율성은
구축되지 않음 - 이 단계는 자율성을 *측정 가능하게* 하고 *정책 준수* 하게 만듦. P0는 이후
단계들이 이득을 증명할 기준 베이스라인을 **확립** ; 자체로는 어떤 개선 배수도 주장하지 않음.

이 단계는 [goals-and-metrics-ko.md](../architecture/goals-and-metrics-ko.md) 를 운영으로 구현하고
[security-and-identity-ko.md](../architecture/security-and-identity-ko.md) 에 추적된 P0 아이덴티티/정책
블로커를 해결. 출력은 [phase-1-rule-catalog-t0-ko.md](phase-1-rule-catalog-t0-ko.md) 의 직접
전제조건.

## 재사용 용어

여기서 도메인 용어를 재정의하지 않음. `Event`, `Scenario set`, `Reference agent`,
`Human touchpoint`, `Auto-resolved event`, `Measurement window` 는
[goals-and-metrics-ko.md#정의definitions](../architecture/goals-and-metrics-ko.md#정의definitions) 에서
한 번 정의; 이 단계는 그 정의를 그대로 사용.

## 산출물

각 산출물은 수용 검사 있는 커밋·버전된 아티팩트. 산출물과 [작업 Items](#work-items) 은 번호로
1:1 매핑.

| # | 산출물 | 수용 검사 |
|---|--------|----------|
| 1 | **원격측정 백본** - OpenTelemetry 배선 + 감사/상태/KPI 저장소 + `shared/contracts/` 의 버전된 이벤트 스키마 ([project-structure-ko.md](../architecture/project-structure-ko.md)). | 스키마가 CI에서 검증; 잘못된 입력에 구성이 fail fast; golden-fixture 테스트가 기록된 원격측정에서 모든 대시보드 메트릭을 재현. |
| 2 | **KPI 대시보드** - 성공 메트릭 1-4, 모든 가드 메트릭, 선행 지표 렌더링 ([goals-and-metrics-ko.md#선행-vs-후행-지표leading-vs-lagging-indicators](../architecture/goals-and-metrics-ko.md#선행-vs-후행-지표leading-vs-lagging-indicators)), 각각 이름 있는 원격측정 소스로 추적. | 모든 패널이 소스(추적, 감사 로그, 비용 기록)에 매핑; 어떤 패널도 수동으로 채워지지 않음. |
| 3 | **베이스라인 리포트** - 고정된 시나리오 세트에서 측정된 pinned 참조 에이전트, 방법론과 원시 카운트 있는 커밋된 아티팩트로 기록. | 재현 가능: 같은 시나리오 세트 버전에서 pinned 에이전트 재실행이 보고된 신뢰구간 내 수치 산출. |
| 4 | **아이덴티티 매핑** - 프로비저닝된 외부 IdP ↔ Entra ↔ Managed Identity 경로 ([security-and-identity-ko.md#인가-모델authorization-model](../architecture/security-and-identity-ko.md#인가-모델authorization-model)). | 종단 경로가 자동 최소권한 프로브 통과; deny-by-default 검증; 접근 재인증 스케줄. |
| 5 | **정책 예외 워크플로** - 준수하는 자율 배포를 위한 요청 가능, time-boxed, 감사, 소유자 승인된 예외 경로. | 워크플로가 소유자와 SLA로 문서화; 예행 실행 요청이 감사 하에 부여·만료, 어떤 컨트롤도 우회하지 않음. |
| 6 | **로컬 개발 프리셋** - `services/core-control-plane/src/fdai/shared/providers/` 의 저장소 / event-bus / 시크릿 / workload-identity 프로바이더 인터페이스, 오프라인 유닛 테스트 + 디버그 용 in-memory 페이크 페어, 리어-레벨 통합 테스트용 **pgvector + Redpanda** Docker Compose (`infra/local/`) 프리셋. [tech-stack-ko.md § 로컬 개발](../architecture/tech-stack-ko.md#로컬-개발) 의 로컬-개발 계약과 [project-structure-ko.md § 주입 가능한-seams](../architecture/project-structure-ko.md#주입-가능한-seams) 의 DI 경계 을 실현. | Docker 없이 `pytest` 가 in-memory 페이크로 green; `scripts/deployment/local/dev-up.sh` 가 `pgvector/pgvector:pg16` + `redpandadata/redpanda` 컨테이너를 건강하게 울림; **동일 계약-테스트 스위트** 가 페이크와 Compose 스택 모두에 대해 통과. |

## 작업 Items

순서가 의존성 인코딩. 항목 1, 2, 5, 6은 병렬 진행 가능; 항목 3은 항목 2(시나리오 freeze) 완료
전 **시작해선 안 됨**; 항목 4는 critical 경로이며 첫날 시작.

1. **원격측정 백본**: OpenTelemetry 배선, 감사/상태/KPI 저장소
   ([tech-stack-ko.md](../architecture/tech-stack-ko.md)), 최소 `event_id`, `tier`, `decision`, `mode`
   (shadow/강제 적용), detect/해석 타임스탬프를 운반하는 `shared/contracts/` 의 버전된
   이벤트 스키마.
2. **시나리오 세트**: 복원력, 변경 안전성, 비용 거버넌스 시나리오 고정 세트를
   정의하고 **freeze** , 세 버티컬에 걸쳐 균형,
  [goals-and-metrics-ko.md#정의definitions](../architecture/goals-and-metrics-ko.md#정의definitions)
   포맷에 매칭되는 버전(예: `v2026.07`) 태그, 고객-비종속 데이터로 저장. 고정 세트는
   베이스라인과 트리트먼트에 동일 사용.
3. **베이스라인 측정**: **pinned** 참조 에이전트(single-model, no tiering)를 명시된 측정
   윈도우 동안 고정 시나리오 세트에서 실행; 성공 메트릭 1-4 **와** 모든 가드 메트릭(CFR,
   false-positive, false-negative, 롤백, policy-violation escape) 기록하여 이후 단계가
   성공뿐 아니라 가드 베이스라인도 가짐. 각 수치를 표본 크기, 신뢰구간, 시나리오 세트 버전과
   함께 보고.
  관측 기록은 계층, 지연 시간, 모델 호출, 토큰, priced 또는 unpriced 비용, abstention,
  검증기 결과도 포함합니다. 보고는 T0/T1/T2 economics를 집계합니다.
  `--require-release-eligible`은 measured 시나리오 30개 미만, 불완전한 텔레메트리, 라우팅
  quality 0.98 미만, T2 share 0.15 초과, abstention 또는 검증기 실패 0.15 초과,
  policy-violation escape 발생 중 하나라도 있으면 release를 차단합니다.
4. **아이덴티티 블로커**: 외부 IdP ↔ Entra ↔ Managed Identity 매핑 프로비저닝 및 테스트;
   최소권한 프로브로 검증 및 재인증 스케줄. 완료를
   [security-and-identity-ko.md#open-decisions](../architecture/security-and-identity-ko.md#open-decisions)
   의 P0 행에 연결.
5. **정책 블로커**: 정책 예외 워크플로(요청 가능, time-boxed, 감사, 소유자 승인) 정의 -
   자율 배포가 플랫폼 정책을 우회하지 않고 준수 유지; 소유자와 SLA 할당.
6. **로컬 개발 프리셋**: 프로바이더 인터페이스(상태 저장소, 이벤트 버스, 시크릿,
   워크로드 신원)를 공개하고 각각 **두** 개 구현을 계약 뒤에 함께 출시 - 유닛 테스트/
   디버거 세션용 in-memory 페이크(Docker 불필요)와 리어-레벨 통합 테스트용 Docker Compose
   프리셋(pgvector + Redpanda). 동일한 계약-테스트 스위트가 둘 다에 대해 실행되므로 페이크가
   실제 백엔드에서 표류 불가.

## 구현 계획

위 각 작업 항목은 구체적 엔지니어링 태스크 세트로 확장. 태스크 ID는 안정 (`Wx.y`) - 시퀀싱
다이어그램과 상태 추적이 균일하게 참조. 크기는 대략 용량 신호(**S** ≤ 1일, **M** 2-5일,
**L** 1-2주); 실제 경과 시간은 병렬성에 따라 다름.

모든 태스크는 **shadow-first** 로 랜딩
([architecture.instructions.md § Shadow → 강제 적용 승격](../../../.github/instructions/architecture.instructions.md#safety-invariants));
P0에는 enforce-mode 능력이 범위에 없음.

### W1.2 생성 계약 결정

**초기 설계.** 백엔드 서비스 5개용 Python 모델과 FDAI Console용 TypeScript 인터페이스를
생성하기 위해 대상 언어마다 외부 생성기를 추가합니다.

**비판.** 외부 생성기 두 개를 사용하면 공급망 계약과 서식 계약도 두 개가 되며, 어느 생성기도
두 번째 와이어 기준 정보가 되어서는 안 됩니다. Python만 생성하면 이 비용을 피할 수 있지만
Console이 지원 언어 계약에서 제외됩니다.

**개정 설계.** JSON Schema Draft 2020-12를 유일한 와이어 기준 정보로 유지합니다. 저장소가
소유하는 `generate_service_contracts.py` 버전 `1.0.0`은 `compatibility-manifest.json`에 선언된
서로 다른 모든 N 및 N-1 생산자 스키마를 다음 읽기 전용 타입으로 결정론적으로 변환합니다.

| 언어 | 소비자 | 생성 아티팩트 |
|------|--------|--------------|
| Python | Core 컨트롤 플레인, Operator 서비스, Document Ingestion API, Document Processing Worker, Isolated Executor | `packages/service-contracts/src/fdai_service_contracts/generated/contracts.py` |
| TypeScript | FDAI Console | `console/src/generated/service-contracts.ts` |

`packages/service-contracts/contract-generation.json`은 생성기 버전, 소스 체크섬, 스키마 선택,
출력 및 소비자를 고정합니다. CI는 오프라인 `--check` 명령을 실행하고 깨끗한 재생성 결과가
다르면 실패하므로 생성 파일을 직접 편집하지 않습니다. 기존 N/N-1 매니페스트 게이트는 같은
메이저 버전의 호환성을 깨는 스키마 변경을 계속 차단하며 모든 생산자-소비자 조합을 분류하도록
요구합니다. 생성 타입에는 검증, 승인, 변경 또는 실행 권한이 없습니다.

### WI1 - 원격측정 백본

| 작업 | 제목 | Deps | 산출물 | 수용 | 크기 |
|------|------|------|--------|------|------|
| **W1.1** | 다중 서비스 workspace skeleton | - | [다중 서비스 저장소 레이아웃](../architecture/multi-service-repository-layout-ko.md)의 서비스 소유 Python 배포판 5개, 공유 서비스 계약 SDK, 루트 workspace lockfile, `infra/`, `policies/`, `.github/` | CI가 서비스 및 모듈 의존성 방향을 강제 | S |
| **W1.2** | 온톨로지 + 이벤트 계약 | W1.1 | 기준 Draft 2020-12 스키마, 서비스 5개용 생성 Python 타입, Console용 생성 TypeScript 타입 | CI가 생성 결과 표류와 같은 메이저 버전의 호환성을 깨는 N/N-1 변경을 차단하며, 새 메이저 버전에는 명시적 호환성 및 이행 근거가 필요 | M |
| **W1.3** | 구성 스키마 + fail-fast 로더 | W1.1 | `services/core-control-plane/src/fdai/shared/config/schema.json` + Python 로더; env + 파일 프로바이더 | 잘못되거나 누락된 필수 필드가 구조화된 에러로 시작 중단 | S |
| **W1.4** | OpenTelemetry 배선 | W1.1 | `services/core-control-plane/src/fdai/shared/telemetry/` traces, metrics, logs; `correlation_id` 있는 JSON-구조화 로그; `infra/` 의 수집기 구성 | 합성 이벤트가 하나의 상관관계 id로 종단 추적 (ingest → 계층 → 게이트 → 감사) | M |
| **W1.5** | PostgreSQL DDL - 인스턴스 + 감사 | W1.2 | `ontology_object_type`, `ontology_link_type`, `ontology_resource`, `ontology_finding`, `ontology_link`, `audit_log`(hash-chain) 마이그레이션 | `flyway`/`alembic` 마이그레이션이 빈 DB에서 클린 실행; DDL이 [llm-strategy-ko.md § 온톨로지 Storage 배치](../architecture/llm-strategy-ko.md#ontology-storage-layout) 와 매칭 | M |
| **W1.6** | PostgreSQL DDL - 계층 캐시 | W1.5 | `learned_action`, `ontology_embedding`(pgvector), TTL, 카탈로그 상태, 레지스트리 및 로테이션 증적을 포함한 명시적 `t2_cache` 파티션 마이그레이션 | pgvector와 HNSW가 계속 활성화되고 로컬 PostgreSQL에서 승격, 만료, 롤백, 중복, 실패, 동시성 및 범위가 제한된 인덱스 적중/누락 검사가 통과 | S |
| **W1.7** | CI 기준선 파이프라인 | W1.1 | `.github/workflows/`: format, lint, ASCII 식별자/경로 및 punctuation 검사, translation/카탈로그 동등성, 시크릿 검사, 커버리지 게이트, 의존성 감사 | 실패한 검사가 머지 블록; 한국어와 영어 natural-language 텍스트는 모두 허용 | M |
| **W1.8** | Golden-fixture 메트릭 테스트 | W1.4, W1.5 | `services/core-control-plane/tests/telemetry/` - 기록된 합성-이벤트 추적 + 픽스처가 모든 대시보드 메트릭이 원격측정에서 재현되는지 단언 | CI에서 green; 추적 속성 제거가 특정 메트릭 단언 실패 | M |
| **W1.9** | KPI 대시보드 | W1.4, W1.5, W1.8 | 성공 1-4, 가드 메트릭, 선행 지표 패널 - 각각 원격측정-소스 주석 | 어떤 패널도 수동으로 채워지지 않음; 소스 이름 변경이 패널 빌드 검사 실패 | M |

### WI2 - 시나리오 세트 (freeze)

| 작업 | 제목 | Deps | 산출물 | 수용 | 크기 |
|------|------|------|--------|------|------|
| **W2.1** | 시나리오 스키마 | W1.2 | `services/core-control-plane/tests/scenarios/schema.json` - 이벤트 입력, 예상 판정, 도메인, 태그 | 스키마가 CI에서 검증; 알려지지 않은 도메인/판정 값은 거부 | S |
| **W2.2** | 균형 시나리오 작성 | W2.1 | `services/core-control-plane/tests/scenarios/v2026.07/` - 변경 / DR / FinOps 균형 합성 이벤트(도메인당 목표 ≥ N, `N` 은 작성 시 결정) | CI에서 균형 검사: 어떤 도메인도 평균 카운트에서 10% 초과 편차 없음 | M |
| **W2.3** | Freeze + 버전 | W2.2 | 디렉토리 `services/core-control-plane/tests/scenarios/v2026.07/` 가 브랜치 보호로 **불변** ; 새 세트는 새 버전 디렉토리 | CI가 기존 버전 디렉토리의 어떤 수정도 거부 | S |
| **W2.4** | 시나리오 커버리지 테스트 | W2.2 | Property 테스트: 고객 값 없음, 식별자/경로는 ASCII, 모든 시나리오가 성공과 가드 기대 모두 가짐 | Customer GUID 또는 non-ASCII 식별자/경로 주입은 실패; natural-language 값은 한국어와 영어 모두 허용 | S |

### WI3 - 베이스라인 측정 (WI2 freeze로 블록됨)

| 작업 | 제목 | Deps | 산출물 | 수용 | 크기 |
|------|------|------|--------|------|------|
| **W3.1** | Pinned 참조 에이전트 | W1.2, W2.3 | `tools/reference_agent/` - pinned 구현 버전을 가진 결정론적 no-tiering 래퍼 | 같은 시나리오 버전에서 두 실행이 동일 출력(결정론) | M |
| **W3.2** | 베이스라인 러너 CLI | W3.1, W1.5 | `python -m tools.baseline_run --scenarios services/core-control-plane/tests/scenarios/v2026.07` - 성공 메트릭 + 가드 메트릭 + 표본 크기 + 신뢰구간 기록 | CLI가 누락 메트릭에 대해 non-zero exit 코드 | S |
| **W3.3** | 베이스라인 리포트 아티팩트 | W3.2 | `docs/baselines/v2026.07.md` - 방법론, 원시 카운트, 환경, CI, 표본 크기 | 리포트가 커밋되고 시나리오 세트 버전으로 다시 링크 | S |
| **W3.4** | 재현성 CI | W3.3 | CI 작업이 `v2026.07` 에서 pinned 에이전트를 재실행하고 보고된 CI 내 수치 단언 | 재실행이 CI 밴드 밖으로 표류하면 작업 실패 | M |

### WI4 - 아이덴티티 블로커 (critical 경로, 첫날 시작)

| 작업 | 제목 | Deps | 산출물 | 수용 | 크기 |
|------|------|------|--------|------|------|
| **W4.1** | Terraform 부트스트랩 모듈 | - | Container Apps env, PostgreSQL Flexible + pgvector, Event Hubs Kafka, Key Vault, Log Analytics, ACR, 명시적 선택 Azure OpenAI ([deploy-and-onboard-ko.md](../deployment/deploy-and-onboard-ko.md#azure-resource-inventory-minimum-set)) 을 위한 `infra/` 모듈 | `terraform apply`가 dev 구독에 최소 인벤토리를 프로비저닝 | L |
| **W4.2** | 실행기 MI (단계 1 형상) | W4.1 | [security-and-identity-ko.md § 신원 대응 (Phased)](../architecture/security-and-identity-ko.md#identity-mapping-phased) 에 따른 RG-스코프 built-in 롤 구성의 `mi-aw-executor` | Terraform이 롤 할당 발행; `az role assignment list` 가 선언 세트와 매칭 | M |
| **W4.3** | Azure Policy deny-by-default | W4.2 | 단계 1 변경 허용 목록 밖의 실행기 MI 액션을 거부하는 정책 할당 | non-allowlisted 액션 시도하는 프로브가 ARM 레이어에서 거부됨 | M |
| **W4.4** | 최소권한 프로브 | W4.2, W4.3 | `tools/lpp-probe` - 허용 액션 성공, 거부 액션 실패 단언; CI에 기록된 실행 | 프로브 업데이트 없이 새 권한 추가하면 CI 실패 | S |
| **W4.5** | App 등록 (dev) | W4.1 | dev 테넌트의 `fdai-console-spa`, `fdai-api`, `fdai-approval-bot` + [user-rbac-and-identity-ko.md § 4.4](../interfaces/user-rbac-and-identity-ko.md#44-app-roles-token-surface) 에 따라 선언된 App Roles | `Contributor` 에 할당된 dev 사용자가 `roles: ["Contributor"]` 토큰 받음 | M |
| **W4.6** | Entra 보안 그룹 + App 역할 바인딩 | W4.5 | 5 그룹 (`aw-readers/contributors/approvers/owners/break-glass`), 각각 Enterprise Applications에서 매칭 App 역할에 바인딩 | 미할당 dev 사용자는 protected 경로에서 거부되고 role-optional self-service 변환 결과만 사용 가능 ([user-rbac-and-identity-ko.md § 10.3](../interfaces/user-rbac-and-identity-ko.md#103-first-sign-in-unassigned-users)) | S |
| **W4.7** | Conditional 접근 정책 | W4.6 | `aw-approvers`/`aw-owners` 에 phishing-resistant MFA; `aw-owners` 에 compliant 장치; `aw-break-glass` 에 named-location | FIDO2 없이 사인인하는 테스트 승인자가 블록됨 | S |
| **W4.8** | 재인증 스케줄 | W4.6 | 문서화된 주기(`docs/runbooks/` 의 수동 분기 체크리스트, 또는 P2 라이선스된 경우 Entra 접근 검토) | 소유자 할당; 다음 리뷰 날짜가 감사 로그에 캡처됨 | S |

### WI5 - 정책 예외 워크플로

| 작업 | 제목 | Deps | 산출물 | 수용 | 크기 |
|------|------|------|--------|------|------|
| **W5.1** | 예외 아티팩트 스키마 | W1.2 | `services/core-control-plane/src/fdai/rule_catalog/schema/exemption.schema.json`; `.github/PULL_REQUEST_TEMPLATE/exemption.md` 의 PR 템플릿 | 누락 `justification` / `expires_at` 이 CI 실패 | S |
| **W5.2** | 요청자 ≠ 승인자 CI 검사 | W5.1, W4.5 | CI가 PR trailer Entra OID 를 리뷰어 OID에 대해 파싱; 자기승인 블록 | Author-approves-own-PR 테스트 케이스가 머지 블록 | S |
| **W5.3** | Auto-expiry Container Apps 작업 | W5.1, W4.1 | `expires_at` 통과 시 감사 `expired` 엔트리 발행하고 기저 할당 재적용하는 일일 cron 작업 | 예행 실행: 생성 → 대기 → 만료 → 감사 엔트리 존재; 할당 재적용 | M |
| **W5.4** | 만료 사전 알림 | W5.3 | 14일 lookahead 다이제스트 ([channels-and-notifications-ko.md § 라우팅](../interfaces/channels-and-notifications-ko.md#6-라우팅-정책-config-driven)) `exemption_expiry_lookahead_weekly` 배선 | 월요일 아침 포스트가 만료되는 각 exemption을 요청자 `@mention` 과 함께 리스트 | S |
| **W5.5** | 소유자 + SLA 문서 | W5.1 | `docs/runbooks/exemption-workflow.md` - 소유자 그룹, 리뷰 SLA, 에스컬레이션 경로 | 소유자 명명; SLA 측정 가능; 에스컬레이션 경로 해결 | S |

### WI6 - 로컬 개발 프리셋 (오프라인 페이크 + Docker Compose)

[tech-stack-ko.md § 로컬 개발](../architecture/tech-stack-ko.md#로컬-개발) 의 로컬-개발 계약을
[project-structure-ko.md § 주입 가능한-seams](../architecture/project-structure-ko.md#주입-가능한-seams)
의 주입 경계 으로 실현. In-memory 페이크는 개발자가 `pytest` 와 디버거에서 실행하는
것; Compose 프리셋은 통합 테스트, `event-ingest` 스모크 런, pgvector 유사도 체크가 실행되는 대상.

**초기 설계.** 인자가 없는 팩터리로 모든 백엔드를 등록하고 일반 pytest 작업에서 Docker 기반
프로바이더를 실행합니다.

**비판.** 실제 프로바이더에는 수명 주기를 관리하는 데이터베이스, 토픽, 소비자 그룹, 타임아웃 및
정리가 필요합니다. 기본 작업에서 이를 시작하면 오프라인 유닛 테스트가 Docker에 의존하며 인프라
누락이 모호한 테스트 동작으로 바뀝니다.

**개정 설계.** 공유 `test_contracts.py` 단언은 수명 주기를 관리하는 픽스처를 사용합니다. 기본
pytest는 페이크만 등록하고 loopback 밖의 네트워크 접근을 차단합니다. 명시적
`provider-contracts-docker` CI 작업은 두 매트릭스를 선택하고 정확한 임시 PostgreSQL 데이터베이스
하나를 생성한 뒤 삭제합니다. 모든 Redpanda 토픽과 소비자 그룹은 UUID로 격리하고 해당 브로커
기록만 삭제하며 실제 백엔드가 없으면 실패합니다. 기준 로컬 엔드포인트는 런타임 PostgreSQL
`127.0.0.1:5432`, 검증 PostgreSQL `127.0.0.1:5433`, Redpanda 호스트 `127.0.0.1:19092`,
Redpanda Compose 네트워크 `redpanda:29092`입니다.

| 작업 | 제목 | Deps | 산출물 | 수용 | 크기 |
|------|------|------|--------|------|------|
| **W6.1** | Storage / 버스 / 시크릿 / 신원 프로바이더 인터페이스 | W1.2 | `services/core-control-plane/src/fdai/shared/providers/` 의 `StateStore`, `EventBus`, `SecretProvider`, `WorkloadIdentity` 프로토콜 클래스 - 각각 네 개의 CSP-중립 계약 중 하나에 매핑 | `mypy --strict` 통과; 인프라에 닿는 모든 코어 모듈이 이 프로토콜 만 가져오기 (W1.7 import-lint 규칙이 `core/` 의 클라우드 SDK 금지 강제) | S |
| **W6.2** | In-memory 페이크 어댑터 + 공유 계약-테스트 스위트 | W6.1 | 수명 주기 픽스처가 `services/core-control-plane/tests/providers/test_contracts.py`의 같은 단언에 페이크, PostgreSQL 및 Redpanda를 등록 | 기본 pytest는 Docker 없이 유지되고 명시적 Docker CI 작업이 상태, 감사 체인, 중복 전달, pgvector, Kafka 순서, 그룹 재개, DLQ, loopback 전용 접근 및 정확한 정리를 검증 | M |
| **W6.3** | Docker Compose 개발 프리셋 + 래퍼 스크립트 | W6.1 | 상태 검사와 래퍼 스크립트를 포함한 pgvector/PostgreSQL 및 단일 노드 Redpanda `infra/local/docker-compose.yml` | 런타임 PostgreSQL `5432`, 검증 PostgreSQL `5433`, Redpanda 호스트 `19092`, Redpanda 컨테이너 `29092`가 Compose, 스크립트, 문서, 테스트 및 CI에서 일치하며 Azure 또는 클라우드 호출이 없음 | M |

### 시퀀싱된 태스크 타임라인

![시퀀싱된 태스크 타임라인. 주요 단계는 W4.1 Bootstrap modules, W4.2 Executor MI, W4.3 Policy deny, W4.4 LPP probe, W4.5 App regs, W4.6 Entra groups, W4.7 Conditional access, W4.8 Recertification, W1.1 Skeleton, W1.2 Ontology contracts, W1.3 Config loader, W1.4 OTel wiring입니다.](../../diagrams/generated/fdai-roadmap-phases-phase-0-instrumentation-01.ko.svg)

### Critical-Path 규칙

- **W4.1은 첫날 시작, 의존성 없음.** 클라우드 프로비저닝 지연(구독 쿼터, 리전 가용성)이 가장
  큰 스케줄 리스크.
- **W3.1은 W2.3 전에 시작해선 안 됨.** 이동하는 시나리오 세트에서 참조 에이전트 실행은 전체
  베이스라인 무효화.
- **W1.9 (KPI 대시보드) 는 W1.8 (golden 고정본) 통과 필요.** 어떤 패널도 수동 채워진 소스로
  출시 안 됨; 픽스처가 소스 그래프 동작 증명.
- **실행기 권한을 추가하는 어떤 태스크도 같은 PR에서 W4.4 업데이트 필요.** CI가 강제.
- **W6.2 (in-memory 페이크) 와 W1.5-W1.6 으로 랜딩하는 Postgres/Redpanda 어댑터는 하나의
  계약-테스트 스위트를 공유해야 함.** 페이크에서는 통과하지만 실제 백엔드에서는 실패(혹은
  반대)하는 테스트는 페이크가 표류했다는 신호 - 테스트가 아닌 페이크를 고친다.

### Done 정의 (태스크별)

각 태스크는 다음 시에만 완료:

1. **코드 + 테스트 머지** - 표준 거버넌스 PR 흐름(작성자 ≠ 검토자, 고위험 차이에
   `Justification:`) 을 통해.
2. **Docs-after 충족** - 만진 설계 문서가 같은 PR에서 업데이트
   ([coding-conventions.instructions.md § Documentation 작업 흐름](../../../.github/instructions/coding-conventions.instructions.md#documentation-workflow)).
3. **수용 검사 통과** - 태스크 테이블에 선언된 대로, 로컬 실행이 아니라 CI에서 검증.
4. **Shadow-mode 기본** - 태스크가 실행할 *가능한* 능력을 도입하면 출시 기본은
   `enforcement: do-not-enforce`.
5. **감사 로그 엔트리 발행** - 런타임에 상태-변경 태스크(Terraform 적용 포함) 에 대해.
## 데이터와 범위 제약

- 이 리포에 커밋된 모든 원격측정, 시나리오, 감사, KPI 데이터는 **시크릿 없음, 고객-비종속**이며
  합성 또는 자리 표시자 값만 사용합니다. 고정된 machine-record 키와 식별자/경로는
  ASCII/English를 유지하고 natural-language 값은 한국어와 영어를 모두 허용합니다
  ([goals-and-metrics-ko.md#데이터-수집과-원격측정](../architecture/goals-and-metrics-ko.md#데이터-수집과-원격측정)).
  실제 환경 기록은 포크의 런타임 저장소에만 존재.
- 대시보드의 각 메트릭은 정확히 하나의 원격측정 소스(OpenTelemetry 추적, 추가 전용 감사 로그,
  또는 비용/사용 기록) 에 매핑; 소스 없는 열망 패널은 출시 불가.

## Exit 기준

모든 기준은 독립적으로 검증 가능; 단계 게이트는 모든 박스가 체크될 때만 통과.

- [ ] **시나리오 세트가 freeze되고 버전** , 복원력 / 변경 안전성 / 비용 거버넌스에 걸쳐 균형, 고객-비종속 데이터로
      저장.
- [ ] **재현 가능한 베이스라인** 존재: 고정 시나리오 세트 버전에서 pinned 참조 에이전트가
      재실행 시 보고된 신뢰구간 내 같은 수치 산출, 표본 크기와 버전 기록.
- [ ] **베이스라인이 성공 메트릭 1-4와 모든 가드 메트릭 커버** - 이후 shadow → 강제 적용 승격이
      성공과 가드 참조 모두 가짐.
- [ ] **KPI 대시보드가 라이브** - 메트릭 1-4, 가드 메트릭, 선행 지표 표시, 각각 원격측정 소스에
      추적.
- [ ] **아이덴티티 블로커 해결**: 종단 IdP ↔ Entra ↔ Managed Identity 경로 프로비저닝,
      최소권한 프로브 통과, deny-by-default 확인, 재인증 스케줄 - 또는 문서화되고 소유자
      할당된 계획으로 명시적 waive.
- [ ] **정책 예외 워크플로** 문서화되고 소유자 할당되고 예행 실행 검증(부여, 감사, auto-expire)
- [ ] **로컬 개발 프리셋이 양방향으로 동작**: `pytest` 가 in-memory 페이크에 대해 오프라인으로
      green, **그리고** `scripts/deployment/local/dev-up.sh` 가 건강한 pgvector + Redpanda 스택을 생산하고
      동일한 계약-테스트 스위트가 그것에 대해서도 통과. 개발자가 Azure 프로비저닝 없이 호스팅된
      IDE에서 어느 서브시스템이든 디버그 가능.
      - 또는 문서화된 계획으로 명시적 waive.

## 리스크

| 리스크 | 가능성 | 영향 | 완화 |
|--------|--------|------|------|
| 불공정하거나 불균형한 시나리오 세트가 베이스라인-vs-트리트먼트 비교 무효화 | 중간 | 높음 | 어떤 측정 전에 세트 freeze하고 버전; 도메인 간 균형; 참조 에이전트는 handicap되지 않음 ([goals-and-metrics-ko.md#measurement-first-규칙](../architecture/goals-and-metrics-ko.md#measurement-first-규칙) 의 공정성 규칙). |
| 아이덴티티 매핑 노력 저평가 | 높음 | 높음 | Critical 경로로 취급; 첫날 시작; "인증됨" 이 아니라 최소권한 프로브로 게이팅. |
| 정책 예외 워크플로가 늦어져 이후 준수 배포 블록 | 중간 | 중간 | P0에서 소유자와 SLA 정의; exit 전 예행 실행 요청으로 검증. |
| 베이스라인이 재현 불가(unpinned 에이전트 또는 표류하는 시나리오) | 중간 | 높음 | Reference-agent 버전 고정, 어떤 랜덤도 시드, 시나리오 세트 freeze; 실행 환경 기록. |
| 원격측정 갭이 메트릭을 측정 불가하게 함 | 중간 | 높음 | 항목 1에서 모든 메트릭을 소스에 매핑; 어떤 패널이라도 수동 채워지면 exit 블록. |
| 고객 식별 데이터가 커밋된 원격측정/픽스처로 유출 | 낮음 | 높음 | CI에서 시크릿 검사와 범위 검사; 합성 데이터만 ([generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md)). |

## 시퀀싱

- **첫날, 병렬로**: 항목 4(아이덴티티, critical 경로) 와 항목 2(시나리오 freeze) 시작, 항목 1
  (원격측정)과 항목 5(정책 워크플로) 준비.
- **시나리오 freeze 이후**: 항목 3(베이스라인 측정) 실행, 고정된 버전 세트에 대해 측정.
- **게이트**: 모든 [Exit 기준](#exit-기준) 통과 후에만
  [phase-1-rule-catalog-t0-ko.md](phase-1-rule-catalog-t0-ko.md) 시작.

## 의존성

- **상류**: 없음 - P0는 루트 단계. 외부 전제조건은 아이덴티티 매핑을 위한 클라우드/IdP 접근과
  원격측정/저장소 대상 ([deployment-ko.md](../deployment/deployment-ko.md),
  [tech-stack-ko.md](../architecture/tech-stack-ko.md)).
- **하류**: P0 원격측정, 고정 시나리오 세트, 측정된 베이스라인, 해결된 아이덴티티/정책 블로커는
  [phase-1-rule-catalog-t0-ko.md](phase-1-rule-catalog-t0-ko.md) 와 모든 이후 단계의 전제조건
  ([README-ko.md](../README-ko.md)).

## 관련 문서

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| 구현 상태 및 남은 작업 | [구현 원장](../../roadmap-implementation/phases/phase-0-instrumentation.md) |
