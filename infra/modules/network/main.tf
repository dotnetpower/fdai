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
    var.enable_functions_subnet || var.enable_evidence_target_subnet ? [var.functions_address_space] : [],
  )
  tags = var.tags
}

resource "azurerm_subnet" "pe" {
  # checkov:skip=CKV2_AZURE_31:This subnet contains only private-endpoint NICs and disables endpoint network policies by design.
  name                            = "snet-pe"
  resource_group_name             = var.resource_group_name
  virtual_network_name            = azurerm_virtual_network.primary.name
  address_prefixes                = [var.pe_subnet_prefix]
  default_outbound_access_enabled = false

  # A private endpoint NIC cannot attach while endpoint network policies are
  # enforced on the subnet.
  private_endpoint_network_policies = "Disabled"
}

resource "azurerm_subnet" "infra" {
  # checkov:skip=CKV2_AZURE_31:Azure Container Apps owns this delegated infrastructure subnet; default outbound access is disabled.
  name                            = "snet-infra"
  resource_group_name             = var.resource_group_name
  virtual_network_name            = azurerm_virtual_network.primary.name
  address_prefixes                = [var.infra_subnet_prefix]
  default_outbound_access_enabled = false

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
  # checkov:skip=CKV2_AZURE_31:PostgreSQL Flexible Server owns this delegated private subnet; default outbound access is disabled.
  name                            = "snet-postgres"
  resource_group_name             = var.resource_group_name
  virtual_network_name            = azurerm_virtual_network.primary.name
  address_prefixes                = [var.postgres_subnet_prefix]
  default_outbound_access_enabled = false

  delegation {
    name = "postgres-flex"
    service_delegation {
      name    = "Microsoft.DBforPostgreSQL/flexibleServers"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}

resource "azurerm_subnet" "functions" {
  # checkov:skip=CKV2_AZURE_31:Flex Consumption owns this delegated integration subnet; default outbound access is disabled.
  count                           = var.enable_functions_subnet ? 1 : 0
  name                            = "snet-functions"
  resource_group_name             = var.resource_group_name
  virtual_network_name            = azurerm_virtual_network.primary.name
  address_prefixes                = [var.functions_subnet_prefix]
  default_outbound_access_enabled = false

  delegation {
    name = "function-flex"
    service_delegation {
      name    = "Microsoft.App/environments"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}

resource "azurerm_subnet" "evidence_target" {
  count                           = var.enable_evidence_target_subnet ? 1 : 0
  name                            = "snet-ohl-evidence"
  resource_group_name             = var.resource_group_name
  virtual_network_name            = azurerm_virtual_network.primary.name
  address_prefixes                = [var.evidence_target_subnet_prefix]
  default_outbound_access_enabled = false
}

resource "azurerm_network_security_group" "evidence_target" {
  count               = var.enable_evidence_target_subnet ? 1 : 0
  name                = "nsg-ohl-evidence"
  location            = var.location
  resource_group_name = var.resource_group_name
  tags                = var.tags

  security_rule {
    name                       = "DenyInternetInbound"
    priority                   = 4000
    direction                  = "Inbound"
    access                     = "Deny"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "Internet"
    destination_address_prefix = "*"
  }
}

resource "azurerm_subnet_network_security_group_association" "evidence_target" {
  count                     = var.enable_evidence_target_subnet ? 1 : 0
  subnet_id                 = azurerm_subnet.evidence_target[0].id
  network_security_group_id = azurerm_network_security_group.evidence_target[0].id
}
