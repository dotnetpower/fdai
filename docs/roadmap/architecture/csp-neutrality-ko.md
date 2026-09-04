---
title: CSP-중립성 계약
translation_of: csp-neutrality.md
translation_source_sha: 0f1d5ce4229cc087258f59eb30e0e58912f32c3e
translation_revised: 2026-09-04
---

# CSP-중립성 계약

[Azure 가 유일한 구현 대상](../../../.github/copilot-instructions.md#implementation-focus-must)
임에도 코어를 CSP-중립으로 유지하는 구체적인 **계약(contracts)** 을 명명합니다. 계약은
와이어 수준(프로토콜, 아티팩트, 토큰 포맷)이므로 미래의 비-Azure 어댑터는 코어 재작성이 아니라
**추가 구성** 으로 붙습니다.

토폴로지는 [app-shape.instructions.md](../../../.github/instructions/app-shape.instructions.md),
모듈 경계는 [project-structure-ko.md](project-structure-ko.md), 기술 선택은
[tech-stack-ko.md](tech-stack-ko.md), 신원 모델은 [security-and-identity-ko.md](security-and-identity-ko.md)
를 보완합니다.

## 구현 상태

### 구현 범위

| 영역 | 상태 | 근거 | 참고 |
|------|------|------|------|
| 이벤트 버스, 런타임, 시크릿 및 워크로드 신원 계약 | implemented | `shared/providers/`; `delivery/azure/`; `infra/modules/event-bus/`; `infra/modules/compute/`; `infra/modules/secret-store/`; 집중 어댑터 및 인프라 테스트 | Azure는 프로바이더 중립 계약 뒤에서 Event Hubs의 Kafka, OCI Container Apps, native 시크릿 참조 및 워크로드 신원을 사용합니다. |
| 인벤토리 수집, 완전 세대 관계 및 범위가 제한된 그래프 변환 결과 | implemented | `shared/providers/inventory.py`; `delivery/azure/generation_relationships.py`; `delivery/inventory_sync.py`; `delivery/inventory_live_evidence.py`; `core/ontology_platform/graph_evidence_refresh.py`; 집중 인벤토리, 관계, 새로 고침 및 변환 결과 테스트 | 지속 수집, 정확한 관계 근거와 명시적 누락 사유, 원자적 승격, 그래프 우선 새로 고침 결정, 안전한 실제 근거 반영 및 범위가 제한된 읽기 변환 결과를 구현했습니다. 일반 의미 쿼리 조립은 아직 새로 고침 선택과 실제 근거 반영을 종단 간 연결하지 않습니다. 배포 완전성은 별도의 검증 근거입니다. |
| 메트릭, 로그 및 추적 조회 계약 | implemented | `shared/providers/metric.py`; `log_query.py`; `trace_query.py`; `delivery/azure/metric_logs.py`; `delivery/azure/log_query.py`; `delivery/azure/telemetry_query.py` | Azure Monitor 및 Log Analytics 어댑터가 있으며 구성이 없으면 의도적으로 no-op 바인딩을 유지합니다. |
| WARA 범위 제한 평가 읽기 | implemented | `shared/providers/wara_assessment.py`; `delivery/azure/wara_observation.py`; 정확한 평가기 overlay 및 집중 어댑터 테스트 | Azure Resource Graph 읽기는 정확한 검토 쿼리, 평가기, ARM 리소스 범위, 프로바이더 종류, 페이지/행/바이트 상한, 승인된 관리 원본 및 결정론적인 권한 없는 증적에 고정됩니다. |
| 8개 계약 전체의 통제된 운영 근거 | in-progress | [배포 및 온보딩 구현 상태](../deployment/deploy-and-onboard-ko.md#구현-상태); `delivery/azure/` 아래의 관측 캠페인 어댑터 | 독립 서비스 배포는 검증됐지만 이 소유 문서는 모든 인벤토리와 텔레메트리 계약을 함께 입증하는 최신 통제 캠페인을 하나로 보존하지 않습니다. |
| 비-Azure 프로바이더 구현 | deferred | [구현 Focus](../../../.github/copilot-instructions.md#implementation-focus-must) | 이식성을 위해 계약 형태를 유지합니다. AWS, GCP 또는 다른 프로바이더 어댑터는 승인된 구현 범위에 없습니다. |

### 구현 이력

| 날짜 | 상태 | 변경 | 근거 | 남은 작업 |
|------|------|------|------|-----------|
| 2026-09-04 | implemented | 프로바이더 중립 관측 계약 뒤에 정확한 WARA 평가 읽기를 위한 Azure 어댑터를 추가했습니다. 수정 권한을 추가하지 않고 승인된 토큰 대상, 정확한 리소스 범위, 쿼리 및 평가기 다이제스트, 범위가 제한된 결정론적 증적을 결속합니다. | `current change`; 집중 WARA overlay, 런타임, Azure 어댑터, Ruff 및 strict mypy 검사입니다. | 운영 검증을 주장하기 전에 별도 권한이 있는 실제 Azure shadow 증적을 보존합니다. |
| 2026-08-19 | implemented | 예약된 프로바이더 신원을 위한 scheduled 인벤토리 reconciliation CLI를 composition binding과 일치시켰습니다. CLI는 이미 프로바이더 범위 coverage를 연결했지만 범위가 제한된 unmapped-resource callback을 누락했으므로, 조립된 adapter와 달리 ARG source가 identity-complete 1.1 fence를 만들 수 없었습니다. 이제 ARG는 두 callback을 모두 binding하고 ARM fallback은 둘 다 binding하지 않습니다. | [이슈 #217](https://github.com/dotnetpower/fdai/issues/217). Source별 wiring 회귀와 전체 인벤토리 작업 구성 파일의 focused case 18개, 작업 범위 Ruff 및 strict mypy가 통과했습니다. | 이 revision에서 새로운 전체 reconciliation을 승격하고 1.1 coverage 증적, snapshot-ontology identity parity 및 빈 realtime overlay를 확인합니다. |
| 2026-08-19 | validated | 운영 범위 coverage를 인증된 읽기 전용 인벤토리 그래프 경로에 연결했습니다. 범위가 제한된 응답의 각 Resource는 `service_ref`를 포함합니다. 검토된 mapping이 없거나 충돌하면 `unknown_service`가 되며, 입력이 잘리거나 대응되지 않은 결과가 하나라도 있으면 명시적 gap과 함께 응답을 강등합니다. | [이슈 #217](https://github.com/dotnetpower/fdai/issues/217). Focused consumer 검사 4개와 strict mypy가 통과했습니다. 읽기 전용 loopback 응답은 Resource 213/213개를 표시하고 `operating_scope_unmapped`를 유지했습니다. | 배포가 검토한 서비스 mapping을 제공합니다. 경로와 완전성 증적은 구현됐습니다. |
| 2026-08-19 | implemented | 검토된 중립 vocabulary 밖의 프로바이더 타입에 대해 신원 수준 종결을 추가했습니다. Azure 어댑터는 별도의 범위 제한 ARG 조회로 해당 행을 읽고, 검토된 단일 `unclassified-resource` 타입으로 구체화하며, 프로바이더 타입별 신원 count가 최종 fence의 coverage 집계와 정확히 일치할 때만 세대를 수락합니다. 예약 타입에는 프로바이더 mapping이나 query terms가 없으며 타입별 Rule 또는 Action 지원을 부여하지 않습니다. | [이슈 #217](https://github.com/dotnetpower/fdai/issues/217). 프로바이더, 동기화, ARG, Azure 인벤토리, 조립, CLI, 온톨로지, 카탈로그 및 값 도메인 focused 검사 259개가 통과했고 작업 범위 Ruff와 strict mypy도 통과했습니다. | 새로운 전체 재조정을 승격하고 identity-complete coverage, 스냅샷-온톨로지 parity 및 실시간 overlay 정리를 확인한 뒤 이 행을 `validated`로 변경합니다. |
| 2026-08-19 | validated | 하드닝 Round 3에서 count, fence, 취소, ARG, 정규화, fallback, seed 복구, precedence, catalog 소유권, 상위 parsing, 그래프 parity 및 근거 lens 12개를 다시 확인했습니다. 검증된 Medium 이상 결함은 남지 않았습니다. 관측 11건은 Low guard 확인 또는 선택적 진단이며 precedence 우려 한 건은 exact mapping 경로와 보존된 실제 운영 parity를 추적한 뒤 기각했습니다. | [이슈 #216](https://github.com/dotnetpower/fdai/issues/216). Round 3은 Round 1 exact-parent guard와 Round 2 count-shape guard 뒤의 현재 HEAD를 검토했습니다. focused suite, 보존된 533/57/15 coverage, 2/2 SQL 스냅샷-온톨로지 parity 및 서명된 framework snapshot이 근거 경계로 남습니다. | 이슈 #216 하드닝에 남은 작업은 없습니다. |
| 2026-08-19 | implemented | 하드닝 Round 2에서 계약, fence, 조회, fallback, mapping, 상위, 검증기, digest 및 근거 우려 14건을 검토했습니다. 제안된 지적과 별개로 실제 Medium 결함 한 건을 채택했습니다. Python boolean이 정수 count로 통과했고 양수 객체/0 타입이라는 불가능한 매니페스트도 유효했습니다. 이제 coverage count는 exact 정수여야 하고 0 객체와 0 타입이 서로 일치해야 하며 관측된 타입 count는 객체 count보다 클 수 없습니다. 반복된 unseeded 세대, ARG filter, shard/fence, 겹치는 glob, 잘못된 상위, 상위 근거 및 digest 우려는 focused 테스트, exact-string mapping grammar, 범위가 제한된 요청 timeout, 완전 세대 검증, 보존된 실제 운영 533/57/15 및 SQL parity 근거와 대조해 기각했습니다. | [이슈 #216](https://github.com/dotnetpower/fdai/issues/216). guard 전에는 negative case 6개가 실패했고 guard 뒤에는 `ProviderTypeCount` boolean 거부를 포함한 7개 case가 통과합니다. | 10개 이상의 lens로 Round 3을 실행해 Low 또는 기각된 관측만 남는지 확인합니다. |
| 2026-08-19 | implemented | 하드닝 Round 1에서 coverage, fence, 조회, mapping, cardinality 및 근거 우려 13건을 검토했습니다. Medium 결함 한 건을 채택했습니다. 출처 타입 하나에 exact 상위 포함 관계 mapping 두 개가 catalog load를 통과해 나중에 온톨로지 변환을 중단할 수 있었습니다. 이제 loader가 프로바이더 I/O 전에 모호한 소유권을 거부합니다. 빈 프로바이더 범위, 리소스 yield 뒤 coverage 실패, null ARM mapping, enum decoding 및 최종 fence 우려는 기각했습니다. 최종 fence가 실행 근거이고, Azure coverage 작업은 어떤 리소스 batch도 yield하기 전에 모두 끝나며, 타입이 지정된 loader와 테스트가 해당 경계를 이미 적용하기 때문입니다. | [이슈 #216](https://github.com/dotnetpower/fdai/issues/216). 새 catalog 회귀는 guard 전에는 실패하고 guard 뒤에는 통과합니다. focused 프로바이더 mapping, ARG 및 관계 검증이 검증 표면으로 남습니다. | 두 번째 10건 이상 검토를 실행해 Medium 이상 결함이 남지 않았는지 확인합니다. 잘린 관측의 drop 상세와 timestamp 정밀도 관측은 Low입니다. |
| 2026-08-19 | validated | 수정된 SQL 포함 관계 세대를 승격하고 활성 인벤토리 스냅샷과 온톨로지 읽기 모델의 parity를 확인했습니다. 관측된 모든 SQL 데이터베이스는 두 저장소 모두에서 논리 서버 `parent_id` 하나와 `contains(sql-server, sql-database)` 간선 하나를 가집니다. 온톨로지 observer failure는 발생하지 않았습니다. | [이슈 #216](https://github.com/dotnetpower/fdai/issues/216). one-shot 작업은 `inventory snapshot promoted from arg`를 보고했습니다. loopback PostgreSQL은 스냅샷 SQL 데이터베이스 2개, parent id가 있는 데이터베이스 2개, 스냅샷 SQL 간선 2개, 온톨로지 SQL 데이터베이스 2개 및 온톨로지 SQL 간선 2개를 보고합니다. | SQL 논리 상위 포함 관계에 남은 작업은 없습니다. |
| 2026-08-19 | implemented | 실제 운영 변환에서 wildcard 리소스 그룹 상위와 exact 논리 서버 상위를 모두 유지하면 `contains` one-to-many cardinality를 위반한다는 사실이 드러나 SQL 포함 관계를 바로잡았습니다. 같은 contained 하위에 대해서 exact 출처 타입 `contains` mapping이 이제 wildcard mapping을 shadow합니다. 서로 다른 하위 계층은 독립적으로 유지되므로 리소스 그룹-VNet과 VNet-subnet 포함 관계는 모두 남습니다. `Resource.parent_id`도 간선과 같은 검토된 exact mapping을 사용합니다. | [이슈 #216](https://github.com/dotnetpower/fdai/issues/216). 승격된 스냅샷은 성공했지만 온톨로지 변환 결과가 `contains violates one_to_many cardinality`로 실패했습니다. SQL 및 VNet 대조와 focused ARG, mapping audit 및 검증기 suite 117개가 통과했고 strict mypy도 통과했습니다. | 수정 사항을 커밋하고 전체 재조정을 다시 실행한 뒤 스냅샷과 온톨로지 SQL 포함 관계가 일치하는지 확인합니다. |
| 2026-08-19 | implemented | `Microsoft.Sql/servers/databases`를 위한 검토된 Azure 프로바이더 상위 mapping을 추가했습니다. 어댑터는 구조가 유효한 immediate nested ARM 상위만 해석하고, 기존 리소스 그룹 포함 관계 후보를 보존하면서 `contains(sql-server, sql-database)`를 발행합니다. 상위가 없거나 완전 세대에서 엔드포인트가 누락되면 검증된 간선을 만들지 않습니다. | [이슈 #216](https://github.com/dotnetpower/fdai/issues/216). focused ARG, exact mapping direction audit 및 완전 세대 검증기 검사 116개가 통과했습니다. 작업 범위 Ruff와 strict mypy, 온톨로지 및 Property coverage gate도 통과했습니다. | 전체 재조정 한 번을 실행하고 승격된 스냅샷 및 온톨로지 변환 결과에서 SQL 서버-데이터베이스 간선을 확인합니다. |
| 2026-08-19 | validated | 활성 로컬 스냅샷에서 프로바이더 범위 coverage를 포함한 전체 ARG 재조정 한 번을 승격했습니다. 스냅샷은 구체화된 Resource 행 516개와 프로바이더 native 객체 533개를 분리해 저장합니다. 객체 476개는 검토된 vocabulary에 매핑되고 프로바이더 타입 15종의 객체 57개는 명시적으로 미매핑 상태를 유지합니다. 매핑된 프로바이더 객체와 스냅샷 Resource 사이의 행 40개 차이는 이전에 측정한 중첩 리소스 구체화와 구독 anchor이며 숨겨진 프로바이더 coverage가 아닙니다. | [이슈 #216](https://github.com/dotnetpower/fdai/issues/216). committed callback은 객체 533/476/57개와 타입 68/15종을 반환했습니다. one-shot 작업은 `inventory snapshot promoted from arg`를 보고했고, loopback PostgreSQL 활성 행은 `source=arg`, `status=active`, `resource_count=516` 및 타입과 count 행 15개를 포함한 같은 coverage count를 보고합니다. | 프로바이더 범위 coverage 기록에 남은 작업은 없습니다. SQL 서버-데이터베이스 포함 관계가 다음 인벤토리 gap으로 남습니다. |
| 2026-08-19 | implemented | 첫 committed 실제 운영 probe가 HTTP 400을 반환한 뒤 프로바이더 범위 Kusto pipeline을 고쳤습니다. ARG는 `Resources &#124; summarize ... &#124; union (...)`을 허용하고, 초기 producer가 사용한 prefix 형식 `union (Resources ...), (...)`은 거부합니다. parser는 이제 명시적인 `resource_count` 집계 열을 고정합니다. | [이슈 #216](https://github.com/dotnetpower/fdai/issues/216). one-shot 작업은 이전 스냅샷을 유지하고 두 출처를 모두 사용할 수 없다고 보고했으며, 격리된 callback이 `ArgQueryError` HTTP 400을 재현했습니다. 수정된 읽기 전용 Azure CLI 조회는 범위가 제한된 타입 및 count 행을 반환했고 focused ARG 및 조립 검사 99개가 통과했습니다. | 수정 사항을 커밋하고 전체 재조정을 다시 실행한 뒤 승격된 리소스 57개 coverage 근거를 주장합니다. |
| 2026-08-19 | implemented | Azure Resource Graph 타입 집계를 전체 스냅샷 fence에 연결했습니다. raw `Resources`와 리소스 그룹 `ResourceContainers`를 세고, 정규화된 프로바이더 타입을 검토된 전체 ARM vocabulary와 비교하며, 선언되지 않은 모든 타입과 count를 지원되는 Resource로 구체화하지 않은 채 기록합니다. 구독 anchor와 파생된 중첩 subnet은 이 프로바이더 범위 측정에서 제외합니다. | [이슈 #216](https://github.com/dotnetpower/fdai/issues/216). focused ARG, Azure 인벤토리, 조립 및 인벤토리 작업 검사 136개와 작업 범위 Ruff 및 strict mypy가 통과했습니다. | 전체 재조정 한 번을 실행하고 승격된 메타데이터가 보존된 리소스 57개, 타입 15종 측정을 재현하는지 확인한 뒤 런타임 근거로 사용합니다. |
| 2026-08-19 | implemented | 범위가 제한된 프로바이더 native 범위 coverage를 CSP-중립 `InventoryBatch` 최종 fence에 추가하고 승격할 때만 변경 불가능한 스냅샷 메타데이터로 변환했습니다. 생성 전에 count 합계를 대조하고, 최종이 아닌 배치는 근거를 운반할 수 없으며, 정적 출처 메타데이터는 완료된 수집을 가장할 수 없습니다. | [이슈 #216](https://github.com/dotnetpower/fdai/issues/216). focused 프로바이더 계약 및 인벤토리 동기화 테스트 31개와 작업 범위 Ruff 및 strict mypy가 통과했습니다. | Azure 전체 범위 타입 집계 producer를 연결하고 승격된 스냅샷에 측정된 미매핑 count를 보존합니다. |
| 2026-08-14 | in-progress | 이전 이력을 재구성하지 않고 구현 원장을 도입했으며 Azure 계약 구현을 운영 근거 및 보류된 비-Azure 어댑터와 분리해 기록했습니다. | `current change`; 구현 범위 표의 프로바이더, 전달, 인프라 및 배포 근거입니다. | 하나의 통제된 8개 계약 캠페인을 보존하고 명시적으로 범위가 정해질 때까지 비-Azure 작업을 보류합니다. |
| 2026-08-20 | implemented | 두 번째 그래프 작성자를 만들지 않고 인벤토리 수집을 지속 실행 형태로 전환했습니다. 1분 틱은 실행 조건 확인 전에 프로바이더 변경을 비우고, 구성 가능한 하한은 변경으로 시작되는 스캔을 합칩니다. 모든 ARG 샤드는 선제적 속도 제어를 공유하고, 반응형 초기화 대기는 제한되며, 각 출처에는 진행 시 다시 설정되는 마감과 절대 마감이 있습니다. | [이슈 #139](https://github.com/dotnetpower/fdai/issues/139); 현재 소스와 집중 ARG, 인벤토리, 예약, 구성, 변환 결과 및 인프라 검사입니다. | 이 범위를 `validated`로 변경하기 전에 exact revision 보호 적용, 측정된 1분 주기와 비용, 실제 프로바이더 변경 조정 증적 하나를 보존합니다. |
| 2026-08-23 | implemented | 계약 5를 스냅샷과 델타 전송에서 완전 세대 관계 근거와 그래프 우선 읽기 동작으로 확장했습니다. 검토된 프로바이더 매핑은 정확한 출처 및 끝점 근거를 운반하고, 억제된 후보는 타입이 지정된 누락 및 사용 불가 사유를 보존하며, 순수 새로 고침 리듀서는 권한이 없는 다섯 결과 중 하나를 선택합니다. 검증된 범위 제한 실제 읽기는 정본 부분 오버레이를 통해 반영됩니다. 읽기 전용 Console 변환 결과는 두 번째 인벤토리 출처가 되지 않으면서 저장된 관계 타입, 방향, 근거 및 불완전한 범위를 보존합니다. | `current change`; [지속 운영 인스턴스 그래프](continuous-operational-instance-graph-ko.md), [네트워크 토폴로지 시각화](../interfaces/network-topology-visualization-ko.md), `shared/providers/inventory.py`, `core/ontology_platform/graph_evidence_refresh.py`, `delivery/inventory_live_evidence.py` 및 해당 소유 문서에 기록된 집중 검사입니다. | 새로 고침 선택과 실제 근거 반영을 일반 의미 쿼리 조립에 연결하고, 정확한 개정 번호의 통제된 캠페인을 보존하며, 새 범위를 `validated`로 올리기 전에 배포된 최신성, 압력 및 비용 근거를 보존합니다. |

### 남은 작업

- [ ] 정확한 개정 번호를 고정하고 이벤트, 런타임, 시크릿, 신원, 인벤토리, 메트릭, 로그 및 추적 행동과 실패 및 최신성 사례를 입증하는 통제된 Azure 캠페인 증적을 보존합니다.
- [ ] 그래프 새로 고침 선택과 실제 근거 반영을 일반 의미 쿼리 조립에 연결한 뒤, 관측, 변경 또는 실행 권한 없이 다섯 결과를 모두 다루는 조립 증적을 보존합니다.
- [ ] 루트 기반 탐색, 관계 누락 및 사용 불가 사유, 저장된 간선 방향, 잘림, 불완전한 그래프의 `unknown`, stale 대체 경로 및 권한 상승 없음을 다루는 정확한 개정 번호의 통제된 인벤토리 그래프 및 Console 근거를 보존합니다.
- [ ] 승인된 대상이 순서, 재현, 신원, 인벤토리 및 텔레메트리 행동의 계약 동등성 테스트를 제공할 때까지 비-Azure 어댑터를 구현하지 않습니다.

## 원칙

코어가 클라우드 프로바이더에서 접근하는 모든 것은 벤더 SDK 가 아니라 **관심사당 하나의
와이어 수준 계약** 을 통해야 합니다. 각 계약의 Azure 구현이 오늘 우리가 만드는 것이며,
포크 나 미래 단계 는 `core/` 를 편집하지 않고 **같은 계약** 의 새 구현을 등록해서 다른 CSP 를 추가합니다.

**동시성(동시성)**: I/O를 수행하는 프로바이더 경계는 **기본 비동기** 입니다 (Kafka poll
루프, Postgres asyncpg, Key Vault HTTP, OIDC 토큰 교환, inventory-graph 쿼리, 그리고
§ 6-8 의 세 telemetry-ingestion 쿼리는 모두 I/O 한계). Sync 는 이벤트 루프 를 블록하지
않도록 CPU / 시작 전용 경계 - `SchemaRegistry`, `ContractValidator`, `ConfigProvider` -
에만 남겨둡니다. 정본 경계 리스트는
[project-structure-ko.md § 주입 가능한 Seams](project-structure-ko.md#주입-가능한-seams)
참조.

CSP 접촉면을 지배하는 여덟 개의 계약 (다섯 wire-level 기반 +
[scope-expansion-ko.md § 3.2](../fork-and-sequencing/scope-expansion-ko.md) 로 추가된 세 telemetry-ingestion
경계):

| # | 계약 | 와이어 / 아티팩트 | Azure 구현 |
|---|------|---------------------|-------------|
| 1 | **이벤트 버스** | Apache Kafka 와이어 프로토콜 | Event Hubs (Kafka 엔드포인트 on 포트 `9093`) |
| 2 | **런타임** | OCI 컨테이너 이미지 + Knative 호환 매니페스트 서브셋 | Container Apps (Consumption, KEDA) |
| 3 | **시크릿** | 환경변수 (또는 K8s 시크릿 마운트) - 앱에서 CSP 시크릿 SDK 호출 안 함 | Container Apps native 시크릿 + Key Vault 참조 |
| 4 | **워크로드 아이덴티티** | OIDC 토큰 (federated) | User-assigned Managed Identity + 워크로드 신원 federation |
| 5 | **인벤토리** | HTTP + OIDC-bearer 와이어로 `(Resource, Link[])` 배치를 반환하는 리소스-그래프 쿼리 표면 | Azure Resource Graph (ARG) + Activity Log delta |
| 6 | **메트릭 인제스트** | `MetricProvider.query(MetricQuery) -> AsyncIterator[MetricPoint]` (CSP-neutral 이름 + 라벨) | Azure Monitor Logs (KQL) - 업스트림 은 `FDAI_MONITOR_WORKSPACE_ID` 가 세팅되면 `AzureMonitorLogsMetricProvider` 를 자동 바인딩, 아니면 `NoopMetricProvider` 유지 |
| 7 | **로그 인제스트** | `LogQueryProvider.query(LogQuery) -> AsyncIterator[LogRecord]` (벤더 `expression` + CSP-neutral 라벨 필터) | Log Analytics (KQL) - 업스트림 은 `NoopLogQueryProvider` ship |
| 8 | **추적 인제스트** | `TraceQueryProvider.query(TraceQuery) -> AsyncIterator[Span]` (`trace_id`, `service`, `operation`, `min_duration`) | Application Insights - 업스트림 은 `NoopTraceQueryProvider` ship |

여덟 개 모두 `core/` 에 프로바이더 특이를 누출하지 MUST NOT.
거부해야 하는 구체적 위반은 [Anti-Patterns](#anti-patterns) 참조.

## 1. 이벤트버스 계약 - Kafka 와이어 프로토콜

이벤트버스는 작고 프로바이더 독립적인 표면 (`bootstrap.servers`, `sasl.mechanism`,
`security.protocol`, 프로바이더별 토큰/자격증명 소스) 을 가진 **Kafka 프로듀서/컨슈머** 로
표현됩니다. 3대 CSP 모두와 여러 멀티클라우드 벤더가 Kafka 호환 엔드포인트 를 노출하므로, 같은
클라이언트 라이브러리와 같은 코드 경로가 모든 대상을 커버합니다.

| CSP / 벤더 | 관리형 Kafka 엔드포인트 | 인증 방식 | 비고 |
|---|---|---|---|
| Azure | **Event Hubs** (Kafka 1.0+ 엔드포인트, `<ns>.servicebus.windows.net:9093`) | SASL/OAUTHBEARER + Entra 토큰 | Standard 1-TU 이름 공간 샤드로 통제된 유입과 파서별 operational 신호를 분리 |
| AWS | **MSK Serverless** | SASL/OAUTHBEARER + AWS IAM SigV4 | 실제 serverless (partition-hour 과금) |
| GCP | **Managed Service for Apache Kafka** (GA) | SASL/OAUTHBEARER + Google IAM 토큰 | 브로커 fleet 는 항상 켜져있음; 최소 클러스터 사용 |
| Multi-cloud | **Confluent Cloud** / **Redpanda Cloud** / **Aiven Kafka** | SASL/PLAIN 또는 SASL/OAUTHBEARER | 하이퍼스케일러에 대한 벤더 락인도 받아들일 수 없을 때의 escape hatch |
| 자체 호스팅 | AKS/EKS/GKE 위의 **Strimzi Kafka**, 또는 **Redpanda** | SASL 또는 mTLS | 최후 수단; 운영 부담 큼 |

**규칙 (MUST):**

- 코어는 **Kafka 클라이언트로만** 프로듀스/컨슘 (예: `librdkafka`, `kafka-python`,
  `KafkaJS`, `Sarama`); `ServiceBusClient`, `SqsClient`, `PubSubClient`, 기타 어떤
  벤더 SDK 도 가져오기 하지 않음.
- Azure 어댑터는 Kafka `connections.max.idle.ms` 및 `metadata.max.age.ms` equivalent를
  180,000 ms로 설정하고 240,000 ms 이상 값을 차단합니다. 이 값은
  [Event Hubs Kafka 클라이언트 구성](https://learn.microsoft.com/azure/event-hubs/apache-kafka-configurations)
  제약을 따르며 managed 브로커가 이미 닫은 소켓의 재사용을 방지합니다.
- 같은 어댑터는 문서화된 Event Hubs 생산자 요청 시간 초과를 60,000 ms로 설정하고 요청을
  1,000,000 바이트로 제한하며 소비자 하트비트/세션 쌍을 3,000/30,000 ms로 유지하고 전송 계층
  실패 후 1초 재시도 재시도 대기를 적용합니다. aiokafka OAUTHBEARER 경계는 토큰 문자열만 받으므로
  어댑터가 주입된 `IdentityToken.expires_at`을 보존하고 만료 30-45초 전에 소비자 재시작을
  결정적으로 분산합니다. 재시작은 poll 사이에서만 일어나 호출자 처리를 가로지르지 않으며
  commit-after-yield at-least-once 전달을 보존합니다.
- 이벤트 스키마는 JSON 스키마 위에 **CloudEvents 묶음** 사용
  ([tech-stack-ko.md](tech-stack-ko.md)); 모든 프로바이더에서 동일 유지.
- **스키마 진화** 는 `check_schema_compatibility`
  (`shared/contracts/compatibility.py`)로 가드된다: 버전별 스키마
  (`event/1.0.0` -> `event/1.1.0`)는 불변이며, catalog-validation 게이트가
  additive-only 가 아닌 bump(필드 제거, 타입/`enum` 제약의 변경 또는 신규
  추가, 신규 필수, enum 축소는 `BREAKING`이며 객체 속성이나 array
  `items` 내부 중첩 변경도 포함)를 거부한다. 이로써 rolling deploy 나 혼합 버전 복제본 가 조용히
  디코딩 실패하는 것을 막아 - 구/신 생산자/소비자 가 상호운용을 유지한다.
- **DLQ** = 명명 규약을 따르는 Kafka **dead-letter 토픽** (예: `<topic>.dlq`) + redrive
  워커. 모든 프로바이더는 `original_topic`, `reason`, 원본 객체를 담은 `payload`로 구성된
  동일한 JSON 묶음을 기록하며 전송 계층 헤더는 redrive 계약에 포함되지 않습니다.
  Native DLQ를 제공하는 프로바이더(Event Hubs는 제공하지 않음)도 동작을 균일하게 유지하기
  위해 토픽 규약을 사용하고 native DLQ는 무시합니다. Multiplexing 어댑터는 logical DLQ
  구독을 physical DLQ로 매핑하고 redrive 전에 logical 토픽을 복원합니다.
- **순서** 는 파티션 키 로 보장 (per-resource 키 ⇒ per-resource 정렬).
  프로바이더 특이 순서 프리미티브 (Service Bus sessions, FIFO groups) 는 코어로 흘러선 안됨.
- **멱등성** 은 이벤트의 앱 수준 멱등성 키 로 강제하지 프로바이더의 "exactly-once"
  플래그로 하지 않음. 실행기 는 인-프로세스 L1 캐시를 유지하고,
  `IdempotencyStore` 경계(`shared/providers/idempotency.py`)이 배선되면 영속
  L2 가드(`PostgresIdempotencyStore`, `INSERT ... ON CONFLICT DO NOTHING`)를
  둔다: 재시작 후 또는 복제본 간에서 *mutating* 액션 이 재전달되면
  재실행 대신 저장소 에서 반환된다. mutating 결과 만 기록된다 - abstain 은
  mutate 하지 않으므로 재평가해도 무해. "변경 적용"과 "결과 기록" 사이의
  좁은 창은 `OutboxStore` 경계(`shared/providers/outbox.py`;
  `PostgresOutboxStore` 백업)이 닫는다: 변경 *전* 에 쓴 점유 이 있으므로
  crash-suspect 재시도는 `IN_PROGRESS` 마커를 발견해 멱등적 변경 을
  완료까지 재실행하며 잃거나 이중 적용하지 않는다. 발신함 는 액션 이
  mutate 할 때(강제 적용 / P2) 의미가 있다; P1 은 shadow 전용이라 거기서는
  아무것도 이중 적용되지 않는다.
- **복제본 간 per-resource 상호배제** 는 `ResourceLock` 경계
  (`shared/providers/resource_lock.py`)으로 강제한다: 인-프로세스 `asyncio.Lock`
  (`ResourceLockManager`)이 단일 복제본 기본값이고,
  `PostgresAdvisoryResourceLock`(`hashtextextended(resource_id)` 로 키잉된 Postgres
  세션 참고용 잠금)이 실행기 가 복제본 하나를 넘어 스케일아웃하면 복제본 간
  상호배제를 준다. partition-key 순서는 *스트림* 을 직렬화하고, 락은 같은 리소스의
  동시 *액션* 을 직렬화한다 - 스케일아웃에선 둘 다 필요하다. 락은 crash-safe
  (연결이 끊기면 세션 락 해제)이며 `lock_timeout` 으로 한계 되어 stuck 보유자 가
  복제본 를 wedge 하지 않고 실패 시 차단 한다.
- **다운스트림 장애 격리** 는 `CircuitBreaker` 기본 요소
  (`shared/resilience/circuit_breaker.py`)를 쓴다: 조립 루트 가 프로바이더
  어댑터의 아웃바운드 호출(Azure ARM, GitHub, Postgres, Kafka)을 감싸, 실패가
  이어지면 회로를 열림 으로 트립해 죽은 의존성을 두드리는(재시도 폭풍) 대신 즉시
  실패하고, HALF_OPEN 단일 탐색 로 탐침 후 닫는다. 시계 주입 가능한 순수 I/O-free
  상태머신이며 조립 루트 에서 배선(`core` 에선 안 함)되어 CSP-neutral 을
  유지하고 판테온 브리지의 자가치유 재시작을 보완한다.
- **시스템 레벨 fail-toward-safety** 는 `DegradationController`
  (`shared/resilience/degradation.py`)다: circuit 차단기 들을 종합해
  `NORMAL` / `DEGRADED` 모드로 판정하고, 중요 의존성이 열림 이면 자율성 를
  shadow 로 캡한다 - 망가진 감사 저장소 나 도달 불가 기반 가 강제 적용 변경
  을 몰아선 안 된다. 컨트롤 루프 이 `autonomy_permitted()` 를 참조해 그 결과를
  risk-gate 권한 에 `system_degraded` 로 전달하고, 이는 shadow 로 캡된
  `system_health` 상한 축 를 추가한다 (execution-model.md 2.6a) - 액션
  승격 전에 적용된다.
- **backpressure** (`shared/resilience/backpressure.py`)는 세마포어로 동시성을
  한계 하고, in-flight 슬롯과 범위가 제한된 대기 큐가 모두 차면 *shed*(즉시 거부,
  브로커 / DLQ 로 재큐잉)해서 이벤트 폭주가 프로세스를 고갈시키는 대신 예측
  가능하게 저하되게 한다.

**Anti-patterns (MUST NOT):**

- Event Hubs 를 native AMQP SDK (또는 Service Bus SDK) 로 사용. Event Hubs 를 쓸 거면
  **`:9093` 의 Kafka 엔드포인트 만** 허용.
- Dapr 의 pub/sub building 블록 사용 - 사이드카 의존성이 추가되고 런타임 레이어를
  다시 락인.

## 2. 런타임 계약 - OCI 이미지 + Knative 호환 매니페스트

코어는 하나 이상의 **OCI 컨테이너 이미지** 와 트래픽 / revisions / autoscaling
트리거 / 상태 탐색 / env·시크릿 바인딩을 기술하는 작은 **Knative 호환 매니페스트 서브셋**
으로 배포됩니다. 프로바이더 어댑터가 이를 CSP 특이 리소스 모양으로 렌더링합니다.

| CSP / 서브스트레이트 | 런타임 | scale-to-zero | 계약에서 렌더링되는 배포 모양 |
|---|---|---|---|
| Azure | **Container Apps** (Consumption + KEDA) | ✓ | Bicep/Terraform 이 매니페스트에서 `containerapp` 리소스 생성 |
| AWS | **App 실행기** (요청 기반) 또는 **ECS Fargate** + KEDA | App 실행기 ✓ / Fargate - | 같은 매니페스트에서 렌더링 |
| GCP | **Cloud 실행** (services & jobs) | ✓ | Cloud 실행 은 native Knative; 매니페스트 직접 적용 |
| Any K8s (AKS/EKS/GKE) | **Knative Serving** + KEDA | ✓ | 매니페스트 직접 적용 |
| 대체 경로 | bare `Deployment` + HPA + KEDA | - (idle ≥ 1 복제본) | scale-to-zero 불가시 렌더링 |

**규칙 (MUST):**

- 이미지는 표준 **`/healthz` 및 `/readyz`** 엔드포인트 노출. Container Apps 탐색, K8s
  탐색, App 실행기 탐색, Cloud 실행 탐색 모두 이 둘을 가리킴.
- **스케일 트리거는 계약 수준 시그널** (예: `scale-on: kafka-lag`, 또는 CPU 대상).
  프로바이더 어댑터가 KEDA CRD, App 실행기 동시성, Cloud 실행 CPU 사용률 등으로 번역.
- 코어는 Dapr 사이드카, Envoy-특이 유입 annotation, Container Apps 전용 기능 (예:
  Container Apps YAML 에만 존재하는 native KEDA scaler 참조) 에 의존하지 **않음**.
- Azure 에서 스케줄 워커를 Container Apps 작업 으로 배송하는 곳에서, 다른 프로바이더는 같은
  계약을 K8s `CronJob`, AWS EventBridge 트리거 태스크, 또는 Cloud 실행 작업 으로 렌더링 -
  모두 상호교환 가능.

**Anti-patterns (MUST NOT):**

- 애플리케이션의 자체 레포에 Container Apps 전용 YAML (Dapr components, native KEDA scaler
  refs) 을 굽는 것.
- Envoy 스타일 유입 규칙 요구; 이식 가능한 유입 추상화를 쓰거나 앱 안에서 라우팅 처리.

## 3. 시크릿 계약 - 환경변수 / K8s 시크릿

애플리케이션은 **환경변수만** 읽거나, Kubernetes 위에서는 `Secret` 에서 마운트된 파일만
읽습니다. CSP 시크릿 SDK 를 **직접 호출하지 않습니다**. 주입 레이어가 CSP 시크릿 백엔드 를
컨테이너의 환경으로 이어줍니다.

| CSP / 서브스트레이트 | 주입 레이어 | 백엔드 | 인증 |
|---|---|---|---|
| Azure Container Apps | **Key Vault 참조** 를 사용하는 native `secret` 필드 | Key Vault | user-assigned MI |
| Any K8s | `SecretStore` CRD 를 가진 **외부 Secrets Operator (ESO)** | Key Vault / AWS Secrets Manager / GCP 시크릿 Manager / Vault | CSP 별 워크로드 신원 |
| AWS (ECS/App 실행기) | native task-def 시크릿 참조 | Secrets Manager / 매개변수 저장소 | IRSA |
| GCP (Cloud 실행) | native environment-from-secret 참조 | 시크릿 Manager | 워크로드 신원 |
| Multi-cloud OSS | **ESO + HashiCorp Vault** | Vault | JWT/OIDC |
| Dev/로컬 | 파일 / `sops`-encrypted git | files | GPG/age |

**규칙 (MUST):**

- 코어는 `shared/providers/` 의 주입된 `SecretProvider` 인터페이스 **를 통해서만** 시크릿
  을 읽음 ([project-structure-ko.md](project-structure-ko.md#주입-가능한-seams));
  어떤 벤더 SDK 의 `SecretClient` 도 `core/` 에 나타나지 않음.
- **시크릿 이름은 프로바이더 전체에서 안정적 스키마** 를 따름 (upper-snake env var 이름) -
  앱이 프로바이더를 모르게.
- **실패 시 차단**: 주입 레이어가 부팅 시 필수 시크릿 을 해결하지 못하면 프로세스가 fail
  fast - 캐시된 값이나 임베디드 값으로 대체 경로 하지 않음
  ([security-and-identity-ko.md](security-and-identity-ko.md#secrets-and-config)).
- **로테이션** 은 주입 레이어의 일; 앱은 프로세스 재시작 시 env 를 다시 읽어서 롤된 시크릿 을
  수용. 복호화된 시크릿 자재의 장기 캐시는 금지.

**Anti-patterns (MUST NOT):**

- 애플리케이션 코드에서 `SecretClient.GetSecret()` (또는 동등물) 호출.
- 평문 또는 암호화된 시크릿 을 출처 에 커밋 (git 내 SOPS 는 dev/로컬 에서만 허용;
  staging/prod 에서는 절대 안됨).

## 4. 워크로드 아이덴티티 계약 - OIDC 토큰

실행기 는 런타임 서브스트레이트에서 얻은 **짧은 수명의 OIDC 토큰** 으로 CSP 에 인증합니다.
어댑터 경계에서 이 토큰이 CSP 자격증명으로 교환됩니다. 실행기 는 장기 키나 공유 시크릿을
보유하지 않습니다.

| CSP / 서브스트레이트 | 워크로드 아이덴티티 프리미티브 | 토큰 교환 |
|---|---|---|
| Azure | User-assigned Managed Identity | IMDS → Entra 토큰 (SASL/OAUTHBEARER, ARM, KV) |
| AWS | IAM Roles for 서비스 Accounts (IRSA) | pod 토큰 → `AssumeRoleWithWebIdentity` |
| GCP | 워크로드 신원 Federation | K8s SA 토큰 → GCP STS |
| Any K8s | **SPIFFE/SPIRE** | SVID (JWT/X.509) 를 어댑터별 교환 |
| CI/CD | GitHub Actions OIDC / Azure DevOps federated 자격 증명 | 발급자 → CSP-side federation trust |

**규칙 (MUST):**

- 코어는 "X 로 audience-scoped 된 토큰을 가져와"를 노출하는 `WorkloadIdentity` 인터페이스만
  봄; 구체적 토큰 발급자 는 프로바이더 어댑터의 관심사.
- **승인 신원 ≠ 실행 신원** ([security-and-identity-ko.md](security-and-identity-ko.md#execution-identity)).
  위 모든 CSP 매핑에서 유지.
- 실행기 프로세스, 구성, 시크릿 저장소 어디에도 **장기 키 없음**. CSP-side 자격증명이
  불가피한 경우 (예: 이전 방식 서비스) 짧은 수명과 자동 로테이션 필수이며 사용은 감사 로그 에 기록.

**Anti-patterns (MUST NOT):**

- `core/` 안의 `DefaultAzureCredential()` 또는 유사한 이름의 SDK 진입점 - 그건 벤더 SDK
  호출이지 계약이 아님. 인터페이스 뒤의 Azure 프로바이더 어댑터에서 **만** 허용.
- 실행기 의 신원을 콘솔, ChatOps, 또는 다른 읽기 전용 표면과 공유.

## 5. 인벤토리 계약 - 리소스 그래프

코어는 리소스와 타입된 엣지의 온톨로지 그래프를 가지고 추론함
([llm-strategy-ko.md § 온톨로지 기반](llm-strategy-ko.md#온톨로지-기반)); **인벤토리** 계약은
그 그래프를 채우고 신선하게 유지하는 방법. 코어는 단일 `Inventory` 프로토콜 만
보며 CSP-중립 레코드를 반환하는 두 연산을 가짐:

- `full_snapshot(since=None) -> AsyncIterator[InventoryBatch]` - 초기 또는 주기적
  조정 로드, 타입된 `Resource` 레코드와 `contains` / `attached_to` /
  `depends_on` 링크 레코드 배치로 발행.
- `delta(cursor) -> AsyncIterator[InventoryBatch]` - 주어진 커서 이후의 증분 변경이며
  프로바이더의 native 변경 스트림이 구동합니다. 운영에서는 리소스 생성,
  갱신, 삭제 신호가 정본 Kafka 유입으로 계속 들어옵니다. Huginn은 실시간
  발견 유입을 소유하고 정규화된 `Event` 기록을 publish하며, 주입된 인벤토리
  projector는 순서가 보장된 리소스, 링크, tombstone delta를 영속 오버레이에
  적용합니다. Azure 어댑터는 범위가 제한된 복구 출처로 direct Activity Log REST factory
  (`AzureActivityLogFactory`)도 유지합니다. 주기적 full 스냅샷은 조정의
  권위 있는 출처로 남으며 누락된 신호를 복구한 뒤 base 세대를 원자적으로
  교체합니다.

완전 세대는 검토된 프로바이더 관계도 발행할 수 있습니다. 각 후보는 독립 검증 전에
매핑 개정 번호, 정확한 출처 속성, 프로바이더 끝점 타입, 관측 증적, 최신성 상한 및 저장된
방향을 운반합니다. 두 끝점을 모두 확정할 수 없는 후보는 간선으로 변환하지 않습니다.
대신 범위가 제한된 `RelationshipDrop`이 타입이 지정된 누락 사유와, 확인된 경우
`target_outside_active_generation`, `target_provider_type_unmodeled` 또는
`reference_not_observed` 같은 안정적인 사용 불가 사유를 보존합니다.

읽기 전용 콘솔은 승격된 그래프의 별도 프로젝션을 `GET /inventory/graph`를 통해
사용합니다. 이 경로는 `OperatorApiConfig.inventory_graph_provider`가 주입된 경우에만
활성화됩니다. CSP-중립 `Resource` 레코드와 `contains`, `attached_to`, `depends_on`,
`peered_with`, `routes_to` 같은 타입이 지정된 링크, 스냅샷 신선도, 잘림 메타데이터를
반환합니다. 이 경로는 Azure Resource Graph를
직접 호출하지 않으며 실행자 ID를 전달받지 않습니다. 반환되는 각 Resource는 검토된
operating-scope `service_ref`도 포함합니다. `workload_runs_on`과 `implemented_by`만 범위가
제한된 역방향으로 조회하고 mapping이 없거나 충돌하면 `unknown_service`를 반환하며, 해당
coverage가 대응되지 않거나 잘리면 응답을 강등합니다.

Console은 [네트워크 토폴로지 시각화](../interfaces/network-topology-visualization-ko.md)에
정의된 대로 동일한 권위 있는 응답에서 인스턴스 포커스 및 Network 표현을 파생할 수 있습니다.
이 읽기 전용 변환 결과는 저장된 관계 타입, 출처, 대상, 매핑 근거, 최신성 및 완전성을
보존합니다. 레이아웃 순서는 트래픽 또는 도달 가능성 근거가 되지 않으며, 관계 집합이
불완전하면 관측 경로가 없다고 주장하는 대신 `unknown`을 반환합니다.

리소스 중심 요청은 `root=<resource-id>`, `depth=1..8`, `limit=1..1000`을 지정합니다.
프로바이더는 활성 스냅샷과 순서가 보장된 실시간 오버레이에서 허용된 들어오는 및
나가는 링크를 하나의 repeatable-read, 읽기 전용 데이터베이스 트랜잭션 안에서 모두
탐색합니다. 경계가 제한된 neighborhood만 반환하며 리소스 또는 관계 상한에
도달하면 `truncated=true`로 표시합니다. 알 수 없는 루트는 named 화면나
전체 인벤토리로 범위를 넓히지 않고 `404`를 반환합니다. 이 rooted 모드를 사용하면 큰
테넌트 그래프를 전부 로드하지 않고 콘솔에서 리소스를 하나씩 확장할 수 있습니다.
`scope`와 `root`는 함께 사용할 수 없으며 custom `limit`은 `root`와 함께만 허용됩니다.
관계 필터는 반복 `link` 값을 최대 64개까지 허용하며, 각 `link` 또는 comma로
구분된 `include` 값은 파싱 전에 512자로 제한합니다. 같은 깊이에서는 간선을
결정론적으로 정렬하고 frontier 리소스별로 보이지 않은 neighbor를 round-robin 확장하므로,
하나의 high-degree 리소스가 남은 결과 자리를 모두 차지할 수 없습니다. 로컬 및 deployed
프로바이더는 내부 관계도 정렬하고 최대 `max(64, limit * 8)`개 간선을 반환하며,
더 많은 간선이 있으면 neighborhood를 잘린으로 표시합니다.
잘린 상태이면 프로바이더는 `resource_limit`, `adjacent_edge_limit`,
`internal_edge_limit`, `source_limit` 중 안정된 머신 사유를 반환합니다. 알 수 없거나
서로 모순되는 사유 메타데이터는 읽기 경로에서 실패 시 차단 처리합니다.

이 프로젝션은 이름이 지정된 아키텍처 뷰를 제공합니다. `scope` 없는 요청은 권위 있는
`fdai:managed=true`와 `fdai:workload=fdai` 인벤토리 tag 쌍으로 식별된 FDAI 자체
컨트롤 플레인만 반환합니다. 값이 정확히 `fdai`인 모호하지 않은 허용 서비스 tag도 전체
쌍이 없는 보조 로직 리소스를 위한 FDAI 소유권 신호로 예약합니다. containment를
보존하기 위해 상위 리소스 그룹 및 구독 경계를 포함할 수 있지만 관련 없는
리소스는 포함하지 않습니다. 두 소유권 신호가 모두 없으면 전체 구독으로 범위를
넓히지 않고 빈 FDAI 뷰를 유지합니다.

추가 뷰는 결정적 근거를 사용하여 FDAI 외 리소스를 분리합니다.

- **서비스 뷰**: 비어 있지 않은 서비스 tag가 서비스를 식별합니다. 허용되는 키는
  `fdai:service`, `service`, `application`, `app`, `workload`, `azd-service-name`입니다.
  프로바이더는 리소스 이름에서 서비스 ID를 추론하지 않습니다. 허용된 키가 서로 다른
  값으로 확인되면 분류를 모호한 것으로 처리하고 리소스 그룹 대체 경로를
  사용합니다. 하나의 서비스 뷰는 여러 리소스 그룹의 리소스를 포함할 수 있으며
  필요한 상위 경계를 함께 포함합니다.
- **Resource 그룹 대체 경로 뷰**: 리소스에 사용할 수 있는 서비스 tag가 없으면 해당
  리소스를 포함하는 리소스 그룹을 뷰 경계로 사용합니다. 이 대체 경로는 서비스 ID를
  만들어 내지 않고 관찰된 구조를 보존합니다.

`scope=<view-id>`를 지정하면 동일한 CSP-중립 와이어 계약을 유지하면서 해당 뷰의
경계가 제한된 리소스와 링크 집합을 반환합니다. 화면 메타데이터는
`kind=fdai|service|resource_group`과 분류 근거(`ownership_tag`, `service_tag`,
`resource_group_fallback`)를 기록합니다. Named-view 프로바이더는 명시된 화면 id가
등록되지 않았으면 기본값 화면으로 대체하지 않고 `404`를 반환합니다. Console은 기본값
매니페스트를 다시 불러와 등록된 복구 링크를 표시할 수 있습니다. Postgres 운영
변환 결과와 로컬 Azure CLI 변환 결과는 동일한 화면 분류 규칙을 사용하여
로컬 및 deployed 콘솔의 의미를 일치시킵니다.

| CSP / 서브스트레이트 | 인벤토리 소스 | Delta 소스 | 와이어 |
|---|---|---|---|
| Azure | **Azure Resource Graph** (ARM 위 Kusto) | [이벤트버스](#1-이벤트버스-계약--kafka-와이어-프로토콜)를 통한 Activity Log 리소스 변경, Huginn 정규화, ordered 오버레이 변환 결과 | HTTPS + `Authorization: Bearer <OIDC>` |
| AWS *(TBD)* | AWS 구성 + Resource Explorer | 구성 configuration-item 스트림이 Kafka 로 포워드 | HTTPS + SigV4 |
| GCP *(TBD)* | Cloud Asset 인벤토리 | Asset 피드 가 Kafka 로 포워드 | HTTPS + Google IAM |
| Any K8s | 리소스-모델 번역기를 통한 `apiserver` list-watch | `watch` 스트림이 Kafka 로 포워드 | HTTPS + service-account 토큰 |

**규칙 (MUST):**

- 코어는 `shared/providers/` 에 주입된 `Inventory` 인터페이스를 통해서만 인벤토리를 읽음
  ([project-structure-ko.md § 주입 가능한 Seams](project-structure-ko.md#주입-가능한-seams)).
  `ResourceManagementClient`, `ArmClient`, `boto3.client("config")`, `google.cloud.asset`
  - 클라우드-인벤토리 SDK 는 `core/` 에 생김 안 함.
- 레코드는 와이어에서 **CSP-중립**: `Resource.type` 은 정본 `resource_type`
  어휘 ([rule-catalog-collection-ko.md](../rules-and-detection/rule-catalog-collection-ko.md#수집-소스))
  이며 링크 종류는 `shared/contracts/ontology/link-type.json` 에 선언된 것. 벤더-네이티브
  id 는 Resource 의 민감정보가 제거된 `provider_ref` 필드에 타고 올 수 있음 - 절대 기본 키 아님.
- **초기 full 스냅샷 은 바운드된 동시성으로 병렬화**: 어댑터는 워크로드를
  `ResourceType` 으로 샤딩 (하나의 타입이 너무 넓으면 스코프로 더 세분화), semaphore 하에서
  동시 확산 쿼리, 배치를 ingest 파이프라인으로 스트리밍. 코어는 절대 단일-연결 블로킹
  스캔을 가정하지 않음.
- **프로바이더 범위 coverage는 최종 fence에서 종결됩니다.** 완전한 어댑터는 범위가 제한된 `ProviderScopeCoverage` 하나를 최종 `InventoryBatch`에 붙일 수 있습니다. 프로바이더 native
  객체 및 타입 count를 구체화된 스냅샷 레코드와 구분하고, 선언된 vocabulary에 없는 native 타입만 나열하며, 생성 전에 mapped와 unmapped count 합계를 대조합니다. 동기화 조정기는 최종 fence 뒤에만
  이 근거를 변경 불가능한 스냅샷 메타데이터로 복사합니다. 부분 스트림 또는 정적 출처 매니페스트는 완료된 프로바이더 coverage를 주장할 수 없습니다.
- **Coverage count는 범위가 제한된 exact 정수입니다.** Boolean 값은 count가 아닙니다. 프로바이더 객체가 0이면 관측된 프로바이더 타입도 0이어야 하며 그 반대도 같습니다. 관측된 타입마다 객체가
  최소 하나 있으므로 `provider_type_count`는 `provider_object_count`보다 클 수 없습니다. 매핑 및 미매핑 객체 count는 계속 프로바이더 총계와 정확히 일치해야 합니다.
- **Azure coverage는 변환된 그래프 객체가 아니라 프로바이더 native 행을 셉니다.** coverage 조회는 모든 ARG `Resources`와 `ResourceContainers`의 리소스 그룹 행을 정규화된 ARM 타입별로
  묶습니다. 구독 anchor와 구체화된 subnet 같은 파생 중첩 리소스는 제외한 다음 해당 그룹을 검토된 전체 ARM vocabulary와 비교합니다. vocabulary에 없는 프로바이더 타입은 명시적인 미매핑 count로
  남고 자동 선언되지 않습니다.
- **미분류 신원은 가시성이며 의미 지원이 아닙니다.** Azure 어댑터는 검토된 ARM vocabulary
  밖의 모든 프로바이더 행을 조회하고, 범위가 제한된 신원, native 타입, 표시 필드 및 포함 관계
  상위만 검토된 `unclassified-resource` ResourceType에 매핑합니다. 해당 신원이 모든 미매핑 타입
  count와 정확히 일치하지 않으면 최종 fence를 내보내지 않습니다. 예약 타입에는 프로바이더
  mapping이나 query terms가 없으며 제공되는 Rule 중 어느 것도 이 타입에 적용되지 않습니다.
- **Exact 포함 관계가 wildcard fallback보다 하나의 하위를 우선 소유합니다.** Exact 출처 타입
  mapping과 wildcard `contains` mapping이 같은 contained 하위를 점유하면 exact mapping이 wildcard
  후보를 shadow합니다. 서로 다른 하위를 포함하는 mapping은 독립적으로 남습니다. 같은 선택된 mapping이
  `Resource.parent_id`도 공급하므로 객체와 간선이 서로 다를 수 없습니다.
- **완전한 ARG 읽기는 1,000개 이후에도 페이지를 계속 조회합니다.** Azure Resource Graph는
  응답 하나에 최대 1,000개 레코드를 반환합니다. 완전한 결과가 필요한 어댑터는 `$top`을
  최대 1,000으로 설정하고, 구성된 페이지 상한 안에서 각 `$skipToken`을 끝까지 따라가며,
  인벤토리 `id` 또는 deployment-history `row_id` 같은 고유 projected 키로 정렬합니다.
  각 페이지는 조회 할당량 하나를
  소비합니다. JSON 변환 결과 전에 raw 응답을 페이지당 10 MB, 조회당 64 MB로 제한합니다.
  토큰 반복, 페이지 상한 초과, 이어가기 토큰 없는 `resultTruncated=true`는
  읽기가 불완전한 것으로 보고 실패 시 차단 처리합니다. 반면 범위가 제한된 interactive 읽기는 명시된
  결과 상한보다 하나 더 요청하고 잘림을 표시합니다. 자세한 내용은
  [페이지 나누기 지침](https://learn.microsoft.com/azure/governance/resource-graph/concepts/paging-results)을
  참조하세요.
- **ARG 호출은 서비스 할당량 신호를 따릅니다.** 어댑터별 shared 게이트는 모든 응답의
  `x-ms-user-quota-remaining`과 `x-ms-user-quota-resets-after`를 읽고 할당량이 0이면 동시
  샤드를 지연합니다. HTTP `429` 재시도는 `Retry-After`만큼 기다립니다. 전송 계층 실패,
  `408`, 일부 `5xx` 응답에는 범위가 제한된 exponential 재시도 대기를 적용합니다. 재시도를 모두 사용하면
  부분 결과를 publish하지 않고 실패 시 차단 처리합니다. Azure가 할당 할당량을 변경할 수
  있으므로 고정 query-rate 상수는 사용하지 않습니다. 자세한 내용은
  [Throttled 요청 지침](https://learn.microsoft.com/azure/governance/resource-graph/concepts/guidance-for-throttled-requests)을
  참조하세요.
- **멱등 세대 저장**은 완전한 검사를 `inventory_snapshot_resource`와
  `inventory_snapshot_link`에 단계하며, 세대와 중립 `resource_id` 또는
  `(from_id, link_type, to_id)`를 키로 사용합니다. 완전한 fence가 `inventory_active`
  포인터를 원자적으로 교체합니다. 순서가 보장된 변경은 다음 세대가 포함할 때까지
  `inventory_realtime_resource`와 `inventory_realtime_link`에 저장됩니다. 읽기 담당은 활성
  세대와 오버레이를 하나의 유효한 온톨로지 형태 리소스 그래프로 병합하며, 스캔된
  리소스를 범용 `ontology_resource` 및 `ontology_link` 인스턴스 저장소에 이중 기록하지
  않습니다. 스냅샷 staging은 리소스와 링크를 기본 1,000-row 조각으로 변환하고 기록하며,
  검증된 상한은 10,000입니다. 하나의 입력 배치에 속한 모든 조각은 같은 데이터베이스
  트랜잭션 안에서 처리합니다. 검증과 엔드포인트 locking 이후 하나의 delta 이벤트는
  reconciled realtime 링크 upsert 전체를 한 번의 batched `executemany` 파이프라인으로 보내며,
  집계 applied-row 개수를 유지합니다. 엔드포인트 리소스 id는 deduplicate 및 sort한 뒤
  하나의 ordered PostgreSQL 구문으로 잠금하므로, 엔드포인트마다 클라이언트 왕복을 만들지
  않으면서 deadlock-safe 순서를 보존합니다.
- **실패 시 차단**: 부분 스냅샷 은 stale 그래프가 자율 결정을 구동하는 상태에 절대
  런딩하지 않음. 스냅샷 이 완료되고 원자적으로 승격되거나, 이전 그래프가 유지되고
  실패가 감사됨.
- **Delta 는 별도 사이드-채널이 아니라 이벤트 버스를 통해 흐름**. 프로바이더 변경 신호
  (Activity Log, 구성 항목, Asset 피드, apiserver watch) 는 Kafka 토픽으로 포워드되어
  다른 `Signal` 과 정확히 같이 소비 - 동일한 멱등성, 동일한 DLQ.
- **Delta 정렬은 활성 스냅샷으로 fence합니다.** 활성 세대 시작 시각 이전 또는
  같은 관측은 이미 반영된 것으로 보고 no-op 처리하며, 설정된 server-clock skew보다
  미래인 관측은 거부합니다. Resource와 링크 엔드포인트 타입은 모두 활성 커버리지에
  속해야 하고 이벤트별 링크 개수를 제한합니다. 관측 시각이 같으면 삭제가 upsert보다
  우선하므로 재생이 tombstone 리소스를 되살리지 않으며 같은 종류는 이벤트 id로 결정합니다.
- **Huginn은 실시간 발견 유입을 소유**하고 프로바이더 어댑터는 cloud 파싱과
  지점 enrichment를 소유합니다. 인벤토리 projector는 영속 리소스, 링크, tombstone
  적용을 소유합니다. Heimdall은 최신성, 전달 lag, 대체 경로, 커버리지 성능 저하를
  관찰하며 cloud 인벤토리를 직접 조회하지 않습니다.
- **지속형 reconciliation은 계속 필요합니다.** Inventory 경로는 변경 스트림, 재개 가능한
  delta, 완전한 ARG/ARM reconciliation 세대를 지속적으로 결합합니다. Delta 스트림만으로
  완전성을 증명하지 않습니다. Durable 원본 정책은 목표 최신성, 최소 및 최대 간격, 우선순위,
  요청 및 byte 예산, 동시성, 공급자 `Retry-After`, 범위가 제한된 backoff, circuit 상태를
  제어합니다. 구현된 결정적 스케줄러는 이 입력에서 범위가 제한된 다음 작업 하나를 선택합니다.
  배포된 주기, 압력 및 비용은 운영 검증 근거로 별도 유지합니다. 변경은 이 컨트롤 플레인이 활성
  snapshot 시작 뒤에 기록했을 때 미조정으로 봅니다.
  시도 하나에는 진행 시 다시 설정되는 무진행 마감과 절대 상한이 있고, 모든 ARG shard는 지속
  요청 예산을 공유합니다. 로컬 새로 고침과 배포 worker는 durable 시도 전이, 활성 pointer 검증,
  범위가 제한된 활동 게시를 공유합니다. 복구 delta는 cursor를 읽거나 전진하기 전에 각 scope를
  직렬화합니다. Worker는 읽기 전용 inventory 신원을 유지하며 Heimdall은 공급자를 직접 조회하거나
  수집을 시작하지 않습니다. 보존, rollup, archive, purge 규칙은
  [지속형 운영 인스턴스 그래프](continuous-operational-instance-graph-ko.md)가 소유합니다.
- **그래프 우선 새로 고침은 결정적이며 권한을 부여하지 않습니다.** 검증된 쿼리 요구 사항,
  현재 그래프의 최신성과 완전성, 온톨로지 릴리스, 충돌, 명시적 실제 읽기 정책, 마감 및
  아카이브 상태는 `use_graph`, `refresh_then_query`, `use_live_evidence`, `query_archive` 또는
  `hold` 중 정확히 하나로 축약됩니다. 결과는 범위가 제한된 읽기 경로만 선택합니다. 관측,
  변경 또는 실행 권한을 운반하지 않으며, 검증된 실제 근거는 완전한 속성이나 링크를 교체하지
  않고 정본 부분 오버레이를 통해 인벤토리에 다시 들어갑니다.
- **미인식 `ResourceType` 또는 LinkType** 은 이슈를 열고 드롭됩니다. 어댑터는 런타임에 새
  온톨로지 타입을 자동 등록하지 않습니다. 전체 프로바이더 스캔은 미리 선언된
  `unclassified-resource` 타입을 통해서만 알려지지 않은 native 리소스 신원을 보존할 수 있습니다.
  ([llm-strategy-ko.md § 포크 확장](llm-strategy-ko.md#포크-확장-self-extending-온톨로지)).
- 신뢰할 수 없는 벤더 속성 (태그, 설명) 은 추가 전에 redact 또는 길이-상한화되어
  있어야 하며 inert 데이터이지 지시가 아님.

**Anti-patterns (MUST NOT):**

- `core/` 에서 `azure-mgmt-*`, `boto3`, `google-cloud-*` 클라이언트 가져오기.
  클라우드 인벤토리 SDK 는 프로바이더 어댑터 패키지에만 있어야 함.
- Kusto / ARG 쿼리를 `core/` 코드 경로에 임베드 (그것들은 매니페스트 / 쿼리 템플릿이
  구동하는 Azure 어댑터에 속함).
- 초기 full 검사 을 글로벌 락 하에 실행하거나, 실행기 의 per-resource 락 하에서 실행;
  인벤토리 sync 와 교정 실행은 독립적 동시성 예산을 가진 별개 관심사.
- 부분 delta 스트림만을 권위 있는 로 신뢰; 다운된 이벤트를 잡으려면 주기 full-snapshot
  조정 이 필수.

### 제한적인 NSG egress 환경의 Azure 인벤토리

이 배포 사례의 네트워크 경로, 순서가 지정된 출처 대체 경로 및 최신성 동작은
[제한된 네트워크의 Azure 인벤토리](azure-inventory-network-paths-ko.md)에서 소유합니다.

## 6. 메트릭 조회 계약 - CSP-Neutral 샘플 Iterator

외부 메트릭 (Prometheus, Azure Monitor Logs, CloudWatch, Datadog) 을
`MetricProvider.query(MetricQuery) -> AsyncIterator[MetricPoint]`
([`shared/providers/metric.py`](../../../services/core-control-plane/src/fdai/shared/providers/metric.py))
로 소비. `MetricQuery` 는 벤더 중립적인 (`metric_name`, `labels`, `since`, `until`,
`aggregation` 힌트); 어댑터는 CSP-neutral 이름을 벤더 이름 공간 로 매핑하고 힌트를
최선 노력 로 honor. 업스트림 은 `NoopMetricProvider` (빈 결과) + `StaticMetricProvider`
(테스트 double) 를 ship; Azure 어댑터 는 `delivery/azure/` 아래 land.

**Design 룰:**

- 비동기 by 계약 (외부 메트릭 조회 는 I/O-bound; 그렇지 않으면 이벤트 루프 를 블록 -
  § 1 / § 3 / § 4 / § 5 와 동일한 discipline).
- 빈 결과는 valid 답 (구간 내 샘플 없음 ≠ 오류).
- 호출자 는 부분 결과 로 auto-remediate MUST NOT; abstain 하고 HIL 로 경로 -
  [architecture.instructions.md § 안전성 Invariants](../../../.github/instructions/architecture.instructions.md#safety-invariants)
  per.

## 7. 로그 조회 계약 - 구조화된 로그 Records

구조화된 로그 (Log Analytics KQL, Loki LogQL, Elasticsearch, CloudWatch Logs) 를
`LogQueryProvider.query(LogQuery) -> AsyncIterator[LogRecord]`
([`shared/providers/log_query.py`](../../../services/core-control-plane/src/fdai/shared/providers/log_query.py))
로 소비. `expression` 필드는 vendor-specific 쿼리 문자열; `labels` 는 어댑터가 라벨
표면 에 매핑하는 CSP-neutral pre-filter. `core/` 에 tail 을 hard-code 하지 않고
CSP-neutral 필터 와 vendor-specific tail 을 compose 할 수 있도록 분리 유지.

## 8. 추적 조회 계약 - Distributed-Trace Spans

구간 (App Insights, Tempo, Jaeger, Honeycomb) 을
`TraceQueryProvider.query(TraceQuery) -> AsyncIterator[Span]`
([`shared/providers/trace_query.py`](../../../services/core-control-plane/src/fdai/shared/providers/trace_query.py))
로 소비. `Span` 은 `trace_id`, `span_id`, `parent_span_id`, `service`, `operation`,
`start`, `duration`, `status`, 그리고 CSP-neutral `labels` 를 carry - RCA 가 어떤
백엔드 가 기록했는지 모른 채 서비스 를 가로질러 요청 를 walk 가능.

**§ 6 - § 8 공통 Design 룰:**

- 세 telemetry-ingestion 프로토콜 은 anomaly detection, SLO burn-rate evaluation, RCA
  가 룰 / 정책 인용 뿐만 아니라 real 텔레메트리 에 ground 하도록 존재. Design
  계약 는 [scope-expansion-ko.md § 3.2](../fork-and-sequencing/scope-expansion-ko.md) 에.
- 업스트림 기본값 는 no-op 프로바이더 - 어떤 구체적인 어댑터 도 wire 되기 전에
  다운스트림 소비자 가 안정된 인터페이스 로 작성자 가능.
- 벤더 SDK 가져오기 는 `delivery/<vendor>/` 에 confined; `core/` 는 프로토콜 만 가져오기 -
  [`scripts/quality/architecture/check-core-imports.sh`](../../../scripts/quality/architecture/check-core-imports.sh) 에 의해 강제.

## Azure-Phase 실현 (요약)

현재 Azure 구현은 위의 계약 표와 구현 원장에 기록돼 있으며 구체적인 tier는 채택 시점에
확인하는 것이 좋습니다. 프로바이더 native 이벤트 소스는 Kafka 버스로 전달할 수 있지만
`core/`의 런타임 의존성이 되지 않습니다.

## 승인된 대안 Azure 구현(Approved 대안 Azure Implementations)

Azure 내부 대안은 `core/`를 바꾸지 않고 인프라 모듈 또는 조립 경계에서 교체합니다.
계약 열은 그대로 유지되며 선택한 모듈과 구성만 바뀝니다.

| 경계 | Day-zero 기본 | 승인된 대안(Azure) | 스왑 시 변경 | 유지되는 것(계약) |
|------|--------------|-------------------|-------------|-------------------|
| Event 버스 | Event Hubs Standard (Kafka `:9093`) | **Strimzi** 통한 AKS 위 Kafka; **Confluent Cloud** (멀티 클라우드 관리형); AKS 위 **Redpanda** | 브로커 엔드포인트, 인증 메커니즘, 비용 프로파일 | Kafka 와이어 프로토콜, 토픽 + DLQ 명명(`<topic>.dlq`), 멱등성 키, partition-key로 순서 |
| 런타임 | Container Apps (Consumption + KEDA) | **AKS** + Knative Serving + KEDA; 버스트/바인딩용 **Azure Functions** (Premium 계획); 공개 HTTPS 표면 필요 시 **App Service** | 스케일 트리거 렌더링, 프로브 배선, 사이드카 레이아웃 | OCI 이미지, Knative 호환 매니페스트 서브셋, `/healthz` + `/readyz` 계약, `scale-on:kafka-lag` 신호 |
| 상태 저장소 | PostgreSQL Flexible + `pgvector` | RU-미터링과 지역 쓰기가 단일 기본을 초과할 때 **Cosmos DB** (SQL API); TDE / SQL-Server 호환이 필수일 때 **Azure SQL Managed Instance** | SQL 방언, 마이그레이션 도구, RU 비용 모델 | 감사 hash-chain 스키마, 버전된 이벤트/액션/룰 계약, `SchemaRegistry`+`ContractValidator` 경계 |
| Vector 저장소 | `pgvector` (상태 저장소와 co-located) | **Azure AI Search** 벡터 인덱스; AKS 위 **Qdrant** / **Milvus** | 인덱스 타입(HNSW/IVFFlat), 거리 메트릭, 새로 고침 경로 | 임베딩 차원, 모델 선택(설정), T1 유사도 임계값 |
| 시크릿 | Container Apps native `secret` + Key Vault 참조 | Key Vault 를 가리키는 `SecretStore` CRD 로 **AKS + 외부 Secrets Operator**; FIPS-규제 데이터용 **Key Vault Premium** (HSM-backed) | 주입 레이어(Container Apps native ↔ ESO) | env-var-only 읽기, upper-snake env 이름, 시작 시 실패 시 차단, `core/` 에 SDK 호출 없음 |
| 워크로드 신원 | User-assigned MI | **Federated 워크로드 신원** (GH Actions OIDC ↔ Entra federated 자격 증명; AKS 워크로드 신원 federation); 리소스 principal 이 단일-소유자일 때 **System-assigned MI** | trust 설정과 토큰 대상 | `WorkloadIdentity` 인터페이스, JIT-스코프 롤, cross-domain assumption 거부 |
| Container 레지스트리 | ACR Basic | **ACR Standard/Premium** (지역 replication, 프라이빗 엔드포인트); 외부 레지스트리로 **GHCR** 또는 **Docker 허브** | 티어 비용, 서명 + 증명 위치 | pin-by-digest, `latest` 없음, SBOM + 출처 이력 기록 |
| Observability | Log Analytics workspace + 여기 바인딩된 App Insights | 독립형 Application Insights; **Grafana Managed for Azure** + Prometheus + Loki; OTel 내보내기 도구 뒤의 벤더 APM | 대시보드, 알림 규칙, 보존 가격 | OpenTelemetry SDK, `correlation_id`, KPI 당 하나의 원격측정 소스 |
| HIL 채팅 | Bot Framework / Teams 통한 Azure Bot(Free) | Container App 위 **커스텀 웹훅 어댑터**; [`chatops`] 전달 어댑터 통한 Slack 네이티브 봇 | 인증된 전송, Adaptive 카드 렌더러 | approval-message 계약, action-bound HIL id, 실패 시 차단 타임아웃 |
| 읽기 전용 콘솔 호스팅 | Static Web Apps (Free) | Storage static-website + **Front Door**; **App Service Static Sites** | HTTPS 표면, 커스텀 도메인 배선 | 읽기 전용 보장, Entra sign-in, privileged 호출 없음 |
| 인벤토리 | Azure Resource Graph + Activity Log delta | ARG 가 느린 테넌트용 **ARM 목록** 폴링 (per-resource-type, 샤딩된); 대상 집합에 권위 있는 하다면 **Microsoft Defender for Cloud 인벤토리** | 쿼리 언어 (Kusto vs REST), delta 커서 시망틱스, 최신성 lag | `Inventory` 프로토콜 모양, CSP-중립 `resource_type` + 링크 종류, 멱등 upsert, 부분 스냅샷 실패 시 차단 |

모든 대안은 기본 모듈의 출력 계약을 유지하고 별도로 선택되는 모듈로 제공하며 배포 명명 규약과
자체 shadow 검증을 따릅니다. 어떤 대안도 `core/`에 벤더 SDK 의존성을 추가하지 않습니다.

## 비-Azure 경로 (가산)

다른 CSP 를 추가하는 것은 **포크 수준 구성 작업** 이며 코어 변경이 아닙니다:

1. 조립 루트 에서 `shared/providers/` 의 여덟 프로바이더 인터페이스 새 구현을
   등록 ([project-structure-ko.md](project-structure-ko.md#customization-via-dependency-injection)).
2. `bootstrap.servers`, `SecretProvider`, `RuntimeAdapter`, `WorkloadIdentity`, `Inventory`,
   `MetricProvider`, `LogQueryProvider`, `TraceQueryProvider` 바인딩을 새 CSP로 지시.
3. 같은 OCI 이미지 + Knative 호환 매니페스트를 대상 런타임으로 렌더링.
4. Azure 구현과의 동등성 가 측정될 때까지 **shadow 모드** 로 배송
   ([architecture.instructions.md](../../../.github/instructions/architecture.instructions.md#safety-invariants)).

**비-Azure 대상은 TBD 로 남아있음**
([구현 Focus](../../../.github/copilot-instructions.md#implementation-focus-must));
계약은 미래 어댑터가 가산 하도록 존재.

## Anti-Patterns (간결)

- 각 CSP 의 native pub/sub (`Service Bus` + `SQS/SNS` + `Pub/Sub`) 을 하나의 인터페이스
  뒤에 감싸는 것. Ack 시맨틱, 정렬 키, DLQ 모양, exactly-once 동작이 충분히 다르므로
  프로바이더 특이 버그가 새어나옴 - **대신 하나의 와이어 프로토콜 (Kafka) 사용**.
- **Dapr** 를 portability 레이어로 도입. 락인이 CSP 에서 Dapr 로 옮겨질 뿐이고 사이드카
  의존이 추가되며 로컬 개발이 복잡해짐.
- "Kafka 클라이언트 복잡성을 아끼려고" **Event Hubs 를 native AMQP SDK 로** 사용. 코드가
  다시 Azure 화됨. Kafka 엔드포인트 를 쓰거나 Event Hubs 를 쓰지 마세요.
- 애플리케이션 코드에서 `SecretClient` 호출로 시크릿 읽기 (계약 3 참조).
- `core/` 안의 `DefaultAzureCredential()` (또는 동등물) (계약 4 참조).

## 관련 문서

| 학습 대상 | 문서 |
|-----------|------|
| 이 계약을 실현하는 구체 스택 | [tech-stack-ko.md](tech-stack-ko.md) |
| 계약에서 렌더링되는 Azure 리소스 인벤토리 | [deploy-and-onboard-ko.md#azure-resource-inventory-minimum-set](../deployment/deploy-and-onboard-ko.md#azure-resource-inventory-minimum-set) |
| 신원 모델과 시크릿 취급 심층 | [security-and-identity-ko.md](security-and-identity-ko.md) |
| 각 계약을 조립 루트에 노출하는 DI 경계 | [project-structure-ko.md#주입-가능한-seams](project-structure-ko.md#주입-가능한-seams) |
