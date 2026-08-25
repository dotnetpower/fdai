data "azurerm_client_config" "current" {}

locals {
  suffix = "fdai-dev-access-${var.region_short}"
  tags = merge({
    "fdai:managed"    = "true"
    "fdai:workload"   = "fdai"
    "fdai:env"        = "dev"
    "fdai:layer"      = "developer-access"
    "fdai:managed-by" = "terraform"
  }, var.additional_tags)
}

resource "azurerm_resource_group" "dev_access" {
  name     = "rg-${local.suffix}"
  location = var.region
  tags     = local.tags
}

resource "azurerm_virtual_network" "dev_access" {
  name                = "vnet-${local.suffix}"
  location            = azurerm_resource_group.dev_access.location
  resource_group_name = azurerm_resource_group.dev_access.name
  address_space       = [var.dev_access_address_space]
  tags                = local.tags
}

resource "azurerm_subnet" "gateway" {
  # checkov:skip=CKV2_AZURE_31:Azure VPN Gateway exclusively owns GatewaySubnet; associating an NSG is not a supported gateway design.
  name                 = "GatewaySubnet"
  resource_group_name  = azurerm_resource_group.dev_access.name
  virtual_network_name = azurerm_virtual_network.dev_access.name
  address_prefixes     = [var.gateway_subnet_prefix]
}

resource "azurerm_subnet" "resolver_inbound" {
  # checkov:skip=CKV2_AZURE_31:Private DNS Resolver exclusively owns this delegated inbound-endpoint subnet.
  name                 = "snet-dns-inbound"
  resource_group_name  = azurerm_resource_group.dev_access.name
  virtual_network_name = azurerm_virtual_network.dev_access.name
  address_prefixes     = [var.resolver_inbound_subnet_prefix]

  delegation {
    name = "dns-resolver"

    service_delegation {
      name    = "Microsoft.Network/dnsResolvers"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}

resource "azurerm_public_ip" "vpn_gateway" {
  name                = "pip-vpng-${local.suffix}"
  location            = azurerm_resource_group.dev_access.location
  resource_group_name = azurerm_resource_group.dev_access.name
  allocation_method   = "Static"
  sku                 = "Standard"
  zones               = ["1", "2", "3"]
  tags                = local.tags

  lifecycle {
    ignore_changes = [ip_tags]
  }
}

resource "azurerm_virtual_network_gateway" "dev_access" {
  name                = "vpng-${local.suffix}"
  location            = azurerm_resource_group.dev_access.location
  resource_group_name = azurerm_resource_group.dev_access.name
  type                = "Vpn"
  vpn_type            = "RouteBased"
  active_active       = false
  bgp_enabled         = false
  sku                 = var.gateway_sku
  tags                = local.tags

  ip_configuration {
    name                          = "gateway"
    public_ip_address_id          = azurerm_public_ip.vpn_gateway.id
    private_ip_address_allocation = "Dynamic"
    subnet_id                     = azurerm_subnet.gateway.id
  }

  vpn_client_configuration {
    address_space        = [var.vpn_client_address_pool]
    vpn_client_protocols = ["OpenVPN"]
    vpn_auth_types       = ["AAD"]
    aad_tenant           = "https://login.microsoftonline.com/${data.azurerm_client_config.current.tenant_id}/"
    aad_audience         = var.entra_audience
    aad_issuer           = "https://sts.windows.net/${data.azurerm_client_config.current.tenant_id}/"
  }
}

resource "azurerm_private_dns_resolver" "dev_access" {
  name                = "dnspr-${local.suffix}"
  resource_group_name = azurerm_resource_group.dev_access.name
  location            = azurerm_resource_group.dev_access.location
  virtual_network_id  = azurerm_virtual_network.dev_access.id
  tags                = local.tags
}

resource "azurerm_private_dns_resolver_inbound_endpoint" "dev_access" {
  name                    = "inbound-${local.suffix}"
  private_dns_resolver_id = azurerm_private_dns_resolver.dev_access.id
  location                = azurerm_resource_group.dev_access.location
  tags                    = local.tags

  ip_configurations {
    private_ip_allocation_method = "Dynamic"
    subnet_id                    = azurerm_subnet.resolver_inbound.id
  }
}

# Azure VPN Gateway pushes VNet custom DNS servers into generated P2S client
# profiles. The resolver inbound endpoint can resolve zones linked below while
# the FDAI VNet keeps its existing DNS configuration unchanged.
resource "azurerm_virtual_network_dns_servers" "dev_access" {
  # checkov:skip=CKV_AZURE_182:Azure Private DNS Resolver is managed and zone-redundant; one inbound endpoint is the supported P2S forwarding target.
  virtual_network_id = azurerm_virtual_network.dev_access.id
  dns_servers = [
    azurerm_private_dns_resolver_inbound_endpoint.dev_access.ip_configurations[0].private_ip_address,
  ]
}

resource "azurerm_virtual_network_peering" "dev_access_to_fdai" {
  name                         = "peer-dev-access-to-fdai"
  resource_group_name          = azurerm_resource_group.dev_access.name
  virtual_network_name         = azurerm_virtual_network.dev_access.name
  remote_virtual_network_id    = var.fdai_vnet.id
  allow_virtual_network_access = true
  allow_forwarded_traffic      = true
  allow_gateway_transit        = true
}

resource "azurerm_virtual_network_peering" "fdai_to_dev_access" {
  name                         = "peer-fdai-to-dev-access"
  resource_group_name          = var.fdai_vnet.resource_group_name
  virtual_network_name         = var.fdai_vnet.name
  remote_virtual_network_id    = azurerm_virtual_network.dev_access.id
  allow_virtual_network_access = true
  allow_forwarded_traffic      = true
  use_remote_gateways          = true

  depends_on = [
    azurerm_virtual_network_gateway.dev_access,
    azurerm_virtual_network_peering.dev_access_to_fdai,
  ]
}

resource "azurerm_private_dns_zone_virtual_network_link" "fdai" {
  for_each = var.fdai_private_dns_zones

  name                  = "link-dev-access-${each.key}"
  resource_group_name   = each.value.resource_group_name
  private_dns_zone_name = each.value.name
  virtual_network_id    = azurerm_virtual_network.dev_access.id
  registration_enabled  = false
  tags                  = local.tags

  lifecycle {
    ignore_changes = [tags]
  }
}
