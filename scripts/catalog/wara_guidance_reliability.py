"""Reviewed reliability mechanisms used by explicit WARA GUID bindings."""
# ruff: noqa: E501

from __future__ import annotations

from typing import Any


def localized(en: str, ko: str | None = None) -> dict[str, str]:
    return {"en": en, **({"ko": ko} if ko else {})}


def profile(
    shape: str,
    rationale: tuple[str, str],
    applies: tuple[str, str],
    before: tuple[str, str],
    after: tuple[str, str],
    configure: tuple[str, str],
    verify: tuple[str, str],
    caution: tuple[str, str],
) -> dict[str, Any]:
    return {
        "shape": shape,
        **{
            key: localized(*value)
            for key, value in (
                ("rationale", rationale),
                ("applies", applies),
                ("before", before),
                ("after", after),
                ("configure", configure),
                ("verify", verify),
                ("caution", caution),
            )
        },
    }


PROFILES = {
    "zone": profile(
        "zone-redundancy",
        (
            "Availability zones separate datacenter failure domains inside one region. Resilience depends on the selected service's actual zone behavior and on compute, state and routing surviving the same failure; a zone label alone does not establish application availability.",
            "가용성 영역은 한 지역 안의 데이터센터 장애 범위를 분리합니다. 서비스의 실제 영역 지원 방식과 컴퓨팅, 데이터, 라우팅을 함께 확인해야 합니다. 영역이 지정되어 있다는 사실만으로 애플리케이션 가용성을 판단할 수는 없습니다.",
        ),
        (
            "Check the exact service, SKU, region, deployment generation and minimum capacity before selecting or changing zones.",
            "영역을 선택하거나 변경하기 전에 서비스, SKU, 지역, 배포 세대와 최소 용량 조건을 확인합니다.",
        ),
        (
            "A resource or its dependencies can be concentrated in one zone, even when another layer is zone-redundant.",
            "일부 계층이 영역 중복을 지원하더라도 리소스나 의존 리소스가 한 영역에 집중되어 있을 수 있습니다.",
        ),
        (
            "Eligible resources and required dependencies use the documented zone-resilient configuration, with enough surviving capacity.",
            "지원되는 리소스와 필수 의존 리소스에 문서가 정한 영역 복원력 구성을 적용하고, 장애 후 남는 용량을 확보합니다.",
        ),
        (
            "Review which zone settings are creation-time only. Plan a supported migration if the current resource cannot be changed in place, then distribute workload and state according to the service's model.",
            "생성할 때만 지정할 수 있는 영역 설정을 확인합니다. 기존 리소스를 직접 변경할 수 없다면 지원되는 이전 방식을 계획한 뒤 서비스 구조에 맞게 워크로드와 데이터를 분산합니다.",
        ),
        (
            "Use a separately authorized failure exercise or existing failover evidence to verify application requests and state access when a zone is unavailable; measure remaining capacity and reconnect time.",
            "별도로 승인된 장애 시험이나 기존 장애 조치 기록으로 한 영역을 사용할 수 없을 때 요청 처리와 데이터 접근을 검증합니다. 남는 용량과 재연결 시간을 측정합니다.",
        ),
        (
            "Zone redundancy is not cross-region disaster recovery and does not provide point-in-time recovery from corruption or deletion.",
            "영역 중복은 지역 간 재해 복구가 아니며, 데이터 손상이나 삭제 이전 시점으로 복구하는 기능도 아닙니다.",
        ),
    ),
    "region": profile(
        "regional-failover",
        (
            "A second region reduces dependence on one regional deployment only when traffic can reach it and its state, identity, network and capacity are usable. The routing decision and the readiness evidence are separate from merely creating another resource.",
            "두 번째 지역은 트래픽이 도달하고 데이터, 신원, 네트워크, 용량을 사용할 수 있어야 복구에 도움이 됩니다. 리소스를 하나 더 만드는 작업과 라우팅 전환, 준비 상태 확인은 서로 다른 절차입니다.",
        ),
        (
            "Apply when the workload's regional outage objectives justify an independent regional deployment; identify data-loss and recovery-time limits first.",
            "지역 장애 목표에 따라 독립적인 지역 배포가 필요한 워크로드에 적용합니다. 먼저 허용 가능한 데이터 손실과 복구 시간을 정합니다.",
        ),
        (
            "Traffic and required dependencies can rely on a single regional path, with no demonstrated alternate-region readiness.",
            "트래픽과 필수 의존 리소스가 한 지역 경로에 의존하고, 대체 지역의 준비 상태는 확인되지 않았을 수 있습니다.",
        ),
        (
            "Primary and secondary regional paths have explicit routing, compatible dependencies and recorded readiness criteria.",
            "주 지역과 보조 지역의 경로에 명시적인 라우팅, 호환되는 의존 리소스와 준비 상태 기준을 마련합니다.",
        ),
        (
            "Choose the supported regional pattern, prepare independent dependencies and capacity, and define the traffic-switch and failback procedure including state reconciliation.",
            "지원되는 지역 배포 방식을 선택하고 독립적인 의존 리소스와 용량을 준비합니다. 데이터 상태 조정을 포함한 트래픽 전환과 원복 절차를 정합니다.",
        ),
        (
            "Validate alternate-region requests using approved existing evidence or a bounded exercise. Record replication lag, routing convergence, dependency access and failback results separately.",
            "기존의 승인된 기록이나 범위가 제한된 시험으로 대체 지역의 요청 처리를 검증합니다. 복제 지연, 라우팅 수렴, 의존 리소스 접근과 원복 결과를 각각 기록합니다.",
        ),
        (
            "A secondary resource does not imply automatic failover, zero data loss or unrestricted data movement between regions.",
            "보조 리소스가 있다고 해서 자동 장애 조치, 무손실 복구 또는 지역 간 자유로운 데이터 이동이 보장되지는 않습니다.",
        ),
    ),
    "replication": profile(
        "replication",
        (
            "Replicas provide additional serving or recovery copies, but the mechanism differs between compute replicas, synchronous state replication and asynchronous data replication. The source recommendation determines which model applies; lag and shared failure domains remain important.",
            "복제본은 추가 처리 용량이나 복구용 사본을 제공합니다. 컴퓨팅 복제본, 동기 데이터 복제, 비동기 데이터 복제는 서로 다릅니다. 원본 권고가 요구하는 방식을 확인하고 복제 지연과 공통 장애 범위를 검토합니다.",
        ),
        (
            "Confirm whether the recommendation concerns serving instances, data replicas or artifact replicas and which failover or promotion operations are supported.",
            "권고가 처리 인스턴스, 데이터 복제본, 배포 아티팩트 중 무엇을 대상으로 하는지 확인하고 지원되는 장애 조치와 승격 방식을 검토합니다.",
        ),
        (
            "One serving copy or an unverified replica can leave the workload dependent on the original instance or location.",
            "처리 사본이 하나뿐이거나 복제본을 확인하지 않으면 원래 인스턴스나 위치에 계속 의존할 수 있습니다.",
        ),
        (
            "The required replica set is healthy, sufficiently independent and connected to an explicit serving or recovery procedure.",
            "필요한 복제본의 상태와 독립성을 확인하고 명시적인 처리 또는 복구 절차에 연결합니다.",
        ),
        (
            "Provision the source-specific replica topology, configure synchronization or workload distribution, and document who selects a replacement and how clients reconnect.",
            "권고에 맞는 복제본 구조를 준비하고 동기화 또는 부하 분산을 구성합니다. 대체 대상을 선택하는 담당자와 클라이언트 재연결 방법을 문서화합니다.",
        ),
        (
            "Inspect each actual replica, readiness and any lag, then validate loss of the original path using an approved exercise or prior evidence. Check data consistency as well as request availability.",
            "실제 복제본의 준비 상태와 지연을 확인한 뒤 승인된 시험이나 기존 기록으로 원래 경로가 사라졌을 때의 동작을 검증합니다. 요청 가용성과 데이터 일관성을 함께 확인합니다.",
        ),
        (
            "Replication can propagate deletion or corruption. It is not a substitute for retained recovery points, and asynchronous replication can lose recent writes at failover.",
            "복제는 삭제나 손상도 전달할 수 있으므로 보존된 복구 지점을 대신하지 못합니다. 비동기 복제는 장애 조치 때 최근 쓰기 일부가 손실될 수 있습니다.",
        ),
    ),
    "backup": profile(
        "backup-restore",
        (
            "A backup retains recoverable state independently of the current live copy. Protection is demonstrated by successful recovery points and a usable restoration procedure, not by a policy assignment or a recent backup-job start.",
            "백업은 현재 운영 사본과 별도로 복구 가능한 상태를 보존합니다. 정책 할당이나 작업 시작 기록만으로 보호 상태를 판단하지 않고, 성공한 복구 지점과 실제로 사용할 수 있는 복원 절차를 확인합니다.",
        ),
        (
            "Identify the exact supported data or configuration objects, consistency requirements, retention, recovery location and encryption-key dependencies.",
            "지원되는 데이터와 구성 개체, 일관성 조건, 보존 기간, 복구 위치와 암호화 키 의존성을 확인합니다.",
        ),
        (
            "Live data or configuration may have no recent recoverable copy, or recovery has not been demonstrated.",
            "운영 데이터나 구성에 최근 복구 사본이 없거나 복구 가능성을 확인하지 않았을 수 있습니다.",
        ),
        (
            "The intended objects have successful retained recovery points and a documented, tested restoration path.",
            "보호 대상에 성공한 복구 지점을 보존하고 문서화된 복원 경로를 시험합니다.",
        ),
        (
            "Select the service-supported protection mechanism and schedule, protect required keys and metadata, and arrange a nonproduction restore target with suitable permissions.",
            "서비스가 지원하는 보호 방식과 일정을 선택하고 필요한 키와 메타데이터를 보존합니다. 적절한 권한을 가진 비운영 복원 대상을 준비합니다.",
        ),
        (
            "Check job completion and recovery-point freshness, restore a representative object into an isolated target, and verify application-level consistency and measured recovery time.",
            "작업 완료와 복구 지점의 최신성을 확인합니다. 대표 개체를 격리된 대상에 복원하고 애플리케이션 수준의 일관성과 실제 복구 시간을 검증합니다.",
        ),
        (
            "A snapshot, replication relationship and independently retained backup have different failure coverage. Do not promise regional recovery unless the specific protection mechanism supports it.",
            "스냅샷, 복제 관계, 독립적으로 보존한 백업은 보호하는 장애 범위가 다릅니다. 해당 방식의 지원 여부를 확인하지 않고 지역 복구를 약속하지 않습니다.",
        ),
    ),
    "restore-test": profile(
        "recovery-exercise",
        (
            "A recovery feature is useful only if the intended state can be restored and the workload works afterward. An isolated recovery exercise distinguishes configuration eligibility from actual recovery-point access, boot, data integrity and application performance.",
            "복구 기능은 필요한 상태를 복원하고 워크로드가 이후에도 동작해야 의미가 있습니다. 격리된 복구 시험으로 구성 지원 여부와 실제 복구 지점 접근, 부팅, 데이터 무결성, 애플리케이션 성능을 구분해 확인합니다.",
        ),
        (
            "Confirm supported recovery objects, available recovery points, target networking, permissions and the allowed test scope.",
            "지원되는 복구 개체, 사용 가능한 복구 지점, 대상 네트워크, 권한과 허용된 시험 범위를 확인합니다.",
        ),
        (
            "Protection settings exist, but the target's recoverability or behavior after restoration is unproven.",
            "보호 설정은 있지만 대상의 복구 가능성이나 복원 후 동작은 검증되지 않았을 수 있습니다.",
        ),
        (
            "A recorded isolated recovery validates the selected point, target dependencies and business recovery objectives.",
            "선택한 복구 지점, 대상 의존 리소스와 업무 복구 목표를 격리된 시험으로 검증하고 기록합니다.",
        ),
        (
            "Select a recoverable point and isolated target, define stop and cleanup conditions, and prepare workload-specific validation without switching production traffic.",
            "복구 가능한 시점과 격리된 대상을 선택하고 중단 및 정리 조건을 정합니다. 운영 트래픽을 전환하지 않고 워크로드별 검증을 준비합니다.",
        ),
        (
            "Record restoration completion, functional checks, data-loss interval, elapsed recovery time and target cleanup; distinguish a test failover from a production failover.",
            "복원 완료, 기능 확인, 데이터 손실 구간, 경과 시간과 대상 정리 결과를 기록합니다. 시험 장애 조치와 운영 장애 조치를 구분합니다.",
        ),
        (
            "Recovery exercises can create billable resources or expose data. They require separate authorization and must not overwrite live state or assume a production cutover.",
            "복구 시험은 비용이 발생하는 리소스를 만들거나 데이터를 노출할 수 있습니다. 별도 승인을 받아야 하며 운영 상태를 덮어쓰거나 운영 전환을 전제로 해서는 안 됩니다.",
        ),
    ),
    "retention": profile(
        "retention",
        (
            "Soft delete, purge protection and version retention extend the opportunity to recover from accidental removal or overwrite. Their scopes and expiry rules differ, so the exact object type and recovery window must be explicit.",
            "일시 삭제, 제거 보호, 버전 보존은 실수로 삭제하거나 덮어쓴 상태를 복구할 시간을 확보합니다. 적용 개체와 만료 규칙이 다르므로 정확한 대상과 복구 가능 기간을 명시해야 합니다.",
        ),
        (
            "Check support for the exact object type, retention range, irreversible settings and interaction with lifecycle cleanup or legal retention.",
            "대상 개체의 지원 여부, 보존 기간 범위, 되돌릴 수 없는 설정과 수명 주기 정리 또는 법적 보존 조건을 확인합니다.",
        ),
        (
            "Deleted or overwritten objects can become irrecoverable immediately or before operators notice the incident.",
            "삭제하거나 덮어쓴 개체를 즉시 또는 운영자가 문제를 발견하기 전에 복구할 수 없게 될 수 있습니다.",
        ),
        (
            "Eligible deleted objects or prior versions remain recoverable for the configured window with an explicit expiry policy.",
            "지원되는 삭제 개체나 이전 버전을 정해진 기간 동안 복구할 수 있도록 보존하고 만료 정책을 명시합니다.",
        ),
        (
            "Choose a retention window from detection and recovery needs, enable the exact protection setting and document recovery, purge and expiry responsibilities.",
            "탐지와 복구에 필요한 시간을 바탕으로 보존 기간을 정합니다. 정확한 보호 설정을 적용하고 복구, 영구 제거, 만료 책임을 문서화합니다.",
        ),
        (
            "Inspect the effective policy and recover an authorized test object or version before expiry; verify retained state and access permissions rather than only the enabled flag.",
            "적용된 정책을 확인하고 만료 전에 승인된 시험 개체나 버전을 복구합니다. 활성화 표시만 보지 않고 보존 상태와 접근 권한을 검증합니다.",
        ),
        (
            "Expiry or permitted permanent deletion can end recoverability. Protection may be irreversible or increase storage cost; it does not replace independent backup.",
            "기간 만료나 허용된 영구 삭제 뒤에는 복구할 수 없을 수 있습니다. 일부 보호 설정은 해제할 수 없거나 저장 비용을 늘리며, 독립적인 백업을 대신하지는 않습니다.",
        ),
    ),
    "recovery-plan": profile(
        "recovery-plan",
        (
            "Business continuity requires a sequence that restores a usable business flow, including state, identity, networking, capacity and operator access. A plan must make dependencies, decision points, data-loss tradeoffs and failback explicit.",
            "업무 연속성을 확보하려면 데이터, 신원, 네트워크, 용량과 운영자 접근을 포함해 업무 흐름을 복구하는 순서가 필요합니다. 의존성, 판단 시점, 데이터 손실의 절충과 원복 방법을 계획에 명시해야 합니다.",
        ),
        (
            "Use business-approved recovery time and recovery point targets and identify which regional and shared dependencies are actually in scope.",
            "업무에서 승인한 복구 시간과 복구 시점 목표를 사용하고 실제 대상인 지역별 또는 공통 의존 리소스를 확인합니다.",
        ),
        (
            "Individual resources have protection features but the end-to-end recovery order, decision owner or failback is incomplete.",
            "개별 리소스에 보호 기능이 있어도 전체 복구 순서, 판단 책임자 또는 원복 절차가 빠져 있을 수 있습니다.",
        ),
        (
            "A versioned dependency-aware runbook defines activation criteria, ordered recovery, validation and controlled failback.",
            "버전으로 관리하는 실행 지침에 가동 기준, 의존성을 고려한 복구 순서, 검증과 통제된 원복을 정의합니다.",
        ),
        (
            "Map the critical flow and dependencies, choose the supported recovery pattern, assign decision owners and specify rollback, stop conditions and reconciliation of divergent state.",
            "중요 업무 흐름과 의존성을 정리하고 지원되는 복구 방식을 선택합니다. 판단 책임자를 정하고 롤백, 중단 조건과 서로 달라진 데이터의 조정 방법을 명시합니다.",
        ),
        (
            "Exercise the runbook in an approved scope and compare measured recovery time and data loss with targets; record blocked steps and unavailable dependencies instead of declaring success.",
            "승인된 범위에서 실행 지침을 시험하고 실제 복구 시간과 데이터 손실을 목표와 비교합니다. 막힌 단계와 사용할 수 없는 의존 리소스를 성공으로 처리하지 않고 기록합니다.",
        ),
        (
            "A document or backup-job success is not a completed recovery. Regional capacity, identity and manual decision delays can dominate recovery time.",
            "문서 작성이나 백업 작업 성공은 복구 완료가 아닙니다. 지역 용량, 신원 서비스와 사람의 판단 지연이 복구 시간에 큰 영향을 줄 수 있습니다.",
        ),
    ),
    "capacity": profile(
        "capacity",
        (
            "Reliability needs usable headroom for peak demand, maintenance and failures. Quota, reservation, physical availability and application throughput are different constraints: increasing one does not demonstrate that the others are sufficient.",
            "안정적인 운영에는 최대 수요, 유지 관리와 장애를 감당할 여유 용량이 필요합니다. 할당량, 예약, 실제 가용 용량과 애플리케이션 처리량은 서로 다른 제약이므로 하나를 늘렸다고 나머지도 충분한 것은 아닙니다.",
        ),
        (
            "Use measured peak and recovery demand for the exact region, SKU, account and service limit named by the recommendation.",
            "권고가 지정한 지역, SKU, 계정과 서비스 한도에 대해 실제 최대 수요와 복구 수요를 확인합니다.",
        ),
        (
            "Normal operation can consume capacity needed for bursts, upgrades, rebuilds or failover.",
            "평상시 사용량이 급증, 업그레이드, 재구축 또는 장애 조치에 필요한 용량까지 소모할 수 있습니다.",
        ),
        (
            "Measured demand fits within effective limits with documented headroom and an expansion or reservation plan.",
            "실제 수요가 유효 한도 안에 들어오도록 여유 용량을 확보하고 증설 또는 예약 계획을 문서화합니다.",
        ),
        (
            "Inventory current usage and hard limits, forecast peak and failure demand, then plan source-specific quota requests, reservations or scaling with realistic lead times.",
            "현재 사용량과 고정 한도를 확인하고 최대 수요와 장애 시 수요를 예측합니다. 실제 소요 시간을 반영해 필요한 할당량 요청, 예약 또는 확장을 계획합니다.",
        ),
        (
            "Compare observed usage and approved limits with the full demand model; validate representative load and confirm alarms fire before the expansion lead time is exhausted.",
            "실제 사용량과 승인된 한도를 전체 수요 모델과 비교합니다. 대표 부하를 검증하고 증설에 필요한 시간이 부족해지기 전에 경고가 발생하는지 확인합니다.",
        ),
        (
            "Quota approval is not physical capacity allocation; a capacity reservation does not automatically cover every quota, SKU or dependent service.",
            "할당량 승인은 물리적 용량 할당이 아닙니다. 용량 예약도 모든 할당량, SKU 또는 의존 서비스를 자동으로 보장하지는 않습니다.",
        ),
    ),
    "autoscale": profile(
        "autoscale",
        (
            "Automatic scaling changes capacity in response to configured demand signals. It must accommodate scale-out delay, safe scale-in, quota and dependency bottlenecks; prediction or an enabled setting alone does not demonstrate available capacity.",
            "자동 크기 조정은 설정된 수요 신호에 따라 용량을 변경합니다. 확장 지연, 안전한 축소, 할당량과 의존 리소스의 병목을 함께 고려해야 합니다. 예측 결과나 활성화 설정만으로 용량 확보를 판단할 수는 없습니다.",
        ),
        (
            "Confirm the service's supported scaling mode, scaling unit, signals and minimum or maximum limits; forecast-only modes do not perform scaling.",
            "서비스가 지원하는 조정 모드, 용량 단위, 신호와 최소 및 최대 한도를 확인합니다. 예측 전용 모드는 실제로 크기를 변경하지 않습니다.",
        ),
        (
            "Fixed or poorly bounded capacity can saturate under bursts or remove required instances during scale-in.",
            "고정 용량이나 부적절한 조정 범위는 트래픽 급증 때 포화되거나 축소 때 필요한 인스턴스를 제거할 수 있습니다.",
        ),
        (
            "Reviewed scaling bounds, demand signals and cooldowns preserve minimum availability and stay within usable capacity.",
            "검토한 조정 범위, 수요 신호와 대기 시간으로 최소 가용성을 유지하고 실제 가용 용량 안에서 조정합니다.",
        ),
        (
            "Set workload-specific minimums and ceilings, account for quotas and startup time, and define drain behavior before enabling supported scaling actions.",
            "워크로드에 맞는 최소값과 상한을 정하고 할당량과 시작 시간을 반영합니다. 지원되는 자동 조정을 활성화하기 전에 처리 중인 작업을 마무리하는 방법을 정합니다.",
        ),
        (
            "Exercise demand growth and reduction in an approved scope; inspect actual instance or unit changes, queue time, errors and safe completion of in-flight work.",
            "승인된 범위에서 수요 증가와 감소를 시험합니다. 실제 인스턴스나 용량 단위 변화, 대기 시간, 오류와 처리 중인 작업의 안전한 완료를 확인합니다.",
        ),
        (
            "Scaling cannot exceed quotas or fix every downstream bottleneck, and scale-in can interrupt work if the application has no draining or durable-state strategy.",
            "크기 조정은 할당량을 초과하거나 모든 하위 시스템 병목을 해결하지 못합니다. 작업 마무리나 영속 상태 전략이 없으면 축소가 작업을 중단할 수 있습니다.",
        ),
    ),
    "sku": profile(
        "eligibility",
        (
            "The recommended tier or hardware class exposes specific reliability, performance or support capabilities. The choice should be justified by those required capabilities and measured workload demand, rather than assuming a higher price always produces resilience.",
            "권장 계층이나 하드웨어 등급은 특정 복원력, 성능 또는 지원 기능을 제공합니다. 가격이 높으면 항상 안정적이라고 가정하지 않고 필요한 기능과 측정한 수요를 바탕으로 선택해야 합니다.",
        ),
        (
            "Compare exact tier, region, generation, feature compatibility and migration constraints against the source recommendation.",
            "원본 권고를 기준으로 정확한 계층, 지역, 세대, 기능 호환성과 이전 제약을 비교합니다.",
        ),
        (
            "The existing tier may omit a needed capability or fail to sustain the workload's required performance.",
            "현재 계층에 필요한 기능이 없거나 워크로드가 요구하는 성능을 지속적으로 제공하지 못할 수 있습니다.",
        ),
        (
            "A supported SKU supplies the specific required feature with validated application performance and documented cost impact.",
            "지원되는 SKU로 필요한 기능을 제공하고 애플리케이션 성능을 검증하며 비용 영향을 문서화합니다.",
        ),
        (
            "List required features and performance, check the exact support matrix, and plan the supported resize or migration including downtime and rollback.",
            "필요한 기능과 성능을 정리하고 정확한 지원 표를 확인합니다. 중단 시간과 롤백을 포함해 지원되는 크기 변경 또는 이전을 계획합니다.",
        ),
        (
            "Read effective tier and feature configuration, validate representative workload behavior and ensure dependent resources remain compatible after the change.",
            "실제 계층과 기능 구성을 확인하고 대표 워크로드의 동작을 검증합니다. 변경 후 의존 리소스도 호환되는지 확인합니다.",
        ),
        (
            "A tier upgrade does not automatically enable zones, replicas, backups or correct routing. Feature eligibility and actual configuration are separate observations.",
            "계층을 올려도 영역, 복제본, 백업이나 올바른 라우팅이 자동으로 적용되는 것은 아닙니다. 기능 지원 여부와 실제 설정을 별도로 확인합니다.",
        ),
    ),
}
