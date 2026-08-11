---
title: 컨트롤 플레인 재해 복구
translation_of: control-plane-disaster-recovery.md
translation_source_sha: b74b9a9b53a058b18ee73db893972c76a94c494e
translation_revised: 2026-08-11
---

# 컨트롤 플레인 재해 복구

이 문서는 두 번째 실행기를 만들거나 이벤트 복구 경계를 잃거나 백업을 복구 증거로 오인하지
않고 FDAI 배포를 지역 장애에서 복구하는 방법을 정의합니다. 복구 프로파일, 상태 순서, platform
제약, failback 계약 및 컨트롤 플레인 DR을 주장하기 전에 필요한 근거를 다룹니다.

> **범위:** 업스트림은 재사용 가능한 복구 계약을 정의합니다. 다운스트림 배포는 지역, numeric
> 복구 지점 목표(RPO)와 복구 시간 목표(RTO), 신원, 리소스 참조,
> 소유자, 승인 및 측정된 훈련 근거를 제공합니다.
>
> **구현 상태:** 단일 지역 기준선, 운영 백업과 availability-zone 게이트, 변경할 수 없는
> recovery-plan 집약기, 영속 compare-and-set 조정기, action-bound approval-verification
> 경계, DR 어댑터, 데이터베이스 복원 검증기 및 예약된 훈련 작업은 제공됩니다. 스케줄러는 활성
> handle을 추적하고 한 프로세스 안에서 용량을 원자적으로 예약합니다. 대체 지역
> infrastructure, 프로세스 간 실험 reservation, event-data 연속성, 프로바이더 액션
> 연결, 트래픽 장애 조치 및 측정된 장애 조치/failback 근거는 게이트를 통과하기 전까지 배포
> 작업으로 남습니다.

## 설계 요약

FDAI는 쓰기 권한을 가진 복구 epoch가 정확히 하나인 active-passive regional 모델을
사용합니다. 복구 런타임이 이벤트를 소비하거나 액션을 실행하기 전에 이전 epoch를
fencing합니다. Event 복구 전에 상태를 복원하고 검증하며, 감사 재생은 judge-only이고,
의존성, 신원, 무결성 및 canary 검사가 통과한 후에만 트래픽을 전환합니다.

배포는 측정된 목표에 따라 하나의 프로파일을 선택합니다.

| 프로파일 | 상시 보조 | 사용 목적 | 승격 조건 |
|---------|----------------|-----------|-----------|
| `restore` | 백업, 이미지, Terraform 상태 및 복구 구성만 유지 | Regional reprovisioning과 데이터베이스 복원을 허용하는 RTO | 전체 복원이 승인된 RTO 안에 완료됨을 훈련으로 입증 |
| `warm` | 보조 네트워크, 신원, event-bus 메타데이터, 레지스트리 복제본 및 비활성 런타임 | `restore` 프로파일로 달성할 수 없는 RTO | Fencing, 상태 복구, activation 및 용량이 승인된 RTO 안에 완료됨을 훈련으로 입증 |

Active-active 실행은 지원되지 않습니다. 읽기 전용 서비스는 multi-region일 수 있지만 Thor의
privileged 실행기와 event-consumption 권한은 single-writer로 유지합니다.

## 필수 계획 입력

운영 복구 계획은 변경할 수 없고 versioned입니다. 다음을 기록합니다.

- **신원:** 계획 id, 개정 번호, 배포 프로파일, 기본 지역, 복구 지역 및 범위.
- **Business 목표:** 승인된 RPO, RTO, 최대 degraded 소요 시간 및 장애 시나리오.
- **권한:** 요청자, reliability 소유자, operations 소유자, 승인자, 실행기 신원 및
 break-glass 정책. 요청자는 같은 activation을 승인할 수 없습니다.
- **안전성:** stop 조건, 롤백 또는 state-forward 복구, 최대 영향 리소스 수,
 비상 정지 상태 및 기본 fencing 방법.
- **상태 출처:** Terraform 상태, 이미지 다이제스트, 데이터베이스 복구 출처, 감사 체크포인트,
 이벤트 복구 출처, 시크릿 strategy 및 구성 다이제스트.
- **검증:** 무결성 검사, 신원과 private-network 탐색, 재생 한계, canary,
 애플리케이션 smoke 검사 및 정리 검사.
- **Failback:** 대상 지역, 데이터 조정 방법, 새 복구 epoch 및 acceptance 게이트.

누락되거나 만료되거나 충돌하는 입력이 있으면 계획은 `draft`에 머뭅니다. 런타임 환경,
포크 상태 또는 인시던트 심각도만으로 계획을 승격할 수 없습니다.

## 장애 영역

| 장애 | 복구 대응 | 변경되지 않는 항목 |
|------|-----------|--------------------|
| Container 또는 호스트 | Container Apps가 복제본을 교체 | 복구 epoch와 regional 권한 |
| 가용성 영역 | Zone-redundant 서비스와 복제본이 손실 흡수 | Regional 장애 조치를 선언하지 않음 |
| Azure 지역 | 승인된 regional 복구 계획 활성화 | 안전성 게이트, 승인 separation, 감사 요구사항 |
| Logical 데이터 corruption | Corruption 이전 시점으로 격리 복원 후 검증 | 지역이 healthy여도 corrupted 상태는 허용하지 않음 |
| 신원 또는 정책 loss | Least-privilege 탐색 통과 전 activation 보류 | 로그나 embedded 구성에서 자격 증명을 복사하지 않음 |
| Event-data loss | 선언된 영속 출처에서 복구하고 공백 기록 | Event Hubs 메타데이터 복구를 event-data 복구로 간주하지 않음 |

## Azure 서비스 제약

CSP-neutral 계획은 기능을 기록합니다. Azure 어댑터와 Terraform 프로파일은 다음 Azure
제약을 적용합니다.

| 서비스 | 복구 계약 |
|---------|---------------|
| Container Apps | Container Apps 환경은 regional입니다. Regional 복구에는 별도 환경, virtual 네트워크, 이미지 가용성 및 명시적 traffic-routing 방식이 필요합니다. 로컬 컨테이너 저장소는 복구 출처가 아닙니다. |
| Event Hubs | Geo-disaster 복구는 이름 공간 메타데이터만 복제하고 이벤트는 복제하지 않습니다. 기본 오프셋은 보조 이름 공간에서 재사용할 수 없습니다. 계획은 수집, 애플리케이션 federation, 생산자 재생 또는 승인된 데이터 공백을 선언하고 RBAC를 다시 만들며 비공개 엔드포인트를 검증합니다. |
| PostgreSQL Flexible Server | Same-region PITR은 새 서버를 만듭니다. Geo-redundant 백업은 paired 지역에서 사용 가능한 최신 copy만 복원하고 asynchronous이며 원격 PITR이 아닙니다. 더 엄격한 RPO에는 측정된 복제본 또는 다른 승인된 data-continuity 설계가 필요합니다. |
| Key Vault | Microsoft-managed regional 장애 조치는 지연될 수 있고 읽기 전용일 수 있습니다. 더 짧은 RTO에는 승인된 synchronization 및 교대 프로세스를 가진 별도 regional vault를 사용합니다. Soft 삭제와 정리 protection은 계속 필요합니다. |
| Azure Container Registry | Geo-replication은 Premium이 필요하고 eventually consistent입니다. Compute를 시작하기 전에 복구 지역에서 정확한 이미지 다이제스트를 검증합니다. Tag는 근거가 아닙니다. |
| Storage | 복구 산출물은 승인된 지역과 residency 룰을 충족하는 replication 프로파일을 사용합니다. Blob 가용성만으로 산출물 다이제스트나 최신성을 입증할 수 없습니다. |
| Terraform 백엔드 | 상태, 잠금, 프로바이더 버전 및 승인된 계획은 장애가 난 애플리케이션 지역 밖에서 사용할 수 있어야 합니다. 적용을 성공시키기 위해 상태를 수동 편집하지 않습니다. |

현재 platform 참고 문서:

- [Event Hubs geo-disaster 복구](https://learn.microsoft.com/azure/event-hubs/event-hubs-geo-dr)
- [PostgreSQL Flexible Server 백업 and 복원](https://learn.microsoft.com/azure/postgresql/backup-restore/concepts-backup-restore)
- [Container Apps reliability](https://learn.microsoft.com/azure/reliability/reliability-container-apps)
- [Key Vault reliability](https://learn.microsoft.com/azure/reliability/reliability-key-vault)
- [Azure Container Registry geo-replication](https://learn.microsoft.com/azure/container-registry/container-registry-geo-replication)

## 복구 상태 순서

모든 전이는 예상 계획 개정 번호와 상태를 검사합니다. 경쟁에서 진 쓰기 담당나 stale 쓰기 담당은
어떤 activation이 이겼는지 추측하지 않고 정본 기록을 다시 읽습니다.

```text
draft -> ready -> approved -> activating -> primary_fenced
  -> state_restored -> runtime_started -> audit_verified
  -> event_recovery_ready -> traffic_shifted -> service_verified
  -> active_recovery -> failback_ready -> failing_back
  -> primary_verified -> closed
```

`halted`는 해당 계획 개정 번호에서 최종입니다. `activating`부터 `primary_verified`까지 어떤
전이에서도 stop 조건이 발동하면 halt할 수 있습니다. Halted 기록의 라벨을 바꾸지
않고 새 개정 번호와 승인을 통해서만 복구를 계속합니다.

### Activation 순서

1. **인시던트와 계획 확인:** 장애 시작, 계획 개정 번호, 목표, 권한 및 fresh 근거를
 연결합니다. 훈련은 같은 순서를 사용하지만 운영 트래픽을 받을 수 없습니다.
2. **기본 fencing:** kill 전환을 활성화하고 이전 실행기 경로를 철회 또는 isolate한 뒤
 단조 증가하는 복구 epoch를 획득합니다. Fence가 독립적으로 관측되기 전까지 보조
 실행은 비활성 상태를 유지합니다.
3. **의존성 준비:** Terraform 상태와 이미지 다이제스트를 검증하고 복구 네트워크, 신원,
 비공개 DNS, RBAC, Key Vault strategy, Event Hubs 이름 공간 및 observability 경로를
 provision하거나 검증합니다.
4. **상태 복원:** PostgreSQL과 변경할 수 없는 산출물을 복원한 후 스키마, hash-chain, 무결성,
 보존 및 애플리케이션 smoke 검사를 실행합니다. 검증할 수 없는 복원은 halt합니다.
5. **권한 없이 시작:** 소비자와 privileged 실행을 비활성화한 복구 모드로
 런타임을 시작합니다. 준비 상태는 상태, 이벤트 버스, 신원, 카탈로그 및 감사 쓰기 담당을
 입증해야 합니다.
6. **감사 재생 검증:** 복원된 결정을 judge-only 모드로 재생합니다. 재생은 실행기를
 호출하지 않으며 해시 또는 스키마 공백 없이 선언된 체크포인트에서 멈춰야 합니다.
7. **Event 복구:** 선언된 이벤트 출처와 범위가 제한된 시간 구간을 선택합니다. Causal 및 per-resource
 정렬을 보존하고 original 멱등성 키를 유지하며 모호함은 human 검토로 보냅니다.
8. **권한과 트래픽 전환:** Canary와 용량 검사가 통과한 후 복구 epoch, 소비자 및
 필요한 경로만 활성화합니다. Stale epoch는 계속 쓰기할 수 없어야 합니다.
9. **서비스 검증:** RPO와 RTO를 측정해 승인된 목표와 비교하고 영향 범위 및 잔여
 공백을 기록합니다. 목표 breach는 실패한 복구 exercise입니다.

## Event 복구 계약

DLQ 재생만으로는 완전한 regional 복구 strategy가 되지 않습니다. 복구 계획은 다음을
기록합니다.

- 장애 전에 커밋되지 않은 이벤트의 권위 있는 출처;
- 시작과 종료 시각, 파티션 또는 causal 키, 마지막 영속 감사 체크포인트;
- 출처와 복원된 감사 상태 사이의 예상 공백;
- original 이벤트 id와 멱등성 키;
- publish 전 정렬 및 deduplication 검증;
- stale, malformed, 누락된 또는 conflicting 기록의 처리 결과;
- 수락된 모든 이벤트가 최종 audited 결과에 도달했음을 보여주는 완료 근거.

출처가 완전성을 입증할 수 없으면 FDAI는 공백을 기록하고 관련 액션을 human 검토로
보냅니다. 오프셋을 만들어 내거나 보조 토픽의 끝에서 조용히 시작하거나 빈 토픽을 성공한
복구로 간주하지 않습니다.

## Failback 계약

Failback은 장애 조치 명령의 역순이 아니라 새 통제된 복구입니다.

1. 활성 복구 지역을 현재 정본으로 간주합니다.
2. 대상, 목표 또는 procedure가 바뀌면 새 계획 개정 번호를 만듭니다. 별도 failback
 승인을 기록한 후 `failing_back` 시작 시 새 epoch를 할당합니다.
3. 활성 출처에서 상태를 재구축 또는 resynchronize합니다. Stale 기본 저장소를 재시작하지
 않습니다.
4. 신원, 네트워크, 이미지 다이제스트, 상태 무결성, 이벤트 체크포인트 및 용량을 검증합니다.
5. 소비자나 privileged 실행을 전환하기 전에 활성 복구 epoch를 fencing합니다.
6. 트래픽을 전환하고 canary와 smoke 검사를 실행하며 검증 구간이 닫힐 때까지 이전
 활성 지역으로 롤백할 수 있게 유지합니다.
7. 선택한 복구 프로파일을 다시 수립하고 정리와 근거 보존 후에만 종료합니다.

## 근거와 승격

각 activation과 훈련은 정제된 변경할 수 없는 근거를 저장합니다.

- 계획 id와 개정 번호, 복구 epoch, 트리거, 장애 구간, 행위자와 승인 참조;
- 승인된 RPO/RTO와 달성한 RPO/RTO 및 측정 시각;
- primary-fence 증적과 stale epoch가 쓰기할 수 없음을 보여주는 증명;
- Terraform 계획 다이제스트, 이미지 다이제스트, 구성 다이제스트 및 프로바이더 버전;
- 데이터베이스 복원 지점, 무결성 보고, 감사 체크포인트와 hash-chain 결과;
- 이벤트 출처, 범위가 제한된 재생 구간, 개수, 공백, 중복 및 최종 결과;
- 신원, RBAC, 비공개 DNS, 시크릿, event-bus, 준비 상태, canary 및 용량 결과;
- 트래픽 shift, 롤백 또는 failback 증적, 정리 결과 및 잔여 risk.

Reliability 소유자가 numeric 목표를 승인하고 완전한 isolated 복원과 regional
장애 조치/failback 훈련이 이를 충족할 때까지 운영은 차단됩니다. 세 번의 shadow 또는 예행 실행
계획은 한 번의 substrate-backed exercise를 대체하지 않습니다.

## 구현 경계

- `core/`는 변경할 수 없는 계획 검증과 legal 전이를 소유하고 Azure를 호출하지 않습니다.
- 영속 조정기는 승인 authenticity, 예상 개정 번호/상태, 단조 증가 전이 시간
 및 compare-and-set 소유권을 검증한 후 `StateStore`를 통해 계획 변환 결과와 감사 행을
 원자적으로 저장합니다. Exact 재전달은 커밋된 기록을 반환하고 변경된 근거는
 충돌입니다. 멱등성 다이제스트가 근거, 승인 및 epoch를 커밋하기 때문입니다.
- 프로바이더 프로토콜은 fencing, 상태 복원, 이벤트 복구, 트래픽 shift 및 탐색을 소유합니다.
- Azure 어댑터는 managed 신원과 범위가 제한된 연산으로 해당 프로토콜을 구현합니다.
- Terraform은 선택된 프로파일을 렌더링하며 배포 값은 업스트림 출처 밖에 둡니다.
- 프로세스 저널과 추가 전용 감사 체인이 영속 전이 권한입니다.
- Console은 읽기 전용이며 액션을 활성화하지 않고 사용 불가 또는 recovering 상태를 보고합니다.

## 관련 문서

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| Regional 장애 조치 및 failback 절차 | [컨트롤 플레인 장애 조치 런북](../../runbooks/control-plane-failover-ko.md) |
| 단일 지역 배포와 release 롤백 | [배포](deployment-ko.md) |
| 예약된 워크로드 DR과 데이터베이스 복원 훈련 | [단계 3 integrated 루프](../phases/phase-3-integrated-loop-ko.md) |
| 런타임 시작 및 준비 상태 게이트 | [시작 and 수명 주기](../operations/startup-and-lifecycle-ko.md) |
| Operational 신호와 런북 요구사항 | [Operating and 검증](../operations/operating-and-verification-ko.md) |
| 운영 아키텍처 승인 근거 | [아키텍처 검토 Board packet](../architecture/architecture-review-board-ko.md) |
