resource "azurerm_container_registry" "primary" {
  # checkov:skip=CKV_AZURE_237:Dedicated data endpoints are enabled whenever the production gate selects Premium.
  # checkov:skip=CKV_AZURE_163:The container supply-chain workflow scans every image before publication and deployment.
  # checkov:skip=CKV_AZURE_139:The production gate selects Premium and the root disables public access behind a private endpoint.
  # checkov:skip=CKV_AZURE_167:Premium registries retain untagged manifests for 30 days below.
  # checkov:skip=CKV_AZURE_166:Quarantine requires an external mark-verified writer; immutable attestations gate deployment instead.
  # checkov:skip=CKV_AZURE_233:Zone redundancy is region-dependent and is not claimed by the current single-region topology.
  # checkov:skip=CKV_AZURE_164:Azure Content Trust is service-deprecated; immutable GitHub attestations gate deployment.
  # checkov:skip=CKV_AZURE_165:The current topology is explicitly single-region; geo-replication remains a measured future profile.
  name                          = var.name
  location                      = var.location
  resource_group_name           = var.resource_group_name
  sku                           = var.sku
  admin_enabled                 = false
  public_network_access_enabled = var.public_network_access_enabled
  data_endpoint_enabled         = var.sku == "Premium"
  retention_policy_in_days      = var.sku == "Premium" ? 30 : null
  tags                          = var.tags
}
