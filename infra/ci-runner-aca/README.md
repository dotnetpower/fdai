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

An eight-shard split cut the slowest shard from 667 s to about 330 s at the same total compute.
Cold start is about 20 s plus a 20 s image pull for this 750 MB image.

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

## Related docs

| To learn about | Read |
|---|---|
| Shared toolchain manifest and VM runner | [SSD-backed CI runner](../ci-runner/README.md) |
| Resource naming and ownership | [Resource conventions](../../docs/roadmap/deployment/deployment-resource-conventions.md) |
