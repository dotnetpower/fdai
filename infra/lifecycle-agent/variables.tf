variable "subscription_id" { type = string }
variable "tenant_id" { type = string }
variable "location" { type = string }
variable "resource_group_name" { type = string }
variable "prefix" {
  type = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,30}$", var.prefix))
    error_message = "Use a bounded lowercase workload prefix."
  }
}
variable "tags" { type = map(string) }
variable "kubeconfig_path" { type = string }
variable "kubeconfig_context" { type = string }
variable "cluster_oidc_issuer_url" {
  type = string
  validation {
    condition     = startswith(var.cluster_oidc_issuer_url, "https://")
    error_message = "Bind the exact HTTPS AKS OIDC issuer."
  }
}
variable "hub" {
  type = object({
    url             = string
    api_client_id   = string
    agent_role_id   = string
    signing_key_id  = string
    signing_epoch   = number
    public_key_pem  = string
    release_key_pem = string
    config_key_pem  = string
  })
  sensitive = true
  validation {
    condition = (
      startswith(var.hub.url, "https://") &&
      can(regex("^[0-9a-f-]{36}$", var.hub.api_client_id)) &&
      can(regex("^[0-9a-f-]{36}$", var.hub.agent_role_id)) &&
      var.hub.signing_epoch >= 1
    )
    error_message = "Bind one HTTPS Hub, valid API/role identifiers, and a positive key epoch."
  }
}
variable "installation" {
  type = object({
    id                          = string
    target_namespace            = string
    fencing_generation          = number
    local_policy_json           = string
    current_state_json          = string
    native_approval_json        = optional(string)
    installation_public_key_pem = optional(string)
    configuration_artifact = optional(object({
      digest           = string
      payload          = string
      signature_base64 = string
    }))
    agent_namespace       = optional(string, "fdai-agent-system")
    poll_interval_seconds = optional(number, 5)
  })
  sensitive = true
  validation {
    condition = (
      var.installation.fencing_generation >= 1 &&
      var.installation.poll_interval_seconds >= 1 &&
      var.installation.poll_interval_seconds <= 60 &&
      (
        var.installation.configuration_artifact == null ||
        can(regex("^[0-9a-f]{64}$", var.installation.configuration_artifact.digest)) &&
        can(base64decode(var.installation.configuration_artifact.signature_base64)) &&
        length(base64decode(var.installation.configuration_artifact.signature_base64)) == 64
      )
    )
    error_message = "Use a positive fencing generation and a 1-60 second poll interval."
  }
}
variable "agent_image" {
  type = string
  validation {
    condition     = can(regex("@sha256:[0-9a-f]{64}$", var.agent_image))
    error_message = "Lifecycle Agent image must be digest-pinned."
  }
}
variable "storage_class_name" {
  type    = string
  default = "managed-csi"
}
variable "enable_agent" {
  type    = bool
  default = false
}
