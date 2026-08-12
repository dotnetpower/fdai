---
title: OHL Scale-Out Evidence Runbook
---
# OHL Scale-Out Evidence Runbook

Use this runbook on a protected runner to collect the remaining Operational Hypothesis Loop (OHL)
Lane F evidence for `ops.scale-out`. It exercises one dedicated non-production VM Scale Set and
keeps provider execution receipts separate from FDAI graph prediction and independent outcome
evidence.

> **Authority boundary:** This runbook doesn't provision or deploy infrastructure. It changes one
> pre-existing non-production VM Scale Set by at most one instance and restores the exact baseline.
> Run it only after the ordinary approval, dry-run, audit-intent, lock, and automation-hold paths
> are available.
>
> **Evidence boundary:** The direct Azure CLI mutation below is provider-side staging evidence. It
> isn't FDAI end-to-end execution evidence until the `ops.scale-out` executor binding emits the
> ordinary typed receipts. Synthetic evidence is not live evidence.

## What this runbook covers

The run prepares and verifies two related scenarios:

| Scenario | Required result |
|----------|-----------------|
| Non-production partial execution and recovery | One `+1` scale operation is accepted, forward work stops, the automation hold is visible, rollback restores the exact baseline, and an independent read verifies recovery and cleanup. |
| Graph-wide live shadow comparison | A live, non-synthetic graph prediction opens for `ops.scale-out`, remains open through the fixed horizon and telemetry grace, and closes from independent observations without changing the active model or applying promotion. |

The machine contract is
[`config/ohl-scale-out-evidence.json`](../../config/ohl-scale-out-evidence.json). Its schema prevents
a transition from `prepared` to `complete` while any residual remains.

## Required runner configuration

Supply values through the protected runner's secret or environment configuration. Don't commit
their resolved values or the generated evidence directory.

```bash
export FDAI_OHL_EXPECTED_SUBSCRIPTION_ID='<subscription-id>'
export FDAI_OHL_RESOURCE_GROUP='<resource-group>'
export FDAI_OHL_VMSS_NAME='<vm-scale-set-name>'
export FDAI_OHL_TARGET_RESOURCE_ID='<vm-scale-set-resource-id>'
export FDAI_OHL_NON_PRODUCTION_TAG_VALUE='<approved-non-production-tag-value>'
export FDAI_OHL_APPROVAL_REF='<approval-receipt-ref>'
export FDAI_OHL_DRY_RUN_REF='<dry-run-receipt-ref>'
export FDAI_OHL_STOP_CONDITION_REF='<stop-condition-receipt-ref>'
export FDAI_OHL_LOCK_REF='<logical-target-lock-receipt-ref>'
export FDAI_OHL_IDEMPOTENCY_KEY='<stable-idempotency-key>'
export FDAI_OHL_AUDIT_INTENT_REF='<audit-intent-receipt-ref>'
export FDAI_OHL_AUTOMATION_HOLD_REF='<automation-hold-receipt-ref>'
export FDAI_OHL_EXPECTED_REVISION='<40-character-git-revision>'
export FDAI_STATE_STORE_DSN='<protected-runner-state-store-dsn>'
```

The target should meet all of these constraints:

- its resource type is `Microsoft.Compute/virtualMachineScaleSets`;
- its orchestration mode is `Uniform`;
- its `environment` tag equals the runner-owned non-production value;
- it is dedicated to this drill and has capacity for one additional instance;
- the runner identity can read the target and Activity Log, scale only this target, and read the
  FDAI state and audit stores;
- the ordinary `ops.scale-out` approval, dry-run, audit, lock, rollback, and hold receipts already
  exist before the mutation command runs.

## Preflight and baseline

Run these commands from the repository root. They stop before mutation on a revision, account,
target, type, tag, or orchestration mismatch.

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

[[ "$(git rev-parse HEAD)" == "$FDAI_OHL_EXPECTED_REVISION" ]]
[[ "$(az account show --query id --output tsv)" == "$FDAI_OHL_EXPECTED_SUBSCRIPTION_ID" ]]

expected_target_id="/subscriptions/$FDAI_OHL_EXPECTED_SUBSCRIPTION_ID/resourceGroups/$FDAI_OHL_RESOURCE_GROUP/providers/Microsoft.Compute/virtualMachineScaleSets/$FDAI_OHL_VMSS_NAME"
[[ "${FDAI_OHL_TARGET_RESOURCE_ID,,}" == "${expected_target_id,,}" ]]

mkdir -p .fdai/evidence/ohl-scale-out
target_json="$(az resource show --ids "$FDAI_OHL_TARGET_RESOURCE_ID" --output json --only-show-errors)"
[[ "$(jq -r '.type' <<<"$target_json")" == 'Microsoft.Compute/virtualMachineScaleSets' ]]
[[ "$(jq -r '.tags.environment // empty' <<<"$target_json")" == "$FDAI_OHL_NON_PRODUCTION_TAG_VALUE" ]]

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

## Partial execution and forced recovery

The live mutation is exactly one capacity increment. The command waits for provider completion,
records the partial state, and then restores the baseline. Don't continue with another forward
operation after the partial-state assertions pass.

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

Treat a provider timeout, target mismatch, count mismatch, missing hold, or rollback command error as
`recovery_incomplete`. Keep the automation hold active, stop all forward dispatch, and route the
target to separately approved Vidar recovery. Human review cannot relabel an incomplete recovery.

## Graph prediction and outcome evidence

The FDAI bindings must create the episode through the normal shadow event path. Don't insert or
edit `state_kv` or `audit_log` rows by hand. After the event is processed, collect the immutable
prediction and audit records:

```bash
psql "$FDAI_STATE_STORE_DSN" -v ON_ERROR_STOP=1 --csv --command "SELECT key, value FROM state_kv WHERE key LIKE 'dynamic-trajectory-episode:%' AND EXISTS (SELECT 1 FROM jsonb_array_elements_text(value->'predicted'->'intervention_refs') AS ref WHERE ref LIKE '%:ops.scale-out') ORDER BY updated_at DESC LIMIT 100" > .fdai/evidence/ohl-scale-out/graph-episodes.csv
psql "$FDAI_STATE_STORE_DSN" -v ON_ERROR_STOP=1 --csv --command "SELECT seq, action_kind, mode, entry FROM audit_log WHERE action_kind IN ('dynamic.trajectory_episode.opened','dynamic.trajectory_outcome.closed','dynamic.trajectory_outcome.rejected','dynamic.graph_closure.processed','dynamic.graph_closure.run') AND created_at >= '$drill_started_at'::timestamptz ORDER BY seq" > .fdai/evidence/ohl-scale-out/graph-audit.csv
```

The graph outcome collector starts only after the fixed 300-second prediction horizon plus the
300-second telemetry grace. Each metric query retains its 60-second observation window. Missing,
synthetic, conflicting, censored, truncated, or incomplete observations keep the episode open or
unscorable; they don't become live success.

## Recurrence and cleanup verification

Repeat the following read-only checks from the protected runner at the end of the 14-day recurrence
window. Don't shorten the window with a fake clock. Fake clocks are only for automated contract
tests.

```bash
az vmss show --subscription "$FDAI_OHL_EXPECTED_SUBSCRIPTION_ID" --resource-group "$FDAI_OHL_RESOURCE_GROUP" --name "$FDAI_OHL_VMSS_NAME" --query '{capacity:sku.capacity,provisioningState:provisioningState}' --output json --only-show-errors > .fdai/evidence/ohl-scale-out/recurrence-vmss.json
az vmss list-instances --subscription "$FDAI_OHL_EXPECTED_SUBSCRIPTION_ID" --resource-group "$FDAI_OHL_RESOURCE_GROUP" --name "$FDAI_OHL_VMSS_NAME" --query 'length(@)' --output tsv --only-show-errors > .fdai/evidence/ohl-scale-out/recurrence-instance-count.txt
az monitor activity-log list --resource-id "$FDAI_OHL_TARGET_RESOURCE_ID" --start-time "$drill_started_at" --max-events 50 --output json --only-show-errors > .fdai/evidence/ohl-scale-out/recurrence-activity-log.json
```

Cleanup is verified only when capacity and instance count still equal the baseline, no pending or
failed scale operation remains, no unexpected dependent resource exists, the automation hold is
released by its owning Process, and the recurrence window contains no matching causal fingerprint.

## Completion criteria

Change the scenario manifest to `complete` only when all conditions in the config's
`manifest_complete_requires` array have independent receipts. In particular:

- the A0 and irreversible ActionType contract proves A3-E non-applicability;
- provider partial execution, FDAI approval/audit/hold, rollback, independent recovery, and cleanup
  receipts refer to the same target revision and correlation;
- graph prediction and outcome are live, non-synthetic, complete, horizon-correct, and independently
  observed;
- at least 100 live-shadow samples span at least 14 distinct days, accuracy is at least `0.98`, the
  14-day recurrence window is complete, and policy escapes equal zero;
- the active graph model is unchanged, no promotion is applied, and a rollback model remains pinned;
- production graph evidence and `ops.scale-out` executor bindings are present and focused tests pass;
- the sanitized source receipt digest is recorded, `result.status` is `verified`, and residuals are
  empty.

## Current blockers

This prepared contract leaves one residual:

- the protected-runner live drill hasn't run;

Production composition binds the graph Dynamic evidence provider, and the development operations
gateway maps `ops.scale-out` to one exact Uniform VM Scale Set capacity increase. Focused tests
verify both bindings without treating them as live outcome evidence.

Until the live residual closes, the frozen scenario manifest remains `partial`, and the generated artifacts
remain local evidence rather than tracked live claims.

## Related docs

| To learn about | Read |
|----------------|------|
| Frozen planning scenarios | [Operational Planning](../roadmap/decisioning/operational-planning.md) |
| Integrated graph evidence and closure | [Operational Hypothesis Loop](../roadmap/rules-and-detection/operational-hypothesis-loop.md) |
| Active and challenger graph models | [Assurance Twin](../roadmap/operations/assurance-twin.md) |
