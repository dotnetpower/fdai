# Network module - the private-networking foundation for a policy-locked
# tenant (e.g. an enterprise tenant that enforces "Key Vault public network
# access disabled"). Creates a VNet with two purpose-built subnets:
#
#   - `pe`    : private endpoints (KV, and later ACR / Event Hubs / Postgres).
#               Network policies are disabled so a private endpoint NIC can
#               attach without an NSG rule dance.
#   - `infra` : the Container App Environment infrastructure subnet. Delegated
#               to `Microsoft.App/environments` and sized >= /23 as the
#               Consumption environment requires.
#
# Rendered only when the root sets `enable_private_networking = true`; the
# default (public) path never instantiates this module, so a day-zero deploy on
# an unrestricted tenant stays unchanged.
#
# Design: docs/roadmap/deployment/deploy-and-onboard.md (private-networking layer).

resource "azurerm_virtual_network" "primary" {
  name                = var.name
  location            = var.location
  resource_group_name = var.resource_group_name
  address_space = concat(
    [var.address_space],
    var.enable_functions_subnet ? [var.functions_address_space] : [],
  )
  tags = var.tags
}

resource "azurerm_subnet" "pe" {
  name                 = "snet-pe"
  resource_group_name  = var.resource_group_name
  virtual_network_name = azurerm_virtual_network.primary.name
  address_prefixes     = [var.pe_subnet_prefix]

  # A private endpoint NIC cannot attach while endpoint network policies are
  # enforced on the subnet.
  private_endpoint_network_policies = "Disabled"
}

resource "azurerm_subnet" "infra" {
  name                 = "snet-infra"
  resource_group_name  = var.resource_group_name
  virtual_network_name = azurerm_virtual_network.primary.name
  address_prefixes     = [var.infra_subnet_prefix]

  # The Container App Environment claims this subnet as its infrastructure
  # subnet; Azure requires the delegation below.
  delegation {
    name = "container-apps"
    service_delegation {
      name    = "Microsoft.App/environments"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}

resource "azurerm_subnet" "postgres" {
  name                 = "snet-postgres"
  resource_group_name  = var.resource_group_name
  virtual_network_name = azurerm_virtual_network.primary.name
  address_prefixes     = [var.postgres_subnet_prefix]

  delegation {
    name = "postgres-flex"
    service_delegation {
      name    = "Microsoft.DBforPostgreSQL/flexibleServers"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}

resource "azurerm_subnet" "functions" {
  count                = var.enable_functions_subnet ? 1 : 0
  name                 = "snet-functions"
  resource_group_name  = var.resource_group_name
  virtual_network_name = azurerm_virtual_network.primary.name
  address_prefixes     = [var.functions_subnet_prefix]

  delegation {
    name = "function-flex"
    service_delegation {
      name    = "Microsoft.App/environments"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}
