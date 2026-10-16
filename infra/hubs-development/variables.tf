variable "subscription_id" {
  type = string
}
variable "tenant_id" {
  type = string
}
variable "location" {
  type = string
}
variable "prefix" {
  type        = string
  description = "Unique synthetic deployment prefix, also used for globally unique vault and database names."
  validation {
    condition     = can(regex("^[a-z][a-z0-9]{3,10}$", var.prefix))
    error_message = "Use 4-11 lowercase ASCII letters/digits beginning with a letter."
  }
}
variable "operator_object_ids" {
  type = set(string)
  validation {
    condition     = length(var.operator_object_ids) > 0
    error_message = "Explicit operator object IDs are required."
  }
}
variable "operator_cidrs" {
  type = set(string)
  validation {
    condition = length(var.operator_cidrs) > 0 && alltrue([
      for cidr in var.operator_cidrs : can(cidrhost(cidr, 0)) && !endswith(cidr, "/0")
    ])
    error_message = "Provide approved operator source CIDRs; unrestricted ingress is not accepted."
  }
}
variable "database_admin" {
  type = object({ object_id = string, display_name = string })
}
variable "registry" {
  type        = object({ id = string, server = string })
  description = "Existing approved image registry. This root never builds or publishes artifacts."
}
variable "images" {
  type = map(string)
  validation {
    condition = alltrue([
      for kind in ["release", "target"] : can(regex("@sha256:[0-9a-f]{64}$", var.images[kind]))
    ])
    error_message = "Supply independently built and verified digest-pinned release and target images."
  }
}
variable "release_public_key" {
  type        = string
  description = "Independently approved DEVELOPMENT Ed25519 public PEM. Not a production root ceremony."
  validation {
    condition     = startswith(var.release_public_key, "-----BEGIN PUBLIC KEY-----")
    error_message = "Supply a separately verified public key, never a private key."
  }
}
variable "enable_apps" {
  type        = bool
  default     = false
  description = "Enable only after per-Hub DB roles, signing-key secrets and explicit migrations exist."
}
variable "enable_migration_jobs" {
  type        = bool
  default     = false
  description = "Create manual-only migration jobs after private secret and DB-role provisioning."
}
variable "secret_versions" {
  type = map(object({
    signing_key = string
    database    = string
  }))
  default     = {}
  description = "Version IDs only, after independent safe provisioning. Never supply secret values to Terraform."
}
