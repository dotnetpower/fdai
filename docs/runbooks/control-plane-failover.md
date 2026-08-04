---
title: Control-Plane Regional Failover and Failback
summary: Operate one approved FDAI recovery plan without split-brain execution or unverified replay.
---

# Control-Plane Regional Failover and Failback

Use this runbook for an FDAI control-plane regional outage or its scheduled regional drill. It
implements the state order, primary fencing, protected deployment, state and event verification,
traffic transition, and governed failback defined by the
[control-plane disaster-recovery design](../roadmap/deployment/control-plane-disaster-recovery.md).

> **Scope:** This procedure is customer-neutral. A downstream deployment supplies regions,
> protected environment files, resource references, traffic provider, event recovery source,
> approval provider, owners, and evidence locations.
>
> **Current upstream boundary:** Upstream doesn't provision an alternate-region stack or traffic
> manager. Stop at readiness unless the fork has bound those capabilities and produced an approved
> protected plan. A laptop or ad-hoc local `terraform apply` is not a recovery path.

## Ownership and entry criteria

- **Incident commander:** declares the regional scenario and outage start.
- **Reliability owner:** owns RPO/RTO and accepts the drill or recovery result.
- **Operations owner:** owns this runbook and recovery environment configuration.
- **Approver:** authenticates the action-bound failover and failback approvals. The requester
  cannot approve the same transition.
- **Executor:** the protected self-hosted deployment runner and the dedicated recovery identity.
- **Impact scope:** one plan revision, one recovery epoch, and one declared control-plane scope.

Start only when the outage is tied to an incident or approved drill and a current recovery plan is
in `ready`. Temporary Azure service degradation, one unhealthy replica, or an availability-zone
event does not by itself justify regional failover.

## Required bindings

Record these values in the governed operator environment. Don't echo tokens or secret values.

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

The operator obtains `FDAI_OPERATOR_BEARER_TOKEN` through the approved interactive identity flow
and keeps it only in process memory. The recovery config supplies primary and recovery regions,
private networking, identity/RBAC, DNS, state source, event source, traffic routing, image digest,
and the selected `restore` or `warm` profile.

Stop if any of these bindings is absent:

- approved numeric RPO/RTO and fresh recovery-plan revision;
- primary fencing operation and independent fence probe;
- remote Terraform state and a VNet-connected `[self-hosted, fdai-deploy]` runner;
- exact digest-pinned image available in the recovery region;
- database restore source and deterministic integrity/smoke verifier;
- event recovery source and bounded replay window;
- action-bound approval verifier and append-only `StateStore` CAS binding;
- identity, RBAC, private endpoint, private DNS, canary, and traffic verification probes;
- rollback or state-forward recovery and cleanup owner.

## Phase 1 - Confirm and freeze

1. Verify the current repository artifact and production evidence:

   ```bash
   test "$(git rev-parse HEAD)" = "$FDAI_COMMIT_SHA"
   python3 scripts/governance/check-arb-readiness.py --require-production-ready
   fdaictl doctor --config "$FDAI_ENVIRONMENT_CONFIG" --output json
   fdaictl deploy preflight \
     --input "$FDAI_PREFLIGHT_INPUT" \
     --environment-config "$FDAI_ENVIRONMENT_CONFIG" \
     --output json
   ```

2. Record the outage start, last successful canary, latest audit checkpoint, current event
   checkpoints, active Process runs, and in-flight privileged actions.
3. Engage the global kill switch with an Owner or Break-Glass principal:

   ```bash
   curl --fail --silent --show-error \
     -H "Authorization: Bearer $FDAI_OPERATOR_BEARER_TOKEN" \
     -H 'Content-Type: application/json' \
     -d "{\"engaged\":true,\"reason\":\"Regional recovery fence for plan $FDAI_RECOVERY_PLAN_ID\",\"request_id\":\"$FDAI_RECOVERY_PLAN_ID-fence-$FDAI_RECOVERY_EPOCH\"}" \
     "$FDAI_READ_API_BASE_URL/system/kill-switch"
   ```

4. Stop new scheduler dispatch and approval delivery. Existing action receipts remain evidence;
   don't issue replacement actions.

## Phase 2 - Fence the primary

1. Execute the fork-bound primary fence. The fence revokes or isolates the old executor, event
   consumer, and traffic path without deleting evidence.
2. Verify the fence from an independent identity and network path. Required evidence includes:
   old epoch, new epoch, affected identities/scopes, provider operation receipt, and probe time.
3. Attempt one non-mutating old-epoch probe. It must be denied. If the old epoch can write, move
   the plan to `halted`; don't start recovery compute.
4. Persist `activating -> primary_fenced` through the durable recovery coordinator. A stale
   storage revision, unverified approval, changed evidence, or CAS loss stops the procedure.

## Phase 3 - Plan and provision recovery

1. Submit a new protected plan. Recovery never reuses a normal deployment plan or approval:

   ```bash
   fdaictl deploy plan \
     --config "$FDAI_ENVIRONMENT_CONFIG" \
     --repository "$FDAI_REPOSITORY" \
     --bundle-digest "$FDAI_BUNDLE_DIGEST" \
     --commit-sha "$FDAI_COMMIT_SHA" \
     --output json
   ```

2. Bind the returned plan id, digest, context digest, workflow run, expiry, and recovery approval
   to the recovery-plan transition. Reject expired or mismatched artifacts.
3. Apply only the exact approved plan through the private runner:

   ```bash
   fdaictl deploy apply \
     --repository "$FDAI_REPOSITORY" \
     --plan-id '<protected-plan-id>' \
     --output json
   ```

4. Require the workflow's post-apply migration, readiness, health, and canary checks to pass. A
   successful Terraform process without these checks is not `runtime_started`.

## Phase 4 - Restore and verify state

1. Restore PostgreSQL and immutable artifacts from the plan's declared sources. For PostgreSQL
   geo-backup, record the latest available paired-region point; don't claim remote PITR.
2. Apply network, private DNS, server parameters, Entra/database roles, alerts, HA, and replicas
   that the managed restore doesn't copy automatically.
3. Run schema, row-count, checksum, foreign-key, retention, and application smoke verification.
4. Verify the restored audit hash chain and exact checkpoint. Replay decisions only in judge-only
   mode; no replay call may reach an executor.
5. Persist `state_restored -> runtime_started -> audit_verified` with immutable evidence refs.

## Phase 5 - Recover events without authority

1. Keep consumers and privileged execution disabled.
2. Validate the declared Event Hubs recovery strategy. Metadata Geo-DR alone is insufficient
   because it doesn't copy events or reusable offsets.
3. Build the bounded replay set from the approved source. Preserve original event ids,
   idempotency keys, causal/resource ordering, source timestamps, and the audit checkpoint.
4. Record missing, duplicate, stale, malformed, or conflicting records. Ambiguous records go to
   human review; they are not silently dropped or replayed.
5. Persist `event_recovery_ready` only when accepted records can reach a terminal audit outcome and
   the measured gap is inside the approved RPO.

## Phase 6 - Shift authority and verify service

1. Enable the new recovery epoch and consumers. Confirm the old epoch remains fenced.
2. Apply the fork-bound traffic switch. A drill switches only isolated synthetic traffic.
3. Run the deployed canary from the protected runner:

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

4. Verify startup readiness, audit writes, Event Hubs produce/consume, database read/write,
   identity/RBAC, private DNS, alert delivery, and bounded capacity.
5. Measure achieved RPO and RTO. An objective breach moves the exercise to `halted` or records the
   incident as an unsuccessful recovery; it never becomes a passing average.
6. Persist `traffic_shifted -> service_verified -> active_recovery` only after all checks pass.

## Failback

Failback is a new recovery, not the reverse of the commands above.

1. Keep the recovery region as source of truth. Create a new plan revision if any target,
   objective, artifact, or procedure changes.
2. Obtain a separate action-bound failback approval and persist `failback_ready`.
3. Rebuild or resynchronize the target from active state. Never start the stale primary database.
4. Verify target image digest, network, identity/RBAC, private DNS, state integrity, event
   checkpoint, canary, and capacity.
5. Allocate a new epoch at `failing_back`, fence the active recovery executor, and prove denial.
6. Shift consumers and traffic, run the full service verification, and retain rollback to the
   former active region through the observation window.
7. Persist `primary_verified -> closed`, re-establish the selected recovery profile, remove
   temporary resources through a reviewed plan, and verify cleanup.

## Stop conditions and rollback

Move the plan to `halted` and retain the current reservation when any condition occurs:

- primary fence or old-epoch denial cannot be proven;
- approval, plan digest, image digest, identity, RBAC, private DNS, or state evidence mismatches;
- restore integrity, audit hash chain, event completeness, canary, smoke, or capacity check fails;
- time box, RPO, RTO, impact scope, or budget is exceeded;
- rollback fails or another writer wins the durable CAS transition.

Before traffic shift, rollback removes or disables the recovery runtime through a new protected
plan and leaves the primary fenced until the incident commander decides the next step. After
traffic shift, rollback returns to the last verified active epoch only when its state and event
checkpoint remain authoritative; otherwise use state-forward recovery under a new plan revision.

## Evidence and completion

Attach these sanitized artifacts to one plan correlation record:

- plan revision, storage revisions, epochs, outage window, actors, approvals, and CAS receipts;
- primary fence and stale-epoch denial;
- protected Terraform plan/apply, image/config/provider digests, and workflow URL;
- database restore point, integrity, smoke, audit hash chain, and checkpoint;
- event source, replay window, counts, gaps, duplicates, conflicts, and terminal outcomes;
- identity/RBAC, private DNS, secret, readiness, canary, alert, traffic, and capacity results;
- approved and achieved RPO/RTO, rollback/failback receipts, cleanup, and residual risk.

Recovery is complete only at `closed` with a restored recovery profile and accepted evidence.
`active_recovery` means service is operating from the recovery region; it is not completion.
