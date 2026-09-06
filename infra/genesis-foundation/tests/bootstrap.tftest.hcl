# Exercise the real bootstrap as the test root so its AzureRM provider is mocked.
# Fixtures match foundation.tftest.hcl, but these tests do not prove that the
# foundation composition forwards inputs or suppresses real provider registration.
# Run after provider installation: terraform -chdir=infra/genesis-foundation test -filter=tests/bootstrap.tftest.hcl
mock_provider "azurerm" {
  mock_resource "azurerm_resource_group" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-ops-krc"
    }
  }
  mock_resource "azurerm_virtual_network" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-ops-krc/providers/Microsoft.Network/virtualNetworks/vnet-example-ops-krc"
    }
  }
  mock_resource "azurerm_network_security_group" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-ops-krc/providers/Microsoft.Network/networkSecurityGroups/nsg-example-runner"
    }
  }
  mock_resource "azurerm_network_interface" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-ops-krc/providers/Microsoft.Network/networkInterfaces/nic-example-runner"
    }
  }
  mock_resource "azurerm_user_assigned_identity" {
    defaults = {
      id           = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-ops-krc/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-example-deploy"
      client_id    = "00000000-0000-0000-0000-000000000001"
      principal_id = "00000000-0000-0000-0000-000000000002"
    }
  }
  mock_resource "azurerm_private_dns_zone" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-ops-krc/providers/Microsoft.Network/privateDnsZones/privatelink.blob.core.windows.net"
    }
  }
  mock_resource "azurerm_public_ip" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-ops-krc/providers/Microsoft.Network/publicIPAddresses/pip-example-nat"
    }
  }
  mock_resource "azurerm_nat_gateway" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-ops-krc/providers/Microsoft.Network/natGateways/nat-example"
    }
  }
  mock_data "azurerm_subscription" {
    defaults = {
      id              = "/subscriptions/00000000-0000-0000-0000-000000000000"
      subscription_id = "00000000-0000-0000-0000-000000000000"
    }
  }
  mock_data "azurerm_resource_group" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-dev-krc"
    }
  }
  mock_data "azurerm_storage_account" {
    defaults = {
      id                    = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-ops-krc/providers/Microsoft.Storage/storageAccounts/stexamplegenesis"
      primary_blob_endpoint = "https://stexamplegenesis.blob.core.windows.net/"
    }
  }
}

override_resource {
  target = azurerm_subnet.runner
  values = {
    id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-ops-krc/providers/Microsoft.Network/virtualNetworks/vnet-example-ops-krc/subnets/snet-runner"
  }
}

override_resource {
  target = azurerm_subnet.pe
  values = {
    id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-ops-krc/providers/Microsoft.Network/virtualNetworks/vnet-example-ops-krc/subnets/snet-pe"
  }
}

variables {
  workload                   = "example"
  env                        = "dev"
  region                     = "koreacentral"
  region_short               = "krc"
  app_resource_group_name    = "rg-example-dev-krc"
  state_storage_account_name = "stexamplegenesis"
  ops_address_space          = "10.70.0.0/24"
  runner_subnet_prefix       = "10.70.0.0/26"
  pe_subnet_prefix           = "10.70.0.64/26"
  runner_ssh_public_key      = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHA6I7nugiew177uO389Zhg2zliPDuRZdNRwT2lKu3To terraform-plan-evaluation-only"
}

run "explicit_context_preserves_private_offline_runner" {
  command = plan

  module {
    source = "../bootstrap"
  }

  variables {
    genesis_provider_context = {
      subscription_id = "00000000-0000-0000-0000-000000000000"
      tenant_id       = "00000000-0000-0000-0000-000000000000"
    }
    genesis_state_account_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-ops-krc/providers/Microsoft.Storage/storageAccounts/stexamplegenesis"
    runner_bootstrap_mode    = "offline"
    runner_source_image_id   = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-images/providers/Microsoft.Compute/galleries/example_gallery/images/runner/versions/1.2.3"
    enable_public_egress     = false
  }

  assert {
    condition = (
      length(data.azurerm_storage_account.state) == 0 &&
      local.state_account_id == var.genesis_state_account_id &&
      local.deploy_runner_role_manifest.state_blob_data_contributor.scope == var.genesis_state_account_id &&
      output.state_storage_account_name == var.state_storage_account_name
    )
    error_message = "Genesis must bypass the key-returning account lookup and use only the exact ARM reference."
  }

  assert {
    condition = (
      azurerm_linux_virtual_machine.runner[0].source_image_id == var.runner_source_image_id &&
      length(azurerm_linux_virtual_machine.runner[0].source_image_reference) == 0 &&
      azurerm_linux_virtual_machine.runner[0].custom_data == null &&
      azurerm_network_interface.runner[0].ip_configuration[0].public_ip_address_id == null &&
      length(azurerm_public_ip.nat) == 0 &&
      length(azurerm_nat_gateway.runner) == 0 &&
      length(azurerm_dev_test_global_vm_shutdown_schedule.runner) == 0
    )
    error_message = "The offline image must reach the private VM without marketplace, cloud-init, public addresses, or destructive auto-shutdown."
  }

  assert {
    condition = (
      azurerm_linux_virtual_machine.runner[0].os_disk[0].diff_disk_settings[0].option == "Local" &&
      azurerm_linux_virtual_machine.runner[0].os_disk[0].diff_disk_settings[0].placement == "ResourceDisk" &&
      azurerm_linux_virtual_machine.runner[0].identity[0].type == "SystemAssigned, UserAssigned" &&
      length(azurerm_linux_virtual_machine.runner[0].identity[0].identity_ids) == 1 &&
      length(output.deploy_runner_role_manifest) == 5 &&
      var.genesis_provider_context.subscription_id == "00000000-0000-0000-0000-000000000000" &&
      var.genesis_provider_context.tenant_id == "00000000-0000-0000-0000-000000000000"
    )
    error_message = "Explicit-context bootstrap must preserve the ephemeral ResourceDisk, stable deploy identity, and existing five-role manifest."
  }
}

run "standalone_bootstrap_preserves_defaults" {
  command = apply

  module {
    source = "../bootstrap"
  }

  assert {
    condition = (
      var.genesis_provider_context == null &&
      var.genesis_state_account_id == null &&
      length(data.azurerm_storage_account.state) == 1 &&
      local.state_account_id == data.azurerm_storage_account.state[0].id &&
      var.runner_bootstrap_mode == "online" &&
      azurerm_linux_virtual_machine.runner[0].source_image_id == null &&
      length(azurerm_linux_virtual_machine.runner[0].source_image_reference) == 1 &&
      azurerm_linux_virtual_machine.runner[0].source_image_reference[0].publisher == "Canonical" &&
      azurerm_linux_virtual_machine.runner[0].source_image_reference[0].offer == "ubuntu-24_04-lts" &&
      azurerm_linux_virtual_machine.runner[0].source_image_reference[0].sku == "server" &&
      azurerm_linux_virtual_machine.runner[0].source_image_reference[0].version == "latest"
    )
    error_message = "Standalone bootstrap must retain its null provider context and existing online marketplace defaults."
  }

  assert {
    condition = azurerm_linux_virtual_machine.runner[0].custom_data == base64encode(templatefile("${path.module}/runner-cloud-init.yaml.tftpl", {
      runner_parallelism = var.runner_parallelism
      runner_url         = var.github_runner_url
      runner_token       = var.github_runner_token
      runner_user        = var.runner_admin_username
    }))
    error_message = "Standalone bootstrap must retain its existing cloud-init template and inputs."
  }
}

run "genesis_requires_state_reference" {
  command = plan
  module {
    source = "../bootstrap"
  }
  variables {
    genesis_provider_context = {
      subscription_id = "00000000-0000-0000-0000-000000000000"
      tenant_id       = "00000000-0000-0000-0000-000000000000"
    }
  }
  expect_failures = [var.genesis_state_account_id]
}

run "genesis_rejects_foreign_state_reference" {
  command = plan
  module {
    source = "../bootstrap"
  }
  variables {
    genesis_provider_context = {
      subscription_id = "00000000-0000-0000-0000-000000000000"
      tenant_id       = "00000000-0000-0000-0000-000000000000"
    }
    genesis_state_account_id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-example-ops-krc/providers/Microsoft.Storage/storageAccounts/stexamplegenesis"
  }
  expect_failures = [var.genesis_state_account_id]
}

run "standalone_rejects_genesis_state_reference" {
  command = plan
  module {
    source = "../bootstrap"
  }
  variables {
    genesis_state_account_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-ops-krc/providers/Microsoft.Storage/storageAccounts/stexamplegenesis"
  }
  expect_failures = [var.genesis_state_account_id]
}
