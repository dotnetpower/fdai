# Generated only during approved private-host apply and retained in private state.
# No keepers or time-based inputs: another apply must not rotate this credential.
resource "random_password" "initial_postgres_admin" {
  count = var.generate_initial_postgres_password ? 1 : 0

  length           = 32
  upper            = true
  lower            = true
  numeric          = true
  special          = true
  min_upper        = 1
  min_lower        = 1
  min_numeric      = 1
  min_special      = 1
  override_special = "!#$%&*+-=_?"
}

locals {
  postgres_admin_password = var.generate_initial_postgres_password ? random_password.initial_postgres_admin[0].result : var.postgres_admin_password
}
