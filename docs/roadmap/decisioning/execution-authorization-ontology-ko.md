---
translation_of: execution-authorization-ontology.md
translation_source_sha: abd0d3a8be19bfc9ccd51f86e742e04c3a7f9373
translation_revised: 2026-08-12
---
# 실행 권한 부여 온톨로지

이 문서는 프로바이더 역할이나 고객 정책을 `ActionType` 또는 코어 코드에 포함하지 않고 FDAI가
액션 실행에 필요한 권한을 확인하는 방법을 정의합니다. 의미 기능, 범위가 지정된 고객 정책,
프로바이더 대응, effective-access 근거, 기존 위험 및 사람 승인 결정을 분리합니다.

> **권한 경계:** 온톨로지는 필요한 기능과 정책 관계를 설명합니다. 접근 권한을 부여하지
> 않습니다. 범위 정책이 기능을 허용하고, 선택된 워크로드 신원의 유효 접근이 확인되며,
> 기존 risk 게이트가 허용한 경우에만 액션이 진행됩니다.
>
> **고객 경계:** 업스트림은 metamodel과 결정론적 해석기를 소유합니다. 다운스트림 배포판은
> 지원되는 카탈로그 및 프로바이더 경계를 통해 정책과 프로바이더 대응을 추가합니다. 배포 신원,
> 범위, 관측은 업스트림 출처 컨트롤 외부에 둡니다.

> **구현 상태(2026-07-31):** Strict 요구사항 및 배정 로더, resolver-backed 평가기,
> hierarchical 범위 해석기, effective-access 탐색 assembly, exact-plan 권한 부여 검증,
> 조립 연결기, role-filtered pending-grant 브라우저 변환 결과 및 revision-bound 브라우저 검토가
> 구현되어 있습니다. 배포 환경은 맥락, 신원, 권한 대응, 탐색, 선택적 권한 부여 어댑터를 바인딩하여 게이트를
> 활성화합니다. 개발 operations 게이트웨이는 `ops.scale-out`을 FinOps 실행기 ID에 매핑하고,
> 인스턴스 한 개의 용량 증가를 허용하기 전에 구성된 정확한 Uniform VM Scale Set 하나를 다시
> 확인합니다. 변경은 새 공급자 ETag를 `If-Match` 전제 조건으로 사용하고, Core는 장기 실행 작업
> polling에 하나의 누적 deadline을 적용합니다. 이 전달 매핑은 기능, 정책 배정, 유효 접근, 위험
> 또는 승인 결정을 대체하지 않습니다.

## 설계 개요

실행 권한 부여는 독립적으로 versioning되는 네 계층에서 확인됩니다. 모든 결정은 결정론적
재생을 위해 네 계층의 입력을 고정합니다.

```mermaid
flowchart LR
    AT[ActionType] -->|requires| AR[AuthorizationRequirement]
    AR -->|demands| AC[AuthorizationCapability]
    AR -->|targets| RT[ResourceType]
    PA[AuthorizationPolicyAssignment] -->|governs| AC
    PA -->|permits| EP[ExecutionProfile]
    PM[ProviderPermissionSet] -->|implements| AC
    EP --> IR[Deployment identity binding]
    PM --> OP[Provider operations]
    IR --> EO[Effective-access observation]
    OP --> EO
    EO --> AD[AuthorizationDecision]
    AD --> RG[Risk gate]
```

| 계층 | 질문 | 권한 |
|------|------|------|
| 의미 | 이 액션에는 어떤 기능이 필요합니까? | Versioned 온톨로지 카탈로그 |
| 거버넌스 | 어디에서 어떤 권한 부여 자세로 사용할 수 있습니까? | Scoped 정책 배정 |
| 프로바이더 | 어떤 실제 연산이 기능을 구현합니까? | 주입된 프로바이더 대응 |
| 근거 | 선택된 신원이 현재 연산을 수행할 수 있습니까? | Effective-access 탐색 |

## Metamodel

권한 부여 개념의 조건, 버전, 수명 주기는 결정에 영향을 주므로 일급 객체로 모델링합니다.
링크 속성만으로 decision-critical 상태를 표현하지 않습니다.

| ObjectType | 목적 |
|------------|------|
| `AuthorizationCapability` | `compute.restart`와 같은 안정적인 프로바이더 중립적인 기능입니다. |
| `AuthorizationRequirement` | `ActionType`에 대한 조건부 기능 요구사항입니다. |
| `ExecutionProfile` | 프로바이더 신원 식별자가 아닌 논리 실행기 프로파일입니다. |
| `AuthorizationPolicyAssignment` | 기능, 프로파일, 범위에 바인딩된 고객 정책입니다. |
| `ProviderPermissionSet` | 기능을 프로바이더 연산과 토큰 대상으로 매핑합니다. |
| `AuthorizationObservation` | 시간 제한이 있는 effective-access 근거입니다. |
| `AccessGrantRequest` | 범위가 제한된 권한 변경 요청입니다. |
| `AccessGrant` | 승인 및 적용 근거와 연결된 만료 가능 권한 부여입니다. |
| `AuthorizationDecision` | Risk 분류 및 전달 전에 생성되는 재생 가능한 결과입니다. |

관계 kernel은 다음과 같습니다.

| LinkType | 엔드포인트 | 의미 |
|----------|----------|------|
| `requires_authorization` | ActionType -> AuthorizationRequirement | 액션 의미에 이 관계가 필요합니다. |
| `demands_capability` | AuthorizationRequirement -> AuthorizationCapability | 요구사항을 안정적인 기능으로 확인합니다. |
| `authorization_targets` | AuthorizationRequirement -> ResourceType | 요구사항이 적용되는 리소스 타입입니다. |
| `governs_capability` | AuthorizationPolicyAssignment -> AuthorizationCapability | 배정이 기능을 제한합니다. |
| `permits_profile` | AuthorizationPolicyAssignment -> ExecutionProfile | 배정에서 적격한 프로파일입니다. |
| `implements_capability` | ProviderPermissionSet -> AuthorizationCapability | 기능을 구현하는 프로바이더 연산입니다. |
| `satisfies_requirement` | AccessGrant -> AuthorizationRequirement | 요구사항을 충족하도록 적용한 권한 부여입니다. |
| `attests_grant` | AuthorizationObservation -> AccessGrant | 적용된 권한 부여의 effective 탐색 근거입니다. |

기능 id는 프로바이더 중립적인 dotted 이름을 사용합니다. 프로바이더 연산 문자열, 테넌트
식별자, 리소스 id, 워크로드 신원 id는 업스트림 기능 선언에 포함하지 않습니다.

## 요구사항 확인

`AuthorizationRequirement`는 고정된 요구사항과 기능 참조, 액션 및 resource-type
선택자, 범위가 제한된 범위 표현식, 결정론적 조건, 대상 quantifier, 출처 이력,
의미 버전을 선언합니다.

범위 표현식은 닫힌 프로바이더 중립적인 grammar를 사용합니다.

| 표현식 | 결과 |
|------------|------|
| `target` | 정확한 액션 대상입니다. |
| `ancestor(resource_group)` | Resource-group-equivalent ancestor입니다. |
| `ancestor(account)` | 계정 또는 구독 ancestor입니다. |
| `related(link, depth)` | 하나의 선언된 온톨로지 링크를 범위가 제한된 탐색합니다. |
| `affected_set` | Risk 게이트에서 이미 계산한 affected 리소스 집합입니다. |

알 수 없는 링크, 잘린 탐색, stale 인벤토리, 확인되지 않은 대상 또는 선언된 최대 범위보다
넓은 결과는 `UNKNOWN`을 생성합니다. 자동으로 ancestor까지 넓히지 않습니다.

요구사항은 다른 ActionType에서 상속하지 않습니다. 여러 액션을 하나의 versioned 요구사항 또는
기능과 연결하여 공통 의미를 표현합니다. 이 방식은 circular inheritance를 방지하고 액션
evolution을 독립적으로 유지합니다.

요구사항은 배포 또는 다운스트림 분포의 catalog-as-code 항목으로 관리합니다. Strict
로더는 시작 전에 알 수 없음 필드, 중복 id, 지원되지 않는 범위 표현식 및 알 수 없는 액션
타입, 리소스 타입, 기능 또는 실행 프로파일 참조를 차단합니다.

```yaml
kind: authorization-requirement
id: object.write.target
version: "1.0.0"
capability_id: object.write
action_type_ids: [object.update]
resource_types: [object-storage]
scope_expressions: [target]
execution_profile: change-executor
provenance:
  created_at: "2026-07-31T00:00:00Z"
  created_by: example-team
```

프로바이더 연산, 대응 다이제스트, 배포 범위 id 및 신원 참조는 런타임 근거입니다.
이 값은 의미 요구사항 항목에 포함하지 않습니다.

## 범위가 지정된 정책 배정

권한 확인 정의는 배정이 기능, 실행 프로파일, 범위에 바인딩할 때까지 inert
상태입니다. 범위 grammar는 기존 `scope://` hierarchy와 선택자를 재사용합니다.

```yaml
kind: authorization-assignment
id: authz.object-write.prod
version: "1.0.0"
capabilities: [object.write]
execution_profiles: [change-executor]
scope:
  include: [scope://example/account/prod]
  selectors:
    resource_types: [object-storage]
posture: request_jit
constraints:
  allowed_grant_modes: [action_bound, time_bound]
  max_scope: resource
  max_duration_seconds: 1800
  quorum: 2
  approver_roles: [owner]
  require_effective_probe: true
  exemptible: false
enforcement: do-not-enforce
```

| 자세 | 의미 |
|---------|------|
| `prohibit` | 선택된 프로파일과 범위에서 기능이 허용되지 않습니다. |
| `delegate_manual` | 사람 또는 외부 시스템이 연산을 수행합니다. |
| `preprovisioned_only` | 기존 effective 접근이 필요하며 권한 부여를 요청할 수 없습니다. |
| `request_jit` | 접근이 없을 때 범위가 제한된 권한 부여 요청을 생성할 수 있습니다. |
| `standing` | 배정 제약 내에서 검토된 standing 권한 부여가 허용됩니다. |

여기의 `standing`은 provider-access 자세이며 헌법의 A3-E standing human 권한 확인이
아닙니다. `AccessGrant`는 액션 HIL 또는 standing Approval을 충족하지 않고 A3-E Approval은
프로바이더 권한을 만들지 않습니다. 둘 다 적용되면 두 독립 게이트가 모두 통과해야 합니다.

새 배정은 `enforcement: do-not-enforce`로 시작합니다. Shadow evaluation은 적용이 생성할
결정을 기록합니다. `enforce` 승격은 기존 검토된 카탈로그 전이를 따르며 환경 또는
포크 표시로 선택할 수 없습니다.

권위 있는 intersection에는 `enforce` 배정만 참여합니다. 일치하는 `do-not-enforce`
배정은 별도 shadow 비교에 사용할 수 있지만 실제 운영 결정을 prohibit, authorize, narrow 또는
widen할 수 없습니다.

## 정책 합성

일치하는 모든 배정이 제약을 제공합니다. FDAI는 더 구체적인 allow가 넓은 restriction을
대체하도록 하지 않고 교집합을 계산합니다.

- `prohibit`는 다른 모든 자세보다 우선합니다.
- 허용되는 권한 부여 모드는 교집합으로 계산합니다.
- 최대 범위는 가장 좁은 선언을 사용합니다.
- 최대 소요 시간은 가장 작은 양의 소요 시간을 사용합니다.
- 정족수는 가장 큰 선언을 사용합니다.
- 필수 승인자 역할과 근거 검사는 합집합으로 계산합니다.
- `exemptible: false`는 `true`보다 우선합니다.
- 빈 교집합 또는 동일한 specificity의 매개변수 불일치는 `POLICY_CONFLICT`를 생성합니다.
- 일치하는 enforced 배정이 없으면 암묵적 allow가 아닌 `UNCONFIGURED`를 생성합니다.

범위 specificity는 같은 specificity의 모든 배정이 동의할 때만 매개변수 출처를 선택합니다.
자세를 높이거나 제약을 제거할 수 없습니다. Relaxation은 resource-group-equivalent 이하 범위의
별도 time-bounded 독립적인 승인 exemption을 사용합니다.

## 신원 및 프로바이더 대응

`ExecutionProfile`은 `change-executor` 또는 `recovery-executor`와 같은 논리 이름입니다. 주입된
`ExecutionIdentityResolver`가 프로파일과 대상 맥락을 배포 신원 참조로 매핑합니다.
Core는 프로바이더 자격 증명을 받거나 리소스 이름을 계산하지 않습니다.

주입된 `ProviderPermissionMapper`는 기능을 atomic 프로바이더 연산, 토큰 대상,
권한 확인 평면, 탐색 strategy 및 대응 버전으로 확인합니다. Azure 대응은 Resource
Manager 액션, RBAC `DataActions`, service-local RBAC 또는 Kubernetes 동사를 포함할 수 있습니다.
Azure 어댑터가 해당 값을 소유합니다.

## 런타임 assembly

`ResolverBackedExecutionAuthorizationEvaluator`는 control-loop 요청을 pure 해석기에 연결하는
프로바이더 중립적인 브리지입니다. 고정된 요구사항 id 순서로 다음 단계를 수행합니다.

1. 고정된 `ExecutionAuthorizationContext`와 neutral `ResourceContext`를 확인합니다.
2. 적용 가능한 카탈로그 요구사항을 선택하고 범위가 제한된 범위 표현식을 각각 확인합니다.
3. 주입된 어댑터를 통해 실행 신원과 프로바이더 권한 대응을 확인합니다.
4. Scoped 정책을 먼저 적용합니다. 최종 정책 결정은 effective-access 탐색을 건너뜁니다.
5. 필요한 모든 범위를 탐색하고 결과를 expiring 관측으로 변환한 다음 pure 해석기를
  호출합니다.
6. 모든 요구사항 결정을 보수적으로 축소합니다. 모든 결과가 `AUTHORIZED`인 경우에만 risk
  게이트로 진행합니다.
   Authorized 요구사항은 정확히 하나의 `executor_identity_ref`로 수렴해야 하며 신원이
  없거나 여러 개면 risk evaluation 전에 실패 시 차단합니다. 이 참조는 타입이 지정된 액션과 모든
  실행기 감사로 복사됩니다. DirectApiRequest 메타데이터는 코어가 프로바이더 클라이언트 id를 알지
  않고도 한계 워크로드 신원을 선택하는 데 사용하며, PR-native 메타데이터는 귀속만
  보존하고 별도로 승인된 Git 발행기 신원을 대체하지 않습니다.
7. `GRANT_REQUIRED`인 경우 모든 누락된 요구사항 및 범위를 combined 결정 다이제스트, allowed
  권한 부여 모드, 최대 소요 시간, 정족수 및 approver-role 하한과 비교하여 검증한 후 각 쌍별로
  정본 순서의 제안 하나를 제출합니다.

`bind_execution_authorization`은 두 카탈로그를 부하 및 교차 검증하고 평가기를 조립한 다음
`execution_authorization_required=True`를 설정합니다. 빈 요구사항 카탈로그와 절반만 바인딩된 권한 부여
플래너/싱크 쌍은 조립 중에 실패합니다. 런타임 근거가 없거나 확인에 실패하면 held 상태를
반환하며 전달로 넘어가지 않습니다.

## 결정 알고리즘

해석기는 결정론적하며 I/O를 수행하지 않습니다. 호출자는 해석기 호출 전에 그래프, 정책,
신원, 대응, 탐색 근거를 수집합니다.

1. 액션, 온톨로지, 정책 번들, 프로바이더 대응 및 인벤토리 개정 번호를 고정합니다.
2. 적용 가능한 모든 요구사항을 고정된 id 순서로 확인합니다.
3. 제공된 그래프 스냅샷에서 대상 범위를 계산하고 제한합니다.
4. 일치하는 배정을 선택하고 제약 교집합을 계산합니다.
5. 정확히 하나의 실행 프로파일과 프로바이더 권한 집합을 확인합니다.
6. 신원, 연산, 범위, 개정 번호 및 만료에 대해 관측을 검증합니다.
7. 하나의 권한 확인 상태와 전체 contribution 추적을 생성합니다.
8. 가장 낮은 권한을 선택하여 결과와 risk 게이트를 결합합니다.

| 상태 | Control-loop 동작 |
|--------|------------------|
| `AUTHORIZED` | 기존 risk 게이트로 계속 진행합니다. |
| `GRANT_REQUIRED` | 액션을 보류하고 모든 누락된 요구사항 및 범위의 범위가 제한된 권한 부여 요청을 생성합니다. |
| `DELEGATED` | 수동 인계를 생성하며 Thor는 원래 액션을 전달하지 않습니다. |
| `PROHIBITED` | 차단하고 security-relevant 결정을 기록합니다. |
| `UNKNOWN` | 근거가 없거나 stale 또는 잘린이므로 검토를 위해 보류합니다. |
| `POLICY_CONFLICT` | 실행을 차단하고 정책 수정을 요청합니다. |
| `UNCONFIGURED` | Enforced 배정이 기능을 포함하지 않으므로 실행을 차단합니다. |

액션에 대한 사람 승인은 권한 확인 상태를 변경하지 않습니다. `GRANT_REQUIRED`는 별도 거버넌스
수명 주기를 시작하며 원래 액션은 계속 보류됩니다.

## 권한 부여 수명 주기

각 `AccessGrantRequest`는 요구사항 하나와 정확한 범위뿐 아니라 논리 실행 프로파일,
프로바이더 대응 버전, 권한 부여 모드, 만료, 원래 액션 id, combined 권한 확인 결정 다이제스트 및
멱등성 키에 바인딩됩니다. 여러 누락된 쌍은 서로 다른 요청 id를 생성합니다. 일부 제안
제출이 실패하면 제안별로 감사하고 원래 액션을 계속 보류합니다.

```mermaid
sequenceDiagram
    participant F as Forseti
    participant V as Var
    participant D as Protected deployer
    participant H as Heimdall
    participant T as Thor
    participant S as Saga
    F->>S: AuthorizationDecision(GRANT_REQUIRED)
    F->>V: AccessGrantRequest
    V->>S: independently approved exact request
    V->>D: exact-plan governance change
    D->>S: apply receipt and expiry
    H->>S: fresh-token effective-access observation
    H->>F: re-evaluate original action from the beginning
    F->>T: authorized verdict only after all gates pass
```

실행기 신원은 자체 역할을 부여할 수 없습니다. Protected deployer가 승인된 exact 계획을 적용합니다.
범위, 연산 집합, 소요 시간, 신원 프로파일 또는 계획 다이제스트가 변경되면 승인은 무효가 됩니다. 만료와
철회는 선택적 정리가 아니라 완료 조건입니다. 각 권한 부여는 `status`, `valid_from`,
`expires_at`, 선택적 `revoked_at` 및 변경할 수 없는 철회 증적을 기록합니다. Pre-dispatch
evaluation은 `status=active`, validity 간격 및 fresh effective-access 관측을 요구합니다.
철회는 pending 액션을 즉시 차단합니다.

Operator API는 App 역할과 요청의 승인자 역할이 교차하는 인증된 브라우저 principal에게 민감정보가 제거된
pending 변환 결과를 스트림할 수 있습니다. 변환 결과에는 요청, 상관관계, 기능, 범위,
모드, 시각, 정족수, 상태 및 개정 번호가 포함됩니다. 요청자, 실행기 신원, 프로바이더
대응, 결정 및 apply-plan 다이제스트는 제외됩니다. 적격 principal은 필수 사유를 입력하고 정확한
변환 결과 개정 번호에 대한 승인 또는 거부를 기록할 수 있습니다. 응답은 권한이 적용되지 않았고
새로운 탐색이 여전히 필요하다고 알립니다. 브라우저는 권한 부여를 적용, verify 또는 철회할 수 없습니다.

## 런타임 실패 분류

Pre-dispatch 근거는 defense in 깊이이며 프로바이더 호출 성공을 보장하지 않습니다. 어댑터는 코어에서
문자열을 파싱하지 않고 실패를 분류합니다.

- `authentication_failed`: 토큰 또는 신원이 인증되지 않았습니다.
- `permission_denied`: 인증된 신원에 effective 접근이 없습니다.
- `policy_denied`: 명시적 프로바이더 정책 또는 거부 배정이 호출을 차단했습니다.
- `network_denied`: 정책으로 권한 확인 엔드포인트 또는 데이터 평면에 접근할 수 없습니다.
- `provider_failed`: 다른 프로바이더 실패가 발생했습니다.

모든 등급은 실패 시 차단하며 감사됩니다. `permission_denied`는 일치하는 cached 근거를 무효화하고,
자동 권한 부여 요청을 생성하지 않으며, 권한 확인 해석으로 다시 진입합니다. 범용 transient
실패로 재시도하지 않습니다.

## Caching 및 재생

캐시 키에는 principal 참조, 기능, 대응 버전, 정확한 범위, 정책 번들 다이제스트,
인벤토리 세대가 포함됩니다. 항목은 관측, 배정 또는 권한 부여 만료 중 가장 이른 시점에
만료됩니다. 권한 확인 변경, 카탈로그 reload, 대응 또는 identity-binding 변경, 인벤토리 변경,
명시적 denial 및 준비 상태 성능 저하가 일치하는 항목을 무효화합니다.

Saga는 요구사항 id, 일치 및 losing 배정 id, intersection 결과, 신원 프로파일, 대응 다이제스트,
관측 다이제스트, 그래프 세대, algorithm 버전 및 최종 상태를 기록합니다. 재생은 해당 입력을
정확히 사용하며 현재 프로바이더 상태로 대체하지 않습니다.

## 확장 및 배포 경계

| 소유자 | 산출물 |
|--------|----------|
| 업스트림 | Metamodel, 해석기, 검증, base 기능, 감사 형태, 프로바이더 프로토콜입니다. |
| 다운스트림 분포 | 추가 기능, 요구사항, 정책 템플릿, 대응, 어댑터입니다. |
| 배포 구성 | Signed 정책 번들 참조, 신원 연결, 실제 범위 id입니다. |
| 런타임 저장소 | 관측, 결정, 요청, 권한 부여, 만료 및 철회 증적입니다. |

포크 표시는 권한 확인 행동을 선택하지 않습니다. 하나의 다운스트림 분포는 서로 다른
signed 정책 번들을 가진 여러 배포를 지원할 수 있습니다. 포크 addition은 제약을 추가할
수 있지만 업스트림 기능 id를 재정의하거나 업스트림 최대를 높일 수 없습니다.

## 검증 매트릭스

| 관심사 | 필수 증명 |
|---------|------------|
| 고객별 차이 | 하나의 액션이 세 가지 synthetic 정책 번들에서 다르게 확인됩니다. |
| 거부 우선 | 일치하는 `prohibit` 배정이 하나라도 있으면 실행을 차단합니다. |
| 교집합 | 범위, 소요 시간, 모드, 정족수, 역할 및 근거를 보수적으로 합성합니다. |
| 알 수 없음 안전성 | 누락된, stale, conflicting 또는 잘린 근거가 권한을 부여하지 않습니다. |
| 신원 분리 | Approver, 실행기 및 grant-applying deployer가 서로 다릅니다. |
| 재생 | 동일하게 고정된 입력이 동일한 결정과 다이제스트를 생성합니다. |
| 만료 | 만료된 관측과 권한 부여가 요구사항을 충족하지 않습니다. |
| 런타임 denial | 프로바이더 권한 denial은 transient로 재시도하지 않습니다. |
| 포크 안전성 | 배포 및 포크 표시는 정책을 선택하거나 권한을 높일 수 없습니다. |

## 관련 문서

| 알아볼 내용 | 문서 |
|-------------|------|
| 액션 의미 및 고객 오버레이 | [액션 온톨로지](action-ontology-ko.md) |
| 위험 및 전달 권한 | [실행 모델](execution-model-ko.md) |
| 워크로드 신원 및 최소 권한 | [Security and 신원](../architecture/security-and-identity-ko.md) |
| 공유 의미 그래프 경계 | [Operating 온톨로지](../architecture/operating-ontology-ko.md) |
| Scoped 배정 동작 | [Rule 거버넌스](../rules-and-detection/rule-governance-ko.md) |
