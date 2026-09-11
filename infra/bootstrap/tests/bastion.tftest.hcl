mock_provider "azurerm" {
  mock_data "azurerm_subscription" {
    defaults = {
      id              = "/subscriptions/00000000-0000-0000-0000-000000000000"
      subscription_id = "00000000-0000-0000-0000-000000000000"
    }
  }

  mock_data "azurerm_resource_group" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai-dev-krc"
    }
  }

  mock_data "azurerm_storage_account" {
    defaults = {
      id                    = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai-ops-krc/providers/Microsoft.Storage/storageAccounts/stexamplebootstrapdrill"
      primary_blob_endpoint = "https://stexamplebootstrapdrill.blob.core.windows.net/"
    }
  }
}

variables {
  env                        = "dev"
  region                     = "koreacentral"
  region_short               = "krc"
  app_resource_group_name    = "rg-fdai-dev-krc"
  state_storage_account_name = "stexamplebootstrapdrill"
  runner_ssh_public_key      = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHA6I7nugiew177uO389Zhg2zliPDuRZdNRwT2lKu3To terraform-plan-evaluation-only"
}

run "default_omits_bastion_and_public_ip" {
  command = plan

  assert {
    condition = (
      !var.enable_bastion &&
      var.bastion_subnet_prefix == null &&
      length(azurerm_subnet.bastion) == 0 &&
      length(azurerm_network_security_group.bastion) == 0 &&
      length(azurerm_subnet_network_security_group_association.bastion) == 0 &&
      length(azurerm_public_ip.bastion) == 0 &&
      length(azurerm_bastion_host.runner) == 0 &&
      output.bastion_id == null
    )
    error_message = "Bastion and its public IP must remain absent unless selected explicitly."
  }
}

run "explicit_bastion_enables_native_tunnel_only" {
  command = plan

  variables {
    enable_bastion        = true
    bastion_subnet_prefix = "10.70.0.128/26"
  }

  assert {
    condition = (
      azurerm_subnet.bastion[0].name == "AzureBastionSubnet" &&
      length(azurerm_subnet.bastion[0].address_prefixes) == 1 &&
      azurerm_subnet.bastion[0].address_prefixes[0] == var.bastion_subnet_prefix &&
      length(azurerm_network_security_group.bastion) == 1 &&
      length(azurerm_subnet_network_security_group_association.bastion) == 1 &&
      toset([for rule in azurerm_network_security_group.bastion[0].security_rule : rule.name]) == toset([
        "AllowHttpsInbound",
        "AllowGatewayManagerInbound",
        "AllowAzureLoadBalancerInbound",
        "AllowBastionCommunicationInbound",
        "AllowSshRdpOutbound",
        "AllowAzureCloudOutbound",
        "AllowBastionCommunicationOutbound",
        "AllowHttpOutbound",
      ]) &&
      azurerm_public_ip.bastion[0].allocation_method == "Static" &&
      azurerm_public_ip.bastion[0].sku == "Standard" &&
      azurerm_bastion_host.runner[0].sku == "Standard" &&
      azurerm_bastion_host.runner[0].scale_units == 2 &&
      azurerm_bastion_host.runner[0].tunneling_enabled &&
      azurerm_bastion_host.runner[0].file_copy_enabled &&
      !azurerm_bastion_host.runner[0].copy_paste_enabled &&
      !azurerm_bastion_host.runner[0].ip_connect_enabled &&
      !azurerm_bastion_host.runner[0].shareable_link_enabled &&
      azurerm_network_interface.runner[0].ip_configuration[0].public_ip_address_id == null
    )
    error_message = "Explicit Bastion must expose only the Standard native tunnel while the runner remains private."
  }
}

run "reject_missing_bastion_subnet" {
  command = plan

  variables {
    enable_bastion = true
  }

  expect_failures = [var.bastion_subnet_prefix]
}

run "reject_small_bastion_subnet" {
  command = plan

  variables {
    enable_bastion        = true
    bastion_subnet_prefix = "10.70.0.128/27"
  }

  expect_failures = [var.bastion_subnet_prefix]
}
