terraform {
  required_version = ">= 1.9, < 2.0"
  backend "local" {}
  required_providers {
    azurerm = { source = "hashicorp/azurerm", version = "~> 4.0" }
  }
}

provider "azurerm" {
  features {}
  subscription_id                 = var.subscription_id
  resource_provider_registrations = "none"
}

module "hub" {
  source                = "../modules/hub-service"
  kind                  = "release"
  prefix                = var.prefix
  tenant_id             = var.tenant_id
  location              = var.location
  tags                  = var.tags
  network               = var.network
  database_admin        = var.database_admin
  database              = var.database
  log_retention_days    = var.log_retention_days
  registry              = var.registry
  image                 = var.image
  app_image             = var.app_image
  ingress_cidrs         = var.ingress_cidrs
  replicas              = var.replicas
  operator_auth         = var.operator_auth
  enable_apps           = var.enable_apps
  enable_bootstrap_job  = var.enable_bootstrap_job
  enable_migration_jobs = var.enable_migration_jobs
  secret_versions       = var.secret_versions
}

output "deployment" {
  value = module.hub.deployment
}
output "bootstrap_job" {
  value = module.hub.bootstrap_job
}
