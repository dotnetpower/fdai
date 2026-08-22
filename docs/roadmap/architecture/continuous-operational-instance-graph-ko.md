---
translation_of: continuous-operational-instance-graph.md
translation_source_sha: 2f6bbc97782e2d9db9305d02fa283620325765f0
translation_revised: 2026-08-22
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
3. 누락 이벤트를 찾고 관계를 복구하며 범위 완전성을 증명하기 위해 범위가 제한된
   reconciliation을 실행합니다.
4. inventory 원본이 제공할 수 없는 근거 유형이나 검증된 쿼리가 현재 그래프보다 최신인
   근거를 요구할 때만 정확한 실시간 조회를 실행합니다.

지속형은 수집에 항상 durable한 다음 작업이 있음을 뜻합니다. 하나의 끝나지 않는 프로세스를
요구하지 않습니다. 이벤트 소비자는 활성 상태를 유지할 수 있고, cursor 및 reconciliation
작업자는 진행 상황을 저장한 후 양보하거나 0으로 확장되는 safe-to-retry 일회성 작업으로
실행할 수 있습니다.

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
그래프가 최신이고 변경량이 낮으면 최대 노후 목표를 넘지 않는 범위에서 간격을 늘립니다.
HTTP `429`와 공급자 throttling은 동시성을 줄이고 `Retry-After`를 따릅니다. 지속적인 사용
불가는 circuit을 열고 최신성을 사용 불가로 표시하며 계속 재시도하는 대신 범위가 제한된
probe를 예약합니다.

구성은 배포 값을 제공합니다. 저장소 기본값과 테스트는 안전한 범위를 정의하며, 하나의 간격이
모든 tenant 또는 공급자 API에 적합하다고 주장하지 않습니다.

### 수렴과 삭제

실시간 delta는 최신성을 높이지만 전역 완전성을 증명하지 않습니다. 완전한 reconciliation
세대는 포함된 overlay를 닫고 삭제를 확인하는 권위로 유지됩니다. promotion은 원자적이며,
부분 또는 충돌 세대는 이전 완전 그래프를 대체할 수 없습니다.

리소스와 관계 변경은 논리 리소스별로 정렬합니다. 중복 전달은 no-op이고, 오래된 cursor 또는
이전 이벤트는 인스턴스를 뒤로 이동시킬 수 없습니다. Tombstone은 원본, 유효 시간, 세대,
archive 계보를 유지합니다.

## 보존, rollup, archive

### 저장 계층

| 계층 | 내용 | 조회 동작 |
|------|------|-----------|
| Hot | 현재 객체와 링크, 최신성 상태, 활성 overlay, 최근의 정확한 관측 | 기본 운영 조회 경로입니다. |
| Warm | 구성된 상세 보존 구간의 bitemporal 원시 관측, 수정본, tombstone, reconciliation 증적 | 범위가 제한된 최근 이력, replay, topology 비교에 사용합니다. |
| Rollup | 타입이 지정된 시간별, 일별 또는 정책 선택 집계와 원본 범위 및 완전성 | 정확한 이벤트가 필요하지 않은 장기 추세에 사용합니다. |
| Archive | 변경 불가능하게 압축된 partition, content-addressed 매니페스트, 출처, 보존 등급, 복원 metadata | 명시적인 이력 검색 경로에서만 읽습니다. |

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
| 정규화된 observation ingress | implemented | `PostgresInventoryDeltaProjector.__call__`은 Huginn discovery 경로가 사용하는 durable 정규화 변경 writer입니다. |
| Snapshot promotion | implemented | `PostgresInventorySnapshotStore.promote`는 promotion lock 아래에서 활성 세대를 원자적으로 전진시킵니다. |
| Realtime overlay | implemented | PostgreSQL overlay 행은 리소스별로 정렬되고 활성 snapshot과 병합되며, 완전 snapshot이 포함한 경우에만 정리됩니다. |
| Ontology projection | implemented | `InventoryOntologyProjector.apply`는 inventory가 소유한 Resource 및 Link 하위 그래프의 단일 writer입니다. |
| Topology history | implemented | `InventoryTopologyHistoryPublisher.publish`는 Core 소유 bitemporal PostgreSQL store 및 migration을 통해 완전 baseline을 추가합니다. |
| Graph-first query | in-progress | 보안이 적용된 ObjectSet query는 현재 graph를 읽지만 문서화된 최신성 결과 5개를 선택하는 policy가 없습니다. |
| 범위가 제한된 live read | in-progress | Resource-state shadow read가 존재하지만 일반 semantic query는 graph 근거 refresh policy를 통해 이를 선택하지 않습니다. |
| Live evidence write-through | not-started | 성공한 범위 제한 live read를 정식 observation ingress와 realtime overlay로 다시 게시하는 owner가 없습니다. |
| 적응형 일정 관리 | in-progress | Durable age, change demand, abandonment, failure backoff는 구현됐지만 freshness, lag, quota, `Retry-After`, endpoint concurrency, circuit recovery는 입력이 아닙니다. |
| Retention 및 hold | not-started | 운영 그래프 retention policy, hold registry, 삭제 gate, durable purge receipt가 없습니다. |
| 타입 지정 rollup | not-started | 범위, 누락 구간, 관측된 0, 충돌, 병합 가능 통계를 보존하는 semantic rollup policy 또는 store가 없습니다. |
| Archive lifecycle | not-started | Immutable partition, 검증된 manifest, restore sampler, hot archive index, hold check, safe-to-retry purge 경로가 없습니다. |

## 구현 상태

### 구현 범위

| 영역 | 상태 | 근거 | 참고 |
|------|------|------|------|
| Push 이벤트와 durable delta overlay | implemented | `delivery/azure/activity_log.py`, 실시간 inventory projector와 집중 테스트 | 리소스 변경은 범위가 제한된 overlay를 업데이트할 수 있습니다. 배포 근거는 별도입니다. |
| 완전한 inventory promotion과 ontology 변환 결과 | implemented | `delivery/inventory_sync.py`, `runtime/inventory_ontology.py`, 집중 inventory 및 변환 결과 테스트 | 완전 세대가 소유된 하위 그래프를 원자적으로 대체합니다. 기존 정기 cadence는 목표 지속형 정책이 아닙니다. |
| Bitemporal topology 이력 | implemented | `core/ontology_platform/topology_history.py`, PostgreSQL topology 이력 adapter와 집중 테스트 | 현재 production 보존, rollup, archive, 복원 근거는 열려 있습니다. |
| 적응형 지속 일정 관리 | in-progress | durable due 상태, cursor, 조기 reconciliation, backoff, 범위가 제한된 scan 기반 | 고정 정기 reconciliation이 구성에 남아 있고, 측정된 적응형 최신성 controller가 수정된 계약을 증명하지 않았습니다. |
| 타입 지정 rollup과 archive lifecycle | not-started | 이 설계 계약 | 원본 범위가 연결된 rollup, archive 매니페스트, 복원 검증, purge 증적은 입증되지 않았습니다. |
| 그래프 우선 조건부 실시간 보강 | in-progress | Semantic runtime, Azure read investigation, 최신성 metadata, shadow 비교 | 조각은 존재하지만 하나의 결정론적 refresh 정책과 관측 write-through 경로가 종단으로 완성되지 않았습니다. |
| 운영 및 semantic 인증 | not-started | 이 문서의 OI 작업 패키지 | 구조 catalog 테스트와 transport 준비 상태는 지속적으로 갱신되는 인스턴스나 질문-인스턴스 해결을 증명하지 않습니다. |
| 원본부터 저장소까지 구현 감사 | implemented | `config/continuous-operational-instance-graph-audit.json`, `check-continuous-operational-instance-graph-audit.py`, 집중 감사 테스트(`3 passed`) | OI-01은 runtime validation을 주장하지 않고 15개 단계의 정확한 owner, binding, 집중 테스트, 상태, 누락 binding을 고정합니다. |

### 구현 이력

| 날짜 | 상태 | 변경 | 근거 | 남은 작업 |
|------|------|------|------|-----------|
| 2026-08-22 | in-progress | 지속형 운영 인스턴스 그래프 계약을 도입했습니다. 고정 6시간 최신성 목표를 이벤트 기반 및 적응형 범위 제한 수집으로 바꾸고, 타입 지정 rollup, 검증된 archive, 복원, purge 요구 사항을 추가했습니다. | `current change`, 쌍을 이루는 설계 문서와 집중 문서 gate | 집중 구현 및 운영 근거로 OI-01부터 OI-12까지 완료합니다. |
| 2026-08-22 | implemented | Machine-readable 15단계 source-to-store 감사와 owner, binding, test, state, missing-gap 근거를 확인하는 결정론적 checker로 OI-01을 완료했습니다. | `current change`, 감사 record, checker, 집중 감사 테스트(`3 passed`) | 검증된 source-policy 선언으로 OI-02를 시작합니다. 적응형 control, rollup, archive, live write-through는 각각을 소유한 이후 패키지에 남깁니다. |

### 남은 작업

- [x] `OI-01`은 원본부터 저장소까지 구현 감사를 기록하고 모든 수집, 변환 결과, 조회,
  보존, archive 단계의 정확한 소유자, 테스트, 누락 binding을 식별합니다. 집중 감사 checker의
  테스트 3개가 통과합니다.
- [ ] `OI-02`는 tenant 값을 hard-code하지 않고 검증된 원본 정책, 최신성 목표, 예산,
  우선순위, throttling 입력을 정의합니다.
- [ ] `OI-03`은 적응형 due 계산을 구현하고 healthy, lagging, changing, `429`, timeout,
  circuit-open, recovery 전환을 순수 결정론적 테스트 matrix로 입증합니다.
- [ ] `OI-04`는 이벤트, delta, 완전 snapshot, 중복, 재정렬, tombstone, 동시 promotion
  수렴을 객체 또는 관계 손실 없이 입증합니다.
- [ ] `OI-05`는 cursor 지연, overlay 상태, 최신성, 범위, 공급자 압력, 다음 예약 작업에
  대해 principal-safe 수집 상태를 노출합니다.
- [ ] `OI-06`은 의미 정책 기반 rollup을 구현하고 지원되는 모든 통계에서 0, 누락, 부분,
  충돌, 병합 동작을 입증합니다.
- [ ] `OI-07`은 archive 매니페스트, 검증, 복원 sampling, 보존 hold, safe-to-retry
  purge 증적을 구현합니다. 어떤 gate가 실패해도 원본 삭제를 차단합니다.
- [ ] `OI-08`은 순수 그래프 근거 refresh 정책을 구현하고 모든 `use_graph`,
  `refresh_then_query`, `use_live_evidence`, `query_archive`, `hold` 전환을 입증합니다.
- [ ] `OI-09`는 범위가 제한된 실시간 근거를 observation ingress로 되돌리고, 부분 보강이
  완전 세대를 대체하거나 권한을 넓힐 수 없음을 입증합니다.
- [ ] `OI-10`은 대표 질문이 답변 text 비교 없이 예상 인스턴스, 경로, 함수, 최신성 결과,
  archive 동작을 선택함을 입증합니다.
- [ ] `OI-11`은 OI-01부터 OI-10이 통과한 후에만 영어와 한국어로 35개 논리 canonical
  expectation을 실행하고 타입이 지정된 무권한 증적을 보존합니다.
- [ ] `OI-12`는 canonical competency matrix가 통과한 후에만 표현 회귀와 배포 Azure 인증을
  실행합니다. 최신성, API 압력, 지연, 저장소 증가, rollup 범위, archive 복원, 공급자 실패
  동작을 측정합니다.

## 관련 문서

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| 온톨로지 권한과 상태 lane | [FDAI 운영 온톨로지](operating-ontology-ko.md) |
| 런타임 topology와 서비스 경계 | [프로젝트 구조](project-structure-ko.md) |
| Semantic query planning | [온톨로지 쿼리 범위 구현 계획](../interfaces/ontology-query-coverage-implementation-plan-ko.md) |
| 관측 및 감지 전달 | [관찰 가능성 및 감지](../rules-and-detection/observability-and-detection-ko.md) |
