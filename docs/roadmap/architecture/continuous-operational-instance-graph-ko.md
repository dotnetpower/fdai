---
translation_of: continuous-operational-instance-graph.md
translation_source_sha: d8803b9f271b123c86d086d7ab710e1bcfc642fd
translation_revised: 2026-09-06
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
- **단일 작성자:** 수집기는 타입이 지정된 관측을 추가합니다. 온톨로지 인스턴스를 직접
  변경하지 않습니다. 하나의 변환 결과 소유자가 관측을 판정하고 현재 하위 그래프를 원자적으로
  전진시킵니다.
- **그래프 우선:** 일반 질문은 공급자 API보다 먼저 현재 운영 그래프를 읽습니다. 필요한
  근거가 누락되거나 오래되거나 불완전하거나 충돌하거나, 범위가 제한된 조회 정책에 따라
  명시적으로 요청된 경우에만 실시간 공급자 조회를 허용합니다.
- **안전한 보강:** 실시간 조회는 현재 답변을 지원할 수 있으며 같은 ingress를 통해 타입이
  지정된 관측을 게시합니다. 부분 조회는 완전한 세대를 대체하거나 관측하지 않은 객체 또는
  관계를 삭제할 수 없습니다.
- **시간과 출처:** 모든 사실은 유효 시간, 가능한 경우 이벤트 시간, 기록 시간, 근거 기준
  시점, 원본 신원, 원본 수정본, 완전성, 충돌, 최신성 정책을 유지합니다.
- **잘못된 부재 방지:** 누락 이벤트, 잘린 조회, cursor 지연, 열린 실시간 overlay, archive
  사용 불가는 명시적인 알 수 없음 또는 불완전한 근거로 유지합니다.
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

지속형은 끝나지 않는 프로세스가 아니라 수집에 항상 durable한 다음 작업이 있음을 뜻합니다.
이벤트 소비자는 활성 상태를 유지하고 safe-to-retry cursor 및 reconciliation 작업은 진행 상황을 저장합니다.

### 비공개 네트워크 변경 가속

비공개 배포 프로필은 내구성 있는 타임스탬프 및 변경 ID cursor로 Azure Resource Graph
`resourcechanges`를 폴링합니다. 범위가 제한된 각 페이지는 오래된 항목부터 정렬하고 경계에서
중복된 행은 멱등하게 처리하며, 수락된 모든 변경이 정식 관측 수신 경로에 들어간 뒤에만 cursor를
진행합니다. 생성 및 업데이트 행은 변경된 Resource ID만 대상으로 범위가 제한된 정확한 Resource
Graph 재조회를 실행합니다. 삭제 행은 확인되지 않은 tombstone이 되며 완전한 reconciliation이
부재를 입증할 때까지 기다립니다. 변경 페이지 또는 재조회가 부분적이면 cursor와 overlay를 모두
진행하지 않습니다.

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

backlog 또는 이벤트 지연이 증가하면 scheduler는 사용할 수 있는 예산을 더 자주 소비합니다.
그래프가 최신이고 변경량이 낮으면 최대 노후 목표 안에서 간격을 늘립니다. HTTP `429`와 공급자
throttling은 동시성을 줄이고 `Retry-After`를 따릅니다. 지속적인 사용 불가는 circuit을 열고
계속 재시도하는 대신 범위가 제한된 probe를 예약합니다.
더 최신의 실패 시도가 없으면 스케줄러는 활성 스냅샷 완료 후 경과 시간을 마지막 시도 후
경과 시간으로 사용합니다. 따라서 실패 타임스탬프가 없다는 이유만으로 변경 수요 또는 최대
노후 상태가 계속 연기되지 않습니다.
로컬 장기 실행 루프는 모든 원본이 실패한 상황을 명시적으로 기록하고 구성된 루프 간격 후에
다시 시도합니다. 일회성 예약 작업은 계속 실패하므로 조정기가 실패한 시도를 관측하고 통제할
수 있습니다.

구성은 배포 값을 제공합니다. 저장소 기본값과 테스트는 안전한 범위를 정의하며, 하나의 간격이
모든 tenant 또는 공급자 API에 적합하다고 주장하지 않습니다.

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
| `hold` | 대체 없이 사용 불가, 오래됨, 불완전함, 충돌, deadline 초과 근거를 반환합니다. |

자연어와 모델 출력은 의미만 제안할 수 있습니다. Core는 그래프, archive, 공급자 I/O 전에
principal, 목적, 범위, ontology release, ObjectType, LinkType 방향, FunctionType, 제한,
refresh 결과를 검증합니다.

Resource ObjectSet receipt는 source generation 및 source completeness를 query truncation과
독립적으로 전달합니다. 결과 Resource가 0개여도 적용되므로 불완전한 coverage가 잘못된 부재
증명이 될 수 없습니다. Operator relationship projection은 current, stale, future-cutoff
evidence를 구분하고 공급자 configuration observation과 independently verified observation
receipt도 구분합니다.

## 원본부터 저장소까지 구현 감사

OI-01은 각 단계의 정확한 코드 소유자, 런타임 또는 저장소 binding, 집중 테스트, 상태, 누락
binding을
[`config/continuous-operational-instance-graph-audit.json`](../../../config/continuous-operational-instance-graph-audit.json)에
기록합니다. Architecture checker는 단계 누락, 근거 경로 누락, 소유자가 없는 구현 작업,
정확한 공백을 명시하지 않은 열린 단계를 거부합니다.

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
| Graph-first query | implemented | 일반 exact-target 현재 상태 조회는 secured graph를 먼저 읽고 5개 결과 정책으로 freshness와 완전성을 축약하며 근거가 계속 부족하면 hold합니다. |
| 범위가 제한된 live read | implemented | 정확한 secured Resource 하나만 고정된 한도 아래 server-scoped provider read를 최대 한 번 실행할 수 있습니다. 더 넓거나 malformed 또는 unresolved 조회는 거절하거나 hold합니다. |
| Live evidence write-through | implemented | 검증된 live evidence는 속성 마스크 및 내용에 결속된 idempotency와 함께 정식 타입 지정 부분 overlay ingress에 들어가며 관측되지 않은 속성이나 관계를 삭제할 수 없습니다. |
| 적응형 일정 관리 | implemented | 검증된 source policy와 순수 reducer가 freshness, lag, demand, provider pressure, `Retry-After`, 남은 budget, concurrency, circuit-open 상태, recovery probe를 사용합니다. PostgreSQL은 durable due 상태를 제공하고 principal-safe health projection은 다음 bounded action을 노출합니다. |
| Retention 및 hold | implemented | Archive purge coordinator는 정확한 verification, restore sampling, retention 또는 legal hold 평가가 통과하기 전까지 삭제를 차단합니다. Append-only PostgreSQL receipt는 blocked, pending, failed, successful, retry 결과를 보존합니다. |
| 타입 지정 rollup | implemented | Fact별 policy가 gauge, counter, categorical state, relationship change, evidence health를 분리해 집계하면서 source와 generation 계보, bitemporal 범위, 누락 구간, 관측된 0, 충돌, 완전성, 병합 가능한 count와 sum을 보존합니다. Percentile은 unavailable로 유지합니다. |
| Archive lifecycle | implemented | Content-addressed 매니페스트, 비공개 Azure Blob writer, principal 범위의 검증된 reader, database gate 기반 source purger, 추가 전용 verification, restore, coverage, hold 및 purge 증적, 전용 고정 shadow Container Apps Job을 구현했습니다. 보호된 배포 및 certification 증적은 별도 운영 근거로 남습니다. |

## 구현 상태
### 구현 범위

| 영역 | 상태 | 근거 | 참고 |
|------|------|------|------|
| Push 이벤트와 durable delta overlay | implemented | `delivery/azure/activity_log.py`, 실시간 inventory projector와 집중 테스트 | 리소스 변경은 범위가 제한된 overlay를 업데이트할 수 있습니다. 배포 근거는 별도입니다. |
| 비공개 네트워크 변경 가속 | in-progress | `arg_resource_changes.py`, `inventory_change_acceleration.py`, 인벤토리 작업 구성, Operator 내구성 무효화 SSE, Console SSE 소비자 및 폴링 카운트다운, 집중 출처, 경로, 재현 및 Console 검사 | 범위가 제한된 구현을 로컬에서 구성했습니다. cursor나 완전성 권위를 변경하지 않고 change-feed 조정을 완전한 reconciliation CLI에서 분리했습니다. 최종 통합 검증은 남아 있습니다. 완전한 reconciliation만 관계 완전성 권위를 유지합니다. |
| 완전한 인벤토리 승격과 온톨로지 변환 결과 | implemented | `delivery/inventory_sync.py`, `runtime/inventory_ontology.py`, 집중 인벤토리 및 변환 결과 테스트 | 완전 세대가 소유된 하위 그래프를 원자적으로 대체합니다. 검토된 중첩 운영 상태 값은 Resource 관측 시각과 세대 메타데이터를 유지합니다. 기존 정기 주기는 목표 지속형 정책이 아닙니다. |
| 관계 세대 수렴 | implemented | `arm_inventory.py`, `postgres_inventory_snapshot.py`, `inventory_projection.py`, `inventory_ontology.py`, PostgreSQL source coverage, Operator/Console evidence projection, 집중 회귀 검사 | 검토된 parent가 일반 fallback을 shadow하고 snapshot과 ontology cardinality gate가 일치합니다. 분류된 non-edge는 complete coverage를 주장하지 않고 exact generation을 전진시키며 graph receipt는 generation, freshness, verification level, zero-result limitation을 보존합니다. |
| Kubernetes 워크로드 관측 | validated | `kubernetes_api_inventory.py`, Kubernetes 실제 및 영속 Event reader, rollout, Pod 복구 및 Pod 진단 FunctionType, lifecycle collector와 PostgreSQL store, 집중 인벤토리, Event, migration, 영속성, 플래너, 증적, 조립 및 런타임 검사, 인증된 Event API와 영속 cursor 증적 | UID에 근거한 세대는 허용 목록에 있는 rollout 상태를 보존합니다. `query.resource_event_history`는 불변 `uid`와 `cluster_ref`로 정확한 child 하나를 좁힐 수 있습니다. Lease 기반 bookmark watch는 `resourceVersion`을 불투명 값으로 취급하고 로컬 단조 cursor 진행과 타입 지정 관측을 원자적으로 append하며 expiry, authorization, source, retention 및 result-limit gap을 보고합니다. `query.kubernetes_pod_diagnosis`는 실제 로그 프로바이더가 연결된 경우에만 정확한 UID 하나를 범위가 제한된 수명 주기 및 로그 본문을 보존하지 않는 근거와 결합합니다. 내용 다이제스트, 개수, 시각, 출처 신원 및 명시적인 공백을 보존하고 인과 및 실행 권한을 false로 고정하며, 로그 행이 0개이면 `zero_records_unverified`로 유지합니다. 원시 Event message, 로그 본문, provider payload 및 ontology 쓰기는 제외합니다. 격리 validation database는 병합된 Core migration head에 도달했고 연속 실제 cycle 5개가 sequence 0에서 5까지 전진하며 약 60초의 완전한 coverage를 보존했습니다. 60초 zero-row 영속 읽기는 해당 구간을 관측한 뒤에만 complete였습니다. 이 로컬 증적은 배포 보존이나 Pod 원인 및 복구를 주장하지 않습니다. |
| 불변 Pod 교체 상관 분석 | in-progress | `kubernetes_pod_replacement_evidence.py`, `core/investigation/kubernetes_pod.py`, `delivery/pod_evidence_binding.py`, 검증된 수명 주기 보존, 집중 교체 축약기 및 CLI 분석기 경로 테스트 | 결정론적 축약기는 클러스터, 네임스페이스 및 루트 컨트롤러 UID를 통해 정확히 한 후보만 허용하며, 복구 시 최신 Deployment UID가 해당 루트 컨트롤러와 일치해야 합니다. 프로덕션 `KubernetesPodLifecycleAnalyzer`는 분석기 CLI 구성 루트를 통해 `default_analyzers`에 바인딩되며, 자유 형식 메타데이터가 아니라 정규 교체 축약기와 복구 축약기에서만 근거 완전성과 복구 완료를 도출해 타입 지정 발견 사항 평가로 전달합니다. 범위가 제한된 시나리오는 실제 CLI 진입점을 실행해 같은 UID의 컨테이너 재시작과 서로 다른 UID의 Pod 교체를 구분하고 감지 지연 시간, 근거 완전성, 브로커 게시 및 복구 완료를 하나의 발견 사항 증적으로 결합합니다. Pod 수명 주기 근거는 `FDAI_POD_LIFECYCLE_EVIDENCE_JSON` 구성 이음새를 통해서만 이 분석기에 도달하며, 실제 Kubernetes 수명 주기 수집기는 바인딩되어 있지 않으므로 바인딩되지 않았거나 형식이 잘못된 근거는 Pod 대상을 가정하지 않고 지원되지 않음으로 남깁니다. 영속 수명 주기 수집은 이름 상관 분석이나 실행 권한 없이 필요한 UID 및 종료 근거를 제공합니다. 보존된 증적은 Pod 수명 주기 프로젝션으로 축약되며, 인증된 Operator API `/detection-readiness` 계열과 기존 Console 경로는 이를 현재 상태, 실패 이력, 복구, 근거 공백이라는 네 가지 답으로 분리해 보고합니다. 자체 최신성 예산을 넘긴 프로젝션은 현재 상태와 복구를 다시 진술하지 않고 철회하며, 누락되었거나 형식이 잘못되었거나 상충하거나 원인을 주장하거나 권한을 주장하거나 복구가 독립 검증되지 않은 행이 하나라도 있으면 이력을 줄이는 대신 명시된 사유와 함께 해당 구획을 사용 불가로 표시합니다. 이 표면은 실행 제어를 제공하지 않습니다. 인증된 실제 삭제 및 재생성 시나리오는 이슈 #295의 범위 밖인 [이슈 #291](https://github.com/dotnetpower/fdai/issues/291)에 남아 있습니다. |
| Bitemporal topology 이력 | implemented | `core/ontology_platform/topology_history.py`, PostgreSQL topology 이력 adapter와 집중 테스트 | 현재 production 보존, rollup, archive, 복원 근거는 열려 있습니다. |
| 적응형 지속 일정 관리 | implemented | `inventory_source_policy.py`, `inventory_scheduler.py`, PostgreSQL 조정 상태, 수집 상태, 분석기 틱 CLI와 로컬 VS Code 작업, 영속 게시 원장 및 집중 수집 검사 | 출처 정책과 결정론적 일정 관리가 구현됐습니다. 배포된 Container Apps Job과 로컬 백그라운드 작업은 같은 one-shot 분석기 논리와 게시 전 PostgreSQL 청구를 사용합니다. 완료된 브로커 증적은 프로세스가 다시 시작되어도 같은 구간의 발견 사항이 다시 게시되지 않도록 억제합니다. 활성 청구가 있으면 틱이 실패하고, 아직 전송하지 않은 오래된 청구는 범위가 제한된 임대 기간 뒤 다시 획득할 수 있습니다. 실행기는 브로커를 호출하기 전에 전송 의도를 영속적으로 기록하므로, 레코드가 확실히 전송되지 않았다고 버스가 증명할 때만 청구를 해제하고 그 밖의 모든 게시 실패는 청구를 불확실 상태로 유지해 재시도 전에 조정을 요구합니다. 만료된 전송 임대와 증적을 기록하지 못한 브로커 확인은 모두 다시 게시하지 않고 불확실한 상태로 남습니다. 청구 저장소 읽기나 쓰기가 실패하면 해당 발견 사항은 게시하지 않고 안전하게 실패합니다. 준비 상태는 일정 관리, 대상 검색, 메트릭 접근, 이벤트 게시 및 구성된 Log Analytics와 Prometheus 지연 시간 하한을 분리합니다. 배포 운영 측정은 별도 검증 근거로 남습니다. |
| 타입 지정 rollup | implemented | `semantic_rollup*.py`, `inventory_rollup.py`, 집중 integration 검사 | 사실별 집계와 범위 계약은 구현되고 로컬에서 검증됐습니다. |
| 영속 정규화 관측 이력 | implemented | `inventory_observation.py`, `operational_history_lifecycle.py`, `postgres_inventory_observation*.py`, `postgres_observation_lifecycle.py`, `20260907_core_oi16_certification_support.py`까지의 Core migration, 타입 지정 replay 및 원본 범위 검사 | OI-13과 OI-14는 정확한 객체 및 관계 관측, 수명 인스턴스 신원, 지연 correction partition, 결정론적 correction 종료, case 또는 legal-hold pin을 보존합니다. 대기 중인 correction은 원본 완전성을 낮추며 보정된 base partition은 purge 전에 더 최신 checkpoint를 요구합니다. |
| 운영 archive 및 제한된 이력 purge | in-progress | `operational_history_archive.py`, Azure Blob artifact adapter, PostgreSQL 수명 주기 store 및 database purge gate, 배포 정책 loader, 수명 주기 planner와 고정 schedule, OI-16 synthetic campaign runner, 격리된 synthetic retention fact family와 추가 전용 recovery rehearsal table, 보호된 certification workflow와 증적 writer, 집중 검사, 보호 apply 증적, 성공한 shadow Job 실행 | OI-15는 실행기 권한이 없는 inventory identity와 비공개 versioned storage를 사용하는 shadow mode로 배포됐습니다. OI-16 구현은 개발 전용 synthetic campaign을 정확한 CI, runtime image attestation, OI-15 apply 증적, bot 소유 요청 및 별도 Environment 승인에 결속합니다. 정확한 `synthetic/oi16-certification/` 범위만 full observation을 purge가 허용된 synthetic fact family에 매핑하며, 검증된 campaign runner가 명시적으로 활성화하지 않으면 공유 journal은 이 매핑을 비활성 상태로 유지합니다. 일반 observation family는 기존 정책을 유지합니다. Database recovery는 archive된 synthetic record를 별도의 추가 전용 table로 복원하고 내용 digest를 검증한 뒤 archive coverage를 다시 구성합니다. 저장된 coverage 증적은 전역 관점에서 불완전 상태를 유지하고 별도 검사는 archive된 모든 synthetic partition의 완전한 coverage를 요구합니다. 13개 시나리오가 모두 통과하지 않으면 certification 증적을 저장하지 않습니다. 보호된 campaign은 아직 실행하지 않았으므로 OI-16은 열려 있으며 운영 검증되지 않았습니다. |
| 그래프 우선 조건부 실시간 보강 | implemented | `graph_evidence_refresh.py`, `graph_query_refresh.py`, `inventory_live_evidence.py`, runtime 의미 조립, 부분 overlay 영속성, 집중 테스트 | Exact-target 현재 상태 조립은 action authority 없이 graph-first 평가, bounded live read 1회, canonical write-through, 재조회 및 fail-closed hold를 종단으로 연결합니다. 최신성을 요구하는 Resource 결과는 반환된 모든 Resource가 완전한 state-fact metadata를 가질 때만 complete입니다. |
| 운영 인스턴스 semantic 정확성 | implemented | `operational_instance_competency.py`, 집중 이중 언어 action-draft routing 검사, 타입 지정 no-authority 증적 | 대표 typed competency와 OI-11 이중 언어 positive 및 negative 분류 검사가 답변 text 또는 keyword routing 없이 통과합니다. 전체 corpus 및 예약 검증은 [지속형 의미 보증](../interfaces/continuous-semantic-assurance-ko.md)이 소유합니다. |
| Runtime-call 근거 binding | implemented | `runtime_calls.yaml`, `runtime_call_projection.py`, `runtime_call_telemetry.py`, `delivery/azure/runtime_call_telemetry.py`, `runtime_call_inventory.py`, `inventory_projection.py`, inventory single-writer 및 집중 endpoint 검사 | 인증된 producer는 정확한 envelope identity를 독립된 credential lineage에 결속합니다. Azure query는 두 runtime table을 모두 요구하고 unavailable, redacted, malformed row coverage를 보존합니다. 부분 candidate가 하나라도 있으면 batch는 incomplete입니다. 검토된 `runtime_calls` LinkType을 projection contract에 등록하여 verified endpoint 방향과 Resource cardinality가 current 및 historical projection에서 유지됩니다. 인증된 runtime 근거는 열려 있습니다. |
| Authorization 및 PostgreSQL role 근거 | implemented | `postgres_role_evidence.py`, `arg_relationships.py`, 집중 principal redaction 및 authorization scope 검사 | Database role은 content-addressed reference를 사용하는 별도의 principal-safe projection으로 유지되며 Resource 또는 Link 형태를 만들지 않습니다. 모델링되지 않은 role-assignment child scope는 `authorization_child_scope_unmodeled`를 보존하고 추론된 edge가 되지 않습니다. |
| 운영자 인스턴스 탐색 | validated | `instance_explorer.py`, `postgres_family_store.py`, Operator 실시간 overlay 읽기 migration, `ontology-instance-graph*.ts*`, 집중 Operator 및 Console 검사, 인증된 표준 port 근거 | 읽기 전용 Console은 Resource Group을 transit hub로 사용하지 않고 깊이 8, Resource 200개, link 1,600개로 제한된 전체 응답을 검사와 맥락에 보존합니다. 기존 Instances canvas는 엄격한 왼쪽에서 오른쪽(`LR`) 좌표 계약을 사용합니다. 양방향 link와 범위가 제한된 cycle에서도 저장된 source occurrence를 target occurrence 왼쪽에 배치하며 저장 edge를 뒤집지 않습니다. 들어오는 occurrence는 선택한 Resource 왼쪽, 나가는 occurrence는 오른쪽에 유지합니다. 의미 column은 288px 간격을 사용합니다. 운영자는 일반 마우스 휠로 10%부터 180%까지 확대 또는 축소하고, 기본 전체 화면으로 전환하며, 빈 canvas를 drag해 pan할 수 있습니다. Node 좌표와 node 선택 동작은 고정됩니다. `contains`는 solid hierarchy line, `attached_to`는 dashed line, 양방향 `peered_with`는 dotted line입니다. Root 직접 containment와 최대 3개의 ancestor edge가 Resource Group, VNet, Subnet hierarchy를 복원하고, Resource Group과 Subscription은 표시되지만 transit 맥락으로 사용되지 않습니다. 정확한 AKS node Resource Group 근거는 AKS에서 VMSS로 향하는 edge를 만들지 않고 해당 분기 안의 hierarchy를 추가합니다. 비순환인 같은 방향 node는 가장 긴 predecessor rank를 사용하고 양방향 또는 cycle edge만 occurrence를 복제합니다. 정확히 검토된 gateway, load balancer, AKS outbound mapping만 검증된 traffic 의미를 추가할 수 있고 나머지 관계는 정직한 graph-direction label을 유지합니다. Inspector는 직접 incoming, 직접 outgoing, 검증된 ingress, 검증된 egress, access, containment, 연결 path segment를 mapping 근거와 함께 분리합니다. Azure Activity Log, Resource Health, runtime call graph는 명시적으로 사용할 수 없는 상태를 유지합니다. |
| 확장 가능 Resource 용량 | validated | `instance_explorer.py`, `ontology-instance-graph.tsx`, `ontology-instances-inspector.tsx`, 집중 Operator 및 Console 검사, 인증된 표준 포트 근거 | AgentPool과 VMSS 카드는 최근 커밋된 프로바이더 용량을 각각 노드 수와 인스턴스 수로 표시합니다. 값이 없으면 0으로 바꾸지 않으며 NodePool 용량으로 Kubernetes Node 준비 상태를 주장하지 않습니다. |
| 애플리케이션 중심 공급자 관계 | in-progress | `azure-arg-v1.yaml`, ARG와 범위가 제한된 ARM child 수집, Kubernetes API pre-promotion enrichment, 완전 세대 검증, endpoint closure, snapshot 분류 metadata, 집중 Core/Operator/Console 검사, Terraform service-root 검사, 인증된 `5273` 근거 | 검토된 mapping 84개가 정확한 containment, identity, authorization, registry, observability, network, ingress, 구성된 data-service reference, Private DNS closure, AKS AgentPool 및 Kubernetes 런타임 토폴로지를 처리합니다. Azure 중첩 child는 검토된 parent 또는 root 해석을 사용합니다. Exact TLS, workload-identity 및 cluster binding이 구성되면 UID에 근거한 Kubernetes 객체와 독립적으로 검증된 링크가 원자적 승격 전에 같은 세대에 들어갑니다. Read-only identity는 request 시점에 수명이 짧은 token을 취득하며 static Kubernetes token은 Terraform에 들어가지 않습니다. 기존 로컬 Azure 근거는 변경되지 않았으며 실제 운영 Kubernetes 증적을 주장하지 않습니다. |
| 원본부터 저장소까지 구현 감사 | implemented | `config/continuous-operational-instance-graph-audit.json`, `check-continuous-operational-instance-graph-audit.py`, 집중 감사 테스트(`3 passed`) | OI-01은 runtime validation을 주장하지 않고 16개 단계의 정확한 owner, binding, 집중 테스트, 상태, 누락 binding을 고정합니다. |

### 구현 이력
| 날짜 | 상태 | 변경 | 근거 | 남은 작업 |
|------|------|------|------|-----------|
| 2026-09-05 | implemented | 검토된 중첩 운영 상태 값을 ARG hydration과 인벤토리 소유 온톨로지 변환 결과까지 보존하고, Dashboard 상태 조회가 커밋된 온톨로지 세대와 일치하도록 검사했습니다. | `current change`, 집중 Core 변환 결과, ARG, Operator 상태 페이지 및 Dashboard 검사가 통과했습니다. | 실제 배포 준비를 주장하기 전에 인증된 운영자 화면 근거를 보존합니다. |
| 2026-09-05 | implemented | 실패 시 안전하게 중단하는 OI-16 보호 certification campaign을 추가했습니다. 개발 전용 runner는 범위가 제한된 synthetic 근거를 생성하고 평가하며, 독립적으로 관측한 Azure PostgreSQL 재시작 전후로 실행을 나눕니다. 단계별 근거는 principal 범위의 비공개 Blob storage에 저장합니다. 안전한 synthetic purge는 dry-run, 영향 범위 제한, 대상 lock, 안정적인 멱등성, 2단계 감사, rollback 및 독립 효과 검사가 모두 충족되어야 허용합니다. 보호 workflow는 bot 소유 요청과 별도 Environment 승인을 요구하며 정확한 source revision, 성공한 required CI run, 일치하는 attested runtime image, OI-15 배포 revision, apply run 및 apply-receipt artifact digest를 결속합니다. 필수 시나리오가 모두 통과한 경우에만 증적 저장과 비공개 sanitized 최종 artifact 생성을 진행합니다. | `current change`, certification model, CLI, campaign runner와 probe, phase store, 보호된 요청 및 campaign workflow, audit와 design route, 집중 model, CLI, campaign, workflow, identity 및 CI contract 검사 | 정확한 revision을 commit하고 push한 뒤 required CI와 runtime image attestation을 확보합니다. zero-destroy 보호 plan을 검토하고 bot 소유 요청과 human Environment 승인을 통해 apply한 다음 실제 시나리오 13개를 모두 실행합니다. Campaign이 통과하기 전까지 `operationally_validated=false`를 유지하고 certification 증적을 append하지 않으며 OI-16과 이슈 #262를 열어 둡니다. |
| 2026-09-05 | validated | OI-15 runtime 조립을 배포하고 실행했습니다. 독립 target Container Apps Job은 실행기 권한이 없는 inventory identity, versionless Key Vault DSN 참조, 비공개 versioned Blob 저장소 및 고정 shadow 명령을 사용합니다. 특수 exact apply는 bot-owned이므로 maintainer가 별도 Environment approver로 남습니다. | Revision `c209b0896`, `3bef1a800`, `69bbdf6c1`, required CI `33951293573`, runtime supply chain `33948715715`, plan `33951584532` (`8 add / 0 change / 0 destroy`), bot 요청 `33951765704`, apply `33951784309`, apply receipt artifact digest `sha256:3fe1b7d77ed4511c9e88283bae9798a8e74e2c79fc502e234fe36477d736cade`, 배포 Job 계약 검증, `2026-09-05T07:16:06Z`부터 `2026-09-05T07:16:43Z`까지 성공한 shadow 실행 | OI-16은 모든 필수 운영 시나리오가 독립 근거를 보존할 때까지 열려 있습니다. 이 shadow 실행은 archive restore, 안전한 purge, schema replay, database recovery/restart 또는 outage 동작을 입증하지 않습니다. |
| 2026-09-05 | implemented | OI-15 runtime 조립을 완료했습니다. 전용 Container Apps Job은 실행기 권한이 없는 inventory identity, Core database secret, 비공개 versioned Blob 저장소, 범위가 제한된 partition 선택, append-only 수명 주기 이벤트, checkpoint, archive 쓰기 및 읽기 검증, restore sampling, hold, 저장소 압력 보고 및 database purge gate를 사용합니다. 예약 실행은 shadow-only이며 enforce는 외부 증적을 요구하고 purge할 수 없습니다. Certify는 database gate를 실행하기 전에 외부 증적을 요구합니다. | `current change`, 수명 주기 runner와 PostgreSQL repository, 전용 storage/private endpoint/Job Terraform, 보호된 bounded-plan 입력 및 집중 runner, workflow, CLI, Terraform 검사 | 정확한 보호 계획을 적용하고 성공한 shadow Job 증적을 보존한 뒤 OI-16 certification을 실행합니다. |
| 2026-09-05 | validated | 최근 커밋된 AKS AgentPool 및 VMSS 용량을 실행 권한이 없는 인스턴스 응답에 변환하고 그래프와 Inspector에서 유형별 라벨로 표시했습니다. 지원되지 않거나 형식이 잘못된 용량은 표시하지 않으며 Console 디코더는 지원되지 않는 Resource 유형의 용량을 거부합니다. | `current change`; 집중 Operator 검사 10개와 집중 Console 검사 102개, Ruff, strict mypy, Console 타입 검사 및 프로덕션 빌드가 통과했습니다. 인증된 그래프와 Inspector는 활성 스냅샷의 `nodepool1=2` 및 VMSS 용량 `2`와 일치했습니다. | 이후 운영자 확장 변경에서 새로운 지연 시간 증적을 보존합니다. 정확한 Kubernetes Node 수와 준비 상태는 런타임 인벤토리를 구성할 때까지 사용할 수 없습니다. |
| 2026-09-05 | implemented | 운영자가 실행한 첫 AKS 시작 관측을 하드닝했습니다. 이제 SSE 재현은 CORS를 통해 `Last-Event-ID`를 허용하고, 현재 `Resources` 행이 이전 상태를 유지할 때 Resource Graph 변경 hydration은 권위 있는 변경 레코드에서 허용 목록의 운영 상태 변경을 적용합니다. | `current change`, 집중 ARG 검사 39개와 Operator CORS 검사 2개가 통과했습니다. 관측된 전환은 약 5분 뒤 VM 및 NIC 그래프 분기를 추가하고 약 10분 뒤 선택한 클러스터를 `Stopped`에서 `Running`으로 변경했습니다. SSE는 연결 상태를 유지하고 그래프를 자동으로 다시 읽었습니다. | 이번 첫 실행에 있던 두 결함 없이 보정된 변경 레코드 상태 병합 시간을 측정하도록 중지 또는 시작 전환을 한 번 더 실행합니다. |
| 2026-09-05 | implemented | 비공개 네트워크 변경 가속기의 동기화 검증과 로컬 런타임 probe를 완료했습니다. 실제 ARG probe에서 중첩 `properties.*` 필드 변환과 재개 조건의 지원되지 않는 직접 문자열 관계 비교를 찾아 수정했습니다. 내구성 SSE는 `200 text/event-stream`을 반환하고 권위 있는 선택 인스턴스 재조회를 즉시 실행했습니다. | `current change`, 동기화된 backend 검사 160개, Console 검사 112개, Ruff, strict mypy, Console typecheck 및 프로덕션 빌드가 통과했습니다. 로컬 ARG probe는 초기 구간에서 `published=3`, 내구성 cursor 이후 `published=0`을 반환했으며 지속 인벤토리 루프는 변경 피드 사용 불가 상태를 보고하지 않았습니다. | 운영자가 Azure Resource 상태 하나를 변경하고 프로바이더 변경부터 화면 반영까지 걸린 시간을 측정해 보존합니다. |
| 2026-09-05 | in-progress | 비공개 네트워크 Resource Graph 변경 가속기, payload 없는 내구성 인벤토리 무효화 SSE, 표시되는 15초 fallback 카운트다운이 있는 Console 즉시 재검증을 추가했습니다. | `current change`, 요청된 중지 전에 출처 어댑터 검사 38개, Operator SSE 검사 140개, Console SSE 및 카운트다운 검사 112개가 통과했습니다. | 공유 main checkout을 동기화하고, 통합 집중 검사와 깨끗한 빌드 검증을 실행하고, 통합 차이를 비평하고, 로컬 상태 전환 시간 증적을 보존합니다. |
| 2026-09-05 | implemented | Tombstone을 명시적으로 타입 지정한 뒤 sparse 속성의 부정 계약을 명확히 했습니다. `properties_complete=false`인 삭제는 `observation_kind=partial`을 명시하지 않으면 tombstone입니다. 부정 테스트는 이제 데이터베이스 접근 전에 허용되지 않는 partial-delete 조합을 검사합니다. | `current change`, `test_inventory_live_evidence.py`, 집중 partial 및 tombstone 의미 검사 5개, Ruff, formatting 통과 | 보호된 배포 plan 전에 정확한 보정 리비전의 필수 CI를 다시 실행합니다. |
| 2026-09-05 | implemented | 관측 원장 도입 이전의 활성 snapshot에도 migration-safe shadow 이중 기록을 적용하도록 복구했습니다. 변환기는 누락된 legacy 범위를 단일 활성 범위에서만 해석하고, sparse 객체와 관계를 결속하기 전에 결정론적 기준 수명 인스턴스를 생성하며, tombstone 우선 순서를 단조롭게 유지하고, root rollback 검사를 서비스 소유 migration 데이터베이스와 격리합니다. | `current change`, PostgreSQL delta 및 수명 주기 어댑터, CI 데이터베이스 순서, migration inventory 및 작업 흐름 계약. 새 pgvector 검사에서 root 테스트 13개와 service-only skip 25개 이후 서비스 소유 테스트 31개가 통과했고, 작업 흐름 및 migration 계약 123개, 집중 OI 및 배포 CLI 검사 187개, Ruff, formatting, strict mypy가 통과했습니다. | 보호된 plan과 apply, 전용 OI-15 runtime Job, OI-16 운영 certification 증적은 계속 열려 있습니다. |
| 2026-09-05 | in-progress | OI-14와 OI-15 및 OI-16의 로컬 코드 표면을 구현했습니다. 관측 ingress는 이제 Resource와 관계 endpoint를 정확한 수명 인스턴스와 시간 및 범위 partition에 결속합니다. 지연 관측은 correction partition을 열고 원본 완전성을 낮추며, content-addressed 온톨로지 replay 증적 이후에만 종료됩니다. Case, investigation, approval, execution, rollback, legal-hold 및 replay-lease pin은 purge를 차단합니다. 배포 policy load, 저장소 압력 저하, 검증된 principal 범위 Blob archive 접근, database gate 기반 source purge, N/N-1 schema replay, database recovery 비교, 고정 shadow schedule 및 고정 개정 certification을 구현했습니다. | `current change`, 수명 주기 및 certification 타입, Core migration `20260906_core_operational_history_lifecycle.py`, PostgreSQL 및 Azure adapter, inventory journal 통합, 원본 완전성 축약, certification CLI, 집중 검사 322개 통과, Ruff, formatting 및 strict mypy 통과 | 고정 수명 주기 schedule을 전용 runtime Job으로 조립한 뒤 green 개정을 commit하고 push하여 보호된 운영 certification을 실행합니다. 그 증적이 생길 때까지 OI-15와 OI-16은 열려 있으며 배포된 제한 증가 또는 recovery를 주장하지 않습니다. |
| 2026-09-05 | implemented | OI-13과 선행 정확성 결함을 완료했습니다. Event Grid 변경은 sparse 변경 힌트로 처리하고, 작업 상태는 리소스 상태가 아니라 원장 metadata로 유지하며, 속성 마스크는 tag, SKU 및 관측하지 않은 값을 보존하고, 확인되지 않은 tombstone은 부재를 입증할 수 없습니다. Core 소유 원장은 기존 overlay를 조회 경로로 유지하면서 전체 snapshot과 delta 객체 또는 관계 관측을 이중 기록합니다. 내용에 결속된 replay는 중복, 재정렬, 오래된 이벤트 및 재시작 전달에서도 결정론적으로 동작합니다. 원장 지연과 대기 중인 tombstone은 온톨로지 원본 완전성을 낮춥니다. | `current change`, 정규화 관측 타입, PostgreSQL 원장 및 migration, delta 및 snapshot 이중 기록, 온톨로지 watermark 증적, 원본 범위 축약, 감사 레지스트리 및 집중 테스트. 최종 OI-13 집중 검사 219개와 Ruff, strict mypy, continuous-graph audit 및 design-route 검사가 통과했습니다. | OI-14는 리소스 수명 인스턴스 신원, 관계 보정 범위, correction partition, 활성 case 또는 legal-hold 고정을 위해 열려 있습니다. OI-15와 OI-16도 열려 있습니다. |
| 2026-09-05 | in-progress | 원본부터 저장소까지 재검토한 뒤 제한된 이력 설계를 확장하고 archive lifecycle 상태를 구성요소 완료에서 운영 binding이 열린 상태로 수정했습니다. 개정된 계약은 정규화 관측, 속성 마스크, 리소스 수명 인스턴스, 관계 이력, partition 상태, 검증된 checkpoint, 지연 보정, 활성 case 고정, 저장소 압력, schema 진화 및 재해 복구를 다룹니다. | `current change`, 이 설계 소유자 및 `config/continuous-operational-instance-graph-audit.json`, continuous-graph audit, roadmap 추적, 번역, 문장 부호 및 문서 크기 검사 | 아래 OI-13부터 OI-16까지 구현하고 검증합니다. 이 전환에서는 runtime 동작을 변경하지 않았습니다. |
| 2026-08-31 | implemented | 이슈 #295의 결정론적 분석기 동등성 경계를 완료했습니다. 분석기 이벤트 ID와 구간 키는 안정적이며, 토큰 소유 PostgreSQL 청구는 완료된 브로커 증적이 있는 발견 사항만 억제합니다. 활성 청구가 있으면 안전하게 실패하고 오래된 청구를 다시 획득할 수 있으며 게시 실패 시 청구를 해제합니다. 범위가 제한된 분석기 경로 시나리오는 같은 UID의 재시작과 서로 다른 UID의 교체를 구분하고 감지 지연 시간, 근거 완전성, 게시 및 복구 완료를 하나의 증적으로 만듭니다. | `current change`, 분석기 실행기, CLI, PostgreSQL 게시 원장, Pod 교체 분석기 경로 시나리오 및 집중 검사 85개 통과, Ruff 통과 | 배포 런타임 또는 Azure 증적을 만들지 않았습니다. 보호된 배포 인증은 이슈 #295 외부에 남아 있습니다. |
| 2026-08-31 | implemented | 이슈 #291의 보고 표면을 완성했습니다. 분석기 증적이 그동안 빠져 있던 대상, 종류, 발생 시각, 복구 상태를 담고, Core 축약기가 보존된 증적을 한정된 Pod 수명 주기 프로젝션으로 바꾸며, 인증된 Operator API `/detection-readiness` 계열과 기존 Console 경로가 같은 엔드포인트에서 현재 상태, 실패 이력, 복구, 근거 공백을 네 가지 답으로 분리해 보고합니다. 탐지는 원인을 진술하지 않고 실행 권한도 갖지 않습니다. 누락, 오래됨, 불완전, 상충 근거는 닫힘으로 실패합니다. 최신성 예산을 넘긴 프로젝션은 이력을 유지한 채 현재 상태와 복구를 철회하고 오래된 근거 공백을 보고하며, 결함이 있는 행 하나는 보존된 이력을 조용히 줄이는 대신 명시된 사유와 함께 구획 전체를 사용 불가로 만듭니다. | `current change`, 축약기, 기록기, Operator 프로젝션, 런타임 판독기, 분석기 tick에 걸친 집중 Python 테스트 122건 통과. 여기에는 하나의 리비전에 고정된 서비스 간 종단 간 증명 8건이 포함되며, 실제 분석기, 원장, 기록기, Operator 판독기를 구동해 동일 UID 재시작, 다른 UID 교체, 누락 및 만료된 근거, 중복 억제, 불확실 후 조정된 전달, 독립 검증된 복구를 확인하고 Console 계약을 픽스처로 고정합니다. Console 단위 테스트 2,204건, strict 타입 검사, 프로덕션 빌드가 통과했고, 구성된 strict mypy 게이트는 기존 7건 기준선 대비 오류를 추가하지 않았습니다. 1440x900, 993x641, 390x844 브라우저 증적에서 네 가지 분리된 답, 가로 넘침 0, 키보드로 도달 가능한 44 px 펼침 요소, 원인 및 권한 주장 없음을 확인했습니다. | 탐지는 여전히 `FDAI_POD_LIFECYCLE_EVIDENCE_JSON` 구성 이음새로만 Pod 수명 주기 근거를 읽으므로, 인증된 실제 삭제 및 재생성 시나리오와 이슈 #292의 타입이 지정된 재개 가능 수집은 열려 있습니다. |
| 2026-08-31 | implemented | 이슈 #295의 검토 지적 두 건을 수정했습니다. 모호한 브로커 실패는 더 이상 게시 청구를 해제하지 않습니다. 실행기는 게시 전에 전송 의도를 영속적으로 기록하고, 레코드가 확실히 전송되지 않았다는 버스 증명이 있을 때만 청구를 해제하며, 그 외에는 조정이 끝날 때까지 청구를 불확실 상태로 유지하므로 증적을 기록하지 못한 확인된 게시도 임대 만료 뒤 다시 게시되지 않습니다. 타입 지정 Kubernetes Pod 수명 주기 분석기와 독립적인 복구 근거는 프로덕션 분석기 구성에 바인딩되며, 증적은 자유 형식 메타데이터가 아니라 정규 교체 축약기와 복구 축약기에서 근거 완전성과 복구 완료를 도출합니다. | `current change`, `shared/providers/event_bus.py` 게시 계약, `delivery/azure/event_bus.py`, `delivery/analyzer_tick.py`, `delivery/persistence/postgres_analyzer_publication.py`, `core/investigation/kubernetes_pod.py`, `delivery/pod_evidence_binding.py`, CLI 기반 Pod 시나리오 및 집중 검사 | 조정기 구현은 포함되지 않으므로 불확실한 청구는 운영자가 조정기를 바인딩할 때까지 조정 대기 상태로 남습니다. 실제 Kubernetes Pod 수명 주기 수집기는 없으며 배포 런타임 증적도 만들지 않았습니다. |
| 2026-08-31 | implemented | 이슈 #295의 결정론적 분석기 동등성 경계를 완료했습니다. 분석기 이벤트 ID와 구간 키는 안정적이며, 토큰 소유 PostgreSQL 청구는 완료된 브로커 증적이 있는 발견 사항만 억제합니다. 활성 청구가 있으면 안전하게 실패하고, 청구 저장소 읽기나 쓰기가 실패하면 해당 발견 사항을 게시하지 않고 안전하게 실패하며, 오래된 청구를 다시 획득할 수 있고 게시 실패 시 청구를 해제합니다. 범위가 제한된 시나리오는 로컬 분석기 루프를 분석기 경로 위에서 실행해 같은 UID의 재시작과 서로 다른 UID의 교체를 구분하고 감지 지연 시간, 근거 완전성, 게시 및 복구 완료를 하나의 증적으로 만듭니다. | `current change`, 분석기 실행기, CLI 로컬 루프, PostgreSQL 게시 원장, Pod 교체 분석기 경로 시나리오 및 집중 검사 116개 통과, Ruff 통과 | 배포 런타임 또는 Azure 증적을 만들지 않았습니다. 보호된 배포 인증은 이슈 #295 외부에 남아 있습니다. |
| 2026-08-28 | implemented | `graph_at`의 bitemporal 토폴로지 재생 완전성과 다이제스트 무결성을 강화했습니다. 선택된 모든 리비전 묶음에 비어 있지 않은 출처 증적 다이제스트가 있어야 완전하며, 재생 다이제스트는 응답이 반환하는 것과 동일하게 정규화하고 중복을 제거한 출처 증적 다이제스트 튜플을 해시합니다. | `current change`; `core/ontology_platform/topology_history.py`; 되돌린 수정으로 이전 다이제스트와 필드 불일치를 재현한 회귀를 포함한 집중 토폴로지 이력 검사 8개 통과. | 배포 재생 근거는 별도로 보존합니다. 현재 프로덕션 작성자는 각 묶음에 출처 증적 다이제스트를 설정합니다. |
| 2026-08-28 | implemented | 로그 provider I/O 전에 정확 Pod 진단을 강화했습니다. 종료 근거는 요청된 lookback 안에 있어야 하고 라이프사이클 행은 정확한 Pod UID와 일치해야 하며 projected 상태는 출처가 있고 신선하며 완전하고 충돌과 synthetic 값이 없어야 합니다. 동일 UID 재시작 판정은 불변 UID가 대체한 과거 소유권 근거를 요구하지 않습니다. | `current change`; 집중 Pod 진단 및 교체 검사 27개, Ruff 및 strict mypy 통과. | 인증된 정확 대상 진단 근거를 별도로 보존합니다. |
| 2026-08-27 | implemented | 양방향 `runtime_calls` 관측을 방향 edge 두 개로 보존했습니다. 서비스 간 상호 호출은 더 이상 방향 충돌로 전체 토폴로지 기준선을 억제하지 않습니다. | `current change`; 집중 인벤토리 변환 및 토폴로지 이력 검사 29개 통과; Ruff 및 strict mypy. | 인증된 런타임 호출 근거는 별도로 보존합니다. 출처 관측을 만들지 않았습니다. |
| 2026-08-27 | implemented | 인벤토리 매니페스트 다시 읽기와 PostgreSQL 토폴로지 재생을 변환 게시자의 정규 링크 순서에 맞췄습니다. 여러 LinkType이 있는 세대도 멱등적으로 재생되며, 저장된 1.2.0 매니페스트는 자체 링크 키를 차단하지 않고 1.3.0으로 다시 만들 수 있습니다. | `current change`; 집중 인벤토리 온톨로지 및 PostgreSQL 토폴로지 이력 검사 23개 통과; Ruff 및 strict mypy. | 배포 환경의 재시작 및 재생 근거는 별도로 보존합니다. 외부 출처는 조회하지 않았습니다. |
| 2026-08-29 | implemented | 불변 Pod 교체 및 복구 근거를 강화했습니다. 이제 축약기는 독립적으로 검증된 Pod-소유자 및 소유자-루트 컨트롤러 링크를 요구한 다음 최신 observed Pod, 종료 및 Deployment 상태를 일치하는 클러스터, 네임스페이스, 워크로드 개정 및 루트 컨트롤러 UID에 연결합니다. 양의 정수 replica와 컨테이너 상태를 요구하고, 종료 시각을 상관 창과 출처 개정에 연결하며, Pod 생성 전 관찰 또는 종료 후 생성을 차단합니다. 같은 UID의 재시작 분류에는 일치하는 생성 신원과 증가한 재시작 횟수가 필요합니다. 롤아웃 분류에는 변경된 워크로드 개정이 필요합니다. 비정상 교체에는 종료부터 교체까지 scale 변경이 없는 완전하고 시각순인 desired-replica 이력도 필요합니다. 모호한 후보 신원과 참조는 재생을 위해 결과에 유지되고, 누락된 모든 복구 필드는 명시적 공백이 됩니다. | `current change`; 검증된 소유권 링크, 범위, 개정, 출처, 수명 주기 순서, 권위 lane, 컨트롤러, replica 이력, 재시작, 모호성 및 상관 창 회귀를 포함한 집중 Pod 교체 축약기 테스트. | 축약기를 보존된 lifecycle 쿼리 조립에 연결하고 이슈 #291에서 인증된 실제 교체 및 복구 증적을 보존합니다. |
| 2026-08-27 | validated | Kubernetes topology 및 lifecycle migration head를 조정하고 격리 validation database를 canonical legacy schema에서 다시 생성한 뒤 병합된 Core service head를 적용했습니다. 인증된 seed/watch cycle 5개가 lease를 다시 획득하고 불투명 cursor를 sequence 0에서 5까지 limitation 없이 전진시켰으며 영속 reader는 이후 완전한 60초 zero-row 결과를 반환했습니다. | `current change`, Core migration head 1개, migration 계약 60개 통과, PostgreSQL lease, duplicate 및 reorder 통합 검사 1개 통과, 인증된 cluster `Running/Succeeded`, Event API HTTP 200, 정확한 UID 실제 읽기 17개 행 | 배포 보존과 실제 Pod 교체 및 복구 결합은 각각 이슈 #292와 #291의 별도 운영 근거로 남아 있습니다. |
| 2026-08-27 | in-progress | Lease 기반의 타입 지정 재개 가능 Kubernetes lifecycle 수집과 indexed 영속 Event 읽기를 추가했습니다. Collector는 현재 시각에서 coverage를 시작하고 bookmark와 함께 watch하며 `resourceVersion`을 불투명 값으로 취급합니다. 관측과 cursor 진행을 원자적으로 commit하고 authorization, expiry, source 및 result-limit gap을 기록합니다. | `current change`, lifecycle 및 기존 Event 검사 76개 통과, service-migration 계약 60개 통과, Ruff, formatter 및 strict mypy 통과, 인증된 실제 Event API HTTP 200 및 정확한 UID 읽기 17개 행 | Validation schema fingerprint와 경쟁하는 untracked migration head를 해결하고 service migration을 적용한 뒤 연속 seed/watch 두 cycle과 완전한 lookback 구간을 보존해야 행 0개가 과거 부재를 증명할 수 있습니다. |
| 2026-08-27 | implemented | 답변 변환에서 가장 최근의 범위가 제한된 Event 행을 보존하고 표시 개수, 전체 개수 및 `display_truncated` 상태를 공개했습니다. 가장 오래된 8개를 조용히 유지하지 않고 최신 8개 Event를 시간순으로 표시합니다. | `current change`, 집중 이중 언어 Resource Event 답변 회귀 검사 | 실제 Kubernetes Event API 접근을 복구하고 Event 행이 있는 인증된 답변 하나를 보존해야 합니다. 행 0개가 과거 부재를 증명하려면 영속 보존이 계속 필요합니다. |
| 2026-08-27 | implemented | 보안이 적용된 identity 조건식이 Resource 0개 또는 여러 개로 해소되면 정확한 대상 Resource Event 읽기가 안전하게 중단되도록 수정했습니다. 완전한 넓은 범위의 기존 빈 결과 동작은 유지합니다. | `current change`, 집중 Resource Event FunctionType 회귀 검사 | 실제 Kubernetes Event API 접근을 복구하고 인증된 정확한 대상 증적 하나를 보존해야 합니다. 행 0개가 과거 부재를 증명하려면 영속 보존이 계속 필요합니다. |
| 2026-08-27 | in-progress | I/O를 수행하지 않는 불변 Pod 교체 축약기를 추가했습니다. 과거 근거는 현재 상태 최신성이 아니라 상관 분석 구간에 대해 검증하고, 현재 Pod와 Deployment 근거는 최신 상태여야 합니다. 결과는 결정론적 재생을 위해 두 UID 기록, 소유권, 타임스탬프, 구간, 여유 시간 및 근거 참조를 다시 기록합니다. | `current change`, 집중 Pod 교체 축약기 테스트 13개 통과, Ruff, formatter 및 strict mypy 통과 | 이슈 #292를 통해 정규화된 수명 주기 관측을 영속화한 뒤 인증된 조회 구성을 연결하고 정확한 교체 및 복구 증적을 보존해야 이 행을 승격할 수 있습니다. |
| 2026-08-27 | implemented | Event 범위에 출처에 근거한 정확한 Resource 하나를 보존하고 제한 사항을 보여주는 이중 언어 Event 답변을 추가했습니다. 이름이 같은 Resource는 검토된 유형 근거가 좁히기 전까지 모호하게 유지하고 모든 답변은 출처 완전성과 권한 없음을 보여줍니다. | `current change`, 집중 Event 수직 경로 검사 287개 통과, Ruff, formatter 및 strict mypy 통과. 오래된 Core를 교체한 뒤 인증된 정확한 대상 실행이 노드 2/2와 근거 검사 8/8을 완료하고 Event 부재, 원인 또는 복구를 주장하지 않은 채 `source_unavailable`을 렌더링했습니다. | 런타임 identity의 Kubernetes Event API 접근을 복구하고 identity-aware 정확한 child 증적 하나를 보존한 뒤 행 0개가 과거 부재를 증명하기 전에 영속 보존을 추가합니다. |
| 2026-08-27 | implemented | 기존 reader seam을 넓히지 않고 증적에 결속된 정확한 child Kubernetes Event 필터를 추가했습니다. Core는 identity-aware reader에만 불변 two-field identity snapshot을 전달하고, 복합 reader는 legacy reader를 보존하며, Kubernetes adapter는 정확한 cluster 및 canonical Resource-id 재계산 뒤에만 UID selector를 허용합니다. | `current change`, Resource 이벤트 FunctionType, 복합 및 Kubernetes reader, legacy compatibility, immutable identity, selector 전달, 위조 UID/cluster 회귀 검사 27개 통과, Ruff, formatter, strict mypy 통과 | 인증된 정확한 child Console 근거를 보존합니다. 행 0개가 과거 부재를 증명하려면 영속 보존이 여전히 필요합니다. |
| 2026-08-26 | implemented | 기존 Resource 이벤트 이력 FunctionType에 범위가 제한된 Kubernetes Event 기능군을 추가했습니다. 프로바이더 라우팅은 Azure Resource Health를 독립적으로 보존하고, Kubernetes 이벤트는 불변 UID를 사용해 정확히 선택한 Resource에 귀속하거나 관련 객체가 이미 사라졌을 때 정확히 선택한 클러스터에 귀속합니다. 어댑터는 정규화한 종류, 상태, 분류, 발생 시각, 내용 기반 근거 신원만 보존합니다. | `current change`, Kubernetes 및 복합 이벤트 읽기 경로, 런타임 연결, 공유 UID 신원 helper, 집중 어댑터, 라우터, FunctionType, 의미 계획, 조립 및 런타임 검사, exact typed duration 정렬, 혼합 범위 보존, 인코딩 응답 거부, raw 256 KiB 상한을 검사했습니다. 인증된 정확한 클러스터 Console 실행에서 서버 소유 ObjectSet 및 `query.resource_event_history` 계획을 사용해 6.8초에 노드 2/2와 근거 검사 8/8을 실행 권한 없이 완료했습니다. 관측된 0건은 Kubernetes Event 보존이 권위 있게 확인되지 않았으므로 과거 부재가 아니며, 강화한 어댑터는 `source_retention_unverified`를 보고합니다. | 프로바이더 TTL 만료 전 이벤트를 과거 커버리지로 취급하려면 영속 이벤트 보존을 추가합니다. Pod 원인 또는 복구를 주장하기 전에 보존된 이벤트, 변경, replica, 교체 UID, 영향 범위, 새 기준 시점 근거를 결합합니다. |
| 2026-08-25 | implemented | 발급된 정확한 Pod S1 평가에 검토된 30분 재시작 횟수 변화량과 정확한 ReplicaSet 및 Deployment로 향하는 명시적인 나가는 소유권 단계 두 개를 추가했습니다. 서버 소유 5-node 계획은 보안이 적용된 그래프 증적 세 개를 모두 인증하고 소유권 link 근거를 검증하며, 범위가 제한된 양수 변화량과 ready 및 available 상태인 소유자 replica 전체를 복구 보고의 조건으로 사용합니다. 불완전하거나 모호하거나 오래되거나 충돌하는 근거는 판단을 보류하며, dependency-only 입력은 모델이 작성한 대체 값을 거부합니다. 현재 상태와 메트릭 모두 원인 또는 실행 권한을 주장하지 않습니다. | `current change`, 집중 메트릭, 검증기, 축약기, 증적, 플래너, 운영 조립 검사 49개 통과, 의미 라우팅 회귀 검사 370개 통과, Ruff, formatter, strict mypy 통과 | 정확한 Pod가 포함된 완전한 Kubernetes 세대를 보존한 뒤 원인 또는 교체 후 복구를 주장하기 전에 독립적인 Kubernetes 이벤트, 변경, 교체 UID, 영향 범위, 새 기준 시점 근거를 추가합니다. |
| 2026-08-25 | implemented | 행이 0개이고 원본이 불완전한 Resource ObjectSet을 일반 기능 실패 대신 완료된 타입 기반 조회 결과로 보존했습니다. 이제 대상 없는 S12 질문은 불완전한 범위를 부재로 취급하지 않고 검증된 후보 0개, `source_incomplete`, 완료된 검증, 실행 권한 없음을 반환합니다. | `current change`, `query_source_handlers.py`, 집중 rollout 및 불완전 원본 검사 19개 통과, 인증된 표준 포트 Console 턴에서 관측 이벤트 4개와 근거 검사 5/5 완료 | 정확한 Deployment 하나가 포함된 완전한 Kubernetes 세대를 보존한 뒤 4-node rollout 평가와 독립적인 새 기준 시점 복구 검증을 실행합니다. |
| 2026-08-25 | implemented | Rollout 관측을 그래프 우선 의미 경로에 연결했습니다. 대상 없는 rollout 표현은 범위가 제한된 Kubernetes Deployment 후보로 해석하고, 정확한 대상은 명시적인 소유권 탐색 두 단계와 원인을 주장하지 않는 발급된 FunctionType으로 컴파일합니다. | `current change`, 집중 대상 없는 요청, 축약기, 증적, 탐색, 플래너, 운영 조립 검사 17개 통과, 작업 범위 Ruff 및 strict mypy 통과 | Core를 재시작하고 완전한 Kubernetes 세대에서 인증된 후보 및 정확한 대상 증적을 보존합니다. |
| 2026-08-25 | implemented | 실제 로컬 세대에서 AKS AgentPool 8개가 검토된 AKS parent와 evidence가 없는 Resource Group parent를 동시에 가진 상태를 확인한 뒤 Azure 관계 수렴을 강화했습니다. Exact-parent shadowing과 durable cardinality gate가 중복 parent 경로를 제거합니다. 분류된 non-edge는 incomplete coverage를 보존하면서 현재의 검증된 Resource와 link를 전진시킬 수 있습니다. Distributed projection lock, source-bound query receipt, stale evidence projection, additive N-1 receipt decode로 generation 및 evidence 공백을 닫았습니다. | `current change`, 집중 ARM, provider contract, projection, runtime, PostgreSQL, ObjectSet, Operator, Console 검사, 아래 adversarial round 12회 | 집중 검증 후 권위 있는 로컬 세대를 refresh하고 보존합니다. 배포 Azure certification은 Issue #262에서 별도로 유지합니다. |
| 2026-08-25 | implemented | 범위가 제한된 Kubernetes Deployment 및 Pod rollout 상태를 완전 인벤토리 세대에 추가했습니다. 어댑터는 replica 수, 단일 Progressing 조건, Pod 준비 상태, 재시작 횟수, 대기 사유만 유지하며 원시 프로바이더 payload를 보존하지 않고 잘못된 status를 거부합니다. | `current change`, `kubernetes_api_inventory.py`, 집중 Kubernetes API 인벤토리 검사 7개 통과 | 완전한 실제 운영 exact-release 세대를 보존하고 타입이 지정된 rollout 평가를 그래프 우선 조회 경로에 결속합니다. |
| 2026-08-25 | implemented | 완전 세대 관계 검증에서 관측된 endpoint의 타입이 잘못된 경우 무관한 duplicate conflict 대신 `target_type_mismatch`로 분류하도록 수정했습니다. Candidate는 활성 그래프에서 계속 제외되며 mapping별 unavailable reason을 보존합니다. | `current change`; 집중 관계 변환 및 검증 검사 65개 통과. | 배포된 완전 세대 근거는 별도로 보존합니다. 이 수정은 관계나 권한을 추가하지 않습니다. |
| 2026-08-22 | in-progress | 지속형 운영 인스턴스 그래프 계약을 도입했습니다. 고정 6시간 최신성 목표를 이벤트 기반 및 적응형 범위 제한 수집으로 바꾸고, 타입 지정 rollup, 검증된 archive, 복원, purge 요구 사항을 추가했습니다. | `current change`, 쌍을 이루는 설계 문서와 집중 문서 gate | 집중 구현 및 운영 근거로 OI-01부터 OI-12까지 완료합니다. |
| 2026-08-22 | implemented | Machine-readable 15단계 source-to-store 감사와 owner, binding, test, state, missing-gap 근거를 확인하는 결정론적 checker로 OI-01을 완료했습니다. | `current change`, 감사 record, checker, 집중 감사 테스트(`3 passed`) | 검증된 source-policy 선언으로 OI-02를 시작합니다. 적응형 control, rollup, archive, live write-through는 각각을 소유한 이후 패키지에 남깁니다. |
| 2026-08-22 | implemented | 검증된 source policy, adaptive scheduling, event/delta/snapshot convergence, principal-safe collection health로 OI-02부터 OI-05까지 완료했습니다. | `current change`, collection source, scheduler, convergence, health, reconciliation, sync, topology-history, loopback PostgreSQL focused 검사(`157 passed`) | Preservation을 닫기 전에 collection observation provenance를 typed rollup input과 통합합니다. |
| 2026-08-22 | implemented | Semantic-policy-driven fact family, 명시적 zero 및 missing interval, 보수적인 partial 및 conflict 처리, replay deduplication, average의 count와 sum을 보존하는 mergeable statistics로 OI-06을 완료했습니다. | `current change`, semantic rollup module과 focused rollup 검사(`6 passed`) | OI-07에서 immutable archive 및 purge safety를 완료합니다. |
| 2026-08-22 | implemented | Content-addressed manifest, verification, restore sampling, archive coverage receipt, retention 및 legal hold, append-only PostgreSQL evidence, safe-to-retry purge behavior로 OI-07을 완료했습니다. | `current change`, archive 및 purge focused 검사(`8 passed`), Core service migration 검사(`51 passed`) | OI-08 전에 collection-to-preservation integration boundary를 실행합니다. |
| 2026-08-22 | implemented | OI-02부터 OI-07까지 integration boundary를 통과했습니다. 명시적 inventory adapter가 source, generation, ontology release, effective/event/recorded time, completeness, conflict를 보존합니다. Event, delta, snapshot, duplicate, reorder, incomplete, conflict, tamper, restore, hold, purge failure, restart case는 결정론적이고 권한이 없습니다. | `current change`, cross-lane integration 검사(`3 passed`), OI-01 audit 검사(`3 passed`), focused static gate | OI-08을 시작할 수 있습니다. OI-09부터 OI-12까지는 각 exit criteria가 충족될 때까지 blocked 상태입니다. |
| 2026-08-22 | implemented | 정확히 `use_graph`, `refresh_then_query`, `use_live_evidence`, `query_archive`, `hold` 중 하나를 반환하고 action authority를 부여하지 않는 순수 graph evidence refresh reducer로 OI-08을 완료했습니다. | `current change`, focused refresh 검사(`5 passed`), Ruff, strict mypy | 정식 campaign blocker를 해결한 후 reducer를 일반 semantic query composition에 연결합니다. |
| 2026-08-22 | implemented | OI-09의 안전한 write-through 범위를 완료했습니다. 검증된 live read는 정식 부분 overlay event가 되며 PostgreSQL은 완전 snapshot 속성이나 관계를 삭제하지 않고 부분 속성을 병합합니다. | `current change`, live-evidence 검사(`5 passed`), loopback PostgreSQL 부분 overlay 검사(`1 passed`), Ruff, strict mypy | 일반 semantic query composition의 refresh 선택 뒤에 writer를 연결합니다. |
| 2026-08-24 | implemented | Exact-target 현재 상태 조회를 graph-first freshness 축약, bounded live read 1회, 내용 결속 canonical 부분 overlay write-through 및 secured 재조회에 연결했습니다. | `current change`, graph refresh, 의미 조립, live evidence 및 runtime 집중 검사 | 배포 provider pressure와 freshness 측정은 별도로 보존하며 더 넓은 조회와 과거 조회는 계속 hold합니다. |
| 2026-08-24 | implemented | 혼합 coverage 최신성 결함을 닫았습니다. Multi-Resource 결과에서 fresh Resource 하나가 state-fact metadata가 없는 다른 반환 Resource를 숨길 수 없습니다. 허용된 경우 조회를 한 번 갱신하고 그렇지 않으면 incomplete로 hold합니다. | `current change`; `graph_query_refresh.py`; current, stale, conflict, refresh, mixed-metadata 집중 검사(`5 passed`). | 배포된 mixed-generation 근거는 별도로 보존합니다. 이 읽기 전용 수정은 observation, mutation 또는 execution authority를 추가하지 않습니다. |
| 2026-08-22 | implemented | 정확한 instance, 저장 방향 path, function, refresh 결과, archive 상태, no-authority를 검사하는 typed 대표 competency evaluator로 OI-10을 완료했습니다. 답변 text는 검사하지 않습니다. | `current change`, 대표 및 대체 오류 검사(`2 passed`), Ruff, strict mypy | OI-11에서 정식 이중 언어 campaign을 실행합니다. |
| 2026-08-22 | in-progress | Direct 70-case 이중 언어 campaign loader와 typed oracle을 구현하고, 자유형 assurance concept를 안정된 machine token으로 강화했으며, 3-turn typed no-authority readiness probe를 통과했습니다. Full campaign은 첫 case `action-incident-mitigation-draft.direct.en`이 허용된 `action_draft` 또는 `held` 대신 `unsupported`를 반환해 중단됐습니다. | `current change`, OI-01부터 OI-10 prerequisite gate(`241 passed`, skipped 없음), campaign runner 검사(`6 passed`), Console typecheck, assurance projection 검사(`9 passed`), 인증된 표준 port readiness(`3/3`) | Keyword routing 없이 action-draft frame 분류를 수정한 뒤 direct 70 cases를 모두 다시 실행합니다. 해당 gate가 통과하기 전까지 OI-12는 blocked 상태입니다. |
| 2026-08-24 | in-progress | Corpus 전체 semantic assurance를 OI-11에서 분리했습니다. 이전 direct 70-case 시도는 과거 근거로 보존하고, 현재 560-case corpus, 생성된 질문 우주, 변경 중심 cohort 및 이후 corpus 증가는 지속형 의미 보증이 관리합니다. | `current change`, [지속형 의미 보증](../interfaces/continuous-semantic-assurance-ko.md), 구조화된 corpus count, 기존 집중 competency 및 typed oracle 계약 | 집중 이중 언어 positive 및 negative action-draft 분류 검사와 typed no-authority 증적으로 OI-11을 완료합니다. 전체 corpus 및 예약 assurance는 소유 문서에 따라 독립적으로 실행합니다. |
| 2026-08-24 | implemented | 타입이 지정된 영어 및 한국어 draft 요청과 같은 표현을 포함한 read 요청으로 OI-11을 완료했습니다. Keyword routing이 아니라 구조화된 `draft_only`와 `advise_only` posture가 terminal path를 선택하며 모든 proposal, receipt, frame, plan, outcome은 권한이 없습니다. | `current change`, `test_semantic_judgment.py::test_bilingual_action_posture_receipts_are_typed_and_authority_free` 및 `test_semantic_planning_tier_routing.py::test_bilingual_typed_action_posture_routes_without_keyword_rules`(`8 passed`) | 로컬 OI-12 표현 회귀를 실행한 뒤 별도로 통제되는 배포 Azure 인증 측정값을 보존합니다. |
| 2026-08-24 | in-progress | 영어와 한국어의 장애 draft 표현 방식 8개 전체에 대해 로컬 OI-12 표현 회귀를 통과했습니다. 이 검사는 production phrase rule이 아니라 생성된 corpus와 타입 지정 judgment를 사용하며 모든 case가 권한 없이 plan 실행 전에 중단됨을 입증합니다. | `current change`, `test_semantic_planning_tier_routing.py::test_incident_action_draft_all_bilingual_wording_styles_remain_authority_free`(`1 passed`, corpus case 16개) | 최신성, API 압력, 지연, 저장소 증가, rollup 범위, archive 복원, 공급자 실패 측정을 위한 배포 Azure 인증은 열려 있습니다. |
| 2026-08-24 | in-progress | 지원되지 않는 edge를 추가하지 않고 남은 authorization 및 runtime-call 근거 경로를 감사했습니다. Azure relationship drop은 이미 모델링되지 않았거나 관측되지 않은 endpoint를 보존하지만 PostgreSQL role에는 별도의 타입 지정 observation 계약이 없습니다. Trace continuity는 hop label만 전달하며 활성 ontology release에는 검토된 runtime-call LinkType이 없습니다. | `current change`, `inventory.py`, `trace_continuity.py`, `delivery/azure/trace_continuity.py`, `instance_explorer.py`, [Issue #260](https://github.com/dotnetpower/fdai/issues/260) | Producer를 binding하기 전에 누락된 계약을 정의하고 다시 검증합니다. 이름, Resource Group, 환경 변수 이름, credential, RBAC grant에서 Resource identity를 추론하지 않습니다. |
| 2026-08-24 | in-progress | Resource를 시작하거나 workflow를 dispatch하지 않고 읽기 전용 배포 preflight를 실행했습니다. 선택한 개발 context가 일치했고 runtime app 5개가 모두 provision됐지만 workload 5개 중 하나만 `POSTGRES_HOST`를 노출했으며 private database와 deploy runner는 정지 상태였습니다. | [Issue #262](https://github.com/dotnetpower/fdai/issues/262) preflight 근거, Azure 또는 workflow 변경 없음 | 테스트한 exact SHA를 push하고 필수 CI와 destroy 0건 plan을 검토한 뒤 protected runner에서 apply 및 인증합니다. |
| 2026-08-24 | implemented | 검토된 `runtime_calls` 선언과 권한 없는 순수 projector를 추가하고 하드닝했습니다. 10개 관점 검토에서 exact-release, 시간 순서, digest binding, principal redaction, freshness bound, verification 의미 결함을 닫았습니다. Observation 하나가 두 exact endpoint identity를 제공해야 candidate edge가 active-generation 및 scope 검사를 통과할 수 있습니다. | `current change`, runtime-call projector(`16 passed`), projector 및 catalog 통합 검사(`24 passed`), 이전 LinkType/provenance 검사(`15 passed`), 이전 catalog/release 검사(`22 passed`), Ruff, strict mypy | 타입 지정 telemetry producer와 single writer를 binding한 뒤 인증된 Operator 및 Console 근거를 보존합니다. |
| 2026-08-24 | implemented | 인증된 타입 지정 runtime-call observation을 기존 inventory single writer에 binding하고, 예약 경로에 명시적 unavailable binding을 추가했으며, principal-safe PostgreSQL role 근거를 Azure RBAC와 분리했습니다. 사용할 수 없는 authorization child scope를 분류하고 권한 없는 source 근거를 Operator와 Console까지 변환했습니다. 독립 hardening 11회 후 Low를 초과하는 미해결 결함은 없습니다. | `current change`, 집중 Core 및 Operator 검사(`111 passed`), Console model 검사(`17 passed`), Console typecheck, 변경한 production 경로의 editor diagnostic 0건 | exact caller와 target Resource ID를 제공하는 권위 있는 telemetry source를 주입한 뒤 push되고 green인 SHA에서 인증된 `8010` 및 `5273` 근거를 보존합니다. 배포와 Azure 인증은 Issue #262에 유지합니다. |
| 2026-08-22 | validated | Resource 인스턴스에 사용하던 Console architecture renderer를 평면 사각형 graph로 교체했습니다. Operator projection은 선택한 1단계 Resource 사이의 범위가 제한된 모든 link를 반환하고 Resource 및 관계 잘림을 구분하며, Console은 권한을 부여하지 않고 검토된 Azure 아이콘과 focus 가능한 상태 및 FDAI 감사 timeline을 표시합니다. | `current change`, 집중 Operator 및 Console 검사, production build, 비평 및 hardening 20회, Resource 3개와 관계 3개를 사용한 인증된 표준 port 활성 세대 근거 | 권위 있는 Azure Activity Log 및 Resource Health projection을 별도로 연결합니다. Allowlist에 정확한 아이콘이 없는 Resource 유형은 일반 Azure fallback을 유지합니다. |
| 2026-08-22 | validated | Server에서 `fdai`로 필터링한 결과 200개 중 Resource 20개를 무작위로 선택해 인증된 browser campaign을 실행했습니다. 출처가 잠긴 Azure asset으로 표본 icon 공백을 수정하고, 밀집 감사 marker를 cluster로 합치고, path를 누락하지 않는 밀집 관계 유형 요약을 추가했으며, viewport 변경 후 선택 Resource를 다시 중앙에 배치했습니다. | `current change`, root 유형 12개에 대한 정확한 Resource 선택 20회, 최대 Resource 80개와 관계 79개. 최종 재실행에서 HTTP, 개수, 선택, 일반 icon, node, label, marker, page overflow, workbench overflow, preview overflow 결함이 모두 0건이었습니다. | 이후 관측된 Resource 유형에 정확하고 검토된 asset이 없으면 출처가 잠긴 icon allowlist를 확장합니다. Azure Activity Log와 Resource Health는 별도의 사용 불가 원본으로 유지합니다. |
| 2026-08-22 | validated | Container App 하나를 권위 있는 Azure 구성 및 활성 온톨로지 그래프와 대조한 뒤 가장 작은 공통 관계 producer를 추가했습니다. 검토된 ARG mapping은 정확한 managed environment ARM 참조를 `Container App -> depends_on -> Container Apps Environment`로 변환하며, snapshot 저장소와 Operator는 관계별 구성 출처, 기준 시점, 완전성, 사용 불가 상태를 보존합니다. | `current change`, 익명 대조에서 environment 1개, Managed Identity 3개, registry 1개, infrastructure subnet 1개, Log Analytics workspace 1개를 확인했지만 이전 그래프는 Resource Group edge 1개만 노출했습니다. 집중 Core, Operator, Console 검사가 통과했습니다. 새로 고친 인증된 `8010` 응답은 새 typed dependency를 포함해 Resource 3개와 관계 3개를 반환했고, 사용 가능한 configuration evidence 3개와 unavailable 관계 evidence 0개를 보존했습니다. Desktop, constrained desktop, mobile overflow 검사가 통과했습니다. | 별도로 검증된 Managed Identity, registry, observability, network, data service, service call producer만 추가합니다. 같은 Resource Group 구성원 관계나 해석되지 않은 environment variable 이름에서 dependency를 유도하지 않습니다. |
| 2026-08-23 | in-progress | 검토된 Azure 관계 producer를 활성 공급자 inventory 전체로 확장했습니다. Per-row mapping과 완전 세대 unique alias join은 각자 소유한 단계에서만 실행되고, endpoint closure는 dangling link를 방지하며, snapshot metadata는 전역 관계 공백을 보존합니다. Operator는 Resource Group transit 없이 범위가 제한된 깊이 8 graph를 탐색합니다. Console은 관계 범위와 traversal truncation을 구분하고, 현재 telemetry가 두 endpoint Resource identity를 입증할 수 없으므로 runtime call graph를 unavailable로 보고합니다. | `current change`, 집중 Core 검사 164개, Operator 검사 3개, Console 검사 26개, migration/readiness 검사 3개가 통과했고 Ruff, strict mypy, Console typecheck가 통과했습니다. 새 권위 있는 로컬 세대는 Resource 519개와 link 924개를 보존했습니다. Resource Group과 Subscription transit을 제외하면 component는 319개에서 103개, isolate는 289개에서 81개로 줄었고 가장 큰 component는 61개에서 190개로 늘었습니다. 정확히 저장된 edge에서 ingress-to-egress endpoint pair 83개와 type-path pattern 59개를 확인했습니다. 인증된 깊이 8 `8010` 응답은 Container App 하나에 대해 Resource 188개와 link 444개, schema `1.3.0`, 독립적인 source state 6개, 권한 없음, 명시적 범위 및 activity 제한을 반환했습니다. Desktop, constrained desktop, mobile 검사에서 document와 workbench horizontal overflow가 0이었습니다. | 남은 `missing_target_endpoint`, `target_type_mismatch`, `unresolved_reference` candidate를 정확한 provider identity로 해석하거나 분류합니다. Telemetry가 독립적으로 검증 가능한 caller와 target Resource ID를 제공할 때만 runtime call edge를 변환합니다. |
| 2026-08-23 | validated | 기존 Instances 화면의 제한 없는 rank별 세로 적재를 선택 Resource 중심 배치로 교체했습니다. 직접 incoming 및 outgoing Resource와 link는 선명하게 유지하고, 간접 맥락은 흐리게 표시하며, 포인터 또는 키보드 focus에서 범위가 제한된 Resource나 link를 제거하지 않고 root까지의 결정론적 최단 경로를 복원합니다. 이웃을 선택하면 같은 화면에서 해당 Resource를 새 root로 중앙에 배치합니다. | `current change`, `ontology-instance-graph.model.test.ts` 검사 14개, Console typecheck와 production build가 통과했습니다. 인증된 표준 port Browser 검사는 높이 600px인 graph에서 Resource 188개와 link 444개를 유지했습니다. `1440x900`, `993x641`, `390x844`에서 root 중심 오차가 8px 이내였고 document, workbench, toolbar, summary overflow는 모두 0이었습니다. 간접 focus는 경로 node, edge, label 8개를 복원했고 직접 이웃 선택은 같은 Instances 화면을 다시 중앙에 배치했습니다. | 별도로 추적하는 권위 있는 Activity Log, Resource Health, 관계 범위, runtime call 근거 작업을 계속합니다. 이 표현 계약에는 추가 온톨로지 화면이 필요하지 않습니다. |
| 2026-08-23 | validated | Key Vault secret URL을 참조하는 Container App과 Job의 정확한 완전 세대 변환 결과를 추가하고, 각 VNet link에 대한 Private DNS zone containment를 추가했으며, 기존 Instances canvas를 모든 link를 rank하는 graph에서 범위가 제한된 semantic focus 변환 결과로 변경했습니다. Dependency, access, containment 의미가 더 이상 하나의 rank에서 경쟁하지 않습니다. Inspector와 대화 맥락은 이제 직접 관계와 연결 path segment를 구분합니다. | `current change`, provider mapping, ARG, generation 검사 124개와 Console instance, graph, localization 검사 31개가 통과했습니다. Console typecheck, production build, catalog parity도 통과했습니다. 새 활성 로컬 snapshot은 Resource 519개와 link 937개를 보존했습니다. 인증된 Browser 근거에서 정확한 workload-to-Key Vault dependency 13개, Private DNS zone parent와 VNet attachment를 확인했습니다. Resource 200개와 link 469개인 Key Vault 응답은 node 25개와 edge 55개, Resource 188개와 link 444개인 PostgreSQL 응답은 node 15개와 edge 31개로 범위가 제한된 focus canvas를 표시했습니다. Desktop, constrained desktop, mobile 검사에서 root 중심 오차는 8px 이내였고 document, workbench, legend overflow는 모두 0이었습니다. | Secret만 사용하는 정확한 database binding, Private Endpoint DNS zone-group 변환 결과, authorization 근거는 각각의 타입이 지정된 원본에서만 추가합니다. 기존 relationship drop이 별도로 해결되거나 분류될 때까지 inventory ontology 변환 결과는 unavailable 상태를 유지합니다. |
| 2026-08-23 | validated | 엄격한 `LR` graph 좌표를 적용하고, AuthorizationResources role assignment를 추가했으며, 완전 세대에서 provider가 없는 authorization scope를 해석했습니다. 범위가 제한된 읽기 전용 ARM child API로 Private Endpoint DNS zone-group을 수집하고 mapping별 drop 분류를 보존했습니다. 다섯 service Terraform root는 secret DSN을 노출하지 않으면서 secret이 아닌 PostgreSQL host를 노출합니다. | `current change`, 집중 ARM, ARG, generation, inventory-sync, hybrid wiring, catalog 검사가 통과했습니다. Operator Terraform format과 service-root 검사도 통과했습니다. 새 활성 로컬 세대는 Resource 765개와 link 1,439개를 보존하고 scope 178개, Managed Identity 106개, DNS closure edge 두 종류 각각 21개를 포함합니다. 인증된 `5273` Browser 검사에서 LR이 아닌 edge 0개, document overflow 0개, 정확한 role-assignment mapping 근거, unavailable 직접 근거가 없는 node 3개와 edge 2개의 DNS focus를 확인했습니다. | 새 service host 입력을 배포하기 전에는 database dependency 근거를 주장하지 않습니다. 저장된 relationship-drop group 11개를 해결하거나 검토된 unavailable 상태로 분류하고, PostgreSQL database-role 근거를 Azure RBAC와 별도로 보존합니다. |
| 2026-08-23 | validated | 기존 Instances graph에 root 기준 Incoming, Selected Resource, Outgoing band를 추가했습니다. 양방향 link와 범위가 제한된 cycle은 presentation occurrence를 복제하므로 표시되는 모든 저장 edge는 source 또는 target을 바꾸지 않고 엄격한 `LR`을 유지합니다. Inspector는 graph direction, access, containment, 연결 path, 검증된 traffic 의미를 분리합니다. 검증된 ingress는 정확한 gateway 또는 load balancer backend target으로 제한하고, 검증된 egress는 해당 source mapping과 AKS effective outbound mapping으로 제한합니다. Alert, telemetry, dependency, attachment, containment, peering, name, DNS, Resource Group 근거는 traffic direction이 되지 않습니다. | `current change`, Console graph 및 instance 검사 31개, typecheck, production build, catalog parity가 통과했습니다. 집중 relationship backend 검사 192개와 Ruff, strict mypy도 통과했습니다. 읽기 전용 ARG와 범위가 제한된 ARM GET refresh가 Resource 832개와 link 1,513개를 promotion했습니다. Key Vault, PostgreSQL, Container App, Private Endpoint, role assignment, Managed Identity, Application Gateway, Load Balancer, AKS root를 대상으로 인증된 `5273`을 검사한 결과 LR이 아닌 edge와 document 또는 workbench overflow가 모두 0개였습니다. `1440x900`, `993x641`, `390x844`에서 root 중심 오차는 8px 이내였고 mobile control은 최소 44px를 유지했습니다. 정확한 AKS outbound edge 1개는 완전한 mapping, source property, cutoff 근거와 함께 검증된 egress로 표시됐습니다. | 이 세대에는 검증된 ingress를 입증하는 활성 gateway 또는 load balancer backend mapping이 없어 Console은 이를 표시하지 않습니다. 같은 residual group 11개와 candidate 26개가 남아 있으며, 줄이기 위해 edge를 조작하지 않았습니다. |
| 2026-08-23 | validated | 선택한 Resource 주변에 containment-aware DAG 맥락을 복원했습니다. 범위가 제한된 ancestor closure는 Resource Group을 Private Endpoint보다 앞에 배치하고 VNet과 Subnet을 복원하며 scope node를 transit hub로 사용하지 않습니다. 비순환 node는 하나의 longest-path occurrence를 사용하고 양방향 또는 cycle edge만 occurrence를 복제합니다. Relationship-drop metadata는 candidate multiplicity를 보존하고 open environment value를 분류하기 전에 exact alias를 시도하며 ARM, URI, hostname reference가 될 수 없는 값을 무시합니다. | `current change`, Console 검사 38개, typecheck, production build, catalog parity가 통과했습니다. 집중 relationship 검사 181개와 Ruff, strict mypy도 통과했습니다. 읽기 전용 ARG와 범위가 제한된 ARM GET refresh는 Resource 832개와 link 1,513개를 유지했습니다. 인증된 PostgreSQL graph는 node 17개와 edge 50개를 Resource Group `-2`, Private Endpoint와 VNet `-1`, 선택한 PostgreSQL `0`, NIC `1`, Subnet `2` 순서로 표시했습니다. 세 viewport 모두 Resource occurrence 중복, collision, LR이 아닌 edge, document, workbench, legend overflow가 0이었고 root 오차는 최대 8px, mobile control은 44px였습니다. | 이전 history의 group 11개와 candidate 26개는 undercount였습니다. 정직한 multiplicity가 처음에는 group 11개와 candidate 863개를 드러냈고, shape filtering으로 잘못된 ARM-value group 하나를 제거해 최종 residual은 group 10개와 candidate 256개입니다. Edge는 추가하지 않았습니다. Provider에 없는 AKS 및 load balancer endpoint, 모델링되지 않은 role principal과 child scope, 해석되지 않은 registry, 구성된 외부 endpoint가 명시적으로 남아 있습니다. |
| 2026-08-23 | validated | 고정 node를 사용하는 넓은 graph viewport를 추가했습니다. 의미 column 간격을 242px에서 288px로 늘리고 containment를 peering처럼 보이는 점선에서 solid hierarchy line으로 바꿨습니다. 축소, 맞춤, 확대, Ctrl 또는 Meta와 wheel, 빈 canvas drag pan은 Resource node를 움직이지 않습니다. Registry dependency는 `workload -> depends_on -> registry`를 유지합니다. Registry를 선택하면 ontology edge를 뒤집지 않고 정확한 consumer를 incoming 관계로 표시합니다. | `current change`, 집중 Console 검사, typecheck, production build, catalog parity가 통과했습니다. 인증된 desktop 근거에서 가장 큰 registry의 consumer 16개를 모두 표시하고 100%에서 canvas 폭 2,232px, fit 31%, center-preserving zoom, node transform이 바뀌지 않는 drag pan, LR이 아닌 edge와 page overflow 0개를 확인했습니다. Constrained desktop은 fit 후 zoom 43%, mobile은 40%였고 mobile control은 44px를 유지했습니다. 두 viewport 모두 node transform이 고정됐고 document, workbench, legend overflow가 0이었습니다. Computed style은 solid containment, `5 4` dashed access, `2 4` dotted peering을 입증했습니다. | App 9개와 Job 11개의 registry 구성 및 edge 범위가 모두 완전합니다. Reverse registry edge 또는 추가 관계는 근거가 없습니다. 남은 작업은 별도로 기록된 provider evidence gap에 유지됩니다. |
| 2026-08-23 | implemented | `properties.nodeResourceGroup`에서 정확한 완전 세대 AKS ownership 근거를 추가했습니다. 고유한 Resource Group 이름은 `AKS -> attached_to -> managed Resource Group`을 만들고, 여러 subscription에서 같은 이름이 나오면 `unresolved_reference`를 기록하고 edge를 만들지 않습니다. Console은 해당 mapping과 저장된 containment 및 dependency edge만 사용해 main Resource Group, AKS, managed Resource Group, VMSS와 Load Balancer, identity와 outbound IP 순서로 표시합니다. | `current change`; provider catalog, 완전 세대 및 inventory-sync 검사 38개와 Console 집중 검사 47개가 통과했고 typecheck와 production build도 통과했습니다. 범위가 제한된 읽기 전용 ARG/ARM refresh는 Resource 765개와 link 1,442개를 promotion했습니다. 인증된 AKS 응답은 정확한 managed Resource Group mapping을 포함해 Resource 14개와 link 21개를 표시했습니다. Focus canvas는 node 7개와 선택한 저장 edge 10개를 모두 렌더링했고 `1440x900`, `993x641`, `390x844`에서 중복 occurrence, collision, LR이 아닌 edge, document overflow가 모두 0개였습니다. | 활성 snapshot은 기존 relationship drop을 유지하므로 inventory ontology 변환 결과는 replacement object 또는 link 없이 올바르게 unavailable 상태를 유지합니다. 이 표현 근거를 promotion하기 전에 정확한 source에 연결된 관리되는 Browser 증적을 보존합니다. |
| 2026-08-23 | validated | Mapping별 drop count에 `source_property_path`와 정확한 provider-native endpoint type을 보존하고, 일치하지 않는 role assignment principal과 일반 Container workload 환경 문자열을 Resource candidate로 취급하지 않도록 수정했습니다. 해석되지 않은 non-loopback endpoint URI는 unavailable 근거로 유지합니다. 완전 세대 endpoint identity 없이는 edge를 만들지 않습니다. | `current change`; 집중 relationship backend 검사 199개와 Operator 및 Console 검사 각각 41개가 통과했고 Ruff, strict mypy, Console typecheck, production build가 통과했습니다. 권위 있는 refresh 한 번은 Resource 832개와 link 1,516개를 promotion했고 residual classification 10개와 candidate 69개를 남겼습니다. 인증된 schema `1.3.0` 깊이 8 응답과 세 viewport는 명시적 coverage, source state 6개, page overflow 0개, node overlap 0개, 실행 및 변경 권한 없음을 보존했습니다. | 남은 정확한 missing target, child authorization scope, managed AKS Resource Group 이름, 외부 registry, 구성된 Communication endpoint 3개를 해결하거나 분류합니다. Runtime call edge는 telemetry가 두 Resource ID를 모두 입증할 때까지 unavailable 상태를 유지합니다. |
| 2026-08-23 | validated | 구성된 Communication endpoint 3개를 정확한 완전 세대 `hostName` alias로 해결하고, 남은 모든 suppressed candidate에 검토된 mapping별 unavailable reason을 부여했습니다. 접근 가능한 모든 subscription을 대상으로 한 ARG 가시성 검사에서 누락된 AKS managed endpoint 또는 cross-subscription subnet target은 발견되지 않았습니다. 일치하지 않는 외부 registry와 모델링되지 않은 authorization child scope는 명시적 non-edge로 유지합니다. | `current change`; 집중 relationship backend 검사 199개와 Ruff, strict mypy가 통과했습니다. 권위 있는 refresh 한 번은 Resource 832개와 link 1,519개를 promotion했습니다. Snapshot metadata는 classification 9개와 candidate 66개를 기록합니다. `target_outside_active_generation` 10개, `target_provider_type_unmodeled` 40개, `reference_not_observed` 16개입니다. 인증된 schema `1.3.0` 깊이 8 근거는 서로 다른 Job 3개에서 들어오는 완전한 Communication edge 3개를 반환하고 runtime call unavailable 상태를 보존했으며 실행 또는 변경 권한을 부여하지 않았습니다. | 이 세대의 mapping별 관계 범위 작업은 완료됐습니다. Runtime call edge는 telemetry가 두 Resource ID를 모두 입증할 때까지 unavailable 상태를 유지합니다. 관련 없는 deployment 및 OI campaign 작업은 별도로 추적합니다. |
| 2026-08-23 | validated | 권위 있는 refresh 경로에 완전한 provider scope coverage와 mapping되지 않은 provider identity를 연결해 local full-stack 준비를 scheduled ARG inventory와 동일하게 복원했습니다. 준비 과정이 identity-complete graph를 vocabulary-only 세대로 교체하지 않습니다. | `current change`; local-refresh 계약, Ruff, strict mypy 검사가 통과했습니다. 수정된 권위 있는 준비 refresh는 동일한 classification 9개와 candidate 66개를 유지하며 Resource 832개와 link 1,519개를 promotion했습니다. Scope transit을 제외한 graph는 Resource 789개, link 800개, component 197개, isolate 160개, largest component 319를 유지했습니다. | 다른 provider identity 또는 source overlay를 추가할 때 준비 경로와 scheduled inventory binding을 동일하게 유지합니다. |
| 2026-08-24 | implemented | 검토된 Azure parent 및 root containment, 범위가 제한된 AKS AgentPool child 수집, single atomic promotion 전 UID 기반 Kubernetes API enrichment를 추가했습니다. Kubernetes binding이 없으면 사용 불가 상태를 기록하며 Azure 세대를 교체하지 않습니다. | `current change`; 집중 Azure, Kubernetes, 인벤토리, 카탈로그 및 조립 검사 260개 통과, Ruff 통과, source 파일 10개의 strict mypy 통과 | 배포 환경 및 secret mount를 추가한 뒤 런타임 검증을 주장하기 전에 완전한 실제 운영 Kubernetes 세대를 보존합니다. |
| 2026-08-24 | implemented | 해결되지 않은 static token mount를 opt-in AKS workload-identity binding으로 교체했습니다. Terraform은 AKS RBAC Reader만 부여하고 endpoint, public CA, cluster id 및 deployment-supplied audience를 전달하며 bearer token을 저장하지 않습니다. | `current change`; 집중 Kubernetes 및 inventory 검사 44개 통과, Terraform validation 및 집중 identity contract 검사 통과 | 런타임 검증을 주장하기 전에 완전하고 release-bound인 실제 운영 Kubernetes 세대를 보존합니다. |
| 2026-08-23 | validated | 저장된 edge를 추가하거나 뒤집거나 재분류하지 않고 AKS outbound Public IP fan-in을 분리했습니다. Public IP는 정확한 Load Balancer parent와 같은 행을 유지합니다. 정확한 `AKS -> routes_to -> Public IP` path는 바깥쪽 위 port를 사용하고, 저장된 `Load Balancer -> attached_to -> Public IP` path는 가운데를 유지하며, Resource Group containment는 아래 port를 사용합니다. 세 path 모두 원래 source, target, 관계 유형, mapping 근거를 유지합니다. | `current change`; 집중 Console 검사 39개와 Console typecheck 및 production build가 통과했습니다. 인증된 표준 port 응답은 Resource 14개와 link 21개를 유지했고, canvas는 node 7개와 선택한 저장 edge 10개를 모두 유지했습니다. `1440x900`, `993x641`, `390x844`에서 중복 occurrence, collision, LR이 아닌 edge, node 교차, document overflow, workbench overflow는 모두 0개였습니다. Root 중심 오차는 8px 이내였고 mobile control은 44px를 유지했습니다. | 정확한 source에 연결된 관리되는 Browser 증적은 별도로 보존합니다. 관계 범위, inventory ontology 변환 결과의 가용성, 남은 공급자 근거 미비점은 변경되지 않습니다. |
| 2026-08-23 | validated | Resource Group 또는 Subscription의 직접 child로 이미 선택된 Resource 사이의 저장 관계를 보존했습니다. Scope 제한은 여전히 최대 36개의 직접 child link만 선택하고 숨겨진 분기를 확장하지 않지만, 정확한 child-to-child edge는 더 이상 삭제하지 않습니다. 측정한 Resource Group은 저장된 `Disk -> attached_to -> VM`과 `NIC -> attached_to -> VM` mapping을 source 또는 target을 뒤집지 않고 렌더링합니다. | `current change`; 집중 Console 검사 39개와 Console typecheck 및 production build가 통과했습니다. 인증된 응답은 Resource 26개와 link 40개를 유지했고, 범위가 제한된 canvas는 node 12개와 저장 edge 15개를 렌더링했습니다. `1440x900`, `993x641`, `390x844`에서 두 VM attachment edge는 모두 엄격한 `LR`을 유지하고 node를 교차하지 않았으며 document 또는 workbench overflow가 0개였습니다. Mobile control은 44px를 유지했습니다. | Scope-root 렌더링은 Resource 또는 관계를 추가하지 않고 기존 응답 완전성 상태를 유지합니다. 관리되는 Browser artifact 보존은 별도 작업으로 남습니다. |
| 2026-08-23 | validated | Cardinality가 높은 Resource Group이 node 38개, 저장 edge 481개 중 72개, edge-to-node 교차 196개를 렌더링한 결과를 근거로 이전 36-child Resource Group summary를 수정했습니다. 이제 scope root는 유형 우선순위에 따라 대표 child를 한 열 7행으로 표시합니다. 선택된 child 사이에서는 정확히 저장된 `attached_to` 관계만 보존하고, dependency와 routing 관계는 운영자가 해당 Resource를 선택할 때 표시합니다. 작은 Resource Group은 Disk와 NIC에서 VM으로 향하는 두 exact attachment를 계속 렌더링합니다. | `current change`; graph model 집중 검사 27개가 통과했습니다. Cardinality가 높은 인증된 응답은 Resource 200개, link 481개, `resource_limit` 불완전 상태를 유지하면서 canvas는 node 8개와 저장 containment edge 7개를 렌더링했습니다. 교차, LR이 아닌 edge, collision, document overflow, workbench overflow는 모두 0개였습니다. `993x641`과 `390x844`에서도 같은 8/7 제한을 유지했고 mobile control은 44px였습니다. 작은 Resource Group은 node 8개와 저장 edge 9개를 렌더링했으며, 엄격한 LR을 유지하는 VM attachment 2개는 node를 교차하지 않았습니다. | Summary는 대표 보기이며 완전한 Resource Group topology를 주장하지 않습니다. 운영자는 child Resource를 선택해 범위가 제한된 dependency, routing, wider relationship context를 검사합니다. |
| 2026-08-23 | validated | Instances 검색창을 정확한 Resource 자동 완성 선택에 연결하고 기본 SVG title 말풍선을 Resource 및 관계용 FDAI 그래프 도구 설명으로 교체했습니다. 표시 label이 중복되면 안정적인 Resource ID를 덧붙여 모든 제안을 선택할 수 있게 합니다. 제안을 선택하면 기존 읽기 전용 URL 선택 경로를 재사용해 선택기와 범위가 제한된 그래프를 함께 갱신합니다. | `current change`; Console 집중 검사 18개, Console typecheck, production build가 통과했고 인증된 표준 port Browser에서 제안 200개를 표시했습니다. 정확한 제안 하나를 선택했을 때 URL과 선택기가 같은 Resource를 선택했고 기본 SVG title은 0개가 됐으며 사용자 지정 도구 설명은 Resource 이름, 유형, 상태를 렌더링했습니다. Desktop, constrained desktop, mobile 검사에서 document, toolbar, workbench overflow는 모두 0개였고 mobile 입력 높이는 44px를 유지했습니다. | 그래프 근거, 완전성, 관계 방향, 권한은 변경되지 않았습니다. Activity Log, Resource Health, runtime call 근거는 계속 별도로 추적합니다. |
| 2026-08-23 | validated | 브라우저 기본 Resource datalist를 Console이 소유하는 접근 가능한 자동 완성으로 교체했습니다. 대소문자를 구분하지 않는 포함 일치로 제안을 최대 5개만 렌더링하고, 키보드 탐색에서도 정확한 Resource 선택을 유지합니다. Console이 소유하는 listbox는 Console의 surface, text, border, focus, height, overflow token을 사용합니다. 높이가 작은 desktop과 mobile layout에서는 목록을 입력 위로 열고, mobile에서는 완전한 44px 행 5개를 유지합니다. | `current change`; 집중 자동 완성 model 및 view 검사 19개, Console typecheck, production build가 통과했습니다. 인증된 표준 port Browser 검사는 `1440x900`, `993x641`, `390x844`에서 통과했습니다. 모든 viewport에서 정확히 제안 5개를 목록과 viewport 안에 렌더링했고 document 또는 explorer overflow는 0개였습니다. Desktop 목록은 최대 높이 220px를 사용했고 mobile 목록은 완전한 touch 행 5개를 위해 230px를 사용했습니다. 방향키 선택은 입력, 선택기, 읽기 전용 URL을 동기화했습니다. | 그래프 근거, 완전성, 관계 방향, 권한은 변경되지 않았습니다. Activity Log, Resource Health, runtime call 근거는 계속 별도로 추적합니다. |
| 2026-08-23 | validated | 관측된 `authorization.role-assignment` Resource를 운영자가 선택하는 인스턴스 디렉터리, 선택기, 자동 완성 및 직접 URL root에서 제외했습니다. 기반 관측 object와 접근 관계는 그래프 근거로 계속 사용할 수 있습니다. 이 표시 필터는 공급자 근거를 삭제하거나 그래프, 변경 또는 실행 권한을 바꾸지 않습니다. | `current change`; 집중 인스턴스 model 및 view 검사 20개, Console typecheck, production build가 통과했습니다. 인증된 표준 port Browser에서 기존 role-assignment URL을 선택되지 않은 Instances view로 정리했습니다. 선택기와 자동 완성에는 role-assignment 항목이 0개였고, 일반 Resource 49개와 일치하는 Container Registry 제안 4개는 page overflow 없이 계속 사용할 수 있었습니다. | 접근 근거와 공급자가 관측한 role assignment는 관계 검사를 위한 범위가 제한된 그래프 응답에 계속 남습니다. Activity Log, Resource Health, runtime call 근거는 계속 별도로 추적합니다. |
| 2026-08-23 | validated | Resource 자동 완성 범위를 5개에서 최대 10개의 제한된 일치 결과로 확장하고 Console을 컴포넌트 시안의 풍부한 선택 항목 계층에 맞췄습니다. 각 행은 간결한 유형 배지, Resource 이름, 정확한 resource type, desktop Resource label을 표시합니다. 목록은 desktop에서 480px 폭과 420px scroll 상한을 사용합니다. Mobile에서는 입력 폭을 유지하고 중복된 type label을 숨기며 touch 크기 행을 보존합니다. | `current change`; 집중 Console 검사 20개와 컴포넌트 시안 계약 검사가 통과했고 Console typecheck 및 production build도 통과했습니다. 인증된 Browser 검사는 표준 Console과 design server를 모두 확인했습니다. Desktop은 480px 목록에 풍부한 행 10개를 렌더링했고 secondary type 잘림과 page overflow가 0개였습니다. Mobile은 높이가 52px 이상인 scroll 가능 행 10개를 page overflow 없이 렌더링했습니다. 시안은 360px scroll 상한 아래에서 일치 결과 10개를 표시했습니다. 두 화면 모두 role-assignment 제안은 0개를 유지했습니다. | 정확한 선택, 키보드 동작, 그래프 근거, 완전성, 관계 방향, 권한은 변경되지 않았습니다. Activity Log, Resource Health, runtime call 근거는 계속 별도로 추적합니다. |

### 관계 하드닝 기록

| 라운드 | 검토 관점 | 확인된 최고 심각도 | 근거 및 처리 결과 |
|--------|-----------|--------------------|-------------------|
| 1 | 방향과 parent ownership | Critical, 해결됨 | AKS AgentPool의 이중 parent 8건을 재현했습니다. 이제 검토된 provider-parent containment가 같은 child의 일반 Resource Group fallback을 shadow합니다. |
| 2 | LinkType cardinality와 durable promotion | High, 해결됨 | Snapshot promotion이 여러 `contains` parent를 거부하고 ontology `replace_subgraph`가 declaration cardinality validation을 독립적으로 실행합니다. |
| 3 | 분류된 non-edge 사유 위조 | Low | Provider contract 경계에서 drop reason과 unavailable reason의 정확한 조합을 검증하며 분류되지 않은 실패는 계속 차단됩니다. |
| 4 | Provider completeness와 relationship coverage | Medium, 해결됨 | `complete`는 안전한 generation 교체를 제어하고 `relationship_complete`는 부재를 주장하지 않으면서 분류된 누락 edge를 독립적으로 보존합니다. |
| 5 | Active snapshot, status, manifest 불일치 | Medium, 해결됨 | PostgreSQL graph read는 정확한 generation 일치를 요구합니다. Status는 최종 commit marker로 유지되고 불일치는 incomplete evidence가 됩니다. |
| 6 | Resource 결과 0건의 잘못된 부재 | High, 해결됨 | 요청한 root ObjectType이 store에 전달되고 Resource 행이 0개여도 source coverage가 유지됩니다. |
| 7 | Freshness, future cutoff, clock 경계 | Medium, 해결됨 | Operator evidence가 주입된 aware clock을 사용하고 만료되거나 future-cutoff인 evidence를 incomplete로 표시하면서 정확한 cutoff와 ceiling을 유지합니다. |
| 8 | Configuration evidence와 independent verification | Medium, 해결됨 | API와 Console이 `configuration_observed`와 `independently_verified`를 분리해 configuration evidence가 verification으로 보이지 않습니다. |
| 9 | ACL, source metadata, digest binding | Medium, 해결됨 | ACL projection, filtering, link closure, immutable freezing, result digest가 source generation과 completeness를 보존합니다. |
| 10 | Rolling N/N-1 compatibility | Medium, 해결됨 | 새 receipt는 1.2를 emit하고 additive source field가 없는 1.1 payload도 보수적인 legacy default로 decode합니다. |
| 11 | Operator, Console, localization parity | Medium, 해결됨 | Strict decoder가 current, stale, unavailable 상태를 수용하고 evidence-kind와 verification의 일관성을 검증하며 영어/한국어 catalog가 같은 label을 제공합니다. |
| 12 | Concurrency, crash recovery, single writer | High, 해결됨 | Process-local lock과 PostgreSQL session advisory lock이 graph와 commit-marker write를 감싸며 failure injection으로 manifest-before-status retry recovery를 증명했습니다. |

2026-09-05 원본부터 저장소까지 재검토에서 이전 비평이 다루지 않은 High 수준의 보존 및 current
상태 공백을 확인했습니다. Sparse 변경 힌트가 완전한 overlay 속성으로 취급될 수 있고, 대기
중인 overlay 작업이 ontology 변환 결과 watermark에 결속되지 않으며, production archive I/O와
purge가 연결되지 않았습니다. 위의 제한된 이력 설계와 OI-13부터 OI-16까지가 해당 공백의 완료를
소유합니다. 이 종료 조건이 통과할 때까지 realtime ontology 최신성과 제한된 이력 보존은
진행 중입니다.
### 남은 작업

- [x] `OI-01`은 원본부터 저장소까지 구현 감사를 기록하고 모든 수집, 변환 결과, 조회,
  보존, archive 단계의 정확한 소유자, 테스트, 누락 binding을 식별합니다. 집중 감사 checker의
  테스트 3개가 통과합니다.
- [x] `OI-02`는 tenant 값을 hard-code하지 않고 검증된 원본 정책, 최신성 목표, 예산,
  우선순위, throttling 입력을 정의합니다.
- [x] `OI-03`은 적응형 due 계산을 구현하고 healthy, lagging, changing, `429`, timeout,
  circuit-open, recovery 전환을 순수 결정론적 테스트 matrix로 입증합니다.
- [x] `OI-04`는 이벤트, delta, 완전 snapshot, 중복, 재정렬, tombstone, 동시 promotion
  수렴을 객체 또는 관계 손실 없이 입증합니다.
- [x] `OI-05`는 cursor 지연, overlay 상태, 최신성, 범위, 공급자 압력, 다음 예약 작업에
  대해 principal-safe 수집 상태를 노출합니다.
- [x] `OI-06`은 의미 정책 기반 rollup을 구현하고 지원되는 모든 통계에서 0, 누락, 부분,
  충돌, 병합 동작을 입증합니다.
- [x] `OI-07`은 archive 매니페스트, 검증, 복원 sampling, 보존 hold, safe-to-retry
  purge 증적을 구현합니다. 어떤 gate가 실패해도 원본 삭제를 차단합니다.
- [x] `OI-08`은 순수 그래프 근거 refresh 정책을 구현하고 모든 `use_graph`,
  `refresh_then_query`, `use_live_evidence`, `query_archive`, `hold` 전환을 입증합니다.
- [x] `OI-09`는 범위가 제한된 실시간 근거를 observation ingress로 되돌리고, 부분 보강이
  완전 세대를 대체하거나 권한을 넓힐 수 없음을 입증합니다.
- [x] `OI-10`은 대표 질문이 답변 text 비교 없이 예상 인스턴스, 경로, 함수, 최신성 결과,
  archive 동작을 선택함을 입증합니다.
- [x] `OI-11`은 keyword routing 없이 action-draft frame 분류를 수정하고 집중 이중 언어
  positive 및 negative routing 검사와 typed no-authority 증적을 통과합니다. 전체 corpus,
  변경 중심, release 및 예약 campaign은
  [지속형 의미 보증](../interfaces/continuous-semantic-assurance-ko.md)을 따르며 OI-11 종료
  조건이 아닙니다.
- [ ] `OI-12`는 OI-11 이후 표현 회귀와 [배포 Azure 인증](https://github.com/dotnetpower/fdai/issues/262)을
  실행해 최신성, API 압력, 지연, 저장소 증가, rollup 범위, archive 복원, 공급자 실패를 측정합니다.
- [x] `OI-13`은 명시적인 전체, 부분, 변경 힌트 및 tombstone 의미를 가진 versioned 정규화
  객체 및 관계 관측 원장을 영속화합니다. 집중 중복, 재정렬, sparse 속성, 작업 상태, 재시작 및
  current 변환 결과 다이제스트 검사를 통과해야 완료됩니다.
- [x] `OI-14`는 리소스 수명 인스턴스 신원, 관계 보정 범위, late correction partition 및 활성
  case 또는 legal-hold 고정을 완료합니다. 선행 원장 및 변환 결과 watermark gate는 이제 대기
  중인 관측과 확인되지 않은 tombstone이 원본 완전성을 낮추게 합니다. 수락된 모든 보정이 영향
  범위를 무효화한 뒤 결정론적으로 닫아야 완료됩니다.
- [x] `OI-15`는 배포 보존 정책 레지스트리, 시간과 범위 partition, 검증된 checkpoint,
  production archive writer와 principal 범위 reader, 구체적인 source purger, 예약 수명 주기
  조정 및 저장소 압력 저하 동작을 결속합니다. 전용 runtime Job은 실행기 권한이 없는 inventory
  identity로 이 표면을 조립합니다. Shadow, enforce, certify, archive 중단, restore 실패, hold 및
  purge 검사는 실패한 gate가 source partition을 보존하고 완전성 의존 작업을 차단함을 입증합니다.
- [ ] `OI-16`은 고정된 개정 하나에서 안정 상태 저장소 증가 제한, exact warm replay, archive
  복원, 안전한 partition purge, N/N-1 schema replay, database 복구, hold 적용 및 false-complete
  0건을 입증하는 운영 증적을 보존합니다. 중복, 지연, 삭제, 재생성, 프로바이더 실패, database
  재시작 및 archive 중단 시나리오를 포함해야 합니다. 개발 전용 synthetic campaign, bot 요청
  기반 보호 workflow, 정확한 provenance 결속, 비공개 단계 근거 및 gate가 적용된 증적 writer는
  구현됐습니다. 모든 시나리오가 통과하지 않으면 `operationally_validated=true`를 보고하거나
  증적을 저장할 수 없습니다. 보호 campaign은 아직 실행하지 않았으므로 운영 증적은 열려 있습니다.
- [x] 표준 로컬 프로필에 `analyzer: run continuously (local)`을 제공합니다. 배포 one-shot
  analyzer CLI, 로컬 런타임 환경, 인벤토리 대상 검색, 메트릭 매핑, 멱등성 키, 이벤트 계약 및
  shadow 상태를 재사용하며 analyzer 로직을 중복하지 않습니다.
- [x] 재시작 후에도 유지되는 완료된 브로커 증적을 사용해 같은 구간의 분석기 게시 반복을
  억제하고, 감지 지연 시간, 근거 완전성, 게시 및 복구 완료를 결합하는 결정론적 같은 UID
  재시작 및 서로 다른 UID 교체 증적을 보존합니다.
- [x] 인증된 Operator API `/detection-readiness` 계열과 기존 Console 경로를 통해 Pod 실패와 복구를 보고합니다. 현재 상태, 실패 이력, 복구, 근거 공백을 분리해 유지하고, 누락, 오래됨, 불완전, 상충 근거에는 닫힘 또는 사용 불가로 실패하며, 원인도 실행 권한도 주장하지 않습니다. 하나의 리비전에 고정된 종단 간 증명이 실제 분석기, 원장, 기록기, Operator 판독기, Console 모델 경로를 구동합니다.
- [ ] [타입이 지정된 재개 가능 Kubernetes 수명 주기 수집](https://github.com/dotnetpower/fdai/issues/292)을 완료하고 보존된 이전/신규 UID 및 종료 관측을 교체 축약기에 연결한 뒤 인증된 정확한 대상 교체 및 새 기준 시점 복구 증적을 보존합니다.
- [x] 저장된 mapping별 모든 relationship candidate를 해결하거나 검토된 unavailable 상태로
  분류합니다. 최종 세대에는 classification 9개와 candidate 66개가 있습니다.
  `target_outside_active_generation` 10개, `target_provider_type_unmodeled` 40개,
  `reference_not_observed` 16개입니다. Communication endpoint 3개는 정확한 verified edge가
  됐습니다. 접근 가능한 모든 subscription을 대상으로 한 읽기 전용 ARG 대조에서 누락된 AKS
  managed endpoint 또는 cross-subscription subnet target은 발견되지 않았고, unavailable
  target을 위해 edge를 조작하지 않았습니다.
- [ ] [다섯 service-root `POSTGRES_HOST` 입력을 모두 배포하고](https://github.com/dotnetpower/fdai/issues/262)
  각 workload에서 PostgreSQL로 향하는 exact dependency 세대 근거를 보존합니다. Secret 이름,
  환경 변수 이름, secret 값, 적용되지 않은 Terraform은 유효한 runtime 근거가 아닙니다.
- [x] 정확한 Private Endpoint에서 zone-group으로 향하는 containment edge 21개와
  zone-group에서 zone으로 향하는 attachment 21개로 Private DNS path를 완성했습니다. 인증된
  node 3개와 edge 2개의 DNS focus는 경쟁하는 Resource Group parent 없이 검토된 두 mapping과
  완전한 직접 근거를 노출합니다.
- [x] 정확한 Container workload registry 의미와 interaction 근거를 보존합니다. Registry
  구성이 있는 App 9개와 Job 11개가 모두 dependency로 변환되고, 가장 큰 registry는 incoming
  workload 16개를 표시하며 zoom, fit, 고정-node pan으로 전체 fan-in을 검사할 수 있습니다.
- [x] Inventory projection commit 레코드를 content-addressed 방식으로 유지합니다. Manifest
  digest는 release-bound status marker와 공유되며, 재시작 후 혼합되었거나 변조된 generation은
  reader가 거부합니다.
- [x] 추론된 edge 없이 부분 Kubernetes topology를 유지합니다. 관찰된 cluster, namespace,
  pool, node, workload, Service, endpoint, Ingress 레코드는 검토된 endpoint가 없을 때에도
  유지되며, 누락된 relationship은 unavailable 증적으로 보고됩니다.
- [x] Role assignment 225개, scope attachment 185개, Managed Identity attachment 106개로
  검증된 Azure 범위를 넘어 로컬 authorization 근거 계약을 완료합니다. 모델링되지 않은 child
  scope는 `authorization_child_scope_unmodeled`를 보존하고, 타입 지정 principal-safe PostgreSQL
  role 근거는 Resource `depends_on` edge를 만들지 않고 Azure RBAC와 분리됩니다.
- [x] 검토된 `runtime_calls` LinkType과 exact endpoint, scope, cutoff, freshness, active-generation,
  exact-release, no-authority 검사를 수행하는 순수 projector를 추가합니다.
- [x] 타입 지정 runtime-call telemetry producer를 기존 inventory single writer에 binding합니다.
  예약 경로는 인증된 source가 두 exact endpoint Resource ID를 모두 제공할 때까지
  `telemetry_source_unavailable`을 기록하고 edge를 추가하지 않습니다.
- [ ] [인증된 `8010` 및 `5273` runtime-call 근거를 보존합니다](https://github.com/dotnetpower/fdai/issues/260).
  Push되고 green인 SHA를 사용하며 이름, group, 환경 변수, credential, RBAC 기반 endpoint 추론은
  계속 거부합니다.
- [ ] 안정적인 분석기 이벤트 ID를 키로 브로커나 다운스트림 중복 제거 저장소를 읽는 게시 조정기를
  바인딩합니다. 그전까지 불확실한 청구는 `publication_reconciler_unbound`를 보고하고 다시 게시하지
  않은 채 조정 대기 상태로 남습니다.
- [ ] `build_pod_lifecycle_evidence_source` 뒤에 실제 Kubernetes Pod 수명 주기 근거 원본을
  바인딩합니다. 그전까지 Pod 발견 사항은 `FDAI_POD_LIFECYCLE_EVIDENCE_JSON`으로 제공된 근거에만
  존재하며 배포 환경의 Pod 분석은 계속 사용할 수 없습니다.

## 운영 상태 전이 원장

FDAI는 의미가 부여된 상태 변경을 Core 소유의 추가 전용 PostgreSQL 원장에 저장합니다.
Event Hubs는 관측을 전달하고 OpenTelemetry는 진단을 보고하며, 온톨로지는 다시 만들 수 있는
현재 상태 변환 결과로 유지됩니다. 이러한 표면은 상태 전이 원장을 대신하지 않습니다.

각 원자적 배치는 콘텐츠 주소가 지정된 상태 전이 0개 이상과 양의 커버리지 레코드 1개 이상을
포함합니다. 상태 전이는 `from_state`, `to_state`, 유효 시각, 기록 시각, 근거 기준 시점, 원본
신원과 개정, 생산자 버전, 최신성, 완전성, 충돌, 근거 참조를 결합합니다. 다시 전달된 멱등성
키는 콘텐츠가 같을 때만 변경 없는 처리로 끝납니다.

인벤토리 승격 경로는 `resource.operational_state` 변경을 기록합니다. 이 경로는 구간을
`initial_state_only` 또는 `snapshot_interval_only`로 표시합니다. 완전한 조정 스냅샷도 중간
상태 전이가 없었다는 사실을 증명하지 못합니다. 향후 지속형 원본은 정확히 보존된 워터마크와
완전한 구간 근거가 있을 때만 커버리지를 높일 수 있습니다.

## 관련 문서

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| 온톨로지 권한과 상태 lane | [FDAI 운영 온톨로지](operating-ontology-ko.md) |
| 런타임 topology와 서비스 경계 | [프로젝트 구조](project-structure-ko.md) |
| Semantic query planning | [온톨로지 쿼리 범위 구현 계획](../interfaces/ontology-query-coverage-implementation-plan-ko.md) |
| 지속형 semantic 검증 | [지속형 의미 보증](../interfaces/continuous-semantic-assurance-ko.md) |
| 관측 및 감지 전달 | [관찰 가능성 및 감지](../rules-and-detection/observability-and-detection-ko.md) |
