---
translation_of: operator-console-tool-catalog.md
translation_source_sha: 66eb6338f678dc3889d075605378c469437a227f
translation_revised: 2026-09-20
---

# 운영자 콘솔 도구 카탈로그

이 문서는 운영자 콘솔을 통해 제공하는 거버넌스 적용 도구 카탈로그를 담당합니다. 상위 문서는 채널 아키텍처, 실행 동작, 안전 불변식, 롤아웃 경계를 유지합니다.

## 설계 개요

이 문서는 [operator-console-ko.md](operator-console-ko.md)에 포함되어 있던 상세 계약을 그대로 보존하는 집중 소유 문서입니다.

## 3. 도구 카탈로그

도구는 **pipeline-stage 화면** 입니다. Core 도구는 안정된 이름, 범위가 제한된 `argument_hint`,
RBAC 하한, side-effect 등급과 문서화된 실패 표면을 가집니다. Web/provider-specific 도구는
자체 타입이 지정된 요청 계약을 추가할 수 있습니다. 새 도구는 가산이며 룰이나 정책을
재정의하지 않습니다.

`RuntimeToolDiscovery`는 installed 서술기 스키마에 검색 및 describe를 제공합니다. 스키마 메타데이터와 실제 installed 도구 이름의 교집합을 만들고 조정기와 동일한 RBAC 단계 구조를 적용하며 이름, verb, description, 인자 힌트, RBAC 하한, side-effect 등급만 반환합니다. 낮은 역할 principal은 높은 역할 도구를 discover할 수 없고 서술자에는 핸들러 또는 호출 기능이 없습니다. 명시적 요청이 principal 역할보다 높은 도구로 해석되더라도 결정론적 거절은 도구, 필수 역할, 현재 역할을 표시하고 도구를 호출하지 않았음을 확인합니다. 발견은 탐색을 개선할 뿐 새 권한을 부여하지 않습니다.

같은 변환 결과는 결정론적 채널 verb `search_tools`, `describe_tool`과 타입이 지정된 읽기 RPC
메서드 `tools.search`, `tools.describe`로 제공됩니다. 채널 호출은 resolved `Principal`을
사용하고 RPC 호출은 호출자가 제공한 역할 매개변수가 아니라 server-authorized 범위에서 역할을
도출합니다. 두 표면 모두 서술자만 반환하며 대상을 invoke할 수 없습니다. 에이전트 위임 전에 서버는 정본 primary 및 secondary intent와 정확히 소유한 ObjectType 대상만으로 담당자를 결정합니다. 요청 facet은 답변 및 근거 형식을 제한할 뿐 에이전트를 선택하거나 점수를 높일 수 없습니다. 이러한 담당자 입력으로 책임 에이전트를 결정할 수 없으면 출력 facet을 라우팅 권한으로 취급하지 않고 해당 턴을 기권하거나 보류 상태로 유지합니다.
### 3.1 Day-1 도구 집합 (읽기 전용 + explain)

| 도구 | 목적 | RBAC 하한 | Delegates to |
|------|---------|-----------|--------------|
| `describe_event(payload)` | 하나의 이벤트를 `EventIngest → TrustRouter → T0Engine`로 in-memory 실행 (PR 없음, 감사 쓰기 없음); 결과 라우팅 결정 + 후보 룰 id 반환. | 읽기 담당 | `EventIngest`, `TrustRouter`, `T0Engine` |
| `explain_verdict(event_id)` | 이미 처리된 이벤트의 감사 trail을 읽어; tier, 결정, citing 룰 id, 검증기 리포트, 모드 반환. | 읽기 담당 | `StateStore.query_audit()` |
| `explore_catalog(query)` | Shipped 룰 카탈로그 / action-type 카탈로그 / 온톨로지 어휘를 id, 키워드, 또는 resource_type으로 검색. | 읽기 담당 | 로딩된 카탈로그 (I/O 없음) |
| `query_audit(filters)` | 구조화된 감사 조회: 이벤트 id, 행위자, 결정, 모드, 시간 구간 별. Paginate. | 읽기 담당 | `StateStore.query_audit()` |
| `query_llm_usage(group_by, lookback_days, usage_scope)` | 1-90일의 범위가 제한된 구간에서 일, 모델, 워크로드 범위 또는 모드별로 측정된 LLM 토큰 사용량을 읽습니다. 독립적인 Operator 서비스는 SELECT-only 런타임 역할로 `llm_invocation`에서 동일한 token-only 변환 결과를 제공하며 기록 및 대화 원장은 500개로 제한하지만 집계 개수는 정확하게 유지합니다. Operator-chat 기록으로 좁힐 수 있고, 측정된 가격 근거 없이 금액을 추정하지 않으며, 결정론적 산문, 표 또는 chart 출력을 반환합니다. `LlmCostPanel`은 `conversation_tool`로 이 도구를 선언하며 chat-enabled 조립에 선언된 기능이 없으면 시작이 실패합니다. | 읽기 담당 | `MeteringReader` |
| `query_inventory(resource_type, filter)` | 서버가 소유한 Azure 인벤토리 개수, 목록, 타입, 위치, resource-group, 이름, 상태, 관계 조회입니다. 스키마로 검증한 `inventory-query-language.yaml` 카탈로그가 자연어 용어, 상태와 연산 의미, 근거 권한, 그룹화, 변환 결과, 범위 기본값, 최신성 요구사항을 소유하고, Python은 질문별 별칭 없이 범용 토큰 matching과 타입이 지정된 조회 assembly만 수행합니다. Resource 타입은 별도의 정본 resource-type 카탈로그에서 가져옵니다. 타입이 지정된 조회가 근거 수집 전에 범위, 그룹화, 변환 결과, 워크로드 의도, state-history 의도, 최신성을 소유하므로 렌더러는 프롬프트를 다시 해석하지 않습니다. 한정되지 않은 화면 간 인벤토리 읽기는 서버가 소유한 구독 루트를 사용하고, current-view 표현을 명시하면 활성 아키텍처 화면을 유지합니다. Current-state 질문은 프로바이더 refresh barrier를 기다리고 stale 근거로 확정 답변을 하는 대신 사용 불가를 반환합니다. Degraded 또는 사용 불가 리소스 질문은 카탈로그 권한에 따라 `query_subscription_health`로 경로되며, 구체적인 resource-family 필터가 유지되어 다른 타입의 발견 사항을 제외합니다. 결과는 제한된 허용 목록 필드, 정확한 범위, 스냅샷 출처/최신성 및 모든 조건식에 일치하는 기록만 노출합니다. 명시적 semantic 상태 그룹은 서로 분리되고 근거 있는 zero-result 그룹도 표시할 수 있습니다. 상태 필터 답변은 정규화된 현재 operational 상태가 배포 또는 활동 로그 실패의 부재를 증명하지 않는다는 한계도 표시합니다. 스트림은 민감정보 제거된 서버 범위와 범위가 제한된 결과 메타데이터가 포함된 verifier-accepted 정본 `query_inventory` 연산을 노출합니다. 프로바이더 실패는 사용 불가로 표시합니다. 서버가 소유한 워크로드 프로바이더가 인벤토리와 일치하는 클러스터에 명시적으로 연결되지 않으면 AKS 결과는 클러스터 리소스만 포함합니다. 유효한 연결은 범위가 제한된 배포와 Pod 준비 상태를 추가하고, 일치하는 다른 클러스터는 명시적인 커버리지 공백으로 유지합니다. 현재 스냅샷은 워크로드가 해당 상태로 전이된 시각을 증명하지 않으며, Kubernetes 이벤트 또는 다른 이력 권한이 연결될 때까지 답변은 그 transition 시간을 미확정으로 유지합니다. | 읽기 담당 | `InventoryGraphProvider`, `KubernetesWorkloadProvider` |
| `query_subscription_scope()` | 스키마로 검증한 의미 판정이 `subscription_scope_identity`를 선택한 뒤 서버에 구성된 구독을 Azure Resource Manager에서 입력 없이 결정론적으로 읽습니다. 검증된 답변은 표시 이름, 상태, 관측 시각, 근거 다이제스트 및 마스킹한 구독 ID를 포함하며 브라우저나 모델 출력은 범위를 제공할 수 없습니다. | 읽기 담당 | `SubscriptionScopeProvider` |
| `query_subscription_health()` | 명시적인 구독 점검, 일반적인 service-outage 질문 및 카탈로그가 선택한 degraded 또는 사용 불가 리소스 collection에 대해 server-configured Azure 읽기 담당 범위를 점검합니다. 프로바이더는 resource-group 허용 목록을 기본으로 사용하며, 조립이 소유하는 명시적인 구독 모드는 interactive 로컬 상태 범위를 구독 인벤토리와 맞춥니다. Resource Graph 인벤토리와 Resource Health를 조회하고, ARG가 비어 있으면 구성된 범위의 현재 Resource Health 상태로 대체 경로한 다음 범위가 제한된 representative 메트릭을 확인합니다. 근거 있는 빈 그룹을 포함한 요청 상태 그룹을 보존합니다. Resource Health display 이름이 없으면 범위가 검증된 대상에서 이름, 프로바이더 타입 및 리소스 그룹을 정규화하고 raw 대상 ID는 노출하지 않습니다. Caller-supplied 범위 또는 모드를 허용하지 않고 발견 사항, cause 분류, 커버리지 공백, 최신성 및 잘림을 반환합니다. | 읽기 담당 | `SubscriptionHealthProvider` |
| `query_detection_readiness()` | Muninn StateSnapshot에서 Heimdall의 최신 AKS 준비 상태 판정을 읽고 6축 커버리지 공백과 권한 상한을 반환합니다. Azure를 탐색하거나 준비 상태를 다시 계산하지 않습니다. | 읽기 담당 | `DetectionReadinessReader` |
| `query_t2_recovery()` | 서버 StateStore에서 정제된 proposer 시도 증적을 읽습니다. 프로바이더 오류 텍스트를 노출하지 않고 retained 시도 개수, 복구 상태, 경로 역할, 실패 등급, 관측 시간 및 명시적인 legacy-detail 공백을 반환합니다. | 읽기 담당 | `T2RecoveryStateReader` |
| `query_configuration_baseline()` | 서버가 구성한 동결된 구성 기준선, 현재 범위의 관측값, 무결성이 고정된 정확한 DOCX 인용을 읽습니다. 호출자는 범위, 버전, 다이제스트, 문서 또는 변경 연산을 선택할 수 없습니다. 구조화된 topology가 없으면 알 수 없음으로 유지합니다. | 읽기 담당 | `ConfigurationDriftService` + `KnowledgeSource` |
| `capture_browser_evidence(policy_id, policy_version, source_url, stable_selectors)` | 정확한 서버가 소유한 정책 아래에서 자격 증명이 없는 범위가 제한된 수집을 제출합니다. 변경할 수 없는 산출물 증적을 반환하며 페이지 또는 interaction API를 반환하지 않습니다. | 읽기 담당 | `BrowserEvidenceCaptureService` |
| `query_operator_memory(scope_kind, scope_ref)` | 범위가 제한된 (scope_kind, scope_ref)에 대해 활성 상태(대체되지 않고 만료되지 않은)인 통제된 운영자 기억 항목을 반환합니다. 읽기 전용입니다. | 읽기 담당 | `OperatorMemoryStore` |

증적에서 도출한 답변 권한과 타입이 지정된 보류는 [Operator Console 점진적 대화](operator-console-progressive-conversations-ko.md#증적에-결속된-답변-권한)에서 정의합니다.
일치하는 인벤토리 결과 집합은 40개 기록 제한을 적용하기 전에 정렬합니다. 목록은 기본적으로
리소스 이름순이며, 상태, 타입 또는 위치 그룹화를 명시하면 해당 그룹화 필드 다음에
리소스 이름순으로 정렬합니다. 렌더링 행과 영속 ordinal 후속 조치는 같은 순서를 사용합니다.
향후 VM 종료 질문은 catalog-owned `scheduled_shutdown` 조회 종류와
`compute.vm-shutdown-schedule` 리소스 타입을 사용합니다. 조회는 timezone-aware 서버 기준 시각과
closed `today_evening` 구간을 고정합니다. 프로바이더 어댑터는 검증된 `ComputeVmShutdownTask`
기록만 변환 결과하고 대상 ARM id는 노출하지 않은 채 대상 VM 이름과 리소스 그룹, 활성화된
상태, daily 로컬 시간, 프로바이더 timezone을 제공합니다. 결정론적 변환 결과는 예약 timezone에서
18:00부터 23:59 사이이며 아직 지나지 않은 활성화된 occurrence만 포함합니다. 비활성화된 예약은
결과가 아닙니다. 스냅샷이 잘린되거나 운영 커버리지에 예약 타입이 없거나 예약이
malformed이거나 timezone을 지원하지 않으면 어떤 VM도 종료되지 않는다고 단정하지 않고 사용 불가를
반환합니다.
구체적인 resource-type 조회에 완전한 lexical 상태 일치가 없으면 semantic 수집은 상태 또는
연산 후보만 제안할 수 있습니다. 모델 및 임베딩 후보는 해당 턴에서 프로바이더
조회를 실행하지 않습니다. 서버가 완전한 타입이 지정된 조회를 만들려면 exact/promoted 카탈로그 대응
또는 별도로 검증된 운영자 확인 증적이 필요합니다.
Semantic 계획 수립을 사용할 수 없거나, 결과가 모호하거나, 필요한 상태를 생략하면 서버는
결정론적 조회 골격이 포함된 타입이 지정된 interpretation 보류를 반환합니다. Type-only 골격을
실행하거나 해결되지 않은 modifier를 삭제하여 결과 범위를 넓히지 않습니다.
부정 상태 후보는 정본 카탈로그 상태에 대해 범위가 제한된 `not_in` 운영자를 사용합니다.
프로바이더 grounding은 같은 스냅샷에서 excluded 값을 해석하며, negation을 지원하지 않는
positive-state guess로 바꾸지 않습니다.
Exact 카탈로그 용어는 유일한 항목 gate가 아니라 T0 지연 시간 optimization으로 유지됩니다. 운영에
기존 T1 임베딩 연결이 있으면 같은 자격 증명 경로로 상태와 연산 description 및 예시를
검색합니다. Retrieved 개념은 `candidate_only`를 유지하고 인벤토리를 조회하지 않은 채 localized
명확화를 만듭니다. Embedder가 없거나 실패하면 해석기는 후보를 반환하지 않고
결정론적 보류가 권위 있는 상태를 유지합니다. 해석기는 카탈로그 vector를 빌드하거나 조회 embedder를 호출하기 전에 빈 프롬프트, 컨트롤 character 및 4,096자를 초과하는 텍스트를 거부합니다.
인벤토리 semantic 수집과 Rule-카탈로그 검색은 독립적으로 제어됩니다. Rule 검색을 비활성화해도
인벤토리 semantic 수집이 암묵적으로 비활성화되지 않습니다.
명확화는 dead end가 아닙니다. 이후 운영자 턴에서 exact promoted 카탈로그 표현식을
선택하면 결정론적하게 다시 compile하고 프로바이더 읽기를 수행할 수 있습니다. 이전 모델 또는
임베딩 인자는 조회 권한으로 재사용하지 않습니다.
Intent-graph 계획 수립은 완전한 결정론적 인벤토리 조회를 재정의할 수 없습니다.
Planner-supplied 상태 개념도 정본 카탈로그로 확인하며 잘못된 값은 차단되고 실행은
결정론적 조회를 사용합니다. 필요한 semantic 상태가 생략되면 보류 상태를 유지합니다.
필터가 없는 요약은 프로바이더가 관찰한 모든 리소스를 계속 보존하고 provider-native 타입별로 그룹화하며 resource-group 컨테이너와 topology-derived 기록을 리소스 합계에서 분리합니다.
Catalog-owned `scope_counts` 조회 종류는 조회를 리소스 그룹으로 좁히지 않고 하나의
fresh 스냅샷에서 provider-native 리소스와 resource-group 합계를 반환합니다. 타입 요약과
동일하게 컨테이너, derived-record, 잘림, 최신성 및 검증 공개를 유지합니다.
아키텍처는 범위가 제한된 화면 다이제스트에 선택된 리소스를 최대 하나만 게시합니다. Current-screen
service-summary 질문은 선택된 resource-group 이름을 선택자 힌트로만 사용할 수 있고, 서버
인벤토리가 정본 service-type 개수를 반환하기 전에 해당 그룹과 구성원을 다시 해석합니다.
선택이 없거나 malformed 또는 non-group이면 범위 권한을 만들지 않습니다.
Selected-group 상세 요청도 같은 경계를 사용합니다. Named 아키텍처 변환 결과는 raw
속성을 제거한 뒤 허용 목록에 있는 위치, resource-group 및 provider-type 필드만 유지합니다.
관찰된 operational 또는 power 상태가 우선하며 프로비저닝 상태는 마지막 display 대체 경로입니다.
결정론적 목록은 resource-group 컨테이너 자체와 프로바이더 타입이 없는 topology-derived
기록을 제외합니다.
인벤토리 기록은 displayed 상태의 출처 이력을 별도로 유지합니다. Catalog-owned
`state_coverage` 결과는 operational 및 power 근거를 직접 관찰로 취급하고,
provisioning-only 및 알 수 없음 근거는 operationally 사용 불가로 유지합니다. Selected-screen
이어가기는 범위가 제한된 그룹 선택자만 재사용하며 모든 기록을 서버 인벤토리에서 재확인합니다.
Catalog-owned `inventory_coverage` 결과는 확인한 프로바이더 타입과 skipped 및 실패한 타입을
분리해 보고합니다. 완전한 atomic 스냅샷은 skipped 0 및 실패한 0을 증명할 수 있지만,
잘린 스냅샷은 skipped 커버리지를 알 수 없음으로 유지합니다. Operational-state 한계는
별도 커버리지 등급이며 인벤토리 읽기 실패로 바꾸지 않습니다.
스키마로 검증한 의미 판정이 구독 또는 platform-health를 선택하면 결정론적 도구 플래닝은
공개 웹 계획보다 우선합니다. Resource Health cause 분류는 서술 전에
platform 영향과 customer-initiated 상태를 분리합니다. Broad platform-impact 읽기는 대표
메트릭을 끄고 활성 서비스 Health 이벤트와 impacted 리소스를 조회하며 장애를 planned
maintenance 및 참고용과 분리합니다. 누락된 가용성 cause는 범위가 제한된 Resource Health
annotation으로 보강합니다. 서비스 Health 또는 annotation 조회가 사용 불가 또는 잘린이면
부분 커버리지 공백으로 유지하며 platform 영향 0을 증명할 수 없습니다.
Catalog-owned resource-health 이력 의도도 같은 결정론적 precedence를 가집니다. Parse한
조회 구간을 최대 24시간으로 제한하고 가용성 상태와 annotation을 chronological 순서로 병합한
뒤 customer-initiated, status-only 및 platform-initiated 개수를 보고합니다. Historical 근거가
없을 때 현재 ARM 상태로 대체하지 않습니다.
완전한 이력 답변은 최신 검증된 이벤트 리소스를 next-turn 선택자 힌트로 반환할 수 있습니다.
귀속 및 이력 후속 조치는 서버 범위에서 해당 리소스를 다시 해석하고 fresh 활동 로그
또는 Resource Health 근거를 수집해야 하며, 힌트 자체는 근거 권한이 되지 않습니다.
카탈로그 matching은 `와`, `과`를 포함한 일반적인 격조사 또는 접속 조사가 붙어도 Korean 조회 용어를
보존하므로 compound 비교에서 요청한 semantic 등급이 누락되지 않습니다.

**Reader-하한 도구는 증명 가능하게 side-effect-free.** `describe_event`는
`EventIngest -> TrustRouter -> T0Engine`을 **메모리 내에서만** 실행: T1
임베딩 조회, T2 모델, 외부 어댑터, 어떤 변경 표면도
호출하지 않고, PR과 감사 항목을 쓰기 안 함. 그 `side_effect_class`는
`read` 이며, shadow-mode 테스트가 실행기 / PR 어댑터 / 상태 저장소를 절대
건드리지 않음을 assert. 이것이 읽기 담당 하한에서 안전한 이유입니다. 브라우저 수집과 Reader 전용 v2 작업 공간은 [브라우저 근거 수집](browser-evidence-ko.md) 계약을 따릅니다. 허용된 스칼라 보관 메타데이터, 식별정보가 없는 보류 개수, 정확한 필터, 커서 및 Audit 또는 Trace 링크는 읽기 전용이며 수집을 요청하거나 수집 자료를 공개하거나 승격, 승인 또는 실행 권한을 부여할 수 없습니다. Bragi는 브라우저 handle을 받지 않습니다.
### 3.2 Week-1 추가 (쓰기 / approve / 런북)

| 도구 | 목적 | RBAC 하한 | 참고 |
|------|---------|-----------|-------|
| `simulate_change(scenario)` | 종단 간 `ControlLoop.process()`를 **shadow** 모드로; publish 없이 실행기 결과 + 생성된 PR 의도 반환. | 기여자 | Shadow-only; 여전히 감사 항목을 남김 → 오퍼레이터가 `query_audit`로 찾을 수 있음. |
| `approve_hil(approval_id, decision, justification)` | 큐잉된 HIL 항목 하나 해결. 검증기 + `no_self_approval` invariant 재확인. | Approver | Approver 그룹; [security-and-identity.md](../architecture/security-and-identity-ko.md)의 PR gate 적용과 동일 principal. |
| `list_hil()` | 호출자의 역할에 visible 한 현재 큐잉된 HIL 항목 반환. | Approver | Reader-visible은 non-approver 에게 의도를 leak; Approver-scoped 유지. |
| `run_runbook(name, params, dry_run)` | `docs/runbooks/` 아래 하나의 런북 실행. `dry_run=true`는 기여자 요구; `dry_run=false`는 Owner 요구. | 기여자 / Owner | 구체 런북 어댑터 (예: `db_dr_drill_cli`)는 이미 shipping; 이 도구는 이름으로 경로. |
| `activate_break_glass(reason, expiry)` | TTL과 사유를 검증하고 Owner 페이지 및 감사 증적을 생성합니다. | 읽기 담당 | 현재 구현은 세션 principal/역할을 변경하지 않으며 실제 권한 상승은 제공하지 않습니다. |

쓰기 집합에 대한 두 명확화:

- **`simulate_change`가 감사 항목을 쓰기 하는 것은 "shadow는 절대
  mutate 안 함"을 위반하지 않음.** 감사 로그는 추가 전용; *시뮬레이션이
  실행되었다는 것*을 기록하는 것은 관리 리소스의 변경이 아니다.
  shadow-mode 속성 테스트는 실행기 / PR / state-store 쓰기가 없음을
  assert 하며 감사 덧붙이기는 명시적으로 허용.
- **`list_hil` (Approver) vs read-console HIL 화면 (읽기 담당)는 다른
  표면.** 읽기 전용 콘솔 SPA는 읽기 담당 에게 큐잉된 HIL 항목의 *존재와
  개수* (대시보드 tile)를 보여줌; `list_hil`은 *전체 항목 상세* (대상,
  proposed 액션, 요청자)를 반환하며 이는 민감한 의도를 드러낼 수
  있으므로 Approver-scoped 유지. 둘은 의도적으로 같은 가시성이 아님.
### 3.3 Month-1 추가 (관찰 깊이)

| 도구 | 목적 | RBAC 하한 | 의존 |
|------|---------|-----------|-------------|
| `query_log(query, window)` | 범위가 제한된 single-workspace 로그 Analytics KQL 조회. | 읽기 담당 | 신규 `AzureMonitorAdapter` |
| `query_metric(namespace, metric, window, aggregation)` | Azure Monitor metrics API. | 읽기 담당 | 신규 `AzureMonitorAdapter` |
| `query_deployments(window)` | Git + ARM deployment-history 결합. | 읽기 담당 | 신규 `DeploymentHistoryAdapter` |
| `correlate_incident(incident_id)` | 하나의 인시던트 id에 대해 ingest 이벤트 + 감사 + 인벤토리 + 로그 + 메트릭을 multi-signal correlate. | 읽기 담당 | 위 셋 + `event_ingest` |

`query_log`는 정확한 운영자 명령에서만 명시적이고 범위가 제한된 KQL을 받습니다. 모든 서술기 노출 도구 스키마, 읽기 계획 및 Pantheon 도구에서 제외되므로 모델이 원시 KQL을 작성하거나 선택할 수 없습니다. 자연어 진단 형태는 별도의 서버 소유 템플릿을 사용합니다. 실패 요청 요약은 `AppRequests`를 작업과 결과 코드별로 그룹화하지만, 이 그룹이 근본 원인을 증명한다고 주장하지 않습니다. 오류 시그니처 타임라인과 관련 로그 요청에는 정확한 시그니처 또는 선택된 맥락이 필요합니다. 맥락이 없으면 프로바이더나 서술기를 호출하지 않고 확인 질문을 반환합니다. 대표 오류 샘플은 고정 multi-table 템플릿을 사용하고 요청 구간을 24시간으로 제한하며 cell을 렌더링하기 전에 시크릿 배정, bearer 값, 리소스 식별자, GUID, 이메일 주소, URL, IP 주소를 제거합니다. 추가 고정 템플릿은 가장 느린 관측 분산 추적의 구간을 순위화하고, 의존성 지연 시간을 집계하며, 느린 데이터베이스 의존성 호출을 나열합니다. 이 결과만으로 근본 원인, 인과적 기여 또는 데이터베이스 호출이 CPU 상승을 설명한다는 결론을 증명하지는 않습니다. 프롬프트 텍스트는 실행 가능한 KQL이 되지 않습니다. workspace 프로바이더가 구성되지 않으면 같은 도구가 타입이 지정된 사용 불가 결과를 반환하며 current-screen, 인시던트, web 또는 서술기 근거로 대체하지 않습니다.
제안, 승인, 실행, 결과 검증, 재시도 또는 멱등성에 대한 context-free 질문은 결정론적 action-context 보류를 사용합니다. 수명 주기 점유를 검증하기 전에 exact ActionType, 대상 리소스, 제안, 승인 또는 액션 증적을 제공해야 합니다. Current-screen, 저장소, 인시던트 및 서술기 근거는 통제된 기록을 대체하지 않으며, 이 보류는 변경이나 모델 호출을 수행하지 않습니다.
정확한 configuration-baseline 파일 이름은 action-context 분류보다 먼저 읽기 전용 기준선 도구를 선택합니다. "완화 도구를 호출하지 마세요"와 같은 부정 지시는 문서 읽기를 action-lifecycle 질문으로 바꾸지 않습니다. 결정론적 답변은 각 섹션에서 고정된 DOCX를 인용하고 사용할 수 없는 관계를 산문에서 추론하지 않고 알 수 없음으로 보고합니다. 일반적인 기준선 표현은 별도 키워드 라우터를 만들지 않고 검증된 semantic 계획 수립 경로에 유지됩니다.
Month-1 추가는 콘솔을 multi-signal 인시덴트 대응 경험에 가깝게
만들어 주지만, 여전히 **이미 correlate 된** 결과를 표면;
correlator는 계층 1에 살고, 서술기 안에 살지 않는다.
### 3.4 도구 발견 계약

각 도구는 다음을 선언:

- `name` - CLI-friendly snake_case verb (`describe-*` / `explore-*`
  접두사 taxonomy 없음; verb 자체가 카테고리).
- `description` - 한 문장, 영어, 마케팅 언어 없음.
- `argument_hint` - 정본 verb 파서가 기대하는 범위가 제한된 인자 형태. 각 도구는 호출 전
  자신의 타입이 지정된/범위가 제한된 검증을 다시 적용하며 잘못된 인자는 부분 호출로 진행하지 않습니다.
- `rbac_floor` - 도구를 호출 MAY 하는 가장 낮은 역할.
- `side_effect_class` - `read` / `simulate` / `approve` / `execute` /
  `breakglass`. 감사 항목이 이 등급을 carry 하므로 downstream
  analytics가 저렴하게 slice.
- `failure_modes` - 도구의 docstring에 문서화된 타입화된 오류 표면.

`RuntimeToolDiscovery`와 `tools.search`/`tools.describe`는 핸들러나 호출 기능 없이
서술자만 반환합니다. Narrator는 principal 역할에 허용된 같은 서술자 목록만 봅니다.

### 3.5 공개 웹 근거

공개 웹 검색 라우팅, 수집, 대안 탐색, 안전 경계 및 회귀 커버리지는
[operator-console-web-evidence-ko.md](operator-console-web-evidence-ko.md)에 정의되어 있습니다.

## 관련 문서

| 알아볼 내용 | 문서 |
|-------------|------|
| 상위 설계 | [운영자 콘솔](operator-console-ko.md) |
| 제공 상태 및 남은 작업 | [구현 원장](../../roadmap-implementation/interfaces/operator-console-tool-catalog.md) |
