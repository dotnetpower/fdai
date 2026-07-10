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
  description = "The app deploy's resource group (rg-<workload>-<env>-<region_short>). The runner MI gets Contributor here."
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
  description = "Runner VM size. B-series is enough for terraform + a self-hosted runner."
  type        = string
  default     = "Standard_B2s"
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

variable "github_runner_url" {
  description = "GitHub repo URL the self-hosted runner registers against (e.g. https://github.com/<owner>/<repo>). Empty leaves the runner unregistered for manual registration."
  type        = string
  default     = ""
}

variable "github_runner_token" {
  description = "Short-lived GitHub Actions runner registration token. Leave empty and register manually if you prefer not to pass it through terraform. NEVER commit a populated value."
  type        = string
  default     = ""
  sensitive   = true
}

variable "additional_tags" {
  description = "Extra tags merged onto every ops resource."
  type        = map(string)
  default     = {}
}

variable "enable_state_lock" {
  description = "Place a CanNotDelete lock on the terraform state storage account so it cannot be accidentally deleted (losing all remote state). Default false for dev tear-down ease; set true for shared/prod ops layers."
  type        = bool
  default     = false
}
