locals {
  backend_resource_ids = toset([
    var.ptu_backend.resource_id,
    var.standard_backend.resource_id,
  ])
}

resource "azurerm_api_management_backend" "ptu" {
  # checkov:skip=CKV_AZURE_215:ptu_backend.url has an HTTPS-only variable validation.
  name                = var.ptu_backend.name
  resource_group_name = var.resource_group_name
  api_management_name = var.api_management_name
  protocol            = "http"
  url                 = trimsuffix(var.ptu_backend.url, "/")
  description         = "FDAI primary provisioned model backend."
}

resource "azurerm_api_management_backend" "standard" {
  # checkov:skip=CKV_AZURE_215:standard_backend.url has an HTTPS-only variable validation.
  name                = var.standard_backend.name
  resource_group_name = var.resource_group_name
  api_management_name = var.api_management_name
  protocol            = "http"
  url                 = trimsuffix(var.standard_backend.url, "/")
  description         = "FDAI same-family Standard spillover backend."
}

resource "azurerm_api_management_api" "model" {
  name                  = var.api_name
  resource_group_name   = var.resource_group_name
  api_management_name   = var.api_management_name
  revision              = "1"
  display_name          = "FDAI model gateway - ${var.api_name}"
  path                  = var.api_path
  protocols             = ["https"]
  subscription_required = false
}

resource "azurerm_api_management_api_operation" "chat_completions" {
  operation_id        = "chat-completions"
  api_name            = azurerm_api_management_api.model.name
  api_management_name = var.api_management_name
  resource_group_name = var.resource_group_name
  display_name        = "Chat completions"
  method              = "POST"
  url_template        = "/v1/chat/completions"
}

resource "azurerm_api_management_api_policy" "model" {
  api_name            = azurerm_api_management_api.model.name
  api_management_name = var.api_management_name
  resource_group_name = var.resource_group_name
  xml_content = templatefile("${path.module}/policy.xml.tftpl", {
    tenant_id           = var.frontend_tenant_id
    frontend_audience   = var.frontend_audience
    ptu_backend_id      = azurerm_api_management_backend.ptu.name
    standard_backend_id = azurerm_api_management_backend.standard.name
    api_version         = var.api_version
  })
}

resource "azurerm_role_assignment" "apim_openai_user" {
  for_each             = local.backend_resource_ids
  scope                = each.value
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = var.apim_principal_id
}
