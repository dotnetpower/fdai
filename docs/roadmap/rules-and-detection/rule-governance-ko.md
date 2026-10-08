---
title: 규칙 거버넌스(Rule Governance)
translation_of: rule-governance.md
translation_source_sha: f29f619d2a798d3edca164d45f4045a45482e1f8
translation_revised: 2026-10-08
---

# 규칙 거버넌스(Rule 거버넌스)

관리자가 규칙을 어떻게 **컨트롤** 하는가 - 작성, 파라미터화, 범위 지정, 활성화, 예외 처리 -
Azure Policy가 운영자에게 정의, 할당, 예외를 관리하게 하는 방식으로. 이는 규칙 카탈로그
위의 사람 대상 컨트롤 표면입니다.

[rule-catalog-collection-ko.md](rule-catalog-collection-ko.md) 의 수집·정규화 규칙과
[phase-1-rule-catalog-t0-ko.md](../phases/phase-1-rule-catalog-t0-ko.md) 의 결정론적 평가 위에
구축됩니다. Console은 권한이 없는 Operator API를 통해 형식화된 요청을 제출하며 관리
리소스 실행 신원을 받지 않는다는 애플리케이션 구조 규칙
([app-shape.instructions.md](../../../.github/instructions/app-shape.instructions.md))을 따릅니다.
Rule 활성화에는 검토된 pull request, 인증된 직접 요청 또는 서명된 오프라인 패키지를 사용할
수 있으며, 모든 경로는
[architecture.instructions.md](../../../.github/instructions/architecture.instructions.md)의
shadow-before-enforce 및 안전 불변식을 유지합니다.
관찰 우선 제품 기본값은 규칙을 감사, 재생 및 자문 근거에만 사용하며 enforce 조립에는 명시적 `governed-execution` 추가 기능과 기존 권한이 모두 필요합니다.

> 고객-비종속: 아래 모든 식별자, 스코프, 값은
> [generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md) 에
> 따라 합성 자리 표시자.

## 카탈로그 검색

규칙 검색은 A0 읽기 프로젝션이며 정책, 승인 또는 실행 권한을 부여하지 않습니다. 프로덕션
`CatalogSemanticIndex` 어댑터는 근거가 확인된 Rule 문서를 PostgreSQL과 `pgvector`에 저장하고,
대소문자를 구분하지 않는 정확한 Rule id, `tsvector` 어휘 순위, 벡터 코사인 순위, 타입이 지정된
이웃 유사도를 결정론적 reciprocal 순위 fusion(RRF)으로 결합합니다. 점수가 같으면 안정적인 Rule
id 순서로 결정합니다.

어휘 변환 결과에는 검토된 활성 카탈로그와 재귀적으로 가져온 수집 말뭉치가 모두 포함됩니다.
각 항목은 `active` 또는 `collected` 출처를 유지합니다. 수집 항목은 조회 전용 참조 기록으로
유지되며 활성 Catalog topology, T0 평가 또는 Workflow 입력에 합쳐지지 않습니다.

인덱스는 요청 및 Operator API 시작 경로 밖에서 빌드합니다. 기계적 워커는 정확한 Rule,
ActionType, Rego, 온톨로지 release 및 promoted 표면 근거를 로드하고 하나의 완전한 세대를
단계한 다음 독립된 검증 증적이 있을 때만 활성 말뭉치 포인터를 변경합니다. 근거가
누락되거나 일치하지 않으면 이전 세대를 활성 상태로 유지합니다. 읽기 전용 `/rules` 경로는
활성 세대가 현재 Git 카탈로그와 일치할 때만 의미 순위를 사용합니다. 그렇지 않으면
명시적인 stale 또는 사용 불가 상태와 함께 현재 lexical 변환 결과를 반환합니다. 전체 계약은
[Rule 의미 검색](rule-semantic-retrieval-ko.md)을 참조하세요.

## 모델 (Azure Policy처럼 세 레이어)

Azure Policy는 *정의* 를 *할당* 과 *예외* 에서 분리. FDAI가 이를 미러링해 관리자가
익숙한 정신 모델을 가짐:

| Azure Policy 개념 | FDAI 아티팩트 | 무엇인가 |
|------------------|----------------------|---------|
| 정책 정의 | **룰** | 하나의 테스트 가능한 컨트롤 ([rule-catalog-collection-ko.md](rule-catalog-collection-ko.md)) |
| initiative (정책 집합) | **룰 집합** | 이름 있고 버전된 규칙 그룹 (예: 보안 베이스라인) |
| 배정 | **배정** | 스코프에 적용된 룰/rule-set, 파라미터와 효과 포함 |
| 배정 `enforcementMode` | **적용 플래그** | `enforce` vs `do-not-enforce` (shadow); 효과와 직교 |
| exemption (waiver / mitigated) | **exemption** | 범위가 제한된 Azure 범위에서 규칙을 time-boxed, justified하게 억제; 배정/category 메타데이터는 향후 스키마 작업 |
| 효과 (감사/거부/...) | **효과 / 모드** | 위반 시 무엇이 일어나는가 (Effects 참조) |

규칙은 **할당** 이 그것을 **스코프** 에 **효과** 와 함께 바인딩하기까지 inert. 이것이 관리자
컨트롤의 핵심: 저자는 한 번 규칙을 작성; 운영자는 *어디*, *얼마나 엄격하게*, *어떤 파라미터로*
적용할지 결정.

## Effects (모드)

효과는 안전 다이얼. 단순 라벨이 아니라 shadow→강제 적용 라이프사이클에 매핑:

| 효과 | Azure Policy 유사 | 의미 | 안전 티어 |
|--------|-------------------|------|-----------|
| `disabled` | `disabled` | 규칙/할당 오프 | inert |
| `audit` | `audit` / `auditIfNotExists` | 판단하고 로그만, 변경 없음 (**shadow 모드** 등가) | 안전 기본 |
| `deny` | `deny` / `denyAction` | PR/admission 게이트에서 비준수 변경 블록 | 강제 적용 (게이팅) |
| `remediate` | `modify` / `deployIfNotExists` | auto-remediation PR 생성 (auto-merge 절대 아님; 항상 risk 게이트 / HIL 통해) | 강제 적용 (게이팅) |

효과(위반 시 무엇을 할지)는 **적용 모드** (액션할지 여부)와 직교, Azure Policy의
`enforcementMode` 미러링. 할당은 둘 다 운반: `effect` + `enforcement: enforce | do-not-enforce`.
`do-not-enforce` 는 검사를 what-if로만 실행하며 `audit`/shadow의 메커니즘; 강제 적용로의 승격이
승격 게이트 하에 이 플래그를 flip. **룰 집합** 은 규칙별 `default_effect` 를 선언 가능하고
**할당** 은 규칙별로 오버라이드 가능(`effect_overrides`), 마치 initiative가 effects를 설정하고
할당이 튠하는 것처럼; 할당의 top-level `effect` 는 오버라이드 없는 규칙의 기본값.

**허용된 효과/적용 전이** (아래 나열되지 않은 전이는 CI에서 거부):

| From | To | 게이트 |
|------|----|----|
| `disabled` | `audit` | 표준 리뷰 |
| `audit` (shadow) | `deny` / `remediate` (강제 적용) | **별도 enforce-promotion 승인** |
| `deny` / `remediate` | `audit` | 표준 리뷰 (강등은 항상 허용 - 불확실할 때는 안전한 쪽을 선택) |
| 어떤 활성 상태 | `disabled` | 표준 리뷰 (사유 기록) |

- **새 할당은 `audit` (shadow) + `enforcement: do-not-enforce` 기본.** `deny`/`remediate`
  으로의 승격은 (1) 최소 shadow dwell 시간과 표본 크기, (2) 임계 위 측정 shadow 정확도, (3)
  정책 위반 escape 0 을 게이트로 하는 명시적·별도 리뷰된 변경
  ([architecture.instructions.md](../../../.github/instructions/architecture.instructions.md)).
- 관찰 우선 프로필은 이 근거를 활성화 권한으로 사용할 수 없습니다. 자문 품질과 드리프트만 기록하며 명시적 `governed-execution` 추가 기능만 이 게이트에 진입할 수 있습니다.
- 회귀는 할당을 `audit` 로 **자동 강등**; 강등은 승격 게이트를 절대 필요로 하지 않아 안전 저하는
  항상 빠름.
- 할당의 **부재** 는 규칙이 그 스코프에서 미강제 (거버넌스는 default-audit, default-deny 아님);
  이것은 런타임에 fail 열림이 아님 - 매칭되지 않거나 모호한 이벤트는 여전히
  [architecture.instructions.md](../../../.github/instructions/architecture.instructions.md) 에
  따라 HIL로 라우팅.
- `deny`/`remediate` 액션은
  [coding-conventions.instructions.md](../../../.github/instructions/coding-conventions.instructions.md)
  의 7개 안전조건(stop-condition, 롤백, blast-radius 한도, 예행 실행, 리소스 잠금,
  멱등성, 감사 항목) 운반. 오발동
  `deny` 는 글로벌 비상 정지 또는 time-boxed exemption으로 복구 가능(그 영향 범위는
  *정당한 변경을 블록* ); `remediate` PR은 멱등 - 재평가된 발견 사항은 중복 오픈이 아니라 열린
  PR 업데이트.

## 스코프(범위)

스코프는 할당이 커버하는 리소스를 CSP-중립적으로 선택:

- **계층**: organization → 계정/구독 → resource-group → 리소스.
- **셀렉터**: resource-type별, tag/라벨별, 명시적 resource-id 허용 목록별.
- **제외**: 스코프는 자식 스코프 제외 가능(예: org-wide 적용하되 샌드박스 제외).
- 스코프는 데이터; 실행기는 여전히 최소권한 아이덴티티와 액션 화이트리스트만 보유
  ([security-and-identity-ko.md](../architecture/security-and-identity-ko.md)) - 광범위 스코프는 실행 권한을
  절대 넓히지 않음.
- **스코프 우선순위**: 중첩된 스코프가 같은 규칙을 바인드할 때, 파라미터는 **가장 구체적인
  스코프가 승리** ; 충돌하는 *effects* 는 **가장 엄격한 효과가 승리**
  (`deny` > `remediate` > `audit` > `disabled`), 진짜 동점은 HIL로 escalate -
  [phase-1-rule-catalog-t0-ko.md](../phases/phase-1-rule-catalog-t0-ko.md#deduplication-conflict-and-precedence)
  의 결정론 순서와 일관.
- **같은 룰+범위의 충돌 할당** 은 같은 strictest-effect-wins 규칙으로 해결; 지는 할당은
  감사 트레일에 기록되어 해결이 리뷰 가능하며, time-boxed exemption이 엄격한 결과를 완화하는
  유일한 승인 방법.

## 관리자 제어 흐름

관리자는 환경에서 사용할 수 있는 전달 채널을 선택할 수 있습니다. 연결된 설치에서는
catalog-as-code pull request를 검토할 수 있습니다. GitHub에 접근할 수 없는 설치에서는
Operator API를 통해 인증된 직접 변경을 제출할 수 있습니다. 공용 산출물 송신이 없는
네트워크에서는 같은 변경 계약을 서명된 오프라인 패키지로 가져올 수 있습니다.

세 채널은 권위 변경 전에 다음 흐름으로 합쳐집니다.

1. 채널은 예상 세대, 안정적인 멱등성 키, 요청한 구성원 차이, 사유, 범위, 출처 근거 및
  인증된 요청자를 포함한 버전형 `RuleActivationChange`를 생성합니다.
2. 서버는 완전한 후보 세대를 검증하고 현재 승인 근거를 확인하며, 오래되거나 모호하거나
  자기 승인된 입력과 권한을 높이는 입력을 차단합니다.
3. Mimir는 Rule 수명 주기의 책임 주체입니다. 검증에 성공한 뒤 Core PostgreSQL에 하나의
  불변 세대를 원자적으로 설치하고 현재 포인터를 변경합니다.
4. Saga는 요청, 승인, 이전 및 결과 세대 다이제스트, 행위자 신원, 출처 채널 및 최종 결과를
  추가 전용 감사 체인에 기록합니다.
5. 런타임은 변경을 적용된 것으로 보고하기 전에 정확한 현재 세대를 다시 읽습니다. 충돌하거나
  재확인에 실패하면 이전 세대를 계속 활성 상태로 유지합니다.

PostgreSQL의 현재 세대 포인터는 배포별 Rule 구성원 상태의 단일 진실 원본입니다. Git과 서명된
패키지는 인증된 작성 및 전달 채널이며 런타임 의존성이 아닙니다. 직접 요청은 브라우저의 SQL
접근을 의미하지 않습니다. Console은 Operator API에 형식화된 요청을 보내고, Operator API는
권한 없는 제안을 영속화한 뒤 Core가 소유하는 검증 및 적용을 위해 이벤트 버스로 게시합니다.

각 Core replica는 이 포인터를 대상으로 범위가 제한된 조정 루프를 실행합니다. replica는 자체
generation digest가 다를 때만 메모리의 Rule 멤버십을 교체하고, 교체 전에 모든 멤버를 정확한
설치 Rule 아티팩트와 대조합니다. 승인 재처리도 이 조정을 수행하므로 영속 pointer commit 후
runtime 교체가 실패해도 권위 전이를 다시 실행하거나 되돌리지 않고 복구할 수 있습니다.

구성원 상태는 실행 권한과 독립적입니다. 활성 세대에 Rule을 추가하면 관찰 모드에서 T0 평가
대상이 됩니다. 이 작업은 배정 효과를 변경하거나 `do-not-enforce`를 `enforce`로 바꾸거나,
승격 게이트를 충족하거나, 승인을 부여하거나, Operator API에 실행기 신원을 부여하지 않습니다.
구성원 제거는 기능을 낮춥니다. 적용 모드 승격은 기존의 별도 승인과 승격 레지스트리를 계속
사용합니다.

연결된 pull request 채널은 기존 검토 흐름을 유지합니다.

검토된 profile rollout은 Core에 `FDAI_PROFILE_ID`, `FDAI_RULE_ACTIVATION_SOURCE`,
`FDAI_RULE_ACTIVATION_SOURCE_REF`, `FDAI_RULE_ACTIVATION_PACKAGE_DIGEST`,
`FDAI_RULE_ACTIVATION_SOURCE_RECORDED_AT`을 제공합니다. Pull request 및 오프라인 source는
5개 값을 모두 제공해야 합니다. Core는 해석한 profile 멤버십을 현재 데이터베이스 세대와
비교하고 같은 CAS ledger를 통해 정확한 차이를 적용합니다. source 메타데이터가 없거나
모호하면 멤버십을 넓히지 않고 시작 조정을 차단합니다.

![관리자 pull request 채널. 주요 단계는 administrator, draft change: rule / assignment / exemption, catalog-as-code PR, CI: schema + policy-as-code + shadow eval, review + approval, blocked, separate enforce-promotion approval, merge -> activation change, T0 loads the committed database generation입니다.](../../diagrams/generated/fdai-roadmap-rules-and-detection-rule-governance-01.ko.svg)

직접 변경과 오프라인 변경은 pull request 채널과 같은 검증 정책을 사용합니다. 승인 근거는
저장소에서 추론하지 않고 PostgreSQL에 저장합니다. 요청자와 승인자 신원은 검증된 principal에서
가져오고 서로 달라야 하며 정확한 후보 다이제스트에 바인딩됩니다. 동시 변경은 예상 세대에 대한
compare-and-set을 사용합니다. 서버는 충돌을 반환하며 권한을 포함한 변경을 암묵적으로 rebase하거나
재시도하지 않습니다.

성공한 각 세대는 직전 세대를 rollback 대상으로 저장합니다. Rollback도 감사되고 승인에
바인딩된 포인터 전이입니다. 실행 중인 결정은 사용한 세대를 고정하므로 이후 활성화가 결정 도중
Rule 신원이나 의미를 변경할 수 없습니다.

## 커스텀 규칙과 우선순위

관리자는 수집된(built-in) 규칙 옆에 **커스텀 규칙** 을 추가 가능, Azure Policy가 built-in
옆에 커스텀 정의를 허용하는 것처럼:

- 커스텀 규칙은 같은 스키마 사용, `source: custom` + shipped 전체 `provenance`
  (`source_url`, 변경할 수 없는 참조/해시, license/redistribution, 수집 시간, 선택적 mapper).
- 커스텀과 built-in 규칙이 겹칠 때의 **우선순위** 는
  [phase-1-rule-catalog-t0-ko.md](../phases/phase-1-rule-catalog-t0-ko.md#deduplication-conflict-and-precedence)
  의 결정론 순서 (심각도, 출처 priority, ties → HIL) 따름. 커스텀 소스는 명시적
  `priority_rank` 을 부여받아 오버라이드가 의도적·감사 가능, 우발 아님. 커스텀은 built-in을
  자동으로 능가하지 **않음** : built-in `deny` 를 *약화* 시킬 커스텀 규칙은 CI에서 플래그되고
  명시적 리뷰 필요, 컨트롤이 조용히 완화되지 않도록.
- 커스텀 규칙은 같은 shadow-before-enforce 라이프사이클 따름; 커스텀 `deny` 는 승격 게이트에서
  면제되지 않음.
- **신뢰할 수 없는 authored 입력**: 커스텀 규칙의 `check-logic`, `remediation`, 파라미터 값은 로드
  시 스키마로 검증되고 sandboxed 정책 엔진(OPA) 을 **통해서만** 평가 - 절대 셸이나 프로바이더
  API 호출로 string-interpolate 되지 않음 - 규칙 텍스트나 파라미터로부터의 주입 경로 폐쇄
  ([coding-conventions.instructions.md](../../../.github/instructions/coding-conventions.instructions.md)).

## Exemption

Exemption은 Azure Policy exemption처럼 스코프의 할당을 waive:

- 현재 필수 필드: `rule_id`, resource-group 또는 리소스로 좁혀진 Azure-shaped `scope`,
  **justification**, 서로 다른 `requested_by` / `approved_by` UUID, `state`, `created_at`,
  `expires_at`. 로더는 no self-exemption, 명시적 UTC 시각, `expires_at > created_at` 및
  일관된 terminal revocation 메타데이터를 강제합니다.
- 예외 아티팩트는 배정 저장소와 독립적으로 유지됩니다. 예약 만료는 배포 조립에서 검토된
  정확한 `ExemptionAssignmentBinding`을 받습니다. 연결이 없거나 모호하면 감사된 보류가
  발생하며, 조정기는 규칙 id나 프로바이더 범위에서 배정을 추측하지 않습니다.
- 구성된 **exemption 최대 기간** 과 **만료 전 알림 리드 타임**
  (`AppConfig.rule_governance.exemption_max_duration_days` /
  `exemption_alert_lead_days`, 리드 타임이 항상 최대 기간보다 짧도록 상호 검증됨) 이
  강제됩니다: 거버넌스 카탈로그 로더는 `expires_at - created_at` 이 구성된 최대치를
  초과하는 exemption을 거부하며 카탈로그 로드를 fail closed 합니다.
- 런타임 시작은 검토된 exemption JSON을 같은 불변 거버넌스 카탈로그에 로드하고,
  구독과 범위를 검증하는 registry를 안전성 검토에 바인딩합니다. 잘못되거나 중복된
  데이터, 알 수 없는 룰, 잘못된 ARM 리소스 id, 만료 및 revoked 상태는 실패 시 닫히거나
  매치되지 않습니다.
- Auto-renew는 지원되지 않습니다.
  `fdai.rule_catalog.schema.exemption_lifecycle.plan_exemption_lifecycle` 은 **예약
  만료 메커니즘** 과 **만료 전 알림** 을 위한 순수하고 결정론적인 판단 코어입니다: 모든
  active exemption에 대해 이미 `expires_at` 을 지났는지(`expire`) 또는 구성된 알림
  리드 타임 안에 있는지(`alert_ahead_of_expiry`) 를 판단합니다.
  `fdai.delivery.exemption_lifecycle.ExemptionLifecycleCoordinator`는 이 판단을
  주입 가능한 `ExemptionLifecycleNotifier`와 표준 추가 전용 감사 경계에 결합합니다.
  기본 구현은 로그만 남기며 네트워크를 사용하지 않습니다. 새로 알림 대상이 된 항목은
  각 예외의 정확한 개정과 요청자를 포함하는 버전 있는 다이제스트로 묶입니다. 원자적 상태
  선점으로 각 항목은 재실행과 복제본 간에 안전합니다.
- 만료 경로는 클라우드 프로바이더를 직접 호출하지 않습니다. 조정기는 활성 예외 개정과 예상
  만료 개정을 정확한 배정 id, 버전, 범위에 연결한 뒤 프로바이더 중립 `EventBus`를 통해
  `governance.reapply-rule-assignment` 제안을 게시합니다. 브로커 수락은
  `broker_accepted_not_executed`로 기록되며 실행 성공을 뜻하지 않습니다. ActionType은
  shadow 모드로 시작하고 T0에서 사람 승인을 요구합니다. 기존 Forseti, Var, Thor, Saga,
  Vidar 경계와 대상 잠금, 롤백, 독립 효과 검증을 그대로 유지합니다. 실제 재적용 전에
  소비자는 예상 최종 예외 개정을 다시 검증해야 합니다. 따라서 철회나 개정 충돌은 변경이
  아니라 보류를 만듭니다.
- 첫 대안은 발견 루프 신호가 범위를 직접 다시 평가하는 방식이었습니다. 이 경로에는 등록된
  변경 계약이 없고 관측과 권한의 경계를 흐릴 수 있습니다. 수정된 설계는 기존 형식화된 액션
  파이프라인을 사용하고 연결 누락, 게시자 사용 불가, 알 수 없는 브로커 결과를 감사된 보류로
  처리합니다. `scripts/governance/exemption-expire.py`는 검토된 카탈로그 아티팩트만
  갱신하며 관리형 리소스를 직접 변경하지 않습니다.
- 모든 exemption과 만료는 감사; exemption은 기저 발견 사항의 감사 기록을 절대 억제하지 않음 -
  발생 안 함이 아니라 *왜 수용됐는지* 기록.

## 재정의

> **현재 상태**: 구현됨. `fdai.rule_catalog.schema.override.Override` +
> `override.schema.json` + `load_override_from_mapping` + `<root>/overrides/` 디렉터리
> 로더(`GovernanceCatalog.overrides`) 가 아래의 모든 MUST 규칙을 카탈로그 로드
> 경계에서 강제하며, `resolve_override` + `apply_governance_override_to_rule` 이
> 배정 해석 위에 재정의를 T0 런타임에 적용합니다. parameter-relaxation 재정의의
> 키와 한계는 별도로 리뷰된
> [`rule-catalog/override-parameter-bounds.yaml`](../../../rule-catalog/override-parameter-bounds.yaml)
> 정책과 대조되며, 목록에 없는 키나 한계를 벗어난 값은 카탈로그 로드를 fail closed
> 합니다 - 정책 위반에 대한 런타임 HIL 폴백은 없고 로드 시점의 거부만 있습니다.
> 업스트림 배포판은 활성 재정의도, 완화 가능한 규칙도 출하하지 않습니다(정책
> 파일은 기본적으로 비어 있음).

**재정의** 는 자동화된 quality 게이트 *위* 의 사람 컨트롤 표면: 운영자가 규칙이 특정 환경에서
너무 공격적이라고 선언하고 규칙을 편집하지 않으면서 좁히거나, 강등하거나, 비활성화. 재정의는
[architecture.instructions.md](../../../.github/instructions/architecture.instructions.md#human-override)
가 말하는 "human 재정의 on top" 의 의미. Exemption을 대체가 아니라 보완.

### 언제 어느 것을 사용

| 상황 | 사용 |
|------|-----|
| 특정 리소스에 범위가 제한된 시간 동안 accepted-risk 또는 mitigated waiver | **exemption** (time-boxed) |
| 규칙 자체가 resource-group에 대해 체계적으로 너무 공격적, 무기한 | **재정의** (permanent 가능) |
| 규칙이 어디서든 잘 맞지 않고 존재해선 안 됨 | 재정의가 아니라 카탈로그 파이프라인을 통한 **룰 retirement** |

재정의는 개별 발견 사항의 waiver가 아님 - 규칙의 shipped 동작이 이 환경과 매칭되지 않는다는
스코프된 정책 자세.

### 규칙 (MUST)

- **Policy-as-code, 별도 아티팩트.** 재정의는 자체 catalog-as-code 엔트리 (`종류:
  재정의`); 대상 규칙 텍스트를 절대 편집하지 않음. 재정의 제거는 규칙을 자동 복원, 상류
  규칙 업데이트는 건드리지 않고 흘러감.
- **스코프는 resource-group-equivalent 이하이어야 함** - 위 스코프 계층의 `resource-group`
  레이어, 또는 특정 `resource`. Organization·계정/subscription-wide 재정의는 CI에서
  거부; 어디서든 규칙 비활성화는 재정의가 아니라 카탈로그 파이프라인을 통한 **룰
  retirement**.
- **허용 모드**: `disabled` (스코프에서 규칙 오프), `severity-downgrade` (예:
  `critical -> medium`), `parameter-relaxation` (규칙 스키마가 선언한 범위 내에서 임계 확대).
  다른 어떤 확대도 거부.
- **강제 만료 없음**: 재정의는 수명이 긴 가능; `expires_at` 은 선택. Exemption과의 핵심
  차이. Justification은 항상 필수.
- **별개 승인자**: 요청자는 승인자가 되어선 안 됨 (no self-override), exemption 규칙과
  [security-and-identity-ko.md](../architecture/security-and-identity-ko.md) 의 승인≠실행 경계 미러링.
- **Shadow는 계속 실행**: 재정의는 스코프의 *실행* 을 비활성화, 감지 아님. 평가기는 규칙이
  플래그했을 것을 계속 기록하고 그 발견 사항을
  [rule-catalog-collection-ko.md](rule-catalog-collection-ko.md#autonomous-rule-discovery) 의
  자율 발견 루프에 공급.
- **Audit-first**: 모든 재정의 생성/수정/제거 이벤트는 추가 전용 감사 엔트리(행위자,
  사유, 대상 룰, 범위, 모드). 재정의는 기저 발견 사항의 감사 기록을 절대 억제하지 않음
  - 실행이 그 스코프에서 왜 억제됐는지 기록.

### 우선순위

- 재정의는 자신이 커버하는 스코프에서 할당의 효과보다 승리. 규칙이 승격 승인에서
  `effect: deny` 를 갖지만 resource-group `R` 의 재정의가 `mode: disabled` 를 설정하면
  규칙은 `R` 에서 inert이고 다른 곳에서 강제 적용.
- 재정의 스코프 밖에서는 [범위](#스코프scope) 의 표준 스코프 우선순위가 변경 없이 적용
  (most-specific 범위 wins, strictest 효과 wins, ties → HIL).
- 재정의는 **stack 되지 않음**: (룰, 범위) 쌍마다 최대 하나의 활성 재정의. 같은 쌍의
  두 번째 재정의는 첫 번째를 대체, 생성과 대체 이벤트 모두 감사.

### 피드백 루프

- 재정의는 발견 루프에 입력
  ([rule-catalog-collection-ko.md](rule-catalog-collection-ko.md#override-feedback)). 규칙이
  스코프에 걸쳐 반복되거나 수명이 긴 재정의를 누적하면 루프는 **개정 번호** (규칙 좁힘)
  또는 **retirement** (규칙이 체계적 poor fit) 제안; 어느 제안이든 카탈로그에 진입 전 quality
  게이트 통과 필요.
- 모든 T0 재정의 해석은 `governance.override_resolved` 추가 전용 감사 엔트리(`rule_id`,
  `override_id`, `override_mode`, `override_scope`) 를 남깁니다 - 반복되거나 수명이 긴
  재정의를 인식하기 위해 `DiscoverySignalKind.OVERRIDE` 신호
  (`operational_learning/discovery_contracts.py`) 가 결국 조회할 구체적 증거
  원본입니다. 이를 위한 `object.override` 버스 토픽은 없으며
  (agent-pantheon.instructions.md), 신호 임계값 자체(개정/retirement 제안 전 필요한
  고유 스코프 수, 체류 시간, shadow-hit 비율) 는 아래 열림 결정으로 남아 있고, 이
  증거를 위한 구체적 `DiscoverySignalSource` 바인딩은 다른 모든 discovery 신호
  종류가 여전히 필요로 하는 것과 같은 composition-root seam입니다.
- 콘솔은 운영자에게 "over-overridden 룰" 뷰를 표면화 가능; 읽기 전용 유지, 개정 번호/
  retirement 제안은 여전히 PR.

## RBAC (누가 무엇을 할 수 있는가)

작성, 승인, 할당, 예외 처리는 **별개 권한** - no 자기 승인,
[security-and-identity-ko.md](../architecture/security-and-identity-ko.md) 의 승인≠실행 규칙
미러링. 이들은 **논리적** 거버넌스 롤; 소수의 Entra 보안 그룹(읽기 담당 / 기여자 / Approver
/ Owner + Break-Glass) 에 매핑 ([user-rbac-and-identity-ko.md](../interfaces/user-rbac-and-identity-ko.md)).
여러 논리 역할은 같은 Entra 그룹에 속할 수 있습니다. 자기 승인 차단은 그룹 분리가 아니라 PR
작성 정보를 기준으로 CI에서 적용합니다. 고위험 승인(`audit → deny / remediate`, 예외, 재정의,
A1 채널 라우팅)은 `aw-approvers`의 **정족수 2**를 요구합니다.

| 논리 롤 | Entra 그룹 | 가능 | 불가 |
|---------|-----------|------|------|
| Rule 저자 | `aw-contributors` | 규칙/룰셋 제안 (초안 PR) | 자신의 변경 승인 또는 할당 |
| Approver | `aw-approvers` | 거버넌스 PR 리뷰/승인 | 승인하는 변경 저자 |
| 배정 운영자 | `aw-contributors` | 규칙을 스코프에 바인딩, 파라미터/효과 설정 (PR 경유) | 단독으로 강제 적용 승격 승인 |
| Enforce-promotion 승인자 | `aw-approvers` (quorum-2) | `audit`→`deny`/`remediate` 승격 승인 | 승격을 제안한 운영자 |
| Exemption 승인자 | `aw-approvers` (quorum-2) | Time-boxed exemption 승인 | 영구 exemption 부여, 자신의 요청 승인 |
| 재정의 승인자 | `aw-approvers` (quorum-2) | Resource-group-스코프 재정의 승인 (permanent 가능) | resource-group-equivalent 밖 재정의 승인, 자신의 요청 승인 |
| A1 라우팅 승인자 | `aw-approvers` (정족수 2) | 결정을 전달하는 기본 또는 대체 경로 변경 승인 | 자신이 제안, 공동 작성 또는 커밋한 경로 승인 |
| 룰 retirement 승인자 | `aw-approvers` (quorum-2, Owner 수준) | 전역 enforce 집합에서 룰을 제외하는 변경 승인 | 정족수에 Owner 수준 검토자가 없는 retirement 또는 자신의 요청 승인 |

해당 표의 결정론적 결정 코어는 `fdai.rule_catalog.schema.governance_review_authority` 입니다.
공유 롤/역량 행렬을 읽고, 비어 있지 않은 운영자 객체 id를 기록하고, 정확한 pull request head
리비전을 검토했으며, 그 리비전 이후 시각에 기록되었고, 변경 클래스가 요구하는 역량을 보유하며,
고위험 클래스의 phishing-resistant 요건을 충족하는 승인만 계수합니다. 한 운영자의 반복 승인은
한 번만 계수되고, 작성자·공동 작성자·커미터의 승인은 다른 승인이 이미 정족수를 채웠더라도 변경을
차단합니다. 이 결정은 검토 전용이며 실행 권한을 부여하지 않습니다.

이들 거버넌스 롤 중 어느 것도 **실행기의** 아이덴티티를 보유하지 않음; 규칙 작성/승인은
액션 실행 능력을 절대 부여하지 않음. 강제 적용 승격, exemption, 재정의는 가장 높은 특권
거버넌스 행위이며 `aw-approvers` 와 `aw-owners` 에 대한 Conditional 접근을 통해 강제되는
MFA / phishing-resistant, 액션-바인딩 승인 필요
([security-and-identity-ko.md](../architecture/security-and-identity-ko.md),
[user-rbac-and-identity-ko.md#conditional-access](../interfaces/user-rbac-and-identity-ko.md#43-conditional-access)).

**Risk-classification 테이블** ([risk-classification-ko.md](../decisioning/risk-classification-ko.md)) 은
각 매칭을 어떻게 라우팅(`auto` / `hil` / `deny`) 할지 결정하는 형제 거버넌스 아티팩트. 규칙과
할당과 같은 PR 흐름으로 편집되며, 완화 변경에는 elevated 정족수와 Owner-티어 리뷰어 필요.

## 라이프사이클과 버전 관리

- 규칙, 룰셋, 할당은 versioned catalog-as-code입니다. Exemption은 고정된 id, 상태,
  creation/만료 시각을 가지지만 현재 스키마에는 산출물 `version`이 없습니다. Tracked 파일
  변경은 PR 이력으로 revert할 수 있습니다.
- 규칙 상태: `draft → audit(shadow) ⇄ enforce(deny/remediate) → deprecated`, `disabled` 은
  어떤 활성 상태에서도 도달 가능, `enforce → audit` 강등은 항상 가능. Deprecation은 규칙을
  tombstone (조용한 삭제 절대 아님) 하여 히스토리 재구성 가능.
- 규칙 로직 변경은 `version` bump; 할당의 파라미터/효과/범위 변경 자체가 감사된 버전 변경.
  Rule 집합은 각 멤버 규칙의 `version` 을 **고정** 하여 규칙 변경이 승격된 세트를 조용히 바꿀 수
  없음.
- **규칙 개정 업그레이드(미구현):** 활성화 세대는 각 멤버의 정확한 버전과 다이제스트를 고정하고,
  ledger는 카탈로그가 바뀌지 않은 상태의 멤버 변경만 받아들입니다. 따라서 활성화된 규칙의 내용을
  바꾸면, 업그레이드된 설치는 현재 세대가 설치된 산출물과 더 이상 일치하지 않아 시작 시 실패합니다.
  업그레이드 경로가 생기기 전에는 활성화된 규칙의 개정을 배포하지 않습니다. 시작 시 자동으로
  이어받는 방식은 검토에서 기각되었습니다. 배포 ID가 승격 없이 강제 적용 규칙의 동작을 바꿀 수 있고,
  승인에 정확한 대상 개정이 묶이지 않으며, 복제본 사이에 경합이 생기고, 순차 배포 중 이전 복제본이
  중단되며, 일반적인 릴리스 롤백이 불가능해지기 때문입니다. 업그레이드 경로에는 다음이 필요합니다.
  - 이전과 대상 버전, 규칙 다이제스트, 대상 세대를 승인된 제안 다이제스트에 묶는 명시적 개정 delta
  - 활성 멤버를 전체 카탈로그 다이제스트와 분리하는 활성화 ID
  - shadow 규칙에만 허용하는 무인 이어받기. 강제 적용 규칙의 개정은 shadow로 돌아가거나 버전별 승격
    승인을 가져야 하며, 승격 근거는 규칙 개정 단위로 기록해야 합니다.
  - 동시에 실행되는 복제본이 다시 읽기로 수렴하도록 릴리스에 묶인 결정적 요청 ID
  - 모든 복제본이 호환될 때까지 두 개정을 함께 보관하는 버전별 산출물 레지스트리와 준비, 활성화 단계
  - 산출물이 보관된, 이전에 기록된 세대로 돌아가는 감사된 롤백 전환

  두 번째 설계는 이전 개정을 보관 레지스트리에 두고 승인된 활성화 변경으로만 개정을 바꾸도록 했지만,
  검토에서 여전히 부족한 점이 확인되었습니다.
  - `rule_digest`는 규칙 정의만 포함하고 참조하는 Rego는 포함하지 않으므로, 정책을 수정하면 활성화나
    승인 ID가 바뀌지 않은 채 동작이 바뀝니다. 멤버 ID에 검증된 정책 내용 다이제스트가 필요하며, 이는
    저장된 모든 세대를 마이그레이션해야 합니다.
  - 해석할 수 없는 멤버를 보류하면 전체 세대의 ID로 일부 세대만 설치하게 됩니다. 현재 세대를 해석할 수
    없는 복제본은 마지막 완전한 세대를 유지하거나 준비되지 않음 상태가 되어야 하며, 목표 세대와 적용된
    세대를 따로 추적해야 합니다.
  - 개정 마이그레이션은 이전과 대상 카탈로그 ID를 명시해야 합니다.
  - 명시적 규칙 할당을 포함해 강제 적용하는 모든 바인딩에 개정 고정이 필요하며, 단계적 거버넌스
    전환이 있어야 합니다.
  - 검토된 시작 원본은 정확한 개정을 나열한 서명된 활성화 매니페스트를 가져야 합니다.
  - 저장된 제안과 결과에는 버전별 코덱이 필요합니다.

  이 작업이 완료될 때까지 `scripts/quality/architecture/check-rule-revision-lock.py`가 배포된 각 규칙의
  버전, 정규화된 정의 다이제스트, 정책 내용 다이제스트를 `rule-catalog/rule-revision-lock.json`에
  고정합니다. 내용을 그 자리에서 바꾸거나 규칙을 제거하면 검사가 실패합니다. 검사를 바꿔야 하면 새 규칙
  ID로 배포하며, 그 활성화는 일반적인 승인된 멤버 변경입니다.
- **테스트 가능성**: 모든 할당/exemption PR은 픽스처와 함께 나감 - 예상 매칭 세트(스코프가
  어떤 합성 리소스 선택) 와 강제 적용 승격의 경우 승격 게이트가 스코어한 shadow-eval 표본 -
  거버넌스 변경이 규칙 변경처럼 회귀 테스트되도록
  ([coding-conventions.instructions.md](../../../.github/instructions/coding-conventions.instructions.md)).

## YAML 형상

### Rule 집합 (initiative)

```yaml
schema_version: 1.0.0
kind: rule-set
id: ruleset.security-baseline
version: 1.0.0
members:
  - { rule_id: object-storage.public-access.deny, version: 1.0.0, default_effect: deny }
  - { rule_id: sql-database.tde-required, version: 1.0.0, default_effect: audit }
  - { rule_id: postgresql-server.point-in-time-restore, version: 1.0.0, default_effect: audit }
provenance:
  created_at: 2026-07-03T00:00:00Z
  created_by: governance-team
```

### 배정

```yaml
schema_version: 1.0.0
kind: assignment
id: assignment.security-baseline.prod
version: 1.0.0
rule_set: ruleset.security-baseline
scope:
  include:
    - scope://org/account-000/prod
  exclude:
    - scope://org/account-000/prod/sandbox
  selector:
    resource_types: [sql-database, postgresql-server, object-storage]
effect: audit
enforcement: do-not-enforce
effect_overrides:
  object-storage.public-access.deny: audit
parameter_overrides:
  postgresql-server.point-in-time-restore:
    min_retention_days: "14"
provenance:
  created_at: 2026-07-03T00:00:00Z
  created_by: assignment-operator
```

### Exemption

```yaml
schema_version: 1.0.0
id: exemption.legacy-store.public-access
rule_id: object-storage.public-access.deny
scope:
  subscription_id: 00000000-0000-0000-0000-000000000000
  resource_group: example-resource-group
justification: Documented migration remains in progress with a compensating control.
requested_by: <requester-entra-oid>
approved_by: <distinct-approver-entra-oid>
state: active
created_at: 2026-07-03T00:00:00Z
expires_at: 2026-09-30T00:00:00Z
```

`requested_by`와 `approved_by`는 배포가 제공하는 서로 다른 UUID여야 합니다. 여기서는 실제
테넌트 식별자를 저장소에 넣지 않기 위해 named 자리 표시자를 사용합니다.

### 재정의

```yaml
schema_version: 1.0.0
id: override.pitr-relaxation.rg-analytics
version: 1.0.0
kind: override
target_rule: postgresql-server.point-in-time-restore
scope: scope://org/account-000/rg-analytics
mode: parameter-relaxation
parameter_overrides:
  min_retention_days: "3"
justification: Non-critical analytics workloads with 3-day retention accepted by the data owner.
requested_by: 00000000-0000-0000-0000-000000000004
approver: 00000000-0000-0000-0000-000000000005
provenance:
  created_at: 2026-07-03T00:00:00Z
  created_by: assignment-operator
```

> `rule-set`, `assignment`, `exemption`, `override` 모두 거버넌스 카탈로그 로더가 읽는
> strict 스키마를 갖습니다(`<root>/overrides/*.yaml` -> `Override`); `exemption`은
> 집중 검증 및 만료 CLI도 유지합니다. 각 rule-set 멤버는 규칙 `version` 을 고정;
> 각 `parameter_overrides` 값은 대상 규칙이 그 파라미터에 선언한 타입에 대해
> 검증하는 것은 배정 쪽에서 아직 후속 작업이며 현재 배정 스키마는 문자열 값을
> 받습니다 - 재정의의 `parameter_overrides` 도 같은 문자열-값 계약에 더해 별도로
> 리뷰된 키/한계 allowlist(`rule-catalog/override-parameter-bounds.yaml`) 를
> 사용합니다. Exemption의 `requested_by`는 `approved_by`와 달라야 하며, 재정의의
> `requested_by`는 `approver`와 달라야 합니다(동일한 no-self-approval 규칙).
> 위 할당은 의도적으로 **완전히 shadow에 유지** - 룰 집합의
> `object-storage.public-access.deny` 에 대한 `deny` 기본이 `audit` 로 오버라이드되고 별도
> 승격 승인이 flip할 때까지 `enforcement` 는 `do-not-enforce`.
## 열림 Decisions

- [x] T0 런타임에서 이벤트의 정규화된 조직, 계정, 리소스 그룹, 리소스 계층을 사용해
      `scope://...`를 해석합니다. ID 일치는 대소문자를 구분하지 않으며 태그와 정규 리소스
      타입은 선언된 의미를 유지합니다.
- [x] 재정의 작성은 catalog-as-code 전용으로 유지합니다. P1 또는 P3에 Console 작성 UI를
      제공하지 않으며, 추가하려면 별도의 초안 전용 제품 설계가 필요합니다.
- [x] 재정의 매개 변수 값은 기존 문자열 와이어 계약을 유지합니다. 별도로 검토된 정책은
      유한 숫자 범위 또는 명시적 문자열 enum을 지원하며, 목록에 없거나 잘못되었거나
      비유한 값 또는 범위를 벗어난 값은 카탈로그 로드를 차단합니다.
- [x] 설정된 **최대 exemption 기간** 과 만료 사전 알림 lead 시간:
      `AppConfig.rule_governance.exemption_max_duration_days`(기본 180) 와
      `exemption_alert_lead_days`(기본 14), lead time이 항상 최대 기간보다 짧도록
      상호 검증됩니다.
- [x] "재정의 범위 is resource-group-equivalent or narrower" 를 스코프 URI 문법에 대해
      강제하는 정확한 검사: `Override.__post_init__` 이 `ScopeRef.level <
      ScopeLevel.RESOURCE_GROUP`(organization/계정 주소) 을 결정론적으로 거부하며,
      `test_override.py`의 `test_organization_scope_is_rejected` /
      `test_account_scope_is_rejected` 로 증명됩니다. 로드 경계 자체가
      `check-governance-transitions.py` 를 포함한 모든 호출에서 fail closed 이므로,
      exemption 디렉터리 검사와 동등한 CI 전용 경로 필터를 추가로 연결하는 것은
      이제 선택 사항입니다.
- [x] 규칙별 허용 `parameter-relaxation` 범위: **거버넌스 레벨 allowlist**
      (`rule-catalog/override-parameter-bounds.yaml`,
      `fdai.rule_catalog.schema.parameter_relaxation_policy`) 이지, 규칙 자체
      스키마(여전히 완화 범위를 선언하지 않음 - 이 결정의 나머지 절반은 열려 있음)
      가 아닙니다. 목록에 없는 키나 한계를 벗어난 값은 카탈로그 로드를 fail closed
      하며, 정책 위반에 대한 런타임 HIL 폴백은 없습니다.
- [x] 최초 "과도하게 재정의된" 신호는 서로 다른 범위 3개, 관측 14일, shadow 적중
      100건을 요구합니다. `OverrideDiscoverySignalSource`는
      `governance.override_resolved` 감사 레코드에 구성 가능한 양수 임계값을 적용하고
      비활성 `DiscoverySignalKind.OVERRIDE` 근거만 내보냅니다.

## 관련 문서

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| 구현 상태 및 남은 작업 | [구현 원장](../../roadmap-implementation/rules-and-detection/rule-governance.md) |
