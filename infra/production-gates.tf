# Fail closed before a production plan can become an apply. These checks cover
# environment-independent minimums; customer-approved RPO/RTO, privacy, owner,
# and operational evidence remain in config/architecture-review.yaml.

check "private_postgres_requires_network" {
  assert {
    condition     = !var.enable_private_postgres || var.enable_private_networking
    error_message = "enable_private_postgres requires enable_private_networking."
  }
}

check "production_image_is_digest_pinned" {
  assert {
    condition = var.env != "prod" || (
      can(regex("@sha256:[0-9a-f]{64}$", lower(var.core_image))) &&
      !endswith(lower(var.core_image), "@sha256:0000000000000000000000000000000000000000000000000000000000000000")
    )
    error_message = "prod core_image must use a non-placeholder sha256 digest."
  }
}

check "production_control_plane_hardening" {
  assert {
    condition = var.env != "prod" || (
      var.enable_private_networking &&
      var.enable_private_postgres &&
      var.enable_resource_locks &&
      var.kv_purge_protection_enabled &&
      var.kv_soft_delete_retention_days == 90 &&
      var.postgres_backup_retention_days == 35 &&
      var.postgres_geo_redundant_backup &&
      var.acr_sku == "Premium"
    )
    error_message = "prod requires private networking/Postgres, delete and purge protection, 90-day KV retention, 35-day geo-redundant Postgres backup, and ACR Premium."
  }
}

check "production_alert_destination" {
  assert {
    condition = var.env != "prod" || (
      var.enable_monitoring &&
      (trimspace(var.alert_email) != "" || trimspace(nonsensitive(var.alert_webhook_url)) != "")
    )
    error_message = "prod monitoring must be enabled with at least one alert destination."
  }
}

check "production_budget" {
  assert {
    condition = var.env != "prod" || (
      var.monthly_budget_amount > 0 && length(var.budget_alert_emails) > 0
    )
    error_message = "prod requires a positive monthly budget and at least one budget alert email."
  }
}