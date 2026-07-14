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

variable "executor_identity_id" {
  description = "User-assigned MI resource id (ACR pull + Key Vault Secrets User). Shared with the core app."
  type        = string
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
  description = "Read-API App ID URI, e.g. `api://<fdai-api-guid>` (FDAI_API_AUDIENCE). The access token aud MUST equal this."
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
