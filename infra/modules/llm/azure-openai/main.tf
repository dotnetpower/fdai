resource "azurerm_cognitive_account" "primary" {
  name                          = var.name
  location                      = var.location
  resource_group_name           = var.resource_group_name
  kind                          = "OpenAI"
  sku_name                      = var.sku_name
  custom_subdomain_name         = var.name
  public_network_access_enabled = false
  local_auth_enabled            = false
  tags                          = var.tags

  # Public access remains disabled by Terraform. Tenant policy may add a deny
  # ACL and approved operator IPs; those policy-owned details must not create
  # an endless apply/remove cycle.
  lifecycle {
    ignore_changes = [network_acls]
  }
}

locals {
  # Standard deployments use 1k TPM units. Provisioned deployments use an
  # exact PTU count; dividing PTUs by 1000 would silently under-provision.
  deployments_by_name = {
    for cap in var.resolved_capabilities : cap.name => merge(cap, {
      capacity_units = (
        cap.capacity_unit == "ptu"
        ? cap.capacity_value
        : max(1, floor(cap.capacity_tpm / 1000))
      )
    })
  }
}

resource "azurerm_cognitive_deployment" "capability" {
  for_each             = local.deployments_by_name
  name                 = each.value.name
  cognitive_account_id = azurerm_cognitive_account.primary.id

  model {
    format  = "OpenAI"
    name    = each.value.family
    version = each.value.version
  }

  sku {
    name     = each.value.sku
    capacity = each.value.capacity_units
  }

}

# Runtime role: executor MI invokes deployments as an AOAI User (data-plane).
resource "azurerm_role_assignment" "executor_openai_user" {
  count                = var.grant_executor_role ? 1 : 0
  scope                = azurerm_cognitive_account.primary.id
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = var.executor_principal_id
}

resource "azurerm_role_assignment" "additional_openai_user" {
  for_each             = var.additional_user_principal_ids
  scope                = azurerm_cognitive_account.primary.id
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = each.value
}
