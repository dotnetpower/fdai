---
translation_of: startup-and-lifecycle.md
translation_source_sha: 56b90f3ab4bf21073be3986f4240d97106965d13
translation_revised: 2026-07-05
---

# 시작과 라이프사이클(Startup and Lifecycle)

AIOpsPilot가 새로 프로비저닝된 Azure 구독에서 **콜드로 시작해 정상 상태에 도달** 하는 방법.
답변: 시스템은 언제 "시작"하는가? 첫날 카탈로그에 무엇이 있는가? 자율 discovery 루프는 언제
시작하는가? shadow → enforce 라이프사이클은 어떻게 시퀀싱되는가?

[deploy-and-onboard-ko.md](deploy-and-onboard-ko.md) (프로비저닝 처리) 와
[operating-and-verification-ko.md](operating-and-verification-ko.md) (지속 관측 처리) 보완.
설계 불변식은
[architecture.instructions.md](../../.github/instructions/architecture.instructions.md) 에서.

Azure 초점: 비-Azure 프로바이더는 TBD
([Implementation Focus](../../.github/copilot-instructions.md#implementation-focus-must)).
아래 타임라인 제안은 방향성이지 하드 규칙 아님; **게이트는 하드**.

## 콜드 스타트 (scale-to-zero 세부사항)

코어 엔진은 Container Apps + **KEDA scale-to-zero** + 이벤트 기반 스케일링으로 실행. 코어는
**하나의 Container App + 사이드카 컨테이너** (`event-ingest` primary, `trust-router` /
`executor` / `audit-writer` 사이드카 —
[deploy-and-onboard-ko.md](deploy-and-onboard-ko.md#compute-shape-sidecar-containers) 참조).
따라서 "시작"은:

1. 최소 하나의 이벤트가 ingress에 도착.
2. KEDA가 앱의 replica 세트를 0에서 스케일; **모든 사이드카가 함께 up** (하나의 scale unit).
3. 주 컨테이너가 config를 로드, state / audit / 이벤트 버스 연결 오픈, rule 카탈로그를 OPA로
   hydrate; 사이드카는 자체 부팅을 병렬로 완료하고 `localhost` 에 readiness 노출.
4. 이벤트가 `event-ingest → correlation → trust-router → tier → risk-gate → audit` 을 통해
   흘러 사이드카 사이를 `localhost` IPC로 hop.

모든 콜드 스타트에 적용되는 규칙:

- **콜드-스타트 메트릭**: 콜드 경로의 첫 이벤트는 replica가 warm 되는 동안 T0 지연 예산을
  초과할 수 있음. 이 지연은 T0 warm 지연 백분위가 오염되지 않도록 별도 **콜드-스타트 메트릭**
  으로 기록되어야 함. 콜드 vs warm은 KPI 대시보드에 나란히 보고
  ([goals-and-metrics-ko.md](goals-and-metrics-ko.md)).
- **콜드-스타트 데드라인**: 설정된 데드라인 초과는 이벤트를 HIL로 강등, 게이트 없는 auto-action
  이 되지 않음
  ([architecture.instructions.md](../../.github/instructions/architecture.instructions.md)).
- **콜드-스타트 순서**: 콜드 시작된 replica는 리소스별 순서 / idempotency 보장을 존중해야 함;
  올라오는 replica가 "같은 이벤트 두 번 = 하나의 효과" 불변식을 위반할 수 없음.
- **사이드카 readiness 게이팅**: 주 컨테이너는 모든 사이드카의 readiness 프로브가 green이
  될 때까지 이벤트를 수락해선 안 됨; 그렇지 않으면 부분 콜드 스타트가 의존성을 열지 않은
  사이드카로 이벤트를 라우팅할 수 있음.

**TBD**: 구체적 콜드-스타트 데드라인과 정확한 콜드-스타트-메트릭 이름/정의.

## 초기 규칙 카탈로그 상태

상류 리포는 **고객 특이 규칙 없음**. 포크 배포의 첫날 카탈로그는 두 소스에서 채워짐 — 순서:

1. **부트스트랩 시드 세트** (포크 책임) — `content_hash` 와 버전으로 고정된 초기 카탈로그
   스냅샷, 포크가 자체 catalog-as-code 리포에 커밋.
2. **자율 컬렉터** (상류) — 첫 성공 컬렉터 실행 후, 상류 소스가
   [rule-catalog-collection-ko.md](rule-catalog-collection-ko.md) 에 따라 설정된 주기로 수집.

첫날 카탈로그에 적용되는 규칙:

- 모든 규칙은 심각도와 무관하게 **`effect: audit` (shadow)** 기본이어야 함. enforce로 시작하는
  규칙을 출시할 방법 없음; 첫날에 enforce로 랜딩할 규칙은 승격 게이트 실패
  ([rule-governance-ko.md](rule-governance-ko.md)).
- 모든 규칙은 시드 규칙 포함해서 grounded **`provenance`** (source URL + resolved revision +
  content hash + license + `redistribution` 플래그) 를 운반해야 함. Provenance 없는 규칙은
  스키마 검증 실패.
- **LLM-생성 후보** 는 자율 discovery 루프가 활성화되고 그 quality gate가 사용 가능해지기 전에는
  카탈로그에 진입하지 않음.

**TBD**: 첫날 시드 세트에 어떤 소스가 실리고 정확한 규칙 id — Phase 1의 "소스별 초기 대상 세트
열거"와 동일한 open 항목
([phase-1-rule-catalog-t0-ko.md](phases/phase-1-rule-catalog-t0-ko.md)).

## 이벤트 소스 부트스트랩

이벤트가 판단되기 전에 ingress는 Azure 신호에 부착되어야 함:

1. **Diagnostic Settings** — 대상 구독과 각 in-scope 리소스 그룹에서, Activity Log(과 리소스별
   로그)을 **Event Hubs Kafka 토픽** 으로 forward 하는 Diagnostic Settings 활성화 — 이것이
   CSP-중립 이벤트 버스 계약
   ([csp-neutrality-ko.md § 이벤트버스 계약](csp-neutrality-ko.md#1-이벤트버스-계약--kafka-와이어-프로토콜)).
2. **Kafka 토픽 + 컨슈머 그룹** — Event Hubs 네임스페이스에 첫날 토픽들을 생성
   (`aw.change.events`, `aw.dr.events`, `aw.finops.events`, 그리고 그들의 `<topic>.dlq`
   형제) 하고 `event-ingest` 를 위한 컨슈머 그룹 등록.
3. **Idempotency prime** — event-ingest 레이어가 처음 수신 시 모든 들어오는 이벤트에
   **idempotency 키** 를 스탬프하여 리플레이가 종단 no-op.
4. **DLQ 도달 가능성 검증** — dead-letter 목적지 (Kafka `<topic>.dlq`) 가 어디에서든
   enforce가 활성화되기 전에 실행됨 (poison-pill 프로브).

구체적 이벤트 타입과 필터 표현식은 **TBD** 이며
[deploy-and-onboard-ko.md#event-source-subscription](deploy-and-onboard-ko.md#event-source-subscription)
에 캡처.

## 모델 프로비저닝 부트스트랩

T2가 실행되기 전에 capability→deployment 매핑이 해결되어야 함. 이는 `azd up` 시점에 자동이며
수동 스텝이 아님:

1. **Resolver가 `rule-catalog/llm-registry.yaml` 에서 실행** — capability별 선호를 읽고,
   대상 리전의 Azure OpenAI / Foundry 카탈로그를 쿼리, `capacity_tpm` 상한과 함께 capability당
   하나의 deployment 프로비저닝.
2. **Mixed-model 불변식 검증** — `t2.reasoner.primary.publisher` 는 `t2.reasoner.secondary.
   publisher` 와 달라야 함, 아니면 부트스트랩 중단 (조용한 same-vendor fallback 없음). 포크의
   `llm.mixed_model_mode` (`azure-foundry` / `external` / `hil-only`) 가 전략 선택.
3. **`resolved-models.json` 이 Key Vault에 기록** — capability → `{deployment, family,
   version, publisher}`. 이후 모든 감사 엔트리는 케이스를 결정한 정확한 모델을 이름 지음.
4. **주간 reconciler 활성화** — Container Apps Job이 새 패밀리와 폐기 공지를 감시; 레지스트리에
   대해 **draft PR** 을 오픈하지만 라이브 매핑을 절대 auto-swap 하지 않음.

전체 설계: [llm-strategy-ko.md § Model Provisioning and Lifecycle](llm-strategy-ko.md#model-provisioning-and-lifecycle).

## Shadow-First 롤아웃 레시피

모든 새 배포는 전체 footprint에 대해 **shadow-only 모드** 로 랜딩. 승격은 액션별, 규칙별,
도메인별 — 절대 글로벌 flip 아님. 제안된 마일스톤 (모든 타임라인은 **방향성** ; 게이트는 하드):

| 마일스톤 | 초점 | 진행 게이트 |
|----------|------|-------------|
| **D+0 → D+7** | 루프가 shadow에서 종단 실행 검증: 이벤트 랜딩 → 티어 결정 → 감사 기록 | 조용한 드롭 0, 미인증 액션 0, canary green |
| **D+7 → D+14** | 규칙별 shadow 정확도 + false-positive 비율 측정; 저위험 승격 후보 식별 | [goals-and-metrics-ko.md](goals-and-metrics-ko.md) 에 따른 shadow 표본 크기와 정확도 임계 |
| **D+14 → D+30** | 소수의 첫 저위험 규칙 배치를 `remediate` (PR-only) 로 승격, 모호한 것은 HIL | shadow 윈도우 내 정책 위반 escape 0 |
| **D+30 →** | 지속적 승격 사이클, 한 번에 한 규칙, 각각 enforce-promotion 승인 게이트에 따라 | 회귀 스위트 green, 측정된 정확도 안정 |

전 구간 적용되는 규칙:

- 어떤 회귀는 승격된 규칙을 **자동으로 shadow로 강등** — 강등은 승격 승인자를 절대 필요로 하지
  않아 안전 방향 저하는 항상 빠름
  ([rule-governance-ko.md](rule-governance-ko.md#effects-mode)).
- Enforce 승격은 제안한 운영자와 **별도 승인** 필요
  ([security-and-identity-ko.md](security-and-identity-ko.md)).
- Kill-switch는 D+7 종료 전에 도달 가능성 검증.

## HIL 승인자 부트스트랩

어떤 enforce-mode 규칙도 승격되기 전에 승인자 그룹이 프로비저닝되어야 함. 승인자가 없으면
고위험 finding은 fallback 채널을 통해 큐잉되고 알림; **절대 auto-execute 안 함**. Entra 그룹
모델은 [user-rbac-and-identity-ko.md](user-rbac-and-identity-ko.md) 에 정의.

단계 (포크 책임):

1. HIL A1 트래픽과 다이제스트를 위해 `aw-approvers` 로 백업된 Teams **그룹-연결 팀** 생성;
   멤버십은 이후 Entra 그룹을 자동 추종
   ([channels-and-notifications-ko.md#51-audience-derivation-channel-as-audience](channels-and-notifications-ko.md#51-audience-derivation-channel-as-audience)).
2. 5개 Entra 보안 그룹 (`aw-readers`, `aw-contributors`, `aw-approvers`, `aw-owners`,
   `aw-break-glass`) 프로비저닝, config slot에 objectId 주입
   ([user-rbac-and-identity-ko.md#42-security-groups-slots](user-rbac-and-identity-ko.md#42-security-groups-slots)).
3. `aw-approvers`/`aw-owners` 에 Conditional Access 적용: phishing-resistant MFA 필수,
   legacy auth 블록; `aw-owners` 에 compliant-device 추가
   ([user-rbac-and-identity-ko.md#43-conditional-access](user-rbac-and-identity-ko.md#43-conditional-access)).
4. enforce 승격, 예외, override에 **quorum-2** 규칙을 유지하는 데 필요한 최소 멤버 수로
   `aw-approvers` 채움
   ([user-rbac-and-identity-ko.md#51-codeowners-single-approver-group-path-based-reviewer-count](user-rbac-and-identity-ko.md#51-codeowners-single-approver-group-path-based-reviewer-count)).
5. executor의 Chat 어댑터 config에 승인자 그룹 id 등록하여 Adaptive Card 승인이 롤 claim을
   검증할 수 있게 함.
6. **Slack 워크스페이스 프로비저닝** (P1 A1 채널): AIOpsPilot Slack 앱 설치, `chat:write`
   부여, 필수 Slack userId ↔ Entra OID 매핑 저장소 채움; 매핑이 비어 있지 않을 때까지 Slack
   어댑터는 A1 트래픽 거부
   ([channels-and-notifications-ko.md#7-channel-specific-notes](channels-and-notifications-ko.md#7-channel-specific-notes)).
7. `rule-catalog/channel-routing/` config (primary/fallback 채널, 다이제스트 스케줄, 오디언스)
   를 규칙과 같은 리뷰 엄격도로 커밋; A1 라우팅을 만지는 모든 변경은 Owner-티어 리뷰어 필요.
8. 카나리 경로를 통해 **dry-run HIL** 실행하여 승인이 랜딩하고 `justification` 이 요구되고
   timeout이 fail-closed이고 모든 승인이 `correlation_id` 있는 감사 엔트리를 씀을 확인.

## 자율 Discovery 루프 시동

[자율 규칙 discovery 루프](rule-catalog-collection-ko.md#autonomous-rule-discovery) 는
**첫날에 비활성**. 다음 모두 이전에 실행되어선 안 됨:

1. 감사 로그가 최소 **`N` shadow 결정** 을 축적하여 observe 스테이지에 실제 베이스라인 제공.
   `N` 은 설정 가능; **TBD** — 낮은 수천대 권장.
2. 최소 하나의 컬렉터가 성공 실행(배선 + provenance 증명).
3. Mixed-model 교차 검사 대상과 결정론적 verifier가 건강.
4. Post-deploy smoke 테스트가 green
   ([operating-and-verification-ko.md](operating-and-verification-ko.md#post-deploy-smoke-tests)).

활성화되면 루프는 설정된 주기로 실행. 루프의 후보 규칙은 전체 quality gate를 통과할 때까지
inert — 루프는 카탈로그를 직접 변형할 수 없음.

루프 비활성화는 **정책 토글** ,  코드 변경 아님; 반복되는 override 신호는 다음 활성화를 위해
감사 로그에 계속 축적됨.

## 라이프사이클 상태

모든 아티팩트는 정의된, 감사 가능한 상태를 진행. 전이가 유일한 이동 방법; 각 전이는 버전되고
감사됨.

- **Rule / rule-set** — `draft → audit(shadow) ⇄ enforce(deny/remediate) → deprecated`,
  `disabled` 은 어떤 활성 상태에서도 도달 가능
  ([rule-governance-ko.md#lifecycle-and-versioning](rule-governance-ko.md#lifecycle-and-versioning)).
- **Assignment** — 스코프, `effect`, `enforcement` 플래그에 바인딩. Effects는 승격 게이트 하에
  전이; 회귀는 자동 강등.
- **Exemption** — `active → expired` (time-boxed; auto-renew 없음)
  ([rule-governance-ko.md#exemptions](rule-governance-ko.md#exemptions)).
- **Override** — `active → removed`; long-lived 가능(강제 만료 없음), 스코프는 resource-group-
  equivalent 이하이어야 함
  ([rule-governance-ko.md#overrides](rule-governance-ko.md#overrides)).
- **Action** — `proposed → risk-gated → executed | rejected → rolled-back (해당 시)`. 모든
  상태가 idempotency 키를 운반하여 리플레이는 no-op.

## Open Decisions

- [ ] 콜드-스타트 데드라인 값과 정확한 콜드-스타트-메트릭 이름.
- [ ] 첫날 시드 규칙 세트(어떤 소스, 어떤 규칙 id) — Phase 1과 교차 링크.
- [ ] Discovery-루프 시동 임계 `N` (shadow-decision 카운트) 과 그 회귀-안전 근거.
- [ ] Kafka 토픽 레이아웃 + Diagnostic-Settings 포워더 필터 형상과 소스별 속도 상한.
- [ ] 부트스트랩 런북: 포크가 D+0에 도달하기 위한 정확한 명령 시퀀스 (
      [operating-and-verification-ko.md](operating-and-verification-ko.md#runbook-set) 소유).
- [ ] Dry-run HIL 절차: 카나리 페이로드, 예상 타이밍, 정리.
