resource "azurerm_static_web_app" "design_mocks" {
  name                = var.name
  resource_group_name = var.resource_group_name
  location            = var.location
  sku_tier            = "Free"
  sku_size            = "Free"

  preview_environments_enabled = false

  tags = var.tags
}
