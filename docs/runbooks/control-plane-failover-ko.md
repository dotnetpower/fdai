---
title: 컨트롤 플레인 Regional Failover 및 Failback
summary: Split-brain execution이나 검증되지 않은 replay 없이 승인된 FDAI recovery plan 하나를 운영합니다.
translation_of: control-plane-failover.md
translation_source_sha: 7b0eec0af22385c79cfe0b88b3c974e685cf86b6
translation_revised: 2026-07-31
---

# 컨트롤 플레인 Regional Failover 및 Failback

FDAI 컨트롤 플레인의 regional outage 또는 예약된 regional drill에 이 runbook을 사용합니다.
[컨트롤 플레인 재해 복구 설계](../roadmap/deployment/control-plane-disaster-recovery-ko.md)에
정의된 state order, primary fencing, protected deployment, state와 event verification, traffic
transition 및 governed failback을 구현합니다.

> **범위:** 이 절차는 customer-neutral입니다. Downstream 배포가 region, protected environment
> file, resource reference, traffic provider, event recovery source, approval provider, owner 및
> evidence location을 제공합니다.
>
> **현재 upstream 경계:** Upstream은 alternate-region stack이나 traffic manager를
> provision하지 않습니다. Fork가 해당 capability를 binding하고 승인된 protected plan을 만들지
> 않았다면 readiness에서 중단합니다. Laptop 또는 ad-hoc local `terraform apply`는 recovery
> path가 아닙니다.

## 담당과 시작 기준

- **Incident commander:** Regional scenario와 outage start를 선언합니다.
- **Reliability owner:** RPO/RTO를 소유하고 drill 또는 recovery result를 수락합니다.
- **Operations owner:** 이 runbook과 recovery environment configuration을 소유합니다.
- **Approver:** Action-bound failover 및 failback approval을 인증합니다. Requester는 같은
  transition을 승인할 수 없습니다.
- **Executor:** Protected self-hosted deployment runner와 dedicated recovery identity입니다.
- **Impact scope:** 하나의 plan revision, 하나의 recovery epoch 및 하나의 선언된 control-plane
  scope입니다.

Outage가 incident 또는 승인된 drill에 연결되고 current recovery plan이 `ready`인 경우에만
시작합니다. Temporary Azure service degradation, unhealthy replica 하나 또는 availability-zone
event만으로 regional failover를 정당화할 수 없습니다.

## 필수 binding

Governed operator environment에 다음 값을 기록합니다. Token이나 secret value를 출력하지
않습니다.

```bash
export FDAI_REPOSITORY='<owner/repository>'
export FDAI_ENVIRONMENT_CONFIG='<recovery-environment-config>'
export FDAI_PREFLIGHT_INPUT='<recovery-preflight-input>'
export FDAI_BUNDLE_DIGEST='<lowercase-sha256>'
export FDAI_COMMIT_SHA='<40-character-git-sha>'
export FDAI_RECOVERY_PLAN_ID='<recovery-plan-id>'
export FDAI_RECOVERY_EPOCH='<positive-integer>'
export FDAI_READ_API_BASE_URL='https://<read-api-origin>'
```

Operator는 승인된 interactive identity flow로 `FDAI_OPERATOR_BEARER_TOKEN`을 얻고 process
memory에만 유지합니다. Recovery config는 primary와 recovery region, private networking,
identity/RBAC, DNS, state source, event source, traffic routing, image digest 및 선택된 `restore`
또는 `warm` profile을 제공합니다.

다음 binding이 하나라도 없으면 중단합니다.

- 승인된 numeric RPO/RTO와 fresh recovery-plan revision;
- primary fencing operation과 independent fence probe;
- remote Terraform state와 VNet-connected `[self-hosted, fdai-deploy]` runner;
- recovery region에서 사용 가능한 exact digest-pinned image;
- database restore source와 deterministic integrity/smoke verifier;
- event recovery source와 bounded replay window;
- action-bound approval verifier와 append-only `StateStore` CAS binding;
- identity, RBAC, private endpoint, private DNS, canary 및 traffic verification probe;
- rollback 또는 state-forward recovery와 cleanup owner.

## Phase 1 - 확인과 동결

1. Current repository artifact와 production evidence를 검증합니다.

   ```bash
   test "$(git rev-parse HEAD)" = "$FDAI_COMMIT_SHA"
   python3 scripts/governance/check-arb-readiness.py --require-production-ready
   fdaictl doctor --config "$FDAI_ENVIRONMENT_CONFIG" --output json
   fdaictl deploy preflight \
     --input "$FDAI_PREFLIGHT_INPUT" \
     --environment-config "$FDAI_ENVIRONMENT_CONFIG" \
     --output json
   ```

2. Outage start, last successful canary, latest audit checkpoint, current event checkpoint,
   active Process run 및 in-flight privileged action을 기록합니다.
3. Owner 또는 Break-Glass principal로 global kill switch를 활성화합니다.

   ```bash
   curl --fail --silent --show-error \
     -H "Authorization: Bearer $FDAI_OPERATOR_BEARER_TOKEN" \
     -H 'Content-Type: application/json' \
     -d "{\"engaged\":true,\"reason\":\"Regional recovery fence for plan $FDAI_RECOVERY_PLAN_ID\",\"request_id\":\"$FDAI_RECOVERY_PLAN_ID-fence-$FDAI_RECOVERY_EPOCH\"}" \
     "$FDAI_READ_API_BASE_URL/system/kill-switch"
   ```

4. 새 scheduler dispatch와 approval delivery를 중단합니다. 기존 action receipt는 evidence로
   유지하며 replacement action을 발행하지 않습니다.

## Phase 2 - Primary fencing

1. Fork-bound primary fence를 실행합니다. Fence는 evidence를 삭제하지 않고 이전 executor,
   event consumer 및 traffic path를 revoke하거나 isolate합니다.
2. 독립 identity와 network path에서 fence를 검증합니다. Evidence에는 old epoch, new epoch,
   영향 identity/scope, provider operation receipt 및 probe time이 포함됩니다.
3. Non-mutating old-epoch probe를 한 번 시도합니다. Deny되어야 합니다. Old epoch가 write할 수
   있으면 plan을 `halted`로 옮기고 recovery compute를 시작하지 않습니다.
4. Durable recovery coordinator를 통해 `activating -> primary_fenced`를 저장합니다. Stale storage
   revision, unverified approval, changed evidence 또는 CAS loss가 발생하면 중단합니다.

## Phase 3 - Recovery plan 및 provision

1. 새 protected plan을 제출합니다. Recovery는 일반 deployment plan이나 approval을 재사용하지
   않습니다.

   ```bash
   fdaictl deploy plan \
     --config "$FDAI_ENVIRONMENT_CONFIG" \
     --repository "$FDAI_REPOSITORY" \
     --bundle-digest "$FDAI_BUNDLE_DIGEST" \
     --commit-sha "$FDAI_COMMIT_SHA" \
     --output json
   ```

2. 반환된 plan id, digest, context digest, workflow run, expiry 및 recovery approval을
   recovery-plan transition에 binding합니다. Expired 또는 mismatched artifact는 차단합니다.
3. Private runner에서 exact approved plan만 apply합니다.

   ```bash
   fdaictl deploy apply \
     --repository "$FDAI_REPOSITORY" \
     --plan-id '<protected-plan-id>' \
     --output json
   ```

4. Workflow의 post-apply migration, readiness, health 및 canary check가 통과해야 합니다. 해당
   check 없는 successful Terraform process는 `runtime_started`가 아닙니다.

## Phase 4 - State 복원과 검증

1. Plan에 선언된 source에서 PostgreSQL과 immutable artifact를 복원합니다. PostgreSQL
   geo-backup은 paired region에서 사용 가능한 latest point를 기록하며 remote PITR을 주장하지
   않습니다.
2. Managed restore가 자동 복사하지 않는 network, private DNS, server parameter,
   Entra/database role, alert, HA 및 replica를 적용합니다.
3. Schema, row-count, checksum, foreign-key, retention 및 application smoke verification을
   실행합니다.
4. 복원된 audit hash chain과 exact checkpoint를 검증합니다. Decision replay는 judge-only
   mode에서만 실행하며 replay call은 executor에 도달할 수 없습니다.
5. Immutable evidence ref와 함께 `state_restored -> runtime_started -> audit_verified`를
   저장합니다.

## Phase 5 - Authority 없이 event 복구

1. Consumer와 privileged execution을 비활성 상태로 유지합니다.
2. 선언된 Event Hubs recovery strategy를 검증합니다. Metadata Geo-DR은 event나 reusable
   offset을 복사하지 않으므로 이것만으로는 충분하지 않습니다.
3. 승인된 source에서 bounded replay set을 만듭니다. Original event id, idempotency key,
   causal/resource ordering, source timestamp 및 audit checkpoint를 보존합니다.
4. Missing, duplicate, stale, malformed 또는 conflicting record를 기록합니다. Ambiguous
   record는 human review로 보내며 조용히 drop하거나 replay하지 않습니다.
5. 수락된 record가 terminal audit outcome에 도달할 수 있고 measured gap이 승인된 RPO 안에
   있을 때만 `event_recovery_ready`를 저장합니다.

## Phase 6 - Authority 전환과 service 검증

1. 새 recovery epoch와 consumer를 활성화합니다. Old epoch가 계속 fenced인지 확인합니다.
2. Fork-bound traffic switch를 적용합니다. Drill은 isolated synthetic traffic만 전환합니다.
3. Protected runner에서 deployed canary를 실행합니다.

   ```bash
   cd infra
   rg="$(terraform output -raw resource_group_name)"
   job="$(terraform output -raw canary_job_name)"
   test -n "$job"
   az containerapp job start --name "$job" --resource-group "$rg" >/dev/null
   execution="$(az containerapp job execution list --name "$job" --resource-group "$rg" \
     --query 'sort_by([], &properties.startTime)[-1].name' -o tsv)"
   az containerapp job execution show --name "$job" --resource-group "$rg" \
     --job-execution-name "$execution" --query properties.status -o tsv
   ```

4. Startup readiness, audit write, Event Hubs produce/consume, database read/write,
   identity/RBAC, private DNS, alert delivery 및 bounded capacity를 검증합니다.
5. Achieved RPO와 RTO를 측정합니다. Objective breach는 exercise를 `halted`로 옮기거나
   incident를 unsuccessful recovery로 기록하며 passing average로 만들지 않습니다.
6. 모든 check가 통과한 후에만 `traffic_shifted -> service_verified -> active_recovery`를
   저장합니다.

## Failback

Failback은 위 command의 역순이 아니라 새 recovery입니다.

1. Recovery region을 source of truth로 유지합니다. Target, objective, artifact 또는
   procedure가 바뀌면 새 plan revision을 만듭니다.
2. 별도 action-bound failback approval을 얻고 `failback_ready`를 저장합니다.
3. Active state에서 target을 rebuild 또는 resynchronize합니다. Stale primary database를
   시작하지 않습니다.
4. Target image digest, network, identity/RBAC, private DNS, state integrity, event checkpoint,
   canary 및 capacity를 검증합니다.
5. `failing_back`에서 새 epoch를 할당하고 active recovery executor를 fencing한 뒤 deny를
   입증합니다.
6. Consumer와 traffic을 전환하고 전체 service verification을 실행하며 observation window가
   끝날 때까지 이전 active region으로 rollback할 수 있게 유지합니다.
7. `primary_verified -> closed`를 저장하고 선택된 recovery profile을 다시 수립하며 reviewed
   plan으로 temporary resource를 제거한 뒤 cleanup을 검증합니다.

## Stop condition 및 rollback

다음 조건이 발생하면 plan을 `halted`로 옮기고 current reservation을 유지합니다.

- primary fence 또는 old-epoch denial을 입증할 수 없음;
- approval, plan digest, image digest, identity, RBAC, private DNS 또는 state evidence mismatch;
- restore integrity, audit hash chain, event completeness, canary, smoke 또는 capacity check 실패;
- time box, RPO, RTO, impact scope 또는 budget 초과;
- rollback 실패 또는 durable CAS transition에서 다른 writer가 승리.

Traffic shift 전 rollback은 새 protected plan을 통해 recovery runtime을 제거하거나 비활성화하고
incident commander가 다음 단계를 결정할 때까지 primary를 fenced로 유지합니다. Traffic shift 후
rollback은 마지막 verified active epoch의 state와 event checkpoint가 계속 authoritative한 경우에만
해당 epoch로 돌아갑니다. 그렇지 않으면 새 plan revision에서 state-forward recovery를 사용합니다.

## Evidence와 완료

하나의 plan correlation record에 다음 sanitized artifact를 첨부합니다.

- plan revision, storage revision, epoch, outage window, actor, approval 및 CAS receipt;
- primary fence와 stale-epoch denial;
- protected Terraform plan/apply, image/config/provider digest 및 workflow URL;
- database restore point, integrity, smoke, audit hash chain 및 checkpoint;
- event source, replay window, count, gap, duplicate, conflict 및 terminal outcome;
- identity/RBAC, private DNS, secret, readiness, canary, alert, traffic 및 capacity result;
- approved와 achieved RPO/RTO, rollback/failback receipt, cleanup 및 residual risk.

복구는 restored recovery profile과 accepted evidence가 있는 `closed`에서만 완료됩니다.
`active_recovery`는 recovery region에서 service가 운영 중이라는 뜻이며 완료가 아닙니다.
