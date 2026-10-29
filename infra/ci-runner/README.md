# SSD-backed CI runner

This standalone Terraform root provisions one CI-only Azure VM. It supports repository
validation, not FDAI deployment or managed-resource execution.

## Files

| File | Purpose |
|---|---|
| `main.tf` | Separate resource group, unpeered network, outbound NAT, and VM |
| `cloud-init.yaml.tftpl` | Checked runner download, Linux dependencies, and SSD storage guard |
| `toolchain.json` | Single declared source for packages, libraries, and pinned tools every runner needs |
| `provision-toolchain.sh` | Idempotent root provisioner for new VMs (cloud-init) and existing VMs (Run Command) |
| `verify-toolchain.py` | Fail-closed conformance check run before registration and at the start of each self-hosted regression job |
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
The NIC has one scoped `AZU-0068` scanner exception because Trivy does not recognize this
root's subnet-level NSG association. The subnet NSG and VM creation dependency remain enforced
and covered by a regression test; no inbound rule is opened for the scanner.

The OS disk uses 256 GiB Premium SSD. `/mnt` is the VM's local temporary SSD: it holds the
job workspace, package cache, and tool cache. These contents can disappear after host movement
or deallocation. The runner service checks this mount before starting and never silently falls
back to the OS disk. Runner registration stays on the OS disk.

Use only a VM SKU with a local temporary SSD. A missing `/mnt` mount fails bootstrap.
One VM supports one through five listeners. Adding listeners shares the VM's existing CPU
and memory; it does not add compute capacity or a security boundary between jobs.

Each listener has a separate distribution, workspace, cache, and tool directory. Its systemd
service limits subprocesses to 3 CPUs and 12 GiB RAM, with memory pressure at 10 GiB.
Five listeners need at least 16 CPUs and 62 GiB RAM, including host headroom. Docker daemon
work is outside those service limits; database/container jobs stay on GitHub-hosted runners.
The shared OPA action installs its checksum-pinned binary under each job's `RUNNER_TEMP` and
exports it through `GITHUB_PATH`. It needs no sudo permission and does not race over a shared
`/tmp/opa` file when several listeners run together.

## Keep runners conformant

Add a package, library, or pinned tool to `toolchain.json` only; never to a single VM by hand.
To converge an existing VM, run `provision-toolchain.sh` as root through protected Run Command
with the three toolchain files; it ends with the verifier and exits non-zero on any drift.
The verifier applies the repository's trusted-tool rules: executables must be root-owned and
not group or world writable under `/usr/bin` or `/usr/local/bin`. Registration refuses a drifted
runner, and the regression job fails in seconds instead of midway through the suite.

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
     --vm-name "$APPROVED_CI_VM" \
     --parallelism 5
   ```

The helper keeps the registration token in memory and sends it only as an Azure protected
parameter. It does not print the token or put it in a subprocess argument. Existing idle CI
registrations are preserved when their names, labels, and local repository binding match.
A busy runner or a mismatched registration stops the operation. New slots copy distribution
files only, never registration credentials or mutable state. The helper starts missing services
without stopping or replacing active registrations. Reducing `--parallelism` does not remove extra
slots; removal requires an explicit idle-runner operation. The limit of five is a bounded host
configuration, not a GitHub platform maximum.
After a timeout, inspect Azure and GitHub state before attempting registration again.

## Enable optional CI routing

After the workflow change is published and the runner is independently verified online,
set the repository variable `FDAI_CI_SSD_RUNNER_ENABLED` to `true`. All four protected-main
regression shards use the `fdai-ci,fdai-ci-ssd` labels and three pytest workers each, after a
separate GitHub-hosted job verifies the exact source against protected main. The matrix admits
four jobs at once; a fifth listener can accept a job from another eligible run. All pull requests,
coverage/database jobs, and an unset or disabled variable keep GitHub-hosted execution.
A manual CI run requires the exact
`commit_sha`; SSD execution rejects a SHA different from the workflow run's commit.

The GitHub-hosted regression matrix is skipped only when its guarded SSD replacement is selected;
the required aggregator checks both paths so a failed source verifier cannot silently skip regression.
Setting the variable before publication has no effect on a workflow that does not reference it.
This routing is not
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
