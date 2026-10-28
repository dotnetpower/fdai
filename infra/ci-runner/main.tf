locals {
  tags = merge({
    "fdai:managed"    = "true"
    "fdai:workload"   = "ci"
    "fdai:env"        = "dev"
    "fdai:layer"      = "ci-runner"
    "fdai:managed-by" = "terraform"
    "fdai:vertical"   = "shared"
  }, var.additional_tags)
}

resource "azurerm_resource_group" "ci" {
  name     = var.resource_group_name
  location = var.location
  tags     = local.tags
}

resource "azurerm_virtual_network" "ci" {
  name                = "vnet-${var.name}"
  resource_group_name = azurerm_resource_group.ci.name
  location            = var.location
  address_space       = [var.address_space]
  tags                = local.tags
}

resource "azurerm_subnet" "ci" {
  name                            = "snet-ci"
  resource_group_name             = azurerm_resource_group.ci.name
  virtual_network_name            = azurerm_virtual_network.ci.name
  address_prefixes                = [var.address_space]
  default_outbound_access_enabled = false
}

resource "azurerm_network_security_group" "ci" {
  name                = "nsg-${var.name}"
  resource_group_name = azurerm_resource_group.ci.name
  location            = var.location
  tags                = local.tags

  security_rule {
    name                       = "DenyAllInbound"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Deny"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }

  security_rule {
    name                       = "DenyVirtualNetworkOutbound"
    priority                   = 100
    direction                  = "Outbound"
    access                     = "Deny"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "*"
    destination_address_prefix = "VirtualNetwork"
  }
}

resource "azurerm_subnet_network_security_group_association" "ci" {
  subnet_id                 = azurerm_subnet.ci.id
  network_security_group_id = azurerm_network_security_group.ci.id
}

# This address belongs only to outbound NAT, never to the VM's NIC.
resource "azurerm_public_ip" "egress" {
  name                = "pip-${var.name}-egress"
  resource_group_name = azurerm_resource_group.ci.name
  location            = var.location
  allocation_method   = "Static"
  sku                 = "Standard"
  ip_tags             = var.egress_ip_tags
  tags                = local.tags
}

resource "azurerm_nat_gateway" "ci" {
  name                = "nat-${var.name}"
  resource_group_name = azurerm_resource_group.ci.name
  location            = var.location
  sku_name            = "Standard"
  tags                = local.tags
}

resource "azurerm_nat_gateway_public_ip_association" "ci" {
  nat_gateway_id       = azurerm_nat_gateway.ci.id
  public_ip_address_id = azurerm_public_ip.egress.id
}

resource "azurerm_subnet_nat_gateway_association" "ci" {
  subnet_id      = azurerm_subnet.ci.id
  nat_gateway_id = azurerm_nat_gateway.ci.id
}

# The subnet NSG association above protects this NIC, and VM creation depends on it.
# Trivy AZU-0068 only recognizes a direct NIC association for this standalone root.
#trivy:ignore:AZU-0068
resource "azurerm_network_interface" "ci" {
  name                = "nic-${var.name}"
  resource_group_name = azurerm_resource_group.ci.name
  location            = var.location
  tags                = local.tags

  ip_configuration {
    name                          = "internal"
    subnet_id                     = azurerm_subnet.ci.id
    private_ip_address_allocation = "Dynamic"
  }
}

resource "azurerm_linux_virtual_machine" "ci" {
  # checkov:skip=CKV_AZURE_50:Protected Azure Run Command enrollment/readback requires the VM agent on this inbound-denied host; no deployment extension is provisioned.
  name                            = "vm-${var.name}"
  resource_group_name             = azurerm_resource_group.ci.name
  location                        = var.location
  size                            = var.vm_size
  admin_username                  = "ciadmin"
  disable_password_authentication = true
  network_interface_ids           = [azurerm_network_interface.ci.id]
  secure_boot_enabled             = true
  vtpm_enabled                    = true
  patch_mode                      = "AutomaticByPlatform"
  patch_assessment_mode           = "AutomaticByPlatform"
  tags                            = local.tags

  admin_ssh_key {
    username   = "ciadmin"
    public_key = var.ssh_public_key
  }

  os_disk {
    name                 = "osdisk-${var.name}"
    caching              = "ReadWrite"
    storage_account_type = "Premium_LRS"
    disk_size_gb         = 256
  }

  source_image_reference {
    publisher = "Canonical"
    offer     = "ubuntu-24_04-lts"
    sku       = "server"
    version   = "latest"
  }

  custom_data = base64encode(templatefile("${path.module}/cloud-init.yaml.tftpl", {
    runner_version = var.runner_version
    runner_sha256  = var.runner_sha256
  }))

  depends_on = [
    azurerm_subnet_network_security_group_association.ci,
    azurerm_nat_gateway_public_ip_association.ci,
    azurerm_subnet_nat_gateway_association.ci,
  ]
}
