# Elastic CI runner (Container Apps Job)

This standalone Terraform root provisions ephemeral, one-job CI runners. A GitHub Actions job
that carries the `fdai-ci-aca` label starts one Container Apps Job execution, which registers a
runner, runs exactly that job, and exits. Executions scale from zero to `max_executions` with the
number of queued jobs, so a burst of pull requests costs one wave of wall time instead of a queue.
It supports repository validation, not FDAI deployment or managed-resource execution.

## Files

| File | Purpose |
|---|---|
| `main.tf` | Resource group, log workspace, registry, pull identity, environment, and the scaled job |
| `Dockerfile` | Runner image built from the shared toolchain manifest in `infra/ci-runner` |
| `entrypoint.sh` | Registers one ephemeral runner and hides the credential from workflow code |
| `build-image.sh` | Builds the image in the registry with a minimal context |
| `set-credential.sh` | Interactive, no-echo entry of the GitHub credential into the job secret |

## Measured basis

Same commit, cold start, heaviest regression shard, `westus3`:

| Runner | Shard 2 test time |
|---|---|
| 16 vCPU VM, 4-5 shards at once (previous pool) | 715-734 s |
| 4 vCPU Container Apps execution, 4 at once | 602-652 s, no queueing |
| 4 vCPU VM, 4 at once | 667-730 s |

An initial eight-shard trial recorded a slowest shard of about 330 s, but used mixed runner sizes
and included test failures. These figures are preliminary timing observations, not passing
throughput or rollout evidence. One image pull for the 750 MB image took about 20 s.

## Isolation and credentials

- No Azure deployment identity. The job has one user-assigned identity with `AcrPull` on this
  registry only; the entrypoint removes its endpoint variables from the workflow process.
- Terraform never holds the GitHub credential. It creates the job secret with the placeholder
  `unset` and ignores later secret changes. Enter the real value with `set-credential.sh`.
- The entrypoint starts as root, exchanges the credential for a one-time registration token, then
  runs the workflow as the unprivileged `runner` user in a clean environment. Workflow code can read
  neither the credential nor the token. Each runner is `--ephemeral`, so no workspace survives.
- Labels and workflow conditions are routing controls, not security boundaries. This runner serves
  protected `main` pushes behind the protected-source guard. Do not route fork pull requests to it.
- Rotate the credential on its expiry by rerunning `set-credential.sh`.
- The image includes `tzdata` and Ubuntu's `tzdata-legacy` aliases, and the shared verifier
  checks required IANA timezone names
  before registration. `tini` is PID 1 and reaps orphaned service children; the runner still
  executes workflow code without root permissions. A completed Actions job and a successful
  container exit are separate outcomes, so verify both before enabling the route.

## Provision

1. Choose the subscription, region, names, and ceiling explicitly. Keep variable values and
   Terraform state outside source control; the `registry_name` must be globally unique.
2. `terraform -chdir=infra/ci-runner-aca init -backend-config="path=$PRIVATE_STATE_PATH"`.
3. Create the group and registry first, then build and tag the image:

   ```bash
   terraform -chdir=infra/ci-runner-aca apply \
     -var-file="$PRIVATE_VARS" -target=azurerm_resource_group.ci -target=azurerm_container_registry.ci
   bash infra/ci-runner-aca/build-image.sh "$REGISTRY_NAME" "$IMAGE_TAG"
   ```

4. Set `runner_image` to `fdai-ci-runner:$IMAGE_TAG` (never `latest`), then plan and apply the
   rest from a reviewed saved plan.
5. Run `bash infra/ci-runner-aca/set-credential.sh "$RESOURCE_GROUP" "$JOB_NAME"` yourself.
6. After the first scaled execution registers and passes, set the repository variable
   `FDAI_CI_ELASTIC_RUNNER_ENABLED` to `true`. It takes precedence over
   `FDAI_CI_SSD_RUNNER_ENABLED`; pull requests keep GitHub-hosted execution.

## Roll back

Set `FDAI_CI_ELASTIC_RUNNER_ENABLED` to `false`; routing falls back to the SSD pool or hosted
runners for new runs. Queued jobs keep their selected label and need an explicit decision.
Rebuild the image with `build-image.sh` and a new tag whenever `infra/ci-runner/toolchain.json`
changes. Destroying this root needs separate destructive-action approval.

## Complete the no-hosted-runner cutover

The current implementation routes only protected-main regression shards to the optional elastic
pool. Other jobs and pull requests still select hosted runners. Infrastructure creation and manual
container benchmarks do not establish a completed GitHub-runner rollout.

Use three separate capabilities rather than sending every job to Container Apps:

| Pool | Jobs | Admission and verification |
|---|---|---|
| Trusted self-hosted control | Change scope, source verification, required aggregator | Protected controls run before candidate code; no deployment credentials |
| Ephemeral Container Apps | Non-Docker pytest and static checks | One registered runner per job, approved exact source, bounded concurrency |
| Isolated ephemeral VM | Database service containers and Docker-dependent jobs | No deployment identity or network peering; one job per disposable environment |

Preserve required checks for untrusted fork PRs. Do not silently skip them or run unreviewed code
on the trusted control pool. A safe admission design and the operator-entered credential are
prerequisites, not reasons to weaken source verification.

Before changing routing or shrinking the existing VM:

1. Run `scripts/quality/ci/check-runner-cutover.py` with the current workflow and a complete
   runner inventory. Remaining hosted jobs and missing pools keep the result unavailable.
2. Verify a real GitHub job registers and succeeds on the selected exact source and image.
   Record the runner capabilities, test count, configured ceiling, and expected stop condition.
3. Use a bounded burst of 1, 4, then 8 jobs. Record scheduling delay, initialization, execution,
   failures, and slot usage separately. Stop on failure or deadline; a faster failed run is not
   performance evidence.
4. Observe ephemeral deregistration and zero idle executions after the queue drains. Check quota
   and costs independently; do not assume queue length overrides the configured ceiling.
5. Keep the existing pool until the no-hosted inventory, safe PR admission, successful jobs,
   scale-out, and scale-in have all been observed. Then drain it before reducing capacity.

The cutover checker reads no credential values and makes no routing, scaling, or approval changes.
Its report is a prerequisite inventory, not installation authority or proof of the complete
operational lifecycle.

## Related docs

| To learn about | Read |
|---|---|
| Shared toolchain manifest and VM runner | [SSD-backed CI runner](../ci-runner/README.md) |
| Resource naming and ownership | [Resource conventions](../../docs/roadmap/deployment/deployment-resource-conventions.md) |
