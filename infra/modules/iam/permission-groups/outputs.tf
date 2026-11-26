output "role_definition_resource_ids" {
  description = "Map of FDAI group id (reader, operator, contributor) to Azure role_definition_resource_id."
  value = {
    for id, role in azurerm_role_definition.fdai_group : id => role.role_definition_resource_id
  }
}

output "role_definition_names" {
  description = "Map of FDAI group id to created Azure Custom Role display name."
  value = {
    for id, role in azurerm_role_definition.fdai_group : id => role.name
  }
}

output "deployer_abac_condition" {
  description = "ABAC v2.0 condition expression restricting role delegation strictly to the three FDAI custom roles."
  value       = local.deployer_abac_condition
}

output "catalog_defaults" {
  description = "Recommended defaults loaded from the canonical JSON catalog."
  value       = local.catalog.defaults
}
