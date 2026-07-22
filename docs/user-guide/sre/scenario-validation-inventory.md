---
title: SRE Scenario Validation
description: Every SRE scenario set FDAI uses, with separate evidence levels for catalog validation, replay, observation-mode coverage, and live enforcement validation.
---

# SRE Scenario Validation

FDAI uses several scenario sets for different questions. A catalog entry proves
that a scenario is well-formed and connected to a known signal. A replay proves
that the control loop reaches the expected result. A live enforcement run proves
that a real fault was injected, observed, and reverted on a disposable Azure
substrate. These evidence levels are not interchangeable.

This page lists every current SRE scenario set and every one of the 135 catalog
scenario IDs. The snapshot was recalculated from the repository on 2026-07-17.

## Validation levels

| Scenario set | Size | Current evidence | What it proves |
|--------------|-----:|------------------|----------------|
| SRE demo pack | 18 | 18/18 shadow coverage | Detect, route, RCA, governed response, and validation mapping exist |
| Reference live-enforce sweep | 10 | 10/10 validated, detected, and reverted | Real injectors and probes worked on the disposable Azure substrate |
| Frozen control-loop set `v2026.07` | 9 | 66 integrity and replay tests passed | Balanced Change, DR, and FinOps expected outcomes replay through the shipped loop |
| Agent decision scenarios | 6 | Included in 22 agent scenario tests passed | Forseti returns expected auto, human approval, deny, or hold for review outcomes |
| Agent pipeline scenarios | 8 | Included in 22 agent scenario tests passed | Forseti, Thor, Var, and Saga preserve cross-agent safety invariants |
| Chaos catalog | 135 | 135/135 schema, signal, and symptom-index validation | Every catalog record is structurally valid and searchable |
| Default-factory dispatch subset | 93 | 93/93 injector and probe pairs build in dry-run | Delivery wiring exists; this is not a live fault run |
| Promoted catalog | 0 | No entries promoted | No collected entry has inherited enforce eligibility |

> A separate 14-case Command Deck claim corpus validates answer evidence check with
> zero unsupported escapes and zero clean rejections. It is a conversational
> safety corpus, not an SRE operational scenario set, so it is not added to the
> scenario totals on this page.

## SRE demo pack: 18 scenarios

| ID | Scenario | Type | Validation |
|----|----------|------|------------|
| S1 | AKS pod kill | Fault | Shadow coverage; live enforcement via `aks-pod-kill` |
| S2 | AKS pod CPU stress | Fault | Shadow coverage; live enforcement via `aks-pod-cpu-spike` |
| S3 | AKS pod network latency | Fault | Shadow coverage; live enforcement via `network-rtt-delay` |
| S4 | AKS HTTP abort | Fault | Shadow coverage; live enforcement via `aks-http-abort` |
| S5 | VM CPU stress | Fault | Shadow coverage; live enforcement via `vm-cpu-stress` |
| S6 | VM memory stress | Fault | Shadow coverage; live enforcement via `vm-mem-stress` |
| S7 | VM network latency | Fault | Shadow coverage; live enforcement via `network-rtt-delay` |
| S8 | MySQL CPU-credit exhaustion | Fault | Shadow coverage; live enforcement via `mysql-cpu-pressure` |
| S9 | Azure OpenAI 429 from TPM pressure | Fault | Shadow coverage; live enforcement via `aoai-tpm-throttle` |
| S10 | Application Gateway backend first-byte latency | Fault | Shadow coverage; live enforcement via `network-rtt-delay` |
| S11 | Dependency outage cascade | Fault | Shadow coverage; live enforcement via `appgw-backend-failure` |
| S12 | Bad deployment and rollout stall | Fault | Shadow coverage; live enforcement via `aks-bad-deploy` |
| S13 | Knowledge ingestion and configuration drift | Non-fault | Scheduled governance and assurance seams |
| S14 | Alert-driven automatic investigation trigger | Non-fault | Webhook, event ingest, and IRP seams |
| C1 | Continuous-load baseline | Baseline | Shadow calibration coverage |
| C2 | Pod kill under continuous load | Fault | Reuses `aks-pod-kill` |
| C3 | One-pod CPU hotspot under load | Fault | Reuses `aks-pod-cpu-spike` |
| C4 | One-pod memory hotspot and OOM kill | Fault | Reuses `vm-mem-stress` as pod memory stress |

## Azure live-enforce reference sweep: 10 scenarios

The 2026-07-13 reference sweep recorded `outcome=validated`, `detected=true`,
and `reverted=true` for every row.

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

Event and status probes were observed in under 3.5 seconds in the latency
sweep, except VM memory pressure at about 31 seconds. The Azure Monitor CPU
measurements retain a documented cold-start measurement gap because the probe
queried a rolling aggregation window; do not treat their first-poll values as
true cold-start latency.

## Frozen control-loop set: 9 scenarios

| Scenario ID | Domain | Expected tier | Expected decision | Expected action |
|-------------|--------|---------------|-------------------|-----------------|
| `change.drift-manual-portal-edit.003` | Change | T0 | human approval | No |
| `change.nsg-allow-any-inbound.002` | Change | T0 | human approval | No |
| `change.tag-owner-missing.001` | Change | T0 | auto | Yes, shadow delivery |
| `dr.backup-vault-restore-rehearsal.002` | DR | T0 | auto | Yes, shadow delivery |
| `dr.chaos-experiment-novel.003` | DR | T2 | human approval | No |
| `dr.replica-lag-degraded.001` | DR | T1 | human approval | No |
| `finops.right-size-vm-high-monthly.002` | FinOps | T0 | human approval | No |
| `finops.stop-idle-dev-vm-off-hours.003` | FinOps | T1 | auto | Yes, shadow delivery |
| `finops.unattached-public-ip.001` | FinOps | T0 | auto | Yes, shadow delivery |

## Agent decision and pipeline scenarios

### Forseti decision matrix: 6 named scenarios

| Scenario | Expected result |
|----------|-----------------|
| `auto_rule_fired` | auto |
| `hil_rule_fired` | human approval |
| `deny_irreversible` | deny with quorum two |
| `hil_unknown_event_triage` | human approval because a concrete resource exists |
| `abstain_no_resource_target` | hold for review because no actionable target exists |
| `rbac_denied_operator` | deny and emit a security event |

### Cross-agent pipeline matrix: 8 scenario cases

| Scenario case | Invariant |
|---------------|-----------|
| Auto in shadow | Judged and audited without mutation |
| human approval request | Exactly one pending approval ticket |
| Deny | Never reaches approval or execution |
| Mixed stream | Decision and dispatch counts remain equal |
| Duplicate delivery | One dispatch, one measured duplicate, no double execution |
| Empty or junk event | Holds for review and causes no downstream action |
| Self-approval attempt | Blocked and measured as a security signal |
| Repeated self-approval | Retry does not inflate the security count |

## Chaos catalog: 135 scenario IDs

The catalog currently contains 93 entries that the default factory classifies
as executable and builds in dry-run. The remaining 42 are 17 AWS FIS
cross-CSP references, 21 GPU scenarios requiring an injector or hardware,
three Kubernetes documentation candidates, and the legacy Redis reboot
scenario. All 135 remain under `collected/`; zero are under `promoted/`.

<details>
<summary>Azure Chaos Studio - 15 IDs</summary>

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
<summary>Chaos Mesh - 14 IDs</summary>

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
<summary>Litmus - 16 IDs</summary>

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
<summary>Kubernetes documentation - 3 IDs</summary>

- `chaos.kubernetes-docs.dns-resolution-failure`
- `chaos.kubernetes-docs.image-pull-backoff`
- `chaos.kubernetes-docs.pod-disruption-budget-gap`

</details>

<details>
<summary>Synthesized general scenarios - 48 IDs</summary>

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
<summary>GPU and AI serving - 22 IDs</summary>

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
<summary>AWS FIS cross-CSP reference - 17 IDs</summary>

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

## How to interpret the inventory

- **Catalog validated** means schema, registered signal, unique ID, and symptom
  index checks pass.
- **Dispatchable** means the default factory can construct the injector and
  probe pair with a complete context. It does not mean a live fault ran.
- **Shadow covered** means the detection, routing, RCA, response, and safety
  mapping exists without mutation.
- **Live enforcement validated** means a disposable substrate recorded injection,
  expected detection, and rollback for that scenario.
- **Promoted** would mean the scenario passed its independent promotion gate.
  The current catalog has zero promoted entries.

## Next steps

| To learn about | Read |
|----------------|------|
| How a catalog scenario runs safely | [Chaos engineering](chaos-engineering.md) |
| How detected issues and forecasts are validated | [Observability, detection, and forecasting](observability-detection-and-forecasting.md) |
| How outcome measurements are compared | [Measuring SRE outcomes](measuring-sre-outcomes.md) |
| The internal scaling design | [Scaling the SRE Scenario Library](../../internals/sre-scenario-library-scaling.md) |
