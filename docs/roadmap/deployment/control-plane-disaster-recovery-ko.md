---
title: 컨트롤 플레인 재해 복구
translation_of: control-plane-disaster-recovery.md
translation_source_sha: b74b9a9b53a058b18ee73db893972c76a94c494e
translation_revised: 2026-07-31
---

# 컨트롤 플레인 재해 복구

이 문서는 두 번째 executor를 만들거나 event 복구 경계를 잃거나 backup을 복구 증거로 오인하지
않고 FDAI 배포를 지역 장애에서 복구하는 방법을 정의합니다. 복구 profile, 상태 순서, platform
제약, failback 계약 및 컨트롤 플레인 DR을 주장하기 전에 필요한 evidence를 다룹니다.

> **범위:** Upstream은 재사용 가능한 복구 계약을 정의합니다. Downstream 배포는 region, numeric
> recovery point objective(RPO)와 recovery time objective(RTO), identity, resource reference,
> owner, approval 및 측정된 훈련 evidence를 제공합니다.
>
> **구현 상태:** 단일 region baseline, production backup과 availability-zone gate, immutable
> recovery-plan reducer, durable compare-and-set coordinator, action-bound approval-verification
> seam, DR adapter, database restore verifier 및 예약된 drill job은 제공됩니다. Scheduler는 active
> handle을 추적하고 한 process 안에서 capacity를 원자적으로 예약합니다. 대체 region
> infrastructure, cross-process experiment reservation, event-data 연속성, provider action
> binding, traffic failover 및 측정된 failover/failback evidence는 gate를 통과하기 전까지 배포
> 작업으로 남습니다.

## 설계 요약

FDAI는 write authority를 가진 recovery epoch가 정확히 하나인 active-passive regional model을
사용합니다. Recovery runtime이 event를 소비하거나 action을 실행하기 전에 이전 epoch를
fencing합니다. Event 복구 전에 state를 복원하고 검증하며, audit replay는 judge-only이고,
dependency, identity, integrity 및 canary 검사가 통과한 후에만 traffic을 전환합니다.

배포는 측정된 objective에 따라 하나의 profile을 선택합니다.

| Profile | 상시 secondary | 사용 목적 | 승격 조건 |
|---------|----------------|-----------|-----------|
| `restore` | Backup, image, Terraform state 및 recovery configuration만 유지 | Regional reprovisioning과 database restore를 허용하는 RTO | 전체 restore가 승인된 RTO 안에 완료됨을 drill로 입증 |
| `warm` | Secondary network, identity, event-bus metadata, registry replica 및 비활성 runtime | `restore` profile로 달성할 수 없는 RTO | Fencing, state recovery, activation 및 capacity가 승인된 RTO 안에 완료됨을 drill로 입증 |

Active-active execution은 지원되지 않습니다. Read-only service는 multi-region일 수 있지만 Thor의
privileged executor와 event-consumption authority는 single-writer로 유지합니다.

## 필수 plan 입력

Production recovery plan은 immutable하고 versioned입니다. 다음을 기록합니다.

- **Identity:** plan id, revision, deployment profile, primary region, recovery region 및 scope.
- **Business objective:** 승인된 RPO, RTO, 최대 degraded duration 및 outage scenario.
- **Authority:** requester, reliability owner, operations owner, approver, executor identity 및
  break-glass policy. Requester는 같은 activation을 승인할 수 없습니다.
- **Safety:** stop condition, rollback 또는 state-forward recovery, 최대 영향 resource 수,
  kill-switch state 및 primary fencing 방법.
- **State source:** Terraform state, image digest, database recovery source, audit checkpoint,
  event recovery source, secret strategy 및 configuration digest.
- **Verification:** integrity check, identity와 private-network probe, replay bound, canary,
  application smoke check 및 cleanup check.
- **Failback:** target region, data reconciliation 방법, 새 recovery epoch 및 acceptance gate.

누락되거나 만료되거나 충돌하는 입력이 있으면 plan은 `draft`에 머뭅니다. Runtime environment,
fork 상태 또는 incident severity만으로 plan을 승격할 수 없습니다.

## 장애 영역

| 장애 | 복구 대응 | 변경되지 않는 항목 |
|------|-----------|--------------------|
| Container 또는 host | Container Apps가 replica를 교체 | Recovery epoch와 regional authority |
| Availability zone | Zone-redundant service와 replica가 손실 흡수 | Regional failover를 선언하지 않음 |
| Azure region | 승인된 regional recovery plan 활성화 | Safety gate, approval separation, audit requirement |
| Logical data corruption | Corruption 이전 시점으로 격리 복원 후 검증 | Region이 healthy여도 corrupted state는 허용하지 않음 |
| Identity 또는 policy loss | Least-privilege probe 통과 전 activation 보류 | Log나 embedded config에서 credential을 복사하지 않음 |
| Event-data loss | 선언된 durable source에서 복구하고 gap 기록 | Event Hubs metadata recovery를 event-data recovery로 간주하지 않음 |

## Azure service 제약

CSP-neutral plan은 capability를 기록합니다. Azure adapter와 Terraform profile은 다음 Azure
제약을 적용합니다.

| Service | Recovery 계약 |
|---------|---------------|
| Container Apps | Container Apps environment는 regional입니다. Regional recovery에는 별도 environment, virtual network, image availability 및 명시적 traffic-routing mechanism이 필요합니다. Local container storage는 recovery source가 아닙니다. |
| Event Hubs | Geo-disaster recovery는 namespace metadata만 복제하고 event는 복제하지 않습니다. Primary offset은 secondary namespace에서 재사용할 수 없습니다. Plan은 Capture, application federation, producer replay 또는 승인된 data gap을 선언하고 RBAC를 다시 만들며 private endpoint를 검증합니다. |
| PostgreSQL Flexible Server | Same-region PITR은 새 server를 만듭니다. Geo-redundant backup은 paired region에서 사용 가능한 최신 copy만 복원하고 asynchronous이며 remote PITR이 아닙니다. 더 엄격한 RPO에는 측정된 replica 또는 다른 승인된 data-continuity 설계가 필요합니다. |
| Key Vault | Microsoft-managed regional failover는 지연될 수 있고 read-only일 수 있습니다. 더 짧은 RTO에는 승인된 synchronization 및 rotation process를 가진 별도 regional vault를 사용합니다. Soft delete와 purge protection은 계속 필요합니다. |
| Azure Container Registry | Geo-replication은 Premium이 필요하고 eventually consistent입니다. Compute를 시작하기 전에 recovery region에서 정확한 image digest를 검증합니다. Tag는 evidence가 아닙니다. |
| Storage | Recovery artifact는 승인된 region과 residency rule을 충족하는 replication profile을 사용합니다. Blob availability만으로 artifact digest나 freshness를 입증할 수 없습니다. |
| Terraform backend | State, lock, provider version 및 승인된 plan은 장애가 난 application region 밖에서 사용할 수 있어야 합니다. Apply를 성공시키기 위해 state를 수동 편집하지 않습니다. |

현재 platform 참고 문서:

- [Event Hubs geo-disaster recovery](https://learn.microsoft.com/azure/event-hubs/event-hubs-geo-dr)
- [PostgreSQL Flexible Server backup and restore](https://learn.microsoft.com/azure/postgresql/backup-restore/concepts-backup-restore)
- [Container Apps reliability](https://learn.microsoft.com/azure/reliability/reliability-container-apps)
- [Key Vault reliability](https://learn.microsoft.com/azure/reliability/reliability-key-vault)
- [Azure Container Registry geo-replication](https://learn.microsoft.com/azure/container-registry/container-registry-geo-replication)

## 복구 상태 순서

모든 transition은 예상 plan revision과 state를 검사합니다. 경쟁에서 진 writer나 stale writer는
어떤 activation이 이겼는지 추측하지 않고 canonical record를 다시 읽습니다.

```text
draft -> ready -> approved -> activating -> primary_fenced
      -> state_restored -> runtime_started -> audit_verified
      -> event_recovery_ready -> traffic_shifted -> service_verified
      -> active_recovery -> failback_ready -> failing_back
      -> primary_verified -> closed
```

`halted`는 해당 plan revision에서 terminal입니다. `activating`부터 `primary_verified`까지 어떤
transition에서도 stop condition이 발동하면 halt할 수 있습니다. Halted record의 label을 바꾸지
않고 새 revision과 approval을 통해서만 복구를 계속합니다.

### Activation 순서

1. **Incident와 plan 확인:** outage start, plan revision, objective, authority 및 fresh evidence를
   binding합니다. Drill은 같은 순서를 사용하지만 production traffic을 받을 수 없습니다.
2. **Primary fencing:** kill switch를 활성화하고 이전 executor path를 revoke 또는 isolate한 뒤
   단조 증가하는 recovery epoch를 획득합니다. Fence가 독립적으로 관측되기 전까지 secondary
   execution은 비활성 상태를 유지합니다.
3. **Dependency 준비:** Terraform state와 image digest를 검증하고 recovery network, identity,
   private DNS, RBAC, Key Vault strategy, Event Hubs namespace 및 observability path를
   provision하거나 검증합니다.
4. **State 복원:** PostgreSQL과 immutable artifact를 복원한 후 schema, hash-chain, integrity,
   retention 및 application smoke check를 실행합니다. 검증할 수 없는 restore는 halt합니다.
5. **Authority 없이 시작:** Consumer와 privileged execution을 비활성화한 recovery mode로
   runtime을 시작합니다. Readiness는 state, event bus, identity, catalog 및 audit writer를
   입증해야 합니다.
6. **Audit replay 검증:** 복원된 decision을 judge-only mode로 replay합니다. Replay는 executor를
   호출하지 않으며 hash 또는 schema gap 없이 선언된 checkpoint에서 멈춰야 합니다.
7. **Event 복구:** 선언된 event source와 bounded time window를 선택합니다. Causal 및 per-resource
   ordering을 보존하고 original idempotency key를 유지하며 ambiguity는 human review로 보냅니다.
8. **Authority와 traffic 전환:** Canary와 capacity check가 통과한 후 recovery epoch, consumer 및
   필요한 route만 활성화합니다. Stale epoch는 계속 write할 수 없어야 합니다.
9. **Service 검증:** RPO와 RTO를 측정해 승인된 objective와 비교하고 impact scope 및 residual
   gap을 기록합니다. Objective breach는 실패한 recovery exercise입니다.

## Event 복구 계약

DLQ replay만으로는 완전한 regional recovery strategy가 되지 않습니다. Recovery plan은 다음을
기록합니다.

- 장애 전에 commit되지 않은 event의 authoritative source;
- 시작과 종료 timestamp, partition 또는 causal key, 마지막 durable audit checkpoint;
- source와 복원된 audit state 사이의 예상 gap;
- original event id와 idempotency key;
- publish 전 ordering 및 deduplication 검증;
- stale, malformed, missing 또는 conflicting record의 disposition;
- 수락된 모든 event가 terminal audited outcome에 도달했음을 보여주는 completion evidence.

Source가 completeness를 입증할 수 없으면 FDAI는 gap을 기록하고 관련 action을 human review로
보냅니다. Offset을 만들어 내거나 secondary topic의 끝에서 조용히 시작하거나 빈 topic을 성공한
복구로 간주하지 않습니다.

## Failback 계약

Failback은 failover command의 역순이 아니라 새 governed recovery입니다.

1. Active recovery region을 현재 source of truth로 간주합니다.
2. Target, objective 또는 procedure가 바뀌면 새 plan revision을 만듭니다. 별도 failback
   approval을 기록한 후 `failing_back` 시작 시 새 epoch를 할당합니다.
3. Active source에서 state를 rebuild 또는 resynchronize합니다. Stale primary store를 재시작하지
   않습니다.
4. Identity, network, image digest, state integrity, event checkpoint 및 capacity를 검증합니다.
5. Consumer나 privileged execution을 전환하기 전에 active recovery epoch를 fencing합니다.
6. Traffic을 전환하고 canary와 smoke check를 실행하며 verification window가 닫힐 때까지 이전
   active region으로 rollback할 수 있게 유지합니다.
7. 선택한 recovery profile을 다시 수립하고 cleanup과 evidence retention 후에만 종료합니다.

## Evidence와 승격

각 activation과 drill은 sanitized immutable evidence를 저장합니다.

- plan id와 revision, recovery epoch, trigger, outage window, actor와 approval reference;
- 승인된 RPO/RTO와 달성한 RPO/RTO 및 measurement timestamp;
- primary-fence receipt와 stale epoch가 write할 수 없음을 보여주는 proof;
- Terraform plan digest, image digest, configuration digest 및 provider version;
- database restore point, integrity report, audit checkpoint와 hash-chain result;
- event source, bounded replay window, count, gap, duplicate 및 terminal outcome;
- identity, RBAC, private DNS, secret, event-bus, readiness, canary 및 capacity result;
- traffic shift, rollback 또는 failback receipt, cleanup result 및 residual risk.

Reliability owner가 numeric objective를 승인하고 완전한 isolated restore와 regional
failover/failback drill이 이를 충족할 때까지 production은 차단됩니다. 세 번의 shadow 또는 dry-run
plan은 한 번의 substrate-backed exercise를 대체하지 않습니다.

## 구현 경계

- `core/`는 immutable plan validation과 legal transition을 소유하고 Azure를 호출하지 않습니다.
- Durable coordinator는 approval authenticity, 예상 revision/state, monotonic transition time
   및 compare-and-set ownership을 검증한 후 `StateStore`를 통해 plan projection과 audit row를
   원자적으로 저장합니다. Exact redelivery는 commit된 record를 반환하고 변경된 evidence는
   conflict입니다. Idempotency digest가 evidence, approval 및 epoch를 commit하기 때문입니다.
- Provider Protocol은 fencing, state restore, event recovery, traffic shift 및 probe를 소유합니다.
- Azure adapter는 managed identity와 bounded operation으로 해당 Protocol을 구현합니다.
- Terraform은 선택된 profile을 렌더링하며 deployment value는 upstream source 밖에 둡니다.
- Process journal과 append-only audit chain이 durable transition authority입니다.
- Console은 read-only이며 action을 활성화하지 않고 unavailable 또는 recovering state를 보고합니다.

## 관련 문서

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| Regional failover 및 failback 절차 | [컨트롤 플레인 failover runbook](../../runbooks/control-plane-failover-ko.md) |
| 단일 region 배포와 release rollback | [Deployment](deployment-ko.md) |
| 예약된 workload DR과 database restore drill | [Phase 3 integrated loop](../phases/phase-3-integrated-loop-ko.md) |
| Runtime startup 및 readiness gate | [Startup and lifecycle](../operations/startup-and-lifecycle-ko.md) |
| Operational signal과 runbook requirement | [Operating and verification](../operations/operating-and-verification-ko.md) |
| Production architecture approval evidence | [Architecture Review Board packet](../architecture/architecture-review-board-ko.md) |
