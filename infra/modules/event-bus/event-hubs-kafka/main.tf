resource "azurerm_eventhub_namespace" "primary" {
  name                          = var.name
  location                      = var.location
  resource_group_name           = var.resource_group_name
  sku                           = var.sku
  capacity                      = 1
  auto_inflate_enabled          = false
  local_authentication_enabled  = false # Entra token / OAUTHBEARER only.
  public_network_access_enabled = var.public_network_access_enabled
  tags                          = var.tags
}

resource "azurerm_eventhub" "topic" {
  for_each          = toset(var.topics)
  name              = each.value
  namespace_id      = azurerm_eventhub_namespace.primary.id
  partition_count   = var.partition_count
  message_retention = 1
}

# DLQ sibling per topic - <topic>.dlq convention (csp-neutrality.md § Event bus).
resource "azurerm_eventhub" "dlq" {
  for_each          = toset(var.topics)
  name              = "${each.value}.dlq"
  namespace_id      = azurerm_eventhub_namespace.primary.id
  partition_count   = var.partition_count
  message_retention = 7
}

resource "azurerm_eventhub" "auxiliary" {
  for_each          = toset(var.auxiliary_topics)
  name              = each.value
  namespace_id      = azurerm_eventhub_namespace.primary.id
  partition_count   = var.partition_count
  message_retention = 1
}
