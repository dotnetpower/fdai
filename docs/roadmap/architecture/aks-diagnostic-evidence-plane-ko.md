---
title: AKS 진단 근거 플레인
translation_of: aks-diagnostic-evidence-plane.md
translation_source_sha: 138da97c722dc90fbd191965c8c1baeb9cb232e4
translation_revised: 2026-09-11
---
# AKS 진단 근거 플레인

이 문서는 정확한 Azure Kubernetes Service(AKS) 리소스를 식별하고 워크로드, 노드, 스토리지,
엔드포인트, 롤아웃 및 컨트롤 플레인 장애를 진단하는 범위가 제한된 읽기 플레인을 정의합니다.
상관관계, 진단 또는 표현을 인과관계나 실행 권한으로 바꾸지 않고 인증된 관측을 결합합니다.

> **권한 경계:** 이 플레인은 읽기 전용 근거를 관측하고 파생합니다. AKS 리소스를 승인, 실행,
> 다시 시작, 확장, 삭제, 퇴거, 롤백 또는 변경할 수 없습니다.
>
> **완전성 경계:** "완전한 진단"은 선언된 기능 하나, 정확한 대상, 출처 집합 및 시간 구간에
> 대해 완전하다는 뜻입니다. 클러스터 전체를 전지적으로 파악한다는 뜻이 아닙니다.
>
> **개인정보 경계:** Secret 값, bearer token, 원시 로그 본문, 환경 값, 명령 출력 및
> 프로바이더가 제어하는 자유 형식 텍스트는 온톨로지 인스턴스나 운영자 응답에 들어가지 않습니다.

## 설계 개요

구성된 각 클러스터에는 변경할 수 없는 ARM 신원 하나와 인증된 Kubernetes API 연결 하나가
있습니다. 인벤토리 및 감시 수집기는 UID와 리소스 버전 신원을 보존합니다. 메트릭, 로그 요약 및
Azure 관측은 정확한 대상을 검증한 뒤에만 결합됩니다. 결정론적 축약기는 명시적인 근거 공백과
실행 권한 없음 상태를 가진 진단 하나를 반환합니다.

## 진단 기능

| ID | 운영자 질문 | 필요한 근거 |
|----|-------------|-------------|
| D1 | 영향을 받은 정확한 클러스터 객체는 무엇인가요? | 클러스터 ARM ID, API 연결 다이제스트, 종류, 네임스페이스, 이름, UID, resourceVersion 및 관측 기준 시점 |
| D2 | Pod가 대기 중인 이유는 무엇인가요? | Pod 스케줄링 조건, 요청량, 노드 선택기, 허용 조건, 선호도 요약, PVC 상태, 할당량 및 후보 Node 용량 |
| D3 | 컨테이너가 대기하거나 다시 시작되는 이유는 무엇인가요? | 컨테이너 그룹, 대기 및 종료 사유, 재시작 변화량, 프로브 종류, Event 및 내용 없는 로그 요약 |
| D4 | Node 근거가 영향 가설을 지지하나요? | 준비, 압력 및 네트워크 조건, 할당 가능 용량, 정확한 providerID 연결 |
| D5 | Service가 준비된 backend를 구성하나요? | Service 선택기, EndpointSlice 대상 UID, ready, serving, terminating, 포트 수 및 Pod 준비 상태. 실제 트래픽 도달은 별도 텔레메트리가 필요합니다. |
| D6 | 롤아웃이 진행 중인가요? | 컨트롤러 세대, replica 상태, 워크로드 revision, Pod revision 및 교체 이력 |
| D7 | 스토리지가 워크로드를 차단하나요? | Pod PVC claim, PVC 단계 및 볼륨 연결, PV 단계, StorageClass 모드 및 관련 Event |
| D8 | 정책 또는 용량이 배치를 차단하나요? | PDB, HPA, ResourceQuota, LimitRange, NetworkPolicy 요약, 요청량 및 Node 용량 |
| D9 | 컨트롤 플레인 또는 Azure 기반이 저하됐나요? | AKS Resource Health, 컨트롤 플레인 진단 범주, API 도달 가능성, AgentPool, VMSS, Node, NIC, subnet, route, NSG, NAT 및 Public IP 근거 |
| D10 | 워크로드가 복구됐나요? | 구분되는 현재 및 과거 관측, 정확한 교체 UID, 준비 전환, 재시작 이력 및 소유자 상태 |
| D11 | 누락되거나 오래된 근거는 무엇인가요? | 출처별 상태, 범위 다이제스트, 기준 시점, 최신성 상한, 커서 범위, 잘림, 충돌 및 교정 |
| D12 | FDAI가 무엇을 할 수 있나요? | 항상 `execution_authority=false`; 작업 계획과 실행은 이 플레인 밖에 유지 |

## 클러스터 출처 연결

런타임은 개수가 제한된 클러스터 연결 모음을 허용합니다. 각 연결은 다음을 포함합니다.

- 표준 AKS ARM ID 하나
- 자격 증명이 없는 HTTPS API 엔드포인트 하나
- CA 경로 또는 CA PEM 중 정확히 하나
- `service-account` token 경로 하나 또는 workload-identity audience 하나
- 고객 식별자 대신 출처 상태에 사용하는 내용 다이제스트

클러스터 ARM ID와 API origin은 각각 고유해야 합니다. 중복, 일부 구성, 잘못된 형식 또는 자격
증명이 포함된 엔드포인트는 네트워크 I/O 전에 구성을 실패시킵니다. 기존 단일 클러스터 변수는 연결
하나로 변환되며 fleet 연결 레코드와 함께 사용할 수 없습니다.
배포는 각 managed cluster의 정확한 ARM ID 범위에서만 `Azure Kubernetes Service RBAC Reader`를
할당합니다. 구독, 리소스 그룹 및 managed cluster 하위 리소스 범위는 허용되지 않습니다.

수집 실패는 클러스터별로 격리합니다. 사용할 수 없는 클러스터 하나가 다른 클러스터에서 검증된
양성 근거를 지우지는 않지만, 필요한 모든 연결이 최신이고 완전하기 전까지 fleet 완전성은
거짓입니다. 출처 상태 키는 `(source, scope_digest)`이므로 한 클러스터가 다른 클러스터의 사용
불가 사유를 덮어쓸 수 없습니다.
각 관계 변환은 프로바이더 리소스와 클러스터 하나의 API 객체만 결합합니다. 앞선 fleet 연결에서
수락한 객체나 관계를 다시 변환하지 않습니다.
영속 저장소와 운영자 변환 결과는 `(source, scope_digest)`별로 개수가 제한된 fleet 상태를
보존합니다. Console은 불투명한 범위 다이제스트를 표시하며 여러 클러스터 상태를 처음 일치한 출처
이름 하나로 축약하지 않습니다.

## 정확한 리소스 신원

안정적인 Kubernetes Resource 신원은 다음 튜플입니다.

`(cluster_ref, uid)`.

버전이 지정된 각 관측은 다음 정보를 별도로 전달합니다.

`(api_version, kind, namespace, name, resource_version, observed_at)`.

UID가 객체 신원을 고정합니다. API 버전, 종류, 이름 및 네임스페이스는 검증된 관측 메타데이터와
조회 별칭이며 안정적인 신원이 아닙니다. `resourceVersion`은 한 API server 안에서 관측 순서를
정하며 클러스터 사이에서 비교하지 않습니다. 확인자는 다음 중 하나를 반환합니다.

- `resolved`: 정확한 선택 조건을 만족하는 현재 또는 과거 UID가 하나입니다.
- `not_found`: 완전한 근거가 요청 범위에 일치하는 객체가 없음을 입증합니다.
- `ambiguous`: 불충분한 선택 조건을 여러 UID 또는 종류가 만족합니다.
- `unavailable`: 출처, 접근, 보존 또는 커서 근거로 결과를 입증할 수 없습니다.

Pod 교체는 두 UID를 모두 보존합니다. 확인자는 이전 UID를 같은 이름의 현재 객체로 다시 쓰지
않습니다.
버전이 지정된 신원 계약보다 먼저 만든 스냅샷도 이행 중에는 목록에서 조회할 수 있습니다.
`api_version`, `kind`, `resource_version`이 모두 없으면 Operator는 전체 인스턴스 응답을 실패시키거나
누락된 값을 만들어 내지 않고 정확한 Kubernetes 신원과 진단을 보류합니다. 버전이 지정된 신원이
일부만 채워져 있으면 계속 잘못된 형식이며 사용할 수 없습니다.

## 근거 수집

### Kubernetes 객체 스냅샷

완전한 스냅샷은 다음 객체를 포함합니다.

- Namespace, Node, Pod, Service, Endpoints, EndpointSlice
- Deployment, ReplicaSet, DaemonSet, StatefulSet, Job, CronJob
- Ingress 및 IngressClass
- PersistentVolumeClaim, PersistentVolume, StorageClass
- HorizontalPodAutoscaler, PodDisruptionBudget, NetworkPolicy
- ResourceQuota 및 LimitRange

출처는 범위가 제한된 진단 필드만 보존합니다. 조건, 전환 시각, 컨테이너 그룹, 재시작 및 종료
사실, 프로브 종류, 스케줄링 제약, 리소스 요청량 및 제한, 용량, 스토리지 연결, replica 상태 및
엔드포인트 상태를 기록합니다. Secret 또는 ConfigMap 값, 컨테이너 명령, 환경 값, image pull
Secret, 원시 Event 메시지, 엔드포인트 주소 또는 원시 로그 본문은 기록하지 않습니다.
API 인벤토리 모듈은 전송, 페이지 처리 및 Resource 신원을 담당합니다. 별도 상태 정규화 모듈은
범위가 제한된 Node, Pod, 컨테이너 및 Deployment 상태 사실을 담당하므로 전송 모듈은 구문 분석
규칙을 복제하지 않고 강제 구조 크기 상한 아래로 유지됩니다.
수집기와 Operator 상한은 같습니다. 컨테이너를 최대 128개 수집하면 프로브 종류 레코드는 최대
384개, 현재 및 이전 종료 레코드는 최대 256개가 될 수 있습니다. 이보다 큰 진단 배열은 조용히
잘리지 않고 사용할 수 없는 상태가 됩니다.
Operator와 Console 허용 목록은 수집된 내용 안전 롤아웃, 스토리지, 정책 및 임시 컨테이너 진단
필드를 모두 포함합니다. 수집한 필드를 완전해 보이는 응답에서 조용히 제거하지 않습니다.
EndpointSlice 준비 상태에서 생략되거나 null인 `ready` 값은 `ready_unknown`에 보존합니다. Forseti는
엔드포인트가 하나 이상 있고 준비 및 준비 상태 미확인 수가 모두 0인 경우에만 `endpoint_unready`를
만듭니다.
명시적인 빈 NetworkPolicy `podSelector`는 `selector_matches_all: true`로 보존합니다. 형식이 지정된
이 NetworkPolicy 표식만 같은 네임스페이스의 모든 Pod를 선택합니다. 누락된 선택기나 빈 Service
선택기에 전체 일치 의미를 부여하지 않습니다.

### 수명 주기 이력

각 클러스터는 독립 Event 커서를 소유합니다. 최초 목록은 `resourceVersion`을 설정하고 범위가
제한된 감시 구간은 타입이 지정된 관측과 bookmark를 추가합니다. HTTP 410은 현재 범위 구간을
불완전 상태로 닫고 다시 seed한 뒤 새 구간을 시작합니다. Kubernetes는 압축된 Event를 복구할 수
없으므로 다른 권위 있는 출처가 정확한 구간을 포함하지 않는 한 보존된 공백은 완전해지지 않습니다.
영속 이력은 Event UID, 관련 객체 UID, 사유, 종류, 횟수, 출처 revision, Event 시각, 기록 시각
및 범위 구간 신원을 보존합니다.
각 불완전 구간은 내용 주소가 지정된 변경 불가 PostgreSQL 범위 구간입니다. 정확한 UID 이력 조회는
완전성을 주장하기 전에 겹치는 구간을 확인하므로 이후 커서 복구가 보존된 `cursor_expired`, 권한,
출처, 응답 또는 결과 상한 공백을 지울 수 없습니다.

### 메트릭

메트릭 근거는 기존 프로바이더 중립 `MetricProvider`를 사용합니다. 고정된 의미 이름은 다음을
포함합니다.

- 컨테이너 CPU 사용량 및 throttled seconds
- working-set memory, OOM Event, 네트워크 수신 및 송신, filesystem 사용량
- Pod 요청 CPU 및 메모리
- Node 할당 가능 용량 및 압력 용량

모든 시계열에는 정확한 `cluster_ref`, 네임스페이스, Pod UID 또는 Node UID 레이블이 필요합니다.
진단 메트릭 출처는 출처 revision, 프로바이더 기준 시점, 페이지 또는 잘림 상태 및 구간 범위도
반환합니다. 기존 점 전용 `MetricProvider`는 후보를 제공할 수 있지만 그 자체로 완전한 진단
구간을 주장할 수 없습니다. 이름만 있는 시계열, 혼합 신원, 미래 표본, 점 전용 출처 및 잘린
구간은 사용할 수 없음으로 유지합니다. 빈 메트릭 조회는 0을 입증하지 않습니다.
Forseti는 신호를 축약하기 전에 메트릭 대상 튜플, 지점 레이블, 메트릭 구간, 프로바이더 기준 시점 및
출처 revision을 정확한 진단 맥락과 다시 대조합니다. 불일치는 충돌로 보존되며 해당 메트릭은 진단
신호를 만들 수 없습니다.
독립 범위 증적은 표준 시간대가 있는 프로바이더 기준 시점이 요청 구간의 끝에 도달하거나 이를 지난
경우에만 구간을 완전하다고 표시할 수 있습니다.

### 로그

로그 근거는 정확한 Pod UID와 범위가 제한된 시간 구간으로 조회합니다. 원시 본문은 내용 해시를
만든 뒤 폐기합니다. 보존된 요약에는 레코드 수, 심각도 수, 타임스탬프, 다이제스트, 출처 신원과
revision, 프로바이더 기준 시점, 페이지 또는 잘림 상태, 구간 범위 및 구조화된 제한 사항이
들어갑니다. 별도 프로바이더 증적이 없으면 점 전용 `LogQueryProvider`는 완전한 구간 범위를
주장할 수 없습니다. 진단은 검토된 구조화 레이블과 수명 주기 사유만 사용할 수 있고 자유 형식
텍스트를 해석하지 않습니다.

### Azure 및 컨트롤 플레인 근거

이 플레인은 운영 인스턴스 그래프의 정확한 Node-to-VMSS VM 연결과 Azure 토폴로지를 재사용합니다.
AKS Resource Health, API 도달 가능성 및 구성된 컨트롤 플레인 진단 범주는 독립 관측입니다. 시간상
인접성과 토폴로지 근접성은 가설을 지지하거나 반박할 수 있지만 인과관계를 입증할 수 없습니다.
수락된 정확한 클러스터 인벤토리 출처는 해당 출처 기준 시점의 API 도달 가능성만 입증합니다. 승격
증적은 정확한 Azure 상태 또는 컨트롤 플레인 출처를 연결할 때까지
`azure_control_plane_evidence_unavailable`을 보존합니다. 토폴로지나 API 성공을 Azure 상태로
대체하지 않습니다.

## Agent 소유권 및 결정론적 진단

수집기는 기계적인 읽기 플레인 어댑터입니다. 인벤토리 승격에 성공하면 범위가 제한된 관측기가 정확한
대상 신원과 출처 상태를 검증하고 결정론적 T0 축약기를 호출한 뒤, 변경 불가 증적과 교정된 감사
항목을 원자적으로 추가합니다. 이 로컬 파생 조회 모델 단계는 에이전트 협업이 아니며 권한을 부여하지
않습니다. Forseti는 증적에 명시된 근본 원인의 최종 책임자로 유지됩니다.

축약기 하나는 정확한 대상 하나와 기준 시점 하나를 분류합니다. 초기 기능 집합은 다음과 같습니다.

- 스케줄링 및 할당량
- image pull 및 init-container 실패
- crash loop, 비정상 종료, OOM 및 프로브 실패
- 퇴거 및 Node 압력
- Service 및 EndpointSlice backend 상태
- 롤아웃 및 교체
- PVC, PV 및 StorageClass 연결
- HPA, PDB 및 정책 제약
- Node 네트워크 사용 불가와 검토된 Pod sandbox, CNI 및 DNS Event 사유
- AKS 컨트롤 플레인 또는 Azure 기반 저하

각 근거 증적에는 인증된 principal 클래스, 목적, 생산자 및 방식 버전, 안정적인 대상 신원, 관측
revision, 온톨로지 release, 출처 revision과 기준 시점, 근거 참조, 공백, 충돌, 최신성, 완전성,
합성 상태, 감사 상관관계, `cause_claim_supported=false` 및 `execution_authority=false`가
들어갑니다. 충돌하거나 불완전한 근거는 명시적으로 보류된 결과를 반환합니다. 모델은 검증된
Forseti 소유 결과를 설명할 수 있지만 선택하거나 변경할 수 없습니다.

## 영속성 및 변환 결과

수집기는 타입이 지정된 레코드를 추가합니다. 인벤토리 single writer는 현재 Resource 및 관계 변환
결과를 계속 소유합니다. 수명 주기 이력은 추가 전용입니다. 진단 결과는 내용 주소 기반 읽기
증적이며 관측된 Resource 상태가 되지 않습니다.

Core는 변경할 수 없는 증적을 읽기 전용 저장소 뒤에 보관하고 공유 스키마를 통해 변환합니다.
Operator API는 일반 Reader 역할과 `operations-review` 목적을 요구하고 서버 소유 교정을 적용하며
허용 목록에 포함된 신원, 상태, 근거 건전성 및 진단 증적을 노출합니다. Console은 공유 스키마를
검증하고 출처, 기준 시점, 공백 및 정확한 리소스 신원을 렌더링합니다. 브라우저에서 Resource,
관계, 메트릭 값, 진단 또는 권한을 만들지 않습니다.
증적 신원은 정확한 대상, UID, resourceVersion, 온톨로지 release, 표준 JSON 시각, 출처 기준 시점
및 출처 revision으로 내용 주소화됩니다. 온톨로지 변환이 비활성화돼도 복구는 대기 중인 승격을
재현합니다. Operator는 증적의 대상 신원, 인벤토리 세대 다이제스트, 온톨로지 release, 출처 기준
시점 및 fleet 범위 다이제스트가 선택한 현재 Resource와 일치할 때만 증적을 노출합니다. 불일치는
진단을 사용 불가로 표시합니다.

## 온톨로지 및 배포 변경

카탈로그는 런타임 인벤토리가 객체를 내보내기 전에 PVC, PV, StorageClass, HPA, PDB,
NetworkPolicy, ResourceQuota 및 LimitRange를 위한 정확한 ResourceType을 추가합니다. 첫
release에는 기존 `contains`, `depends_on`, `attached_to` 및 `kubernetes_selects` LinkType으로
충분합니다. 새 mapping은 각각 갱신된 Kubernetes 출처 스키마 다이제스트를 고정합니다.

`InventoryProjectionSourceState`는 선택적 `scope_digest`를 추가하고 고유성은
`(source, scope_digest)`가 됩니다. 기존 레코드는 이 필드를 생략합니다. Fleet 연결 변수는
검증된 레코드를 최대 32개 제공하며 기존 단일 클러스터 변수와 함께 사용할 수 없습니다.
Terraform은 정확한 각 클러스터 ARM 범위에서 인벤토리 신원에 Reader 접근 권한을 부여하며 bearer
token을 전달하지 않습니다. 별도 Terraform deployer 역할은 구성된 안정 실행기 UAMI principal을
사용하며 인증된 principal이 다르면 계획을 중단합니다. 실행기 호스트를 다시 만들어도 AKS 관찰
권한이 다른 principal로 바뀌지 않습니다.

## 상한과 실패 동작

| 경계 | 초기 상한 |
|------|-----------|
| 클러스터 연결 | 32 |
| 클러스터 세대별 Kubernetes 객체 | 20,000 |
| 종류별 페이지 | 64 |
| 객체별 조건 또는 상태 항목 | 128 |
| 읽기별 Event 행 | 256 |
| 읽기별 로그 레코드 | 최대 24시간 동안 128개 |
| 메트릭 시계열 | 대상 16개 및 시계열별 점 20개 |
| 진단 대상 | 증적별 정확한 Resource 하나 |

상한을 넘으면 이전 활성 근거를 유지하고 타입이 지정된 제한 사항을 기록합니다. 일부 입력은 이전
객체, 관계 또는 출처 증적을 삭제할 수 없습니다.

## 전달 및 검증

구현은 다음과 같이 집중된 배치로 진행합니다.

1. Fleet 안전성을 갖춘 연결과 클러스터별 출처 상태를 추가합니다.
2. 정확한 신원 및 리소스 버전 확인을 추가합니다.
3. 범위가 제한된 Kubernetes 진단 사실과 관계를 확장합니다.
4. 엔드포인트 상태, 메트릭, 로그 및 수명 주기 이력을 연결합니다.
5. 결정론적 진단과 권한 없는 변환 결과를 추가합니다.
6. 독립적인 비평 및 하드닝 라운드를 10회 이상 완료합니다.
7. 외부에서 준비된 정확한 실제 AKS 클러스터 하나에서 양성 및 사용 불가 사례를 검증합니다.

근거 플레인 자체는 클러스터를 시작하거나 중지하지 않습니다. 이번 전달 캠페인에서는 유지관리자의
현재 세션 명시적 승인을 통해 코딩 세션 운영자가 집중 검사를 통과한 뒤 정확한 클러스터를 시작할
수 있습니다. 근거를 수집한 뒤 초기 전원 및 로컬 연결 상태를 복구합니다. 이 테스트 작업은
런타임 실행 권한을 부여하지 않습니다.

## 관련 문서

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| 구현 상태와 남은 작업 | [AKS 진단 구현 원장](../../roadmap-implementation/architecture/aks-diagnostic-evidence-plane.md) |
| 연속 출처 최신성과 승격 | [연속 운영 인스턴스 그래프](continuous-operational-instance-graph-ko.md) |
| 리소스 및 관계 신원 | [온톨로지 구조 모델](ontology-structural-model-ko.md) |
| 근본 원인 근거 경계 | [근본 원인 분석](../rules-and-detection/root-cause-analysis-ko.md) |
