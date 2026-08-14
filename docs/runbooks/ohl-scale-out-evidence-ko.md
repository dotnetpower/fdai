---
title: OHL Scale-Out 근거 Runbook
translation_of: ohl-scale-out-evidence.md
translation_source_sha: 886b5a1753cd0305f56e8f44060aa950187ed2d5
translation_revised: 2026-08-14
---
# OHL Scale-Out 근거 Runbook

이 runbook은 protected runner에서 `ops.scale-out`의 Operational Hypothesis Loop(OHL) Lane F
잔여 근거를 수집할 때 사용합니다. 전용 non-production VM Scale Set 하나를 실행하고 provider
실행 증적과 FDAI graph 예측 및 독립 결과 근거를 분리합니다.

> **권한 경계:** 이 runbook은 infrastructure를 프로비전하거나 배포하지 않습니다. 기존
> non-production VM Scale Set 하나를 최대 인스턴스 1개만큼 변경하고 exact 기준선으로
> 복원합니다. 이 runbook을 사용하기 전에 protected 배포 작업 흐름을 통해 선택적 대상을
> 프로비저닝하세요. 기존 승인, dry-run, audit intent, lock, automation hold 경로를 사용할 수
> 있을 때만 훈련을 실행하세요. 실행 경로는 pre-dispatch exact V2 plan의 kinetic safety receipt도
> 저장해야 하며 Heimdall 소유 adapter는 post-effect observation을 독립적으로 authenticate해야
> 합니다. Action에서 plan을 reconstruct하거나 executor 또는 provider receipt를 observed outcome으로
> 사용하지 마세요.
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
residual이 남은 상태에서 `prepared`를 `complete`로 바꾸지 못하게 합니다. Schema는 상태 형태를
검사합니다. 계약에 고정된 완료 검증기는 receipt bundle digest, sample 기준값, 경과 window,
정확도, policy escape, 관측 독립성 및 조건과 receipt 간 binding도 다시 계산합니다.

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

현재 repository는 immutable kinetic receipt store를 구현했지만 dispatch 전 writer를 아직 연결하지
않았고 verified independent effect-observation adapter도 제공하지 않습니다. 두 residual이 focused
runtime evidence로 제거되기 전까지 contract를 `prepared`로 유지하고 live mutation 단계를 시작하지
마세요. 항상 unavailable을 반환하는 deferred observer는 production binding이 아니며 이 gate를
충족할 수 없습니다.

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
export FDAI_OHL_CAMPAIGN_ID='<retry-stable-campaign-id>'
export FDAI_OHL_CORRELATION_ID='<operator-request-correlation-id>'
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
: "${FDAI_OHL_CAMPAIGN_ID:?}"
: "${FDAI_OHL_CORRELATION_ID:?}"
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

Baseline artifact는 runner session 사이에서도 authoritative campaign start입니다. 이후의 각 command
block은 shell variable 지속성에 의존하지 않고 해당 file에서 `drill_started_at`을 다시 읽습니다.

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
drill_started_at="$(jq -er '.started_at' .fdai/evidence/ohl-scale-out/baseline.json)"
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
drill_started_at="$(jq -er '.started_at' .fdai/evidence/ohl-scale-out/baseline.json)"
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
drill_started_at="$(jq -er '.started_at' .fdai/evidence/ohl-scale-out/baseline.json)"
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

## 완료 bundle 생성 및 검증

Receipt bundle은 계약의 `evidence.output_path`에 보관합니다. 이 JSON object 하나에는 campaign 및
correlation 식별자, exact target revision, campaign 시작 및 recurrence timestamp, 고유 type을 가진
receipt 21개, 완료 조건 12개의 receipt digest 및 모든 live-shadow sample이 포함됩니다. 각
receipt에는 `common_receipt_fields`의 모든 field가 들어갑니다. 각 sample에는 prediction 및 outcome
digest, event, horizon, grace가 완료된 관측 timestamp, 60초 observation window, completeness 및
censoring flag, prediction과 outcome, policy-escape 및 promotion flag, 서로 다른 observer와 executor
identity digest가 포함됩니다.
`graph_shadow_prediction` 및 `graph_shadow_outcome` receipt에는 각각 `graph_prediction_fields`와
`graph_outcome_fields`의 모든 field도 들어갑니다. Graph outcome receipt 하나가 독립 종결, horizon
보존 및 zero policy escape를 함께 충족할 수 있으며, 이때 각 조건은 해당 receipt의 동일한
`provenance_digest`를 참조합니다.

Receipt와 sample 값은 위에서 설명한 protected-runner source에서 가져와야 합니다. 검증기는
결정론적 일관성과 무결성을 검사합니다. 수동으로 작성하거나 synthetic인 JSON을 live evidence로
바꾸지 않습니다.

각 typed receipt를 `.fdai/evidence/ohl-scale-out/receipts/` 아래에 JSON object 하나로 저장합니다.
Filename은 operator label일 뿐입니다. `kind` field가 authoritative하며 `required_receipts`의 21개
값 중 하나여야 합니다. 모든 receipt는 다음과 같은 exact 공통 구조로 시작합니다.

```json
{
  "kind": "approval",
  "evidence_level": "live_execution",
  "authority_class": "human-approval",
  "source_identity_digest": "<64-lowercase-hex-characters>",
  "scope_digest": "<64-lowercase-hex-characters>",
  "purpose": "OHL scale-out completion",
  "query_version": "<collector-or-query-version>",
  "event_time": "<RFC-3339-UTC-timestamp>",
  "recorded_at": "<RFC-3339-UTC-timestamp>",
  "freshness_seconds": 0,
  "completeness": true,
  "provenance_digest": "<64-lowercase-hex-characters>",
  "synthetic": false,
  "correlation_id": "<operator-request-correlation-id>",
  "target_revision": "<40-character-git-revision>",
  "verified": true
}
```

`authority_class`에는 `human-approval`, `isolated-executor`, `independent-observer`처럼 receipt를
생성한 authority boundary를 기록합니다. `purpose`에는 bounded campaign 목적을 기록하고
`query_version`에는 immutable collector 또는 query version을 기록합니다. `freshness_seconds`는
`recorded_at - event_time`의 정확한 초로 설정합니다. Placeholder 값을 복사하지 마세요. Identity,
scope, provenance, correlation, revision 및 timestamp는 protected source에서 가져옵니다.

해당 graph receipt에는 `graph_prediction_fields` 또는 `graph_outcome_fields`의 field를 추가합니다.
모든 observation은 `.fdai/evidence/ohl-scale-out/samples.json`에 JSON array 하나로 저장합니다. 각
sample은 검증기가 적용하는 exact field를 포함하며, `executor_identity_digest`는
`provider_scale_out` receipt의 `source_identity_digest`와 같아야 합니다.

14일 recurrence window를 완료한 다음 bundle을 조립합니다. Builder는 누락되거나 예상 밖이거나
중복된 receipt kind를 차단하고 manifest에서 완료 조건 12개와 receipt digest의 binding을
생성합니다. 제공된 receipt 및 sample 값은 그대로 유지하며 live evidence로 검증하거나 승격하지
않습니다. 기존 evidence bundle을 덮어쓰지 않도록 output path는 한 번만 생성합니다.

```bash
receipts='.fdai/evidence/ohl-scale-out/receipts'
samples='.fdai/evidence/ohl-scale-out/samples.json'
bundle='.fdai/evidence/ohl-scale-out-live.json'
drill_started_at="$(jq -er '.started_at' .fdai/evidence/ohl-scale-out/baseline.json)"
recurrence_observed_at="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

python3 scripts/quality/repository/build-ohl-scale-out-evidence-bundle.py \
  config/ohl-scale-out-evidence.json \
  "$receipts" \
  "$samples" \
  "$bundle" \
  --campaign-id "$FDAI_OHL_CAMPAIGN_ID" \
  --correlation-id "$FDAI_OHL_CORRELATION_ID" \
  --target-revision "$FDAI_OHL_EXPECTED_REVISION" \
  --started-at "$drill_started_at" \
  --recurrence-observed-at "$recurrence_observed_at"
```

Exact bundle byte의 digest를 계산하고 tracked prepared 계약을 덮어쓰지 않은 상태로 candidate
manifest를 생성합니다.

```bash
candidate='.fdai/evidence/ohl-scale-out-complete.json'
source_receipt_digest="$(sha256sum "$bundle" | awk '{print $1}')"
completed_at="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

jq \
  --arg digest "$source_receipt_digest" \
  --arg completed_at "$completed_at" \
  '.status="complete" | .evidence_level="live_execution" | .result={status:"verified",source_receipt_digest:$digest,completed_at:$completed_at} | .residuals=[]' \
  config/ohl-scale-out-evidence.json > "$candidate"

python3 scripts/quality/repository/validate-ohl-scale-out-evidence.py \
  "$candidate" \
  "$bundle"
```

검증기는 schema drift, 누락 또는 중복 receipt, 잘못된 조건 binding, synthetic 또는 incomplete
관측, 100개 미만 sample, 14일 미만의 경과 기간 또는 UTC 날짜 수, `0.98` 미만의 정확도, 하나라도
있는 policy escape, 짧아진 horizon 또는 grace, 독립적이지 않은 관측, active-model 변경,
promotion, exact-byte digest 불일치를 차단합니다. `ohl-evidence: OK`를 출력한 뒤에만 tracked
manifest에 검증된 candidate를 반영할 수 있습니다.

## 현재 blocker

이 prepared 계약에는 residual 두 개가 남아 있습니다.

- Independent Core 및 Operator service root에 이 action을 park하고 resolve하는 데 필요한 사람 승인
  channel 및 callback signing secret binding이 아직 없습니다.
- protected-runner live drill을 아직 실행하지 않았습니다.

Production composition에는 graph Dynamic evidence provider가 연결되어 있으며, 개발 operations
게이트웨이는 `ops.scale-out`을 정확한 Uniform VM Scale Set 하나의 용량 증가로 매핑합니다.
Focused test는 두 연결을 검증하지만 이를 실제 운영 결과 증거로 취급하지 않습니다.

두 residual을 모두 닫기 전에는 frozen scenario manifest가 `partial`로 유지되고 생성된 artifact는
tracked live claim이 아닌 local evidence로 유지됩니다.

## 관련 문서

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| 고정된 계획 시나리오 | [운영 계획](../roadmap/decisioning/operational-planning-ko.md) |
| 통합 graph 근거 및 종결 | [Operational Hypothesis Loop](../roadmap/rules-and-detection/operational-hypothesis-loop-ko.md) |
| Active 및 challenger graph model | [Assurance Twin](../roadmap/operations/assurance-twin-ko.md) |
