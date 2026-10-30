resource "azurerm_user_assigned_identity" "controller" {
  name                = "id-${var.name}-controller"
  resource_group_name = azurerm_resource_group.controller.name
  location            = var.location
  tags                = local.tags
}

resource "azurerm_user_assigned_identity" "worker_pull" {
  name                = "id-${var.name}-worker-pull"
  resource_group_name = azurerm_resource_group.controller.name
  location            = var.location
  tags                = local.worker_tags
}

resource "azurerm_role_assignment" "controller_pull" {
  scope                = var.registry_id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.controller.principal_id
  principal_type       = "ServicePrincipal"
}

# This is the worker identity's only assignment. No ARM, state or GitHub credential.
resource "azurerm_role_assignment" "worker_pull" {
  scope                = var.registry_id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.worker_pull.principal_id
  principal_type       = "ServicePrincipal"
}

resource "azurerm_role_assignment" "state" {
  scope                = azurerm_storage_container.state.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.controller.principal_id
  principal_type       = "ServicePrincipal"
}

resource "azurerm_role_definition" "jobs" {
  name        = "${var.name}-manual-job-dispatch"
  scope       = azurerm_resource_group.workers.id
  description = "Read and start only the two assigned Manual CI Jobs; no write, secrets or stop."
  permissions {
    actions = [
      "Microsoft.App/jobs/read",
      "Microsoft.App/jobs/start/action",
      "Microsoft.App/jobs/executions/read",
    ]
    not_actions = []
  }
  assignable_scopes = [azurerm_resource_group.workers.id]
}

resource "azurerm_role_assignment" "jobs" {
  for_each           = local.jobs
  scope              = azurerm_container_app_job.worker[each.key].id
  role_definition_id = azurerm_role_definition.jobs.role_definition_resource_id
  principal_id       = azurerm_user_assigned_identity.controller.principal_id
  principal_type     = "ServicePrincipal"
}

resource "azurerm_role_definition" "vm_workers" {
  count       = local.vm_enabled ? 1 : 0
  name        = "${var.name}-ephemeral-vm-worker"
  scope       = azurerm_resource_group.workers.id
  description = "Exclusive CI VM, NIC and disk lifecycle; no run command, extensions, public IP, identity assignment, role assignment or network management."
  permissions {
    actions = [
      "Microsoft.Compute/virtualMachines/read",
      "Microsoft.Compute/virtualMachines/write",
      "Microsoft.Compute/virtualMachines/delete",
      "Microsoft.Compute/virtualMachines/instanceView/read",
      "Microsoft.Compute/disks/read",
      "Microsoft.Compute/disks/write",
      "Microsoft.Compute/disks/delete",
      "Microsoft.Network/networkInterfaces/read",
      "Microsoft.Network/networkInterfaces/write",
      "Microsoft.Network/networkInterfaces/delete",
      "Microsoft.Network/networkInterfaces/join/action",
    ]
    not_actions = []
  }
  assignable_scopes = [azurerm_resource_group.workers.id]
}

resource "azurerm_role_assignment" "vm_workers" {
  count              = local.vm_enabled ? 1 : 0
  scope              = azurerm_resource_group.workers.id
  role_definition_id = azurerm_role_definition.vm_workers[0].role_definition_resource_id
  principal_id       = azurerm_user_assigned_identity.controller.principal_id
  principal_type     = "ServicePrincipal"
}

resource "azurerm_role_definition" "subnet_join" {
  count       = local.vm_enabled ? 1 : 0
  name        = "${var.name}-ci-subnet-join"
  scope       = local.subnet_resource_group_id
  description = "Join the one existing unpeered CI subnet; no topology or NSG changes."
  permissions {
    actions = [
      "Microsoft.Network/virtualNetworks/subnets/read",
      "Microsoft.Network/virtualNetworks/subnets/join/action",
    ]
    not_actions = []
  }
  assignable_scopes = [local.subnet_resource_group_id]
}

resource "azurerm_role_assignment" "subnet_join" {
  count              = local.vm_enabled ? 1 : 0
  scope              = var.vm_subnet_id
  role_definition_id = azurerm_role_definition.subnet_join[0].role_definition_resource_id
  principal_id       = azurerm_user_assigned_identity.controller.principal_id
  principal_type     = "ServicePrincipal"
}

# Reading this exact image is required to create a VM from an existing baked image.
resource "azurerm_role_definition" "image_read" {
  count       = local.vm_enabled ? 1 : 0
  name        = "${var.name}-runner-image-read"
  scope       = local.image_resource_group_id
  description = "Read one pre-baked credential-free VM image, without modifying or capturing images."
  permissions {
    actions = [
      "Microsoft.Compute/galleries/images/versions/read",
    ]
    not_actions = []
  }
  assignable_scopes = [local.image_resource_group_id]
}

resource "azurerm_role_assignment" "image_read" {
  count              = local.vm_enabled ? 1 : 0
  scope              = var.vm_image_id
  role_definition_id = azurerm_role_definition.image_read[0].role_definition_resource_id
  principal_id       = azurerm_user_assigned_identity.controller.principal_id
  principal_type     = "ServicePrincipal"
}
