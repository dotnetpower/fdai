locals {
  resolved_catalog_path = (
    var.catalog_path != ""
    ? var.catalog_path
    : "${path.module}/../../../../config/azure-iam-permission-groups.json"
  )
  catalog = jsondecode(file(local.resolved_catalog_path))
  groups_by_id = {
    for group in local.catalog.groups : group.id => group
  }
  resolved_assignable_scopes = (
    length(var.assignable_scopes) > 0
    ? var.assignable_scopes
    : [var.role_definition_scope]
  )
  default_principal_type = var.binding_mode == "entra_group" ? "Group" : "ServicePrincipal"
  role_name_suffix       = var.name_suffix == "" ? "" : " (${var.name_suffix})"

  # ABAC v2.0 delegation condition limiting deployer ServicePrincipal assignments to FDAI roles only.
  fdai_role_definition_guids = sort([
    for role in azurerm_role_definition.fdai_group : basename(role.role_definition_id)
  ])
  deployer_abac_condition = <<-EOT
    (
      (!(ActionMatches{'Microsoft.Authorization/roleAssignments/write'}))
      OR
      (
        @Request[Microsoft.Authorization/roleAssignments:RoleDefinitionId] ForAnyOfAnyValues:GuidEquals {${join(", ", local.fdai_role_definition_guids)}}
        AND
        @Request[Microsoft.Authorization/roleAssignments:PrincipalType] ForAnyOfAnyValues:StringEqualsIgnoreCase {'${local.default_principal_type}'}
      )
    )
    AND
    (
      (!(ActionMatches{'Microsoft.Authorization/roleAssignments/delete'}))
      OR
      (
        @Resource[Microsoft.Authorization/roleAssignments:RoleDefinitionId] ForAnyOfAnyValues:GuidEquals {${join(", ", local.fdai_role_definition_guids)}}
        AND
        @Resource[Microsoft.Authorization/roleAssignments:PrincipalType] ForAnyOfAnyValues:StringEqualsIgnoreCase {'${local.default_principal_type}'}
      )
    )
  EOT
}

resource "azurerm_role_definition" "fdai_group" {
  for_each = local.groups_by_id

  name        = "${each.value.role_name_template}${local.role_name_suffix}"
  scope       = var.role_definition_scope
  description = each.value.summary_en

  permissions {
    actions          = each.value.actions
    not_actions      = each.value.not_actions
    data_actions     = each.value.data_actions
    not_data_actions = each.value.not_data_actions
  }

  assignable_scopes = local.resolved_assignable_scopes
}

resource "azurerm_role_assignment" "fdai_group" {
  for_each = var.assignments

  scope              = each.value.scope
  role_definition_id = azurerm_role_definition.fdai_group[each.value.group_id].role_definition_resource_id
  principal_id       = each.value.principal_id
  principal_type     = coalesce(each.value.principal_type, local.default_principal_type)
}
