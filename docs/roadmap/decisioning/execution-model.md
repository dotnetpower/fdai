---
title: Execution Model
---

# Execution Model

How FDAI decides **whether** and **how** to run an action. This
document is authoritative for the unified RiskGate, the way the
authoritative [risk-classification.md](risk-classification.md) first-match
table combines with the **six-axis** ActionType ceiling, the four
executor paths (PR-native / direct API / PR-manual / tool call), the live-blast probe
combinator, and the safety invariants a live change must satisfy.

> Decision-engine relationship (authoritative): FDAI has **one**
> decision, produced by combining **two** inputs. The
> [risk-classification.md](risk-classification.md) first-match table is the
> **authoritative baseline** - it consumes the finding feature vector
> (`policy_violation`, `destructive`, `irreversible`, `data_plane_touched`,
> `cost_impact_monthly`, `verifier_confidence`, `blast_radius`,
> `environment`) and returns `auto | hil | deny` plus a `quorum`. The
> six-axis ceiling in this document consumes the ActionType + runtime
> context (tier, ActionType ceiling, static/live blast, role, env) and
> returns a per-dispatch ceiling. The RiskGate returns the **minimum** of
> the two; neither can raise autonomy above the other. The table is not
> replaced by the matrix - the matrix is an additional, never-raising
> constraint layered on top of it.

Consumers of this model:

- ControlLoop and the operator-console coordinator ask the RiskGate
  before dispatching any action.
- Each executor path implements the safety envelope declared by the
  action's ActionType ([action-ontology.md](action-ontology.md)).
- The operator-console surfaces the `resolved_ceiling` so an operator
  can see exactly why the system decided auto / HIL / deny.

> Customer-agnostic: every ceiling default, probe expression, and role
> assignment below is a placeholder. A fork tunes via the override seams
> documented in
> [action-ontology.md § 7](action-ontology.md#7-fork-override-seams).

> **Implementation status (2026-07-21):** Authority, risk table, kill switch, HIL resume,
> four paths, probe catalog, and typed operator proposals are implemented. Azure Monitor probe I/O remains a deployment binding.

## 1. What "execute" means here

Until this document, everything FDAI did was **shadow** - judge
and log, never mutate. Execution means that after all gates pass, the
executor calls the mutation surface (git PR merge, Azure ARM API,
scripted rollback runner) for real. Shadow mode is still the default
for every new action; execution is a promoted state, per-action, gated
on measured evidence and re-checked on every dispatch.

Four execution paths are supported (§5); their venue lifecycle stays behind Thor ([backend design](../interfaces/execution-backends.md)):

- **PR-native** - the change lands as a git PR that a merge policy
  auto-accepts (or a human accepts). Audit + rollback come from git.
- **Direct API** - the executor calls the substrate API directly (Azure
  ARM, kubectl, Redis). Audit lives in the audit log; rollback lives in
  the ActionType's `rollback_contract`.
- **PR-manual** - the change lands as a PR carrying the `hil` label; no
  auto-merge, an approver must accept. Used for high-risk actions where
  automated verification is not enough.
- **Tool call** - invoke a capability-bounded function through `ToolExecutor`, without an executor bypass.

A single ActionType declares its path; a fork overrides via ontology overlays. A backend adds no path
or role: risk, Var approval, lock, Vidar rollback, and Saga audit stay outside it; profiles only narrow.

## 2. Six-axis ceiling + risk-classification table

The RiskGate collapses **six orthogonal ceiling axes** plus the
authoritative risk-classification table into one decision. Every axis and
the table lowers autonomy independently; the final decision is the
**minimum** of what each input permits. Nothing here ever raises
autonomy - upgrades go through the promotion pipeline
([phase-2-quality-and-t1.md § Promotion](../phases/phase-2-quality-and-t1.md#promotion-shadow--enforce)),
not through the RiskGate at dispatch time.

```
authority = min(
  A_risk_table    # risk-classification.md first-match table (authoritative baseline; also yields quorum)
  A_tier          # T0 | T1 | T2
  A_ceiling       # ActionType.ceiling_by_tier[tier]
  A_static_blast  # ActionType.blast_radius (declared)
  A_live_blast    # live probe -> quiet | active | overloaded (Month 1+)
  A_role          # min_role vs principal role (RBAC)
  A_env           # prod -> downgrade per ActionType.prod_downgrade
)
```

Each input returns one of:

- `enforce_auto` - allowed to execute without HIL.
- `enforce_hil` - allowed to execute, but a human approval is required.
- `shadow_only` - judge and log; no mutation.
- `deny` - do not proceed; the decision is a hard stop.

The final RiskGate output is a **`RiskDecision`** carrying the winning
minimum, the `quorum` from the risk-classification table (default 1;
`2` for irreversible per [risk-classification.md](risk-classification.md)),
plus a `resolved_ceiling` breakdown (§8) that names each input's
contribution so the audit consumer can render the reasoning.

### 2.0 Axis A - Risk-classification table (authoritative baseline)

`A_risk_table` is the result of evaluating the first-match table in
[risk-classification.md](risk-classification.md) against the finding
feature vector. This axis is the **only** place the following signals are
evaluated - the six ceiling axes deliberately do not re-derive them:

- `policy_violation` (verifier verdict) -> `deny`.
- `destructive` (`operation in {delete, drop, purge, detach}`) -> `hil`.
- `irreversible` (`ActionType.irreversible == true`) -> `hil` with
  `quorum: 2`.
- `data_plane_touched` (`interfaces include DataPlaneMutating`) -> `hil`.
- `cost_impact_monthly >= $100` -> `hil` (Cost Governance vertical gate;
  this is why `ops.scale-out` and every cost-increasing action cannot go
  `auto` without clearing the cost threshold - see §2.8).
- `verifier_confidence < 0.85` (T2 quality-gate signal) -> `hil`.
- `blast_radius` and `environment` are also evaluated here and are the
  authoritative source for those two signals (the six-axis static/live
  blast and env axes only ever *further* lower, never contradict).

`A_risk_table` returns the table's `decision` mapped onto the four
levels (`deny -> deny`, `hil -> enforce_hil`, `auto -> enforce_auto`),
and carries the matched rule id + `catalog_version` into the audit entry.

### 2.1 Axis B - Tier

Comes from the trust router.

| Tier | Default posture |
|------|-----------------|
| T0 (deterministic) | `enforce_auto` allowed - the T0 verdict is a policy-as-code pass |
| T1 (lightweight similarity) | Upstream catalog ceilings are conservative; overlays may only lower autonomy. Raising authority requires the separate governed promotion path, never a dispatch-time override. |
| T2 (frontier reasoning) | Catalog loading hard-caps T2 at `shadow_only`; changing that hard cap is a reviewed upstream policy change, not a fork overlay. |

### 2.2 Axis C - ActionType ceiling

From `ceiling_by_tier` on the ActionType (see
[action-ontology.md § 2](action-ontology.md#2-schema)).

### 2.3 Axis D - Static blast radius

The `blast_radius` block on the ActionType. Two computation modes:

- `static_enum` - one of `resource | resource_group | subscription`
  (the CSP-neutral bucket vocabulary shared with
  [risk-classification.md](risk-classification.md)). The wider the
  bucket, the lower this axis returns:
  - `resource` -> does not lower autonomy on its own.
  - `resource_group` -> caps at `enforce_hil`.
  - `subscription` -> `deny` (no autonomous change spans a full
    subscription; matches the risk-classification deny rule).
- `graph_derived` - computed from the inventory graph at dispatch time.
  A value above `max_affected_resources` caps at `enforce_hil`
  regardless of the other axes.

### 2.4 Axis E - Live blast probe (Month 1+)

`ActionType.live_probe_ref` names a probe. The probe returns one of
three levels (§4). The mapping is:

| Probe result | Effect on ceiling |
|--------------|-------------------|
| `quiet` | no change - static ceiling wins |
| `active` | cap at `enforce_hil` (human approves) |
| `overloaded` | cap at `shadow_only` (defer; too risky right now) |

If `live_probe_ref` is unset the axis returns "no opinion" - it does
not lower autonomy on its own.

### 2.5 Axis F - Role (RBAC)

`ActionType.ceiling_by_tier[tier].min_role` vs the calling principal's
resolved role (from
[user-rbac-and-identity.md](../interfaces/user-rbac-and-identity.md)):

- Principal at or above `min_role` in the ordinary ladder
  (`reader < contributor < approver < owner`) -> axis returns the tier
  default.
- Principal below `min_role` -> axis returns `deny`.
- **BreakGlass is off-ladder, not the top rung.** BreakGlass is a
  separate Entra group that is *not* nested inside Owner
  ([user-rbac-and-identity.md § 2](../interfaces/user-rbac-and-identity.md#2-role-model-4-tiers--break-glass)).
  An active, time-boxed BreakGlass grant makes the caller *eligible* to
  approve a HIL item they would otherwise be under-privileged for, but it
  never returns `enforce_auto` - the axis caps at `enforce_hil` for a
  BreakGlass-eligible caller. BreakGlass raises approval eligibility, not
  automation.

For rule-fired actions the "principal" is the executor identity
(system MI); its role is fixed at composition time
([composition.py](../../../src/fdai/composition/__init__.py)).

### 2.6 Axis G - Environment (prod downgrade)

`ActionType.prod_downgrade.detection_ref` names an env-detector. To avoid
two definitions of "prod", the detector reference resolves to the **same**
environment classifier defined in
[risk-classification.md § Environment Detection](risk-classification.md#environment-detection)
(resource-group `environment` tag; missing/unrecognized tag -> `prod`,
fail-safe). When the detector returns "prod" for the target resource, the
axis caps at `prod_downgrade.mode` (typically `enforce_hil` or
`shadow_only`).

A missing `prod_downgrade` block means the axis is inactive **only for
dev-only ActionTypes that declare `env_scope: non_prod`**; any ActionType
without an explicit `env_scope` inherits the risk-classification env
signal (Axis A) so a missing block can never silently fail open into a
prod auto-execution.

### 2.6a Fail-safe axis - System health (degradation)

A seventh axis, `system_health`, is present **only when the control plane
is DEGRADED** - one or more critical dependencies (audit store, event bus,
substrate) have a tripped circuit breaker. It caps autonomy at
`shadow_only`, so a failing dependency can never drive an enforce-mode
mutation ("fail toward safety" at system scope, see
[csp-neutrality.md](../architecture/csp-neutrality.md)). The axis is fed by
[`DegradationController.autonomy_permitted()`](../../../src/fdai/shared/resilience/degradation.py)
through the `system_degraded` input on `evaluate_execution_authority`; when
the system is healthy the axis is omitted and the decision is the
byte-identical six-axis result.

### 2.6b Fail-safe axis - Kill-switch (operator emergency stop)

An eighth axis, `kill_switch`, is present **only when the operator has
engaged the global kill-switch** - a deliberate emergency action (RBAC
`TRIGGER_KILL_SWITCH`) that halts all auto-execution immediately. Like
`system_health` it caps autonomy at `shadow_only`, so no action mutates
while the halt is active (a human path stays open via HIL). It is fed by
[`KillSwitch.is_engaged()`](../../../src/fdai/shared/resilience/kill_switch.py)
through the `kill_switch_engaged` input on `evaluate_execution_authority`;
the switch is operable without the executor identity (a fork backs its state
in the state store) - see
[security-and-identity.md](../architecture/security-and-identity.md). When
disengaged the axis is omitted (byte-identical result).

### 2.7 Combining

Every input returns one of the four levels above; the RiskGate takes the
**minimum** in the ordering
`enforce_auto > enforce_hil > shadow_only > deny` (over the six axes plus
the optional `system_health` and `kill_switch` fail-safe axes). `deny` from
any input (including the risk-classification table) is a hard stop; the
executor is never called. The `quorum` accompanying `enforce_hil` is the
maximum of the table quorum and any axis-declared quorum.

### 2.8 Cost-increasing ops actions

`ops.*` actions that raise spend (`ops.scale-out`, `ops.failover-primary`
to a larger tier) MUST declare a `cost_impact_monthly` estimate on the
ActionType so Axis A (the risk-classification table) can apply the
`>= $100 -> hil` gate. An `ops.scale-out` with an unknown or above-
threshold cost estimate is never `auto`; this keeps the Cost Governance
vertical authoritative over runtime ops that would otherwise bypass it
through the `direct_api` fast path. The Cost Governance vertical
([verticals](../../../src/fdai/core/verticals)) owns the estimate
function; the ActionType only references it.

## 3. Unified RiskGate

The RiskGate lives in
[`src/fdai/core/risk_gate/`](../../../src/fdai/core/risk_gate)
and is the single decision point for **both** trigger surfaces (rule-
fired and operator-requested; see
[action-ontology.md § 4](action-ontology.md#4-trigger-surfaces)).

> Implementation status: the pure combinator ships as
> [`ceiling.py`](../../../src/fdai/core/risk_gate/ceiling.py) (the six
> axes), [`risk_table.py`](../../../src/fdai/core/risk_gate/risk_table.py)
> (Axis A first-match table + `rule-catalog/risk-classification.yaml`), and
> [`feature.py`](../../../src/fdai/core/risk_gate/feature.py) (the
> `FeatureVector` extractor), unified end-to-end by
> [`authority.py`](../../../src/fdai/core/risk_gate/authority.py)
> `evaluate_execution_authority()`. That function is the single pipeline
> `feature -> table (Axis A) -> six-axis min() -> ExecutionAuthorityDecision`.
> The [`ControlLoop`](../../../src/fdai/core/control_loop/orchestrator.py) invokes it in
> two modes. When only a risk table is wired it records one
> `risk_gate.shadow_authority` audit entry per executed action (authority-only,
> judge-and-log, executor path unchanged). When both the risk table and the
> pre-existing [`gate.py`](../../../src/fdai/core/risk_gate/gate.py)
> `RiskGate` are wired, the gate (runtime Action safety: exemption /
> precondition / promotion) and the authority (policy ceiling) are combined
> into one `UnifiedRiskDecision` by
> [`evaluator.py`](../../../src/fdai/core/risk_gate/evaluator.py)
> `combine()` (canonical-level `min()`, both evaluators unchanged), and the
> loop **routes on it**: a `deny` or `hil` decision skips the executor
> (overall outcome `DENIED` / `HIL`, no PR published), only `auto` proceeds to
> execution. Each routed action writes one `risk_gate.unified` audit entry.

Contract:

```python
class RiskGate(Protocol):
    def evaluate(
        self,
        *,
        action_type: OntologyActionType,
        action: Action,
        trigger_kind: TriggerKind,
        tier: TrustTier,
        principal: Principal,
        env: EnvClassification,
        risk_table_result: RiskTableResult,   # Axis A, pre-computed (§2.0)
        live_probe_result: ProbeResult | None, # Axis E, pre-fetched (§4)
        promotion_state: ActionModeRecord,
    ) -> RiskDecision: ...

@dataclass(frozen=True)
class RiskDecision:
    decision: Literal["auto", "hil", "abstain", "deny"]
    mode: Literal["shadow", "enforce"]
    quorum: int                            # from Axis A; 1 default, 2 for irreversible
    matched_rule_id: str                   # risk-classification rule id (or "default")
    catalog_version: str                   # risk-classification.yaml version at decision time
    execution_path: ExecutionPath          # inherited from ActionType, may be forced lower
    resolved_ceiling: ResolvedCeiling      # audit-friendly breakdown (§8)
    hil_queue_id: str | None               # populated when decision == "hil"
```

- **RiskGate stays a pure, synchronous function.** All I/O (the live
  probe, the inventory graph walk for `graph_derived` blast) is performed
  **before** `evaluate` and passed in as `live_probe_result` /
  pre-resolved blast. This preserves determinism (§7), keeps `evaluate`
  off the async seam list in
  [coding-conventions.instructions.md](../../../.github/instructions/coding-conventions.instructions.md#safety),
  and matches the existing synchronous
  [`RiskGate.evaluate`](../../../src/fdai/core/risk_gate/gate.py). The
  probe pre-fetch happens in the ControlLoop / coordinator, which are
  already async.
- **Compatibility boundary.** The runtime safety gate keeps its typed
  `RiskDecision(outcome: RiskDecisionOutcome, ...)`; the authority evaluator
  produces `ExecutionAuthorityDecision`, and `evaluator.py` combines both into
  `UnifiedRiskDecision`. Callers consume that combined contract rather than a
  staged field migration on the original dataclass.
- `promotion_state` is read from the existing
  [`ActionPromotionRegistry`](../../../src/fdai/core/risk_gate/gate.py) -
  a shadow-mode ActionType clamps `mode` to `shadow` regardless of
  what the axes permit.
- `execution_path` is the ActionType default unless an axis
  (typically the role or env axis) forces a downgrade (e.g. a
  compliance-heavy fork forces `pr_manual` for all direct-API
  ActionTypes in prod).
- The RiskGate is called **once per dispatch attempt**. Re-check on
  retry is a fresh dispatch (fresh audit entry).

### 3.1 Interaction with the operator-console verifier

The console's coordinator re-runs the RiskGate on every write-class
tool call ([operator-console.md § 7.2](../interfaces/operator-console.md#72-three-chat-specific-invariants),
invariant 5). The console never bypasses this path; there is no
"trusted narrator shortcut".

### 3.2 Interaction with `ActionPromotionRegistry`

Promotion is orthogonal to the RiskGate:

- `ActionPromotionRegistry.mode_of(action_type)` decides whether the
  ActionType is enforce-eligible at all.
- The RiskGate takes that as an upper bound and combines it with the 5
  axes. A promoted ActionType may still be gated to `hil` by the axes;
  the promotion state does not force `auto`.

## 4. Live blast probe

Static `blast_radius` says "this ActionType could affect up to a resource
group"; live probes say "this specific resource has zero traffic in
the last 5 minutes, so the affect is nil". Combining static + live is
the mechanism behind the intuition that a running NSG rule change is
low-impact when nothing calls it.

### 4.1 Probe declaration

Probes live under [`rule-catalog/probes/`](../../../rule-catalog/probes):

```yaml
schema_version: "1.0.0"
id: vm_traffic_last_5m
description: "Return quiet/active/overloaded based on VM network throughput over the last 5 minutes."
adapter_ref: probe-adapters/azure-monitor       # DI seam id
adapter_payload:                                # adapter-specific; NOT part of the core probe
  kql: |                                        # schema, so the core stays CSP-neutral
    AzureMetrics
    | where ResourceId == '{{ target_ref }}'
    | where MetricName == 'Network In Total'
    | where TimeGenerated > ago(5m)
    | summarize p = percentile(Total, 95)
interpretation:
  quiet:      p < 1000000            # <1 MB/5min
  active:     p < 100000000          # <100 MB/5min
  overloaded: p >= 100000000
timeout_seconds: 5
cache_ttl_seconds: 60
```

### 4.2 Runtime shape

The RiskGate calls the probe **only** when:

- `ActionType.live_probe_ref` is set.
- The other axes have not already forced `shadow_only` or `deny`
  (probe cost is only paid when it can actually change the decision).
- The probe cache has no fresh answer for the target.

**Probe failure handling (fail toward safety).** The probe is a
*ceiling-lowering* axis, never an authorizer. On a single failure
(timeout, adapter error) the axis returns `active` - it forces HIL rather
than auto, so a human confirms while the probe is blind, but it does not
hard-stop an operator-initiated action. On **repeated** failure across a
rolling window (default 3 within `cache_ttl_seconds * 5`) the axis
escalates its own posture to `shadow_only` and writes a `probe.degraded`
audit entry: a persistently blind probe means the loop should stop
executing that ActionType until an operator inspects, not keep approving
by hand indefinitely. It still does not fail-close the *entire* loop -
only the ActionTypes bound to the degraded probe.

**Replay uses the recorded result, never a re-query.** When the audit log
is replayed for debugging or post-incident review, the RiskGate reads
`live_probe_result` from the recorded `resolved_ceiling` (§8); it MUST NOT
call the probe again. This keeps replay judge-only and deterministic
([architecture.instructions.md § Idempotency, Ordering, and Replay](../../../.github/instructions/architecture.instructions.md#idempotency-ordering-and-replay)).

### 4.3 Probe adapter seam

```python
class LiveBlastProbe(Protocol):
    async def measure(
        self,
        *,
        probe_id: str,
        target_ref: str,
        deadline_seconds: float,
    ) -> ProbeResult: ...
```

Upstream Day-1 ships the fake `NoOpBlastProbe` (returns "no opinion");
Month-1 adds `AzureMonitorBlastProbe`. A fork may bind any adapter that
implements the Protocol.

## 5. Executor paths

Four paths cover every action. Three form a substrate-mutation ladder
(`pr_native`, `direct_api`, `pr_manual`); the ActionType names one and
the RiskGate may downgrade (never upgrade) to `pr_manual`. The fourth,
`tool_call`, is a separate function-invocation surface (§5.6) - it
mutates no substrate, so it does not sit on that ladder.

### 5.1 PR-native (`pr_native`)

- Executor builds a PR via
  [`GitOpsPrAdapter`](../../../src/fdai/delivery/gitops_pr/adapter.py).
- On `auto` decision, the PR carries no `hil` label and the branch's
  auto-merge policy accepts.
- On `hil` decision, the PR carries the `hil` label and an approver
  merges via the console.
- Audit + rollback lean on git: revert commit is the rollback path.

Best for: configuration changes, IaC patches, catalog updates,
governance changes.

### 5.2 Direct API (`direct_api`)

- Executor calls the substrate API directly (Azure ARM, kubectl, Redis
  via the corresponding delivery adapter under `src/fdai/delivery/`).
- On `auto` decision, the call proceeds without HIL; the ActionType's
  `stop_conditions` and `preconditions` are enforced by the executor
  before and during the call.
- On `hil` decision, the executor enqueues a HIL item (identical to
  the PR-manual queue but with `mutation_target=direct` in the item);
  an approver accepts via the console; the executor then dispatches.
- Rollback comes from the ActionType's `rollback_contract`
  (`scripted`, `pitr`, `snapshot_restore`).
- **Idempotency invariant** - every direct-API call uses the action's
  stable idempotency key (existing invariant in
  [coding-conventions.instructions.md](../../../.github/instructions/coding-conventions.instructions.md));
  a retried call MUST NOT double-apply.

Best for: ops actions where latency matters (restart, scale, cache
flush).

### 5.3 PR-manual (`pr_manual`)

- Same as PR-native but the auto-merge policy is disabled for this
  PR (label `hil` + explicit `merge-not-eligible`).
- Human review is required regardless of the axes; even
  `enforce_auto` on every axis still lands as a manual-merge PR.
- Used for very high-risk actions or compliance-heavy environments
  where every mutation MUST be reviewable diff regardless of
  automation.

Best for: irreversible changes with a scripted rollback, governance
changes that a fork wants a second pair of eyes on regardless of
automation.

### 5.4 Executor selection at dispatch

```
requested_path = ActionType.execution_path
forced_path = RiskGate.resolved_ceiling.forced_execution_path  # optional axis output
final_path = strictest(requested_path, forced_path)
                # strict order (by review-stringency, not speed):
                #   pr_manual > pr_native > direct_api
```

"Strictest" here means **most human-review-gated**, not fastest:
`pr_manual` (mandatory human merge) is stricter than `pr_native`
(policy auto-merge) which is stricter than `direct_api` (no diff). An
axis may only move a dispatch **up** this ladder (toward more review); it
can never move it down for latency. A fork can force every dispatch in
prod to `pr_manual` via the env axis. The upstream never forces from
below (never lifts `pr_manual` to `direct_api` for speed).

**Fallback idempotency.** When a dispatch degrades from `direct_api` to
`pr_manual` mid-flight (§11), the fallback PR reuses the action's stable
idempotency key. The direct-API adapter records the attempted-and-failed
call under that key so the manual PR path cannot double-apply the same
mutation; a subsequent retry observes the key and is a no-op on whichever
path already succeeded.

### 5.5 HIL approval round-trip (park and resume)

When the RiskGate returns `hil`, the executor does not run and the
control loop does not block on a human. The `HilResumeCoordinator`
(`core/hil_resume`) applies a **park and return** model:

1. **park** - the full `Action` (+ rule id, submitter, correlation id)
   is serialized into the `StateStore` under an opaque `approval_id`
   with `status=pending`;
2. **push** - an A1 approval card is dispatched via the `HilChannel`
   (Teams / Slack); a delivery failure leaves the action parked and
   recoverable, never executed;
3. **audit** - a `hil.requested` entry is written, then
   `ControlLoop.process(...)` returns `hil` without blocking.

A later decision (a ChatOps callback or a poll) drives
`HilResumeCoordinator.resolve(approval_id, decision, approver_oid)`:

- **APPROVE** - the parked `Action` is restored (`model_validate`) and
  re-dispatched through the same executor selection (§5.4); one
  `hil.approved.executed` audit entry is written.
- **REJECT** / **TIMEOUT** - recorded, never executed (fail-closed).
- **expired APPROVE** - `expires_at` is checked before delegation and executor
  selection. An approval at or after expiry is atomically resolved as
  `TIMEOUT`, writes `hil.timeout`, and never executes. Expired records are
  excluded from the Reader HIL queue and `hil_pending` KPI projection.
- **idempotent** - the first terminal decision resolves the park; duplicates are no-ops and conflicts are refused, so approval cannot double-apply.
- **approval ID claim** - parking atomically claims the ID and audit record; exact replays reuse the park without another channel push, while different content conflicts.
- **no self-approval** - `approver_oid == submitter_oid` is refused
  before any execution; the loop parks with a system submitter identity
  so any real approver is distinct.

**Role-scoped queue + delegation (Scenario A).** A parked HIL item is a
**queue, not a per-person inbox**: any operator holding
`Capability.APPROVE_RUNTIME_HIL` may resolve it. The park records an
optional `assignee_oid` - the operator the item was surfaced to, defaulting
to the resolved on-call primary. When a *different* authorized operator
approves it, that is a **delegated** approval: allowed (same authority) and
recorded distinctly, so the audit entry names both the actual `approver_oid`
and the original `assignee_oid` (`delegation_mode` = `direct` / `delegated`
/ `role_scoped`). The gate is one pure function
(`core/hil_resume/delegation.py`) shared by the coordinator and the read-API
callback so the rule never drifts. Refusals stay fail-closed: a blank /
self-approving / capability-lacking approver never executes
(`missing_capability` returns 403 and leaves the park resolvable by an
authorized operator). The read-API callback derives
`approver_can_approve_hil` from the HMAC-signed `actor_roles` the push
channel asserts; an omitted `actor_roles` trusts the channel (defaults to
allowed) while no-self-approval and the HMAC gate still apply.

This closes the loop between the `hil` verdict (§2) and an approved
action actually running, without a blocking wait or an ungated
auto-execution. The read-API HIL callback
(`POST /hil/{approval_id}/decision`) drives the resolve trigger: an
inbound decision hits the coordinator first (park path - `APPROVE`
re-dispatches to the executor), and falls through to the registry for
console-pull approvals raised via `approve_hil`. The coordinator is
transport-neutral. `__main__` wires it into the control loop when a
ChatOps channel is configured (`FDAI_CHATOPS_WEBHOOK_URL`), so a `hil`
verdict parks the action and pushes an A1 card; absent, the loop records
the verdict and falls back to the persisted queue. The read-API server
supplies the same coordinator to the callback route so an inbound
decision resolves the park.

**Notify-on-decision.** The same loop also emits an A2 operational-alert
on every terminal decision (`executed` / `hil` / `denied`) through the
notification router - outbound-only, informational, and never carrying
approval buttons (see
[channels-and-notifications.md § 3](../interfaces/channels-and-notifications.md)). The
router is an optional seam: absent, the loop behaves exactly as before.

### 5.6 Tool call (`tool_call`)

- Executor invokes a **registered function** - generate a PDF report,
  send a notification, open a ticket - through the
  [`ToolExecutor`](../../../src/fdai/shared/providers/tool.py) Protocol
  (`ToolCallShadowExecutor` in `core/executor/tool_call.py`). It mutates
  no cloud substrate; it produces an **artifact** or a side effect. This
  is the ontology-native counterpart of the way an LLM calls a tool: a
  `tool.*` ActionType names one registered tool and the executor
  dispatches it here. The tool registry is the natural attach point for
  an MCP adapter - an `McpToolExecutor` implementing the Protocol maps
  one MCP server tool onto one `tool.*` ActionType.
- MCP servers register through `McpServerCatalog`. A server manifest validates its endpoint and
  ActionType-to-tool allowlist, installs disabled, and can enable only after a read-only
  `tools/list` discovery proves every allowlisted tool exists. Public endpoints require HTTPS;
  HTTP is accepted only for loopback sidecars. Payload URLs never override the configured server
  endpoint. Two enabled servers cannot own the same ActionType. The enabled catalog projects
  routes into the existing `RoutingToolExecutor`; it creates no new execution path.
- `core/` knows only the Protocol; a fork binds a live adapter (a native
  Python registry, an MCP client, an HTTP callout) at the composition
  root. The default binding is `RecordingToolExecutor` (no real function
  runs). A configured `FDAI_JIRA_BASE_URL` binds `JiraToolExecutor` with a
  PostgreSQL idempotency ledger and distributed resource lock. It remains
  shadow until both the ActionType promotion gate and `FDAI_JIRA_ENFORCE=1`
  permit enforce mode. Enforce creation adds a deterministic
  `fdai-idem-<sha256>` label. Before any POST, it atomically writes a durable
  pending claim and searches through Jira's enhanced `/rest/api/3/search/jql`
  endpoint. A retry after a create-before-ledger crash may reconcile the
  existing issue and return `already_applied`; while a prior claim remains but
  Jira has not exposed an issue yet, it fails closed instead of risking a
  duplicate. Search failures before POST and definitive create `4xx` responses
  release a newly acquired claim. Transport failures, `5xx` responses, and
  malformed successful create responses keep the claim quarantined because the
  side effect is ambiguous. Each retry searches Jira again, and retryable
  adapter failures are audited but not cached by the core executor. The
  `fdai-idem-` label namespace is adapter-owned: request-supplied labels with
  that prefix are discarded so one request cannot alias another key. Audit
  entries record the Action's actual `shadow` or `enforce` mode. Cancellation
  before POST releases the claim and writes a failed audit entry before it is
  re-raised. The core populates its in-memory dedupe cache only after the
  durable execution result is recorded, so a transient durable-write failure
  remains retryable.
- On `auto` decision, the call proceeds without HIL; the ActionType's
  `preconditions` and `stop_conditions` are enforced by the executor.
- On `hil` decision, the executor parks the action and resumes it on
  approval through the same HIL round-trip as `direct_api` (§5.5).
- Rollback comes from the ActionType's `rollback_contract` - usually
  `state_forward_only` (delete the produced artifact) or `scripted`.
- **Idempotency invariant** - every tool call uses the action's stable
  idempotency key; a retried call MUST NOT re-run the tool (a second
  call with the same key returns `already_applied`).
- All four safety invariants still apply. A `tool.*` ActionType is
  shadow-first with a measurable `promotion_gate`, exactly like a
  mutation ActionType; the executor writes exactly one audit entry per
  attempt with `action_kind=executor.tool_call.<outcome>` and
  `execution_path=tool_call`.
- `tool.open-incident-ticket` is the built-in ticket ActionType. Shadow
  receipts are never linked as real tickets. A successful enforce receipt
  passes through `link_ticket_receipt` before terminal executor success and
  appends `incident.ticket`; linkage failure stays retryable and cannot be
  cached as success.

Best for: document generation, notifications, ticketing, and any
registered function a workflow step wants to invoke via
`action_type_ref` without opening a PR or touching a substrate.

## 6. Safety invariants (unchanged + one extension)

Every executed action already carries the four autonomy invariants
from
[coding-conventions.instructions.md § Safety](../../../.github/instructions/coding-conventions.instructions.md#safety)
(stop-condition, rollback, blast-radius limit, audit). This document
adds one:

5. **Every dispatch writes its `resolved_ceiling`.** The audit entry
   MUST carry the full 6-axis breakdown (including the `risk_table` axis)
   that produced the decision, so
   a future overlay change never breaks the reproducibility of a past
   decision.

The other invariants apply exactly as before - no chat-specific
carve-outs, no direct-API relaxation.

### 6.1 Interaction with the operator-console invariants

The chat-specific invariants ([operator-console.md § 7.2](../interfaces/operator-console.md#72-three-chat-specific-invariants))
are additive:

- **Chat invariant 5 (verifier re-check)** = "run the RiskGate on
  every write-class tool call". This document is the definition of
  that RiskGate; the console just calls it.
- **Chat invariant 6 (no self-approval)** = the RiskGate's role axis
  (Axis F) refuses `approve_hil` when the caller's Entra `oid`
  matches the requester recorded on the queued item.
- **Chat invariant 7 (BreakGlass time-boxed)** = Axis F's BreakGlass
  behaviour (§2.5): BreakGlass raises the eligible role for approval
  but never bypasses HIL.

## 7. Determinism + auditability

- Given the same 6-axis inputs, the RiskGate returns the same
  `RiskDecision`. Any stochastic component (a probe that queries a
  moving window) is bounded by `cache_ttl_seconds` on the probe so a
  replay within the TTL yields the identical decision.
- The `resolved_ceiling` block is a full self-explanation of the
  decision - a future overlay change never invalidates a past audit
  entry, because the ceiling that was in effect at dispatch time is
  the record of truth.

## 8. `resolved_ceiling` audit block

Every dispatch writes:

```json
{
  "resolved_ceiling": {
    "tier": "T0",
    "action_type_id": "ops.restart-service",
    "axes": {
      "risk_table":     {"level": "enforce_hil",  "reason": "cost_impact_monthly >= 100", "matched_rule_id": "cost-threshold", "catalog_version": "1.0.0", "quorum": 1},
      "tier":           {"level": "enforce_auto", "reason": "T0 verdict on shadow-promoted ActionType"},
      "ceiling":        {"level": "enforce_hil",  "reason": "ceiling_by_tier.t0.max_autonomy"},
      "static_blast":   {"level": "enforce_auto", "reason": "static_bucket=resource"},
      "live_blast":     {"level": "enforce_hil",  "reason": "probe=vm_traffic_last_5m returned active", "probe_result": "active"},
      "role":           {"level": "enforce_hil",  "reason": "principal=contributor >= min_role=contributor"},
      "env":            {"level": "enforce_auto", "reason": "not-prod"}
    },
    "winning_axis": "risk_table",
    "final_level":  "enforce_hil",
    "final_quorum": 1,
    "final_path":   "direct_api",
    "overlay_layers_applied": ["upstream", "rego"]
  }
}
```

The `resolved_ceiling` shape is a fixed, versioned contract validated by a
JSON Schema (`ontology/resolved-ceiling`), added in the Week-1 schema-
extension PR alongside the `RiskDecision` migration (§3). The narrator and
audit consumers render it verbatim, so a schema-checked shape is required,
not optional; a contract test asserts every dispatch emits a schema-valid
block including the `risk_table` axis.

## 9. Rollout record

The execution model landed as a data + policy change without a subsystem tier
upgrade. The sequence below records the rollout and matches the ActionType
migration record in [action-ontology.md § 10](action-ontology.md#10-migration-record).

### Day 1

- Schema extension only. Loader learns the new fields; every existing
  ActionType validates. The RiskGate keeps behaving as it does today
  (shadow-only) because `promotion_state` is shadow for every entry.
- **Exit gate**: property tests over the 6-axis min-combination; every
  existing shipped rule still produces the same shadow-only outcome
  it did before the change.

### Week 1

- Ontology backfill lands (see action-ontology.md § 10 step 2).
- ControlLoop starts routing through the unified RiskGate on every
  dispatch (was previously a stub); execution stays shadow-only because
  no ActionType has been promoted yet.
- Operator-console pull-direction ships with the argument-schema-
  validated dispatch path (§3.1).
- **Exit gate**: `resolved_ceiling` audit block appears on every
  dispatch; end-to-end test covers rule-fired and operator-fired paths
  reaching the same executor via the same RiskGate.

### Week 2

- First `ops.*` ActionTypes land with `execution_path=direct_api` and
  `ceiling_by_tier.t0.max_autonomy=enforce_auto`. The RiskGate now
  produces `auto` for those in non-prod on a Reader-visible resource.
- **Exit gate**: a Contributor via the console executes
  `ops.restart-service` on a non-prod resource under live-probe fake
  (`quiet`), the executor calls the (mocked) ARM API, the audit entry
  carries the `direct_api` path.

### Month 1

- Real `AzureMonitorBlastProbe` binds; live probes go live on the
  ActionTypes that opt in.
- `governance.override-ceiling` lands so an Owner can time-box a
  ceiling downgrade from the console (§7.4 of action-ontology).
- **Exit gate**: at least one live probe reduces autonomy at least
  once in production shadow measurement; the audit entry shows
  `winning_axis=live_blast` on that dispatch.

## 10. Testability

- **Six-axis + table matrix** - the full cartesian product
  (`risk_table` x tier x ceiling x static_blast x live_blast x role x env)
  is combinatorially large, so the suite uses **pairwise (all-pairs)**
  generation over the determinate values plus explicit hand-picked corner
  cases (any-`deny` short-circuit, irreversible-quorum, prod downgrade,
  BreakGlass-eligible); each generated row asserts `min()` semantics and
  that no input ever raises autonomy.
- **Overlay precedence + resolved_ceiling** - fixture with all four
  overlay layers active on the same axis; assert the higher-precedence
  layer wins and its name appears under `overlay_layers_applied`.
- **Live-probe fake** - `NoOpBlastProbe` returns each of `quiet /
  active / overloaded`; RiskGate output changes as expected.
- **Executor path selection** - table-driven: ActionType.default vs
  forced_path; strict-order winner asserted.
- **Direct-API idempotency** - the executor's dispatch is called
  twice with the same idempotency key; the substrate adapter records
  exactly one mutation.
- **Idempotency collision** - each key binds to an action fingerprint; changed input conflicts and same-key requests serialize before resource locking.
- **PR-native + PR-manual auto-merge policy** - contract tests over
  the label sets the adapter emits; the label matrix is asserted.
- **RiskDecision cannot upgrade authority** - property test:
  `promotion_state=shadow` on the ActionType → RiskDecision.mode is
  always `shadow` regardless of every other axis.

## 11. Failure modes

- **Probe timeout / error** -> single failure returns `active`, repeated
  failure returns `shadow_only` (§4.2); log `probe.degraded`; do not
  fail-close the whole loop.
- **Overlay load error** (Rego syntax error, missing file overlay
  target) -> **fail toward the safer value, not toward upstream.** If the
  failed overlay was a *tightening* overlay (fork downgraded autonomy),
  the RiskGate keeps the last-known tightened ceiling (fail-closed) rather
  than reverting to the looser upstream default; a loosening overlay that
  fails simply leaves the stricter upstream value in place. Either way it
  writes an `overlay.load_failed` audit and marks `overlay_layers_applied`
  so it never silently pretends the overlay was applied.
- **Executor path unreachable** (direct_api adapter down) -> for a
  low-urgency action, fall back to `pr_manual` and write
  `executor.path.degraded`. For a **latency-critical ops action**
  (`ops.restart-service`, `ops.failover-primary`, anything whose
  ActionType sets `urgency: high`), a `pr_manual` fallback would defeat
  the purpose, so instead the dispatch is enqueued as a **direct HIL
  item** (`mutation_target=direct`) that an on-call approver can accept
  from the console within seconds; the fallback and its reason appear in
  `resolved_ceiling`. The fallback reuses the action's idempotency key
  (§5.4) so no path double-applies.
- **RiskGate itself unavailable** (should not happen - it is a pure
  function of its inputs) -> fail-close: no dispatch, `deny` audit,
  page the operational lane.

## 12. Related docs

- [action-ontology.md](action-ontology.md) - the ActionType schema this
  document consumes and the override seams a fork uses to tune the
  matrix.
- [operator-console.md](../interfaces/operator-console.md) - the RiskGate is the
  verifier the console's chat invariants require on every write-class
  tool call.
- [phase-2-quality-and-t1.md](../phases/phase-2-quality-and-t1.md) - the
  promotion pipeline that flips an ActionType from shadow to
  enforce.
- [risk-classification.md](risk-classification.md) - the authoritative
  first-match auto / HIL / deny table (Axis A, §2.0) that the six-axis
  ceiling combines with via `min()`; it is not replaced by the matrix.
- [security-and-identity.md](../architecture/security-and-identity.md) - the four
  autonomy invariants and the executor identity contract.
- [architecture.instructions.md](../../../.github/instructions/architecture.instructions.md) -
  trust routing, verifier authority.
