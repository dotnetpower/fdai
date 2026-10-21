---
translation_of: continuous-operational-instance-graph-evidence.md
translation_source_sha: 103fc4772c3080206683d3519813fd3a8153f477
translation_revised: 2026-10-21
---

# 지속형 운영 인스턴스 그래프 근거

이 문서는 지속형 그래프의 원본부터 저장소까지 구현 감사와 운영 상태 전이 근거를 기록합니다. 상위 문서는 수집, 보존, 조회 의미 체계를 담당합니다.

## 설계 개요

이 문서는 [continuous-operational-instance-graph-ko.md](continuous-operational-instance-graph-ko.md)에 포함되어 있던 상세 계약을 그대로 보존하는 집중 소유 문서입니다.

## 원본부터 저장소까지 구현 감사

OI-01은 각 단계의 정확한 코드 소유자, 런타임 또는 저장소 binding, 집중 테스트, 상태, 누락
binding을
[`config/continuous-operational-instance-graph-audit.json`](../../../config/continuous-operational-instance-graph-audit.json)에
기록합니다. Architecture checker는 단계 누락, 근거 경로 누락, 소유자가 없는 구현 작업,
일부만 연결되거나 연결되지 않은 binding을 가진 implemented 단계, 정확한 공백을 명시하지 않은
열린 단계를 거부합니다. 인증 범위는 합성 작동 방식, 배포 binding, 프로덕션 데이터 검증을 별도로
기록하므로 보호된 합성 campaign 하나가 일반 프로덕션 보존을 인증할 수 없습니다. 정본 소유권은
이 설계에서 검증하고 구현 상태와 남은 작업은 연결된 전달 원장에서 검증합니다.

| 단계 | 상태 | 감사 결과 |
|------|------|-----------|
| 공급자 push ingress | implemented | Event Grid 쓰기와 삭제가 raw Event Hub에 도달하고 `_consume_resource_changes`가 정식 inventory 이벤트로 정규화합니다. |
| 재개 가능한 delta cursor | implemented | `forward_inventory_delta`는 final fence 이후에만 durable Activity Log cursor를 전진시킵니다. |
| 완전 reconciliation | implemented | `InventorySyncCoordinator.run`은 범위가 제한된 ARG 또는 ARM 관측을 준비하고 완전한 stream만 수락합니다. 프로바이더, 출처와 보강 단계 및 기존 1 MiB 저장 청크의 바이트 검사는 JSON 형태 레코드를 복사하거나 정규화하거나 문자열 전체를 인코딩하기 전에 크기를 확인하며 내용을 자르지 않습니다. [정규화 레코드의 메모리 할당 사전 검사](../interfaces/azure-resource-discovery-commands-ko.md#정규화-레코드의-메모리-할당-사전-검사)는 기존 인코더의 정확한 계산을 유지하고 남은 할당 제한을 명시합니다. |
| 정규화된 observation ingress | implemented | `PostgresInventoryDeltaProjector.__call__`은 타입이 지정된 관측 의미를 검증하고 기존 overlay를 갱신하기 전에 Core 소유 추가 전용 관측 원장에 이중 기록합니다. |
| Snapshot promotion | implemented | `PostgresInventorySnapshotStore.promote`는 promotion lock 아래에서 활성 세대를 원자적으로 전진시키고 정확한 Resource 및 Link 개수를 기록합니다. Operator 활동 읽기는 이 불변 요약을 사용하고, 개수가 없는 혼합 버전 행에만 범위가 제한된 하위 행 집계를 사용합니다. |
| Realtime overlay | implemented | PostgreSQL overlay 행은 유효 시각과 내용 신원에 따라 정규화된 관측을 replay하고, 선언된 속성 마스크만 병합하며, 관측하지 않은 snapshot 속성을 보존하고, 완전한 reconciliation 전에는 tombstone 후보를 대기 상태로 유지합니다. |
| 온톨로지 변환 결과 | implemented | `InventoryOntologyProjector.apply`는 인벤토리가 소유한 Resource 및 Link 하위 그래프의 단일 작성자입니다. 검토된 중첩 운영 상태 필드는 관측 메타데이터와 함께 상위 속성으로 올리며, 원장과 변환 결과 워터마크 및 대기 중인 tombstone은 각각 원본 완전성을 낮춥니다. |
| Topology history | implemented | `InventoryTopologyHistoryPublisher.publish`는 Core 소유 bitemporal PostgreSQL store 및 migration을 통해 완전 baseline을 추가합니다. |
| Graph-first query | implemented | 일반 exact-target 현재 상태 조회는 secured graph를 먼저 읽고 검증된 읽기 전용 부분 결과와 명시적인 안내를 제시하며, 안전한 부분 집합이 없으면 판단을 보류합니다. |
| 범위가 제한된 live read | implemented | 정확한 secured Resource 하나만 고정된 한도 아래 server-scoped provider read를 최대 한 번 실행할 수 있습니다. 더 넓거나 malformed 또는 unresolved 조회는 거절하거나 hold합니다. 정확한 revision 인증은 공유 DNS를 변경하지 않고 정상 hostname 검증을 유지하면서 작업 전용 비공개 엔드포인트 주소를 통해 권한 없는 증적을 저장합니다. 지연된 최선형 SSL 종료는 이미 검증된 handshake를 무효화하지 않으며 PostgreSQL TLS는 협상된 프로토콜과 `pg_stat_ssl`로 입증합니다. |
| Live evidence write-through | implemented | 검증된 live evidence는 속성 마스크 및 내용에 결속된 idempotency와 함께 정식 타입 지정 부분 overlay ingress에 들어가며 관측되지 않은 속성이나 관계를 삭제할 수 없습니다. |
| 적응형 일정 관리 | implemented | 검증된 source policy와 순수 reducer가 freshness, lag, demand, provider pressure, `Retry-After`, 남은 budget, concurrency, circuit-open 상태, recovery probe를 사용합니다. PostgreSQL은 durable due 상태를 제공하고 principal-safe health projection은 다음 bounded action을 노출합니다. |
| Retention 및 hold | implemented | Archive purge coordinator는 정확한 verification, restore sampling, retention 또는 legal hold 평가가 통과하기 전까지 삭제를 차단합니다. Append-only PostgreSQL receipt는 blocked, pending, failed, successful, retry 결과를 보존합니다. |
| 타입 지정 rollup | implemented | Fact별 policy가 gauge, counter, categorical state, relationship change, evidence health를 분리해 집계하면서 source와 generation 계보, bitemporal 범위, 누락 구간, 관측된 0, 충돌, 완전성, 병합 가능한 count와 sum을 보존합니다. Percentile은 unavailable로 유지합니다. |
| Archive lifecycle | in-progress | Content-addressed 매니페스트, 비공개 Azure Blob 입출력, principal 범위 읽기, 데이터베이스 게이트 기반 purge, 추가 전용 수명 주기 증적을 구현했습니다. Container Apps와 AKS는 고정 `shadow` 작업을 예약합니다. Non-shadow 시작은 상태 또는 Blob 접근 전에 정확히 저장된 인증 증적을 요구합니다. 보존된 OI-16 증적은 합성 작동 방식과 배포 binding을 검증하지만 반복되는 프로덕션 데이터 보존은 아직 검증되지 않았으며 별도 승인이 필요합니다. |

보호된 증적 readback은 배포 실행기 VNet에 연결된 ops 소유의 Blob 비공개 DNS 영역에서
storage 계정 전용 record를 해석합니다. Workload 해석은 앱 소유 영역에 유지합니다. 이
분리는 공용 네트워크 접근이나 storage key 인증 권한을 부여하지 않습니다.

## 변환 결과의 메모리 할당 사전 검사

인벤토리를 변환하는 순수 함수는 속성 복사, 관측 판정, 그래프 객체 생성 전에 펼쳐진 값
2,000,000개(컨테이너와 매핑 키 포함)와 문자열에 포함된 문자 16,777,216개까지만 허용합니다.
정규화 과정에서 같은 참조가
여러 번 펼쳐지므로 나타날 때마다 계산합니다. 순환 참조나 과도한 입력 깊이는 명시적인
오류로 보류합니다. 기존 리소스/링크 개수 제한과 정규 값 검사도 그대로 적용됩니다.
작은 컨테이너가 많이 들어 있으면 기존 바이트 허용량 안에서도 이 정규화 작업량을 넘을 수 있습니다.

이는 명시적인 작업량 계수이며, 얕은 객체 크기의 가중 추정치, 인코딩된 JSON 크기,
최대 메모리 할당량 또는 프로세스 RSS가 아닙니다. 수집 단계의 정규화된 세대 허용량 16 MiB와
영속 청크 제한 1 MiB를 대체하지 않습니다. 실패하면 부분적인 변환 결과를 반환하지 않으며
원본, 승격 또는 실행 권한도 부여하지 않습니다. 스냅샷과 파생 그래프의 담당 경계는 분리됩니다.

권위 있는 [보존된 개념 평가](../../roadmap-implementation/interfaces/azure-resource-discovery-commands.md#retained-concept-assessment-2111)는
3분류 스파이크 평가(이미 구현됨, 대체됨, 재현 가능한 잔여)를 완결합니다. 스냅샷 저장소도 정규 JSON
매핑의 복사 전 1 MiB 바이트 상한, `jsonb_to_recordset` SQL 배치당 누적 UTF-8 전송 바이트 4 MiB
상한, 봉인 전 변환 작업량 허용 검사, 승격 시 잠긴 영속 후보 행의 신원 및 시간 구간 검증을
강제합니다. 독립 발급자와 전체 구간의 가시성 증명, 재시작 후에도 유지되는 공유 요청/바이트 및 대기
시간 허용 예산, 세대 내 동등 읽기 재사용, 배포 환경의 최대 RSS 검증은 재현 가능한 잔여로 분류하여
#2329, #1393 및 항목 04, 13, 14, 17, 31에서 후속 추적합니다.

## 수집 인증 구성

ARG/ARM의 유효한 수집 구성에는 이제 기존 어댑터에 구성된 인증 모드와 선택자의 비밀 값이
없는 다이제스트가 포함됩니다. 기존 PostgreSQL 준비 후보와 미완료 청크 리더는 구성된
클라이언트/백엔드 선택자가 바뀌면 재사용하지 않습니다. 유효한 입력이 같으면 원래 시도를
유지합니다. 이는 구성 연속성이며 인증된 principal 신원이나 권한을 입증하지 않습니다.
알 수 없는 주입 ID 어댑터는 바인딩되지 않은 상태입니다.
[제한된 수정과 비평](../interfaces/azure-resource-discovery-commands-ko.md#제한된-수정-구성된-인증-선택자의-연속성)에서
포함하는 선택자와 제외하는 자격 증명을 정의합니다. 영구 보존형 공유 허용 예산, 전체 구간의
신원 입증 및 실제 설치의 사용량 검증은 #2329와 #1393에서 계속 미완료 상태입니다.

## 운영 상태 전이 원장

FDAI는 의미가 부여된 상태 변경을 Core 소유의 추가 전용 PostgreSQL 원장에 저장합니다.
Event Hubs는 관측을 전달하고 OpenTelemetry는 진단을 보고하며, 온톨로지는 다시 만들 수 있는
현재 상태 변환 결과로 유지됩니다. 이러한 표면은 상태 전이 원장을 대신하지 않습니다.

각 원자적 배치는 콘텐츠 주소가 지정된 상태 전이 0개 이상과 양의 커버리지 레코드 1개 이상을
포함합니다. 상태 전이는 `from_state`, `to_state`, 유효 시각, 기록 시각, 근거 기준 시점, 원본
신원과 개정, 생산자 버전, 최신성, 완전성, 충돌, 근거 참조를 결합합니다. 다시 전달된 멱등성
키는 콘텐츠가 같을 때만 변경 없는 처리로 끝납니다.
커버리지 식별자는 전역 콘텐츠 주소입니다. 복구된 배치는 두 번째 행을 삽입하지 않고도 동일하게
보존된 커버리지 레코드를 참조할 수 있으며, replay는 자식이 해당 배치에서 처음 삽입됐다고
요구하는 대신 예상한 각 자식을 콘텐츠 식별자로 검증합니다.

인벤토리 경로는 속성 수준 근거가 있는 운영 및 가용성 변경만 기록합니다. 프로비저닝은 같은
출처 정보가 생길 때까지 현재 상태로만 유지합니다. 모든 구간은 `initial_state_only` 또는
`snapshot_interval_only`이며, 완전한 스냅샷도 중간 전이 부재를 증명하지 못합니다. 정확히
보존된 워터마크만 해당 커버리지를 높일 수 있습니다.

## 관련 문서

| 알아볼 내용 | 문서 |
|-------------|------|
| 상위 설계 | [지속형 운영 인스턴스 그래프](continuous-operational-instance-graph-ko.md) |
| 제공 상태 및 남은 작업 | [구현 원장](../../roadmap-implementation/architecture/continuous-operational-instance-graph-evidence.md) |
