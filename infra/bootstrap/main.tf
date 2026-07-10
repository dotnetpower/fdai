# -----------------------------------------------------------------------
# Ops (hub) layer composition. Names follow the same CAF pattern as the app
# config: <type>-<workload>-<env>-<region_short>.
# -----------------------------------------------------------------------

locals {
  suffix = "${var.workload}-${var.env}-${var.region_short}"

  tags = merge({
    workload   = var.workload
    env        = var.env
    managed_by = "terraform"
    layer      = "ops-bootstrap"
  }, var.additional_tags)
}

# -----------------------------------------------------------------------
# Ops resource group - separate from the app RG so it survives app rebuilds.
# -----------------------------------------------------------------------
resource "azurerm_resource_group" "ops" {
  name     = "rg-${var.workload}-ops-${var.region_short}"
  location = var.region
  tags     = local.tags
}

# -----------------------------------------------------------------------
# Ops (hub) VNet - runner subnet + PE subnet. Peered to the app spoke VNet
# by the app config (which owns the spoke side).
# -----------------------------------------------------------------------
resource "azurerm_virtual_network" "ops" {
  name                = "vnet-${var.workload}-ops-${var.region_short}"
  location            = var.region
  resource_group_name = azurerm_resource_group.ops.name
  address_space       = [var.ops_address_space]
  tags                = local.tags
}

resource "azurerm_subnet" "runner" {
  name                 = "snet-runner"
  resource_group_name  = azurerm_resource_group.ops.name
  virtual_network_name = azurerm_virtual_network.ops.name
  address_prefixes     = [var.runner_subnet_prefix]
}

# Defense-in-depth NSG on the runner subnet. The VM has no public IP so
# inbound from the internet is already unreachable; the explicit deny documents
# intent and lights up NSG flow logs. Outbound stays default-allowed (the
# runner needs GitHub + Azure + apt over 443/80).
resource "azurerm_network_security_group" "runner" {
  name                = "nsg-runner-${local.suffix}"
  location            = var.region
  resource_group_name = azurerm_resource_group.ops.name
  tags                = local.tags

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

resource "azurerm_subnet_network_security_group_association" "runner" {
  subnet_id                 = azurerm_subnet.runner.id
  network_security_group_id = azurerm_network_security_group.runner.id
}

resource "azurerm_subnet" "pe" {
  name                              = "snet-pe"
  resource_group_name               = azurerm_resource_group.ops.name
  virtual_network_name              = azurerm_virtual_network.ops.name
  address_prefixes                  = [var.pe_subnet_prefix]
  private_endpoint_network_policies = "Disabled"
}

# -----------------------------------------------------------------------
# Terraform remote-state storage. Created OUT OF BAND with `az` (control
# plane only) because terraform's post-create blob readiness poll cannot
# reach a private + key-disabled account from the operator laptop. See
# create-state-account.sh / README.md. Terraform only references it (data
# source), so no data-plane call happens from the laptop.
# -----------------------------------------------------------------------
data "azurerm_storage_account" "state" {
  name                = var.state_storage_account_name
  resource_group_name = azurerm_resource_group.ops.name
}

# The state container is also created data-plane (from the runner, inside the
# VNet, over the blob PE) by the deploy workflow:
#   az storage container create --account-name <sa> --name tfstate --auth-mode login

# Blob private endpoint + privatelink.blob DNS, linked to the ops VNet so the
# runner resolves the state account privately.
module "state_blob_pe" {
  source                = "../modules/private-endpoint"
  name                  = "pe-st-${local.suffix}"
  location              = var.region
  resource_group_name   = azurerm_resource_group.ops.name
  subnet_id             = azurerm_subnet.pe.id
  vnet_id               = azurerm_virtual_network.ops.id
  target_resource_id    = data.azurerm_storage_account.state.id
  subresource_name      = "blob"
  private_dns_zone_name = "privatelink.blob.core.windows.net"
  tags                  = local.tags
}

# -----------------------------------------------------------------------
# Self-hosted deploy runner - the only host with line-of-sight to the app's
# private endpoints. System-assigned MI authenticates terraform to Azure;
# no public IP (reach via Bastion / az vm run-command / serial console).
# -----------------------------------------------------------------------
resource "azurerm_network_interface" "runner" {
  count               = var.create_runner_vm ? 1 : 0
  name                = "nic-runner-${local.suffix}"
  location            = var.region
  resource_group_name = azurerm_resource_group.ops.name
  tags                = local.tags

  ip_configuration {
    name                          = "internal"
    subnet_id                     = azurerm_subnet.runner.id
    private_ip_address_allocation = "Dynamic"
  }
}

resource "azurerm_linux_virtual_machine" "runner" {
  count               = var.create_runner_vm ? 1 : 0
  name                = "vm-runner-${local.suffix}"
  location            = var.region
  resource_group_name = azurerm_resource_group.ops.name
  size                = var.runner_vm_size
  admin_username      = var.runner_admin_username
  network_interface_ids = [
    azurerm_network_interface.runner[0].id,
  ]
  tags = local.tags

  identity {
    type = "SystemAssigned"
  }

  admin_ssh_key {
    username   = var.runner_admin_username
    public_key = var.runner_ssh_public_key
  }

  os_disk {
    caching              = "ReadWrite"
    storage_account_type = "StandardSSD_LRS"
  }

  source_image_reference {
    publisher = "Canonical"
    offer     = "ubuntu-24_04-lts"
    sku       = "server"
    version   = "latest"
  }

  custom_data = base64encode(templatefile("${path.module}/runner-cloud-init.yaml.tftpl", {
    runner_url   = var.github_runner_url
    runner_token = var.github_runner_token
    runner_user  = var.runner_admin_username
  }))

  # Do not replace the runner on a cloud-init edit or a new "latest" image:
  # replacing the VM destroys the registered GitHub runner (and any in-flight
  # job). Re-provision deliberately (taint) when the bootstrap really changes.
  lifecycle {
    ignore_changes = [custom_data, source_image_reference[0].version]
  }
}

# -----------------------------------------------------------------------
# Runner permissions:
#   - Contributor on the app RG so terraform can create/replace app resources.
#   - Storage Blob Data Contributor on the state account for remote-state I/O.
# Key Vault Secrets Officer on the app KV is granted by the app config
# (the KV lives there and may not exist at bootstrap time); the app config
# consumes runner_principal_id from this layer's output.
# -----------------------------------------------------------------------
data "azurerm_resource_group" "app" {
  count = var.create_runner_vm ? 1 : 0
  name  = var.app_resource_group_name
}

# Only the runner needs data-plane access to the state account (Storage Blob
# Data Contributor below). The bootstrap operator (laptop) reads the account
# via a control-plane data source only, so no laptop blob-data grant is issued
# - the tfstate (which carries secrets) stays reachable by the runner alone.
resource "azurerm_role_assignment" "runner_app_contributor" {
  count                = var.create_runner_vm ? 1 : 0
  scope                = data.azurerm_resource_group.app[0].id
  role_definition_name = "Contributor"
  principal_id         = azurerm_linux_virtual_machine.runner[0].identity[0].principal_id
}

resource "azurerm_role_assignment" "runner_state_blob" {
  count                = var.create_runner_vm ? 1 : 0
  scope                = data.azurerm_storage_account.state.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_linux_virtual_machine.runner[0].identity[0].principal_id
}

# Network Contributor on the ops RG so the runner's app apply can create the
# hub->spoke VNet peering and the ops-side private DNS zone links (the app
# spoke VNet id only exists after that apply, so these cross into the ops RG).
resource "azurerm_role_assignment" "runner_ops_network" {
  count                = var.create_runner_vm ? 1 : 0
  scope                = azurerm_resource_group.ops.id
  role_definition_name = "Network Contributor"
  principal_id         = azurerm_linux_virtual_machine.runner[0].identity[0].principal_id
}

# User Access Administrator on the app RG so the runner can manage the role
# assignments the app config declares (kv_officer_self grants the apply
# principal Key Vault Secrets Officer; the executor MI role bindings on ACR /
# Event Hubs / KV). Contributor alone lacks Microsoft.Authorization/* .
resource "azurerm_role_assignment" "runner_app_uaa" {
  count                = var.create_runner_vm ? 1 : 0
  scope                = data.azurerm_resource_group.app[0].id
  role_definition_name = "User Access Administrator"
  principal_id         = azurerm_linux_virtual_machine.runner[0].identity[0].principal_id
}

# Opt-in delete-protection on the state account - losing it loses all remote
# state, so a shared/prod ops layer should set enable_state_lock = true.
resource "azurerm_management_lock" "state" {
  count      = var.enable_state_lock ? 1 : 0
  name       = "lock-tfstate-${local.suffix}"
  scope      = data.azurerm_storage_account.state.id
  lock_level = "CanNotDelete"
  notes      = "Protects the terraform remote-state account from accidental deletion."
}

# Opt-in daily auto-shutdown for the runner VM to cut idle cost. Start it again
# (az vm start / teardown-env.sh runner-start) before a CI run.
resource "azurerm_dev_test_global_vm_shutdown_schedule" "runner" {
  count              = var.create_runner_vm && var.runner_auto_shutdown_time != "" ? 1 : 0
  virtual_machine_id = azurerm_linux_virtual_machine.runner[0].id
  location           = var.region
  enabled            = true

  daily_recurrence_time = var.runner_auto_shutdown_time
  timezone              = var.runner_auto_shutdown_timezone

  notification_settings {
    enabled = false
  }
}
