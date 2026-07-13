variable "name" {
  description = "VNet name, e.g. vnet-fdai-dev-krc."
  type        = string
}

variable "location" {
  type = string
}

variable "resource_group_name" {
  type = string
}

variable "address_space" {
  description = "VNet CIDR. /22 gives room for the PE subnet plus the Container Apps /23 infra subnet."
  type        = string
  default     = "10.60.0.0/22"
}

variable "pe_subnet_prefix" {
  description = "Private-endpoint subnet CIDR (must fit inside address_space)."
  type        = string
  default     = "10.60.0.0/24"
}

variable "infra_subnet_prefix" {
  description = "Container App Environment infrastructure subnet CIDR. MUST be >= /23 for a Consumption environment."
  type        = string
  default     = "10.60.2.0/23"
}

variable "postgres_subnet_prefix" {
  description = "PostgreSQL Flexible Server delegated subnet CIDR (must fit inside address_space)."
  type        = string
  default     = "10.60.1.0/24"
}

variable "tags" {
  type    = map(string)
  default = {}
}
