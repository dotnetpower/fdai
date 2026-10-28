variable "subscription_id" {
  type        = string
  description = "Explicitly approved Azure subscription. Supply outside source control."
}

variable "resource_group_name" {
  type = string
}

variable "location" {
  type = string
}

variable "name" {
  type        = string
  description = "Resource name stem for the isolated CI host."
}

variable "ssh_public_key" {
  type = string
}

variable "vm_size" {
  type    = string
  default = "Standard_D16ds_v4"
}

variable "address_space" {
  type    = string
  default = "10.240.0.0/24"
}

variable "runner_version" {
  type    = string
  default = "2.338.2"
}

variable "runner_sha256" {
  type    = string
  default = "baebf204307bac6193480852732f0aba2ae97b6c5597c244f4d5558390147c40"

  validation {
    condition     = can(regex("^[a-f0-9]{64}$", var.runner_sha256))
    error_message = "Supply the official runner archive SHA-256."
  }
}

variable "additional_tags" {
  type    = map(string)
  default = {}
}

variable "egress_ip_tags" {
  type        = map(string)
  default     = {}
  description = "Exact policy-owned IP tags observed on the approved outbound address."
}
