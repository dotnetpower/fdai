# Plan-only bootstrap contract; all resource IDs and registration inputs are synthetic.
# Run: terraform -chdir=infra/bootstrap test -filter=tests/offline_runner.tftest.hcl

mock_provider "azurerm" {
  mock_data "azurerm_subscription" {
    defaults = {
      id              = "/subscriptions/00000000-0000-0000-0000-000000000000"
      subscription_id = "00000000-0000-0000-0000-000000000000"
    }
  }

  mock_data "azurerm_resource_group" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai-dev-krc"
    }
  }

  mock_data "azurerm_storage_account" {
    defaults = {
      id                    = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai-ops-krc/providers/Microsoft.Storage/storageAccounts/stexamplebootstrapdrill"
      primary_blob_endpoint = "https://stexamplebootstrapdrill.blob.core.windows.net/"
    }
  }
}

variables {
  env                        = "dev"
  region                     = "koreacentral"
  region_short               = "krc"
  app_resource_group_name    = "rg-fdai-dev-krc"
  state_storage_account_name = "stexamplebootstrapdrill"
  # Reuse the throwaway public key from public_egress.tftest.hcl.
  runner_ssh_public_key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHA6I7nugiew177uO389Zhg2zliPDuRZdNRwT2lKu3To terraform-plan-evaluation-only"
}

run "online_default_preserves_marketplace_and_cloud_init" {
  command = plan

  assert {
    condition = (
      var.runner_bootstrap_mode == "online" &&
      azurerm_linux_virtual_machine.runner[0].source_image_id == null &&
      length(azurerm_linux_virtual_machine.runner[0].source_image_reference) == 1 &&
      azurerm_linux_virtual_machine.runner[0].source_image_reference[0].publisher == "Canonical" &&
      azurerm_linux_virtual_machine.runner[0].source_image_reference[0].offer == "ubuntu-24_04-lts" &&
      azurerm_linux_virtual_machine.runner[0].source_image_reference[0].sku == "server" &&
      azurerm_linux_virtual_machine.runner[0].source_image_reference[0].version == "latest"
    )
    error_message = "Online defaults must preserve the existing Ubuntu marketplace image."
  }

  assert {
    condition = azurerm_linux_virtual_machine.runner[0].custom_data == base64encode(templatefile("${path.module}/runner-cloud-init.yaml.tftpl", {
      runner_parallelism = var.runner_parallelism
      runner_url         = var.github_runner_url
      runner_token       = var.github_runner_token
      runner_user        = var.runner_admin_username
    }))
    error_message = "Online defaults must preserve the existing cloud-init template and inputs."
  }
}

run "offline_gallery_version_skips_network_bootstrap" {
  command = plan

  variables {
    runner_bootstrap_mode  = "offline"
    runner_source_image_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-images/providers/Microsoft.Compute/galleries/example_gallery/images/runner/versions/1.2.3"
    enable_public_egress   = false
  }

  assert {
    condition = (
      azurerm_linux_virtual_machine.runner[0].source_image_id == var.runner_source_image_id &&
      length(azurerm_linux_virtual_machine.runner[0].source_image_reference) == 0 &&
      azurerm_linux_virtual_machine.runner[0].custom_data == null
    )
    error_message = "Offline bootstrap must use only the pinned gallery version with no marketplace image or cloud-init."
  }

  assert {
    condition = (
      azurerm_network_interface.runner[0].ip_configuration[0].public_ip_address_id == null &&
      length(azurerm_public_ip.nat) == 0 &&
      length(azurerm_nat_gateway.runner) == 0
    )
    error_message = "Offline bootstrap with public egress disabled must preserve the private NIC and create no public address."
  }

  assert {
    condition = (
      azurerm_linux_virtual_machine.runner[0].identity[0].type == "SystemAssigned, UserAssigned" &&
      length(azurerm_linux_virtual_machine.runner[0].identity[0].identity_ids) == 1 &&
      length(output.deploy_runner_role_manifest) == 5 &&
      azurerm_linux_virtual_machine.runner[0].os_disk[0].diff_disk_settings[0].option == "Local" &&
      azurerm_linux_virtual_machine.runner[0].os_disk[0].diff_disk_settings[0].placement == "ResourceDisk" &&
      length(azurerm_dev_test_global_vm_shutdown_schedule.runner) == 0
    )
    error_message = "Offline bootstrap must preserve the identity, role manifest, ephemeral OS disk, and shutdown behavior."
  }
}

run "offline_managed_image_skips_network_bootstrap" {
  command = plan

  variables {
    runner_bootstrap_mode  = "offline"
    runner_source_image_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-images/providers/Microsoft.Compute/images/runner-v1"
    enable_public_egress   = false
  }

  assert {
    condition = (
      azurerm_linux_virtual_machine.runner[0].source_image_id == var.runner_source_image_id &&
      length(azurerm_linux_virtual_machine.runner[0].source_image_reference) == 0 &&
      azurerm_linux_virtual_machine.runner[0].custom_data == null
    )
    error_message = "Offline bootstrap must also support an exact managed image without network cloud-init."
  }
}

run "offline_requires_image" {
  command = plan

  variables {
    runner_bootstrap_mode = "offline"
  }

  expect_failures = [var.runner_source_image_id]
}

run "offline_rejects_empty_image" {
  command = plan

  variables {
    runner_bootstrap_mode  = "offline"
    runner_source_image_id = ""
  }

  expect_failures = [var.runner_source_image_id]
}

run "offline_rejects_latest_gallery_version" {
  command = plan

  variables {
    runner_bootstrap_mode  = "offline"
    runner_source_image_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-images/providers/Microsoft.Compute/galleries/example_gallery/images/runner/versions/latest"
  }

  expect_failures = [var.runner_source_image_id]
}

run "offline_rejects_unversioned_gallery" {
  command = plan

  variables {
    runner_bootstrap_mode  = "offline"
    runner_source_image_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-images/providers/Microsoft.Compute/galleries/example_gallery/images/runner"
  }

  expect_failures = [var.runner_source_image_id]
}

run "offline_rejects_latest_managed_image" {
  command = plan

  variables {
    runner_bootstrap_mode  = "offline"
    runner_source_image_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-images/providers/Microsoft.Compute/images/latest"
  }

  expect_failures = [var.runner_source_image_id]
}

run "offline_rejects_image_endpoint" {
  command = plan

  variables {
    runner_bootstrap_mode  = "offline"
    runner_source_image_id = "https://example.com/images/runner-v1"
  }

  expect_failures = [var.runner_source_image_id]
}

run "offline_rejects_github_url" {
  command = plan

  variables {
    runner_bootstrap_mode  = "offline"
    runner_source_image_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-images/providers/Microsoft.Compute/images/runner-v1"
    github_runner_url      = "https://github.com/example/runner-test"
  }

  expect_failures = [var.github_runner_url]
}

run "offline_rejects_github_token" {
  command = plan

  variables {
    runner_bootstrap_mode  = "offline"
    runner_source_image_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-images/providers/Microsoft.Compute/images/runner-v1"
    github_runner_token    = "synthetic-registration-input"
  }

  expect_failures = [var.github_runner_token]
}

run "online_rejects_prebuilt_image" {
  command = plan

  variables {
    runner_source_image_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-images/providers/Microsoft.Compute/images/runner-v1"
  }

  expect_failures = [var.runner_source_image_id]
}

run "rejects_unknown_bootstrap_mode" {
  command = plan

  variables {
    runner_bootstrap_mode = "automatic"
  }

  expect_failures = [var.runner_bootstrap_mode]
}
