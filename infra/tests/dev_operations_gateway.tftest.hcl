# Config contract: the development operations gateway stays out of every
# environment that is not dev.
#
# deploy-and-onboard.md lists the gateway as "dev and private-networking only".
# Its function app sets public_network_access_enabled unconditionally, because
# a developer has to reach it, so that constraint is what keeps a public inbound
# endpoint out of a closed network.
#
# The constraint is enforced by a lifecycle precondition on the function app,
# which blocks the plan outright. Nothing exercised it, so a refactor could have
# dropped or weakened it silently. These runs assert the refusal itself rather
# than the source text.
#
# The non-dev cases use "staging" and the day-zero empty environment rather than
# "prod", because a prod plan trips every other production gate and would bury
# this one under unrelated failures.
#
# The precondition's private-networking clause is not covered here, and cannot
# be: with private networking off, the gateway's private endpoints index an
# empty module.network and the plan dies before the precondition is evaluated.
# That combination is still refused, just by a message that explains nothing.
# Terraform cannot express "expect a failure from a module", so asserting it
# would mean asserting text from an error string.
#
# `mock_provider` supplies synthetic provider responses, so `terraform test`
# runs the real plan graph with no Azure subscription, no credentials, and no
# network. Every identifier below is synthetic.
#
# Run: terraform -chdir=infra test

mock_provider "azurerm" {}
mock_provider "archive" {}

variables {
  region                  = "koreacentral"
  tenant_id               = "00000000-0000-0000-0000-000000000000"
  postgres_admin_login    = "fdaiadmin"
  postgres_admin_password = "terraform-test-placeholder-value"
  core_image              = "mcr.microsoft.com/example/fdai@sha256:0000000000000000000000000000000000000000000000000000000000000000"
}

run "the_gateway_is_absent_by_default" {
  command = plan

  assert {
    condition     = length(azurerm_function_app_flex_consumption.dev_gateway) == 0
    error_message = "a default plan MUST NOT provision a public development gateway"
  }
}

run "a_day_zero_plan_refuses_the_gateway" {
  command = plan

  variables {
    env                           = ""
    enable_private_networking     = true
    enable_dev_operations_gateway = true
  }

  expect_failures = [azurerm_function_app_flex_consumption.dev_gateway]
}

run "a_staging_plan_refuses_the_gateway" {
  command = plan

  variables {
    env                           = "staging"
    enable_private_networking     = true
    enable_dev_operations_gateway = true
  }

  expect_failures = [azurerm_function_app_flex_consumption.dev_gateway]
}

run "a_dev_plan_with_private_networking_is_accepted" {
  command = plan

  variables {
    env                           = "dev"
    enable_private_networking     = true
    enable_dev_operations_gateway = true
  }

  assert {
    condition     = length(azurerm_function_app_flex_consumption.dev_gateway) == 1
    error_message = "dev with private networking is the supported combination and MUST plan the gateway"
  }
}
