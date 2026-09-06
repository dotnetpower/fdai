# Only the credential and its real PostgreSQL consumer are planned. Provider
# responses are synthetic; these plans neither generate credentials nor call Azure.
# Run: terraform -chdir=infra test -filter=tests/initial_postgres_credential.tftest.hcl

mock_provider "azurerm" {}
mock_provider "archive" {}
mock_provider "random" {}

override_module {
  target = module.resource_group
  outputs = {
    name = "rg-example"
  }
}

variables {
  region               = "koreacentral"
  tenant_id            = "00000000-0000-0000-0000-000000000000"
  postgres_admin_login = "fdaiadmin"
  core_image           = "registry.example.com/fdai@sha256:0000000000000000000000000000000000000000000000000000000000000000"
}

run "supplied_password_preserves_default_path" {
  command = plan

  plan_options {
    target = [random_password.initial_postgres_admin, module.state_store]
  }

  variables {
    postgres_admin_password = "terraform-test-placeholder-value"
  }

  assert {
    condition     = !var.generate_initial_postgres_password && length(random_password.initial_postgres_admin) == 0
    error_message = "The default supplied-password path must not plan a generated credential."
  }

  assert {
    condition     = local.postgres_admin_password == var.postgres_admin_password
    error_message = "The supplied password must reach the selected credential unchanged."
  }

  assert {
    condition     = issensitive(local.postgres_admin_password)
    error_message = "The selected credential must remain sensitive."
  }
}

run "missing_password_is_rejected_by_default" {
  command = plan

  plan_options {
    target = [random_password.initial_postgres_admin, module.state_store]
  }

  expect_failures = [var.postgres_admin_password]
}

run "explicit_null_password_is_rejected_without_generation" {
  command = plan

  plan_options {
    target = [random_password.initial_postgres_admin, module.state_store]
  }

  variables {
    postgres_admin_password = null
  }

  expect_failures = [var.postgres_admin_password]
}

run "short_supplied_password_is_still_rejected" {
  command = plan

  plan_options {
    target = [random_password.initial_postgres_admin, module.state_store]
  }

  variables {
    postgres_admin_password = substr("terraform-test-placeholder-value", 0, 9)
  }

  expect_failures = [var.postgres_admin_password]
}

run "example_placeholder_is_still_rejected" {
  command = plan

  plan_options {
    target = [random_password.initial_postgres_admin, module.state_store]
  }

  variables {
    postgres_admin_password = join("-", ["SET", "ME", "VIA", "VAULT"])
  }

  expect_failures = [var.postgres_admin_password]
}

run "generation_rejects_a_supplied_password" {
  command = plan

  plan_options {
    target = [random_password.initial_postgres_admin, module.state_store]
  }

  variables {
    generate_initial_postgres_password = true
    postgres_admin_password            = "terraform-test-placeholder-value"
  }

  expect_failures = [var.postgres_admin_password]
}

run "generation_rejects_even_an_empty_supplied_password" {
  command = plan

  plan_options {
    target = [random_password.initial_postgres_admin, module.state_store]
  }

  variables {
    generate_initial_postgres_password = true
    postgres_admin_password            = ""
  }

  expect_failures = [var.postgres_admin_password]
}

run "generation_plans_one_persistent_strong_credential" {
  command = plan

  plan_options {
    target = [random_password.initial_postgres_admin, module.state_store]
  }

  variables {
    generate_initial_postgres_password = true
    postgres_admin_password            = null
  }

  assert {
    condition     = length(random_password.initial_postgres_admin) == 1
    error_message = "Explicit generation with no supplied password must plan one persistent credential."
  }

  assert {
    condition = (
      random_password.initial_postgres_admin[0].length == 32 &&
      random_password.initial_postgres_admin[0].upper &&
      random_password.initial_postgres_admin[0].lower &&
      random_password.initial_postgres_admin[0].numeric &&
      random_password.initial_postgres_admin[0].special &&
      random_password.initial_postgres_admin[0].min_upper >= 1 &&
      random_password.initial_postgres_admin[0].min_lower >= 1 &&
      random_password.initial_postgres_admin[0].min_numeric >= 1 &&
      random_password.initial_postgres_admin[0].min_special >= 1 &&
      random_password.initial_postgres_admin[0].override_special == "!#$%&*+-=_?"
    )
    error_message = "Generated credentials must use 32 characters and every required Azure-safe character class."
  }

  assert {
    condition     = random_password.initial_postgres_admin[0].keepers == null
    error_message = "Repeated applies must not rotate the credential through keepers."
  }

  assert {
    condition     = issensitive(local.postgres_admin_password)
    error_message = "The generated credential must remain sensitive."
  }
}
