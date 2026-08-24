mock_provider "azurerm" {}

variables {
  name_prefix         = "fdai-preflight-fixture"
  resource_group_name = "rg-fdai"
  location            = "koreacentral"
}

run "inline_plan_contains_policy_denied_shape" {
  command = plan

  variables {
    mode = "inline"
  }

  assert {
    condition     = length(azurerm_managed_disk.inline) == 1
    error_message = "the inline rendering must plan one managed disk"
  }
}

run "attach_existing_plan_omits_policy_denied_shape" {
  command = plan

  variables {
    mode = "attach_existing"
    existing_disk_ids = [
      "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai/providers/Microsoft.Compute/disks/existing-data"
    ]
  }

  assert {
    condition     = length(azurerm_managed_disk.inline) == 0
    error_message = "the attach-existing rendering must not plan an inline managed disk"
  }

  assert {
    condition     = output.effective_disk_ids == var.existing_disk_ids
    error_message = "the attach-existing rendering must preserve the supplied disk ids"
  }
}
