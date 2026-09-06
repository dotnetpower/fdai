mock_provider "azurerm" {}

variables {
  name     = "rg-example"
  location = "koreacentral"
}

run "managed_default" {
  command = apply

  assert {
    condition     = length(azurerm_resource_group.primary) == 1 && length(data.azurerm_resource_group.foundation) == 0
    error_message = "The existing default must still manage the resource group."
  }
}

run "managed_state_cannot_silently_switch_owner" {
  command = plan
  variables {
    reference_existing        = true
    foundation_context_digest = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  }
  expect_failures = [terraform_data.ownership]
}
