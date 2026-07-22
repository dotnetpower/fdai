---
title: SRE 시나리오 검증
description: FDAI가 사용하는 모든 SRE 시나리오 세트와 카탈로그 검증, 재생, 관찰 모드 적용 범위, 실제 변경 적용 검증의 구분입니다.
translation_of: scenario-validation-inventory.md
translation_source_sha: 6694b899dadbff5cd6acd9a37fc50b8d924f9681
translation_revised: 2026-07-22
---

# SRE 시나리오 검증

FDAI는 서로 다른 질문에 여러 scenario set을 사용합니다. Catalog entry는 scenario가
well-formed 상태이고 알려진 signal에 연결됐음을 증명합니다. Replay는 control loop가 예상
결과에 도달함을 증명합니다. Live 적용 모드 run은 일회용 Azure substrate에서 실제 fault가
주입되고 관찰되고 원복됐음을 증명합니다. 이 evidence level은 서로 바꿔 쓸 수 없습니다.

이 페이지는 현재 SRE scenario set과 catalog scenario ID 135개를 모두 보여 줍니다.
Snapshot은 2026-07-17에 repository에서 다시 계산했습니다.

## 검증 수준

| Scenario set | 수 | 현재 증거 | 증명 범위 |
|--------------|---:|-----------|-----------|
| SRE demo pack | 18 | 18/18 shadow coverage | Detect, route, RCA, governed response, validation mapping 존재 |
| Reference live-enforce sweep | 10 | 10/10 validated, detected, reverted | 일회용 Azure substrate에서 실제 injector와 probe 작동 |
| Frozen control-loop set `v2026.07` | 9 | Integrity 및 replay test 66개 통과 | Change, DR, FinOps 기대 결과가 shipped loop에서 replay됨 |
| Agent decision scenario | 6 | Agent scenario test 22개에 포함되어 통과 | Forseti가 예상 auto, 사람 승인, deny, 판단 보류 반환 |
| Agent pipeline scenario | 8 | Agent scenario test 22개에 포함되어 통과 | Forseti, Thor, Var, Saga의 cross-agent safety invariant 유지 |
| Chaos catalog | 135 | 135/135 schema, signal, symptom-index validation | 모든 catalog record가 구조적으로 유효하고 검색 가능 |
| Default-factory dispatch subset | 93 | 93/93 injector 및 probe pair dry-run build | Delivery wiring 존재. Live fault run을 뜻하지 않음 |
| Promoted catalog | 0 | 승격된 entry 없음 | Collected entry가 enforce eligibility를 상속하지 않음 |

> 별도의 Command Deck claim corpus 14개는 unsupported escape 0건과 clean rejection 0건으로
> answer 근거 확인을 검증합니다. Conversational safety corpus이며 SRE 운영 scenario set이
> 아니므로 이 페이지의 scenario 합계에는 더하지 않습니다.

## SRE demo pack: 18개

| ID | Scenario | 유형 | 검증 |
|----|----------|------|------|
| S1 | AKS pod kill | Fault | Shadow coverage. `aks-pod-kill` live 적용 모드 |
| S2 | AKS pod CPU stress | Fault | Shadow coverage. `aks-pod-cpu-spike` live 적용 모드 |
| S3 | AKS pod network latency | Fault | Shadow coverage. `network-rtt-delay` live 적용 모드 |
| S4 | AKS HTTP abort | Fault | Shadow coverage. `aks-http-abort` live 적용 모드 |
| S5 | VM CPU stress | Fault | Shadow coverage. `vm-cpu-stress` live 적용 모드 |
| S6 | VM memory stress | Fault | Shadow coverage. `vm-mem-stress` live 적용 모드 |
| S7 | VM network latency | Fault | Shadow coverage. `network-rtt-delay` live 적용 모드 |
| S8 | MySQL CPU-credit exhaustion | Fault | Shadow coverage. `mysql-cpu-pressure` live 적용 모드 |
| S9 | TPM pressure에 따른 Azure OpenAI 429 | Fault | Shadow coverage. `aoai-tpm-throttle` live 적용 모드 |
| S10 | Application Gateway backend first-byte latency | Fault | Shadow coverage. `network-rtt-delay` live 적용 모드 |
| S11 | Dependency outage cascade | Fault | Shadow coverage. `appgw-backend-failure` live 적용 모드 |
| S12 | Bad deployment와 rollout stall | Fault | Shadow coverage. `aks-bad-deploy` live 적용 모드 |
| S13 | Knowledge ingestion과 configuration drift | Non-fault | Scheduled governance 및 assurance seam |
| S14 | Alert-driven automatic investigation trigger | Non-fault | Webhook, event ingest, IRP seam |
| C1 | Continuous-load baseline | Baseline | Shadow calibration coverage |
| C2 | Continuous load 중 pod kill | Fault | `aks-pod-kill` 재사용 |
| C3 | Load 중 single-pod CPU hotspot | Fault | `aks-pod-cpu-spike` 재사용 |
| C4 | Single-pod memory hotspot과 OOM kill | Fault | `vm-mem-stress`를 pod memory stress로 재사용 |

## Azure live-enforce reference sweep: 10개

2026-07-13 reference sweep은 모든 행에 `outcome=validated`, `detected=true`,
`reverted=true`를 기록했습니다.

| Scenario ID | Expected signal | Probe class |
|-------------|-----------------|-------------|
| `aks-pod-kill` | `pod_restart` | Kubernetes event |
| `aks-pod-cpu-spike` | `node_cpu` | Chaos Mesh status |
| `network-rtt-delay` | `gateway_latency` | Chaos Mesh status |
| `aks-http-abort` | `request_failure` | Chaos Mesh status |
| `vm-cpu-stress` | `host_cpu` | Azure Monitor metric |
| `vm-mem-stress` | `host_memory` | VM guest command |
| `mysql-cpu-pressure` | `db_cpu` | Azure Monitor metric |
| `aoai-tpm-throttle` | `rate_limit` | HTTP 429 sample |
| `appgw-backend-failure` | `backend_health` | Kubernetes endpoints |
| `aks-bad-deploy` | `rollout_stall` | Kubernetes pod status |

Latency sweep에서 event 및 status probe는 3.5초 안에 관찰됐고 VM memory pressure는 약
31초였습니다. Azure Monitor CPU 측정은 rolling aggregation window를 조회했기 때문에
cold-start measurement gap이 남아 있습니다. First-poll 값을 실제 cold-start latency로
취급하지 않습니다.

## Frozen control-loop set: 9개

| Scenario ID | Domain | 기대 tier | 기대 decision | 기대 action |
|-------------|--------|-----------|---------------|-------------|
| `change.drift-manual-portal-edit.003` | Change | T0 | 사람 승인 | 없음 |
| `change.nsg-allow-any-inbound.002` | Change | T0 | 사람 승인 | 없음 |
| `change.tag-owner-missing.001` | Change | T0 | auto | 있음. Shadow delivery |
| `dr.backup-vault-restore-rehearsal.002` | DR | T0 | auto | 있음. Shadow delivery |
| `dr.chaos-experiment-novel.003` | DR | T2 | 사람 승인 | 없음 |
| `dr.replica-lag-degraded.001` | DR | T1 | 사람 승인 | 없음 |
| `finops.right-size-vm-high-monthly.002` | FinOps | T0 | 사람 승인 | 없음 |
| `finops.stop-idle-dev-vm-off-hours.003` | FinOps | T1 | auto | 있음. Shadow delivery |
| `finops.unattached-public-ip.001` | FinOps | T0 | auto | 있음. Shadow delivery |

## Agent decision 및 pipeline scenario

### Forseti decision matrix: named scenario 6개

| Scenario | 기대 결과 |
|----------|-----------|
| `auto_rule_fired` | auto |
| `hil_rule_fired` | 사람 승인 |
| `deny_irreversible` | deny와 quorum 2 |
| `hil_unknown_event_triage` | 구체적인 resource가 있어 사람 승인 |
| `abstain_no_resource_target` | actionable target이 없어 판단 보류 |
| `rbac_denied_operator` | deny 및 security event 생성 |

### Cross-agent pipeline matrix: scenario case 8개

| Scenario case | 불변식 |
|---------------|--------|
| Shadow의 auto | 변경 없이 판단하고 감사함 |
| 사람 승인 request | Pending approval ticket 정확히 1개 |
| Deny | Approval 또는 execution에 도달하지 않음 |
| Mixed stream | 결정과 dispatch count가 같음 |
| Duplicate delivery | Dispatch 1회, duplicate 1회 측정, 이중 실행 없음 |
| Empty 또는 junk event | 판단 보류하고 downstream action 없음 |
| Self-approval attempt | 차단되고 security signal로 측정됨 |
| Repeated self-approval | Retry가 security count를 부풀리지 않음 |

## Chaos catalog: scenario ID 135개

현재 catalog에서 default factory가 executable로 분류하고 dry-run에서 build하는 entry는
93개입니다. 나머지 42개는 AWS FIS cross-CSP reference 17개, injector 또는 hardware가
필요한 GPU scenario 21개, Kubernetes documentation candidate 3개, legacy Redis reboot
scenario 1개입니다. 135개 모두 `collected/`에 있으며 `promoted/`에는 0개가 있습니다.

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
<summary>Kubernetes documentation - ID 3개</summary>

- `chaos.kubernetes-docs.dns-resolution-failure`
- `chaos.kubernetes-docs.image-pull-backoff`
- `chaos.kubernetes-docs.pod-disruption-budget-gap`

</details>

<details>
<summary>Synthesized general scenario - ID 48개</summary>

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
<summary>AWS FIS cross-CSP reference - ID 17개</summary>

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

- **Catalog validated**는 schema, registered signal, unique ID, symptom index 검사를
  통과했다는 뜻입니다.
- **Dispatchable**은 complete context에서 default factory가 injector 및 probe pair를
  구성할 수 있다는 뜻입니다. Live fault 실행을 뜻하지 않습니다.
- **Shadow covered**는 변경 없이 detection, routing, RCA, response, safety mapping이
  존재한다는 뜻입니다.
- **Live 적용 모드 validated**는 일회용 substrate에서 injection, expected detection,
  rollback을 기록했다는 뜻입니다.
- **Promoted**는 scenario가 독립 promotion gate를 통과했다는 뜻입니다. 현재 catalog의
  promoted entry는 0개입니다.

## 다음 단계

| 학습 대상 | 문서 |
|-----------|------|
| Catalog scenario를 안전하게 실행하는 방법 | [카오스 엔지니어링](chaos-engineering-ko.md) |
| 발견된 문제와 forecast를 검증하는 방법 | [관측성, 감지, 예측](observability-detection-and-forecasting-ko.md) |
| Outcome measurement를 비교하는 방법 | [SRE 성과 측정](measuring-sre-outcomes-ko.md) |
| 내부 scaling design | [SRE Scenario Library 확장](../../internals/sre-scenario-library-scaling.md) |
