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
}

locals {
  # Terraform expresses capacity in units of 1k TPM per the AOAI provider.
  # The resolver emits raw tokens/min; convert here and clamp to >= 1.
  deployments_by_name = {
    for cap in var.resolved_capabilities : cap.name => merge(cap, {
      capacity_units = max(1, floor(cap.capacity_tpm / 1000))
    })
  }
}

resource "azurerm_cognitive_deployment" "capability" {
  for_each             = local.deployments_by_name
  name                 = each.value.name
  cognitive_account_id = azurerm_cognitive_account.primary.id

  model {
    format = "OpenAI"
    name   = each.value.family
    # Version is auto-picked by Azure when not pinned; the resolver records
    # the resolved family + capacity in resolved-models.json.
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
