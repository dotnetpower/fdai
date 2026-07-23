---
title: 시작과 라이프사이클(Startup and Lifecycle)
translation_of: startup-and-lifecycle.md
translation_source_sha: 82f5193802f010c5ee659443bddf01d95f234b75
translation_revised: 2026-07-23
---

# 시작과 라이프사이클(Startup and Lifecycle)

FDAI가 새로 프로비저닝된 Azure 구독에서 **콜드로 시작해 정상 상태에 도달** 하는 방법.
답변: 시스템은 언제 "시작"하는가? 첫날 카탈로그에 무엇이 있는가? 자율 discovery 루프는 언제
시작하는가? shadow → enforce 라이프사이클은 어떻게 시퀀싱되는가?

[deploy-and-onboard-ko.md](../deployment/deploy-and-onboard-ko.md) (프로비저닝 처리) 와
[operating-and-verification-ko.md](operating-and-verification-ko.md) (지속 관측 처리) 보완.
설계 불변식은
[architecture.instructions.md](../../../.github/instructions/architecture.instructions.md) 에서.

Azure 초점: 비-Azure 프로바이더는 TBD
([Always-On Rules](../../../.github/copilot-instructions.md#always-on-rules-must)).
아래 타임라인 제안은 방향성이지 하드 규칙 아님; **게이트는 하드**.

> **구현 상태**: 현재 reference Terraform은 KEDA scale rule 없이 `min_replicas = 1`인 단일
> `core` container를 배포합니다. Generic rule catalog와 model resolver CLI는 존재하지만 아래
> 자동 collector/discovery startup, end-to-end HIL bootstrap 및 model lifecycle reconciliation은
> 완전한 runtime workflow로 연결되지 않았습니다. 이 문서는 현재 bootstrap contract와 목표
> lifecycle을 함께 표시합니다.

## 콜드 스타트 (scale-to-zero 세부사항)

현재 코어 엔진은 **하나의 Container App과 하나의 `core` container**로 실행됩니다. Trust
router, executor, audit writer는 현재 같은 Python process 안에 있고 localhost sidecar IPC는
없습니다. Day-zero `min_replicas` 기본값은 1이며 Event Hubs lag KEDA rule은 없습니다. 포크가
lag 기반 scale rule을 추가한 뒤에만 `min_replicas = 0`으로 낮춰 scale-to-zero를 사용할 수
있습니다. 현재 "시작"은 다음과 같습니다:

1. Container App revision이 `core` replica를 시작하고 최소 한 replica를 유지합니다.
2. Core process가 config를 로드하고 state, audit, event-bus adapter 및 rule catalog를 구성합니다.
3. HTTP startup/readiness probe가 `/ready`를 확인한 뒤 replica가 traffic-ready가 됩니다.
4. Consumer가 이벤트를 `event-ingest → correlation → trust-router → tier → risk-gate → audit`
   in-process 경로로 처리합니다.

향후 scale-to-zero를 enable한 배포의 콜드 스타트에는 다음 규칙이 적용됩니다:

- **콜드-스타트 메트릭**: 콜드 경로의 첫 이벤트는 replica가 warm 되는 동안 T0 지연 예산을
  초과할 수 있음. 이 지연은 T0 warm 지연 백분위가 오염되지 않도록 별도 **콜드-스타트 메트릭**
  으로 기록되어야 함. 콜드 vs warm은 KPI 대시보드에 나란히 보고
  ([goals-and-metrics-ko.md](../architecture/goals-and-metrics-ko.md)).
- **콜드-스타트 데드라인**: 설정된 데드라인 초과는 이벤트를 HIL로 강등, 게이트 없는 auto-action
  이 되지 않음
  ([architecture.instructions.md](../../../.github/instructions/architecture.instructions.md)).
- **콜드-스타트 순서**: 콜드 시작된 replica는 리소스별 순서 / idempotency 보장을 존중해야 함;
  올라오는 replica가 "같은 이벤트 두 번 = 하나의 효과" 불변식을 위반할 수 없음.
- **향후 sidecar readiness 게이팅**: Sidecar topology를 실제로 추가하는 경우 주 컨테이너는
   모든 sidecar의 readiness가 green일 때까지 이벤트를 받지 않는 것이 좋습니다. 현재 단일
   container topology에는 적용되지 않습니다.

**TBD**: 구체적 콜드-스타트 데드라인과 정확한 콜드-스타트-메트릭 이름/정의.

## 시작 환경 Preflight

`/ready`가 열리기 전에 runtime은 dependency별 startup preflight를 평가하는 것이 좋습니다. 이는
provisioning 중심 deployment preflight 및 active post-deploy smoke test와 구분됩니다.

> **구현 상태**: Headless runtime은 이제 Pantheon 또는 event consumer를 시작하기 전에 하나의
> deterministic `StartupReadinessReport`를 조립합니다. 표준 probe inventory는 로드된
> config/catalog/policy, secret injection, workload identity, state, audit, kill-switch, Kafka
> round trip, embedding 및 바인딩된 모든 T2 cross-check candidate를 검사합니다. Fork는 동일한
> injected probe seam으로 활성화된 optional destination을 등록합니다.

### 단계와 결정

| 단계 | 검사 | 변경 정책 |
|------|------|-----------|
| Static load | release manifest, config hash, catalog version, model binding, migration expectation | network와 변경 없음 |
| Required reachability | identity token, private DNS, TLS, PostgreSQL, Kafka, catalog와 policy engine | bounded read-only |
| Capability warm-up | 활성화된 각 model, embedding, search, notification 및 telemetry adapter | 명시적 비용 한도가 있는 최소 요청 |
| Active smoke | Kafka probe topic round trip, database probe transaction, canary, 사람 승인 dry run | 전용 synthetic scope만 사용 |

Report는 세 가지 결정을 사용합니다. `blocked`는 `/ready`를 닫습니다. `degraded`는 관찰 또는 read-only
작업을 열 수 있지만 unavailable capability의 권한을 낮춥니다. `ready`는 낮은 권한 상한 없이 필수
검사가 통과했음을 뜻합니다. 결과는 check id, dependency 또는 capability, required/optional 분류,
결정, latency, evidence time, 정제된 failure class 및 다음 retry를 기록합니다.

### 필수 Probe Inventory

| 영역 | Startup evidence |
|------|------------------|
| Release와 config | image digest, release version, config hash, catalog version, `resolved-models.json` schema와 freshness |
| Host trust | 설정된 token/TLS 허용 범위 이내의 clock skew, certificate chain과 expiry, proxy와 custom CA config |
| Identity와 secret | audience-scoped token 획득, 필수 role 관찰, native secret/reference injection |
| State와 policy | PostgreSQL 연결, migration head, audit 가용성, kill-switch 읽기, catalog load, OPA compile |
| Event path | Kafka DNS/TCP/TLS/auth, 필수 topic, consumer group, DLQ 및 Diagnostic Settings forwarder 상태 |
| Model capability | deployment readiness, auth, quota headroom, feature flag, mixed-publisher 불변식, verifier와 grounding 가용성 |
| Optional adapter | web search, notification, 사람 승인 channel, OTLP export 및 fork가 등록한 provider |

단일 `internet_available` 결정은 사용하지 않습니다. 활성화된 각 destination을 DNS, TCP, TLS,
authentication 및 하나의 bounded protocol operation으로 검사합니다. Package와 image registry는
build-time evidence로 유지합니다. Private endpoint는 runtime subnet에서 검사합니다.

### Model Latency와 Recovery

각 model candidate는 최소 두 개의 bounded startup sample을 받습니다. Streaming은 time to first token
(TTFT), total latency, output-token rate, sample count 및 정제된 failure class를 기록합니다. Embedding은
latency와 vector shape를, structured-output과 tool-calling candidate는 해당 feature를 증명합니다.
Probe는 최소 prompt와 capped output을 사용하고 무관한 tool 비용과 error 저장을 피합니다.

Narrator target은 TTFT p95 2.5초 이내로 유지합니다
([operator-console-view-snapshot-ko.md](../interfaces/operator-console-view-snapshot-ko.md)). Startup
sample은 minimum sample count 전에는 percentile을 주장하지 않습니다. Target miss는 `degraded`,
deadline 전 valid first token 부재는 unavailable입니다. T2는 계속 mixed-model과 verifier gate를
요구하며 deadline miss는 case를 사람 승인으로 낮춥니다.

Evidence는 설정된 interval 이후 만료됩니다. Periodic probe는 report를 refresh하고 transition만
append합니다. Recovery는 `ready`를 복원할 수 있지만 promotion state보다 권한을 높일 수 없습니다.

### 실패와 권한 규칙

- **Process-critical**: 잘못된 config, token/secret failure, PostgreSQL/audit failure, policy compile failure 또는 필수 Kafka failure는 `/ready`를 닫습니다.
- **Authority-critical**: 읽을 수 없는 kill-switch, 누락된 T2 verification 또는 unavailable approval은 shadow나 사람 승인을 강제합니다. 검증되지 않은 자동 action을 활성화하지 않습니다.
- **Optional capability**: narrator, search, notification 또는 telemetry failure는 deterministic fallback 또는 disabled 상태와 함께 `degraded`로 보고하며 healthy로 가장하지 않습니다.
- **Probe safety**: Check는 bounded, safe to retry, sanitized이며 전용 synthetic resource 외에는 read-only입니다. Partial required probe는 `ready`가 아니라 `blocked`가 됩니다.

### 제공되는 Runtime 경계

Provider-neutral contract와 reducer는 `core/readiness` 아래에 있습니다. Probe 구현은
`delivery` 아래에 있고, `runtime/readiness.py`가 순서가 있는 네 단계를 조립합니다. 한 단계 안에서는
bounded concurrency를 사용하지만 현재 단계가 끝나기 전에는 다음 단계를 시작하지 않습니다.
Coordinator는 probe별/단계별 deadline, retry, 전체 startup cost limit 및 활성화된 model candidate별
최소 두 sample을 적용합니다.

Runtime은 정제된 evidence만 `runtime:startup-readiness:latest`에 저장합니다. 결정이 변경되면 audit
record를 append하고 JSON Schema로 검증된 `readiness_transition` event를 publish합니다. Provider error
text, credential, endpoint value, deployment name 및 customer identifier는 report와 transition payload에
포함되지 않습니다.

`/live`는 process liveness를 별도로 보고합니다. `blocked`이면 `/ready`는 `503`을 반환하며 core
consumer, discovery, canary, 사람 승인, retention, runtime-state 및 Pantheon task는 중지 상태를
유지합니다. Periodic refresh는 process-critical dependency가 blocked가 되면 실행 중인 task를
cancel하고 recovery 후 다시 시작합니다. Recovery는 composition에서 받은 deployment ceiling을
재사용하며 authority를 승격할 수 없습니다.

Bounded runner는 `FDAI_STARTUP_MAX_CONCURRENCY`, `FDAI_STARTUP_PROBE_TIMEOUT_SECONDS`,
`FDAI_STARTUP_PHASE_TIMEOUT_SECONDS`, `FDAI_STARTUP_PROBE_RETRIES`,
`FDAI_STARTUP_COST_LIMIT_USD`, `FDAI_STARTUP_MODEL_SAMPLE_COUNT` 및
`FDAI_STARTUP_REFRESH_SECONDS`로 조정할 수 있습니다. 활성화된 optional adapter는 blanket connectivity
flag를 추가하지 말고 `StartupProbeSpec`과 `StartupProbe`를 등록하는 것이 좋습니다.

### Live 검증 Evidence

2026-07-23에 VNet-integrated self-hosted runner가 기존 development dependency에 bounded check를
실행했습니다. PostgreSQL은 resolve 후 TCP 및 protocol-aware TLS handshake를 수락했습니다. Event
Hubs는 resolve 후 Kafka port TCP/TLS를 수락했습니다. 구성된 model endpoint는 private address로
resolve되었고 TCP/TLS를 수락했습니다. 최소 managed-identity model operation은 `401`을 반환했으므로
probe는 healthy capability evidence를 기록하지 않고 model path를 degraded로 분류했습니다. 통제된
refused destination은 정제된 `ConnectionRefusedError` class와 함께 `blocked`로 축소되었습니다. 검증
후 임시 role을 제거하고 database와 runner를 이전 stopped/deallocated 상태로 되돌렸습니다.

## 초기 규칙 카탈로그 상태

상류 리포는 **고객 특이 규칙 없음**. 포크 배포의 첫날 카탈로그는 두 소스에서 채워짐 - 순서:

1. **부트스트랩 시드 세트** (포크 책임) - `content_hash` 와 버전으로 고정된 초기 카탈로그
   스냅샷, 포크가 자체 catalog-as-code 리포에 커밋.
2. **자율 컬렉터** (상류) - 첫 성공 컬렉터 실행 후, 상류 소스가
   [rule-catalog-collection-ko.md](../rules-and-detection/rule-catalog-collection-ko.md) 에 따라 설정된 주기로 수집.

현재 upstream은 `rule-catalog/catalog/`, generic profiles, source manifest 및
`tools/seed_p1_manifest.yaml`을 함께 제공합니다. 포크는 이를 customer-specific 값 없이 그대로
사용하거나 fork-owned overlay/seed를 추가할 수 있습니다. Collector schedule은 배포가 별도로
binding해야 합니다.

첫날 카탈로그에 적용되는 규칙:

- 모든 규칙은 심각도와 무관하게 **`effect: audit` (shadow)** 기본이어야 함. enforce로 시작하는
  규칙을 출시할 방법 없음; 첫날에 enforce로 랜딩할 규칙은 승격 게이트 실패
  ([rule-governance-ko.md](../rules-and-detection/rule-governance-ko.md)).
- 모든 규칙은 시드 규칙 포함해서 grounded **`provenance`** (source URL + resolved revision +
  content hash + license + `redistribution` 플래그) 를 운반해야 함. Provenance 없는 규칙은
  스키마 검증 실패.
- **LLM-생성 후보** 는 자율 discovery 루프가 활성화되고 그 quality gate가 사용 가능해지기 전에는
  카탈로그에 진입하지 않음.

**TBD**: 첫날 시드 세트에 어떤 소스가 실리고 정확한 규칙 id - Phase 1의 "소스별 초기 대상 세트
열거"와 동일한 open 항목
([phase-1-rule-catalog-t0-ko.md](../phases/phase-1-rule-catalog-t0-ko.md)).

## 이벤트 소스 부트스트랩

이벤트가 판단되기 전에 ingress는 Azure 신호에 부착되어야 함:

1. **Diagnostic Settings** - 대상 구독과 각 in-scope 리소스 그룹에서, Activity Log(과 리소스별
   로그)을 **Event Hubs Kafka 토픽** 으로 forward 하는 Diagnostic Settings 활성화 - 이것이
   CSP-중립 이벤트 버스 계약
   ([csp-neutrality-ko.md § 이벤트버스 계약](../architecture/csp-neutrality-ko.md#1-이벤트버스-계약--kafka-와이어-프로토콜)).
2. **Kafka 토픽 + 컨슈머 그룹** - Event Hubs 네임스페이스에 첫날 토픽들을 생성
   (`aw.change.events`, `aw.dr.events`, `aw.finops.events`, 그리고 그들의 `<topic>.dlq`
   형제) 하고 `event-ingest` 를 위한 컨슈머 그룹 등록.
3. **Idempotency prime** - event-ingest 레이어가 처음 수신 시 모든 들어오는 이벤트에
   **idempotency 키** 를 스탬프하여 리플레이가 종단 no-op.
4. **DLQ 도달 가능성 검증** - dead-letter 목적지 (Kafka `<topic>.dlq`) 가 어디에서든
   enforce가 활성화되기 전에 실행됨 (poison-pill 프로브).

구체적 이벤트 타입과 필터 표현식은 **TBD** 이며
[deploy-and-onboard-ko.md#event-source-subscription](../deployment/deploy-and-onboard-ko.md#event-source-subscription)
에 캡처.

## 모델 프로비저닝 부트스트랩

T2가 실행되기 전에 capability→deployment 매핑을 해결해야 합니다. Resolver CLI와 schema는
구현되어 있지만 현재 `deploy-dev.yml`은 `terraform apply` 전에 resolver를 자동 실행하지
않습니다. CI는 repository variable `RESOLVED_MODELS_JSON`을 `resolved-models.json`으로
materialize하고 runtime/read API는 configured filesystem path를 읽습니다.

1. **Resolver가 `rule-catalog/llm-registry.yaml` 에서 실행** - capability별 선호를 읽고,
   대상 리전의 Azure OpenAI / Foundry 카탈로그를 쿼리, `capacity_tpm` 상한과 함께 capability당
   하나의 deployment 프로비저닝.
2. **Mixed-model 불변식 검증** - `t2.reasoner.primary.publisher` 는 `t2.reasoner.secondary.
   publisher` 와 달라야 함, 아니면 부트스트랩 중단 (조용한 same-vendor fallback 없음). 포크의
   `llm.mixed_model_mode` (`azure-foundry` / `external` / `hil-only`) 가 전략 선택.
3. **`resolved-models.json`을 protected deployment artifact로 제공** - capability →
   `{deployment, family, version, publisher}`를 기록합니다. 현재 Terraform은 이 manifest를 Key
   Vault secret으로 저장하지 않으며 path/CI variable이 배포 경계입니다.
4. **주간 reconciler는 후속 increment로 연기** -
   [dev-and-deploy-parity-ko.md](../deployment/dev-and-deploy-parity-ko.md)의 W-I가 완료되기
   전에는 명시적인 registry PR로 모델 변경을 검토합니다. Reconciler는 새 family와 폐기
   공지를 감시하고 draft PR을 열지만 live mapping을 자동 교체하지 않습니다.

전체 설계: [llm-strategy-ko.md § Model Provisioning and Lifecycle](../architecture/llm-strategy-ko.md#model-provisioning-and-lifecycle).

## Shadow-First 롤아웃 레시피

모든 새 배포는 전체 footprint에 대해 **shadow-only 모드** 로 랜딩. 승격은 액션별, 규칙별,
도메인별 - 절대 글로벌 flip 아님. 제안된 마일스톤 (모든 타임라인은 **방향성** ; 게이트는 하드):

| 마일스톤 | 초점 | 진행 게이트 |
|----------|------|-------------|
| **D+0 → D+7** | 루프가 shadow에서 종단 실행 검증: 이벤트 랜딩 → 티어 결정 → 감사 기록 | 조용한 드롭 0, 미인증 액션 0, canary green |
| **D+7 → D+14** | 규칙별 shadow 정확도 + false-positive 비율 측정; 저위험 승격 후보 식별 | [goals-and-metrics-ko.md](../architecture/goals-and-metrics-ko.md) 에 따른 shadow 표본 크기와 정확도 임계 |
| **D+14 → D+30** | 소수의 첫 저위험 규칙 배치를 `remediate` (PR-only) 로 승격, 모호한 것은 HIL | shadow 윈도우 내 정책 위반 escape 0 |
| **D+30 →** | 지속적 승격 사이클, 한 번에 한 규칙, 각각 enforce-promotion 승인 게이트에 따라 | 회귀 스위트 green, 측정된 정확도 안정 |

전 구간 적용되는 규칙:

- 어떤 회귀는 승격된 규칙을 **자동으로 shadow로 강등** - 강등은 승격 승인자를 절대 필요로 하지
  않아 안전 방향 저하는 항상 빠름
  ([rule-governance-ko.md](../rules-and-detection/rule-governance-ko.md#effects-mode)).
- Enforce 승격은 제안한 운영자와 **별도 승인** 필요
  ([security-and-identity-ko.md](../architecture/security-and-identity-ko.md)).
- Kill-switch는 D+7 종료 전에 도달 가능성 검증.

## 사람 승인 담당자 부트스트랩

> **현재 경계**: Role/group resolver와 Teams/Slack delivery adapter는 구현되어 있지만 Teams SSO
> OBO approval callback, group-connected audience derivation, governance PR quorum CI 및 dry-run HIL
> bootstrap workflow는 아직 end-to-end로 연결되지 않았습니다. BreakGlass role은 runtime HIL
> approval capability를 갖지 않습니다. 아래 단계는 포크 deployment 목표입니다.

어떤 enforce-mode 규칙도 승격되기 전에 승인자 그룹이 프로비저닝되어야 함. 승인자가 없으면
고위험 finding은 fallback 채널을 통해 큐잉되고 알림; **절대 auto-execute 안 함**. Entra 그룹
모델은 [user-rbac-and-identity-ko.md](../interfaces/user-rbac-and-identity-ko.md) 에 정의.

단계 (포크 책임):

1. HIL A1 트래픽과 다이제스트를 위해 `aw-approvers` 로 백업된 Teams **그룹-연결 팀** 생성;
   멤버십은 이후 Entra 그룹을 자동 추종
   ([channels-and-notifications-ko.md#51-audience-derivation-channel-as-audience](../interfaces/channels-and-notifications-ko.md#51-audience-derivation-channel-as-audience)).
2. 5개 Entra 보안 그룹 (`aw-readers`, `aw-contributors`, `aw-approvers`, `aw-owners`,
   `aw-break-glass`) 프로비저닝, config slot에 objectId 주입
   ([user-rbac-and-identity-ko.md#42-security-groups-slots](../interfaces/user-rbac-and-identity-ko.md#42-security-groups-slots)).
3. `aw-approvers`/`aw-owners` 에 Conditional Access 적용: phishing-resistant MFA 필수,
   legacy auth 블록; `aw-owners` 에 compliant-device 추가
   ([user-rbac-and-identity-ko.md#43-conditional-access](../interfaces/user-rbac-and-identity-ko.md#43-conditional-access)).
4. enforce 승격, 예외, override에 **quorum-2** 규칙을 유지하는 데 필요한 최소 멤버 수로
   `aw-approvers` 채움
   ([user-rbac-and-identity-ko.md#51-codeowners-single-approver-group-path-based-reviewer-count](../interfaces/user-rbac-and-identity-ko.md#51-codeowners-single-approver-group-path-based-reviewer-count)).
5. executor의 Chat 어댑터 config에 승인자 그룹 id 등록하여 Adaptive Card 승인이 롤 claim을
   검증할 수 있게 함.
6. **Slack 워크스페이스 프로비저닝** (P1 A1 채널): FDAI Slack 앱 설치, `chat:write`
   부여, 필수 Slack userId ↔ Entra OID 매핑 저장소 채움; 매핑이 비어 있지 않을 때까지 Slack
   어댑터는 A1 트래픽 거부
   ([channels-and-notifications-ko.md#7-channel-specific-notes](../interfaces/channels-and-notifications-ko.md#7-channel-specific-notes)).
7. `rule-catalog/channel-routing/` config (primary/fallback 채널, 다이제스트 스케줄, 오디언스)
   를 규칙과 같은 리뷰 엄격도로 커밋; A1 라우팅을 만지는 모든 변경은 Owner-티어 리뷰어 필요.
8. 카나리 경로를 통해 **dry-run HIL** 실행하여 승인이 랜딩하고 `justification` 이 요구되고
   timeout이 fail-closed이고 모든 승인이 `correlation_id` 있는 감사 엔트리를 씀을 확인.

## 자율 Discovery 루프 시동

[자율 규칙 discovery 루프](../rules-and-detection/rule-catalog-collection-ko.md#autonomous-rule-discovery) 는
**첫날에 비활성**. 다음 모두 이전에 실행되어선 안 됨:

> 현재 upstream에는 이 모든 조건을 평가해 loop를 자동 enable하는 startup coordinator가
> 없습니다. 아래 조건은 향후 activation gate 계약입니다.

1. 감사 로그가 최소 **`N` shadow 결정** 을 축적하여 observe 스테이지에 실제 베이스라인 제공.
   `N` 은 설정 가능; **TBD** - 낮은 수천대 권장.
2. 최소 하나의 컬렉터가 성공 실행(배선 + provenance 증명).
3. Mixed-model 교차 검사 대상과 결정론적 verifier가 건강.
4. Post-deploy smoke 테스트가 green
   ([operating-and-verification-ko.md](operating-and-verification-ko.md#post-deploy-smoke-테스트-계약)).

활성화되면 루프는 설정된 주기로 실행. 루프의 후보 규칙은 전체 quality gate를 통과할 때까지
inert - 루프는 카탈로그를 직접 변형할 수 없음.

루프 비활성화는 **정책 토글** ,  코드 변경 아님; 반복되는 override 신호는 다음 활성화를 위해
감사 로그에 계속 축적됨.

## 라이프사이클 상태

모든 아티팩트는 정의된, 감사 가능한 상태를 진행. 전이가 유일한 이동 방법; 각 전이는 버전되고
감사됨.

- **Rule / rule-set** - `draft → audit(shadow) ⇄ enforce(deny/remediate) → deprecated`,
  `disabled` 은 어떤 활성 상태에서도 도달 가능
  ([rule-governance-ko.md#lifecycle-and-versioning](../rules-and-detection/rule-governance-ko.md#lifecycle-and-versioning)).
- **Assignment** - 스코프, `effect`, `enforcement` 플래그에 바인딩. Effects는 승격 게이트 하에
  전이; 회귀는 자동 강등.
- **Exemption** - `active → expired` (time-boxed; auto-renew 없음)
  ([rule-governance-ko.md#exemptions](../rules-and-detection/rule-governance-ko.md#exemptions)).
- **Override** - `active → removed`; long-lived 가능(강제 만료 없음), 스코프는 resource-group-
  equivalent 이하이어야 함
  ([rule-governance-ko.md#overrides](../rules-and-detection/rule-governance-ko.md#overrides)).
- **Action** - `proposed → risk-gated → executed | rejected → rolled-back (해당 시)`. 모든
  상태가 idempotency 키를 운반하여 리플레이는 no-op.

## Open Decisions

- [ ] 콜드-스타트 데드라인 값과 정확한 콜드-스타트-메트릭 이름.
- [ ] 첫날 시드 규칙 세트(어떤 소스, 어떤 규칙 id) - Phase 1과 교차 링크.
- [ ] Discovery-루프 시동 임계 `N` (shadow-decision 카운트) 과 그 회귀-안전 근거.
- [ ] Kafka 토픽 레이아웃 + Diagnostic-Settings 포워더 필터 형상과 소스별 속도 상한.
- [ ] 부트스트랩 런북: 포크가 D+0에 도달하기 위한 정확한 명령 시퀀스 (
      [operating-and-verification-ko.md](operating-and-verification-ko.md#runbook-set) 소유).
- [ ] Dry-run HIL 절차: 카나리 페이로드, 예상 타이밍, 정리.
