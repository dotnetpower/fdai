output "target_contract" {
  description = "Sensitive deployment binding retained with the exact reviewed plan."
  sensitive   = true
  value = {
    executor_client_id       = azurerm_user_assigned_identity.executor.client_id
    executor_principal_id    = azurerm_user_assigned_identity.executor.principal_id
    observer_client_id       = azurerm_user_assigned_identity.observer.client_id
    observer_principal_id    = azurerm_user_assigned_identity.observer.principal_id
    source_region            = var.region
    target_resource_id       = azurerm_linux_virtual_machine.target.id
    target_resource_group_id = data.azurerm_resource_group.target.id
  }
}

output "post_provision_requirement" {
  description = "Required independent observation before the evidence cohort can start."
  value = {
    expected_power_state = "deallocated"
    effect_authorized    = false
    promotion_authorized = false
  }
}
