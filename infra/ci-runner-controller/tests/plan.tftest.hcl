# Mocked plans only: no authentication, Azure requests, credentials or resources.
mock_provider "azapi" {
  mock_resource "azapi_resource" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-ci/providers/Microsoft.App/containerApps/ca-example-controller"
      output = {
        properties = {
          configuration = {
            ingress = { fqdn = "example.azurecontainerapps.io" }
          }
        }
      }
    }
  }
}

mock_provider "azurerm" {
  mock_resource "azurerm_resource_group" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-ci"
    }
  }
  mock_resource "azurerm_user_assigned_identity" {
    defaults = {
      id           = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-ci/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-example"
      principal_id = "00000000-0000-0000-0000-000000000001"
      client_id    = "00000000-0000-0000-0000-000000000002"
    }
  }
  mock_resource "azurerm_log_analytics_workspace" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-ci/providers/Microsoft.OperationalInsights/workspaces/log-example"
    }
  }
  mock_resource "azurerm_container_app_environment" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-ci/providers/Microsoft.App/managedEnvironments/cae-example"
    }
  }
  mock_resource "azurerm_container_app_job" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-ci/providers/Microsoft.App/jobs/caj-example"
    }
  }
  mock_resource "azurerm_storage_account" {
    defaults = {
      id                    = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-ci/providers/Microsoft.Storage/storageAccounts/stexample"
      primary_blob_endpoint = "https://stexample.blob.core.windows.net/"
    }
  }
  mock_resource "azurerm_storage_container" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-ci/providers/Microsoft.Storage/storageAccounts/stexample/blobServices/default/containers/controller-state"
    }
  }
  mock_resource "azurerm_role_definition" {
    defaults = {
      role_definition_resource_id = "/subscriptions/00000000-0000-0000-0000-000000000000/providers/Microsoft.Authorization/roleDefinitions/00000000-0000-0000-0000-000000000003"
    }
  }
}

variables {
  subscription_id            = "00000000-0000-0000-0000-000000000000"
  resource_group_name        = "rg-example-controller"
  worker_resource_group_name = "rg-example-workers"
  location                   = "westus3"
  name                       = "example-ci"
  registry_id                = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-registry/providers/Microsoft.ContainerRegistry/registries/example"
  registry_server            = "example.azurecr.io"
  controller_image           = "example.azurecr.io/controller@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  worker_image               = "example.azurecr.io/worker@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
  github_repository          = "example/repository"
  storage_account_name       = "stexampleci"
}

run "container_only_defaults" {
  command = plan

  assert {
    condition     = length(azurerm_container_app_job.worker) == 2
    error_message = "Exactly control and general Manual Jobs must exist."
  }
  assert {
    condition     = local.config.vm_image_id == "" && local.config.vm_subnet_id == "" && local.config.ssh_public_key == ""
    error_message = "Missing VM inputs must explicitly leave Docker unavailable."
  }
  assert {
    condition     = length(azurerm_role_assignment.vm_workers) == 0 && length(azurerm_role_assignment.subnet_join) == 0 && length(azurerm_role_assignment.image_read) == 0
    error_message = "Container-only operation must grant no VM, subnet or image permissions."
  }
  assert {
    condition     = !var.controller_apply && local.config.cpu_budgets.container_cpu == 260 && local.config.cpu_budgets.vm_cpu == 64
    error_message = "The controller must default to non-applying operation with fixed CPU ceilings."
  }
  assert {
    condition     = azapi_resource.controller.type == "Microsoft.App/containerApps@2024-03-01" && azapi_resource.controller.body.properties.template.scale.minReplicas == 1 && azapi_resource.controller.body.properties.template.scale.maxReplicas == 1
    error_message = "Only the generic ARM resource may own the singleton credential controller."
  }
  assert {
    condition     = alltrue([for secret in azapi_resource.controller.body.properties.configuration.secrets : secret.value == "unset"]) && length(azapi_resource.controller.body.properties.configuration.secrets) == 2
    error_message = "Terraform may seed only two nonsecret placeholders, never operator credentials."
  }
  assert {
    condition     = azapi_resource.controller.body.properties.configuration.ingress.external && !azapi_resource.controller.body.properties.configuration.ingress.allowInsecure && azapi_resource.controller.body.properties.configuration.ingress.targetPort == 8080
    error_message = "The AzAPI migration must preserve external HTTPS ingress on port 8080."
  }
  assert {
    condition     = length(azapi_resource.controller.response_export_values) == 1 && azapi_resource.controller.response_export_values[0] == "properties.configuration.ingress.fqdn" && azapi_resource.controller.body.properties.template.containers[0].resources.cpu == 0.5
    error_message = "Export only the nonsecret FQDN and preserve controller resource limits."
  }
}

run "explicit_vm_prerequisites" {
  command = plan
  variables {
    vm_subnet_id   = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-network/providers/Microsoft.Network/virtualNetworks/vnet-example/subnets/snet-ci"
    vm_image_id    = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-images/providers/Microsoft.Compute/galleries/galexample/images/runner/versions/1.0.0"
    ssh_public_key = "ssh-ed25519 ZXhhbXBsZQ== example"
  }
  assert {
    condition     = length(azurerm_role_assignment.vm_workers) == 1 && azurerm_role_assignment.subnet_join[0].scope == var.vm_subnet_id && azurerm_role_assignment.image_read[0].scope == var.vm_image_id
    error_message = "VM permissions require explicit prerequisites and exact subnet/image scopes."
  }
}

run "reject_mutable_worker_image" {
  command = plan
  variables {
    worker_image = "example.azurecr.io/worker:latest"
  }
  expect_failures = [var.worker_image]
}

run "reject_mutable_controller_image" {
  command = plan
  variables {
    controller_image = "example.azurecr.io/controller:latest"
  }
  expect_failures = [var.controller_image]
}

run "reject_shared_resource_group" {
  command = plan
  variables {
    worker_resource_group_name = "RG-EXAMPLE-CONTROLLER"
  }
  expect_failures = [var.worker_resource_group_name]
}

run "reject_missing_vm_subnet_and_key" {
  command = plan
  variables {
    vm_image_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-images/providers/Microsoft.Compute/galleries/galexample/images/runner/versions/1.0.0"
  }
  expect_failures = [var.vm_subnet_id, var.ssh_public_key]
}

run "reject_unsupported_managed_image" {
  command = plan
  variables {
    vm_image_id    = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-images/providers/Microsoft.Compute/images/img-example"
    vm_subnet_id   = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-network/providers/Microsoft.Network/virtualNetworks/vnet-example/subnets/snet-ci"
    ssh_public_key = "ssh-ed25519 ZXhhbXBsZQ== example"
  }
  expect_failures = [var.vm_image_id]
}

run "reject_unpinned_gallery_image" {
  command = plan
  variables {
    vm_image_id    = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-images/providers/Microsoft.Compute/galleries/galexample/images/runner/versions/latest"
    vm_subnet_id   = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-network/providers/Microsoft.Network/virtualNetworks/vnet-example/subnets/snet-ci"
    ssh_public_key = "ssh-ed25519 ZXhhbXBsZQ== example"
  }
  expect_failures = [var.vm_image_id]
}

run "reject_insecure_controller_origin" {
  command = plan
  variables {
    controller_base_url = "http://example.com"
  }
  expect_failures = [var.controller_base_url]
}
