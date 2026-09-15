variable "workload" {
  description = "Stable workload token used in resource names."
  type        = string
  default     = "fdai"
}

variable "location" {
  description = "Azure region for the AKS cluster."
  type        = string
}

variable "resource_group_name" {
  description = "Existing application resource group."
  type        = string
}

variable "aks_subnet_id" {
  description = "Existing subnet dedicated to AKS nodes."
  type        = string
}

variable "container_registry_id" {
  description = "Existing ACR resource id granted to the kubelet identity."
  type        = string
}

variable "log_analytics_workspace_id" {
  description = "Existing Log Analytics workspace resource id."
  type        = string
}

variable "managed_host_principal_id" {
  description = "Object id of the approved managed deployment host identity."
  type        = string
}

variable "environment" {
  description = "Deployment environment, independent of runtime authority."
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be dev, staging, or prod."
  }
}

variable "region_short" {
  description = "Stable short region token used in resource names."
  type        = string
}

variable "database_placement" {
  description = "PostgreSQL placement selected by the sealed runtime profile."
  type        = string
  default     = "postgres-flex"

  validation {
    condition     = contains(["postgres-flex", "postgres-aks"], var.database_placement)
    error_message = "database_placement must be postgres-flex or postgres-aks."
  }
}

variable "system_node_count" {
  description = "Fixed system-pool node count."
  type        = number
  default     = 3

  validation {
    condition     = var.system_node_count >= 2 && var.system_node_count <= 100
    error_message = "system_node_count must be in [2, 100]."
  }
}

variable "system_node_sku" {
  description = "System-pool Azure VM SKU."
  type        = string
  default     = "Standard_D4as_v5"
}

variable "user_node_min_count" {
  description = "Autoscaled user-pool minimum node count."
  type        = number
  default     = 3

  validation {
    condition     = var.user_node_min_count >= 3 && var.user_node_min_count <= 100
    error_message = "user_node_min_count must be in [3, 100]."
  }
}

variable "user_node_max_count" {
  description = "Autoscaled user-pool maximum node count."
  type        = number
  default     = 5

  validation {
    condition     = var.user_node_max_count >= var.user_node_min_count && var.user_node_max_count <= 100
    error_message = "user_node_max_count must cover the minimum and be at most 100."
  }
}

variable "user_node_sku" {
  description = "User-pool Azure VM SKU."
  type        = string
  default     = "Standard_D4as_v5"
}

variable "availability_zones" {
  description = "Availability zones used by both node pools."
  type        = list(string)
  default     = ["1", "2", "3"]

  validation {
    condition = (
      length(var.availability_zones) >= 2 &&
      length(var.availability_zones) == length(distinct(var.availability_zones)) &&
      alltrue([for zone in var.availability_zones : contains(["1", "2", "3"], zone)])
    )
    error_message = "availability_zones must contain at least two unique values from 1, 2, and 3."
  }
}

variable "tags" {
  description = "Deployment-supplied generic resource tags."
  type        = map(string)
  default     = {}
}

check "production_system_pool_floor" {
  assert {
    condition     = var.environment != "prod" || var.system_node_count >= 3
    error_message = "Production AKS requires at least three system nodes."
  }
}

check "in_cluster_postgres_user_pool_floor" {
  assert {
    condition     = var.database_placement != "postgres-aks" || var.user_node_min_count >= 4
    error_message = "postgres-aks requires at least four user nodes."
  }
}

check "in_cluster_postgres_is_non_production" {
  assert {
    condition     = var.environment != "prod" || var.database_placement == "postgres-flex"
    error_message = "Production keeps PostgreSQL Flexible Server until in-cluster HA is validated."
  }
}
