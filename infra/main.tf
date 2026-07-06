# -----------------------------------------------------------------------
# Deterministic name suffixes.
# -----------------------------------------------------------------------
locals {
  env_suffix    = var.env == "" ? "" : "-${var.env}"
  region_suffix = var.region_short == "" ? "" : "-${var.region_short}"
  full_suffix   = "${local.env_suffix}${local.region_suffix}"

  # ACR names cannot contain hyphens (5-50, alphanumeric only).
  # Strip hyphens from the composed suffix.
  acr_suffix = replace(local.full_suffix, "-", "")

  base_tags = {
    workload        = var.workload
    env             = var.env == "" ? "day-zero" : var.env
    managed_by      = "terraform"
    source_of_truth = "aiopspilot"
  }
  tags = merge(local.base_tags, var.additional_tags)

  # Kafka topics served by Event Hubs (see docs/roadmap/deploy-and-onboard.md § Event Source Subscription).
  event_topics = [
    "aw.change.events",
    "aw.dr.events",
    "aw.finops.events",
  ]
}

# -----------------------------------------------------------------------
# Resource Group — the single container per deploy-and-onboard.md.
# -----------------------------------------------------------------------
module "resource_group" {
  source   = "./modules/resource-group"
  name     = "rg-${var.workload}${local.full_suffix}"
  location = var.region
  tags     = local.tags
}

# -----------------------------------------------------------------------
# Observability — Log Analytics first because Container Apps depend on it.
# -----------------------------------------------------------------------
module "log_analytics" {
  source              = "./modules/observability/log-analytics"
  name                = "log-${var.workload}${local.full_suffix}"
  location            = var.region
  resource_group_name = module.resource_group.name
  retention_days      = var.log_retention_days
  tags                = local.tags
}

# -----------------------------------------------------------------------
# Container Registry — pin-by-digest images live here.
# -----------------------------------------------------------------------
module "container_registry" {
  source              = "./modules/container-registry"
  name                = "cr${var.workload}${local.acr_suffix}"
  location            = var.region
  resource_group_name = module.resource_group.name
  tags                = local.tags
}

# -----------------------------------------------------------------------
# Executor Managed Identity — RG-scoped, action-whitelisted (Phase 1 = Change).
# -----------------------------------------------------------------------
module "identity" {
  source              = "./modules/identity/user-assigned-mi"
  name                = "id-${var.workload}${local.full_suffix}-executor"
  resource_group_name = module.resource_group.name
  location            = var.region
  tags                = local.tags
}

# -----------------------------------------------------------------------
# Key Vault — secret store. Executor MI has 'Secrets User' via role assignment.
# -----------------------------------------------------------------------
module "key_vault" {
  source                = "./modules/secret-store/key-vault"
  name                  = "kv-${var.workload}${local.full_suffix}"
  location              = var.region
  resource_group_name   = module.resource_group.name
  tenant_id             = var.tenant_id
  executor_principal_id = module.identity.principal_id
  tags                  = local.tags
}

# -----------------------------------------------------------------------
# Event Bus — Event Hubs (Kafka wire on :9093).
# -----------------------------------------------------------------------
module "event_bus" {
  source              = "./modules/event-bus/event-hubs-kafka"
  name                = "evhns-${var.workload}${local.full_suffix}"
  location            = var.region
  resource_group_name = module.resource_group.name
  topics              = local.event_topics
  tags                = local.tags
}

# -----------------------------------------------------------------------
# State Store — PostgreSQL Flexible with pgvector.
# -----------------------------------------------------------------------
module "state_store" {
  source                 = "./modules/state-store/postgres-flex"
  name                   = "psql-${var.workload}${local.full_suffix}"
  location               = var.region
  resource_group_name    = module.resource_group.name
  tenant_id              = var.tenant_id
  administrator_login    = var.postgres_admin_login
  administrator_password = var.postgres_admin_password
  database_name          = var.workload
  tags                   = local.tags
}

# -----------------------------------------------------------------------
# Compute — Container Apps env + core app + out-of-band job.
# -----------------------------------------------------------------------
module "compute" {
  source                = "./modules/compute/container-apps"
  env_name              = "cae-${var.workload}${local.full_suffix}"
  core_app_name         = "ca-${var.workload}${local.full_suffix}-core"
  oob_job_name          = "caj-${var.workload}${local.full_suffix}-oob"
  rule_watcher_job_name = "caj-${var.workload}${local.full_suffix}-rule-watcher"
  location              = var.region
  resource_group_name   = module.resource_group.name
  log_workspace_id      = module.log_analytics.workspace_id
  executor_identity_id  = module.identity.resource_id
  image                 = var.core_image
  max_replicas          = var.max_replicas
  tags                  = local.tags
}


# -----------------------------------------------------------------------
# LLM — Azure OpenAI (opt-in, docs/roadmap/dev-and-deploy-parity.md § W-D).
# Skipped by default so a Reader-only deployer can plan/apply.
# -----------------------------------------------------------------------
module "llm_azure_openai" {
  count  = var.enable_llm ? 1 : 0
  source = "./modules/llm/azure-openai"

  name                  = "oai-${var.workload}${local.full_suffix}"
  location              = var.region
  resource_group_name   = module.resource_group.name
  executor_principal_id = module.identity.principal_id
  resolved_capabilities = var.resolved_capabilities
  tags                  = local.tags
}

# -----------------------------------------------------------------------
# Phase-4 continuous measurement — two Container Apps Jobs that wire the
# regression detector + pattern-growth intake into scheduled runs.
# The jobs share the same Container Apps env + user-assigned MI as the
# core app + rule watcher (least privilege — no extra role assignments).
# -----------------------------------------------------------------------
module "measurement_runners" {
  source = "./modules/measurement-runners"

  baseline_job_name            = "caj-${var.workload}${local.full_suffix}-measure-baseline"
  growth_job_name              = "caj-${var.workload}${local.full_suffix}-measure-growth"
  container_app_environment_id = module.compute.environment_id
  location                     = var.region
  resource_group_name          = module.resource_group.name
  executor_identity_id         = module.identity.resource_id
  image                        = var.core_image
  scenario_set_version         = var.measurement_scenario_set_version
  tags                         = local.tags
}

