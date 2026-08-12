---
title: OHL Scale-Out 근거 Runbook
translation_of: ohl-scale-out-evidence.md
translation_source_sha: ac61d8dbc2efff0da791ee6a2f70303b9a997d3e
translation_revised: 2026-08-13
---
# OHL Scale-Out 근거 Runbook

이 runbook은 protected runner에서 `ops.scale-out`의 Operational Hypothesis Loop(OHL) Lane F
잔여 근거를 수집할 때 사용합니다. 전용 non-production VM Scale Set 하나를 실행하고 provider
실행 증적과 FDAI graph 예측 및 독립 결과 근거를 분리합니다.

> **권한 경계:** 이 runbook은 infrastructure를 프로비전하거나 배포하지 않습니다. 기존
> non-production VM Scale Set 하나를 최대 인스턴스 1개만큼 변경하고 exact 기준선으로
> 복원합니다. 이 runbook을 사용하기 전에 protected 배포 작업 흐름을 통해 선택적 대상을
> 프로비저닝하세요. 기존 승인, dry-run, audit intent, lock, automation hold 경로를 사용할 수
> 있을 때만 훈련을 실행하세요.
>
> **근거 경계:** 아래의 direct Azure CLI 변경은 provider-side staging 근거입니다.
> `ops.scale-out` executor binding이 기존 typed receipt를 생성하기 전에는 FDAI end-to-end 실행
> 근거가 아닙니다. Synthetic evidence is not live evidence.

## 이 runbook의 범위

runbook은 관련 시나리오 두 개를 준비하고 검증합니다.

| 시나리오 | 필요한 결과 |
|----------|-------------|
| Non-production 부분 실행 및 복구 | `+1` scale 작업 하나가 수락되고 forward 작업이 중단되며 automation hold가 표시됩니다. 롤백은 exact 기준선을 복원하고 독립 read가 복구와 정리를 확인합니다. |
| Graph-wide live shadow 비교 | `ops.scale-out`에 대해 live non-synthetic graph 예측을 열고 고정 horizon 및 telemetry grace 동안 유지한 다음 active model 변경이나 promotion 적용 없이 독립 관측으로 닫습니다. |

Machine 계약은
[`config/ohl-scale-out-evidence.json`](../../config/ohl-scale-out-evidence.json)입니다. 이 schema는
residual이 남은 상태에서 `prepared`를 `complete`로 바꾸지 못하게 합니다.

## 대상 및 런타임 프로비저닝

훈련을 시작하기 전에 protected 작업 흐름을 사용하세요.

1. `container-supply-chain`으로 exact source revision을 빌드하고 증명합니다.
2. 증명된 source revision이 훈련 revision과 같은 이미지를 사용해 `service-deploy`에서
  `core-control-plane`과 `isolated-executor`를 각각 계획하고 적용합니다.
3. `deploy_dev_operations_gateway=true`와 `deploy_ohl_scale_out_evidence_target=true`를 사용해
  `deploy-dev`를 계획하고 적용합니다. Region에서 사용할 수 있는 exact Jammy Gen2 image
  version은 `OHL_SCALE_OUT_EVIDENCE_IMAGE_VERSION`으로, non-secret SSH public key는
  `OHL_SCALE_OUT_EVIDENCE_SSH_PUBLIC_KEY` repository variable로 공급합니다. Retry-stable
  `OHL_SCALE_OUT_EVIDENCE_CAMPAIGN_ID`와 human initiator object id인
  `OHL_SCALE_OUT_EVIDENCE_INITIATOR_PRINCIPAL_ID`도 공급합니다.
4. Exact protected 적용 출력에서 `ohl_scale_out_evidence_target_id`와
  `ohl_scale_out_evidence_target_name`을 읽습니다. Proposal-only manual Job 이름은
  `ohl_scale_out_evidence_proposal_job_name`에서 읽습니다. 추적되지 않거나 수동으로 생성한 VM
  Scale Set으로 대체하지 마세요.

대상은 기본적으로 비활성화됩니다. 활성화하면 Terraform은 애플리케이션 resource group의
비공개 전용 subnet에 용량 `1`인 Uniform `Standard_B1s` VM Scale Set 하나를 생성합니다. Public
IP와 autoscale 설정은 없습니다. Image version은 exact 값이며 변경 가능한 `latest`는 허용되지
않습니다. 기존 gateway reader 및 executor identity는 애플리케이션 resource group 범위를
유지하므로 배포에서 새로운 cross-resource-group 권한을 부여하지 않습니다.

Manual proposal Job은 ACR pull과 primary ingress Event Hub Data Sender 권한만 가진 별도 Managed
Identity를 사용합니다. State-store secret, Key Vault role, gateway role 또는 Azure provider
mutation 권한은 없습니다. Job을 시작하면 retry-stable `operator_request` 하나만 게시하며 target을
scale하지 않습니다.

## 필요한 runner 구성

protected runner의 secret 또는 환경 구성에서 값을 제공하세요. 해석된 값이나 생성된 evidence
directory를 커밋하지 마세요.

```bash
export FDAI_OHL_EXPECTED_SUBSCRIPTION_ID='<subscription-id>'
export FDAI_OHL_RESOURCE_GROUP='<resource-group>'
export FDAI_OHL_VMSS_NAME='<vm-scale-set-name>'
export FDAI_OHL_TARGET_RESOURCE_ID='<vm-scale-set-resource-id>'
export FDAI_OHL_NON_PRODUCTION_TAG_VALUE='<approved-fdai-env-tag-value>'
export FDAI_OHL_APPROVAL_REF='<approval-receipt-ref>'
export FDAI_OHL_DRY_RUN_REF='<dry-run-receipt-ref>'
export FDAI_OHL_STOP_CONDITION_REF='<stop-condition-receipt-ref>'
export FDAI_OHL_LOCK_REF='<logical-target-lock-receipt-ref>'
export FDAI_OHL_IDEMPOTENCY_KEY='<stable-idempotency-key>'
export FDAI_OHL_AUDIT_INTENT_REF='<audit-intent-receipt-ref>'
export FDAI_OHL_AUTOMATION_HOLD_REF='<automation-hold-receipt-ref>'
export FDAI_OHL_EXPECTED_REVISION='<40-character-git-revision>'
export FDAI_STATE_STORE_DSN='<protected-runner-state-store-dsn>'
export FDAI_OHL_PROPOSAL_JOB_NAME='<terraform-output-job-name>'
```

대상은 다음 제약을 모두 충족해야 합니다.

- resource type은 `Microsoft.Compute/virtualMachineScaleSets`입니다.
- orchestration mode는 `Uniform`입니다.
- `fdai:managed` tag는 `true`이고 `fdai:env` tag는 승인된 non-production 값과 같으며
  `fdai:component` tag는 `ohl-scale-out-evidence`입니다.
- drill 전용 대상이며 추가 인스턴스 1개를 위한 capacity가 있습니다.
- protected runner는 대상, Activity Log, FDAI state 및 audit store를 읽을 수 있고 gateway reader
  및 executor identity는 대상의 애플리케이션 resource group 범위에 남습니다.
- 변경 명령 전에 기존 `ops.scale-out` 승인, dry-run, audit, lock, rollback 및 hold receipt가
  이미 존재합니다.

## Preflight 및 기준선

repository root에서 다음 명령을 실행하세요. revision, account, target, type, tag 또는
orchestration이 일치하지 않으면 변경 전에 중단됩니다.

```bash
set -euo pipefail
umask 077

: "${FDAI_OHL_EXPECTED_SUBSCRIPTION_ID:?}"
: "${FDAI_OHL_RESOURCE_GROUP:?}"
: "${FDAI_OHL_VMSS_NAME:?}"
: "${FDAI_OHL_TARGET_RESOURCE_ID:?}"
: "${FDAI_OHL_NON_PRODUCTION_TAG_VALUE:?}"
: "${FDAI_OHL_APPROVAL_REF:?}"
: "${FDAI_OHL_DRY_RUN_REF:?}"
: "${FDAI_OHL_STOP_CONDITION_REF:?}"
: "${FDAI_OHL_LOCK_REF:?}"
: "${FDAI_OHL_IDEMPOTENCY_KEY:?}"
: "${FDAI_OHL_AUDIT_INTENT_REF:?}"
: "${FDAI_OHL_AUTOMATION_HOLD_REF:?}"
: "${FDAI_OHL_EXPECTED_REVISION:?}"
: "${FDAI_STATE_STORE_DSN:?}"
: "${FDAI_OHL_PROPOSAL_JOB_NAME:?}"

[[ "$(git rev-parse HEAD)" == "$FDAI_OHL_EXPECTED_REVISION" ]]
[[ "$(az account show --query id --output tsv)" == "$FDAI_OHL_EXPECTED_SUBSCRIPTION_ID" ]]

expected_target_id="/subscriptions/$FDAI_OHL_EXPECTED_SUBSCRIPTION_ID/resourceGroups/$FDAI_OHL_RESOURCE_GROUP/providers/Microsoft.Compute/virtualMachineScaleSets/$FDAI_OHL_VMSS_NAME"
[[ "${FDAI_OHL_TARGET_RESOURCE_ID,,}" == "${expected_target_id,,}" ]]

mkdir -p .fdai/evidence/ohl-scale-out
target_json="$(az resource show --ids "$FDAI_OHL_TARGET_RESOURCE_ID" --output json --only-show-errors)"
[[ "$(jq -r '.type' <<<"$target_json")" == 'Microsoft.Compute/virtualMachineScaleSets' ]]
[[ "$(jq -r '.tags["fdai:managed"] // empty' <<<"$target_json")" == 'true' ]]
[[ "$(jq -r '.tags["fdai:env"] // empty' <<<"$target_json")" == "$FDAI_OHL_NON_PRODUCTION_TAG_VALUE" ]]
[[ "$(jq -r '.tags["fdai:component"] // empty' <<<"$target_json")" == 'ohl-scale-out-evidence' ]]

vmss_json="$(az vmss show --subscription "$FDAI_OHL_EXPECTED_SUBSCRIPTION_ID" --resource-group "$FDAI_OHL_RESOURCE_GROUP" --name "$FDAI_OHL_VMSS_NAME" --output json --only-show-errors)"
[[ "$(jq -r '.orchestrationMode' <<<"$vmss_json")" == 'Uniform' ]]
baseline_capacity="$(jq -r '.sku.capacity' <<<"$vmss_json")"
[[ "$baseline_capacity" =~ ^[0-9]+$ ]]
baseline_instance_count="$(az vmss list-instances --subscription "$FDAI_OHL_EXPECTED_SUBSCRIPTION_ID" --resource-group "$FDAI_OHL_RESOURCE_GROUP" --name "$FDAI_OHL_VMSS_NAME" --query 'length(@)' --output tsv --only-show-errors)"
[[ "$baseline_instance_count" == "$baseline_capacity" ]]

drill_started_at="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
target_capacity="$((baseline_capacity + 1))"
jq -n \
  --arg revision "$FDAI_OHL_EXPECTED_REVISION" \
  --arg started_at "$drill_started_at" \
  --arg approval_ref "$FDAI_OHL_APPROVAL_REF" \
  --arg dry_run_ref "$FDAI_OHL_DRY_RUN_REF" \
  --arg stop_condition_ref "$FDAI_OHL_STOP_CONDITION_REF" \
  --arg lock_ref "$FDAI_OHL_LOCK_REF" \
  --arg idempotency_key "$FDAI_OHL_IDEMPOTENCY_KEY" \
  --arg audit_intent_ref "$FDAI_OHL_AUDIT_INTENT_REF" \
  --arg hold_ref "$FDAI_OHL_AUTOMATION_HOLD_REF" \
  --argjson baseline_capacity "$baseline_capacity" \
  --argjson baseline_instance_count "$baseline_instance_count" \
  --argjson target_capacity "$target_capacity" \
  '{revision:$revision,started_at:$started_at,approval_ref:$approval_ref,dry_run_ref:$dry_run_ref,stop_condition_ref:$stop_condition_ref,lock_ref:$lock_ref,idempotency_key:$idempotency_key,audit_intent_ref:$audit_intent_ref,automation_hold_ref:$hold_ref,baseline_capacity:$baseline_capacity,baseline_instance_count:$baseline_instance_count,target_capacity:$target_capacity}' \
  > .fdai/evidence/ohl-scale-out/baseline.json
```

## 통제된 shadow proposal

기준선 검사가 통과하면 protected runner에서 proposal-only Job을 시작합니다.

```bash
az containerapp job start \
  --subscription "$FDAI_OHL_EXPECTED_SUBSCRIPTION_ID" \
  --resource-group "$FDAI_OHL_RESOURCE_GROUP" \
  --name "$FDAI_OHL_PROPOSAL_JOB_NAME" \
  --only-show-errors
```

고정된 campaign id를 사용하므로 Job retry가 같은 operator-request idempotency key를 게시합니다.
이후 normal path는 Huginn ingest, ActionType argument validation, risk evaluation, 분리된 human
approval, isolated Executor dispatch, logical target lock, gateway plan 및 terminal audit을
실행합니다. Approver는 설정된 initiator와 다른 principal이어야 합니다.

`ops.scale-out`은 shadow로 유지합니다. 따라서 approval은 gateway dry-run 및 evidence path를
허용하지만 provider mutation은 허용하지 않습니다. 다음 단계로 진행하기 전에 일치하는 approval,
dry-run, stop-condition, target-lock, idempotency, audit, automation-hold, graph-prediction 및
graph-outcome reference를 기록합니다. Reference가 없거나 충돌하면 campaign을 중단합니다. 이
drill을 실행하려고 ActionType을 승격하지 마세요.

## 부분 실행 및 강제 복구

실제 변경은 capacity를 정확히 1개 늘립니다. 명령은 provider 완료를 기다리고 부분 상태를 기록한
다음 기준선을 복원합니다. 부분 상태 assertion이 통과한 뒤 다른 forward 작업을 진행하지 마세요.

```bash
rollback_required=1
restore_baseline() {
  if [[ "$rollback_required" == '1' ]]; then
    az vmss scale --ids "$FDAI_OHL_TARGET_RESOURCE_ID" --new-capacity "$baseline_capacity" --only-show-errors
    az vmss wait --ids "$FDAI_OHL_TARGET_RESOURCE_ID" --updated --interval 15 --timeout 300 --only-show-errors
  fi
}
trap restore_baseline EXIT INT TERM

az vmss scale --ids "$FDAI_OHL_TARGET_RESOURCE_ID" --new-capacity "$target_capacity" --only-show-errors
az vmss wait --ids "$FDAI_OHL_TARGET_RESOURCE_ID" --updated --interval 15 --timeout 300 --only-show-errors

partial_capacity="$(az vmss show --subscription "$FDAI_OHL_EXPECTED_SUBSCRIPTION_ID" --resource-group "$FDAI_OHL_RESOURCE_GROUP" --name "$FDAI_OHL_VMSS_NAME" --query 'sku.capacity' --output tsv --only-show-errors)"
partial_instance_count="$(az vmss list-instances --subscription "$FDAI_OHL_EXPECTED_SUBSCRIPTION_ID" --resource-group "$FDAI_OHL_RESOURCE_GROUP" --name "$FDAI_OHL_VMSS_NAME" --query 'length(@)' --output tsv --only-show-errors)"
[[ "$partial_capacity" == "$target_capacity" ]]
[[ "$partial_instance_count" == "$target_capacity" ]]

az monitor activity-log list --resource-id "$FDAI_OHL_TARGET_RESOURCE_ID" --start-time "$drill_started_at" --max-events 50 --output json --only-show-errors > .fdai/evidence/ohl-scale-out/activity-log.json

az vmss scale --ids "$FDAI_OHL_TARGET_RESOURCE_ID" --new-capacity "$baseline_capacity" --only-show-errors
az vmss wait --ids "$FDAI_OHL_TARGET_RESOURCE_ID" --updated --interval 15 --timeout 300 --only-show-errors

restored_capacity="$(az vmss show --subscription "$FDAI_OHL_EXPECTED_SUBSCRIPTION_ID" --resource-group "$FDAI_OHL_RESOURCE_GROUP" --name "$FDAI_OHL_VMSS_NAME" --query 'sku.capacity' --output tsv --only-show-errors)"
restored_instance_count="$(az vmss list-instances --subscription "$FDAI_OHL_EXPECTED_SUBSCRIPTION_ID" --resource-group "$FDAI_OHL_RESOURCE_GROUP" --name "$FDAI_OHL_VMSS_NAME" --query 'length(@)' --output tsv --only-show-errors)"
[[ "$restored_capacity" == "$baseline_capacity" ]]
[[ "$restored_instance_count" == "$baseline_instance_count" ]]
rollback_required=0
trap - EXIT INT TERM
```

Provider timeout, target 불일치, count 불일치, 누락된 hold 또는 rollback 명령 오류는
`recovery_incomplete`로 처리하세요. Automation hold를 유지하고 모든 forward dispatch를 중단한
다음 별도 승인된 Vidar 복구로 대상을 전달하세요. 사람 검토로 불완전한 복구를 다시 분류할 수
없습니다.

## Graph 예측 및 결과 근거

FDAI binding은 일반 shadow event 경로를 통해 episode를 만들어야 합니다. `state_kv` 또는
`audit_log` row를 직접 삽입하거나 편집하지 마세요. Event가 처리된 뒤 immutable prediction 및
audit record를 수집합니다.

```bash
psql "$FDAI_STATE_STORE_DSN" -v ON_ERROR_STOP=1 --csv --command "SELECT key, value FROM state_kv WHERE key LIKE 'dynamic-trajectory-episode:%' AND EXISTS (SELECT 1 FROM jsonb_array_elements_text(value->'predicted'->'intervention_refs') AS ref WHERE ref LIKE '%:ops.scale-out') ORDER BY updated_at DESC LIMIT 100" > .fdai/evidence/ohl-scale-out/graph-episodes.csv
psql "$FDAI_STATE_STORE_DSN" -v ON_ERROR_STOP=1 --csv --command "SELECT seq, action_kind, mode, entry FROM audit_log WHERE action_kind IN ('dynamic.trajectory_episode.opened','dynamic.trajectory_outcome.closed','dynamic.trajectory_outcome.rejected','dynamic.graph_closure.processed','dynamic.graph_closure.run') AND created_at >= '$drill_started_at'::timestamptz ORDER BY seq" > .fdai/evidence/ohl-scale-out/graph-audit.csv
```

Graph outcome collector는 고정된 300초 prediction horizon과 300초 telemetry grace가 지난 후에만
시작합니다. 각 metric query는 60초 observation window를 유지합니다. 누락, synthetic, conflict,
censored, truncated 또는 incomplete 관측은 episode를 open 또는 unscorable로 유지하며 live
success가 되지 않습니다.

## Recurrence 및 cleanup 검증

14일 recurrence window가 끝날 때 protected runner에서 다음 read-only 검사를 반복하세요. Fake
clock으로 window를 줄이지 마세요. Fake clock은 automated contract test에만 사용합니다.

```bash
az vmss show --subscription "$FDAI_OHL_EXPECTED_SUBSCRIPTION_ID" --resource-group "$FDAI_OHL_RESOURCE_GROUP" --name "$FDAI_OHL_VMSS_NAME" --query '{capacity:sku.capacity,provisioningState:provisioningState}' --output json --only-show-errors > .fdai/evidence/ohl-scale-out/recurrence-vmss.json
az vmss list-instances --subscription "$FDAI_OHL_EXPECTED_SUBSCRIPTION_ID" --resource-group "$FDAI_OHL_RESOURCE_GROUP" --name "$FDAI_OHL_VMSS_NAME" --query 'length(@)' --output tsv --only-show-errors > .fdai/evidence/ohl-scale-out/recurrence-instance-count.txt
az monitor activity-log list --resource-id "$FDAI_OHL_TARGET_RESOURCE_ID" --start-time "$drill_started_at" --max-events 50 --output json --only-show-errors > .fdai/evidence/ohl-scale-out/recurrence-activity-log.json
```

Capacity와 instance count가 기준선과 계속 같고, pending 또는 failed scale 작업이 없고,
예상하지 못한 종속 리소스가 없고, owning Process가 automation hold를 해제하고, recurrence
window에 같은 causal fingerprint가 없을 때만 cleanup이 검증됩니다.

## 완료 기준

config의 `manifest_complete_requires` 배열에 있는 모든 조건에 독립 receipt가 있을 때만 scenario
manifest를 `complete`로 변경하세요. 특히 다음 조건을 확인합니다.

- A0 및 irreversible ActionType 계약이 A3-E non-applicability를 증명합니다.
- Provider 부분 실행, FDAI 승인/audit/hold, rollback, 독립 복구 및 cleanup receipt가 같은 target
  revision과 correlation을 참조합니다.
- Graph prediction과 outcome은 live, non-synthetic, complete, horizon-correct 상태이며 독립적으로
  관측됩니다.
- 최소 100개의 live-shadow sample이 최소 14일에 걸쳐 있고 정확도는 `0.98` 이상이며 14일
  recurrence window가 완료되고 policy escape는 0입니다.
- Active graph model은 변경되지 않고 promotion이 적용되지 않으며 rollback model이 고정됩니다.
- Production graph evidence 및 `ops.scale-out` executor binding이 존재하고 focused test를
  통과합니다.
- Sanitized source receipt digest가 기록되고 `result.status`가 `verified`이며 residual이 없습니다.

## 현재 blocker

이 prepared 계약에는 residual 하나가 남아 있습니다.

- protected-runner live drill을 아직 실행하지 않았습니다.

Production composition에는 graph Dynamic evidence provider가 연결되어 있으며, 개발 operations
게이트웨이는 `ops.scale-out`을 정확한 Uniform VM Scale Set 하나의 용량 증가로 매핑합니다.
Focused test는 두 연결을 검증하지만 이를 실제 운영 결과 증거로 취급하지 않습니다.

실제 운영 residual을 닫기 전에는 frozen scenario manifest가 `partial`로 유지되고 생성된 artifact는
tracked live claim이 아닌 local evidence로 유지됩니다.

## 관련 문서

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| 고정된 계획 시나리오 | [운영 계획](../roadmap/decisioning/operational-planning-ko.md) |
| 통합 graph 근거 및 종결 | [Operational Hypothesis Loop](../roadmap/rules-and-detection/operational-hypothesis-loop-ko.md) |
| Active 및 challenger graph model | [Assurance Twin](../roadmap/operations/assurance-twin-ko.md) |
