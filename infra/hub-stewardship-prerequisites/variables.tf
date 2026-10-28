variable "location" {
  type = string
}

variable "resource_group_name" {
  type = string
}

variable "acr_name" {
  type = string
}

variable "key_vault_name" {
  type = string
}

variable "state_store_dsn_secret_name" {
  type    = string
  default = "fdai-state-store-dsn"
}

variable "eventhub_namespace_name" {
  type = string
}

variable "log_analytics_workspace_name" {
  type = string
}

variable "vnet_name" {
  type = string
}

variable "private_endpoint_subnet_name" {
  type    = string
  default = "snet-pe"
}

variable "ops_resource_group_name" {
  type = string
}

variable "ops_vnet_name" {
  type = string
}

variable "aks_name" {
  type = string
}

variable "kubeconfig_path" {
  description = "Private kubeconfig used only for the reviewed prerequisite objects."
  type        = string
  sensitive   = true
}

variable "kubeconfig_context" {
  description = "Exact kubeconfig context for the reviewed AKS target."
  type        = string
}

variable "namespace" {
  type    = string
  default = "fdai-runtime"

  validation {
    condition     = can(regex("^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$", var.namespace))
    error_message = "namespace must be one Kubernetes DNS label."
  }
}

variable "tenant_id" {
  description = "Microsoft Entra tenant used for AKS workload identity."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-fA-F-]{36}$", var.tenant_id))
    error_message = "tenant_id must be a GUID."
  }
}

variable "identity_names" {
  description = "Deployment-owned names for the six prerequisite user-assigned managed identities."
  type = object({
    ingestion    = string
    worker       = string
    migration    = string
    notification = string
    operator_api = string
    command      = string
  })

  validation {
    condition = alltrue([
      for name in values(var.identity_names) :
      can(regex("^[A-Za-z0-9_-]{3,128}$", name))
    ]) && length(toset(values(var.identity_names))) == 6
    error_message = "identity_names must contain six distinct valid managed identity names."
  }
}

variable "document_storage_name" {
  type = string

  validation {
    condition     = can(regex("^[a-z0-9]{3,24}$", var.document_storage_name))
    error_message = "document_storage_name MUST be a valid Storage account name."
  }
}

variable "document_intelligence_name" {
  type = string
}

variable "document_blob_private_endpoint_name" {
  type = string
}

variable "document_dfs_private_endpoint_name" {
  type = string
}

variable "document_intelligence_private_endpoint_name" {
  type = string
}

variable "communication_service_name" {
  type = string
}

variable "email_communication_service_name" {
  type = string
}

variable "deployer_principal_id" {
  type = string
}

variable "config_map_data" {
  description = "Exact non-secret runtime environment maps emitted by full-topology generation."
  type        = map(map(string))

  validation {
    condition = toset(keys(var.config_map_data)) == toset([
      "analyzer-job-env",
      "canary-job-env",
      "core-control-plane-env",
      "document-ingestion-api-env",
      "document-processing-worker-env",
      "inventory-job-env",
      "observation-campaign-job-env",
      "operator-service-env",
      ]) && alltrue(flatten([
        for values_by_name in values(var.config_map_data) : [
          for name, value in values_by_name :
          can(regex("^[A-Za-z_][A-Za-z0-9_]{0,127}$", name)) &&
          length(value) <= 4096
        ]
    ]))
    error_message = "config_map_data must contain the exact eight generated environment ConfigMaps with valid entries."
  }
}

variable "secret_bindings" {
  description = "Exact environment variable to Key Vault secret-name bindings emitted by full-topology generation. Values are references, never secret values."
  type        = map(map(string))

  validation {
    condition = (
      toset(keys(var.secret_bindings)) == toset([
        "document-ingestion-api",
        "document-processing-worker",
        "operator-service",
      ]) &&
      length(var.secret_bindings["document-ingestion-api"]) == 1 &&
      var.secret_bindings["document-ingestion-api"]["FDAI_DATABASE_URL"] == "fdai-ingestion-api-dsn" &&
      length(var.secret_bindings["document-processing-worker"]) == 1 &&
      var.secret_bindings["document-processing-worker"]["FDAI_DATABASE_URL"] == "fdai-ingestion-worker-dsn" &&
      length(var.secret_bindings["operator-service"]) == 3 &&
      var.secret_bindings["operator-service"]["FDAI_COST_PSEUDONYM_KEY"] == "fdai-cost-pseudonym-key" &&
      var.secret_bindings["operator-service"]["FDAI_DATABASE_URL"] == "fdai-state-store-dsn" &&
      var.secret_bindings["operator-service"]["FDAI_OPERATOR_REQUEST_OPERATOR_SIGNING_SEED"] == "fdai-operator-request-operator-signing-seed"
    )
    error_message = "secret_bindings must contain the exact three generated environment-to-Key Vault Secret bindings."
  }
}

variable "email_data_location" {
  type    = string
  default = "Korea"
}

variable "tags" {
  type    = map(string)
  default = {}
}
