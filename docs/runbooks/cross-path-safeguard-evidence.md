---
title: Cross-Path Safeguard Evidence Runbook
---
# Cross-Path Safeguard Evidence Runbook

Retain governed safeguard and independent effect evidence for every registered execution path on
one pinned revision, so FDAI-CONST-007 can be reconciled without treating dispatch as success.

This runbook describes a campaign that **has not run**. The repository currently ships the
contract, the matrix, the observation machinery, and a plan-only workflow. Producing live evidence
is a separate, separately approved activity.

## Authority boundary

Reading this runbook authorizes nothing. Each of the following requires explicit current human
approval at the time it happens:

- selecting the pinned revision,
- pushing that revision and running required CI,
- any protected deployment of Core or the isolated Executor,
- any live effect on any managed resource, pull request, or issue,
- any promotion, registry mutation, or traceability status change.

The approver must be a different principal from the initiator. Silence never grants authority.

## Evidence boundary

- Dispatch, broker acceptance, and a provider receipt are **not** operational success.
- An observation whose evidence is missing, stale, conflicting, censored, or unavailable is an
  unknown hold. It authorizes no retry, no new effect, no lock release, and no promotion.
- Synthetic evidence is not live evidence. The contract sets `allow_synthetic_evidence` to
  `false`, and the verifier rejects any synthetic receipt.
- A campaign may only claim `live_execution` after a protected deployment of the pinned revision
  and retained independent observations for every eligible cell.

## The predeclared matrix

[`config/cross-path-safeguard-evidence.json`](../../config/cross-path-safeguard-evidence.json)
declares all sixteen cells: four execution paths, two orchestration origins, and two execution
venues. Eight are eligible and eight are structurally denied.

| Cell group | Eligibility | Why |
|---|---|---|
| `pr_native` and `tool_call` in the Core venue | eligible | Core owns the PR publisher and the tool router. |
| `direct_api` in either venue | eligible | Core and the isolated Executor can each own the provider dispatch. |
| any `pr_manual` cell | structurally denied | No shipped ActionType declares `pr_manual`, and `resolve_ceiling` derives the final path from the ActionType alone, so `strictest_execution_path` has no production caller to narrow a path onto it. |
| `pr_native` and `tool_call` in the isolated venue | structurally denied | The isolated Executor refuses any command whose path is not `direct_api`. |

A structurally denied cell is recorded with its reason and its evidence. It is never quietly
dropped, and it is never made eligible by inventing a producer.

### Venue exclusivity

`enable_isolated_executor_authority_cutover` moves gateway caller authority and the vertical
execution identities from Core to the isolated Executor. One deployed configuration therefore
cannot host both `direct_api` venues. Covering both cells requires two protected applies of the
**same** pinned revision, not two revisions.

## Safe ActionTypes and reversal

| Path | ActionType | Effect | Reversal | Independent observer |
|---|---|---|---|---|
| `direct_api` | `ops.start-vm@1.0.0` | One pre-existing non-production VM reaches `running` | `ops.deallocate-vm@1.0.0` | Azure VM power state read through an identity that never calls the mutation gateway |
| `pr_native` | `ops.publish-change-summary@1.0.0` | One pull request in a dedicated non-production evidence repository | close the pull request, or `pr_revert` | GitHub pull-request state through a read-only token distinct from the GitOps writer |
| `tool_call` | `tool.open-incident-ticket@1.0.0` | One issue in the same evidence repository | close the issue | GitHub issue state through the same read-only token |

The impact limit is one resource per cell. Never target this repository.

## Rollout order

Core first, then the isolated Executor, both pinned to the same commit.

1. Land the campaign revision on protected `main` and confirm the `required` check is green.
2. Build attested images for that exact commit through `container-supply-chain`.
3. Plan, then apply, `core-control-plane` through `service-deploy` with the cutover disabled.
   Run the Core-venue lanes.
4. Plan, then apply, `isolated-executor` through `service-deploy` at the same `commit_sha`.
5. Apply the authority cutover through `deploy-dev`, run the isolated-venue `direct_api` lane,
   then restore the previous cutover value and verify the restoration.
6. Assemble and verify the bundle, then request independent review.

## Running the plan-only lane today

```bash
uv run python scripts/quality/repository/validate-cross-path-safeguard-evidence.py
```

The `cross-path-safeguard-evidence` workflow runs the same verifier against an exact
protected-`main` revision, retains the validation receipt for 90 days, and refuses any `apply`
request because effect execution is not implemented.

## Assembling a bundle

```bash
uv run python scripts/quality/repository/build-cross-path-safeguard-evidence-bundle.py \
  --receipt-dir .fdai/evidence/cross-path-safeguard/ \
  --output .fdai/evidence/cross-path-safeguard-live.json \
  --campaign-id "<campaign id>" \
  --base-revision "<40-character commit>"

uv run python scripts/quality/repository/validate-cross-path-safeguard-evidence.py \
  --bundle .fdai/evidence/cross-path-safeguard-live.json
```

The builder writes a bundle once and refuses duplicate keys, unexpected or missing receipt kinds,
non-finite numbers, and any receipt pinned to another revision. The verifier then requires an
independent observation for every eligible cell and an exercised receipt for every denial class.

## Remaining work

The contract lists these as residuals, and they stay listed until each one is genuinely closed:

- no pinned revision has been selected;
- no protected deployment has been performed;
- independent observation is not yet wired into the dispatch lifecycle, so a campaign cannot yet
  emit observation receipts automatically;
- `pr_manual` has no reachable runtime trigger;
- the `tool_call` enforce binding has no Terraform variable;
- no independent review has been performed.

FDAI-CONST-007 stays `partial` until every one of these is closed and an independent review has no
unresolved Medium-or-higher finding.
