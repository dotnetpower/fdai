// Proposal-only OHL evidence driver. The dedicated identity can pull this image
// and send to the primary ingress Event Hub; it has no provider-effect, state,
// Key Vault, or gateway role. The normal control loop owns every later decision.

resource "azurerm_container_app_job" "ohl_evidence_proposal" {
  count = var.ohl_evidence_enabled ? 1 : 0

  name                         = "${var.core_app_name}-ohl-evidence"
  container_app_environment_id = azurerm_container_app_environment.primary.id
  resource_group_name          = var.resource_group_name
  location                     = var.location
  workload_profile_name        = "Consumption"
  replica_timeout_in_seconds   = 120
  replica_retry_limit          = 2

  identity {
    type         = "UserAssigned"
    identity_ids = [var.ohl_evidence_identity_id]
  }

  dynamic "registry" {
    for_each = var.acr_login_server == "" ? toset([]) : toset(["1"])
    content {
      server   = var.acr_login_server
      identity = var.ohl_evidence_identity_id
    }
  }

  manual_trigger_config {
    replica_completion_count = 1
    parallelism              = 1
  }

  template {
    container {
      name    = "ohl-evidence-proposal"
      image   = var.image
      cpu     = 0.25
      memory  = "0.5Gi"
      command = ["python", "-m", "fdai.delivery.ohl_scale_out_evidence_cli"]

      env {
        name  = "KAFKA_BOOTSTRAP_SERVERS"
        value = var.kafka_bootstrap_servers
      }
      env {
        name  = "KAFKA_TOPIC_EVENTS"
        value = var.kafka_topic_events
      }
      env {
        name  = "FDAI_MI_CLIENT_ID"
        value = var.ohl_evidence_identity_client_id
      }
      env {
        name  = "FDAI_OHL_TARGET_RESOURCE_ID"
        value = var.ohl_evidence_target_resource_id
      }
      env {
        name  = "FDAI_OHL_INITIATOR_PRINCIPAL_ID"
        value = var.ohl_evidence_initiator_principal_id
      }
      env {
        name  = "FDAI_OHL_CAMPAIGN_ID"
        value = var.ohl_evidence_campaign_id
      }
      env {
        name  = "FDAI_OHL_BASELINE_CAPACITY"
        value = "1"
      }
    }
  }

  tags = merge(var.tags, { "fdai:component" = "ohl-scale-out-evidence" })

  lifecycle {
    precondition {
      condition = (
        var.ohl_evidence_identity_id != "" &&
        var.ohl_evidence_identity_client_id != "" &&
        var.ohl_evidence_target_resource_id != "" &&
        can(regex("^[A-Za-z0-9._:-]{1,128}$", var.ohl_evidence_campaign_id)) &&
        can(regex("^[0-9a-fA-F-]{36}$", var.ohl_evidence_initiator_principal_id))
      )
      error_message = "the OHL evidence proposal Job requires its dedicated identity, target, campaign, and human initiator."
    }
  }
}
