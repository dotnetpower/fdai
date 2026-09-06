# Bootstrap layer inputs. Real values live in a gitignored bootstrap.tfvars
# (see bootstrap.tfvars.example). Never bake tenant/subscription values into
# these defaults - the repo stays customer-agnostic.

variable "workload" {
  description = "Workload short name used in every resource name (e.g. fdai)."
  type        = string
  default     = "fdai"
}

variable "env" {
  description = "Environment slug (dev | staging | prod)."
  type        = string
}

variable "region" {
  description = "Azure region for every ops resource (e.g. koreacentral)."
  type        = string
}

variable "region_short" {
  description = "Short region token used in names (e.g. krc)."
  type        = string
}

variable "app_resource_group_name" {
  description = "The app deploy's resource group (rg-<workload>-<env>-<region_short>). The stable deploy UAMI gets Contributor here."
  type        = string
}

variable "ops_address_space" {
  description = "Address space for the ops (hub) VNet. Must NOT overlap the app spoke VNet."
  type        = string
  default     = "10.70.0.0/24"
}

variable "runner_subnet_prefix" {
  description = "Subnet prefix for the runner VM NIC inside the ops VNet."
  type        = string
  default     = "10.70.0.0/26"
}

variable "pe_subnet_prefix" {
  description = "Subnet prefix for the state-storage private endpoint inside the ops VNet."
  type        = string
  default     = "10.70.0.64/26"
}

variable "state_container_name" {
  description = "Blob container that holds the app's terraform state."
  type        = string
  default     = "tfstate"
}

variable "state_storage_account_name" {
  description = "Name of the terraform remote-state storage account. Created OUT OF BAND with `az` (see create-state-account.sh) because a private + key-disabled account cannot complete terraform's data-plane readiness poll from the operator laptop. Terraform references it via data source only."
  type        = string
}

variable "runner_vm_size" {
  description = "Runner VM size. The default provides sustained CPU and a local resource SSD for the ephemeral OS disk."
  type        = string
  default     = "Standard_D4ds_v5"
}

variable "runner_bootstrap_mode" {
  description = "Runner bootstrap source: online preserves marketplace Ubuntu and network cloud-init; offline uses a prebuilt image without cloud-init or GitHub registration."
  type        = string
  default     = "online"

  validation {
    condition     = contains(["online", "offline"], var.runner_bootstrap_mode)
    error_message = "runner_bootstrap_mode must be online or offline."
  }
}

variable "runner_source_image_id" {
  description = "Pinned Azure managed image or gallery image-version resource ID for offline bootstrap. The generalized Linux image must already contain Azure CLI, Terraform, and runner tooling compatible with the ephemeral OS disk. Leave null in online mode."
  type        = string
  default     = null

  validation {
    condition     = var.runner_bootstrap_mode == "offline" ? var.runner_source_image_id != null : var.runner_source_image_id == null
    error_message = "runner_source_image_id is required in offline mode and must be null in online mode."
  }

  validation {
    condition = var.runner_source_image_id == null ? true : (
      can(regex(
        "(?i)^/subscriptions/[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}/resourceGroups/[a-z0-9_().-]+/providers/Microsoft\\.Compute/(images/[a-z0-9_][a-z0-9_.-]*|galleries/[a-z0-9_][a-z0-9_.-]*/images/[a-z0-9_][a-z0-9_.-]*/versions/[0-9]+\\.[0-9]+\\.[0-9]+)$",
        var.runner_source_image_id
      )) &&
      !endswith(lower(var.runner_source_image_id), "/latest")
    )
    error_message = "runner_source_image_id must be a full Azure managed image or numeric gallery image-version resource ID; latest, unversioned galleries, and URLs are not allowed."
  }
}

variable "runner_parallelism" {
  description = "Number of independent GitHub Actions runner slots registered on the runner VM. Slots share the VM managed identity but use separate work directories."
  type        = number
  default     = 1

  validation {
    condition     = var.runner_parallelism >= 1 && var.runner_parallelism <= 5 && floor(var.runner_parallelism) == var.runner_parallelism
    error_message = "runner_parallelism must be an integer from 1 through 5."
  }
}

variable "runner_admin_username" {
  description = "Admin username on the runner VM (SSH is key-only; no public IP)."
  type        = string
  default     = "fdairunner"
}

variable "runner_ssh_public_key" {
  description = "SSH public key for the runner admin user. Required by Azure even though the VM has no public IP (access is via Bastion / run-command / serial console)."
  type        = string
}

variable "create_runner_vm" {
  description = "Create the self-hosted runner VM. Set false to provision only the state backend + networking first."
  type        = bool
  default     = true
}

variable "enable_deploy_identity_roles" {
  description = "Assign the stable deploy UAMI role manifest independently of runner VM creation. Set false only before the app resource group exists."
  type        = bool
  default     = true
}

variable "github_runner_url" {
  description = "GitHub repo URL the self-hosted runner registers against (e.g. https://github.com/<owner>/<repo>). Empty leaves the runner unregistered for manual registration. Must be empty in offline bootstrap mode."
  type        = string
  default     = ""

  validation {
    condition     = var.runner_bootstrap_mode != "offline" || var.github_runner_url == ""
    error_message = "github_runner_url must be empty in offline bootstrap mode."
  }
}

variable "github_runner_token" {
  description = "Short-lived GitHub Actions runner registration token. Leave empty and register manually if you prefer not to pass it through terraform. Must be empty in offline bootstrap mode. NEVER commit a populated value."
  type        = string
  default     = ""
  sensitive   = true

  validation {
    condition     = var.runner_bootstrap_mode != "offline" || var.github_runner_token == ""
    error_message = "github_runner_token must be empty in offline bootstrap mode."
  }
}

variable "additional_tags" {
  description = "Extra tags merged onto every ops resource."
  type        = map(string)
  default     = {}
}

variable "enable_state_lock" {
  description = "Optionally place a CanNotDelete lock on the Terraform state storage account. Standard FDAI profiles keep this false so full teardown remains available."
  type        = bool
  default     = false
}

variable "runner_auto_shutdown_time" {
  description = "Daily auto-shutdown time for a managed-OS runner. The ephemeral runner profile requires this to remain empty because deallocation resets the OS and runner registration."
  type        = string
  default     = ""
}

variable "runner_auto_shutdown_timezone" {
  description = "Timezone for runner_auto_shutdown_time (e.g. 'Korea Standard Time', 'UTC')."
  type        = string
  default     = "UTC"
}

variable "enable_public_egress" {
  description = "Give the runner subnet outbound internet through a NAT gateway and one static public IP. Default true: the self-hosted GitHub runner registers over the internet and terraform reaches management.azure.com and login.microsoftonline.com directly. Set false for a closed network, where the host is a jumpbox rather than a GitHub runner and the tenant supplies its own approved path to the Azure management and identity planes (Private Link or a hub route). Turning it off removes the only outbound path this layer creates; nothing else here substitutes for it."
  type        = bool
  default     = true
}
