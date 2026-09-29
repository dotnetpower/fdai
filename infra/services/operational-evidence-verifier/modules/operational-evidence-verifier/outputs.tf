output "service" {
  description = "Operational evidence verifier service handles."
  value = {
    id                   = module.container_app.id
    name                 = module.container_app.name
    latest_revision_name = module.container_app.latest_revision_name
  }
}

output "internal_ingress" {
  description = "Verifier ingress boundary; external access must stay disabled."
  value = {
    external_enabled = module.container_app.ingress_external_enabled
    target_port      = module.container_app.ingress_target_port
  }
}
