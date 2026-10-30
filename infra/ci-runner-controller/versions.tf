terraform {
  required_version = ">= 1.11.0"

  # Supply an owner-only durable path with -backend-config=path=... on encrypted storage.
  # Never share this state with application, deployment, or legacy runner roots.
  backend "local" {}

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.81"
    }
    azapi = {
      source  = "Azure/azapi"
      version = "= 2.13.0"
    }
  }
}

provider "azapi" {
  subscription_id            = var.subscription_id
  enable_preflight           = false
  skip_provider_registration = true
}

provider "azurerm" {
  subscription_id                 = var.subscription_id
  resource_provider_registrations = "none"
  storage_use_azuread             = true
  features {
    resource_group {
      prevent_deletion_if_contains_resources = false
    }
    log_analytics_workspace {
      permanently_delete_on_destroy = true
    }
  }
}
