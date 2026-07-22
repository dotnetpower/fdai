# Fail closed before a production plan can become an apply. These checks cover
# environment-independent minimums; customer-approved RPO/RTO, privacy, owner,
# and operational evidence remain in config/architecture-review.yaml.

check "private_postgres_requires_network" {
  assert {
    condition     = !var.enable_private_postgres || var.enable_private_networking
    error_message = "enable_private_postgres requires enable_private_networking."
  }
}

check "vm_task_enforce_requires_binding" {
  assert {
    condition     = !var.vm_task_enforce || var.vm_task_enabled
    error_message = "vm_task_enforce requires vm_task_enabled."
  }
}

check "python_task_author_requires_resolved_capability" {
  assert {
    condition = var.python_task_author_capability == "" || (
      var.enable_llm &&
      var.enable_read_api &&
      contains(
        [for capability in var.resolved_capabilities : capability.name],
        var.python_task_author_capability,
      )
    )
    error_message = "python_task_author_capability requires enable_llm, enable_read_api, and a matching resolved capability."
  }
}

check "document_ingestion_requires_dependencies" {
  assert {
    condition = !var.enable_document_ingestion || (
      var.enable_llm &&
      trimspace(var.read_api_audience) != "" &&
      trimspace(var.ingestion_cors_allow_origins) != "" &&
      trimspace(var.rbac_readers_group_id) != "" &&
      trimspace(var.rbac_contributors_group_id) != "" &&
      trimspace(var.rbac_approvers_group_id) != "" &&
      trimspace(var.rbac_owners_group_id) != "" &&
      trimspace(var.rbac_break_glass_group_id) != "" &&
      contains(
        [for capability in var.resolved_capabilities : capability.name],
        var.ingestion_embedding_capability,
      )
    )
    error_message = "document ingestion requires Entra/RBAC/CORS values, enable_llm, and a matching embedding capability."
  }
}

check "read_api_requires_stewardship_bindings" {
  assert {
    condition = !var.enable_read_api || (
      trimspace(var.stewardship_maintainers) != "" &&
      var.read_api_iam_directory_provider == "entra" &&
      alltrue([
        for agent in ["Odin", "Thor", "Forseti", "Huginn", "Heimdall", "Vidar", "Var", "Bragi", "Saga", "Mimir", "Muninn", "Norns", "Njord", "Freyr"] :
        contains(keys(var.stewardship_agent_bindings), agent)
      ])
    )
    error_message = "enable_read_api requires the Entra directory, stewardship_maintainers, and bindings for every non-autonomous pantheon agent."
  }
}

check "stewardship_governance_requires_delivery" {
  assert {
    condition = !var.enable_stewardship_governance || (
      var.enable_document_ingestion &&
      var.enable_read_api &&
      var.enable_chatops_hil &&
      trimspace(var.gitops_owner) != "" &&
      trimspace(var.gitops_repo) != "" &&
      trimspace(nonsensitive(var.gitops_token)) != "" &&
      length(nonsensitive(var.github_webhook_secret)) >= 32 &&
      trimspace(var.stewardship_maintainers) != "" &&
      alltrue([
        for agent in ["Odin", "Thor", "Forseti", "Huginn", "Heimdall", "Vidar", "Var", "Bragi", "Saga", "Mimir", "Muninn", "Norns", "Njord", "Freyr"] :
        contains(keys(var.stewardship_agent_bindings), agent)
      ])
    )
    error_message = "stewardship governance requires document ingestion, read API, ChatOps, GitOps credentials, a 32+ character webhook secret, and complete stewardship bindings."
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

check "production_ingestion_is_private_and_pinned" {
  assert {
    condition = var.env != "prod" || (
      !var.enable_document_ingestion || (
        var.enable_private_networking &&
        can(regex("@sha256:[0-9a-f]{64}$", lower(var.clamav_image))) &&
        !endswith(lower(var.clamav_image), "@sha256:0000000000000000000000000000000000000000000000000000000000000000") &&
        (
          var.ingestion_image == "" ||
          can(regex("@sha256:[0-9a-f]{64}$", lower(var.ingestion_image)))
        )
      )
    )
    error_message = "prod requires private document ingestion and digest-pinned FDAI/ClamAV images."
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
      var.postgres_high_availability_mode == "ZoneRedundant" &&
      var.acr_sku == "Premium"
    )
    error_message = "prod requires private networking/Postgres, delete and purge protection, 90-day KV retention, 35-day geo-redundant backup, zone-redundant Postgres HA, and ACR Premium."
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

check "production_hil_transport" {
  assert {
    condition = var.env != "prod" || (
      var.enable_chatops_hil &&
      trimspace(nonsensitive(var.chatops_webhook_url)) != "" &&
      length(nonsensitive(var.chatops_webhook_secret)) >= 32
    )
    error_message = "prod requires signed ChatOps HIL delivery with a webhook URL and a secret of at least 32 characters."
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
