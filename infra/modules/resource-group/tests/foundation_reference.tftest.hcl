mock_provider "azurerm" {
  mock_data "azurerm_resource_group" {
    defaults = {
      id       = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example"
      name     = "rg-example"
      location = "koreacentral"
      tags = {
        "fdai:foundation-context" = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
      }
    }
  }
}

variables {
  name                      = "rg-example"
  location                  = "koreacentral"
  reference_existing        = true
  foundation_context_digest = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
}

run "reference_only_has_no_azure_resource_writer" {
  command = apply

  assert {
    condition     = length(azurerm_resource_group.primary) == 0 && output.name == "rg-example"
    error_message = "Foundation reference mode must never create a second resource-group owner."
  }
}

run "reference_context_must_match" {
  command = plan
  variables {
    foundation_context_digest = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
  }
  expect_failures = [data.azurerm_resource_group.foundation]
}

run "reference_region_must_match" {
  command = plan
  variables {
    location = "eastus"
  }
  expect_failures = [data.azurerm_resource_group.foundation]
}

run "reference_state_cannot_silently_adopt_group" {
  command = plan
  variables {
    reference_existing        = false
    foundation_context_digest = null
  }
  expect_failures = [terraform_data.ownership]
}
