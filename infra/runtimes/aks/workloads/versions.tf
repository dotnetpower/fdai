terraform {
  required_version = ">= 1.9"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.14"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.36"
    }
  }
}

provider "azurerm" {
  resource_provider_registrations = "none"
  storage_use_azuread             = true
  features {}
}

provider "kubernetes" {
  config_path = var.kubeconfig_path
}
