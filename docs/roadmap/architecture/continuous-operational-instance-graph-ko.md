---
translation_of: continuous-operational-instance-graph.md
translation_source_sha: 1582b3292dda3084eeae15ab2be5ce09f897df4f
translation_revised: 2026-09-11
---
# 지속형 운영 인스턴스 그래프

이 문서는 클라우드 리소스 인스턴스, 관계, 관측 상태를 FDAI 온톨로지에서 최신으로
유지하는 런타임 계약을 소유합니다. 수집은 지속적이며 부하를 고려하고, 원시 이력은 타입이
지정된 rollup과 검증된 archive를 거쳐 활성 데이터 플레인의 크기를 제한합니다.

> **범위 경계:** 이 설계는 공급자 관측, 온톨로지 인스턴스 변환 결과, 최신성, 압축,
> archive, 그래프 우선 조회를 다룹니다. 승인, 변경, 실행 권한을 부여하지 않습니다.
>
> **공급자 경계:** 계약은 cloud-provider-neutral (CSP-neutral)하게 유지합니다. Azure
> Resource Graph, Activity Log, Monitor, Resource Health가 현재 구현된 공급자 원본입니다.

## 설계 개요

지속형 수집은 push 이벤트, 재개 가능한 공급자 delta, 적응형 reconciliation을 결합합니다.
일반 최신성 수단으로 고정된 6시간 scan을 사용하지 않으며, 제한 없는 촘촘한 polling loop도
실행하지 않습니다.

![설계 개요. 주요 단계는 Provider events and delta APIs, Durable observation ingress, Normalize and adjudicate, Current operational graph, Bitemporal observation history, Typed rollups, Verified archive, Verified semantic query, Evidence current and complete?, Evidence-backed result, Bounded live read입니다.](../../diagrams/generated/fdai-roadmap-architecture-continuous-operational-instance-graph-01.ko.svg)

## 변경할 수 없는 불변식

- **관측된 사실:** 인증된 공급자 관측만 `observed` 상태 lane에 들어갈 수 있습니다. 질문,
  모델 출력, 의도 상태, dispatch 증적, 실행기 결과는 관측 사실을 만들 수 없습니다.
- **배포 근거:** 보호된 플랫폼 계획 메타데이터는 전용 저장소 모듈에서 생성합니다. 워크플로
  YAML은 봉인된 입력을 이 모듈에 전달하며, 계획과 해당 증적은 관측 그래프 사실을 만들 수
  없습니다. 상태를 재정의하는 모든 서비스 배포 실행 또는 작업 단계는 보호된 원본 검증기가
  성공한 후에만 실행합니다. 정리, 실패 보고 또는 아티팩트 보존은 디스패치를 관측 근거로
  바꾸지 않습니다. 서비스 워크플로 계약 테스트는 최종 롤백 실패 보고에서 이 검증기 성공
  조건식을 고정합니다.
- **단일 작성자:** 수집기는 타입이 지정된 관측을 추가합니다. 온톨로지 인스턴스를 직접
  변경하지 않습니다. 하나의 변환 결과 소유자가 관측을 판정하고 현재 하위 그래프를 원자적으로
  전진시킵니다.
- **그래프 우선:** 일반 질문은 공급자 API보다 먼저 현재 운영 그래프를 읽습니다. 필요한
  근거가 누락되거나 오래되거나 불완전하거나 충돌하거나, 범위가 제한된 조회 정책에 따라
  명시적으로 요청된 경우에만 실시간 공급자 조회를 허용합니다.
- **안전한 보강:** 실시간 조회는 현재 답변을 지원할 수 있으며 같은 ingress를 통해 타입이
  지정된 관측을 게시합니다. 부분 조회는 완전한 세대를 대체하거나 관측하지 않은 객체 또는
  관계를 삭제할 수 없습니다. 런타임 환경 바인딩은 메모리 안에서 정확한 신원으로 관계를
  결합할 때만 사용할 수 있습니다. 인벤토리 스냅샷이나 온톨로지에 저장하기 전에는 바인딩
  이름과 값을 제거합니다.
- **시간과 출처:** 모든 사실은 유효 시간, 가능한 경우 이벤트 시간, 기록 시간, 근거 기준
  시점, 원본 신원, 원본 수정본, 완전성, 충돌, 최신성 정책을 유지합니다.
- **잘못된 부재 방지:** 누락 이벤트, 잘린 조회, cursor 지연, 열린 실시간 overlay, archive
  사용 불가는 명시적인 알 수 없음 또는 불완전한 근거로 유지합니다.
  범위가 제한된 조회는 사용 가능한 범위의 검증된 양성 관측을 반환할 수 있지만 결과를
  불완전하게 유지하며, 누락 범위를 다른 관측이 없다는 증거로 취급하지 않습니다.
- **조회와 쓰기 분리:** 공급자 관측과 온톨로지 변환 결과는 조회 플레인 작업입니다. 관리
  리소스 writeback은 통제되는 작업 경로에 남고 독립적인 재관측 후에만 닫힙니다.
- **제한된 보존:** rollup 또는 archive 매니페스트가 완전한 원본 범위를 검증하고 적용되는
  보존 hold가 삭제를 허용한 후에만 hot 또는 warm 저장소에서 원시 데이터를 제거합니다.

## 지속형 수집 계약

### 원본 전략

수집기는 필요한 최신성을 보존할 수 있는 가장 저렴한 권위 있는 신호를 사용합니다.

1. 리소스 생성, 변경, 삭제 이벤트를 정식 이벤트 스트림에 push합니다.
2. 지연 또는 불완전한 overlay가 존재하는 동안 durable cursor에서 재개 가능한 공급자
   delta를 가져옵니다.
3. 누락 이벤트를 찾고 관계를 복구하며 범위 완전성을 증명하도록 제한된 reconciliation을 실행합니다.
4. inventory에 근거 유형이 없거나 검증된 쿼리에 더 최신 근거가 필요할 때만 정확한 실시간 조회를 실행합니다.

수집된 속성은 검토된 프로바이더 mapping을 거쳐야만 관계가 됩니다. Mapping이 관측된 연결
대상을 빠뜨리면 없는 그래프 edge가 경로 부재를 입증하지 않습니다. 따라서 도달 가능한 모든
관리형 서비스 연결의 대상 유형을 검토된 카탈로그에 선언하는 것이 좋습니다.
비활성화된 리소스 변경 및 복구 가속기는 수집 정책 항목을 요구하지 않으며 조정에 커서 접두사나
오래된 커서 기한을 추가하지 않습니다.

Kubernetes fleet 수집은 정확한 클러스터 연결마다 출처 상태 레코드 하나를 보존합니다. 레코드는
고객에게 안전한 범위 다이제스트를 사용하므로, 사용할 수 없는 클러스터 하나가 다른 클러스터의
검증된 양성 근거를 지우거나 ARM 신원을 노출하지 않고 fleet 완전성을 낮춥니다.
배포된 Inventory Job은 기존 연결 또는 범위가 제한된 fleet JSON 레코드 중 하나만 허용하며 같은
읽기 신원에는 정확한 각 클러스터 범위에서 AKS RBAC Reader만 부여합니다.
수명 주기 수집은 각 연결마다 독립 lease와 resourceVersion 커서를 획득합니다. 한 클러스터 실패는
fleet 근거를 불완전하게 유지하지만 다른 클러스터에서 수락된 Event 관측을 중지하거나 지우지
않습니다.

런타임 호출 근거에는 해시된 요청 식별자와 정확한 호출자 및 대상 Container App Resource ID가
같은 타입 지정 엔드포인트 증표 두 개가 필요합니다. Operator는 인증된 브로커 수락 뒤에만 호출자
증표를 내보내며 관측 시점도 수락 이후에 기록합니다. Core는 해당 브로커 전달이 대상 경계에
도달하는 즉시 turn 처리에서 거절되기
전에 대상 증표를 내보냅니다. 두 증표 모두 요청 내용이나 권한을 포함하지 않습니다. 소비자가
취소되면 전달 작업이 끝나기 전에 연결된 진행상황 게시자를 항상 중지하므로 대상 경계 뒤에
오래된 진행상황 작업이 남지 않습니다. Azure Monitor
원본으로부터 받은 신뢰할 수 없는 원격 분석 묶음은 변환 결과 입력으로 직접 바꾸는 기능을
제공하지 않습니다. 인증된 생성기만 정확한 묶음 다이제스트와 독립 원본 컨텍스트를 검증한 뒤
유한한 양의 기한 안에서 변환할 수 있습니다. Azure Monitor 원본은 일치하는 구조의 Container Apps 로그
스키마만 수락한 다음 플랫폼이 기록한 각 Resource ID, revision 및 replica를 해당 증표가 주장한 정확한
Container App ARM ID 아래에서 다시 읽습니다. 이 방식으로 독립적으로 결속된 엔드포인트 증표만
기존 정식 Resource ID 매핑으로 변환합니다. 독립 채널
경계 프로세스는 호출자 바인딩을 받지 않으므로 공유 토픽의 요청을 잘못된 Operator-to-Core
edge로 결합할 수 없습니다. 짝이 없거나 형식이 잘못되거나 일치하지 않는 증표가 있으면 원본은
불완전 상태가 됩니다. 결합된 반복 호출은 정확한 엔드포인트 쌍별 최신 관측으로 축약합니다.
60초 후행 유예 구간은 처리 중인 쌍을 대기 상태로 유지하며, 원본은 최신성 구간보다 유예 구간
하나를 더 읽어 기준 시점 경계가 보존 대상 쌍을 나누지 않도록 합니다. 불완전 원본의 범위
정보는 고정된 행 개수 키만 허용하며 프로바이더 식별자나 임의 원본 텍스트를 포함할 수 없습니다.
정확한 replica 검증은
하나의 30초 기한 안에서 최대 네 개의 동시 읽기를 사용하며, 최신성은 해당
읽기가 끝난 뒤에만 평가합니다. 그런 다음 인벤토리 기록기는 `runtime_calls`를 변환하기 전에
완전한 활성 세대, principal 범위, 최신성 예산 및 정확한 온톨로지 릴리스에 대해 두 엔드포인트
ID를 다시 검사합니다. 검증 증적은 두 엔드포인트 Resource ID와 활성 세대의 Resource 형식을
함께 결속합니다. 로컬 개발에는 Container Apps 로그 식별이 없으므로 edge를 날조하지 않고
이 원본을 사용 불가로 보고합니다. 바인딩이 비활성화됐거나 증표 쿼리가 비어 있을 때도 같은
사용 불가 결과를 유지합니다.
플랫폼의 `enable_runtime_call_evidence` 입력은 기존 Operator API 모듈과 독립적으로 이 Inventory
Job 원본을 제어하므로 상태 이행이 수집을 조용히 제거할 수 없습니다. 스키마가 유효한
`plan-runtime-*` 및 `apply-runtime-*` 요청은 전용 플래그, workspace 및 정확한 이미지 전환 리소스를
대상으로 하며 혼합 대상을 거부합니다. 전환은 검증된 롤백을 포함한 제한된 업데이터를 사용해
관련 없는 모듈 의존성을 계획하지 않고 기존 Inventory Job을 활성화합니다. 검증된 개정 번호를
선택하면 오래된 이미지도 교체합니다. 바인딩 업데이터는 정확한 Log Analytics customer ID도
해석해 런타임 플래그와 함께 적용하며 롤백은 두 이전 값을 복원합니다. 계획 후 범위 검사는
다른 모든 주소를 차단하며, 적용 후 검증은 원본을 활성 상태로 처리하기 전에 플래그, workspace
다이제스트 및 이미지 다이제스트를 모두 독립적으로 읽습니다.
계획의 전체 JSON 변환 결과와 값 없는 요약은 범위가 제한된 계획 메타데이터를 봉인할 때까지
현재 UID가 소유한 mode-0700 임시 디렉터리에 유지하며, 이후 두 비공개 파일을 제거합니다.
PostgreSQL 데이터베이스 역할 관측은 Resource 또는 Link 형태가 없는 별도의 principal-safe 변환
결과로 유지합니다. 관측, 정제된 근거 및 변환 결과 계약은 형식 주석에만 의존하지 않고 실행
중에도 실행 또는 변경 권한을 각각 거부합니다. 변환된 principal handle은 불투명한 인증 근거
참조와 범위가 지정된 원본 컨텍스트에서 파생하며 엔트로피가 낮은 역할 이름을 해시하지 않습니다.
현재 Operator 및 Console 인스턴스 상세 응답은 런타임 호출 및 PostgreSQL 역할 원본 상태를
명시해야 합니다. 누락은 가용성이나 측정된 0이 아니라 잘못된 응답으로 처리합니다. Operator
영속성 판독기는 포함된 인벤토리 세대가 선택한 정확한 스냅샷과 일치할 때만 런타임 호출 링크
메타데이터를 허용합니다. 사용 불가 원본 사유는 정식 기계 토큰이어야 하며 principal 텍스트,
엔드포인트 또는 프로바이더 세부 정보를 포함할 수 없습니다.
Operator 수명 주기는 전용 보낼 편지함 수명 주기 facade와 재시도 가능한 작업자를 통해 영속 Incident 개입 요청도 게시할 수 있습니다.
어댑터는 해당 논리 토픽을 명시적으로 허용 목록에 등록하고 설정된 물리 전송 계층을 통해 다중화합니다.
런타임 호출 증표, 그래프 edge, 프로바이더 관측 또는 실행 권한은 만들지 않습니다.

보호된 서비스 배포는 먼저 플랫폼이 소유한 런타임 호출 바인딩을 사용합니다. Operator 상태
이행으로 기존 플랫폼 모듈이 비활성화되면 두 Container App이 계속 배포되어 있어도 해당 출력이
없을 수 있습니다. 이때 Virtual Network 내부 runner는 독립 서비스 상태에서 정확한 Operator 앱
이름을 권한 모드 0600의 임시 파일로 읽고 플랫폼 상태에서 Core 앱 이름과 리소스 그룹을
읽습니다. 임시 이름은 정제된 peer-state 매니페스트에 포함되지 않으며 peer-state 작업 영역과
함께 제거됩니다. 이 이름과 고정된 구독을
사용해 Azure에서 두 개의 정확한 Resource ID를 읽습니다. 이후 같은 폐쇄형 검증이 서로 다른 두
Container App ID를 요구한 뒤에만 서비스에 바인딩을 제공합니다. 두 서비스 루트는 정확한 구독
UUID, 리소스 그룹 세그먼트, 프로바이더 경로 및 마지막 앱 세그먼트가 있는 정식 비공백 ARM ID를
요구합니다. 일부만 있거나 후행 슬래시 또는 공백이 있거나 두 엔드포인트가 같으면 검증에
실패합니다. 상태 또는 프로바이더 읽기가 실패하거나 모호하면 계획을 차단하며 조합한 신원으로
대체하지 않습니다.

지속형은 끝나지 않는 프로세스가 아니라 수집에 항상 durable한 다음 작업이 있음을 뜻합니다. 이벤트 소비자는 활성 상태를 유지하고 safe-to-retry cursor 및 reconciliation 작업은 진행 상황을 저장합니다.

현재 그래프 checkpoint는 활성 스냅샷 세대와 정확한 범위 집합에 결속됩니다. 완전한 프로바이더 스냅샷은 같은 범위의 해당 세대 및 시작 시각 이전 관측을 포함하므로 연속된 checkpoint는 해당 범위만 탐색합니다.
비활성 범위 관측은 내구성 있는 이력과 보존 작업으로 유지합니다. 범위를 다시 활성화하려면 새로운 완전한 reconciliation이 필요하며, 활성 범위의 스냅샷 이후 관측은 변환 결과가 따라잡을 때까지 그래프를 불완전하게 유지합니다.
PostgreSQL 영속성은 저장소 조정을 `postgres_ontology.py`에 유지하고 인벤토리 상태 기준의 완전성과
객체 소유권 검증을 `postgres_ontology_records.py`에 통합합니다. 이 공통 레코드 검증 경계는
다른 그래프 기록기나 권한 표면을 만들지 않습니다.

### 비공개 네트워크 변경 가속

비공개 배포 프로필은 내구성 있는 cursor로 Azure Resource Graph `resourcechanges`를 폴링하고
위치가 그대로여도 활성화된 모든 가속기의 폴링 상태를 추적합니다. 범위가 제한된 각 페이지는 오래된 항목부터
정렬하고 경계 중복을 멱등하게 처리하며, 수락된 모든 변경이 정식 관측 수신 경로에 들어간 뒤 cursor를
진행합니다. 생성 및 업데이트 행은 변경된 Resource ID만 대상으로 범위가 제한된 정확한 Resource
Graph 재조회를 실행합니다. 삭제 행은 확인되지 않은 tombstone이 되며 완전한 reconciliation이
부재를 입증할 때까지 기다립니다. 부분 페이지나 매핑된 대상의 누락은 cursor와 overlay를 진행하지
않으며, 반환된 미지원 공급자 형식은 명시적인 커버리지 공백으로 유지합니다.

변경 가속기는 최대 2초 동안 급증한 변경을 묶고 리소스별 순서를 적용하며, 정확한 재조회와 검토된
mapping 카탈로그가 지원하지 않은 관계를 게시하지 않습니다. Azure Activity Log는 감사 및 복구
출처로 유지하고, 완전한 ARG 및 ARM reconciliation은 누락된 변경을 복구하고 하위 토폴로지를
수집합니다. Resource Graph 변경 정보는 최종 일관성을 사용하므로 이 경로는 즉시성을 보장하는
프로바이더 기능이 아니라 실시간에 가까운 처리입니다.

AKS AgentPool 크기는 Resource Graph가 해당 자식을 일반 Resource로 노출하지 않으므로 범위가
제한된 ARM 자식 수집이 소유합니다. VM Scale Set 크기는 프로바이더 `sku.capacity`에서
가져옵니다. 두 값은 인벤토리 작성기가 새 관측 또는 완전한 세대를 커밋한 뒤에만 Console에
도달합니다. SSE watermark는 다시 읽기를 앞당기지만 용량을 만들거나 추정하지 않습니다.

관측 journal과 실시간 overlay가 커밋된 뒤 단조 증가 watermark를 정제된 인벤토리 무효화 이벤트로
사용합니다. Operator SSE 경로는 인증된 읽기 권한 아래에서 watermark, 개수, 관측 시각만
노출합니다. 프로바이더 payload를 노출하거나 그래프 사실을 만들지 않습니다. 표시 중인 Console이
무효화 이벤트를 받으면 범위가 제한된 선택 인스턴스 변환 결과를 다시 읽습니다. SSE는
`Last-Event-ID`부터 다시 연결하며 폴링은 범위가 제한된 fallback으로 유지합니다.

관측된 모델 배포도 같은 세대와 무효화 경로를 사용합니다. Operator 변환 결과는 추가
`model_deployment` 객체에서 모델 이름, 모델 버전, 배포 SKU 및 정규화된 TPM만 노출합니다.
Console 카드, 도구 설명, 상세 패널 및 화면 맥락은 원시 프로바이더 속성을 받지 않고 이 허용
목록을 사용합니다. 변경된 TPM은 다음 관측이 수락되어 커밋된 뒤에만 표시됩니다. 무효화 이벤트는
다시 읽기를 앞당기지만 즉시성이나 강한 일관성을 프로바이더 수준에서 보장하지 않습니다.

### 부하 인식 일정 관리

각 원본은 하나의 전역 간격 대신 검증된 정책을 사용합니다. 정책은 다음을 포함합니다.

- 목표 최신성과 허용 가능한 최대 노후 시간
- 최소 및 최대 polling 간격
- 구간별 요청 및 byte 예산
- 전역, 범위, 리소스 타입, endpoint 동시성 제한
- cursor page, 객체, 관계, 시간, 무진행 제한
- 변경됨, 오래됨, 중요함, 운영자 요청 대상의 우선순위
- 범위가 제한된 jitter, 지수 backoff, circuit-breaker 임계값
- 공급자 `Retry-After`, quota, 남은 예산 관측

backlog, 이벤트 지연 또는 폴링 상태 지연이 증가하면 scheduler는 예산을 더 빨리 사용합니다.
각 가속기는 장애를 합산 건수로 숨기지 않고 정제된 이유 코드로 보고합니다. HTTP `429`와 공급자
throttling은 동시성을 줄이고 `Retry-After`를 따르며, 지속적인 사용 불가는 circuit을 열고
계속 재시도하는 대신 범위가 제한된 probe를 예약합니다.
더 최신의 실패 시도가 없으면 스케줄러는 활성 스냅샷 완료 후 경과 시간을 마지막 시도 후
경과 시간으로 사용하고 오버레이 행, 삭제 표식, 열린 변환 워터마크를 조정 대기로 처리합니다.
변경 수요 또는 최대 노후 상태가 실패 시간 부재로 계속 연기되지 않습니다.
로컬 장기 실행 루프는 원본, 변환 또는 대기 재생 실패를 형식화해 기록하고 구성된 간격 후 다시
시도합니다. 일회성 작업은 원본 수집이나 승격된 온톨로지 변환이 실패해도 실패하며, 다음
tick의 범위가 제한된 복구를 위해 정본 인벤토리 세대는 유지합니다.

검증된 구성은 배포 값을 제공합니다. 저장소 기본값과 테스트는 안전한 범위를 정의하며, 하나의 간격이
모든 tenant 또는 공급자 API에 적합하다고 주장하지 않습니다.
조정기는 승격된 관측과 관계 범위의 불변 레코드를 전용 전달 모듈에서 가져와 명시적으로 다시
내보냅니다. 기존 소비자는 같은 전달 경계를 유지하며, 이 분리는 단일 작성자 소유권이나 승격
권한을 변경하지 않습니다.

### 수렴과 삭제

실시간 delta는 최신성을 높이지만 전역 완전성을 증명하지 않습니다. 완전한 reconciliation
세대는 포함된 overlay를 닫고 삭제를 확인하는 권위로 유지됩니다. promotion은 원자적이며,
부분 또는 충돌 세대는 이전 완전 그래프를 대체할 수 없습니다.

리소스와 관계 변경은 논리 리소스별로 정렬합니다. 중복 전달은 no-op이고, 오래된 cursor 또는
이전 이벤트는 인스턴스를 뒤로 이동시킬 수 없습니다. Tombstone은 원본, 유효 시간, 세대,
archive 계보를 유지합니다.

완전한 공급자 세대에는 endpoint가 활성 세대 밖에 있거나 공급자 타입이 모델링되지 않았거나
정확한 참조가 관측되지 않아 edge가 될 수 없는 검토된 candidate가 포함될 수 있습니다. 이
타입 지정 non-edge는 최신 Resource 객체와 독립적으로 검증된 link의 전진을 막지 않습니다.
Ontology projection은 같은 세대를 `relationship_complete=false`로 전진시키고 분류된 모든
사유를 보존합니다. 관계 커버리지는 관계 주장을 한정합니다. 즉 쿼리가 그래프를 완전한 관계
근거로 사용하지 못하게 하되, 객체 집합이 집합 내부 edge를 만들 수 없는 스냅샷은 관계에 대해
아무것도 진술하지 않으므로 자신의 객체 커버리지를 그대로 유지합니다. 분류되지 않은 drop,
잘못된 검증 metadata, 부분 source 세대, conflict 또는 cardinality 위반은 계속 차단되며 이전
그래프를 보존합니다.

정확히 검토된 공급자 parent는 같은 child에 대한 일반 Resource Group containment를
shadow합니다. Snapshot promotion은 활성 pointer를 변경하기 전에 child별 `contains` parent가
하나를 초과하는지 독립적으로 거부하고, ontology store는 commit 전에 LinkType cardinality를
다시 검증합니다. Bounded ARM compute source는 다른 ARM-only nested resource와 같은 page,
child-collection, host 및 generation fence 아래에서 VM Scale Set VM child와 각 child의 network
interface를 나열합니다. Child collection 실패는 generation을 중단하며 template network
configuration으로 instance identity를 만들지 않습니다. Ontology projector는 graph 교체와 manifest/status commit marker 전체에서
process-local lock과 PostgreSQL session advisory lock을 유지합니다. Reader는 active snapshot,
status, manifest generation과 content digest가 일치해야 한다고 요구합니다. 따라서 crash 또는
stale replica는 safe-to-retry migration 또는 commit이 상태를 닫을 때까지 incomplete evidence를
반환하며 혼합 세대를 complete로 노출하지 않습니다. Legacy 1.2.0 manifest는 같은 릴리스의
다음 exact projection에서 다시 만들고 1.3.0으로 기록하며, 검증되지 않은 소유권을 릴리스
전환에 넘길 수 없습니다. 온톨로지 릴리스가 바뀌면 projector는
보존된 manifest를 기록된 릴리스 digest로 먼저 검증한 뒤 완전한 활성 인벤토리를 새 릴리스로
다시 projection합니다. 보존된 identity는 원자적 교체를 위한 소유권 근거로 유지하지만 이전
manifest digest는 새 릴리스의 같은 generation content를 인증할 수 없습니다. 별도의
릴리스 독립적 content digest가 전환 중에도 같은 generation의 변조 감지를 유지합니다.

PostgreSQL projector는 lock을 획득하고 활성 인벤토리 세대를 다시 확인한 뒤 그래프 교체와
매니페스트 및 상태 마커를 하나의 트랜잭션으로 커밋합니다. 엔드포인트 외래 키는 동시 리소스
삭제가 고아 관계를 남기지 않도록 방지합니다. 대기 중인 관계 조정 마커는 해당 관측 이후의
완전한 전체 범위 세대가 마커를 지울 때까지 그래프 완전성을 낮춥니다. 리소스 타입 하위 집합
스캔은 전역 스냅샷으로 승격하거나 전역 온톨로지 projection을 대체할 수 없습니다.

## 보존, rollup, archive

### 저장 계층

| 계층 | 내용 | 조회 동작 |
|------|------|-----------|
| Hot | 현재 객체와 링크, 최신성 상태, 활성 overlay, 최근의 정확한 관측 | 기본 운영 조회 경로입니다. |
| Warm | 구성된 상세 보존 구간의 bitemporal 원시 관측, 수정본, tombstone, reconciliation 증적 | 범위가 제한된 최근 이력, replay, topology 비교에 사용합니다. |
| Rollup | 타입이 지정된 시간별, 일별 또는 정책 선택 집계와 원본 범위 및 완전성 | 정확한 이벤트가 필요하지 않은 장기 추세에 사용합니다. |
| Archive | 변경 불가능하게 압축된 partition, content-addressed 매니페스트, 출처, 보존 등급, 복원 metadata | 명시적인 이력 검색 경로에서만 읽습니다. |

### 범위가 제한된 관측 이력

런타임은 기존 overlay를 현재 조회 경로로 유지하면서 정규화된 관측을 추가 전용 원장에
이중 기록합니다. 원장 레코드는 범위가 제한된 사실 또는 변경 힌트 하나를 전달하고 원본
schema와 원본 수정본을 고정합니다. Partition 수명 주기, archive 보존 및 수명 인스턴스 경계는
이제 Core 소유의 타입 지정 수명 주기 레코드를 사용합니다. Production archive 구성요소는
전용 예약 Job이 배포 개정에서 결속할 때까지 조립되지 않은 상태로 남아 있습니다.

각 레코드는 다음 의미를 구분합니다.

- **변경 힌트:** 프로바이더가 리소스 변경을 알리지만 전체 속성을 제공하지 않은 경우입니다.
  명시적인 속성 마스크를 사용하며 관측하지 않은 값을 대체할 수 없습니다.
- **전체 관측:** 권위 있는 읽기가 원본 개정에서 리소스 또는 관계 하나의 검토된 전체 속성
  집합을 반환한 경우입니다.
- **부분 관측:** 범위가 제한된 읽기가 지정된 속성만 반환한 경우입니다. 변환 결과는 선언된
  마스크만 병합하고 나머지 값에는 이전 근거의 제한 사항을 계속 적용합니다.
- **Tombstone 후보:** 삭제 신호가 정확한 대상을 작업에 사용할 수 없게 만들지만, 정확한 읽기
  또는 완전한 reconciliation이 확인하기 전까지 전체 범위의 부재를 입증하지는 않습니다.
- **확인된 tombstone:** 재관측 또는 완전한 reconciliation이 삭제를 확인하고 리소스 수명
  인스턴스, 유효 시각, 원본 개정 및 근거 참조를 기록한 경우입니다.

원장은 프로바이더 이벤트 시각, 유효 시각, 관측 시각, 수집 시각, 기록 시각 및 근거 기준
시점을 구분합니다. 또한 원본 신원, 원본 이벤트 ID, cursor 또는 개정, 범위, 완전성, 충돌,
속성 마스크, 내용 다이제스트 및 보존 등급을 유지합니다. 성공한 쓰기와 같은 작업 상태는 변경
metadata로 유지하며 리소스 운영 상태가 될 수 없습니다.

삭제 후 같은 리소스 ID가 다시 사용될 수 있습니다. 따라서 변환 결과는 변경할 수 없는
프로바이더 신원, 세대 또는 독립적으로 검증된 수명 주기 경계에서 리소스 수명 인스턴스를
할당합니다. 객체와 관계 관측은 이 수명 인스턴스를 참조합니다. 이름 일치, 이벤트 순서만을
사용한 판단 또는 추론된 재생성으로 서로 다른 두 수명 주기를 합칠 수 없습니다.

### 보존 정책과 partition 수명 주기

배포 소유 보존 정책 레지스트리는 각 사실 계열의 목적, hot 및 warm 보존, archive 등급, hold
동작, 삭제 방법 및 검토 날짜를 지정합니다. 저장소 기본값은 안전한 범위만 정의하며 모든
tenant에 하나의 보존 기간을 강제하지 않습니다.

| 사실 계열 | Hot 또는 warm 처리 | 장기 처리 |
|-----------|--------------------|-----------|
| 변경 힌트와 대체된 부분 관측 | 짧은 exact replay 구간 | 검증된 checkpoint와 archive 정책이 허용한 뒤 purge합니다. |
| 전체 객체 및 관계 관측 | 상세 replay 구간 | 등록된 목적에 따라 checkpoint, archive 또는 보존합니다. |
| 확인된 tombstone과 수명 인스턴스 경계 | 일반 delta보다 오래 보존 | 신원 재사용과 잘못된 부재 판단을 막을 수 있는 계보를 유지합니다. |
| 상태 전이와 범위 | 의미 및 인시던트 요구사항에 따라 보존 | 관측하지 못한 중간 전이를 주장하지 않고 타입 지정 rollup 또는 archive로 이동합니다. |
| 감사, 승인, 실행 및 rollback 근거 | 별도 관리 일정 | Inventory 보존 정책을 암묵적으로 상속하지 않습니다. |
| 매니페스트, 범위 index, hold 이벤트 및 purge 증적 | 최소 영속 metadata | 설명 대상인 원본 partition보다 오래 유지합니다. |

PostgreSQL 원장과 이력 테이블은 시간과 범위에 따른 range partition을 사용합니다. Partition은
`open`, `sealed`, `checkpointed`, `archived`, `verified`, `purge_eligible`, `purged` 순서로
전진합니다. `held`와 `correction_pending`은 전진을 차단합니다. 행 단위 삭제는 일반 수명 주기
동작이 아닙니다. 모든 gate가 통과한 뒤에만 purger가 정확한 partition을 분리하고 제거합니다.

Checkpoint가 purge 권한을 제공하려면 다음 정보를 결속해야 합니다.

- 포함된 첫 번째 및 마지막 원장 watermark
- 범위, 리소스 타입, 객체, 관계 및 속성 범위
- 원본, schema, ontology release 및 변환 결과 다이제스트
- 누락, 격리, 충돌 및 tombstone 레코드 수
- 결과 current graph 다이제스트와 변환 결과 watermark

원장 상위 watermark와 변환 결과 상위 watermark는 모든 current graph 증적에 표시됩니다.
원장이 더 앞서 있거나 해결되지 않은 부분 관측이 있거나 tombstone이 확인을 기다리면 graph는
불완전한 근거를 보고합니다. Snapshot이나 archive 매니페스트가 이 공백을 숨길 수 없습니다.

늦게 도착한 관측은 correction partition에 추가합니다. 변경 불가능한 partition을 다시 쓰지
않습니다. 새 content-addressed correction 매니페스트와 replay 증적이 해당 구간을 닫을 때까지
보정은 영향을 받은 checkpoint, rollup 및 archive 범위를 무효화합니다. 오래된 이벤트는 이력을
개선할 수 있지만 current 상태를 이전으로 되돌릴 수 없습니다.

활성 incident, investigation, 승인, 실행, rollback, legal hold 또는 replay lease는 참조하는
모든 partition을 고정합니다. 근거 참조에서 partition으로 역추적할 수 있으므로 보존 작업이
활성 case 의존성을 제거할 수 없습니다. 해제 이벤트는 추가 전용이며 별도 권한을 요구합니다.

### 용량과 실패 동작

Archive 실패는 purge를 중단하지만 PostgreSQL이 조용히 가득 차도록 두어서는 안 됩니다. 각
배포는 경고, 심각 및 hard 저장소 예산과 최대 purge backlog 및 변환 결과 지연을 설정합니다.
임계값을 넘으면 다음 순서로 대응합니다.

1. 저장소 압력과 예상 소진 시각을 보고합니다.
2. Archive와 checkpoint 우선순위를 높입니다.
3. 최신성 한도 안에서 필수적이지 않은 보강과 reconciliation 빈도를 낮춥니다.
4. 중요한 관측을 보존하면서 원본별 수집 예산을 적용합니다.
5. 근거를 더 이상 보존할 수 없으면 완전성에 의존하는 조회와 변경 작업을 보류합니다.

검증하지 않은 데이터를 삭제하거나 필수 감사 근거를 sampling하거나 압력을 낮추기 위해 완전한
graph를 보고하지 않습니다. 복구에는 성공한 archive 검증, 복원 sampling, partition purge 및
최신 변환 결과 증적이 필요합니다.

### 운영 완료 gate

고정된 배포 개정 하나가 다음 결과를 모두 입증한 경우에만 범위가 제한된 이력을 운영 완료로
판단합니다.

| Gate | 필요한 근거 |
|------|-------------|
| 결정론적 replay | 중복, 재정렬, 지연, 부분, 삭제, 재생성 및 재시작 사례가 같은 current 다이제스트를 생성합니다. |
| 제한된 증가 | 측정된 변경률에서 안정 상태 저장소, WAL, index 증가 및 purge backlog가 구성된 예산 안에 유지됩니다. |
| 안전한 압축 | Checkpoint 범위, archive 검증, 복원 sampling, 참조 고정 및 hold 평가가 통과하기 전에 partition을 purge하지 않습니다. |
| 이력 연속성 | Warm 이력은 직접 replay하고 더 오래된 이력은 명시적인 공백과 함께 principal 범위의 archive 경로로 복원합니다. |
| 실패 격리 | Archive, database, 프로바이더 및 scheduler 실패가 수락한 관측을 잃지 않고 최신성 또는 완전성을 낮춥니다. |
| Schema 진화 | N 및 N-1 reader가 보존된 관측을 replay하고 원본 및 변환된 다이제스트를 유지합니다. |
| 재해 복구 | Database 복원과 archive index 재구축이 같은 범위 및 변환 결과 watermark를 복구합니다. |
| 보안 및 privacy | Redaction, 암호화, key rotation, 접근 검토, residency, 삭제 및 legal-hold 근거가 배포 정책과 일치합니다. |

### Rollup 규칙

Rollup은 의미 정책에 따라 수행합니다. gauge, counter, 범주형 상태, 관계 변경, 근거 상태는
하나의 일반 집계 규칙을 공유하지 않습니다. 적격 속성 또는 metric은 허용되는 구간과 병합
가능한 통계를 선언합니다.

모든 rollup은 원본 수, 포함 구간, 누락 구간, 관측된 0, 충돌 수, 완전성, 원본 partition
digest, 집계 정책 수정본을 보존합니다. 백분위수는 병합 가능한 검토된 sketch를 사용하거나
사용 불가로 유지합니다. 개수와 합계가 없는 평균은 수락하지 않으며, 불완전한 원본 구간은
완전한 집계가 되지 않습니다.

### Archive와 purge

Archive partition은 변경 불가능하고 content-addressed입니다. 매니페스트는 포함된 원본
partition, 시간 범위, 객체 및 관계 수, schema와 ontology release, 암호화 및 압축 profile,
대상 등급, 생성 증적, 검증 결과를 기록합니다. 저장소에 배포 secret을 저장하지 않습니다.

Hot 또는 warm 삭제는 매니페스트 검증, 복원 sampling, 보존 및 법적 hold 평가, durable purge
증적 이후에만 적격합니다. Purge는 safe-to-retry입니다. 실패하면 원본 데이터를 유지하고
저장소 압력을 보고합니다. 이력을 조용히 축소하지 않습니다.

Hot 그래프는 archive index와 범위 요약을 유지하여 쿼리가 archive된 이력과 존재하지 않는
이력을 구분하도록 합니다. Archive 복원은 명시적이고 범위가 제한되며 principal 범위를
따릅니다. 일반 현재 상태 쿼리를 조용히 지연시키지 않습니다.

## 그래프 우선 조회와 실시간 보강


검증된 쿼리 계획은 근거 요구 사항과 최신성 예산을 포함합니다. 결정론적 refresh 정책은 그래프
근거를 다음 결과 중 하나로 축소합니다.

| 결과 | 동작 |
|------|------|
| `use_graph` | 현재의 완전한 그래프 근거로 실행합니다. |
| `refresh_then_query` | 범위가 제한된 공급자 조회를 한 번 수행하고 관측을 게시하며, deadline이 허용하면 reconciliation 결과를 조회합니다. |
| `use_live_evidence` | 이 답변에는 검증된 실시간 증적을 사용하고 비동기 변환 결과가 따라오게 합니다. |
| `query_archive` | 명시적으로 범위가 제한된 이력 partition을 검색하고 archive 계보를 보존합니다. |
| `hold` | 신원, 권한, 충돌 또는 누락된 근거 때문에 안전하게 제시할 수 있는 검증된 부분 집합이 없으면 운영 결론을 반환하지 않습니다. |

자연어와 모델 출력은 의미만 제안할 수 있습니다. Core는 그래프, archive, 공급자 I/O 전에
principal, 목적, 범위, ontology release, ObjectType, LinkType 방향, FunctionType, 제한,
refresh 결과를 검증합니다.

Resource ObjectSet receipt는 source generation 및 source completeness를 query truncation과
독립적으로 전달합니다. 결과 Resource가 0개여도 적용되므로 불완전한 coverage가 잘못된 부재
증명이 될 수 없습니다. Operator relationship projection은 current, stale, future-cutoff
evidence를 구분하고 공급자 configuration observation과 independently verified observation
receipt도 구분합니다.

읽기 전용 대화는 불완전한 원본을 설명하기 전에 검증된 행을 먼저 제시합니다. 빈 부분 결과에는 검증된 범위에서 일치하는 항목이 없다고 설명한 뒤 정확한 제한 사항과 복구 단계를 안내합니다. 부분 결과를 완전한 개수, 전체 부재 또는 현재 전체 인벤토리로 표현하지 않으며, 안전한 부분 집합이 없으면 판단을 보류합니다.

## 원본부터 저장소까지 구현 감사

OI-01은 각 단계의 정확한 코드 소유자, 런타임 또는 저장소 binding, 집중 테스트, 상태, 누락
binding을
[`config/continuous-operational-instance-graph-audit.json`](../../../config/continuous-operational-instance-graph-audit.json)에
기록합니다. Architecture checker는 단계 누락, 근거 경로 누락, 소유자가 없는 구현 작업,
정확한 공백을 명시하지 않은 열린 단계를 거부합니다. 정본 소유권은 이 설계에서 검증하고 구현 상태와
남은 작업은 연결된 전달 원장에서 검증합니다.

| 단계 | 상태 | 감사 결과 |
|------|------|-----------|
| 공급자 push ingress | implemented | Event Grid 쓰기와 삭제가 raw Event Hub에 도달하고 `_consume_resource_changes`가 정식 inventory 이벤트로 정규화합니다. |
| 재개 가능한 delta cursor | implemented | `forward_inventory_delta`는 final fence 이후에만 durable Activity Log cursor를 전진시킵니다. |
| 완전 reconciliation | implemented | `InventorySyncCoordinator.run`은 범위가 제한된 ARG 또는 ARM 관측을 준비하고 완전한 stream만 수락합니다. |
| 정규화된 observation ingress | implemented | `PostgresInventoryDeltaProjector.__call__`은 타입이 지정된 관측 의미를 검증하고 기존 overlay를 갱신하기 전에 Core 소유 추가 전용 관측 원장에 이중 기록합니다. |
| Snapshot promotion | implemented | `PostgresInventorySnapshotStore.promote`는 promotion lock 아래에서 활성 세대를 원자적으로 전진시킵니다. |
| Realtime overlay | implemented | PostgreSQL overlay 행은 유효 시각과 내용 신원에 따라 정규화된 관측을 replay하고, 선언된 속성 마스크만 병합하며, 관측하지 않은 snapshot 속성을 보존하고, 완전한 reconciliation 전에는 tombstone 후보를 대기 상태로 유지합니다. |
| 온톨로지 변환 결과 | implemented | `InventoryOntologyProjector.apply`는 인벤토리가 소유한 Resource 및 Link 하위 그래프의 단일 작성자입니다. 검토된 중첩 운영 상태 필드는 관측 메타데이터와 함께 상위 속성으로 올리며, 원장과 변환 결과 워터마크 및 대기 중인 tombstone은 각각 원본 완전성을 낮춥니다. |
| Topology history | implemented | `InventoryTopologyHistoryPublisher.publish`는 Core 소유 bitemporal PostgreSQL store 및 migration을 통해 완전 baseline을 추가합니다. |
| Graph-first query | implemented | 일반 exact-target 현재 상태 조회는 secured graph를 먼저 읽고 검증된 읽기 전용 부분 결과와 명시적인 안내를 제시하며, 안전한 부분 집합이 없으면 판단을 보류합니다. |
| 범위가 제한된 live read | implemented | 정확한 secured Resource 하나만 고정된 한도 아래 server-scoped provider read를 최대 한 번 실행할 수 있습니다. 더 넓거나 malformed 또는 unresolved 조회는 거절하거나 hold합니다. |
| Live evidence write-through | implemented | 검증된 live evidence는 속성 마스크 및 내용에 결속된 idempotency와 함께 정식 타입 지정 부분 overlay ingress에 들어가며 관측되지 않은 속성이나 관계를 삭제할 수 없습니다. |
| 적응형 일정 관리 | implemented | 검증된 source policy와 순수 reducer가 freshness, lag, demand, provider pressure, `Retry-After`, 남은 budget, concurrency, circuit-open 상태, recovery probe를 사용합니다. PostgreSQL은 durable due 상태를 제공하고 principal-safe health projection은 다음 bounded action을 노출합니다. |
| Retention 및 hold | implemented | Archive purge coordinator는 정확한 verification, restore sampling, retention 또는 legal hold 평가가 통과하기 전까지 삭제를 차단합니다. Append-only PostgreSQL receipt는 blocked, pending, failed, successful, retry 결과를 보존합니다. |
| 타입 지정 rollup | implemented | Fact별 policy가 gauge, counter, categorical state, relationship change, evidence health를 분리해 집계하면서 source와 generation 계보, bitemporal 범위, 누락 구간, 관측된 0, 충돌, 완전성, 병합 가능한 count와 sum을 보존합니다. Percentile은 unavailable로 유지합니다. |
| Archive lifecycle | implemented | Content-addressed 매니페스트, 비공개 Azure Blob writer, principal 범위의 검증된 reader, database gate 기반 source purger, 추가 전용 verification, restore, coverage, hold 및 purge 증적, 전용 고정 shadow Container Apps Job을 구현했습니다. 보호된 인증은 정확한 source attestation 검증을 위해 GitHub API와 registry 자격 증명을 분리해 연결합니다. OCI 검증은 workflow 자격 증명을 프로세스 내부에서 mode 0700의 일시적 Docker 구성 안의 mode 0600 파일로 렌더링하고 Docker CLI에 의존하지 않으며 종료할 때 자격 증명 디렉터리를 제거합니다. Job 해석, 정확한 OCI 출처 증명 검증, ACR 연결은 별도의 보호된 단계이며 검증된 저장소, 개정 번호, 다이제스트만 검증 경계를 넘습니다. 인증은 Terraform ACR 출력 또는 검증된 배포 Job 이미지를 Azure login host로 정규화하고 같은 digest를 다시 빌드하지 않고 명시적으로 가져올 수 있습니다. OI-12 연결은 인벤토리 Job, 이력 Job, 보관 URL, 리소스 그룹의 최상위 출력을 우선 사용합니다. 배포된 상태가 해당 출력보다 오래된 경우 한 번의 범위가 제한된 ARM 열거에서 `Microsoft.App/jobs`만 읽고 리소스를 최대 64개까지 허용하며, 검토된 인벤토리 런타임 계약과 이력 런타임 계약에 일치하는 컨테이너를 각각 정확히 하나 요구합니다. 하나의 fail-closed 동등성 조건식이 두 정확한 런타임에서 공급자가 관측한 그룹이 동일함을 증명해야 누락된 리소스 그룹을 채택합니다. 인벤토리 새로 고침은 검토된 실제 Job을 검증하고 정식 컨테이너 이미지만 바꾸면서 안정 시작 API의 `containers` 및 `initContainers` 필드만 mode 0600 요청에 넣습니다. 컨테이너 수준의 명령, 인자, 환경, 리소스, 시크릿 참조와 볼륨 mount는 보존합니다. 시작 schema가 Job 소유 볼륨을 허용하지 않으므로 구성된 볼륨은 Job에서 상속합니다. 명령과 환경을 교체하는 CLI 이미지 단축 경로는 사용하지 않습니다. 대기 중인 스냅샷을 복구할 때 타입 지정 관측 메타데이터가 없는 관계는 제외하고 `unverified_metadata` drop을 보존합니다. 나머지 검증된 스냅샷은 계속 복구하므로 이후 새로 고침 전체가 차단되지 않습니다. 보존한 상태 전이 하위 항목은 동등성 검증 전에 입력 batch의 digest 결속 순서로 복원합니다. 누락되거나 추가되거나 중복되거나 개별 검증에 실패한 항목은 계속 거부합니다. 보호된 측정은 각 스냅샷 전에 최대 120초 동안 활성 인벤토리와 온톨로지 변환 결과 세대가 수렴하기를 기다립니다. 타입이 지정된 세대 대기 조건만 다시 시도하고 그 밖의 오류는 안전하게 종료합니다. 프로바이더 실패 및 복구 측정은 현재 활성 세대의 원본과 관측 종류에서 발생한 실패만 선택한 뒤 실패 원본, 관측 종류, 범위와 리소스 종류가 정확히 일치하는 이후 성공 스냅샷을 요구합니다. 폐기한 원본은 현재 인스턴스 측정값을 제공하거나 억제할 수 없습니다. 비어 있지 않은 최상위 출력은 선택한 ARM 런타임과 일치해야 하며 Job 이름은 신원 근거로 사용되지 않습니다. 프로바이더 출력은 단계가 끝난 뒤 제거됩니다. 보호된 계획은 이전 archive data owner를 보존하고 저장소에 바인딩된 deploy UAMI를 별도 주소에 추가하며 제거는 별도의 파괴적 작업으로 유지합니다. |

보호된 증적 readback은 배포 실행기 VNet에 연결된 ops 소유의 Blob 비공개 DNS 영역에서
storage 계정 전용 record를 해석합니다. Workload 해석은 앱 소유 영역에 유지합니다. 이
분리는 공용 네트워크 접근이나 storage key 인증 권한을 부여하지 않습니다.

## 운영 상태 전이 원장

FDAI는 의미가 부여된 상태 변경을 Core 소유의 추가 전용 PostgreSQL 원장에 저장합니다.
Event Hubs는 관측을 전달하고 OpenTelemetry는 진단을 보고하며, 온톨로지는 다시 만들 수 있는
현재 상태 변환 결과로 유지됩니다. 이러한 표면은 상태 전이 원장을 대신하지 않습니다.

각 원자적 배치는 콘텐츠 주소가 지정된 상태 전이 0개 이상과 양의 커버리지 레코드 1개 이상을
포함합니다. 상태 전이는 `from_state`, `to_state`, 유효 시각, 기록 시각, 근거 기준 시점, 원본
신원과 개정, 생산자 버전, 최신성, 완전성, 충돌, 근거 참조를 결합합니다. 다시 전달된 멱등성
키는 콘텐츠가 같을 때만 변경 없는 처리로 끝납니다.

인벤토리 경로는 속성 수준 근거가 있는 운영 및 가용성 변경만 기록합니다. 프로비저닝은 같은
출처 정보가 생길 때까지 현재 상태로만 유지합니다. 모든 구간은 `initial_state_only` 또는
`snapshot_interval_only`이며, 완전한 스냅샷도 중간 전이 부재를 증명하지 못합니다. 정확히
보존된 워터마크만 해당 커버리지를 높일 수 있습니다.

## 관련 문서

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| 구현 상태 및 남은 작업 | [구현 원장](../../roadmap-implementation/architecture/continuous-operational-instance-graph.md) |
| 온톨로지 권한과 상태 lane | [FDAI 운영 온톨로지](operating-ontology-ko.md) |
| 런타임 topology와 서비스 경계 | [프로젝트 구조](project-structure-ko.md) |
| Semantic query planning | [온톨로지 쿼리 범위 구현 계획](../interfaces/ontology-query-coverage-implementation-plan-ko.md) |
| 지속형 semantic 검증 | [지속형 의미 보증](../interfaces/continuous-semantic-assurance-ko.md) |
| 관측 및 감지 전달 | [관찰 가능성 및 감지](../rules-and-detection/observability-and-detection-ko.md) |
