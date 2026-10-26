data "azurerm_resource_group" "target" {
  name = var.resource_group_name
}

locals {
  console_name = "stapp-${var.workload}-${var.environment}-${var.console_region_short}-${var.resource_name_suffix}"
  gateway_name = "apim-${var.workload}-${var.environment}-${var.region_short}-${var.resource_name_suffix}"
  tags = merge(var.tags, {
    "fdai:env"          = var.environment
    "fdai:layer"        = "development-console-gateway"
    "fdai:managed"      = "true"
    "fdai:managed-by"   = "terraform"
    "fdai:region-token" = var.region_short
    "fdai:vertical"     = "shared"
    "fdai:workload"     = var.workload
  })
}

module "console" {
  source = "../modules/console/static-web-app"

  name                = local.console_name
  location            = var.console_location
  resource_group_name = data.azurerm_resource_group.target.name
  custom_hostname     = var.console_custom_hostname
  tags                = merge(local.tags, { "fdai:component" = "console" })
}

locals {
  console_hostname = var.console_custom_hostname != "" ? var.console_custom_hostname : module.console.default_hostname
  console_origin   = "https://${local.console_hostname}"
}

module "browser_gateway" {
  source = "../modules/console/browser-gateway"

  name                              = local.gateway_name
  resource_group_name               = data.azurerm_resource_group.target.name
  location                          = var.gateway_location
  publisher_name                    = var.publisher_name
  publisher_email                   = var.publisher_email
  frontend_tenant_id                = var.frontend_tenant_id
  frontend_audience                 = var.frontend_audience
  console_origin                    = local.console_origin
  operator_backend_url              = var.operator_backend_url
  ingestion_backend_url             = var.ingestion_backend_url
  backend_nsg_id                    = var.backend_nsg_id
  backend_nsg_destination_addresses = var.backend_nsg_destination_addresses
  tags                              = merge(local.tags, { "fdai:component" = "browser-gateway" })
}
