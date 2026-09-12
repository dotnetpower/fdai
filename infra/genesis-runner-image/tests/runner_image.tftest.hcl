mock_provider "azapi" {
  override_data {
    target = data.azapi_resource.runner_image
    values = {
      output = {
        id       = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-runner-image-krc-2e17f214622f/providers/Microsoft.Compute/images/img-runner-example-dev-krc-2e17f214622f"
        location = "koreacentral"
        properties = {
          hyperVGeneration  = "V2"
          provisioningState = "Succeeded"
          sourceVirtualMachine = {
            id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-runner-build-krc-2e17f214622f/providers/Microsoft.Compute/virtualMachines/vm-runner-build-example-dev-krc-2e17f214622f"
          }
          storageProfile = {
            osDisk = {
              osState = "Generalized"
              osType  = "Linux"
            }
          }
        }
        tags = {
          "fdai:source-commit"    = "0000000000000000000000000000000000000000"
          "fdai:run-digest"       = "0000000000000000000000000000000000000000000000000000000000000000"
          "fdai:toolchain-digest" = "2e17f214622f0459c1c104c5d0caf970ea2ea940fea71a092d6da1320370dcb1"
        }
      }
    }
  }
}

mock_provider "azurerm" {
  override_resource {
    target = azurerm_resource_group.image
    values = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-runner-image-krc-2e17f214622f"
    }
  }
  override_resource {
    target = azurerm_resource_group.staging
    values = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-runner-build-krc-2e17f214622f"
    }
  }
  override_resource {
    target = azurerm_linux_virtual_machine.builder
    values = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-runner-build-krc-2e17f214622f/providers/Microsoft.Compute/virtualMachines/vm-runner-build-example-dev-krc-2e17f214622f"
    }
  }
  override_resource {
    target = azurerm_linux_virtual_machine.verifier
    values = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-runner-build-krc-2e17f214622f/providers/Microsoft.Compute/virtualMachines/vm-runner-verify-example-dev-krc-2e17f214622f"
    }
  }
  override_resource {
    target = azurerm_image.runner
    values = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-runner-image-krc-2e17f214622f/providers/Microsoft.Compute/images/img-runner-example-dev-krc-2e17f214622f"
    }
  }
  override_resource {
    target = azurerm_subnet.builder
    values = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-runner-build-krc-2e17f214622f/providers/Microsoft.Network/virtualNetworks/vnet-example/subnets/snet-runner-build"
    }
  }
  override_resource {
    target = azurerm_network_security_group.builder
    values = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-runner-build-krc-2e17f214622f/providers/Microsoft.Network/networkSecurityGroups/nsg-example"
    }
  }
  override_resource {
    target = azurerm_subnet.firewall
    values = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-runner-build-krc-2e17f214622f/providers/Microsoft.Network/virtualNetworks/vnet-example/subnets/AzureFirewallSubnet"
    }
  }
  override_resource {
    target = azurerm_subnet.firewall_management
    values = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-runner-build-krc-2e17f214622f/providers/Microsoft.Network/virtualNetworks/vnet-example/subnets/AzureFirewallManagementSubnet"
    }
  }
  override_resource {
    target = azurerm_public_ip.firewall
    values = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-runner-build-krc-2e17f214622f/providers/Microsoft.Network/publicIPAddresses/pip-firewall"
    }
  }
  override_resource {
    target = azurerm_public_ip.firewall_management
    values = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-runner-build-krc-2e17f214622f/providers/Microsoft.Network/publicIPAddresses/pip-firewall-management"
    }
  }
  override_resource {
    target = azurerm_firewall_policy.builder
    values = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-runner-build-krc-2e17f214622f/providers/Microsoft.Network/firewallPolicies/afwp-example"
    }
  }
  override_resource {
    target = azurerm_firewall.builder
    values = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-runner-build-krc-2e17f214622f/providers/Microsoft.Network/azureFirewalls/afw-example"
      ip_configuration = {
        name                 = "data"
        private_ip_address   = "192.168.240.68"
        public_ip_address_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-runner-build-krc-2e17f214622f/providers/Microsoft.Network/publicIPAddresses/pip-firewall"
        subnet_id            = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-runner-build-krc-2e17f214622f/providers/Microsoft.Network/virtualNetworks/vnet-example/subnets/AzureFirewallSubnet"
      }
    }
  }
  override_resource {
    target = azurerm_route_table.builder
    values = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-runner-build-krc-2e17f214622f/providers/Microsoft.Network/routeTables/rt-example"
    }
  }
  override_resource {
    target = azurerm_network_interface.builder
    values = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-runner-build-krc-2e17f214622f/providers/Microsoft.Network/networkInterfaces/nic-builder"
    }
  }
  override_resource {
    target = azurerm_network_interface.verifier
    values = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-runner-build-krc-2e17f214622f/providers/Microsoft.Network/networkInterfaces/nic-verifier"
    }
  }
}

variables {
  subscription_id                   = "00000000-0000-0000-0000-000000000000"
  tenant_id                         = "00000000-0000-0000-0000-000000000000"
  workload                          = "example"
  env                               = "dev"
  region                            = "koreacentral"
  region_short                      = "krc"
  source_commit                     = "0000000000000000000000000000000000000000"
  run_digest                        = "0000000000000000000000000000000000000000000000000000000000000000"
  source_image_version              = "24.04.202608270"
  azure_cli_version                 = "2.88.0"
  azure_cli_package_version         = "2.88.0-1~noble"
  microsoft_package_key_fingerprint = "BC528686B50D79E339D3721CEB3E94ADBE1229CF"
  terraform_version                 = "1.9.8"
  terraform_binary_sha256           = "7386e89a97d0f24024955acc79ccf693b75b97f7c6383cb9d966e7d59aa5b223"
  terraform_sha256                  = "186e0145f5e5f2eb97cbd785bc78f21bae4ef15119349f6ad4fa535b83b10df8"
  opa_version                       = "0.68.0"
  opa_sha256                        = "dfd5081fc6f930dfeaf2a225e31e616fc227dc0c7b43019b73d6f8fb8a1de1aa"
  github_runner_version             = "2.337.0"
  github_runner_sha256              = "0000000000000000000000000000000000000000000000000000000000000001"
  runner_ssh_public_key             = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHA6I7nugiew177uO389Zhg2zliPDuRZdNRwT2lKu3To terraform-plan-evaluation-only"
}

run "exact_direct_builder_contract" {
  command = plan

  assert {
    condition = (
      azurerm_linux_virtual_machine.builder.source_image_reference[0].publisher == "Canonical" &&
      azurerm_linux_virtual_machine.builder.source_image_reference[0].offer == "ubuntu-24_04-lts" &&
      azurerm_linux_virtual_machine.builder.source_image_reference[0].sku == "server" &&
      azurerm_linux_virtual_machine.builder.source_image_reference[0].version == var.source_image_version
    )
    error_message = "The builder must use the exact Canonical source image."
  }

  assert {
    condition = (
      length(azurerm_linux_virtual_machine.builder.network_interface_ids) == 1 &&
      azurerm_network_interface.builder.ip_configuration[0].public_ip_address_id == null
    )
    error_message = "The builder must use one private NIC without a public IP."
  }

  assert {
    condition = (
      azurerm_route.builder_default.next_hop_type == "VirtualAppliance" &&
      azurerm_firewall.builder.sku_tier == "Basic" &&
      azurerm_firewall.builder.threat_intel_mode == "Deny" &&
      one(azurerm_network_security_group.builder.security_rule).access == "Deny" &&
      one(azurerm_network_security_group.builder.security_rule).direction == "Inbound"
    )
    error_message = "The build network must route through Firewall Basic and deny inbound traffic."
  }

  assert {
    condition = (
      toset(flatten([
        for collection in azurerm_firewall_policy_rule_collection_group.builder.application_rule_collection : [
          for rule in collection.rule : rule.destination_fqdns
        ]
        ])) == toset([
        "azure.archive.ubuntu.com",
        "github.com",
        "*.githubusercontent.com",
        "packages.microsoft.com",
        "releases.hashicorp.com",
        "security.ubuntu.com",
      ])
    )
    error_message = "The build firewall must allow only exact package and toolchain source FQDNs."
  }

  assert {
    condition = (
      strcontains(file("${path.module}/enroll-runner.sh"), "ACTIONS_RUNNER_INPUT_TOKEN") &&
      !strcontains(file("${path.module}/enroll-runner.sh"), "--token") &&
      strcontains(azapi_resource.builder_deprovision.body.properties.source.script, "cloud-init clean") &&
      strcontains(azapi_resource.builder_deprovision.body.properties.source.script, "waagent -force -deprovision+user") &&
      strcontains(azapi_resource.builder_deprovision.body.properties.source.script, "systemctl poweroff") &&
      strcontains(azapi_resource.builder_deprovision.body.properties.source.script, "systemd-run --unit=fdai-deprovision") &&
      strcontains(azapi_resource.builder_deprovision.body.properties.source.script, "/var/lib/fdai/image-deprovisioned") &&
      !strcontains(azapi_resource.builder_deprovision.body.properties.source.script, "systemctl enable") &&
      !strcontains(azapi_resource.builder_deprovision.body.properties.source.script, "/etc/systemd/system/fdai-deprovision.service") &&
      azapi_resource.builder_deprovision.body.properties.treatFailureAsDeploymentFailure == true &&
      length(terraform_data.await_builder_poweroff.triggers_replace) == 1 &&
      azapi_resource_action.builder_deallocate.action == "deallocate" &&
      azapi_resource_action.builder_generalize.action == "generalize" &&
      azurerm_image.runner.hyper_v_generation == "V2"
    )
    error_message = "The exact toolchain must complete before ordered deallocation, generalization, and capture."
  }

  assert {
    condition = (
      length(azurerm_linux_virtual_machine.verifier.network_interface_ids) == 1 &&
      azurerm_network_interface.verifier.ip_configuration[0].public_ip_address_id == null &&
      strcontains(local.verifier_command, local.toolchain_digest) &&
      azapi_resource_action.verifier_deallocate.action == "deallocate" &&
      output.runner_image.runner_registered == false &&
      output.runner_image.subscription_ready == false
    )
    error_message = "A private verifier must boot the captured image and complete before the no-readiness output."
  }

  assert {
    condition = (
      local.toolchain_digest == "353d53d5f6a8f2b7b7d63f50809aabfd9ba25d01515c861b8477f5bbcea0dba1" &&
      output.runner_image.toolchain_digest == local.toolchain_digest
    )
    error_message = "The captured image must bind the exact source VM and toolchain provenance."
  }
}

run "reject_mutable_source_image" {
  command = plan

  variables {
    source_image_version = "latest"
  }

  expect_failures = [var.source_image_version]
}

run "reject_malformed_tool_digest" {
  command = plan

  variables {
    terraform_sha256 = "not-a-digest"
  }

  expect_failures = [var.terraform_sha256]
}

run "reject_malformed_terraform_binary_digest" {
  command = plan

  variables {
    terraform_binary_sha256 = "not-a-digest"
  }

  expect_failures = [var.terraform_binary_sha256]
}

run "reject_public_or_malformed_build_network" {
  command = plan

  variables {
    build_address_space = "8.8.8.0/24"
  }

  expect_failures = [var.build_address_space]
}
