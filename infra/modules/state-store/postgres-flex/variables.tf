variable "name" {
  description = "Postgres Flexible Server name (CAF: psql-<workload>[-env][-region])."
  type        = string
}

variable "location" {
  description = "Azure region."
  type        = string
}

variable "resource_group_name" {
  description = "Enclosing resource group."
  type        = string
}

variable "tenant_id" {
  description = "Entra tenant id for AAD authentication."
  type        = string
}

variable "administrator_login" {
  description = "Bootstrap admin login (rotate to AAD auth once running)."
  type        = string
  sensitive   = true
}

variable "administrator_password" {
  description = "Bootstrap admin password."
  type        = string
  sensitive   = true
}

variable "database_name" {
  description = "Application database name."
  type        = string
}

variable "sku_name" {
  description = "Postgres SKU. Day-zero: B_Standard_B1ms (Burstable). Scale up when measurement shows a need."
  type        = string
  default     = "B_Standard_B1ms"
}

variable "storage_mb" {
  description = "Storage in MB. 32768 = 32 GB (Burstable minimum)."
  type        = number
  default     = 32768
}

variable "postgres_version" {
  description = "Postgres major version. pgvector is available on 16."
  type        = string
  default     = "16"
}

variable "tags" {
  description = "Tags."
  type        = map(string)
  default     = {}
}

variable "allow_azure_services_firewall" {
  description = <<-EOT
    When true, install a firewall rule that lets Microsoft-owned outbound IPs
    reach the public server. Private endpoint and delegated-subnet deployments
    keep this false.
  EOT
  type        = bool
  default     = true
}

# ---------------------------------------------------------------------------
# Network + backup posture knobs. Defaults preserve day-zero connectivity;
# flip these once a private endpoint or VNet integration is in place.
# ---------------------------------------------------------------------------
variable "public_network_access_enabled" {
  description = "When false, Postgres refuses public-plane connections. Use a delegated subnet or approved private endpoint and private DNS."
  type        = bool
  default     = true
}

variable "delegated_subnet_id" {
  description = "Delegated subnet for private PostgreSQL access. Null keeps the public day-zero path."
  type        = string
  default     = null
  nullable    = true
}

variable "private_dns_zone_id" {
  description = "Private DNS zone ending in postgres.database.azure.com. Null keeps the public day-zero path."
  type        = string
  default     = null
  nullable    = true
}

variable "backup_retention_days" {
  description = "Postgres Flexible Server backup retention in days. 7-35 range enforced by Azure."
  type        = number
  default     = 7

  validation {
    condition     = var.backup_retention_days >= 7 && var.backup_retention_days <= 35
    error_message = "backup_retention_days must be between 7 and 35."
  }
}

variable "geo_redundant_backup_enabled" {
  description = "Enable geo-redundant backup (paired region). Adds cost; prod default should typically be true once RTO/RPO SLO is signed off."
  type        = bool
  default     = false
}

variable "high_availability_mode" {
  description = "PostgreSQL Flexible HA mode: Disabled, SameZone, or ZoneRedundant."
  type        = string
  default     = "Disabled"

  validation {
    condition     = contains(["Disabled", "SameZone", "ZoneRedundant"], var.high_availability_mode)
    error_message = "high_availability_mode must be Disabled, SameZone, or ZoneRedundant."
  }
}
