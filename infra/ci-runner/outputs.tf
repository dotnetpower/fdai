output "resource_group_name" {
  value = azurerm_resource_group.ci.name
}

output "vm_name" {
  value = azurerm_linux_virtual_machine.ci.name
}

output "runner_labels" {
  value = ["self-hosted", "Linux", "X64", "fdai-ci", "fdai-ci-ssd"]
}
