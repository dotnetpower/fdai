# Plan-only contract tests for FDAI 3-tier Azure IAM permission groups.
# Run: terraform -chdir=infra/modules/iam/permission-groups test

mock_provider "azurerm" {
  mock_resource "azurerm_role_definition" {
    defaults = {
      role_definition_id          = "00000000-0000-0000-0000-000000000101"
      role_definition_resource_id = "/subscriptions/00000000-0000-0000-0000-000000000000/providers/Microsoft.Authorization/roleDefinitions/00000000-0000-0000-0000-000000000101"
    }
  }
}

variables {
  role_definition_scope = "/subscriptions/00000000-0000-0000-0000-000000000000"
  environment           = "dev"
  binding_mode          = "direct"
  assignments = {
    inventory_reader = {
      group_id     = "reader"
      scope        = "/subscriptions/00000000-0000-0000-0000-000000000000"
      principal_id = "00000000-0000-0000-0000-000000000010"
    }
    devgw_operator = {
      group_id     = "operator"
      scope        = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai-dev-krc"
      principal_id = "00000000-0000-0000-0000-000000000020"
    }
  }
}

run "creates_three_roles_at_subscription_scope_with_safety_floor" {
  command = plan

  assert {
    condition     = toset(keys(azurerm_role_definition.fdai_group)) == toset(["reader", "operator", "contributor"])
    error_message = "Module must define exactly reader, operator, and contributor custom roles."
  }

  assert {
    condition = alltrue([
      for r in values(azurerm_role_definition.fdai_group) :
      contains(r.permissions[0].not_actions, "Microsoft.Authorization/*/Write") &&
      contains(r.permissions[0].not_actions, "Microsoft.Resources/subscriptions/resourceGroups/delete") &&
      contains(r.permissions[0].not_data_actions, "Microsoft.KeyVault/vaults/secrets/getSecret/action")
    ])
    error_message = "Every FDAI custom role must carry the mandatory NotActions and NotDataActions safety floor."
  }

  assert {
    condition     = azurerm_role_assignment.fdai_group["devgw_operator"].principal_type == "ServicePrincipal"
    error_message = "Direct binding mode must assign roles to ServicePrincipal subjects."
  }
}

run "supports_entra_group_binding_and_management_group_scope" {
  command = plan

  variables {
    role_definition_scope = "/providers/Microsoft.Management/managementGroups/mg-fdai-example"
    binding_mode          = "entra_group"
    assignments = {
      exec_change_group = {
        group_id     = "operator"
        scope        = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai-dev-krc"
        principal_id = "00000000-0000-0000-0000-000000000030"
      }
    }
  }

  assert {
    condition     = azurerm_role_assignment.fdai_group["exec_change_group"].principal_type == "Group"
    error_message = "Entra group binding mode must assign roles to Group subjects."
  }
}

run "rejects_subscription_wide_operator_or_contributor" {
  command = plan

  variables {
    assignments = {
      bad_sub_operator = {
        group_id     = "operator"
        scope        = "/subscriptions/00000000-0000-0000-0000-000000000000"
        principal_id = "00000000-0000-0000-0000-000000000040"
      }
    }
  }

  expect_failures = [var.assignments]
}

run "rejects_contributor_in_production" {
  command = plan

  variables {
    environment = "production"
    assignments = {
      bad_prod_contributor = {
        group_id     = "contributor"
        scope        = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai-prod-krc"
        principal_id = "00000000-0000-0000-0000-000000000050"
      }
    }
  }

  expect_failures = [var.assignments]
}
