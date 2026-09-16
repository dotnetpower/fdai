data "azurerm_client_config" "current" {}

data "azurerm_resource_group" "target" {
  name = var.resource_group_name
}

locals {
  suffix                = "fdai-a3e-${var.environment}-${var.region_short}"
  subnet_address_prefix = cidrsubnet(var.vnet_address_space, 3, 0)
  tags = merge(var.additional_tags, {
    "fdai:managed"        = "true"
    "fdai:workload"       = "fdai"
    "fdai:env"            = var.environment
    "fdai:layer"          = "a3e-evidence"
    "fdai:managed-by"     = "terraform"
    "fdai:ephemeral"      = "true"
    "fdai:expires-at"     = var.expires_at_utc
    "fdai:authority"      = "none"
    "fdai:required-state" = "deallocated"
  }, var.additional_tags)
}

resource "terraform_data" "deployment_context" {
  input = {
    deploy_runner_principal_id = var.deploy_runner_principal_id
    region                     = var.region
    resource_group_name        = var.resource_group_name
  }

  lifecycle {
    precondition {
      condition = (
        lower(data.azurerm_client_config.current.object_id) ==
        lower(var.deploy_runner_principal_id)
      )
      error_message = "The authenticated Terraform principal must match deploy_runner_principal_id."
    }

    precondition {
      condition     = lower(data.azurerm_resource_group.target.location) == lower(var.region)
      error_message = "The protected holding resource group must be in the approved region."
    }

  }
}

resource "azurerm_user_assigned_identity" "executor" {
  name                = "id-${local.suffix}-executor"
  location            = data.azurerm_resource_group.target.location
  resource_group_name = data.azurerm_resource_group.target.name
  tags                = local.tags

  depends_on = [terraform_data.deployment_context]
}

resource "azurerm_user_assigned_identity" "observer" {
  name                = "id-${local.suffix}-observer"
  location            = data.azurerm_resource_group.target.location
  resource_group_name = data.azurerm_resource_group.target.name
  tags                = local.tags

  depends_on = [terraform_data.deployment_context]
}

resource "azurerm_virtual_network" "target" {
  name                = "vnet-${local.suffix}"
  location            = data.azurerm_resource_group.target.location
  resource_group_name = data.azurerm_resource_group.target.name
  address_space       = [var.vnet_address_space]
  tags                = local.tags

  depends_on = [terraform_data.deployment_context]
}

resource "azurerm_subnet" "target" {
  name                 = "snet-${local.suffix}"
  resource_group_name  = data.azurerm_resource_group.target.name
  virtual_network_name = azurerm_virtual_network.target.name
  address_prefixes     = [local.subnet_address_prefix]
}

resource "azurerm_network_security_group" "target" {
  name                = "nsg-${local.suffix}"
  location            = data.azurerm_resource_group.target.location
  resource_group_name = data.azurerm_resource_group.target.name
  tags                = local.tags

  security_rule {
    name                       = "DenyInternetInbound"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Deny"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "Internet"
    destination_address_prefix = "*"
  }

  security_rule {
    name                       = "DenyInternetOutbound"
    priority                   = 100
    direction                  = "Outbound"
    access                     = "Deny"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "*"
    destination_address_prefix = "Internet"
  }
}

resource "azurerm_subnet_network_security_group_association" "target" {
  subnet_id                 = azurerm_subnet.target.id
  network_security_group_id = azurerm_network_security_group.target.id
}

resource "azurerm_network_interface" "target" {
  name                = "nic-${local.suffix}"
  location            = data.azurerm_resource_group.target.location
  resource_group_name = data.azurerm_resource_group.target.name
  tags                = local.tags

  ip_configuration {
    name                          = "private"
    subnet_id                     = azurerm_subnet.target.id
    private_ip_address_allocation = "Dynamic"
  }

  depends_on = [azurerm_subnet_network_security_group_association.target]
}

resource "azurerm_network_interface_security_group_association" "target" {
  network_interface_id      = azurerm_network_interface.target.id
  network_security_group_id = azurerm_network_security_group.target.id
}

resource "azurerm_linux_virtual_machine" "target" {
  name                            = "vm-${local.suffix}"
  computer_name                   = "fdaia3eevidence"
  location                        = data.azurerm_resource_group.target.location
  resource_group_name             = data.azurerm_resource_group.target.name
  size                            = var.vm_size
  admin_username                  = "fdaievidence"
  allow_extension_operations      = false
  disable_password_authentication = true
  network_interface_ids           = [azurerm_network_interface.target.id]
  secure_boot_enabled             = true
  vtpm_enabled                    = true
  tags                            = local.tags

  admin_ssh_key {
    username   = "fdaievidence"
    public_key = trimspace(var.admin_ssh_public_key)
  }

  os_disk {
    name                 = "osdisk-${local.suffix}"
    caching              = "ReadWrite"
    storage_account_type = "Standard_LRS"
    disk_size_gb         = 30
  }

  source_image_reference {
    publisher = var.vm_image.publisher
    offer     = var.vm_image.offer
    sku       = var.vm_image.sku
    version   = var.vm_image.version
  }

  depends_on = [azurerm_network_interface_security_group_association.target]

}

resource "azurerm_role_definition" "executor" {
  name        = "fdai-a3e-vm-power-${substr(sha1(data.azurerm_resource_group.target.id), 0, 12)}"
  scope       = data.azurerm_resource_group.target.id
  description = "Start, deallocate, and read the isolated FDAI A3-E evidence VM."

  permissions {
    actions = [
      "Microsoft.Compute/virtualMachines/deallocate/action",
      "Microsoft.Compute/virtualMachines/instanceView/read",
      "Microsoft.Compute/virtualMachines/read",
      "Microsoft.Compute/virtualMachines/start/action",
    ]
    not_actions = []
  }

  assignable_scopes = [data.azurerm_resource_group.target.id]
}

resource "azurerm_role_assignment" "executor" {
  scope              = azurerm_linux_virtual_machine.target.id
  role_definition_id = azurerm_role_definition.executor.role_definition_resource_id
  principal_id       = azurerm_user_assigned_identity.executor.principal_id
}

resource "azurerm_role_assignment" "observer" {
  scope                = azurerm_linux_virtual_machine.target.id
  role_definition_name = "Reader"
  principal_id         = azurerm_user_assigned_identity.observer.principal_id
}
