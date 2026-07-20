variable "name" {
  description = "Read-API Container App name (CAF: ca-<workload>[-env][-region]-readapi)."
  type        = string
}

variable "migrate_job_name" {
  description = "Schema-migration Container Apps Job name (CAF: caj-<workload>[-env][-region]-migrate)."
  type        = string
}

variable "container_app_environment_id" {
  description = "Container Apps Environment resource id (shared with the core app)."
  type        = string
}

variable "location" {
  description = "Azure region (for the migration job resource)."
  type        = string
}

variable "resource_group_name" {
  description = "Enclosing resource group."
  type        = string
}

variable "image" {
  description = "Container image reference (the fdai runtime image, e.g. `<acr>/fdai:dev`). Must be built with the `serve` extra so uvicorn is present, and bundle alembic for the migration job."
  type        = string
}

variable "read_api_identity_id" {
  description = "Dedicated read-API user-assigned MI resource id (ACR pull + Key Vault secret read only)."
  type        = string
}

variable "read_api_identity_client_id" {
  description = "User-assigned MI client id passed to the local MSI endpoint."
  type        = string
}

variable "monitor_workspace_customer_id" {
  description = "Log Analytics workspace customer id exposed as FDAI_MONITOR_WORKSPACE_ID for bounded Command Deck KQL reads."
  type        = string
  default     = ""
}

variable "chatops_webhook_secret_id" {
  description = "Key Vault secret id containing the HIL callback HMAC secret."
  type        = string
  sensitive   = true
  default     = ""
}

variable "command_api_identity_id" {
  description = "Dedicated command-transport UAMI resource id with Event Hubs send/receive only."
  type        = string
}

variable "command_api_identity_client_id" {
  description = "Command-transport UAMI client id selected for Event Hubs token acquisition."
  type        = string
}

variable "resolved_models_path" {
  description = "Container path to the resolver output used by the Command Deck narrator. Empty disables the narrator routes."
  type        = string
  default     = ""
}

variable "narrator_probe_interval_seconds" {
  description = "Periodic narrator model latency-probe interval in seconds."
  type        = number
  default     = 300

  validation {
    condition     = var.narrator_probe_interval_seconds >= 30
    error_message = "narrator_probe_interval_seconds MUST be >= 30."
  }
}

variable "web_search_enabled" {
  description = "Enable controlled Azure Responses web search for eligible chat turns."
  type        = bool
  default     = false
}

variable "web_search_allowed_domains" {
  description = "Exact public source hosts allowed for conversational web search."
  type        = list(string)
  default     = []

  validation {
    condition = (
      length(var.web_search_allowed_domains) <= 100 &&
      alltrue([
        for domain in var.web_search_allowed_domains :
        can(regex("^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$", domain))
      ])
    )
    error_message = "web_search_allowed_domains MUST contain at most 100 host names without schemes or paths."
  }
}

variable "web_search_max_results" {
  description = "Maximum citations retained from one web search."
  type        = number
  default     = 3

  validation {
    condition     = var.web_search_max_results >= 1 && var.web_search_max_results <= 10
    error_message = "web_search_max_results MUST be in [1, 10]."
  }
}

variable "web_search_budget_ms" {
  description = "Per-search Azure Responses timeout in milliseconds."
  type        = number
  default     = 15000

  validation {
    condition     = var.web_search_budget_ms >= 1
    error_message = "web_search_budget_ms MUST be >= 1."
  }
}

variable "web_search_probe_interval_seconds" {
  description = "Periodic web-search candidate model probe interval in seconds."
  type        = number
  default     = 300

  validation {
    condition     = var.web_search_probe_interval_seconds >= 30
    error_message = "web_search_probe_interval_seconds MUST be >= 30."
  }
}

variable "acr_login_server" {
  description = "ACR login server for MI-authenticated image pulls. Empty string for a public image."
  type        = string
  default     = ""
}

variable "state_store_dsn_secret_id" {
  description = "Key Vault secret id holding the Postgres DSN (postgresql://...?sslmode=require). The API reads it as FDAI_DATABASE_URL via the executor MI."
  type        = string
}

variable "entra_tenant_id" {
  description = "Entra tenant id for JWT issuer/JWKS (FDAI_ENTRA_TENANT_ID)."
  type        = string
}

variable "api_audience" {
  description = "Expected access-token aud claim (FDAI_API_AUDIENCE). For v2 tokens this is commonly the API application client id, not the `api://.../access` scope string."
  type        = string
}

variable "rbac_readers_group_id" {
  description = "Entra security group id mapped to the Reader role."
  type        = string
}

variable "rbac_contributors_group_id" {
  description = "Entra security group id mapped to the Contributor role."
  type        = string
}

variable "rbac_approvers_group_id" {
  description = "Entra security group id mapped to the Approver role."
  type        = string
}

variable "rbac_owners_group_id" {
  description = "Entra security group id mapped to the Owner role."
  type        = string
}

variable "rbac_break_glass_group_id" {
  description = "Entra security group id mapped to the break-glass role."
  type        = string
}

variable "cors_allow_origins" {
  description = "Comma-separated allowed origins for the console SPA (e.g. the Static Web App origin). MUST NOT contain `*` outside dev; prod fails fast on a wildcard."
  type        = string
  default     = ""
}

variable "iam_directory_provider" {
  description = "Human identity directory adapter. Empty disables search; supported value is entra after User.Read.All admin consent is granted to the read API managed identity."
  type        = string
  default     = ""
}

variable "inventory_freshness_seconds" {
  description = "Maximum active inventory age before the graph is stale."
  type        = number
  default     = 86400
}

variable "python_task_author_endpoint" {
  description = "Azure OpenAI endpoint for editable PythonTask draft generation. Empty disables model authoring."
  type        = string
  default     = ""
}

variable "python_task_author_deployment" {
  description = "Azure OpenAI deployment paired with python_task_author_endpoint."
  type        = string
  default     = ""
}

variable "kafka_bootstrap_servers" {
  description = "Event Hubs Kafka bootstrap used only to publish typed proposals. Empty disables proposal submission."
  type        = string
  default     = ""
}

variable "kafka_topic_events" {
  description = "Raw event topic consumed by Huginn. Empty disables proposal submission."
  type        = string
  default     = ""
}

variable "azure_subscription_id" {
  description = "Subscription inspected by the onboarding ResourceProbe."
  type        = string
}

variable "azure_resource_group" {
  description = "Resource group inspected by the onboarding ResourceProbe."
  type        = string
}

variable "executor_principal_id" {
  description = "Executor principal whose required role assignments are verified."
  type        = string
}

variable "executor_event_role_definition_id" {
  description = "Expected Event Hubs data-owner role definition id for the executor."
  type        = string
}

variable "executor_secret_role_definition_id" {
  description = "Expected Key Vault secret-reader role definition id for the executor."
  type        = string
}

variable "min_replicas" {
  description = "Minimum replicas. 1 keeps the read API always-on for the console."
  type        = number
  default     = 1
}

variable "max_replicas" {
  description = "Maximum replicas."
  type        = number
  default     = 1
}

variable "cpu" {
  description = "vCPU per replica."
  type        = number
  default     = 0.5
}

variable "memory" {
  description = "Memory per replica (e.g. `1Gi`)."
  type        = string
  default     = "1Gi"
}

variable "tags" {
  description = "Resource tags."
  type        = map(string)
  default     = {}
}
