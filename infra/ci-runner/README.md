# SSD-backed CI runner

This standalone Terraform root provisions one CI-only Azure VM. It supports repository
validation, not FDAI deployment or managed-resource execution.

## Files

| File | Purpose |
|---|---|
| `main.tf` | Separate resource group, unpeered network, outbound NAT, and VM |
| `cloud-init.yaml.tftpl` | Checked runner download, Linux dependencies, and SSD storage guard |
| `register.py` | Short-lived GitHub registration over protected Azure Run Command parameters |

## Isolation and storage

The VM has no public IP, managed identity, deployment role assignment, or deployment-runner
label. Its network denies inbound connections and has no deployment-network peering. The
NAT gateway has an outbound-only public address and adds separate hourly and data charges.
If Azure policy adds IP tags, supply the observed values through `egress_ip_tags` rather
than planning a replacement address to remove them.

The Azure VM agent remains enabled for protected Run Command enrollment and readiness checks.
This management requirement has one documented `CKV_AZURE_50` exception; Terraform does not
provision deployment extensions. Azure control-plane access remains operator-authenticated.

The OS disk uses 256 GiB Premium SSD. `/mnt` is the VM's local temporary SSD: it holds the
job workspace, package cache, and tool cache. These contents can disappear after host movement
or deallocation. The runner service checks this mount before starting and never silently falls
back to the OS disk. Runner registration stays on the OS disk.

Use only a VM SKU with a local temporary SSD. A missing `/mnt` mount fails bootstrap.
One VM runs one listener. Adding more listener processes does not add CPU or isolation.

## Provision and register

1. Select the subscription, location, VM size, and cost explicitly. Keep variable values and
   Terraform state outside source control. Include an existing SSH **public** key; no private
   key or GitHub token belongs in Terraform input or state.
2. Initialize the explicit local backend with
   `terraform -chdir=infra/ci-runner init -backend-config="path=$PRIVATE_STATE_PATH"`,
   then run `terraform validate` and an approved saved plan for this root.
   Apply only the reviewed plan. Existing deployment resources are not part of this state.
   Use the backend setting, not the deprecated plan-only `-state` flag, to keep both reads and
   writes at the private state path.
3. Wait for cloud-init completion and verify `/var/lib/fdai-ci-bootstrap-ready` through Azure
   VM Run Command. A VM provisioning success alone does not prove bootstrap completion.
4. For this public repository, require approval for **all external contributors** in GitHub
   Actions settings before enrollment. This is stronger than first-time-contributor approval.
5. Run the registration helper with the approved coordinates:

   ```bash
   python3 infra/ci-runner/register.py \
     --repository example-owner/example-repository \
     --subscription "$APPROVED_SUBSCRIPTION" \
     --resource-group "$APPROVED_CI_RESOURCE_GROUP" \
     --vm-name "$APPROVED_CI_VM"
   ```

The helper keeps the registration token in memory and sends it only as an Azure protected
parameter. It does not print the token or put it in a subprocess argument. An existing runner
name or local configuration stops registration rather than replacing a possibly active runner.
After a timeout, inspect Azure and GitHub state before attempting registration again.

## Enable optional CI routing

After the workflow change is published and the runner is independently verified online,
set the repository variable `FDAI_CI_SSD_RUNNER_ENABLED` to `true`. Only protected-main
regression shard 4 uses the `fdai-ci,fdai-ci-ssd` labels and eight pytest workers, after a separate
GitHub-hosted job verifies the exact source against protected main. Other shards, all pull requests,
and an unset or disabled variable keep GitHub-hosted execution. A manual CI run requires the exact
`commit_sha`; SSD execution rejects a SHA different from the workflow run's commit.

This limited initial routing avoids serializing all Python shards onto one VM. It is not
automatic capacity fallback: an enabled job waits if its matching runner is unavailable.
Set the variable to `false` before stopping the VM. Already queued jobs retain their selected
runner and need an explicit operator decision; this setting does not migrate them.

Labels and workflow conditions are routing controls, not security boundaries. Public-repository
self-hosting still requires trusted-code review and external-contributor approval. Avoid approving
untrusted workflows that target this runner. A persistent runner is not a disposable per-job VM.
Never add deployment credentials or peer this network to a deployment network.

## Verify and roll back

Verify the Azure VM size, Premium SSD OS disk, local SSD mount, absent managed identity,
absent NIC public IP, bootstrap marker, and GitHub online status. Compare the same CI workload
before and after routing; readiness alone does not prove a speedup.

To roll back, disable the routing variable, wait for the runner to become idle, and remove its
GitHub registration. Deallocation stops compute billing but leaves disk and NAT charges.
Destroying this standalone Terraform root needs separate destructive-action approval.

## Related docs

| To learn about | Read |
|---|---|
| Deployment runner boundary | [Bootstrap runner](../bootstrap/README.md) |
| Resource naming and ownership | [Resource conventions](../../docs/roadmap/deployment/deployment-resource-conventions.md) |
