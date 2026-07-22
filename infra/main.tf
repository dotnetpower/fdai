# -----------------------------------------------------------------------
# Deterministic name suffixes.
# -----------------------------------------------------------------------
moved {
  from = azurerm_role_assignment.executor_eventhubs_data_owner
  to   = azurerm_role_assignment.executor_eventhubs_data_owner["aw.change.events"]
}

moved {
  from = azurerm_role_assignment.command_api_eventhubs_sender[0]
  to   = azurerm_role_assignment.command_api_eventhubs_sender["aw.change.events"]
}

moved {
  from = azurerm_role_assignment.command_api_eventhubs_receiver[0]
  to   = azurerm_role_assignment.command_api_eventhubs_receiver["aw.pipeline.stages"]
}

data "azurerm_client_config" "current" {}

locals {
  env_suffix    = var.env == "" ? "" : "-${var.env}"
  region_suffix = var.region_short == "" ? "" : "-${var.region_short}"
  full_suffix   = "${local.env_suffix}${local.region_suffix}"

  # ACR names cannot contain hyphens (5-50, alphanumeric only).
  # Strip hyphens from the composed suffix.
  acr_suffix = replace(local.full_suffix, "-", "")
  # Storage account names are globally unique. Derive a stable, non-reversible
  # suffix from the subscription + environment without committing an id.
  storage_unique_suffix = substr(md5("${data.azurerm_client_config.current.subscription_id}:${local.env_label}"), 0, 6)

  # Environment label: 'day-zero' for the unqualified deployment, else the env.
  env_label = var.env == "" ? "day-zero" : var.env

  # FDAI tag taxonomy. Every key is namespaced under `fdai:` so the full set is
  # grep-able and FDAI-owned resources are unambiguous in a shared subscription
  # (`az resource list --tag fdai:managed=true`). `fdai:managed` is the ownership
  # marker used for blast-radius scoping, safe teardown, and cost attribution.
  # See deploy-and-onboard.md § Resource Tagging Convention.
  base_tags = {
    "fdai:managed"    = "true"
    "fdai:workload"   = var.workload
    "fdai:env"        = local.env_label
    "fdai:layer"      = "control-plane"
    "fdai:managed-by" = "terraform"
    "fdai:vertical"   = var.cost_vertical
  }
  tags = merge(local.base_tags, var.additional_tags)

  # Kafka topics served by Event Hubs (see docs/roadmap/deployment/deploy-and-onboard.md § Event Source Subscription).
  canary_topic        = "aw.control.canary"
  inventory_raw_topic = "aw.inventory.raw"
  event_topics = [
    "aw.change.events",
    "aw.dr.events",
    "aw.finops.events",
    "aw.pantheon.objects",
  ]
  event_auxiliary_topics = ["aw.hil.decisions", "aw.pipeline.stages"]
}

# -----------------------------------------------------------------------
# Resource Group - the single container per deploy-and-onboard.md.
# -----------------------------------------------------------------------
module "resource_group" {
  source   = "./modules/resource-group"
  name     = "rg-${var.workload}${local.full_suffix}"
  location = var.region
  tags     = local.tags
}

# Opt-in delete-protection: a CanNotDelete lock blocks an accidental RG (and
# thus whole-env) deletion. Default off so a dev tear-down stays a one-liner;
# set enable_resource_locks = true for staging/prod.
resource "azurerm_management_lock" "resource_group" {
  count      = var.enable_resource_locks ? 1 : 0
  name       = "lock-${var.workload}${local.full_suffix}"
  scope      = module.resource_group.id
  lock_level = "CanNotDelete"
  notes      = "Protects the FDAI environment from accidental deletion (enable_resource_locks)."
}

# Opt-in monthly cost budget on the RG with progressive alert thresholds. Set
# monthly_budget_amount > 0 to enable; alerts fire to the address list only
# (never an autonomous action).
resource "azurerm_consumption_budget_resource_group" "monthly" {
  count             = var.monthly_budget_amount > 0 ? 1 : 0
  name              = "budget-${var.workload}${local.full_suffix}"
  resource_group_id = module.resource_group.id

  amount     = var.monthly_budget_amount
  time_grain = "Monthly"

  time_period {
    start_date = formatdate("YYYY-MM-01'T'00:00:00Z", timestamp())
  }

  # One notification per threshold (each carrying the full email list). A
  # per-email dynamic would blow past Azure's 5-notifications-per-budget cap
  # once more than two addresses are configured.
  dynamic "notification" {
    for_each = length(var.budget_alert_emails) > 0 ? toset(["90", "100"]) : toset([])
    content {
      enabled        = true
      threshold      = tonumber(notification.value)
      operator       = "GreaterThanOrEqualTo"
      threshold_type = notification.value == "100" ? "Forecasted" : "Actual"
      contact_emails = var.budget_alert_emails
    }
  }

  lifecycle {
    ignore_changes = [time_period[0].start_date]
  }
}

# -----------------------------------------------------------------------
# Private networking (policy-locked tenants) - VNet + delegated subnets.
# Only instantiated when enable_private_networking = true; the default
# public path never creates a VNet (see variables.tf).
# -----------------------------------------------------------------------
module "network" {
  count                   = var.enable_private_networking ? 1 : 0
  source                  = "./modules/network"
  name                    = "vnet-${var.workload}${local.full_suffix}"
  location                = var.region
  resource_group_name     = module.resource_group.name
  enable_functions_subnet = var.enable_dev_operations_gateway
  tags                    = local.tags
}

# -----------------------------------------------------------------------
# Observability - Log Analytics first because Container Apps depend on it.
# -----------------------------------------------------------------------
module "log_analytics" {
  source              = "./modules/observability/log-analytics"
  name                = "log-${var.workload}${local.full_suffix}"
  location            = var.region
  resource_group_name = module.resource_group.name
  retention_days      = var.log_retention_days
  tags                = local.tags
}

resource "azurerm_application_insights" "core" {
  name                = "appi-${var.workload}${local.full_suffix}"
  location            = var.region
  resource_group_name = module.resource_group.name
  workspace_id        = module.log_analytics.workspace_id
  application_type    = "web"
  retention_in_days   = var.log_retention_days
  tags                = local.tags
}

# -----------------------------------------------------------------------
# Container Registry - pin-by-digest images live here.
# -----------------------------------------------------------------------
module "container_registry" {
  source              = "./modules/container-registry"
  name                = "cr${var.workload}${local.acr_suffix}"
  location            = var.region
  resource_group_name = module.resource_group.name
  sku                 = var.acr_sku
  tags                = local.tags
}

# Grant the executor MI `AcrPull` so the Container App can pull an image
# a fork pushes to this ACR. Upstream's default `core_image` points at
# `mcr.microsoft.com/...` (anonymous pull, no role needed), but the
# role assignment is idempotent and lets a fork override `core_image`
# with an ACR-hosted digest without extra IAM work.
resource "azurerm_role_assignment" "executor_acr_pull" {
  scope                = module.container_registry.id
  role_definition_name = "AcrPull"
  principal_id         = module.identity.principal_id
}

# -----------------------------------------------------------------------
# Executor Managed Identity - RG-scoped, action-whitelisted (Phase 1 = Change).
# -----------------------------------------------------------------------
module "identity" {
  source              = "./modules/identity/user-assigned-mi"
  name                = "id-${var.workload}${local.full_suffix}-executor"
  resource_group_name = module.resource_group.name
  location            = var.region
  tags                = local.tags
}

# Inventory discovery has read-only management-plane authority and is kept
# separate from the privileged executor principal.
module "inventory_identity" {
  source              = "./modules/identity/user-assigned-mi"
  name                = "id-${var.workload}${local.full_suffix}-inventory"
  resource_group_name = module.resource_group.name
  location            = var.region
  tags                = local.tags
}

module "canary_identity" {
  source              = "./modules/identity/user-assigned-mi"
  name                = "id-${var.workload}${local.full_suffix}-canary"
  resource_group_name = module.resource_group.name
  location            = var.region
  tags                = merge(local.tags, { "fdai:component" = "control-loop-canary" })
}

module "notification_identity" {
  count               = var.enable_email_notifications ? 1 : 0
  source              = "./modules/identity/user-assigned-mi"
  name                = "id-${var.workload}${local.full_suffix}-notification"
  resource_group_name = module.resource_group.name
  location            = var.region
  tags                = merge(local.tags, { "fdai:component" = "notification-delivery" })
}

# Read API identity is intentionally distinct from the executor. It can pull
# the API image and read the state-store DSN, but receives no VM Run Command or
# mutation role. This preserves the console/proposal identity boundary.
module "read_api_identity" {
  count               = var.enable_read_api ? 1 : 0
  source              = "./modules/identity/user-assigned-mi"
  name                = "id-${var.workload}${local.full_suffix}-readapi"
  resource_group_name = module.resource_group.name
  location            = var.region
  tags                = local.tags
}

module "command_api_identity" {
  count               = var.enable_read_api ? 1 : 0
  source              = "./modules/identity/user-assigned-mi"
  name                = "id-${var.workload}${local.full_suffix}-command"
  resource_group_name = module.resource_group.name
  location            = var.region
  tags                = merge(local.tags, { "fdai:component" = "command-transport" })
}

module "dev_gateway_reader_identity" {
  count               = var.enable_dev_operations_gateway ? 1 : 0
  source              = "./modules/identity/user-assigned-mi"
  name                = "id-${var.workload}${local.full_suffix}-devgw-reader"
  resource_group_name = module.resource_group.name
  location            = var.region
  tags                = merge(local.tags, { "fdai:component" = "dev-operations-gateway" })
}

module "dev_gateway_executor_identity" {
  count               = var.enable_dev_operations_gateway ? 1 : 0
  source              = "./modules/identity/user-assigned-mi"
  name                = "id-${var.workload}${local.full_suffix}-devgw-executor"
  resource_group_name = module.resource_group.name
  location            = var.region
  tags                = merge(local.tags, { "fdai:component" = "dev-operations-gateway" })
}

resource "azurerm_role_assignment" "dev_gateway_reader" {
  count                = var.enable_dev_operations_gateway ? 1 : 0
  scope                = module.resource_group.id
  role_definition_name = "Reader"
  principal_id         = module.dev_gateway_reader_identity[0].principal_id
}

resource "azurerm_role_assignment" "dev_gateway_executor_network" {
  count                = var.enable_dev_operations_gateway ? 1 : 0
  scope                = module.resource_group.id
  role_definition_name = "Network Contributor"
  principal_id         = module.dev_gateway_executor_identity[0].principal_id
}

resource "azurerm_role_assignment" "dev_gateway_executor_vm" {
  count                = var.enable_dev_operations_gateway ? 1 : 0
  scope                = module.resource_group.id
  role_definition_name = "Virtual Machine Contributor"
  principal_id         = module.dev_gateway_executor_identity[0].principal_id
}

module "ingestion_identity" {
  count               = var.enable_document_ingestion ? 1 : 0
  source              = "./modules/identity/user-assigned-mi"
  name                = "id-${var.workload}${local.full_suffix}-ingestion"
  resource_group_name = module.resource_group.name
  location            = var.region
  tags                = merge(local.tags, { "fdai:component" = "document-ingestion" })
}

resource "azurerm_role_assignment" "read_api_acr_pull" {
  count                = var.enable_read_api ? 1 : 0
  scope                = module.container_registry.id
  role_definition_name = "AcrPull"
  principal_id         = module.read_api_identity[0].principal_id
}

# -----------------------------------------------------------------------
# Notification delivery - ACS Email with an Azure-managed sender domain.
# -----------------------------------------------------------------------
resource "azurerm_communication_service" "notifications" {
  count               = var.enable_email_notifications ? 1 : 0
  name                = "acs-${var.workload}${local.full_suffix}"
  resource_group_name = module.resource_group.name
  data_location       = var.email_data_location
  tags                = merge(local.tags, { "fdai:component" = "notification-delivery" })
}

resource "azurerm_email_communication_service" "notifications" {
  count               = var.enable_email_notifications ? 1 : 0
  name                = "ec-${var.workload}${local.full_suffix}"
  resource_group_name = module.resource_group.name
  data_location       = var.email_data_location
  tags                = merge(local.tags, { "fdai:component" = "notification-delivery" })
}

resource "azurerm_email_communication_service_domain" "notifications" {
  count             = var.enable_email_notifications ? 1 : 0
  name              = "AzureManagedDomain"
  email_service_id  = azurerm_email_communication_service.notifications[0].id
  domain_management = "AzureManaged"
  tags              = merge(local.tags, { "fdai:component" = "notification-delivery" })
}

resource "azurerm_communication_service_email_domain_association" "notifications" {
  count                    = var.enable_email_notifications ? 1 : 0
  communication_service_id = azurerm_communication_service.notifications[0].id
  email_service_domain_id  = azurerm_email_communication_service_domain.notifications[0].id
}

resource "azurerm_role_assignment" "notification_email_sender" {
  count                = var.enable_email_notifications ? 1 : 0
  name                 = uuidv5("url", "fdai.notification-email-sender:${azurerm_communication_service.notifications[0].id}")
  scope                = azurerm_communication_service.notifications[0].id
  role_definition_name = "Communication and Email Service Owner"
  principal_id         = module.notification_identity[0].principal_id
}

import {
  for_each = var.import_existing_email_notifications ? toset(["notification"]) : toset([])
  to       = module.notification_identity[0].azurerm_user_assigned_identity.primary
  id       = "/subscriptions/${data.azurerm_client_config.current.subscription_id}/resourceGroups/rg-${var.workload}${local.full_suffix}/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-${var.workload}${local.full_suffix}-notification"
}

import {
  for_each = var.import_existing_email_notifications ? toset(["notification"]) : toset([])
  to       = azurerm_communication_service.notifications[0]
  id       = "/subscriptions/${data.azurerm_client_config.current.subscription_id}/resourceGroups/rg-${var.workload}${local.full_suffix}/providers/Microsoft.Communication/communicationServices/acs-${var.workload}${local.full_suffix}"
}

import {
  for_each = var.import_existing_email_notifications ? toset(["notification"]) : toset([])
  to       = azurerm_email_communication_service.notifications[0]
  id       = "/subscriptions/${data.azurerm_client_config.current.subscription_id}/resourceGroups/rg-${var.workload}${local.full_suffix}/providers/Microsoft.Communication/emailServices/ec-${var.workload}${local.full_suffix}"
}

import {
  for_each = var.import_existing_email_notifications ? toset(["notification"]) : toset([])
  to       = azurerm_email_communication_service_domain.notifications[0]
  id       = "/subscriptions/${data.azurerm_client_config.current.subscription_id}/resourceGroups/rg-${var.workload}${local.full_suffix}/providers/Microsoft.Communication/emailServices/ec-${var.workload}${local.full_suffix}/domains/AzureManagedDomain"
}

import {
  for_each = var.import_existing_email_notifications ? toset(["notification"]) : toset([])
  to       = azurerm_communication_service_email_domain_association.notifications[0]
  id       = "/subscriptions/${data.azurerm_client_config.current.subscription_id}/resourceGroups/rg-${var.workload}${local.full_suffix}/providers/Microsoft.Communication/communicationServices/acs-${var.workload}${local.full_suffix}|/subscriptions/${data.azurerm_client_config.current.subscription_id}/resourceGroups/rg-${var.workload}${local.full_suffix}/providers/Microsoft.Communication/emailServices/ec-${var.workload}${local.full_suffix}/domains/AzureManagedDomain"
}

import {
  for_each = var.import_existing_email_notifications ? toset(["notification"]) : toset([])
  to       = azurerm_role_assignment.notification_email_sender[0]
  id       = "/subscriptions/${data.azurerm_client_config.current.subscription_id}/resourceGroups/rg-${var.workload}${local.full_suffix}/providers/Microsoft.Communication/communicationServices/acs-${var.workload}${local.full_suffix}/providers/Microsoft.Authorization/roleAssignments/${uuidv5("url", "fdai.notification-email-sender:/subscriptions/${data.azurerm_client_config.current.subscription_id}/resourceGroups/rg-${var.workload}${local.full_suffix}/providers/Microsoft.Communication/communicationServices/acs-${var.workload}${local.full_suffix}")}"
}

resource "azurerm_role_assignment" "command_api_eventhubs_sender" {
  for_each = var.enable_read_api ? {
    (local.event_topics[0]) = module.event_bus.topic_ids[local.event_topics[0]]
    "aw.hil.decisions"      = module.event_bus.auxiliary_topic_ids["aw.hil.decisions"]
  } : {}
  scope                = each.value
  role_definition_name = "Azure Event Hubs Data Sender"
  principal_id         = module.command_api_identity[0].principal_id
}

resource "azurerm_role_assignment" "command_api_eventhubs_receiver" {
  for_each = var.enable_read_api ? {
    "aw.pipeline.stages" = module.event_bus.auxiliary_topic_ids["aw.pipeline.stages"]
  } : {}
  scope                = each.value
  role_definition_name = "Azure Event Hubs Data Receiver"
  principal_id         = module.command_api_identity[0].principal_id
}

resource "azurerm_role_assignment" "read_api_reader" {
  count                = var.enable_read_api ? 1 : 0
  scope                = module.resource_group.id
  role_definition_name = "Reader"
  principal_id         = module.read_api_identity[0].principal_id
}

resource "azurerm_role_assignment" "ingestion_acr_pull" {
  count                = var.enable_document_ingestion ? 1 : 0
  scope                = module.container_registry.id
  role_definition_name = "AcrPull"
  principal_id         = module.ingestion_identity[0].principal_id
}

resource "azurerm_role_assignment" "ingestion_eventhubs_sender" {
  count                = var.enable_document_ingestion ? 1 : 0
  scope                = module.event_bus.auxiliary_topic_ids["aw.pipeline.stages"]
  role_definition_name = "Azure Event Hubs Data Sender"
  principal_id         = module.ingestion_identity[0].principal_id
}

resource "azurerm_role_assignment" "ingestion_eventhubs_receiver" {
  count                = var.enable_document_ingestion ? 1 : 0
  scope                = module.event_bus.auxiliary_topic_ids["aw.pipeline.stages"]
  role_definition_name = "Azure Event Hubs Data Receiver"
  principal_id         = module.ingestion_identity[0].principal_id
}

resource "azurerm_role_assignment" "ingestion_ocr_user" {
  count                = var.enable_document_ingestion && var.document_ocr_resource_id != "" ? 1 : 0
  scope                = var.document_ocr_resource_id
  role_definition_name = "Cognitive Services User"
  principal_id         = module.ingestion_identity[0].principal_id
}

resource "azurerm_role_assignment" "inventory_reader" {
  scope                = "/subscriptions/${data.azurerm_client_config.current.subscription_id}"
  role_definition_name = "Reader"
  principal_id         = module.inventory_identity.principal_id
}

resource "azurerm_role_assignment" "inventory_acr_pull" {
  scope                = module.container_registry.id
  role_definition_name = "AcrPull"
  principal_id         = module.inventory_identity.principal_id
}

resource "azurerm_role_assignment" "inventory_eventhubs_sender" {
  scope                = module.event_bus.topic_ids[local.event_topics[0]]
  role_definition_name = "Azure Event Hubs Data Sender"
  principal_id         = module.inventory_identity.principal_id
}

resource "azurerm_role_assignment" "inventory_eventhubs_raw_sender" {
  scope                = module.event_bus_auxiliary.auxiliary_topic_ids[local.inventory_raw_topic]
  role_definition_name = "Azure Event Hubs Data Sender"
  principal_id         = module.inventory_identity.principal_id
}

data "azurerm_resources" "eventgrid_system_topics" {
  type = "Microsoft.EventGrid/systemTopics"
}

locals {
  tracked_subscription_system_topics = [
    for topic in data.azurerm_resources.eventgrid_system_topics.resources : topic
    if topic.location == "global" && startswith(
      topic.name,
      data.azurerm_client_config.current.subscription_id,
    )
  ]
}

import {
  for_each = var.enable_realtime_inventory_discovery && length(local.tracked_subscription_system_topics) == 1 ? {
    existing = one(local.tracked_subscription_system_topics)
  } : {}
  to = azurerm_eventgrid_system_topic.inventory_resource_changes[0]
  id = each.value.id
}

resource "azurerm_eventgrid_system_topic" "inventory_resource_changes" {
  count = var.enable_realtime_inventory_discovery ? 1 : 0
  name = (
    length(local.tracked_subscription_system_topics) == 1
    ? one(local.tracked_subscription_system_topics).name
    : "evgst-${var.workload}${local.full_suffix}-inventory"
  )
  resource_group_name = (
    length(local.tracked_subscription_system_topics) == 1
    ? one(local.tracked_subscription_system_topics).resource_group_name
    : module.resource_group.name
  )
  location           = "global"
  source_resource_id = "/subscriptions/${data.azurerm_client_config.current.subscription_id}"
  topic_type         = "microsoft.resources.subscriptions"
  tags               = merge(local.tags, { "fdai:component" = "realtime-inventory" })

  identity {
    type         = "UserAssigned"
    identity_ids = [module.inventory_identity.resource_id]
  }

  lifecycle {
    precondition {
      condition     = length(local.tracked_subscription_system_topics) <= 1
      error_message = "multiple tracked Event Grid system topics match the Azure subscription source."
    }
  }
}

resource "azurerm_eventgrid_system_topic_event_subscription" "inventory_resource_changes" {
  count = var.enable_realtime_inventory_discovery ? 1 : 0

  name                  = "evgs-${var.workload}${local.full_suffix}-inventory"
  resource_group_name   = azurerm_eventgrid_system_topic.inventory_resource_changes[0].resource_group_name
  system_topic          = azurerm_eventgrid_system_topic.inventory_resource_changes[0].name
  eventhub_endpoint_id  = module.event_bus_auxiliary.auxiliary_topic_ids[local.inventory_raw_topic]
  event_delivery_schema = "EventGridSchema"
  included_event_types = [
    "Microsoft.Resources.ResourceWriteSuccess",
    "Microsoft.Resources.ResourceDeleteSuccess",
  ]

  delivery_identity {
    type                   = "UserAssigned"
    user_assigned_identity = module.inventory_identity.resource_id
  }

  retry_policy {
    event_time_to_live    = 1440
    max_delivery_attempts = 30
  }

  depends_on = [azurerm_role_assignment.inventory_eventhubs_raw_sender]
}

resource "azurerm_role_assignment" "canary_acr_pull" {
  scope                = module.container_registry.id
  role_definition_name = "AcrPull"
  principal_id         = module.canary_identity.principal_id
}

resource "azurerm_role_assignment" "canary_eventhubs_sender" {
  scope                = module.event_bus_auxiliary.topic_ids[local.canary_topic]
  role_definition_name = "Azure Event Hubs Data Sender"
  principal_id         = module.canary_identity.principal_id
}

# -----------------------------------------------------------------------
# Per-vertical Managed Identities - phase-3 § Unified Control Loop.
# Each vertical (Change / Resilience / FinOps) executes under its own MI
# so blast radius is bounded by vertical (no vertical can assume
# another's identity). The executor MI above stays as the aggregate
# "action-router" identity; individual verticals attach these MIs when
# invoking their delivery adapters. Role assignments (per-vertical
# action whitelists) land in fork-specific policy modules - this
# module only guarantees the MI resources exist.
# -----------------------------------------------------------------------
module "identity_change" {
  source              = "./modules/identity/user-assigned-mi"
  name                = "id-${var.workload}${local.full_suffix}-change"
  resource_group_name = module.resource_group.name
  location            = var.region
  tags                = merge(local.tags, { "fdai:vertical" = "change-safety" })
}

module "identity_resilience" {
  source              = "./modules/identity/user-assigned-mi"
  name                = "id-${var.workload}${local.full_suffix}-resilience"
  resource_group_name = module.resource_group.name
  location            = var.region
  tags                = merge(local.tags, { "fdai:vertical" = "resilience" })
}

module "identity_finops" {
  source              = "./modules/identity/user-assigned-mi"
  name                = "id-${var.workload}${local.full_suffix}-finops"
  resource_group_name = module.resource_group.name
  location            = var.region
  tags                = merge(local.tags, { "fdai:vertical" = "cost-governance" })
}

# -----------------------------------------------------------------------
# Key Vault - secret store. Executor MI has 'Secrets User' via role assignment.
# -----------------------------------------------------------------------
module "key_vault" {
  source                = "./modules/secret-store/key-vault"
  name                  = "kv-${var.workload}${local.full_suffix}"
  location              = var.region
  resource_group_name   = module.resource_group.name
  tenant_id             = var.tenant_id
  executor_principal_id = module.identity.principal_id
  tags                  = local.tags

  # Private-networking tenants lock the vault: no public plane access, and
  # network ACLs default-deny (the private endpoint below is the only path in).
  # The public path keeps the day-zero Enabled + Allow posture.
  public_network_access_enabled = !var.enable_private_networking
  network_acls_default_action   = var.enable_private_networking ? "Deny" : "Allow"

  # Hardening knobs (default to dev posture; tighten via tfvars for prod).
  purge_protection_enabled   = var.kv_purge_protection_enabled
  soft_delete_retention_days = var.kv_soft_delete_retention_days
}

resource "azurerm_role_assignment" "inventory_kv_secrets_user" {
  scope                = azurerm_key_vault_secret.state_store_dsn.resource_versionless_id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = module.inventory_identity.principal_id
}

resource "azurerm_role_assignment" "read_api_kv_secrets_user" {
  count                = var.enable_read_api ? 1 : 0
  scope                = azurerm_key_vault_secret.state_store_dsn.resource_versionless_id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = module.read_api_identity[0].principal_id
}

resource "azurerm_role_assignment" "ingestion_kv_secrets_user" {
  count                = var.enable_document_ingestion ? 1 : 0
  scope                = azurerm_key_vault_secret.state_store_dsn.resource_versionless_id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = module.ingestion_identity[0].principal_id
}

# -----------------------------------------------------------------------
# Governed document storage - StorageV2 with ADLS Gen2 HNS.
# -----------------------------------------------------------------------
module "document_storage" {
  count  = var.enable_document_ingestion ? 1 : 0
  source = "./modules/storage/adls-gen2"

  name                            = substr("st${var.workload}doc${local.acr_suffix}${local.storage_unique_suffix}", 0, 24)
  resource_group_name             = module.resource_group.name
  location                        = var.region
  deployer_principal_id           = data.azurerm_client_config.current.object_id
  replication_type                = var.document_storage_replication_type
  public_network_access_enabled   = !var.enable_private_networking
  soft_delete_retention_days      = var.document_soft_delete_retention_days
  container_delete_retention_days = var.document_soft_delete_retention_days
  quarantine_retention_days       = var.document_quarantine_retention_days
  derived_cool_after_days         = var.document_derived_cool_after_days
  private_link_access = var.enable_private_networking ? {
    defender_storage_data_scanner = {
      endpoint_resource_id = "/subscriptions/${data.azurerm_client_config.current.subscription_id}/providers/Microsoft.Security/datascanners/StorageDataScanner"
      endpoint_tenant_id   = var.tenant_id
    }
  } : {}
  tags = merge(local.tags, { "fdai:component" = "document-ingestion" })
}

resource "azurerm_role_assignment" "ingestion_document_data" {
  count                = var.enable_document_ingestion ? 1 : 0
  scope                = module.document_storage[0].id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = module.ingestion_identity[0].principal_id
}

# Key Vault private endpoint + private DNS (privatelink.vaultcore.azure.net).
# Only when private networking is on; this is what lets a VNet-resident deploy
# host (CI runner / jumpbox) and the VNet-integrated Container App reach the
# locked vault.
module "kv_private_endpoint" {
  count                 = var.enable_private_networking ? 1 : 0
  source                = "./modules/private-endpoint"
  name                  = "pe-kv-${var.workload}${local.full_suffix}"
  location              = var.region
  resource_group_name   = module.resource_group.name
  subnet_id             = module.network[0].pe_subnet_id
  vnet_id               = module.network[0].vnet_id
  target_resource_id    = module.key_vault.id
  subresource_name      = "vault"
  private_dns_zone_name = "privatelink.vaultcore.azure.net"
  tags                  = local.tags

  # Link the KV private DNS zone to the ops/hub VNet too, so the deploy runner
  # (which lives in the peered ops VNet) resolves the vault privately and can
  # write the persistence DSN secrets during apply.
  extra_vnet_links = var.runner_vnet_id != "" ? { ops = var.runner_vnet_id } : {}
}

module "document_blob_private_endpoint" {
  count                 = var.enable_document_ingestion && var.enable_private_networking ? 1 : 0
  source                = "./modules/private-endpoint"
  name                  = "pe-doc-blob-${var.workload}${local.full_suffix}"
  location              = var.region
  resource_group_name   = module.resource_group.name
  subnet_id             = module.network[0].pe_subnet_id
  vnet_id               = module.network[0].vnet_id
  target_resource_id    = module.document_storage[0].id
  subresource_name      = "blob"
  private_dns_zone_name = "privatelink.blob.core.windows.net"
  extra_vnet_links      = {}
  tags                  = local.tags
}

# -----------------------------------------------------------------------
# Development-only operations gateway - authenticated FC1 Function App.
# -----------------------------------------------------------------------
resource "azurerm_storage_account" "dev_gateway" {
  count                    = var.enable_dev_operations_gateway ? 1 : 0
  name                     = substr("st${var.workload}gw${local.acr_suffix}${local.storage_unique_suffix}", 0, 24)
  resource_group_name      = module.resource_group.name
  location                 = var.region
  account_tier             = "Standard"
  account_replication_type = "LRS"
  account_kind             = "StorageV2"

  public_network_access_enabled   = false
  shared_access_key_enabled       = false
  default_to_oauth_authentication = true
  allow_nested_items_to_be_public = false
  min_tls_version                 = "TLS1_2"
  tags                            = merge(local.tags, { "fdai:component" = "dev-operations-gateway" })
}

resource "azurerm_role_assignment" "dev_gateway_storage_deployer" {
  count                = var.enable_dev_operations_gateway ? 1 : 0
  scope                = azurerm_storage_account.dev_gateway[0].id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = data.azurerm_client_config.current.object_id
}

resource "azurerm_role_assignment" "dev_gateway_storage_runtime" {
  count                = var.enable_dev_operations_gateway ? 1 : 0
  scope                = azurerm_storage_account.dev_gateway[0].id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = module.dev_gateway_reader_identity[0].principal_id
}

resource "azurerm_role_assignment" "dev_gateway_storage_host" {
  count                = var.enable_dev_operations_gateway ? 1 : 0
  scope                = azurerm_storage_account.dev_gateway[0].id
  role_definition_name = "Storage Blob Data Owner"
  principal_id         = module.dev_gateway_reader_identity[0].principal_id
}

module "dev_gateway_blob_private_endpoint" {
  count                 = var.enable_dev_operations_gateway && !var.enable_document_ingestion ? 1 : 0
  source                = "./modules/private-endpoint"
  name                  = "pe-devgw-blob-${var.workload}${local.full_suffix}"
  location              = var.region
  resource_group_name   = module.resource_group.name
  subnet_id             = module.network[0].pe_subnet_id
  vnet_id               = module.network[0].vnet_id
  target_resource_id    = azurerm_storage_account.dev_gateway[0].id
  subresource_name      = "blob"
  private_dns_zone_name = "privatelink.blob.core.windows.net"
  extra_vnet_links      = var.runner_vnet_id != "" ? { ops = var.runner_vnet_id } : {}
  tags                  = merge(local.tags, { "fdai:component" = "dev-operations-gateway" })
}

resource "azurerm_private_endpoint" "dev_gateway_blob_shared_dns" {
  count               = var.enable_dev_operations_gateway && var.enable_document_ingestion ? 1 : 0
  name                = "pe-devgw-blob-${var.workload}${local.full_suffix}"
  location            = var.region
  resource_group_name = module.resource_group.name
  subnet_id           = module.network[0].pe_subnet_id
  tags                = merge(local.tags, { "fdai:component" = "dev-operations-gateway" })

  private_service_connection {
    name                           = "pe-devgw-blob-${var.workload}${local.full_suffix}-psc"
    private_connection_resource_id = azurerm_storage_account.dev_gateway[0].id
    subresource_names              = ["blob"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "default"
    private_dns_zone_ids = [module.document_blob_private_endpoint[0].private_dns_zone_id]
  }
}

resource "azurerm_storage_container" "dev_gateway_deployment" {
  count                 = var.enable_dev_operations_gateway ? 1 : 0
  name                  = "function-releases"
  storage_account_id    = azurerm_storage_account.dev_gateway[0].id
  container_access_type = "private"

  depends_on = [
    azurerm_role_assignment.dev_gateway_storage_deployer,
    module.dev_gateway_blob_private_endpoint,
    azurerm_private_endpoint.dev_gateway_blob_shared_dns,
    azurerm_virtual_network_peering.spoke_to_hub,
    azurerm_virtual_network_peering.hub_to_spoke,
  ]
}

resource "azurerm_storage_container" "dev_gateway_idempotency" {
  count                 = var.enable_dev_operations_gateway ? 1 : 0
  name                  = "operation-idempotency"
  storage_account_id    = azurerm_storage_account.dev_gateway[0].id
  container_access_type = "private"

  depends_on = [
    azurerm_role_assignment.dev_gateway_storage_deployer,
    module.dev_gateway_blob_private_endpoint,
    azurerm_private_endpoint.dev_gateway_blob_shared_dns,
    azurerm_virtual_network_peering.spoke_to_hub,
    azurerm_virtual_network_peering.hub_to_spoke,
  ]
}

resource "azurerm_service_plan" "dev_gateway" {
  count               = var.enable_dev_operations_gateway ? 1 : 0
  name                = "asp-${var.workload}${local.full_suffix}-devgw"
  resource_group_name = module.resource_group.name
  location            = var.region
  os_type             = "Linux"
  sku_name            = "FC1"
  tags                = merge(local.tags, { "fdai:component" = "dev-operations-gateway" })
}

resource "azurerm_function_app_flex_consumption" "dev_gateway" {
  count               = var.enable_dev_operations_gateway ? 1 : 0
  name                = "func-${var.workload}${local.full_suffix}-devgw-${local.storage_unique_suffix}"
  resource_group_name = module.resource_group.name
  location            = var.region
  service_plan_id     = azurerm_service_plan.dev_gateway[0].id

  runtime_name                                   = "python"
  runtime_version                                = "3.12"
  storage_container_type                         = "blobContainer"
  storage_container_endpoint                     = "${azurerm_storage_account.dev_gateway[0].primary_blob_endpoint}${azurerm_storage_container.dev_gateway_deployment[0].name}"
  storage_authentication_type                    = "UserAssignedIdentity"
  storage_user_assigned_identity_id              = module.dev_gateway_reader_identity[0].resource_id
  virtual_network_subnet_id                      = module.network[0].functions_subnet_id
  public_network_access_enabled                  = true
  https_only                                     = true
  maximum_instance_count                         = 2
  instance_memory_in_mb                          = 2048
  webdeploy_publish_basic_authentication_enabled = false

  identity {
    type = "UserAssigned"
    identity_ids = [
      module.dev_gateway_reader_identity[0].resource_id,
      module.dev_gateway_executor_identity[0].resource_id,
    ]
  }

  app_settings = {
    AzureWebJobsStorage__accountName           = azurerm_storage_account.dev_gateway[0].name
    AzureWebJobsStorage__credential            = "managedidentity"
    AzureWebJobsStorage__clientId              = module.dev_gateway_reader_identity[0].client_id
    FDAI_ENV                                   = "dev"
    FDAI_DEV_GATEWAY_ENABLED                   = "1"
    FDAI_DEV_GATEWAY_SUBSCRIPTION_ID           = data.azurerm_client_config.current.subscription_id
    FDAI_DEV_GATEWAY_RESOURCE_GROUPS           = module.resource_group.name
    FDAI_DEV_GATEWAY_CONTRIBUTOR_GROUP_ID      = var.rbac_contributors_group_id
    FDAI_DEV_GATEWAY_EXECUTOR_PRINCIPAL_ID     = module.identity.principal_id
    FDAI_DEV_GATEWAY_READER_MI_CLIENT_ID       = module.dev_gateway_reader_identity[0].client_id
    FDAI_DEV_GATEWAY_EXECUTOR_MI_CLIENT_ID     = module.dev_gateway_executor_identity[0].client_id
    FDAI_DEV_GATEWAY_IDEMPOTENCY_CONTAINER_URL = "${azurerm_storage_account.dev_gateway[0].primary_blob_endpoint}${azurerm_storage_container.dev_gateway_idempotency[0].name}"
    FDAI_DEV_GATEWAY_MUTATIONS_ENABLED         = "1"
    FDAI_DEV_GATEWAY_PRIVATE_PROBES_JSON       = var.dev_operations_gateway_private_probes_json
  }

  auth_settings_v2 {
    auth_enabled           = true
    require_authentication = true
    require_https          = true
    unauthenticated_action = "Return401"

    login {
      token_store_enabled = false
    }

    active_directory_v2 {
      client_id            = trimprefix(var.read_api_audience, "api://")
      tenant_auth_endpoint = "https://login.microsoftonline.com/${var.tenant_id}/v2.0"
      allowed_audiences    = [var.read_api_audience]
      allowed_applications = [module.identity.client_id]
    }
  }

  site_config {
    application_insights_connection_string = azurerm_application_insights.core.connection_string
    health_check_eviction_time_in_min      = 2
    health_check_path                      = "/api/health"
    minimum_tls_version                    = "1.2"
    remote_debugging_enabled               = false
    vnet_route_all_enabled                 = true
  }

  lifecycle {
    precondition {
      condition     = var.env == "dev" && var.enable_private_networking
      error_message = "enable_dev_operations_gateway requires env=dev and enable_private_networking=true."
    }
  }

  depends_on = [
    azurerm_role_assignment.dev_gateway_reader,
    azurerm_role_assignment.dev_gateway_executor_network,
    azurerm_role_assignment.dev_gateway_executor_vm,
    azurerm_role_assignment.dev_gateway_storage_runtime,
    azurerm_role_assignment.dev_gateway_storage_host,
    azurerm_storage_container.dev_gateway_idempotency,
    module.dev_gateway_blob_private_endpoint,
    azurerm_private_endpoint.dev_gateway_blob_shared_dns,
  ]
}

resource "azurerm_private_dns_a_record" "document_blob_ops" {
  count               = var.enable_document_ingestion && var.enable_private_networking && var.runner_vnet_id != "" ? 1 : 0
  name                = module.document_storage[0].name
  zone_name           = "privatelink.blob.core.windows.net"
  resource_group_name = var.ops_resource_group_name
  ttl                 = 300
  records             = [module.document_blob_private_endpoint[0].private_ip_address]
  tags                = merge(local.tags, { "fdai:component" = "document-ingestion" })

  lifecycle {
    ignore_changes = [tags]
  }
}

module "document_dfs_private_endpoint" {
  count                 = var.enable_document_ingestion && var.enable_private_networking ? 1 : 0
  source                = "./modules/private-endpoint"
  name                  = "pe-doc-dfs-${var.workload}${local.full_suffix}"
  location              = var.region
  resource_group_name   = module.resource_group.name
  subnet_id             = module.network[0].pe_subnet_id
  vnet_id               = module.network[0].vnet_id
  target_resource_id    = module.document_storage[0].id
  subresource_name      = "dfs"
  private_dns_zone_name = "privatelink.dfs.core.windows.net"
  extra_vnet_links      = var.runner_vnet_id != "" ? { ops = var.runner_vnet_id } : {}
  tags                  = local.tags
}

# -----------------------------------------------------------------------
# Spoke <-> hub VNet peering. Lets the deploy runner in the ops/hub VNet
# route to the app's private endpoints (Key Vault). Both directions are
# created here (the app owns the spoke side; the hub side is a child of the
# ops VNet, referenced by name + RG from the bootstrap outputs). Gated on a
# private-networking deploy that supplied the ops VNet coordinates.
# -----------------------------------------------------------------------
locals {
  peer_hub = var.enable_private_networking && var.runner_vnet_id != "" && var.runner_vnet_name != "" && var.ops_resource_group_name != ""
}

resource "azurerm_virtual_network_peering" "spoke_to_hub" {
  count                        = local.peer_hub ? 1 : 0
  name                         = "peer-to-ops"
  resource_group_name          = module.resource_group.name
  virtual_network_name         = module.network[0].vnet_name
  remote_virtual_network_id    = var.runner_vnet_id
  allow_virtual_network_access = true
  allow_forwarded_traffic      = true
}

resource "azurerm_virtual_network_peering" "hub_to_spoke" {
  count                        = local.peer_hub ? 1 : 0
  name                         = "peer-to-${var.workload}${local.full_suffix}"
  resource_group_name          = var.ops_resource_group_name
  virtual_network_name         = var.runner_vnet_name
  remote_virtual_network_id    = module.network[0].vnet_id
  allow_virtual_network_access = true
  allow_forwarded_traffic      = true
}

# PostgreSQL Flexible Server uses delegated-subnet private access rather than
# a private endpoint. The zone must end in postgres.database.azure.com and is
# linked to both the app VNet and, when supplied, the ops/hub runner VNet.
resource "azurerm_private_dns_zone" "postgres" {
  count               = var.enable_private_postgres ? 1 : 0
  name                = "private.postgres.database.azure.com"
  resource_group_name = module.resource_group.name
  tags                = local.tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "postgres_app" {
  count                 = var.enable_private_postgres ? 1 : 0
  name                  = "link-postgres-app"
  resource_group_name   = module.resource_group.name
  private_dns_zone_name = azurerm_private_dns_zone.postgres[0].name
  virtual_network_id    = module.network[0].vnet_id
  registration_enabled  = false
  tags                  = local.tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "postgres_ops" {
  count                 = var.enable_private_postgres && var.runner_vnet_id != "" ? 1 : 0
  name                  = "link-postgres-ops"
  resource_group_name   = module.resource_group.name
  private_dns_zone_name = azurerm_private_dns_zone.postgres[0].name
  virtual_network_id    = var.runner_vnet_id
  registration_enabled  = false
  tags                  = local.tags
}

# -----------------------------------------------------------------------
# Event Bus - Event Hubs (Kafka wire on :9093).
# -----------------------------------------------------------------------
module "event_bus" {
  source              = "./modules/event-bus/event-hubs-kafka"
  name                = "evhns-${var.workload}${local.full_suffix}"
  location            = var.region
  resource_group_name = module.resource_group.name
  topics              = local.event_topics
  auxiliary_topics    = local.event_auxiliary_topics
  tags                = local.tags
}

# Standard namespaces are limited to ten Event Hub entities. Keep the four
# governed ingress topics, their DLQs, and the two shared control topics on the
# primary namespace. Canary and raw inventory traffic use this isolated
# namespace so parser-specific consumers never share a physical topic.
module "event_bus_auxiliary" {
  source              = "./modules/event-bus/event-hubs-kafka"
  name                = "evhns-${var.workload}${local.full_suffix}-ops"
  location            = var.region
  resource_group_name = module.resource_group.name
  topics              = [local.canary_topic]
  auxiliary_topics    = [local.inventory_raw_topic]
  tags                = merge(local.tags, { "fdai:component" = "operational-signals" })
}

# Executor MI needs both send and receive on the namespace: the control
# loop consumes ingress topics via the Kafka wire on :9093 AND publishes
# DLQ / derived events. `Azure Event Hubs Data Owner` covers both without
# splitting into two role assignments; the namespace has
# `local_authentication_enabled = false` so this is the only path in.
resource "azurerm_role_assignment" "executor_eventhubs_data_owner" {
  for_each = merge(
    module.event_bus.all_topic_ids,
    module.event_bus_auxiliary.all_topic_ids,
  )
  scope                = each.value
  role_definition_name = "Azure Event Hubs Data Owner"
  principal_id         = module.identity.principal_id
}

# -----------------------------------------------------------------------
# State Store - PostgreSQL Flexible with pgvector.
# -----------------------------------------------------------------------
module "state_store" {
  source                 = "./modules/state-store/postgres-flex"
  name                   = "psql-${var.workload}${local.full_suffix}"
  location               = var.region
  resource_group_name    = module.resource_group.name
  tenant_id              = var.tenant_id
  administrator_login    = var.postgres_admin_login
  administrator_password = var.postgres_admin_password
  database_name          = var.workload
  tags                   = local.tags

  # Hardening knobs (default to dev posture; tighten via tfvars for prod).
  backup_retention_days         = var.postgres_backup_retention_days
  geo_redundant_backup_enabled  = var.postgres_geo_redundant_backup
  high_availability_mode        = var.postgres_high_availability_mode
  public_network_access_enabled = !var.enable_private_postgres
  allow_azure_services_firewall = !var.enable_private_postgres
  delegated_subnet_id           = var.enable_private_postgres ? module.network[0].postgres_subnet_id : null
  private_dns_zone_id           = var.enable_private_postgres ? azurerm_private_dns_zone.postgres[0].id : null

  depends_on = [azurerm_private_dns_zone_virtual_network_link.postgres_app]
}

# -----------------------------------------------------------------------
# Persistence DSNs - Key Vault-backed secrets consumed by the core app.
#
# Provisioning the secrets from the same apply requires the caller to hold
# `Key Vault Secrets Officer` on the vault. `kv_officer_self` grants it to
# the apply principal (the executing Entra identity) so the secret create
# does not race against a manual out-of-band RBAC step. This role is scoped
# to the vault only and never granted to the executor MI - executor keeps
# read-only `Secrets User` from the KV module.
#
# Day-zero the three DSNs point at the same database (deploy-and-onboard.md
# § PostgreSQL Flexible Server "single store"); a fork MAY split them
# without touching the core, because each is a separate env var.
# -----------------------------------------------------------------------
resource "azurerm_role_assignment" "kv_officer_self" {
  scope                = module.key_vault.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = data.azurerm_client_config.current.object_id
}

resource "azurerm_key_vault_secret" "state_store_dsn" {
  name         = "fdai-state-store-dsn"
  value        = module.state_store.application_dsn
  key_vault_id = module.key_vault.id
  content_type = "postgres-dsn"
  tags         = local.tags

  depends_on = [azurerm_role_assignment.kv_officer_self, module.kv_private_endpoint, azurerm_virtual_network_peering.spoke_to_hub, azurerm_virtual_network_peering.hub_to_spoke]
}

resource "azurerm_key_vault_secret" "chatops_webhook_url" {
  count        = var.enable_chatops_hil ? 1 : 0
  name         = "fdai-chatops-webhook-url"
  value        = var.chatops_webhook_url
  key_vault_id = module.key_vault.id
  content_type = "chatops-webhook-url"
  tags         = local.tags

  depends_on = [azurerm_role_assignment.kv_officer_self, module.kv_private_endpoint, azurerm_virtual_network_peering.spoke_to_hub, azurerm_virtual_network_peering.hub_to_spoke]
}

resource "azurerm_key_vault_secret" "chatops_webhook_secret" {
  count        = var.enable_chatops_hil ? 1 : 0
  name         = "fdai-chatops-webhook-secret"
  value        = var.chatops_webhook_secret
  key_vault_id = module.key_vault.id
  content_type = "chatops-hmac-secret"
  tags         = local.tags

  depends_on = [azurerm_role_assignment.kv_officer_self, module.kv_private_endpoint, azurerm_virtual_network_peering.spoke_to_hub, azurerm_virtual_network_peering.hub_to_spoke]
}

resource "azurerm_key_vault_secret" "gitops_token" {
  count        = var.enable_stewardship_governance ? 1 : 0
  name         = "fdai-gitops-token"
  value        = var.gitops_token
  key_vault_id = module.key_vault.id
  content_type = "github-app-installation-token"
  tags         = local.tags

  depends_on = [azurerm_role_assignment.kv_officer_self, module.kv_private_endpoint, azurerm_virtual_network_peering.spoke_to_hub, azurerm_virtual_network_peering.hub_to_spoke]
}

resource "azurerm_key_vault_secret" "github_webhook_secret" {
  count        = var.enable_stewardship_governance ? 1 : 0
  name         = "fdai-github-webhook-secret"
  value        = var.github_webhook_secret
  key_vault_id = module.key_vault.id
  content_type = "github-webhook-hmac-secret"
  tags         = local.tags

  depends_on = [azurerm_role_assignment.kv_officer_self, module.kv_private_endpoint, azurerm_virtual_network_peering.spoke_to_hub, azurerm_virtual_network_peering.hub_to_spoke]
}

resource "azurerm_key_vault_secret" "operator_memory_dsn" {
  name         = "fdai-operator-memory-dsn"
  value        = module.state_store.application_dsn
  key_vault_id = module.key_vault.id
  content_type = "postgres-dsn"
  tags         = local.tags

  depends_on = [azurerm_role_assignment.kv_officer_self, module.kv_private_endpoint, azurerm_virtual_network_peering.spoke_to_hub, azurerm_virtual_network_peering.hub_to_spoke]
}

resource "azurerm_key_vault_secret" "pattern_library_dsn" {
  name         = "fdai-pattern-library-dsn"
  value        = module.state_store.application_dsn
  key_vault_id = module.key_vault.id
  content_type = "postgres-dsn"
  tags         = local.tags

  depends_on = [azurerm_role_assignment.kv_officer_self, module.kv_private_endpoint, azurerm_virtual_network_peering.spoke_to_hub, azurerm_virtual_network_peering.hub_to_spoke]
}

# -----------------------------------------------------------------------
# Compute - Container Apps env + core app + out-of-band job.
# -----------------------------------------------------------------------
module "compute" {
  source                       = "./modules/compute/container-apps"
  env_name                     = "cae-${var.workload}${local.full_suffix}"
  core_app_name                = "ca-${var.workload}${local.full_suffix}-core"
  oob_job_name                 = "caj-${var.workload}${local.full_suffix}-oob"
  rule_watcher_job_name        = "caj-${var.workload}${local.full_suffix}-watcher"
  location                     = var.region
  resource_group_name          = module.resource_group.name
  log_workspace_id             = module.log_analytics.workspace_id
  executor_identity_id         = module.identity.resource_id
  executor_identity_client_id  = module.identity.client_id
  inventory_identity_id        = module.inventory_identity.resource_id
  inventory_identity_client_id = module.inventory_identity.client_id
  inventory_raw_topic          = local.inventory_raw_topic
  canary_identity_id           = module.canary_identity.resource_id
  canary_identity_client_id    = module.canary_identity.client_id
  canary_topic                 = local.canary_topic
  canary_cron_expression       = var.canary_cron_expression
  image                        = var.core_image
  max_replicas                 = var.max_replicas
  extra_identity_ids = (
    var.enable_email_notifications ? [module.notification_identity[0].resource_id] : []
  )

  # Private-networking: bind the Container App Environment to the delegated
  # infra subnet so the app's Key Vault references resolve the KV private
  # endpoint over the VNet. Null on the public path (no VNet integration).
  infrastructure_subnet_id = var.enable_private_networking ? module.network[0].infra_subnet_id : null

  # Wire the private ACR so image pulls authenticate via the executor MI
  # (which already holds `AcrPull` on this ACR). If the fork points
  # `core_image` at a public registry (mcr.microsoft.com / Docker Hub)
  # the Container App simply ignores this block - the pull is anonymous.
  acr_login_server = module.container_registry.login_server

  # Required config env vars - `EnvVarConfigProvider` fails-fast if any is
  # unset, so wire them all from the surrounding infra outputs.
  azure_tenant_id                     = var.tenant_id
  azure_subscription_id               = data.azurerm_client_config.current.subscription_id
  azure_resource_group                = module.resource_group.name
  azure_region                        = var.region
  kafka_bootstrap_servers             = module.event_bus.kafka_bootstrap
  operational_kafka_bootstrap_servers = module.event_bus_auxiliary.kafka_bootstrap
  kafka_topic_events                  = local.event_topics[0]
  postgres_host                       = module.state_store.fqdn
  postgres_database                   = module.state_store.database_name
  runtime_env                         = var.env == "" ? "dev" : var.env
  autonomy_mode_default               = "shadow"
  dev_operations_gateway_url = (
    var.enable_dev_operations_gateway
    ? "https://${azurerm_function_app_flex_consumption.dev_gateway[0].default_hostname}"
    : ""
  )
  dev_operations_gateway_audience = (
    var.enable_dev_operations_gateway ? var.read_api_audience : ""
  )

  # Auto-bind the Azure Monitor Logs metric adapter at composition time.
  # Threading the Log Analytics workspace **customer GUID** (NOT the ARM
  # resource id - `azurerm_log_analytics_workspace` calls the ARM id `id`
  # and the customer GUID `workspace_id`) makes
  # `wire_azure_container` swap `NoopMetricProvider` for the live adapter
  # so the deterministic detection pipeline sees real telemetry with no
  # fork required. See src/fdai/composition/wire_azure.py.
  monitor_workspace_customer_id = module.log_analytics.workspace_customer_id

  email_endpoint = (
    var.enable_email_notifications
    ? "https://${azurerm_communication_service.notifications[0].hostname}"
    : ""
  )
  email_sender_address = (
    var.enable_email_notifications
    ? "DoNotReply@${azurerm_email_communication_service_domain.notifications[0].from_sender_domain}"
    : ""
  )
  email_recipient_addresses_json = jsonencode(var.notification_email_recipients)
  notification_identity_client_id = (
    var.enable_email_notifications ? module.notification_identity[0].client_id : ""
  )

  # Persistence DSNs (KV-backed; executor MI reads at runtime).
  state_store_dsn_secret_id     = azurerm_key_vault_secret.state_store_dsn.id
  operator_memory_dsn_secret_id = azurerm_key_vault_secret.operator_memory_dsn.id
  pattern_library_dsn_secret_id = azurerm_key_vault_secret.pattern_library_dsn.id
  chatops_webhook_url_secret_id = (
    var.enable_chatops_hil ? azurerm_key_vault_secret.chatops_webhook_url[0].id : ""
  )
  chatops_webhook_secret_id = (
    var.enable_chatops_hil ? azurerm_key_vault_secret.chatops_webhook_secret[0].id : ""
  )
  inventory_dsn_secret_id     = azurerm_key_vault_secret.state_store_dsn.id
  inventory_cron_expression   = var.inventory_cron_expression
  inventory_sources           = var.inventory_sources
  inventory_freshness_seconds = var.inventory_freshness_seconds

  # DB-DR drill (opt-in; the fork toggles dr_drill_enabled + supplies the
  # source server ARM id once the runbook in docs/runbooks/db-dr-drill.md
  # is signed off. Upstream keeps it disabled.).
  dr_drill_enabled              = var.dr_drill_enabled
  dr_drill_job_name             = "caj-${var.workload}${local.full_suffix}-drill"
  dr_drill_source_server_arm_id = var.dr_drill_source_server_arm_id
  dr_drill_dry_run              = var.dr_drill_dry_run

  # Metric analyzer tick (opt-in) - drives the reference threshold
  # analyzers so metric-based scenarios (node_cpu_percent, http_429_rate,
  # ...) get near-real-time detection instead of sitting dark. Empty
  # cron (default) leaves the job unprovisioned; a fork sets a cadence
  # + targets JSON + optional Prom endpoint to enable. See
  # docs/roadmap/rules-and-detection/observability-and-detection.md.
  analyzer_tick_cron_expression = var.analyzer_tick_cron_expression
  analyzer_targets_json         = var.analyzer_targets_json
  analyzer_window_seconds       = var.analyzer_window_seconds
  analyzer_budget_seconds       = var.analyzer_budget_seconds
  prometheus_endpoint           = var.prometheus_endpoint
  prometheus_audience           = var.prometheus_audience
  vm_task_enabled               = var.vm_task_enabled
  vm_task_enforce               = var.vm_task_enforce
  vm_task_run_as_user           = var.vm_task_run_as_user
  vm_task_root                  = var.vm_task_root
  scheduler_cron_expression = (
    var.vm_task_enabled && var.scheduler_tick_cron_expression == ""
    ? "* * * * *"
    : var.scheduler_tick_cron_expression
  )

  tags = local.tags

  # Wait for every runtime prerequisite:
  #   - KV secrets present and the executor MI has Secrets User on them.
  #   - Postgres firewall lets the Container App outbound IPs in
  #     (`module.state_store` is a superset that also covers the DB + the
  #     server itself; using the module handle keeps this correct if the
  #     firewall resource gets renamed).
  #   - Event Hubs Data Owner effective for Kafka OAUTHBEARER.
  #   - AcrPull effective on the ACR (matters once the fork's image is
  #     pushed there; upstream default pulls from MCR which needs no role).
  # Without these `depends_on` edges Terraform can create the Container
  # App revision first, watch it crash-loop on missing IAM, and only
  # then finish the role assignments a minute or two later.
  depends_on = [
    module.state_store,
    azurerm_key_vault_secret.state_store_dsn,
    azurerm_key_vault_secret.operator_memory_dsn,
    azurerm_key_vault_secret.pattern_library_dsn,
    azurerm_role_assignment.executor_eventhubs_data_owner,
    azurerm_role_assignment.executor_acr_pull,
    azurerm_role_assignment.inventory_reader,
    azurerm_role_assignment.inventory_kv_secrets_user,
    azurerm_role_assignment.inventory_acr_pull,
    azurerm_role_assignment.inventory_eventhubs_sender,
    azurerm_role_assignment.canary_acr_pull,
    azurerm_role_assignment.canary_eventhubs_sender,
    azurerm_communication_service_email_domain_association.notifications,
    azurerm_role_assignment.notification_email_sender,
  ]
}


# -----------------------------------------------------------------------
# LLM - Azure OpenAI (opt-in, docs/roadmap/deployment/dev-and-deploy-parity.md § W-D).
# Skipped by default so a Reader-only deployer can plan/apply.
# -----------------------------------------------------------------------
module "llm_azure_openai" {
  count  = var.enable_llm ? 1 : 0
  source = "./modules/llm/azure-openai"

  name                  = "oai-${var.workload}${local.full_suffix}"
  location              = var.region
  resource_group_name   = module.resource_group.name
  executor_principal_id = module.identity.principal_id
  additional_user_principal_ids = (
    merge(
      var.enable_read_api
      ? { read_api = module.read_api_identity[0].principal_id }
      : {},
      var.enable_document_ingestion
      ? { ingestion = module.ingestion_identity[0].principal_id }
      : {},
    )
  )
  resolved_capabilities = var.resolved_capabilities
  tags                  = local.tags
}

module "model_apim_gateway" {
  count  = var.enable_model_apim_gateway ? 1 : 0
  source = "./modules/llm/apim-ai-gateway"

  resource_group_name = var.model_apim_gateway == null ? "" : var.model_apim_gateway.resource_group_name
  api_management_name = var.model_apim_gateway == null ? "" : var.model_apim_gateway.api_management_name
  gateway_url         = var.model_apim_gateway == null ? "https://example.com" : var.model_apim_gateway.gateway_url
  api_name            = var.model_apim_gateway == null ? "disabled" : var.model_apim_gateway.api_name
  api_path            = var.model_apim_gateway == null ? "disabled/path" : var.model_apim_gateway.api_path
  frontend_tenant_id  = var.model_apim_gateway == null ? "" : var.model_apim_gateway.frontend_tenant_id
  frontend_audience   = var.model_apim_gateway == null ? "" : var.model_apim_gateway.frontend_audience
  api_version         = var.model_apim_gateway == null ? "2024-10-21" : var.model_apim_gateway.api_version
  apim_principal_id   = var.model_apim_gateway == null ? "" : var.model_apim_gateway.apim_principal_id
  ptu_backend = var.model_apim_gateway == null ? {
    name        = "disabled-ptu"
    url         = "https://example.com/openai/deployments/disabled-ptu"
    resource_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/example/providers/Microsoft.CognitiveServices/accounts/example"
  } : var.model_apim_gateway.ptu_backend
  standard_backend = var.model_apim_gateway == null ? {
    name        = "disabled-standard"
    url         = "https://example.com/openai/deployments/disabled-standard"
    resource_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/example/providers/Microsoft.CognitiveServices/accounts/example"
  } : var.model_apim_gateway.standard_backend
}

module "llm_private_endpoint" {
  count                 = var.enable_llm && var.enable_private_networking ? 1 : 0
  source                = "./modules/private-endpoint"
  name                  = "pe-oai-${var.workload}${local.full_suffix}"
  location              = var.region
  resource_group_name   = module.resource_group.name
  subnet_id             = module.network[0].pe_subnet_id
  vnet_id               = module.network[0].vnet_id
  target_resource_id    = module.llm_azure_openai[0].resource_id
  subresource_name      = "account"
  private_dns_zone_name = "privatelink.openai.azure.com"
  extra_vnet_links      = var.runner_vnet_id != "" ? { ops = var.runner_vnet_id } : {}
  tags                  = local.tags
}

# -----------------------------------------------------------------------
# Phase-4 continuous measurement - two Container Apps Jobs that wire the
# regression detector + pattern-growth intake into scheduled runs.
# The jobs share the same Container Apps env + user-assigned MI as the
# core app + rule watcher (least privilege - no extra role assignments).
# -----------------------------------------------------------------------
module "measurement_runners" {
  source = "./modules/measurement-runners"

  baseline_job_name            = "caj-${var.workload}${local.full_suffix}-baseline"
  growth_job_name              = "caj-${var.workload}${local.full_suffix}-growth"
  container_app_environment_id = module.compute.environment_id
  location                     = var.region
  resource_group_name          = module.resource_group.name
  executor_identity_id         = module.identity.resource_id
  image                        = var.core_image
  acr_login_server             = module.container_registry.login_server
  scenario_set_version         = var.measurement_scenario_set_version
  state_store_dsn_secret_id    = azurerm_key_vault_secret.state_store_dsn.id
  environment = merge({
    AZURE_TENANT_ID         = data.azurerm_client_config.current.tenant_id
    AZURE_SUBSCRIPTION_ID   = data.azurerm_client_config.current.subscription_id
    AZURE_REGION            = var.region
    AZURE_RESOURCE_GROUP    = module.resource_group.name
    KAFKA_BOOTSTRAP_SERVERS = module.event_bus.kafka_bootstrap
    KAFKA_TOPIC_EVENTS      = local.event_topics[0]
    POSTGRES_HOST           = module.state_store.fqdn
    POSTGRES_DATABASE       = module.state_store.database_name
    RUNTIME_ENV             = local.env_label == "day-zero" ? "dev" : local.env_label
    FDAI_MI_CLIENT_ID       = module.identity.client_id
    }, var.enable_llm ? {
    LLM_MODE                 = "azure"
    LLM_RESOLVED_MODELS_PATH = "/app/resolved-models.json"
    FDAI_LLM_ENDPOINT        = module.llm_azure_openai[0].endpoint
  } : {})
  tags = local.tags
}

# -----------------------------------------------------------------------
# Monitoring (opt-in) - action group + metric alerts + diagnostic settings
# for the control-plane resources. Alerts are a human signal only; they never
# take an autonomous action (risk-gated autonomy). Skipped by default.
# -----------------------------------------------------------------------
module "monitoring" {
  count  = var.enable_monitoring ? 1 : 0
  source = "./modules/observability/monitoring"

  workload                   = var.workload
  resource_group_name        = module.resource_group.name
  log_analytics_workspace_id = module.log_analytics.workspace_id
  action_group_name          = "ag-${var.workload}${local.full_suffix}"
  action_group_short_name    = substr(var.workload, 0, 12)
  alert_email                = var.alert_email
  alert_webhook_url          = var.alert_webhook_url

  postgres_id            = module.state_store.id
  key_vault_id           = module.key_vault.id
  event_hub_namespace_id = module.event_bus.namespace_id
  container_app_id       = module.compute.core_app_id

  tags = local.tags
}

# -----------------------------------------------------------------------
# Operator console (opt-in) - Azure Static Web App hosting the read-only
# SPA (`console/dist/`). Layer 3 in app-shape.instructions.md. The SWA is
# a passive HTTPS artifact host; the SPA issues no privileged calls, so no
# Managed Identity is attached. `console_region` is decoupled from
# var.region because Static Web Apps is not offered in every region.
# The build output is uploaded out-of-band with the SWA deployment token.
# -----------------------------------------------------------------------
module "console" {
  count  = var.enable_console ? 1 : 0
  source = "./modules/console/static-web-app"

  name                = "stapp-${var.workload}${local.full_suffix}"
  location            = var.console_region
  resource_group_name = module.resource_group.name
  tags                = local.tags
}

# -----------------------------------------------------------------------
# Operator console read API (opt-in) - Azure Container App serving
# `fdai.delivery.read_api.prod:app` with external ingress so the console
# SPA can call it cross-origin. Enforces Entra JWT + RBAC group resolution.
# Uses separate read and command-transport identities in the shared
# Container Apps Environment.
# A manual-trigger migration job runs `alembic upgrade head`. Tenant-specific
# Entra/RBAC ids arrive via CI Variables (never committed).
# -----------------------------------------------------------------------
module "read_api" {
  count  = var.enable_read_api ? 1 : 0
  source = "./modules/read-api/container-app"

  name                              = "ca-${var.workload}${local.full_suffix}-readapi"
  migrate_job_name                  = "caj-${var.workload}${local.full_suffix}-migrate"
  container_app_environment_id      = module.compute.environment_id
  location                          = var.region
  resource_group_name               = module.resource_group.name
  image                             = var.read_api_image == "" ? var.core_image : var.read_api_image
  read_api_identity_id              = module.read_api_identity[0].resource_id
  read_api_identity_client_id       = module.read_api_identity[0].client_id
  monitor_workspace_customer_id     = module.log_analytics.workspace_customer_id
  command_api_identity_id           = module.command_api_identity[0].resource_id
  command_api_identity_client_id    = module.command_api_identity[0].client_id
  resolved_models_path              = var.read_api_resolved_models_path
  narrator_probe_interval_seconds   = var.read_api_narrator_probe_interval_seconds
  web_search_enabled                = var.read_api_web_search_enabled
  web_search_allowed_domains        = var.read_api_web_search_allowed_domains
  web_search_max_results            = var.read_api_web_search_max_results
  web_search_budget_ms              = var.read_api_web_search_budget_ms
  web_search_probe_interval_seconds = var.read_api_web_search_probe_interval_seconds
  acr_login_server                  = module.container_registry.login_server
  state_store_dsn_secret_id         = azurerm_key_vault_secret.state_store_dsn.id
  chatops_webhook_secret_id = (
    var.enable_chatops_hil ? azurerm_key_vault_secret.chatops_webhook_secret[0].id : ""
  )
  entra_tenant_id                    = var.tenant_id
  api_audience                       = var.read_api_audience
  rbac_readers_group_id              = var.rbac_readers_group_id
  rbac_contributors_group_id         = var.rbac_contributors_group_id
  rbac_approvers_group_id            = var.rbac_approvers_group_id
  rbac_owners_group_id               = var.rbac_owners_group_id
  rbac_break_glass_group_id          = var.rbac_break_glass_group_id
  cors_allow_origins                 = var.read_api_cors_allow_origins
  iam_directory_provider             = var.read_api_iam_directory_provider
  stewardship_maintainers            = var.stewardship_maintainers
  stewardship_agent_bindings         = var.stewardship_agent_bindings
  stewardship_audit_interval_seconds = var.stewardship_audit_interval_seconds
  inventory_freshness_seconds        = var.inventory_freshness_seconds
  python_task_author_endpoint = (
    var.enable_llm && var.python_task_author_capability != ""
    ? module.llm_azure_openai[0].endpoint
    : ""
  )
  python_task_author_deployment = (
    var.enable_llm && var.python_task_author_capability != ""
    ? lookup(module.llm_azure_openai[0].deployments, var.python_task_author_capability, "")
    : ""
  )
  kafka_bootstrap_servers            = module.event_bus.kafka_bootstrap
  kafka_topic_events                 = local.event_topics[0]
  azure_subscription_id              = data.azurerm_client_config.current.subscription_id
  azure_resource_group               = module.resource_group.name
  executor_principal_id              = module.identity.principal_id
  executor_event_role_definition_id  = azurerm_role_assignment.executor_eventhubs_data_owner[local.event_topics[0]].role_definition_id
  executor_secret_role_definition_id = module.key_vault.executor_role_definition_id
  tags                               = local.tags

  depends_on = [
    azurerm_key_vault_secret.state_store_dsn,
    azurerm_role_assignment.read_api_acr_pull,
    azurerm_role_assignment.read_api_kv_secrets_user,
    azurerm_role_assignment.command_api_eventhubs_receiver,
    azurerm_role_assignment.command_api_eventhubs_sender,
    azurerm_role_assignment.read_api_reader,
    module.llm_azure_openai,
  ]
}

module "ingestion_gateway" {
  count  = var.enable_document_ingestion ? 1 : 0
  source = "./modules/ingestion-gateway/container-app"

  name                           = "ca-${var.workload}${local.full_suffix}-ingestion"
  migrate_job_name               = "caj-${var.workload}${local.full_suffix}-docmig"
  container_app_environment_id   = module.compute.environment_id
  location                       = var.region
  resource_group_name            = module.resource_group.name
  image                          = var.ingestion_image == "" ? var.core_image : var.ingestion_image
  clamav_image                   = var.clamav_image
  identity_id                    = module.ingestion_identity[0].resource_id
  identity_client_id             = module.ingestion_identity[0].client_id
  database_dsn_secret_id         = azurerm_key_vault_secret.state_store_dsn.id
  stewardship_governance_enabled = var.enable_stewardship_governance
  gitops_owner                   = var.gitops_owner
  gitops_repo                    = var.gitops_repo
  gitops_token_secret_id = (
    var.enable_stewardship_governance ? azurerm_key_vault_secret.gitops_token[0].id : ""
  )
  github_webhook_secret_id = (
    var.enable_stewardship_governance ? azurerm_key_vault_secret.github_webhook_secret[0].id : ""
  )
  chatops_webhook_url_secret_id = (
    var.enable_stewardship_governance ? azurerm_key_vault_secret.chatops_webhook_url[0].id : ""
  )
  stewardship_maintainers        = var.stewardship_maintainers
  stewardship_agent_bindings     = var.stewardship_agent_bindings
  entra_tenant_id                = var.tenant_id
  api_audience                   = var.read_api_audience
  rbac_readers_group_id          = var.rbac_readers_group_id
  rbac_contributors_group_id     = var.rbac_contributors_group_id
  rbac_approvers_group_id        = var.rbac_approvers_group_id
  rbac_owners_group_id           = var.rbac_owners_group_id
  rbac_break_glass_group_id      = var.rbac_break_glass_group_id
  cors_allow_origins             = var.ingestion_cors_allow_origins
  adls_account_name              = module.document_storage[0].name
  adls_account_url               = module.document_storage[0].primary_dfs_endpoint
  adls_source_file_system        = module.document_storage[0].source_file_system
  adls_derived_file_system       = module.document_storage[0].derived_file_system
  embedding_endpoint             = var.enable_llm ? module.llm_azure_openai[0].endpoint : ""
  embedding_deployment           = var.enable_llm ? lookup(module.llm_azure_openai[0].deployments, var.ingestion_embedding_capability, "") : ""
  ocr_endpoint                   = var.document_ocr_endpoint
  ocr_operation_timeout_seconds  = var.document_ocr_operation_timeout_seconds
  kafka_bootstrap_servers        = module.event_bus.kafka_bootstrap
  document_event_topic           = "aw.pipeline.stages"
  runtime_env                    = var.env == "" ? "dev" : var.env
  max_file_size_bytes            = var.document_max_file_size_bytes
  max_batch_count                = var.document_max_batch_count
  chunk_max_chars                = var.document_chunk_max_chars
  chunk_overlap                  = var.document_chunk_overlap
  indexing_stage_timeout_seconds = var.document_indexing_stage_timeout_seconds
  policy_version                 = var.document_policy_version
  document_collections           = var.document_collections
  min_replicas                   = var.ingestion_min_replicas
  max_replicas                   = var.ingestion_max_replicas
  acr_login_server               = module.container_registry.login_server
  tags                           = merge(local.tags, { "fdai:component" = "document-ingestion" })

  depends_on = [
    azurerm_role_assignment.ingestion_acr_pull,
    azurerm_role_assignment.ingestion_eventhubs_sender,
    azurerm_role_assignment.ingestion_eventhubs_receiver,
    azurerm_role_assignment.ingestion_kv_secrets_user,
    azurerm_role_assignment.ingestion_ocr_user,
    azurerm_key_vault_secret.gitops_token,
    azurerm_key_vault_secret.github_webhook_secret,
    azurerm_role_assignment.ingestion_document_data,
    module.document_blob_private_endpoint,
    module.document_dfs_private_endpoint,
  ]
}
