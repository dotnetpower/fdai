output "service" {
  description = "Code-security worker deployment outputs."
  value = {
    id                   = module.code_security_worker.id
    name                 = module.code_security_worker.name
    latest_revision_name = module.code_security_worker.latest_revision_name
  }
}

output "worker_contract" {
  description = "Bounded serialized worker settings used by deployment verification."
  value       = var.worker
}

output "database_role" {
  description = "Restricted database role required by the worker."
  value       = nonsensitive(var.database.role)
}
