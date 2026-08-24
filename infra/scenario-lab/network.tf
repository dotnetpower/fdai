resource "azurerm_virtual_network" "scenario_lab" {
  name                = "vnet-${local.suffix}"
  location            = azurerm_resource_group.scenario_lab.location
  resource_group_name = azurerm_resource_group.scenario_lab.name
  address_space       = var.lab_address_space
  tags                = local.tags
}

resource "azurerm_network_security_group" "scenario_lab" {
  name                = "nsg-${local.suffix}"
  location            = azurerm_resource_group.scenario_lab.location
  resource_group_name = azurerm_resource_group.scenario_lab.name
  tags                = local.tags
}

resource "azurerm_subnet" "aks" {
  name                 = "snet-aks"
  resource_group_name  = azurerm_resource_group.scenario_lab.name
  virtual_network_name = azurerm_virtual_network.scenario_lab.name
  address_prefixes     = [var.aks_subnet_prefix]
}

resource "azurerm_subnet" "stress_vm" {
  name                 = "snet-stress-vm"
  resource_group_name  = azurerm_resource_group.scenario_lab.name
  virtual_network_name = azurerm_virtual_network.scenario_lab.name
  address_prefixes     = [var.vm_subnet_prefix]
}

resource "azurerm_subnet" "mysql" {
  name                 = "snet-mysql"
  resource_group_name  = azurerm_resource_group.scenario_lab.name
  virtual_network_name = azurerm_virtual_network.scenario_lab.name
  address_prefixes     = [var.mysql_subnet_prefix]

  delegation {
    name = "mysql-flexible-server"

    service_delegation {
      name    = "Microsoft.DBforMySQL/flexibleServers"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}

resource "azurerm_subnet" "private_endpoints" {
  name                              = "snet-private-endpoints"
  resource_group_name               = azurerm_resource_group.scenario_lab.name
  virtual_network_name              = azurerm_virtual_network.scenario_lab.name
  address_prefixes                  = [var.private_endpoint_subnet_prefix]
  private_endpoint_network_policies = "Disabled"
}

resource "azurerm_subnet_network_security_group_association" "scenario_lab" {
  for_each = {
    aks               = azurerm_subnet.aks.id
    mysql             = azurerm_subnet.mysql.id
    private_endpoints = azurerm_subnet.private_endpoints.id
    stress_vm         = azurerm_subnet.stress_vm.id
  }

  subnet_id                 = each.value
  network_security_group_id = azurerm_network_security_group.scenario_lab.id
}

resource "azurerm_public_ip" "egress" {
  name                = "pip-${local.suffix}-egress"
  location            = azurerm_resource_group.scenario_lab.location
  resource_group_name = azurerm_resource_group.scenario_lab.name
  allocation_method   = "Static"
  sku                 = "Standard"
  tags                = local.tags

  lifecycle {
    ignore_changes = [ip_tags]
  }
}

resource "azurerm_nat_gateway" "egress" {
  name                    = "nat-${local.suffix}"
  location                = azurerm_resource_group.scenario_lab.location
  resource_group_name     = azurerm_resource_group.scenario_lab.name
  sku_name                = "Standard"
  idle_timeout_in_minutes = 10
  tags                    = local.tags
}

resource "azurerm_nat_gateway_public_ip_association" "egress" {
  nat_gateway_id       = azurerm_nat_gateway.egress.id
  public_ip_address_id = azurerm_public_ip.egress.id
}

resource "azurerm_subnet_nat_gateway_association" "aks" {
  subnet_id      = azurerm_subnet.aks.id
  nat_gateway_id = azurerm_nat_gateway.egress.id
}

resource "azurerm_subnet_nat_gateway_association" "stress_vm" {
  subnet_id      = azurerm_subnet.stress_vm.id
  nat_gateway_id = azurerm_nat_gateway.egress.id
}
