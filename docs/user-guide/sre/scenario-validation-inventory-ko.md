---
title: SRE 시나리오 검증
description: FDAI가 사용하는 모든 SRE 시나리오 묶음과, 카탈로그 검증, 재생, 관찰 모드 적용 범위, 실제 변경 적용 검증이 어떻게 다른지 정리했습니다.
translation_of: scenario-validation-inventory.md
translation_source_sha: 6694b899dadbff5cd6acd9a37fc50b8d924f9681
translation_revised: 2026-08-11
---

# SRE 시나리오 검증

FDAI는 질문이 다르면 시나리오 묶음도 다르게 씁니다. 카탈로그 항목은 시나리오가 형식에 맞게
작성되었고 알려진 신호에 연결되어 있음을 증명합니다. 재생은 컨트롤 루프가 예상한 결과에
도달함을 증명합니다. 실제 적용 모드 실행은 일회용 Azure 환경에서 진짜 장애가 주입되고,
관찰되고, 원상 복구됐음을 증명합니다. 이 세 가지 근거 수준은 서로 바꿔 쓸 수 없습니다.

이 문서는 현재 SRE 시나리오 묶음과 카탈로그 시나리오 ID 135개를 모두 보여 줍니다. 이
집계는 2026-07-17에 저장소에서 다시 계산했습니다.

## 검증 수준

| 시나리오 집합 | 수 | 현재 증거 | 증명 범위 |
|--------------|---:|-----------|-----------|
| SRE demo 묶음 | 18 | 18/18 shadow 커버리지 | Detect, 경로, RCA, 통제된 응답, 검증 대응 존재 |
| 참조 live-enforce 일괄 점검 | 10 | 10/10 검증된, detected, reverted | 일회용 Azure 기반에서 실제 injector와 탐색 작동 |
| 고정된 control-loop 집합 `v2026.07` | 9 | 무결성 및 재생 테스트 66개 통과 | 변경, DR, FinOps 기대 결과가 shipped 루프에서 재생됨 |
| 에이전트 결정 시나리오 | 6 | 에이전트 시나리오 테스트 22개에 포함되어 통과 | Forseti가 예상 auto, 사람 승인, 거부, 판단 보류 반환 |
| 에이전트 파이프라인 시나리오 | 8 | 에이전트 시나리오 테스트 22개에 포함되어 통과 | Forseti, Thor, Var, Saga의 cross-agent 안전성 불변식 유지 |
| Chaos 카탈로그 | 135 | 135/135 스키마, 신호, symptom-index 검증 | 모든 카탈로그 기록이 구조적으로 유효하고 검색 가능 |
| Default-factory 전달 subset | 93 | 93/93 injector 및 탐색 쌍 예행 실행 빌드 | 전달 배선 존재. 실제 운영 fault 실행을 뜻하지 않음 |
| Promoted 카탈로그 | 0 | 승격된 항목 없음 | Collected 항목이 강제 적용 충족 여부를 상속하지 않음 |

> 이와 별도로 Command Deck 주장 모음 14건은 근거 없는 통과 0건, 잘못된 거절 0건으로 답변의
> 근거 확인을 검증합니다. 이는 대화 안전성 모음이지 SRE 운영 시나리오 묶음이 아니므로 이
> 문서의 시나리오 합계에는 넣지 않습니다.

## SRE 데모 묶음: 18개

| ID | 시나리오 | 유형 | 검증 |
|----|----------|------|------|
| S1 | AKS pod kill | Fault | Shadow 커버리지. `aks-pod-kill` 실제 운영 적용 모드 |
| S2 | AKS pod CPU stress | Fault | Shadow 커버리지. `aks-pod-cpu-spike` 실제 운영 적용 모드 |
| S3 | AKS pod 네트워크 지연 시간 | Fault | Shadow 커버리지. `network-rtt-delay` 실제 운영 적용 모드 |
| S4 | AKS HTTP abort | Fault | Shadow 커버리지. `aks-http-abort` 실제 운영 적용 모드 |
| S5 | VM CPU stress | Fault | Shadow 커버리지. `vm-cpu-stress` 실제 운영 적용 모드 |
| S6 | VM 기억 stress | Fault | Shadow 커버리지. `vm-mem-stress` 실제 운영 적용 모드 |
| S7 | VM 네트워크 지연 시간 | Fault | Shadow 커버리지. `network-rtt-delay` 실제 운영 적용 모드 |
| S8 | MySQL CPU-credit exhaustion | Fault | Shadow 커버리지. `mysql-cpu-pressure` 실제 운영 적용 모드 |
| S9 | TPM pressure에 따른 Azure OpenAI 429 | Fault | Shadow 커버리지. `aoai-tpm-throttle` 실제 운영 적용 모드 |
| S10 | 애플리케이션 게이트웨이 백엔드 first-byte 지연 시간 | Fault | Shadow 커버리지. `network-rtt-delay` 실제 운영 적용 모드 |
| S11 | 의존성 장애 cascade | Fault | Shadow 커버리지. `appgw-backend-failure` 실제 운영 적용 모드 |
| S12 | Bad 배포와 롤아웃 stall | Fault | Shadow 커버리지. `aks-bad-deploy` 실제 운영 적용 모드 |
| S13 | 지식 인제스트와 구성 표류 | Non-fault | Scheduled 거버넌스 및 assurance 경계 |
| S14 | Alert-driven automatic 조사 트리거 | Non-fault | 웹훅, 이벤트 ingest, IRP 경계 |
| C1 | Continuous-load 기준선 | 기준선 | Shadow calibration 커버리지 |
| C2 | Continuous 부하 중 pod kill | Fault | `aks-pod-kill` 재사용 |
| C3 | 부하 중 single-pod CPU hotspot | Fault | `aks-pod-cpu-spike` 재사용 |
| C4 | Single-pod 기억 hotspot과 OOM kill | Fault | `vm-mem-stress`를 pod 기억 stress로 재사용 |

## Azure 실제 적용 기준 점검: 10개

2026-07-13 기준 점검에서는 모든 행에 `outcome=validated`, `detected=true`,
`reverted=true`가 기록됐습니다.

| 시나리오 ID | 예상 신호 | 탐색 등급 |
|-------------|-----------------|-------------|
| `aks-pod-kill` | `pod_restart` | Kubernetes 이벤트 |
| `aks-pod-cpu-spike` | `node_cpu` | Chaos Mesh 상태 |
| `network-rtt-delay` | `gateway_latency` | Chaos Mesh 상태 |
| `aks-http-abort` | `request_failure` | Chaos Mesh 상태 |
| `vm-cpu-stress` | `host_cpu` | Azure Monitor 메트릭 |
| `vm-mem-stress` | `host_memory` | VM 게스트 명령 |
| `mysql-cpu-pressure` | `db_cpu` | Azure Monitor 메트릭 |
| `aoai-tpm-throttle` | `rate_limit` | HTTP 429 샘플 |
| `appgw-backend-failure` | `backend_health` | Kubernetes endpoints |
| `aks-bad-deploy` | `rollout_stall` | Kubernetes pod 상태 |

지연 시간 점검에서 이벤트와 상태 확인은 3.5초 안에 관찰됐고, VM 메모리 압박은 약 31초가
걸렸습니다. Azure Monitor의 CPU 측정은 이동 집계 구간을 조회하기 때문에 초기 측정 공백이
남아 있습니다. 첫 조회 값을 실제 초기 지연 시간으로 취급하지는 않습니다.

## 고정된 컨트롤 루프 묶음: 9개

| 시나리오 ID | 도메인 | 기대 계층 | 기대 결정 | 기대 액션 |
|-------------|--------|-----------|---------------|-------------|
| `change.drift-manual-portal-edit.003` | 변경 | T0 | 사람 승인 | 없음 |
| `change.nsg-allow-any-inbound.002` | 변경 | T0 | 사람 승인 | 없음 |
| `change.tag-owner-missing.001` | 변경 | T0 | auto | 있음. Shadow 전달 |
| `dr.backup-vault-restore-rehearsal.002` | DR | T0 | auto | 있음. Shadow 전달 |
| `dr.chaos-experiment-novel.003` | DR | T2 | 사람 승인 | 없음 |
| `dr.replica-lag-degraded.001` | DR | T1 | 사람 승인 | 없음 |
| `finops.right-size-vm-high-monthly.002` | FinOps | T0 | 사람 승인 | 없음 |
| `finops.stop-idle-dev-vm-off-hours.003` | FinOps | T1 | auto | 있음. Shadow 전달 |
| `finops.unattached-public-ip.001` | FinOps | T0 | auto | 있음. Shadow 전달 |

## 에이전트 판단과 파이프라인 시나리오

### Forseti 판단 매트릭스: 이름이 붙은 시나리오 6개

| 시나리오 | 기대 결과 |
|----------|-----------|
| `auto_rule_fired` | auto |
| `hil_rule_fired` | 사람 승인 |
| `deny_irreversible` | 거부와 정족수 2 |
| `hil_unknown_event_triage` | 구체적인 리소스가 있어 사람 승인 |
| `abstain_no_resource_target` | actionable 대상이 없어 판단 보류 |
| `rbac_denied_operator` | 거부 및 security 이벤트 생성 |

### 에이전트 간 파이프라인 매트릭스: 사례 8개

| 시나리오 사례 | 불변식 |
|---------------|--------|
| Shadow의 auto | 변경 없이 판단하고 감사함 |
| 사람 승인 요청 | Pending 승인 티켓 정확히 1개 |
| 거부 | Approval 또는 실행에 도달하지 않음 |
| Mixed 스트림 | 결정과 전달 개수가 같음 |
| 중복 전달 | 전달 1회, 중복 1회 측정, 이중 실행 없음 |
| 빈 또는 junk 이벤트 | 판단 보류하고 다운스트림 액션 없음 |
| 자기 승인 시도 | 차단되고 security 신호로 측정됨 |
| Repeated 자기 승인 | 재시도가 security 개수를 부풀리지 않음 |

## 카오스 카탈로그: 시나리오 ID 135개

현재 카탈로그에서 기본 팩토리가 실행 가능으로 분류하고 사전 검증 단계에서 만들어 내는
항목은 93개입니다. 나머지 42개는 AWS FIS 교차 클라우드 참고용 17개, 별도 주입기나 하드웨어가
필요한 GPU 시나리오 21개, Kubernetes 문서 기반 후보 3개, 예전 Redis 재부팅 시나리오
1개입니다. 135개 모두 `collected/`에 있고 `promoted/`에는 아직 하나도 없습니다.

<details>
<summary>Azure Chaos Studio - ID 15개</summary>

- `chaos.azure-chaos-studio.agent-cpu-pressure`
- `chaos.azure-chaos-studio.agent-network-disconnect`
- `chaos.azure-chaos-studio.agent-network-latency`
- `chaos.azure-chaos-studio.agent-network-packet-loss`
- `chaos.azure-chaos-studio.agent-physical-memory-pressure`
- `chaos.azure-chaos-studio.agent-stop-service`
- `chaos.azure-chaos-studio.cosmos-db-failover`
- `chaos.azure-chaos-studio.keyvault-deny-access`
- `chaos.azure-chaos-studio.load-balancer-backend-remove`
- `chaos.azure-chaos-studio.nsg-security-rule`
- `chaos.azure-chaos-studio.redis-reboot`
- `chaos.azure-chaos-studio.service-bus-firewall-block`
- `chaos.azure-chaos-studio.vm-redeploy`
- `chaos.azure-chaos-studio.vm-shutdown`
- `chaos.azure-chaos-studio.vmss-shutdown`

</details>

<details>
<summary>Chaos Mesh - ID 14개</summary>

- `chaos.chaos-mesh.block-delay`
- `chaos.chaos-mesh.container-kill`
- `chaos.chaos-mesh.dns-error`
- `chaos.chaos-mesh.http-delay`
- `chaos.chaos-mesh.http-replace`
- `chaos.chaos-mesh.io-fault`
- `chaos.chaos-mesh.kernel-panic`
- `chaos.chaos-mesh.network-bandwidth`
- `chaos.chaos-mesh.network-corrupt`
- `chaos.chaos-mesh.network-duplicate`
- `chaos.chaos-mesh.network-loss`
- `chaos.chaos-mesh.network-partition`
- `chaos.chaos-mesh.pod-failure`
- `chaos.chaos-mesh.stress-memory`

</details>

<details>
<summary>Litmus - ID 16개</summary>

- `chaos.litmus.container-kill`
- `chaos.litmus.disk-fill`
- `chaos.litmus.node-cpu-hog`
- `chaos.litmus.node-drain`
- `chaos.litmus.node-memory-hog`
- `chaos.litmus.pod-cpu-hog`
- `chaos.litmus.pod-delete`
- `chaos.litmus.pod-dns-error`
- `chaos.litmus.pod-http-latency`
- `chaos.litmus.pod-http-status-code`
- `chaos.litmus.pod-io-stress`
- `chaos.litmus.pod-memory-hog`
- `chaos.litmus.pod-network-corruption`
- `chaos.litmus.pod-network-duplication`
- `chaos.litmus.pod-network-latency`
- `chaos.litmus.pod-network-loss`

</details>

<details>
<summary>Kubernetes 문서 기반 - ID 3개</summary>

- `chaos.kubernetes-docs.dns-resolution-failure`
- `chaos.kubernetes-docs.image-pull-backoff`
- `chaos.kubernetes-docs.pod-disruption-budget-gap`

</details>

<details>
<summary>합성한 일반 시나리오 - ID 48개</summary>

- `chaos.general.db-saturate-db-cpu-extreme`
- `chaos.general.db-saturate-db-cpu-high`
- `chaos.general.db-saturate-db-cpu-mild`
- `chaos.general.disk-delay-host-cpu-extreme`
- `chaos.general.disk-delay-host-cpu-high`
- `chaos.general.disk-delay-host-cpu-mild`
- `chaos.general.dns-delay-gateway-latency-extreme`
- `chaos.general.dns-delay-gateway-latency-high`
- `chaos.general.dns-delay-gateway-latency-mild`
- `chaos.general.lb-deny-backend-health-extreme`
- `chaos.general.lb-deny-backend-health-high`
- `chaos.general.lb-deny-backend-health-mild`
- `chaos.general.llm_endpoint-throttle-rate-limit-extreme`
- `chaos.general.llm_endpoint-throttle-rate-limit-high`
- `chaos.general.llm_endpoint-throttle-rate-limit-mild`
- `chaos.general.pod-corrupt-rollout-stall-extreme`
- `chaos.general.pod-corrupt-rollout-stall-high`
- `chaos.general.pod-corrupt-rollout-stall-mild`
- `chaos.general.pod-delay-gateway-latency-extreme-v2`
- `chaos.general.pod-delay-gateway-latency-extreme`
- `chaos.general.pod-delay-gateway-latency-high-v2`
- `chaos.general.pod-delay-gateway-latency-high`
- `chaos.general.pod-delay-gateway-latency-mild-v2`
- `chaos.general.pod-delay-gateway-latency-mild`
- `chaos.general.pod-drop-request-failure-extreme-v2`
- `chaos.general.pod-drop-request-failure-extreme`
- `chaos.general.pod-drop-request-failure-high-v2`
- `chaos.general.pod-drop-request-failure-high`
- `chaos.general.pod-drop-request-failure-mild-v2`
- `chaos.general.pod-drop-request-failure-mild`
- `chaos.general.pod-saturate-node-cpu-extreme-v2`
- `chaos.general.pod-saturate-node-cpu-extreme`
- `chaos.general.pod-saturate-node-cpu-high-v2`
- `chaos.general.pod-saturate-node-cpu-high`
- `chaos.general.pod-saturate-node-cpu-mild-v2`
- `chaos.general.pod-saturate-node-cpu-mild`
- `chaos.general.pod-stop-pod-restart-extreme`
- `chaos.general.pod-stop-pod-restart-high`
- `chaos.general.pod-stop-pod-restart-mild`
- `chaos.general.vm-saturate-host-cpu-extreme-v2`
- `chaos.general.vm-saturate-host-cpu-extreme`
- `chaos.general.vm-saturate-host-cpu-high-v2`
- `chaos.general.vm-saturate-host-cpu-high`
- `chaos.general.vm-saturate-host-cpu-mild-v2`
- `chaos.general.vm-saturate-host-cpu-mild`
- `chaos.general.vm-saturate-host-memory-extreme`
- `chaos.general.vm-saturate-host-memory-high`
- `chaos.general.vm-saturate-host-memory-mild`

</details>

<details>
<summary>GPU 및 AI serving - ID 22개</summary>

- `chaos.gpu.gpu-delay-gpu-pcie-degradation`
- `chaos.gpu.gpu-ecc_error-gpu-ecc-uncorrectable-v2`
- `chaos.gpu.gpu-ecc_error-gpu-ecc-uncorrectable`
- `chaos.gpu.gpu-hang-gpu-util-zero-wasted`
- `chaos.gpu.gpu-oom-gpu-vram-oom-v2`
- `chaos.gpu.gpu-oom-gpu-vram-oom`
- `chaos.gpu.gpu-quota_shrink-gpu-idle-hours-wasted`
- `chaos.gpu.gpu-quota_shrink-gpu-sku-mismatch`
- `chaos.gpu.gpu-thermal_throttle-gpu-temp-throttle`
- `chaos.gpu.gpu-throttle-gpu-power-throttle`
- `chaos.gpu.gpu-xid_event-gpu-xid-event-v2`
- `chaos.gpu.gpu-xid_event-gpu-xid-event`
- `chaos.gpu.gpu_cluster-saturate-gpu-util-saturated`
- `chaos.gpu.inference_endpoint-cache_overflow-kv-cache-pressure`
- `chaos.gpu.inference_endpoint-delay-inference-p99-spike`
- `chaos.gpu.inference_endpoint-delay-weights-fetch-stall`
- `chaos.gpu.inference_endpoint-ramp-cold-start-latency-spike`
- `chaos.gpu.llm_endpoint-quota_shrink-token-spend-spike`
- `chaos.gpu.training_job-checkpoint_fail-spot-preempt-cascade`
- `chaos.gpu.training_job-delay-distributed-straggler`
- `chaos.gpu.training_job-hang-nccl-timeout`
- `chaos.gpu.training_job-preempt-spot-preempt-cascade`

</details>

<details>
<summary>AWS FIS cross-CSP 참조 - ID 17개</summary>

- `chaos.aws-fis.ec2-reboot-instances`
- `chaos.aws-fis.ec2-send-spot-instance-interruptions`
- `chaos.aws-fis.ec2-stop-instances`
- `chaos.aws-fis.ec2-terminate-instances`
- `chaos.aws-fis.ecs-stop-task`
- `chaos.aws-fis.eks-pod-cpu-stress`
- `chaos.aws-fis.eks-pod-network-latency`
- `chaos.aws-fis.network-disrupt-connectivity`
- `chaos.aws-fis.rds-failover-db-cluster`
- `chaos.aws-fis.rds-reboot-db-instances`
- `chaos.aws-fis.s3-bucket-pause-replication`
- `chaos.aws-fis.ssm-cpu-stress`
- `chaos.aws-fis.ssm-disk-fill`
- `chaos.aws-fis.ssm-kill-process`
- `chaos.aws-fis.ssm-memory-stress`
- `chaos.aws-fis.ssm-network-latency`
- `chaos.aws-fis.ssm-network-packet-loss`

</details>

## 인벤토리 해석 방법

- **카탈로그 검증 완료**는 스키마, 등록된 신호, 고유 ID, 증상 색인 검사를 통과했다는
  뜻입니다.
- **실행 가능**은 필요한 정보가 다 갖춰졌을 때 기본 팩토리가 주입기와 점검 쌍을 만들어 낼 수
  있다는 뜻입니다. 실제로 장애를 실행했다는 뜻은 아닙니다.
- **관찰 커버리지 확보**는 아무것도 바꾸지 않은 채로 감지, 라우팅, 근본 원인 분석, 대응,
  안전성 매핑이 모두 갖춰져 있다는 뜻입니다.
- **실제 적용 모드 검증 완료**는 일회용 환경에서 주입, 예상한 감지, 롤백까지 기록했다는
  뜻입니다.
- **승격됨**은 시나리오가 자체 승격 기준을 통과했다는 뜻입니다. 현재 카탈로그에 승격된
  항목은 하나도 없습니다.

## 다음 단계

| 알아볼 내용 | 문서 |
|-------------|------|
| 카탈로그 시나리오를 안전하게 실행하는 방법 | [카오스 엔지니어링](chaos-engineering-ko.md) |
| 발견된 문제와 예측을 검증하는 방법 | [관측성, 감지, 예측](observability-detection-and-forecasting-ko.md) |
| 성과 측정을 비교하는 방법 | [SRE 성과 측정](measuring-sre-outcomes-ko.md) |
| 내부 확장 설계 | [SRE 시나리오 라이브러리 확장](../../internals/sre-scenario-library-scaling.md) |
