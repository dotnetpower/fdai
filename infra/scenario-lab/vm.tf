resource "azurerm_network_interface" "stress_vm" {
  name                = "nic-${local.suffix}-stress"
  location            = azurerm_resource_group.scenario_lab.location
  resource_group_name = azurerm_resource_group.scenario_lab.name
  tags                = local.tags

  ip_configuration {
    name                          = "private"
    subnet_id                     = azurerm_subnet.stress_vm.id
    private_ip_address_allocation = "Dynamic"
  }
}

resource "azurerm_network_interface_security_group_association" "stress_vm" {
  network_interface_id      = azurerm_network_interface.stress_vm.id
  network_security_group_id = azurerm_network_security_group.scenario_lab.id
}

resource "azurerm_linux_virtual_machine" "stress" {
  # checkov:skip=CKV_AZURE_50:Azure Managed Run Command is the bounded injector transport and requires VM agent operations.
  name                            = "vm-${local.suffix}-stress"
  computer_name                   = "fdai-sre-stress"
  location                        = azurerm_resource_group.scenario_lab.location
  resource_group_name             = azurerm_resource_group.scenario_lab.name
  size                            = var.stress_vm_size
  admin_username                  = "fdailab"
  disable_password_authentication = true
  network_interface_ids           = [azurerm_network_interface.stress_vm.id]
  custom_data = base64encode(<<-CLOUD_INIT
    #cloud-config
    package_update: true
    packages:
      - stress-ng
      - jq
    final_message: "FDAI scenario stress host ready"
  CLOUD_INIT
  )
  tags = local.tags

  admin_ssh_key {
    username   = "fdailab"
    public_key = trimspace(var.admin_ssh_public_key)
  }

  identity {
    type = "SystemAssigned"
  }

  os_disk {
    name                 = "osdisk-${local.suffix}-stress"
    caching              = "ReadWrite"
    storage_account_type = "StandardSSD_LRS"
    disk_size_gb         = 30
  }

  source_image_reference {
    publisher = "Canonical"
    offer     = "0001-com-ubuntu-server-jammy"
    sku       = "22_04-lts-gen2"
    version   = var.vm_image_version
  }

  boot_diagnostics {}

  depends_on = [azurerm_subnet_nat_gateway_association.stress_vm]
}

resource "azurerm_role_assignment" "operator_vm_contributor" {
  count = local.operator_enabled ? 1 : 0

  scope                = azurerm_linux_virtual_machine.stress.id
  role_definition_name = "Virtual Machine Contributor"
  principal_id         = var.operator_access.principal_id
}
