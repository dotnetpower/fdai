# Config contract: the ops layer's only outbound path is optional.
#
# A closed network has no public egress at all, and the runner subnet's NAT
# gateway is the one place this layer creates it. `mock_provider` evaluates the
# real plan graph with no subscription, credentials, or network. Every
# identifier below is synthetic.
#
# Run: terraform -chdir=infra/bootstrap test

mock_provider "azurerm" {
  # The layer scopes role assignments at data-source ids, and a mocked empty id
  # is rejected as a root scope, so supply synthetic ids for the three sources
  # this configuration reads.
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
  # Throwaway key generated for plan evaluation; its private half was never
  # kept. A public key is not a secret, and the provider parses this field.
  runner_ssh_public_key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHA6I7nugiew177uO389Zhg2zliPDuRZdNRwT2lKu3To terraform-plan-evaluation-only"
}

run "public_egress_provisions_one_nat_path" {
  command = plan

  variables {
    enable_public_egress = true
  }

  assert {
    condition     = length(azurerm_nat_gateway.runner) == 1
    error_message = "the default posture MUST keep the runner's NAT gateway"
  }

  assert {
    condition     = length(azurerm_public_ip.nat) == 1
    error_message = "the NAT gateway MUST keep its static public IP"
  }

  assert {
    condition     = length(azurerm_subnet_nat_gateway_association.runner) == 1
    error_message = "the runner subnet MUST stay associated with the NAT gateway"
  }
}

run "closed_network_creates_no_public_address" {
  command = plan

  variables {
    enable_public_egress = false
  }

  assert {
    condition     = length(azurerm_public_ip.nat) == 0
    error_message = "a closed network MUST NOT plan a public IP"
  }

  assert {
    condition     = length(azurerm_nat_gateway.runner) == 0
    error_message = "a closed network MUST NOT plan a NAT gateway"
  }

  assert {
    condition     = length(azurerm_nat_gateway_public_ip_association.nat) == 0
    error_message = "a closed network MUST NOT plan a NAT public-IP association"
  }

  assert {
    condition     = length(azurerm_subnet_nat_gateway_association.runner) == 0
    error_message = "a closed network MUST NOT plan a NAT subnet association"
  }
}
