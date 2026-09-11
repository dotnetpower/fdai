locals {
  toolchain_manifest = {
    schema_version                    = "fdai.genesis-runner-image.v1"
    source_commit                     = var.source_commit
    source_image_version              = var.source_image_version
    azure_cli_version                 = var.azure_cli_version
    azure_cli_package_version         = var.azure_cli_package_version
    microsoft_package_key_fingerprint = var.microsoft_package_key_fingerprint
    terraform_version                 = var.terraform_version
    terraform_binary_sha256           = var.terraform_binary_sha256
    terraform_sha256                  = var.terraform_sha256
    opa_version                       = var.opa_version
    opa_sha256                        = var.opa_sha256
    github_runner_version             = var.github_runner_version
    github_runner_sha256              = var.github_runner_sha256
  }
  toolchain_digest = sha256(jsonencode(local.toolchain_manifest))
  digest_prefix    = substr(local.toolchain_digest, 0, 12)
  suffix           = "${var.workload}-${var.env}-${var.region_short}-${local.digest_prefix}"
  image_name       = "img-runner-${local.suffix}"
  image_id         = "${azurerm_resource_group.image.id}/providers/Microsoft.Compute/images/${local.image_name}"
  customizer = templatefile("${path.module}/customize-runner-image.sh.tftpl", {
    azure_cli_version                 = var.azure_cli_version
    azure_cli_package_version         = var.azure_cli_package_version
    microsoft_package_key_fingerprint = var.microsoft_package_key_fingerprint
    terraform_version                 = var.terraform_version
    terraform_binary_sha256           = var.terraform_binary_sha256
    terraform_sha256                  = var.terraform_sha256
    opa_version                       = var.opa_version
    opa_sha256                        = var.opa_sha256
    github_runner_version             = var.github_runner_version
    github_runner_sha256              = var.github_runner_sha256
    source_commit                     = var.source_commit
    source_image_version              = var.source_image_version
    toolchain_digest                  = local.toolchain_digest
    enrollment_script                 = base64encode(file("${path.module}/enroll-runner.sh"))
    attestation_script                = base64encode(file("${path.module}/attest-runner.sh"))
    state_migration_script            = base64encode(file("${path.module}/migrate-foundation-state.py"))
  })
  builder_command = join(" && ", [
    "printf '%s' '${base64encode(local.customizer)}' | base64 -d >/tmp/fdai-runner-image.sh",
    "chmod 0700 /tmp/fdai-runner-image.sh",
    "/tmp/fdai-runner-image.sh",
    "rm -f /tmp/fdai-runner-image.sh",
  ])
  verifier_command = join(" && ", [
    "test \"$(az version --query '\"azure-cli\"' --output tsv)\" = '${var.azure_cli_version}'",
    "test \"$(terraform version -json | jq -r .terraform_version)\" = '${var.terraform_version}'",
    "opa version | grep -F 'Version: ${var.opa_version}' >/dev/null",
    "printf '%s  %s\\n' '${var.github_runner_sha256}' '/opt/fdai/runner/actions-runner-linux-x64-${var.github_runner_version}.tar.gz' | sha256sum -c -",
    "printf '%s  %s\\n' '${var.terraform_binary_sha256}' '/usr/local/bin/terraform' | sha256sum -c -",
    "printf '%s  %s\\n' '${var.opa_sha256}' '/usr/local/bin/opa' | sha256sum -c -",
    "test \"$(jq -r .toolchain_digest /etc/fdai-runner-image.json)\" = '${local.toolchain_digest}'",
    "test -x /usr/local/sbin/fdai-enroll-runner",
    "test -x /usr/local/sbin/fdai-attest-runner",
    "test -x /usr/local/sbin/fdai-migrate-foundation-state",
    "test ! -e /root/.azure && test ! -e /root/.config/gh && test ! -e /root/.docker && test ! -e /root/.git-credentials",
    "test \"$(cat /var/lib/fdai/image-deprovisioned)\" = 'complete'",
    "test ! -e /etc/systemd/system/fdai-deprovision.service",
    "test ! -e /etc/systemd/system/multi-user.target.wants/fdai-deprovision.service",
  ])
  tags = {
    "fdai:managed"          = "true"
    "fdai:workload"         = var.workload
    "fdai:env"              = var.env
    "fdai:layer"            = "genesis-runner-image"
    "fdai:managed-by"       = "terraform"
    "fdai:vertical"         = "shared"
    "fdai:source-commit"    = var.source_commit
    "fdai:run-digest"       = var.run_digest
    "fdai:toolchain-digest" = local.toolchain_digest
  }
}

resource "azurerm_resource_group" "image" {
  name     = "rg-${var.workload}-runner-image-${var.region_short}-${local.digest_prefix}"
  location = var.region
  tags     = local.tags
}

resource "azurerm_resource_group" "staging" {
  name     = "rg-${var.workload}-runner-build-${var.region_short}-${local.digest_prefix}"
  location = var.region
  tags     = local.tags
}

resource "azurerm_virtual_network" "builder" {
  name                = "vnet-runner-build-${local.suffix}"
  location            = var.region
  resource_group_name = azurerm_resource_group.staging.name
  address_space       = [var.build_address_space]
  tags                = local.tags
}

resource "azurerm_subnet" "builder" {
  name                            = "snet-runner-build"
  resource_group_name             = azurerm_resource_group.staging.name
  virtual_network_name            = azurerm_virtual_network.builder.name
  address_prefixes                = [var.build_subnet_prefix]
  default_outbound_access_enabled = false
}

resource "azurerm_subnet" "firewall" {
  name                 = "AzureFirewallSubnet"
  resource_group_name  = azurerm_resource_group.staging.name
  virtual_network_name = azurerm_virtual_network.builder.name
  address_prefixes     = [var.firewall_subnet_prefix]
}

resource "azurerm_subnet" "firewall_management" {
  name                 = "AzureFirewallManagementSubnet"
  resource_group_name  = azurerm_resource_group.staging.name
  virtual_network_name = azurerm_virtual_network.builder.name
  address_prefixes     = [var.firewall_management_subnet_prefix]
}

resource "azurerm_network_security_group" "builder" {
  name                = "nsg-runner-build-${local.suffix}"
  location            = var.region
  resource_group_name = azurerm_resource_group.staging.name
  tags                = local.tags

  security_rule {
    name                       = "DenyAllInbound"
    priority                   = 4096
    direction                  = "Inbound"
    access                     = "Deny"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }
}

resource "azurerm_subnet_network_security_group_association" "builder" {
  subnet_id                 = azurerm_subnet.builder.id
  network_security_group_id = azurerm_network_security_group.builder.id
}

resource "azurerm_public_ip" "firewall" {
  name                = "pip-runner-firewall-${local.suffix}"
  location            = var.region
  resource_group_name = azurerm_resource_group.staging.name
  allocation_method   = "Static"
  sku                 = "Standard"
  tags                = local.tags
}

resource "azurerm_public_ip" "firewall_management" {
  name                = "pip-runner-firewall-management-${local.suffix}"
  location            = var.region
  resource_group_name = azurerm_resource_group.staging.name
  allocation_method   = "Static"
  sku                 = "Standard"
  tags                = local.tags
}

resource "azurerm_firewall_policy" "builder" {
  name                = "afwp-runner-build-${local.suffix}"
  resource_group_name = azurerm_resource_group.staging.name
  location            = var.region
  sku                 = "Basic"
  tags                = local.tags
}

resource "azurerm_firewall_policy_rule_collection_group" "builder" {
  name               = "runner-build-egress"
  firewall_policy_id = azurerm_firewall_policy.builder.id
  priority           = 100

  application_rule_collection {
    name     = "exact-toolchain-sources"
    priority = 100
    action   = "Allow"

    rule {
      name = "https-toolchain"
      protocols {
        type = "Https"
        port = 443
      }
      source_addresses = [var.build_subnet_prefix]
      destination_fqdns = [
        "azure.archive.ubuntu.com",
        "github.com",
        "*.githubusercontent.com",
        "packages.microsoft.com",
        "releases.hashicorp.com",
        "security.ubuntu.com",
      ]
    }

    rule {
      name = "ubuntu-apt-http"
      protocols {
        type = "Http"
        port = 80
      }
      source_addresses = [var.build_subnet_prefix]
      destination_fqdns = [
        "azure.archive.ubuntu.com",
        "security.ubuntu.com",
      ]
    }
  }
}

resource "azurerm_firewall" "builder" {
  name                = "afw-runner-build-${local.suffix}"
  location            = var.region
  resource_group_name = azurerm_resource_group.staging.name
  sku_name            = "AZFW_VNet"
  sku_tier            = "Basic"
  firewall_policy_id  = azurerm_firewall_policy.builder.id
  tags                = local.tags

  ip_configuration {
    name                 = "data"
    subnet_id            = azurerm_subnet.firewall.id
    public_ip_address_id = azurerm_public_ip.firewall.id
  }

  management_ip_configuration {
    name                 = "management"
    subnet_id            = azurerm_subnet.firewall_management.id
    public_ip_address_id = azurerm_public_ip.firewall_management.id
  }
}

resource "azurerm_route_table" "builder" {
  name                          = "rt-runner-build-${local.suffix}"
  location                      = var.region
  resource_group_name           = azurerm_resource_group.staging.name
  bgp_route_propagation_enabled = false
  tags                          = local.tags
}

resource "azurerm_route" "builder_default" {
  name                   = "default-through-firewall"
  resource_group_name    = azurerm_resource_group.staging.name
  route_table_name       = azurerm_route_table.builder.name
  address_prefix         = "0.0.0.0/0"
  next_hop_type          = "VirtualAppliance"
  next_hop_in_ip_address = azurerm_firewall.builder.ip_configuration[0].private_ip_address
}

resource "azurerm_subnet_route_table_association" "builder" {
  subnet_id      = azurerm_subnet.builder.id
  route_table_id = azurerm_route_table.builder.id
}

resource "azurerm_network_interface" "builder" {
  name                = "nic-runner-build-${local.suffix}"
  location            = var.region
  resource_group_name = azurerm_resource_group.staging.name
  tags                = local.tags

  ip_configuration {
    name                          = "private"
    subnet_id                     = azurerm_subnet.builder.id
    private_ip_address_allocation = "Dynamic"
  }

  depends_on = [
    azurerm_subnet_network_security_group_association.builder,
    azurerm_subnet_route_table_association.builder,
    azurerm_firewall_policy_rule_collection_group.builder,
    azurerm_route.builder_default,
  ]
}

resource "azurerm_network_interface_security_group_association" "builder" {
  network_interface_id      = azurerm_network_interface.builder.id
  network_security_group_id = azurerm_network_security_group.builder.id
}

resource "azurerm_linux_virtual_machine" "builder" {
  name                            = "vm-runner-build-${local.suffix}"
  computer_name                   = "fdai-runner-build"
  location                        = var.region
  resource_group_name             = azurerm_resource_group.staging.name
  size                            = var.build_vm_size
  admin_username                  = var.build_admin_username
  disable_password_authentication = true
  network_interface_ids           = [azurerm_network_interface.builder.id]
  tags                            = local.tags

  admin_ssh_key {
    username   = var.build_admin_username
    public_key = var.runner_ssh_public_key
  }

  source_image_reference {
    publisher = "Canonical"
    offer     = "ubuntu-24_04-lts"
    sku       = "server"
    version   = var.source_image_version
  }

  os_disk {
    caching              = "ReadWrite"
    storage_account_type = "Standard_LRS"
    disk_size_gb         = 64
  }
}

resource "azurerm_virtual_machine_extension" "builder" {
  name                       = "install-exact-runner-toolchain"
  virtual_machine_id         = azurerm_linux_virtual_machine.builder.id
  publisher                  = "Microsoft.Azure.Extensions"
  type                       = "CustomScript"
  type_handler_version       = "2.1"
  auto_upgrade_minor_version = false
  automatic_upgrade_enabled  = false
  protected_settings = jsonencode({
    commandToExecute = local.builder_command
  })
  tags = local.tags
}

resource "azapi_resource_action" "builder_deallocate" {
  type        = "Microsoft.Compute/virtualMachines@2024-07-01"
  resource_id = azurerm_linux_virtual_machine.builder.id
  action      = "deallocate"
  method      = "POST"
  when        = "apply"

  timeouts {
    create = "30m"
  }

  depends_on = [terraform_data.await_builder_poweroff]
}

resource "azapi_resource" "builder_deprovision" {
  type      = "Microsoft.Compute/virtualMachines/runCommands@2024-07-01"
  name      = "deprovision-runner-image"
  parent_id = azurerm_linux_virtual_machine.builder.id
  location  = var.region
  tags      = local.tags

  body = {
    properties = {
      asyncExecution                  = false
      timeoutInSeconds                = 900
      treatFailureAsDeploymentFailure = true
      source = {
        script = <<-SCRIPT
          set -euo pipefail
          systemd-run --unit=fdai-deprovision --on-active=5s /bin/bash -c 'set -euo pipefail; rm -rf /root/.azure /root/.config/gh /root/.docker /root/.git-credentials; cloud-init clean --logs --seed; /usr/sbin/waagent -force -deprovision+user; install -d -m 0755 /var/lib/fdai; printf "complete\n" >/var/lib/fdai/image-deprovisioned; chmod 0444 /var/lib/fdai/image-deprovisioned; sync; /usr/bin/systemctl poweroff'
        SCRIPT
      }
    }
  }

  depends_on = [azurerm_virtual_machine_extension.builder]
}

resource "terraform_data" "await_builder_poweroff" {
  triggers_replace = [azapi_resource.builder_deprovision.id]

  provisioner "local-exec" {
    interpreter = ["/bin/bash", "-c"]
    command     = <<-SCRIPT
      set -euo pipefail
      for _ in $(seq 1 90); do
        state="$("$AZ_CLI" vm get-instance-view --ids "$VM_ID" --query "instanceView.statuses[?starts_with(code, 'PowerState/')].code | [0]" --output tsv --only-show-errors)"
        case "$state" in
          PowerState/stopped|PowerState/deallocated) exit 0 ;;
        esac
        sleep 10
      done
      exit 1
    SCRIPT
    environment = {
      AZ_CLI = abspath("/usr/bin/az")
      VM_ID  = azurerm_linux_virtual_machine.builder.id
    }
  }
}

resource "azapi_resource_action" "builder_generalize" {
  type        = "Microsoft.Compute/virtualMachines@2024-07-01"
  resource_id = azurerm_linux_virtual_machine.builder.id
  action      = "generalize"
  method      = "POST"
  when        = "apply"

  timeouts {
    create = "10m"
  }

  depends_on = [azapi_resource_action.builder_deallocate]
}

resource "azurerm_image" "runner" {
  name                      = local.image_name
  location                  = var.region
  resource_group_name       = azurerm_resource_group.image.name
  source_virtual_machine_id = azurerm_linux_virtual_machine.builder.id
  hyper_v_generation        = "V2"
  tags                      = local.tags

  depends_on = [azapi_resource_action.builder_generalize]
}

resource "azurerm_network_interface" "verifier" {
  name                = "nic-runner-verify-${local.suffix}"
  location            = var.region
  resource_group_name = azurerm_resource_group.staging.name
  tags                = local.tags

  ip_configuration {
    name                          = "private"
    subnet_id                     = azurerm_subnet.builder.id
    private_ip_address_allocation = "Dynamic"
  }

  depends_on = [
    azurerm_subnet_network_security_group_association.builder,
    azurerm_subnet_route_table_association.builder,
    azurerm_firewall_policy_rule_collection_group.builder,
    azurerm_route.builder_default,
  ]
}

resource "azurerm_network_interface_security_group_association" "verifier" {
  network_interface_id      = azurerm_network_interface.verifier.id
  network_security_group_id = azurerm_network_security_group.builder.id
}

resource "azurerm_linux_virtual_machine" "verifier" {
  name                            = "vm-runner-verify-${local.suffix}"
  computer_name                   = "fdai-runner-verify"
  location                        = var.region
  resource_group_name             = azurerm_resource_group.staging.name
  size                            = var.verify_vm_size
  admin_username                  = var.build_admin_username
  disable_password_authentication = true
  network_interface_ids           = [azurerm_network_interface.verifier.id]
  source_image_id                 = azurerm_image.runner.id
  tags                            = local.tags

  admin_ssh_key {
    username   = var.build_admin_username
    public_key = var.runner_ssh_public_key
  }

  os_disk {
    caching              = "ReadWrite"
    storage_account_type = "Standard_LRS"
    disk_size_gb         = 64
  }
}

resource "azurerm_virtual_machine_extension" "verifier" {
  name                       = "verify-exact-runner-toolchain"
  virtual_machine_id         = azurerm_linux_virtual_machine.verifier.id
  publisher                  = "Microsoft.Azure.Extensions"
  type                       = "CustomScript"
  type_handler_version       = "2.1"
  auto_upgrade_minor_version = false
  automatic_upgrade_enabled  = false
  protected_settings = jsonencode({
    commandToExecute = local.verifier_command
  })
  tags = local.tags
}

resource "azapi_resource_action" "verifier_deallocate" {
  type        = "Microsoft.Compute/virtualMachines@2024-07-01"
  resource_id = azurerm_linux_virtual_machine.verifier.id
  action      = "deallocate"
  method      = "POST"
  when        = "apply"

  timeouts {
    create = "30m"
  }

  depends_on = [azurerm_virtual_machine_extension.verifier]
}

data "azapi_resource" "runner_image" {
  type                   = "Microsoft.Compute/images@2024-03-01"
  name                   = local.image_name
  parent_id              = azurerm_resource_group.image.id
  response_export_values = ["id", "location", "properties.hyperVGeneration", "properties.provisioningState", "properties.sourceVirtualMachine.id", "properties.storageProfile.osDisk.osState", "properties.storageProfile.osDisk.osType", "tags"]

  depends_on = [azapi_resource_action.verifier_deallocate]

  lifecycle {
    postcondition {
      condition = (
        lower(self.output.id) == lower(local.image_id) &&
        lower(self.output.properties.sourceVirtualMachine.id) == lower(azurerm_linux_virtual_machine.builder.id) &&
        lower(self.output.location) == lower(var.region) &&
        self.output.properties.provisioningState == "Succeeded" &&
        self.output.properties.hyperVGeneration == "V2" &&
        self.output.properties.storageProfile.osDisk.osState == "Generalized" &&
        self.output.properties.storageProfile.osDisk.osType == "Linux" &&
        self.output.tags["fdai:source-commit"] == var.source_commit &&
        self.output.tags["fdai:run-digest"] == var.run_digest &&
        self.output.tags["fdai:toolchain-digest"] == local.toolchain_digest
      )
      error_message = "The built runner image failed exact identity, location, Linux, provisioning, or provenance readback."
    }
  }
}
