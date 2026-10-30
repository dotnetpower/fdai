# Isolated runner controller infrastructure

This Terraform root separates the GitHub credential-owning controller from disposable CI workers.
The controller manages capacity and registration; it never executes repository builds.

## Files

| File | Purpose |
|---|---|
| `main.tf`, `controller.tf`, `jobs.tf` | Separate resource groups, environments and logs; private state container; one AzAPI controller; two AzureRM Manual Jobs. |
| `identity.tf` | Exact Job dispatch, container-only state access, registry pull, and optional VM permissions. |
| `variables.tf`, `outputs.tf` | Deployment inputs and nonsecret runtime/output contracts. |
| `Dockerfile`, `Dockerfile.dockerignore`, `build-controller-image.sh` | Minimal repository-root build context with a required Python 3.13 slim digest. No image push. |
| `set-controller-credential.py` | Hidden terminal input and controller-only secret PATCH. |
| `build-vm-image.py`, `provision-vm-image.sh` | Exact-commit image preparation and explicit new-builder capture, without registration credentials. |
| `tests/plan.tftest.hcl` | Mocked plans without Azure authentication or effects. |

## Inputs and outputs

Supply these required inputs outside source control:

```text
subscription_id
location
resource_group_name
worker_resource_group_name
name
registry_id
registry_server
controller_image
worker_image
github_repository
storage_account_name
```

Both resource groups are new, dedicated ownership boundaries. The existing registry is referenced,
not duplicated. Both image inputs are complete `registry/repository@sha256:<digest>` references.
Confirm that the registry resource ID and login server identify the same registry.

Optional inputs:

| Input | Default and meaning |
|---|---|
| `storage_blob` | `controller-state.json` |
| `controller_base_url` | Empty; runtime uses `https://CONTAINER_APP_HOSTNAME`. An explicit value is an HTTPS origin. |
| `vm_image_id` | Empty; Docker workers are explicitly unavailable. Accepts only an exact Azure Compute Gallery version; managed images and `latest` are unsupported. |
| `vm_subnet_id`, `ssh_public_key` | Empty while Docker is unavailable. Enabling Docker requires an existing unpeered CI subnet and a public SSH key. |
| `vm_size` | `Standard_D4ds_v4`; the four-vCPU alternatives are `Standard_D4s_v5`, `Standard_D4as_v5`, and `Standard_D4ads_v5`. Check quota and capacity before enabling up to 16 VM workers. |
| `replica_timeout_seconds` | Fixed `86400`; a 24-hour platform ceiling, not a drain timer. The runtime rotates old idle workers only after a replacement is ready; CI jobs remain bounded to six hours. |
| `controller_apply` | `false`; dispatch stays disabled until independently approved activation. |
| `additional_tags` | Empty map; fixed ownership tags take precedence. |

Use an owner-only durable backend path on encrypted local storage with
`terraform init -backend-config=path=<private-state-path>`. Keep this state separate from legacy
runner, application and deployment state. Terraform's local backend does not encrypt its file.
The controller's runtime lease/state uses an Entra-only private Blob container with
platform-managed double encryption, zone-redundant storage and Blob read/write/delete diagnostics.
There is no shared build workspace or state volume.

Outputs are `controller_resource_id`, `controller_url`, `controller_identity_client_id`,
`worker_resource_group_name`, `jobs`, `controller_config`, `worker_name_prefix`, and
`activation_requirements`. An output URL is not evidence of deployment success.

## Runtime contract

`CONFIG_JSON` and `controller_config` contain exactly these fields:

```text
repository, name_prefix, subscription_id, resource_group, jobs,
storage_url, storage_container, storage_blob, worker_image,
controller_url, location, vm_subnet_id, vm_image_id, vm_size,
ssh_public_key, cpu_budgets
```

`resource_group` is the worker group. `jobs` maps `control` and `general` to their exact Manual Job
names. `name_prefix` is `<name>-worker`. `cpu_budgets` is
`{"container_cpu":260,"vm_cpu":64}`. The image includes `config/ci-runner-pools.json`; no external
policy mount is configured.

The controller receives `GITHUB_REPOSITORY`, `CONFIG_JSON`, `GITHUB_RUNNER_CREDENTIAL`,
`GITHUB_WEBHOOK_SECRET`, `AZURE_CLIENT_ID`, and `FDAI_RUNNER_CONTROLLER_APPLY` (`0` by default).
The platform supplies the hostname and managed-identity endpoint. The service listens on port 8080.
Treat `unset` credential placeholders as unavailable, including for webhook verification.

Each Manual Job starts `/usr/bin/python3 /opt/fdai-ci/broker-entrypoint.py` from the exact worker
digest. It has no PAT secret, scaler, state access or management role. The controller supplies an
HTTPS bootstrap URL and a one-use ticket per execution. Those transient values are not stored in
Terraform. VM creation and root-only custom-data bootstrap belong to the controller runtime, not
this Terraform state. VM requests use no managed identity or public IP.

## Credentials and activation

The controller uses pinned `Azure/azapi` 2.13.0, not `azurerm_container_app`. AzureRM's
[Container App Read implementation](https://github.com/hashicorp/terraform-provider-azurerm/blob/main/internal/services/containerapps/resources/container_app/r_read.go)
calls `ListSecrets` and flattens returned values into state even with `ignore_changes`.
The pinned [AzAPI resource implementation](https://github.com/Azure/terraform-provider-azapi/blob/v2.13.0/internal/services/azapi_resource.go)
refreshes through generic ARM GET, without that action. The
[2024-03-01 Container App schema](https://learn.microsoft.com/en-us/azure/templates/microsoft.app/2024-03-01/containerapps)
defines the body; only the nonsecret ingress FQDN is exported.

Terraform seeds `unset` placeholders at creation and ignores
`body.properties.configuration.secrets` during planning. Because ARM `PUT` rejects `GET`-redacted
secret stubs that omit `value`, `ignore_body_changes` is not used on `secrets`; re-run the
credential setter and restart the controller revision after a controller `PUT` update. No actual
PAT/HMAC is a Terraform input, output or state value. Generic GET refresh does not recover secret
values.
This fixes the new root; it does not scrub historical states or backups from an older AzureRM
deployment. Any such migration and credential rotation needs separate approval.

Run the credential setter from a real terminal:

```bash
python infra/ci-runner-controller/set-controller-credential.py \
  --controller-resource-id "$CONTROLLER_RESOURCE_ID" --prompt-webhook-key
```

Enter the PAT and an independently configured webhook key directly at the hidden prompts.
Use `--disable-webhook` instead for polling-only operation. This explicitly replaces the webhook
key with the unavailable placeholder. `--generate-webhook-key` creates a key in memory without
printing it; the setter does not create a GitHub webhook or disclose a key for manual installation.
The fine-grained PAT needs Administration read/write and Actions read; Webhooks read/write is
optional only for separately supported, explicitly selected controller-managed webhook setup.
An existing manually configured webhook and polling-only operation don't need that PAT permission.
A supplied webhook key needs at least 32 characters.
Generation keeps the key in memory and does not display a value to copy elsewhere.

The setter obtains an Azure CLI access token in memory, PATCHes only the named controller app,
refuses redirects and environment proxies, and prints only `controller_credentials_stored` on
success. It never reads existing worker credentials or lists app secrets. Restart the controller
revision separately after secret changes. Secret storage is not service readiness.

Before setting `controller_apply=true`, verify exclusive ownership against the legacy scaler,
separate environments, running digests, exact role assignments and independent Blob/worker
readback. AzureRM does not expose registry-only `identitySettings` with lifecycle `None`; the worker
identity has only registry-scoped `AcrPull`, but its runtime endpoint restriction still needs
platform-specific verification before activation. Do not assign the controller identity to workers.

When Docker inputs are complete, the controller receives VM/NIC/disk lifecycle permissions in the
worker group, join permission on the one subnet, and read permission on the one baked image. It has
no VM Run Command, extension, role-assignment or managed-identity-assignment permission. Drain waits
for natural completion. Delete only recorded, prefix-owned VM/NIC resources after both the terminal
worker callback and independent GitHub job-terminal/runner-absent evidence.

## Build the baked VM image

Publish the approved source commit and complete its required CI before an image build. Select an
exact Ubuntu 24.04 Gallery version ARM ID or versioned marketplace URN; managed images and
`latest` are not accepted. The driver
reads the committed source with `git show`, not a dirty checkout or a credential-bearing archive.

The following command prepares root-owned cloud-init locally and makes no Azure request:

```bash
python infra/ci-runner-controller/build-vm-image.py \
  --subscription-id "$SUBSCRIPTION_ID" \
  --resource-group "$CI_RESOURCE_GROUP" --location "$LOCATION" \
  --subnet-id "$CI_SUBNET_ID" --source-sha "$PUBLISHED_CI_GREEN_SHA" \
  --base-image-id "$EXACT_UBUNTU_IMAGE_ID_OR_URN" \
  --builder-name "$NEW_BUILDER_VM_NAME" --nic-name "$NEW_BUILDER_NIC_NAME" \
  --disk-name "$NEW_BUILDER_DISK_NAME" --gallery-name "$CI_GALLERY_NAME" \
  --image-definition "$TRUSTED_LAUNCH_IMAGE_DEFINITION" --image-version "$EXACT_X_Y_Z_VERSION" \
  --ssh-public-key-file "$SSH_PUBLIC_KEY_FILE" \
  --state-dir ".fdai/image-prepare-$PUBLISHED_CI_GREEN_SHA"
```

For an explicitly approved build, append `--execute` and select a different new private
`--state-dir`. Preparation claims its directory; reusing an existing attempt is not supported.
The driver refuses existing named builder resources or an existing target image version. It creates
a private NIC and identity-free Trusted Launch VM with Secure Boot and vTPM enabled in the
existing CI subnet and verifies their ownership, security settings and network references.
It creates a private Gallery and image definition when absent; existing definitions are read-only
and need Linux, x64, Generalized, V2, and exactly `SecurityType=TrustedLaunch`.
The operator needs Gallery/image
creation and builder-only Run Command permission. Neither permission is added to the controller.

The clean builder reuses the shared toolchain, verifies the pinned runner archive checksum,
creates `runner` with Docker access and `/opt/hostedtoolcache`, and installs the root-owned broker
at `/opt/fdai-ci/broker-entrypoint.py`. The runner lives at `/opt/actions-runner` with home
`/home/runner`. The listener bundles its action JavaScript runtime; workflows select Node/npm with
`setup-node`. Both `tzdata` and `tzdata-legacy` are installed before verification, including
`America/Buenos_Aires`. No GitHub registration, bootstrap ticket, Azure login or private SSH key is baked.

After cloud-init and toolchain readiness, the driver cleans cloud-init, deprovisions the builder
user, deallocates and generalizes only its new VM, and creates a Gallery image version directly
from that VM. It requests full replication to the source region, excludes the version from
`latest`, and verifies completed replication, the exact source VM, and the generalized Trusted
Launch definition before deleting only its builder VM/NIC/disk. Gallery resources remain intact.
Failures and ambiguous timeouts stop without retry or speculative deletion. Keep the private
attempt directory and diagnose any remaining named builder resources before a new attempt.
Commands have stage deadlines and a two-hour total deadline.

Tag arguments follow each command's parser, not one universal encoding. `az sig create` and
`az network nic create` receive one JSON object argument so colon-bearing keys such as
`fdai:source-sha` stay quoted. `az sig image-definition create`, `az sig image-version create`,
`az vm create`, and `az tag update` receive separate `key=value` arguments through their legacy
tag validator. Passing the JSON form to those legacy validators creates the wrong tag key.
The focused infrastructure tests check all six operations semantically and exercise the installed
Azure CLI tag actions/validators with HTTP and socket transports blocked, synthetic identity
metadata, and isolated local CLI configuration. They do not execute an Azure operation or read an
operator token. A parser pass is not evidence that a Gallery, image or VM was created.

Set Terraform `vm_image_id` to the returned `image_id`, and supply the approved CI subnet and
public SSH key in a new plan. Image capture and builder cleanup don't prove that a Docker worker
successfully bootstrapped or completed a GitHub job; verify that separately before activation.

Microsoft documents [managed images as unsupported for Trusted Launch](https://learn.microsoft.com/en-us/azure/virtual-machines/trusted-launch#unsupported-features).
For a [Trusted Launch VM capture](https://learn.microsoft.com/en-us/azure/virtual-machines/trusted-launch-portal#trusted-launch-vm-images),
the definition uses `SecurityType=TrustedLaunch`, not `TrustedLaunchSupported`, which is for Gen2
sources without VM Guest State. The [Gallery image-version procedure](https://learn.microsoft.com/en-us/azure/virtual-machines/image-version)
supports capturing the generalized VM directly without a managed-image intermediate.

## Validation

With the existing local toolchain and initialized provider, run:

```bash
terraform -chdir=infra/ci-runner-controller fmt -check -recursive
terraform -chdir=infra/ci-runner-controller validate
terraform -chdir=infra/ci-runner-controller test
uv run --no-sync pytest -q --no-cov tests/integration/infra/test_runner_controller_infra.py \
  --basetemp=infra/ci-runner-controller/.pytest-runtime
shellcheck infra/ci-runner-controller/{build-controller-image,provision-vm-image}.sh
```

Security exceptions are resource-local and explained beside the affected resource. Blob HTTPS
remains public but requires Entra authorization; private endpoints need a separate trusted
controller network. Zone replication and platform-managed keys are explicit choices. Blob service
diagnostics replace unused legacy queue logging. Trivy should exclude `**/*.dockerignore` because
its filename detector otherwise mistakes Docker ignore metadata for a Dockerfile.

These are local contract checks, not evidence that images were built, credentials were supplied,
Azure resources were deployed, worker identity endpoints were restricted, or jobs completed.

## Related docs

| To learn about | Read |
|---|---|
| Existing worker image and shared toolchain | [Container Apps worker](../ci-runner-aca/README.md) |
| Existing CI subnet and VM bootstrap conventions | [VM runner](../ci-runner/README.md) |
